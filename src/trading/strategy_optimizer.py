"""Controlled optimization pipeline for OB Rejection Short Only Trailing ATR."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.trading.backtest_validation import BacktestValidationEngine
from src.trading.blueprint_backtester import BlueprintBacktester
from src.trading.strategy_schemas import BacktestBlueprintSpec


@dataclass(slots=True)
class OptimizationCandidate:
    candidate_name: str
    trail_atr_multiple: float
    break_even_trigger_r: float | None
    allowed_hours_utc: list[int]
    blocked_hours_utc: list[int]
    allowed_atr_bands: list[str]
    blocked_atr_bands: list[str]
    required_rejection_signals: list[str]
    blocked_rejection_signals: list[str]
    max_range_atr_multiple: float
    daily_max_losses: int | None
    daily_min_pnl_r: float | None
    cooldown_bars_after_loss: int | None
    cooldown_until_new_structure: bool
    max_trades_per_day: int | None


class OBRejectionOptimizer:
    """Optimize only the current short-only trailing baseline for paper-trading readiness."""

    BASE_SPEC_NAME = "ob_rejection_short_only_trailing_atr.json"
    BASELINE_FILE_NAME = "baseline_ob_rejection_short_trailing_atr.json"
    FINAL_FILE_NAME = "final_candidate_v3.json"
    FINAL_REPORT_NAME = "final_validation_report_v3.md"
    PREVIOUS_FINAL_FILE_NAME = "final_candidate_v2.json"
    LEGACY_FINAL_FILE_NAME = "final_candidate.json"
    LEGACY_FINAL_REPORT_NAME = "final_validation_report.md"

    def __init__(self, input_dir: Path, results_dir: Path, reports_dir: Path, optimization_dir: Path) -> None:
        self.input_dir = input_dir
        self.results_dir = results_dir
        self.reports_dir = reports_dir
        self.optimization_dir = optimization_dir
        self.specs_dir = self.results_dir.parent / "specs"
        self.strategies_dir = self.results_dir.parent.parent / "strategies"
        self.optimization_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.strategies_dir.mkdir(parents=True, exist_ok=True)
        self.backtester = BlueprintBacktester(input_dir, results_dir, reports_dir)
        self.validator = BacktestValidationEngine(self.backtester)
        self._evaluation_cache: dict[str, dict] = {}

    def run(self) -> dict:
        base_spec = self._load_base_spec()
        baseline = self._baseline_validation(base_spec)
        baseline_path = self._write_immutable_baseline(base_spec, baseline)

        candidates = self._restricted_candidates()
        evaluations = [self._evaluate_candidate(base_spec, candidate) for candidate in candidates]
        ranked = sorted(evaluations, key=lambda item: (-item["score"], item["candidate"]["candidate_name"]))
        accepted = [item for item in ranked if item["acceptance"]["accepted"]]
        best_candidate = accepted[0] if accepted else None
        final_selection = best_candidate or self._best_nonaccepted(ranked)
        decision = self._decision(baseline, final_selection, accepted_count=len(accepted))
        previous_v2 = self._load_previous_final_candidate()

        comparison = self._comparison_block(baseline, final_selection, previous_v2)
        final_candidate_payload = self._final_candidate_payload(
            decision=decision,
            baseline=baseline,
            final_selection=final_selection,
            comparison=comparison,
            previous_v2=previous_v2,
        )
        final_candidate_path = self.strategies_dir / self.FINAL_FILE_NAME
        final_candidate_path.write_text(json.dumps(final_candidate_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        legacy_final_candidate_path = self.strategies_dir / self.LEGACY_FINAL_FILE_NAME
        legacy_final_candidate_path.write_text(json.dumps(final_candidate_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        report_path = self.reports_dir / self.FINAL_REPORT_NAME
        report_path.write_text(self._final_report_markdown(final_candidate_payload), encoding="utf-8")
        legacy_report_path = self.reports_dir / self.LEGACY_FINAL_REPORT_NAME
        legacy_report_path.write_text(self._final_report_markdown(final_candidate_payload), encoding="utf-8")

        optimization_payload = {
            "search_summary": {
                "candidates_tested": len(candidates),
                "accepted_candidates": len(accepted),
            },
            "baseline_previous_version": baseline,
            "top_candidates": ranked[:10],
            "decision": decision,
            "baseline_path": str(baseline_path.resolve()),
            "final_candidate_path": str(final_candidate_path.resolve()),
            "final_validation_report_path": str(report_path.resolve()),
        }
        json_path = self.optimization_dir / "ob_rejection_optimization_results.json"
        report_summary_path = self.optimization_dir / "ob_rejection_optimization_report.md"
        csv_path = self.optimization_dir / "top_candidates.csv"
        json_path.write_text(json.dumps(optimization_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_top_candidates_csv(csv_path, ranked[:10])
        report_summary_path.write_text(self._optimization_summary_markdown(optimization_payload), encoding="utf-8")

        return {
            "optimization_dir": str(self.optimization_dir.resolve()),
            "results_json": str(json_path.resolve()),
            "report_md": str(report_summary_path.resolve()),
            "top_candidates_csv": str(csv_path.resolve()),
            "best_candidate": final_selection["candidate"]["candidate_name"] if final_selection else None,
            "decision": decision["status"],
            "baseline_path": str(baseline_path.resolve()),
            "final_candidate_path": str(final_candidate_path.resolve()),
            "final_validation_report_path": str(report_path.resolve()),
        }

    def _load_base_spec(self) -> BacktestBlueprintSpec:
        path = self.specs_dir / self.BASE_SPEC_NAME
        if not path.exists():
            raise FileNotFoundError(
                "Short Only Trailing ATR spec not found. Run generate-robust-ob-backtests before optimize-ob-rejection."
            )
        return BacktestBlueprintSpec.model_validate_json(path.read_text(encoding="utf-8"))

    def _baseline_validation(self, base_spec: BacktestBlueprintSpec) -> dict:
        validation = self.validator.validate(base_spec)
        return {
            "strategy_name": base_spec.strategy_name,
            "parameters": self._spec_parameters(base_spec),
            "train": validation["train"],
            "test": validation["test"],
            "full": validation["full"],
            "month_by_month": validation["month_by_month"],
            "rolling_7030": validation["rolling_7030"],
            "walk_forward_blocks": validation["walk_forward_blocks"],
            "stability_by_hour": validation["stability_by_hour"],
            "acceptance": self._acceptance(validation),
            "dataset_used": self._dataset_summary(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _write_immutable_baseline(self, base_spec: BacktestBlueprintSpec, baseline: dict) -> Path:
        path = self.strategies_dir / self.BASELINE_FILE_NAME
        if path.exists():
            return path
        payload = {
            "strategy_name": base_spec.strategy_name,
            "date": baseline["generated_at"],
            "dataset_used": baseline["dataset_used"],
            "parameters": baseline["parameters"],
            "train": baseline["train"],
            "test": baseline["test"],
            "full": baseline["full"],
            "month_by_month": baseline["month_by_month"],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _load_previous_final_candidate(self) -> dict | None:
        path = self.strategies_dir / self.PREVIOUS_FINAL_FILE_NAME
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _restricted_candidates(self) -> list[OptimizationCandidate]:
        candidates: list[OptimizationCandidate] = []
        blocked_hours = [2, 3, 12, 16, 23]
        daily_guards = [("none", None), ("dayr2", -2.0), ("dayr3", -3.0)]
        cooldowns = [("nocd", None, False), ("cd1", 1, False), ("cd2", 2, False)]
        atr_modes = [
            ("allatr", [], []),
            ("nop4060", [], ["p40_60"]),
        ]
        for guard_key, min_pnl_r in daily_guards:
            for cooldown_key, cooldown_bars, cooldown_structure in cooldowns:
                for max_trades in (None, 3, 4):
                    for atr_key, allowed_atr_bands, blocked_atr_bands in atr_modes:
                        max_trades_key = "nolimit" if max_trades is None else f"max{max_trades}"
                        candidates.append(
                            OptimizationCandidate(
                                candidate_name=f"shorttrail_v3_{guard_key}_{cooldown_key}_{max_trades_key}_{atr_key}",
                                trail_atr_multiple=1.0,
                                break_even_trigger_r=None,
                                allowed_hours_utc=[],
                                blocked_hours_utc=blocked_hours,
                                allowed_atr_bands=allowed_atr_bands,
                                blocked_atr_bands=blocked_atr_bands,
                                required_rejection_signals=["wick_rejection"],
                                blocked_rejection_signals=[],
                                max_range_atr_multiple=2.0,
                                daily_min_pnl_r=min_pnl_r,
                                cooldown_bars_after_loss=cooldown_bars,
                                cooldown_until_new_structure=cooldown_structure,
                                max_trades_per_day=max_trades,
                                daily_max_losses=None,
                            )
                        )
        for atr_key, allowed_atr_bands, blocked_atr_bands in atr_modes:
            candidates.append(
                OptimizationCandidate(
                    candidate_name=f"shorttrail_v3_dayr2_struct_nolimit_{atr_key}",
                    trail_atr_multiple=1.0,
                    break_even_trigger_r=None,
                    allowed_hours_utc=[],
                    blocked_hours_utc=blocked_hours,
                    allowed_atr_bands=allowed_atr_bands,
                    blocked_atr_bands=blocked_atr_bands,
                    required_rejection_signals=["wick_rejection"],
                    blocked_rejection_signals=[],
                    max_range_atr_multiple=2.0,
                    daily_max_losses=None,
                    daily_min_pnl_r=-2.0,
                    cooldown_bars_after_loss=None,
                    cooldown_until_new_structure=True,
                    max_trades_per_day=None,
                )
            )
        return candidates

    def _evaluate_candidate(self, base_spec: BacktestBlueprintSpec, candidate: OptimizationCandidate) -> dict:
        cache_key = json.dumps(asdict(candidate), sort_keys=True)
        cached = self._evaluation_cache.get(cache_key)
        if cached is not None:
            return json.loads(json.dumps(cached))
        spec = self._candidate_spec(base_spec, candidate)
        validation = self.validator.validate(spec)
        acceptance = self._acceptance(validation)
        result = {
            "candidate": asdict(candidate),
            "parameters": self._spec_parameters(spec),
            "train": validation["train"],
            "test": validation["test"],
            "full": validation["full"],
            "month_by_month": validation["month_by_month"],
            "rolling_7030": validation["rolling_7030"],
            "walk_forward_blocks": validation["walk_forward_blocks"],
            "stability_by_hour": validation["stability_by_hour"],
            "acceptance": acceptance,
            "score": self._score_candidate(validation, acceptance),
        }
        self._evaluation_cache[cache_key] = result
        return json.loads(json.dumps(result))

    def _candidate_spec(self, base_spec: BacktestBlueprintSpec, candidate: OptimizationCandidate) -> BacktestBlueprintSpec:
        payload = base_spec.model_dump()
        overrides = dict(payload.get("simulation_overrides") or {})
        overrides.update(
            {
                "validation_profile": "controlled_short_trailing_optimization_v3",
                "direction_filter": "short_only",
                "exit_management": "trailing_atr_after_1r",
                "trail_atr_multiple": candidate.trail_atr_multiple,
                "break_even_trigger_r": candidate.break_even_trigger_r,
                "allowed_hours_utc": candidate.allowed_hours_utc,
                "blocked_hours_utc": candidate.blocked_hours_utc,
                "allowed_atr_bands": candidate.allowed_atr_bands,
                "blocked_atr_bands": candidate.blocked_atr_bands,
                "required_rejection_signals": candidate.required_rejection_signals,
                "blocked_rejection_signals": candidate.blocked_rejection_signals,
                "max_range_atr_multiple": candidate.max_range_atr_multiple,
                "stop_buffer_atr": 0.10,
                "daily_max_losses": candidate.daily_max_losses,
                "daily_min_pnl_r": candidate.daily_min_pnl_r,
                "cooldown_bars_after_loss": candidate.cooldown_bars_after_loss,
                "cooldown_until_new_structure": candidate.cooldown_until_new_structure,
                "max_trades_per_day": candidate.max_trades_per_day,
            }
        )
        payload["strategy_name"] = candidate.candidate_name
        payload["simulation_overrides"] = overrides
        payload["session_filter"] = ["any_session"]
        return BacktestBlueprintSpec.model_validate(payload)

    def _acceptance(self, validation: dict) -> dict:
        test_metrics = validation["test"]
        full_metrics = validation["full"]
        monthly = validation["month_by_month"]
        stability_by_hour = validation["stability_by_hour"]
        checks = {
            "test_profit_factor": test_metrics.get("profit_factor", 0.0) >= 1.20,
            "full_profit_factor": full_metrics.get("profit_factor", 0.0) >= 1.30,
            "max_drawdown": max(test_metrics.get("max_drawdown", 999.0), full_metrics.get("max_drawdown", 999.0)) <= 12.0,
            "trades": full_metrics.get("total_trades", 0) >= 150,
            "losing_streak": max(test_metrics.get("losing_streak", 999), full_metrics.get("losing_streak", 999)) <= 6,
            "stable_months": self._stable_months(monthly),
        }
        return {
            "accepted": all(checks.values()),
            "checks": checks,
            "negative_month_streak": self._max_negative_month_streak(monthly),
            "positive_hours_with_sample": sum(
                1 for row in stability_by_hour if row["trades"] >= 10 and row["expectancy"] > 0
            ),
        }

    def _score_candidate(self, validation: dict, acceptance: dict) -> float:
        train = validation["train"]
        test = validation["test"]
        full = validation["full"]
        monthly = validation["month_by_month"]
        stability = validation["stability_by_hour"]
        score = 0.0
        score += test.get("profit_factor", 0.0) * 35
        score += full.get("profit_factor", 0.0) * 30
        score += max(test.get("expectancy", -1.0), -1.0) * 20
        score += max(full.get("expectancy", -1.0), -1.0) * 15
        score += min(full.get("total_trades", 0) / 150, 1.0) * 20
        score -= max(test.get("max_drawdown", 999.0), full.get("max_drawdown", 999.0)) * 4
        score -= max(test.get("losing_streak", 999), full.get("losing_streak", 999)) * 4
        score += self._positive_month_ratio(monthly) * 10
        score += sum(1 for row in stability if row["trades"] >= 10 and row["expectancy"] > 0) * 4
        trade_deficit = max(0, 150 - full.get("total_trades", 0))
        score -= trade_deficit * 1.5
        if not acceptance["checks"]["trades"]:
            score -= 150
        if not acceptance["checks"]["max_drawdown"]:
            score -= 120
        if not acceptance["checks"]["test_profit_factor"]:
            score -= 80
        if not acceptance["checks"]["full_profit_factor"]:
            score -= 60
        if acceptance["accepted"]:
            score += 50
        return round(score, 4)

    @staticmethod
    def _positive_month_ratio(monthly: list[dict]) -> float:
        if not monthly:
            return 0.0
        positive = sum(1 for row in monthly if not row["negative_month"])
        return round(positive / len(monthly), 4)

    @staticmethod
    def _stable_months(monthly: list[dict]) -> bool:
        if len(monthly) < 4:
            return False
        positive = sum(1 for row in monthly if not row["negative_month"])
        return positive >= max(3, int(len(monthly) * 0.6)) and OBRejectionOptimizer._max_negative_month_streak(monthly) <= 2

    @staticmethod
    def _max_negative_month_streak(monthly: list[dict]) -> int:
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
    def _best_nonaccepted(ranked: list[dict]) -> dict | None:
        sample_qualified = [item for item in ranked if item["full"].get("total_trades", 0) >= 150]
        if sample_qualified:
            return sample_qualified[0]
        return ranked[0] if ranked else None

    def _decision(self, baseline: dict, final_selection: dict | None, *, accepted_count: int) -> dict:
        if accepted_count > 0 and final_selection is not None:
            return {
                "status": "READY_FOR_PAPER_TRADING",
                "reason": "A controlled variant satisfied all acceptance thresholds.",
            }
        if baseline["full"].get("total_trades", 0) < 150:
            return {
                "status": "NEEDS_MORE_DATA",
                "reason": "The baseline still lacks enough total trades for a robust decision.",
            }
        return {
            "status": "NOT_ROBUST",
            "reason": "No restricted variant met the paper-trading thresholds, and the baseline still fails at least one acceptance criterion.",
        }

    def _comparison_block(self, baseline: dict, final_selection: dict | None, previous_v2: dict | None) -> dict:
        selected = final_selection if final_selection is not None else None
        return {
            "baseline": {
                "train": baseline["train"],
                "test": baseline["test"],
                "full": baseline["full"],
            },
            "v2": {
                "strategy_name": previous_v2["selected_configuration"]["strategy_name"] if previous_v2 else None,
                "train": previous_v2["selected_configuration"]["train"] if previous_v2 else None,
                "test": previous_v2["selected_configuration"]["test"] if previous_v2 else None,
                "full": previous_v2["selected_configuration"]["full"] if previous_v2 else None,
            },
            "selected": {
                "candidate_name": selected["candidate"]["candidate_name"] if selected else None,
                "train": selected["train"] if selected else None,
                "test": selected["test"] if selected else None,
                "full": selected["full"] if selected else None,
            },
        }

    def _final_candidate_payload(
        self,
        *,
        decision: dict,
        baseline: dict,
        final_selection: dict | None,
        comparison: dict,
        previous_v2: dict | None,
    ) -> dict:
        risks = self._risks(baseline, final_selection)
        if final_selection and final_selection["acceptance"]["accepted"]:
            selection_type = "accepted_candidate"
        elif final_selection:
            selection_type = "best_rejected_candidate"
        else:
            selection_type = "baseline_reference"
        return {
            "decision": decision["status"],
            "decision_reason": decision["reason"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "baseline_reference": str((self.strategies_dir / self.BASELINE_FILE_NAME).resolve()),
            "v2_reference": str((self.strategies_dir / self.PREVIOUS_FINAL_FILE_NAME).resolve()) if previous_v2 else None,
            "selected_configuration": {
                "type": selection_type,
                "strategy_name": final_selection["candidate"]["candidate_name"] if final_selection else baseline["strategy_name"],
                "parameters": final_selection["parameters"] if final_selection else baseline["parameters"],
                "train": final_selection["train"] if final_selection else baseline["train"],
                "test": final_selection["test"] if final_selection else baseline["test"],
                "full": final_selection["full"] if final_selection else baseline["full"],
                "month_by_month": final_selection["month_by_month"] if final_selection else baseline["month_by_month"],
                "stability_by_hour": final_selection["stability_by_hour"] if final_selection else baseline["stability_by_hour"],
                "acceptance": final_selection["acceptance"] if final_selection else baseline["acceptance"],
            },
            "comparison_vs_baseline": comparison,
            "dataset_used": baseline["dataset_used"],
            "risks_identified": risks,
        }

    def _risks(self, baseline: dict, final_selection: dict | None) -> list[str]:
        subject = final_selection if final_selection is not None else baseline
        full = subject["full"]
        risks: list[str] = []
        if full.get("max_drawdown", 0.0) > 12.0:
            risks.append(f"Max drawdown remains above threshold at {full['max_drawdown']}.")
        if full.get("losing_streak", 0) > 6:
            risks.append(f"Losing streak remains above threshold at {full['losing_streak']}.")
        if full.get("total_trades", 0) < 150:
            risks.append(f"Trade sample is too small at {full['total_trades']} trades.")
        if self._max_negative_month_streak(subject["month_by_month"]) > 2:
            risks.append("Temporal stability is weak because there are more than two consecutive negative months.")
        if not risks:
            risks.append("No blocking risk identified under the current acceptance gate.")
        return risks

    def _dataset_summary(self) -> dict:
        summary = {"files": []}
        for path in sorted(self.input_dir.glob("XAUUSDm_*.csv")):
            rows = 0
            first = None
            last = None
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    rows += 1
                    first = first or row["time"]
                    last = row["time"]
            summary["files"].append(
                {
                    "path": str(path.resolve()),
                    "rows": rows,
                    "first_time": first,
                    "last_time": last,
                }
            )
        return summary

    @staticmethod
    def _spec_parameters(spec: BacktestBlueprintSpec) -> dict:
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
            "required_rejection_signals": overrides.get("required_rejection_signals", []),
            "blocked_rejection_signals": overrides.get("blocked_rejection_signals", []),
            "max_range_atr_multiple": overrides.get("max_range_atr_multiple"),
            "daily_max_losses": overrides.get("daily_max_losses"),
            "daily_min_pnl_r": overrides.get("daily_min_pnl_r"),
            "cooldown_bars_after_loss": overrides.get("cooldown_bars_after_loss"),
            "cooldown_until_new_structure": overrides.get("cooldown_until_new_structure", False),
            "max_trades_per_day": overrides.get("max_trades_per_day"),
        }

    @staticmethod
    def _write_top_candidates_csv(path: Path, items: list[dict]) -> None:
        fields = [
            "candidate_name",
            "trail_atr_multiple",
            "break_even_trigger_r",
            "allowed_hours_utc",
            "allowed_atr_bands",
            "test_pf",
            "full_pf",
            "full_trades",
            "full_drawdown",
            "accepted",
            "score",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in items:
                candidate = item["candidate"]
                writer.writerow(
                    {
                        "candidate_name": candidate["candidate_name"],
                        "trail_atr_multiple": candidate["trail_atr_multiple"],
                        "break_even_trigger_r": candidate["break_even_trigger_r"],
                        "allowed_hours_utc": ",".join(str(value) for value in candidate["allowed_hours_utc"]),
                        "allowed_atr_bands": ",".join(candidate["allowed_atr_bands"]),
                        "test_pf": item["test"]["profit_factor"],
                        "full_pf": item["full"]["profit_factor"],
                        "full_trades": item["full"]["total_trades"],
                        "full_drawdown": item["full"]["max_drawdown"],
                        "accepted": item["acceptance"]["accepted"],
                        "score": item["score"],
                    }
                )

    def _optimization_summary_markdown(self, payload: dict) -> str:
        lines = ["# Controlled Optimization Summary", ""]
        lines.append("## Baseline")
        baseline = payload["baseline_previous_version"]
        lines.append(
            f"- {baseline['strategy_name']}: train_pf={baseline['train']['profit_factor']} test_pf={baseline['test']['profit_factor']} full_pf={baseline['full']['profit_factor']} drawdown={baseline['full']['max_drawdown']} trades={baseline['full']['total_trades']}"
        )
        lines.extend(["", "## Top Candidates"])
        for item in payload["top_candidates"][:10]:
            lines.append(
                f"- {item['candidate']['candidate_name']}: test_pf={item['test']['profit_factor']} full_pf={item['full']['profit_factor']} trades={item['full']['total_trades']} dd={item['full']['max_drawdown']} accepted={item['acceptance']['accepted']}"
            )
        lines.extend(["", "## Decision"])
        lines.append(f"- {payload['decision']['status']}: {payload['decision']['reason']}")
        return "\n".join(lines) + "\n"

    def _final_report_markdown(self, payload: dict) -> str:
        selected = payload["selected_configuration"]
        comparison = payload["comparison_vs_baseline"]
        lines = ["# Final Validation Report", ""]
        lines.append(f"- decision: {payload['decision']}")
        lines.append(f"- reason: {payload['decision_reason']}")
        lines.append(f"- selected_strategy: {selected['strategy_name']}")
        lines.extend(["", "## Parameters Finales"])
        for key, value in selected["parameters"].items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Metrics"])
        lines.append(
            f"- train: trades={selected['train']['total_trades']} pf={selected['train']['profit_factor']} expectancy={selected['train']['expectancy']} dd={selected['train']['max_drawdown']}"
        )
        lines.append(
            f"- test: trades={selected['test']['total_trades']} pf={selected['test']['profit_factor']} expectancy={selected['test']['expectancy']} dd={selected['test']['max_drawdown']}"
        )
        lines.append(
            f"- full: trades={selected['full']['total_trades']} pf={selected['full']['profit_factor']} expectancy={selected['full']['expectancy']} dd={selected['full']['max_drawdown']}"
        )
        lines.extend(["", "## Comparación vs Baseline"])
        lines.append(
            f"- baseline full_pf={comparison['baseline']['full']['profit_factor']} full_dd={comparison['baseline']['full']['max_drawdown']} full_trades={comparison['baseline']['full']['total_trades']}"
        )
        if comparison["v2"]["strategy_name"]:
            lines.append(
                f"- v2 {comparison['v2']['strategy_name']} full_pf={comparison['v2']['full']['profit_factor']} full_dd={comparison['v2']['full']['max_drawdown']} full_trades={comparison['v2']['full']['total_trades']}"
            )
        if comparison["selected"]["candidate_name"]:
            lines.append(
                f"- selected full_pf={comparison['selected']['full']['profit_factor']} full_dd={comparison['selected']['full']['max_drawdown']} full_trades={comparison['selected']['full']['total_trades']}"
            )
        else:
            lines.append("- selected: baseline retained as reference because no candidate passed the controlled gate.")
        lines.extend(["", "## Estabilidad Temporal"])
        for row in selected["month_by_month"]:
            lines.append(
                f"- {row['month']}: trades={row['trades']} pf={row['profit_factor']} expectancy={row['expectancy']} negative={row['negative_month']}"
            )
        lines.extend(["", "## Estabilidad por Hora"])
        for row in selected["stability_by_hour"]:
            lines.append(
                f"- {row['hour_utc']:02d}:00: trades={row['trades']} share={row['trade_share']} pf={row['profit_factor']} expectancy={row['expectancy']}"
            )
        lines.extend(["", "## Riesgos Identificados"])
        for risk in payload["risks_identified"]:
            lines.append(f"- {risk}")
        return "\n".join(lines) + "\n"
