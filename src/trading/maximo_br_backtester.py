"""Dedicated backtester for MAXIMO B&R PRO v2.0 1.3R."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from src.core.logging import get_logger
from src.trading.blueprint_backtester import BlueprintBacktester, Candle

logger = get_logger(__name__)

NY_TZ = ZoneInfo("America/New_York")
TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}


@dataclass(slots=True)
class SessionVariant:
    code: str
    label: str
    windows: list[tuple[int, int]]


@dataclass(slots=True)
class SlippageScenario:
    code: str
    label: str
    spread_points: float
    fixed_slippage_points: float
    dynamic: bool
    commission_per_trade_r: float


@dataclass(slots=True)
class StrategyProfile:
    code: str
    label: str
    pivot_len: int
    retest_lookahead: int
    cooldown_bars: int
    min_score: int
    max_trades_per_day: int
    max_losses_per_day: int
    daily_stop_r: float
    breakout_body_ratio_min: float
    close_extreme_ratio_max: float
    wick_body_ratio_min: float
    max_distance_atr: float
    max_entry_range_atr: float
    max_breakout_range_atr: float
    min_ema_spread_atr: float
    min_level_distance_atr: float
    require_htf_slope: bool
    break_even_trigger_r: float = 0.0
    trail_trigger_r: float = 0.0
    trail_atr_multiple: float = 0.0


@dataclass(slots=True)
class TradeResult:
    symbol: str
    timeframe: str
    strategy_profile: str
    session_variant: str
    execution_mode: str
    slippage_scenario: str
    direction: str
    breakout_time: datetime
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    take_profit_price: float
    support_resistance_level: float
    score: int
    body_ratio: float
    distance_atr_ratio: float
    retest_bars_waited: int
    trend_aligned: bool
    retest_valid: bool
    reaction_valid: bool
    distance_valid: bool
    month: str
    session_bucket: str
    hour_ny: int
    pnl_r: float
    exit_reason: str


@dataclass(slots=True)
class PendingBreakout:
    direction: str
    level: float
    breakout_index: int
    breakout_time: datetime
    expires_index: int


@dataclass(slots=True)
class OpenTrade:
    direction: str
    signal_index: int
    activation_index: int
    breakout_time: datetime
    signal_time: datetime
    entry_time: datetime
    entry_price: float
    stop_price: float
    initial_stop_price: float
    take_profit_price: float
    support_resistance_level: float
    trade_day: date
    risk_amount: float
    score: int
    body_ratio: float
    distance_atr_ratio: float
    retest_bars_waited: int
    trend_aligned: bool
    retest_valid: bool
    reaction_valid: bool
    distance_valid: bool


@dataclass(slots=True)
class OrderBlockZone:
    direction: str
    low: float
    high: float
    source_index: int


class MaximoBRProBacktester:
    """Run a realistic research backtest for MAXIMO B&R PRO v2.0 1.3R."""

    EMA_FAST = 20
    EMA_SLOW = 40
    EMA_HTF = 50
    ATR_PERIOD = 14
    PIVOT_LEN = 6
    RR = 1.3
    COOLDOWN_BARS = 45
    RETEST_LOOKAHEAD = 10
    BREAKOUT_BUFFER_ATR = 0.08
    RETEST_BUFFER_ATR = 0.12
    STOP_BUFFER_ATR = 0.25
    MAX_DISTANCE_ATR = 0.75
    MAX_ENTRY_RANGE_ATR = 2.0
    MAX_BREAKOUT_RANGE_ATR = 2.0
    MIN_EMA_SPREAD_ATR = 0.0
    MIN_LEVEL_DISTANCE_ATR = 0.0

    SESSION_VARIANTS = [
        SessionVariant("all", "Sin filtro horario", []),
        SessionVariant("london", "Solo Londres", [(2, 6)]),
        SessionVariant("ny_am", "Solo NY AM", [(8, 12)]),
        SessionVariant("london_ny_am", "Londres + NY AM", [(2, 6), (8, 12)]),
    ]

    SLIPPAGE_SCENARIOS = [
        SlippageScenario("A", "0 slippage", spread_points=0.10, fixed_slippage_points=0.00, dynamic=False, commission_per_trade_r=0.0),
        SlippageScenario("B", "normal slippage", spread_points=0.12, fixed_slippage_points=0.02, dynamic=False, commission_per_trade_r=0.01),
        SlippageScenario("C", "adverse volatility slippage", spread_points=0.15, fixed_slippage_points=0.02, dynamic=True, commission_per_trade_r=0.02),
    ]
    STRATEGY_PROFILES = [
        StrategyProfile(
            "baseline_v20",
            "Baseline v2.0",
            pivot_len=6,
            retest_lookahead=10,
            cooldown_bars=45,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.55,
            close_extreme_ratio_max=0.30,
            wick_body_ratio_min=0.35,
            max_distance_atr=0.75,
            max_entry_range_atr=2.0,
            max_breakout_range_atr=2.0,
            min_ema_spread_atr=0.0,
            min_level_distance_atr=0.0,
            require_htf_slope=False,
        ),
        StrategyProfile(
            "precision_v21",
            "Precision v2.1",
            pivot_len=6,
            retest_lookahead=6,
            cooldown_bars=45,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.60,
            close_extreme_ratio_max=0.22,
            wick_body_ratio_min=0.45,
            max_distance_atr=0.60,
            max_entry_range_atr=1.8,
            max_breakout_range_atr=1.8,
            min_ema_spread_atr=0.08,
            min_level_distance_atr=0.80,
            require_htf_slope=True,
        ),
        StrategyProfile(
            "balanced_precision_v21",
            "Balanced Precision v2.1",
            pivot_len=6,
            retest_lookahead=5,
            cooldown_bars=45,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.58,
            close_extreme_ratio_max=0.25,
            wick_body_ratio_min=0.40,
            max_distance_atr=0.65,
            max_entry_range_atr=1.8,
            max_breakout_range_atr=1.9,
            min_ema_spread_atr=0.06,
            min_level_distance_atr=0.70,
            require_htf_slope=True,
        ),
        StrategyProfile(
            "smart_precision_v21",
            "Smart Precision v2.1",
            pivot_len=6,
            retest_lookahead=7,
            cooldown_bars=45,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.57,
            close_extreme_ratio_max=0.27,
            wick_body_ratio_min=0.38,
            max_distance_atr=0.70,
            max_entry_range_atr=1.9,
            max_breakout_range_atr=1.75,
            min_ema_spread_atr=0.03,
            min_level_distance_atr=0.45,
            require_htf_slope=True,
        ),
        StrategyProfile(
            "frequency_control_v22",
            "Frequency Control v2.2",
            pivot_len=5,
            retest_lookahead=8,
            cooldown_bars=18,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.54,
            close_extreme_ratio_max=0.31,
            wick_body_ratio_min=0.34,
            max_distance_atr=0.78,
            max_entry_range_atr=2.1,
            max_breakout_range_atr=1.9,
            min_ema_spread_atr=0.02,
            min_level_distance_atr=0.25,
            require_htf_slope=False,
        ),
        StrategyProfile(
            "aggressive_control_v22",
            "Aggressive Control v2.2",
            pivot_len=4,
            retest_lookahead=9,
            cooldown_bars=12,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.52,
            close_extreme_ratio_max=0.34,
            wick_body_ratio_min=0.30,
            max_distance_atr=0.85,
            max_entry_range_atr=2.25,
            max_breakout_range_atr=2.0,
            min_ema_spread_atr=0.0,
            min_level_distance_atr=0.15,
            require_htf_slope=False,
        ),
        StrategyProfile(
            "ultra_precision_v21",
            "Ultra Precision v2.1",
            pivot_len=7,
            retest_lookahead=4,
            cooldown_bars=45,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.65,
            close_extreme_ratio_max=0.20,
            wick_body_ratio_min=0.50,
            max_distance_atr=0.50,
            max_entry_range_atr=1.6,
            max_breakout_range_atr=1.6,
            min_ema_spread_atr=0.12,
            min_level_distance_atr=1.00,
            require_htf_slope=True,
        ),
        StrategyProfile(
            "mtf_confluence_v23",
            "MTF Confluence v2.3",
            pivot_len=5,
            retest_lookahead=7,
            cooldown_bars=20,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.55,
            close_extreme_ratio_max=0.28,
            wick_body_ratio_min=0.34,
            max_distance_atr=0.72,
            max_entry_range_atr=1.9,
            max_breakout_range_atr=1.85,
            min_ema_spread_atr=0.03,
            min_level_distance_atr=0.35,
            require_htf_slope=True,
        ),
        StrategyProfile(
            "mtf_balanced_v23",
            "MTF Balanced v2.3",
            pivot_len=5,
            retest_lookahead=8,
            cooldown_bars=18,
            min_score=90,
            max_trades_per_day=0,
            max_losses_per_day=0,
            daily_stop_r=0.0,
            breakout_body_ratio_min=0.54,
            close_extreme_ratio_max=0.30,
            wick_body_ratio_min=0.33,
            max_distance_atr=0.76,
            max_entry_range_atr=2.0,
            max_breakout_range_atr=1.95,
            min_ema_spread_atr=0.02,
            min_level_distance_atr=0.25,
            require_htf_slope=True,
        ),
        StrategyProfile(
            "aggressive_guarded_v24",
            "Aggressive Guarded v2.4",
            pivot_len=4,
            retest_lookahead=9,
            cooldown_bars=8,
            min_score=85,
            max_trades_per_day=3,
            max_losses_per_day=2,
            daily_stop_r=-2.5,
            breakout_body_ratio_min=0.51,
            close_extreme_ratio_max=0.36,
            wick_body_ratio_min=0.28,
            max_distance_atr=0.90,
            max_entry_range_atr=2.30,
            max_breakout_range_atr=2.10,
            min_ema_spread_atr=0.0,
            min_level_distance_atr=0.10,
            require_htf_slope=False,
            break_even_trigger_r=0.8,
            trail_trigger_r=1.0,
            trail_atr_multiple=1.0,
        ),
        StrategyProfile(
            "mtf_guarded_v24",
            "MTF Guarded v2.4",
            pivot_len=4,
            retest_lookahead=8,
            cooldown_bars=10,
            min_score=85,
            max_trades_per_day=3,
            max_losses_per_day=2,
            daily_stop_r=-2.5,
            breakout_body_ratio_min=0.52,
            close_extreme_ratio_max=0.34,
            wick_body_ratio_min=0.30,
            max_distance_atr=0.85,
            max_entry_range_atr=2.20,
            max_breakout_range_atr=2.00,
            min_ema_spread_atr=0.0,
            min_level_distance_atr=0.12,
            require_htf_slope=True,
            break_even_trigger_r=0.8,
            trail_trigger_r=1.0,
            trail_atr_multiple=0.9,
        ),
        StrategyProfile(
            "aggressive_managed_v25",
            "Aggressive Managed v2.5",
            pivot_len=4,
            retest_lookahead=9,
            cooldown_bars=8,
            min_score=84,
            max_trades_per_day=4,
            max_losses_per_day=2,
            daily_stop_r=-2.5,
            breakout_body_ratio_min=0.50,
            close_extreme_ratio_max=0.36,
            wick_body_ratio_min=0.27,
            max_distance_atr=0.92,
            max_entry_range_atr=2.35,
            max_breakout_range_atr=2.15,
            min_ema_spread_atr=0.0,
            min_level_distance_atr=0.08,
            require_htf_slope=False,
            break_even_trigger_r=0.7,
            trail_trigger_r=0.9,
            trail_atr_multiple=0.8,
        ),
        StrategyProfile(
            "mtf_managed_v25",
            "MTF Managed v2.5",
            pivot_len=4,
            retest_lookahead=8,
            cooldown_bars=10,
            min_score=84,
            max_trades_per_day=4,
            max_losses_per_day=2,
            daily_stop_r=-2.5,
            breakout_body_ratio_min=0.51,
            close_extreme_ratio_max=0.34,
            wick_body_ratio_min=0.29,
            max_distance_atr=0.88,
            max_entry_range_atr=2.25,
            max_breakout_range_atr=2.05,
            min_ema_spread_atr=0.0,
            min_level_distance_atr=0.10,
            require_htf_slope=True,
            break_even_trigger_r=0.7,
            trail_trigger_r=0.9,
            trail_atr_multiple=0.8,
        ),
    ]

    def __init__(self, input_dir: Path, output_dir: Path) -> None:
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results_json = self.output_dir / "maximo_br_pro_v2_0_results.json"
        self.report_md = self.output_dir / "maximo_br_pro_v2_0_report.md"
        self.summary_csv = self.output_dir / "maximo_br_pro_v2_0_summary.csv"
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
            run_result = self._run_dataset(
                symbol=resolved_symbol,
                dataset_label=spec["label"],
                timeframe=spec["timeframe"],
                entry_candles=spec["entry_candles"],
                htf_candles=spec["htf_candles"],
                coverage=spec["coverage"],
                context=spec.get("context"),
            )
            runs.append(run_result)

        payload = {
            "strategy_name": "MAXIMO B&R PRO v2.0 1.3R",
            "symbol_requested": symbol,
            "symbol_used": resolved_symbol,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "assumptions": {
                "ema_fast": self.EMA_FAST,
                "ema_slow": self.EMA_SLOW,
                "atr_period": self.ATR_PERIOD,
                "htf_timeframe": "H1",
                "htf_ema": self.EMA_HTF,
                "pivot_length": self.PIVOT_LEN,
                "rr_target": self.RR,
                "cooldown_bars": self.COOLDOWN_BARS,
                "retest_lookahead_bars": self.RETEST_LOOKAHEAD,
                "strategy_profiles": [asdict(profile) for profile in self.STRATEGY_PROFILES],
                "same_bar_tp_sl_policy": "worst_case_stop_first",
                "net_profit_units": "R multiples, after spread/slippage/commission assumptions",
                "session_time_reference": "America/New_York",
            },
            "coverage_notes": self._coverage_notes(dataset_specs),
            "runs": runs,
            "conservative_focus": self._conservative_focus(runs),
            "viability_decision": self._viability_decision(runs),
        }

        self.results_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report_md.write_text(self._markdown_report(payload), encoding="utf-8")
        self._write_summary_csv(runs)
        return {
            "strategy_name": payload["strategy_name"],
            "symbol_used": resolved_symbol,
            "runs": len(runs),
            "results_json": str(self.results_json.resolve()),
            "report_md": str(self.report_md.resolve()),
            "summary_csv": str(self.summary_csv.resolve()),
            "decision": payload["viability_decision"]["status"],
        }

    def _run_dataset(
        self,
        *,
        symbol: str,
        dataset_label: str,
        timeframe: str,
        entry_candles: list[Candle],
        htf_candles: list[Candle],
        coverage: dict,
        context: dict | None = None,
    ) -> dict:
        all_results: list[dict] = []
        for profile in self.STRATEGY_PROFILES:
            for session_variant in self.SESSION_VARIANTS:
                for execution_mode in ("close", "next_open"):
                    for slippage_scenario in self.SLIPPAGE_SCENARIOS:
                        trades = self._simulate(
                            symbol=symbol,
                            timeframe=timeframe,
                            entry_candles=entry_candles,
                            htf_candles=htf_candles,
                            context=context or {},
                            profile=profile,
                            session_variant=session_variant,
                            execution_mode=execution_mode,
                            slippage_scenario=slippage_scenario,
                        )
                        metrics = self._metrics(trades)
                        splits = self._split_metrics(trades)
                        monthly = self._monthly_distribution(trades)
                        all_results.append(
                            {
                                "strategy_profile": profile.code,
                                "strategy_profile_label": profile.label,
                                "session_variant": session_variant.code,
                                "session_label": session_variant.label,
                                "execution_mode": execution_mode,
                                "slippage_scenario": slippage_scenario.code,
                                "slippage_label": slippage_scenario.label,
                                "trade_count": len(trades),
                                "metrics": metrics,
                                "in_sample": splits["in_sample"],
                                "out_of_sample": splits["out_of_sample"],
                                "monthly_distribution": monthly,
                                "best_session_bucket": self._session_bucket_edge(trades, best=True),
                                "worst_session_bucket": self._session_bucket_edge(trades, best=False),
                            }
                        )

        conservative = [
            item for item in all_results if item["execution_mode"] == "next_open" and item["slippage_scenario"] == "C"
        ]
        best_conservative = max(
            conservative,
            key=lambda item: (
                item["metrics"]["profit_factor"],
                item["metrics"]["expectancy_r"],
                item["metrics"]["total_trades"],
            ),
            default=None,
        )
        best_overall = max(
            all_results,
            key=lambda item: (
                item["metrics"]["profit_factor"],
                item["metrics"]["expectancy_r"],
                item["metrics"]["total_trades"],
            ),
        )
        return {
            "dataset_label": dataset_label,
            "timeframe": timeframe,
            "bars": len(entry_candles),
            "start_time": entry_candles[0].time.isoformat() if entry_candles else None,
            "end_time": entry_candles[-1].time.isoformat() if entry_candles else None,
            "coverage": coverage,
            "coverage_sufficient": coverage["sufficient"],
            "best_conservative": best_conservative,
            "best_overall": best_overall,
            "results": all_results,
        }

    def _simulate(
        self,
        *,
        symbol: str,
        timeframe: str,
        entry_candles: list[Candle],
        htf_candles: list[Candle],
        context: dict,
        profile: StrategyProfile,
        session_variant: SessionVariant,
        execution_mode: str,
        slippage_scenario: SlippageScenario,
    ) -> list[TradeResult]:
        if len(entry_candles) < max(self.EMA_SLOW, self.ATR_PERIOD) + profile.pivot_len * 3:
            return []
        closes = [candle.close for candle in entry_candles]
        highs = [candle.high for candle in entry_candles]
        lows = [candle.low for candle in entry_candles]
        ema20 = self._ema(closes, self.EMA_FAST)
        ema40 = self._ema(closes, self.EMA_SLOW)
        atr = self._atr(entry_candles, self.ATR_PERIOD)
        support_by_index, resistance_by_index = self._confirmed_pivots(highs, lows, profile.pivot_len)
        htf_ema50 = self._ema([c.close for c in htf_candles], self.EMA_HTF)
        htf_map = self._map_htf_indices(entry_candles, htf_candles)
        mtf_enabled = profile.code in {"mtf_confluence_v23", "mtf_balanced_v23", "mtf_guarded_v24", "mtf_managed_v25"} and timeframe in {"M5", "M15"}
        m15_context = context.get("m15", []) if mtf_enabled else []
        m30_context = context.get("m30", []) if mtf_enabled else []
        lower_context = (context.get("m1", []) if timeframe == "M5" else context.get("m5", [])) if mtf_enabled else []
        m30_ema20 = self._ema([c.close for c in m30_context], self.EMA_FAST) if m30_context else []
        m30_ema40 = self._ema([c.close for c in m30_context], self.EMA_SLOW) if m30_context else []
        m30_atr = self._atr(m30_context, self.ATR_PERIOD) if m30_context else []
        m30_supports, m30_resistances = self._confirmed_pivots(
            [c.high for c in m30_context],
            [c.low for c in m30_context],
            4,
        ) if m30_context else ([], [])
        m15_atr = self._atr(m15_context, self.ATR_PERIOD) if m15_context else []
        bearish_obs, bullish_obs = self._order_block_zones(m15_context, m15_atr) if m15_context else ([], [])
        m15_map = self._map_completed_indices(entry_candles, m15_context, timedelta(minutes=15)) if m15_context else []
        m30_map = self._map_completed_indices(entry_candles, m30_context, timedelta(minutes=30)) if m30_context else []
        lower_ranges = self._map_lower_ranges(entry_candles, lower_context) if lower_context else []
        trades: list[TradeResult] = []
        pending: PendingBreakout | None = None
        open_trade: OpenTrade | None = None
        cooldown_until = -1
        day_stats: dict[date, dict[str, float | int]] = {}
        blocked_days: set[date] = set()

        for index, candle in enumerate(entry_candles):
            trade_day = candle.time.astimezone(NY_TZ).date()
            if open_trade is not None and index >= open_trade.activation_index:
                self._apply_trade_management(
                    open_trade=open_trade,
                    candle=candle,
                    atr_value=atr[index] or 0.0,
                    profile=profile,
                )
                exit_result = self._maybe_exit_trade(
                    open_trade=open_trade,
                    candle=candle,
                    atr_value=atr[index] or 0.0,
                    slippage_scenario=slippage_scenario,
                    timeframe=timeframe,
                    symbol=symbol,
                    strategy_profile_code=profile.code,
                    session_variant_code=session_variant.code,
                    execution_mode=execution_mode,
                )
                if exit_result is not None:
                    trades.append(exit_result)
                    stats = day_stats.setdefault(open_trade.trade_day, {"trades": 0, "losses": 0, "pnl_r": 0.0})
                    stats["trades"] = int(stats["trades"]) + 1
                    stats["pnl_r"] = float(stats["pnl_r"]) + exit_result.pnl_r
                    if exit_result.pnl_r < 0:
                        stats["losses"] = int(stats["losses"]) + 1
                    if profile.max_losses_per_day and int(stats["losses"]) >= profile.max_losses_per_day:
                        blocked_days.add(open_trade.trade_day)
                    if profile.daily_stop_r and float(stats["pnl_r"]) <= profile.daily_stop_r:
                        blocked_days.add(open_trade.trade_day)
                    cooldown_until = max(cooldown_until, open_trade.signal_index + profile.cooldown_bars)
                    open_trade = None
                    pending = None

            if open_trade is not None:
                continue
            if trade_day in blocked_days:
                continue
            if index <= cooldown_until:
                continue
            if index + 1 >= len(entry_candles):
                break
            stats = day_stats.setdefault(trade_day, {"trades": 0, "losses": 0, "pnl_r": 0.0})
            if profile.max_trades_per_day and int(stats["trades"]) >= profile.max_trades_per_day:
                continue

            htf_index = htf_map[index]
            if htf_index is None:
                continue
            ema20_value = ema20[index]
            ema40_value = ema40[index]
            atr_value = atr[index]
            htf_close = htf_candles[htf_index].close
            htf_ema = htf_ema50[htf_index]
            if None in {ema20_value, ema40_value, atr_value, htf_ema}:
                continue

            if pending is not None and index > pending.expires_index:
                pending = None

            trend_buy = candle.close > ema20_value and ema20_value > ema40_value and htf_close > htf_ema
            trend_sell = candle.close < ema20_value and ema20_value < ema40_value and htf_close < htf_ema
            ema_spread = abs(ema20_value - ema40_value)
            if ema_spread < atr_value * profile.min_ema_spread_atr:
                trend_buy = False
                trend_sell = False
            if profile.require_htf_slope and htf_index <= 0:
                trend_buy = False
                trend_sell = False
            elif profile.require_htf_slope:
                prev_htf_ema = htf_ema50[htf_index - 1]
                if prev_htf_ema is None:
                    trend_buy = False
                    trend_sell = False
                else:
                    trend_buy = trend_buy and htf_ema > prev_htf_ema
                    trend_sell = trend_sell and htf_ema < prev_htf_ema
            current_session_ok = self._session_allowed(candle.time, session_variant)
            if not current_session_ok:
                continue

            if pending is not None and index > pending.breakout_index:
                lower_tf_confirmation = True
                mtf_context_ok = True
                if mtf_enabled:
                    lower_tf_confirmation = (
                        self._lower_tf_confirmation_ok(
                            index=index,
                            entry_candles=entry_candles,
                            lower_candles=lower_context,
                            lower_ranges=lower_ranges,
                            direction=pending.direction,
                        )
                        if lower_context
                        else self._trigger_candle_ok(candle, pending.direction)
                    )
                    mtf_context_ok = self._mtf_context_ok(
                        index=index,
                        direction=pending.direction,
                        level=pending.level,
                        entry_candle=candle,
                        atr_value=atr_value,
                        m15_map=m15_map,
                        m30_map=m30_map,
                        m15_context=m15_context,
                        m30_context=m30_context,
                        m30_ema20=m30_ema20,
                        m30_ema40=m30_ema40,
                        m30_atr=m30_atr,
                        m30_supports=m30_supports,
                        m30_resistances=m30_resistances,
                        bearish_obs=bearish_obs,
                        bullish_obs=bullish_obs,
                        strict=profile.code == "mtf_confluence_v23",
                    )
                confirmed = self._maybe_confirm_entry(
                    index=index,
                    candle=candle,
                    pending=pending,
                    atr_value=atr_value,
                    profile=profile,
                    trend_buy=trend_buy and mtf_context_ok,
                    trend_sell=trend_sell and mtf_context_ok,
                    lower_tf_confirmation=lower_tf_confirmation,
                )
                if confirmed is not None:
                    entry_price = self._entry_price(
                        execution_mode=execution_mode,
                        signal_candle=candle,
                        next_candle=entry_candles[index + 1],
                        direction=confirmed["direction"],
                        slippage_scenario=slippage_scenario,
                        atr_value=atr_value,
                    )
                    if entry_price is None:
                        pending = None
                        continue
                    stop_price = self._stop_price(
                        direction=confirmed["direction"],
                        candle=candle,
                        level=pending.level,
                        atr_value=atr_value,
                    )
                    risk = abs(entry_price - stop_price)
                    if risk <= 0:
                        pending = None
                        continue
                    take_profit = (
                        entry_price + risk * self.RR
                        if confirmed["direction"] == "buy"
                        else entry_price - risk * self.RR
                    )
                    open_trade = OpenTrade(
                        direction=confirmed["direction"],
                        signal_index=index,
                        activation_index=index + 1,
                        breakout_time=pending.breakout_time,
                        signal_time=candle.time,
                        entry_time=candle.time if execution_mode == "close" else entry_candles[index + 1].time,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        initial_stop_price=stop_price,
                        take_profit_price=take_profit,
                        support_resistance_level=pending.level,
                        trade_day=trade_day,
                        risk_amount=risk,
                        score=confirmed["score"],
                        body_ratio=confirmed["body_ratio"],
                        distance_atr_ratio=confirmed["distance_atr_ratio"],
                        retest_bars_waited=index - pending.breakout_index,
                        trend_aligned=True,
                        retest_valid=confirmed["retest_valid"],
                        reaction_valid=confirmed["reaction_valid"],
                        distance_valid=confirmed["distance_valid"],
                    )
                    pending = None
                    continue

            if pending is None:
                body_ratio = self._body_ratio(candle)
                candle_range = max(candle.high - candle.low, 1e-9)
                breakout_buffer = atr_value * self.BREAKOUT_BUFFER_ATR
                resistance = resistance_by_index[index]
                support = support_by_index[index]
                level_distance_ok = True
                if resistance is not None and support is not None and profile.min_level_distance_atr > 0:
                    level_distance_ok = abs(resistance - support) >= atr_value * profile.min_level_distance_atr
                buy_breakout = (
                    resistance is not None
                    and trend_buy
                    and level_distance_ok
                    and candle.close > resistance + breakout_buffer
                    and body_ratio >= profile.breakout_body_ratio_min
                    and (candle.high - candle.close) <= candle_range * profile.close_extreme_ratio_max
                    and candle_range <= atr_value * profile.max_breakout_range_atr
                )
                sell_breakout = (
                    support is not None
                    and trend_sell
                    and level_distance_ok
                    and candle.close < support - breakout_buffer
                    and body_ratio >= profile.breakout_body_ratio_min
                    and (candle.close - candle.low) <= candle_range * profile.close_extreme_ratio_max
                    and candle_range <= atr_value * profile.max_breakout_range_atr
                )
                if buy_breakout:
                    pending = PendingBreakout(
                        direction="buy",
                        level=resistance,
                        breakout_index=index,
                        breakout_time=candle.time,
                        expires_index=index + profile.retest_lookahead,
                    )
                elif sell_breakout:
                    pending = PendingBreakout(
                        direction="sell",
                        level=support,
                        breakout_index=index,
                        breakout_time=candle.time,
                        expires_index=index + profile.retest_lookahead,
                    )

        return trades

    def _maybe_confirm_entry(
        self,
        *,
        index: int,
        candle: Candle,
        pending: PendingBreakout,
        atr_value: float,
        profile: StrategyProfile,
        trend_buy: bool,
        trend_sell: bool,
        lower_tf_confirmation: bool = True,
    ) -> dict | None:
        retest_buffer = atr_value * self.RETEST_BUFFER_ATR
        level = pending.level
        if pending.direction == "buy":
            retest_valid = candle.low <= level + retest_buffer and candle.close > level
            reaction_valid = candle.close > candle.open and (
                self._lower_wick(candle) >= abs(candle.close - candle.open) * profile.wick_body_ratio_min
                or candle.close > (candle.high + candle.low) / 2.0
            )
            trend_aligned = trend_buy
            distance_value = abs(candle.close - level)
            distance_valid = distance_value <= atr_value * profile.max_distance_atr
        else:
            retest_valid = candle.high >= level - retest_buffer and candle.close < level
            reaction_valid = candle.close < candle.open and (
                self._upper_wick(candle) >= abs(candle.close - candle.open) * profile.wick_body_ratio_min
                or candle.close < (candle.high + candle.low) / 2.0
            )
            trend_aligned = trend_sell
            distance_value = abs(candle.close - level)
            distance_valid = distance_value <= atr_value * profile.max_distance_atr

        if candle.high - candle.low > atr_value * profile.max_entry_range_atr:
            distance_valid = False
        if not lower_tf_confirmation:
            return None

        score = 35
        if trend_aligned:
            score += 25
        if retest_valid:
            score += 20
        if reaction_valid:
            score += 10
        if distance_valid:
            score += 10
        if score < profile.min_score:
            return None
        return {
            "direction": pending.direction,
            "score": score,
            "retest_valid": retest_valid,
            "reaction_valid": reaction_valid,
            "distance_valid": distance_valid,
            "body_ratio": self._body_ratio(candle),
            "distance_atr_ratio": round(distance_value / max(atr_value, 1e-9), 4),
        }

    def _entry_price(
        self,
        *,
        execution_mode: str,
        signal_candle: Candle,
        next_candle: Candle,
        direction: str,
        slippage_scenario: SlippageScenario,
        atr_value: float,
    ) -> float | None:
        raw_entry = signal_candle.close if execution_mode == "close" else next_candle.open
        reference_candle = signal_candle if execution_mode == "close" else next_candle
        adverse_slippage = self._slippage_points(
            scenario=slippage_scenario,
            candle=reference_candle,
            atr_value=atr_value,
        )
        spread_half = slippage_scenario.spread_points / 2.0
        if direction == "buy":
            return raw_entry + spread_half + adverse_slippage
        return raw_entry - spread_half - adverse_slippage

    def _stop_price(self, *, direction: str, candle: Candle, level: float, atr_value: float) -> float:
        if direction == "buy":
            return min(candle.low, level - atr_value * self.STOP_BUFFER_ATR)
        return max(candle.high, level + atr_value * self.STOP_BUFFER_ATR)

    def _apply_trade_management(
        self,
        *,
        open_trade: OpenTrade,
        candle: Candle,
        atr_value: float,
        profile: StrategyProfile,
    ) -> None:
        risk = max(open_trade.risk_amount, 1e-9)
        if open_trade.direction == "buy":
            favorable_r = (candle.high - open_trade.entry_price) / risk
            if profile.break_even_trigger_r > 0 and favorable_r >= profile.break_even_trigger_r:
                open_trade.stop_price = max(open_trade.stop_price, open_trade.entry_price)
            if profile.trail_trigger_r > 0 and profile.trail_atr_multiple > 0 and favorable_r >= profile.trail_trigger_r:
                trailed = candle.close - atr_value * profile.trail_atr_multiple
                open_trade.stop_price = max(open_trade.stop_price, trailed)
        else:
            favorable_r = (open_trade.entry_price - candle.low) / risk
            if profile.break_even_trigger_r > 0 and favorable_r >= profile.break_even_trigger_r:
                open_trade.stop_price = min(open_trade.stop_price, open_trade.entry_price)
            if profile.trail_trigger_r > 0 and profile.trail_atr_multiple > 0 and favorable_r >= profile.trail_trigger_r:
                trailed = candle.close + atr_value * profile.trail_atr_multiple
                open_trade.stop_price = min(open_trade.stop_price, trailed)

    def _maybe_exit_trade(
        self,
        *,
        open_trade: OpenTrade,
        candle: Candle,
        atr_value: float,
        slippage_scenario: SlippageScenario,
        timeframe: str,
        symbol: str,
        strategy_profile_code: str,
        session_variant_code: str,
        execution_mode: str,
    ) -> TradeResult | None:
        stop_hit = candle.low <= open_trade.stop_price if open_trade.direction == "buy" else candle.high >= open_trade.stop_price
        tp_hit = candle.high >= open_trade.take_profit_price if open_trade.direction == "buy" else candle.low <= open_trade.take_profit_price
        if not stop_hit and not tp_hit:
            return None

        adverse_slippage = self._slippage_points(
            scenario=slippage_scenario,
            candle=candle,
            atr_value=atr_value,
        )
        spread_half = slippage_scenario.spread_points / 2.0
        risk = max(open_trade.risk_amount, abs(open_trade.entry_price - open_trade.initial_stop_price))
        if risk <= 0:
            return None

        if stop_hit:
            exit_reason = "stop_loss_first" if tp_hit else "stop_loss"
            raw_exit = open_trade.stop_price
            if open_trade.direction == "buy":
                exit_price = raw_exit - spread_half - adverse_slippage
            else:
                exit_price = raw_exit + spread_half + adverse_slippage
        else:
            exit_reason = "take_profit"
            raw_exit = open_trade.take_profit_price
            if open_trade.direction == "buy":
                exit_price = raw_exit - spread_half - adverse_slippage
            else:
                exit_price = raw_exit + spread_half + adverse_slippage

        pnl_r_raw = (exit_price - open_trade.entry_price) / risk if open_trade.direction == "buy" else (open_trade.entry_price - exit_price) / risk
        pnl_r = round(pnl_r_raw - slippage_scenario.commission_per_trade_r, 4)
        return TradeResult(
            symbol=symbol,
            timeframe=timeframe,
            strategy_profile=strategy_profile_code,
            session_variant=session_variant_code,
            execution_mode=execution_mode,
            slippage_scenario=slippage_scenario.code,
            direction=open_trade.direction,
            breakout_time=open_trade.breakout_time,
            signal_time=open_trade.signal_time,
            entry_time=open_trade.entry_time,
            exit_time=candle.time,
            entry_price=round(open_trade.entry_price, 4),
            exit_price=round(exit_price, 4),
            stop_price=round(open_trade.stop_price, 4),
            take_profit_price=round(open_trade.take_profit_price, 4),
            support_resistance_level=round(open_trade.support_resistance_level, 4),
            score=open_trade.score,
            body_ratio=round(open_trade.body_ratio, 4),
            distance_atr_ratio=round(open_trade.distance_atr_ratio, 4),
            retest_bars_waited=open_trade.retest_bars_waited,
            trend_aligned=open_trade.trend_aligned,
            retest_valid=open_trade.retest_valid,
            reaction_valid=open_trade.reaction_valid,
            distance_valid=open_trade.distance_valid,
            month=candle.time.strftime("%Y-%m"),
            session_bucket=self._session_bucket(candle.time),
            hour_ny=candle.time.astimezone(NY_TZ).hour,
            pnl_r=pnl_r,
            exit_reason=exit_reason,
        )

    def _dataset_specs(self, symbol: str) -> list[dict]:
        specs: list[dict] = []
        recent = self._load_range_family(symbol, "20251101_20260505")
        if recent:
            now = recent["M5"][-1].time if recent["M5"] else recent["H1"][-1].time
            specs.extend(
                self._build_period_specs(
                    label_prefix="recent",
                    symbol=symbol,
                    m1=recent.get("M1", []),
                    m5=recent.get("M5", []),
                    h1=recent.get("H1", []),
                    periods=[
                        ("last_3_months", now - timedelta(days=90), now),
                        ("last_6_months", now - timedelta(days=180), now),
                    ],
                )
            )
        annual = self._load_year_family(symbol, 2025)
        if annual:
            end = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc)
            start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            specs.extend(
                self._build_period_specs(
                    label_prefix="annual_2025",
                    symbol=symbol,
                    m1=annual.get("M1", []),
                    m5=annual.get("M5", []),
                    h1=annual.get("H1", []),
                    periods=[("full_year_2025", start, end)],
                )
            )
        return specs

    def _build_period_specs(
        self,
        *,
        label_prefix: str,
        symbol: str,
        m1: list[Candle],
        m5: list[Candle],
        h1: list[Candle],
        periods: list[tuple[str, datetime, datetime]],
    ) -> list[dict]:
        specs: list[dict] = []
        for period_name, start, end in periods:
            m1_slice = [c for c in m1 if start <= c.time <= end]
            m5_slice = [c for c in m5 if start <= c.time <= end]
            h1_slice = [c for c in h1 if start <= c.time <= end]
            m15_slice = self._resample(m5_slice, "M15") if m5_slice else []
            for timeframe, entry_candles in (("M1", m1_slice), ("M5", m5_slice), ("M15", m15_slice)):
                coverage = self._coverage_for_timeframe(
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    entry_candles=entry_candles,
                    htf_candles=h1_slice,
                )
                if entry_candles:
                    specs.append(
                        {
                            "label": f"{label_prefix}_{period_name}",
                            "timeframe": timeframe,
                            "entry_candles": entry_candles,
                            "htf_candles": h1_slice,
                            "coverage": coverage,
                            "context": {
                                "m1": m1_slice,
                                "m5": m5_slice,
                                "m15": m15_slice,
                                "m30": self._resample(m5_slice, "M30") if m5_slice else [],
                            },
                        }
                    )
        return specs

    def _load_range_family(self, symbol: str, suffix: str) -> dict[str, list[Candle]]:
        family = {}
        for timeframe in ("M1", "M5", "H1"):
            path = self.input_dir / f"{symbol}_{timeframe}_{suffix}.csv"
            if path.exists():
                family[timeframe] = self._loader._load_candles(path)
        return family

    def _load_year_family(self, symbol: str, year: int) -> dict[str, list[Candle]]:
        family = {}
        for timeframe in ("M1", "M5", "H1"):
            path = self.input_dir / f"{symbol}_{timeframe}_{year}.csv"
            if path.exists():
                family[timeframe] = self._loader._load_candles(path)
        return family

    @staticmethod
    def _coverage_for_timeframe(
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        entry_candles: list[Candle],
        htf_candles: list[Candle],
    ) -> dict:
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
            "first_entry_time": entry_candles[0].time.isoformat() if entry_candles else None,
            "last_entry_time": entry_candles[-1].time.isoformat() if entry_candles else None,
        }

    @staticmethod
    def _coverage_notes(specs: list[dict]) -> list[str]:
        notes = []
        for spec in specs:
            if not spec["coverage"]["sufficient"]:
                label = spec.get("dataset_label") or spec.get("label") or "dataset"
                notes.append(
                    f"{label} {spec['timeframe']} has insufficient coverage ratio {spec['coverage']['coverage_ratio']}."
                )
        if not notes:
            notes.append("M1 annual coverage remains insufficient; recent-window M1 only is used where enough bars exist.")
        return notes

    @staticmethod
    def _conservative_focus(runs: list[dict]) -> list[dict]:
        items = []
        for run in runs:
            items.append(
                {
                    "dataset_label": run["dataset_label"],
                    "timeframe": run["timeframe"],
                    "coverage_sufficient": run["coverage_sufficient"],
                    "best_conservative": run["best_conservative"],
                }
            )
        return items

    @staticmethod
    def _viability_decision(runs: list[dict]) -> dict:
        conservative_runs = [
            run for run in runs if run["coverage_sufficient"] and run["best_conservative"] is not None
        ]
        if not conservative_runs:
            return {
                "status": "NEEDS_MORE_DATA",
                "reason": "No timeframe-period combination has sufficient coverage for a conservative evaluation.",
            }
        strongest = max(
            conservative_runs,
            key=lambda item: (
                item["best_conservative"]["metrics"]["profit_factor"],
                item["best_conservative"]["out_of_sample"]["profit_factor"],
                item["best_conservative"]["metrics"]["total_trades"],
            ),
        )
        metrics = strongest["best_conservative"]["metrics"]
        oos = strongest["best_conservative"]["out_of_sample"]
        monthly = strongest["best_conservative"]["monthly_distribution"]
        negative_streak = MaximoBRProBacktester._negative_month_streak(monthly)
        if (
            metrics["total_trades"] >= 100
            and metrics["profit_factor"] >= 1.3
            and oos["profit_factor"] >= 1.2
            and metrics["expectancy_r"] > 0
            and metrics["max_drawdown_r"] <= 15
            and negative_streak <= 2
        ):
            return {
                "status": "VIABLE",
                "reason": f"Conservative best run {strongest['dataset_label']} {strongest['timeframe']} passes the minimum viability gate.",
                "best_run": strongest,
            }
        return {
            "status": "NOT_ROBUST",
            "reason": f"Best conservative run {strongest['dataset_label']} {strongest['timeframe']} still fails one or more viability gates.",
            "best_run": strongest,
        }

    @staticmethod
    def _negative_month_streak(monthly: list[dict]) -> int:
        max_streak = 0
        current = 0
        for row in monthly:
            if row["net_profit_r"] < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def _session_allowed(time_value: datetime, session_variant: SessionVariant) -> bool:
        if not session_variant.windows:
            return True
        local = time_value.astimezone(NY_TZ)
        return any(start <= local.hour < end for start, end in session_variant.windows)

    @staticmethod
    def _session_bucket(time_value: datetime) -> str:
        local = time_value.astimezone(NY_TZ)
        if 2 <= local.hour < 6:
            return "london"
        if 8 <= local.hour < 12:
            return "ny_am"
        return "other"

    @staticmethod
    def _resolve_symbol(symbol: str) -> str:
        clean = symbol.strip()
        if clean.endswith("m"):
            return clean
        return f"{clean}m"

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float | None]:
        return BlueprintBacktester._ema(values, period)

    @staticmethod
    def _atr(candles: list[Candle], period: int) -> list[float | None]:
        return BlueprintBacktester._atr(candles, period)

    @staticmethod
    def _resample(candles: list[Candle], timeframe: str) -> list[Candle]:
        return BlueprintBacktester._resample(candles, timeframe)

    @staticmethod
    def _body_ratio(candle: Candle) -> float:
        rng = max(candle.high - candle.low, 1e-9)
        return abs(candle.close - candle.open) / rng

    @staticmethod
    def _lower_wick(candle: Candle) -> float:
        return min(candle.open, candle.close) - candle.low

    @staticmethod
    def _upper_wick(candle: Candle) -> float:
        return candle.high - max(candle.open, candle.close)

    @staticmethod
    def _slippage_points(
        *,
        scenario: SlippageScenario,
        candle: Candle,
        atr_value: float,
    ) -> float:
        if not scenario.dynamic:
            return scenario.fixed_slippage_points
        rng = candle.high - candle.low
        if atr_value <= 0:
            return scenario.fixed_slippage_points
        ratio = rng / atr_value
        if ratio >= 2.5:
            return 0.08
        if ratio >= 1.5:
            return 0.05
        return scenario.fixed_slippage_points

    @staticmethod
    def _map_htf_indices(entry_candles: list[Candle], htf_candles: list[Candle]) -> list[int | None]:
        mapping: list[int | None] = [None] * len(entry_candles)
        htf_pointer = -1
        htf_duration = timedelta(hours=1)
        for index, candle in enumerate(entry_candles):
            while htf_pointer + 1 < len(htf_candles) and (htf_candles[htf_pointer + 1].time + htf_duration) <= candle.time:
                htf_pointer += 1
            mapping[index] = htf_pointer if htf_pointer >= 0 else None
        return mapping

    @staticmethod
    def _map_completed_indices(
        entry_candles: list[Candle],
        context_candles: list[Candle],
        duration: timedelta,
    ) -> list[int | None]:
        mapping: list[int | None] = [None] * len(entry_candles)
        pointer = -1
        for index, candle in enumerate(entry_candles):
            cutoff = candle.time - duration
            while pointer + 1 < len(context_candles) and context_candles[pointer + 1].time <= cutoff:
                pointer += 1
            mapping[index] = pointer if pointer >= 0 else None
        return mapping

    @staticmethod
    def _map_lower_ranges(
        entry_candles: list[Candle],
        lower_candles: list[Candle],
    ) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        if not entry_candles or not lower_candles:
            return [(0, 0)] * len(entry_candles)
        entry_duration = (
            entry_candles[1].time - entry_candles[0].time if len(entry_candles) > 1 else timedelta(minutes=5)
        )
        lower_pointer = 0
        for candle in entry_candles:
            start_time = candle.time
            end_time = candle.time + entry_duration
            while lower_pointer < len(lower_candles) and lower_candles[lower_pointer].time < start_time:
                lower_pointer += 1
            start_index = lower_pointer
            end_index = start_index
            while end_index < len(lower_candles) and lower_candles[end_index].time < end_time:
                end_index += 1
            ranges.append((start_index, end_index))
        return ranges

    @staticmethod
    def _order_block_zones(
        candles: list[Candle],
        atr_values: list[float | None],
    ) -> tuple[list[OrderBlockZone | None], list[OrderBlockZone | None]]:
        bearish: list[OrderBlockZone | None] = [None] * len(candles)
        bullish: list[OrderBlockZone | None] = [None] * len(candles)
        latest_bearish: OrderBlockZone | None = None
        latest_bullish: OrderBlockZone | None = None
        for index, candle in enumerate(candles):
            if index > 0 and atr_values[index] is not None:
                prev = candles[index - 1]
                body_ratio = MaximoBRProBacktester._body_ratio(candle)
                candle_range = candle.high - candle.low
                atr_value = atr_values[index] or 0.0
                displacement = candle_range >= atr_value * 0.8 and body_ratio >= 0.55
                if displacement and candle.close < candle.open and prev.close > prev.open:
                    latest_bearish = OrderBlockZone(
                        direction="sell",
                        low=min(prev.open, prev.close),
                        high=max(prev.open, prev.close),
                        source_index=index - 1,
                    )
                if displacement and candle.close > candle.open and prev.close < prev.open:
                    latest_bullish = OrderBlockZone(
                        direction="buy",
                        low=min(prev.open, prev.close),
                        high=max(prev.open, prev.close),
                        source_index=index - 1,
                    )
            bearish[index] = latest_bearish
            bullish[index] = latest_bullish
        return bearish, bullish

    @staticmethod
    def _lower_tf_confirmation_ok(
        *,
        index: int,
        entry_candles: list[Candle],
        lower_candles: list[Candle],
        lower_ranges: list[tuple[int, int]],
        direction: str,
    ) -> bool:
        if index >= len(lower_ranges):
            return False
        start_index, end_index = lower_ranges[index]
        window = lower_candles[start_index:end_index]
        if not window:
            return False
        aligned_hits = 0
        for candle in window:
            candle_range = max(candle.high - candle.low, 1e-9)
            body = abs(candle.close - candle.open)
            body_ratio = body / candle_range
            if direction == "buy":
                supportive = candle.close > candle.open and (
                    (candle.high - candle.close) <= candle_range * 0.35
                    or MaximoBRProBacktester._lower_wick(candle) >= body * 0.30
                )
            else:
                supportive = candle.close < candle.open and (
                    (candle.close - candle.low) <= candle_range * 0.35
                    or MaximoBRProBacktester._upper_wick(candle) >= body * 0.30
                )
            if supportive and body_ratio >= 0.45:
                aligned_hits += 1
            if aligned_hits >= 1:
                return True
        return False

    @staticmethod
    def _trigger_candle_ok(candle: Candle, direction: str) -> bool:
        candle_range = max(candle.high - candle.low, 1e-9)
        body = abs(candle.close - candle.open)
        if direction == "buy":
            return candle.close > candle.open and (
                body / candle_range >= 0.45
                or MaximoBRProBacktester._lower_wick(candle) >= body * 0.30
            )
        return candle.close < candle.open and (
            body / candle_range >= 0.45
            or MaximoBRProBacktester._upper_wick(candle) >= body * 0.30
        )

    @staticmethod
    def _mtf_context_ok(
        *,
        index: int,
        direction: str,
        level: float,
        entry_candle: Candle,
        atr_value: float,
        m15_map: list[int | None],
        m30_map: list[int | None],
        m15_context: list[Candle],
        m30_context: list[Candle],
        m30_ema20: list[float | None],
        m30_ema40: list[float | None],
        m30_atr: list[float | None],
        m30_supports: list[float | None],
        m30_resistances: list[float | None],
        bearish_obs: list[OrderBlockZone | None],
        bullish_obs: list[OrderBlockZone | None],
        strict: bool,
    ) -> bool:
        if index >= len(m15_map) or index >= len(m30_map):
            return False
        m15_index = m15_map[index]
        m30_index = m30_map[index]
        if m15_index is None or m30_index is None:
            return False
        if m15_index >= len(m15_context) or m30_index >= len(m30_context):
            return False
        m30_candle = m30_context[m30_index]
        ema20 = m30_ema20[m30_index] if m30_index < len(m30_ema20) else None
        ema40 = m30_ema40[m30_index] if m30_index < len(m30_ema40) else None
        m30_atr_value = m30_atr[m30_index] if m30_index < len(m30_atr) else None
        if None in {ema20, ema40, m30_atr_value}:
            return False

        if direction == "buy":
            bias_ok = m30_candle.close > ema20 > ema40
            liquidity_level = m30_resistances[m30_index] if m30_index < len(m30_resistances) else None
            zone = bullish_obs[m15_index] if m15_index < len(bullish_obs) else None
        else:
            bias_ok = m30_candle.close < ema20 < ema40
            liquidity_level = m30_supports[m30_index] if m30_index < len(m30_supports) else None
            zone = bearish_obs[m15_index] if m15_index < len(bearish_obs) else None
        if not bias_ok or liquidity_level is None or zone is None:
            return False

        liquidity_ok = abs(level - liquidity_level) <= max(atr_value * 0.9, (m30_atr_value or 0.0) * 0.8)
        zone_buffer = atr_value * 0.18
        zone_touch = entry_candle.high >= zone.low - zone_buffer and entry_candle.low <= zone.high + zone_buffer
        return (liquidity_ok and zone_touch) if strict else (liquidity_ok or zone_touch)

    @staticmethod
    def _confirmed_pivots(
        highs: list[float],
        lows: list[float],
        pivot_len: int,
    ) -> tuple[list[float | None], list[float | None]]:
        supports: list[float | None] = [None] * len(highs)
        resistances: list[float | None] = [None] * len(highs)
        latest_support: float | None = None
        latest_resistance: float | None = None
        for index in range(len(highs)):
            candidate_index = index - pivot_len
            if candidate_index >= pivot_len and candidate_index + pivot_len < len(highs):
                high_value = highs[candidate_index]
                low_value = lows[candidate_index]
                left_highs = highs[candidate_index - pivot_len : candidate_index]
                right_highs = highs[candidate_index + 1 : candidate_index + pivot_len + 1]
                left_lows = lows[candidate_index - pivot_len : candidate_index]
                right_lows = lows[candidate_index + 1 : candidate_index + pivot_len + 1]
                if left_highs and right_highs and high_value > max(left_highs) and high_value >= max(right_highs):
                    latest_resistance = high_value
                if left_lows and right_lows and low_value < min(left_lows) and low_value <= min(right_lows):
                    latest_support = low_value
            supports[index] = latest_support
            resistances[index] = latest_resistance
        return supports, resistances

    @staticmethod
    def _split_metrics(trades: list[TradeResult]) -> dict:
        if not trades:
            empty = MaximoBRProBacktester._metrics([])
            return {"in_sample": empty, "out_of_sample": empty}
        cutoff = max(1, int(len(trades) * 0.7))
        return {
            "in_sample": MaximoBRProBacktester._metrics(trades[:cutoff]),
            "out_of_sample": MaximoBRProBacktester._metrics(trades[cutoff:]),
        }

    @staticmethod
    def _metrics(trades: list[TradeResult]) -> dict:
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "net_profit_r": 0.0,
                "max_drawdown_r": 0.0,
                "average_r": 0.0,
                "expectancy_r": 0.0,
                "losing_streak": 0,
            }
        wins = [trade for trade in trades if trade.pnl_r > 0]
        losses = [trade for trade in trades if trade.pnl_r < 0]
        gross_profit = sum(trade.pnl_r for trade in wins)
        gross_loss = abs(sum(trade.pnl_r for trade in losses))
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        current_losing = 0
        worst_losing = 0
        for trade in trades:
            equity += trade.pnl_r
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            if trade.pnl_r < 0:
                current_losing += 1
                worst_losing = max(worst_losing, current_losing)
            else:
                current_losing = 0
        net_profit = sum(trade.pnl_r for trade in trades)
        return {
            "total_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100.0, 2),
            "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4),
            "net_profit_r": round(net_profit, 4),
            "max_drawdown_r": round(max_drawdown, 4),
            "average_r": round(net_profit / len(trades), 4),
            "expectancy_r": round(net_profit / len(trades), 4),
            "losing_streak": worst_losing,
        }

    @staticmethod
    def _monthly_distribution(trades: list[TradeResult]) -> list[dict]:
        by_month: dict[str, list[TradeResult]] = {}
        for trade in trades:
            by_month.setdefault(trade.month, []).append(trade)
        rows: list[dict] = []
        for month in sorted(by_month):
            month_trades = by_month[month]
            metrics = MaximoBRProBacktester._metrics(month_trades)
            rows.append(
                {
                    "month": month,
                    "trades": metrics["total_trades"],
                    "win_rate": metrics["win_rate"],
                    "profit_factor": metrics["profit_factor"],
                    "net_profit_r": metrics["net_profit_r"],
                    "expectancy_r": metrics["expectancy_r"],
                    "max_drawdown_r": metrics["max_drawdown_r"],
                    "losing_streak": metrics["losing_streak"],
                }
            )
        return rows

    @staticmethod
    def _session_bucket_edge(trades: list[TradeResult], *, best: bool) -> dict | None:
        if not trades:
            return None
        grouped: dict[str, list[TradeResult]] = {}
        for trade in trades:
            grouped.setdefault(trade.session_bucket, []).append(trade)
        rows = []
        for bucket, bucket_trades in grouped.items():
            metrics = MaximoBRProBacktester._metrics(bucket_trades)
            rows.append(
                {
                    "bucket": bucket,
                    "trades": metrics["total_trades"],
                    "win_rate": metrics["win_rate"],
                    "profit_factor": metrics["profit_factor"],
                    "expectancy_r": metrics["expectancy_r"],
                }
            )
        key_fn = lambda item: (item["profit_factor"], item["expectancy_r"], item["trades"])
        return max(rows, key=key_fn) if best else min(rows, key=key_fn)

    def _write_summary_csv(self, runs: list[dict]) -> None:
        fields = [
            "dataset_label",
            "timeframe",
            "strategy_profile",
            "session_variant",
            "execution_mode",
            "slippage_scenario",
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
                            "strategy_profile": result["strategy_profile"],
                            "session_variant": result["session_variant"],
                            "execution_mode": result["execution_mode"],
                            "slippage_scenario": result["slippage_scenario"],
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
            "# MAXIMO B&R PRO v2.0 1.3R",
            "",
            f"- symbol_requested: {payload['symbol_requested']}",
            f"- symbol_used: {payload['symbol_used']}",
            f"- generated_at: {payload['generated_at']}",
            "",
            "## Assumptions",
        ]
        for key, value in payload["assumptions"].items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Coverage Notes"])
        for note in payload["coverage_notes"]:
            lines.append(f"- {note}")
        lines.extend(["", "## Conservative Focus (Scenario C + next_open)"])
        for item in payload["conservative_focus"]:
            lines.append(f"### {item['dataset_label']} | {item['timeframe']}")
            lines.append(f"- coverage_sufficient: {item['coverage_sufficient']}")
            best = item["best_conservative"]
            if not best:
                lines.append("- no conservative result")
                continue
            lines.append(f"- strategy_profile: {best['strategy_profile']} ({best['strategy_profile_label']})")
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
        best_run = payload["viability_decision"].get("best_run")
        if best_run:
            lines.append(f"- best_dataset: {best_run['dataset_label']}")
            lines.append(f"- best_timeframe: {best_run['timeframe']}")
        return "\n".join(lines) + "\n"
