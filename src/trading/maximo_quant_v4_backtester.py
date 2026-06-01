"""Dedicated backtester for the TradingView strategy MAXIMO MTF Quant Institutional v4."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.core.logging import get_logger
from src.trading.blueprint_backtester import BlueprintBacktester, Candle

logger = get_logger(__name__)

NY_TZ = ZoneInfo("America/New_York")


@dataclass(slots=True)
class SessionVariant:
    code: str
    label: str
    windows: list[tuple[time, time]]


@dataclass(slots=True)
class StrategyVariant:
    code: str
    label: str
    a_plus_only: bool = False
    require_preferred_side: bool = False
    allowed_directions: set[str] | None = None
    allowed_setup_types: set[str] | None = None
    disallow_chop: bool = False
    min_quant_score: int = 0
    min_impulse_score: int = 0
    allowed_hours_ny: set[int] | None = None
    excluded_hours_ny: set[int] | None = None
    require_recent_compression_for_agg: bool = False
    disallow_normal_hours_ny: set[int] | None = None
    require_quant_expansion: bool = False
    require_recent_compression: bool = False
    min_atr_ratio: float | None = None
    min_range_ratio: float | None = None
    max_atr_ratio: float | None = None
    max_range_ratio: float | None = None


@dataclass(slots=True)
class PendingOrder:
    direction: str
    setup_type: str
    signal_index: int
    signal_time: datetime
    desired_entry: float
    stop_price: float
    target_price: float
    risk_per_unit: float
    selected_rr: float
    quant_score: int
    impulse_score: int
    buy_mtf_score: int
    sell_mtf_score: int
    confidence: int
    market_regime: str
    expires_index: int


@dataclass(slots=True)
class OpenTrade:
    direction: str
    setup_type: str
    signal_index: int
    signal_time: datetime
    entry_time: datetime
    entry_price: float
    stop_price: float
    target_price: float
    initial_stop_price: float
    risk_per_unit: float
    selected_rr: float
    quant_score: int
    impulse_score: int
    buy_mtf_score: int
    sell_mtf_score: int
    confidence: int
    market_regime: str


@dataclass(slots=True)
class ClosedTrade:
    symbol: str
    dataset_label: str
    timeframe: str
    session_variant: str
    setup_type: str
    direction: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    initial_stop_price: float
    risk_per_unit: float
    selected_rr: float
    quant_score: int
    impulse_score: int
    buy_mtf_score: int
    sell_mtf_score: int
    confidence: int
    market_regime: str
    month: str
    hour_ny: int
    pnl_r: float
    exit_reason: str


class MaximoMTFQuantV4Backtester:
    """Research backtester for the TradingView strategy MAXIMO MTF Quant Institutional v4."""

    FAST_LEN = 20
    SLOW_LEN = 50
    ATR_LEN = 14
    ATR_MA_LEN = 50
    RANGE_AVG_LEN = 20
    VOL_LEN = 20
    VELOCITY_LEN = 3
    COMPRESSION_LOOKBACK = 12
    LIQUIDITY_LOOKBACK = 20
    SWING_LEN = 5
    RANGE_LEN = 80

    BODY_MIN_A = 52.0
    BODY_MIN_AGG = 38.0
    CLOSE_EXTREME_PCT = 38.0

    MIN_QUANT_A = 72
    MIN_QUANT_AGG = 58
    MIN_CONF_A = 74
    MIN_CONF_AGG = 60
    MIN_IMPULSE_A = 68
    MIN_IMPULSE_AGG = 55
    MIN_ATR_EXPANSION = 0.80
    MIN_RANGE_EXPANSION = 0.90
    MIN_EMA_SPREAD_ATR = 0.08
    MIN_SLOPE_ATR = 0.015
    MAX_CHOP_RATIO = 0.65

    COMPRESSION_ATR_MAX = 0.85
    COMPRESSION_RANGE_MAX = 0.85
    COMPRESSION_BONUS = 8

    PULLBACK_ATR_PCT = 0.32
    MAX_RISK_ATR = 1.30
    SL_ATR_PCT = 0.16
    COOLDOWN_BARS = 20
    LIMIT_ORDER_BARS = 3

    PAUSE_AFTER_LOSS = 8
    PAUSE_AFTER_TWO_LOSSES = 18

    RR_A = 1.45
    RR_AGG = 1.15
    RR_STRONG = 1.75
    RR_DEFENSIVE = 1.05

    COMMISSION_R = 0.01

    SESSION_VARIANTS = [
        SessionVariant("all", "Sin filtro horario", []),
        SessionVariant("london", "Solo Londres", [(time(7, 0), time(11, 0))]),
        SessionVariant("ny_am", "Solo NY AM", [(time(13, 30), time(15, 0))]),
        SessionVariant("london_ny_am", "Londres + NY AM", [(time(7, 0), time(11, 0)), (time(13, 30), time(15, 0))]),
    ]
    STRATEGY_VARIANTS = [
        StrategyVariant("baseline_v4", "Baseline TV v4"),
        StrategyVariant(
            "aligned_v41",
            "Aligned non-chop",
            require_preferred_side=True,
            disallow_chop=True,
            min_quant_score=60,
            min_impulse_score=58,
        ),
        StrategyVariant(
            "hour_clean_v43",
            "Hour clean balanced",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            excluded_hours_ny={8, 13},
        ),
        StrategyVariant(
            "hour_clean_trend_v44",
            "Hour clean trend",
            require_preferred_side=True,
            disallow_chop=True,
            min_quant_score=60,
            min_impulse_score=58,
            excluded_hours_ny={8, 13},
        ),
        StrategyVariant(
            "prime_hours_v45",
            "Prime hours",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={9, 11, 14, 15},
        ),
        StrategyVariant(
            "prime_hours_refined_v46",
            "Prime hours refined",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={9, 11, 14, 15},
            disallow_normal_hours_ny={14, 15},
        ),
        StrategyVariant(
            "extended_flow_v47",
            "Extended flow core hours",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={1, 4, 5, 9, 15, 19},
        ),
        StrategyVariant(
            "extended_flow_plus_v48",
            "Extended flow plus hours",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={1, 4, 5, 9, 15, 19, 21},
        ),
        StrategyVariant(
            "extended_flow_refined_v49",
            "Extended flow refined",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={1, 4, 5, 9, 15, 19, 21},
            disallow_normal_hours_ny={21},
        ),
        StrategyVariant(
            "volatility_confirmed_v50",
            "Volatility confirmed",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={1, 4, 5, 9, 15, 19},
            require_quant_expansion=True,
            min_atr_ratio=0.95,
            min_range_ratio=0.95,
            max_range_ratio=1.85,
        ),
        StrategyVariant(
            "volatility_refined_v51",
            "Volatility refined",
            require_preferred_side=True,
            min_quant_score=60,
            min_impulse_score=58,
            allowed_hours_ny={1, 4, 5, 9, 15, 19},
            require_quant_expansion=True,
            require_recent_compression=True,
            min_atr_ratio=0.95,
            min_range_ratio=1.0,
            max_range_ratio=1.65,
        ),
        StrategyVariant(
            "volatility_aggressive_v52",
            "Volatility aggressive",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={1, 4, 5, 9, 15, 19, 21},
            require_quant_expansion=True,
            min_atr_ratio=0.9,
            min_range_ratio=0.9,
            max_range_ratio=2.1,
        ),
        StrategyVariant(
            "volatility_balanced_v53",
            "Volatility balanced",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={1, 4, 5, 9, 15, 19},
            min_atr_ratio=0.85,
            min_range_ratio=0.85,
            max_range_ratio=1.95,
        ),
        StrategyVariant(
            "volatility_pulse_v54",
            "Volatility pulse",
            require_preferred_side=True,
            min_quant_score=58,
            min_impulse_score=55,
            allowed_hours_ny={1, 4, 5, 9, 15, 19},
            require_quant_expansion=True,
            min_atr_ratio=0.85,
            min_range_ratio=0.85,
            max_range_ratio=2.2,
        ),
        StrategyVariant(
            "a_plus_focus_v41",
            "A+ focus",
            a_plus_only=True,
            require_preferred_side=True,
            disallow_chop=True,
            min_quant_score=72,
            min_impulse_score=68,
            excluded_hours_ny={8, 13},
        ),
        StrategyVariant(
            "london_precision_v42",
            "London precision",
            a_plus_only=True,
            require_preferred_side=True,
            disallow_chop=True,
            min_quant_score=74,
            min_impulse_score=68,
            allowed_hours_ny={9, 10},
            require_recent_compression_for_agg=True,
        ),
    ]

    def __init__(self, input_dir: Path, output_dir: Path) -> None:
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results_json = self.output_dir / "maximo_mtf_quant_v4_results.json"
        self.report_md = self.output_dir / "maximo_mtf_quant_v4_report.md"
        self.summary_csv = self.output_dir / "maximo_mtf_quant_v4_summary.csv"
        self.best_candidates_json = self.output_dir / "maximo_mtf_quant_v4_best_candidates.json"
        self._loader = BlueprintBacktester(
            input_dir=input_dir,
            results_dir=output_dir / "_cache_results",
            reports_dir=output_dir / "_cache_reports",
        )

    def run(self, symbol: str) -> dict:
        resolved_symbol = self._resolve_symbol(symbol)
        dataset_specs = self._dataset_specs(resolved_symbol)
        runs: list[dict] = []
        for spec in dataset_specs:
            runs.append(self._run_dataset(symbol=resolved_symbol, **spec))

        payload = {
            "strategy_name": "MAXIMO MTF Quant Institutional v4",
            "symbol_requested": symbol,
            "symbol_used": resolved_symbol,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "runs": runs,
            "coverage_notes": self._coverage_notes(dataset_specs),
            "viability_decision": self._viability_decision(runs),
        }
        self.results_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report_md.write_text(self._markdown_report(payload), encoding="utf-8")
        self._write_summary_csv(runs)
        self.best_candidates_json.write_text(
            json.dumps(self._best_candidates_snapshot(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "strategy_name": payload["strategy_name"],
            "symbol_used": resolved_symbol,
            "runs": len(runs),
            "results_json": str(self.results_json.resolve()),
            "report_md": str(self.report_md.resolve()),
            "summary_csv": str(self.summary_csv.resolve()),
            "best_candidates_json": str(self.best_candidates_json.resolve()),
            "decision": payload["viability_decision"]["status"],
        }

    def _run_dataset(
        self,
        *,
        symbol: str,
        label: str,
        timeframe: str,
        entry_candles: list[Candle],
        context: dict,
        coverage: dict,
    ) -> dict:
        all_results: list[dict] = []
        for strategy_variant in self.STRATEGY_VARIANTS:
            for session_variant in self.SESSION_VARIANTS:
                trades = self._simulate(
                    symbol=symbol,
                    dataset_label=label,
                    timeframe=timeframe,
                    entry_candles=entry_candles,
                    context=context,
                    session_variant=session_variant,
                    strategy_variant=strategy_variant,
                )
                split = self._split_metrics(trades)
                all_results.append(
                    {
                        "strategy_variant": strategy_variant.code,
                        "strategy_label": strategy_variant.label,
                        "session_variant": session_variant.code,
                        "session_label": session_variant.label,
                        "metrics": self._metrics(trades),
                        "in_sample": split["in_sample"],
                        "out_of_sample": split["out_of_sample"],
                        "monthly_distribution": self._monthly_distribution(trades),
                        "best_hour": self._hour_edge(trades, best=True),
                        "worst_hour": self._hour_edge(trades, best=False),
                    }
                )

        eligible = [item for item in all_results if item["metrics"]["total_trades"] >= 20]
        pool = eligible or all_results
        best = max(pool, key=self._selection_score, default=None)
        return {
            "dataset_label": label,
            "timeframe": timeframe,
            "coverage": coverage,
            "coverage_sufficient": coverage["sufficient"],
            "results": all_results,
            "best_result": best,
        }

    def _simulate(
        self,
        *,
        symbol: str,
        dataset_label: str,
        timeframe: str,
        entry_candles: list[Candle],
        context: dict,
        session_variant: SessionVariant,
        strategy_variant: StrategyVariant,
    ) -> list[ClosedTrade]:
        if len(entry_candles) < 250:
            return []

        closes = [c.close for c in entry_candles]
        highs = [c.high for c in entry_candles]
        lows = [c.low for c in entry_candles]
        volumes = [c.volume for c in entry_candles]
        ema_fast = self._ema(closes, self.FAST_LEN)
        ema_slow = self._ema(closes, self.SLOW_LEN)
        atr_now = self._atr(entry_candles, self.ATR_LEN)
        atr_mean = self._sma(atr_now, self.ATR_MA_LEN)
        bar_range = [c.high - c.low for c in entry_candles]
        range_mean = self._sma(bar_range, self.RANGE_AVG_LEN)
        vol_mean = self._sma(volumes, self.VOL_LEN)
        body_abs = [abs(c.close - c.open) for c in entry_candles]
        body_avg = self._sma(body_abs, self.RANGE_AVG_LEN)
        latest_highs, latest_lows = self._latest_swings(highs, lows, self.SWING_LEN)
        daily_open_map = self._daily_open_map(entry_candles)

        macro = context["macro"]
        trend = context["trend"]
        setup = context["setup"]
        macro_map = self._map_completed_indices(entry_candles, macro["candles"], timedelta(hours=4))
        trend_map = self._map_completed_indices(entry_candles, trend["candles"], timedelta(hours=1))
        setup_map = self._map_completed_indices(entry_candles, setup["candles"], timedelta(minutes=15))

        trades: list[ClosedTrade] = []
        open_trade: OpenTrade | None = None
        pending_order: PendingOrder | None = None
        last_signal_bar: int | None = None
        pause_until: int | None = None
        loss_streak = 0

        for index in range(len(entry_candles)):
            candle = entry_candles[index]

            if open_trade is not None:
                closed = self._maybe_exit_trade(open_trade, candle)
                if closed is not None:
                    trades.append(
                        self._finalize_trade(
                            trade=closed,
                            symbol=symbol,
                            dataset_label=dataset_label,
                            timeframe=timeframe,
                            session_variant=session_variant.code,
                        )
                    )
                    if closed.exit_reason == "stop_loss_first":
                        loss_streak += 1
                        pause_until = index + (self.PAUSE_AFTER_TWO_LOSSES if loss_streak >= 2 else self.PAUSE_AFTER_LOSS)
                    else:
                        loss_streak = 0
                    open_trade = None
                    pending_order = None

            if open_trade is None and pending_order is not None:
                if index > pending_order.expires_index:
                    pending_order = None
                elif index > pending_order.signal_index:
                    filled = self._try_fill_limit_order(pending_order, candle)
                    if filled is not None:
                        open_trade = filled
                        pending_order = None

            if index >= len(entry_candles) - 1:
                continue
            if open_trade is not None or pending_order is not None:
                continue
            if pause_until is not None and index <= pause_until:
                continue
            if last_signal_bar is not None and index - last_signal_bar < self.COOLDOWN_BARS:
                continue
            if not self._session_allowed(candle.time, session_variant):
                continue
            hour_ny = candle.time.astimezone(NY_TZ).hour
            if not self._hour_allowed(hour_ny, strategy_variant):
                continue

            atr_value = atr_now[index]
            ema_fast_value = ema_fast[index]
            ema_slow_value = ema_slow[index]
            atr_mean_value = atr_mean[index]
            range_mean_value = range_mean[index]
            body_avg_value = body_avg[index]
            vol_mean_value = vol_mean[index]
            macro_idx = macro_map[index]
            trend_idx = trend_map[index]
            setup_idx = setup_map[index]
            if None in {
                atr_value,
                ema_fast_value,
                ema_slow_value,
                atr_mean_value,
                range_mean_value,
                body_avg_value,
                macro_idx,
                trend_idx,
                setup_idx,
            }:
                continue

            candle_range = max(candle.high - candle.low, 1e-9)
            candle_body = abs(candle.close - candle.open)
            body_pct = candle_body / candle_range * 100.0
            atr_ratio = atr_value / atr_mean_value if atr_mean_value else 1.0
            range_ratio = candle_range / range_mean_value if range_mean_value else 1.0
            vol_ok = vol_mean_value is None or candle.volume >= (vol_mean_value * 1.05)
            local_bull = ema_fast_value > ema_slow_value and candle.close > ema_fast_value
            local_bear = ema_fast_value < ema_slow_value and candle.close < ema_fast_value
            ema_spread_atr = abs(ema_fast_value - ema_slow_value) / max(atr_value, 1e-9)
            ema_fast_prev_3 = ema_fast[index - 3] if index >= 3 and ema_fast[index - 3] is not None else ema_fast_value
            ema_slope_atr = abs(ema_fast_value - ema_fast_prev_3) / max(atr_value, 1e-9)
            local_slope_up = index > 0 and ema_fast[index - 1] is not None and ema_fast_value > ema_fast[index - 1]
            local_slope_down = index > 0 and ema_fast[index - 1] is not None and ema_fast_value < ema_fast[index - 1]
            chop_ratio = body_avg_value / range_mean_value if range_mean_value else 1.0

            quant_expansion_ok = atr_ratio >= self.MIN_ATR_EXPANSION or range_ratio >= self.MIN_RANGE_EXPANSION
            quant_trend_ok = ema_spread_atr >= self.MIN_EMA_SPREAD_ATR and ema_slope_atr >= self.MIN_SLOPE_ATR
            quant_chop_ok = chop_ratio <= self.MAX_CHOP_RATIO or range_ratio >= 1.20
            quant_ok = quant_expansion_ok and quant_trend_ok and quant_chop_ok

            macro_row = macro["rows"][macro_idx]
            trend_row = trend["rows"][trend_idx]
            setup_row = setup["rows"][setup_idx]
            day_open = daily_open_map.get(candle.time.date(), candle.open)
            buy_mtf_score, sell_mtf_score = self._mtf_scores(
                local_bull=local_bull,
                local_bear=local_bear,
                macro_row=macro_row,
                trend_row=trend_row,
                setup_row=setup_row,
                day_bull=candle.close > day_open,
                day_bear=candle.close < day_open,
            )

            close_near_high = (candle.high - candle.close) <= candle_range * (self.CLOSE_EXTREME_PCT / 100.0)
            close_near_low = (candle.close - candle.low) <= candle_range * (self.CLOSE_EXTREME_PCT / 100.0)
            close_power_buy = (candle.close - candle.low) / candle_range
            close_power_sell = (candle.high - candle.close) / candle_range

            recent_compression = self._recent_compression(index, atr_now, atr_mean, bar_range, range_mean)
            compression_ok = recent_compression or atr_ratio >= 1.10 or range_ratio >= 1.20

            velocity_ref = closes[index - self.VELOCITY_LEN] if index >= self.VELOCITY_LEN else closes[0]
            velocity = abs(candle.close - velocity_ref) / max(atr_value, 1e-9)
            impulse_score = 0
            impulse_score += 20 if body_pct >= self.BODY_MIN_AGG else 0
            impulse_score += 20 if range_ratio >= self.MIN_RANGE_EXPANSION else 0
            impulse_score += 20 if velocity >= 0.35 else 0
            impulse_score += 20 if ema_slope_atr >= self.MIN_SLOPE_ATR else 0
            impulse_score += 20 if compression_ok else 0
            impulse_score = min(100, impulse_score)

            quant_score = 0
            quant_score += 20 if atr_ratio >= self.MIN_ATR_EXPANSION else 0
            quant_score += 20 if range_ratio >= self.MIN_RANGE_EXPANSION else 0
            quant_score += 20 if ema_spread_atr >= self.MIN_EMA_SPREAD_ATR else 0
            quant_score += 20 if ema_slope_atr >= self.MIN_SLOPE_ATR else 0
            quant_score += 20 if quant_chop_ok else 0
            quant_score += self.COMPRESSION_BONUS if recent_compression else 0
            quant_score = min(100, quant_score)

            range_high = max(highs[max(0, index - self.RANGE_LEN + 1) : index + 1])
            range_low = min(lows[max(0, index - self.RANGE_LEN + 1) : index + 1])
            eq = (range_high + range_low) / 2.0
            pd_buy_ok = candle.close <= eq or macro_row["discount"] or trend_row["discount"]
            pd_sell_ok = candle.close >= eq or macro_row["premium"] or trend_row["premium"]

            swing_low = latest_lows[index]
            swing_high = latest_highs[index]
            sell_side_sweep = swing_low is not None and candle.low < swing_low and candle.close > swing_low
            buy_side_sweep = swing_high is not None and candle.high > swing_high and candle.close < swing_high
            liq_high = max(highs[max(0, index - self.LIQUIDITY_LOOKBACK) : index]) if index > 0 else candle.high
            liq_low = min(lows[max(0, index - self.LIQUIDITY_LOOKBACK) : index]) if index > 0 else candle.low
            liquidity_grab_buy = candle.low < liq_low and candle.close > liq_low
            liquidity_grab_sell = candle.high > liq_high and candle.close < liq_high
            liquidity_quality_buy = sell_side_sweep or liquidity_grab_buy
            liquidity_quality_sell = buy_side_sweep or liquidity_grab_sell

            bull_disp_a = candle.close > candle.open and body_pct >= self.BODY_MIN_A and close_near_high and close_power_buy >= 0.60
            bear_disp_a = candle.close < candle.open and body_pct >= self.BODY_MIN_A and close_near_low and close_power_sell >= 0.60
            bull_disp_agg = candle.close > candle.open and body_pct >= self.BODY_MIN_AGG and close_power_buy >= 0.52
            bear_disp_agg = candle.close < candle.open and body_pct >= self.BODY_MIN_AGG and close_power_sell >= 0.52

            bull_fvg = index >= 2 and candle.low > highs[index - 2]
            bear_fvg = index >= 2 and candle.high < lows[index - 2]
            bull_fvg_mid = (candle.low + highs[index - 2]) / 2.0 if bull_fvg else candle.close
            bear_fvg_mid = (candle.high + lows[index - 2]) / 2.0 if bear_fvg else candle.close

            pullback_buy = (
                local_bull
                and local_slope_up
                and candle.low <= ema_fast_value + atr_value * self.PULLBACK_ATR_PCT
                and candle.close > ema_fast_value
                and candle.close > candle.open
            )
            pullback_sell = (
                local_bear
                and local_slope_down
                and candle.high >= ema_fast_value - atr_value * self.PULLBACK_ATR_PCT
                and candle.close < ema_fast_value
                and candle.close < candle.open
            )

            trend_quality_buy = (20 if local_bull else 0) + (15 if local_slope_up else 0) + (15 if ema_spread_atr >= self.MIN_EMA_SPREAD_ATR else 0)
            trend_quality_sell = (20 if local_bear else 0) + (15 if local_slope_down else 0) + (15 if ema_spread_atr >= self.MIN_EMA_SPREAD_ATR else 0)
            structure_quality_buy = (20 if liquidity_quality_buy else 0) + (15 if bull_disp_a else 8 if bull_disp_agg else 0) + (10 if pd_buy_ok else 0)
            structure_quality_sell = (20 if liquidity_quality_sell else 0) + (15 if bear_disp_a else 8 if bear_disp_agg else 0) + (10 if pd_sell_ok else 0)
            continuation_quality_buy = (25 if pullback_buy else 0) + (10 if bull_disp_agg else 0)
            continuation_quality_sell = (25 if pullback_sell else 0) + (10 if bear_disp_agg else 0)

            buy_conf_a = min(100, round((buy_mtf_score * 0.32) + (quant_score * 0.25) + (impulse_score * 0.18) + (trend_quality_buy * 0.15) + (structure_quality_buy * 0.10)))
            sell_conf_a = min(100, round((sell_mtf_score * 0.32) + (quant_score * 0.25) + (impulse_score * 0.18) + (trend_quality_sell * 0.15) + (structure_quality_sell * 0.10)))
            buy_conf_agg = min(100, round((buy_mtf_score * 0.28) + (quant_score * 0.25) + (impulse_score * 0.22) + (trend_quality_buy * 0.15) + (continuation_quality_buy * 0.10)))
            sell_conf_agg = min(100, round((sell_mtf_score * 0.28) + (quant_score * 0.25) + (impulse_score * 0.22) + (trend_quality_sell * 0.15) + (continuation_quality_sell * 0.10)))

            market_regime = "EXPANSION" if quant_score >= 75 and impulse_score >= 65 and (buy_mtf_score >= 65 or sell_mtf_score >= 65) else "NORMAL" if quant_score >= 55 else "CHOP"
            preferred_side = "BUY" if buy_mtf_score > sell_mtf_score + 15 else "SELL" if sell_mtf_score > buy_mtf_score + 15 else "NEUTRAL"

            setup_buy_a = all([
                liquidity_quality_buy,
                bull_disp_a,
                buy_mtf_score >= 72,
                pd_buy_ok,
                vol_ok,
                quant_ok,
                compression_ok,
                impulse_score >= self.MIN_IMPULSE_A,
                quant_score >= self.MIN_QUANT_A,
                buy_conf_a >= self.MIN_CONF_A,
            ])
            setup_sell_a = all([
                liquidity_quality_sell,
                bear_disp_a,
                sell_mtf_score >= 72,
                pd_sell_ok,
                vol_ok,
                quant_ok,
                compression_ok,
                impulse_score >= self.MIN_IMPULSE_A,
                quant_score >= self.MIN_QUANT_A,
                sell_conf_a >= self.MIN_CONF_A,
            ])
            setup_buy_agg = all([
                pullback_buy,
                bull_disp_agg,
                buy_mtf_score >= 58,
                quant_ok,
                compression_ok,
                impulse_score >= self.MIN_IMPULSE_AGG,
                quant_score >= self.MIN_QUANT_AGG,
                buy_conf_agg >= self.MIN_CONF_AGG,
                preferred_side != "SELL",
            ])
            setup_sell_agg = all([
                pullback_sell,
                bear_disp_agg,
                sell_mtf_score >= 58,
                quant_ok,
                compression_ok,
                impulse_score >= self.MIN_IMPULSE_AGG,
                quant_score >= self.MIN_QUANT_AGG,
                sell_conf_agg >= self.MIN_CONF_AGG,
                preferred_side != "BUY",
            ])

            setup_buy_a = self._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="buy",
                setup_type="A+",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_buy_a,
            )
            setup_sell_a = self._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="sell",
                setup_type="A+",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_sell_a,
            )
            setup_buy_agg = self._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="buy",
                setup_type="AGG",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_buy_agg,
            )
            setup_sell_agg = self._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="sell",
                setup_type="AGG",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_sell_agg,
            )

            signal = self._build_signal(
                candle=candle,
                next_candle=entry_candles[index + 1],
                index=index,
                atr_value=atr_value,
                ema_slow_value=ema_slow_value,
                bull_fvg_mid=bull_fvg_mid,
                bear_fvg_mid=bear_fvg_mid,
                setup_buy_a=setup_buy_a,
                setup_sell_a=setup_sell_a,
                setup_buy_agg=setup_buy_agg,
                setup_sell_agg=setup_sell_agg,
                buy_conf_a=buy_conf_a,
                sell_conf_a=sell_conf_a,
                buy_conf_agg=buy_conf_agg,
                sell_conf_agg=sell_conf_agg,
                buy_mtf_score=buy_mtf_score,
                sell_mtf_score=sell_mtf_score,
                quant_score=quant_score,
                impulse_score=impulse_score,
                market_regime=market_regime,
            )
            if signal is None:
                continue
            last_signal_bar = index
            if signal["entry_kind"] == "market":
                open_trade = signal["open_trade"]
            else:
                pending_order = signal["pending_order"]

        return trades

    def latest_snapshot_signal(
        self,
        *,
        symbol: str,
        timeframe: str,
        entry_candles: list[Candle],
        context: dict,
        session_variant: SessionVariant,
        strategy_variant: StrategyVariant,
    ) -> dict | None:
        if len(entry_candles) < 250:
            return None

        closes = [c.close for c in entry_candles]
        highs = [c.high for c in entry_candles]
        lows = [c.low for c in entry_candles]
        volumes = [c.volume for c in entry_candles]
        ema_fast = self._ema(closes, self.FAST_LEN)
        ema_slow = self._ema(closes, self.SLOW_LEN)
        atr_now = self._atr(entry_candles, self.ATR_LEN)
        atr_mean = self._sma(atr_now, self.ATR_MA_LEN)
        bar_range = [c.high - c.low for c in entry_candles]
        range_mean = self._sma(bar_range, self.RANGE_AVG_LEN)
        vol_mean = self._sma(volumes, self.VOL_LEN)
        body_abs = [abs(c.close - c.open) for c in entry_candles]
        body_avg = self._sma(body_abs, self.RANGE_AVG_LEN)
        latest_highs, latest_lows = self._latest_swings(highs, lows, self.SWING_LEN)
        daily_open_map = self._daily_open_map(entry_candles)

        macro = context["macro"]
        trend = context["trend"]
        setup = context["setup"]
        macro_map = self._map_completed_indices(entry_candles, macro["candles"], timedelta(hours=4))
        trend_map = self._map_completed_indices(entry_candles, trend["candles"], timedelta(hours=1))
        setup_map = self._map_completed_indices(entry_candles, setup["candles"], timedelta(minutes=15))

        open_trade: OpenTrade | None = None
        pending_order: PendingOrder | None = None
        last_signal_bar: int | None = None
        pause_until: int | None = None
        loss_streak = 0
        latest_signal_index = len(entry_candles) - 2

        for index in range(len(entry_candles) - 1):
            candle = entry_candles[index]

            if open_trade is not None:
                closed = self._maybe_exit_trade(open_trade, candle)
                if closed is not None:
                    if closed.exit_reason == "stop_loss_first":
                        loss_streak += 1
                        pause_until = index + (self.PAUSE_AFTER_TWO_LOSSES if loss_streak >= 2 else self.PAUSE_AFTER_LOSS)
                    else:
                        loss_streak = 0
                    open_trade = None
                    pending_order = None

            if open_trade is None and pending_order is not None:
                if index > pending_order.expires_index:
                    pending_order = None
                elif index > pending_order.signal_index:
                    filled = self._try_fill_limit_order(pending_order, candle)
                    if filled is not None:
                        open_trade = filled
                        pending_order = None

            if open_trade is not None or pending_order is not None:
                continue
            if pause_until is not None and index <= pause_until:
                continue
            if last_signal_bar is not None and index - last_signal_bar < self.COOLDOWN_BARS:
                continue
            if not self._session_allowed(candle.time, session_variant):
                continue
            hour_ny = candle.time.astimezone(NY_TZ).hour
            if not self._hour_allowed(hour_ny, strategy_variant):
                continue

            atr_value = atr_now[index]
            ema_fast_value = ema_fast[index]
            ema_slow_value = ema_slow[index]
            atr_mean_value = atr_mean[index]
            range_mean_value = range_mean[index]
            body_avg_value = body_avg[index]
            vol_mean_value = vol_mean[index]
            macro_idx = macro_map[index]
            trend_idx = trend_map[index]
            setup_idx = setup_map[index]
            if None in {
                atr_value,
                ema_fast_value,
                ema_slow_value,
                atr_mean_value,
                range_mean_value,
                body_avg_value,
                macro_idx,
                trend_idx,
                setup_idx,
            }:
                continue

            candle_range = max(candle.high - candle.low, 1e-9)
            candle_body = abs(candle.close - candle.open)
            body_pct = candle_body / candle_range * 100.0
            atr_ratio = atr_value / atr_mean_value if atr_mean_value else 1.0
            range_ratio = candle_range / range_mean_value if range_mean_value else 1.0
            vol_ok = vol_mean_value is None or candle.volume >= (vol_mean_value * 1.05)
            local_bull = ema_fast_value > ema_slow_value and candle.close > ema_fast_value
            local_bear = ema_fast_value < ema_slow_value and candle.close < ema_fast_value
            ema_spread_atr = abs(ema_fast_value - ema_slow_value) / max(atr_value, 1e-9)
            ema_fast_prev_3 = ema_fast[index - 3] if index >= 3 and ema_fast[index - 3] is not None else ema_fast_value
            ema_slope_atr = abs(ema_fast_value - ema_fast_prev_3) / max(atr_value, 1e-9)
            local_slope_up = index > 0 and ema_fast[index - 1] is not None and ema_fast_value > ema_fast[index - 1]
            local_slope_down = index > 0 and ema_fast[index - 1] is not None and ema_fast_value < ema_fast[index - 1]
            chop_ratio = body_avg_value / range_mean_value if range_mean_value else 1.0

            quant_expansion_ok = atr_ratio >= self.MIN_ATR_EXPANSION or range_ratio >= self.MIN_RANGE_EXPANSION
            quant_trend_ok = ema_spread_atr >= self.MIN_EMA_SPREAD_ATR and ema_slope_atr >= self.MIN_SLOPE_ATR
            quant_chop_ok = chop_ratio <= self.MAX_CHOP_RATIO or range_ratio >= 1.20
            quant_ok = quant_expansion_ok and quant_trend_ok and quant_chop_ok

            macro_row = macro["rows"][macro_idx]
            trend_row = trend["rows"][trend_idx]
            setup_row = setup["rows"][setup_idx]
            day_open = daily_open_map.get(candle.time.date(), candle.open)
            buy_mtf_score, sell_mtf_score = self._mtf_scores(
                local_bull=local_bull,
                local_bear=local_bear,
                macro_row=macro_row,
                trend_row=trend_row,
                setup_row=setup_row,
                day_bull=candle.close > day_open,
                day_bear=candle.close < day_open,
            )

            close_near_high = (candle.high - candle.close) <= candle_range * (self.CLOSE_EXTREME_PCT / 100.0)
            close_near_low = (candle.close - candle.low) <= candle_range * (self.CLOSE_EXTREME_PCT / 100.0)
            close_power_buy = (candle.close - candle.low) / candle_range
            close_power_sell = (candle.high - candle.close) / candle_range

            recent_compression = self._recent_compression(index, atr_now, atr_mean, bar_range, range_mean)
            compression_ok = recent_compression or atr_ratio >= 1.10 or range_ratio >= 1.20

            velocity_ref = closes[index - self.VELOCITY_LEN] if index >= self.VELOCITY_LEN else closes[0]
            velocity = abs(candle.close - velocity_ref) / max(atr_value, 1e-9)
            impulse_score = 0
            impulse_score += 20 if body_pct >= self.BODY_MIN_AGG else 0
            impulse_score += 20 if range_ratio >= self.MIN_RANGE_EXPANSION else 0
            impulse_score += 20 if velocity >= 0.35 else 0
            impulse_score += 20 if ema_slope_atr >= self.MIN_SLOPE_ATR else 0
            impulse_score += 20 if compression_ok else 0
            impulse_score = min(100, impulse_score)

            quant_score = 0
            quant_score += 20 if atr_ratio >= self.MIN_ATR_EXPANSION else 0
            quant_score += 20 if range_ratio >= self.MIN_RANGE_EXPANSION else 0
            quant_score += 20 if ema_spread_atr >= self.MIN_EMA_SPREAD_ATR else 0
            quant_score += 20 if ema_slope_atr >= self.MIN_SLOPE_ATR else 0
            quant_score += 20 if quant_chop_ok else 0
            quant_score += self.COMPRESSION_BONUS if recent_compression else 0
            quant_score = min(100, quant_score)

            range_high = max(highs[max(0, index - self.RANGE_LEN + 1) : index + 1])
            range_low = min(lows[max(0, index - self.RANGE_LEN + 1) : index + 1])
            eq = (range_high + range_low) / 2.0
            pd_buy_ok = candle.close <= eq or macro_row["discount"] or trend_row["discount"]
            pd_sell_ok = candle.close >= eq or macro_row["premium"] or trend_row["premium"]

            swing_low = latest_lows[index]
            swing_high = latest_highs[index]
            sell_side_sweep = swing_low is not None and candle.low < swing_low and candle.close > swing_low
            buy_side_sweep = swing_high is not None and candle.high > swing_high and candle.close < swing_high
            liq_high = max(highs[max(0, index - self.LIQUIDITY_LOOKBACK) : index]) if index > 0 else candle.high
            liq_low = min(lows[max(0, index - self.LIQUIDITY_LOOKBACK) : index]) if index > 0 else candle.low
            liquidity_grab_buy = candle.low < liq_low and candle.close > liq_low
            liquidity_grab_sell = candle.high > liq_high and candle.close < liq_high
            liquidity_quality_buy = sell_side_sweep or liquidity_grab_buy
            liquidity_quality_sell = buy_side_sweep or liquidity_grab_sell

            bull_disp_a = candle.close > candle.open and body_pct >= self.BODY_MIN_A and close_near_high and close_power_buy >= 0.60
            bear_disp_a = candle.close < candle.open and body_pct >= self.BODY_MIN_A and close_near_low and close_power_sell >= 0.60
            bull_disp_agg = candle.close > candle.open and body_pct >= self.BODY_MIN_AGG and close_power_buy >= 0.52
            bear_disp_agg = candle.close < candle.open and body_pct >= self.BODY_MIN_AGG and close_power_sell >= 0.52

            bull_fvg = index >= 2 and candle.low > highs[index - 2]
            bear_fvg = index >= 2 and candle.high < lows[index - 2]
            bull_fvg_mid = (candle.low + highs[index - 2]) / 2.0 if bull_fvg else candle.close
            bear_fvg_mid = (candle.high + lows[index - 2]) / 2.0 if bear_fvg else candle.close

            pullback_buy = (
                local_bull
                and local_slope_up
                and candle.low <= ema_fast_value + atr_value * self.PULLBACK_ATR_PCT
                and candle.close > ema_fast_value
                and candle.close > candle.open
            )
            pullback_sell = (
                local_bear
                and local_slope_down
                and candle.high >= ema_fast_value - atr_value * self.PULLBACK_ATR_PCT
                and candle.close < ema_fast_value
                and candle.close < candle.open
            )

            trend_quality_buy = (20 if local_bull else 0) + (15 if local_slope_up else 0) + (15 if ema_spread_atr >= self.MIN_EMA_SPREAD_ATR else 0)
            trend_quality_sell = (20 if local_bear else 0) + (15 if local_slope_down else 0) + (15 if ema_spread_atr >= self.MIN_EMA_SPREAD_ATR else 0)
            structure_quality_buy = (20 if liquidity_quality_buy else 0) + (15 if bull_disp_a else 8 if bull_disp_agg else 0) + (10 if pd_buy_ok else 0)
            structure_quality_sell = (20 if liquidity_quality_sell else 0) + (15 if bear_disp_a else 8 if bear_disp_agg else 0) + (10 if pd_sell_ok else 0)
            continuation_quality_buy = (25 if pullback_buy else 0) + (10 if bull_disp_agg else 0)
            continuation_quality_sell = (25 if pullback_sell else 0) + (10 if bear_disp_agg else 0)

            buy_conf_a = min(100, round((buy_mtf_score * 0.32) + (quant_score * 0.25) + (impulse_score * 0.18) + (trend_quality_buy * 0.15) + (structure_quality_buy * 0.10)))
            sell_conf_a = min(100, round((sell_mtf_score * 0.32) + (quant_score * 0.25) + (impulse_score * 0.18) + (trend_quality_sell * 0.15) + (structure_quality_sell * 0.10)))
            buy_conf_agg = min(100, round((buy_mtf_score * 0.28) + (quant_score * 0.25) + (impulse_score * 0.22) + (trend_quality_buy * 0.15) + (continuation_quality_buy * 0.10)))
            sell_conf_agg = min(100, round((sell_mtf_score * 0.28) + (quant_score * 0.25) + (impulse_score * 0.22) + (trend_quality_sell * 0.15) + (continuation_quality_sell * 0.10)))

            market_regime = "EXPANSION" if quant_score >= 75 and impulse_score >= 65 and (buy_mtf_score >= 65 or sell_mtf_score >= 65) else "NORMAL" if quant_score >= 55 else "CHOP"
            preferred_side = "BUY" if buy_mtf_score > sell_mtf_score + 15 else "SELL" if sell_mtf_score > buy_mtf_score + 15 else "NEUTRAL"

            setup_buy_a = all([
                liquidity_quality_buy,
                bull_disp_a,
                buy_mtf_score >= 72,
                pd_buy_ok,
                vol_ok,
                quant_ok,
                compression_ok,
                impulse_score >= self.MIN_IMPULSE_A,
                quant_score >= self.MIN_QUANT_A,
                buy_conf_a >= self.MIN_CONF_A,
            ])
            setup_sell_a = all([
                liquidity_quality_sell,
                bear_disp_a,
                sell_mtf_score >= 72,
                pd_sell_ok,
                vol_ok,
                quant_ok,
                compression_ok,
                impulse_score >= self.MIN_IMPULSE_A,
                quant_score >= self.MIN_QUANT_A,
                sell_conf_a >= self.MIN_CONF_A,
            ])
            setup_buy_agg = all([
                pullback_buy,
                bull_disp_agg,
                buy_mtf_score >= 58,
                quant_ok,
                compression_ok,
                impulse_score >= self.MIN_IMPULSE_AGG,
                quant_score >= self.MIN_QUANT_AGG,
                buy_conf_agg >= self.MIN_CONF_AGG,
                preferred_side != "SELL",
            ])
            setup_sell_agg = all([
                pullback_sell,
                bear_disp_agg,
                sell_mtf_score >= 58,
                quant_ok,
                compression_ok,
                impulse_score >= self.MIN_IMPULSE_AGG,
                quant_score >= self.MIN_QUANT_AGG,
                sell_conf_agg >= self.MIN_CONF_AGG,
                preferred_side != "BUY",
            ])

            setup_buy_a = self._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="buy",
                setup_type="A+",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_buy_a,
            )
            setup_sell_a = self._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="sell",
                setup_type="A+",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_sell_a,
            )
            setup_buy_agg = self._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="buy",
                setup_type="AGG",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_buy_agg,
            )
            setup_sell_agg = self._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="sell",
                setup_type="AGG",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_sell_agg,
            )

            signal = self._build_signal(
                candle=candle,
                next_candle=entry_candles[index + 1],
                index=index,
                atr_value=atr_value,
                ema_slow_value=ema_slow_value,
                bull_fvg_mid=bull_fvg_mid,
                bear_fvg_mid=bear_fvg_mid,
                setup_buy_a=setup_buy_a,
                setup_sell_a=setup_sell_a,
                setup_buy_agg=setup_buy_agg,
                setup_sell_agg=setup_sell_agg,
                buy_conf_a=buy_conf_a,
                sell_conf_a=sell_conf_a,
                buy_conf_agg=buy_conf_agg,
                sell_conf_agg=sell_conf_agg,
                buy_mtf_score=buy_mtf_score,
                sell_mtf_score=sell_mtf_score,
                quant_score=quant_score,
                impulse_score=impulse_score,
                market_regime=market_regime,
            )
            if signal is None:
                continue
            if index == latest_signal_index:
                if signal["entry_kind"] == "market":
                    trade = signal["open_trade"]
                    return {
                        "entry_kind": "market",
                        "strategy_variant": strategy_variant.code,
                        "session_variant": session_variant.code,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "signal_time": candle.time.isoformat(),
                        "entry_time": trade.entry_time.isoformat(),
                        "direction": trade.direction,
                        "setup_type": trade.setup_type,
                        "entry_price": trade.entry_price,
                        "stop_price": trade.stop_price,
                        "target_price": trade.target_price,
                        "risk_per_unit": trade.risk_per_unit,
                        "selected_rr": trade.selected_rr,
                        "quant_score": trade.quant_score,
                        "impulse_score": trade.impulse_score,
                        "buy_mtf_score": trade.buy_mtf_score,
                        "sell_mtf_score": trade.sell_mtf_score,
                        "confidence": trade.confidence,
                        "market_regime": trade.market_regime,
                        "hour_ny": hour_ny,
                        "preferred_side": preferred_side,
                    }
                pending = signal["pending_order"]
                return {
                    "entry_kind": "limit",
                    "strategy_variant": strategy_variant.code,
                    "session_variant": session_variant.code,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "signal_time": candle.time.isoformat(),
                    "entry_time": entry_candles[index + 1].time.isoformat(),
                    "direction": pending.direction,
                    "setup_type": pending.setup_type,
                    "entry_price": pending.desired_entry,
                    "stop_price": pending.stop_price,
                    "target_price": pending.target_price,
                    "risk_per_unit": pending.risk_per_unit,
                    "selected_rr": pending.selected_rr,
                    "quant_score": pending.quant_score,
                    "impulse_score": pending.impulse_score,
                    "buy_mtf_score": pending.buy_mtf_score,
                    "sell_mtf_score": pending.sell_mtf_score,
                    "confidence": pending.confidence,
                    "market_regime": pending.market_regime,
                    "hour_ny": hour_ny,
                    "preferred_side": preferred_side,
                }

            last_signal_bar = index
            if signal["entry_kind"] == "market":
                open_trade = signal["open_trade"]
            else:
                pending_order = signal["pending_order"]

        return None

    def _build_signal(self, **kwargs) -> dict | None:
        candle: Candle = kwargs["candle"]
        next_candle: Candle = kwargs["next_candle"]
        atr_value: float = kwargs["atr_value"]
        ema_slow_value: float = kwargs["ema_slow_value"]

        for side in ("buy", "sell"):
            is_a = kwargs[f"setup_{side}_a"]
            is_agg = kwargs[f"setup_{side}_agg"]
            if not (is_a or is_agg):
                continue

            direction = "buy" if side == "buy" else "sell"
            confidence = kwargs[f"{side}_conf_a"] if is_a else kwargs[f"{side}_conf_agg"]
            setup_type = "A+" if is_a else "AGG"
            body_mid = (candle.open + candle.close) / 2.0
            fvg_mid = kwargs["bull_fvg_mid"] if side == "buy" else kwargs["bear_fvg_mid"]
            desired_entry = fvg_mid if is_a else candle.close

            if side == "buy":
                base_sl = (candle.low - atr_value * self.SL_ATR_PCT) if is_a else min(candle.low, ema_slow_value - atr_value * self.SL_ATR_PCT)
                risk = desired_entry - base_sl
            else:
                base_sl = (candle.high + atr_value * self.SL_ATR_PCT) if is_a else max(candle.high, ema_slow_value + atr_value * self.SL_ATR_PCT)
                risk = base_sl - desired_entry
            if risk <= 0 or risk > atr_value * self.MAX_RISK_ATR:
                continue

            selected_rr = self._resolve_rr(
                is_a=is_a,
                market_regime=kwargs["market_regime"],
                quant_score=kwargs["quant_score"],
                impulse_score=kwargs["impulse_score"],
            )
            target_price = desired_entry + risk * selected_rr if side == "buy" else desired_entry - risk * selected_rr
            use_limit = is_a and abs(desired_entry - candle.close) > 1e-9

            if use_limit:
                return {
                    "entry_kind": "limit",
                    "pending_order": PendingOrder(
                        direction=direction,
                        setup_type=setup_type,
                        signal_index=kwargs["index"],
                        signal_time=candle.time,
                        desired_entry=body_mid if abs(desired_entry - candle.close) < 1e-9 else desired_entry,
                        stop_price=base_sl,
                        target_price=target_price,
                        risk_per_unit=risk,
                        selected_rr=selected_rr,
                        quant_score=kwargs["quant_score"],
                        impulse_score=kwargs["impulse_score"],
                        buy_mtf_score=kwargs["buy_mtf_score"],
                        sell_mtf_score=kwargs["sell_mtf_score"],
                        confidence=confidence,
                        market_regime=kwargs["market_regime"],
                        expires_index=kwargs["index"] + self.LIMIT_ORDER_BARS,
                    ),
                }

            entry_price = next_candle.open
            if side == "buy":
                risk_market = entry_price - base_sl
            else:
                risk_market = base_sl - entry_price
            if risk_market <= 0 or risk_market > atr_value * self.MAX_RISK_ATR * 1.25:
                continue
            market_target = entry_price + risk_market * selected_rr if side == "buy" else entry_price - risk_market * selected_rr
            return {
                "entry_kind": "market",
                "open_trade": OpenTrade(
                    direction=direction,
                    setup_type=setup_type,
                    signal_index=kwargs["index"],
                    signal_time=candle.time,
                    entry_time=next_candle.time,
                    entry_price=entry_price,
                    stop_price=base_sl,
                    target_price=market_target,
                    initial_stop_price=base_sl,
                    risk_per_unit=risk_market,
                    selected_rr=selected_rr,
                    quant_score=kwargs["quant_score"],
                    impulse_score=kwargs["impulse_score"],
                    buy_mtf_score=kwargs["buy_mtf_score"],
                    sell_mtf_score=kwargs["sell_mtf_score"],
                    confidence=confidence,
                    market_regime=kwargs["market_regime"],
                ),
            }
        return None

    @staticmethod
    def _hour_allowed(hour_ny: int, variant: StrategyVariant) -> bool:
        if variant.allowed_hours_ny is not None and hour_ny not in variant.allowed_hours_ny:
            return False
        if variant.excluded_hours_ny is not None and hour_ny in variant.excluded_hours_ny:
            return False
        return True

    @staticmethod
    def _variant_allows_setup(
        *,
        strategy_variant: StrategyVariant,
        direction: str,
        setup_type: str,
        signal_hour_ny: int,
        preferred_side: str,
        market_regime: str,
        quant_score: int,
        impulse_score: int,
        recent_compression: bool,
        quant_expansion_ok: bool,
        atr_ratio: float,
        range_ratio: float,
        current_state: bool,
    ) -> bool:
        if not current_state:
            return False
        if strategy_variant.allowed_directions is not None and direction not in strategy_variant.allowed_directions:
            return False
        if strategy_variant.allowed_setup_types is not None and setup_type not in strategy_variant.allowed_setup_types:
            return False
        if strategy_variant.a_plus_only and setup_type != "A+":
            return False
        if strategy_variant.require_preferred_side:
            expected = "BUY" if direction == "buy" else "SELL"
            if preferred_side != expected:
                return False
        if strategy_variant.disallow_chop and market_regime == "CHOP":
            return False
        if quant_score < strategy_variant.min_quant_score:
            return False
        if impulse_score < strategy_variant.min_impulse_score:
            return False
        if (
            strategy_variant.disallow_normal_hours_ny is not None
            and market_regime == "NORMAL"
            and signal_hour_ny in strategy_variant.disallow_normal_hours_ny
        ):
            return False
        if strategy_variant.require_quant_expansion and not quant_expansion_ok:
            return False
        if strategy_variant.require_recent_compression and not recent_compression:
            return False
        if strategy_variant.min_atr_ratio is not None and atr_ratio < strategy_variant.min_atr_ratio:
            return False
        if strategy_variant.min_range_ratio is not None and range_ratio < strategy_variant.min_range_ratio:
            return False
        if strategy_variant.max_atr_ratio is not None and atr_ratio > strategy_variant.max_atr_ratio:
            return False
        if strategy_variant.max_range_ratio is not None and range_ratio > strategy_variant.max_range_ratio:
            return False
        if setup_type == "AGG" and strategy_variant.require_recent_compression_for_agg and not recent_compression:
            return False
        return True

    def _resolve_rr(self, *, is_a: bool, market_regime: str, quant_score: int, impulse_score: int) -> float:
        base = self.RR_A if is_a else self.RR_AGG
        if market_regime == "EXPANSION" and quant_score >= 85 and impulse_score >= 75:
            return self.RR_STRONG
        if market_regime == "CHOP":
            return self.RR_DEFENSIVE
        return base

    def _try_fill_limit_order(self, pending: PendingOrder, candle: Candle) -> OpenTrade | None:
        if not (candle.low <= pending.desired_entry <= candle.high):
            return None
        return OpenTrade(
            direction=pending.direction,
            setup_type=pending.setup_type,
            signal_index=pending.signal_index,
            signal_time=pending.signal_time,
            entry_time=candle.time,
            entry_price=pending.desired_entry,
            stop_price=pending.stop_price,
            target_price=pending.target_price,
            initial_stop_price=pending.stop_price,
            risk_per_unit=pending.risk_per_unit,
            selected_rr=pending.selected_rr,
            quant_score=pending.quant_score,
            impulse_score=pending.impulse_score,
            buy_mtf_score=pending.buy_mtf_score,
            sell_mtf_score=pending.sell_mtf_score,
            confidence=pending.confidence,
            market_regime=pending.market_regime,
        )

    def _maybe_exit_trade(self, trade: OpenTrade, candle: Candle) -> ClosedTrade | None:
        stop_hit = candle.low <= trade.stop_price if trade.direction == "buy" else candle.high >= trade.stop_price
        tp_hit = candle.high >= trade.target_price if trade.direction == "buy" else candle.low <= trade.target_price
        if not stop_hit and not tp_hit:
            return None
        exit_price = trade.stop_price if stop_hit else trade.target_price
        pnl_r = (
            (exit_price - trade.entry_price) / trade.risk_per_unit
            if trade.direction == "buy"
            else (trade.entry_price - exit_price) / trade.risk_per_unit
        ) - self.COMMISSION_R
        return ClosedTrade(
            symbol="",
            dataset_label="",
            timeframe="",
            session_variant="",
            setup_type=trade.setup_type,
            direction=trade.direction,
            signal_time=trade.signal_time,
            entry_time=trade.entry_time,
            exit_time=candle.time,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            stop_price=trade.stop_price,
            target_price=trade.target_price,
            initial_stop_price=trade.initial_stop_price,
            risk_per_unit=trade.risk_per_unit,
            selected_rr=trade.selected_rr,
            quant_score=trade.quant_score,
            impulse_score=trade.impulse_score,
            buy_mtf_score=trade.buy_mtf_score,
            sell_mtf_score=trade.sell_mtf_score,
            confidence=trade.confidence,
            market_regime=trade.market_regime,
            month=trade.entry_time.strftime("%Y-%m"),
            hour_ny=trade.entry_time.astimezone(NY_TZ).hour,
            pnl_r=round(pnl_r, 4),
            exit_reason="stop_loss_first" if stop_hit else "take_profit",
        )

    def _finalize_trade(
        self,
        *,
        trade: ClosedTrade,
        symbol: str,
        dataset_label: str,
        timeframe: str,
        session_variant: str,
    ) -> ClosedTrade:
        trade.symbol = symbol
        trade.dataset_label = dataset_label
        trade.timeframe = timeframe
        trade.session_variant = session_variant
        return trade

    def _dataset_specs(self, symbol: str) -> list[dict]:
        specs: list[dict] = []
        recent = self._load_range_family(symbol, "20251101_20260505")
        if recent:
            anchor = recent["M5"][-1].time if recent.get("M5") else recent["H1"][-1].time
            specs.extend(
                self._build_period_specs(
                    "recent",
                    recent,
                    [
                        ("last_3_months", anchor - timedelta(days=90), anchor),
                        ("last_6_months", anchor - timedelta(days=180), anchor),
                    ],
                )
            )
        annual = self._load_year_family(symbol, 2025)
        if annual:
            start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            end = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc)
            specs.extend(self._build_period_specs("annual_2025", annual, [("full_year_2025", start, end)]))
        return specs

    def _build_period_specs(self, label_prefix: str, family: dict[str, list[Candle]], periods: list[tuple[str, datetime, datetime]]) -> list[dict]:
        specs: list[dict] = []
        for period_name, start, end in periods:
            m1 = [c for c in family.get("M1", []) if start <= c.time <= end]
            m5 = [c for c in family.get("M5", []) if start <= c.time <= end]
            h1 = [c for c in family.get("H1", []) if start <= c.time <= end]
            m15 = self._resample(m5, "M15") if m5 else []
            h4 = self._resample(h1, "H4") if h1 else []
            for timeframe, entry in (("M1", m1), ("M5", m5), ("M15", m15)):
                if not entry:
                    continue
                coverage = self._coverage_for_timeframe(timeframe, start, end, entry, h1)
                specs.append(
                    {
                        "label": f"{label_prefix}_{period_name}",
                        "timeframe": timeframe,
                        "entry_candles": entry,
                        "context": {
                            "macro": self._context_pack(h4),
                            "trend": self._context_pack(h1),
                            "setup": self._context_pack(m15),
                        },
                        "coverage": coverage,
                    }
                )
        return specs

    def _context_pack(self, candles: list[Candle]) -> dict:
        closes = [c.close for c in candles]
        ema_fast = self._ema(closes, self.FAST_LEN)
        ema_slow = self._ema(closes, self.SLOW_LEN)
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        rows = []
        for idx, candle in enumerate(candles):
            if ema_fast[idx] is None or ema_slow[idx] is None:
                rows.append({"bull": False, "bear": False, "discount": False, "premium": False})
                continue
            window_high = max(highs[max(0, idx - self.RANGE_LEN + 1) : idx + 1])
            window_low = min(lows[max(0, idx - self.RANGE_LEN + 1) : idx + 1])
            eq = (window_high + window_low) / 2.0
            prev_fast = ema_fast[idx - 1] if idx > 0 and ema_fast[idx - 1] is not None else ema_fast[idx]
            rows.append(
                {
                    "bull": ema_fast[idx] > ema_slow[idx] and candle.close > ema_fast[idx] and ema_fast[idx] >= prev_fast,
                    "bear": ema_fast[idx] < ema_slow[idx] and candle.close < ema_fast[idx] and ema_fast[idx] <= prev_fast,
                    "discount": candle.close <= eq,
                    "premium": candle.close >= eq,
                }
            )
        return {"candles": candles, "rows": rows}

    def _mtf_scores(self, *, local_bull: bool, local_bear: bool, macro_row: dict, trend_row: dict, setup_row: dict, day_bull: bool, day_bear: bool) -> tuple[int, int]:
        buy = 0
        buy += 25 if macro_row["bull"] else 0
        buy += 25 if trend_row["bull"] else 0
        buy += 20 if setup_row["bull"] else 0
        buy += 15 if local_bull else 0
        buy += 15 if macro_row["discount"] or trend_row["discount"] else 0
        buy += 8 if day_bull else 0

        sell = 0
        sell += 25 if macro_row["bear"] else 0
        sell += 25 if trend_row["bear"] else 0
        sell += 20 if setup_row["bear"] else 0
        sell += 15 if local_bear else 0
        sell += 15 if macro_row["premium"] or trend_row["premium"] else 0
        sell += 8 if day_bear else 0
        return buy, sell

    def _latest_swings(self, highs: list[float], lows: list[float], swing_len: int) -> tuple[list[float | None], list[float | None]]:
        latest_high = None
        latest_low = None
        result_high: list[float | None] = [None] * len(highs)
        result_low: list[float | None] = [None] * len(lows)
        for index in range(len(highs)):
            candidate = index - swing_len
            if candidate >= swing_len and candidate + swing_len < len(highs):
                ph = highs[candidate]
                pl = lows[candidate]
                if ph == max(highs[candidate - swing_len : candidate + swing_len + 1]):
                    latest_high = ph
                if pl == min(lows[candidate - swing_len : candidate + swing_len + 1]):
                    latest_low = pl
            result_high[index] = latest_high
            result_low[index] = latest_low
        return result_high, result_low

    @staticmethod
    def _daily_open_map(candles: list[Candle]) -> dict[date, float]:
        mapping: dict[date, float] = {}
        for candle in candles:
            mapping.setdefault(candle.time.date(), candle.open)
        return mapping

    def _recent_compression(
        self,
        index: int,
        atr_values: list[float | None],
        atr_mean_values: list[float | None],
        bar_ranges: list[float],
        range_means: list[float | None],
    ) -> bool:
        for cursor in range(max(0, index - self.COMPRESSION_LOOKBACK + 1), index + 1):
            atr_value = atr_values[cursor]
            atr_mean = atr_mean_values[cursor]
            range_mean = range_means[cursor]
            if atr_value is None or atr_mean is None or range_mean is None:
                continue
            atr_ratio = atr_value / atr_mean if atr_mean else 9.0
            range_ratio = bar_ranges[cursor] / range_mean if range_mean else 9.0
            if atr_ratio <= self.COMPRESSION_ATR_MAX and range_ratio <= self.COMPRESSION_RANGE_MAX:
                return True
        return False

    def _load_range_family(self, symbol: str, suffix: str) -> dict[str, list[Candle]]:
        family: dict[str, list[Candle]] = {}
        for timeframe in ("M1", "M5", "H1"):
            path = self.input_dir / f"{symbol}_{timeframe}_{suffix}.csv"
            if path.exists():
                family[timeframe] = self._loader._load_candles(path)
        return family

    def _load_year_family(self, symbol: str, year: int) -> dict[str, list[Candle]]:
        family: dict[str, list[Candle]] = {}
        for timeframe in ("M1", "M5", "H1"):
            path = self.input_dir / f"{symbol}_{timeframe}_{year}.csv"
            if path.exists():
                family[timeframe] = self._loader._load_candles(path)
        return family

    @staticmethod
    def _coverage_for_timeframe(timeframe: str, start: datetime, end: datetime, entry_candles: list[Candle], htf_candles: list[Candle]) -> dict:
        expected_minutes = (end - start).total_seconds() / 60.0
        actual_minutes = ((entry_candles[-1].time - entry_candles[0].time).total_seconds() / 60.0) if len(entry_candles) > 1 else 0.0
        ratio = round(actual_minutes / expected_minutes, 4) if expected_minutes > 0 else 0.0
        sufficient = bool(entry_candles and htf_candles and ratio >= 0.75)
        return {
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "entry_rows": len(entry_candles),
            "htf_rows": len(htf_candles),
            "coverage_ratio": ratio,
            "sufficient": sufficient,
            "timeframe": timeframe,
        }

    @staticmethod
    def _coverage_notes(specs: list[dict]) -> list[str]:
        notes = []
        for spec in specs:
            if not spec["coverage"]["sufficient"]:
                notes.append(
                    f"{spec['label']} {spec['timeframe']} coverage {spec['coverage']['coverage_ratio']} is insufficient."
                )
        return notes or ["Recent M1 coverage is partial; annual M1 may be under-covered depending on broker history."]

    @staticmethod
    def _viability_decision(runs: list[dict]) -> dict:
        strongest = None
        for run in runs:
            candidate = run["best_result"]
            if candidate is None:
                continue
            current_tuple = (
                candidate["metrics"]["profit_factor"],
                candidate["out_of_sample"]["profit_factor"],
                candidate["metrics"]["total_trades"],
            )
            if strongest is None or current_tuple > strongest[0]:
                strongest = (current_tuple, run)
        if strongest is None:
            return {"status": "NEEDS_MORE_DATA", "reason": "No valid runs."}
        run = strongest[1]
        best = run["best_result"]
        metrics = best["metrics"]
        oos = best["out_of_sample"]
        status = "VIABLE" if metrics["total_trades"] >= 100 and metrics["profit_factor"] >= 1.3 and oos["profit_factor"] >= 1.2 else "NOT_ROBUST"
        return {"status": status, "reason": f"Best run {run['dataset_label']} {run['timeframe']} {best['session_variant']}."}

    @staticmethod
    def _metrics(trades: list[ClosedTrade]) -> dict:
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "net_profit_r": 0.0,
                "max_drawdown_r": 0.0,
                "expectancy_r": 0.0,
                "losing_streak": 0,
            }
        wins = [t for t in trades if t.pnl_r > 0]
        losses = [t for t in trades if t.pnl_r < 0]
        gross_profit = sum(t.pnl_r for t in wins)
        gross_loss = abs(sum(t.pnl_r for t in losses))
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        streak = worst = 0
        for trade in trades:
            equity += trade.pnl_r
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if trade.pnl_r < 0:
                streak += 1
                worst = max(worst, streak)
            else:
                streak = 0
        net = sum(t.pnl_r for t in trades)
        return {
            "total_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100.0, 2),
            "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4),
            "net_profit_r": round(net, 4),
            "max_drawdown_r": round(max_dd, 4),
            "expectancy_r": round(net / len(trades), 4),
            "losing_streak": worst,
        }

    @staticmethod
    def _split_metrics(trades: list[ClosedTrade]) -> dict:
        if not trades:
            empty = MaximoMTFQuantV4Backtester._metrics([])
            return {"in_sample": empty, "out_of_sample": empty}
        cutoff = max(1, int(len(trades) * 0.7))
        return {
            "in_sample": MaximoMTFQuantV4Backtester._metrics(trades[:cutoff]),
            "out_of_sample": MaximoMTFQuantV4Backtester._metrics(trades[cutoff:]),
        }

    @staticmethod
    def _monthly_distribution(trades: list[ClosedTrade]) -> list[dict]:
        grouped: dict[str, list[ClosedTrade]] = {}
        for trade in trades:
            grouped.setdefault(trade.month, []).append(trade)
        rows = []
        for month in sorted(grouped):
            metrics = MaximoMTFQuantV4Backtester._metrics(grouped[month])
            rows.append({"month": month, **metrics})
        return rows

    @staticmethod
    def _hour_edge(trades: list[ClosedTrade], *, best: bool) -> dict | None:
        if not trades:
            return None
        grouped: dict[int, list[ClosedTrade]] = {}
        for trade in trades:
            grouped.setdefault(trade.hour_ny, []).append(trade)
        rows = []
        for hour, bucket in grouped.items():
            metrics = MaximoMTFQuantV4Backtester._metrics(bucket)
            rows.append(
                {
                    "hour_ny": hour,
                    "trades": metrics["total_trades"],
                    "profit_factor": metrics["profit_factor"],
                    "expectancy_r": metrics["expectancy_r"],
                }
            )
        return max(rows, key=lambda r: (r["profit_factor"], r["expectancy_r"], r["trades"])) if best else min(rows, key=lambda r: (r["profit_factor"], r["expectancy_r"], -r["trades"]))

    @staticmethod
    def _selection_score(result: dict) -> tuple[float, float, int]:
        metrics = result["metrics"]
        oos = result["out_of_sample"]
        return (
            metrics["profit_factor"] * oos["profit_factor"],
            metrics["profit_factor"],
            metrics["total_trades"],
        )

    def _write_summary_csv(self, runs: list[dict]) -> None:
        fields = [
            "dataset_label",
            "timeframe",
            "strategy_variant",
            "session_variant",
            "trades",
            "win_rate",
            "profit_factor",
            "net_profit_r",
            "max_drawdown_r",
            "in_sample_pf",
            "out_of_sample_pf",
            "coverage_sufficient",
        ]
        with self.summary_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for run in runs:
                for result in run["results"]:
                    writer.writerow(
                        {
                            "dataset_label": run["dataset_label"],
                            "timeframe": run["timeframe"],
                            "strategy_variant": result["strategy_variant"],
                            "session_variant": result["session_variant"],
                            "trades": result["metrics"]["total_trades"],
                            "win_rate": result["metrics"]["win_rate"],
                            "profit_factor": result["metrics"]["profit_factor"],
                            "net_profit_r": result["metrics"]["net_profit_r"],
                            "max_drawdown_r": result["metrics"]["max_drawdown_r"],
                            "in_sample_pf": result["in_sample"]["profit_factor"],
                            "out_of_sample_pf": result["out_of_sample"]["profit_factor"],
                            "coverage_sufficient": run["coverage_sufficient"],
                        }
                    )

    def _markdown_report(self, payload: dict) -> str:
        lines = [
            "# MAXIMO MTF Quant Institutional v4",
            "",
            f"- symbol_requested: {payload['symbol_requested']}",
            f"- symbol_used: {payload['symbol_used']}",
            f"- generated_at: {payload['generated_at']}",
            "",
            "## Coverage Notes",
        ]
        for note in payload["coverage_notes"]:
            lines.append(f"- {note}")
        lines.extend(["", "## Best Results"])
        for run in payload["runs"]:
            lines.append(f"### {run['dataset_label']} | {run['timeframe']}")
            best = run["best_result"]
            if not best:
                lines.append("- no result")
                continue
            lines.append(f"- strategy_variant: {best['strategy_variant']}")
            lines.append(f"- session_variant: {best['session_variant']}")
            lines.append(f"- trades: {best['metrics']['total_trades']}")
            lines.append(f"- win_rate: {best['metrics']['win_rate']}")
            lines.append(f"- profit_factor: {best['metrics']['profit_factor']}")
            lines.append(f"- net_profit_r: {best['metrics']['net_profit_r']}")
            lines.append(f"- max_drawdown_r: {best['metrics']['max_drawdown_r']}")
            lines.append(f"- in_sample_pf: {best['in_sample']['profit_factor']}")
            lines.append(f"- out_of_sample_pf: {best['out_of_sample']['profit_factor']}")
        lines.extend(["", "## Decision"])
        lines.append(f"- status: {payload['viability_decision']['status']}")
        lines.append(f"- reason: {payload['viability_decision']['reason']}")
        return "\n".join(lines) + "\n"

    def _best_candidates_snapshot(self, payload: dict) -> dict:
        candidates = []
        for run in payload["runs"]:
            for result in run["results"]:
                if result["metrics"]["total_trades"] < 20:
                    continue
                candidates.append(
                    {
                        "dataset_label": run["dataset_label"],
                        "timeframe": run["timeframe"],
                        "strategy_variant": result["strategy_variant"],
                        "session_variant": result["session_variant"],
                        "metrics": result["metrics"],
                        "in_sample": result["in_sample"],
                        "out_of_sample": result["out_of_sample"],
                        "selection_score": self._selection_score(result),
                    }
                )
        candidates.sort(
            key=lambda item: (
                item["selection_score"][0],
                item["selection_score"][1],
                item["selection_score"][2],
            ),
            reverse=True,
        )
        return {
            "strategy_name": payload["strategy_name"],
            "generated_at": payload["generated_at"],
            "top_candidates": candidates[:20],
        }

    @staticmethod
    def _session_allowed(time_value: datetime, variant: SessionVariant) -> bool:
        if not variant.windows:
            return True
        local = time_value.astimezone(NY_TZ).time()
        return any(start <= local <= end for start, end in variant.windows)

    @staticmethod
    def _map_completed_indices(entry_candles: list[Candle], context_candles: list[Candle], duration: timedelta) -> list[int | None]:
        result: list[int | None] = [None] * len(entry_candles)
        pointer = -1
        for index, candle in enumerate(entry_candles):
            cutoff = candle.time - duration
            while pointer + 1 < len(context_candles) and context_candles[pointer + 1].time <= cutoff:
                pointer += 1
            result[index] = pointer if pointer >= 0 else None
        return result

    @staticmethod
    def _resolve_symbol(symbol: str) -> str:
        return symbol if symbol.endswith("m") else f"{symbol}m"

    @staticmethod
    def _resample(candles: list[Candle], timeframe: str) -> list[Candle]:
        return BlueprintBacktester._resample(candles, timeframe)

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float | None]:
        return BlueprintBacktester._ema(values, period)

    @staticmethod
    def _atr(candles: list[Candle], period: int) -> list[float | None]:
        return BlueprintBacktester._atr(candles, period)

    @staticmethod
    def _sma(values: list[float | None], period: int) -> list[float | None]:
        result: list[float | None] = [None] * len(values)
        for index in range(len(values)):
            window = [value for value in values[max(0, index - period + 1) : index + 1] if value is not None]
            if len(window) == period:
                result[index] = sum(window) / period
        return result
