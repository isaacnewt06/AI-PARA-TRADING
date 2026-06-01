"""Controlled quantitative optimizer for MAXIMO MTF Quant Institutional v4."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.logging import get_logger
from src.trading.maximo_quant_v4_backtester import (
    ClosedTrade,
    MaximoMTFQuantV4Backtester,
    StrategyVariant,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class OptimizationCandidate:
    family: str
    code: str
    label: str
    phase: str
    session_variant: str = "all"
    timeframe: str = "M5"
    require_preferred_side: bool = True
    allowed_directions: set[str] | None = None
    allowed_setup_types: set[str] | None = None
    allowed_hours_ny: set[int] | None = None
    excluded_hours_ny: set[int] | None = None
    disallow_chop: bool = False
    disallow_normal_hours_ny: set[int] | None = None
    require_quant_expansion: bool = False
    require_recent_compression: bool = False
    min_quant_score_variant: int = 58
    min_impulse_score_variant: int = 55
    min_quant_score_agg: int = 58
    min_impulse_score_agg: int = 55
    min_confidence_agg: int = 60
    min_atr_ratio: float | None = 0.85
    min_range_ratio: float | None = 0.85
    max_atr_ratio: float | None = None
    max_range_ratio: float | None = 1.95
    max_risk_atr: float = 1.30
    rr_agg: float = 1.15
    rr_a_plus: float = 1.45
    cooldown_bars: int = 20
    pause_after_loss: int = 8
    pause_after_two_losses: int = 18


class MaximoQuantV4Optimizer:
    """Stage-based optimizer focused on stable improvements over volatility_balanced_v53."""

    def __init__(self, *, input_dir: Path, backtests_dir: Path, strategies_dir: Path) -> None:
        self.input_dir = input_dir
        self.backtests_dir = backtests_dir
        self.strategies_dir = strategies_dir
        self.output_dir = backtests_dir / "yearly"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.strategies_dir.mkdir(parents=True, exist_ok=True)
        self.backtester = MaximoMTFQuantV4Backtester(
            input_dir=input_dir,
            output_dir=backtests_dir / "maximo_mtf_quant_v4",
        )

    def run(self, symbol: str = "XAUUSDm") -> dict:
        resolved_symbol = symbol if symbol.endswith("m") else f"{symbol}m"
        family_2025 = self.backtester._load_year_family(resolved_symbol, 2025)
        family_2024 = self.backtester._load_year_family(resolved_symbol, 2024)
        baseline = self._baseline_candidate()

        baseline_eval = self._evaluate_candidate(baseline, resolved_symbol, family_2025, family_2024)

        phase1 = self._evaluate_many(self._phase1_candidates(), resolved_symbol, family_2025, family_2024)
        phase1_best = self._best_balanced(phase1) or baseline_eval

        phase2 = self._evaluate_many(self._phase2_candidates(phase1_best["config"]), resolved_symbol, family_2025, family_2024)
        phase2_best = self._best_balanced(phase2) or phase1_best

        phase3 = self._evaluate_many(self._phase3_candidates(phase2_best["config"]), resolved_symbol, family_2025, family_2024)
        phase3_best = self._best_balanced(phase3) or phase2_best

        phase4 = self._evaluate_many(self._phase4_candidates(phase3_best["config"]), resolved_symbol, family_2025, family_2024)
        phase4_best = self._best_balanced(phase4) or phase3_best

        all_candidates = [baseline_eval, *phase1, *phase2, *phase3, *phase4]
        all_candidates.sort(key=lambda item: item["score"], reverse=True)

        top_for_deep = all_candidates[:5]
        for candidate in top_for_deep:
            candidate["deep_analysis"] = self._deep_analysis(candidate["config"], resolved_symbol, family_2025)

        ranking = self._rankings(all_candidates)
        recommendation = self._recommendation(ranking["balanced"], family_2024)

        payload = {
            "strategy_name": "MAXIMO MTF Quant Institutional v4",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": resolved_symbol,
            "baseline": baseline_eval,
            "phase_1": phase1,
            "phase_2": phase2,
            "phase_3": phase3,
            "phase_4": phase4,
            "all_candidates": all_candidates,
            "ranking": ranking,
            "recommendation": recommendation,
        }

        results_path = self.output_dir / "optimization_annual_results.json"
        report_path = self.output_dir / "optimization_annual_report.md"
        top_csv_path = self.output_dir / "top_annual_candidates.csv"
        comparison_path = self.output_dir / "comparison_2024_2025.md"

        results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path.write_text(self._report_markdown(payload), encoding="utf-8")
        self._write_top_candidates_csv(top_csv_path, all_candidates)
        comparison_path.write_text(self._comparison_markdown(payload), encoding="utf-8")

        return {
            "strategy_name": payload["strategy_name"],
            "symbol": resolved_symbol,
            "baseline": {
                "variant": baseline_eval["config"]["code"],
                "profit_factor": baseline_eval["annual_2025"]["metrics"]["profit_factor"],
                "trades": baseline_eval["annual_2025"]["metrics"]["total_trades"],
                "drawdown": baseline_eval["annual_2025"]["metrics"]["max_drawdown_r"],
            },
            "best_balanced": {
                "variant": ranking["balanced"]["config"]["code"],
                "profit_factor": ranking["balanced"]["annual_2025"]["metrics"]["profit_factor"],
                "trades": ranking["balanced"]["annual_2025"]["metrics"]["total_trades"],
                "drawdown": ranking["balanced"]["annual_2025"]["metrics"]["max_drawdown_r"],
            },
            "recommendation": recommendation,
            "results_path": str(results_path.resolve()),
            "report_path": str(report_path.resolve()),
            "top_csv_path": str(top_csv_path.resolve()),
            "comparison_path": str(comparison_path.resolve()),
        }

    def _baseline_candidate(self) -> OptimizationCandidate:
        return OptimizationCandidate(
            family="baseline_reference",
            code="v53_baseline_reference",
            label="volatility_balanced_v53 reference",
            phase="baseline",
            session_variant="all",
            allowed_hours_ny={1, 4, 5, 9, 15, 19},
            min_quant_score_variant=58,
            min_impulse_score_variant=55,
            min_quant_score_agg=58,
            min_impulse_score_agg=55,
            min_confidence_agg=60,
            min_atr_ratio=0.85,
            min_range_ratio=0.85,
            max_range_ratio=1.95,
            max_risk_atr=1.30,
            rr_agg=1.15,
            rr_a_plus=1.45,
            cooldown_bars=20,
            pause_after_loss=8,
            pause_after_two_losses=18,
        )

    def _phase1_candidates(self) -> list[OptimizationCandidate]:
        return [
            OptimizationCandidate(
                family="v54_conservative",
                code="v54_conservative_a",
                label="Conservative volatility tighter cap",
                phase="phase_1_volatility",
                allowed_hours_ny={1, 4, 5, 9, 15, 19},
                min_quant_score_variant=60,
                min_impulse_score_variant=58,
                min_quant_score_agg=60,
                min_impulse_score_agg=58,
                min_confidence_agg=62,
                require_quant_expansion=True,
                min_atr_ratio=0.90,
                min_range_ratio=0.90,
                max_range_ratio=1.75,
                max_risk_atr=1.10,
            ),
            OptimizationCandidate(
                family="v54_conservative",
                code="v54_conservative_b",
                label="Conservative volatility balanced cap",
                phase="phase_1_volatility",
                allowed_hours_ny={1, 4, 5, 9, 15, 19},
                min_quant_score_variant=60,
                min_impulse_score_variant=58,
                min_quant_score_agg=60,
                min_impulse_score_agg=58,
                min_confidence_agg=62,
                require_quant_expansion=True,
                min_atr_ratio=0.85,
                min_range_ratio=0.90,
                max_range_ratio=1.95,
                max_risk_atr=1.20,
            ),
            OptimizationCandidate(
                family="v55_balanced_plus",
                code="v55_balanced_plus_a",
                label="Balanced plus baseline-like",
                phase="phase_1_volatility",
                allowed_hours_ny={1, 4, 5, 9, 15, 19},
                min_quant_score_variant=58,
                min_impulse_score_variant=55,
                min_quant_score_agg=58,
                min_impulse_score_agg=55,
                min_confidence_agg=60,
                min_atr_ratio=0.85,
                min_range_ratio=0.85,
                max_range_ratio=1.95,
                max_risk_atr=1.20,
            ),
            OptimizationCandidate(
                family="v55_balanced_plus",
                code="v55_balanced_plus_b",
                label="Balanced plus more quality",
                phase="phase_1_volatility",
                allowed_hours_ny={1, 4, 5, 9, 15, 19},
                min_quant_score_variant=58,
                min_impulse_score_variant=55,
                min_quant_score_agg=60,
                min_impulse_score_agg=58,
                min_confidence_agg=62,
                min_atr_ratio=0.85,
                min_range_ratio=0.85,
                max_range_ratio=1.95,
                max_risk_atr=1.20,
            ),
            OptimizationCandidate(
                family="v56_aggressive_filtered",
                code="v56_aggressive_filtered_a",
                label="Aggressive filtered wider cap",
                phase="phase_1_volatility",
                allowed_hours_ny={1, 4, 5, 9, 15, 19},
                min_quant_score_variant=58,
                min_impulse_score_variant=55,
                min_quant_score_agg=58,
                min_impulse_score_agg=55,
                min_confidence_agg=60,
                require_quant_expansion=True,
                min_atr_ratio=0.80,
                min_range_ratio=0.80,
                max_range_ratio=2.20,
                max_risk_atr=1.45,
            ),
            OptimizationCandidate(
                family="v56_aggressive_filtered",
                code="v56_aggressive_filtered_b",
                label="Aggressive filtered tighter ATR risk",
                phase="phase_1_volatility",
                allowed_hours_ny={1, 4, 5, 9, 15, 19},
                min_quant_score_variant=58,
                min_impulse_score_variant=55,
                min_quant_score_agg=58,
                min_impulse_score_agg=55,
                min_confidence_agg=60,
                require_quant_expansion=True,
                min_atr_ratio=0.80,
                min_range_ratio=0.85,
                max_range_ratio=2.20,
                max_risk_atr=1.30,
            ),
        ]

    def _phase2_candidates(self, seed: dict[str, Any]) -> list[OptimizationCandidate]:
        base = self._candidate_from_dict(seed)
        hour_sets = [
            ("v57_session_adaptive_a", {1, 4, 5, 9, 15, 19}),
            ("v57_session_adaptive_b", {1, 4, 5, 8, 9, 15, 19}),
            ("v57_session_adaptive_c", {4, 5, 9, 15, 19}),
            ("v57_session_adaptive_d", {1, 5, 9, 15, 19}),
            ("v57_session_adaptive_e", {1, 4, 5, 9, 10, 15, 19}),
        ]
        return [
            OptimizationCandidate(
                **{**asdict(base), "family": "v57_session_adaptive", "code": code, "label": f"Session adaptive {index + 1}", "phase": "phase_2_hours", "allowed_hours_ny": hours}
            )
            for index, (code, hours) in enumerate(hour_sets)
        ]

    def _phase3_candidates(self, seed: dict[str, Any]) -> list[OptimizationCandidate]:
        base = self._candidate_from_dict(seed)
        rr_profiles = [
            ("v58_rr_adaptive_a", 1.05, 1.35),
            ("v58_rr_adaptive_b", 1.10, 1.45),
            ("v58_rr_adaptive_c", 1.15, 1.45),
            ("v58_rr_adaptive_d", 1.20, 1.55),
        ]
        return [
            OptimizationCandidate(
                **{**asdict(base), "family": "v58_rr_adaptive", "code": code, "label": f"RR adaptive {index + 1}", "phase": "phase_3_rr", "rr_agg": rr_agg, "rr_a_plus": rr_a}
            )
            for index, (code, rr_agg, rr_a) in enumerate(rr_profiles)
        ]

    def _phase4_candidates(self, seed: dict[str, Any]) -> list[OptimizationCandidate]:
        base = self._candidate_from_dict(seed)
        management = [
            ("v58_rr_adaptive_m1", 15, 6),
            ("v58_rr_adaptive_m2", 20, 8),
            ("v58_rr_adaptive_m3", 25, 10),
            ("v58_rr_adaptive_m4", 30, 12),
        ]
        return [
            OptimizationCandidate(
                **{
                    **asdict(base),
                    "family": "v58_rr_adaptive",
                    "code": code,
                    "label": f"RR adaptive management {index + 1}",
                    "phase": "phase_4_management",
                    "cooldown_bars": cooldown,
                    "pause_after_loss": pause,
                    "pause_after_two_losses": max(pause + 8, pause * 2),
                }
            )
            for index, (code, cooldown, pause) in enumerate(management)
        ]

    def _evaluate_many(
        self,
        candidates: list[OptimizationCandidate],
        symbol: str,
        family_2025: dict[str, list[Any]],
        family_2024: dict[str, list[Any]],
    ) -> list[dict]:
        return [self._evaluate_candidate(candidate, symbol, family_2025, family_2024) for candidate in candidates]

    def _evaluate_candidate(
        self,
        candidate: OptimizationCandidate,
        symbol: str,
        family_2025: dict[str, list[Any]],
        family_2024: dict[str, list[Any]],
    ) -> dict:
        annual_2025 = self._simulate_period(candidate, symbol, family_2025, "annual_2025", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc))
        in_sample_2025 = self._simulate_period(candidate, symbol, family_2025, "in_sample_2025", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 8, 31, 23, 59, tzinfo=timezone.utc))
        out_of_sample_2025 = self._simulate_period(candidate, symbol, family_2025, "out_of_sample_2025", datetime(2025, 9, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc))
        annual_2024 = self._simulate_period(candidate, symbol, family_2024, "annual_2024", datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc))

        combined_trades = [*annual_2025["trades"]]
        if annual_2024["coverage"]["sufficient"]:
            combined_trades.extend(annual_2024["trades"])
        combined = self._metrics_package(combined_trades)

        hourly = self._breakdown_by_hour(annual_2025["trades"])
        setup_breakdown = self._breakdown_by_attr(annual_2025["trades"], "setup_type")
        regime_breakdown = self._breakdown_by_attr(annual_2025["trades"], "market_regime")
        direction_breakdown = self._breakdown_by_attr(annual_2025["trades"], "direction")
        monthly = self.backtester._monthly_distribution(annual_2025["trades"])

        acceptance = self._acceptance(
            annual_2025=annual_2025["metrics"],
            in_sample_2025=in_sample_2025["metrics"],
            out_of_sample_2025=out_of_sample_2025["metrics"],
            combined=combined,
            hourly=hourly,
            monthly=monthly,
            coverage_2024=annual_2024["coverage"],
        )
        score = self._score(
            annual_2025=annual_2025["metrics"],
            out_of_sample_2025=out_of_sample_2025["metrics"],
            combined=combined,
            acceptance=acceptance,
            hourly=hourly,
        )

        return {
            "config": self._serialize_candidate(candidate),
            "annual_2025": {"metrics": annual_2025["metrics"], "coverage": annual_2025["coverage"]},
            "in_sample_2025": {"metrics": in_sample_2025["metrics"], "coverage": in_sample_2025["coverage"]},
            "out_of_sample_2025": {"metrics": out_of_sample_2025["metrics"], "coverage": out_of_sample_2025["coverage"]},
            "annual_2024": {"metrics": annual_2024["metrics"], "coverage": annual_2024["coverage"]},
            "combined": combined,
            "hourly": hourly,
            "setup_breakdown": setup_breakdown,
            "regime_breakdown": regime_breakdown,
            "direction_breakdown": direction_breakdown,
            "monthly_distribution": monthly,
            "acceptance": acceptance,
            "score": score,
        }

    def _simulate_period(
        self,
        candidate: OptimizationCandidate,
        symbol: str,
        family: dict[str, list[Any]],
        label: str,
        start: datetime,
        end: datetime,
    ) -> dict:
        empty_coverage = {
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "entry_rows": 0,
            "htf_rows": 0,
            "coverage_ratio": 0.0,
            "sufficient": False,
            "timeframe": candidate.timeframe,
        }
        if not family or "M5" not in family or "H1" not in family:
            return {"trades": [], "metrics": self.backtester._metrics([]), "coverage": empty_coverage}

        specs = self.backtester._build_period_specs("optimizer", family, [(label, start, end)])
        spec = next((item for item in specs if item["timeframe"] == candidate.timeframe), None)
        if spec is None:
            return {"trades": [], "metrics": self.backtester._metrics([]), "coverage": empty_coverage}

        bt = MaximoMTFQuantV4Backtester(
            input_dir=self.input_dir,
            output_dir=self.backtests_dir / "maximo_mtf_quant_v4",
        )
        bt.MIN_QUANT_AGG = candidate.min_quant_score_agg
        bt.MIN_IMPULSE_AGG = candidate.min_impulse_score_agg
        bt.MIN_CONF_AGG = candidate.min_confidence_agg
        bt.MAX_RISK_ATR = candidate.max_risk_atr
        bt.RR_AGG = candidate.rr_agg
        bt.RR_A = candidate.rr_a_plus
        bt.COOLDOWN_BARS = candidate.cooldown_bars
        bt.PAUSE_AFTER_LOSS = candidate.pause_after_loss
        bt.PAUSE_AFTER_TWO_LOSSES = candidate.pause_after_two_losses

        variant = StrategyVariant(
            code=candidate.code,
            label=candidate.label,
            require_preferred_side=candidate.require_preferred_side,
            allowed_directions=set(candidate.allowed_directions) if candidate.allowed_directions else None,
            allowed_setup_types=set(candidate.allowed_setup_types) if candidate.allowed_setup_types else None,
            allowed_hours_ny=set(candidate.allowed_hours_ny) if candidate.allowed_hours_ny else None,
            excluded_hours_ny=set(candidate.excluded_hours_ny) if candidate.excluded_hours_ny else None,
            disallow_chop=candidate.disallow_chop,
            disallow_normal_hours_ny=set(candidate.disallow_normal_hours_ny) if candidate.disallow_normal_hours_ny else None,
            min_quant_score=candidate.min_quant_score_variant,
            min_impulse_score=candidate.min_impulse_score_variant,
            require_quant_expansion=candidate.require_quant_expansion,
            require_recent_compression=candidate.require_recent_compression,
            min_atr_ratio=candidate.min_atr_ratio,
            min_range_ratio=candidate.min_range_ratio,
            max_atr_ratio=candidate.max_atr_ratio,
            max_range_ratio=candidate.max_range_ratio,
        )
        session = next(item for item in bt.SESSION_VARIANTS if item.code == candidate.session_variant)
        trades = bt._simulate(
            symbol=symbol,
            dataset_label=spec["label"],
            timeframe=candidate.timeframe,
            entry_candles=spec["entry_candles"],
            context=spec["context"],
            session_variant=session,
            strategy_variant=variant,
        )
        return {"trades": trades, "metrics": bt._metrics(trades), "coverage": spec["coverage"]}

    def _deep_analysis(self, config_dict: dict[str, Any], symbol: str, family_2025: dict[str, list[Any]]) -> dict:
        config = self._candidate_from_dict(config_dict)
        buy_only = self._candidate_from_dict({**self._serialize_candidate(config), "code": f"{config.code}_buy_only", "allowed_directions": ["buy"]})
        sell_only = self._candidate_from_dict({**self._serialize_candidate(config), "code": f"{config.code}_sell_only", "allowed_directions": ["sell"]})
        a_plus_only = self._candidate_from_dict({**self._serialize_candidate(config), "code": f"{config.code}_aplus_only", "allowed_setup_types": ["A+"]})
        agg_only = self._candidate_from_dict({**self._serialize_candidate(config), "code": f"{config.code}_agg_only", "allowed_setup_types": ["AGG"]})

        # Direction/setup filtering uses the StrategyVariant gates.
        analyses = {
            "both": self._simulate_period(config, symbol, family_2025, "deep_full", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc))["metrics"],
            "buy_only": self._simulate_period(buy_only, symbol, family_2025, "buy_only", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc))["metrics"],
            "sell_only": self._simulate_period(sell_only, symbol, family_2025, "sell_only", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc))["metrics"],
            "a_plus_only": self._simulate_period(a_plus_only, symbol, family_2025, "a_plus_only", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc))["metrics"],
            "agg_only": self._simulate_period(agg_only, symbol, family_2025, "agg_only", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc))["metrics"],
        }
        return analyses

    def _breakdown_by_hour(self, trades: list[ClosedTrade]) -> list[dict]:
        rows = []
        for hour in sorted({trade.hour_ny for trade in trades}):
            subset = [trade for trade in trades if trade.hour_ny == hour]
            metrics = self.backtester._metrics(subset)
            rows.append({"hour_ny": hour, **metrics})
        return rows

    def _breakdown_by_attr(self, trades: list[ClosedTrade], attr: str) -> list[dict]:
        values = sorted({getattr(trade, attr) for trade in trades})
        rows = []
        for value in values:
            subset = [trade for trade in trades if getattr(trade, attr) == value]
            metrics = self.backtester._metrics(subset)
            rows.append({attr: value, **metrics})
        return rows

    def _metrics_package(self, trades: list[ClosedTrade]) -> dict:
        metrics = self.backtester._metrics(trades)
        metrics["average_r"] = metrics["expectancy_r"]
        metrics["total_trades"] = metrics["total_trades"]
        return metrics

    def _acceptance(
        self,
        *,
        annual_2025: dict,
        in_sample_2025: dict,
        out_of_sample_2025: dict,
        combined: dict,
        hourly: list[dict],
        monthly: list[dict],
        coverage_2024: dict,
    ) -> dict:
        reasons: list[str] = []
        if annual_2025["total_trades"] < 40:
            reasons.append("less_than_40_trades_2025")
        if out_of_sample_2025["profit_factor"] < 1.3:
            reasons.append("oos_profit_factor_below_1_3")
        if annual_2025["max_drawdown_r"] > 6:
            reasons.append("drawdown_above_6")
        if in_sample_2025["profit_factor"] > 1.3 and out_of_sample_2025["profit_factor"] < 1.0:
            reasons.append("possible_curve_fitting")
        if annual_2025["expectancy_r"] <= 0 or out_of_sample_2025["expectancy_r"] <= 0:
            reasons.append("non_positive_expectancy")
        dominant_share = 0.0
        if hourly and annual_2025["total_trades"]:
            dominant_share = max(row["total_trades"] for row in hourly) / annual_2025["total_trades"]
            if dominant_share > 0.45:
                reasons.append("depends_on_single_hour")
        negative_streak_months = self._max_consecutive_negative_months(monthly)
        if negative_streak_months > 2:
            reasons.append("too_many_consecutive_negative_months")
        accepted = not reasons
        status = "accepted" if accepted else "rejected"
        if not coverage_2024.get("sufficient", False):
            status = "needs_more_data" if accepted else status
            reasons.append("2024_coverage_insufficient")
        return {
            "status": status,
            "accepted": accepted and coverage_2024.get("sufficient", False),
            "reasons": sorted(set(reasons)),
            "dominant_hour_trade_share": round(dominant_share, 4),
            "consecutive_negative_months": negative_streak_months,
        }

    @staticmethod
    def _max_consecutive_negative_months(monthly: list[dict]) -> int:
        current = 0
        worst = 0
        for row in monthly:
            if row["net_profit_r"] < 0:
                current += 1
                worst = max(worst, current)
            else:
                current = 0
        return worst

    @staticmethod
    def _score(*, annual_2025: dict, out_of_sample_2025: dict, combined: dict, acceptance: dict, hourly: list[dict]) -> float:
        score = 0.0
        score += annual_2025["profit_factor"] * 3.5
        score += out_of_sample_2025["profit_factor"] * 4.5
        score += annual_2025["win_rate"] / 20.0
        score += min(annual_2025["total_trades"], 120) / 30.0
        score += combined["expectancy_r"] * 2.0
        score -= annual_2025["max_drawdown_r"] * 0.8
        score -= max(0, acceptance["dominant_hour_trade_share"] - 0.35) * 8.0
        if "2024_coverage_insufficient" in acceptance["reasons"]:
            score -= 0.5
        if acceptance["status"] == "accepted":
            score += 2.0
        if "possible_curve_fitting" in acceptance["reasons"]:
            score -= 3.0
        if out_of_sample_2025["profit_factor"] < 1.0:
            score -= 4.0
        return round(score, 6)

    @staticmethod
    def _best_balanced(candidates: list[dict]) -> dict | None:
        if not candidates:
            return None
        accepted = [item for item in candidates if item["acceptance"]["status"] in {"accepted", "needs_more_data"}]
        pool = accepted or candidates
        return max(pool, key=lambda item: item["score"])

    def _rankings(self, candidates: list[dict]) -> dict:
        by_pf = max(candidates, key=lambda item: (item["annual_2025"]["metrics"]["profit_factor"], item["annual_2025"]["metrics"]["total_trades"]))
        by_net = max(candidates, key=lambda item: item["annual_2025"]["metrics"]["net_profit_r"])
        by_low_dd = min(candidates, key=lambda item: (item["annual_2025"]["metrics"]["max_drawdown_r"], -item["annual_2025"]["metrics"]["profit_factor"]))
        balanced = self._best_balanced(candidates)
        return {
            "by_profit_factor": by_pf,
            "by_net_profit": by_net,
            "by_low_drawdown": by_low_dd,
            "balanced": balanced,
        }

    @staticmethod
    def _recommendation(best_balanced: dict, family_2024: dict[str, list[Any]]) -> dict:
        if best_balanced["acceptance"]["accepted"]:
            return {"status": "READY_FOR_PAPER_TRADING", "reason": "Candidate passed all acceptance checks including 2024 coverage."}
        if not family_2024 or "M5" not in family_2024:
            return {"status": "NEEDS_MORE_DATA", "reason": "2024 M5 coverage is insufficient for robust multi-year approval."}
        if "2024_coverage_insufficient" in best_balanced["acceptance"]["reasons"]:
            return {"status": "NEEDS_MORE_DATA", "reason": "2024 coverage exists but is insufficient for reliable validation."}
        return {"status": "NOT_ROBUST", "reason": "Best balanced candidate still fails one or more stability criteria."}

    def _write_top_candidates_csv(self, path: Path, candidates: list[dict]) -> None:
        rows = []
        for item in candidates:
            rows.append(
                {
                    "code": item["config"]["code"],
                    "family": item["config"]["family"],
                    "phase": item["config"]["phase"],
                    "trades_2025": item["annual_2025"]["metrics"]["total_trades"],
                    "win_rate_2025": item["annual_2025"]["metrics"]["win_rate"],
                    "profit_factor_2025": item["annual_2025"]["metrics"]["profit_factor"],
                    "net_profit_r_2025": item["annual_2025"]["metrics"]["net_profit_r"],
                    "drawdown_r_2025": item["annual_2025"]["metrics"]["max_drawdown_r"],
                    "oos_profit_factor_2025": item["out_of_sample_2025"]["metrics"]["profit_factor"],
                    "score": item["score"],
                    "status": item["acceptance"]["status"],
                }
            )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def _report_markdown(self, payload: dict) -> str:
        ranking = payload["ranking"]
        lines = [
            "# MAXIMO Quant v4 Annual Optimization",
            "",
            f"- symbol: {payload['symbol']}",
            f"- generated_at: {payload['generated_at']}",
            f"- recommendation: {payload['recommendation']['status']}",
            f"- reason: {payload['recommendation']['reason']}",
            "",
            "## Baseline",
            self._candidate_markdown(payload["baseline"]),
            "",
            "## Rankings",
            "### Best by Profit Factor",
            self._candidate_markdown(ranking["by_profit_factor"]),
            "",
            "### Best by Net Profit",
            self._candidate_markdown(ranking["by_net_profit"]),
            "",
            "### Best by Low Drawdown",
            self._candidate_markdown(ranking["by_low_drawdown"]),
            "",
            "### Best Balanced",
            self._candidate_markdown(ranking["balanced"]),
        ]
        deep = ranking["balanced"].get("deep_analysis")
        if deep:
            lines.extend(
                [
                    "",
                    "## Special Analysis",
                    f"- both: {deep['both']}",
                    f"- buy_only: {deep['buy_only']}",
                    f"- sell_only: {deep['sell_only']}",
                    f"- a_plus_only: {deep['a_plus_only']}",
                    f"- agg_only: {deep['agg_only']}",
                ]
            )
        return "\n".join(lines) + "\n"

    def _comparison_markdown(self, payload: dict) -> str:
        baseline = payload["baseline"]
        best = payload["ranking"]["balanced"]
        lines = [
            "# 2024 vs 2025 Comparison",
            "",
            "## Baseline vs Best Balanced",
            f"- baseline: {baseline['config']['code']} | 2025 PF {baseline['annual_2025']['metrics']['profit_factor']} | trades {baseline['annual_2025']['metrics']['total_trades']}",
            f"- best_balanced: {best['config']['code']} | 2025 PF {best['annual_2025']['metrics']['profit_factor']} | trades {best['annual_2025']['metrics']['total_trades']}",
            "",
            "## 2024 Coverage",
            f"- baseline 2024 sufficient: {baseline['annual_2024']['coverage']['sufficient']}",
            f"- best 2024 sufficient: {best['annual_2024']['coverage']['sufficient']}",
            "",
            "## 2024 Metrics",
            f"- baseline 2024: {baseline['annual_2024']['metrics']}",
            f"- best 2024: {best['annual_2024']['metrics']}",
            "",
            "## 2025 Metrics",
            f"- baseline 2025: {baseline['annual_2025']['metrics']}",
            f"- best 2025: {best['annual_2025']['metrics']}",
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _candidate_markdown(candidate: dict) -> str:
        annual = candidate["annual_2025"]["metrics"]
        oos = candidate["out_of_sample_2025"]["metrics"]
        return (
            f"- code: {candidate['config']['code']}\n"
            f"- family: {candidate['config']['family']}\n"
            f"- trades_2025: {annual['total_trades']}\n"
            f"- win_rate_2025: {annual['win_rate']}%\n"
            f"- profit_factor_2025: {annual['profit_factor']}\n"
            f"- oos_profit_factor_2025: {oos['profit_factor']}\n"
            f"- net_profit_r_2025: {annual['net_profit_r']}\n"
            f"- max_drawdown_r_2025: {annual['max_drawdown_r']}\n"
            f"- status: {candidate['acceptance']['status']}\n"
            f"- reasons: {candidate['acceptance']['reasons']}"
        )

    @staticmethod
    def _candidate_from_dict(data: dict[str, Any]) -> OptimizationCandidate:
        cleaned = dict(data)
        for key in ("allowed_directions", "allowed_setup_types", "allowed_hours_ny", "excluded_hours_ny", "disallow_normal_hours_ny"):
            if cleaned.get(key) is not None:
                cleaned[key] = set(cleaned[key])
        return OptimizationCandidate(**cleaned)

    @staticmethod
    def _serialize_candidate(candidate: OptimizationCandidate) -> dict[str, Any]:
        data = asdict(candidate)
        for key, value in list(data.items()):
            if isinstance(value, set):
                data[key] = sorted(value)
        return data
