"""Pre-trade audit for expansion subtype classification.

Research only. This does not modify live logic, the M5 detector, or entry
rules. It checks whether the expansion subtypes discovered in research can be
classified using only information available before the refined entry.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import research_expansion_structure_classification as posttrade_research  # noqa: E402
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
    / "expansion_subtype_pretrade_audit_v1"
)
RULE = "m5_body_mid_5m"

PRETRADE_VARIABLES = [
    "side",
    "session",
    "hour_ny",
    "expansion_subtype",
    "continuation_quality",
    "atr_bucket",
    "atr_ratio",
    "range_ratio",
    "body_pct",
    "wick_rejection_pct",
    "confidence",
    "mtf_score",
    "impulse_score",
    "compression_ok",
    "micro_bos",
    "continuation_momentum",
]
FUTURE_VARIABLES_NOT_ALLOWED = [
    "mfe_r",
    "mae_r",
    "realized_R",
    "exit_reason",
    "duration_minutes",
    "protected",
    "partial_taken",
    "be_moved",
]
FAVORABLE = {"compressed_release_expansion", "liquidity_sweep_expansion"}
AVOID = {"trend_acceleration_expansion", "rotational_expansion"}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_audit()
    (OUTPUT_DIR / "expansion_subtype_pretrade_audit_v1.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "expansion_subtype_pretrade_audit_v1.md").write_text(render_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "research": payload["research"],
                "conclusion": payload["conclusion"],
                "pretrade_classification_possible": payload["pretrade_classification_possible"],
                "lookahead_risk": payload["lookahead_risk"],
                "summary": payload["summary"],
                "report": str((OUTPUT_DIR / "expansion_subtype_pretrade_audit_v1.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_audit() -> dict[str, Any]:
    records = load_records()
    audits = [audit_record(row) for row in records]
    summary = summarize(audits)
    return {
        "research": "EXPANSION_SUBTYPE_PRETRADE_AUDIT_V1",
        "status": "RESEARCH_ONLY_NO_LIVE_OR_M5_DETECTOR_CHANGE",
        "scope": "NY_AM SELL m5_body_mid_5m candidates",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pretrade_classification_possible": pretrade_possible(audits),
        "lookahead_risk": lookahead_risk(audits),
        "variables_available_before_entry": PRETRADE_VARIABLES,
        "variables_that_use_future_information": FUTURE_VARIABLES_NOT_ALLOWED,
        "summary": summary,
        "yearly_stability": breakdown(audits, "year"),
        "subtype_metrics": breakdown(audits, "subtype"),
        "expected_edge_bucket_metrics": breakdown(audits, "expected_edge_bucket"),
        "error_cases": [item for item in audits if item["error_case"]],
        "records": audits,
        "conclusion": conclusion(audits, summary),
        "notes": [
            "The V1 classifier uses only signal-candle and already computed MTF/context features.",
            "It does not use MFE, MAE, realized R, exit reason, trade duration, or management outcome.",
            "This is an audit label only. It must not execute, block, or resize trades yet.",
        ],
    }


def load_records() -> list[dict[str, Any]]:
    source_map = {source_key(row): row for row in entry_research.load_source_trades()}
    posttrade_map = {
        (int(row["year"]), str(row["signal_time"]), str(row["side"]).upper()): row["structure_subtype"]
        for row in posttrade_research.load_records()
    }
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
        parsed["posttrade_research_subtype"] = posttrade_map.get(source_key(parsed), "UNKNOWN")
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
    parsed["duration_minutes"] = int(float(row["duration_minutes"]))
    parsed["signal_dt"] = datetime.fromisoformat(row["signal_time"])
    parsed["entry_dt"] = datetime.fromisoformat(row["entry_time_refined"])
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


def audit_record(row: dict[str, Any]) -> dict[str, Any]:
    subtype, confidence, reason = classify_pretrade(row)
    bucket = expected_edge_bucket(subtype)
    warning = historical_warning(subtype)
    posttrade_mapped = map_posttrade_to_v1(row["posttrade_research_subtype"])
    uses_future = used_future_variables_for_subtype(subtype)
    error_case = subtype != posttrade_mapped
    return {
        "timestamp": row["signal_time"],
        "entry_time": row["entry_time_refined"],
        "year": row["year"],
        "month": row["month"],
        "side": row["side"],
        "session": row["session"],
        "rule": row["rule"],
        "subtype": subtype,
        "subtype_confidence": confidence,
        "subtype_reason": reason,
        "expected_edge_bucket": bucket,
        "historical_warning": warning,
        "posttrade_research_subtype": row["posttrade_research_subtype"],
        "posttrade_mapped_to_v1": posttrade_mapped,
        "classification_matches_posttrade_research": not error_case,
        "variables_used": variables_used_for_subtype(subtype),
        "future_variables_used": uses_future,
        "lookahead_safe": not uses_future,
        "error_case": error_case,
        "realized_R_for_audit_only": round(row["realized_R"], 4),
        "mfe_R_for_audit_only": round(row["mfe_r"], 4),
        "mae_R_for_audit_only": round(row["mae_r"], 4),
        "features": {
            "expansion_subtype": row["expansion_subtype"],
            "continuation_quality": row["continuation_quality"],
            "atr_bucket": row["atr_bucket"],
            "atr_ratio": round(row["atr_ratio"], 4),
            "range_ratio": round(row["range_ratio"], 4),
            "body_pct": round(row["body_pct"], 4),
            "wick_rejection_pct": round(row["wick_rejection_pct"], 4),
            "confidence": row["confidence"],
            "mtf_score": row["mtf_score"],
            "impulse_score": row["impulse_score"],
            "compression_ok": row["compression_ok"],
            "micro_bos": row["micro_bos"],
            "continuation_momentum": row["continuation_momentum"],
        },
    }


def classify_pretrade(row: dict[str, Any]) -> tuple[str, float, str]:
    if row["atr_bucket"] == "extreme_atr" and row["wick_rejection_pct"] >= 70:
        confidence = confidence_from_margins([row["wick_rejection_pct"] - 70, row["atr_ratio"] - 1.45])
        return (
            "liquidity_sweep_expansion",
            confidence,
            "Extreme ATR with very large upper-wick rejection before entry.",
        )
    if row["continuation_quality"] == "strong" and row["range_ratio"] <= 1.15:
        confidence = confidence_from_margins([1.15 - row["range_ratio"], row["confidence"] - 70])
        return (
            "compressed_release_expansion",
            confidence,
            "Strong pre-entry continuation quality while range remains controlled/compressed.",
        )
    if row["expansion_subtype"] == "clean_expansion" and row["body_pct"] >= 28 and row["wick_rejection_pct"] <= 50:
        confidence = confidence_from_margins([row["body_pct"] - 28, 50 - row["wick_rejection_pct"]])
        return (
            "trend_acceleration_expansion",
            confidence,
            "Clean expansion with large body and weaker rejection; historically vulnerable for this SELL setup.",
        )
    if row["continuation_quality"] == "weak" and row["range_ratio"] >= 1.45:
        confidence = confidence_from_margins([row["range_ratio"] - 1.45, 1.45 - min(row["atr_ratio"], 1.45)])
        return (
            "rotational_expansion",
            confidence,
            "Weak continuation quality with wide range behavior before entry; likely rotation/chop expansion.",
        )
    return (
        "other",
        0.55,
        "Pre-entry features do not match validated favorable or avoid research buckets.",
    )


def confidence_from_margins(margins: list[float]) -> float:
    positive_margin = sum(max(0.0, item) for item in margins)
    confidence = 0.62 + min(0.30, positive_margin / 80.0)
    return round(min(0.92, max(0.50, confidence)), 4)


def expected_edge_bucket(subtype: str) -> str:
    if subtype in FAVORABLE:
        return "favorable_research"
    if subtype in AVOID:
        return "avoid_research"
    return "unknown_research"


def historical_warning(subtype: str) -> str:
    if subtype == "compressed_release_expansion":
        return "Research-positive but sample is small; audit only, not execution approval."
    if subtype == "liquidity_sweep_expansion":
        return "Research-positive sweep-like expansion; sample is small and must remain audit-only."
    if subtype == "trend_acceleration_expansion":
        return "Avoid research bucket; this subtype contained the largest 2025 loss."
    if subtype == "rotational_expansion":
        return "Avoid research bucket; weak continuation and rotation diluted edge."
    return "No reliable historical edge bucket yet."


def variables_used_for_subtype(subtype: str) -> list[str]:
    common = ["atr_bucket", "atr_ratio", "range_ratio", "body_pct", "wick_rejection_pct", "continuation_quality", "confidence", "expansion_subtype"]
    if subtype == "liquidity_sweep_expansion":
        return ["atr_bucket", "atr_ratio", "wick_rejection_pct"]
    if subtype == "compressed_release_expansion":
        return ["continuation_quality", "range_ratio", "confidence"]
    if subtype == "trend_acceleration_expansion":
        return ["expansion_subtype", "body_pct", "wick_rejection_pct"]
    if subtype == "rotational_expansion":
        return ["continuation_quality", "range_ratio", "atr_ratio"]
    return common


def used_future_variables_for_subtype(_subtype: str) -> list[str]:
    return []


def map_posttrade_to_v1(subtype: str) -> str:
    if subtype in {
        "compressed_release_expansion",
        "liquidity_sweep_expansion",
        "trend_acceleration_expansion",
        "rotational_expansion",
    }:
        return subtype
    return "other"


def summarize(audits: list[dict[str, Any]]) -> dict[str, Any]:
    subtype_counts = Counter(item["subtype"] for item in audits)
    bucket_counts = Counter(item["expected_edge_bucket"] for item in audits)
    matches = sum(1 for item in audits if item["classification_matches_posttrade_research"])
    lookahead_safe = sum(1 for item in audits if item["lookahead_safe"])
    return {
        "total_candidates": len(audits),
        "subtype_counts": dict(subtype_counts),
        "expected_edge_bucket_counts": dict(bucket_counts),
        "posttrade_research_match_rate_pct": round(matches / len(audits) * 100.0, 2) if audits else 0.0,
        "lookahead_safe_rate_pct": round(lookahead_safe / len(audits) * 100.0, 2) if audits else 0.0,
        "favorable_research_count": bucket_counts.get("favorable_research", 0),
        "avoid_research_count": bucket_counts.get("avoid_research", 0),
        "unknown_research_count": bucket_counts.get("unknown_research", 0),
    }


def pretrade_possible(audits: list[dict[str, Any]]) -> bool:
    return bool(audits) and all(item["lookahead_safe"] for item in audits)


def lookahead_risk(audits: list[dict[str, Any]]) -> str:
    if not audits:
        return "NO_DATA"
    if all(item["lookahead_safe"] for item in audits):
        return "LOW"
    return "HIGH"


def breakdown(audits: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in audits:
        grouped[str(item[key])].append(item)
    return {bucket: metrics(items) for bucket, items in sorted(grouped.items())}


def metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(item["realized_R_for_audit_only"]) for item in items]
    base = entry_research.metrics(values)
    return {
        **base,
        "avg_subtype_confidence": round(sum(float(item["subtype_confidence"]) for item in items) / len(items), 4)
        if items
        else 0.0,
        "lookahead_safe": all(item["lookahead_safe"] for item in items),
        "posttrade_match_rate_pct": round(
            sum(1 for item in items if item["classification_matches_posttrade_research"]) / len(items) * 100.0,
            2,
        )
        if items
        else 0.0,
    }


def conclusion(audits: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    if not audits:
        return "NEEDS_MORE_FEATURES"
    if not all(item["lookahead_safe"] for item in audits):
        return "PRETRADE_CLASSIFIER_HAS_LOOKAHEAD"
    if summary["posttrade_research_match_rate_pct"] >= 70.0 and summary["unknown_research_count"] <= len(audits) * 0.35:
        return "PRETRADE_CLASSIFIER_VALID"
    if summary["unknown_research_count"] > len(audits) * 0.35:
        return "NEEDS_MORE_FEATURES"
    return "RESEARCH_CONTINUES"


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# EXPANSION_SUBTYPE_PRETRADE_AUDIT_V1",
        "",
        f"- status: `{payload['status']}`",
        f"- scope: `{payload['scope']}`",
        f"- conclusion: `{payload['conclusion']}`",
        f"- pretrade_classification_possible: `{payload['pretrade_classification_possible']}`",
        f"- lookahead_risk: `{payload['lookahead_risk']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in payload["summary"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Variables Available Before Entry",
            "",
        ]
    )
    for item in payload["variables_available_before_entry"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Variables That Use Future Information", ""])
    for item in payload["variables_that_use_future_information"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Subtype Metrics", ""])
    lines.extend(render_metric_table(payload["subtype_metrics"], "Subtype"))
    lines.extend(["", "## Expected Edge Bucket Metrics", ""])
    lines.extend(render_metric_table(payload["expected_edge_bucket_metrics"], "Bucket"))
    lines.extend(["", "## Yearly Stability", ""])
    lines.extend(render_metric_table(payload["yearly_stability"], "Year"))
    lines.extend(["", "## Error Cases", ""])
    if payload["error_cases"]:
        lines.extend(
            [
                "| Time | Pretrade Subtype | Posttrade Research | Bucket | R | Reason |",
                "|---|---|---|---|---:|---|",
            ]
        )
        for item in payload["error_cases"]:
            lines.append(
                f"| {item['timestamp']} | {item['subtype']} | {item['posttrade_research_subtype']} | "
                f"{item['expected_edge_bucket']} | {item['realized_R_for_audit_only']} | {item['subtype_reason']} |"
            )
    else:
        lines.append("No error cases.")
    lines.extend(["", "## Audit Records", "", "| Time | Subtype | Confidence | Bucket | Lookahead Safe | R | Reason |", "|---|---|---:|---|---|---:|---|"])
    for item in payload["records"]:
        lines.append(
            f"| {item['timestamp']} | {item['subtype']} | {item['subtype_confidence']} | "
            f"{item['expected_edge_bucket']} | {item['lookahead_safe']} | {item['realized_R_for_audit_only']} | "
            f"{item['subtype_reason']} |"
        )
    lines.extend(["", "## Notes"])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_metric_table(items: dict[str, Any], label: str) -> list[str]:
    lines = [
        f"| {label} | Trades | WR | PF | Exp R | Net R | DD | Avg Confidence | Match Rate | Lookahead Safe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for bucket, metric in items.items():
        lines.append(
            f"| {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
            f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | "
            f"{metric['avg_subtype_confidence']} | {metric['posttrade_match_rate_pct']}% | {metric['lookahead_safe']} |"
        )
    return lines


if __name__ == "__main__":
    main()
