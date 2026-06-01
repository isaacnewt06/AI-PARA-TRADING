"""NY AM-only executable M1 entry optimization research.

Research only. This script does not modify the frozen M5
displacement_plus_wick_v1 detector or any live trading logic. It validates
whether the promising M1 executable entry rules observed in NY AM survive by
year under realistic MT5 costs.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import research_reaction_entry_optimization as entry_research  # noqa: E402


OUTPUT_DIR = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "ny_am_only_entry_optimization"
)

RULE_CODES = {
    "limit_retrace_20r_3m",
    "limit_retrace_30r_3m",
    "m5_body_mid_5m",
    "atr_retrace_15_5m",
}
SCENARIO_CODE = "realistic_mt5"
YEARS = (2023, 2024, 2025, 2026)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_research()
    (OUTPUT_DIR / "ny_am_only_entry_optimization.json").write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "ny_am_only_entry_optimization.md").write_text(render_report(payload), encoding="utf-8")
    write_records_csv(OUTPUT_DIR / "ny_am_only_entry_optimization_records.csv", payload["records"])
    print(
        json.dumps(
            {
                "classification": payload["classification"],
                "best_rule": payload["best_rule"],
                "best_aggregate": payload["aggregate_by_rule"].get(payload["best_rule"], {}),
                "yearly": payload["yearly_by_rule"].get(payload["best_rule"], {}),
                "report": str((OUTPUT_DIR / "ny_am_only_entry_optimization.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_research() -> dict[str, Any]:
    rules = [rule for rule in entry_research.RULES if rule.code in RULE_CODES]
    scenario = next(item for item in entry_research.SCENARIOS if item.code == SCENARIO_CODE)
    source_rows = [row for row in entry_research.load_source_trades() if str(row.get("session", "")).lower() == "ny_am"]
    m1_by_year = entry_research.load_candles("M1")
    m5_by_year = entry_research.load_candles("M5")
    source_counts_by_year = count_source_by_year(source_rows)
    records: list[dict[str, Any]] = []
    miss_counts: dict[str, dict[int, int]] = {rule.code: {year: 0 for year in YEARS} for rule in rules}

    for row in source_rows:
        year = int(row["year"])
        m1 = m1_by_year.get(year, [])
        m5 = m5_by_year.get(year, [])
        for rule in rules:
            candidate = entry_research.build_entry_candidate(row=row, m1=m1, m5=m5, rule=rule)
            if candidate is None:
                miss_counts[rule.code][year] += 1
                continue
            simulated = entry_research.simulate_candidate(row=row, candidate=candidate, scenario=scenario)
            simulated["source_session_filter"] = "ny_am_only"
            records.append(simulated)

    yearly_by_rule = summarize_yearly(records, source_counts_by_year, miss_counts, rules)
    aggregate_by_rule = summarize_aggregate(records, len(source_rows), miss_counts, rules)
    ranking = rank_rules(aggregate_by_rule, yearly_by_rule)
    best_rule = ranking[0]["rule"] if ranking else "none"
    classification = classify(best_rule=best_rule, aggregate_by_rule=aggregate_by_rule, yearly_by_rule=yearly_by_rule)
    return {
        "research": "NY_AM_ONLY_ENTRY_OPTIMIZATION",
        "status": "RESEARCH_ONLY_NO_M5_DETECTOR_OR_LIVE_LOGIC_CHANGE",
        "detector": "M5 displacement_plus_wick_v1 frozen",
        "baseline": "MTF_REAL_H4_FIXED_BASELINE",
        "session_filter": "ny_am",
        "scenario": asdict(scenario),
        "management": "REACTION_ZONE_MANAGEMENT_OVERLAY_V1 fast_03_be_08",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_trades_total_ny_am": len(source_rows),
        "source_counts_by_year": source_counts_by_year,
        "rules": [asdict(rule) for rule in rules],
        "aggregate_by_rule": aggregate_by_rule,
        "yearly_by_rule": yearly_by_rule,
        "ranking": ranking,
        "best_rule": best_rule,
        "classification": classification,
        "records": records,
        "notes": [
            "No oracle/best-achievable rule is used as an executable candidate.",
            "A candidate must survive by year, not only in total aggregate.",
            "2026 is partial and is reported separately, but weakness there still reduces confidence.",
        ],
    }


def count_source_by_year(rows: list[dict[str, Any]]) -> dict[int, int]:
    counts = {year: 0 for year in YEARS}
    for row in rows:
        counts[int(row["year"])] += 1
    return counts


def summarize_yearly(
    records: list[dict[str, Any]],
    source_counts_by_year: dict[int, int],
    miss_counts: dict[str, dict[int, int]],
    rules: list[Any],
) -> dict[str, dict[int, dict[str, Any]]]:
    result: dict[str, dict[int, dict[str, Any]]] = {}
    for rule in rules:
        result[rule.code] = {}
        for year in YEARS:
            bucket = [row for row in records if row["rule"] == rule.code and int(row["year"]) == year]
            source_count = source_counts_by_year.get(year, 0)
            result[rule.code][year] = summary_from_bucket(
                bucket=bucket,
                source_count=source_count,
                missed=miss_counts[rule.code].get(year, 0),
            )
    return result


def summarize_aggregate(
    records: list[dict[str, Any]],
    source_count: int,
    miss_counts: dict[str, dict[int, int]],
    rules: list[Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for rule in rules:
        bucket = [row for row in records if row["rule"] == rule.code]
        result[rule.code] = summary_from_bucket(
            bucket=bucket,
            source_count=source_count,
            missed=sum(miss_counts[rule.code].values()),
        )
    return result


def summary_from_bucket(*, bucket: list[dict[str, Any]], source_count: int, missed: int) -> dict[str, Any]:
    return {
        **entry_research.metrics([float(row["realized_R"]) for row in bucket]),
        "source_candidates": source_count,
        "missed_trades": missed,
        "fill_probability_pct": round(len(bucket) / source_count * 100.0, 2) if source_count else 0.0,
        "avg_entry_improvement_R": round(avg([float(row["entry_improvement_R_original"]) for row in bucket]), 4),
        "avg_risk_reduction_pct": round(avg([float(row["risk_reduction_pct"]) for row in bucket]), 2),
        "avg_rr_improvement": round(avg([float(row["rr_improvement"]) for row in bucket]), 4),
        "avg_cost_R": round(avg([float(row["cost_r"]) for row in bucket]), 4),
        "avg_spread_efficiency": round(
            avg([float(row["spread_efficiency"]) for row in bucket if float(row["spread_efficiency"]) < 999]),
            4,
        ),
        "avg_mae_reduction_R": round(avg([float(row["mae_reduction_R"]) for row in bucket]), 4),
        "buy_sell": entry_research.breakdown(bucket, "side"),
    }


def rank_rules(aggregate_by_rule: dict[str, dict[str, Any]], yearly_by_rule: dict[str, dict[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for rule, aggregate in aggregate_by_rule.items():
        years = yearly_by_rule[rule]
        stable_years = count_stable_years(years)
        losing_years = count_losing_years(years)
        min_pf = min([metric["profit_factor"] for metric in years.values() if metric["trades"] > 0] or [0.0])
        score = (
            aggregate["profit_factor"] * 8.0
            + aggregate["expectancy_R"] * 30.0
            + stable_years * 8.0
            - losing_years * 10.0
            - aggregate["max_drawdown_R"] * 0.35
            + aggregate["fill_probability_pct"] * 0.04
        )
        rows.append(
            {
                "rule": rule,
                "score": round(score, 4),
                "stable_years": stable_years,
                "losing_years": losing_years,
                "min_pf_with_trades": round(min_pf, 4),
                "aggregate": aggregate,
            }
        )
    return sorted(rows, key=lambda item: item["score"], reverse=True)


def classify(
    *,
    best_rule: str,
    aggregate_by_rule: dict[str, dict[str, Any]],
    yearly_by_rule: dict[str, dict[int, dict[str, Any]]],
) -> str:
    if best_rule == "none":
        return "NEEDS_MORE_DATA"
    aggregate = aggregate_by_rule[best_rule]
    years = yearly_by_rule[best_rule]
    active_years = [metric for metric in years.values() if metric["trades"] >= 3]
    stable_years = count_stable_years(years)
    losing_years = count_losing_years(years)
    if aggregate["trades"] < 30 or len(active_years) < 3:
        return "NEEDS_MORE_DATA"
    if stable_years >= 3 and losing_years == 0 and aggregate["profit_factor"] >= 1.2 and aggregate["expectancy_R"] > 0:
        return "NY_AM_EDGE_CONFIRMED"
    if aggregate["profit_factor"] >= 1.2 and aggregate["expectancy_R"] > 0 and losing_years >= 1:
        return "NY_AM_OVERFIT"
    if aggregate["profit_factor"] >= 1.0 or stable_years >= 2:
        return "NY_AM_EDGE_WEAK"
    return "NY_AM_OVERFIT"


def count_stable_years(years: dict[int, dict[str, Any]]) -> int:
    return sum(
        1
        for metric in years.values()
        if metric["trades"] >= 3 and metric["profit_factor"] >= 1.1 and metric["expectancy_R"] > 0
    )


def count_losing_years(years: dict[int, dict[str, Any]]) -> int:
    return sum(1 for metric in years.values() if metric["trades"] >= 3 and metric["expectancy_R"] < 0)


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def write_records_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# NY_AM_ONLY_ENTRY_OPTIMIZATION",
        "",
        f"- status: `{payload['status']}`",
        f"- detector: `{payload['detector']}`",
        f"- baseline: `{payload['baseline']}`",
        f"- session_filter: `{payload['session_filter']}`",
        f"- management: `{payload['management']}`",
        f"- classification: `{payload['classification']}`",
        f"- best_rule: `{payload['best_rule']}`",
        f"- source_trades_total_ny_am: `{payload['source_trades_total_ny_am']}`",
        "",
        "## Ranking",
        "",
        "| Rank | Rule | Score | Stable Years | Losing Years | Min PF | Trades | Fill | PF | Exp R | Net R | DD | Missed | Entry Improve R | MAE Red |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, item in enumerate(payload["ranking"], start=1):
        r = item["aggregate"]
        lines.append(
            f"| {idx} | {item['rule']} | {item['score']} | {item['stable_years']} | {item['losing_years']} | "
            f"{item['min_pf_with_trades']} | {r['trades']} | {r['fill_probability_pct']}% | {r['profit_factor']} | "
            f"{r['expectancy_R']} | {r['net_R']} | {r['max_drawdown_R']} | {r['missed_trades']} | "
            f"{r['avg_entry_improvement_R']} | {r['avg_mae_reduction_R']} |"
        )
    lines.extend(
        [
            "",
            "## Yearly Stability Matrix",
            "",
            "| Rule | Year | Source | Trades | Fill | Missed | WR | PF | Exp R | Net R | DD | Entry Improve R | Risk Red | Cost R | MAE Red |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rule, years in payload["yearly_by_rule"].items():
        for year, metric in years.items():
            lines.append(
                f"| {rule} | {year} | {metric['source_candidates']} | {metric['trades']} | {metric['fill_probability_pct']}% | "
                f"{metric['missed_trades']} | {metric['win_rate']} | {metric['profit_factor']} | {metric['expectancy_R']} | "
                f"{metric['net_R']} | {metric['max_drawdown_R']} | {metric['avg_entry_improvement_R']} | "
                f"{metric['avg_risk_reduction_pct']}% | {metric['avg_cost_R']} | {metric['avg_mae_reduction_R']} |"
            )
    lines.extend(["", "## Best Rule BUY vs SELL", ""])
    best = payload["best_rule"]
    if best != "none":
        lines.extend(render_breakdown(payload["aggregate_by_rule"][best]["buy_sell"]))
    lines.extend(["", "## Notes"])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_breakdown(items: dict[str, Any]) -> list[str]:
    lines = ["| Side | Trades | WR | PF | Exp R | Net R | DD | Losing Streak |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    if not items:
        lines.append("| none | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")
        return lines
    for bucket, metric in items.items():
        lines.append(
            f"| {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
            f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']} |"
        )
    return lines


if __name__ == "__main__":
    main()
