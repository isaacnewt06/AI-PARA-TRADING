"""Final pre-execution confirmation layer for MAXIMO demo trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.core.logging import get_logger
from src.trading.supervised_calibration_profile import v56_thresholds

logger = get_logger(__name__)


@dataclass(frozen=True)
class FinalConfirmationThresholds:
    execute_score: float = 72.0
    prepare_score: float = 50.0
    max_trap_risk: float = 0.72
    max_late_entry_risk: float = 0.72
    min_zone_validity: float = 0.45


class FinalConfirmationEngine:
    """Separates a valid idea from a valid entry moment.

    This layer does not create strategy ideas. It audits whether an existing
    signal/watch is still timely, tradable and aligned enough to execute.
    """

    def __init__(self, thresholds: FinalConfirmationThresholds | None = None) -> None:
        self.thresholds = thresholds or FinalConfirmationThresholds()

    def evaluate(
        self,
        *,
        symbol: str,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        market_pulse: dict[str, Any],
        execution_environment: dict[str, Any],
        q_learning_decision: dict[str, Any],
        direction_consistency_guard: dict[str, Any] | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        readiness = intelligence.get("execution_readiness", {}) or {}
        overview = intelligence.get("overview", {}) or {}
        market_state = overview.get("market_state", {}) or {}
        harmony = (overview.get("knowledge_alignment", {}) or {}).get("harmony", {}) or {}
        event_risk = intelligence.get("event_risk", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        market_clarity = market_state.get("market_clarity") or {}
        clarity_side = str(market_clarity.get("selected_side") or "").upper()

        side = str(
            (signal or {}).get("direction")
            or (active_watch or {}).get("side")
            or watch_trigger.get("side")
            or (clarity_side if clarity_side in {"BUY", "SELL"} else None)
            or market_state.get("preferred_side")
            or "NEUTRAL"
        ).upper()
        setup_maturity = self._safe_float(readiness.get("setup_maturity") or watch_trigger.get("setup_maturity"))
        confidence = self._normalize_probability(readiness.get("confidence") or watch_trigger.get("confidence"))
        harmony_score = self._normalize_probability(harmony.get("harmony_score") or watch_trigger.get("harmony_score"))
        pulse_score = self._safe_float(market_pulse.get("score"))
        pulse_probability = max(0.0, min(1.0, pulse_score / 100.0))
        q_values = q_learning_decision.get("q_values") or {}
        q_side_value = self._safe_float(q_values.get(side)) if side in {"BUY", "SELL"} else 0.0
        q_hold_value = self._safe_float(q_values.get("HOLD"))
        q_alignment = 0.5
        q_policy = str(q_learning_decision.get("q_policy_action") or "HOLD").upper()
        if side in {"BUY", "SELL"}:
            if q_policy == side:
                q_alignment = 0.82
            elif q_policy == "HOLD" and q_hold_value > q_side_value + 0.18:
                q_alignment = 0.22
            elif q_policy in {"BUY", "SELL"} and q_policy != side:
                q_alignment = 0.35
            else:
                q_alignment = 0.58

        rr = self._safe_float((signal or {}).get("selected_rr"))
        rr_score = 0.0 if signal and rr <= 0 else min(1.0, rr / 2.0) if signal else 0.5
        logical_sl = bool((signal or {}).get("stop_price")) or self._contains_truthy(watch_trigger, "sl_logical_available")
        rr_evaluable = bool(rr > 0) or self._contains_truthy(watch_trigger, "rr_evaluable")
        execution_viability = str(execution_environment.get("execution_viability") or "UNKNOWN").upper()
        spread_safe = execution_viability != "UNSAFE"
        event_allow = self._event_allows_final_confirmation(event_risk=event_risk, signal=signal)
        direction_allowed = bool((direction_consistency_guard or {}).get("allowed", True))
        execution_cost_analysis = self._execution_cost_analysis(
            symbol=symbol,
            execution_environment=execution_environment,
            market_state=market_state,
        )
        session_execution_analysis = self._session_execution_analysis(
            signal=signal,
            market_state=market_state,
            execution_environment=execution_environment,
            snapshot=snapshot,
        )
        premium_discount_analysis = self._premium_discount_analysis(
            side=side,
            signal=signal,
            market_state=market_state,
            snapshot=snapshot,
        )
        liquidity_volume_trap = self._liquidity_volume_trap_analysis(
            side=side,
            signal=signal,
            market_state=market_state,
            market_pulse=market_pulse,
            snapshot=snapshot,
        )

        entry_timing_score = self._entry_timing_score(signal=signal, market_state=market_state, market_pulse=market_pulse)
        trap_risk_score = self._trap_risk_score(
            signal=signal,
            market_state=market_state,
            market_pulse=market_pulse,
            execution_environment=execution_environment,
            q_alignment=q_alignment,
            liquidity_volume_trap=liquidity_volume_trap,
        )
        late_entry_risk = self._late_entry_risk(signal=signal, market_state=market_state)
        zone_validity_score = self._zone_validity_score(active_watch=active_watch, watch_trigger=watch_trigger, signal=signal)
        continuation_probability = self._continuation_probability(
            side=side,
            signal=signal,
            market_state=market_state,
            market_pulse=market_pulse,
            q_alignment=q_alignment,
        )
        reversal_probability = self._reversal_probability(
            side=side,
            signal=signal,
            market_state=market_state,
            q_alignment=q_alignment,
        )

        score = (
            setup_maturity * 0.18
            + confidence * 100.0 * 0.13
            + harmony_score * 100.0 * 0.12
            + pulse_probability * 100.0 * 0.14
            + entry_timing_score * 100.0 * 0.14
            + zone_validity_score * 100.0 * 0.12
            + continuation_probability * 100.0 * 0.10
            + rr_score * 100.0 * 0.07
            + liquidity_volume_trap["liquidity_readiness_score"] * 100.0 * 0.06
            + liquidity_volume_trap["volume_confirmation_score"] * 100.0 * 0.04
            + liquidity_volume_trap["movement_quality_score"] * 100.0 * 0.05
            - trap_risk_score * 18.0
            - late_entry_risk * 16.0
            - liquidity_volume_trap["manipulation_risk_score"] * 10.0
        )
        score -= self._safe_float(execution_cost_analysis.get("score_penalty"))
        score -= self._safe_float(session_execution_analysis.get("score_penalty"))
        score -= self._safe_float(premium_discount_analysis.get("score_penalty"))
        score = round(max(0.0, min(100.0, score)), 2)
        dynamic_threshold = self._dynamic_execute_threshold(
            q_learning_decision=q_learning_decision,
            q_alignment=q_alignment,
        )

        blockers: list[str] = []
        warnings: list[str] = []
        if signal is not None and not logical_sl:
            blockers.append("no_logical_stop_loss")
        if signal is not None and not rr_evaluable:
            blockers.append("rr_not_evaluable")
        if not event_allow:
            blockers.append("macro_event_not_allow")
        elif event_risk.get("action") != "allow":
            warnings.append("macro_event_caution_reduced_signal")
        if execution_viability == "UNSAFE":
            blockers.append("execution_environment_not_safe")
        elif execution_viability == "UNKNOWN":
            warnings.append("execution_environment_unknown")
        blockers.extend(execution_cost_analysis.get("blockers") or [])
        warnings.extend(execution_cost_analysis.get("warnings") or [])
        blockers.extend(session_execution_analysis.get("blockers") or [])
        warnings.extend(session_execution_analysis.get("warnings") or [])
        blockers.extend(premium_discount_analysis.get("blockers") or [])
        warnings.extend(premium_discount_analysis.get("warnings") or [])
        if not direction_allowed:
            blockers.append("direction_consistency_not_valid")
        if zone_validity_score < self.thresholds.min_zone_validity:
            blockers.append("zone_invalid_or_expired")
        if trap_risk_score >= self.thresholds.max_trap_risk:
            blockers.append("trap_risk_too_high")
        if late_entry_risk >= self.thresholds.max_late_entry_risk:
            blockers.append("late_entry_risk_too_high")
        if signal is not None and liquidity_volume_trap["manipulation_risk_score"] >= 0.78:
            blockers.append("liquidity_trap_risk_too_high")
        if signal is not None and liquidity_volume_trap["volume_confirmation_score"] < 0.32 and liquidity_volume_trap["movement_quality_score"] < 0.42:
            blockers.append("volume_movement_not_confirmed")

        if pulse_score <= 50:
            warnings.append("market_pulse_requires_defense")
        if q_alignment < 0.45:
            warnings.append("q_learning_not_aligned")
        if continuation_probability < 0.45 and signal is not None:
            warnings.append("weak_continuation_probability")
        if liquidity_volume_trap["opposite_liquidity_sweep"]:
            warnings.append("possible_liquidity_trap_against_side")
        if liquidity_volume_trap["volume_confirmation_score"] < 0.45:
            warnings.append("volume_not_confirming")
        if liquidity_volume_trap["liquidity_readiness_score"] < 0.45:
            warnings.append("liquidity_not_ready")

        confirmation_awareness = self._confirmation_awareness(
            side=side,
            signal=signal,
            intelligence=intelligence,
            logical_sl=logical_sl,
            rr_evaluable=rr_evaluable,
            event_allow=event_allow,
            direction_allowed=direction_allowed,
            execution_viability=execution_viability,
            zone_validity_score=zone_validity_score,
            trap_risk_score=trap_risk_score,
            late_entry_risk=late_entry_risk,
            liquidity_volume_trap=liquidity_volume_trap,
            q_alignment=q_alignment,
            readiness_action=str(readiness.get("action") or "").upper(),
        )
        confirmation_awareness = self._apply_supervised_retest_awareness(
            signal=signal,
            awareness=confirmation_awareness,
            score=score,
            pulse_score=pulse_score,
            session_execution_analysis=session_execution_analysis,
            zone_validity_score=zone_validity_score,
            trap_risk_score=trap_risk_score,
            late_entry_risk=late_entry_risk,
            liquidity_volume_trap=liquidity_volume_trap,
            logical_sl=logical_sl,
            rr_evaluable=rr_evaluable,
            event_allow=event_allow,
            direction_allowed=direction_allowed,
            execution_viability=execution_viability,
        )
        if signal is not None:
            awareness_missing = set(confirmation_awareness.get("critical_missing") or [])
            if "clean_structure_trigger" in awareness_missing:
                blockers.append("clean_structure_trigger_missing")
            if "displacement_confirmation" in awareness_missing:
                blockers.append("displacement_confirmation_missing")
            if "entry_confirmation_consciousness" in awareness_missing:
                blockers.append("entry_confirmation_incomplete")

        awareness_allows_execute = bool(confirmation_awareness.get("execution_allowed_by_confirmation", False))
        blockers = self._dedupe(blockers)
        warnings = self._dedupe(warnings)
        armed_retest_execute_recovery = self._armed_retest_execute_recovery(
            signal=signal,
            score=score,
            pulse_score=pulse_score,
            awareness_allows_execute=awareness_allows_execute,
            blockers=blockers,
            trap_risk_score=trap_risk_score,
            late_entry_risk=late_entry_risk,
            zone_validity_score=zone_validity_score,
            liquidity_volume_trap=liquidity_volume_trap,
            execution_viability=execution_viability,
        )
        m1_micro_trigger_execute_recovery = self._m1_micro_trigger_execute_recovery(
            signal=signal,
            score=score,
            pulse_score=pulse_score,
            awareness_allows_execute=awareness_allows_execute,
            blockers=blockers,
            trap_risk_score=trap_risk_score,
            late_entry_risk=late_entry_risk,
            zone_validity_score=zone_validity_score,
            liquidity_volume_trap=liquidity_volume_trap,
            execution_viability=execution_viability,
            logical_sl=logical_sl,
            rr_evaluable=rr_evaluable,
        )
        supervised_v56_execute_recovery = self._supervised_v56_execute_recovery(
            signal=signal,
            score=score,
            dynamic_threshold=dynamic_threshold,
            readiness_action=str(readiness.get("action") or "").upper(),
            pulse_score=pulse_score,
            awareness=confirmation_awareness,
            blockers=blockers,
            trap_risk_score=trap_risk_score,
            late_entry_risk=late_entry_risk,
            zone_validity_score=zone_validity_score,
            liquidity_volume_trap=liquidity_volume_trap,
            logical_sl=logical_sl,
            rr_evaluable=rr_evaluable,
            event_allow=event_allow,
            direction_allowed=direction_allowed,
            execution_viability=execution_viability,
            q_alignment=q_alignment,
        )
        if blockers:
            decision = "BLOCK"
        elif (
            signal is not None
            and score >= dynamic_threshold["required_execute_score"]
            and readiness.get("action") == "EXECUTE"
            and awareness_allows_execute
        ):
            decision = "EXECUTE"
        elif armed_retest_execute_recovery["eligible"]:
            decision = "EXECUTE"
        elif m1_micro_trigger_execute_recovery["eligible"]:
            decision = "EXECUTE"
        elif supervised_v56_execute_recovery["eligible"]:
            decision = "EXECUTE"
        elif signal is not None and score >= self.thresholds.prepare_score:
            decision = "PREPARE"
        elif score >= self.thresholds.prepare_score:
            decision = "PREPARE"
        else:
            decision = "WAIT"

        return {
            "symbol": symbol,
            "side": side,
            "final_confirmation_score": score,
            "entry_timing_quality": self._quality_label(entry_timing_score),
            "entry_timing_score": round(entry_timing_score, 4),
            "trap_risk_score": round(trap_risk_score, 4),
            "late_entry_risk": round(late_entry_risk, 4),
            "zone_validity": self._quality_label(zone_validity_score),
            "zone_validity_score": round(zone_validity_score, 4),
            "continuation_probability": round(continuation_probability, 4),
            "reversal_probability": round(reversal_probability, 4),
            "required_execute_score": dynamic_threshold["required_execute_score"],
            "dynamic_threshold_analysis": dynamic_threshold,
            "execution_cost_analysis": execution_cost_analysis,
            "session_execution_analysis": session_execution_analysis,
            "premium_discount_analysis": premium_discount_analysis,
            "liquidity_volume_trap_analysis": liquidity_volume_trap,
            "confirmation_awareness": confirmation_awareness,
            "armed_retest_execute_recovery": armed_retest_execute_recovery,
            "m1_micro_trigger_execute_recovery": m1_micro_trigger_execute_recovery,
            "supervised_v56_execute_recovery": supervised_v56_execute_recovery,
            "decision": decision,
            "blockers": blockers,
            "warnings": warnings,
            "requires_signal": signal is None,
            "logical_sl": logical_sl,
            "rr_evaluable": rr_evaluable,
            "event_action": event_risk.get("action"),
            "execution_viability": execution_environment.get("execution_viability"),
            "q_learning_alignment": round(q_alignment, 4),
            "market_pulse_score": market_pulse.get("score"),
            "reason": self._reason(decision=decision, blockers=blockers, warnings=warnings, score=score, signal=signal),
        }

    @classmethod
    def _armed_retest_execute_recovery(
        cls,
        *,
        signal: dict[str, Any] | None,
        score: float,
        pulse_score: float,
        awareness_allows_execute: bool,
        blockers: list[str],
        trap_risk_score: float,
        late_entry_risk: float,
        zone_validity_score: float,
        liquidity_volume_trap: dict[str, Any],
        execution_viability: str,
    ) -> dict[str, Any]:
        if signal is None:
            return {"eligible": False, "reason": "no_signal"}
        signal_type = str(signal.get("signal_type") or signal.get("setup_type") or "").upper()
        if "ARMED_RETEST" not in signal_type:
            return {"eligible": False, "reason": "not_armed_retest_signal"}
        if blockers:
            return {"eligible": False, "reason": "blockers_active", "blockers": blockers}
        if not awareness_allows_execute:
            return {"eligible": False, "reason": "confirmation_awareness_not_complete"}
        if str(execution_viability).upper() != "SAFE":
            return {"eligible": False, "reason": "execution_environment_not_safe"}
        liquidity_score = cls._safe_float(liquidity_volume_trap.get("liquidity_readiness_score"))
        movement_score = cls._safe_float(liquidity_volume_trap.get("movement_quality_score"))
        volume_score = cls._safe_float(liquidity_volume_trap.get("volume_confirmation_score"))
        if (
            score < 66.0
            or pulse_score < 85.0
            or zone_validity_score < 0.5
            or trap_risk_score >= 0.55
            or late_entry_risk >= 0.55
            or max(liquidity_score, movement_score, volume_score) < 0.45
        ):
            return {
                "eligible": False,
                "reason": "armed_retest_recovery_thresholds_not_met",
                "thresholds": {
                    "min_score": 66.0,
                    "min_pulse": 85.0,
                    "min_zone_validity": 0.5,
                    "max_trap": 0.55,
                    "max_late": 0.55,
                    "min_liquidity_or_movement_or_volume": 0.45,
                },
            }
        return {
            "eligible": True,
            "reason": "armed_retest_reduced_signal_has_complete_confirmation",
            "execution_mode": "armed_retest_reduced_execute_recovery",
        }

    @staticmethod
    def _event_allows_final_confirmation(*, event_risk: dict[str, Any], signal: dict[str, Any] | None) -> bool:
        action = str(event_risk.get("action") or "unknown").lower()
        if action == "allow":
            return True
        if action == "watch":
            return True
        signal_type = str((signal or {}).get("signal_type") or "").upper()
        if signal_type != "M1_MICRO_TRIGGER_REDUCED_SIGNAL":
            return False
        active_events = event_risk.get("active_events") or []
        upcoming_events = event_risk.get("upcoming_events") or []
        highest_active = str(event_risk.get("highest_active_impact") or "").lower()
        if active_events or highest_active in {"high", "critical", "red"}:
            return False
        # A stale/empty calendar block is treated as caution for reduced demo
        # precision signals, not as a hard veto. Real high-impact events above
        # still block.
        if not active_events and not upcoming_events:
            return True
        return False

    @classmethod
    def _m1_micro_trigger_execute_recovery(
        cls,
        *,
        signal: dict[str, Any] | None,
        score: float,
        pulse_score: float,
        awareness_allows_execute: bool,
        blockers: list[str],
        trap_risk_score: float,
        late_entry_risk: float,
        zone_validity_score: float,
        liquidity_volume_trap: dict[str, Any],
        execution_viability: str,
        logical_sl: bool,
        rr_evaluable: bool,
    ) -> dict[str, Any]:
        if signal is None:
            return {"eligible": False, "reason": "no_signal"}
        signal_type = str(signal.get("signal_type") or signal.get("setup_type") or "").upper()
        if signal_type != "M1_MICRO_TRIGGER_REDUCED_SIGNAL":
            return {"eligible": False, "reason": "not_m1_micro_trigger_signal"}
        if blockers:
            return {"eligible": False, "reason": "blockers_active", "blockers": blockers}
        if not awareness_allows_execute:
            return {"eligible": False, "reason": "confirmation_awareness_not_complete"}
        if str(execution_viability).upper() != "SAFE":
            return {"eligible": False, "reason": "execution_environment_not_safe"}
        if not (logical_sl and rr_evaluable):
            return {"eligible": False, "reason": "risk_geometry_not_ready", "logical_sl": logical_sl, "rr_evaluable": rr_evaluable}
        liquidity_score = cls._safe_float(liquidity_volume_trap.get("liquidity_readiness_score"))
        movement_score = cls._safe_float(liquidity_volume_trap.get("movement_quality_score"))
        volume_score = cls._safe_float(liquidity_volume_trap.get("volume_confirmation_score"))
        if (
            score < 64.0
            or pulse_score < 82.0
            or zone_validity_score < 0.50
            or trap_risk_score >= 0.58
            or late_entry_risk >= 0.60
            or max(liquidity_score, movement_score, volume_score) < 0.42
        ):
            return {
                "eligible": False,
                "reason": "m1_micro_trigger_thresholds_not_met",
                "thresholds": {
                    "min_score": 64.0,
                    "min_pulse": 82.0,
                    "min_zone_validity": 0.50,
                    "max_trap": 0.58,
                    "max_late": 0.60,
                    "min_liquidity_or_movement_or_volume": 0.42,
                },
            }
        return {
            "eligible": True,
            "reason": "m1_micro_trigger_has_clear_zone_and_micro_confirmation",
            "execution_mode": "m1_micro_trigger_reduced_execute_recovery",
        }

    @classmethod
    def _supervised_v56_execute_recovery(
        cls,
        *,
        signal: dict[str, Any] | None,
        score: float,
        dynamic_threshold: dict[str, Any],
        readiness_action: str,
        pulse_score: float,
        awareness: dict[str, Any],
        blockers: list[str],
        trap_risk_score: float,
        late_entry_risk: float,
        zone_validity_score: float,
        liquidity_volume_trap: dict[str, Any],
        logical_sl: bool,
        rr_evaluable: bool,
        event_allow: bool,
        direction_allowed: bool,
        execution_viability: str,
        q_alignment: float,
    ) -> dict[str, Any]:
        """Recover statistically valid v56/AGG entries without weakening hard guards.

        The normal execute threshold remains the main path. This reduced recovery exists for
        the supervised 2025 v56 family, where backtest evidence showed profitable setups
        being blocked only because final confirmation stayed slightly below the global gate.
        """

        if signal is None:
            return {"eligible": False, "reason": "no_signal"}
        setup = str(signal.get("setup_type") or "").upper()
        signal_type = str(signal.get("signal_type") or "").upper()
        variant = str(signal.get("strategy_variant") or "").upper()
        regime = str(signal.get("market_regime") or signal.get("regime") or "").upper()
        resembles_v56 = (
            "V56" in variant
            or "V56" in setup
            or "V56" in signal_type
            or "AGG" in setup
            or "AGGRESSIVE" in signal_type
            or regime == "EXPANSION"
        )
        if not resembles_v56:
            return {"eligible": False, "reason": "not_supervised_v56_family"}
        if readiness_action != "EXECUTE":
            return {"eligible": False, "reason": "readiness_not_execute"}
        if blockers:
            return {"eligible": False, "reason": "blockers_active", "blockers": blockers}
        if not awareness.get("execution_allowed_by_confirmation", False):
            return {"eligible": False, "reason": "confirmation_awareness_not_complete"}
        if str(execution_viability).upper() != "SAFE":
            return {"eligible": False, "reason": "execution_environment_not_safe"}
        if not (logical_sl and rr_evaluable and event_allow and direction_allowed):
            return {
                "eligible": False,
                "reason": "hard_trade_safety_not_met",
                "logical_sl": logical_sl,
                "rr_evaluable": rr_evaluable,
                "event_allow": event_allow,
                "direction_allowed": direction_allowed,
            }
        recent_losses = int(cls._safe_float(dynamic_threshold.get("recent_similar_losses")))
        threshold_reasons = [str(item) for item in dynamic_threshold.get("reasons", []) or []]
        # Do not bypass Q-learning's textbook mode after a real similar-loss streak.
        if recent_losses >= 3 or "recent_similar_loss_streak_requires_textbook_confirmation" in threshold_reasons:
            return {"eligible": False, "reason": "dynamic_threshold_requires_textbook_confirmation"}

        thresholds = v56_thresholds()
        min_score = 55.0
        zone_floor = cls._safe_float(thresholds.get("zone_validity_floor")) / 100.0
        min_zone = max(0.45, min(0.58, zone_floor - 0.06 if zone_floor else 0.45))
        max_trap = max(0.50, min(0.62, cls._safe_float(thresholds.get("max_winner_trap_risk")) + 0.10))
        max_late = max(0.42, min(0.52, cls._safe_float(thresholds.get("max_winner_late_entry_risk")) + 0.08))
        liquidity_score = cls._safe_float(liquidity_volume_trap.get("liquidity_readiness_score"))
        movement_score = cls._safe_float(liquidity_volume_trap.get("movement_quality_score"))
        volume_score = cls._safe_float(liquidity_volume_trap.get("volume_confirmation_score"))
        if (
            score < min_score
            or pulse_score < 74.0
            or zone_validity_score < min_zone
            or trap_risk_score > max_trap
            or late_entry_risk > max_late
            or q_alignment < 0.22
            or max(liquidity_score, movement_score, volume_score) < 0.40
        ):
            return {
                "eligible": False,
                "reason": "supervised_v56_recovery_thresholds_not_met",
                "thresholds": {
                    "min_score": round(min_score, 2),
                    "min_pulse": 74.0,
                    "min_zone_validity": round(min_zone, 4),
                    "max_trap": round(max_trap, 4),
                    "max_late": round(max_late, 4),
                    "min_liquidity_or_movement_or_volume": 0.40,
                    "min_q_alignment": 0.22,
                },
            }
        return {
            "eligible": True,
            "reason": "supervised_v56_valid_setup_recovered_for_reduced_execute",
            "execution_mode": "supervised_v56_reduced_execute_recovery",
            "thresholds": {
                "min_score": round(min_score, 2),
                "min_pulse": 74.0,
                "min_zone_validity": round(min_zone, 4),
                "max_trap": round(max_trap, 4),
                "max_late": round(max_late, 4),
            },
        }

    def apply_execution_guard(
        self,
        *,
        execution_risk_decision: dict[str, Any],
        final_confirmation: dict[str, Any],
        signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        guarded = dict(execution_risk_decision)
        guarded["final_confirmation"] = final_confirmation
        guarded["final_confirmation_score"] = final_confirmation.get("final_confirmation_score")
        if signal is None or not guarded.get("can_execute"):
            return guarded
        awareness = final_confirmation.get("confirmation_awareness") or {}
        if awareness and not awareness.get("execution_allowed_by_confirmation", False):
            if awareness.get("recoverable_for_armed_retest"):
                guarded.update(
                    {
                        "can_execute": False,
                        "allowed_risk_mode": "blocked",
                        "max_risk_multiplier": 0.0,
                        "decision": "waiting_for_entry_confirmation_retest",
                        "execution_mode": "waiting_for_entry_confirmation_retest",
                        "execution_status": "waiting_for_entry_confirmation_retest",
                        "risk_application_reason": (
                            str(guarded.get("risk_application_reason") or "")
                            + " Confirmación incompleta pero recuperable: mantener ARMED_RETEST y esperar "
                            + "microestructura/desplazamiento limpio antes de ejecutar."
                        ).strip(),
                    }
                )
                return guarded
            guarded.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_entry_confirmation_awareness",
                    "execution_mode": "blocked_by_entry_confirmation_awareness",
                    "execution_status": "blocked_by_entry_confirmation_awareness",
                    "risk_application_reason": (
                        str(guarded.get("risk_application_reason") or "")
                        + " La IA no tiene todas las confirmaciones conscientes para ejecutar: "
                        + str(awareness.get("summary") or awareness.get("missing"))
                    ).strip(),
                }
            )
            return guarded
        if final_confirmation.get("decision") != "EXECUTE":
            guarded.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_final_confirmation",
                    "execution_mode": "blocked_by_final_confirmation",
                    "execution_status": "blocked_by_final_confirmation",
                    "risk_application_reason": (
                        str(guarded.get("risk_application_reason") or "")
                        + " FinalConfirmationEngine no autorizó EXECUTE: "
                        + str(final_confirmation.get("reason"))
                    ).strip(),
                }
            )
        return guarded

    @classmethod
    def _apply_supervised_retest_awareness(
        cls,
        *,
        signal: dict[str, Any] | None,
        awareness: dict[str, Any],
        score: float,
        pulse_score: float,
        session_execution_analysis: dict[str, Any],
        zone_validity_score: float,
        trap_risk_score: float,
        late_entry_risk: float,
        liquidity_volume_trap: dict[str, Any],
        logical_sl: bool,
        rr_evaluable: bool,
        event_allow: bool,
        direction_allowed: bool,
        execution_viability: str,
    ) -> dict[str, Any]:
        """Turn v56-like incomplete trigger gaps into ARMED_RETEST patience, not execution."""

        if signal is None:
            return awareness
        thresholds = v56_thresholds()
        setup = str(signal.get("setup_type") or signal.get("signal_type") or "").upper()
        variant = str(signal.get("strategy_variant") or "").upper()
        regime = str(signal.get("market_regime") or signal.get("regime") or "").upper()
        resembles_v56 = "V56" in variant or "V56" in setup or "AGG" in setup or regime == "EXPANSION"
        if not thresholds or not resembles_v56:
            return awareness

        critical_missing = [str(item) for item in awareness.get("critical_missing", []) or []]
        missing = [str(item) for item in awareness.get("missing", []) or []]
        missing_to_recover = critical_missing or missing
        recoverable_missing = {
            "clean_structure_trigger",
            "displacement_confirmation",
            "entry_confirmation_consciousness",
            "liquidity_context_ready",
            "volume_confirms",
            "q_learning_not_contradicting",
        }
        hard_missing = [item for item in missing_to_recover if item not in recoverable_missing]
        if not missing_to_recover or hard_missing:
            return awareness

        max_trap = float(thresholds.get("max_winner_trap_risk", 0.72))
        max_late = float(thresholds.get("max_winner_late_entry_risk", 0.72))
        zone_floor = float(thresholds.get("zone_validity_floor", 45.0)) / 100.0
        liquidity_or_flow = max(
            cls._safe_float(liquidity_volume_trap.get("liquidity_readiness_score")),
            cls._safe_float(liquidity_volume_trap.get("movement_quality_score")),
            cls._safe_float(liquidity_volume_trap.get("volume_confirmation_score")),
        )
        direct_reduced_execute = (
            score >= 60.0
            and pulse_score >= 80.0
            and str(session_execution_analysis.get("session_status") or session_execution_analysis.get("status") or "").lower()
            == "optimal_session"
            and zone_validity_score >= min(0.78, max(0.45, zone_floor))
            and trap_risk_score <= max_trap
            and late_entry_risk <= max_late
            and liquidity_or_flow >= 0.50
            and logical_sl
            and rr_evaluable
            and event_allow
            and direction_allowed
            and str(execution_viability).upper() == "SAFE"
        )
        if direct_reduced_execute:
            updated = dict(awareness)
            updated["original_critical_missing"] = critical_missing
            updated["original_missing"] = missing
            updated["critical_missing"] = []
            updated["missing"] = [item for item in missing if item not in recoverable_missing]
            updated["status"] = "SUPERVISED_REDUCED_EXECUTE_READY"
            updated["execution_allowed_by_confirmation"] = True
            updated["recoverable_for_armed_retest"] = False
            updated["supervised_v56_confirmation_recovery"] = {
                "eligible": True,
                "reason": (
                    "Setup v56/AGG calibrado: la falta de trigger micro queda compensada por "
                    "sesión óptima, flujo/liquidez suficiente, SL/RR lógico y confirmación reducida."
                ),
                "missing_recovered": missing_to_recover,
                "execution_mode": "supervised_v56_reduced_execute",
                "thresholds": {
                    "min_score": 60.0,
                    "min_pulse": 80.0,
                    "zone_floor": round(min(0.78, max(0.45, zone_floor)), 4),
                    "max_trap": max_trap,
                    "max_late": max_late,
                    "min_liquidity_or_flow": 0.50,
                },
            }
            updated["summary"] = (
                "Confirmación v56/AGG recuperada para ejecución reducida: "
                + ", ".join(missing_to_recover)
                + " se compensa con sesión, flujo, zona y riesgo válidos."
            )
            return updated
        if (
            score < 58.0
            or pulse_score < 80.0
            or zone_validity_score < min(0.78, max(0.45, zone_floor))
            or trap_risk_score > max_trap
            or late_entry_risk > max_late
            or not logical_sl
            or not rr_evaluable
            or not event_allow
            or not direction_allowed
            or str(execution_viability).upper() != "SAFE"
        ):
            return awareness

        updated = dict(awareness)
        updated["original_critical_missing"] = critical_missing
        updated["original_missing"] = missing
        updated["critical_missing"] = []
        updated["missing"] = [item for item in missing if item not in recoverable_missing]
        updated["status"] = "WAIT_RETEST_CONFIRMATION"
        updated["execution_allowed_by_confirmation"] = False
        updated["recoverable_for_armed_retest"] = True
        updated["supervised_v56_confirmation_recovery"] = {
            "eligible": True,
            "reason": (
                "Setup v56/AGG históricamente válido: no ejecutar todavía, pero mantener armado "
                "hasta que aparezca microestructura/desplazamiento limpio."
            ),
            "missing_to_recover": missing_to_recover,
            "thresholds": {
                "min_score": 58.0,
                "min_pulse": 80.0,
                "zone_floor": round(min(0.78, max(0.45, zone_floor)), 4),
                "max_trap": max_trap,
                "max_late": max_late,
            },
        }
        updated["summary"] = (
            "Confirmación incompleta recuperable para ARMED_RETEST: falta "
            + ", ".join(missing_to_recover)
            + ". No ejecutar hasta trigger limpio."
        )
        return updated

    def _confirmation_awareness(
        self,
        *,
        side: str,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        logical_sl: bool,
        rr_evaluable: bool,
        event_allow: bool,
        direction_allowed: bool,
        execution_viability: str,
        zone_validity_score: float,
        trap_risk_score: float,
        late_entry_risk: float,
        liquidity_volume_trap: dict[str, Any],
        q_alignment: float,
        readiness_action: str,
    ) -> dict[str, Any]:
        """Builds an explicit checklist of what the AI knows before execution."""

        movement_quality = self._safe_float(liquidity_volume_trap.get("movement_quality_score"))
        volume_score = self._safe_float(liquidity_volume_trap.get("volume_confirmation_score"))
        liquidity_score = self._safe_float(liquidity_volume_trap.get("liquidity_readiness_score"))
        manipulation_risk = self._safe_float(liquidity_volume_trap.get("manipulation_risk_score"))
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        market_clarity = market_state.get("market_clarity") or {}
        clarity_side = str(market_clarity.get("selected_side") or "").upper()
        entry_trigger_plan = market_state.get("entry_trigger_plan") or market_clarity.get("entry_trigger_plan") or {}
        signal_type = str((signal or {}).get("signal_type") or "").upper()
        learned_candidate = self._learned_reduced_candidate_for_side(intelligence=intelligence, side=side)
        micro_structure = bool(
            signal
            and (
                signal.get("micro_bos")
                or signal.get("micro_choch")
                or signal.get("choch")
                or signal.get("bos")
                or signal.get("structure_break")
                or learned_candidate.get("micro_bos")
                or learned_candidate.get("micro_choch")
                or learned_candidate.get("choch")
            )
        )
        learned_bias_trigger = bool(
            signal
            and (
                signal.get("manual_bias_confirmation")
                or signal.get("course_bias_confirmation")
                or signal.get("sensei_bias_confirmation")
                or learned_candidate.get("manual_bias_confirmation")
                or learned_candidate.get("course_bias_confirmation")
                or learned_candidate.get("sensei_bias_confirmation")
            )
        )
        liquidity_trigger = bool(
            liquidity_volume_trap.get("liquidity_sweep_detected")
            or (signal or {}).get("liquidity_sweep")
            or (signal or {}).get("sweep_confirmed")
            or learned_candidate.get("liquidity_sweep")
            or learned_candidate.get("sweep_confirmed")
            or learned_candidate.get("manual_bias_confirmation")
        )
        displacement_trigger = bool(
            self._safe_float((signal or {}).get("displacement_score")) >= 55.0
            or self._safe_float((signal or {}).get("continuation_momentum")) >= 0.55
            or self._safe_float(learned_candidate.get("displacement_score")) >= 55.0
            or self._safe_float(learned_candidate.get("continuation_momentum")) >= 0.55
            or learned_candidate.get("continuation_momentum") is True
            or movement_quality >= 0.55
        )
        clean_structure_trigger = bool(
            signal
            and (
                micro_structure
                or (learned_bias_trigger and displacement_trigger)
                or (liquidity_trigger and displacement_trigger)
                or ("SESSION_Q_LEARNING" in signal_type and displacement_trigger and liquidity_score >= 0.5)
            )
        )

        checks = {
            "side_defined": side in {"BUY", "SELL"},
            "signal_detected": signal is not None,
            "zone_valid": zone_validity_score >= self.thresholds.min_zone_validity,
            "timing_not_late": late_entry_risk < self.thresholds.max_late_entry_risk,
            "trap_risk_acceptable": trap_risk_score < self.thresholds.max_trap_risk and manipulation_risk < 0.78,
            "clean_structure_trigger": clean_structure_trigger,
            "liquidity_context_ready": liquidity_trigger or liquidity_score >= 0.55,
            "volume_confirms": volume_score >= 0.45,
            "displacement_confirmation": displacement_trigger,
            "q_learning_not_contradicting": q_alignment >= 0.45,
            "logical_stop_loss": logical_sl,
            "risk_reward_evaluable": rr_evaluable,
            "event_allows": event_allow,
            "execution_environment_safe": execution_viability == "SAFE",
            "direction_consistency_valid": direction_allowed,
        }
        required = list(checks.keys())
        confirmed = [key for key, passed in checks.items() if passed]
        missing = [key for key, passed in checks.items() if not passed]
        critical_keys = {
            "side_defined",
            "signal_detected",
            "zone_valid",
            "timing_not_late",
            "trap_risk_acceptable",
            "clean_structure_trigger",
            "displacement_confirmation",
            "logical_stop_loss",
            "risk_reward_evaluable",
            "event_allows",
            "execution_environment_safe",
            "direction_consistency_valid",
        }
        critical_missing = [key for key in missing if key in critical_keys]
        if signal is not None and len(missing) >= 5:
            critical_missing.append("entry_confirmation_consciousness")
        execution_allowed = signal is not None and not critical_missing and readiness_action == "EXECUTE"
        status = "READY_TO_EXECUTE" if execution_allowed else "WAIT_CONFIRMATIONS"
        if signal is None:
            status = "WAIT_SIGNAL"
        elif critical_missing:
            status = "BLOCK_INCOMPLETE_CONFIRMATION"

        if execution_allowed:
            summary = "Confirmaciones completas: estructura, desplazamiento, zona, SL/RR, evento y ambiente permiten ejecutar."
        else:
            summary = "Faltan confirmaciones antes de ejecutar: " + ", ".join(critical_missing or missing or ["none"])

        return {
            "status": status,
            "side": side,
            "market_clarity_side": clarity_side if clarity_side in {"BUY", "SELL"} else "NEUTRAL",
            "entry_trigger_plan": entry_trigger_plan,
            "required_confirmations": required,
            "confirmed": confirmed,
            "missing": missing,
            "critical_missing": critical_missing,
            "execution_allowed_by_confirmation": execution_allowed,
            "micro_structure_confirmed": micro_structure,
            "learned_bias_trigger": learned_bias_trigger,
            "liquidity_trigger": liquidity_trigger,
            "displacement_trigger": displacement_trigger,
            "volume_confirmation_score": round(volume_score, 4),
            "movement_quality_score": round(movement_quality, 4),
            "liquidity_readiness_score": round(liquidity_score, 4),
            "learned_reduced_candidate_used": bool(learned_candidate),
            "summary": summary,
        }

    @classmethod
    def _learned_reduced_candidate_for_side(cls, *, intelligence: dict[str, Any], side: str) -> dict[str, Any]:
        if side not in {"BUY", "SELL"}:
            return {}
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        families = market_state.get("ob_rejection_families") or {}
        candidates: list[dict[str, Any]] = []
        for key in ("manual_bias", "aggressive", "institutional"):
            node = families.get(key) if isinstance(families, dict) else None
            if not isinstance(node, dict):
                continue
            candidate = node.get("reduced_signal_candidate")
            if isinstance(candidate, dict):
                candidates.append(candidate)
            sensei = node.get("sensei_manual_bias")
            if isinstance(sensei, dict) and isinstance(sensei.get("reduced_signal_candidate"), dict):
                candidates.append(sensei["reduced_signal_candidate"])
        for candidate in candidates:
            candidate_side = str(candidate.get("direction") or candidate.get("side") or "").upper()
            if candidate_side != side:
                continue
            displacement = cls._safe_float(candidate.get("displacement_score"))
            if (
                candidate.get("manual_bias_confirmation")
                and (candidate.get("micro_bos") or candidate.get("micro_choch"))
                and displacement >= 55.0
            ):
                return candidate
        return {}

    @staticmethod
    def _entry_timing_score(
        *,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        market_pulse: dict[str, Any],
    ) -> float:
        if signal is None:
            return 0.48 if (market_pulse.get("score") or 0) >= 55 else 0.35
        continuation = FinalConfirmationEngine._safe_float(signal.get("continuation_momentum"))
        displacement = FinalConfirmationEngine._safe_float(signal.get("displacement_score"))
        micro_bos = bool(signal.get("micro_bos"))
        impulse = FinalConfirmationEngine._safe_float(market_state.get("impulse_score"))
        score = 0.42
        score += min(0.24, continuation * 0.24)
        score += min(0.18, displacement / 100.0 * 0.18)
        score += 0.12 if micro_bos else 0.0
        score += min(0.08, impulse * 0.08)
        return max(0.0, min(1.0, score))

    @staticmethod
    def _trap_risk_score(
        *,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        market_pulse: dict[str, Any],
        execution_environment: dict[str, Any],
        q_alignment: float,
        liquidity_volume_trap: dict[str, Any] | None = None,
    ) -> float:
        risk = 0.18
        regime = str(market_state.get("market_regime") or "").upper()
        if regime in {"CHOP", "RANGE_DEAD", "DEAD", "NEUTRAL"}:
            risk += 0.22
        if (market_pulse.get("score") or 0) <= 50:
            risk += 0.18
        if str(execution_environment.get("execution_viability") or "").upper() != "SAFE":
            risk += 0.20
        if q_alignment < 0.45:
            risk += 0.14
        if signal is not None and not signal.get("micro_bos") and not signal.get("countertrend_reversal_scalp"):
            risk += 0.10
        if liquidity_volume_trap:
            risk += max(0.0, FinalConfirmationEngine._safe_float(liquidity_volume_trap.get("manipulation_risk_score")) - 0.35) * 0.32
            if liquidity_volume_trap.get("opposite_liquidity_sweep"):
                risk += 0.12
        return max(0.0, min(1.0, risk))

    @staticmethod
    def _liquidity_volume_trap_analysis(
        *,
        side: str,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        market_pulse: dict[str, Any],
        snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        candles_by_tf = (snapshot or {}).get("candles") or {}
        timeframe = "M5" if candles_by_tf.get("M5") else "M1"
        candles = list(candles_by_tf.get(timeframe) or [])
        side = str(side or "NEUTRAL").upper()
        if len(candles) < 8:
            return {
                "status": "insufficient_candles",
                "timeframe": timeframe,
                "side": side,
                "liquidity_sweep_detected": False,
                "opposite_liquidity_sweep": False,
                "volume_confirmation_score": 0.5,
                "movement_quality_score": 0.5,
                "liquidity_readiness_score": 0.45,
                "manipulation_risk_score": 0.25,
                "volume_ratio": None,
                "body_ratio": None,
                "displacement_ratio": None,
                "reason": "No hay suficientes velas para auditar liquidez/volumen con confianza.",
            }

        last = candles[-1]
        history = candles[-21:-1] if len(candles) >= 22 else candles[:-1]
        high = FinalConfirmationEngine._safe_float(FinalConfirmationEngine._candle_value(last, "high"))
        low = FinalConfirmationEngine._safe_float(FinalConfirmationEngine._candle_value(last, "low"))
        open_ = FinalConfirmationEngine._safe_float(FinalConfirmationEngine._candle_value(last, "open"))
        close = FinalConfirmationEngine._safe_float(FinalConfirmationEngine._candle_value(last, "close"))
        volume = FinalConfirmationEngine._safe_float(
            FinalConfirmationEngine._candle_value(last, "volume")
            or FinalConfirmationEngine._candle_value(last, "tick_volume")
        )
        ranges = [
            max(
                0.0,
                FinalConfirmationEngine._safe_float(FinalConfirmationEngine._candle_value(item, "high"))
                - FinalConfirmationEngine._safe_float(FinalConfirmationEngine._candle_value(item, "low")),
            )
            for item in history
        ]
        volumes = [
            FinalConfirmationEngine._safe_float(
                FinalConfirmationEngine._candle_value(item, "volume")
                or FinalConfirmationEngine._candle_value(item, "tick_volume")
            )
            for item in history
            if FinalConfirmationEngine._safe_float(
                FinalConfirmationEngine._candle_value(item, "volume")
                or FinalConfirmationEngine._candle_value(item, "tick_volume")
            )
            > 0
        ]
        avg_range = sum(ranges) / len(ranges) if ranges else 0.0
        avg_volume = sum(volumes) / len(volumes) if volumes else 0.0
        previous_high = max(
            FinalConfirmationEngine._safe_float(FinalConfirmationEngine._candle_value(item, "high")) for item in history
        )
        previous_low = min(
            FinalConfirmationEngine._safe_float(FinalConfirmationEngine._candle_value(item, "low")) for item in history
        )
        candle_range = max(0.0, high - low)
        body = abs(close - open_)
        body_ratio = body / candle_range if candle_range > 0 else 0.0
        displacement_ratio = body / avg_range if avg_range > 0 else 0.0
        volume_ratio = volume / avg_volume if avg_volume > 0 and volume > 0 else 1.0
        close_location = (close - low) / candle_range if candle_range > 0 else 0.5
        bullish_intent = close > open_ and close_location >= 0.58
        bearish_intent = close < open_ and close_location <= 0.42
        buy_side_sweep = high > previous_high and close < previous_high
        sell_side_sweep = low < previous_low and close > previous_low
        sweep_with_side = (side == "BUY" and sell_side_sweep) or (side == "SELL" and buy_side_sweep)
        opposite_sweep = (side == "BUY" and buy_side_sweep and bearish_intent) or (side == "SELL" and sell_side_sweep and bullish_intent)

        volume_score = FinalConfirmationEngine._volume_score(volume_ratio)
        movement_quality = 0.22 + min(0.28, body_ratio * 0.28) + min(0.24, displacement_ratio / 1.6 * 0.24) + volume_score * 0.16
        if (side == "BUY" and bullish_intent) or (side == "SELL" and bearish_intent):
            movement_quality += 0.10
        if bool((signal or {}).get("micro_bos")):
            movement_quality += 0.06
        movement_quality = max(0.0, min(1.0, movement_quality))

        pulse_liquidity = FinalConfirmationEngine._safe_float((market_pulse.get("components") or {}).get("liquidity_sweep")) / 10.0
        signal_liquidity = bool((signal or {}).get("liquidity_sweep") or (signal or {}).get("manual_bias_confirmation"))
        liquidity_readiness = 0.34 + max(0.0, min(1.0, pulse_liquidity)) * 0.18
        if sweep_with_side:
            liquidity_readiness += 0.28
        if signal_liquidity:
            liquidity_readiness += 0.15
        if side in {"BUY", "SELL"} and str(market_state.get("higher_timeframe_bias") or "").upper() == side:
            liquidity_readiness += 0.05
        liquidity_readiness = max(0.0, min(1.0, liquidity_readiness))

        manipulation_risk = 0.18
        if opposite_sweep:
            manipulation_risk += 0.35
        if volume_ratio >= 1.5 and ((side == "BUY" and bearish_intent) or (side == "SELL" and bullish_intent)):
            manipulation_risk += 0.22
        if body_ratio < 0.28 and volume_ratio >= 1.35:
            manipulation_risk += 0.14
        if movement_quality < 0.42 and volume_score < 0.45:
            manipulation_risk += 0.12
        manipulation_risk = max(0.0, min(1.0, manipulation_risk))

        reason_parts = []
        if sweep_with_side:
            reason_parts.append("liquidez barrida a favor del lado esperado")
        if opposite_sweep:
            reason_parts.append("posible barrida/trampa contra el lado esperado")
        if volume_score >= 0.62:
            reason_parts.append("volumen acompaña el desplazamiento")
        elif volume_score < 0.45:
            reason_parts.append("volumen todavía no confirma")
        if movement_quality >= 0.65:
            reason_parts.append("movimiento con intención suficiente")
        elif movement_quality < 0.45:
            reason_parts.append("movimiento débil o absorbido")

        return {
            "status": "available",
            "timeframe": timeframe,
            "side": side,
            "liquidity_sweep_detected": sweep_with_side,
            "opposite_liquidity_sweep": opposite_sweep,
            "buy_side_sweep": buy_side_sweep,
            "sell_side_sweep": sell_side_sweep,
            "volume_confirmation_score": round(volume_score, 4),
            "movement_quality_score": round(movement_quality, 4),
            "liquidity_readiness_score": round(liquidity_readiness, 4),
            "manipulation_risk_score": round(manipulation_risk, 4),
            "volume_ratio": round(volume_ratio, 4),
            "body_ratio": round(body_ratio, 4),
            "displacement_ratio": round(displacement_ratio, 4),
            "close_location": round(close_location, 4),
            "reason": "; ".join(reason_parts) if reason_parts else "Lectura de liquidez/volumen neutral; esperar confirmación limpia.",
        }

    @staticmethod
    def _volume_score(volume_ratio: float) -> float:
        if volume_ratio >= 1.75:
            return 0.9
        if volume_ratio >= 1.25:
            return 0.74
        if volume_ratio >= 1.0:
            return 0.6
        if volume_ratio >= 0.75:
            return 0.45
        return 0.25

    @staticmethod
    def _candle_value(candle: Any, key: str) -> Any:
        if isinstance(candle, dict):
            return candle.get(key)
        return getattr(candle, key, None)

    @staticmethod
    def _late_entry_risk(*, signal: dict[str, Any] | None, market_state: dict[str, Any]) -> float:
        if signal is None:
            return 0.2
        entry = FinalConfirmationEngine._safe_float(signal.get("entry_price"))
        stop = FinalConfirmationEngine._safe_float(signal.get("stop_price"))
        current = FinalConfirmationEngine._safe_float(market_state.get("last_price") or market_state.get("current_price"))
        if entry <= 0 or stop <= 0 or current <= 0:
            return 0.28
        risk = abs(entry - stop)
        if risk <= 0:
            return 0.65
        side = str(signal.get("direction") or "").upper()
        favorable_move = current - entry if side == "BUY" else entry - current
        if favorable_move <= 0:
            return 0.22
        return max(0.0, min(1.0, favorable_move / max(risk, 0.00001)))

    @staticmethod
    def _zone_validity_score(
        *,
        active_watch: dict[str, Any] | None,
        watch_trigger: dict[str, Any],
        signal: dict[str, Any] | None,
    ) -> float:
        status = str((active_watch or {}).get("status") or "").upper()
        if status in {"CANCELLED", "EXPIRED", "BLOCKED"}:
            return 0.0
        if signal is not None:
            return 0.78 if signal.get("entry_price") and signal.get("stop_price") else 0.45
        missing = len(watch_trigger.get("missing_for_execute") or [])
        cancel_risks = len(watch_trigger.get("cancel_conditions") or [])
        base = 0.64
        base -= min(0.20, missing * 0.03)
        base -= min(0.10, cancel_risks * 0.01)
        return max(0.0, min(1.0, base))

    @staticmethod
    def _continuation_probability(
        *,
        side: str,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        market_pulse: dict[str, Any],
        q_alignment: float,
    ) -> float:
        htf = str(market_state.get("higher_timeframe_bias") or "").upper()
        pulse = max(0.0, min(1.0, FinalConfirmationEngine._safe_float(market_pulse.get("score")) / 100.0))
        continuation = FinalConfirmationEngine._safe_float((signal or {}).get("continuation_momentum"))
        score = 0.25 + pulse * 0.28 + q_alignment * 0.18 + continuation * 0.18
        if side in {"BUY", "SELL"} and htf in {side, "BOTH", "MIXED"}:
            score += 0.11
        elif htf in {"BUY", "SELL"} and htf != side:
            score -= 0.14
        return max(0.0, min(1.0, score))

    @staticmethod
    def _reversal_probability(
        *,
        side: str,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        q_alignment: float,
    ) -> float:
        htf = str(market_state.get("higher_timeframe_bias") or "").upper()
        score = 0.18
        if signal and signal.get("countertrend_reversal_scalp"):
            score += 0.40
        if htf in {"BUY", "SELL"} and side in {"BUY", "SELL"} and htf != side:
            score += 0.18
        if q_alignment >= 0.7:
            score += 0.12
        return max(0.0, min(1.0, score))

    @classmethod
    def _execution_cost_analysis(
        cls,
        *,
        symbol: str,
        execution_environment: dict[str, Any],
        market_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Vet execution cost against a p80 spread band when telemetry provides it."""

        spread = cls._first_float(
            execution_environment,
            market_state,
            keys=("live_spread", "spread_price", "spread", "current_spread"),
        )
        spread_p80 = cls._first_float(
            execution_environment,
            market_state,
            keys=(
                "spread_p80",
                "spread_percentile_80",
                "spread_percentile_p80",
                "p80_spread",
                "historical_spread_p80",
                "max_spread_p80",
            ),
        )
        if spread_p80 <= 0:
            spread_stats = execution_environment.get("spread_stats") or market_state.get("spread_stats") or {}
            spread_p80 = cls._safe_float(
                spread_stats.get("p80")
                or spread_stats.get("p80_spread")
                or spread_stats.get("percentile_80")
            )

        blockers: list[str] = []
        warnings: list[str] = []
        score_penalty = 0.0
        status = "unknown"
        if spread <= 0:
            warnings.append("spread_unavailable_for_p80_check")
            status = "spread_unavailable"
            score_penalty = 3.0
        elif spread_p80 <= 0:
            warnings.append("spread_p80_unavailable")
            status = "p80_unavailable"
            score_penalty = 0.0
        elif spread > spread_p80:
            blockers.append("spread_above_p80")
            status = "blocked_spread_above_p80"
            excess_ratio = min(2.0, (spread - spread_p80) / max(spread_p80, 0.00001))
            score_penalty = 10.0 + excess_ratio * 8.0
            logger.info(
                "Final confirmation delayed by spread P80 guard symbol=%s spread=%s p80=%s",
                symbol,
                spread,
                spread_p80,
            )
        elif spread_p80 > 0 and spread > spread_p80 * 0.9:
            warnings.append("spread_near_p80")
            status = "spread_near_p80"
            score_penalty = 4.0
        else:
            status = "spread_ok"

        return {
            "status": status,
            "symbol": symbol,
            "spread": round(spread, 6) if spread > 0 else None,
            "spread_p80": round(spread_p80, 6) if spread_p80 > 0 else None,
            "score_penalty": round(score_penalty, 2),
            "blockers": blockers,
            "warnings": warnings,
        }

    @classmethod
    def _session_execution_analysis(
        cls,
        *,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        execution_environment: dict[str, Any],
        snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Keep execution inside validated London/NY liquidity windows."""

        session = cls._session_label(market_state=market_state, execution_environment=execution_environment, snapshot=snapshot)
        server_time = cls._server_time(market_state=market_state, execution_environment=execution_environment, snapshot=snapshot)
        valid_sessions = {
            "london",
            "london_rd",
            "new_york",
            "new_york_rd",
            "ny",
            "ny_am",
            "ny_pm",
            "ny_rd",
            "pm_volatility_rd",
            "evening_volatility_rd",
            "asia_evening_rd",
        }
        blockers: list[str] = []
        warnings: list[str] = []
        score_penalty = 0.0
        normalized_session = session.lower()
        if normalized_session in valid_sessions:
            status = "optimal_session"
        elif normalized_session == "unknown":
            status = "session_unknown"
            warnings.append("session_unknown")
            score_penalty = 5.0
        else:
            status = "outside_optimal_session"
            warnings.append("outside_optimal_session")
            score_penalty = 14.0
            if signal is not None:
                blockers.append("outside_optimal_session")
                logger.info(
                    "Final confirmation blocked outside validated session session=%s server_time=%s",
                    session,
                    server_time or "unknown",
                )

        return {
            "status": status,
            "session": session,
            "server_time": server_time,
            "score_penalty": round(score_penalty, 2),
            "blockers": blockers,
            "warnings": warnings,
        }

    @classmethod
    def _premium_discount_analysis(
        cls,
        *,
        side: str,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Prevent FOMO entries by requiring BUY in discount or SELL in premium."""

        side = str(side or "NEUTRAL").upper()
        current = cls._safe_float(
            market_state.get("last_price")
            or market_state.get("current_price")
            or (signal or {}).get("entry_price")
        )
        candles = cls._analysis_candles(snapshot)
        high = max((cls._safe_float(cls._candle_value(item, "high")) for item in candles), default=0.0)
        low = min((cls._safe_float(cls._candle_value(item, "low")) for item in candles), default=0.0)
        operating_range = max(0.0, high - low)
        in_origin_zone = cls._price_in_origin_zone(current=current, market_state=market_state)

        blockers: list[str] = []
        warnings: list[str] = []
        score_penalty = 0.0
        position_in_range: float | None = None
        status = "unknown"
        if side not in {"BUY", "SELL"}:
            status = "side_not_directional"
        elif current <= 0:
            warnings.append("current_price_unavailable_for_premium_discount")
            status = "price_unavailable"
            score_penalty = 4.0
        elif not candles:
            status = "premium_discount_data_unavailable"
            warnings.append("premium_discount_data_unavailable")
            score_penalty = 0.0
        elif operating_range <= 0:
            status = "operating_range_unavailable"
            score_penalty = 8.0
            if signal is not None:
                blockers.append("operating_range_unavailable")
                logger.info("Final confirmation blocked: operating range unavailable for premium/discount validation.")
        else:
            position_in_range = max(0.0, min(1.0, (current - low) / operating_range))
            if side == "BUY":
                valid_location = position_in_range <= 0.55 or in_origin_zone
                severe_chase = position_in_range >= 0.72 and not in_origin_zone
                blocker = "buy_chasing_price"
            else:
                valid_location = position_in_range >= 0.45 or in_origin_zone
                severe_chase = position_in_range <= 0.28 and not in_origin_zone
                blocker = "sell_chasing_price"
            if valid_location:
                status = "valid_premium_discount_location"
            else:
                status = "poor_premium_discount_location"
                warnings.append(blocker)
                score_penalty = 9.0
            if signal is not None and severe_chase:
                blockers.append(blocker)
                status = "blocked_chasing_price"
                score_penalty = 18.0
                logger.info(
                    "Final confirmation blocked by premium/discount guard side=%s position_in_range=%.4f",
                    side,
                    position_in_range,
                )

        return {
            "status": status,
            "side": side,
            "current_price": round(current, 6) if current > 0 else None,
            "range_high": round(high, 6) if high > 0 else None,
            "range_low": round(low, 6) if low > 0 else None,
            "position_in_range": round(position_in_range, 4) if position_in_range is not None else None,
            "in_origin_zone": in_origin_zone,
            "score_penalty": round(score_penalty, 2),
            "blockers": blockers,
            "warnings": warnings,
        }

    @classmethod
    def _dynamic_execute_threshold(cls, *, q_learning_decision: dict[str, Any], q_alignment: float) -> dict[str, Any]:
        required = 72.0
        reasons: list[str] = []
        recent_losses = int(
            cls._safe_float(
                q_learning_decision.get("recent_similar_losses")
                or q_learning_decision.get("similar_context_recent_losses")
                or q_learning_decision.get("recent_loss_streak")
                or q_learning_decision.get("loss_streak")
            )
        )
        if recent_losses >= 3:
            required = 90.0
            reasons.append("recent_similar_loss_streak_requires_textbook_confirmation")
        elif q_alignment < 0.45:
            required = min(90.0, required + 8.0)
            reasons.append("q_learning_alignment_defensive")
        return {
            "required_execute_score": round(required, 2),
            "base_execute_score": 72.0,
            "recent_similar_losses": recent_losses,
            "q_alignment": round(q_alignment, 4),
            "reasons": reasons or ["base_threshold"],
        }

    @classmethod
    def _analysis_candles(cls, snapshot: dict[str, Any] | None) -> list[Any]:
        candles_by_tf = (snapshot or {}).get("candles") or {}
        for timeframe in ("M15", "M5", "M1"):
            candles = list(candles_by_tf.get(timeframe) or [])
            if len(candles) >= 3:
                return candles[-48:]
        return []

    @classmethod
    def _price_in_origin_zone(cls, *, current: float, market_state: dict[str, Any]) -> bool:
        if current <= 0:
            return False
        market_clarity = market_state.get("market_clarity") or {}
        zones = [
            market_clarity.get("expected_entry_zone"),
            market_clarity.get("zone"),
            market_state.get("expected_entry_zone"),
            market_state.get("active_zone"),
            market_state.get("order_block"),
            market_state.get("fair_value_gap"),
        ]
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            if zone.get("in_zone_now") is True:
                return True
            lower = cls._first_float(zone, keys=("low", "lower", "bottom", "min", "zone_low", "from_price"))
            upper = cls._first_float(zone, keys=("high", "upper", "top", "max", "zone_high", "to_price"))
            if lower and upper:
                low, high = sorted((lower, upper))
                if low <= current <= high:
                    return True
        return False

    @classmethod
    def _session_label(
        cls,
        *,
        market_state: dict[str, Any],
        execution_environment: dict[str, Any],
        snapshot: dict[str, Any] | None,
    ) -> str:
        for payload in (execution_environment, market_state, snapshot or {}):
            for key in ("session_rd",):
                value = payload.get(key) if isinstance(payload, dict) else None
                if value:
                    return str(value).lower()
        hour_rd = cls._first_present_float(execution_environment, market_state, snapshot or {}, keys=("hour_rd", "rd_hour"))
        if hour_rd is not None:
            rd_session = cls._rd_session_from_hour(hour_rd)
            if rd_session:
                return rd_session
            return "outside_validation_sessions"
        hour_ny = cls._first_present_float(execution_environment, market_state, snapshot or {}, keys=("hour_ny", "ny_hour"))
        if hour_ny is not None:
            if 8 <= hour_ny < 11.5:
                return "ny_rd"
            return "outside_validation_sessions"
        for payload in (execution_environment, market_state, snapshot or {}):
            for key in ("session_name", "session", "session_variant"):
                value = payload.get(key) if isinstance(payload, dict) else None
                if value:
                    return str(value).lower()
        tags = market_state.get("session_tags") or []
        if tags:
            return str(tags[0]).lower()
        return "unknown"

    @staticmethod
    def _rd_session_from_hour(hour_rd: float) -> str | None:
        if 3 <= hour_rd < 5:
            return "london_rd"
        if 8 <= hour_rd < 11.5:
            return "ny_rd"
        if 14 <= hour_rd < 16:
            return "pm_volatility_rd"
        if 20 <= hour_rd < 22:
            return "evening_volatility_rd"
        return None

    @classmethod
    def _server_time(
        cls,
        *,
        market_state: dict[str, Any],
        execution_environment: dict[str, Any],
        snapshot: dict[str, Any] | None,
    ) -> str | None:
        for payload in (execution_environment, market_state, snapshot or {}):
            if not isinstance(payload, dict):
                continue
            for key in ("server_time", "server_time_iso", "timestamp", "timestamp_utc", "time"):
                value = payload.get(key)
                if value:
                    if isinstance(value, datetime):
                        return value.isoformat()
                    return str(value)
        return None

    @classmethod
    def _first_float(cls, *payloads: dict[str, Any], keys: tuple[str, ...]) -> float:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key in keys:
                value = payload.get(key)
                if value is not None:
                    return cls._safe_float(value)
        return 0.0

    @classmethod
    def _first_present_float(cls, *payloads: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key in keys:
                if key in payload and payload.get(key) is not None:
                    return cls._safe_float(payload.get(key))
        return None

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
    def _quality_label(score: float) -> str:
        if score >= 0.75:
            return "strong"
        if score >= 0.55:
            return "acceptable"
        if score >= 0.35:
            return "weak"
        return "invalid"

    @staticmethod
    def _reason(*, decision: str, blockers: list[str], warnings: list[str], score: float, signal: dict[str, Any] | None) -> str:
        if blockers:
            return "Bloqueado por confirmación final: " + ", ".join(blockers)
        if decision == "EXECUTE":
            return f"Confirmación final válida con score {score}; señal, zona, pulso y riesgo pasan guardias."
        if decision == "PREPARE":
            return f"Idea preparada pero aún no autorizada a ejecutar; score {score}; warnings={warnings or ['none']}."
        if signal is None:
            return f"Sin señal final; mantener WATCH/observación hasta trigger. Score {score}."
        return f"Esperar mejor timing; score {score}; warnings={warnings or ['none']}."

    @staticmethod
    def _contains_truthy(payload: dict[str, Any], key: str) -> bool:
        text = str(payload).lower()
        return key.lower() in text and "true" in text

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_probability(value: Any) -> float:
        numeric = FinalConfirmationEngine._safe_float(value)
        if numeric > 1.0:
            numeric /= 100.0
        return max(0.0, min(1.0, numeric))
