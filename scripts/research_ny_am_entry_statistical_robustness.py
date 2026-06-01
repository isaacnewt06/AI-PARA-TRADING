"""Statistical robustness audit for NY AM executable M1 entries.

Research only. This script reads the already generated NY_AM_ONLY records and
audits whether the two best-looking rules have enough statistical robustness to
be considered beyond an interesting sample.
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
from statistics import mean, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    / "ny_am_entry_statistical_robustness"
)
RULES = ("limit_retrace_30r_3m", "m5_body_mid_5m")
YEARS = (2023, 2024, 2025, 2026)
BOOTSTRAP_ROUNDS = 5000
MONTE_CARLO_ROUNDS = 5000
RANDOM_SEED = 260515


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_audit()
    (OUTPUT_DIR / "ny_am_entry_statistical_robustness.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "ny_am_entry_statistical_robustness.md").write_text(render_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "research": payload["research"],
                "overall_classification": payload["overall_classification"],
                "best_rule": payload["best_rule"],
                "rules": {
                    rule: {
                        "classification": data["classification"],
                        "trades": data["aggregate"]["trades"],
                        "profit_factor": data["aggregate"]["profit_factor"],
                        "expectancy_R": data["aggregate"]["expectancy_R"],
                        "probability_edge_gt_0": data["bootstrap"]["probability_edge_gt_0"],
                        "robustness_score": data["robustness_score"],
                        "overfit_probability": data["overfit_probability"],
                        "sample_sufficiency": data["sample_sufficiency"],
                    }
                    for rule, data in payload["rule_audits"].items()
                },
                "report": str((OUTPUT_DIR / "ny_am_entry_statistical_robustness.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_audit() -> dict[str, Any]:
    records = enrich_records(load_records())
    rule_audits = {rule: audit_rule([row for row in records if row["rule"] == rule], rule) for rule in RULES}
    walk_forward = audit_walk_forward(records)
    best_rule = max(rule_audits, key=lambda rule: rule_audits[rule]["robustness_score"]) if rule_audits else "none"
    return {
        "research": "NY_AM_ENTRY_STATISTICAL_ROBUSTNESS",
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "detector": "M5 displacement_plus_wick_v1 frozen",
        "session_filter": "ny_am",
        "rules": RULES,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_records": str(INPUT_RECORDS.resolve()),
        "bootstrap_rounds": BOOTSTRAP_ROUNDS,
        "monte_carlo_rounds": MONTE_CARLO_ROUNDS,
        "rule_audits": rule_audits,
        "walk_forward": walk_forward,
        "best_rule": best_rule,
        "overall_classification": classify_overall(rule_audits, walk_forward),
        "notes": [
            "Cost sensitivity adjusts realized R by additional price cost divided by each trade risk.",
            "Bootstrap and Monte Carlo use deterministic seed for reproducibility.",
            "2026 is partial, so it is treated as evidence but not as a full-year confirmation.",
        ],
    }


def load_records() -> list[dict[str, Any]]:
    if not INPUT_RECORDS.exists():
        raise FileNotFoundError(f"Missing NY AM records: {INPUT_RECORDS}")
    with INPUT_RECORDS.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [normalize_row(row) for row in rows if row.get("rule") in RULES]


def normalize_row(row: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = dict(row)
    parsed["year"] = int(float(row["year"]))
    parsed["hour_ny"] = int(float(row["hour_ny"]))
    parsed["risk"] = float(row["risk"])
    parsed["realized_R"] = float(row["realized_R"])
    parsed["mfe_r"] = float(row["mfe_r"])
    parsed["mae_r"] = float(row["mae_r"])
    parsed["mae_reduction_R"] = float(row["mae_reduction_R"])
    parsed["entry_improvement_R_original"] = float(row["entry_improvement_R_original"])
    parsed["cost_r"] = float(row["cost_r"])
    parsed["signal_dt"] = datetime.fromisoformat(row["signal_time"])
    parsed["month"] = parsed["signal_dt"].strftime("%Y-%m")
    return parsed


def enrich_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_map = {}
    for row in entry_research.load_source_trades():
        key = source_key(row)
        source_map[key] = row
    for row in records:
        source = source_map.get(source_key(row), {})
        row["expansion_subtype"] = source.get("expansion_subtype", "UNKNOWN")
        row["continuation_quality"] = source.get("continuation_quality", "UNKNOWN")
        row["atr_bucket"] = source.get("atr_bucket", "UNKNOWN")
        row["compression_ok"] = str(source.get("compression_ok", "UNKNOWN"))
        row["body_pct"] = float(source.get("body_pct", 0.0) or 0.0)
        row["wick_rejection_pct"] = float(source.get("wick_rejection_pct", 0.0) or 0.0)
        row["mtf_score"] = float(source.get("mtf_score", 0.0) or 0.0)
        row["confidence"] = float(source.get("confidence", 0.0) or 0.0)
    return records


def source_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (int(row["year"]), str(row["signal_time"]), str(row["side"]).upper())


def audit_rule(records: list[dict[str, Any]], rule: str) -> dict[str, Any]:
    values = [float(row["realized_R"]) for row in records]
    aggregate = metric_block(records)
    yearly = breakdown(records, "year")
    monthly = breakdown(records, "month")
    direction = breakdown(records, "side")
    regime = breakdown(records, "expansion_subtype")
    atr = breakdown(records, "atr_bucket")
    continuation = breakdown(records, "continuation_quality")
    clusters = clustering(records)
    sensitivity = cost_sensitivity(records)
    bootstrap = bootstrap_expectancy(values)
    monte_carlo = monte_carlo_shuffle(values)
    variance = expectancy_variance(records)
    sufficiency = sample_sufficiency(records)
    robustness_score = score_rule(
        aggregate=aggregate,
        yearly=yearly,
        direction=direction,
        bootstrap=bootstrap,
        sensitivity=sensitivity,
        sufficiency=sufficiency,
    )
    overfit_probability = overfit_probability_estimate(
        yearly=yearly,
        monthly=monthly,
        direction=direction,
        bootstrap=bootstrap,
        sufficiency=sufficiency,
    )
    return {
        "rule": rule,
        "aggregate": aggregate,
        "yearly": yearly,
        "monthly": monthly,
        "direction": direction,
        "regime": regime,
        "atr_bucket": atr,
        "continuation_quality": continuation,
        "clustering": clusters,
        "cost_sensitivity": sensitivity,
        "bootstrap": bootstrap,
        "monte_carlo": monte_carlo,
        "expectancy_variance": variance,
        "sample_sufficiency": sufficiency,
        "robustness_score": robustness_score,
        "overfit_probability": overfit_probability,
        "classification": classify_rule(
            aggregate=aggregate,
            yearly=yearly,
            bootstrap=bootstrap,
            robustness_score=robustness_score,
            overfit_probability=overfit_probability,
            sufficiency=sufficiency,
        ),
    }


def metric_block(records: list[dict[str, Any]], value_key: str = "realized_R") -> dict[str, Any]:
    values = [float(row[value_key]) for row in records]
    base = entry_research.metrics(values)
    return {
        **base,
        "avg_mfe_R": round(avg([float(row["mfe_r"]) for row in records]), 4),
        "avg_mae_R": round(avg([float(row["mae_r"]) for row in records]), 4),
        "avg_mae_reduction_R": round(avg([float(row["mae_reduction_R"]) for row in records]), 4),
        "avg_entry_improvement_R": round(avg([float(row["entry_improvement_R_original"]) for row in records]), 4),
        "avg_cost_R": round(avg([float(row["cost_r"]) for row in records]), 4),
        "expectancy_std_R": round(pstdev(values), 4) if len(values) > 1 else 0.0,
    }


def breakdown(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[str(row.get(key, "UNKNOWN"))].append(row)
    return {bucket: metric_block(items) for bucket, items in sorted(grouped.items())}


def clustering(records: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: row["signal_dt"])
    monthly_net = Counter({month: data["net_R"] for month, data in breakdown(records, "month").items()})
    top_month, top_month_net = monthly_net.most_common(1)[0] if monthly_net else ("none", 0.0)
    net_total = sum(float(row["realized_R"]) for row in records)
    positive_months = sum(1 for value in monthly_net.values() if value > 0)
    negative_months = sum(1 for value in monthly_net.values() if value < 0)
    win_runs, loss_runs = run_lengths([float(row["realized_R"]) > 0 for row in ordered])
    return {
        "months_with_trades": len(monthly_net),
        "positive_months": positive_months,
        "negative_months": negative_months,
        "top_month": top_month,
        "top_month_net_R": round(float(top_month_net), 4),
        "top_month_share_of_net_pct": round((float(top_month_net) / net_total * 100.0), 2) if net_total > 0 else 0.0,
        "max_win_cluster": max(win_runs) if win_runs else 0,
        "max_loss_cluster": max(loss_runs) if loss_runs else 0,
        "avg_win_cluster": round(avg([float(item) for item in win_runs]), 2),
        "avg_loss_cluster": round(avg([float(item) for item in loss_runs]), 2),
    }


def run_lengths(flags: list[bool]) -> tuple[list[int], list[int]]:
    win_runs: list[int] = []
    loss_runs: list[int] = []
    current: bool | None = None
    count = 0
    for flag in flags:
        if current is None or flag == current:
            count += 1
            current = flag
            continue
        (win_runs if current else loss_runs).append(count)
        current = flag
        count = 1
    if current is not None:
        (win_runs if current else loss_runs).append(count)
    return win_runs, loss_runs


def cost_sensitivity(records: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = {
        "base_recorded": 0.0,
        "spread_plus_0_05": 0.05,
        "spread_plus_0_10": 0.10,
        "slippage_plus_0_05": 0.05,
        "slippage_plus_0_10": 0.10,
        "spread_0_10_slip_0_05": 0.15,
        "spread_0_20_slip_0_10": 0.30,
    }
    output = {}
    for name, extra_price_cost in scenarios.items():
        adjusted = []
        for row in records:
            adjusted.append(float(row["realized_R"]) - (extra_price_cost / max(float(row["risk"]), 1e-9)))
        output[name] = entry_research.metrics(adjusted)
    return output


def bootstrap_expectancy(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "mean_expectancy_R": 0.0,
            "ci_5_R": 0.0,
            "ci_95_R": 0.0,
            "probability_edge_gt_0": 0.0,
            "samples": 0,
        }
    rng = random.Random(RANDOM_SEED + len(values))
    means = []
    n = len(values)
    for _ in range(BOOTSTRAP_ROUNDS):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    positive = sum(1 for item in means if item > 0)
    return {
        "mean_expectancy_R": round(sum(means) / len(means), 4),
        "ci_5_R": round(percentile(means, 0.05), 4),
        "ci_95_R": round(percentile(means, 0.95), 4),
        "probability_edge_gt_0": round(positive / len(means), 4),
        "samples": BOOTSTRAP_ROUNDS,
    }


def monte_carlo_shuffle(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"median_max_dd_R": 0.0, "p90_max_dd_R": 0.0, "p95_losing_streak": 0, "risk_of_negative_terminal": 0.0}
    rng = random.Random(RANDOM_SEED + 101 + len(values))
    dds = []
    losing_streaks = []
    negative_terminal = 0
    for _ in range(MONTE_CARLO_ROUNDS):
        sample = list(values)
        rng.shuffle(sample)
        metric = entry_research.metrics(sample)
        dds.append(float(metric["max_drawdown_R"]))
        losing_streaks.append(int(metric["losing_streak"]))
        negative_terminal += 1 if sum(sample) < 0 else 0
    dds.sort()
    losing_streaks.sort()
    return {
        "median_max_dd_R": round(percentile(dds, 0.50), 4),
        "p90_max_dd_R": round(percentile(dds, 0.90), 4),
        "p95_losing_streak": int(percentile([float(item) for item in losing_streaks], 0.95)),
        "risk_of_negative_terminal": round(negative_terminal / MONTE_CARLO_ROUNDS, 4),
    }


def expectancy_variance(records: list[dict[str, Any]]) -> dict[str, Any]:
    yearly = breakdown(records, "year")
    monthly = breakdown(records, "month")
    year_exps = [float(data["expectancy_R"]) for data in yearly.values() if data["trades"] > 0]
    month_exps = [float(data["expectancy_R"]) for data in monthly.values() if data["trades"] > 0]
    return {
        "yearly_expectancy_std_R": round(pstdev(year_exps), 4) if len(year_exps) > 1 else 0.0,
        "monthly_expectancy_std_R": round(pstdev(month_exps), 4) if len(month_exps) > 1 else 0.0,
        "best_year_expectancy_R": round(max(year_exps), 4) if year_exps else 0.0,
        "worst_year_expectancy_R": round(min(year_exps), 4) if year_exps else 0.0,
        "best_month_expectancy_R": round(max(month_exps), 4) if month_exps else 0.0,
        "worst_month_expectancy_R": round(min(month_exps), 4) if month_exps else 0.0,
    }


def sample_sufficiency(records: list[dict[str, Any]]) -> dict[str, Any]:
    yearly_counts = Counter(int(row["year"]) for row in records)
    monthly_counts = Counter(row["month"] for row in records)
    active_years = sum(1 for year in YEARS if yearly_counts[year] >= 3)
    active_months = sum(1 for count in monthly_counts.values() if count >= 2)
    trades = len(records)
    if trades >= 80 and active_years >= 4 and active_months >= 20:
        grade = "GOOD"
    elif trades >= 50 and active_years >= 3 and active_months >= 12:
        grade = "ACCEPTABLE"
    elif trades >= 25 and active_years >= 3:
        grade = "THIN"
    else:
        grade = "INSUFFICIENT"
    return {
        "grade": grade,
        "trades": trades,
        "active_years_ge_3_trades": active_years,
        "active_months_ge_2_trades": active_months,
        "min_trades_in_active_year": min([yearly_counts[year] for year in YEARS if yearly_counts[year] > 0] or [0]),
        "max_trades_in_month": max(monthly_counts.values() or [0]),
    }


def score_rule(
    *,
    aggregate: dict[str, Any],
    yearly: dict[str, Any],
    direction: dict[str, Any],
    bootstrap: dict[str, Any],
    sensitivity: dict[str, Any],
    sufficiency: dict[str, Any],
) -> float:
    positive_years = sum(1 for data in yearly.values() if data["trades"] >= 3 and data["expectancy_R"] > 0)
    negative_years = sum(1 for data in yearly.values() if data["trades"] >= 3 and data["expectancy_R"] < 0)
    positive_dirs = sum(1 for data in direction.values() if data["trades"] >= 3 and data["expectancy_R"] > 0)
    sensitivity_survivors = sum(
        1
        for name, data in sensitivity.items()
        if name != "base_recorded" and data["trades"] > 0 and data["expectancy_R"] > 0 and data["profit_factor"] >= 1.0
    )
    sample_bonus = {"GOOD": 20.0, "ACCEPTABLE": 12.0, "THIN": 4.0, "INSUFFICIENT": -10.0}[sufficiency["grade"]]
    score = (
        float(aggregate["profit_factor"]) * 6.0
        + float(aggregate["expectancy_R"]) * 45.0
        + float(bootstrap["probability_edge_gt_0"]) * 25.0
        + positive_years * 7.0
        + positive_dirs * 4.0
        + sensitivity_survivors * 2.5
        + sample_bonus
        - negative_years * 8.0
        - float(aggregate["max_drawdown_R"]) * 1.5
    )
    return round(max(0.0, min(100.0, score)), 2)


def overfit_probability_estimate(
    *,
    yearly: dict[str, Any],
    monthly: dict[str, Any],
    direction: dict[str, Any],
    bootstrap: dict[str, Any],
    sufficiency: dict[str, Any],
) -> float:
    active_years = [data for data in yearly.values() if data["trades"] >= 3]
    losing_years = sum(1 for data in active_years if data["expectancy_R"] < 0)
    top_month_share = max((abs(float(data["net_R"])) for data in monthly.values()), default=0.0)
    total_abs = sum(abs(float(data["net_R"])) for data in monthly.values()) or 1.0
    direction_edges = [data for data in direction.values() if data["trades"] >= 3 and data["expectancy_R"] > 0]
    raw = 0.20
    raw += 0.18 if sufficiency["grade"] == "INSUFFICIENT" else 0.10 if sufficiency["grade"] == "THIN" else 0.0
    raw += min(0.25, losing_years * 0.10)
    raw += 0.15 if len(direction_edges) <= 1 else 0.0
    raw += 0.15 if bootstrap["ci_5_R"] < 0 else 0.0
    raw += min(0.15, (top_month_share / total_abs) * 0.20)
    raw -= max(0.0, (bootstrap["probability_edge_gt_0"] - 0.50) * 0.25)
    return round(max(0.0, min(1.0, raw)), 4)


def classify_rule(
    *,
    aggregate: dict[str, Any],
    yearly: dict[str, Any],
    bootstrap: dict[str, Any],
    robustness_score: float,
    overfit_probability: float,
    sufficiency: dict[str, Any],
) -> str:
    active_years = [data for data in yearly.values() if data["trades"] >= 3]
    positive_years = sum(1 for data in active_years if data["expectancy_R"] > 0)
    if sufficiency["grade"] == "INSUFFICIENT":
        return "INSUFFICIENT_SAMPLE"
    if overfit_probability >= 0.65:
        return "HIGH_OVERFIT_RISK"
    if (
        robustness_score >= 65
        and aggregate["profit_factor"] >= 1.2
        and aggregate["expectancy_R"] > 0
        and bootstrap["probability_edge_gt_0"] >= 0.70
        and positive_years >= 3
    ):
        return "STATISTICALLY_INTERESTING"
    if robustness_score >= 45 and aggregate["expectancy_R"] > 0 and positive_years >= 2:
        return "RESEARCH_CANDIDATE"
    return "WEAK_EDGE"


def classify_overall(rule_audits: dict[str, Any], walk_forward: dict[str, Any]) -> str:
    classifications = Counter(data["classification"] for data in rule_audits.values())
    if classifications["STATISTICALLY_INTERESTING"]:
        return "STATISTICALLY_INTERESTING"
    if classifications["RESEARCH_CANDIDATE"]:
        return "RESEARCH_CANDIDATE"
    if classifications["INSUFFICIENT_SAMPLE"] == len(rule_audits):
        return "INSUFFICIENT_SAMPLE"
    if classifications["HIGH_OVERFIT_RISK"]:
        return "HIGH_OVERFIT_RISK"
    if walk_forward.get("test_expectancy_R", 0.0) > 0:
        return "WEAK_EDGE"
    return "WEAK_EDGE"


def audit_walk_forward(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for test_year in (2024, 2025, 2026):
        train = [row for row in records if int(row["year"]) < test_year]
        test = [row for row in records if int(row["year"]) == test_year]
        if not train or not test:
            continue
        train_scores = {
            rule: metric_block([row for row in train if row["rule"] == rule])["expectancy_R"] for rule in RULES
        }
        selected = max(train_scores, key=train_scores.get)
        test_bucket = [row for row in test if row["rule"] == selected]
        rows.append(
            {
                "test_year": test_year,
                "selected_rule": selected,
                "train_expectancy_R": train_scores[selected],
                "test_metrics": metric_block(test_bucket),
            }
        )
    combined = []
    for item in rows:
        year = item["test_year"]
        rule = item["selected_rule"]
        combined.extend([row for row in records if int(row["year"]) == year and row["rule"] == rule])
    return {
        "steps": rows,
        "test_metrics": metric_block(combined),
        "test_expectancy_R": metric_block(combined)["expectancy_R"] if combined else 0.0,
    }


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, math.floor((len(sorted_values) - 1) * pct)))
    return sorted_values[idx]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# NY_AM_ENTRY_STATISTICAL_ROBUSTNESS",
        "",
        f"- status: `{payload['status']}`",
        f"- detector: `{payload['detector']}`",
        f"- session_filter: `{payload['session_filter']}`",
        f"- overall_classification: `{payload['overall_classification']}`",
        f"- best_rule: `{payload['best_rule']}`",
        "",
        "## Rule Summary",
        "",
        "| Rule | Class | Trades | WR | PF | Exp R | DD | Prob Edge > 0 | CI 5% | CI 95% | Robustness | Overfit Prob | Sample |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for rule, audit in payload["rule_audits"].items():
        aggregate = audit["aggregate"]
        bootstrap = audit["bootstrap"]
        lines.append(
            f"| {rule} | {audit['classification']} | {aggregate['trades']} | {aggregate['win_rate']} | "
            f"{aggregate['profit_factor']} | {aggregate['expectancy_R']} | {aggregate['max_drawdown_R']} | "
            f"{bootstrap['probability_edge_gt_0']} | {bootstrap['ci_5_R']} | {bootstrap['ci_95_R']} | "
            f"{audit['robustness_score']} | {audit['overfit_probability']} | {audit['sample_sufficiency']['grade']} |"
        )
    lines.extend(["", "## Yearly Stability", ""])
    lines.extend(render_nested_metrics(payload["rule_audits"], "yearly", "Year"))
    lines.extend(["", "## Direction Dependence", ""])
    lines.extend(render_nested_metrics(payload["rule_audits"], "direction", "Side"))
    lines.extend(["", "## Regime Stability", ""])
    lines.extend(render_nested_metrics(payload["rule_audits"], "regime", "Regime"))
    lines.extend(["", "## Cost Sensitivity", ""])
    lines.extend(render_cost_sensitivity(payload["rule_audits"]))
    lines.extend(["", "## Clustering And Variance", "", "| Rule | Months | Positive Months | Negative Months | Top Month | Top Month Net R | Top Month Share | Max Win Cluster | Max Loss Cluster | Year Exp Std | Month Exp Std |", "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|"])
    for rule, audit in payload["rule_audits"].items():
        cluster = audit["clustering"]
        variance = audit["expectancy_variance"]
        lines.append(
            f"| {rule} | {cluster['months_with_trades']} | {cluster['positive_months']} | {cluster['negative_months']} | "
            f"{cluster['top_month']} | {cluster['top_month_net_R']} | {cluster['top_month_share_of_net_pct']}% | "
            f"{cluster['max_win_cluster']} | {cluster['max_loss_cluster']} | {variance['yearly_expectancy_std_R']} | "
            f"{variance['monthly_expectancy_std_R']} |"
        )
    lines.extend(["", "## Monte Carlo Shuffle", "", "| Rule | Median DD | P90 DD | P95 Losing Streak | Risk Negative Terminal |", "|---|---:|---:|---:|---:|"])
    for rule, audit in payload["rule_audits"].items():
        mc = audit["monte_carlo"]
        lines.append(
            f"| {rule} | {mc['median_max_dd_R']} | {mc['p90_max_dd_R']} | {mc['p95_losing_streak']} | "
            f"{mc['risk_of_negative_terminal']} |"
        )
    lines.extend(["", "## Walk Forward Behavior", ""])
    lines.extend(render_walk_forward(payload["walk_forward"]))
    lines.extend(["", "## Notes"])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_nested_metrics(rule_audits: dict[str, Any], key: str, bucket_label: str) -> list[str]:
    lines = [
        f"| Rule | {bucket_label} | Trades | WR | PF | Exp R | Net R | DD | Avg Entry Improve | Avg MAE Reduction |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rule, audit in rule_audits.items():
        for bucket, metric in audit[key].items():
            lines.append(
                f"| {rule} | {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | "
                f"{metric['avg_entry_improvement_R']} | {metric['avg_mae_reduction_R']} |"
            )
    return lines


def render_cost_sensitivity(rule_audits: dict[str, Any]) -> list[str]:
    lines = [
        "| Rule | Scenario | Trades | WR | PF | Exp R | Net R | DD |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for rule, audit in rule_audits.items():
        for scenario, metric in audit["cost_sensitivity"].items():
            lines.append(
                f"| {rule} | {scenario} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
    return lines


def render_walk_forward(walk_forward: dict[str, Any]) -> list[str]:
    lines = [
        "| Test Year | Selected Rule | Train Exp R | Test Trades | Test PF | Test Exp R | Test Net R | Test DD |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for step in walk_forward["steps"]:
        metric = step["test_metrics"]
        lines.append(
            f"| {step['test_year']} | {step['selected_rule']} | {step['train_expectancy_R']} | "
            f"{metric['trades']} | {metric['profit_factor']} | {metric['expectancy_R']} | "
            f"{metric['net_R']} | {metric['max_drawdown_R']} |"
        )
    total = walk_forward["test_metrics"]
    lines.append(
        f"| ALL | walk_forward_selected | - | {total['trades']} | {total['profit_factor']} | "
        f"{total['expectancy_R']} | {total['net_R']} | {total['max_drawdown_R']} |"
    )
    return lines


if __name__ == "__main__":
    main()
