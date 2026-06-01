"""Stress test REACTION_ZONE_MANAGEMENT_OVERLAY_V1.

Research only. This freezes the entry set and tests whether the fast_03_be_08
management overlay survives realistic and pessimistic execution degradation.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "v0_compression_quality_reaction_zone_expansion_brain_trades.csv"
OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "management_overlay_v1_stress"
CORE_FILTERS = {"displacement_AGG", "fully_valid_non_overlap"}


@dataclass(frozen=True, slots=True)
class ManagementProfile:
    code: str = "fast_03_be_08"
    label: str = "REACTION_ZONE_MANAGEMENT_OVERLAY_V1"
    partial_trigger_r: float = 0.30
    partial_fraction: float = 0.40
    protect_trigger_r: float = 0.80
    protected_stop_r: float = 0.30
    target_r: float = 1.75
    stop_r: float = -1.01


@dataclass(frozen=True, slots=True)
class ExecutionScenario:
    code: str
    label: str
    partial_trigger_delay_r: float = 0.0
    protect_trigger_delay_r: float = 0.0
    partial_slippage_r: float = 0.0
    target_slippage_r: float = 0.0
    be_slippage_r: float = 0.0
    protected_stop_slippage_r: float = 0.0
    stop_slippage_r: float = 0.0
    partial_fill_ratio: float = 1.0
    trailing_success_ratio: float = 1.0
    partial_queue_fail_every: int = 0
    trailing_queue_fail_every: int = 0
    fast_reversal_buffer_r: float = 0.0


SCENARIOS = [
    ExecutionScenario(
        code="ideal_replay",
        label="Ideal replay: perfect partial, BE and trailing execution.",
    ),
    ExecutionScenario(
        code="realistic_mt5_execution",
        label="Realistic MT5: small delays, slippage, partial fill haircut and occasional queue misses.",
        partial_trigger_delay_r=0.05,
        protect_trigger_delay_r=0.05,
        partial_slippage_r=0.03,
        target_slippage_r=0.03,
        be_slippage_r=0.03,
        protected_stop_slippage_r=0.05,
        stop_slippage_r=0.03,
        partial_fill_ratio=0.85,
        trailing_success_ratio=0.90,
        partial_queue_fail_every=17,
        trailing_queue_fail_every=19,
        fast_reversal_buffer_r=0.04,
    ),
    ExecutionScenario(
        code="pessimistic_execution",
        label="Pessimistic execution: delayed partial/trailing, wider BE loss, partial failures and queue stress.",
        partial_trigger_delay_r=0.12,
        protect_trigger_delay_r=0.15,
        partial_slippage_r=0.07,
        target_slippage_r=0.08,
        be_slippage_r=0.08,
        protected_stop_slippage_r=0.12,
        stop_slippage_r=0.08,
        partial_fill_ratio=0.65,
        trailing_success_ratio=0.75,
        partial_queue_fail_every=7,
        trailing_queue_fail_every=9,
        fast_reversal_buffer_r=0.10,
    ),
    ExecutionScenario(
        code="fast_reversal_after_03r",
        label="Fast reversal after 0.3R: tests whether the partial is too close to real execution noise.",
        partial_trigger_delay_r=0.10,
        be_slippage_r=0.06,
        protected_stop_slippage_r=0.08,
        stop_slippage_r=0.04,
        partial_fill_ratio=0.70,
        partial_queue_fail_every=5,
        fast_reversal_buffer_r=0.12,
    ),
    ExecutionScenario(
        code="broker_degradation",
        label="Broker degradation: spread/slippage/latency stack in a non-ideal broker environment.",
        partial_trigger_delay_r=0.08,
        protect_trigger_delay_r=0.10,
        partial_slippage_r=0.10,
        target_slippage_r=0.12,
        be_slippage_r=0.12,
        protected_stop_slippage_r=0.15,
        stop_slippage_r=0.12,
        partial_fill_ratio=0.75,
        trailing_success_ratio=0.70,
        partial_queue_fail_every=6,
        trailing_queue_fail_every=8,
        fast_reversal_buffer_r=0.08,
    ),
]


def load_core_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("missing_filter") not in CORE_FILTERS:
                continue
            row["year"] = int(row["year"])
            row["hour_ny"] = int(row["hour_ny"])
            row["mfe_r"] = float(row["mfe_r"])
            row["mae_r"] = float(row["mae_r"])
            row["raw_r"] = float(row["raw_r"])
            rows.append(row)
    return rows


def queue_fails(index: int, every: int) -> bool:
    return every > 0 and (index + 1) % every == 0


def simulate_trade(
    *,
    row: dict[str, Any],
    index: int,
    profile: ManagementProfile,
    scenario: ExecutionScenario,
) -> dict[str, Any]:
    mfe = float(row["mfe_r"])
    raw_result = str(row["raw_result"]).upper()
    partial_trigger = profile.partial_trigger_r + scenario.partial_trigger_delay_r
    protect_trigger = profile.protect_trigger_r + scenario.protect_trigger_delay_r
    partial_queue_failed = queue_fails(index, scenario.partial_queue_fail_every)
    trailing_queue_failed = queue_fails(index, scenario.trailing_queue_fail_every)
    fast_reversal_failed = (
        scenario.fast_reversal_buffer_r > 0
        and partial_trigger <= mfe < partial_trigger + scenario.fast_reversal_buffer_r
        and raw_result != "TP"
    )
    partial_taken = mfe >= partial_trigger and not partial_queue_failed and not fast_reversal_failed
    partial_fraction = profile.partial_fraction * scenario.partial_fill_ratio if partial_taken else 0.0
    remaining_fraction = 1.0 - partial_fraction
    partial_exit_r = max(0.0, profile.partial_trigger_r - scenario.partial_slippage_r)
    target_r = profile.target_r - scenario.target_slippage_r
    be_stop_r = -scenario.be_slippage_r
    protected_stop_r = profile.protected_stop_r - scenario.protected_stop_slippage_r
    stop_r = profile.stop_r - scenario.stop_slippage_r
    trailing_success = not trailing_queue_failed and scenario.trailing_success_ratio > 0

    if raw_result == "TP":
        realized_r = partial_fraction * partial_exit_r + remaining_fraction * target_r
        final_result = "TP_WITH_MANAGEMENT"
    elif mfe >= protect_trigger and trailing_success:
        realized_r = partial_fraction * partial_exit_r + remaining_fraction * protected_stop_r
        final_result = "PROTECTED_STOP"
    elif partial_taken:
        realized_r = partial_fraction * partial_exit_r + remaining_fraction * be_stop_r
        final_result = "BE_AFTER_PARTIAL"
    else:
        realized_r = stop_r
        final_result = "SL"

    return {
        "year": row["year"],
        "signal_time": row["signal_time"],
        "entry_time": row["entry_time"],
        "side": row["side"],
        "session": row["session"],
        "atr_bucket": row["atr_bucket"],
        "missing_filter": row["missing_filter"],
        "scenario": scenario.code,
        "raw_result": raw_result,
        "mfe_r": mfe,
        "mae_r": float(row["mae_r"]),
        "partial_taken": partial_taken,
        "partial_queue_failed": partial_queue_failed,
        "partial_fill_ratio": scenario.partial_fill_ratio,
        "partial_fraction_effective": round(partial_fraction, 4),
        "be_moved": partial_taken,
        "protected_at_08r": bool(mfe >= protect_trigger and trailing_success),
        "trailing_queue_failed": trailing_queue_failed,
        "fast_reversal_failed": fast_reversal_failed,
        "final_result_after_management": final_result,
        "realized_r": round(realized_r, 5),
    }


def metrics(values: list[float]) -> dict[str, Any]:
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    losing_streak = 0
    max_losing_streak = 0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if value < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0
    return {
        "trades": len(values),
        "win_rate": round(len(wins) / len(values) * 100, 2) if values else 0.0,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else (math.inf if gross_win else 0.0),
        "expectancy_R": round(sum(values) / len(values), 4) if values else 0.0,
        "net_R": round(sum(values), 4),
        "max_drawdown_R": round(max_dd, 4),
        "losing_streak": max_losing_streak,
    }


def grouped_metrics(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for record in records:
        grouped[str(record[key])].append(float(record["realized_r"]))
    return {group: metrics(values) for group, values in sorted(grouped.items())}


def scenario_summary(records: list[dict[str, Any]], ideal_records: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(item["realized_r"]) for item in records]
    ideal_values = [float(item["realized_r"]) for item in ideal_records]
    metric = metrics(values)
    ideal_metric = metrics(ideal_values)
    ideal_by_key = {item["entry_time"]: float(item["realized_r"]) for item in ideal_records}
    protected_eligible = [item for item in records if float(item["mfe_r"]) >= 0.8 and item["raw_result"] != "TP"]
    protected_success = [item for item in protected_eligible if item["protected_at_08r"] and float(item["realized_r"]) > 0]
    be_eligible = [item for item in records if float(item["mfe_r"]) >= 0.3 and item["raw_result"] != "TP"]
    be_success = [item for item in be_eligible if item["be_moved"] and float(item["realized_r"]) > -0.15]
    protected_winners_lost = sum(
        1
        for item in records
        if ideal_by_key.get(item["entry_time"], 0.0) > 0 and float(item["realized_r"]) <= 0
    )
    return {
        "metrics": metric,
        "pf_degradation_pct": round((ideal_metric["profit_factor"] - metric["profit_factor"]) / ideal_metric["profit_factor"] * 100, 2)
        if ideal_metric["profit_factor"]
        else 0.0,
        "expectancy_degradation_pct": round(
            (ideal_metric["expectancy_R"] - metric["expectancy_R"]) / ideal_metric["expectancy_R"] * 100,
            2,
        )
        if ideal_metric["expectancy_R"]
        else 0.0,
        "dd_increase_pct": round(
            (metric["max_drawdown_R"] - ideal_metric["max_drawdown_R"]) / ideal_metric["max_drawdown_R"] * 100,
            2,
        )
        if ideal_metric["max_drawdown_R"]
        else 0.0,
        "protected_winners_lost": protected_winners_lost,
        "be_effectiveness": round(len(be_success) / len(be_eligible) * 100, 2) if be_eligible else 0.0,
        "trailing_survival": round(len(protected_success) / len(protected_eligible) * 100, 2) if protected_eligible else 0.0,
        "partial_taken": sum(1 for item in records if item["partial_taken"]),
        "partial_queue_failed": sum(1 for item in records if item["partial_queue_failed"]),
        "trailing_queue_failed": sum(1 for item in records if item["trailing_queue_failed"]),
        "fast_reversal_failed": sum(1 for item in records if item["fast_reversal_failed"]),
        "by_year": grouped_metrics(records, "year"),
        "by_session": grouped_metrics(records, "session"),
        "by_atr_bucket": grouped_metrics(records, "atr_bucket"),
    }


def classify(summaries: dict[str, Any]) -> str:
    realistic = summaries["realistic_mt5_execution"]["metrics"]
    pessimistic = summaries["pessimistic_execution"]["metrics"]
    realistic_dd = summaries["realistic_mt5_execution"]["dd_increase_pct"]
    pessimistic_dd = summaries["pessimistic_execution"]["dd_increase_pct"]
    if (
        pessimistic["profit_factor"] >= 1.45
        and pessimistic["expectancy_R"] >= 0.15
        and pessimistic_dd <= 75
        and summaries["pessimistic_execution"]["trailing_survival"] >= 65
    ):
        return "ROBUST MANAGEMENT"
    if (
        realistic["profit_factor"] >= 1.45
        and realistic["expectancy_R"] >= 0.15
        and realistic_dd <= 60
        and pessimistic["profit_factor"] >= 1.15
        and pessimistic["expectancy_R"] > 0.03
    ):
        return "ACCEPTABLE MANAGEMENT"
    return "FRAGILE MANAGEMENT"


def fragile_causes_and_adjustments(summaries: dict[str, Any]) -> dict[str, Any]:
    pessimistic = summaries["pessimistic_execution"]
    causes: list[str] = []
    if pessimistic["partial_queue_failed"] > 40:
        causes.append("partial_execution_queue_failure")
    if pessimistic["fast_reversal_failed"] > 40:
        causes.append("fast_reversal_after_0_3R")
    if pessimistic["trailing_survival"] < 60:
        causes.append("trailing_execution_failure")
    if pessimistic["metrics"]["profit_factor"] < 1.2:
        causes.append("cost_degradation_kills_pf")
    if pessimistic["dd_increase_pct"] > 100:
        causes.append("drawdown_expands_under_execution_stress")

    adjustments = []
    if "fast_reversal_after_0_3R" in causes:
        adjustments.append("Require a small post-partial confirmation buffer before assuming 0.3R protection is executable.")
    if "partial_execution_queue_failure" in causes:
        adjustments.append("Use broker-confirmed partial fill state before moving the remaining stop to BE.")
    if "trailing_execution_failure" in causes:
        adjustments.append("Move protection with a conservative market-safe buffer instead of relying on instant trailing at 0.8R.")
    if not adjustments:
        adjustments.append("Keep V1 unchanged but require demo dry/live telemetry before enabling real demo orders.")
    return {"causes": causes[:5], "max_3_defensive_adjustments": adjustments[:3]}


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# REACTION_ZONE_MANAGEMENT_OVERLAY_V1 Stress Test",
        "",
        f"- status: {payload['status']}",
        f"- baseline: `{payload['baseline']}`",
        f"- profile: `{payload['profile']['code']}`",
        f"- classification: `{payload['classification']}`",
        f"- generated_at_utc: {payload['generated_at_utc']}",
        "",
        "## Scenario Comparison",
        "",
        "| Scenario | Trades | WR | PF | Exp R | Net R | DD R | PF Deg | Exp Deg | DD Inc | BE Eff | Trail Survival | Protected Winners Lost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in payload["scenarios"]:
        summary = payload["scenario_summaries"][scenario["code"]]
        metric = summary["metrics"]
        lines.append(
            "| {scenario} | {trades} | {wr} | {pf} | {exp} | {net} | {dd} | {pf_deg}% | {exp_deg}% | {dd_inc}% | {be}% | {trail}% | {lost} |".format(
                scenario=scenario["code"],
                trades=metric["trades"],
                wr=metric["win_rate"],
                pf=metric["profit_factor"],
                exp=metric["expectancy_R"],
                net=metric["net_R"],
                dd=metric["max_drawdown_R"],
                pf_deg=summary["pf_degradation_pct"],
                exp_deg=summary["expectancy_degradation_pct"],
                dd_inc=summary["dd_increase_pct"],
                be=summary["be_effectiveness"],
                trail=summary["trailing_survival"],
                lost=summary["protected_winners_lost"],
            )
        )

    lines.extend(
        [
            "",
            "## Execution Failure Counters",
            "",
            "| Scenario | Partial Taken | Partial Queue Failed | Trailing Queue Failed | Fast Reversal Failed |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for scenario in payload["scenarios"]:
        summary = payload["scenario_summaries"][scenario["code"]]
        lines.append(
            f"| {scenario['code']} | {summary['partial_taken']} | {summary['partial_queue_failed']} | "
            f"{summary['trailing_queue_failed']} | {summary['fast_reversal_failed']} |"
        )

    lines.extend(
        [
            "",
            "## Classification Logic",
            "",
            "- `ROBUST MANAGEMENT`: pessimistic execution keeps PF >= 1.45, expectancy >= 0.15R, DD increase <= 75%, trailing survival >= 65%.",
            "- `ACCEPTABLE MANAGEMENT`: realistic execution remains strong and pessimistic execution stays positive.",
            "- `FRAGILE MANAGEMENT`: execution degradation breaks PF/expectancy or expands drawdown too much.",
            "",
            "## Fragility Review",
            "",
        ]
    )
    causes = payload["fragility_review"]["causes"]
    if causes:
        for cause in causes:
            lines.append(f"- cause: {cause}")
    else:
        lines.append("- cause: none_detected_under_current_thresholds")
    for adjustment in payload["fragility_review"]["max_3_defensive_adjustments"]:
        lines.append(f"- defensive_adjustment: {adjustment}")

    lines.extend(
        [
            "",
            "## Operational Read",
            "",
            "- No live approval.",
            "- No scaling.",
            "- No entry logic changed.",
            "- This research uses MFE/MAE replay, not broker tick-by-tick fills.",
            "- Next validation should be demo dry/live telemetry with actual spread, partial fill and stop-modification logs.",
            "",
        ]
    )
    return "\n".join(lines)


def write_records(path: Path, records: list[dict[str, Any]]) -> None:
    fields = list(records[0].keys()) if records else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    rows = load_core_rows()
    profile = ManagementProfile()
    scenario_records: dict[str, list[dict[str, Any]]] = {}
    for scenario in SCENARIOS:
        scenario_records[scenario.code] = [
            simulate_trade(row=row, index=index, profile=profile, scenario=scenario)
            for index, row in enumerate(rows)
        ]

    ideal = scenario_records["ideal_replay"]
    scenario_summaries = {
        scenario.code: scenario_summary(records, ideal)
        for scenario, records in ((scenario, scenario_records[scenario.code]) for scenario in SCENARIOS)
    }
    classification = classify(scenario_summaries)
    fragility = fragile_causes_and_adjustments(scenario_summaries)
    payload = {
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "baseline": "MTF_REAL_H4_FIXED_BASELINE",
        "frozen_strategy": "REACTION_ZONE_MANAGEMENT_OVERLAY_V1",
        "profile": asdict(profile),
        "source": str(SOURCE.resolve()),
        "core_filters": sorted(CORE_FILTERS),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scenarios": [asdict(scenario) for scenario in SCENARIOS],
        "scenario_summaries": scenario_summaries,
        "classification": classification,
        "fragility_review": fragility,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "reaction_zone_management_overlay_v1_stress.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "reaction_zone_management_overlay_v1_stress.md").write_text(render_report(payload), encoding="utf-8")
    for scenario_code, records in scenario_records.items():
        write_records(OUTPUT_DIR / f"{scenario_code}_managed_trades.csv", records)

    print(
        json.dumps(
            {
                "classification": classification,
                "scenario_summaries": {
                    code: {
                        "metrics": summary["metrics"],
                        "pf_degradation_pct": summary["pf_degradation_pct"],
                        "expectancy_degradation_pct": summary["expectancy_degradation_pct"],
                        "dd_increase_pct": summary["dd_increase_pct"],
                        "protected_winners_lost": summary["protected_winners_lost"],
                        "be_effectiveness": summary["be_effectiveness"],
                        "trailing_survival": summary["trailing_survival"],
                    }
                    for code, summary in scenario_summaries.items()
                },
                "fragility_review": fragility,
                "report": str((OUTPUT_DIR / "reaction_zone_management_overlay_v1_stress.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
