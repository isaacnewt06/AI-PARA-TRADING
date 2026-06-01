"""Annual optimization for OB Rejection Short Only Trailing ATR v3."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.core.config import Settings
from src.trading.approved_strategy_loader import load_ob_rejection_short_trailing_atr_v3
from src.trading.blueprint_backtester import BlueprintBacktester, Trade
from src.trading.yearly_backtester import RealizedTrade, YearlyBacktester


@dataclass(slots=True)
class AnnualOptimizationCandidate:
    candidate_name: str
    allowed_hours_utc: list[int]
    blocked_hours_utc: list[int]
    allowed_atr_bands: list[str]
    blocked_atr_bands: list[str]
    allowed_confirmation_bands: list[str]
    blocked_confirmation_bands: list[str]
    required_rejection_signals: list[str]
    blocked_rejection_signals: list[str]
    trail_atr_multiple: float
    break_even_trigger_r: float | None
    daily_max_losses: int | None
    daily_min_pnl_r: float | None
    cooldown_bars_after_loss: int | None
    max_trades_per_day: int | None
    max_range_atr_multiple: float
    relaxed_htf_bias: bool = False
    balanced_htf_bias: bool = False
    relaxed_order_block: bool = False
    balanced_order_block: bool = False
    confirmation_mode: str | None = None
    min_confirmation_signals: int | None = None
    recent_order_block_window: int | None = None
    stop_buffer_atr: float | None = None


class AnnualOBRejectionOptimizer:
    """Run disciplined annual optimization using 2024 and 2025 yearly datasets."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        backtests_root = self.settings.paths.data_dir / "backtests"
        self.input_dir = backtests_root / "input"
        self.yearly_dir = backtests_root / "yearly"
        self.yearly_dir.mkdir(parents=True, exist_ok=True)
        self.backtester = YearlyBacktester(
            input_dir=self.input_dir,
            yearly_dir=self.yearly_dir,
            strategies_dir=self.settings.paths.data_dir / "strategies",
        )
        self._candidate_cache: dict[str, dict] = {}

    def run(self, *, symbol: str = "XAUUSDm", initial_capital: float = 500.0) -> dict:
        base_spec = load_ob_rejection_short_trailing_atr_v3(self.settings, symbol)
        baseline = self._evaluate_candidate(
            symbol=symbol,
            initial_capital=initial_capital,
            candidate=self._baseline_candidate(base_spec),
            base_spec=base_spec,
        )
        candidates = [self._evaluate_candidate(symbol=symbol, initial_capital=initial_capital, candidate=item, base_spec=base_spec) for item in self._candidates()]
        ranked = sorted(candidates, key=lambda item: (-item["score"], item["candidate"]["candidate_name"]))
        best_candidate = ranked[0] if ranked else baseline
        best_2025_candidate = self._select_best_2025_candidate(candidates) or baseline
        decision = self._decision(baseline=baseline, best_candidate=best_candidate)

        results_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "initial_capital": initial_capital,
            "baseline": baseline,
            "best_candidate": best_candidate,
            "best_2025_candidate": best_2025_candidate,
            "target_income_analysis": self._safe_target_income_analysis(
                symbol=symbol,
                initial_capital=initial_capital,
                base_spec=base_spec,
                baseline_candidate=self._baseline_candidate(base_spec),
                best_2025_candidate=self._candidate_from_result(best_2025_candidate),
            ),
            "top_candidates": ranked[:10],
            "decision": decision,
        }
        results_path = self.yearly_dir / "optimization_annual_results.json"
        report_path = self.yearly_dir / "optimization_annual_report.md"
        csv_path = self.yearly_dir / "top_annual_candidates.csv"
        results_path.write_text(json.dumps(results_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path.write_text(self._report_markdown(results_payload), encoding="utf-8")
        self._write_candidates_csv(csv_path, ranked[:10])
        return {
            "symbol": symbol,
            "initial_capital": initial_capital,
            "decision": decision["status"],
            "reason": decision["reason"],
            "best_candidate": best_candidate["candidate"]["candidate_name"],
            "results_json": str(results_path.resolve()),
            "report_md": str(report_path.resolve()),
            "top_candidates_csv": str(csv_path.resolve()),
        }

    def _baseline_candidate(self, base_spec) -> AnnualOptimizationCandidate:
        overrides = base_spec.simulation_overrides or {}
        return AnnualOptimizationCandidate(
            candidate_name="baseline_v3",
            allowed_hours_utc=list(overrides.get("allowed_hours_utc", [])),
            blocked_hours_utc=list(overrides.get("blocked_hours_utc", [])),
            allowed_atr_bands=list(overrides.get("allowed_atr_bands", [])),
            blocked_atr_bands=list(overrides.get("blocked_atr_bands", [])),
            allowed_confirmation_bands=list(overrides.get("allowed_confirmation_bands", [])),
            blocked_confirmation_bands=list(overrides.get("blocked_confirmation_bands", [])),
            required_rejection_signals=list(overrides.get("required_rejection_signals", ["wick_rejection"])),
            blocked_rejection_signals=list(overrides.get("blocked_rejection_signals", [])),
            trail_atr_multiple=float(overrides.get("trail_atr_multiple") or 1.0),
            break_even_trigger_r=overrides.get("break_even_trigger_r"),
            daily_max_losses=overrides.get("daily_max_losses"),
            daily_min_pnl_r=overrides.get("daily_min_pnl_r"),
            cooldown_bars_after_loss=overrides.get("cooldown_bars_after_loss"),
            max_trades_per_day=overrides.get("max_trades_per_day"),
            max_range_atr_multiple=float(overrides.get("max_range_atr_multiple") or 2.0),
        )

    def _candidates(self) -> list[AnnualOptimizationCandidate]:
        blocked_base = [2, 3, 12, 16, 23]
        hours_negative_2025 = [1, 4, 8, 11, 17]
        return [
            AnnualOptimizationCandidate("hours_core", [10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_extended", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_negative_excluded", [], sorted(set(blocked_base + hours_negative_2025)), [], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("wick_clean", [], blocked_base, [], [], [], [], ["wick_rejection"], ["displacement_candle", "close_back_inside_structure"], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("wick_medium_large", [], blocked_base, [], [], ["medium_0.8_1.2_atr", "large_1.2_1.8_atr"], ["small_lt_0.8_atr"], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("atr_no_p4060", [], blocked_base, [], ["p40_60"], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("atr_core_bands", [], blocked_base, ["p20_40", "p60_80"], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("confirm_no_small_extreme", [], blocked_base, [], [], [], ["small_lt_0.8_atr", "extreme_gt_1.8_atr"], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("trail_08", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 0.8, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("trail_12", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.2, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("trail_15", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.5, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("trigger_08", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, 0.8, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("trigger_12", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, 1.2, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("guard_2_losses", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, 2, None, None, None, 2.0),
            AnnualOptimizationCandidate("guard_minus_2r", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, None, -2.0, None, None, 2.0),
            AnnualOptimizationCandidate("max_3_trades", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, 3, 2.0),
            AnnualOptimizationCandidate("cooldown_1", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, 1, None, 2.0),
            AnnualOptimizationCandidate("hours_extended_atr_medium", [8, 9, 10, 11, 13], blocked_base, [], ["p40_60"], ["medium_0.8_1.2_atr", "large_1.2_1.8_atr"], ["small_lt_0.8_atr"], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_core_wick_clean_trail12", [10, 11, 13], blocked_base, [], ["p40_60"], ["medium_0.8_1.2_atr", "large_1.2_1.8_atr"], ["small_lt_0.8_atr", "extreme_gt_1.8_atr"], ["wick_rejection"], ["displacement_candle", "close_back_inside_structure"], 1.2, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_extended_trigger08", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], ["displacement_candle"], 1.0, 0.8, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_extended_wick_clean", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], ["displacement_candle", "close_back_inside_structure"], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_extended_wick_clean_trail12", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], ["displacement_candle", "close_back_inside_structure"], 1.2, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_extended_wick_clean_be08", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], ["displacement_candle", "close_back_inside_structure"], 1.0, 0.8, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_extended_wick_clean_no_p4060", [8, 9, 10, 11, 13], blocked_base, [], ["p40_60"], [], [], ["wick_rejection"], ["displacement_candle", "close_back_inside_structure"], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_extended_wick_clean_no_small_extreme", [8, 9, 10, 11, 13], blocked_base, [], [], [], ["small_lt_0.8_atr", "extreme_gt_1.8_atr"], ["wick_rejection"], ["displacement_candle", "close_back_inside_structure"], 1.0, None, None, None, None, None, 2.0),
            AnnualOptimizationCandidate("hours_extended_wick_clean_range18", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], ["displacement_candle", "close_back_inside_structure"], 1.0, None, None, None, None, None, 1.8),
            AnnualOptimizationCandidate("canonical_relaxed_wick_core", [], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0, relaxed_htf_bias=True, relaxed_order_block=True, confirmation_mode="any_of_three", recent_order_block_window=20, stop_buffer_atr=0.10),
            AnnualOptimizationCandidate("canonical_relaxed_wick_hours_ext", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0, relaxed_htf_bias=True, relaxed_order_block=True, confirmation_mode="any_of_three", recent_order_block_window=20, stop_buffer_atr=0.10),
            AnnualOptimizationCandidate("canonical_relaxed_wick_no_small", [8, 9, 10, 11, 13], blocked_base, [], [], [], ["small_lt_0.8_atr"], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0, relaxed_htf_bias=True, relaxed_order_block=True, confirmation_mode="any_of_three", recent_order_block_window=20, stop_buffer_atr=0.10),
            AnnualOptimizationCandidate("canonical_relaxed_wick_rr12_trail12", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.2, None, None, None, None, None, 2.0, relaxed_htf_bias=True, relaxed_order_block=True, confirmation_mode="any_of_three", recent_order_block_window=20, stop_buffer_atr=0.10),
            AnnualOptimizationCandidate("canonical_balanced_wick_twoofthree", [8, 9, 10, 11, 13], blocked_base, [], ["p40_60"], ["medium_0.8_1.2_atr", "large_1.2_1.8_atr"], ["small_lt_0.8_atr"], ["wick_rejection"], [], 1.0, None, None, None, None, None, 2.0, balanced_htf_bias=True, balanced_order_block=True, confirmation_mode="two_of_three", min_confirmation_signals=2, recent_order_block_window=30, stop_buffer_atr=0.10),
            AnnualOptimizationCandidate("canonical_relaxed_wick_guard2", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, 2, None, None, None, 2.0, relaxed_htf_bias=True, relaxed_order_block=True, confirmation_mode="any_of_three", recent_order_block_window=20, stop_buffer_atr=0.10),
            AnnualOptimizationCandidate("canonical_relaxed_wick_max3", [8, 9, 10, 11, 13], blocked_base, [], [], [], [], ["wick_rejection"], [], 1.0, None, None, None, None, 3, 2.0, relaxed_htf_bias=True, relaxed_order_block=True, confirmation_mode="any_of_three", recent_order_block_window=20, stop_buffer_atr=0.10),
        ]

    def _candidate_from_result(self, result: dict) -> AnnualOptimizationCandidate:
        payload = dict(result.get("candidate", {}))
        payload.setdefault("allowed_hours_utc", [])
        payload.setdefault("blocked_hours_utc", [])
        payload.setdefault("allowed_atr_bands", [])
        payload.setdefault("blocked_atr_bands", [])
        payload.setdefault("allowed_confirmation_bands", [])
        payload.setdefault("blocked_confirmation_bands", [])
        payload.setdefault("required_rejection_signals", ["wick_rejection"])
        payload.setdefault("blocked_rejection_signals", [])
        payload.setdefault("trail_atr_multiple", 1.0)
        payload.setdefault("break_even_trigger_r", None)
        payload.setdefault("daily_max_losses", None)
        payload.setdefault("daily_min_pnl_r", None)
        payload.setdefault("cooldown_bars_after_loss", None)
        payload.setdefault("max_trades_per_day", None)
        payload.setdefault("max_range_atr_multiple", 2.0)
        payload.setdefault("relaxed_htf_bias", False)
        payload.setdefault("balanced_htf_bias", False)
        payload.setdefault("relaxed_order_block", False)
        payload.setdefault("balanced_order_block", False)
        payload.setdefault("confirmation_mode", None)
        payload.setdefault("min_confirmation_signals", None)
        payload.setdefault("recent_order_block_window", None)
        payload.setdefault("stop_buffer_atr", None)
        return AnnualOptimizationCandidate(**payload)

    def _evaluate_candidate(self, *, symbol: str, initial_capital: float, candidate: AnnualOptimizationCandidate, base_spec) -> dict:
        cache_key = json.dumps(asdict(candidate), sort_keys=True)
        cached = self._candidate_cache.get(cache_key)
        if cached is not None:
            return cached
        spec = self._candidate_spec(base_spec, candidate)
        year_2024 = self._evaluate_year(spec=spec, symbol=symbol, year=2024, initial_capital=initial_capital)
        year_2025 = self._evaluate_year(spec=spec, symbol=symbol, year=2025, initial_capital=initial_capital)
        combined = self._evaluate_combined(year_2024=year_2024, year_2025=year_2025, initial_capital=initial_capital)
        acceptance = self._acceptance(year_2024=year_2024, year_2025=year_2025, combined=combined)
        result = {
            "candidate": asdict(candidate),
            "parameters": self._spec_parameters(spec),
            "year_2024": year_2024["summary"],
            "year_2025": year_2025["summary"],
            "combined": combined,
            "acceptance": acceptance,
            "score": self._score(year_2024=year_2024, year_2025=year_2025, combined=combined, acceptance=acceptance),
        }
        self._candidate_cache[cache_key] = result
        return result

    def _candidate_spec(self, base_spec, candidate: AnnualOptimizationCandidate):
        payload = base_spec.model_dump()
        overrides = dict(payload.get("simulation_overrides") or {})
        overrides.update(
            {
                "direction_filter": "short_only",
                "exit_management": "trailing_atr_after_1r",
                "trail_atr_multiple": candidate.trail_atr_multiple,
                "break_even_trigger_r": candidate.break_even_trigger_r,
                "allowed_hours_utc": candidate.allowed_hours_utc,
                "blocked_hours_utc": candidate.blocked_hours_utc,
                "allowed_atr_bands": candidate.allowed_atr_bands,
                "blocked_atr_bands": candidate.blocked_atr_bands,
                "allowed_confirmation_bands": candidate.allowed_confirmation_bands,
                "blocked_confirmation_bands": candidate.blocked_confirmation_bands,
                "required_rejection_signals": candidate.required_rejection_signals,
                "blocked_rejection_signals": candidate.blocked_rejection_signals,
                "daily_max_losses": candidate.daily_max_losses,
                "daily_min_pnl_r": candidate.daily_min_pnl_r,
                "cooldown_bars_after_loss": candidate.cooldown_bars_after_loss,
                "max_trades_per_day": candidate.max_trades_per_day,
                "max_range_atr_multiple": candidate.max_range_atr_multiple,
                "relaxed_htf_bias": candidate.relaxed_htf_bias,
                "balanced_htf_bias": candidate.balanced_htf_bias,
                "relaxed_order_block": candidate.relaxed_order_block,
                "balanced_order_block": candidate.balanced_order_block,
                "confirmation_mode": candidate.confirmation_mode,
                "min_confirmation_signals": candidate.min_confirmation_signals,
                "recent_order_block_window": candidate.recent_order_block_window,
                "stop_buffer_atr": candidate.stop_buffer_atr,
            }
        )
        payload["strategy_name"] = f"annual_{candidate.candidate_name}"
        payload["simulation_overrides"] = overrides
        payload["session_filter"] = ["any_session"]
        return base_spec.__class__.model_validate(payload)

    def _evaluate_year(self, *, spec, symbol: str, year: int, initial_capital: float) -> dict:
        summary = self.backtester.evaluate(settings=self.settings, symbol=symbol, year=year, initial_capital=initial_capital, spec=spec)
        trades = self._collect_year_trades(spec=spec, symbol=symbol, year=year)
        realized_by_risk = {
            "0.5": self.backtester._realize_trades(trades=trades, initial_capital=initial_capital, risk_percent=0.5),
            "1.0": self.backtester._realize_trades(trades=trades, initial_capital=initial_capital, risk_percent=1.0),
        }
        coverage_sufficient = self._coverage_sufficient(summary["coverage"])
        return {
            "summary": summary,
            "trades": trades,
            "realized_by_risk": realized_by_risk,
            "coverage_sufficient": coverage_sufficient,
        }

    def _collect_year_trades(self, *, spec, symbol: str, year: int) -> list[Trade]:
        snapshot = self.backtester._load_year_snapshot(spec=spec, symbol=symbol, year=year)
        trades = self.backtester._simulate_year_trades(spec=spec, symbol=symbol, snapshot=snapshot)
        trades.sort(key=lambda item: (item.entry_time, item.exit_time, item.entry_timeframe))
        return trades

    def _evaluate_combined(self, *, year_2024: dict, year_2025: dict, initial_capital: float) -> dict:
        combined_trades = sorted(year_2024["trades"] + year_2025["trades"], key=lambda item: (item.entry_time, item.exit_time))
        combined_realized_05 = self.backtester._realize_trades(trades=combined_trades, initial_capital=initial_capital, risk_percent=0.5)
        combined_realized_10 = self.backtester._realize_trades(trades=combined_trades, initial_capital=initial_capital, risk_percent=1.0)
        monthly_05 = self._multi_year_monthly(combined_realized_05)
        monthly_10 = self._multi_year_monthly(combined_realized_10)
        return {
            "0.5": {
                "annual": self._aggregate_realized(realized=combined_realized_05, monthly=monthly_05, initial_capital=initial_capital, risk_percent=0.5),
                "monthly": monthly_05,
                "hourly": self._hourly_stability(combined_trades),
            },
            "1.0": {
                "annual": self._aggregate_realized(realized=combined_realized_10, monthly=monthly_10, initial_capital=initial_capital, risk_percent=1.0),
                "monthly": monthly_10,
                "hourly": self._hourly_stability(combined_trades),
            },
        }

    def _multi_year_monthly(self, realized: list[RealizedTrade]) -> list[dict]:
        if not realized:
            return []
        grouped: dict[str, list[RealizedTrade]] = {}
        for item in realized:
            key = item.trade.exit_time.strftime("%Y-%m")
            grouped.setdefault(key, []).append(item)
        months = sorted(grouped)
        rows: list[dict] = []
        running_balance = realized[0].balance_after - realized[0].pnl_usd if realized else 0.0
        for month_key in months:
            items = grouped[month_key]
            wins = [item for item in items if item.pnl_usd > 0]
            losses = [item for item in items if item.pnl_usd < 0]
            gross_profit = sum(item.pnl_usd for item in wins)
            gross_loss = abs(sum(item.pnl_usd for item in losses))
            net_profit = round(sum(item.pnl_usd for item in items), 4)
            ending_balance = round(running_balance + net_profit, 4)
            equity = running_balance
            peak = running_balance
            max_drawdown_usd = 0.0
            losing_streak = 0
            current_losing_streak = 0
            expectancy_r = round(sum(item.trade.pnl_r for item in items) / len(items), 4) if items else 0.0
            for item in items:
                equity += item.pnl_usd
                peak = max(peak, equity)
                max_drawdown_usd = max(max_drawdown_usd, peak - equity)
                if item.pnl_usd < 0:
                    current_losing_streak += 1
                    losing_streak = max(losing_streak, current_losing_streak)
                else:
                    current_losing_streak = 0
            rows.append(
                {
                    "month": month_key,
                    "trades": len(items),
                    "wins": len(wins),
                    "losses": len(losses),
                    "win_rate": round((len(wins) / len(items) * 100.0), 2) if items else 0.0,
                    "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4) if items else 0.0,
                    "expectancy": round(net_profit / len(items), 4) if items else 0.0,
                    "expectancy_r": expectancy_r,
                    "net_profit_usd": net_profit,
                    "ending_balance": ending_balance,
                    "max_drawdown_usd": round(max_drawdown_usd, 4),
                    "max_drawdown_percent": round((max_drawdown_usd / max(running_balance, 0.0001) * 100.0), 4) if items else 0.0,
                    "losing_streak": losing_streak,
                    "negative_month": net_profit < 0,
                }
            )
            running_balance = ending_balance
        return rows

    def _aggregate_realized(self, *, realized: list[RealizedTrade], monthly: list[dict], initial_capital: float, risk_percent: float) -> dict:
        total_trades = len(realized)
        wins = [item for item in realized if item.pnl_usd > 0]
        losses = [item for item in realized if item.pnl_usd < 0]
        gross_profit = sum(item.pnl_usd for item in wins)
        gross_loss = abs(sum(item.pnl_usd for item in losses))
        ending_balance = round(realized[-1].balance_after, 4) if realized else round(initial_capital, 4)
        total_profit = round(ending_balance - initial_capital, 4)
        max_drawdown_usd = max((item.drawdown_usd for item in realized), default=0.0)
        max_drawdown_percent = max((item.drawdown_percent for item in realized), default=0.0)
        best_month = max(monthly, key=lambda item: item["net_profit_usd"]) if monthly else None
        worst_month = min(monthly, key=lambda item: item["net_profit_usd"]) if monthly else None
        return {
            "risk_percent": risk_percent,
            "initial_capital": initial_capital,
            "ending_balance": ending_balance,
            "total_profit_usd": total_profit,
            "total_return_percent": round((total_profit / initial_capital) * 100.0, 4) if initial_capital else 0.0,
            "total_trades": total_trades,
            "win_rate": round((len(wins) / total_trades) * 100.0, 2) if total_trades else 0.0,
            "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4) if total_trades else 0.0,
            "expectancy": round(total_profit / total_trades, 4) if total_trades else 0.0,
            "expectancy_r": round(sum(item.trade.pnl_r for item in realized) / total_trades, 4) if total_trades else 0.0,
            "max_drawdown_usd": round(max_drawdown_usd, 4),
            "max_drawdown_percent": round(max_drawdown_percent, 4),
            "best_month": best_month,
            "worst_month": worst_month,
            "consecutive_negative_months": self._max_negative_streak(monthly),
            "losing_streak": self._max_losing_streak(realized),
        }

    @staticmethod
    def _hourly_stability(trades: list[Trade]) -> list[dict]:
        total = len(trades) or 1
        grouped: dict[int, list[Trade]] = {}
        for trade in trades:
            if trade.hour_utc is None:
                continue
            grouped.setdefault(trade.hour_utc, []).append(trade)
        rows = []
        for hour in sorted(grouped):
            hour_trades = grouped[hour]
            metrics = BlueprintBacktester._metrics(hour_trades)
            rows.append(
                {
                    "hour_utc": hour,
                    "trades": len(hour_trades),
                    "trade_share": round(len(hour_trades) / total, 4),
                    "profit_factor": metrics["profit_factor"],
                    "expectancy_r": metrics["expectancy"],
                }
            )
        return rows

    def _acceptance(self, *, year_2024: dict, year_2025: dict, combined: dict) -> dict:
        annual_2024 = year_2024["summary"]["simulations"]["0.5"]["annual"]
        annual_2025 = year_2025["summary"]["simulations"]["0.5"]["annual"]
        combined_annual = combined["0.5"]["annual"]
        hourly = combined["0.5"]["hourly"]
        coverage_sufficient = year_2024["coverage_sufficient"] and year_2025["coverage_sufficient"]
        checks = {
            "coverage_2024": year_2024["coverage_sufficient"],
            "coverage_2025": year_2025["coverage_sufficient"],
            "combined_trades": combined_annual["total_trades"] >= 150,
            "profit_factor_2025": annual_2025["profit_factor"] >= 1.25,
            "profit_factor_2024_or_more_data": annual_2024["profit_factor"] >= 1.25 if year_2024["coverage_sufficient"] else False,
            "combined_profit_factor": combined_annual["profit_factor"] >= 1.35,
            "combined_expectancy": combined_annual["expectancy_r"] > 0,
            "combined_drawdown": combined_annual["max_drawdown_percent"] <= 12.0,
            "combined_losing_streak": combined_annual["losing_streak"] <= 7,
            "negative_month_streak": combined_annual["consecutive_negative_months"] <= 2,
            "hour_dependency": self._top_hour_share(hourly) <= 0.35,
        }
        return {
            "coverage_sufficient": coverage_sufficient,
            "accepted": coverage_sufficient and all(
                checks[key]
                for key in (
                    "combined_trades",
                    "profit_factor_2025",
                    "profit_factor_2024_or_more_data",
                    "combined_profit_factor",
                    "combined_expectancy",
                    "combined_drawdown",
                    "combined_losing_streak",
                    "negative_month_streak",
                    "hour_dependency",
                )
            ),
            "checks": checks,
            "risk_1_0_drawdown_ok": combined["1.0"]["annual"]["max_drawdown_percent"] <= 15.0,
            "coverage_warnings": year_2024["summary"]["coverage"]["warnings"] + year_2025["summary"]["coverage"]["warnings"],
        }

    def _score(self, *, year_2024: dict, year_2025: dict, combined: dict, acceptance: dict) -> float:
        score = 0.0
        annual_2025 = year_2025["summary"]["simulations"]["0.5"]["annual"]
        annual_2024 = year_2024["summary"]["simulations"]["0.5"]["annual"]
        combined_annual = combined["0.5"]["annual"]
        trades_2024 = int(annual_2024["total_trades"])
        trades_2025 = int(annual_2025["total_trades"])
        combined_trades = int(combined_annual["total_trades"])
        score += annual_2025["profit_factor"] * 40
        score += combined_annual["profit_factor"] * 50
        score += min(combined_trades / 150, 1.0) * 20
        score += max(combined_annual["expectancy_r"], -2.0) * 20
        score -= combined_annual["max_drawdown_percent"] * 5
        score -= combined_annual["losing_streak"] * 5
        score += self._positive_month_ratio(combined["0.5"]["monthly"]) * 10
        if year_2024["coverage_sufficient"]:
            score += annual_2024["profit_factor"] * 20
        else:
            score -= 80
        if not year_2025["coverage_sufficient"]:
            score -= 80
        if trades_2025 == 0:
            score -= 300
        elif trades_2025 < 25:
            score -= 180
        elif trades_2025 < 50:
            score -= 90
        if combined_trades < 150:
            score -= min((150 - combined_trades) * 1.6, 220.0)
        if trades_2024 == 0:
            score -= 40
        top_hour_share = self._top_hour_share(combined["0.5"]["hourly"])
        if top_hour_share > 0.35:
            score -= (top_hour_share - 0.35) * 120.0
        if not acceptance["risk_1_0_drawdown_ok"]:
            score -= 20
        if acceptance["accepted"]:
            score += 50
        return round(score, 4)

    def _decision(self, *, baseline: dict, best_candidate: dict) -> dict:
        if not best_candidate["acceptance"]["coverage_sufficient"]:
            return {
                "status": "NEEDS_MORE_DATA",
                "reason": "Historical coverage is insufficient for at least one required annual entry dataset, so a robust cross-year approval is not justified.",
            }
        if best_candidate["acceptance"]["accepted"]:
            return {
                "status": "READY_FOR_PAPER_TRADING",
                "reason": "The best annual candidate satisfies the cross-year quantitative acceptance gate.",
            }
        return {
            "status": "NOT_ROBUST",
            "reason": "Annual coverage is sufficient, but no controlled variant satisfied the cross-year acceptance thresholds.",
        }

    @staticmethod
    def _top_hour_share(hourly: list[dict]) -> float:
        return max((row["trade_share"] for row in hourly), default=1.0)

    def _select_best_2025_candidate(self, candidates: list[dict]) -> dict | None:
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.get("year_2025", {}).get("simulations", {}).get("0.5", {}).get("annual", {}).get("total_profit_usd", 0.0),
                item.get("year_2025", {}).get("simulations", {}).get("0.5", {}).get("annual", {}).get("profit_factor", 0.0),
                item.get("year_2025", {}).get("simulations", {}).get("0.5", {}).get("annual", {}).get("total_trades", 0),
            ),
        )

    def _safe_target_income_analysis(
        self,
        *,
        symbol: str,
        initial_capital: float,
        base_spec,
        baseline_candidate: AnnualOptimizationCandidate,
        best_2025_candidate: AnnualOptimizationCandidate,
    ) -> dict:
        try:
            return {
                "baseline": self._target_income_analysis(
                    symbol=symbol,
                    initial_capital=initial_capital,
                    candidate=baseline_candidate,
                    base_spec=base_spec,
                ),
                "best_2025_candidate": self._target_income_analysis(
                    symbol=symbol,
                    initial_capital=initial_capital,
                    candidate=best_2025_candidate,
                    base_spec=base_spec,
                ),
            }
        except Exception as exc:
            return {
                "baseline": {"candidate_name": baseline_candidate.candidate_name, "analysis_available": False, "error": str(exc)},
                "best_2025_candidate": {"candidate_name": best_2025_candidate.candidate_name, "analysis_available": False, "error": str(exc)},
            }

    def _target_income_analysis(
        self,
        *,
        symbol: str,
        initial_capital: float,
        candidate: AnnualOptimizationCandidate,
        base_spec,
    ) -> dict:
        spec = self._candidate_spec(base_spec, candidate)
        year_2025 = self._evaluate_year(spec=spec, symbol=symbol, year=2025, initial_capital=initial_capital)
        risk_levels = [0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0]
        rows: list[dict] = []
        for risk_percent in risk_levels:
            realized = self.backtester._realize_trades(
                trades=year_2025["trades"],
                initial_capital=initial_capital,
                risk_percent=risk_percent,
            )
            monthly = self.backtester._monthly_report(realized=realized, year=2025, initial_capital=initial_capital)
            annual = self._aggregate_realized(
                realized=realized,
                monthly=monthly,
                initial_capital=initial_capital,
                risk_percent=risk_percent,
            )
            month_profits = [float(row["net_profit_usd"]) for row in monthly]
            positive_months = sum(1 for value in month_profits if value > 0)
            rows.append(
                {
                    "risk_percent": risk_percent,
                    "ending_balance": annual["ending_balance"],
                    "total_profit_usd": annual["total_profit_usd"],
                    "avg_monthly_profit_usd": round(sum(month_profits) / max(len(month_profits), 1), 4),
                    "median_monthly_profit_usd": round(self._median(month_profits), 4),
                    "best_month_profit_usd": round(max(month_profits, default=0.0), 4),
                    "worst_month_profit_usd": round(min(month_profits, default=0.0), 4),
                    "months_above_1500": sum(1 for value in month_profits if value >= 1500.0),
                    "positive_months": positive_months,
                    "total_trades": annual["total_trades"],
                    "profit_factor": annual["profit_factor"],
                    "expectancy_r": annual["expectancy_r"],
                    "max_drawdown_percent": annual["max_drawdown_percent"],
                    "losing_streak": annual["losing_streak"],
                }
            )
        feasible = [row for row in rows if row["avg_monthly_profit_usd"] >= 1500.0]
        return {
            "candidate_name": candidate.candidate_name,
            "coverage_sufficient_2025": year_2025["coverage_sufficient"],
            "required_monthly_profit_usd": 1500.0,
            "risk_sweep": rows,
            "target_reached": bool(feasible),
            "lowest_risk_reaching_target": feasible[0] if feasible else None,
            "best_avg_monthly_profit_variant": max(rows, key=lambda item: item["avg_monthly_profit_usd"], default=None),
        }

    @staticmethod
    def _median(values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    @staticmethod
    def _positive_month_ratio(monthly: list[dict]) -> float:
        if not monthly:
            return 0.0
        positive = sum(1 for row in monthly if not row["negative_month"])
        return positive / len(monthly)

    @staticmethod
    def _max_negative_streak(monthly: list[dict]) -> int:
        max_streak = 0
        current = 0
        for row in monthly:
            if row["negative_month"]:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def _max_losing_streak(realized: list[RealizedTrade]) -> int:
        max_streak = 0
        current = 0
        for item in realized:
            if item.pnl_usd < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def _coverage_sufficient(coverage: dict) -> bool:
        timeframes = coverage["timeframes"]
        context_ok = bool(timeframes.get("H1", {}).get("complete_for_year"))
        entry_ok = any(timeframes.get(tf, {}).get("complete_for_year") for tf in ("M1", "M5"))
        return context_ok and entry_ok

    @staticmethod
    def _spec_parameters(spec) -> dict:
        overrides = spec.simulation_overrides or {}
        return {
            "strategy_name": spec.strategy_name,
            "session_filter": spec.session_filter,
            "rr_min": spec.rr_min,
            "trail_atr_multiple": overrides.get("trail_atr_multiple"),
            "break_even_trigger_r": overrides.get("break_even_trigger_r"),
            "allowed_hours_utc": overrides.get("allowed_hours_utc", []),
            "blocked_hours_utc": overrides.get("blocked_hours_utc", []),
            "allowed_atr_bands": overrides.get("allowed_atr_bands", []),
            "blocked_atr_bands": overrides.get("blocked_atr_bands", []),
            "allowed_confirmation_bands": overrides.get("allowed_confirmation_bands", []),
            "blocked_confirmation_bands": overrides.get("blocked_confirmation_bands", []),
            "required_rejection_signals": overrides.get("required_rejection_signals", []),
            "blocked_rejection_signals": overrides.get("blocked_rejection_signals", []),
            "daily_max_losses": overrides.get("daily_max_losses"),
            "daily_min_pnl_r": overrides.get("daily_min_pnl_r"),
            "cooldown_bars_after_loss": overrides.get("cooldown_bars_after_loss"),
            "max_trades_per_day": overrides.get("max_trades_per_day"),
            "max_range_atr_multiple": overrides.get("max_range_atr_multiple"),
            "relaxed_htf_bias": overrides.get("relaxed_htf_bias", False),
            "balanced_htf_bias": overrides.get("balanced_htf_bias", False),
            "relaxed_order_block": overrides.get("relaxed_order_block", False),
            "balanced_order_block": overrides.get("balanced_order_block", False),
            "confirmation_mode": overrides.get("confirmation_mode"),
            "min_confirmation_signals": overrides.get("min_confirmation_signals"),
            "recent_order_block_window": overrides.get("recent_order_block_window"),
            "stop_buffer_atr": overrides.get("stop_buffer_atr"),
        }

    def _write_candidates_csv(self, path: Path, candidates: list[dict]) -> None:
        fields = [
            "candidate_name",
            "pf_2024",
            "trades_2024",
            "pf_2025",
            "trades_2025",
            "pf_combined",
            "trades_combined",
            "dd_combined",
            "coverage_2024",
            "coverage_2025",
            "accepted",
            "decision_hint",
            "score",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in candidates:
                annual_2024 = item.get("year_2024", {}).get("simulations", {}).get("0.5", {}).get("annual", {})
                annual_2025 = item.get("year_2025", {}).get("simulations", {}).get("0.5", {}).get("annual", {})
                writer.writerow(
                    {
                        "candidate_name": item["candidate"]["candidate_name"],
                        "pf_2024": annual_2024.get("profit_factor", 0.0),
                        "trades_2024": annual_2024.get("total_trades", 0),
                        "pf_2025": annual_2025.get("profit_factor", 0.0),
                        "trades_2025": annual_2025.get("total_trades", 0),
                        "pf_combined": item["combined"]["0.5"]["annual"]["profit_factor"],
                        "trades_combined": item["combined"]["0.5"]["annual"]["total_trades"],
                        "dd_combined": item["combined"]["0.5"]["annual"]["max_drawdown_percent"],
                        "coverage_2024": item["acceptance"]["checks"]["coverage_2024"],
                        "coverage_2025": item["acceptance"]["checks"]["coverage_2025"],
                        "accepted": item["acceptance"]["accepted"],
                        "decision_hint": "coverage_gap" if not item["acceptance"]["coverage_sufficient"] else "robust" if item["acceptance"]["accepted"] else "not_robust",
                        "score": item["score"],
                    }
                )

    def _report_markdown(self, payload: dict) -> str:
        baseline = payload["baseline"]
        best = payload["best_candidate"]
        def _annual(item: dict, year_key: str) -> dict:
            return item.get(year_key, {}).get("simulations", {}).get("0.5", {}).get("annual", {})

        lines = [
            "# Annual Optimization Report",
            "",
            f"- symbol: {payload['symbol']}",
            f"- initial_capital: {payload['initial_capital']}",
            f"- decision: {payload['decision']['status']}",
            f"- reason: {payload['decision']['reason']}",
            "",
            "## Baseline",
            f"- candidate: {baseline['candidate']['candidate_name']}",
            f"- 2024 PF (0.5%): {_annual(baseline, 'year_2024').get('profit_factor', 0.0)}",
            f"- 2025 PF (0.5%): {_annual(baseline, 'year_2025').get('profit_factor', 0.0)}",
            f"- combined PF (0.5%): {baseline['combined']['0.5']['annual']['profit_factor']}",
            "",
            "## Best Candidate",
            f"- candidate: {best['candidate']['candidate_name']}",
            f"- 2024 PF (0.5%): {_annual(best, 'year_2024').get('profit_factor', 0.0)}",
            f"- 2025 PF (0.5%): {_annual(best, 'year_2025').get('profit_factor', 0.0)}",
            f"- combined PF (0.5%): {best['combined']['0.5']['annual']['profit_factor']}",
            f"- combined trades (0.5%): {best['combined']['0.5']['annual']['total_trades']}",
            f"- combined DD% (0.5%): {best['combined']['0.5']['annual']['max_drawdown_percent']}",
            "",
            "## Coverage Warnings",
        ]
        warnings = best["acceptance"]["coverage_warnings"] or ["none"]
        for item in warnings:
            lines.append(f"- {item}")
        lines.extend(["", "## Top 10 Candidates"])
        for item in payload["top_candidates"]:
            annual_2024 = _annual(item, "year_2024")
            annual_2025 = _annual(item, "year_2025")
            lines.append(
                f"- {item['candidate']['candidate_name']}: 2024_trades={annual_2024.get('total_trades', 0)} 2025_trades={annual_2025.get('total_trades', 0)} 2025_pf={annual_2025.get('profit_factor', 0.0)} combined_pf={item['combined']['0.5']['annual']['profit_factor']} trades={item['combined']['0.5']['annual']['total_trades']} dd={item['combined']['0.5']['annual']['max_drawdown_percent']} accepted={item['acceptance']['accepted']}"
            )
        lines.extend(["", "## Monthly Income Target Analysis"])
        for label, analysis in payload.get("target_income_analysis", {}).items():
            lines.append(f"### {label}")
            lines.append(f"- candidate: {analysis['candidate_name']}")
            if analysis.get("analysis_available") is False:
                lines.append(f"- analysis_available: false")
                lines.append(f"- error: {analysis.get('error')}")
                continue
            lines.append(f"- coverage_sufficient_2025: {analysis['coverage_sufficient_2025']}")
            lines.append(f"- target_reached: {analysis['target_reached']}")
            best_variant = analysis.get("best_avg_monthly_profit_variant")
            if best_variant:
                lines.append(
                    f"- best_avg_monthly_profit: risk={best_variant['risk_percent']} avg_monthly={best_variant['avg_monthly_profit_usd']} dd={best_variant['max_drawdown_percent']} ending_balance={best_variant['ending_balance']}"
                )
        return "\n".join(lines) + "\n"
