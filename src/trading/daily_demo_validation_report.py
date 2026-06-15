"""Daily demo validation report for MAXIMO session monitoring."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class DailyDemoValidationReport:
    """Summarize demo-only validation evidence for London/NY RD sessions."""

    RD_TZ = ZoneInfo("America/Santo_Domingo")
    SESSION_WINDOWS = {
        "london_rd": (time(3, 0), time(5, 0)),
        "ny_rd": (time(8, 0), time(11, 30)),
    }

    def __init__(self, *, demo_dir: Path, reports_dir: Path) -> None:
        self.demo_dir = demo_dir
        self.reports_dir = reports_dir
        self.telemetry_path = demo_dir / "demo_validation_cycles.jsonl"
        self.position_history_path = demo_dir / "position_management_history.jsonl"
        self.executions_path = demo_dir / "executions.csv"

    def append_cycle(self, payload: dict[str, Any]) -> None:
        self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        with self.telemetry_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def build_cycle_payload(
        self,
        *,
        symbol: str,
        execution_status: str,
        intelligence: dict[str, Any],
        signal: dict[str, Any] | None,
        final_confirmation: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        market_pulse: dict[str, Any],
        position_management: dict[str, Any],
        q_learning_decision: dict[str, Any],
        open_positions: int,
    ) -> dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        now_rd = now_utc.astimezone(self.RD_TZ)
        block_reasons = self._block_reasons(
            execution_status=execution_status,
            intelligence=intelligence,
            final_confirmation=final_confirmation,
            execution_risk_decision=execution_risk_decision,
        )
        return {
            "timestamp_utc": now_utc.isoformat(),
            "timestamp_rd": now_rd.isoformat(),
            "date_rd": now_rd.date().isoformat(),
            "session_rd": self._session_name(now_rd),
            "symbol": symbol,
            "execution_mode": "DEMO_REALISTIC_PROFIT_MODE",
            "intelligence_action": (intelligence.get("execution_readiness") or {}).get("action"),
            "execution_status": execution_status,
            "cycle_class": self._cycle_class(execution_status, intelligence, final_confirmation, signal),
            "signal_detected": signal is not None,
            "signal_side": str((signal or {}).get("direction") or "").upper() or None,
            "risk_mode": execution_risk_decision.get("allowed_risk_mode"),
            "market_pulse_score": market_pulse.get("score"),
            "market_pulse_label": market_pulse.get("label"),
            "final_confirmation_score": final_confirmation.get("final_confirmation_score"),
            "final_confirmation_decision": final_confirmation.get("decision"),
            "final_confirmation_reason": final_confirmation.get("reason"),
            "block_reasons": block_reasons,
            "open_positions": open_positions,
            "position_management_feedback": (position_management or {}).get("feedback", {}),
            "q_learning_policy": q_learning_decision.get("q_policy_action"),
            "q_learning_reward": ((q_learning_decision.get("experience_update") or {}).get("latest_experience") or {}).get("reward"),
        }

    def generate(self, *, target_date: date | None = None) -> dict[str, Any]:
        target_date = target_date or datetime.now(self.RD_TZ).date()
        cycles = [
            item for item in self._read_jsonl(self.telemetry_path)
            if self._date_matches(item.get("date_rd"), target_date)
            and str(item.get("session_rd") or "") in self.SESSION_WINDOWS
        ]
        position_events = [
            item for item in self._read_jsonl(self.position_history_path)
            if self._timestamp_in_target_sessions(item.get("timestamp"), target_date)
        ]
        executions = [
            item for item in self._read_csv(self.executions_path)
            if self._timestamp_in_target_sessions(item.get("timestamp_utc"), target_date)
        ]
        classes = Counter(str(item.get("cycle_class") or "UNKNOWN") for item in cycles)
        block_reasons: Counter[str] = Counter()
        for item in cycles:
            for reason in item.get("block_reasons") or []:
                block_reasons[str(reason)] += 1
        market_pulse_values = [self._safe_float(item.get("market_pulse_score")) for item in cycles if item.get("market_pulse_score") is not None]
        final_confirmation_values = [
            self._safe_float(item.get("final_confirmation_score")) for item in cycles if item.get("final_confirmation_score") is not None
        ]
        trade_rows = [row for row in executions if str(row.get("execution_status") or "") == "demo_order_sent"]
        reached_half_r = [event for event in position_events if self._safe_float(event.get("mfe_r")) >= 0.5]
        gaveback = [
            event for event in reached_half_r
            if self._safe_float(event.get("current_r")) < 0
        ]
        be_events = [
            event for event in position_events
            if str(event.get("action_taken") or "") in {"move_to_be", "protect_sl"}
        ]
        fast_exit_events = [
            event for event in position_events
            if str(event.get("action_taken") or "") == "fast_exit"
        ]
        partial_events = [
            event for event in position_events
            if str(event.get("action_taken") or "") in {"partial_close", "partial_skipped_min_lot_fallback"}
        ]
        trailing_events = [
            event for event in position_events
            if str(event.get("action_taken") or "") == "trail_sl"
        ]
        momentum_events = [
            event for event in position_events
            if "momentum" in str(event.get("reason") or "").lower() or bool(event.get("momentum_decay_detected"))
        ]
        mfe_values = [self._safe_float(event.get("mfe_r")) for event in position_events if event.get("mfe_r") is not None]
        mae_values = [self._safe_float(event.get("mae_r")) for event in position_events if event.get("mae_r") is not None]
        current_r_values = [self._safe_float(event.get("current_r")) for event in position_events if event.get("current_r") is not None]

        conclusion = self._conclusion(
            cycles=len(cycles),
            watch=classes.get("WATCH", 0),
            block=classes.get("BLOCK", 0),
            execute=classes.get("EXECUTE", 0),
            avg_pulse=self._avg(market_pulse_values),
            avg_final=self._avg(final_confirmation_values),
            gaveback=len(gaveback),
        )
        summary = {
            "date_rd": target_date.isoformat(),
            "report_path": str(self._report_path(target_date).resolve()),
            "cycles": len(cycles),
            "total_watch": classes.get("WATCH", 0),
            "total_block": classes.get("BLOCK", 0),
            "total_execute": classes.get("EXECUTE", 0),
            "block_reasons": dict(block_reasons.most_common(10)),
            "operations_taken": len(trade_rows),
            "mfe_max": max(mfe_values) if mfe_values else 0.0,
            "mae_max": min(mae_values) if mae_values else 0.0,
            "avg_result_r": self._avg(current_r_values),
            "trades_reached_0_5r": len(reached_half_r),
            "trades_gave_back_profit": len(gaveback),
            "be_events": len(be_events),
            "partial_events": len(partial_events),
            "trailing_events": len(trailing_events),
            "fast_exit_events": len(fast_exit_events),
            "momentum_decay_events": len(momentum_events),
            "avg_market_pulse": self._avg(market_pulse_values),
            "avg_final_confirmation": self._avg(final_confirmation_values),
            "conclusion": conclusion,
        }
        self._write_report(
            target_date=target_date,
            summary=summary,
            cycles=cycles,
            trade_rows=trade_rows,
            position_events=position_events,
        )
        return summary

    def _write_report(
        self,
        *,
        target_date: date,
        summary: dict[str, Any],
        cycles: list[dict[str, Any]],
        trade_rows: list[dict[str, Any]],
        position_events: list[dict[str, Any]],
    ) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# Daily Demo Validation Report {target_date.isoformat()}",
            "",
            "- mode: DEMO_REALISTIC_PROFIT_MODE",
            "- scope: London RD 03:00-05:00 and New York RD 08:00-11:30",
            "- note: report-only; no trading logic, risk, credentials or real mode changed.",
            "",
            "## Summary",
        ]
        for key in (
            "cycles",
            "total_watch",
            "total_block",
            "total_execute",
            "operations_taken",
            "trades_reached_0_5r",
            "trades_gave_back_profit",
            "be_events",
            "partial_events",
            "trailing_events",
            "fast_exit_events",
            "momentum_decay_events",
            "avg_market_pulse",
            "avg_final_confirmation",
            "mfe_max",
            "mae_max",
            "avg_result_r",
            "conclusion",
        ):
            lines.append(f"- {key}: {summary.get(key)}")
        lines.extend(["", "## Main Block Reasons"])
        if summary["block_reasons"]:
            for reason, count in summary["block_reasons"].items():
                lines.append(f"- {reason}: {count}")
        else:
            lines.append("- none")
        lines.extend(["", "## Operations Taken"])
        if not trade_rows:
            lines.append("- none")
        else:
            for row in trade_rows:
                lines.append(
                    "- {time} {symbol} {direction} status={status} entry={entry} sl={sl} tp={tp} rr={rr}".format(
                        time=row.get("timestamp_utc"),
                        symbol=row.get("symbol"),
                        direction=row.get("direction"),
                        status=row.get("execution_status"),
                        entry=row.get("entry_price"),
                        sl=row.get("stop_price"),
                        tp=row.get("target_price"),
                        rr=row.get("selected_rr"),
                    )
                )
        lines.extend(["", "## Post Entry Management"])
        if not position_events:
            lines.append("- no position management events in target sessions")
        else:
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for event in position_events:
                grouped[str(event.get("ticket") or "unknown")].append(event)
            for ticket, events in grouped.items():
                mfe = max(self._safe_float(item.get("mfe_r")) for item in events)
                mae = min(self._safe_float(item.get("mae_r")) for item in events)
                last = events[-1]
                actions = Counter(str(item.get("action_taken") or "none") for item in events)
                lines.append(
                    f"- ticket={ticket} side={last.get('side')} mfe_r={round(mfe, 4)} mae_r={round(mae, 4)} "
                    f"last_r={last.get('current_r')} actions={dict(actions)}"
                )
        lines.extend(["", "## Last 10 Session Cycles"])
        for item in cycles[-10:]:
            lines.append(
                "- {time} {session} {klass} action={action} status={status} pulse={pulse} final={final} risk={risk} reasons={reasons}".format(
                    time=item.get("timestamp_rd"),
                    session=item.get("session_rd"),
                    klass=item.get("cycle_class"),
                    action=item.get("intelligence_action"),
                    status=item.get("execution_status"),
                    pulse=item.get("market_pulse_score"),
                    final=item.get("final_confirmation_score"),
                    risk=item.get("risk_mode"),
                    reasons=item.get("block_reasons"),
                )
            )
        self._report_path(target_date).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _report_path(self, target_date: date) -> Path:
        return self.reports_dir / f"DAILY_DEMO_VALIDATION_REPORT_{target_date.strftime('%Y_%m_%d')}.md"

    @classmethod
    def _session_name(cls, value: datetime) -> str:
        local_time = value.timetz().replace(tzinfo=None)
        for name, (start, end) in cls.SESSION_WINDOWS.items():
            if start <= local_time <= end:
                return name
        return "outside_validation_sessions"

    @staticmethod
    def _cycle_class(
        execution_status: str,
        intelligence: dict[str, Any],
        final_confirmation: dict[str, Any],
        signal: dict[str, Any] | None,
    ) -> str:
        if execution_status in {"demo_order_sent", "dry_run_signal_detected"} or signal is not None:
            return "EXECUTE"
        if (
            str(execution_status).startswith("blocked")
            or final_confirmation.get("decision") == "BLOCK"
            or "block" in str((intelligence.get("event_risk") or {}).get("action") or "").lower()
        ):
            return "BLOCK"
        if (intelligence.get("execution_readiness") or {}).get("action") == "WATCH":
            return "WATCH"
        return "OBSERVE"

    @staticmethod
    def _block_reasons(
        *,
        execution_status: str,
        intelligence: dict[str, Any],
        final_confirmation: dict[str, Any],
        execution_risk_decision: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        if str(execution_status).startswith("blocked"):
            reasons.append(str(execution_status))
        reasons.extend(str(item) for item in final_confirmation.get("blockers") or [])
        reasons.extend(str(item) for item in (intelligence.get("execution_readiness") or {}).get("blockers") or [])
        if execution_risk_decision.get("allowed_risk_mode") == "blocked":
            reasons.append(str(execution_risk_decision.get("execution_status") or execution_risk_decision.get("decision") or "risk_blocked"))
        return DailyDemoValidationReport._dedupe(reasons)

    def _timestamp_in_target_sessions(self, value: Any, target_date: date) -> bool:
        try:
            raw = str(value)
            if not raw:
                return False
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            local = parsed.astimezone(self.RD_TZ)
        except (TypeError, ValueError):
            return False
        return local.date() == target_date and self._session_name(local) in self.SESSION_WINDOWS

    @staticmethod
    def _date_matches(value: Any, target_date: date) -> bool:
        try:
            return date.fromisoformat(str(value)) == target_date
        except (TypeError, ValueError):
            return False

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
    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = item.strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    @staticmethod
    def _conclusion(
        *,
        cycles: int,
        watch: int,
        block: int,
        execute: int,
        avg_pulse: float,
        avg_final: float,
        gaveback: int,
    ) -> str:
        if cycles < 20:
            return "datos_insuficientes"
        if gaveback > 0:
            return "demasiado_agresivo_en_gestion_post_entrada"
        if execute == 0 and avg_pulse >= 60 and avg_final >= 50 and block > watch:
            return "demasiado_estricto"
        if execute > max(3, cycles * 0.12):
            return "demasiado_agresivo"
        return "balanceado"
