"""Expansion structure classification research.

Research only. No live trading logic or M5 detector is modified.

Scope:
- SELL only
- NY_AM
- m5_body_mid_5m
- realistic MT5 execution
- reduced-risk research context

The goal is to split broad clean/extended expansion labels into structural
subtypes and identify whether the edge is concentrated in a durable subtype or
fragmented into a tiny overfit pocket.
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

from scripts import research_reaction_entry_optimization as entry_research  # noqa: E402


INPUT_RECORDS = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "reaction_entry_optimization"
    / "reaction_entry_optimization_records.csv"
)
OUTPUT_DIR = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "expansion_structure_classification"
)
RULE = "m5_body_mid_5m"
BOOTSTRAP_ROUNDS = 5000
RANDOM_SEED = 202605151


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_research()
    (OUTPUT_DIR / "expansion_structure_classification_research.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "expansion_structure_classification_research.md").write_text(render_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "research": payload["research"],
                "classification": payload["classification"],
                "best_subtype": payload["best_subtype"],
                "base_metrics": payload["base_metrics"],
                "subtypes": {
                    subtype: {
                        "class": data["classification"],
                        "trades": data["metrics"]["trades"],
                        "profit_factor": data["metrics"]["profit_factor"],
                        "expectancy_R": data["metrics"]["expectancy_R"],
                        "probability_expectancy_gt_0": data["bootstrap"]["probability_expectancy_gt_0"],
                        "overfit_probability": data["overfit_probability"],
                    }
                    for subtype, data in payload["subtype_audits"].items()
                },
                "report": str((OUTPUT_DIR / "expansion_structure_classification_research.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_research() -> dict[str, Any]:
    records = load_records()
    subtype_audits = {
        subtype: audit_subtype(subtype, [row for row in records if row["structure_subtype"] == subtype])
        for subtype in sorted({row["structure_subtype"] for row in records})
    }
    base_metrics = metric_block([row["realized_R"] for row in records])
    best_subtype = max(subtype_audits, key=lambda name: subtype_audits[name]["score"]) if subtype_audits else "none"
    return {
        "research": "EXPANSION_STRUCTURE_CLASSIFICATION_RESEARCH",
        "status": "RESEARCH_ONLY_NO_LIVE_OR_M5_DETECTOR_CHANGE",
        "scope": "SELL + NY_AM + m5_body_mid_5m + realistic MT5 execution + reduced risk",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": [public_record(row) for row in records],
        "base_metrics": base_metrics,
        "subtype_audits": subtype_audits,
        "best_subtype": best_subtype,
        "edge_concentration": edge_concentration(records, subtype_audits),
        "classification": classify_overall(records, subtype_audits),
        "notes": [
            "Subtypes are deterministic research labels derived from existing trade features, not new entry rules.",
            "Small subtypes are penalized to avoid approving one-or-two-trade illusions.",
            "The goal is to identify where the edge concentrates, not to deploy a new live classifier.",
        ],
    }


def load_records() -> list[dict[str, Any]]:
    source_map = {source_key(row): row for row in entry_research.load_source_trades()}
    with INPUT_RECORDS.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output = []
    for row in rows:
        if (
            row.get("scenario") != "realistic_mt5"
            or row.get("rule") != RULE
            or row.get("side") != "SELL"
            or row.get("session") != "ny_am"
        ):
            continue
        parsed = normalize(row)
        source = source_map.get(source_key(parsed), {})
        parsed.update(source_features(source))
        parsed["structure_subtype"] = classify_structure(parsed)
        output.append(parsed)
    return sorted(output, key=lambda item: item["signal_dt"])


def normalize(row: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = dict(row)
    parsed["year"] = int(float(row["year"]))
    parsed["hour_ny"] = int(float(row["hour_ny"]))
    parsed["risk"] = float(row["risk"])
    parsed["realized_R"] = float(row["realized_R"])
    parsed["mfe_r"] = float(row["mfe_r"])
    parsed["mae_r"] = float(row["mae_r"])
    parsed["cost_r"] = float(row["cost_r"])
    parsed["entry_improvement_R_original"] = float(row["entry_improvement_R_original"])
    parsed["duration_minutes"] = int(float(row["duration_minutes"]))
    parsed["signal_dt"] = datetime.fromisoformat(row["signal_time"])
    parsed["month"] = parsed["signal_dt"].strftime("%Y-%m")
    return parsed


def source_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (int(row["year"]), str(row["signal_time"]), str(row["side"]).upper())


def source_features(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "expansion_subtype": source.get("expansion_subtype", "UNKNOWN"),
        "continuation_quality": source.get("continuation_quality", "UNKNOWN"),
        "atr_bucket": source.get("atr_bucket", "UNKNOWN"),
        "atr_ratio": float(source.get("atr_ratio", 0.0) or 0.0),
        "range_ratio": float(source.get("range_ratio", 0.0) or 0.0),
        "body_pct": float(source.get("body_pct", 0.0) or 0.0),
        "wick_rejection_pct": float(source.get("wick_rejection_pct", 0.0) or 0.0),
        "confidence": float(source.get("confidence", 0.0) or 0.0),
        "mtf_score": float(source.get("mtf_score", 0.0) or 0.0),
        "impulse_score": float(source.get("impulse_score", 0.0) or 0.0),
        "compression_ok": str(source.get("compression_ok", "False")).lower() == "true",
        "micro_bos": str(source.get("micro_bos", "False")).lower() == "true",
        "continuation_momentum": str(source.get("continuation_momentum", "False")).lower() == "true",
    }


def classify_structure(row: dict[str, Any]) -> str:
    """Assign deterministic research subtype from existing features.

    Priority matters. The labels intentionally avoid adding trading logic; they
    only describe the context already present in the historical record.
    """
    if row["atr_bucket"] == "extreme_atr" and row["wick_rejection_pct"] >= 70:
        return "liquidity_sweep_expansion"
    if row["expansion_subtype"] == "extended_expansion" and row["body_pct"] <= 8 and row["wick_rejection_pct"] >= 45:
        return "exhaustion_expansion"
    if row["continuation_quality"] == "strong" and row["range_ratio"] <= 1.15:
        return "compressed_release_expansion"
    if row["continuation_quality"] == "strong":
        return "continuation_expansion"
    if row["expansion_subtype"] == "clean_expansion" and row["body_pct"] >= 28 and row["wick_rejection_pct"] <= 50:
        return "trend_acceleration_expansion"
    if row["mfe_r"] < 0.80 and row["mae_r"] >= 0.70:
        return "rotational_expansion"
    if row["wick_rejection_pct"] >= 55 and row["mfe_r"] >= 0.80:
        return "reversal_expansion"
    if row["atr_bucket"] == "extreme_atr" and row["range_ratio"] >= 1.30:
        return "post_news_expansion"
    return "rotational_expansion"


def audit_subtype(subtype: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row["realized_R"] for row in records]
    metrics = metric_block(values)
    yearly = breakdown(records, "year")
    monthly = breakdown(records, "month")
    spread = cost_curve(records, "spread")
    slippage = cost_curve(records, "slippage")
    bootstrap = bootstrap_expectancy(values)
    overfit = overfit_probability(records, yearly, monthly, bootstrap)
    score = score_subtype(metrics, yearly, monthly, bootstrap, overfit, len(records))
    return {
        "subtype": subtype,
        "metrics": metrics,
        "yearly_consistency": yearly,
        "monthly_consistency": monthly,
        "spread_sensitivity": spread,
        "slippage_sensitivity": slippage,
        "bootstrap": bootstrap,
        "overfit_probability": overfit,
        "score": score,
        "feature_profile": feature_profile(records),
        "classification": classify_subtype(metrics, bootstrap, overfit, len(records)),
    }


def metric_block(values: list[float]) -> dict[str, Any]:
    base = entry_research.metrics(values)
    sorted_values = sorted(values)
    return {
        **base,
        "p05_R": round(percentile(sorted_values, 0.05), 4) if values else 0.0,
        "p50_R": round(percentile(sorted_values, 0.50), 4) if values else 0.0,
        "p95_R": round(percentile(sorted_values, 0.95), 4) if values else 0.0,
        "tail_loss_R": round(min(values), 4) if values else 0.0,
    }


def breakdown(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in records:
        grouped[str(row.get(key, "UNKNOWN"))].append(float(row["realized_R"]))
    return {bucket: metric_block(values) for bucket, values in sorted(grouped.items())}


def cost_curve(records: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    costs = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
    output = {}
    for cost in costs:
        values = [float(row["realized_R"]) - cost / max(float(row["risk"]), 1e-9) for row in records]
        output[f"{kind}_plus_{cost:.2f}"] = metric_block(values)
    return output


def bootstrap_expectancy(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean_expectancy_R": 0.0, "ci_5_R": 0.0, "ci_95_R": 0.0, "probability_expectancy_gt_0": 0.0}
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


def overfit_probability(
    records: list[dict[str, Any]],
    yearly: dict[str, Any],
    monthly: dict[str, Any],
    bootstrap: dict[str, Any],
) -> float:
    active_years = [item for item in yearly.values() if item["trades"] > 0]
    losing_years = sum(1 for item in active_years if item["expectancy_R"] < 0)
    positive_months = sum(1 for item in monthly.values() if item["expectancy_R"] > 0)
    negative_months = sum(1 for item in monthly.values() if item["expectancy_R"] < 0)
    raw = 0.20
    raw += 0.40 if len(records) < 3 else 0.25 if len(records) < 6 else 0.12 if len(records) < 12 else 0.0
    raw += min(0.25, losing_years * 0.10)
    raw += 0.15 if bootstrap["ci_5_R"] < 0 else 0.0
    raw += 0.10 if positive_months <= negative_months else 0.0
    raw -= max(0.0, (bootstrap["probability_expectancy_gt_0"] - 0.65) * 0.20)
    return round(max(0.0, min(1.0, raw)), 4)


def score_subtype(
    metrics: dict[str, Any],
    yearly: dict[str, Any],
    monthly: dict[str, Any],
    bootstrap: dict[str, Any],
    overfit: float,
    sample_size: int,
) -> float:
    positive_years = sum(1 for item in yearly.values() if item["trades"] > 0 and item["expectancy_R"] > 0)
    positive_months = sum(1 for item in monthly.values() if item["trades"] > 0 and item["expectancy_R"] > 0)
    score = (
        metrics["profit_factor"] * 4.0
        + metrics["expectancy_R"] * 40.0
        + bootstrap["probability_expectancy_gt_0"] * 25.0
        + positive_years * 5.0
        + positive_months * 1.5
        + min(16.0, sample_size * 1.0)
        - metrics["max_drawdown_R"] * 1.2
        - overfit * 30.0
    )
    return round(max(0.0, min(100.0, score)), 2)


def classify_subtype(metrics: dict[str, Any], bootstrap: dict[str, Any], overfit: float, sample_size: int) -> str:
    if sample_size < 3 and metrics["expectancy_R"] > 0:
        return "OVERFIT_FRAGMENT"
    if metrics["expectancy_R"] <= 0 or metrics["profit_factor"] < 1:
        return "EDGE_DESTROYER"
    if bootstrap["probability_expectancy_gt_0"] >= 0.80 and overfit < 0.65 and sample_size >= 4:
        return "EDGE_CONCENTRATION_CANDIDATE"
    if metrics["expectancy_R"] > 0:
        return "RESEARCH_CONTINUES"
    return "OVERFIT_FRAGMENT"


def feature_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    return {
        "avg_atr_ratio": round(avg([row["atr_ratio"] for row in records]), 4),
        "avg_range_ratio": round(avg([row["range_ratio"] for row in records]), 4),
        "avg_body_pct": round(avg([row["body_pct"] for row in records]), 4),
        "avg_wick_rejection_pct": round(avg([row["wick_rejection_pct"] for row in records]), 4),
        "avg_mfe_R": round(avg([row["mfe_r"] for row in records]), 4),
        "avg_mae_R": round(avg([row["mae_r"] for row in records]), 4),
        "avg_cost_R": round(avg([row["cost_r"] for row in records]), 4),
        "continuation_quality": dict(Counter(row["continuation_quality"] for row in records)),
        "atr_bucket": dict(Counter(row["atr_bucket"] for row in records)),
        "original_expansion_label": dict(Counter(row["expansion_subtype"] for row in records)),
    }


def edge_concentration(records: list[dict[str, Any]], audits: dict[str, Any]) -> dict[str, Any]:
    total_net = sum(max(0.0, float(row["realized_R"])) for row in records)
    rows = []
    for subtype, audit in audits.items():
        positive_net = max(0.0, audit["metrics"]["net_R"])
        rows.append(
            {
                "subtype": subtype,
                "trades": audit["metrics"]["trades"],
                "net_R": audit["metrics"]["net_R"],
                "positive_net_share_pct": round(positive_net / total_net * 100.0, 2) if total_net else 0.0,
                "classification": audit["classification"],
            }
        )
    rows.sort(key=lambda item: item["positive_net_share_pct"], reverse=True)
    return {
        "total_positive_net_R": round(total_net, 4),
        "top_subtype": rows[0] if rows else {},
        "subtype_shares": rows,
    }


def classify_overall(records: list[dict[str, Any]], audits: dict[str, Any]) -> str:
    if not records:
        return "RESEARCH_CONTINUES"
    candidates = [item for item in audits.values() if item["classification"] == "EDGE_CONCENTRATION_CANDIDATE"]
    positive_research = [
        item
        for item in audits.values()
        if item["classification"] == "RESEARCH_CONTINUES" and item["metrics"]["expectancy_R"] > 0
    ]
    edge_destroyers = [item for item in audits.values() if item["classification"] == "EDGE_DESTROYER"]
    if candidates and len(records) >= 20:
        return "EDGE_CONCENTRATION_CONFIRMED"
    if candidates and edge_destroyers:
        return "EXPANSION_TYPE_DEPENDENT"
    if positive_research and edge_destroyers:
        return "EXPANSION_TYPE_DEPENDENT"
    if candidates:
        return "REGIME_FRAGMENTED"
    if any(item["classification"] == "OVERFIT_FRAGMENT" for item in audits.values()):
        return "OVERFIT_FRAGMENT"
    return "RESEARCH_CONTINUES"


def public_record(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "year",
        "month",
        "signal_time",
        "structure_subtype",
        "expansion_subtype",
        "continuation_quality",
        "atr_bucket",
        "atr_ratio",
        "range_ratio",
        "body_pct",
        "wick_rejection_pct",
        "realized_R",
        "mfe_r",
        "mae_r",
        "cost_r",
        "exit_reason",
    ]
    return {key: row.get(key) for key in keys}


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, math.floor((len(sorted_values) - 1) * pct)))
    return sorted_values[idx]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# EXPANSION_STRUCTURE_CLASSIFICATION_RESEARCH",
        "",
        f"- status: `{payload['status']}`",
        f"- scope: `{payload['scope']}`",
        f"- classification: `{payload['classification']}`",
        f"- best_subtype: `{payload['best_subtype']}`",
        "",
        "## Base Metrics",
        "",
        render_metric_table({"all": payload["base_metrics"]}),
        "",
        "## Subtype Ranking",
        "",
        "| Subtype | Class | Score | Trades | PF | Exp R | Net R | DD | Prob Exp > 0 | CI 5 | Overfit | Avg ATR | Avg Range | Avg Body | Avg Wick |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for subtype, audit in sorted(payload["subtype_audits"].items(), key=lambda pair: pair[1]["score"], reverse=True):
        metric = audit["metrics"]
        bootstrap = audit["bootstrap"]
        profile = audit["feature_profile"]
        lines.append(
            f"| {subtype} | {audit['classification']} | {audit['score']} | {metric['trades']} | {metric['profit_factor']} | "
            f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | "
            f"{bootstrap['probability_expectancy_gt_0']} | {bootstrap['ci_5_R']} | {audit['overfit_probability']} | "
            f"{profile.get('avg_atr_ratio', 0.0)} | {profile.get('avg_range_ratio', 0.0)} | "
            f"{profile.get('avg_body_pct', 0.0)} | {profile.get('avg_wick_rejection_pct', 0.0)} |"
        )
    lines.extend(["", "## Yearly Consistency", ""])
    lines.extend(render_nested(payload["subtype_audits"], "yearly_consistency", "Year"))
    lines.extend(["", "## Monthly Consistency", ""])
    lines.extend(render_nested(payload["subtype_audits"], "monthly_consistency", "Month"))
    lines.extend(["", "## Spread Sensitivity", ""])
    lines.extend(render_sensitivity(payload["subtype_audits"], "spread_sensitivity"))
    lines.extend(["", "## Slippage Sensitivity", ""])
    lines.extend(render_sensitivity(payload["subtype_audits"], "slippage_sensitivity"))
    lines.extend(["", "## Edge Concentration", "", "| Subtype | Trades | Net R | Positive Net Share | Class |", "|---|---:|---:|---:|---|"])
    for row in payload["edge_concentration"]["subtype_shares"]:
        lines.append(
            f"| {row['subtype']} | {row['trades']} | {row['net_R']} | {row['positive_net_share_pct']}% | {row['classification']} |"
        )
    lines.extend(["", "## Classified Records", "", "| Time | Year | Subtype | Original Label | Quality | ATR | Range | Body | Wick | R | Exit |", "|---|---:|---|---|---|---:|---:|---:|---:|---:|---|"])
    for row in payload["records"]:
        lines.append(
            f"| {row['signal_time']} | {row['year']} | {row['structure_subtype']} | {row['expansion_subtype']} | "
            f"{row['continuation_quality']} | {row['atr_ratio']} | {row['range_ratio']} | {row['body_pct']} | "
            f"{row['wick_rejection_pct']} | {row['realized_R']} | {row['exit_reason']} |"
        )
    lines.extend(["", "## Notes"])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_metric_table(items: dict[str, Any]) -> str:
    lines = ["| Bucket | Trades | WR | PF | Exp R | Net R | DD | Tail Loss |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for bucket, metric in items.items():
        lines.append(
            f"| {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
            f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['tail_loss_R']} |"
        )
    return "\n".join(lines)


def render_nested(audits: dict[str, Any], key: str, label: str) -> list[str]:
    lines = [f"| Subtype | {label} | Trades | WR | PF | Exp R | Net R | DD |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for subtype, audit in audits.items():
        for bucket, metric in audit[key].items():
            lines.append(
                f"| {subtype} | {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
    return lines


def render_sensitivity(audits: dict[str, Any], key: str) -> list[str]:
    lines = ["| Subtype | Scenario | Trades | PF | Exp R | Net R | DD |", "|---|---|---:|---:|---:|---:|---:|"]
    for subtype, audit in audits.items():
        for scenario, metric in audit[key].items():
            lines.append(
                f"| {subtype} | {scenario} | {metric['trades']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
    return lines


if __name__ == "__main__":
    main()
