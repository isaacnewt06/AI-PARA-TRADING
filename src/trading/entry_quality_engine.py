"""Entry quality scoring for MAXIMO demo trading.

This layer does not create signals or bypass execution guards.  It grades the
actual entry location so strong market context does not become a late entry.
"""

from __future__ import annotations

from typing import Any

from src.trading.supervised_calibration_profile import v56_thresholds


class EntryQualityEngine:
    """Evaluate whether a candidate entry is clean, late, trapped or invalid."""

    def evaluate(
        self,
        *,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        final_confirmation: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        execution_environment: dict[str, Any],
        market_pulse: dict[str, Any],
    ) -> dict[str, Any]:
        watch_trigger = intelligence.get("watch_trigger") or {}
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        recovery_plan = execution_risk_decision.get("execution_recovery_plan") or {}

        side = str(
            (signal or {}).get("direction")
            or (active_watch or {}).get("side")
            or watch_trigger.get("side")
            or market_state.get("preferred_side")
            or "NEUTRAL"
        ).upper()
        final_score = self._safe_float(final_confirmation.get("final_confirmation_score"))
        pulse_score = self._safe_float(market_pulse.get("score"))
        late_entry_risk = self._bounded(final_confirmation.get("late_entry_risk"), default=0.35)
        trap_risk = self._bounded(final_confirmation.get("trap_risk_score"), default=0.35)
        zone_validity_score = self._bounded(final_confirmation.get("zone_validity_score"), default=0.5)
        liquidity = final_confirmation.get("liquidity_volume_trap_analysis") or {}
        knowledge_context = self._knowledge_context_score(
            intelligence=intelligence,
            signal=signal,
            side=side,
            final_confirmation=final_confirmation,
            market_pulse=market_pulse,
        )

        entry_price = self._safe_float((signal or {}).get("entry_price"))
        stop_price = self._safe_float((signal or {}).get("stop_price"))
        target_price = self._safe_float((signal or {}).get("target_price"))
        rr = self._safe_float((signal or {}).get("selected_rr"))
        risk_per_unit = abs(entry_price - stop_price) if entry_price and stop_price else 0.0
        reward_per_unit = abs(target_price - entry_price) if target_price and entry_price else 0.0

        timing_quality = max(0.0, min(100.0, final_score - late_entry_risk * 24.0 + pulse_score * 0.12))
        zone_quality = max(0.0, min(100.0, zone_validity_score * 100.0 - trap_risk * 10.0))
        retest_quality = self._retest_quality(signal=signal, recovery_plan=recovery_plan, watch_trigger=watch_trigger)
        sl_quality = self._sl_quality(risk_per_unit=risk_per_unit, recovery_plan=recovery_plan, execution_risk_decision=execution_risk_decision)
        tp_quality = self._tp_quality(rr=rr, reward_per_unit=reward_per_unit, risk_per_unit=risk_per_unit)
        liquidity_context_score = self._bounded(
            liquidity.get("liquidity_readiness_score"),
            default=0.5,
        ) * 100.0
        compact_sl_score = sl_quality

        score = (
            timing_quality * 0.20
            + retest_quality * 0.16
            + sl_quality * 0.18
            + tp_quality * 0.14
            + zone_quality * 0.16
            + liquidity_context_score * 0.10
            + compact_sl_score * 0.06
            + knowledge_context["boost"]
            - late_entry_risk * 12.0
            - trap_risk * 12.0
        )
        if recovery_plan:
            score -= 12.0
        if str(execution_environment.get("execution_viability") or "").upper() == "UNSAFE":
            score -= 16.0
        supervised_calibration = self._supervised_v56_calibration(
            signal=signal,
            final_score=final_score,
            pulse_score=pulse_score,
            zone_quality=zone_quality,
            trap_risk=trap_risk,
            late_entry_risk=late_entry_risk,
            retest_quality=retest_quality,
            sl_quality=sl_quality,
            tp_quality=tp_quality,
            timing_quality=timing_quality,
            recovery_plan=recovery_plan,
            execution_environment=execution_environment,
        )
        if supervised_calibration["eligible"]:
            score += supervised_calibration["boost"]
            if supervised_calibration["floor"] > 0:
                score = max(score, supervised_calibration["floor"])
        score = round(max(0.0, min(100.0, score)), 2)
        if (
            signal is not None
            and not recovery_plan
            and risk_per_unit > 0
            and risk_per_unit <= 4.0
            and (rr >= 1.2 or (risk_per_unit > 0 and reward_per_unit / risk_per_unit >= 1.2))
            and zone_validity_score >= 0.45
            and trap_risk < 0.72
            and late_entry_risk < 0.72
            and final_score >= 72.0
        ):
            score = max(score, 76.0)

        reasons: list[str] = []
        decision = "CLEAN_ENTRY"
        if zone_validity_score < 0.45:
            decision = "INVALID_ZONE_BLOCK"
            reasons.append("La zona activa está invalidada o expirada.")
        elif trap_risk >= 0.72:
            decision = "TRAP_RISK_BLOCK"
            reasons.append("El riesgo de trampa/liquidez contra la entrada es alto.")
        elif late_entry_risk >= 0.72:
            decision = "LATE_ENTRY_BLOCK"
            reasons.append("La entrada llega tarde para la geometría actual.")
        elif recovery_plan:
            decision = "WAIT_RETEST"
            reasons.append(str(recovery_plan.get("reason") or "Esperar retest para compactar SL y riesgo."))
        elif score >= 75 and (final_score >= 75 or (final_score >= 72 and knowledge_context["score"] >= 75)):
            decision = "EXECUTION_READY"
            if knowledge_context["score"] >= 75:
                reasons.append(
                    "Entrada limpia con conocimiento aprendido alineado: timing, zona, SL/RR, patrón y confirmación final están sincronizados."
                )
            else:
                reasons.append("Entrada limpia: timing, zona, SL/RR y confirmación final están alineados.")
        elif score < 75:
            decision = "WAIT_RETEST"
            reasons.append("La idea es válida, pero necesita mejor precio/retest o confirmación más limpia.")
        else:
            reasons.append("Entrada aceptable, todavía sujeta a ExecutionReadiness y guards.")

        return {
            "side": side,
            "entry_quality_score": score,
            "timing_quality": round(timing_quality, 2),
            "retest_quality": round(retest_quality, 2),
            "sl_quality": round(sl_quality, 2),
            "tp_quality": round(tp_quality, 2),
            "zone_quality": round(zone_quality, 2),
            "late_entry_risk": round(late_entry_risk, 4),
            "trap_risk": round(trap_risk, 4),
            "liquidity_context_score": round(liquidity_context_score, 2),
            "compact_sl_score": round(compact_sl_score, 2),
            "learned_knowledge_entry_score": round(knowledge_context["score"], 2),
            "learned_knowledge_entry_boost": round(knowledge_context["boost"], 2),
            "learned_knowledge_entry_reasons": knowledge_context["reasons"],
            "supervised_v56_calibration": supervised_calibration,
            "risk_per_unit": round(risk_per_unit, 5),
            "reward_per_unit": round(reward_per_unit, 5),
            "decision": decision,
            "reasons": reasons,
            "retest_required": decision == "WAIT_RETEST",
            "late_entry_block": decision == "LATE_ENTRY_BLOCK",
            "trap_risk_block": decision == "TRAP_RISK_BLOCK",
            "invalid_zone_block": decision == "INVALID_ZONE_BLOCK",
        }

    @classmethod
    def _supervised_v56_calibration(
        cls,
        *,
        signal: dict[str, Any] | None,
        final_score: float,
        pulse_score: float,
        zone_quality: float,
        trap_risk: float,
        late_entry_risk: float,
        retest_quality: float,
        sl_quality: float,
        tp_quality: float,
        timing_quality: float,
        recovery_plan: dict[str, Any],
        execution_environment: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = v56_thresholds()
        if not thresholds or signal is None:
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "no_supervised_profile_or_signal"}
        setup = str(signal.get("setup_type") or signal.get("signal_type") or "").upper()
        market_regime = str(signal.get("market_regime") or signal.get("regime") or "").upper()
        resembles_v56 = "AGG" in setup or "V56" in setup or market_regime == "EXPANSION"
        if not resembles_v56:
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "not_v56_like_setup"}
        if recovery_plan:
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "risk_recovery_plan_active"}
        if str(execution_environment.get("execution_viability") or "").upper() == "UNSAFE":
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "execution_environment_unsafe"}
        max_trap = thresholds.get("max_winner_trap_risk", 0.72)
        max_late = thresholds.get("max_winner_late_entry_risk", 0.72)
        zone_floor = thresholds.get("zone_validity_floor", 45.0)
        if trap_risk > max_trap or late_entry_risk > max_late or zone_quality < zone_floor:
            return {
                "eligible": False,
                "boost": 0.0,
                "floor": 0.0,
                "reason": "v56_profile_rejected_by_trap_late_or_zone",
                "thresholds": {
                    "max_trap": max_trap,
                    "max_late": max_late,
                    "zone_floor": zone_floor,
                },
            }
        if final_score < 58.0 or pulse_score < 70.0:
            return {"eligible": False, "boost": 0.0, "floor": 0.0, "reason": "v56_profile_requires_min_confirmation_and_pulse"}
        component_strength = (retest_quality + sl_quality + tp_quality + timing_quality + zone_quality) / 5.0
        boost = 3.0
        if component_strength >= 70:
            boost += 3.0
        if pulse_score >= 85:
            boost += 2.0
        floor = min(76.0, thresholds.get("entry_quality_winner_floor", 68.0) + 2.0)
        return {
            "eligible": True,
            "boost": round(boost, 2),
            "floor": round(floor, 2),
            "reason": "v56_supervised_winner_like_context",
            "component_strength": round(component_strength, 2),
            "thresholds": {
                "entry_quality_winner_floor": thresholds.get("entry_quality_winner_floor"),
                "zone_validity_floor": zone_floor,
                "max_winner_trap_risk": max_trap,
                "max_winner_late_entry_risk": max_late,
            },
        }

    @classmethod
    def _knowledge_context_score(
        cls,
        *,
        intelligence: dict[str, Any],
        signal: dict[str, Any] | None,
        side: str,
        final_confirmation: dict[str, Any],
        market_pulse: dict[str, Any],
    ) -> dict[str, Any]:
        """Quantify whether extracted course/Telegram knowledge supports this entry.

        This score only gives a controlled boost to entry quality. It cannot bypass
        macro, execution, SL/RR, direction or risk guards.
        """
        side = str(side or "NEUTRAL").upper()
        if signal is None or side not in {"BUY", "SELL"}:
            return {"score": 0.0, "boost": 0.0, "reasons": []}

        watch_trigger = intelligence.get("watch_trigger") or {}
        projection = watch_trigger.get("pattern_projection") or {}
        overview = intelligence.get("overview", {}) or {}
        market_state = overview.get("market_state", {}) or {}
        knowledge_alignment = overview.get("knowledge_alignment", {}) or {}
        harmony = knowledge_alignment.get("harmony", {}) or {}
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        manual_bias = ob_families.get("manual_bias") or {}
        active_family = str(market_state.get("operational_family") or ob_families.get("active_family") or "").upper()
        extracted_brain = projection.get("extracted_knowledge_operational_brain") or {}
        professional_matrix = projection.get("professional_decision_matrix") or {}
        historical_analogs = projection.get("historical_analogs") or {}
        cool_learning = projection.get("cool_learning_memory") or projection.get("q_learning_memory") or {}
        course_alignment = cool_learning.get("course_alignment") or {}

        score = 0.0
        reasons: list[str] = []
        brain_status = str(extracted_brain.get("status") or "").lower()
        brain_role = str(extracted_brain.get("role") or "").lower()
        if brain_status in {"primary_operational_brain", "armed_course_protocol"}:
            score += 22.0
            reasons.append(f"cerebro_extraido={brain_status}")
        elif "operativo" in brain_role or "decision" in brain_role:
            score += 14.0
            reasons.append(f"rol_conocimiento={brain_role}")

        protocol_priority = str(extracted_brain.get("protocol_priority") or "").lower()
        protocols = list(course_alignment.get("auto_selected_protocols") or extracted_brain.get("protocols") or [])
        if "sensei" in protocol_priority or any("SENSEI" in str(item).upper() or "BIAS" in str(item).upper() for item in protocols):
            score += 18.0
            reasons.append("protocolo_sensei_manual_bias_activo")

        if bool((signal or {}).get("manual_bias_confirmation")):
            score += 16.0
            reasons.append("signal_manual_bias_confirmation")
        if bool(manual_bias.get("active")) and str(manual_bias.get("side") or "").upper() == side:
            score += 14.0
            reasons.append("manual_bias_side_aligned")

        if "OB_REJECTION" in active_family:
            score += 10.0
            reasons.append(f"familia_operativa={active_family}")
        harmony_score = cls._bounded(harmony.get("harmony_score"), default=0.0)
        support_score = cls._bounded(knowledge_alignment.get("support_score"), default=0.0)
        score += min(12.0, harmony_score * 12.0)
        score += min(8.0, support_score * 8.0)
        if harmony_score >= 0.60:
            reasons.append(f"harmony_score={round(harmony_score, 2)}")
        if support_score >= 0.45:
            reasons.append(f"support_score={round(support_score, 2)}")

        if str(historical_analogs.get("bias") or "").lower() == "favorable":
            score += 12.0
            reasons.append("analogias_historicas_favorables")
        course_status = str(course_alignment.get("status") or "").lower()
        course_action = str(course_alignment.get("course_recommended_action") or "").upper()
        if course_status in {"aligned", "partial"}:
            score += 10.0 if course_action in {side, "WAIT", ""} else 4.0
            reasons.append(f"curso_estado={course_status}")
        if str(cool_learning.get("policy_action") or "").upper() == side:
            score += 8.0
            reasons.append("q_learning_curso_alineado")
        if str(professional_matrix.get("selected_side") or "").upper() == side:
            score += 6.0
            reasons.append("matriz_profesional_lado_alineado")

        final_score = cls._safe_float(final_confirmation.get("final_confirmation_score"))
        pulse_score = cls._safe_float(market_pulse.get("score"))
        zone_validity = cls._bounded(final_confirmation.get("zone_validity_score"), default=0.5)
        trap_risk = cls._bounded(final_confirmation.get("trap_risk_score"), default=0.35)
        late_entry_risk = cls._bounded(final_confirmation.get("late_entry_risk"), default=0.35)

        if pulse_score < 70 or final_score < 58:
            score *= 0.45
            reasons.append("conocimiento_limitado_por_pulso_o_confirmacion_baja")
        if zone_validity < 0.45 or trap_risk >= 0.72 or late_entry_risk >= 0.72:
            score = min(score, 24.0)
            reasons.append("conocimiento_no_supera_zona_trampa_o_entrada_tardia")

        score = round(max(0.0, min(100.0, score)), 2)
        boost = 0.0
        if score >= 75:
            boost = 9.0
        elif score >= 62:
            boost = 5.0
        elif score >= 48:
            boost = 2.5
        return {"score": score, "boost": boost, "reasons": reasons[:8]}

    @staticmethod
    def _retest_quality(
        *,
        signal: dict[str, Any] | None,
        recovery_plan: dict[str, Any],
        watch_trigger: dict[str, Any],
    ) -> float:
        if recovery_plan:
            return 45.0
        if signal and (signal.get("micro_bos") or signal.get("wick_rejection_quality")):
            return 78.0
        required = " ".join(str(item).lower() for item in watch_trigger.get("required_conditions", []))
        if "retest" in required or "pullback" in required:
            return 62.0
        return 68.0 if signal else 54.0

    @staticmethod
    def _sl_quality(
        *,
        risk_per_unit: float,
        recovery_plan: dict[str, Any],
        execution_risk_decision: dict[str, Any],
    ) -> float:
        if recovery_plan:
            return 42.0
        if execution_risk_decision.get("execution_status") == "blocked_by_min_lot_exceeds_10_percent_account_risk":
            return 25.0
        if risk_per_unit <= 0:
            return 48.0
        if risk_per_unit <= 4.0:
            return 90.0
        if risk_per_unit <= 8.0:
            return 76.0
        if risk_per_unit <= 14.0:
            return 58.0
        return 38.0

    @staticmethod
    def _tp_quality(*, rr: float, reward_per_unit: float, risk_per_unit: float) -> float:
        if rr > 0:
            if rr >= 1.5:
                return 86.0
            if rr >= 1.0:
                return 72.0
            return 45.0
        if risk_per_unit > 0 and reward_per_unit > 0:
            implied_rr = reward_per_unit / risk_per_unit
            return 80.0 if implied_rr >= 1.2 else 50.0
        return 50.0

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _bounded(cls, value: Any, *, default: float) -> float:
        numeric = cls._safe_float(value, default)
        return max(0.0, min(1.0, numeric))
