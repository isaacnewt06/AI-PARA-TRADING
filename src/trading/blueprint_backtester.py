"""Conservative OHLCV backtesting for executable blueprint specs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from src.core.logging import get_logger
from src.trading.strategy_schemas import BacktestBlueprintSpec

logger = get_logger(__name__)

TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

SESSION_WINDOWS = {
    "new_york": (ZoneInfo("America/New_York"), 8, 12),
    "london": (ZoneInfo("Europe/London"), 7, 11),
}


@dataclass(slots=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class Zone:
    direction: str
    created_time: datetime
    low: float
    high: float
    midpoint: float
    bias_timeframe: str
    invalidated: bool = False


@dataclass(slots=True)
class Trade:
    strategy_name: str
    symbol: str
    direction: str
    ob_detected: bool
    htf_bias: str | None
    rejection_type: str | None
    confirmation_band: str | None
    atr_band: str | None
    hour_utc: int | None
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    take_profit_price: float
    result: str
    pnl_r: float
    rr_target: float
    session: str | None
    setup_time: datetime
    context_timeframe: str
    entry_timeframe: str
    entry_reason: str | None = None
    exit_reason: str | None = None


class BlueprintBacktester:
    """Run conservative blueprint backtests over CSV OHLCV."""

    def __init__(self, input_dir: Path, results_dir: Path, reports_dir: Path) -> None:
        self.input_dir = input_dir
        self.results_dir = results_dir
        self.reports_dir = reports_dir
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._candles_cache: dict[str, list[Candle]] = {}
        self._resample_cache: dict[tuple[str, str, str], list[Candle]] = {}
        self._atr_cache: dict[tuple[str, str, int, tuple[int, str | None, str | None]], list[float | None]] = {}
        self._context_indicator_cache: dict[tuple[str, str, str, tuple[int, str | None, str | None]], list[dict]] = {}
        self._zone_cache: dict[tuple[str, str, str, float, int, tuple[int, str | None, str | None]], list[Zone]] = {}

    def run_specs(self, specs_dir: Path) -> dict:
        specs = sorted(specs_dir.glob("*.json"))
        summary = {
            "specs_total": len(specs),
            "specs_executed": 0,
            "specs_skipped": 0,
            "results_dir": str(self.results_dir.resolve()),
            "reports_dir": str(self.reports_dir.resolve()),
            "items": [],
        }
        for path in specs:
            try:
                spec = BacktestBlueprintSpec.model_validate_json(path.read_text(encoding="utf-8"))
            except ValidationError:
                logger.debug("Skipping non-backtest JSON artifact path=%s", path)
                continue
            result = self.run_spec(spec)
            if result.get("status") == "completed":
                summary["specs_executed"] += 1
            else:
                summary["specs_skipped"] += 1
            summary["items"].append(result)
        return summary

    def run_spec(self, spec: BacktestBlueprintSpec) -> dict:
        return self.evaluate_spec(spec, split="all", persist=True)

    def evaluate_spec(
        self,
        spec: BacktestBlueprintSpec,
        *,
        split: str = "all",
        persist: bool = False,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> dict:
        symbol_runs = []
        processed_pairs: set[tuple[str, str]] = set()
        for symbol in spec.symbols_suggested:
            resolved_symbol, entry_tf = self._resolve_entry_timeframe(symbol, spec.entry_timeframe)
            if entry_tf is None:
                continue
            pair = (resolved_symbol, entry_tf)
            if pair in processed_pairs:
                continue
            processed_pairs.add(pair)
            entry_candles = self._load_candles(self._csv_path(resolved_symbol, entry_tf))
            if not entry_candles:
                continue
            context_tf = spec.context_timeframe[0] if spec.context_timeframe else "H1"
            context_candles = self._load_or_resample_context(resolved_symbol, context_tf, entry_tf, entry_candles)
            if not context_candles:
                continue
            window = (window_start, window_end) if (window_start or window_end) else self._split_window(entry_candles, split=split)
            if window is None:
                continue
            trades = self._simulate_symbol(
                spec=spec,
                symbol=resolved_symbol,
                entry_tf=entry_tf,
                entry_candles=entry_candles,
                context_tf=context_tf,
                context_candles=context_candles,
                window_start=window[0],
                window_end=window[1],
            )
            symbol_runs.append((resolved_symbol, entry_tf, trades))

        if not symbol_runs:
            reason = (
                "No compatible OHLCV CSV files found. Expected files like "
                "XAUUSDm_M5.csv or XAUUSDm_M1.csv in data/backtests/input, "
                "with optional fallback compatibility for XAUUSD_M5.csv and XAUUSD_M1.csv."
            )
            if persist:
                return self._write_empty_result(spec, reason=reason)
            return {
                "strategy_name": spec.strategy_name,
                "status": "skipped",
                "reason": reason,
                "metrics": self._metrics([]),
                "trades": [],
                "split": split,
            }

        all_trades = [trade for _, _, trades in symbol_runs for trade in trades]
        result_payload = self._result_payload(spec, symbol_runs, all_trades)
        result_payload["split"] = split
        if not persist:
            return {
                "strategy_name": spec.strategy_name,
                "status": "completed",
                "trades_count": len(all_trades),
                "metrics": result_payload["metrics"],
                "payload": result_payload,
                "trades": all_trades,
                "split": split,
            }
        result_json = self.results_dir / f"{self._slug(spec.strategy_name)}_results.json"
        trades_csv = self.results_dir / f"{self._slug(spec.strategy_name)}_trades.csv"
        report_md = self.reports_dir / f"{self._slug(spec.strategy_name)}_report.md"
        result_json.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_trades_csv(trades_csv, all_trades)
        report_md.write_text(self._markdown_report(spec, result_payload), encoding="utf-8")
        return {
            "strategy_name": spec.strategy_name,
            "status": "completed",
            "trades": len(all_trades),
            "result_path": str(result_json.resolve()),
            "trades_path": str(trades_csv.resolve()),
            "report_path": str(report_md.resolve()),
        }

    def _simulate_symbol(
        self,
        *,
        spec: BacktestBlueprintSpec,
        symbol: str,
        entry_tf: str,
        entry_candles: list[Candle],
        context_tf: str,
        context_candles: list[Candle],
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> list[Trade]:
        overrides = spec.simulation_overrides or {}
        bias_mode = "strict"
        if overrides.get("relaxed_htf_bias"):
            bias_mode = "relaxed"
        if overrides.get("balanced_htf_bias"):
            bias_mode = "balanced"
        relaxed_zone = bool(overrides.get("relaxed_order_block"))
        balanced_zone = bool(overrides.get("balanced_order_block"))
        zone_lookback = int(overrides.get("recent_order_block_window") or (20 if relaxed_zone else 30 if balanced_zone else 0))
        confirmation_mode = str(overrides.get("confirmation_mode") or ("any_of_three" if overrides.get("relaxed_confirmation_any") else "strict"))
        min_confirmation_signals = int(overrides.get("min_confirmation_signals") or (2 if confirmation_mode == "two_of_three" else 1))
        min_atr_percentile = overrides.get("min_atr_percentile")
        max_atr_percentile = overrides.get("max_atr_percentile")
        atr_percentile_lookback = int(overrides.get("atr_percentile_lookback") or 100)
        max_range_atr_multiple = float(overrides.get("max_range_atr_multiple") or 999.0)
        large_confirmation_atr_multiple = float(overrides.get("large_confirmation_atr_multiple") or 999.0)
        large_confirmation_retrace = float(overrides.get("large_confirmation_retrace") or 0.0)
        allowed_hours_utc = set(int(item) for item in overrides.get("allowed_hours_utc", []))
        blocked_hours_utc = set(int(item) for item in overrides.get("blocked_hours_utc", []))
        direction_filter = str(overrides.get("direction_filter") or "both").lower()
        allowed_atr_bands = set(str(item) for item in overrides.get("allowed_atr_bands", []))
        blocked_atr_bands = set(str(item) for item in overrides.get("blocked_atr_bands", []))
        allowed_confirmation_bands = set(str(item) for item in overrides.get("allowed_confirmation_bands", []))
        blocked_confirmation_bands = set(str(item) for item in overrides.get("blocked_confirmation_bands", []))
        required_rejection_signals = set(str(item) for item in overrides.get("required_rejection_signals", []))
        blocked_rejection_signals = set(str(item) for item in overrides.get("blocked_rejection_signals", []))
        exit_management = str(overrides.get("exit_management") or "static")
        trail_atr_multiple = float(overrides.get("trail_atr_multiple") or 1.0)
        break_even_trigger_r = float(overrides.get("break_even_trigger_r") or 1.0)
        daily_max_losses = int(overrides["daily_max_losses"]) if overrides.get("daily_max_losses") is not None else None
        daily_min_pnl_r = float(overrides["daily_min_pnl_r"]) if overrides.get("daily_min_pnl_r") is not None else None
        cooldown_bars_after_loss = int(overrides.get("cooldown_bars_after_loss") or 0)
        cooldown_until_new_structure = bool(overrides.get("cooldown_until_new_structure"))
        max_trades_per_day = int(overrides["max_trades_per_day"]) if overrides.get("max_trades_per_day") is not None else None

        context_with_indicators = self._get_context_with_indicators(
            symbol=symbol,
            context_tf=context_tf,
            context_candles=context_candles,
            bias_mode=bias_mode,
        )
        body_threshold_multiplier = 0.6 if relaxed_zone else 0.7 if balanced_zone else 0.8
        source_lookback = 20 if relaxed_zone else 10 if balanced_zone else 5
        zones = self._get_detected_zones(
            symbol=symbol,
            context_tf=context_tf,
            bias_mode=bias_mode,
            context_with_indicators=context_with_indicators,
            body_threshold_multiplier=body_threshold_multiplier,
            source_lookback=source_lookback,
        )
        zones_by_direction = {
            "long": [zone for zone in zones if zone.direction == "long"],
            "short": [zone for zone in zones if zone.direction == "short"],
        }
        zone_pointers = {"long": -1, "short": -1}
        atr_values = self._get_atr_values(symbol=symbol, timeframe=entry_tf, candles=entry_candles, period=14)
        trades: list[Trade] = []
        open_until: datetime | None = None
        context_duration = timedelta(minutes=TIMEFRAME_MINUTES.get(context_tf, 60))
        context_pointer = -1
        index_by_time = {item.time: idx for idx, item in enumerate(entry_candles)}
        day_stats: dict[date, dict[str, float | int]] = {}
        blocked_days: set[date] = set()
        cooldown_until_index = -1
        cooldown_structure_after: datetime | None = None

        for index, candle in enumerate(entry_candles[:-1]):
            if open_until and candle.time <= open_until:
                continue
            if cooldown_until_index >= 0 and index <= cooldown_until_index:
                continue
            if window_start and candle.time < window_start:
                continue
            if window_end and candle.time > window_end:
                continue
            next_candle = entry_candles[index + 1]
            if not self._in_allowed_session(next_candle.time, spec.session_filter):
                continue
            if not self._passes_hour_filters(next_candle.time, allowed_hours_utc, blocked_hours_utc):
                continue
            cutoff = candle.time - context_duration
            while (
                context_pointer + 1 < len(context_with_indicators)
                and context_with_indicators[context_pointer + 1]["candle"].time <= cutoff
            ):
                context_pointer += 1
            context_snapshot = context_with_indicators[context_pointer] if context_pointer >= 0 else None
            if context_snapshot is None:
                continue
            bias = context_snapshot["bias"]
            if bias not in {"long", "short"}:
                continue
            if not self._passes_direction_filter(bias, direction_filter):
                continue
            direction_zones = zones_by_direction[bias]
            while (
                zone_pointers[bias] + 1 < len(direction_zones)
                and direction_zones[zone_pointers[bias] + 1].created_time < candle.time
            ):
                zone_pointers[bias] += 1
            recent_context_start_time = None
            if zone_lookback and context_pointer >= 0:
                recent_index = max(0, context_pointer - zone_lookback + 1)
                recent_context_start_time = context_with_indicators[recent_index]["candle"].time
            if relaxed_zone or balanced_zone:
                active_zone = self._latest_zone(
                    direction_zones,
                    last_index=zone_pointers[bias],
                    recent_context_start_time=recent_context_start_time,
                )
            else:
                active_zone = self._active_zone(
                    zones,
                    candle.time,
                    bias,
                    entry_candles[: index + 1],
                    allow_mitigated=False,
                    recent_context_candles=zone_lookback or None,
                    context_candles=context_candles,
                )
            if active_zone is None:
                continue
            if cooldown_structure_after is not None:
                if active_zone.created_time <= cooldown_structure_after:
                    continue
                cooldown_structure_after = None
            if not self._touches_zone(candle, active_zone):
                continue
            atr = atr_values[index] or max(0.0001, abs(candle.high - candle.low))
            atr_band = self._atr_band_from_values(atr_values, index, atr_percentile_lookback)
            if allowed_atr_bands and atr_band not in allowed_atr_bands:
                continue
            if blocked_atr_bands and atr_band in blocked_atr_bands:
                continue
            if min_atr_percentile is not None and not self._passes_atr_percentile_filter(
                atr_values,
                index,
                percentile=float(min_atr_percentile),
                lookback=atr_percentile_lookback,
            ):
                continue
            if max_atr_percentile is not None and not self._passes_max_atr_percentile_filter(
                atr_values,
                index,
                percentile=float(max_atr_percentile),
                lookback=atr_percentile_lookback,
            ):
                continue
            candle_range = max(0.0000001, candle.high - candle.low)
            if candle_range > atr * max_range_atr_multiple:
                continue
            confirmation_size_band = self._confirmation_size_band(candle_range / atr if atr else None)
            if allowed_confirmation_bands and confirmation_size_band not in allowed_confirmation_bands:
                continue
            if blocked_confirmation_bands and confirmation_size_band in blocked_confirmation_bands:
                continue
            if not self._is_rejection(
                candle,
                active_zone,
                mode=confirmation_mode,
                min_confirmation_signals=min_confirmation_signals,
            ):
                continue

            rejection_signals = self._rejection_signals(candle, active_zone)
            if required_rejection_signals and not required_rejection_signals.issubset(set(rejection_signals)):
                continue
            if blocked_rejection_signals and blocked_rejection_signals.intersection(rejection_signals):
                continue
            trade_day = next_candle.time.astimezone(timezone.utc).date()
            if trade_day in blocked_days:
                continue
            stats = day_stats.setdefault(trade_day, {"trades": 0, "losses": 0, "pnl_r": 0.0})
            if max_trades_per_day is not None and int(stats["trades"]) >= max_trades_per_day:
                continue
            entry_reason = self._entry_reason(
                candle,
                active_zone,
                confirmation_mode=confirmation_mode,
                large_confirmation_atr_multiple=large_confirmation_atr_multiple,
                retrace_fraction=large_confirmation_retrace,
                atr=atr,
            )
            entry_price = self._resolve_entry_price(
                confirmation_candle=candle,
                next_candle=next_candle,
                direction=bias,
                atr=atr,
                large_confirmation_atr_multiple=large_confirmation_atr_multiple,
                retrace_fraction=large_confirmation_retrace,
            )
            if entry_price is None:
                continue
            stop_price = self._stop_price(
                active_zone,
                atr,
                bias,
                buffer_multiplier=float(overrides.get("stop_buffer_atr") or 0.10),
            )
            risk = abs(entry_price - stop_price)
            if risk <= 0:
                continue
            liquidity_target = self._liquidity_target(entry_candles[: index + 1], entry_price, bias)
            rr_min = spec.rr_min or 2.0
            min_target = entry_price + risk * rr_min if bias == "long" else entry_price - risk * rr_min
            if liquidity_target is None:
                target_price = min_target
            else:
                target_price = liquidity_target
                projected_rr = (target_price - entry_price) / risk if bias == "long" else (entry_price - target_price) / risk
                if projected_rr < rr_min:
                    continue

            trade = self._run_trade(
                spec=spec,
                symbol=symbol,
                direction=bias,
                entry_time=next_candle.time,
                entry_price=entry_price,
                stop_price=stop_price,
                take_profit_price=target_price,
                candles=entry_candles[index + 1 :],
                rr_target=rr_min,
                session=self._derive_session_bucket(next_candle.time),
                setup_time=candle.time,
                context_timeframe=context_tf,
                entry_timeframe=entry_tf,
                entry_reason=entry_reason,
                ob_detected=True,
                htf_bias=bias,
                rejection_type="+".join(rejection_signals) if rejection_signals else "strict_rejection",
                confirmation_band=confirmation_size_band,
                atr_band=atr_band,
                hour_utc=next_candle.time.astimezone(timezone.utc).hour,
                entry_atr=atr,
                exit_management=exit_management,
                trail_atr_multiple=trail_atr_multiple,
                break_even_trigger_r=break_even_trigger_r,
                window_end=window_end,
            )
            trades.append(trade)
            open_until = trade.exit_time
            stats["trades"] = int(stats["trades"]) + 1
            stats["pnl_r"] = float(stats["pnl_r"]) + trade.pnl_r
            if trade.pnl_r < 0:
                stats["losses"] = int(stats["losses"]) + 1
                exit_index = index_by_time.get(trade.exit_time, len(entry_candles) - 1)
                if cooldown_bars_after_loss > 0:
                    cooldown_until_index = max(cooldown_until_index, exit_index + cooldown_bars_after_loss)
                if cooldown_until_new_structure:
                    cooldown_structure_after = trade.exit_time
            if daily_max_losses is not None and int(stats["losses"]) >= daily_max_losses:
                blocked_days.add(trade_day)
            if daily_min_pnl_r is not None and float(stats["pnl_r"]) <= daily_min_pnl_r:
                blocked_days.add(trade_day)
        return trades

    def _get_context_with_indicators(
        self,
        *,
        symbol: str,
        context_tf: str,
        context_candles: list[Candle],
        bias_mode: str,
    ) -> list[dict]:
        cache_key = (symbol, context_tf, bias_mode, self._series_fingerprint(context_candles))
        cached = self._context_indicator_cache.get(cache_key)
        if cached is not None:
            return cached
        enriched = self._decorate_context(context_candles, bias_mode=bias_mode)
        self._context_indicator_cache[cache_key] = enriched
        return enriched

    def _get_detected_zones(
        self,
        *,
        symbol: str,
        context_tf: str,
        bias_mode: str,
        context_with_indicators: list[dict],
        body_threshold_multiplier: float,
        source_lookback: int,
    ) -> list[Zone]:
        cache_key = (
            symbol,
            context_tf,
            bias_mode,
            body_threshold_multiplier,
            source_lookback,
            self._series_fingerprint([row["candle"] for row in context_with_indicators]),
        )
        cached = self._zone_cache.get(cache_key)
        if cached is not None:
            return cached
        zones = self._detect_zones(
            context_with_indicators,
            context_tf,
            body_threshold_multiplier=body_threshold_multiplier,
            source_lookback=source_lookback,
        )
        self._zone_cache[cache_key] = zones
        return zones

    def _get_atr_values(self, *, symbol: str, timeframe: str, candles: list[Candle], period: int) -> list[float | None]:
        cache_key = (symbol, timeframe, period, self._series_fingerprint(candles))
        cached = self._atr_cache.get(cache_key)
        if cached is not None:
            return cached
        values = self._atr(candles, period=period)
        self._atr_cache[cache_key] = values
        return values

    @staticmethod
    def _series_fingerprint(candles: list[Candle]) -> tuple[int, str | None, str | None]:
        if not candles:
            return (0, None, None)
        return (len(candles), candles[0].time.isoformat(), candles[-1].time.isoformat())

    def _run_trade(
        self,
        *,
        spec: BacktestBlueprintSpec,
        symbol: str,
        direction: str,
        ob_detected: bool,
        htf_bias: str | None,
        rejection_type: str | None,
        confirmation_band: str | None,
        atr_band: str | None,
        hour_utc: int | None,
        entry_time: datetime,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
        candles: list[Candle],
        rr_target: float,
        session: str | None,
        setup_time: datetime,
        context_timeframe: str,
        entry_timeframe: str,
        entry_reason: str | None = None,
        entry_atr: float | None = None,
        exit_management: str = "static",
        trail_atr_multiple: float = 1.0,
        break_even_trigger_r: float = 1.0,
        window_end: datetime | None = None,
    ) -> Trade:
        risk = abs(entry_price - stop_price)
        current_stop = stop_price
        current_tp = take_profit_price
        trigger_r_price = (
            entry_price + (risk * break_even_trigger_r)
            if direction == "long"
            else entry_price - (risk * break_even_trigger_r)
        )
        two_r_price = entry_price + (risk * 2.0) if direction == "long" else entry_price - (risk * 2.0)
        partial_taken = False
        break_even_armed = False
        trailing_armed = False
        realized_r = 0.0
        trail_distance = max(entry_atr or 0.0, 0.0000001) * trail_atr_multiple

        for candle in candles:
            if window_end and candle.time > window_end:
                break
            stop_hit = candle.low <= current_stop if direction == "long" else candle.high >= current_stop
            tp_hit = candle.high >= current_tp if direction == "long" else candle.low <= current_tp
            if stop_hit and tp_hit:
                exit_price = current_stop
                result = "loss_same_bar_conservative"
                exit_reason = "stop_loss_same_bar_conservative"
            elif stop_hit:
                exit_price = current_stop
                if partial_taken:
                    result = "partial_stop"
                    exit_reason = "partial_tp_1r_then_stop_loss"
                elif break_even_armed and abs(current_stop - entry_price) < 1e-8:
                    result = "breakeven"
                    exit_reason = "break_even_after_1r"
                elif trailing_armed:
                    result = "trailing_stop"
                    exit_reason = "trailing_atr_stop_after_1r"
                else:
                    result = "loss"
                    exit_reason = "stop_loss"
            elif tp_hit:
                exit_price = current_tp
                result = "win"
                if partial_taken:
                    exit_reason = "partial_tp_1r_then_final_tp_2r"
                elif break_even_armed:
                    exit_reason = "take_profit_after_break_even"
                elif trailing_armed:
                    exit_reason = "take_profit_after_trailing"
                else:
                    exit_reason = "take_profit"
            else:
                trigger_hit = candle.high >= trigger_r_price if direction == "long" else candle.low <= trigger_r_price
                if exit_management == "partial_1r_then_2r" and not partial_taken and trigger_hit:
                    partial_taken = True
                    realized_r += 0.5
                    current_tp = two_r_price
                    continue
                if exit_management == "break_even_after_1r" and not break_even_armed and trigger_hit:
                    break_even_armed = True
                    current_stop = entry_price
                    continue
                if exit_management == "trailing_atr_after_1r" and not trailing_armed and trigger_hit:
                    trailing_armed = True
                    current_stop = entry_price
                if trailing_armed:
                    if direction == "long":
                        current_stop = max(current_stop, candle.close - trail_distance)
                    else:
                        current_stop = min(current_stop, candle.close + trail_distance)
                continue
            pnl_r = (exit_price - entry_price) / risk if direction == "long" else (entry_price - exit_price) / risk
            if partial_taken:
                pnl_r = realized_r + (pnl_r * 0.5)
            return Trade(
                strategy_name=spec.strategy_name,
                symbol=symbol,
                direction=direction,
                ob_detected=ob_detected,
                htf_bias=htf_bias,
                rejection_type=rejection_type,
                confirmation_band=confirmation_band,
                atr_band=atr_band,
                hour_utc=hour_utc,
                entry_time=entry_time,
                exit_time=candle.time,
                entry_price=entry_price,
                exit_price=exit_price,
                stop_price=current_stop,
                take_profit_price=current_tp,
                result=result,
                pnl_r=round(pnl_r, 4),
                rr_target=rr_target,
                session=session,
                setup_time=setup_time,
                context_timeframe=context_timeframe,
                entry_timeframe=entry_timeframe,
                entry_reason=entry_reason,
                exit_reason=exit_reason,
            )

        eligible_candles = [candle for candle in candles if not window_end or candle.time <= window_end]
        final_candle = eligible_candles[-1] if eligible_candles else candles[0]
        pnl_r = (final_candle.close - entry_price) / risk if direction == "long" else (entry_price - final_candle.close) / risk
        if partial_taken:
            pnl_r = realized_r + (pnl_r * 0.5)
        return Trade(
            strategy_name=spec.strategy_name,
            symbol=symbol,
            direction=direction,
            ob_detected=ob_detected,
            htf_bias=htf_bias,
            rejection_type=rejection_type,
            confirmation_band=confirmation_band,
            atr_band=atr_band,
            hour_utc=hour_utc,
            entry_time=entry_time,
            exit_time=final_candle.time,
            entry_price=entry_price,
            exit_price=final_candle.close,
            stop_price=current_stop,
            take_profit_price=current_tp,
            result="open_to_end_of_data",
            pnl_r=round(pnl_r, 4),
            rr_target=rr_target,
            session=session,
            setup_time=setup_time,
            context_timeframe=context_timeframe,
            entry_timeframe=entry_timeframe,
            entry_reason=entry_reason,
            exit_reason="end_of_data_after_partial" if partial_taken else "end_of_data_after_trailing" if trailing_armed else "end_of_data",
        )

    @staticmethod
    def _decorate_context(candles: list[Candle], *, bias_mode: str = "strict") -> list[dict]:
        ema20 = BlueprintBacktester._ema([item.close for item in candles], 20)
        ema50 = BlueprintBacktester._ema([item.close for item in candles], 50)
        atr14 = BlueprintBacktester._atr(candles, 14)
        enriched = []
        for index, candle in enumerate(candles):
            bias = None
            if bias_mode == "relaxed" and ema50[index] is not None:
                recent = candles[max(0, index - 4) : index + 1]
                rising_swings = len(recent) >= 3 and recent[-1].high > recent[-2].high and recent[-1].low > recent[-2].low
                falling_swings = len(recent) >= 3 and recent[-1].high < recent[-2].high and recent[-1].low < recent[-2].low
                if candle.close > ema50[index] or rising_swings:
                    bias = "long"
                elif candle.close < ema50[index] or falling_swings:
                    bias = "short"
            elif bias_mode == "balanced" and index > 0 and ema50[index] is not None and ema50[index - 1] is not None:
                if candle.close > ema50[index] and ema50[index] > ema50[index - 1]:
                    bias = "long"
                elif candle.close < ema50[index] and ema50[index] < ema50[index - 1]:
                    bias = "short"
            elif index > 0 and ema20[index] and ema50[index] and ema20[index - 1]:
                if ema20[index] > ema50[index] and ema20[index] > ema20[index - 1]:
                    bias = "long"
                elif ema20[index] < ema50[index] and ema20[index] < ema20[index - 1]:
                    bias = "short"
            enriched.append({"candle": candle, "ema20": ema20[index], "ema50": ema50[index], "atr": atr14[index], "bias": bias})
        return enriched

    @staticmethod
    def _detect_zones(
        context_rows: list[dict],
        context_tf: str,
        *,
        body_threshold_multiplier: float = 0.8,
        source_lookback: int = 5,
    ) -> list[Zone]:
        zones: list[Zone] = []
        highs = [row["candle"].high for row in context_rows]
        lows = [row["candle"].low for row in context_rows]
        for index in range(6, len(context_rows)):
            candle = context_rows[index]["candle"]
            atr = context_rows[index]["atr"] or abs(candle.high - candle.low)
            recent_high = max(highs[index - 5 : index])
            recent_low = min(lows[index - 5 : index])
            body = abs(candle.close - candle.open)
            body_threshold = atr * body_threshold_multiplier

            if candle.close > recent_high and candle.close > candle.open and body >= body_threshold:
                source = next(
                    (
                        context_rows[j]["candle"]
                        for j in range(index - 1, max(index - source_lookback, -1), -1)
                        if context_rows[j]["candle"].close < context_rows[j]["candle"].open
                    ),
                    None,
                )
                if source is not None:
                    zones.append(Zone("long", candle.time, source.low, source.high, (source.high + source.low) / 2, context_tf))

            if candle.close < recent_low and candle.close < candle.open and body >= body_threshold:
                source = next(
                    (
                        context_rows[j]["candle"]
                        for j in range(index - 1, max(index - source_lookback, -1), -1)
                        if context_rows[j]["candle"].close > context_rows[j]["candle"].open
                    ),
                    None,
                )
                if source is not None:
                    zones.append(Zone("short", candle.time, source.low, source.high, (source.high + source.low) / 2, context_tf))
        return zones

    @staticmethod
    def _active_zone(
        zones: list[Zone],
        time_value: datetime,
        direction: str,
        entry_history: list[Candle],
        *,
        allow_mitigated: bool = False,
        recent_context_candles: int | None = None,
        context_candles: list[Candle] | None = None,
    ) -> Zone | None:
        candidates = [zone for zone in zones if zone.direction == direction and zone.created_time < time_value]
        for zone in reversed(candidates):
            if recent_context_candles and context_candles:
                visible_context = [item.time for item in context_candles if item.time < time_value]
                recent_times = visible_context[-recent_context_candles:]
                if recent_times and zone.created_time < recent_times[0]:
                    continue
            if not allow_mitigated and BlueprintBacktester._zone_invalidated(zone, entry_history):
                continue
            return zone
        return None

    @staticmethod
    def _latest_zone(
        zones: list[Zone],
        *,
        last_index: int,
        recent_context_start_time: datetime | None = None,
    ) -> Zone | None:
        if last_index < 0:
            return None
        for index in range(last_index, -1, -1):
            zone = zones[index]
            if recent_context_start_time and zone.created_time < recent_context_start_time:
                continue
            return zone
        return None

    @staticmethod
    def _zone_invalidated(zone: Zone, entry_history: list[Candle]) -> bool:
        midpoint = zone.midpoint
        relevant = [candle for candle in entry_history if candle.time > zone.created_time]
        for candle in relevant:
            if zone.direction == "long" and candle.close < midpoint:
                return True
            if zone.direction == "short" and candle.close > midpoint:
                return True
        return False

    @staticmethod
    def _touches_zone(candle: Candle, zone: Zone) -> bool:
        return candle.high >= zone.low and candle.low <= zone.high

    @staticmethod
    def _is_rejection(
        candle: Candle,
        zone: Zone,
        *,
        mode: str = "strict",
        min_confirmation_signals: int = 1,
    ) -> bool:
        signal_count = BlueprintBacktester._confirmation_signal_count(candle, zone)
        if mode == "two_of_three":
            return signal_count >= max(2, min_confirmation_signals)
        if mode == "any_of_three":
            return signal_count >= max(1, min_confirmation_signals)
        body = abs(candle.close - candle.open)
        lower_wick = min(candle.open, candle.close) - candle.low
        upper_wick = candle.high - max(candle.open, candle.close)
        if zone.direction == "long":
            return candle.close > candle.open and lower_wick >= body * 0.8 and candle.close >= zone.midpoint
        return candle.close < candle.open and upper_wick >= body * 0.8 and candle.close <= zone.midpoint

    @staticmethod
    def _confirmation_signal_count(candle: Candle, zone: Zone) -> int:
        body = abs(candle.close - candle.open)
        candle_range = max(0.0000001, candle.high - candle.low)
        lower_wick = min(candle.open, candle.close) - candle.low
        upper_wick = candle.high - max(candle.open, candle.close)
        strong_body = body >= candle_range * 0.55
        displacement = candle_range > 0 and body >= candle_range * 0.65
        if zone.direction == "long":
            wick_rejection = lower_wick >= max(body * 0.6, candle_range * 0.25)
            displacement_candle = candle.close > candle.open and displacement
            close_back_inside_structure = candle.close >= zone.midpoint and candle.close > candle.open
        else:
            wick_rejection = upper_wick >= max(body * 0.6, candle_range * 0.25)
            displacement_candle = candle.close < candle.open and displacement
            close_back_inside_structure = candle.close <= zone.midpoint and candle.close < candle.open
        return sum(1 for item in (wick_rejection, displacement_candle, close_back_inside_structure) if item)

    @staticmethod
    def _passes_atr_percentile_filter(
        atr_values: list[float | None],
        index: int,
        *,
        percentile: float,
        lookback: int,
    ) -> bool:
        if index <= 0:
            return False
        window = [value for value in atr_values[max(0, index - lookback + 1) : index + 1] if value is not None]
        current = atr_values[index]
        if current is None or len(window) < max(30, min(lookback, 50)):
            return False
        ordered = sorted(window)
        cutoff_index = max(0, min(len(ordered) - 1, int((percentile / 100.0) * (len(ordered) - 1))))
        threshold = ordered[cutoff_index]
        return current >= threshold

    @staticmethod
    def _passes_max_atr_percentile_filter(
        atr_values: list[float | None],
        index: int,
        *,
        percentile: float,
        lookback: int,
    ) -> bool:
        if index <= 0:
            return False
        window = [value for value in atr_values[max(0, index - lookback + 1) : index + 1] if value is not None]
        current = atr_values[index]
        if current is None or len(window) < max(30, min(lookback, 50)):
            return False
        ordered = sorted(window)
        cutoff_index = max(0, min(len(ordered) - 1, int((percentile / 100.0) * (len(ordered) - 1))))
        threshold = ordered[cutoff_index]
        return current <= threshold

    @staticmethod
    def _resolve_entry_price(
        *,
        confirmation_candle: Candle,
        next_candle: Candle,
        direction: str,
        atr: float,
        large_confirmation_atr_multiple: float,
        retrace_fraction: float,
    ) -> float | None:
        candle_range = max(0.0000001, confirmation_candle.high - confirmation_candle.low)
        if candle_range < atr * large_confirmation_atr_multiple or retrace_fraction <= 0:
            return next_candle.open

        if direction == "long":
            retrace_price = confirmation_candle.close - (candle_range * retrace_fraction)
            if next_candle.open <= retrace_price:
                return next_candle.open
            if next_candle.low <= retrace_price <= next_candle.high:
                return retrace_price
            return None

        retrace_price = confirmation_candle.close + (candle_range * retrace_fraction)
        if next_candle.open >= retrace_price:
            return next_candle.open
        if next_candle.low <= retrace_price <= next_candle.high:
            return retrace_price
        return None

    @staticmethod
    def _stop_price(zone: Zone, atr: float, direction: str, *, buffer_multiplier: float = 0.10) -> float:
        buffer = atr * buffer_multiplier
        return zone.low - buffer if direction == "long" else zone.high + buffer

    @staticmethod
    def _liquidity_target(history: list[Candle], entry_price: float, direction: str) -> float | None:
        if direction == "long":
            highs = [item.high for item in history[-40:] if item.high > entry_price]
            return max(highs) if highs else None
        lows = [item.low for item in history[-40:] if item.low < entry_price]
        return min(lows) if lows else None

    @staticmethod
    def _latest_closed_context(context_rows: list[dict], time_value: datetime, context_tf: str) -> dict | None:
        duration = timedelta(minutes=TIMEFRAME_MINUTES.get(context_tf, 60))
        cutoff = time_value - duration
        eligible = [row for row in context_rows if row["candle"].time <= cutoff]
        return eligible[-1] if eligible else None

    def _load_or_resample_context(
        self,
        symbol: str,
        context_tf: str,
        entry_tf: str,
        entry_candles: list[Candle],
    ) -> list[Candle]:
        if context_tf == entry_tf:
            return entry_candles
        context_path = self._csv_path(symbol, context_tf)
        if context_path.exists():
            return self._load_candles(context_path)
        if TIMEFRAME_MINUTES.get(entry_tf, 0) >= TIMEFRAME_MINUTES.get(context_tf, 0):
            return []
        cache_key = (symbol, entry_tf, context_tf)
        cached = self._resample_cache.get(cache_key)
        if cached is not None:
            return cached
        resampled = self._resample(entry_candles, context_tf)
        self._resample_cache[cache_key] = resampled
        return resampled

    @staticmethod
    def _split_window(entry_candles: list[Candle], *, split: str) -> tuple[datetime | None, datetime | None] | None:
        if not entry_candles:
            return None
        if split == "all":
            return None, None
        cutoff_index = max(1, int(len(entry_candles) * 0.7))
        if cutoff_index >= len(entry_candles):
            cutoff_index = len(entry_candles) - 1
        cutoff_time = entry_candles[cutoff_index].time
        test_start = entry_candles[min(cutoff_index + 1, len(entry_candles) - 1)].time
        if split == "train":
            return None, cutoff_time
        if split == "test":
            return test_start, None
        return None, None

    def _resolve_entry_timeframe(self, symbol: str, preferred: list[str]) -> tuple[str, str | None]:
        for candidate_symbol in self._candidate_symbols(symbol):
            for timeframe in preferred:
                if self._csv_path(candidate_symbol, timeframe).exists():
                    return candidate_symbol, timeframe
        return symbol, None

    @staticmethod
    def _candidate_symbols(symbol: str) -> list[str]:
        cleaned = symbol.strip()
        if not cleaned:
            return []
        candidates = [cleaned]
        if cleaned.endswith("m"):
            base_symbol = cleaned[:-1]
            if base_symbol:
                candidates.append(base_symbol)
        else:
            candidates.append(f"{cleaned}m")
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped

    @staticmethod
    def _passes_hour_filters(
        time_value: datetime,
        allowed_hours_utc: set[int],
        blocked_hours_utc: set[int],
    ) -> bool:
        hour = time_value.astimezone(timezone.utc).hour
        if allowed_hours_utc and hour not in allowed_hours_utc:
            return False
        if blocked_hours_utc and hour in blocked_hours_utc:
            return False
        return True

    @staticmethod
    def _passes_direction_filter(direction: str, direction_filter: str) -> bool:
        if direction_filter == "short_only":
            return direction == "short"
        if direction_filter == "long_only":
            return direction == "long"
        return True

    @classmethod
    def _atr_band_from_values(cls, atr_values: list[float | None], index: int, lookback: int) -> str:
        percentile = cls._atr_percentile_value(atr_values, index, lookback)
        if percentile is None:
            return "unknown"
        if percentile < 20:
            return "p00_20"
        if percentile < 40:
            return "p20_40"
        if percentile < 60:
            return "p40_60"
        if percentile < 80:
            return "p60_80"
        return "p80_100"

    @staticmethod
    def _atr_percentile_value(atr_values: list[float | None], index: int, lookback: int) -> float | None:
        if index <= 0:
            return None
        window = [value for value in atr_values[max(0, index - lookback + 1) : index + 1] if value is not None]
        current = atr_values[index]
        if current is None or len(window) < 20:
            return None
        ordered = sorted(window)
        less_or_equal = sum(1 for value in ordered if value <= current)
        return (less_or_equal / len(ordered)) * 100

    @staticmethod
    def _confirmation_size_band(ratio: float | None) -> str:
        if ratio is None:
            return "unknown"
        if ratio < 0.8:
            return "small_lt_0.8_atr"
        if ratio < 1.2:
            return "medium_0.8_1.2_atr"
        if ratio < 1.8:
            return "large_1.2_1.8_atr"
        return "extreme_gt_1.8_atr"

    @classmethod
    def _entry_reason(
        cls,
        candle: Candle,
        zone: Zone,
        *,
        confirmation_mode: str,
        large_confirmation_atr_multiple: float,
        retrace_fraction: float,
        atr: float,
    ) -> str:
        parts = cls._rejection_signals(candle, zone)
        candle_range = max(0.0000001, candle.high - candle.low)
        if confirmation_mode == "strict" and not parts:
            parts.append("strict_rejection")
        if candle_range >= atr * large_confirmation_atr_multiple and retrace_fraction > 0:
            parts.append("retrace_entry")
        else:
            parts.append("next_open_entry")
        return "+".join(parts)

    @staticmethod
    def _rejection_signals(candle: Candle, zone: Zone) -> list[str]:
        body = abs(candle.close - candle.open)
        candle_range = max(0.0000001, candle.high - candle.low)
        lower_wick = min(candle.open, candle.close) - candle.low
        upper_wick = candle.high - max(candle.open, candle.close)
        wick = lower_wick >= max(body * 0.6, candle_range * 0.25) if zone.direction == "long" else upper_wick >= max(body * 0.6, candle_range * 0.25)
        displacement = candle_range > 0 and body >= candle_range * 0.65
        close_back = candle.close >= zone.midpoint and candle.close > candle.open if zone.direction == "long" else candle.close <= zone.midpoint and candle.close < candle.open
        parts: list[str] = []
        if wick:
            parts.append("wick_rejection")
        if displacement:
            parts.append("displacement_candle")
        if close_back:
            parts.append("close_back_inside_structure")
        return parts

    @staticmethod
    def _derive_session_bucket(entry_time: datetime) -> str:
        in_london = BlueprintBacktester._is_in_session(entry_time, "london")
        in_new_york = BlueprintBacktester._is_in_session(entry_time, "new_york")
        if in_london and in_new_york:
            return "london_new_york_overlap"
        if in_london:
            return "london"
        if in_new_york:
            return "new_york"
        return "other"

    @staticmethod
    def _is_in_session(entry_time: datetime, session_name: str) -> bool:
        session = SESSION_WINDOWS.get(session_name)
        if session is None:
            return False
        tz, start_hour, end_hour = session
        localized = entry_time.astimezone(tz)
        return start_hour <= localized.hour < end_hour

    def _csv_path(self, symbol: str, timeframe: str) -> Path:
        return self.input_dir / f"{symbol}_{timeframe}.csv"

    def _load_candles(self, path: Path) -> list[Candle]:
        cache_key = str(path.resolve())
        cached = self._candles_cache.get(cache_key)
        if cached is not None:
            return cached
        candles: list[Candle] = []
        if not path.exists():
            return candles
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not row:
                    continue
                required = (row.get("time"), row.get("open"), row.get("high"), row.get("low"), row.get("close"), row.get("volume"))
                if any(value is None or str(value).strip() == "" for value in required):
                    continue
                candles.append(
                    Candle(
                        time=BlueprintBacktester._parse_time(row["time"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
        candles.sort(key=lambda item: item.time)
        self._candles_cache[cache_key] = candles
        return candles

    @staticmethod
    def _parse_time(value: str) -> datetime:
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _resample(candles: list[Candle], timeframe: str) -> list[Candle]:
        minutes = TIMEFRAME_MINUTES[timeframe]
        buckets: dict[datetime, list[Candle]] = {}
        for candle in candles:
            minutes_from_midnight = candle.time.hour * 60 + candle.time.minute
            bucket_minutes = (minutes_from_midnight // minutes) * minutes
            bucket_time = candle.time.replace(
                hour=bucket_minutes // 60,
                minute=bucket_minutes % 60,
                second=0,
                microsecond=0,
            )
            buckets.setdefault(bucket_time, []).append(candle)
        result: list[Candle] = []
        for bucket_time in sorted(buckets):
            items = buckets[bucket_time]
            result.append(
                Candle(
                    time=bucket_time,
                    open=items[0].open,
                    high=max(item.high for item in items),
                    low=min(item.low for item in items),
                    close=items[-1].close,
                    volume=sum(item.volume for item in items),
                )
            )
        return result

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float | None]:
        if not values:
            return []
        multiplier = 2 / (period + 1)
        result: list[float | None] = [None] * len(values)
        ema_value: float | None = None
        for index, value in enumerate(values):
            if ema_value is None:
                ema_value = value
            else:
                ema_value = (value - ema_value) * multiplier + ema_value
            result[index] = round(ema_value, 8)
        return result

    @staticmethod
    def _atr(candles: list[Candle], period: int) -> list[float | None]:
        if not candles:
            return []
        tr_values: list[float] = []
        prev_close = candles[0].close
        for candle in candles:
            tr = max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close))
            tr_values.append(tr)
            prev_close = candle.close
        result: list[float | None] = [None] * len(candles)
        if not tr_values:
            return result
        avg = tr_values[0]
        for index, tr in enumerate(tr_values):
            if index == 0:
                avg = tr
            else:
                avg = ((avg * (period - 1)) + tr) / period
            result[index] = round(avg, 8)
        return result

    @staticmethod
    def _in_allowed_session(time_value: datetime, sessions: list[str]) -> bool:
        if not sessions:
            return True
        if any((item or "").lower() == "any_session" for item in sessions):
            return True
        for session_name in sessions:
            session = SESSION_WINDOWS.get(session_name.lower())
            if session is None:
                continue
            tz, start_hour, end_hour = session
            localized = time_value.astimezone(tz)
            if start_hour <= localized.hour < end_hour:
                return True
        return False

    def _result_payload(self, spec: BacktestBlueprintSpec, symbol_runs: list[tuple[str, str, list[Trade]]], trades: list[Trade]) -> dict:
        metrics = self._metrics(trades)
        return {
            "strategy_name": spec.strategy_name,
            "family": spec.family,
            "status": "completed",
            "symbols_tested": [symbol for symbol, _, _ in symbol_runs],
            "timeframes_tested": {symbol: timeframe for symbol, timeframe, _ in symbol_runs},
            "metrics": metrics,
            "trade_metadata_fields": [
                "ob_detected",
                "htf_bias",
                "rejection_type",
                "confirmation_band",
                "atr_band",
                "session",
                "hour_utc",
                "direction",
                "entry_reason",
                "exit_reason",
            ],
            "limitations": self._limitations(),
            "source_traceability": spec.source_traceability,
        }

    def _write_empty_result(self, spec: BacktestBlueprintSpec, reason: str) -> dict:
        result_payload = {
            "strategy_name": spec.strategy_name,
            "family": spec.family,
            "status": "skipped",
            "reason": reason,
            "limitations": self._limitations(),
            "source_traceability": spec.source_traceability,
        }
        result_json = self.results_dir / f"{self._slug(spec.strategy_name)}_results.json"
        trades_csv = self.results_dir / f"{self._slug(spec.strategy_name)}_trades.csv"
        report_md = self.reports_dir / f"{self._slug(spec.strategy_name)}_report.md"
        result_json.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_trades_csv(trades_csv, [])
        report_md.write_text(self._markdown_skipped(spec, reason), encoding="utf-8")
        return {
            "strategy_name": spec.strategy_name,
            "status": "skipped",
            "reason": reason,
            "result_path": str(result_json.resolve()),
            "trades_path": str(trades_csv.resolve()),
            "report_path": str(report_md.resolve()),
        }

    @staticmethod
    def _metrics(trades: list[Trade]) -> dict:
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "max_drawdown": 0.0,
                "avg_rr": 0.0,
                "losing_streak": 0,
                "best_trade": None,
                "worst_trade": None,
            }
        total_trades = len(trades)
        wins = [trade for trade in trades if trade.pnl_r > 0]
        losses = [trade for trade in trades if trade.pnl_r < 0]
        gross_profit = sum(trade.pnl_r for trade in wins)
        gross_loss = abs(sum(trade.pnl_r for trade in losses))
        expectancy = sum(trade.pnl_r for trade in trades) / total_trades
        avg_rr = sum(trade.pnl_r for trade in trades) / total_trades
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        current_losing_streak = 0
        worst_losing_streak = 0
        for trade in trades:
            equity += trade.pnl_r
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            if trade.pnl_r < 0:
                current_losing_streak += 1
                worst_losing_streak = max(worst_losing_streak, current_losing_streak)
            else:
                current_losing_streak = 0
        best_trade = max(trades, key=lambda item: item.pnl_r)
        worst_trade = min(trades, key=lambda item: item.pnl_r)
        return {
            "total_trades": total_trades,
            "win_rate": round((len(wins) / total_trades) * 100, 2),
            "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4),
            "expectancy": round(expectancy, 4),
            "max_drawdown": round(max_drawdown, 4),
            "avg_rr": round(avg_rr, 4),
            "losing_streak": worst_losing_streak,
            "best_trade": {"symbol": best_trade.symbol, "pnl_r": best_trade.pnl_r, "result": best_trade.result},
            "worst_trade": {"symbol": worst_trade.symbol, "pnl_r": worst_trade.pnl_r, "result": worst_trade.result},
        }

    @staticmethod
    def _write_trades_csv(path: Path, trades: list[Trade]) -> None:
        fields = [
            "strategy_name",
            "symbol",
            "direction",
            "ob_detected",
            "htf_bias",
            "rejection_type",
            "confirmation_band",
            "atr_band",
            "hour_utc",
            "entry_time",
            "exit_time",
            "entry_price",
            "exit_price",
            "stop_price",
            "take_profit_price",
            "result",
            "pnl_r",
            "rr_target",
            "session",
            "setup_time",
            "context_timeframe",
            "entry_timeframe",
            "entry_reason",
            "exit_reason",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for trade in trades:
                row = asdict(trade)
                row["entry_time"] = trade.entry_time.isoformat()
                row["exit_time"] = trade.exit_time.isoformat()
                row["setup_time"] = trade.setup_time.isoformat()
                writer.writerow(row)

    def _markdown_report(self, spec: BacktestBlueprintSpec, payload: dict) -> str:
        metrics = payload["metrics"]
        lines = [
            f"# Backtest Report: {spec.strategy_name}",
            "",
            f"- family: {spec.family}",
            f"- total_trades: {metrics['total_trades']}",
            f"- win_rate: {metrics['win_rate']}",
            f"- profit_factor: {metrics['profit_factor']}",
            f"- expectancy: {metrics['expectancy']}",
            f"- max_drawdown: {metrics['max_drawdown']}",
            f"- avg_rr: {metrics['avg_rr']}",
            f"- losing_streak: {metrics['losing_streak']}",
            "",
            "## Limitations",
        ]
        lines.extend(f"- {item}" for item in self._limitations())
        return "\n".join(lines) + "\n"

    def _markdown_skipped(self, spec: BacktestBlueprintSpec, reason: str) -> str:
        lines = [
            f"# Backtest Report: {spec.strategy_name}",
            "",
            f"- status: skipped",
            f"- reason: {reason}",
            "",
            "## Limitations",
        ]
        lines.extend(f"- {item}" for item in self._limitations())
        return "\n".join(lines) + "\n"

    @staticmethod
    def _limitations() -> list[str]:
        return [
            "This is a conservative heuristic backtester, not a tick-accurate engine.",
            "If SL and TP are touched in the same candle, the engine assumes SL first.",
            "Naive CSV timestamps are interpreted as UTC.",
            "H1 context is derived from lower timeframes when a dedicated H1 CSV is missing.",
            "Order block and BOS detection are proxies based on OHLCV and EMA/ATR rules, not full discretionary SMC interpretation.",
            "Entry is taken on the next candle open after confirmation to avoid lookahead bias.",
        ]

    @staticmethod
    def _slug(value: str) -> str:
        return (
            value.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace(":", "")
            .replace("|", "_")
        )
