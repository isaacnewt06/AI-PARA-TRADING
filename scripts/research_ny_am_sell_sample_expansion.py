"""Controlled sample expansion for NY AM SELL edge.

Research only. This does not modify live logic or the frozen M5 detector. It
tests one expansion at a time around the observed micro-edge:

SELL + NY_AM + extended_expansion + m5_body_mid_5m.
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
from typing import Any, Callable

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
    / "ny_am_sell_sample_expansion"
)

BOOTSTRAP_ROUNDS = 5000
RANDOM_SEED = 20260515
SAFE_MAX_SPREAD_PRICE = 0.15
SAFE_SLIPPAGE_PRICE = 0.05
RECORDED_REALISTIC_PRICE_COST = 0.308 + 0.05


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_research()
    (OUTPUT_DIR / "ny_am_sell_sample_expansion.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "ny_am_sell_sample_expansion.md").write_text(render_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "research": payload["research"],
                "classification": payload["classification"],
                "best_variant": payload["best_variant"],
                "variants": {
                    name: {
                        "classification": data["classification"],
                        "trades": data["metrics"]["trades"],
                        "profit_factor": data["metrics"]["profit_factor"],
                        "expectancy_R": data["metrics"]["expectancy_R"],
                        "max_drawdown_R": data["metrics"]["max_drawdown_R"],
                        "bootstrap_probability_expectancy_gt_0": data["bootstrap"]["probability_expectancy_gt_0"],
                        "overfit_risk": data["overfit_risk"],
                    }
                    for name, data in payload["variants"].items()
                },
                "report": str((OUTPUT_DIR / "ny_am_sell_sample_expansion.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_research() -> dict[str, Any]:
    records = enrich_records(load_records())
    variant_defs = [
        ("core_extended_only", "Baseline micro-edge only", lambda rows: select_single(rows, expansion={"extended_expansion"}, session={"ny_am"}, rule={"m5_body_mid_5m"}), "recorded"),
        ("expand_1_add_clean_expansion", "Add clean_expansion to extended_expansion", lambda rows: select_single(rows, expansion={"extended_expansion", "clean_expansion"}, session={"ny_am"}, rule={"m5_body_mid_5m"}), "recorded"),
        ("expand_2_add_first_ny_pm", "Add first NY PM hour while keeping extended_expansion", lambda rows: select_single(rows, expansion={"extended_expansion"}, session={"ny_am", "ny_pm"}, rule={"m5_body_mid_5m"}, allowed_hours={9, 10, 15}), "recorded"),
        ("expand_3_add_limit_retrace_30_fallback", "Allow limit_retrace_30r_3m only when m5_body_mid_5m does not fill", lambda rows: select_combo_fallback(rows, expansion={"extended_expansion"}, session={"ny_am"}), "recorded"),
        ("expand_4_safe_max_spread_environment", "Same core, but normalized to SAFE max spread/slippage environment", lambda rows: select_single(rows, expansion={"extended_expansion"}, session={"ny_am"}, rule={"m5_body_mid_5m"}), "safe_max"),
        ("expand_5_entry_improvement_ge_0_05", "Add clean_expansion but require executable entry improvement >= 0.05R", lambda rows: select_single(rows, expansion={"extended_expansion", "clean_expansion"}, session={"ny_am"}, rule={"m5_body_mid_5m"}, min_entry_improvement=0.05), "recorded"),
    ]
    variants = {}
    for name, description, selector, cost_mode in variant_defs:
        selected = selector(records)
        if cost_mode == "safe_max":
            selected = [apply_safe_max_cost(row) for row in selected]
        variants[name] = audit_variant(name=name, description=description, records=selected)
    best_variant = max(variants, key=lambda name: variants[name]["score"]) if variants else "none"
    return {
        "research": "NY_AM_SELL_SAMPLE_EXPANSION_RESEARCH",
        "status": "RESEARCH_ONLY_NO_LIVE_OR_M5_DETECTOR_CHANGE",
        "core": "SELL + NY_AM + extended_expansion + m5_body_mid_5m + realistic MT5 costs + reduced risk",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "safe_max_spread_price": SAFE_MAX_SPREAD_PRICE,
        "safe_slippage_price": SAFE_SLIPPAGE_PRICE,
        "recorded_realistic_price_cost": RECORDED_REALISTIC_PRICE_COST,
        "variants": variants,
        "best_variant": best_variant,
        "classification": classify_overall(variants),
        "notes": [
            "Each variant expands one dimension from the core unless explicitly labeled as a SAFE execution environment normalization.",
            "The limit_retrace_30 variant is a deterministic fallback, not an oracle: m5_body_mid_5m has priority when both fill.",
            "A variant is not considered live-ready here; this is research-only sample expansion.",
        ],
    }


def load_records() -> list[dict[str, Any]]:
    with INPUT_RECORDS.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [normalize(row) for row in rows if row.get("scenario") == "realistic_mt5" and row.get("side") == "SELL"]


def normalize(row: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = dict(row)
    parsed["year"] = int(float(row["year"]))
    parsed["hour_ny"] = int(float(row["hour_ny"]))
    parsed["risk"] = float(row["risk"])
    parsed["realized_R"] = float(row["realized_R"])
    parsed["adjusted_R"] = parsed["realized_R"]
    parsed["mfe_r"] = float(row["mfe_r"])
    parsed["mae_r"] = float(row["mae_r"])
    parsed["cost_r"] = float(row["cost_r"])
    parsed["entry_improvement_R_original"] = float(row["entry_improvement_R_original"])
    parsed["signal_dt"] = datetime.fromisoformat(row["signal_time"])
    parsed["month"] = parsed["signal_dt"].strftime("%Y-%m")
    return parsed


def enrich_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_map = {source_key(row): row for row in entry_research.load_source_trades()}
    for row in records:
        source = source_map.get(source_key(row), {})
        row["expansion_subtype"] = source.get("expansion_subtype", "UNKNOWN")
        row["continuation_quality"] = source.get("continuation_quality", "UNKNOWN")
        row["atr_bucket"] = source.get("atr_bucket", "UNKNOWN")
        row["confidence"] = float(source.get("confidence", 0.0) or 0.0)
        row["mtf_score"] = float(source.get("mtf_score", 0.0) or 0.0)
    return records


def source_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (int(row["year"]), str(row["signal_time"]), str(row["side"]).upper())


def select_single(
    rows: list[dict[str, Any]],
    *,
    expansion: set[str],
    session: set[str],
    rule: set[str],
    allowed_hours: set[int] | None = None,
    min_entry_improvement: float | None = None,
) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        if row["rule"] not in rule:
            continue
        if str(row.get("expansion_subtype")) not in expansion:
            continue
        if str(row.get("session")) not in session:
            continue
        if allowed_hours is not None and int(row["hour_ny"]) not in allowed_hours:
            continue
        if min_entry_improvement is not None and float(row["entry_improvement_R_original"]) < min_entry_improvement:
            continue
        selected.append(dict(row))
    return sorted(selected, key=lambda item: item["signal_dt"])


def select_combo_fallback(rows: list[dict[str, Any]], *, expansion: set[str], session: set[str]) -> list[dict[str, Any]]:
    eligible = select_single(
        rows,
        expansion=expansion,
        session=session,
        rule={"m5_body_mid_5m", "limit_retrace_30r_3m"},
    )
    grouped: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        grouped[source_key(row)].append(row)
    selected = []
    for items in grouped.values():
        by_rule = {item["rule"]: item for item in items}
        selected.append(dict(by_rule.get("m5_body_mid_5m") or by_rule["limit_retrace_30r_3m"]))
    return sorted(selected, key=lambda item: item["signal_dt"])


def apply_safe_max_cost(row: dict[str, Any]) -> dict[str, Any]:
    adjusted = dict(row)
    gross_before_cost = float(row["realized_R"]) + RECORDED_REALISTIC_PRICE_COST / max(float(row["risk"]), 1e-9)
    safe_cost = (SAFE_MAX_SPREAD_PRICE + SAFE_SLIPPAGE_PRICE) / max(float(row["risk"]), 1e-9)
    adjusted["adjusted_R"] = round(gross_before_cost - safe_cost, 4)
    adjusted["cost_r"] = round(safe_cost, 4)
    adjusted["cost_mode"] = "safe_max_spread_environment"
    return adjusted


def audit_variant(*, name: str, description: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["adjusted_R"]) for row in records]
    metrics = metric_block(values)
    yearly = breakdown(records, "year")
    monthly = breakdown(records, "month")
    costs = cost_sensitivity(records)
    bootstrap = bootstrap_expectancy(values)
    overfit_risk = estimate_overfit_risk(metrics=metrics, yearly=yearly, monthly=monthly, bootstrap=bootstrap, records=records)
    score = score_variant(metrics=metrics, yearly=yearly, bootstrap=bootstrap, overfit_risk=overfit_risk, records=records)
    return {
        "description": description,
        "metrics": metrics,
        "yearly_stability": yearly,
        "monthly_consistency": monthly,
        "cost_sensitivity": costs,
        "bootstrap": bootstrap,
        "overfit_risk": overfit_risk,
        "score": score,
        "classification": classify_variant(metrics=metrics, bootstrap=bootstrap, overfit_risk=overfit_risk, records=records),
        "sample": {
            "trades": len(records),
            "years_present": sorted({int(row["year"]) for row in records}),
            "months_present": sorted({row["month"] for row in records}),
            "rules_used": dict(Counter(row["rule"] for row in records)),
            "sessions_used": dict(Counter(row["session"] for row in records)),
            "regimes_used": dict(Counter(row["expansion_subtype"] for row in records)),
        },
    }


def metric_block(values: list[float]) -> dict[str, Any]:
    base = entry_research.metrics(values)
    sorted_values = sorted(values)
    base.update(
        {
            "p05_R": round(percentile(sorted_values, 0.05), 4) if values else 0.0,
            "p50_R": round(percentile(sorted_values, 0.50), 4) if values else 0.0,
            "p95_R": round(percentile(sorted_values, 0.95), 4) if values else 0.0,
            "tail_loss_R": round(min(values), 4) if values else 0.0,
        }
    )
    return base


def breakdown(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in records:
        grouped[str(row.get(key, "UNKNOWN"))].append(float(row["adjusted_R"]))
    return {bucket: metric_block(values) for bucket, values in sorted(grouped.items())}


def cost_sensitivity(records: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = {
        "base": 0.0,
        "extra_spread_0_05": 0.05,
        "extra_spread_0_10": 0.10,
        "extra_slippage_0_05": 0.05,
        "extra_spread_0_10_slip_0_05": 0.15,
        "extra_spread_0_20_slip_0_10": 0.30,
    }
    output = {}
    for name, extra_price_cost in scenarios.items():
        values = [float(row["adjusted_R"]) - extra_price_cost / max(float(row["risk"]), 1e-9) for row in records]
        output[name] = metric_block(values)
    return output


def bootstrap_expectancy(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean_expectancy_R": 0.0, "ci_5_R": 0.0, "ci_95_R": 0.0, "probability_expectancy_gt_0": 0.0}
    rng = random.Random(RANDOM_SEED + len(values))
    samples = []
    for _ in range(BOOTSTRAP_ROUNDS):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        samples.append(sum(sample) / len(sample))
    samples.sort()
    return {
        "mean_expectancy_R": round(sum(samples) / len(samples), 4),
        "ci_5_R": round(percentile(samples, 0.05), 4),
        "ci_95_R": round(percentile(samples, 0.95), 4),
        "probability_expectancy_gt_0": round(sum(1 for item in samples if item > 0) / len(samples), 4),
    }


def estimate_overfit_risk(
    *,
    metrics: dict[str, Any],
    yearly: dict[str, Any],
    monthly: dict[str, Any],
    bootstrap: dict[str, Any],
    records: list[dict[str, Any]],
) -> float:
    active_years = [item for item in yearly.values() if item["trades"] > 0]
    losing_years = sum(1 for item in active_years if item["expectancy_R"] < 0)
    positive_months = sum(1 for item in monthly.values() if item["expectancy_R"] > 0)
    negative_months = sum(1 for item in monthly.values() if item["expectancy_R"] < 0)
    raw = 0.15
    raw += 0.35 if len(records) < 10 else 0.20 if len(records) < 20 else 0.08 if len(records) < 35 else 0.0
    raw += min(0.25, losing_years * 0.08)
    raw += 0.15 if bootstrap["ci_5_R"] < 0 else 0.0
    raw += 0.10 if positive_months <= negative_months else 0.0
    raw += 0.10 if metrics["max_drawdown_R"] > abs(metrics["net_R"]) else 0.0
    raw -= max(0.0, (bootstrap["probability_expectancy_gt_0"] - 0.65) * 0.20)
    return round(max(0.0, min(1.0, raw)), 4)


def score_variant(
    *,
    metrics: dict[str, Any],
    yearly: dict[str, Any],
    bootstrap: dict[str, Any],
    overfit_risk: float,
    records: list[dict[str, Any]],
) -> float:
    positive_years = sum(1 for item in yearly.values() if item["trades"] > 0 and item["expectancy_R"] > 0)
    score = (
        metrics["profit_factor"] * 5.0
        + metrics["expectancy_R"] * 45.0
        + bootstrap["probability_expectancy_gt_0"] * 25.0
        + positive_years * 6.0
        + min(20.0, len(records) * 0.45)
        - metrics["max_drawdown_R"] * 1.5
        - overfit_risk * 30.0
    )
    return round(max(0.0, min(100.0, score)), 2)


def classify_variant(*, metrics: dict[str, Any], bootstrap: dict[str, Any], overfit_risk: float, records: list[dict[str, Any]]) -> str:
    if len(records) < 10 and metrics["expectancy_R"] > 0:
        return "ONLY_THIN_EDGE"
    if metrics["expectancy_R"] <= 0 or metrics["profit_factor"] < 1.0:
        return "SAMPLE_EXPANDED_EDGE_DIES"
    if bootstrap["probability_expectancy_gt_0"] < 0.70:
        return "NEEDS_MORE_DATA"
    if overfit_risk >= 0.65:
        return "ONLY_THIN_EDGE"
    if len(records) >= 20 and metrics["profit_factor"] >= 1.2 and metrics["expectancy_R"] > 0:
        return "SAMPLE_EXPANDED_EDGE_SURVIVES"
    return "NEEDS_MORE_DATA"


def classify_overall(variants: dict[str, Any]) -> str:
    classes = Counter(item["classification"] for item in variants.values())
    if classes["SAMPLE_EXPANDED_EDGE_SURVIVES"]:
        return "SAMPLE_EXPANDED_EDGE_SURVIVES"
    if classes["ONLY_THIN_EDGE"]:
        return "ONLY_THIN_EDGE"
    if classes["SAMPLE_EXPANDED_EDGE_DIES"] >= max(1, len(variants) // 2):
        return "SAMPLE_EXPANDED_EDGE_DIES"
    return "NEEDS_MORE_DATA"


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, math.floor((len(sorted_values) - 1) * pct)))
    return sorted_values[idx]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# NY_AM_SELL_SAMPLE_EXPANSION_RESEARCH",
        "",
        f"- status: `{payload['status']}`",
        f"- core: `{payload['core']}`",
        f"- classification: `{payload['classification']}`",
        f"- best_variant: `{payload['best_variant']}`",
        "",
        "## Variant Ranking",
        "",
        "| Variant | Class | Score | Trades | PF | Exp R | Net R | DD | Prob Exp > 0 | CI 5% | Overfit Risk | Years | Months | Rules |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|",
    ]
    for name, item in sorted(payload["variants"].items(), key=lambda pair: pair[1]["score"], reverse=True):
        metric = item["metrics"]
        sample = item["sample"]
        bootstrap = item["bootstrap"]
        lines.append(
            f"| {name} | {item['classification']} | {item['score']} | {metric['trades']} | {metric['profit_factor']} | "
            f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | "
            f"{bootstrap['probability_expectancy_gt_0']} | {bootstrap['ci_5_R']} | {item['overfit_risk']} | "
            f"{','.join(str(year) for year in sample['years_present'])} | {len(sample['months_present'])} | {sample['rules_used']} |"
        )
    lines.extend(["", "## Yearly Stability", ""])
    lines.extend(render_nested(payload["variants"], "yearly_stability", "Year"))
    lines.extend(["", "## Monthly Consistency", ""])
    lines.extend(render_nested(payload["variants"], "monthly_consistency", "Month"))
    lines.extend(["", "## Cost Sensitivity", ""])
    lines.extend(render_costs(payload["variants"]))
    lines.extend(["", "## Variant Definitions"])
    for name, item in payload["variants"].items():
        lines.append(f"- `{name}`: {item['description']}")
    lines.extend(["", "## Notes"])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_nested(variants: dict[str, Any], key: str, label: str) -> list[str]:
    lines = [
        f"| Variant | {label} | Trades | WR | PF | Exp R | Net R | DD |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in variants.items():
        for bucket, metric in item[key].items():
            lines.append(
                f"| {name} | {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
    return lines


def render_costs(variants: dict[str, Any]) -> list[str]:
    lines = [
        "| Variant | Scenario | Trades | WR | PF | Exp R | Net R | DD |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in variants.items():
        for scenario, metric in item["cost_sensitivity"].items():
            lines.append(
                f"| {name} | {scenario} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
    return lines


if __name__ == "__main__":
    main()
