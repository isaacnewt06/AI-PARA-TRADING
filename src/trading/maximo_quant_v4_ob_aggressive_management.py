"""Defensive management replay for OB aggressive reduced signals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PARTIAL_TRIGGER_R = 0.5
PROTECTION_TRIGGER_R = 0.8
PROTECTED_STOP_R = 0.3
PARTIAL_CLOSE_FRACTION = 0.5


def ob_aggressive_defensive_management_plan() -> dict[str, Any]:
    """Return the isolated defensive exit policy for OB aggressive reduced signals."""
    return {
        "applies_to": "OB_AGGRESSIVE_REDUCED_SIGNAL",
        "partial_trigger_r": PARTIAL_TRIGGER_R,
        "partial_close_fraction": PARTIAL_CLOSE_FRACTION,
        "move_sl_after_partial": "break_even_or_small_positive_margin",
        "protection_trigger_r": PROTECTION_TRIGGER_R,
        "protected_stop_min_r": PROTECTED_STOP_R,
        "premature_sl_move": False,
    }


def apply_ob_aggressive_defensive_management(signal: dict[str, Any]) -> dict[str, Any]:
    """Replay the defensive management policy against one historical signal result.

    The historical quality file already tells us whether price reached each R
    level before final exit through ``max_favorable_excursion_r``. This function
    does not alter entry logic; it only recalculates realized R after the
    defensive partial/BE rules.
    """
    original_result = str(signal.get("result") or "UNKNOWN").upper()
    original_pnl_r = float(signal.get("pnl_r") or 0.0)
    rr = float(signal.get("RR") or signal.get("selected_rr") or 1.15)
    mfe_r = float(signal.get("max_favorable_excursion_r") or 0.0)

    partial_taken = mfe_r >= PARTIAL_TRIGGER_R
    be_moved = partial_taken
    protected_at_0_8r = mfe_r >= PROTECTION_TRIGGER_R

    if not partial_taken:
        realized_r = original_pnl_r
        final_result = original_result
        management_reason = "Price never reached +0.5R; original SL/TP management remains unchanged."
    elif original_result == "TP":
        realized_r = (PARTIAL_CLOSE_FRACTION * PARTIAL_TRIGGER_R) + ((1.0 - PARTIAL_CLOSE_FRACTION) * rr)
        final_result = "TP_WITH_PARTIAL"
        management_reason = "50% closed at +0.5R; remaining position reached full TP."
    elif protected_at_0_8r:
        realized_r = (PARTIAL_CLOSE_FRACTION * PARTIAL_TRIGGER_R) + (
            (1.0 - PARTIAL_CLOSE_FRACTION) * PROTECTED_STOP_R
        )
        final_result = "PROTECTED_STOP_AFTER_0_8R"
        management_reason = "50% closed at +0.5R; remaining stop protected to at least +0.3R after +0.8R."
    else:
        realized_r = PARTIAL_CLOSE_FRACTION * PARTIAL_TRIGGER_R
        final_result = "BE_AFTER_PARTIAL"
        management_reason = "50% closed at +0.5R; remaining stop moved to break-even."

    managed = dict(signal)
    managed.update(
        {
            "partial_taken": partial_taken,
            "be_moved": be_moved,
            "protected_at_0_8R": protected_at_0_8r,
            "final_result_after_management": final_result,
            "realized_R": round(realized_r, 4),
            "management_reason": management_reason,
            "sl_reduced": original_result == "SL" and round(realized_r, 4) > original_pnl_r,
            "full_tp_affected": original_result == "TP" and partial_taken and round(realized_r, 4) < round(rr, 4),
        }
    )
    return managed


def summarize_ob_aggressive_management(records: list[dict[str, Any]]) -> dict[str, Any]:
    managed = [apply_ob_aggressive_defensive_management(record) for record in records]
    before_r = [float(record.get("pnl_r") or 0.0) for record in records]
    after_r = [float(record.get("realized_R") or 0.0) for record in managed]
    before = _metric_summary(before_r)
    after = _metric_summary(after_r)
    conclusion = _management_conclusion(before=before, after=after)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": ob_aggressive_defensive_management_plan(),
        "total_signals": len(records),
        "before": before,
        "after": after,
        "partial_taken": sum(1 for record in managed if record["partial_taken"]),
        "be_moved": sum(1 for record in managed if record["be_moved"]),
        "protected_at_0_8R": sum(1 for record in managed if record["protected_at_0_8R"]),
        "sl_reduced": sum(1 for record in managed if record["sl_reduced"]),
        "full_tp_affected": sum(1 for record in managed if record["full_tp_affected"]),
        "managed_records": managed,
        "conclusion": conclusion,
    }


def write_ob_aggressive_management_replay_report(
    *,
    input_jsonl: Path,
    output_jsonl: Path,
    output_report: Path,
) -> dict[str, Any]:
    records = _read_jsonl(input_jsonl)
    summary = summarize_ob_aggressive_management(records)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for record in summary["managed_records"]:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    output_report.write_text(_render_management_report(summary), encoding="utf-8")
    return summary


def _metric_summary(values: list[float]) -> dict[str, Any]:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    return {
        "trades": len(values),
        "win_rate": round((sum(1 for value in values if value > 0) / len(values) * 100.0) if values else 0.0, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "expectancy_r": round((sum(values) / len(values)) if values else 0.0, 4),
        "net_r": round(sum(values), 4),
        "max_drawdown_r": round(_max_drawdown(values), 4),
    }


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _management_conclusion(*, before: dict[str, Any], after: dict[str, Any]) -> str:
    if not before["trades"]:
        return "NECESITA MÁS DATOS"
    expectancy_improved = float(after["expectancy_r"]) > float(before["expectancy_r"])
    dd_improved = float(after["max_drawdown_r"]) < float(before["max_drawdown_r"])
    pf_after = after["profit_factor"]
    pf_before = before["profit_factor"]
    pf_improved = pf_after == "inf" or (pf_before != "inf" and float(pf_after) > float(pf_before))
    if expectancy_improved and (dd_improved or pf_improved):
        return "GESTIÓN MEJORA EDGE"
    if float(after["expectancy_r"]) < float(before["expectancy_r"]) and not dd_improved:
        return "GESTIÓN EMPEORA"
    return "GESTIÓN NO MEJORA"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def _render_management_report(summary: dict[str, Any]) -> str:
    before = summary["before"]
    after = summary["after"]
    lines = [
        "# OB Aggressive Reduced Defensive Management Replay",
        "",
        "## Policy",
        f"- applies_to: {summary['policy']['applies_to']}",
        f"- partial: close 50% at +{PARTIAL_TRIGGER_R}R",
        "- break_even: move remaining SL to BE after partial",
        f"- protection: after +{PROTECTION_TRIGGER_R}R protect remaining position at +{PROTECTED_STOP_R}R minimum",
        "- scope: exit management only; institutional entry and filters unchanged",
        "",
        "## Before vs After",
        "| Metric | Before | After |",
        "|---|---:|---:|",
        f"| trades | {before['trades']} | {after['trades']} |",
        f"| win_rate | {before['win_rate']}% | {after['win_rate']}% |",
        f"| profit_factor | {before['profit_factor']} | {after['profit_factor']} |",
        f"| expectancy_r | {before['expectancy_r']} | {after['expectancy_r']} |",
        f"| net_r | {before['net_r']} | {after['net_r']} |",
        f"| max_drawdown_r | {before['max_drawdown_r']} | {after['max_drawdown_r']} |",
        "",
        "## Management Effects",
        f"- partial_taken: {summary['partial_taken']}",
        f"- be_moved: {summary['be_moved']}",
        f"- protected_at_0_8R: {summary['protected_at_0_8R']}",
        f"- sl_reduced: {summary['sl_reduced']}",
        f"- full_tp_affected: {summary['full_tp_affected']}",
        "",
        "## Signals",
        "| Time | Side | Original | Original R | Managed Result | Realized R | Partial | BE | 0.8R Protect |",
        "|---|---|---|---:|---|---:|---|---|---|",
    ]
    for record in summary["managed_records"]:
        lines.append(
            "| {time} | {side} | {original} | {original_r} | {managed} | {realized} | {partial} | {be} | {protect} |".format(
                time=record.get("timestamp"),
                side=record.get("side"),
                original=record.get("result"),
                original_r=record.get("pnl_r"),
                managed=record.get("final_result_after_management"),
                realized=record.get("realized_R"),
                partial=record.get("partial_taken"),
                be=record.get("be_moved"),
                protect=record.get("protected_at_0_8R"),
            )
        )
    lines.extend(["", "## Conclusion", f"- {summary['conclusion']}", ""])
    return "\n".join(lines)
