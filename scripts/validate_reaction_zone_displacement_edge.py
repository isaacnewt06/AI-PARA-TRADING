"""Validate the displacement_AGG bucket for REACTION_ZONE_EXPANSION_BRAIN.

Research only. This script does not modify live/demo trading logic.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.blueprint_backtester import Candle
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester, NY_TZ


INPUT_DIR = ROOT / "data" / "backtests" / "input"
OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "V1_displacement_validation"
YEARLY_DIR = ROOT / "data" / "backtests" / "maximo_mtf_quant_v4" / "yearly"


@dataclass(slots=True)
class ValidationVariant:
    code: str
    label: str
    require_wick_rejection: bool = False
    require_continuation_momentum: bool = False
    require_micro_bos: bool = False
    session_hours: set[int] | None = None
    require_atr_expansion: bool = False
    defensive_management: bool = True
    require_compression: bool = True


@dataclass(slots=True)
class EdgeTrade:
    variant: str
    year: int
    side: str
    signal_time: datetime
    entry_time: datetime
    hour_ny: int
    session: str
    expansion_subtype: str
    continuation_quality: str
    atr_bucket: str
    entry: float
    stop: float
    target: float
    risk: float
    rr: float
    raw_result: str
    raw_r: float
    realized_r: float
    managed_result: str
    mfe_r: float
    mae_r: float
    confidence: int
    mtf_score: int
    opposite_mtf_score: int
    quant_score: int
    impulse_score: int
    atr_ratio: float
    range_ratio: float
    body_pct: float
    wick_rejection_pct: float
    continuation_momentum: bool
    micro_bos: bool
    compression_ok: bool


VARIANTS = [
    ValidationVariant("displacement_gap_only", "1. displacement_AGG solo"),
    ValidationVariant("displacement_plus_wick", "2. displacement_AGG + wick rejection", require_wick_rejection=True),
    ValidationVariant(
        "displacement_plus_continuation",
        "3. displacement_AGG + continuation momentum",
        require_continuation_momentum=True,
    ),
    ValidationVariant("displacement_plus_micro_bos", "4. displacement_AGG + micro BOS", require_micro_bos=True),
    ValidationVariant("displacement_plus_session", "5. displacement_AGG + session filter", session_hours={9, 15, 19}),
    ValidationVariant("displacement_plus_atr", "6. displacement_AGG + ATR expansion", require_atr_expansion=True),
    ValidationVariant("displacement_raw_management_off", "7. displacement_AGG sin gestión defensiva", defensive_management=False),
    ValidationVariant("displacement_no_compression_filter", "8. displacement_AGG + no compression filter", require_compression=False),
]


class DisplacementEdgeValidator:
    allowed_hours_ny = {1, 4, 5, 9, 15, 19}

    def __init__(self) -> None:
        self.bt = MaximoMTFQuantV4Backtester(INPUT_DIR, OUTPUT_DIR)

    def run(self, symbol: str = "XAUUSDm", years: tuple[int, ...] = (2023, 2024, 2025, 2026)) -> dict[str, Any]:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        all_candidates = {year: self._candidates_for_year(symbol=symbol, year=year) for year in years}
        results: list[dict[str, Any]] = []
        all_variant_trades: list[EdgeTrade] = []
        for variant in VARIANTS:
            variant_trades: list[EdgeTrade] = []
            yearly = {}
            for year in years:
                trades = [self._apply_variant(candidate, variant) for candidate in all_candidates[year]]
                trades = [trade for trade in trades if trade is not None]
                yearly[str(year)] = {
                    "metrics": self._metrics(trades),
                    "by_side": self._breakdown(trades, "side"),
                    "by_session": self._breakdown(trades, "session"),
                    "by_expansion_subtype": self._breakdown(trades, "expansion_subtype"),
                    "by_continuation_quality": self._breakdown(trades, "continuation_quality"),
                    "by_atr_bucket": self._breakdown(trades, "atr_bucket"),
                }
                variant_trades.extend(trades)
            result = {
                "variant": asdict(variant),
                "yearly": yearly,
                "aggregate": self._metrics(variant_trades),
                "aggregate_by_side": self._breakdown(variant_trades, "side"),
                "aggregate_by_session": self._breakdown(variant_trades, "session"),
                "aggregate_by_expansion_subtype": self._breakdown(variant_trades, "expansion_subtype"),
                "aggregate_by_continuation_quality": self._breakdown(variant_trades, "continuation_quality"),
                "aggregate_by_atr_bucket": self._breakdown(variant_trades, "atr_bucket"),
                "stability": self._stability(yearly),
            }
            results.append(result)
            all_variant_trades.extend(variant_trades)
            self._write_trades_csv(OUTPUT_DIR / f"{variant.code}_trades.csv", variant_trades)

        payload = {
            "research": "REACTION_ZONE_EXPANSION_BRAIN_V1_displacement_validation",
            "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
            "baseline": "MTF_REAL_H4_FIXED_BASELINE",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "candidate_definition": (
                "Near-candidate where AGG would pass except the classic side-specific displacement_AGG candle. "
                "This validates the displacement_AGG blocker bucket, not live execution."
            ),
            "candidate_counts": {str(year): len(all_candidates[year]) for year in years},
            "results": results,
            "ranking": self._ranking(results),
            "conclusion": self._conclusion(results),
        }
        (OUTPUT_DIR / "displacement_edge_validation.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        (OUTPUT_DIR / "displacement_edge_validation.md").write_text(self._main_report(payload), encoding="utf-8")
        (OUTPUT_DIR / "yearly_stability_matrix.md").write_text(self._yearly_matrix(payload), encoding="utf-8")
        (OUTPUT_DIR / "regime_behavior_matrix.md").write_text(self._regime_matrix(payload), encoding="utf-8")
        return payload

    def _candidates_for_year(self, *, symbol: str, year: int) -> list[dict[str, Any]]:
        family = self.bt._load_year_family(symbol, year)
        if not family.get("M5") or not family.get("H1"):
            return []
        start, end = self._period(year)
        m5 = [c for c in family["M5"] if start <= c.time <= end]
        h1 = [c for c in family["H1"] if start <= c.time <= end]
        m15 = self.bt._resample(m5, "M15")
        h4 = self.bt._resample(h1, "H4")
        context = {
            "macro": self.bt._context_pack(h4),
            "trend": self.bt._context_pack(h1),
            "setup": self.bt._context_pack(m15),
        }
        raw = self._scan_displacement_gap_candidates(year=year, entry_candles=m5, context=context)
        reps = self._cluster(raw)
        real_trade_times = self._real_trade_signal_times(year)
        return [item for item in reps if item["time"] not in real_trade_times]

    def _scan_displacement_gap_candidates(self, *, year: int, entry_candles: list[Candle], context: dict[str, Any]) -> list[dict[str, Any]]:
        closes = [c.close for c in entry_candles]
        highs = [c.high for c in entry_candles]
        lows = [c.low for c in entry_candles]
        volumes = [c.volume for c in entry_candles]
        ema_fast = self.bt._ema(closes, self.bt.FAST_LEN)
        ema_slow = self.bt._ema(closes, self.bt.SLOW_LEN)
        atr_now = self.bt._atr(entry_candles, self.bt.ATR_LEN)
        atr_mean = self.bt._sma(atr_now, self.bt.ATR_MA_LEN)
        bar_range = [c.high - c.low for c in entry_candles]
        range_mean = self.bt._sma(bar_range, self.bt.RANGE_AVG_LEN)
        vol_mean = self.bt._sma(volumes, self.bt.VOL_LEN)
        body_avg = self.bt._sma([abs(c.close - c.open) for c in entry_candles], self.bt.RANGE_AVG_LEN)
        latest_highs, latest_lows = self.bt._latest_swings(highs, lows, self.bt.SWING_LEN)
        daily_open_map = self.bt._daily_open_map(entry_candles)
        macro_map = self.bt._map_completed_indices(entry_candles, context["macro"]["candles"], timedelta(hours=4))
        trend_map = self.bt._map_completed_indices(entry_candles, context["trend"]["candles"], timedelta(hours=1))
        setup_map = self.bt._map_completed_indices(entry_candles, context["setup"]["candles"], timedelta(minutes=15))
        candidates = []
        for index in range(250, len(entry_candles) - 82):
            candle = entry_candles[index]
            hour_ny = candle.time.astimezone(NY_TZ).hour
            if hour_ny not in self.allowed_hours_ny:
                continue
            if any(
                value is None
                for value in (
                    atr_now[index],
                    ema_fast[index],
                    ema_slow[index],
                    atr_mean[index],
                    range_mean[index],
                    body_avg[index],
                    macro_map[index],
                    trend_map[index],
                    setup_map[index],
                )
            ):
                continue
            features = self._features(
                year=year,
                index=index,
                candle=candle,
                entry_candles=entry_candles,
                closes=closes,
                highs=highs,
                lows=lows,
                ema_fast=ema_fast,
                ema_slow=ema_slow,
                atr_now=atr_now,
                atr_mean=atr_mean,
                bar_range=bar_range,
                range_mean=range_mean,
                vol_mean=vol_mean,
                body_avg=body_avg,
                latest_highs=latest_highs,
                latest_lows=latest_lows,
                daily_open_map=daily_open_map,
                context=context,
                macro_idx=macro_map[index],
                trend_idx=trend_map[index],
                setup_idx=setup_map[index],
            )
            if features["market_regime"] != "EXPANSION":
                continue
            for side in ("BUY", "SELL"):
                item = self._candidate_for_side(features, side)
                if item is not None:
                    candidates.append(item)
        return candidates

    def _features(self, **kwargs: Any) -> dict[str, Any]:
        index = kwargs["index"]
        candle: Candle = kwargs["candle"]
        entry_candles: list[Candle] = kwargs["entry_candles"]
        closes = kwargs["closes"]
        highs = kwargs["highs"]
        lows = kwargs["lows"]
        ema_fast = kwargs["ema_fast"]
        ema_slow = kwargs["ema_slow"]
        atr_now = kwargs["atr_now"]
        atr_mean = kwargs["atr_mean"]
        bar_range = kwargs["bar_range"]
        range_mean = kwargs["range_mean"]
        vol_mean = kwargs["vol_mean"]
        body_avg = kwargs["body_avg"]
        latest_highs = kwargs["latest_highs"]
        latest_lows = kwargs["latest_lows"]
        daily_open_map = kwargs["daily_open_map"]
        context = kwargs["context"]
        atr_value = atr_now[index]
        ema_fast_value = ema_fast[index]
        ema_slow_value = ema_slow[index]
        candle_range = max(candle.high - candle.low, 1e-9)
        body_pct = abs(candle.close - candle.open) / candle_range * 100.0
        atr_ratio = atr_value / atr_mean[index] if atr_mean[index] else 1.0
        range_ratio = candle_range / range_mean[index] if range_mean[index] else 1.0
        lower_wick_pct = (min(candle.open, candle.close) - candle.low) / candle_range * 100.0
        upper_wick_pct = (candle.high - max(candle.open, candle.close)) / candle_range * 100.0
        close_power_buy = (candle.close - candle.low) / candle_range
        close_power_sell = (candle.high - candle.close) / candle_range
        local_bull = ema_fast_value > ema_slow_value and candle.close > ema_fast_value
        local_bear = ema_fast_value < ema_slow_value and candle.close < ema_fast_value
        ema_spread_atr = abs(ema_fast_value - ema_slow_value) / max(atr_value, 1e-9)
        ema_fast_prev_3 = ema_fast[index - 3] if index >= 3 and ema_fast[index - 3] is not None else ema_fast_value
        ema_slope_atr = abs(ema_fast_value - ema_fast_prev_3) / max(atr_value, 1e-9)
        local_slope_up = index > 0 and ema_fast[index - 1] is not None and ema_fast_value > ema_fast[index - 1]
        local_slope_down = index > 0 and ema_fast[index - 1] is not None and ema_fast_value < ema_fast[index - 1]
        chop_ratio = body_avg[index] / range_mean[index] if range_mean[index] else 1.0
        quant_expansion_ok = atr_ratio >= self.bt.MIN_ATR_EXPANSION or range_ratio >= self.bt.MIN_RANGE_EXPANSION
        quant_chop_ok = chop_ratio <= self.bt.MAX_CHOP_RATIO or range_ratio >= 1.20
        quant_ok = quant_expansion_ok and ema_spread_atr >= self.bt.MIN_EMA_SPREAD_ATR and ema_slope_atr >= self.bt.MIN_SLOPE_ATR and quant_chop_ok
        macro_row = context["macro"]["rows"][kwargs["macro_idx"]]
        trend_row = context["trend"]["rows"][kwargs["trend_idx"]]
        setup_row = context["setup"]["rows"][kwargs["setup_idx"]]
        day_open = daily_open_map.get(candle.time.date(), candle.open)
        buy_mtf_score, sell_mtf_score = self.bt._mtf_scores(
            local_bull=local_bull,
            local_bear=local_bear,
            macro_row=macro_row,
            trend_row=trend_row,
            setup_row=setup_row,
            day_bull=candle.close > day_open,
            day_bear=candle.close < day_open,
        )
        recent_compression = self.bt._recent_compression(index, atr_now, atr_mean, bar_range, range_mean)
        compression_ok = recent_compression or atr_ratio >= 1.10 or range_ratio >= 1.20
        velocity_ref = closes[index - self.bt.VELOCITY_LEN] if index >= self.bt.VELOCITY_LEN else closes[0]
        velocity_signed = (candle.close - velocity_ref) / max(atr_value, 1e-9)
        velocity = abs(velocity_signed)
        impulse_score = 0
        impulse_score += 20 if body_pct >= self.bt.BODY_MIN_AGG else 0
        impulse_score += 20 if range_ratio >= self.bt.MIN_RANGE_EXPANSION else 0
        impulse_score += 20 if velocity >= 0.35 else 0
        impulse_score += 20 if ema_slope_atr >= self.bt.MIN_SLOPE_ATR else 0
        impulse_score += 20 if compression_ok else 0
        impulse_score = min(100, impulse_score)
        quant_score = 0
        quant_score += 20 if atr_ratio >= self.bt.MIN_ATR_EXPANSION else 0
        quant_score += 20 if range_ratio >= self.bt.MIN_RANGE_EXPANSION else 0
        quant_score += 20 if ema_spread_atr >= self.bt.MIN_EMA_SPREAD_ATR else 0
        quant_score += 20 if ema_slope_atr >= self.bt.MIN_SLOPE_ATR else 0
        quant_score += 20 if quant_chop_ok else 0
        quant_score += self.bt.COMPRESSION_BONUS if recent_compression else 0
        quant_score = min(100, quant_score)
        market_regime = "EXPANSION" if quant_score >= 75 and impulse_score >= 65 and (buy_mtf_score >= 65 or sell_mtf_score >= 65) else "NORMAL" if quant_score >= 55 else "CHOP"
        preferred_side = "BUY" if buy_mtf_score > sell_mtf_score + 15 else "SELL" if sell_mtf_score > buy_mtf_score + 15 else "NEUTRAL"
        return {
            "year": kwargs["year"],
            "index": index,
            "time": candle.time,
            "hour_ny": candle.time.astimezone(NY_TZ).hour,
            "candle": candle,
            "entry_candles": entry_candles,
            "atr": atr_value,
            "atr_ratio": atr_ratio,
            "range_ratio": range_ratio,
            "body_pct": body_pct,
            "lower_wick_pct": lower_wick_pct,
            "upper_wick_pct": upper_wick_pct,
            "close_power_buy": close_power_buy,
            "close_power_sell": close_power_sell,
            "local_bull": local_bull,
            "local_bear": local_bear,
            "local_slope_up": local_slope_up,
            "local_slope_down": local_slope_down,
            "ema_fast": ema_fast_value,
            "ema_slow": ema_slow_value,
            "ema_spread_atr": ema_spread_atr,
            "ema_slope_atr": ema_slope_atr,
            "quant_ok": quant_ok,
            "compression_ok": compression_ok,
            "buy_mtf_score": buy_mtf_score,
            "sell_mtf_score": sell_mtf_score,
            "quant_score": quant_score,
            "impulse_score": impulse_score,
            "market_regime": market_regime,
            "preferred_side": preferred_side,
            "velocity_signed": velocity_signed,
            "latest_highs": kwargs["latest_highs"],
            "latest_lows": kwargs["latest_lows"],
        }

    def _candidate_for_side(self, f: dict[str, Any], side: str) -> dict[str, Any] | None:
        candle: Candle = f["candle"]
        index = f["index"]
        highs = [c.high for c in f["entry_candles"]]
        lows = [c.low for c in f["entry_candles"]]
        if side == "BUY":
            pullback = f["local_bull"] and f["local_slope_up"] and candle.low <= f["ema_fast"] + f["atr"] * self.bt.PULLBACK_ATR_PCT and candle.close > f["ema_fast"] and candle.close > candle.open
            displacement = candle.close > candle.open and f["body_pct"] >= self.bt.BODY_MIN_AGG and f["close_power_buy"] >= 0.52
            mtf_score = f["buy_mtf_score"]
            opposite_mtf = f["sell_mtf_score"]
            confidence = min(100, round((mtf_score * 0.28) + (f["quant_score"] * 0.25) + (f["impulse_score"] * 0.22) + (((20 if f["local_bull"] else 0) + (15 if f["local_slope_up"] else 0) + (15 if f["ema_spread_atr"] >= self.bt.MIN_EMA_SPREAD_ATR else 0)) * 0.15) + (((25 if pullback else 0) + (10 if displacement else 0)) * 0.10)))
            wick_pct = f["lower_wick_pct"]
            continuation = f["velocity_signed"] >= 0.35 and candle.close > candle.open
            micro_bos = index >= 3 and candle.high > max(highs[index - 3 : index])
            stop = min(candle.low, f["ema_slow"] - f["atr"] * self.bt.SL_ATR_PCT)
            entry = f["entry_candles"][index + 1].open
            risk = entry - stop
            target = entry + risk * self.bt._resolve_rr(is_a=False, market_regime=f["market_regime"], quant_score=f["quant_score"], impulse_score=f["impulse_score"])
            preferred_ok = f["preferred_side"] != "SELL"
        else:
            pullback = f["local_bear"] and f["local_slope_down"] and candle.high >= f["ema_fast"] - f["atr"] * self.bt.PULLBACK_ATR_PCT and candle.close < f["ema_fast"] and candle.close < candle.open
            displacement = candle.close < candle.open and f["body_pct"] >= self.bt.BODY_MIN_AGG and f["close_power_sell"] >= 0.52
            mtf_score = f["sell_mtf_score"]
            opposite_mtf = f["buy_mtf_score"]
            confidence = min(100, round((mtf_score * 0.28) + (f["quant_score"] * 0.25) + (f["impulse_score"] * 0.22) + (((20 if f["local_bear"] else 0) + (15 if f["local_slope_down"] else 0) + (15 if f["ema_spread_atr"] >= self.bt.MIN_EMA_SPREAD_ATR else 0)) * 0.15) + (((25 if pullback else 0) + (10 if displacement else 0)) * 0.10)))
            wick_pct = f["upper_wick_pct"]
            continuation = f["velocity_signed"] <= -0.35 and candle.close < candle.open
            micro_bos = index >= 3 and candle.low < min(lows[index - 3 : index])
            stop = max(candle.high, f["ema_slow"] + f["atr"] * self.bt.SL_ATR_PCT)
            entry = f["entry_candles"][index + 1].open
            risk = stop - entry
            target = entry - risk * self.bt._resolve_rr(is_a=False, market_regime=f["market_regime"], quant_score=f["quant_score"], impulse_score=f["impulse_score"])
            preferred_ok = f["preferred_side"] != "BUY"

        conditions = {
            "pullback_valid": pullback,
            "displacement_AGG": displacement,
            "mtf_score_58": mtf_score >= self.bt.MIN_QUANT_AGG,
            "quant_ok": f["quant_ok"],
            "compression_ok": f["compression_ok"],
            "impulse_ok": f["impulse_score"] >= self.bt.MIN_IMPULSE_AGG,
            "quant_score_ok": f["quant_score"] >= self.bt.MIN_QUANT_AGG,
            "confidence_AGG": confidence >= self.bt.MIN_CONF_AGG,
            "preferred_side_not_opposite": preferred_ok,
        }
        missing = [key for key, ok in conditions.items() if not ok]
        if missing != ["displacement_AGG"]:
            return None
        if risk <= 0 or risk > f["atr"] * self.bt.MAX_RISK_ATR * 1.25:
            return None
        return {
            **f,
            "side": side,
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk": risk,
            "rr": self.bt._resolve_rr(is_a=False, market_regime=f["market_regime"], quant_score=f["quant_score"], impulse_score=f["impulse_score"]),
            "confidence": confidence,
            "mtf_score": mtf_score,
            "opposite_mtf_score": opposite_mtf,
            "wick_rejection_pct": wick_pct,
            "wick_rejection": wick_pct >= 28.0,
            "continuation_momentum": continuation,
            "micro_bos": micro_bos,
            "session": self._session(f["hour_ny"]),
            "atr_bucket": self._atr_bucket(f["atr_ratio"]),
            "expansion_subtype": self._expansion_subtype(f),
            "continuation_quality": self._continuation_quality(continuation, micro_bos, wick_pct),
        }

    def _apply_variant(self, candidate: dict[str, Any], variant: ValidationVariant) -> EdgeTrade | None:
        if variant.require_wick_rejection and not candidate["wick_rejection"]:
            return None
        if variant.require_continuation_momentum and not candidate["continuation_momentum"]:
            return None
        if variant.require_micro_bos and not candidate["micro_bos"]:
            return None
        if variant.session_hours is not None and candidate["hour_ny"] not in variant.session_hours:
            return None
        if variant.require_atr_expansion and candidate["atr_ratio"] < 1.0:
            return None
        if variant.require_compression and not candidate["compression_ok"]:
            return None
        return self._simulate(candidate, variant)

    def _simulate(self, candidate: dict[str, Any], variant: ValidationVariant) -> EdgeTrade | None:
        entry_candles: list[Candle] = candidate["entry_candles"]
        entry_index = candidate["index"] + 1
        entry = candidate["entry"]
        stop = candidate["stop"]
        target = candidate["target"]
        risk = candidate["risk"]
        max_scan = min(len(entry_candles), entry_index + 80)
        mfe = mae = 0.0
        partial = protected = False
        raw_result = managed_result = "OPEN_UNKNOWN"
        raw_r = realized_r = 0.0
        for idx in range(entry_index, max_scan):
            candle = entry_candles[idx]
            if candidate["side"] == "BUY":
                favorable = (candle.high - entry) / risk
                adverse = (entry - candle.low) / risk
                stop_hit = candle.low <= stop
                target_hit = candle.high >= target
            else:
                favorable = (entry - candle.low) / risk
                adverse = (candle.high - entry) / risk
                stop_hit = candle.high >= stop
                target_hit = candle.low <= target
            mfe = max(mfe, favorable)
            mae = max(mae, adverse)
            if favorable >= 0.5:
                partial = True
            if favorable >= 0.8:
                protected = True
            if stop_hit or target_hit:
                if stop_hit:
                    raw_result = "SL"
                    raw_r = -1.01
                    if not variant.defensive_management:
                        managed_result = "SL_RAW"
                        realized_r = raw_r
                    elif protected:
                        managed_result = "PROTECTED_STOP_AFTER_0_8R"
                        realized_r = 0.4
                    elif partial:
                        managed_result = "BE_AFTER_PARTIAL"
                        realized_r = 0.25
                    else:
                        managed_result = "SL"
                        realized_r = -1.01
                else:
                    raw_result = "TP"
                    raw_r = candidate["rr"] - 0.01
                    managed_result = "TP_RAW" if not variant.defensive_management else "TP_WITH_PARTIAL"
                    realized_r = raw_r if not variant.defensive_management else 0.25 + candidate["rr"] * 0.5
                break
        else:
            close = entry_candles[max_scan - 1].close
            raw_r = ((close - entry) / risk) if candidate["side"] == "BUY" else ((entry - close) / risk)
            raw_result = "OPEN_UNKNOWN_WIN" if raw_r > 0 else "OPEN_UNKNOWN_LOSS"
            realized_r = raw_r
            managed_result = raw_result
        return EdgeTrade(
            variant=variant.code,
            year=candidate["year"],
            side=candidate["side"],
            signal_time=candidate["time"],
            entry_time=entry_candles[entry_index].time,
            hour_ny=candidate["hour_ny"],
            session=candidate["session"],
            expansion_subtype=candidate["expansion_subtype"],
            continuation_quality=candidate["continuation_quality"],
            atr_bucket=candidate["atr_bucket"],
            entry=round(entry, 5),
            stop=round(stop, 5),
            target=round(target, 5),
            risk=round(risk, 5),
            rr=round(candidate["rr"], 4),
            raw_result=raw_result,
            raw_r=round(raw_r, 4),
            realized_r=round(realized_r, 4),
            managed_result=managed_result,
            mfe_r=round(mfe, 4),
            mae_r=round(mae, 4),
            confidence=candidate["confidence"],
            mtf_score=candidate["mtf_score"],
            opposite_mtf_score=candidate["opposite_mtf_score"],
            quant_score=candidate["quant_score"],
            impulse_score=candidate["impulse_score"],
            atr_ratio=round(candidate["atr_ratio"], 4),
            range_ratio=round(candidate["range_ratio"], 4),
            body_pct=round(candidate["body_pct"], 4),
            wick_rejection_pct=round(candidate["wick_rejection_pct"], 4),
            continuation_momentum=candidate["continuation_momentum"],
            micro_bos=candidate["micro_bos"],
            compression_ok=candidate["compression_ok"],
        )

    @staticmethod
    def _metrics(trades: list[EdgeTrade]) -> dict[str, Any]:
        if not trades:
            return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0, "net_R": 0.0, "max_drawdown_R": 0.0, "losing_streak": 0}
        wins = [t.realized_r for t in trades if t.realized_r > 0]
        losses = [t.realized_r for t in trades if t.realized_r < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        equity = peak = max_dd = 0.0
        streak = losing_streak = 0
        for trade in trades:
            equity += trade.realized_r
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if trade.realized_r < 0:
                streak += 1
                losing_streak = max(losing_streak, streak)
            else:
                streak = 0
        net = sum(t.realized_r for t in trades)
        return {
            "trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100.0, 2),
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else 999.0,
            "expectancy_R": round(net / len(trades), 4),
            "net_R": round(net, 4),
            "max_drawdown_R": round(max_dd, 4),
            "losing_streak": losing_streak,
        }

    def _breakdown(self, trades: list[EdgeTrade], attr: str) -> dict[str, Any]:
        grouped: dict[str, list[EdgeTrade]] = defaultdict(list)
        for trade in trades:
            grouped[str(getattr(trade, attr))].append(trade)
        return {key: self._metrics(bucket) for key, bucket in sorted(grouped.items())}

    @staticmethod
    def _stability(yearly: dict[str, Any]) -> dict[str, Any]:
        full = [yearly[str(year)]["metrics"] for year in (2023, 2024, 2025)]
        positive_full_years = sum(1 for metric in full if metric["trades"] >= 10 and metric["profit_factor"] >= 1.2 and metric["expectancy_R"] > 0)
        worst_pf = min((metric["profit_factor"] for metric in full if metric["trades"] > 0), default=0.0)
        worst_dd = max((metric["max_drawdown_R"] for metric in full), default=0.0)
        return {
            "positive_full_years": positive_full_years,
            "worst_full_year_pf": round(worst_pf, 4),
            "worst_full_year_dd_R": round(worst_dd, 4),
            "is_stable": positive_full_years >= 3 and worst_dd <= 8.0,
        }

    @staticmethod
    def _ranking(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = sorted(
            results,
            key=lambda item: (
                item["stability"]["positive_full_years"],
                item["aggregate"]["profit_factor"],
                item["aggregate"]["expectancy_R"],
                -item["aggregate"]["max_drawdown_R"],
            ),
            reverse=True,
        )
        return [
            {
                "variant": item["variant"]["code"],
                "label": item["variant"]["label"],
                "aggregate": item["aggregate"],
                "stability": item["stability"],
            }
            for item in ranked
        ]

    @staticmethod
    def _conclusion(results: list[dict[str, Any]]) -> str:
        stable = [item for item in results if item["stability"]["is_stable"]]
        if not stable:
            return "DISPLACEMENT_EDGE_NEEDS_MORE_DATA_OR_FILTERING"
        best = max(stable, key=lambda item: (item["aggregate"]["profit_factor"], item["aggregate"]["expectancy_R"]))
        return f"DISPLACEMENT_EDGE_VALIDATED_FOR_RESEARCH:{best['variant']['code']}"

    @staticmethod
    def _period(year: int) -> tuple[datetime, datetime]:
        if year == 2026:
            return datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc)
        return datetime(year, 1, 1, tzinfo=timezone.utc), datetime(year, 12, 31, 23, 59, tzinfo=timezone.utc)

    @staticmethod
    def _session(hour_ny: int) -> str:
        if hour_ny == 1:
            return "asia_to_london"
        if hour_ny in {4, 5}:
            return "london"
        if hour_ny == 9:
            return "ny_am"
        if hour_ny == 15:
            return "ny_pm"
        if hour_ny == 19:
            return "asia_open"
        return "other"

    @staticmethod
    def _atr_bucket(atr_ratio: float) -> str:
        if atr_ratio < 0.85:
            return "low_atr"
        if atr_ratio < 1.10:
            return "normal_atr"
        if atr_ratio < 1.45:
            return "high_atr"
        return "extreme_atr"

    @staticmethod
    def _expansion_subtype(f: dict[str, Any]) -> str:
        if f["atr_ratio"] >= 1.45 or f["range_ratio"] >= 1.75:
            return "extended_expansion"
        if f["quant_score"] >= 88 and f["impulse_score"] >= 80:
            return "clean_expansion"
        if f["atr_ratio"] < 0.85:
            return "thin_expansion"
        return "standard_expansion"

    @staticmethod
    def _continuation_quality(continuation: bool, micro_bos: bool, wick_pct: float) -> str:
        score = int(continuation) + int(micro_bos) + int(wick_pct >= 28.0)
        if score >= 3:
            return "strong"
        if score == 2:
            return "medium"
        return "weak"

    @staticmethod
    def _cluster(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        representatives = []
        active: list[dict[str, Any]] = []
        for item in candidates:
            if not active or (item["time"] - active[-1]["time"] <= timedelta(minutes=20) and item["side"] == active[-1]["side"]):
                active.append(item)
                continue
            representatives.append(max(active, key=lambda row: (row["confidence"], row["mtf_score"], -row["risk"])))
            active = [item]
        if active:
            representatives.append(max(active, key=lambda row: (row["confidence"], row["mtf_score"], -row["risk"])))
        return representatives

    def _real_trade_signal_times(self, year: int) -> set[datetime]:
        candidates = [
            YEARLY_DIR / f"{year}_v56_aggressive_filtered_b_all_h4_fixed_trades.csv",
            YEARLY_DIR / f"{year}_v56_aggressive_filtered_b_all_jan_mar_partial_h4_fixed_trades.csv",
            YEARLY_DIR / "2025_v56_aggressive_filtered_b_all_trades.csv",
        ]
        path = next((item for item in candidates if item.exists()), None)
        if path is None:
            return set()
        result: set[datetime] = set()
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                value = row.get("signal_time") or row.get("entry_time")
                if value:
                    result.add(datetime.fromisoformat(value))
        return result

    @staticmethod
    def _write_trades_csv(path: Path, trades: list[EdgeTrade]) -> None:
        if not trades:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(trades[0]).keys()))
            writer.writeheader()
            for trade in trades:
                writer.writerow(asdict(trade))

    @staticmethod
    def _metric_row(metric: dict[str, Any]) -> str:
        return f"{metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | {metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']}"

    def _main_report(self, payload: dict[str, Any]) -> str:
        lines = [
            "# REACTION_ZONE_EXPANSION_BRAIN_V1_displacement_validation",
            "",
            f"- status: {payload['status']}",
            f"- baseline: `{payload['baseline']}`",
            f"- conclusion: `{payload['conclusion']}`",
            f"- candidate_definition: {payload['candidate_definition']}",
            "",
            "## Ranking",
            "",
            "| Rank | Variant | Trades | WR | PF | Exp R | Net R | DD R | Stable Full Years |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for rank, item in enumerate(payload["ranking"], start=1):
            metric = item["aggregate"]
            lines.append(
                f"| {rank} | {item['label']} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {item['stability']['positive_full_years']} |"
            )
        lines.extend(["", "## Variant Summary", "", "| Variant | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
        for item in payload["results"]:
            lines.append(f"| {item['variant']['label']} | {self._metric_row(item['aggregate'])} |")
        lines.extend(["", "## BUY vs SELL"])
        for item in payload["results"]:
            lines.extend(["", f"### {item['variant']['label']}", "", "| Side | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
            for side, metric in item["aggregate_by_side"].items():
                lines.append(f"| {side} | {self._metric_row(metric)} |")
        return "\n".join(lines) + "\n"

    def _yearly_matrix(self, payload: dict[str, Any]) -> str:
        lines = ["# Yearly Stability Matrix", "", "| Variant | Year | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for item in payload["results"]:
            for year in ("2023", "2024", "2025", "2026"):
                lines.append(f"| {item['variant']['label']} | {year} | {self._metric_row(item['yearly'][year]['metrics'])} |")
        return "\n".join(lines) + "\n"

    def _regime_matrix(self, payload: dict[str, Any]) -> str:
        lines = ["# Regime Behavior Matrix", ""]
        for breakdown_key, title in (
            ("aggregate_by_session", "London vs NY / Sessions"),
            ("aggregate_by_expansion_subtype", "Expansion Subtype"),
            ("aggregate_by_continuation_quality", "Continuation Quality"),
            ("aggregate_by_atr_bucket", "ATR Range"),
        ):
            lines.extend(["", f"## {title}"])
            for item in payload["results"]:
                lines.extend(["", f"### {item['variant']['label']}", "", "| Bucket | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
                for bucket, metric in item[breakdown_key].items():
                    lines.append(f"| {bucket} | {self._metric_row(metric)} |")
        return "\n".join(lines) + "\n"


def main() -> None:
    payload = DisplacementEdgeValidator().run()
    print(
        json.dumps(
            {
                "conclusion": payload["conclusion"],
                "candidate_counts": payload["candidate_counts"],
                "report": str((OUTPUT_DIR / "displacement_edge_validation.md").resolve()),
                "ranking": payload["ranking"][:3],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
