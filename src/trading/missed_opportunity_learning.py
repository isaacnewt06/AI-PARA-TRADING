"""Learning journal for high-quality opportunities that were not executed."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MissedOpportunityLearning:
    """Record WATCH/BLOCK opportunities so strictness can be calibrated later."""

    def __init__(self, *, history_path: Path, report_path: Path) -> None:
        self.history_path = history_path
        self.report_path = report_path
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.touch(exist_ok=True)

    def record_cycle(
        self,
        *,
        symbol: str,
        signal: dict[str, Any] | None,
        execution_status: str,
        intelligence: dict[str, Any],
        final_confirmation: dict[str, Any],
        market_pulse: dict[str, Any],
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
        armed_retest: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        pulse = self._safe_float(market_pulse.get("score"))
        final_score = self._safe_float(final_confirmation.get("final_confirmation_score"))
        readiness = self._safe_float(execution_readiness.get("execution_readiness_score"))
        entry_score = self._safe_float(entry_quality.get("entry_quality_score"))
        interesting = pulse >= 80 or final_score >= 60 or readiness >= 70 or armed_retest.get("action") == "ARMED_RETEST_WAIT"
        if signal is not None and execution_status in {"demo_order_sent", "dry_run_signal_detected"}:
            interesting = False
        if not interesting:
            status = {"status": "watching", "recorded": False, "reason": "No hubo oportunidad no ejecutada de alta prioridad."}
            self.generate_report()
            return status

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "event": "MISSED_OPPORTUNITY_CANDIDATE",
            "execution_status": execution_status,
            "side": str((signal or {}).get("direction") or final_confirmation.get("side") or (intelligence.get("overview", {}).get("market_state", {}) or {}).get("preferred_side") or "NEUTRAL").upper(),
            "setup_type": (signal or {}).get("setup_type") or (intelligence.get("watch_trigger") or {}).get("setup_detected"),
            "price_at_block": self._latest_price(snapshot),
            "market_pulse": pulse,
            "final_confirmation": final_score,
            "execution_readiness": readiness,
            "entry_quality": entry_score,
            "blocking_reason": self._blocking_reason(
                execution_status=execution_status,
                final_confirmation=final_confirmation,
                execution_readiness=execution_readiness,
                entry_quality=entry_quality,
            ),
            "evolution_after_5_candles": "pending",
            "evolution_after_10_candles": "pending",
            "evolution_after_15_candles": "pending",
            "evolution_after_30_candles": "pending",
            "would_hit_tp_simulated": None,
            "would_hit_sl_simulated": None,
            "armed_retest_would_help": armed_retest.get("action") in {"ARMED_RETEST_WAIT", "ARMED_RETEST_CREATED"},
            "strictness_assessment": "pending_forward_resolution",
        }
        self._append(event)
        report = self.generate_report()
        return {
            "status": "recorded",
            "recorded": True,
            "latest_event": event,
            "history_path": str(self.history_path.resolve()),
            "report_path": report.get("report_path"),
        }

    def generate_report(self) -> dict[str, Any]:
        rows = self._read_jsonl()
        blockers = Counter(str(item.get("blocking_reason") or "unknown") for item in rows)
        armed_help = sum(1 for item in rows if item.get("armed_retest_would_help"))
        lines = [
            "# Missed Opportunity Learning Report",
            "",
            f"- generated_at_utc: {datetime.now(timezone.utc).isoformat()}",
            f"- total_candidates: {len(rows)}",
            f"- armed_retest_would_help: {armed_help}",
            "",
            "## Blocking Reasons",
        ]
        if blockers:
            for reason, count in blockers.most_common(10):
                lines.append(f"- {reason}: {count}")
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "## Interpretation",
                "- Este reporte mide oportunidades no ejecutadas; no cambia lógica por sí solo.",
                "- Las filas pending deben resolverse con velas futuras para saber si el bloqueo fue correcto o demasiado estricto.",
            ]
        )
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {
            "status": "generated",
            "total_candidates": len(rows),
            "top_blockers": blockers.most_common(5),
            "armed_retest_would_help": armed_help,
            "report_path": str(self.report_path.resolve()),
        }

    @staticmethod
    def _blocking_reason(
        *,
        execution_status: str,
        final_confirmation: dict[str, Any],
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
    ) -> str:
        if final_confirmation.get("blockers"):
            return "final:" + ",".join(str(item) for item in final_confirmation.get("blockers", [])[:3])
        if execution_readiness.get("blockers"):
            return "readiness:" + ",".join(str(item) for item in execution_readiness.get("blockers", [])[:3])
        if entry_quality.get("decision") in {"WAIT_RETEST", "LATE_ENTRY_BLOCK", "TRAP_RISK_BLOCK", "INVALID_ZONE_BLOCK"}:
            return "entry_quality:" + str(entry_quality.get("decision"))
        return execution_status

    def _append(self, payload: dict[str, Any]) -> None:
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _read_jsonl(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.history_path.exists():
            return rows
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
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
    def _latest_price(snapshot: dict[str, Any]) -> float | None:
        candles = snapshot.get("candles", {}).get("M1") if isinstance(snapshot.get("candles"), dict) else None
        if not candles:
            candles = snapshot.get("candles", {}).get("M5") if isinstance(snapshot.get("candles"), dict) else None
        if not candles:
            return None
        candle = candles[-1]
        value = candle.get("close") if isinstance(candle, dict) else getattr(candle, "close", None)
        try:
            return round(float(value), 5)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
