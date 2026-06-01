"""Audit compression_ok variants for REACTION_ZONE_EXPANSION_BRAIN_V0."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.replay_reaction_zone_expansion_brain import OUTPUT_DIR, ReactionZoneExpansionBrainReplay, ReplayVariant


VARIANTS = [
    ReplayVariant(
        code="v0_actual",
        label="V0 actual",
        compression_mode="blocker",
        selected_missing_filters={"compression_ok", "displacement_AGG"},
    ),
    ReplayVariant(
        code="v0_without_compression_ok",
        label="V0 sin compression_ok",
        compression_mode="blocker",
        selected_missing_filters={"displacement_AGG"},
    ),
    ReplayVariant(
        code="v0_compression_quality",
        label="V0 compression_ok como calidad",
        compression_mode="quality",
        selected_missing_filters={"displacement_AGG"},
    ),
]


def _row(metric: dict[str, Any]) -> str:
    return (
        f"{metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
        f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']}"
    )


def _conclusion(results: list[dict[str, Any]]) -> str:
    by_code = {item["variant"]["code"]: item for item in results}
    actual = by_code["v0_actual"]["aggregate"]
    no_compression = by_code["v0_without_compression_ok"]["aggregate"]
    quality = by_code["v0_compression_quality"]["aggregate"]
    full_years_quality = [by_code["v0_compression_quality"]["yearly"][str(year)]["metrics"] for year in (2023, 2024, 2025)]
    full_years_no = [by_code["v0_without_compression_ok"]["yearly"][str(year)]["metrics"] for year in (2023, 2024, 2025)]

    if no_compression["profit_factor"] > actual["profit_factor"] and no_compression["expectancy_R"] > actual["expectancy_R"]:
        return "compression_ok mata edge"
    if quality["profit_factor"] > no_compression["profit_factor"] and all(item["profit_factor"] >= 1.2 for item in full_years_quality):
        return "compression_ok debe ser filtro parcial"
    if all(item["profit_factor"] >= 1.2 for item in full_years_no) and quality["max_drawdown_R"] > no_compression["max_drawdown_R"] * 1.4:
        return "compression_ok protege edge"
    return "necesita más datos"


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# compression_ok Audit - REACTION_ZONE_EXPANSION_BRAIN_V0",
        "",
        f"- status: {payload['status']}",
        f"- baseline: `{payload['baseline']}`",
        f"- conclusion: `{payload['conclusion']}`",
        "",
        "## Variant Comparison",
        "",
        "| Variant | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in payload["variants"]:
        lines.append(f"| {item['variant']['label']} | {_row(item['aggregate'])} |")

    lines.extend(["", "## Performance By Year"])
    for item in payload["variants"]:
        lines.extend(
            [
                "",
                f"### {item['variant']['label']}",
                "",
                "| Year | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for year in ("2023", "2024", "2025", "2026"):
            lines.append(f"| {year} | {_row(item['yearly'][year]['metrics'])} |")

    for breakdown_key, title in (
        ("aggregate_by_session", "Performance By Session"),
        ("aggregate_by_atr_bucket", "Performance By ATR Range"),
        ("aggregate_by_displacement_agg", "Performance By displacement_AGG"),
    ):
        lines.extend(["", f"## {title}"])
        for item in payload["variants"]:
            lines.extend(
                [
                    "",
                    f"### {item['variant']['label']}",
                    "",
                    "| Bucket | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for bucket, metric in item[breakdown_key].items():
                lines.append(f"| {bucket} | {_row(metric)} |")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `V0 actual` measures the current research candidate: displacement_AGG or compression_ok can be the single missing blocker.",
            "- `V0 sin compression_ok` keeps only displacement_AGG as the allowed missing blocker.",
            "- `V0 compression_ok como calidad` removes compression_ok from the hard blocker set and audits whether it should be a score/quality input instead.",
            "- No live or demo execution logic was changed.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    results = [ReactionZoneExpansionBrainReplay(variant).run() for variant in VARIANTS]
    payload = {
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "baseline": "MTF_REAL_H4_FIXED_BASELINE",
        "variants": results,
        "conclusion": _conclusion(results),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "compression_ok_audit.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (OUTPUT_DIR / "compression_ok_audit.md").write_text(_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "conclusion": payload["conclusion"],
                "report": str((OUTPUT_DIR / "compression_ok_audit.md").resolve()),
                "variants": {
                    item["variant"]["code"]: item["aggregate"]
                    for item in results
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
