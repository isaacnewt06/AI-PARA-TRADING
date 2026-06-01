"""Research defensive management overlays for REACTION_ZONE_EXPANSION_BRAIN.

This script does not change live/demo entry logic. It re-simulates existing
research trades using MFE/MAE and raw TP/SL labels to compare management plans.
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

OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "management_overlay_research"
SOURCE = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "v0_compression_quality_reaction_zone_expansion_brain_trades.csv"


@dataclass(frozen=True, slots=True)
class ManagementProfile:
    code: str
    label: str
    partial_trigger_r: float
    partial_fraction: float
    protect_trigger_r: float
    protected_stop_r: float
    target_r: float = 1.75
    stop_r: float = -1.01


PROFILES = [
    ManagementProfile("current_05_be_08", "Actual: 50% en 0.5R, BE, protege 0.8R a +0.3R", 0.5, 0.50, 0.8, 0.30),
    ManagementProfile("fast_03_be_08", "Rapida: 40% en 0.3R, BE, protege 0.8R a +0.3R", 0.3, 0.40, 0.8, 0.30),
    ManagementProfile("balanced_04_be_08", "Balanceada: 50% en 0.4R, BE, protege 0.8R a +0.3R", 0.4, 0.50, 0.8, 0.30),
    ManagementProfile("hold_more_05_be_08", "Ofensiva controlada: 35% en 0.5R, BE, protege 0.8R a +0.3R", 0.5, 0.35, 0.8, 0.30),
    ManagementProfile("tight_03_protect_06", "Muy defensiva: 50% en 0.3R, protege 0.6R a +0.2R", 0.3, 0.50, 0.6, 0.20),
    ManagementProfile("profit_lock_05_10", "Dejar correr: 40% en 0.5R, protege 1.0R a +0.5R", 0.5, 0.40, 1.0, 0.50),
]

BLOCKED_FILTERS = {"compression_quality_only"}
CORE_FILTERS = {"displacement_AGG", "fully_valid_non_overlap"}


def load_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["year"] = int(row["year"])
            row["hour_ny"] = int(row["hour_ny"])
            row["mfe_r"] = float(row["mfe_r"])
            row["mae_r"] = float(row["mae_r"])
            row["raw_r"] = float(row["raw_r"])
            row["current_realized_r"] = float(row["realized_r"])
            rows.append(row)
    return rows


def managed_r(row: dict[str, Any], profile: ManagementProfile) -> float:
    mfe = float(row["mfe_r"])
    raw_result = str(row["raw_result"]).upper()
    partial_gain = profile.partial_fraction * profile.partial_trigger_r
    remaining = 1.0 - profile.partial_fraction

    if raw_result == "TP":
        if mfe >= profile.partial_trigger_r:
            return partial_gain + remaining * profile.target_r
        return profile.target_r

    if mfe >= profile.protect_trigger_r:
        return partial_gain + remaining * profile.protected_stop_r
    if mfe >= profile.partial_trigger_r:
        return partial_gain
    return profile.stop_r


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


def compound_result(values: list[float], *, initial: float = 500.0, risk_pct: float = 0.01) -> dict[str, Any]:
    equity = initial
    peak = equity
    max_dd_pct = 0.0
    for value in values:
        equity += equity * risk_pct * value
        peak = max(peak, equity)
        max_dd_pct = max(max_dd_pct, (peak - equity) / peak * 100)
    return {
        "initial_balance": initial,
        "final_balance": round(equity, 2),
        "profit_usd": round(equity - initial, 2),
        "return_pct": round((equity / initial - 1.0) * 100, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
    }


def breakdown(rows: list[dict[str, Any]], values: list[float], key: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(rows, values, strict=True):
        grouped[str(row.get(key))].append(value)
    return {bucket: metrics(bucket_values) for bucket, bucket_values in sorted(grouped.items())}


def evaluate_profile(rows: list[dict[str, Any]], profile: ManagementProfile, *, core_only: bool) -> dict[str, Any]:
    selected = [row for row in rows if not core_only or row["missing_filter"] in CORE_FILTERS]
    values = [managed_r(row, profile) for row in selected]
    return {
        "profile": asdict(profile),
        "scope": "core_only_without_compression_quality_noise" if core_only else "all_v0_compression_quality",
        "metrics": metrics(values),
        "compound_1pct_500": compound_result(values),
        "by_year": breakdown(selected, values, "year"),
        "by_missing_filter": breakdown(selected, values, "missing_filter"),
        "by_session": breakdown(selected, values, "session"),
        "by_atr_bucket": breakdown(selected, values, "atr_bucket"),
        "by_hour_ny": breakdown(selected, values, "hour_ny"),
    }


def score(result: dict[str, Any]) -> float:
    metric = result["metrics"]
    compound = result["compound_1pct_500"]
    return (
        float(metric["net_R"])
        + float(metric["profit_factor"]) * 5.0
        - float(metric["max_drawdown_R"]) * 1.4
        - max(0.0, float(compound["max_drawdown_pct"]) - 6.0) * 2.0
    )


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# REACTION_ZONE_EXPANSION_BRAIN Management Overlay Research",
        "",
        f"- status: {payload['status']}",
        f"- source: `{payload['source']}`",
        f"- generated_at_utc: {payload['generated_at_utc']}",
        f"- conclusion: `{payload['conclusion']}`",
        "",
        "## Ranking",
        "",
        "| Rank | Scope | Profile | Trades | WR | PF | Exp R | Net R | DD R | $500 @1% | Return | DD % |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, item in enumerate(payload["ranking"], start=1):
        metric = item["metrics"]
        compound = item["compound_1pct_500"]
        lines.append(
            "| {rank} | {scope} | {profile} | {trades} | {wr} | {pf} | {exp} | {net} | {dd} | ${final} | {ret}% | {dd_pct}% |".format(
                rank=idx,
                scope=item["scope"],
                profile=item["profile"]["code"],
                trades=metric["trades"],
                wr=metric["win_rate"],
                pf=metric["profit_factor"],
                exp=metric["expectancy_R"],
                net=metric["net_R"],
                dd=metric["max_drawdown_R"],
                final=compound["final_balance"],
                ret=compound["return_pct"],
                dd_pct=compound["max_drawdown_pct"],
            )
        )
    best = payload["ranking"][0]
    lines.extend(
        [
            "",
            "## Best Profile Read",
            "",
            f"- profile: `{best['profile']['code']}`",
            f"- scope: `{best['scope']}`",
            f"- final_balance_1pct_500: ${best['compound_1pct_500']['final_balance']}",
            f"- profit_usd: ${best['compound_1pct_500']['profit_usd']}",
            f"- max_drawdown_pct: {best['compound_1pct_500']['max_drawdown_pct']}%",
            "",
            "## Important Finding",
            "",
            "- `compression_quality_only` is excluded in the core scope because it was negative in 2025 and weak in 2026.",
            "- This is not a live logic change. It is a management/frequency research candidate.",
            "- Next gate should be cost/slippage stress before demo permission.",
        ]
    )
    return "\n".join(lines) + "\n"


def conclusion(ranking: list[dict[str, Any]]) -> str:
    best = ranking[0]
    metrics_ = best["metrics"]
    compound = best["compound_1pct_500"]
    if metrics_["profit_factor"] >= 1.45 and compound["max_drawdown_pct"] <= 6.0 and metrics_["trades"] >= 150:
        return "GESTION_MEJORA_Y_AUMENTA_FRECUENCIA_RESEARCH"
    if metrics_["profit_factor"] >= 1.25 and metrics_["trades"] >= 100:
        return "PROMETEDOR_PERO_NECESITA_STRESS_TEST"
    return "NO_APROBAR_AUN"


def main() -> None:
    rows = load_rows()
    results = []
    for profile in PROFILES:
        results.append(evaluate_profile(rows, profile, core_only=False))
        results.append(evaluate_profile(rows, profile, core_only=True))
    ranking = sorted(results, key=score, reverse=True)
    payload = {
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "source": str(SOURCE.resolve()),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "blocked_noise_filters": sorted(BLOCKED_FILTERS),
        "core_filters": sorted(CORE_FILTERS),
        "ranking": ranking,
        "conclusion": conclusion(ranking),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "reaction_zone_management_overlay_research.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "reaction_zone_management_overlay_research.md").write_text(render(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "conclusion": payload["conclusion"],
                "best_profile": ranking[0]["profile"]["code"],
                "best_scope": ranking[0]["scope"],
                "best_metrics": ranking[0]["metrics"],
                "best_compound_1pct_500": ranking[0]["compound_1pct_500"],
                "report": str((OUTPUT_DIR / "reaction_zone_management_overlay_research.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
