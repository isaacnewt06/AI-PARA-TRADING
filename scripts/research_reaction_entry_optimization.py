"""Research executable M1 entry optimization rules.

Research only. The M5 displacement_plus_wick_v1 detector is frozen. This
script turns the previous "best achievable M1" upper bound into executable
limit/confirmation rules and measures whether any rule approximates the oracle
without relying on lookahead.
"""

from __future__ import annotations

import csv
import json
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
OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "reaction_entry_optimization"


@dataclass(frozen=True, slots=True)
class EntryRule:
    code: str
    label: str
    mode: str
    max_wait_m1: int
    retrace_r: float = 0.0
    retrace_fraction: float = 0.0
    atr_fraction: float = 0.0
    executable: bool = True


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


RULES = [
    EntryRule("m5_original", "Original M5 entry", "original", 0),
    EntryRule("limit_retrace_20r_3m", "Limit retrace 20% original R, first 3 M1", "risk_retrace", 3, retrace_r=0.20),
    EntryRule("limit_retrace_30r_3m", "Limit retrace 30% original R, first 3 M1", "risk_retrace", 3, retrace_r=0.30),
    EntryRule("limit_retrace_40r_5m", "Limit retrace 40% original R, first 5 M1", "risk_retrace", 5, retrace_r=0.40),
    EntryRule("limit_retrace_50r_5m", "Limit retrace 50% original R, first 5 M1", "risk_retrace", 5, retrace_r=0.50),
    EntryRule("m5_body_33_5m", "M5 displacement zone 33% body retrace", "m5_body_retrace", 5, retrace_fraction=0.33),
    EntryRule("m5_body_mid_5m", "M5 displacement zone 50% body retrace", "m5_body_retrace", 5, retrace_fraction=0.50),
    EntryRule("m5_wick_retrace_50_5m", "M5 wick retrace midpoint", "m5_wick_retrace", 5, retrace_fraction=0.50),
    EntryRule("atr_retrace_15_5m", "ATR-relative retrace 0.15 ATR(M5)", "atr_retrace", 5, atr_fraction=0.15),
    EntryRule("atr_retrace_25_5m", "ATR-relative retrace 0.25 ATR(M5)", "atr_retrace", 5, atr_fraction=0.25),
    EntryRule("inside_first_m1_body_50_3m", "Entry inside first M1 reaction candle body midpoint", "first_m1_body", 3, retrace_fraction=0.50),
    EntryRule("mini_liquidity_tap_5m", "Enter after mini liquidity tap confirmation", "mini_liquidity_tap", 5),
    EntryRule("failed_continuation_5m", "Enter after failed continuation and reclaim", "failed_continuation", 5),
    EntryRule("oracle_best_of_first_3", "Oracle benchmark best of first 3 M1", "oracle_best", 3, executable=False),
    EntryRule("oracle_best_of_first_5", "Oracle benchmark best of first 5 M1", "oracle_best", 5, executable=False),
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
    (OUTPUT_DIR / "reaction_entry_optimization_research.json").write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "reaction_entry_optimization_research.md").write_text(render_report(payload), encoding="utf-8")
    write_records_csv(OUTPUT_DIR / "reaction_entry_optimization_records.csv", payload["records"])
    print(
        json.dumps(
            {
                "classification": payload["classification"],
                "best_executable_rule": payload["best_executable_rule"],
                "baseline_realistic": payload["baseline_realistic"],
                "best_executable_realistic": payload["best_executable_realistic"],
                "oracle_best_5_realistic": payload["summaries"]["oracle_best_of_first_5"]["realistic_mt5"],
                "report": str((OUTPUT_DIR / "reaction_entry_optimization_research.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_research() -> dict[str, Any]:
    source_rows = load_source_trades()
    m1_by_year = load_candles("M1")
    m5_by_year = load_candles("M5")
    records: list[dict[str, Any]] = []
    misses: dict[str, int] = defaultdict(int)
    for row in source_rows:
        m1 = m1_by_year.get(int(row["year"]), [])
        m5 = m5_by_year.get(int(row["year"]), [])
        for rule in RULES:
            candidate = build_entry_candidate(row=row, m1=m1, m5=m5, rule=rule)
            if candidate is None:
                misses[rule.code] += 1
                continue
            for scenario in SCENARIOS:
                records.append(simulate_candidate(row=row, candidate=candidate, scenario=scenario))
    summaries = summarize(records=records, source_count=len(source_rows), misses=misses)
    ranking = rank_rules(summaries)
    executable_ranking = [item for item in ranking if item["executable"]]
    best_rule = executable_ranking[0]["rule"] if executable_ranking else "none"
    return {
        "research": "REACTION_ENTRY_OPTIMIZATION_RESEARCH",
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "detector": "M5 displacement_plus_wick_v1 frozen",
        "baseline": "MTF_REAL_H4_FIXED_BASELINE",
        "management": "REACTION_ZONE_MANAGEMENT_OVERLAY_V1 fast_03_be_08",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_trades": str(SOURCE_TRADES.resolve()),
        "rules": [asdict(rule) for rule in RULES],
        "scenarios": [asdict(scenario) for scenario in SCENARIOS],
        "summaries": summaries,
        "ranking": ranking,
        "best_executable_rule": best_rule,
        "baseline_realistic": summaries["m5_original"]["realistic_mt5"],
        "best_executable_realistic": summaries[best_rule]["realistic_mt5"] if best_rule != "none" else {},
        "classification": classify(
            baseline=summaries["m5_original"]["realistic_mt5"],
            best=summaries[best_rule]["realistic_mt5"] if best_rule != "none" else {},
        ),
        "records": records,
        "notes": [
            "Oracle rules are included only to measure the achievable ceiling and are excluded from executable classification.",
            "Limit rules are executable only if M1 actually touches the limit within the allowed window.",
            "M1 confirmation rules enter after confirmation, so they can be late and are penalized by spread in R.",
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
    return {year: loader._load_year_family("XAUUSDm", year).get(timeframe, []) for year in (2023, 2024, 2025, 2026)}


def build_entry_candidate(*, row: dict[str, Any], m1: list[Candle], m5: list[Candle], rule: EntryRule) -> dict[str, Any] | None:
    if not m1:
        return None
    original_entry_time = datetime.fromisoformat(str(row["entry_time"]))
    start = next((idx for idx, candle in enumerate(m1) if candle.time >= original_entry_time), None)
    if start is None:
        return None
    original_entry = float(row["entry"])
    original_stop = float(row["stop"])
    original_target = float(row["target"])
    original_risk = float(row["risk"])
    side = str(row["side"]).upper()
    if rule.mode == "original":
        return candidate_from_price(
            row=row,
            rule=rule,
            entry=original_entry,
            stop=original_stop,
            target=original_target,
            entry_index=start,
            reason="original_m5_entry",
            m1=m1,
        )
    window = m1[start : start + max(1, rule.max_wait_m1)]
    if not window:
        return None
    if rule.mode == "risk_retrace":
        entry = original_entry - original_risk * rule.retrace_r if side == "BUY" else original_entry + original_risk * rule.retrace_r
        fill_offset = limit_fill_offset(window, side=side, entry=entry)
        if fill_offset is None:
            return None
        return candidate_from_price(row=row, rule=rule, entry=entry, stop=original_stop, target=original_target, entry_index=start + fill_offset, reason="limit_risk_retrace", m1=m1)
    if rule.mode == "oracle_best":
        if side == "BUY":
            fill_offset, candle = min(enumerate(window), key=lambda item: item[1].low)
            entry = candle.low
        else:
            fill_offset, candle = max(enumerate(window), key=lambda item: item[1].high)
            entry = candle.high
        return candidate_from_price(row=row, rule=rule, entry=entry, stop=original_stop, target=original_target, entry_index=start + fill_offset, reason="oracle_best_window_price", m1=m1)
    signal_m5 = find_signal_m5(row=row, m5=m5)
    if signal_m5 is None:
        return None
    if rule.mode == "m5_body_retrace":
        body_low = min(signal_m5.open, signal_m5.close)
        body_high = max(signal_m5.open, signal_m5.close)
        if side == "BUY":
            entry = signal_m5.close - abs(signal_m5.close - signal_m5.open) * rule.retrace_fraction
            entry = min(max(entry, body_low), body_high)
        else:
            entry = signal_m5.close + abs(signal_m5.close - signal_m5.open) * rule.retrace_fraction
            entry = min(max(entry, body_low), body_high)
        fill_offset = limit_fill_offset(window, side=side, entry=entry)
        if fill_offset is None:
            return None
        return candidate_from_price(row=row, rule=rule, entry=entry, stop=original_stop, target=original_target, entry_index=start + fill_offset, reason="m5_body_limit_zone", m1=m1)
    if rule.mode == "m5_wick_retrace":
        entry = wick_retrace_price(signal_m5, side=side, fraction=rule.retrace_fraction)
        if entry is None:
            return None
        fill_offset = limit_fill_offset(window, side=side, entry=entry)
        if fill_offset is None:
            return None
        return candidate_from_price(row=row, rule=rule, entry=entry, stop=original_stop, target=original_target, entry_index=start + fill_offset, reason="m5_wick_limit_zone", m1=m1)
    if rule.mode == "atr_retrace":
        atr = estimate_m5_atr(m5=m5, signal_candle=signal_m5)
        entry = original_entry - atr * rule.atr_fraction if side == "BUY" else original_entry + atr * rule.atr_fraction
        fill_offset = limit_fill_offset(window, side=side, entry=entry)
        if fill_offset is None:
            return None
        return candidate_from_price(row=row, rule=rule, entry=entry, stop=original_stop, target=original_target, entry_index=start + fill_offset, reason="atr_relative_limit", m1=m1)
    if rule.mode == "first_m1_body":
        first = window[0]
        body_mid = (first.open + first.close) / 2.0
        fill_offset = limit_fill_offset(window[1:] or window, side=side, entry=body_mid)
        if fill_offset is None:
            return None
        offset_base = 1 if len(window) > 1 else 0
        return candidate_from_price(row=row, rule=rule, entry=body_mid, stop=original_stop, target=original_target, entry_index=start + offset_base + fill_offset, reason="first_m1_body_mid_limit", m1=m1)
    if rule.mode == "mini_liquidity_tap":
        return confirmation_candidate(row=row, rule=rule, m1=m1, start=start, window=window, condition="liquidity_tap")
    if rule.mode == "failed_continuation":
        return confirmation_candidate(row=row, rule=rule, m1=m1, start=start, window=window, condition="failed_continuation")
    return None


def candidate_from_price(
    *,
    row: dict[str, Any],
    rule: EntryRule,
    entry: float,
    stop: float,
    target: float,
    entry_index: int,
    reason: str,
    m1: list[Candle],
) -> dict[str, Any] | None:
    side = str(row["side"]).upper()
    original_entry = float(row["entry"])
    original_risk = float(row["risk"])
    risk = entry - stop if side == "BUY" else stop - entry
    rr = (target - entry) / risk if side == "BUY" and risk > 0 else (entry - target) / risk if risk > 0 else 0.0
    if risk <= 0 or rr <= 0:
        return None
    if risk < original_risk * 0.25:
        return None
    improvement = original_entry - entry if side == "BUY" else entry - original_entry
    return {
        "rule": rule.code,
        "executable": rule.executable,
        "entry": round(entry, 5),
        "stop": round(stop, 5),
        "target": round(target, 5),
        "risk": round(risk, 5),
        "rr": round(rr, 4),
        "entry_index": entry_index,
        "entry_time_refined": m1[entry_index].time.isoformat(),
        "reason": reason,
        "entry_improvement_price": round(improvement, 5),
        "entry_improvement_R_original": round(improvement / original_risk, 4) if original_risk else 0.0,
        "risk_reduction_pct": round((original_risk - risk) / original_risk * 100.0, 2) if original_risk else 0.0,
        "rr_improvement": round(rr - float(row["rr"]), 4),
    }


def confirmation_candidate(
    *,
    row: dict[str, Any],
    rule: EntryRule,
    m1: list[Candle],
    start: int,
    window: list[Candle],
    condition: str,
) -> dict[str, Any] | None:
    side = str(row["side"]).upper()
    original_stop = float(row["stop"])
    original_target = float(row["target"])
    original_risk = float(row["risk"])
    for offset, candle in enumerate(window):
        idx = start + offset
        if condition == "liquidity_tap" and not mini_liquidity_tap(m1=m1, index=idx, side=side):
            continue
        if condition == "failed_continuation" and not failed_continuation(m1=m1, index=idx, side=side):
            continue
        entry_index = min(idx + 1, len(m1) - 1)
        entry = m1[entry_index].open
        stop = micro_stop(m1=m1, start=start, confirm_index=idx, side=side, original_stop=original_stop, original_risk=original_risk)
        return candidate_from_price(row=row, rule=rule, entry=entry, stop=stop, target=original_target, entry_index=entry_index, reason=condition, m1=m1)
    return None


def limit_fill_offset(window: list[Candle], *, side: str, entry: float) -> int | None:
    for offset, candle in enumerate(window):
        if side == "BUY" and candle.low <= entry:
            return offset
        if side == "SELL" and candle.high >= entry:
            return offset
    return None


def find_signal_m5(*, row: dict[str, Any], m5: list[Candle]) -> Candle | None:
    signal_time = datetime.fromisoformat(str(row["signal_time"]))
    return next((candle for candle in m5 if candle.time == signal_time), None)


def wick_retrace_price(candle: Candle, *, side: str, fraction: float) -> float | None:
    if side == "BUY":
        wick_top = min(candle.open, candle.close)
        wick_size = wick_top - candle.low
        if wick_size <= 0:
            return None
        return wick_top - wick_size * fraction
    wick_bottom = max(candle.open, candle.close)
    wick_size = candle.high - wick_bottom
    if wick_size <= 0:
        return None
    return wick_bottom + wick_size * fraction


def estimate_m5_atr(*, m5: list[Candle], signal_candle: Candle) -> float:
    idx = next((i for i, candle in enumerate(m5) if candle.time == signal_candle.time), None)
    if idx is None or idx < 15:
        return signal_candle.high - signal_candle.low
    trs = []
    prev_close = m5[idx - 15].close
    for candle in m5[idx - 14 : idx + 1]:
        trs.append(max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close)))
        prev_close = candle.close
    return sum(trs) / len(trs) if trs else signal_candle.high - signal_candle.low


def mini_liquidity_tap(*, m1: list[Candle], index: int, side: str) -> bool:
    if index < 3:
        return False
    candle = m1[index]
    previous = m1[index - 3 : index]
    if side == "BUY":
        swept = candle.low < min(item.low for item in previous)
        reclaimed = candle.close > candle.open and candle.close > min(item.close for item in previous)
        return swept and reclaimed
    swept = candle.high > max(item.high for item in previous)
    reclaimed = candle.close < candle.open and candle.close < max(item.close for item in previous)
    return swept and reclaimed


def failed_continuation(*, m1: list[Candle], index: int, side: str) -> bool:
    if index < 1:
        return False
    prev = m1[index - 1]
    candle = m1[index]
    if side == "BUY":
        return prev.close < prev.open and candle.close > candle.open and candle.close > prev.open
    return prev.close > prev.open and candle.close < candle.open and candle.close < prev.open


def micro_stop(*, m1: list[Candle], start: int, confirm_index: int, side: str, original_stop: float, original_risk: float) -> float:
    window = m1[start : confirm_index + 1]
    buffer = original_risk * 0.05
    if side == "BUY":
        return max(original_stop, min(candle.low for candle in window) - buffer)
    return min(original_stop, max(candle.high for candle in window) + buffer)


def simulate_candidate(*, row: dict[str, Any], candidate: dict[str, Any], scenario: ExecutionScenario) -> dict[str, Any]:
    m1 = load_candles_for_year_cached(int(row["year"]))
    entry_index = int(candidate["entry_index"])
    side = str(row["side"]).upper()
    entry = float(candidate["entry"])
    risk = max(float(candidate["risk"]), 1e-9)
    target_r = float(candidate["rr"])
    partial_trigger = 0.30 + scenario.partial_delay_r
    protect_trigger = 0.80 + scenario.protect_delay_r
    cost_r = (scenario.spread_price + scenario.slippage_price) / risk
    partial_taken = protected = be_active = False
    mfe = mae = 0.0
    realized = 0.0
    exit_reason = "OPEN_UNKNOWN"
    exit_index = min(len(m1) - 1, entry_index + 400)
    for cursor in range(entry_index, min(len(m1), entry_index + 400)):
        candle = m1[cursor]
        favorable, adverse = favorable_adverse(candle=candle, side=side, entry=entry, risk=risk)
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)
        active_stop_r = -1.0
        if protected:
            active_stop_r = 0.30 - scenario.protected_slippage_r
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
        close = m1[exit_index].close
        realized = ((close - entry) / risk) if side == "BUY" else ((entry - close) / risk)
    if partial_taken:
        partial_gain = 0.40 * max(0.0, 0.30 - cost_r * 0.25)
        realized = partial_gain + 0.60 * realized
    return {
        "rule": candidate["rule"],
        "executable": candidate["executable"],
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
        "entry_improvement_R_original": candidate["entry_improvement_R_original"],
        "risk_reduction_pct": candidate["risk_reduction_pct"],
        "rr_improvement": candidate["rr_improvement"],
        "mfe_r": round(mfe, 4),
        "mae_r": round(mae, 4),
        "mae_reduction_R": round(float(row.get("mae_r", 0.0)) - mae, 4),
        "partial_taken": partial_taken,
        "be_moved": be_active,
        "protected": protected,
        "cost_r": round(cost_r, 4),
        "spread_efficiency": round(1.0 / cost_r, 4) if cost_r > 0 else 999.0,
        "exit_reason": exit_reason,
        "realized_R": round(realized - cost_r, 4),
        "duration_minutes": max(0, exit_index - entry_index + 1),
    }


_CANDLE_CACHE: dict[int, list[Candle]] = {}


def load_candles_for_year_cached(year: int) -> list[Candle]:
    if year not in _CANDLE_CACHE:
        _CANDLE_CACHE.update(load_candles("M1"))
    return _CANDLE_CACHE[year]


def favorable_adverse(*, candle: Candle, side: str, entry: float, risk: float) -> tuple[float, float]:
    if side == "BUY":
        return (candle.high - entry) / risk, (entry - candle.low) / risk
    return (entry - candle.low) / risk, (candle.high - entry) / risk


def stop_hit_for_active_stop(*, candle: Candle, side: str, entry: float, risk: float, active_stop_r: float) -> bool:
    if side == "BUY":
        return candle.low <= entry + active_stop_r * risk
    return candle.high >= entry - active_stop_r * risk


def summarize(*, records: list[dict[str, Any]], source_count: int, misses: dict[str, int]) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for rule in RULES:
        result[rule.code] = {}
        for scenario in SCENARIOS:
            bucket = [row for row in records if row["rule"] == rule.code and row["scenario"] == scenario.code]
            result[rule.code][scenario.code] = {
                **metrics([float(row["realized_R"]) for row in bucket]),
                "executable": rule.executable,
                "missed_trades": misses.get(rule.code, 0),
                "fill_probability_pct": round(len(bucket) / source_count * 100.0, 2) if source_count else 0.0,
                "avg_entry_improvement_R": round(avg([float(row["entry_improvement_R_original"]) for row in bucket]), 4),
                "avg_risk_reduction_pct": round(avg([float(row["risk_reduction_pct"]) for row in bucket]), 2),
                "avg_rr_improvement": round(avg([float(row["rr_improvement"]) for row in bucket]), 4),
                "avg_cost_R": round(avg([float(row["cost_r"]) for row in bucket]), 4),
                "avg_spread_efficiency": round(avg([float(row["spread_efficiency"]) for row in bucket if float(row["spread_efficiency"]) < 999]), 4),
                "avg_mae_reduction_R": round(avg([float(row["mae_reduction_R"]) for row in bucket]), 4),
                "by_session": breakdown(bucket, "session"),
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


def rank_rules(summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rule in RULES:
        realistic = summaries[rule.code]["realistic_mt5"]
        score = (
            realistic["profit_factor"] * 10.0
            + realistic["expectancy_R"] * 25.0
            - realistic["max_drawdown_R"] * 0.50
            + realistic["fill_probability_pct"] * 0.03
            + realistic["avg_entry_improvement_R"] * 2.0
            - (0.0 if rule.executable else 5.0)
        )
        rows.append({"rule": rule.code, "label": rule.label, "executable": rule.executable, "score": round(score, 4), "realistic": realistic, "ideal": summaries[rule.code]["ideal"]})
    return sorted(rows, key=lambda item: item["score"], reverse=True)


def classify(*, baseline: dict[str, Any], best: dict[str, Any]) -> str:
    if not best:
        return "NEEDS MORE DATA"
    if best["fill_probability_pct"] < 40.0:
        return "UNREALISTIC FILL"
    if best["profit_factor"] >= 1.2 and best["expectancy_R"] > 0 and best["avg_cost_R"] < baseline["avg_cost_R"] * 2.5:
        return "EXECUTABLE IMPROVEMENT"
    if best["avg_spread_efficiency"] > baseline["avg_spread_efficiency"] and best["expectancy_R"] > baseline["expectancy_R"]:
        return "SPREAD EFFICIENT"
    if best["profit_factor"] > baseline["profit_factor"] and best["fill_probability_pct"] < 60.0:
        return "OVERFIT ENTRY"
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
        "# REACTION_ENTRY_OPTIMIZATION_RESEARCH",
        "",
        f"- status: {payload['status']}",
        f"- detector: `{payload['detector']}`",
        f"- baseline: `{payload['baseline']}`",
        f"- management: `{payload['management']}`",
        f"- classification: `{payload['classification']}`",
        f"- best_executable_rule: `{payload['best_executable_rule']}`",
        "",
        "## Ranking",
        "",
        "| Rank | Rule | Exec | Score | Trades | Fill | Missed | PF Real | Exp R | DD | Entry Improve R | Risk Red | RR Improve | Cost R | Spread Eff | MAE Red |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, item in enumerate(payload["ranking"], start=1):
        r = item["realistic"]
        lines.append(
            f"| {idx} | {item['rule']} | {item['executable']} | {item['score']} | {r['trades']} | "
            f"{r['fill_probability_pct']}% | {r['missed_trades']} | {r['profit_factor']} | {r['expectancy_R']} | "
            f"{r['max_drawdown_R']} | {r['avg_entry_improvement_R']} | {r['avg_risk_reduction_pct']}% | "
            f"{r['avg_rr_improvement']} | {r['avg_cost_R']} | {r['avg_spread_efficiency']} | {r['avg_mae_reduction_R']} |"
        )
    lines.extend(
        [
            "",
            "## Scenario Comparison",
            "",
            "| Rule | Scenario | Trades | WR | PF | Exp R | Net R | DD | Fill | Entry Improve R | Risk Red | Cost R | MAE Red |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rule, scenario_map in payload["summaries"].items():
        for scenario, metric in scenario_map.items():
            lines.append(
                f"| {rule} | {scenario} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['fill_probability_pct']}% | "
                f"{metric['avg_entry_improvement_R']} | {metric['avg_risk_reduction_pct']}% | {metric['avg_cost_R']} | {metric['avg_mae_reduction_R']} |"
            )
    best = payload["best_executable_rule"]
    lines.extend(["", "## Best Executable Rule By Session", ""])
    lines.extend(render_breakdown(payload["summaries"][best]["realistic_mt5"]["by_session"]))
    lines.extend(["", "## Notes"])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_breakdown(items: dict[str, Any]) -> list[str]:
    lines = ["| Bucket | Trades | WR | PF | Exp R | Net R | DD | Losing Streak |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    if not items:
        lines.append("| none | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")
        return lines
    for bucket, metric in items.items():
        lines.append(f"| {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | {metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']} |")
    return lines


if __name__ == "__main__":
    main()
