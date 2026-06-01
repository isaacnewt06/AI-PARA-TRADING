"""Research wider management variants for displacement_plus_wick_v1.

Research only. Entries, detector, displacement logic and wick logic remain
frozen. This script replays the existing displacement_plus_wick_v1 entries on
historical M5 candles and compares management profiles under ideal, realistic
and pessimistic execution assumptions.
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

from src.trading.blueprint_backtester import Candle  # noqa: E402
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester  # noqa: E402


INPUT_DIR = ROOT / "data" / "backtests" / "input"
SOURCE_TRADES = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "V1_displacement_validation"
    / "displacement_plus_wick_trades.csv"
)
OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "wider_management_research"


@dataclass(frozen=True, slots=True)
class ManagementProfile:
    code: str
    label: str
    partial_trigger_r: float
    partial_fraction: float
    protect_trigger_r: float
    protected_stop_r: float
    target_r: float
    adaptive: bool = False


@dataclass(frozen=True, slots=True)
class ExecutionScenario:
    code: str
    label: str
    spread_price: float = 0.0
    slippage_price: float = 0.0
    partial_trigger_delay_r: float = 0.0
    protect_trigger_delay_r: float = 0.0
    target_delay_r: float = 0.0
    partial_fill_ratio: float = 1.0
    partial_queue_fail_every: int = 0
    trailing_queue_fail_every: int = 0
    conflict_policy: str = "stop_first"
    be_slippage_r: float = 0.0
    protected_stop_slippage_r: float = 0.0
    stop_slippage_r: float = 0.0


PROFILES = [
    ManagementProfile(
        "fast_03_be_08",
        "Baseline fast: partial 0.3R, BE, protect 0.8R at +0.3R",
        partial_trigger_r=0.30,
        partial_fraction=0.40,
        protect_trigger_r=0.80,
        protected_stop_r=0.30,
        target_r=1.75,
    ),
    ManagementProfile(
        "medium_05_be_12",
        "Medium: partial 0.5R, BE, protect 1.2R at +0.5R",
        partial_trigger_r=0.50,
        partial_fraction=0.40,
        protect_trigger_r=1.20,
        protected_stop_r=0.50,
        target_r=2.00,
    ),
    ManagementProfile(
        "swing_micro_08_be_15",
        "Swing micro: partial 0.8R, BE, protect 1.5R at +0.8R",
        partial_trigger_r=0.80,
        partial_fraction=0.35,
        protect_trigger_r=1.50,
        protected_stop_r=0.80,
        target_r=2.50,
    ),
    ManagementProfile(
        "delayed_trailing",
        "Delayed trailing: partial 0.5R, delayed protect 1.4R at +0.4R",
        partial_trigger_r=0.50,
        partial_fraction=0.35,
        protect_trigger_r=1.40,
        protected_stop_r=0.40,
        target_r=2.20,
    ),
    ManagementProfile(
        "ATR_adaptive_BE",
        "ATR adaptive: wider BE/trailing in high ATR, tighter in low ATR",
        partial_trigger_r=0.50,
        partial_fraction=0.40,
        protect_trigger_r=1.20,
        protected_stop_r=0.50,
        target_r=2.00,
        adaptive=True,
    ),
]


SCENARIOS = [
    ExecutionScenario("ideal_replay", "Ideal M5 replay with no cost/degradation."),
    ExecutionScenario(
        "realistic_mt5",
        "Realistic MT5: XAU spread, light slippage, queue misses and delayed protection.",
        spread_price=0.308,
        slippage_price=0.05,
        partial_trigger_delay_r=0.05,
        protect_trigger_delay_r=0.05,
        target_delay_r=0.03,
        partial_fill_ratio=0.85,
        partial_queue_fail_every=17,
        trailing_queue_fail_every=19,
        be_slippage_r=0.03,
        protected_stop_slippage_r=0.05,
        stop_slippage_r=0.03,
    ),
    ExecutionScenario(
        "pessimistic_execution",
        "Pessimistic: high spread, higher slippage, more queue misses and delayed trailing.",
        spread_price=0.396,
        slippage_price=0.15,
        partial_trigger_delay_r=0.12,
        protect_trigger_delay_r=0.15,
        target_delay_r=0.08,
        partial_fill_ratio=0.65,
        partial_queue_fail_every=7,
        trailing_queue_fail_every=9,
        be_slippage_r=0.08,
        protected_stop_slippage_r=0.12,
        stop_slippage_r=0.08,
    ),
]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_research()
    (OUTPUT_DIR / "wider_management_research.json").write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "wider_management_research.md").write_text(render_report(payload), encoding="utf-8")
    write_records_csv(OUTPUT_DIR / "wider_management_research_records.csv", payload["records"])
    print(
        json.dumps(
            {
                "classification": payload["classification"],
                "best_profile": payload["best_profile"],
                "baseline": payload["baseline_summary"],
                "best": payload["best_summary"],
                "report": str((OUTPUT_DIR / "wider_management_research.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_research() -> dict[str, Any]:
    source_rows = load_source_trades()
    candles_by_year = load_m5_candles()
    records: list[dict[str, Any]] = []
    for profile in PROFILES:
        for scenario in SCENARIOS:
            for index, row in enumerate(source_rows):
                candles = candles_by_year.get(int(row["year"]), [])
                record = simulate_entry(row=row, trade_index=index, candles=candles, profile=profile, scenario=scenario)
                if record is not None:
                    records.append(record)
    summaries = summarize_records(records)
    ranking = rank_profiles(summaries)
    baseline_summary = summaries["fast_03_be_08"]["realistic_mt5"]
    best_profile = ranking[0]["profile"]
    best_summary = summaries[best_profile]["realistic_mt5"]
    return {
        "research": "DISPLACEMENT_PLUS_WICK_V1_WIDER_MANAGEMENT_RESEARCH",
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "baseline": "MTF_REAL_H4_FIXED_BASELINE",
        "source_trades": str(SOURCE_TRADES.resolve()),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "profiles": [asdict(profile) for profile in PROFILES],
        "scenarios": [asdict(scenario) for scenario in SCENARIOS],
        "summaries": summaries,
        "ranking": ranking,
        "best_profile": best_profile,
        "baseline_summary": baseline_summary,
        "best_summary": best_summary,
        "classification": classify_result(baseline_summary=baseline_summary, best_summary=best_summary),
        "records": records,
        "notes": [
            "Entries are frozen from displacement_plus_wick_v1.",
            "M5 candle path is used for target/stop replay; M1 precision is not used in this research.",
            "Execution costs are subtracted in R using spread/slippage divided by original risk.",
        ],
    }


def load_source_trades() -> list[dict[str, Any]]:
    with SOURCE_TRADES.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("year", "hour_ny", "confidence", "mtf_score", "quant_score", "impulse_score"):
            row[key] = int(float(row[key]))
        for key in ("entry", "stop", "target", "risk", "rr", "mfe_r", "mae_r", "atr_ratio", "range_ratio"):
            row[key] = float(row[key])
    return rows


def load_m5_candles() -> dict[int, list[Candle]]:
    loader = MaximoMTFQuantV4Backtester(INPUT_DIR, OUTPUT_DIR)
    result: dict[int, list[Candle]] = {}
    for year in (2023, 2024, 2025, 2026):
        family = loader._load_year_family("XAUUSDm", year)
        result[year] = family.get("M5", [])
    return result


def simulate_entry(
    *,
    row: dict[str, Any],
    trade_index: int,
    candles: list[Candle],
    profile: ManagementProfile,
    scenario: ExecutionScenario,
) -> dict[str, Any] | None:
    if not candles:
        return None
    entry_time = datetime.fromisoformat(str(row["entry_time"]))
    start_index = next((idx for idx, candle in enumerate(candles) if candle.time >= entry_time), None)
    if start_index is None:
        return None
    p = adapt_profile(profile, row)
    entry = float(row["entry"])
    risk = max(float(row["risk"]), 1e-9)
    side = str(row["side"]).upper()
    cost_r = (scenario.spread_price + scenario.slippage_price) / risk
    partial_trigger = p.partial_trigger_r + scenario.partial_trigger_delay_r
    protect_trigger = p.protect_trigger_r + scenario.protect_trigger_delay_r
    target_trigger = p.target_r + scenario.target_delay_r
    partial_queue_failed = queue_fails(trade_index, scenario.partial_queue_fail_every)
    trailing_queue_failed = queue_fails(trade_index, scenario.trailing_queue_fail_every)

    partial_taken = False
    protected_active = False
    be_active = False
    max_favorable = 0.0
    max_adverse = 0.0
    exit_reason = "OPEN_UNKNOWN"
    exit_index = min(len(candles) - 1, start_index + 80)
    realized_r = 0.0
    partial_fraction_effective = 0.0

    for cursor in range(start_index, min(len(candles), start_index + 80)):
        candle = candles[cursor]
        favorable, adverse = favorable_adverse(candle=candle, side=side, entry=entry, risk=risk)
        max_favorable = max(max_favorable, favorable)
        max_adverse = max(max_adverse, adverse)

        active_stop_r = -1.0
        if protected_active:
            active_stop_r = p.protected_stop_r - scenario.protected_stop_slippage_r
        elif be_active:
            active_stop_r = -scenario.be_slippage_r

        target_hit = favorable >= target_trigger
        stop_hit = stop_hit_for_active_stop(candle=candle, side=side, entry=entry, risk=risk, active_stop_r=active_stop_r)
        if target_hit or stop_hit:
            exit_index = cursor
            if target_hit and stop_hit and scenario.conflict_policy == "target_first":
                exit_reason = "TARGET"
                realized_r = p.target_r
            elif stop_hit:
                exit_reason = "PROTECTED_STOP" if protected_active else "BE_STOP" if be_active else "SL"
                realized_r = active_stop_r if active_stop_r > -1.0 else -1.01 - scenario.stop_slippage_r
            else:
                exit_reason = "TARGET"
                realized_r = p.target_r
            break

        if not partial_taken and favorable >= partial_trigger and not partial_queue_failed:
            partial_taken = True
            be_active = True
            partial_fraction_effective = p.partial_fraction * scenario.partial_fill_ratio
        if partial_taken and not protected_active and favorable >= protect_trigger and not trailing_queue_failed:
            protected_active = True
        exit_index = cursor
    else:
        final_close = candles[exit_index].close
        realized_r = ((final_close - entry) / risk) if side == "BUY" else ((entry - final_close) / risk)

    if partial_taken:
        partial_exit_r = max(0.0, p.partial_trigger_r - cost_r * 0.25)
        remaining_fraction = 1.0 - partial_fraction_effective
        realized_r = partial_fraction_effective * partial_exit_r + remaining_fraction * realized_r

    realized_after_cost = realized_r - cost_r
    duration_minutes = max(0, (exit_index - start_index + 1) * 5)
    return {
        "profile": profile.code,
        "scenario": scenario.code,
        "year": row["year"],
        "side": row["side"],
        "session": row["session"],
        "hour_ny": row["hour_ny"],
        "atr_bucket": row["atr_bucket"],
        "expansion_subtype": row["expansion_subtype"],
        "continuation_quality": row["continuation_quality"],
        "signal_time": row["signal_time"],
        "entry_time": row["entry_time"],
        "exit_reason": exit_reason,
        "risk": round(risk, 5),
        "target_r": p.target_r,
        "partial_trigger_r": p.partial_trigger_r,
        "protect_trigger_r": p.protect_trigger_r,
        "partial_taken": partial_taken,
        "protected_at_0_8R": protected_active,
        "be_moved": be_active,
        "partial_queue_failed": partial_queue_failed,
        "trailing_queue_failed": trailing_queue_failed,
        "cost_r": round(cost_r, 4),
        "spread_price": scenario.spread_price,
        "slippage_price": scenario.slippage_price,
        "mfe_r": round(max_favorable, 4),
        "mae_r": round(max_adverse, 4),
        "realized_before_cost_R": round(realized_r, 4),
        "realized_R": round(realized_after_cost, 4),
        "duration_minutes": duration_minutes,
        "mfe_utilization": round(realized_after_cost / max_favorable, 4) if max_favorable > 0 else 0.0,
    }


def adapt_profile(profile: ManagementProfile, row: dict[str, Any]) -> ManagementProfile:
    if not profile.adaptive:
        return profile
    atr_bucket = str(row.get("atr_bucket", "normal_atr"))
    if atr_bucket in {"high_atr", "extreme_atr"}:
        return ManagementProfile(
            profile.code,
            profile.label,
            partial_trigger_r=0.60,
            partial_fraction=0.35,
            protect_trigger_r=1.35,
            protected_stop_r=0.55,
            target_r=2.25,
            adaptive=True,
        )
    if atr_bucket == "low_atr":
        return ManagementProfile(
            profile.code,
            profile.label,
            partial_trigger_r=0.40,
            partial_fraction=0.45,
            protect_trigger_r=0.95,
            protected_stop_r=0.25,
            target_r=1.60,
            adaptive=True,
        )
    return profile


def favorable_adverse(*, candle: Candle, side: str, entry: float, risk: float) -> tuple[float, float]:
    if side == "BUY":
        return (candle.high - entry) / risk, (entry - candle.low) / risk
    return (entry - candle.low) / risk, (candle.high - entry) / risk


def stop_hit_for_active_stop(*, candle: Candle, side: str, entry: float, risk: float, active_stop_r: float) -> bool:
    if side == "BUY":
        stop_price = entry + active_stop_r * risk
        return candle.low <= stop_price
    stop_price = entry - active_stop_r * risk
    return candle.high >= stop_price


def queue_fails(index: int, every: int) -> bool:
    return every > 0 and (index + 1) % every == 0


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for profile in (profile.code for profile in PROFILES):
        result[profile] = {}
        for scenario in (scenario.code for scenario in SCENARIOS):
            bucket = [row for row in records if row["profile"] == profile and row["scenario"] == scenario]
            ideal_bucket = [row for row in records if row["profile"] == profile and row["scenario"] == "ideal_replay"]
            result[profile][scenario] = scenario_summary(bucket, ideal_bucket)
    return result


def scenario_summary(records: list[dict[str, Any]], ideal_records: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["realized_R"]) for row in records]
    ideal_values = [float(row["realized_R"]) for row in ideal_records]
    metric = metrics(values)
    ideal_metric = metrics(ideal_values)
    ideal_by_entry = {row["entry_time"]: float(row["realized_R"]) for row in ideal_records}
    protected_winners_lost = sum(
        1
        for row in records
        if ideal_by_entry.get(row["entry_time"], 0.0) > 0 and float(row["realized_R"]) <= 0
    )
    avg_mfe = average([float(row["mfe_r"]) for row in records])
    avg_realized = average(values)
    return {
        **metric,
        "spread_impact_R": round(sum(float(row["cost_r"]) for row in records), 4),
        "protected_winners_lost": protected_winners_lost,
        "average_R_captured": round(avg_realized, 4),
        "average_MFE_R": round(avg_mfe, 4),
        "MFE_utilization": round(avg_realized / avg_mfe, 4) if avg_mfe > 0 else 0.0,
        "avg_trade_duration_minutes": round(average([float(row["duration_minutes"]) for row in records]), 2),
        "partial_taken": sum(1 for row in records if row["partial_taken"]),
        "be_moved": sum(1 for row in records if row["be_moved"]),
        "protected": sum(1 for row in records if row["protected_at_0_8R"]),
        "BE_degradation": sum(1 for row in records if row["be_moved"] and float(row["realized_R"]) <= 0),
        "pf_degradation_pct": degradation(ideal_metric["profit_factor"], metric["profit_factor"]),
        "expectancy_degradation_pct": degradation(ideal_metric["expectancy_R"], metric["expectancy_R"]),
        "by_year": breakdown(records, "year"),
        "by_session": breakdown(records, "session"),
        "by_side": breakdown(records, "side"),
    }


def metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_R": 0.0,
            "net_R": 0.0,
            "max_drawdown_R": 0.0,
            "losing_streak": 0,
        }
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = peak = max_dd = 0.0
    streak = losing_streak = 0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if value < 0:
            streak += 1
            losing_streak = max(losing_streak, streak)
        else:
            streak = 0
    return {
        "trades": len(values),
        "win_rate": round(len(wins) / len(values) * 100.0, 2),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else 0.0),
        "expectancy_R": round(sum(values) / len(values), 4),
        "net_R": round(sum(values), 4),
        "max_drawdown_R": round(max_dd, 4),
        "losing_streak": losing_streak,
    }


def breakdown(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in records:
        grouped[str(row.get(key, "UNKNOWN"))].append(float(row["realized_R"]))
    return {bucket: metrics(values) for bucket, values in sorted(grouped.items())}


def rank_profiles(summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for profile, scenario_map in summaries.items():
        realistic = scenario_map["realistic_mt5"]
        pessimistic = scenario_map["pessimistic_execution"]
        score = (
            realistic["profit_factor"] * 8.0
            + realistic["expectancy_R"] * 20.0
            - realistic["max_drawdown_R"] * 0.8
            + pessimistic["profit_factor"] * 3.0
            - realistic["protected_winners_lost"] * 0.05
        )
        rows.append(
            {
                "profile": profile,
                "score": round(score, 4),
                "ideal": scenario_map["ideal_replay"],
                "realistic": realistic,
                "pessimistic": pessimistic,
            }
        )
    return sorted(rows, key=lambda item: item["score"], reverse=True)


def classify_result(*, baseline_summary: dict[str, Any], best_summary: dict[str, Any]) -> str:
    if best_summary["profit_factor"] <= baseline_summary["profit_factor"] and best_summary["expectancy_R"] <= baseline_summary["expectancy_R"]:
        return "NO IMPROVEMENT"
    if best_summary["profit_factor"] >= 1.2 and best_summary["expectancy_R"] > 0:
        return "MANAGEMENT IMPROVEMENT"
    if best_summary["max_drawdown_R"] > baseline_summary["max_drawdown_R"] * 1.5:
        return "OVEREXTENDED MANAGEMENT"
    return "NO IMPROVEMENT"


def degradation(ideal: float, stressed: float) -> float:
    if ideal in (0.0, 999.0):
        return 0.0
    return round((ideal - stressed) / abs(ideal) * 100.0, 2)


def average(values: list[float]) -> float:
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
        "# displacement_plus_wick_v1 Wider Management Research",
        "",
        f"- status: {payload['status']}",
        f"- baseline: `{payload['baseline']}`",
        f"- classification: `{payload['classification']}`",
        f"- best_profile: `{payload['best_profile']}`",
        f"- source_trades: `{payload['source_trades']}`",
        "",
        "## Ranking",
        "",
        "| Rank | Profile | Score | Realistic PF | Realistic Exp R | Realistic DD | Pessimistic PF | Protected Winners Lost | MFE Util | Avg Duration |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, item in enumerate(payload["ranking"], start=1):
        realistic = item["realistic"]
        pessimistic = item["pessimistic"]
        lines.append(
            f"| {index} | {item['profile']} | {item['score']} | {realistic['profit_factor']} | "
            f"{realistic['expectancy_R']} | {realistic['max_drawdown_R']} | {pessimistic['profit_factor']} | "
            f"{realistic['protected_winners_lost']} | {realistic['MFE_utilization']} | {realistic['avg_trade_duration_minutes']} |"
        )
    lines.extend(
        [
            "",
            "## Scenario Comparison",
            "",
            "| Profile | Scenario | Trades | WR | PF | Exp R | Net R | DD R | Spread Impact R | BE Deg | Avg R Captured | MFE Util | Duration |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for profile, scenario_map in payload["summaries"].items():
        for scenario, metric in scenario_map.items():
            lines.append(
                f"| {profile} | {scenario} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['spread_impact_R']} | "
                f"{metric['BE_degradation']} | {metric['average_R_captured']} | {metric['MFE_utilization']} | "
                f"{metric['avg_trade_duration_minutes']} |"
            )
    lines.extend(["", "## Notes"])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
