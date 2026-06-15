"""Performance laboratory for MAXIMO demo trading evidence."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TradingAIPerformanceLab:
    """Builds objective metrics from demo execution and management logs."""

    def __init__(self, *, demo_dir: Path, reports_dir: Path) -> None:
        self.demo_dir = demo_dir
        self.reports_dir = reports_dir
        self.report_path = reports_dir / "AI_PERFORMANCE_LAB_REPORT.md"

    def generate(self) -> dict[str, Any]:
        executions = self._read_csv(self.demo_dir / "executions.csv")
        management_events = self._read_jsonl(self.demo_dir / "position_management_history.jsonl")
        q_events = self._read_jsonl(self.demo_dir / "q_learning_experience_replay.jsonl")
        decision_events = self._read_jsonl(self.demo_dir / "decision_source_audit.jsonl")

        trades = self._trade_rows(management_events)
        closed_like = [event for event in management_events if str(event.get("action_taken") or "") in {"fast_exit", "partial_close", "protect_sl", "move_to_be", "trail_sl"}]
        final_r_values = [self._safe_float(event.get("current_r")) for event in management_events if event.get("current_r") is not None]
        positive_r = [value for value in final_r_values if value > 0]
        negative_r = [value for value in final_r_values if value < 0]
        wins = len(positive_r)
        losses = len(negative_r)
        win_rate = round(wins / (wins + losses), 4) if wins + losses else 0.0
        gross_win = sum(positive_r)
        gross_loss = abs(sum(negative_r))
        profit_factor = round(gross_win / gross_loss, 4) if gross_loss > 0 else (round(gross_win, 4) if gross_win else 0.0)
        expectancy_r = round(sum(final_r_values) / len(final_r_values), 4) if final_r_values else 0.0
        max_drawdown_r = self._max_drawdown(final_r_values)

        actions = Counter(str(event.get("action_taken") or "none") for event in management_events)
        execution_statuses = Counter(str(row.get("execution_status") or "unknown") for row in executions)
        sessions = Counter(self._session_from_row(row) for row in executions)
        pulse_buckets = Counter(self._pulse_bucket(row) for row in executions)
        q_alignment = Counter(str(row.get("q_learning_policy_action") or "unknown") for row in executions)
        source_drivers = Counter(
            str(((event.get("decision_attribution") or {}).get("primary_driver")) or "unknown")
            for event in decision_events
        )

        reached_half_r = [
            event for event in management_events if self._safe_float(event.get("mfe_r")) >= 0.5
        ]
        giveback_negative = [
            event
            for event in reached_half_r
            if self._safe_float(event.get("current_r")) < 0 and str(event.get("action_taken") or "") not in {"move_to_be", "protect_sl", "fast_exit"}
        ]
        be_saved = [event for event in management_events if str(event.get("action_taken") or "") in {"move_to_be", "protect_sl"}]
        fast_exit_saved = [event for event in management_events if str(event.get("action_taken") or "") == "fast_exit"]
        q_feedback_count = len(q_events)
        q_real_feedback = [
            event
            for event in q_events
            if (event.get("position_management_feedback") or {}) or event.get("final_confirmation_score") is not None
        ]

        readiness = self._classification(
            total_cycles=len(executions),
            trades=len(trades),
            profit_factor=profit_factor,
            expectancy_r=expectancy_r,
            giveback_negative=len(giveback_negative),
            q_feedback_count=len(q_real_feedback),
        )
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_path": str(self.report_path.resolve()),
            "total_cycles": len(executions),
            "trade_management_events": len(management_events),
            "trades_observed": len(trades),
            "position_actions": dict(actions),
            "execution_statuses": dict(execution_statuses),
            "win_rate_proxy": win_rate,
            "profit_factor_proxy": profit_factor,
            "expectancy_r_proxy": expectancy_r,
            "max_drawdown_r_proxy": max_drawdown_r,
            "average_r_won": round(sum(positive_r) / len(positive_r), 4) if positive_r else 0.0,
            "average_r_lost": round(sum(negative_r) / len(negative_r), 4) if negative_r else 0.0,
            "sessions": dict(sessions),
            "market_pulse_buckets": dict(pulse_buckets),
            "q_learning_alignment": dict(q_alignment),
            "decision_primary_drivers": dict(source_drivers),
            "trades_reached_0_5r": len(reached_half_r),
            "trades_reached_0_5r_then_negative_unprotected": len(giveback_negative),
            "trades_saved_by_be_or_protect": len(be_saved),
            "trades_saved_by_fast_exit": len(fast_exit_saved),
            "q_learning_feedback_events": q_feedback_count,
            "q_learning_real_feedback_events": len(q_real_feedback),
            "classification": readiness["classification"],
            "classification_reason": readiness["reason"],
            "urgent_flags": readiness["urgent_flags"],
        }
        self._write_report(summary)
        return summary

    def _write_report(self, summary: dict[str, Any]) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "# AI Performance Lab Report",
            "",
            f"- generated_at_utc: {summary['generated_at']}",
            f"- classification: {summary['classification']}",
            f"- classification_reason: {summary['classification_reason']}",
            f"- total_cycles: {summary['total_cycles']}",
            f"- trades_observed: {summary['trades_observed']}",
            f"- trade_management_events: {summary['trade_management_events']}",
            f"- win_rate_proxy: {summary['win_rate_proxy']}",
            f"- profit_factor_proxy: {summary['profit_factor_proxy']}",
            f"- expectancy_r_proxy: {summary['expectancy_r_proxy']}",
            f"- max_drawdown_r_proxy: {summary['max_drawdown_r_proxy']}",
            f"- average_r_won: {summary['average_r_won']}",
            f"- average_r_lost: {summary['average_r_lost']}",
            f"- trades_reached_0_5r: {summary['trades_reached_0_5r']}",
            f"- trades_reached_0_5r_then_negative_unprotected: {summary['trades_reached_0_5r_then_negative_unprotected']}",
            f"- trades_saved_by_be_or_protect: {summary['trades_saved_by_be_or_protect']}",
            f"- trades_saved_by_fast_exit: {summary['trades_saved_by_fast_exit']}",
            f"- q_learning_feedback_events: {summary['q_learning_feedback_events']}",
            f"- q_learning_real_feedback_events: {summary['q_learning_real_feedback_events']}",
            "",
            "## Execution Statuses",
        ]
        for key, value in sorted(summary["execution_statuses"].items()):
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Position Actions"])
        for key, value in sorted(summary["position_actions"].items()):
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Session / Pulse / Drivers"])
        lines.append(f"- sessions: {summary['sessions']}")
        lines.append(f"- market_pulse_buckets: {summary['market_pulse_buckets']}")
        lines.append(f"- q_learning_alignment: {summary['q_learning_alignment']}")
        lines.append(f"- decision_primary_drivers: {summary['decision_primary_drivers']}")
        lines.extend(["", "## Urgent Flags"])
        if summary["urgent_flags"]:
            for item in summary["urgent_flags"]:
                lines.append(f"- {item}")
        else:
            lines.append("- none")
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _classification(
        *,
        total_cycles: int,
        trades: int,
        profit_factor: float,
        expectancy_r: float,
        giveback_negative: int,
        q_feedback_count: int,
    ) -> dict[str, Any]:
        flags: list[str] = []
        if giveback_negative:
            flags.append("Trades reached +0.5R and later became negative without enough protection.")
        if q_feedback_count < max(3, trades):
            flags.append("Q-learning still needs more real trade outcome feedback.")
        if total_cycles < 100 or trades < 10:
            return {
                "classification": "INSUFFICIENT_DATA",
                "reason": "Not enough demo cycles/trades for robust statistical judgement.",
                "urgent_flags": flags,
            }
        if profit_factor >= 1.35 and expectancy_r > 0 and giveback_negative == 0:
            return {
                "classification": "DEMO_HEALTHY_NOT_REAL_APPROVED",
                "reason": "Demo evidence is improving, but real still requires three-week validation.",
                "urgent_flags": flags,
            }
        if profit_factor < 1.0 or expectancy_r <= 0:
            flags.append("Profit factor or expectancy is not yet acceptable.")
            return {
                "classification": "NEEDS_CALIBRATION",
                "reason": "Current demo metrics do not justify real trading.",
                "urgent_flags": flags,
            }
        return {
            "classification": "WATCH_AND_VALIDATE",
            "reason": "Metrics are mixed; continue structured demo observation.",
            "urgent_flags": flags,
        }

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _trade_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for event in events:
            ticket = str(event.get("ticket") or "")
            if ticket:
                seen[ticket] = event
        return list(seen.values())

    @staticmethod
    def _max_drawdown(values: list[float]) -> float:
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            max_dd = min(max_dd, equity - peak)
        return round(abs(max_dd), 4)

    @staticmethod
    def _session_from_row(row: dict[str, Any]) -> str:
        hour = row.get("controlled_demo_environment_hour_ny") or row.get("controlled_demo_hour_ny")
        if hour is None:
            return "unknown"
        try:
            hour_int = int(float(hour))
        except (TypeError, ValueError):
            return "unknown"
        if 3 <= hour_int <= 5:
            return "london_rd_window"
        if 8 <= hour_int <= 11:
            return "ny_rd_window"
        return "outside_main_windows"

    @staticmethod
    def _pulse_bucket(row: dict[str, Any]) -> str:
        raw = row.get("market_pulse_score") or row.get("market_pulse")
        try:
            score = float(raw)
        except (TypeError, ValueError):
            return "unknown"
        if score <= 30:
            return "dead_market"
        if score <= 50:
            return "observation"
        if score <= 70:
            return "normal_opportunity"
        if score <= 85:
            return "strong_opportunity"
        return "predator_opportunity"

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
