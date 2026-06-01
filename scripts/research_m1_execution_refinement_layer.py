"""Research M1 execution refinement for displacement_plus_wick_v1.

Research only. The M5 detector and displacement_plus_wick_v1 entry set remain
frozen. M1 is used only to test whether a short execution window can improve
entry price, effective risk and cost-adjusted R.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
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
OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "m1_execution_refinement"


@dataclass(frozen=True, slots=True)
class M1Variant:
    code: str
    label: str
    max_wait_m1: int
    mode: str


@dataclass(frozen=True, slots=True)
class ManagementProfile:
    partial_trigger_r: float = 0.30
    partial_fraction: float = 0.40
    protect_trigger_r: float = 0.80
    protected_stop_r: float = 0.30


@dataclass(frozen=True, slots=True)
class ExecutionScenario:
    code: str
    spread_price: float = 0.0
    slippage_price: float = 0.0
    partial_delay_r: float = 0.0
    protect_delay_r: float = 0.0
    be_slippage_r: float = 0.0
    protected_slippage_r: float = 0.0
    stop_slippage_r: float = 0.0


VARIANTS = [
    M1Variant("m5_original", "Original M5 entry baseline", 0, "original"),
    M1Variant("m1_immediate_next_candle", "M1 immediate next candle", 1, "immediate"),
    M1Variant("m1_pullback_30_50", "M1 pullback to 30%-50% of original risk", 5, "pullback_30_50"),
    M1Variant("m1_wick_rejection_confirmation", "M1 wick rejection confirmation", 5, "wick_rejection"),
    M1Variant("m1_micro_bos", "M1 micro BOS/CHOCH", 5, "micro_bos"),
    M1Variant("m1_continuation_candle", "M1 continuation candle", 5, "continuation"),
    M1Variant("m1_best_of_first_3", "M1 best achievable entry in first 3 candles", 3, "best_of_window"),
    M1Variant("m1_best_of_first_5", "M1 best achievable entry in first 5 candles", 5, "best_of_window"),
]


SCENARIOS = [
    ExecutionScenario("ideal"),
    ExecutionScenario(
        "realistic_mt5",
        spread_price=0.308,
        slippage_price=0.05,
        partial_delay_r=0.05,
        protect_delay_r=0.05,
        be_slippage_r=0.03,
        protected_slippage_r=0.05,
        stop_slippage_r=0.03,
    ),
]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_research()
    (OUTPUT_DIR / "m1_execution_refinement_layer.json").write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "m1_execution_refinement_layer.md").write_text(render_report(payload), encoding="utf-8")
    write_records_csv(OUTPUT_DIR / "m1_execution_refinement_records.csv", payload["records"])
    print(
        json.dumps(
            {
                "classification": payload["classification"],
                "best_variant": payload["best_variant"],
                "baseline_realistic": payload["baseline_realistic"],
                "best_realistic": payload["best_realistic"],
                "report": str((OUTPUT_DIR / "m1_execution_refinement_layer.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_research() -> dict[str, Any]:
    source_rows = load_source_trades()
    m1_by_year = load_candles("M1")
    records: list[dict[str, Any]] = []
    misses: dict[str, int] = defaultdict(int)
    for row in source_rows:
        m1 = m1_by_year.get(int(row["year"]), [])
        for variant in VARIANTS:
            candidate = refine_entry(row=row, candles=m1, variant=variant)
            if candidate is None:
                misses[variant.code] += 1
                continue
            for scenario in SCENARIOS:
                records.append(simulate_candidate(row=row, candidate=candidate, scenario=scenario))
    summaries = summarize(records=records, total_source_trades=len(source_rows), misses=misses)
    ranking = rank_variants(summaries)
    best_variant = ranking[0]["variant"]
    baseline_realistic = summaries["m5_original"]["realistic_mt5"]
    best_realistic = summaries[best_variant]["realistic_mt5"]
    return {
        "research": "M1_EXECUTION_REFINEMENT_LAYER",
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "detector": "M5 displacement_plus_wick_v1 frozen",
        "baseline": "MTF_REAL_H4_FIXED_BASELINE",
        "management": "REACTION_ZONE_MANAGEMENT_OVERLAY_V1 fast_03_be_08",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_trades": str(SOURCE_TRADES.resolve()),
        "variants": [asdict(variant) for variant in VARIANTS],
        "scenarios": [asdict(scenario) for scenario in SCENARIOS],
        "summaries": summaries,
        "ranking": ranking,
        "best_variant": best_variant,
        "baseline_realistic": baseline_realistic,
        "best_realistic": best_realistic,
        "classification": classify(baseline=baseline_realistic, best=best_realistic),
        "records": records,
        "notes": [
            "M5 detector is unchanged; only the execution price/SL is refined after the frozen M5 signal.",
            "M1 best-of variants are optimistic upper-bound research and should not be treated as executable logic.",
            "Realistic MT5 scenario subtracts XAUUSDm spread/slippage in R, so smaller M1 stops are punished if too tight.",
        ],
    }


def load_source_trades() -> list[dict[str, Any]]:
    with SOURCE_TRADES.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("year", "hour_ny"):
            row[key] = int(float(row[key]))
        for key in ("entry", "stop", "target", "risk", "rr", "atr_ratio", "range_ratio"):
            row[key] = float(row[key])
    return rows


def load_candles(timeframe: str) -> dict[int, list[Candle]]:
    loader = MaximoMTFQuantV4Backtester(INPUT_DIR, OUTPUT_DIR)
    result: dict[int, list[Candle]] = {}
    for year in (2023, 2024, 2025, 2026):
        family = loader._load_year_family("XAUUSDm", year)
        result[year] = family.get(timeframe, [])
    return result


def refine_entry(*, row: dict[str, Any], candles: list[Candle], variant: M1Variant) -> dict[str, Any] | None:
    if not candles:
        return None
    original_entry_time = datetime.fromisoformat(str(row["entry_time"]))
    start = next((idx for idx, candle in enumerate(candles) if candle.time >= original_entry_time), None)
    if start is None:
        return None
    original_entry = float(row["entry"])
    original_stop = float(row["stop"])
    original_target = float(row["target"])
    original_risk = float(row["risk"])
    side = str(row["side"]).upper()
    if variant.mode == "original":
        return build_candidate(
            row=row,
            variant=variant,
            entry=original_entry,
            stop=original_stop,
            target=original_target,
            entry_index=start,
            reason="m5_original_entry",
            candles=candles,
        )
    window = candles[start : start + max(1, variant.max_wait_m1)]
    if not window:
        return None
    if variant.mode == "immediate":
        candle = window[0]
        return build_candidate(
            row=row,
            variant=variant,
            entry=candle.open,
            stop=original_stop,
            target=original_target,
            entry_index=start,
            reason="first_m1_open",
            candles=candles,
        )
    if variant.mode == "pullback_30_50":
        desired = original_entry - original_risk * 0.40 if side == "BUY" else original_entry + original_risk * 0.40
        for offset, candle in enumerate(window):
            touched = candle.low <= desired if side == "BUY" else candle.high >= desired
            if touched:
                return build_candidate(
                    row=row,
                    variant=variant,
                    entry=desired,
                    stop=original_stop,
                    target=original_target,
                    entry_index=start + offset,
                    reason="limit_pullback_40pct_original_risk",
                    candles=candles,
                )
        return None
    if variant.mode == "best_of_window":
        if side == "BUY":
            best_offset, best_candle = min(enumerate(window), key=lambda item: item[1].low)
            entry = best_candle.low
        else:
            best_offset, best_candle = max(enumerate(window), key=lambda item: item[1].high)
            entry = best_candle.high
        return build_candidate(
            row=row,
            variant=variant,
            entry=entry,
            stop=original_stop,
            target=original_target,
            entry_index=start + best_offset,
            reason="optimistic_best_achievable_window_entry",
            candles=candles,
        )
    for offset, candle in enumerate(window):
        if variant.mode == "wick_rejection" and not has_wick_rejection(candle, side):
            continue
        if variant.mode == "micro_bos" and not has_micro_bos(candles, start + offset, side):
            continue
        if variant.mode == "continuation" and not has_continuation(candle, side):
            continue
        confirm_index = start + offset
        entry_index = min(confirm_index + 1, len(candles) - 1)
        entry = candles[entry_index].open
        stop = micro_stop(candles=candles, start=start, confirm_index=confirm_index, side=side, original_risk=original_risk)
        return build_candidate(
            row=row,
            variant=variant,
            entry=entry,
            stop=stop,
            target=original_target,
            entry_index=entry_index,
            reason=variant.mode,
            candles=candles,
        )
    return None


def build_candidate(
    *,
    row: dict[str, Any],
    variant: M1Variant,
    entry: float,
    stop: float,
    target: float,
    entry_index: int,
    reason: str,
    candles: list[Candle],
) -> dict[str, Any] | None:
    side = str(row["side"]).upper()
    original_entry = float(row["entry"])
    original_risk = float(row["risk"])
    risk = entry - stop if side == "BUY" else stop - entry
    rr = (target - entry) / risk if side == "BUY" and risk > 0 else (entry - target) / risk if risk > 0 else 0.0
    if risk <= 0 or rr <= 0:
        return None
    if variant.mode in {"wick_rejection", "micro_bos", "continuation"} and risk > original_risk * 1.05:
        return None
    improvement = original_entry - entry if side == "BUY" else entry - original_entry
    return {
        "variant": variant.code,
        "entry": round(entry, 5),
        "stop": round(stop, 5),
        "target": round(target, 5),
        "risk": round(risk, 5),
        "rr": round(rr, 4),
        "entry_index": entry_index,
        "entry_time_refined": candles[entry_index].time.isoformat(),
        "reason": reason,
        "entry_improvement_price": round(improvement, 5),
        "entry_improvement_R_original": round(improvement / original_risk, 4) if original_risk else 0.0,
        "risk_reduction_pct": round((original_risk - risk) / original_risk * 100.0, 2) if original_risk else 0.0,
        "rr_improvement": round(rr - float(row["rr"]), 4),
    }


def simulate_candidate(*, row: dict[str, Any], candidate: dict[str, Any], scenario: ExecutionScenario) -> dict[str, Any]:
    candles = load_candles_for_year_cached(int(row["year"]))
    entry_index = int(candidate["entry_index"])
    side = str(row["side"]).upper()
    entry = float(candidate["entry"])
    risk = max(float(candidate["risk"]), 1e-9)
    target_r = float(candidate["rr"])
    profile = ManagementProfile()
    partial_trigger = profile.partial_trigger_r + scenario.partial_delay_r
    protect_trigger = profile.protect_trigger_r + scenario.protect_delay_r
    cost_r = (scenario.spread_price + scenario.slippage_price) / risk
    partial_taken = False
    protected = False
    be_active = False
    mfe = mae = 0.0
    realized = 0.0
    exit_reason = "OPEN_UNKNOWN"
    exit_index = min(len(candles) - 1, entry_index + 400)
    for cursor in range(entry_index, min(len(candles), entry_index + 400)):
        candle = candles[cursor]
        favorable, adverse = favorable_adverse(candle=candle, side=side, entry=entry, risk=risk)
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)
        active_stop_r = -1.0
        if protected:
            active_stop_r = profile.protected_stop_r - scenario.protected_slippage_r
        elif be_active:
            active_stop_r = -scenario.be_slippage_r
        target_hit = favorable >= target_r
        stop_hit = stop_hit_for_active_stop(candle=candle, side=side, entry=entry, risk=risk, active_stop_r=active_stop_r)
        if target_hit or stop_hit:
            exit_index = cursor
            if stop_hit:
                realized = active_stop_r if active_stop_r > -1.0 else -1.01 - scenario.stop_slippage_r
                exit_reason = "PROTECTED_STOP" if protected else "BE_STOP" if be_active else "SL"
            else:
                realized = target_r
                exit_reason = "TARGET"
            break
        if not partial_taken and favorable >= partial_trigger:
            partial_taken = True
            be_active = True
        if partial_taken and not protected and favorable >= protect_trigger:
            protected = True
        exit_index = cursor
    else:
        final_close = candles[exit_index].close
        realized = ((final_close - entry) / risk) if side == "BUY" else ((entry - final_close) / risk)

    if partial_taken:
        partial_gain = profile.partial_fraction * max(0.0, profile.partial_trigger_r - cost_r * 0.25)
        realized = partial_gain + (1.0 - profile.partial_fraction) * realized
    realized_after_cost = realized - cost_r
    return {
        "variant": candidate["variant"],
        "scenario": scenario.code,
        "year": row["year"],
        "side": row["side"],
        "session": row["session"],
        "hour_ny": row["hour_ny"],
        "signal_time": row["signal_time"],
        "original_entry_time": row["entry_time"],
        "entry_time_refined": candidate["entry_time_refined"],
        "reason": candidate["reason"],
        "entry": candidate["entry"],
        "stop": candidate["stop"],
        "target": candidate["target"],
        "risk": candidate["risk"],
        "rr": candidate["rr"],
        "entry_improvement_price": candidate["entry_improvement_price"],
        "entry_improvement_R_original": candidate["entry_improvement_R_original"],
        "risk_reduction_pct": candidate["risk_reduction_pct"],
        "rr_improvement": candidate["rr_improvement"],
        "mfe_r": round(mfe, 4),
        "mae_r": round(mae, 4),
        "partial_taken": partial_taken,
        "be_moved": be_active,
        "protected": protected,
        "cost_r": round(cost_r, 4),
        "exit_reason": exit_reason,
        "realized_R": round(realized_after_cost, 4),
        "duration_minutes": max(0, (exit_index - entry_index + 1)),
    }


_CANDLE_CACHE: dict[int, list[Candle]] = {}


def load_candles_for_year_cached(year: int) -> list[Candle]:
    if year not in _CANDLE_CACHE:
        _CANDLE_CACHE.update(load_candles("M1"))
    return _CANDLE_CACHE[year]


def has_wick_rejection(candle: Candle, side: str) -> bool:
    candle_range = max(candle.high - candle.low, 1e-9)
    body = abs(candle.close - candle.open)
    lower_wick = min(candle.open, candle.close) - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    body_pct = body / candle_range * 100.0
    if side == "BUY":
        return lower_wick / candle_range * 100.0 >= 35.0 and candle.close > candle.open and body_pct >= 20.0
    return upper_wick / candle_range * 100.0 >= 35.0 and candle.close < candle.open and body_pct >= 20.0


def has_micro_bos(candles: list[Candle], index: int, side: str) -> bool:
    if index < 3:
        return False
    previous = candles[index - 3 : index]
    candle = candles[index]
    if side == "BUY":
        return candle.high > max(item.high for item in previous) and candle.close > candle.open
    return candle.low < min(item.low for item in previous) and candle.close < candle.open


def has_continuation(candle: Candle, side: str) -> bool:
    candle_range = max(candle.high - candle.low, 1e-9)
    body_pct = abs(candle.close - candle.open) / candle_range * 100.0
    if side == "BUY":
        close_power = (candle.close - candle.low) / candle_range
        return candle.close > candle.open and body_pct >= 45.0 and close_power >= 0.65
    close_power = (candle.high - candle.close) / candle_range
    return candle.close < candle.open and body_pct >= 45.0 and close_power >= 0.65


def micro_stop(*, candles: list[Candle], start: int, confirm_index: int, side: str, original_risk: float) -> float:
    window = candles[start : confirm_index + 1]
    buffer = original_risk * 0.05
    if side == "BUY":
        return min(item.low for item in window) - buffer
    return max(item.high for item in window) + buffer


def favorable_adverse(*, candle: Candle, side: str, entry: float, risk: float) -> tuple[float, float]:
    if side == "BUY":
        return (candle.high - entry) / risk, (entry - candle.low) / risk
    return (entry - candle.low) / risk, (candle.high - entry) / risk


def stop_hit_for_active_stop(*, candle: Candle, side: str, entry: float, risk: float, active_stop_r: float) -> bool:
    if side == "BUY":
        return candle.low <= entry + active_stop_r * risk
    return candle.high >= entry - active_stop_r * risk


def summarize(*, records: list[dict[str, Any]], total_source_trades: int, misses: dict[str, int]) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for variant in (variant.code for variant in VARIANTS):
        result[variant] = {}
        for scenario in (scenario.code for scenario in SCENARIOS):
            bucket = [row for row in records if row["variant"] == variant and row["scenario"] == scenario]
            result[variant][scenario] = {
                **metrics([float(row["realized_R"]) for row in bucket]),
                "missed_trades": misses.get(variant, 0),
                "frequency_retained_pct": round(len(bucket) / total_source_trades * 100.0, 2) if total_source_trades else 0.0,
                "avg_entry_improvement_R": round(avg([float(row["entry_improvement_R_original"]) for row in bucket]), 4),
                "avg_risk_reduction_pct": round(avg([float(row["risk_reduction_pct"]) for row in bucket]), 2),
                "avg_rr_improvement": round(avg([float(row["rr_improvement"]) for row in bucket]), 4),
                "avg_cost_R": round(avg([float(row["cost_r"]) for row in bucket]), 4),
                "avg_duration_m1": round(avg([float(row["duration_minutes"]) for row in bucket]), 2),
                "by_session": breakdown(bucket, "session"),
                "by_side": breakdown(bucket, "side"),
            }
    return result


def metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0, "net_R": 0.0, "max_drawdown_R": 0.0, "losing_streak": 0}
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


def rank_variants(summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for variant, scenario_map in summaries.items():
        realistic = scenario_map["realistic_mt5"]
        ideal = scenario_map["ideal"]
        score = (
            realistic["profit_factor"] * 10.0
            + realistic["expectancy_R"] * 25.0
            - realistic["max_drawdown_R"] * 0.6
            - realistic["missed_trades"] * 0.04
            + realistic["avg_entry_improvement_R"] * 2.0
        )
        rows.append({"variant": variant, "score": round(score, 4), "ideal": ideal, "realistic": realistic})
    return sorted(rows, key=lambda item: item["score"], reverse=True)


def classify(*, baseline: dict[str, Any], best: dict[str, Any]) -> str:
    if best["missed_trades"] > baseline["trades"] * 0.45:
        return "M1 REDUCES FREQUENCY TOO MUCH"
    if best["expectancy_R"] <= baseline["expectancy_R"] and best["profit_factor"] <= baseline["profit_factor"]:
        return "M1 NO IMPROVEMENT"
    if best["avg_entry_improvement_R"] < 0:
        return "M1 TOO LATE"
    if best["profit_factor"] >= 1.1 and best["expectancy_R"] > 0:
        return "M1 IMPROVES EDGE"
    return "NEEDS MORE DATA"


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
        "# M1_EXECUTION_REFINEMENT_LAYER Research",
        "",
        f"- status: {payload['status']}",
        f"- detector: `{payload['detector']}`",
        f"- baseline: `{payload['baseline']}`",
        f"- management: `{payload['management']}`",
        f"- classification: `{payload['classification']}`",
        f"- best_variant: `{payload['best_variant']}`",
        "",
        "## Ranking",
        "",
        "| Rank | Variant | Score | Trades | Missed | Retained | PF Realistic | Exp R Realistic | DD | Entry Improve R | Risk Reduction | RR Improve | Cost R |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, item in enumerate(payload["ranking"], start=1):
        r = item["realistic"]
        lines.append(
            f"| {index} | {item['variant']} | {item['score']} | {r['trades']} | {r['missed_trades']} | "
            f"{r['frequency_retained_pct']}% | {r['profit_factor']} | {r['expectancy_R']} | {r['max_drawdown_R']} | "
            f"{r['avg_entry_improvement_R']} | {r['avg_risk_reduction_pct']}% | {r['avg_rr_improvement']} | {r['avg_cost_R']} |"
        )
    lines.extend(
        [
            "",
            "## Variant Comparison",
            "",
            "| Variant | Scenario | Trades | WR | PF | Exp R | Net R | DD R | Missed | Entry Improve R | Risk Reduction | RR Improve | Cost R | Duration M1 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for variant, scenario_map in payload["summaries"].items():
        for scenario, metric in scenario_map.items():
            lines.append(
                f"| {variant} | {scenario} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['missed_trades']} | "
                f"{metric['avg_entry_improvement_R']} | {metric['avg_risk_reduction_pct']}% | {metric['avg_rr_improvement']} | "
                f"{metric['avg_cost_R']} | {metric['avg_duration_m1']} |"
            )
    lines.extend(["", "## Best Variant By Session", ""])
    best = payload["best_variant"]
    lines.extend(render_breakdown(payload["summaries"][best]["realistic_mt5"]["by_session"]))
    lines.extend(["", "## Notes"])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_breakdown(items: dict[str, Any]) -> list[str]:
    lines = ["| Bucket | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for bucket, metric in items.items():
        lines.append(
            f"| {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
            f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']} |"
        )
    return lines


if __name__ == "__main__":
    main()
