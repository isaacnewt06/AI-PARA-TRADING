"""Harmony audit for the MAXIMO trading AI stack."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AIHarmonyAuditor:
    """Produces a compact audit of whether MAXIMO layers agree or conflict."""

    def __init__(self, *, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.report_path = reports_dir / "AI_HARMONY_AUDIT_REPORT.md"

    def generate(
        self,
        *,
        intelligence: dict[str, Any],
        signal: dict[str, Any] | None,
        active_watch: dict[str, Any] | None,
        market_pulse: dict[str, Any],
        q_learning_decision: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        position_management: dict[str, Any],
        direction_consistency_guard: dict[str, Any],
        final_confirmation: dict[str, Any],
        real_account_safety_gate: dict[str, Any],
    ) -> dict[str, Any]:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        readiness = intelligence.get("execution_readiness", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        entry_quality = intelligence.get("entry_quality") or {}
        execution_readiness_quality = intelligence.get("execution_readiness_quality") or {}
        armed_retest = intelligence.get("armed_retest") or {}
        trade_experience_memory = intelligence.get("trade_experience_memory") or {}
        projection = (watch_trigger.get("pattern_projection") or {})
        brain = projection.get("extracted_knowledge_operational_brain") or {}
        preferred_side = str(market_state.get("preferred_side") or "").upper()
        signal_side = str((signal or {}).get("direction") or "").upper()
        q_side = str(q_learning_decision.get("q_policy_action") or "").upper()
        final_decision = str(final_confirmation.get("decision") or "").upper()
        final_blockers = list(final_confirmation.get("blockers") or [])
        contradictions: list[str] = []
        warnings: list[str] = []
        confirmations: list[str] = []

        if signal_side in {"BUY", "SELL"} and preferred_side in {"BUY", "SELL"} and signal_side != preferred_side:
            if not (signal or {}).get("countertrend_reversal_scalp"):
                contradictions.append("BUY/SELL contradiction without explicit countertrend reversal scalp.")
            else:
                confirmations.append("Countertrend side is explicitly labelled as reversal scalp.")
        if q_side in {"BUY", "SELL"} and signal_side in {"BUY", "SELL"} and q_side != signal_side and final_decision == "EXECUTE":
            contradictions.append("Q-learning policy contradicts signal side.")
        elif q_side in {"BUY", "SELL"} and signal_side in {"BUY", "SELL"} and q_side != signal_side:
            warnings.append("Q-learning policy contradicts signal side, but final guard is not executing yet.")
        if q_side in {"BUY", "SELL"} and preferred_side in {"BUY", "SELL"} and q_side != preferred_side:
            warnings.append("Q-learning policy is not aligned with preferred_side; require stronger final confirmation.")
        watch_side = str(watch_trigger.get("side") or watch_trigger.get("candidate_side") or "").upper()
        if watch_side in {"BUY", "SELL"}:
            watch_text = " ".join(
                str(item)
                for item in list(watch_trigger.get("required_conditions") or [])
                + list(watch_trigger.get("cancel_conditions") or [])
                + list(watch_trigger.get("missing_for_execute") or [])
            ).upper()
            opposite = "SELL" if watch_side == "BUY" else "BUY"
            if f"HIGHER_TIMEFRAME_BIAS EN {opposite}" in watch_text:
                contradictions.append("Watch trigger contains higher-timeframe requirement for the opposite side.")
            if f"LADO CANDIDATO CAMBIA A {watch_side}" in watch_text:
                contradictions.append("Watch trigger cancel condition invalidates its own side.")
        if market_pulse.get("score", 0) >= 70 and not execution_risk_decision.get("can_execute") and signal is not None and not final_blockers:
            contradictions.append("Strong Market Pulse but execution is blocked; check blocker transparency.")
        elif market_pulse.get("score", 0) >= 70 and not execution_risk_decision.get("can_execute") and signal is not None:
            warnings.append("Strong Market Pulse is present, but final guard is blocking with transparent reasons.")
        if readiness.get("action") == "EXECUTE" and final_decision != "EXECUTE":
            if final_blockers:
                warnings.append("Market intelligence says EXECUTE, but final confirmation correctly requires more safety.")
            else:
                contradictions.append("Market intelligence says EXECUTE but final confirmation does not.")
        if market_pulse.get("score", 0) >= 85 and final_confirmation.get("final_confirmation_score", 0) < 60:
            warnings.append("Market Pulse is predator/strong while Final Confirmation remains below 60; avoid treating pulse as entry signal.")
        if market_pulse.get("score", 0) >= 85 and readiness.get("action") == "WATCH" and not signal:
            warnings.append("Strong market context is only WATCH; system needs final trigger/retest before execution.")
        if final_confirmation.get("warnings"):
            warnings.extend(f"FinalConfirmation warning: {item}" for item in final_confirmation.get("warnings", []))
        if execution_readiness_quality:
            readiness_score = float(execution_readiness_quality.get("execution_readiness_score") or 0.0)
            if readiness_score < 78:
                warnings.append(
                    f"ExecutionReadiness below executable threshold: {readiness_score} ({execution_readiness_quality.get('classification')})."
                )
            penalties = execution_readiness_quality.get("penalties") or []
            for penalty in penalties[:3]:
                warnings.append(f"ExecutionReadiness penalty: {penalty.get('reason')}={penalty.get('penalty')}.")
        if entry_quality:
            entry_score = float(entry_quality.get("entry_quality_score") or 0.0)
            entry_decision = str(entry_quality.get("decision") or "")
            if entry_decision in {"WAIT_RETEST", "LATE_ENTRY_BLOCK", "TRAP_RISK_BLOCK", "INVALID_ZONE_BLOCK"}:
                warnings.append(f"EntryQuality requires caution: {entry_decision} score={entry_score}.")
        if armed_retest:
            action = str(armed_retest.get("action") or "")
            if action in {"ARMED_RETEST_DROP", "ARMED_RETEST_EXPIRED"}:
                warnings.append(f"ARMED_RETEST not active: {action}; reason={armed_retest.get('reason')}.")
            elif action in {"ARMED_RETEST_WAIT", "ARMED_RETEST_CREATED"}:
                confirmations.append("ARMED_RETEST is keeping the idea alive while waiting for better timing.")
        memory_bias = str(trade_experience_memory.get("memory_bias") or "").upper()
        if memory_bias in {"REDUCE_RISK", "BLOCK"}:
            warnings.append(
                f"TradeExperienceMemory is defensive: {memory_bias}; similarity_to_losers={trade_experience_memory.get('similarity_to_losers')}."
            )
        if position_management.get("status") == "inactive" and position_management.get("positions_managed", 0):
            contradictions.append("Position exists but post-entry management appears inactive.")
        if execution_risk_decision.get("risk_percent_policy") and execution_risk_decision.get("account_risk_percent") is None:
            contradictions.append("Risk policy exists but applied account risk is missing.")
        if real_account_safety_gate.get("real_allowed"):
            contradictions.append("Real gate unexpectedly allowed real; expected blocked in this phase.")

        if brain.get("status") in {"primary_operational_brain", "armed_course_protocol"}:
            confirmations.append("Extracted course/Telegram/manual knowledge is active in operational brain.")
        if direction_consistency_guard.get("allowed"):
            confirmations.append("Direction consistency guard allows current thesis.")
        if market_pulse.get("score", 0) >= 51:
            confirmations.append("Market Pulse sees a tradable or stronger context.")
        if position_management.get("history_path"):
            confirmations.append("Position management history is configured.")
        if q_learning_decision.get("experience_count", 0) is not None:
            confirmations.append("Persistent Q-learning memory is reporting experience count.")

        contradictions = self._dedupe(contradictions)
        warnings = self._dedupe(warnings)
        confirmations = self._dedupe(confirmations)
        status = "HARMONIZED_WITH_WARNINGS" if contradictions or warnings else "HARMONIZED"
        if len(contradictions) >= 3:
            status = "CONFLICTED_REQUIRES_ATTENTION"

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "preferred_side": preferred_side,
            "signal_side": signal_side or "NONE",
            "q_learning_policy": q_side,
            "market_pulse_score": market_pulse.get("score"),
            "final_confirmation_decision": final_confirmation.get("decision"),
            "final_confirmation_score": final_confirmation.get("final_confirmation_score"),
            "risk_mode": execution_risk_decision.get("allowed_risk_mode"),
            "execution_mode": execution_risk_decision.get("execution_mode"),
            "real_gate_status": real_account_safety_gate.get("status"),
            "contradictions": contradictions,
            "warnings": warnings,
            "layer_tensions": warnings,
            "confirmations": confirmations,
            "report_path": str(self.report_path.resolve()),
        }
        self._write_report(payload)
        return payload

    def _write_report(self, payload: dict[str, Any]) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "# AI Harmony Audit Report",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- status: {payload['status']}",
            f"- preferred_side: {payload['preferred_side']}",
            f"- signal_side: {payload['signal_side']}",
            f"- q_learning_policy: {payload['q_learning_policy']}",
            f"- market_pulse_score: {payload['market_pulse_score']}",
            f"- final_confirmation_decision: {payload['final_confirmation_decision']}",
            f"- final_confirmation_score: {payload['final_confirmation_score']}",
            f"- risk_mode: {payload['risk_mode']}",
            f"- execution_mode: {payload['execution_mode']}",
            f"- real_gate_status: {payload['real_gate_status']}",
            "",
            "## Contradictions",
        ]
        if payload["contradictions"]:
            for item in payload["contradictions"]:
                lines.append(f"- {item}")
        else:
            lines.append("- none")
        lines.extend(["", "## Warnings / Layer Tensions"])
        if payload["warnings"]:
            for item in payload["warnings"]:
                lines.append(f"- {item}")
        else:
            lines.append("- none")
        lines.extend(["", "## Confirmations"])
        for item in payload["confirmations"]:
            lines.append(f"- {item}")
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = str(item).strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result
