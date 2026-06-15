"""Execution readiness scoring for MAXIMO demo trading."""

from __future__ import annotations

from typing import Any

from src.trading.supervised_calibration_profile import v56_thresholds


class ExecutionReadinessEngine:
    """Combine confirmation, pulse, direction and risk geometry into one score."""

    def evaluate(
        self,
        *,
        final_confirmation: dict[str, Any],
        market_pulse: dict[str, Any],
        direction_consistency_guard: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        q_learning_decision: dict[str, Any],
        intelligence: dict[str, Any],
        entry_quality: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        final_score = self._score(final_confirmation.get("final_confirmation_score"))
        pulse_score = self._score(market_pulse.get("score"))
        direction_score = self._direction_alignment_score(
            direction_consistency_guard=direction_consistency_guard,
            q_learning_decision=q_learning_decision,
            final_confirmation=final_confirmation,
        )
        risk_geometry_score = self._risk_geometry_score(
            execution_risk_decision=execution_risk_decision,
            entry_quality=entry_quality,
        )
        score = (
            final_score * 0.35
            + pulse_score * 0.25
            + direction_score * 0.20
            + risk_geometry_score * 0.20
        )

        penalties: list[dict[str, Any]] = []
        q_conflict_accepted_as_caution = bool(
            direction_consistency_guard.get("allowed", True)
            and direction_consistency_guard.get("conflicts") == ["persistent_q_learning_policy"]
            and (
                direction_consistency_guard.get("armed_retest_q_learning_override")
                or direction_consistency_guard.get("supervised_v56_override")
            )
        )
        self._penalize(penalties, "spread_or_latency_not_safe", self._execution_env_penalty(final_confirmation))
        self._penalize(penalties, "sl_too_wide_or_min_lot_risk", 6.0 if execution_risk_decision.get("execution_recovery_plan") else 0.0)
        self._penalize(penalties, "tp_or_rr_not_realistic", 12.0 if final_confirmation.get("rr_evaluable") is False else 0.0)
        self._penalize(penalties, "zone_invalid", 28.0 if "zone_invalid_or_expired" in final_confirmation.get("blockers", []) else 0.0)
        self._penalize(penalties, "late_entry", self._bounded(final_confirmation.get("late_entry_risk")) * 16.0)
        self._penalize(
            penalties,
            "q_learning_against",
            12.0 if self._q_learning_against(q_learning_decision, final_confirmation) and not q_conflict_accepted_as_caution else 0.0,
        )
        event_action = final_confirmation.get("event_action")
        self._penalize(penalties, "macro_event_not_allow", 35.0 if event_action not in {None, "allow", "watch"} else 0.0)
        self._penalize(penalties, "final_confirmation_low", 16.0 if final_score < 60.0 else 0.0)
        if entry_quality:
            self._penalize(penalties, "entry_quality_low", max(0.0, 75.0 - self._score(entry_quality.get("entry_quality_score"))) * 0.35)

        penalty_total = sum(item["penalty"] for item in penalties)
        score = round(max(0.0, min(100.0, score - penalty_total)), 2)
        supervised_calibration = self._supervised_v56_calibration(
            score=score,
            final_score=final_score,
            pulse_score=pulse_score,
            direction_score=direction_score,
            risk_geometry_score=risk_geometry_score,
            final_confirmation=final_confirmation,
            entry_quality=entry_quality,
            execution_risk_decision=execution_risk_decision,
            penalties=penalties,
        )
        if supervised_calibration["eligible"]:
            score = round(max(score + supervised_calibration["boost"], supervised_calibration["floor"]), 2)
            score = round(max(0.0, min(100.0, score)), 2)
        armed_retest_context_recovery = self._armed_retest_context_recovery(
            score=score,
            final_score=final_score,
            pulse_score=pulse_score,
            direction_score=direction_score,
            final_confirmation=final_confirmation,
            entry_quality=entry_quality,
            penalties=penalties,
        )
        if armed_retest_context_recovery["eligible"]:
            score = round(max(score, armed_retest_context_recovery["floor"]), 2)
        classification = self._classification(score)

        blockers = list(final_confirmation.get("blockers", []) or [])
        if not direction_consistency_guard.get("allowed", True):
            blockers.append("direction_consistency_not_valid")
        if execution_risk_decision.get("execution_status") == "blocked_by_min_lot_exceeds_10_percent_account_risk":
            blockers.append("min_lot_exceeds_risk")

        return {
            "execution_readiness_score": score,
            "classification": classification,
            "components": {
                "final_confirmation_score": round(final_score, 2),
                "market_pulse_score": round(pulse_score, 2),
                "direction_alignment_score": round(direction_score, 2),
                "risk_geometry_score": round(risk_geometry_score, 2),
            },
            "supervised_v56_calibration": supervised_calibration,
            "armed_retest_context_recovery": armed_retest_context_recovery,
            "penalties": penalties,
            "blockers": self._dedupe(blockers),
            "warnings": list(final_confirmation.get("warnings", []) or []),
            "can_execute_quality_gate": score >= 78.0,
            "should_arm_retest": 71.0 <= score <= 77.0,
            "reason": self._reason(score=score, classification=classification, penalties=penalties, intelligence=intelligence),
        }

    @classmethod
    def _armed_retest_context_recovery(
        cls,
        *,
        score: float,
        final_score: float,
        pulse_score: float,
        direction_score: float,
        final_confirmation: dict[str, Any],
        entry_quality: dict[str, Any] | None,
        penalties: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Keep strong pre-entry context armed without allowing execution.

        This recovery is intentionally capped in the ARMED_RETEST band.  It fixes
        the "I see the opportunity but classify it as NOT_READY" problem while
        preserving the hard execution gate: Final Confirmation, Entry Quality and
        Execution Readiness still need to reach the execution thresholds before an
        order can be sent.
        """
        entry_quality = entry_quality or {}
        critical_penalties = {
            "spread_or_latency_not_safe",
            "zone_invalid",
            "macro_event_not_allow",
            "q_learning_against",
        }
        active_critical = [item["reason"] for item in penalties if item.get("reason") in critical_penalties]
        if active_critical:
            return {
                "eligible": False,
                "floor": 0.0,
                "reason": "critical_penalty_active",
                "critical_penalties": active_critical,
            }
        blockers = {str(item) for item in final_confirmation.get("blockers", []) or []}
        if blockers.intersection({"zone_invalid_or_expired", "macro_event_not_allow", "direction_consistency_not_valid"}):
            return {"eligible": False, "floor": 0.0, "reason": "critical_blocker_active"}
        entry_decision = str(entry_quality.get("decision") or "")
        zone_quality = cls._score(entry_quality.get("zone_quality"))
        trap_risk = cls._bounded(final_confirmation.get("trap_risk_score"))
        late_entry_risk = cls._bounded(final_confirmation.get("late_entry_risk"))
        if (
            pulse_score < 85.0
            or not (45.0 <= final_score < 60.0)
            or direction_score < 68.0
            or entry_decision != "WAIT_RETEST"
            or zone_quality < 45.0
            or trap_risk >= 0.72
            or late_entry_risk >= 0.72
        ):
            return {"eligible": False, "floor": 0.0, "reason": "context_not_strong_enough_for_armed_retest"}

        liquidity = final_confirmation.get("liquidity_volume_trap_analysis") or {}
        liquidity_readiness = cls._bounded(liquidity.get("liquidity_readiness_score"), default=0.0)
        floor = 71.0
        if zone_quality >= 60.0:
            floor += 1.5
        if liquidity_readiness >= 0.5:
            floor += 1.5
        floor = min(77.0, floor)
        return {
            "eligible": True,
            "floor": round(floor, 2),
            "reason": "strong_context_wait_retest_kept_armed",
            "previous_score": round(score, 2),
            "requirements": {
                "market_pulse_min": 85.0,
                "final_confirmation_band": "45-60",
                "entry_decision": "WAIT_RETEST",
                "zone_quality_min": 45.0,
                "direction_score_min": 68.0,
            },
        }

    @classmethod
    def _supervised_v56_calibration(
        cls,
        *,
        score: float,
        final_score: float,
        pulse_score: float,
        direction_score: float,
        risk_geometry_score: float,
        final_confirmation: dict[str, Any],
        entry_quality: dict[str, Any] | None,
        execution_risk_decision: dict[str, Any],
        penalties: list[dict[str, Any]],
    ) -> dict[str, Any]:
        thresholds = v56_thresholds()
        entry_calibration = (entry_quality or {}).get("supervised_v56_calibration") or {}
        if not thresholds or not entry_calibration.get("eligible"):
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "no_v56_entry_calibration"}
        critical_penalties = {
            "spread_or_latency_not_safe",
            "tp_or_rr_not_realistic",
            "zone_invalid",
            "macro_event_not_allow",
        }
        active_critical = [item["reason"] for item in penalties if item.get("reason") in critical_penalties]
        if active_critical:
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "critical_penalty_active", "critical_penalties": active_critical}
        if execution_risk_decision.get("execution_status") == "blocked_by_min_lot_exceeds_10_percent_account_risk":
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "min_lot_risk_block_active"}
        blockers = [str(item) for item in final_confirmation.get("blockers", []) or []]
        if final_score < 58.0 or pulse_score < 70.0:
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "confirmation_pulse_or_direction_below_profile"}
        if direction_score < thresholds.get("direction_alignment_floor", 50.0) and "direction_consistency_not_valid" in blockers:
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "direction_consistency_blocker_below_profile"}
        floor = min(78.0, thresholds.get("execution_readiness_recovery_floor", 70.0) + 3.0)
        boost = 3.0
        if risk_geometry_score >= 70.0:
            boost += 2.0
        if pulse_score >= 85.0:
            boost += 2.0
        if score >= floor:
            boost = min(boost, 2.0)
        return {
            "eligible": True,
            "boost": round(boost, 2),
            "floor": round(floor, 2),
            "reason": "v56_supervised_readiness_recovery",
            "thresholds": {
                "execution_readiness_recovery_floor": thresholds.get("execution_readiness_recovery_floor"),
                "direction_alignment_floor": thresholds.get("direction_alignment_floor"),
            },
        }

    @staticmethod
    def _classification(score: float) -> str:
        if score <= 50:
            return "NOT_READY"
        if score <= 70:
            return "WATCH_ONLY"
        if score <= 77:
            return "ARMED_RETEST"
        return "EXECUTION_READY"

    @classmethod
    def _direction_alignment_score(
        cls,
        *,
        direction_consistency_guard: dict[str, Any],
        q_learning_decision: dict[str, Any],
        final_confirmation: dict[str, Any],
    ) -> float:
        if not direction_consistency_guard.get("allowed", True):
            return 0.0
        conflicts = [str(item) for item in direction_consistency_guard.get("conflicts", []) or []]
        if (
            conflicts == ["persistent_q_learning_policy"]
            and (
                direction_consistency_guard.get("armed_retest_q_learning_override")
                or direction_consistency_guard.get("supervised_v56_override")
            )
        ):
            return 72.0
        side = str(final_confirmation.get("side") or "").upper()
        q_policy = str(q_learning_decision.get("q_policy_action") or q_learning_decision.get("policy_action") or "HOLD").upper()
        q_alignment = cls._bounded(final_confirmation.get("q_learning_alignment"))
        if side in {"BUY", "SELL"} and q_policy == side:
            return 92.0
        if q_policy == "HOLD":
            return 65.0 + q_alignment * 20.0
        if side in {"BUY", "SELL"} and q_policy in {"BUY", "SELL"} and q_policy != side:
            return 35.0
        return 70.0

    @staticmethod
    def _risk_geometry_score(
        *,
        execution_risk_decision: dict[str, Any],
        entry_quality: dict[str, Any] | None,
    ) -> float:
        if execution_risk_decision.get("execution_recovery_plan"):
            return 38.0
        if execution_risk_decision.get("allowed_risk_mode") == "blocked":
            return 25.0
        if entry_quality:
            return max(20.0, min(100.0, float(entry_quality.get("sl_quality") or 50.0) * 0.55 + float(entry_quality.get("tp_quality") or 50.0) * 0.45))
        return 70.0 if execution_risk_decision.get("can_execute") else 45.0

    @staticmethod
    def _execution_env_penalty(final_confirmation: dict[str, Any]) -> float:
        viability = str(final_confirmation.get("execution_viability") or "").upper()
        if viability == "UNSAFE":
            return 24.0
        if viability == "UNKNOWN":
            return 7.0
        return 0.0

    @classmethod
    def _q_learning_against(cls, q_learning_decision: dict[str, Any], final_confirmation: dict[str, Any]) -> bool:
        side = str(final_confirmation.get("side") or "").upper()
        q_policy = str(q_learning_decision.get("q_policy_action") or q_learning_decision.get("policy_action") or "HOLD").upper()
        return side in {"BUY", "SELL"} and q_policy in {"BUY", "SELL"} and q_policy != side

    @staticmethod
    def _penalize(penalties: list[dict[str, Any]], reason: str, penalty: float) -> None:
        if penalty > 0:
            penalties.append({"reason": reason, "penalty": round(float(penalty), 2)})

    @staticmethod
    def _score(value: Any) -> float:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _bounded(value: Any, *, default: float = 0.5) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = str(item)
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    @staticmethod
    def _reason(
        *,
        score: float,
        classification: str,
        penalties: list[dict[str, Any]],
        intelligence: dict[str, Any],
    ) -> str:
        action = intelligence.get("execution_readiness", {}).get("action")
        if penalties:
            top = ", ".join(item["reason"] for item in penalties[:3])
            return f"{classification}: score={score}. Penalizaciones principales: {top}. action={action}."
        return f"{classification}: score={score}. Confirmación, pulso, dirección y geometría están balanceados. action={action}."
