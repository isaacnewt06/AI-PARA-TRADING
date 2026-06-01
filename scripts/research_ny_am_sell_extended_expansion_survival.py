"""NY AM SELL extended-expansion survival research.

Research only. No live logic or M5 detector is modified. This script isolates:

- SELL
- NY_AM
- extended_expansion
- m5_body_mid_5m
- realistic MT5 execution
- reduced-risk research context

Then it stresses execution conditions to estimate whether the apparent edge can
survive spread, slippage, latency, queue delay, partial fill, and spike scenarios.
"""

from __future__ import annotations

import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import research_ny_am_entry_statistical_robustness as stat_audit  # noqa: E402
from scripts import research_reaction_entry_optimization as entry_research  # noqa: E402


INPUT_RECORDS = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "ny_am_only_entry_optimization"
    / "ny_am_only_entry_optimization_records.csv"
)
OUTPUT_DIR = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "ny_am_sell_extended_expansion_survival"
)
RULE = "m5_body_mid_5m"
BOOTSTRAP_ROUNDS = 5000
MONTE_CARLO_ROUNDS = 5000
RANDOM_SEED = 5152026


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_research()
    (OUTPUT_DIR / "ny_am_sell_extended_expansion_survival.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "ny_am_sell_extended_expansion_survival.md").write_text(render_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "research": payload["research"],
                "classification": payload["classification"],
                "sample": payload["sample"],
                "base_metrics": payload["base_metrics"],
                "bootstrap": payload["bootstrap"],
                "tail_risk": payload["tail_risk"],
                "edge_persistence": payload["edge_persistence"],
                "report": str((OUTPUT_DIR / "ny_am_sell_extended_expansion_survival.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_research() -> dict[str, Any]:
    source_candidates = source_extended_candidates()
    records = load_filtered_records()
    values = [float(row["realized_R"]) for row in records]
    payload = {
        "research": "NY_AM_SELL_EXTENDED_EXPANSION_SURVIVAL_RESEARCH",
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "detector": "M5 displacement_plus_wick_v1 frozen",
        "rule": RULE,
        "filters": {
            "side": "SELL",
            "session": "ny_am",
            "expansion_subtype": "extended_expansion",
            "execution": "realistic_mt5",
            "risk": "reduced",
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample": {
            "source_candidates": len(source_candidates),
            "filled_records": len(records),
            "missed_fills": max(0, len(source_candidates) - len(records)),
            "fill_probability_pct": round(len(records) / len(source_candidates) * 100.0, 2)
            if source_candidates
            else 0.0,
            "years_present": sorted({int(row["year"]) for row in records}),
            "months_present": sorted({str(row["month"]) for row in records}),
        },
        "base_metrics": metric_block(values),
        "monthly_consistency": breakdown(records, "month"),
        "yearly_consistency": breakdown(records, "year"),
        "spread_degradation_curve": degradation_curve(records, "spread", [0.0, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30]),
        "slippage_degradation_curve": degradation_curve(records, "slippage", [0.0, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]),
        "latency_degradation": latency_degradation(records),
        "queue_delay": queue_delay_degradation(records),
        "partial_fills": partial_fill_degradation(records),
        "spread_spikes": spread_spike_monte_carlo(records),
        "volatility_spikes": volatility_spike_monte_carlo(records),
        "execution_failure_scenarios": execution_failure_scenarios(records),
        "regime_transitions": regime_transition_proxy(records),
        "bootstrap": bootstrap_expectancy(values),
        "tail_risk": monte_carlo_tail(values),
        "walk_forward": walk_forward(records),
    }
    payload["edge_persistence"] = edge_persistence(payload)
    payload["classification"] = classify(payload)
    return payload


def source_extended_candidates() -> list[dict[str, Any]]:
    rows = []
    for row in entry_research.load_source_trades():
        if (
            str(row.get("side", "")).upper() == "SELL"
            and str(row.get("session", "")).lower() == "ny_am"
            and str(row.get("expansion_subtype", "")).lower() == "extended_expansion"
        ):
            rows.append(row)
    return rows


def load_filtered_records() -> list[dict[str, Any]]:
    with INPUT_RECORDS.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    source_map = {source_key(row): row for row in entry_research.load_source_trades()}
    output = []
    for row in rows:
        if row.get("rule") != RULE or row.get("side") != "SELL" or row.get("session") != "ny_am":
            continue
        parsed = normalize(row)
        source = source_map.get(source_key(parsed), {})
        if str(source.get("expansion_subtype", "")).lower() != "extended_expansion":
            continue
        parsed["expansion_subtype"] = source.get("expansion_subtype", "UNKNOWN")
        parsed["continuation_quality"] = source.get("continuation_quality", "UNKNOWN")
        parsed["atr_bucket"] = source.get("atr_bucket", "UNKNOWN")
        parsed["body_pct"] = float(source.get("body_pct", 0.0) or 0.0)
        parsed["wick_rejection_pct"] = float(source.get("wick_rejection_pct", 0.0) or 0.0)
        parsed["confidence"] = float(source.get("confidence", 0.0) or 0.0)
        parsed["mtf_score"] = float(source.get("mtf_score", 0.0) or 0.0)
        output.append(parsed)
    return sorted(output, key=lambda item: item["signal_dt"])


def normalize(row: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = dict(row)
    parsed["year"] = int(float(row["year"]))
    parsed["risk"] = float(row["risk"])
    parsed["realized_R"] = float(row["realized_R"])
    parsed["mfe_r"] = float(row["mfe_r"])
    parsed["mae_r"] = float(row["mae_r"])
    parsed["mae_reduction_R"] = float(row["mae_reduction_R"])
    parsed["cost_r"] = float(row["cost_r"])
    parsed["entry_improvement_R_original"] = float(row["entry_improvement_R_original"])
    parsed["duration_minutes"] = int(float(row["duration_minutes"]))
    parsed["signal_dt"] = datetime.fromisoformat(row["signal_time"])
    parsed["month"] = parsed["signal_dt"].strftime("%Y-%m")
    parsed["partial_taken_bool"] = str(row.get("partial_taken", "")).lower() == "true"
    parsed["protected_bool"] = str(row.get("protected", "")).lower() == "true"
    return parsed


def source_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (int(row["year"]), str(row["signal_time"]), str(row["side"]).upper())


def metric_block(values: list[float]) -> dict[str, Any]:
    base = entry_research.metrics(values)
    if values:
        sorted_values = sorted(values)
        base.update(
            {
                "p05_R": round(percentile(sorted_values, 0.05), 4),
                "p50_R": round(percentile(sorted_values, 0.50), 4),
                "p95_R": round(percentile(sorted_values, 0.95), 4),
                "tail_loss_R": round(min(values), 4),
            }
        )
    else:
        base.update({"p05_R": 0.0, "p50_R": 0.0, "p95_R": 0.0, "tail_loss_R": 0.0})
    return base


def breakdown(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in records:
        grouped[str(row.get(key, "UNKNOWN"))].append(float(row["realized_R"]))
    return {bucket: metric_block(values) for bucket, values in sorted(grouped.items())}


def degradation_curve(records: list[dict[str, Any]], kind: str, extra_costs: list[float]) -> dict[str, Any]:
    output = {}
    for cost in extra_costs:
        values = [float(row["realized_R"]) - cost / max(float(row["risk"]), 1e-9) for row in records]
        key = f"{kind}_plus_{cost:.2f}"
        output[key] = metric_block(values)
    return output


def latency_degradation(records: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = {
        "latency_0ms": 0.0,
        "latency_250ms": 0.015,
        "latency_500ms": 0.025,
        "latency_1000ms": 0.045,
        "latency_2000ms": 0.080,
    }
    return {name: metric_block([float(row["realized_R"]) - penalty for row in records]) for name, penalty in scenarios.items()}


def queue_delay_degradation(records: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for delay_m1 in (0, 1, 2, 3):
        values = []
        missed = 0
        for row in records:
            if delay_m1 > 0 and int(row["duration_minutes"]) <= delay_m1:
                missed += 1
                continue
            values.append(float(row["realized_R"]) - delay_m1 * 0.04)
        output[f"queue_delay_{delay_m1}m"] = {**metric_block(values), "missed_by_delay": missed}
    return output


def partial_fill_degradation(records: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for fill_ratio in (1.0, 0.75, 0.50, 0.25):
        values = []
        for row in records:
            value = float(row["realized_R"])
            if row["partial_taken_bool"]:
                value -= (1.0 - fill_ratio) * 0.12
            values.append(value)
        output[f"partial_fill_{fill_ratio:.2f}"] = metric_block(values)
    return output


def spread_spike_monte_carlo(records: list[dict[str, Any]]) -> dict[str, Any]:
    return spike_monte_carlo(records, name="spread_spike", probability=0.20, penalty_r=0.18)


def volatility_spike_monte_carlo(records: list[dict[str, Any]]) -> dict[str, Any]:
    return spike_monte_carlo(records, name="volatility_spike", probability=0.15, penalty_r=0.25)


def spike_monte_carlo(records: list[dict[str, Any]], *, name: str, probability: float, penalty_r: float) -> dict[str, Any]:
    rng = random.Random(RANDOM_SEED + int(probability * 1000) + int(penalty_r * 1000))
    exp_values = []
    dd_values = []
    pf_values = []
    for _ in range(MONTE_CARLO_ROUNDS):
        sample = []
        for row in records:
            value = float(row["realized_R"])
            if rng.random() < probability:
                value -= penalty_r
            sample.append(value)
        metric = metric_block(sample)
        exp_values.append(metric["expectancy_R"])
        dd_values.append(metric["max_drawdown_R"])
        pf_values.append(metric["profit_factor"])
    exp_values.sort()
    dd_values.sort()
    pf_values.sort()
    return {
        "scenario": name,
        "probability": probability,
        "penalty_R": penalty_r,
        "median_expectancy_R": round(percentile(exp_values, 0.50), 4),
        "p10_expectancy_R": round(percentile(exp_values, 0.10), 4),
        "probability_expectancy_gt_0": round(sum(1 for item in exp_values if item > 0) / len(exp_values), 4),
        "p90_dd_R": round(percentile(dd_values, 0.90), 4),
        "median_pf": round(percentile(pf_values, 0.50), 4),
    }


def execution_failure_scenarios(records: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = {
        "one_random_missed_fill": 1,
        "two_random_missed_fills": 2,
        "three_random_missed_fills": 3,
    }
    rng = random.Random(RANDOM_SEED + 77)
    output = {}
    for name, misses in scenarios.items():
        exp_values = []
        for _ in range(MONTE_CARLO_ROUNDS):
            sample = list(records)
            if len(sample) > misses:
                remove = set(rng.sample(range(len(sample)), misses))
                values = [float(row["realized_R"]) for idx, row in enumerate(sample) if idx not in remove]
            else:
                values = []
            exp_values.append(metric_block(values)["expectancy_R"])
        exp_values.sort()
        output[name] = {
            "median_expectancy_R": round(percentile(exp_values, 0.50), 4),
            "p10_expectancy_R": round(percentile(exp_values, 0.10), 4),
            "probability_expectancy_gt_0": round(sum(1 for item in exp_values if item > 0) / len(exp_values), 4),
        }
    return output


def regime_transition_proxy(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_exit = breakdown(records, "exit_reason")
    weak_reaction = [row for row in records if float(row["mfe_r"]) < 0.80 or str(row["exit_reason"]) in {"SL", "BE_STOP"}]
    strong_reaction = [row for row in records if float(row["mfe_r"]) >= 0.80 and str(row["exit_reason"]) in {"TARGET", "PROTECTED_STOP"}]
    return {
        "all_records_are_extended_expansion": True,
        "exit_reason_distribution": by_exit,
        "weak_reaction_count": len(weak_reaction),
        "strong_reaction_count": len(strong_reaction),
        "weak_reaction_metrics": metric_block([float(row["realized_R"]) for row in weak_reaction]),
        "strong_reaction_metrics": metric_block([float(row["realized_R"]) for row in strong_reaction]),
    }


def bootstrap_expectancy(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"ci_5_R": 0.0, "ci_95_R": 0.0, "probability_expectancy_gt_0": 0.0}
    rng = random.Random(RANDOM_SEED + len(values))
    means = []
    for _ in range(BOOTSTRAP_ROUNDS):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        means.append(sum(sample) / len(sample))
    means.sort()
    return {
        "mean_expectancy_R": round(sum(means) / len(means), 4),
        "ci_5_R": round(percentile(means, 0.05), 4),
        "ci_95_R": round(percentile(means, 0.95), 4),
        "probability_expectancy_gt_0": round(sum(1 for item in means if item > 0) / len(means), 4),
    }


def monte_carlo_tail(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"p90_dd_R": 0.0, "p95_losing_streak": 0, "risk_negative_terminal": 0.0}
    rng = random.Random(RANDOM_SEED + 909)
    dds = []
    streaks = []
    negative = 0
    for _ in range(MONTE_CARLO_ROUNDS):
        sample = list(values)
        rng.shuffle(sample)
        metric = entry_research.metrics(sample)
        dds.append(metric["max_drawdown_R"])
        streaks.append(metric["losing_streak"])
        negative += 1 if sum(sample) < 0 else 0
    dds.sort()
    streaks.sort()
    return {
        "p90_dd_R": round(percentile(dds, 0.90), 4),
        "p95_losing_streak": int(percentile([float(item) for item in streaks], 0.95)),
        "risk_negative_terminal": round(negative / MONTE_CARLO_ROUNDS, 4),
    }


def walk_forward(records: list[dict[str, Any]]) -> dict[str, Any]:
    steps = []
    for test_year in (2024, 2025, 2026):
        train = [row for row in records if int(row["year"]) < test_year]
        test = [row for row in records if int(row["year"]) == test_year]
        if not train or not test:
            continue
        steps.append(
            {
                "test_year": test_year,
                "train_metrics": metric_block([float(row["realized_R"]) for row in train]),
                "test_metrics": metric_block([float(row["realized_R"]) for row in test]),
            }
        )
    combined_test_values = [
        float(row["realized_R"])
        for row in records
        if int(row["year"]) in {step["test_year"] for step in steps}
    ]
    return {"steps": steps, "combined_test_metrics": metric_block(combined_test_values)}


def edge_persistence(payload: dict[str, Any]) -> dict[str, Any]:
    base = payload["base_metrics"]
    stress_checks = [
        payload["spread_degradation_curve"]["spread_plus_0.10"]["expectancy_R"] > 0,
        payload["slippage_degradation_curve"]["slippage_plus_0.10"]["expectancy_R"] > 0,
        payload["latency_degradation"]["latency_1000ms"]["expectancy_R"] > 0,
        payload["partial_fills"]["partial_fill_0.50"]["expectancy_R"] > 0,
        payload["spread_spikes"]["probability_expectancy_gt_0"] >= 0.70,
        payload["volatility_spikes"]["probability_expectancy_gt_0"] >= 0.70,
    ]
    monthly = payload["monthly_consistency"]
    positive_months = sum(1 for item in monthly.values() if item["expectancy_R"] > 0)
    negative_months = sum(1 for item in monthly.values() if item["expectancy_R"] < 0)
    return {
        "base_positive": base["expectancy_R"] > 0 and base["profit_factor"] > 1.2,
        "stress_checks_passed": sum(1 for item in stress_checks if item),
        "stress_checks_total": len(stress_checks),
        "positive_months": positive_months,
        "negative_months": negative_months,
        "monthly_positive_ratio": round(positive_months / (positive_months + negative_months), 4)
        if positive_months + negative_months
        else 0.0,
    }


def classify(payload: dict[str, Any]) -> str:
    sample = payload["sample"]
    base = payload["base_metrics"]
    bootstrap = payload["bootstrap"]
    persistence = payload["edge_persistence"]
    spread_020 = payload["spread_degradation_curve"]["spread_plus_0.20"]
    latency_1000 = payload["latency_degradation"]["latency_1000ms"]
    if sample["filled_records"] < 20:
        if base["expectancy_R"] > 0 and persistence["stress_checks_passed"] >= 4:
            return "THIN_EDGE"
        return "NOT_LIVE_READY"
    if bootstrap["probability_expectancy_gt_0"] < 0.70:
        return "RESEARCH_CONTINUES"
    if spread_020["expectancy_R"] < 0 or latency_1000["expectancy_R"] < 0:
        return "EXECUTION_SENSITIVE"
    if persistence["stress_checks_passed"] >= 5 and persistence["monthly_positive_ratio"] >= 0.60:
        return "SURVIVES_REALISTICALLY"
    return "RESEARCH_CONTINUES"


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, math.floor((len(sorted_values) - 1) * pct)))
    return sorted_values[idx]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# NY_AM_SELL_EXTENDED_EXPANSION_SURVIVAL_RESEARCH",
        "",
        f"- status: `{payload['status']}`",
        f"- detector: `{payload['detector']}`",
        f"- rule: `{payload['rule']}`",
        f"- classification: `{payload['classification']}`",
        f"- source_candidates: `{payload['sample']['source_candidates']}`",
        f"- filled_records: `{payload['sample']['filled_records']}`",
        f"- fill_probability: `{payload['sample']['fill_probability_pct']}%`",
        "",
        "## Base Edge",
        "",
        render_metric_table({"base": payload["base_metrics"]}),
        "",
        "## Bootstrap And Tail Risk",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| expectancy_ci_5_R | {payload['bootstrap']['ci_5_R']} |",
        f"| expectancy_ci_95_R | {payload['bootstrap']['ci_95_R']} |",
        f"| probability_expectancy_gt_0 | {payload['bootstrap']['probability_expectancy_gt_0']} |",
        f"| p90_dd_R | {payload['tail_risk']['p90_dd_R']} |",
        f"| p95_losing_streak | {payload['tail_risk']['p95_losing_streak']} |",
        f"| risk_negative_terminal | {payload['tail_risk']['risk_negative_terminal']} |",
        "",
        "## Spread Degradation Curve",
        "",
        render_metric_table(payload["spread_degradation_curve"]),
        "",
        "## Slippage Degradation Curve",
        "",
        render_metric_table(payload["slippage_degradation_curve"]),
        "",
        "## Latency Degradation",
        "",
        render_metric_table(payload["latency_degradation"]),
        "",
        "## Queue Delay",
        "",
        render_metric_table(payload["queue_delay"]),
        "",
        "## Partial Fill Degradation",
        "",
        render_metric_table(payload["partial_fills"]),
        "",
        "## Spike Scenarios",
        "",
        "| Scenario | Median Exp R | P10 Exp R | Prob Exp > 0 | P90 DD | Median PF |",
        "|---|---:|---:|---:|---:|---:|",
        spike_row(payload["spread_spikes"]),
        spike_row(payload["volatility_spikes"]),
        "",
        "## Execution Failure Scenarios",
        "",
        "| Scenario | Median Exp R | P10 Exp R | Prob Exp > 0 |",
        "|---|---:|---:|---:|",
    ]
    for scenario, item in payload["execution_failure_scenarios"].items():
        lines.append(
            f"| {scenario} | {item['median_expectancy_R']} | {item['p10_expectancy_R']} | "
            f"{item['probability_expectancy_gt_0']} |"
        )
    lines.extend(
        [
            "",
            "## Monthly Consistency",
            "",
            render_metric_table(payload["monthly_consistency"]),
            "",
            "## Walk Forward Stability",
            "",
            "| Test Year | Train Trades | Train PF | Train Exp R | Test Trades | Test PF | Test Exp R | Test DD |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for step in payload["walk_forward"]["steps"]:
        train = step["train_metrics"]
        test = step["test_metrics"]
        lines.append(
            f"| {step['test_year']} | {train['trades']} | {train['profit_factor']} | {train['expectancy_R']} | "
            f"{test['trades']} | {test['profit_factor']} | {test['expectancy_R']} | {test['max_drawdown_R']} |"
        )
    combined = payload["walk_forward"]["combined_test_metrics"]
    lines.extend(
        [
            f"| ALL | - | - | - | {combined['trades']} | {combined['profit_factor']} | {combined['expectancy_R']} | {combined['max_drawdown_R']} |",
            "",
            "## Edge Persistence",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| stress_checks_passed | {payload['edge_persistence']['stress_checks_passed']} / {payload['edge_persistence']['stress_checks_total']} |",
            f"| positive_months | {payload['edge_persistence']['positive_months']} |",
            f"| negative_months | {payload['edge_persistence']['negative_months']} |",
            f"| monthly_positive_ratio | {payload['edge_persistence']['monthly_positive_ratio']} |",
        ]
    )
    return "\n".join(lines) + "\n"


def render_metric_table(items: dict[str, Any]) -> str:
    lines = [
        "| Scenario | Trades | WR | PF | Exp R | Net R | DD | Losing Streak | Tail Loss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metric in items.items():
        lines.append(
            f"| {name} | {metric.get('trades', 0)} | {metric.get('win_rate', 0.0)} | {metric.get('profit_factor', 0.0)} | "
            f"{metric.get('expectancy_R', 0.0)} | {metric.get('net_R', 0.0)} | {metric.get('max_drawdown_R', 0.0)} | "
            f"{metric.get('losing_streak', 0)} | {metric.get('tail_loss_R', 0.0)} |"
        )
    return "\n".join(lines)


def spike_row(item: dict[str, Any]) -> str:
    return (
        f"| {item['scenario']} | {item['median_expectancy_R']} | {item['p10_expectancy_R']} | "
        f"{item['probability_expectancy_gt_0']} | {item['p90_dd_R']} | {item['median_pf']} |"
    )


if __name__ == "__main__":
    main()
