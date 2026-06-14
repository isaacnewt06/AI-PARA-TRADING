"""Definitive execution confirmation engine - integrated signal, direction, volume and risk validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class DefinitiveConfirmationThresholds:
    """Unified thresholds from v56 calibration with optimized defaults."""
    execute_score: float = 72.0
    armed_retest_score: float = 71.0
    prepare_score: float = 50.0

    max_trap_risk: float = 0.4969
    max_late_entry_risk: float = 0.38
    min_zone_validity: float = 0.45

    min_volume_confirmation: float = 0.42
    min_movement_quality: float = 0.42
    min_liquidity_readiness: float = 0.40
    min_q_alignment: float = 0.22

    min_pulse_score: float = 74.0
    min_market_clarity: float = 70.0


class DefinitiveExecutionConfirmationEngine:
    """Integrated confirmation engine that validates AI decisions with clear signal, direction, volume and risk."""

    def __init__(self, thresholds: DefinitiveConfirmationThresholds | None = None) -> None:
        self.thresholds = thresholds or DefinitiveConfirmationThresholds()

    def evaluate(self, *, symbol: str, signal: dict[str, Any] | None, intelligence: dict[str, Any],
                 snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        """Evaluate all confirmation layers and return final execution decision."""
        overview = intelligence.get("overview", {}) or {}
        market_state = overview.get("market_state", {}) or {}
        readiness = intelligence.get("execution_readiness", {}) or {}
        event_risk = intelligence.get("event_risk", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        market_clarity = market_state.get("market_clarity") or {}

        side = self._determine_side(signal, market_state, watch_trigger, market_clarity)
        pulse_score = self._safe_float(market_state.get("pulse_score") or readiness.get("pulse_score"))
        clarity_score = self._safe_float(market_clarity.get("clarity_score") or market_state.get("clarity_score", 0))
        harmony_score = self._normalize(self._safe_float(market_state.get("harmony_score")))
        setup_maturity = self._safe_float(readiness.get("setup_maturity") or watch_trigger.get("setup_maturity"))

        volume_movement = self._volume_movement_validation(
            signal=signal,
            market_state=market_state,
            snapshot=snapshot,
        )

        risk_geometry = self._risk_geometry_validation(
            signal=signal,
            market_state=market_state,
        )

        direction_consistency = self._direction_consistency_validation(
            signal=signal,
            market_state=market_state,
        )

        timing_assessment = self._timing_assessment(
            signal=signal,
            market_state=market_state,
            pulse_score=pulse_score,
        )

        penalties: list[dict[str, Any]] = []
        score = self._calculate_base_score(
            pulse_score=pulse_score,
            clarity_score=clarity_score,
            harmony_score=harmony_score,
            setup_maturity=setup_maturity,
            volume_movement=volume_movement,
            risk_geometry=risk_geometry,
            direction_consistency=direction_consistency,
            timing_assessment=timing_assessment,
        )

        self._apply_penalties(
            penalties=penalties,
            signal=signal,
            event_risk=event_risk,
            risk_geometry=risk_geometry,
            timing_assessment=timing_assessment,
            volume_movement=volume_movement,
        )

        score = max(0.0, min(100.0, score - sum(p["penalty"] for p in penalties)))
        decision, blockers = self._make_decision(
            score=score,
            signal=signal,
            event_risk=event_risk,
            risk_geometry=risk_geometry,
            volume_movement=volume_movement,
            timing_assessment=timing_assessment,
            direction_consistency=direction_consistency,
        )

        return {
            "symbol": symbol,
            "side": side,
            "final_confirmation_score": round(score, 2),
            "pulse_score": pulse_score,
            "clarity_score": clarity_score,
            "harmony_score": harmony_score,
            "setup_maturity": setup_maturity,
            "volume_confirmation_score": volume_movement["volume_score"],
            "volume_movement_quality": volume_movement["movement_score"],
            "liquidity_readiness_score": volume_movement["liquidity_score"],
            "risk_geometry": risk_geometry,
            "direction_consistency": direction_consistency,
            "timing_assessment": timing_assessment,
            "penalties": penalties,
            "blockers": blockers,
            "decision": decision,
            "can_execute": decision == "EXECUTE",
            "should_arm_retest": 71.0 <= score < 72.0,
            "reason": self._build_reason(decision, score, blockers, penalties),
            "confirmation_checklist": {
                "signal_detected": signal is not None,
                "side_defined": side in {"BUY", "SELL"},
                "pulse_strong": pulse_score >= self.thresholds.min_pulse_score,
                "clarity_sufficient": clarity_score >= self.thresholds.min_market_clarity,
                "volume_confirmed": volume_movement["volume_score"] >= self.thresholds.min_volume_confirmation,
                "movement_quality": volume_movement["movement_score"] >= self.thresholds.min_movement_quality,
                "liquidity_ready": volume_movement["liquidity_score"] >= self.thresholds.min_liquidity_readiness,
                "sl_valid": risk_geometry["sl_valid"],
                "rr_evaluable": risk_geometry["rr_evaluable"],
                "event_allows": self._event_allows(event_risk),
            },
            "staged_exit_plan": self._calculate_staged_exit(signal=signal, side=side, risk_geometry=risk_geometry) if signal and decision == "EXECUTE" else None,
            "trap_analysis": self._analyze_trap_risks(signal=signal, market_state=market_state, volume_movement=volume_movement) if signal else None,
            "probability": self._assess_probability(signal=signal, intelligence=intelligence, score=score) if signal else None,
        }

    def _assess_probability(self, *, signal: dict[str, Any], intelligence: dict[str, Any], score: float) -> dict[str, Any]:
        """Assess win probability from historical pattern similarity."""
        from .probability_assessment import PatternProbabilityAssessor
        assessor = PatternProbabilityAssessor()
        return assessor.assess_probability(signal=signal, intelligence=intelligence)

    def _determine_side(self, signal: dict[str, Any] | None, market_state: dict[str, Any],
                        watch_trigger: dict[str, Any], market_clarity: dict[str, Any]) -> str:
        """Determine the trade side with priority: signal -> clarity -> preferred_side."""
        side = str((signal or {}).get("direction") or "").upper()
        if side in {"BUY", "SELL"}:
            return side
        clarity_side = str(market_clarity.get("selected_side") or "").upper()
        if clarity_side in {"BUY", "SELL"}:
            return clarity_side
        preferred = str(market_state.get("preferred_side") or "").upper()
        if preferred in {"BUY", "SELL"}:
            return preferred
        return str(watch_trigger.get("side", "NEUTRAL")).upper()

    def _volume_movement_validation(self, *, signal: dict[str, Any] | None,
                                     market_state: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
        """Validate volume and movement quality for the signal direction."""
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        institutional = ob_families.get("institutional", {}) or {}

        volume_score = 0.5
        movement_score = 0.5
        liquidity_score = 0.45
        manipulation_risk = 0.25

        if aggressive.get("active"):
            checks = aggressive.get("checks", {}) or {}
            if checks.get("strong_bullish_rejection") or checks.get("strong_bearish_rejection"):
                volume_score = max(volume_score, 0.65)
                movement_score = max(movement_score, 0.60)
            if checks.get("partial_bull_displacement") or checks.get("partial_bear_displacement"):
                movement_score = max(movement_score, 0.55)
            if checks.get("continuation_momentum_buy") or checks.get("continuation_momentum_sell"):
                movement_score = max(movement_score, 0.65)
            volume_score = max(volume_score, 0.55)
            liquidity_score = max(liquidity_score, 0.55)

        if institutional.get("active"):
            volume_score = max(volume_score, 0.60)
            movement_score = max(movement_score, 0.58)
            liquidity_score = max(liquidity_score, 0.50)

        if signal:
            disp_score = self._safe_float(signal.get("displacement_score", 0))
            cont_mom = self._safe_float(signal.get("continuation_momentum", 0))
            if disp_score >= 55:
                volume_score = max(volume_score, min(1.0, disp_score / 100.0))
                movement_score = max(movement_score, min(1.0, cont_mom))
            if signal.get("micro_bos") or signal.get("micro_choch"):
                liquidity_score = max(liquidity_score, 0.65)

        return {
            "volume_score": round(volume_score, 4),
            "movement_score": round(movement_score, 4),
            "liquidity_score": round(liquidity_score, 4),
            "manipulation_risk_score": round(manipulation_risk, 4),
            "status": "validated",
        }

    def _risk_geometry_validation(self, *, signal: dict[str, Any] | None,
                                   market_state: dict[str, Any]) -> dict[str, Any]:
        """Validate stop loss and risk-reward geometry."""
        sl_valid = False
        rr_evaluable = False
        sl_quality = 0.0
        tp_quality = 0.0

        if signal:
            stop_price = signal.get("stop_price")
            target_price = signal.get("target_price")
            entry_price = signal.get("entry_price")
            sl_valid = bool(stop_price and entry_price)
            rr = signal.get("selected_rr", 0)
            if rr and rr > 0:
                rr_evaluable = True
                sl_quality = min(1.0, rr / 3.0) * 0.55
                tp_quality = min(1.0, rr / 2.0) * 0.45
                sl_quality = max(sl_quality, 0.65)

        return {
            "sl_valid": sl_valid,
            "rr_evaluable": rr_evaluable,
            "sl_quality": round(sl_quality, 4),
            "tp_quality": round(tp_quality, 4),
        }

    def _direction_consistency_validation(self, *, signal: dict[str, Any] | None,
                                           market_state: dict[str, Any]) -> dict[str, Any]:
        """Validate direction consistency across timeframes."""
        timeframe_alignment = market_state.get("timeframe_alignment", {}) or {}
        daily_bias = str(market_state.get("daily_bias", "NEUTRAL")).upper()
        macro_bias = str(market_state.get("macro_bias", "NEUTRAL")).upper()
        trend_bias = str(market_state.get("trend_bias", "NEUTRAL")).upper()

        side = str((signal or {}).get("direction", "NEUTRAL")).upper()
        weights = {"D1": 2.0, "H4": 1.6, "H1": 1.2, "M15": 0.8, "M5": 0.6}
        scores = {"BUY": 0.0, "SELL": 0.0}
        for tf, bias in [("D1", daily_bias), ("H4", macro_bias), ("H1", trend_bias)]:
            if bias in scores:
                scores[bias] += weights.get(tf, 0.6)

        align_score = max(scores["BUY"], scores["SELL"]) / sum(weights.values()) if any(scores.values()) else 0.0
        dominant = "BUY" if scores["BUY"] > scores["SELL"] else "SELL" if scores["SELL"] > scores["BUY"] else "NEUTRAL"
        consistent = side == dominant or (side in {"BUY", "SELL"} and dominant == "NEUTRAL")

        return {
            "aligned": consistent,
            "alignment_score": round(align_score, 4),
            "dominant_side": dominant,
            "signal_side": side,
        }

    def _timing_assessment(self, *, signal: dict[str, Any] | None,
                            market_state: dict[str, Any], pulse_score: float) -> dict[str, Any]:
        """Assess entry timing quality."""
        late_entry_risk = 0.0
        trap_risk = 0.0
        zone_validity = 0.5

        impulse_score = self._safe_float(market_state.get("impulse_score", 0))
        atr_ratio = self._safe_float(market_state.get("atr_ratio", 1.0))
        range_ratio = self._safe_float(market_state.get("range_ratio", 1.0))

        if pulse_score < 50:
            late_entry_risk = max(late_entry_risk, 0.45)
        if impulse_score < 50:
            trap_risk = max(trap_risk, 0.35)

        zone_validity = min(1.0, (pulse_score + impulse_score + atr_ratio * 20) / 300.0)

        return {
            "late_entry_risk": round(late_entry_risk, 4),
            "trap_risk": round(trap_risk, 4),
            "zone_validity": round(zone_validity, 4),
            "optimal_timing": pulse_score >= 74.0 and impulse_score >= 60,
        }

    def _calculate_base_score(self, *, pulse_score: float, clarity_score: float, harmony_score: float,
                               setup_maturity: float, volume_movement: dict[str, Any],
                               risk_geometry: dict[str, Any], direction_consistency: dict[str, Any],
                               timing_assessment: dict[str, Any]) -> float:
        """Calculate the weighted confirmation score."""
        score = (
            pulse_score * 0.25 +
            clarity_score * 0.20 +
            harmony_score * 100 * 0.15 +
            setup_maturity * 0.15 +
            volume_movement["volume_score"] * 100 * 0.10 +
            volume_movement["movement_score"] * 100 * 0.08 +
            volume_movement["liquidity_score"] * 100 * 0.07 +
            risk_geometry["sl_quality"] * 100 * 0.02 +
            direction_consistency["alignment_score"] * 100 * 0.03
        )
        return round(max(0.0, min(100.0, score)), 2)

    def _apply_penalties(self, *, penalties: list[dict[str, Any]], signal: dict[str, Any] | None,
                          event_risk: dict[str, Any], risk_geometry: dict[str, Any],
                          timing_assessment: dict[str, Any], volume_movement: dict[str, Any]) -> None:
        """Apply penalties for missing confirmation elements."""
        if event_risk.get("action") == "block":
            penalties.append({"reason": "macro_event_block", "penalty": 35.0})

        late_risk = timing_assessment.get("late_entry_risk", 0)
        trap_risk = timing_assessment.get("trap_risk", 0)
        if late_risk >= self.thresholds.max_late_entry_risk:
            penalties.append({"reason": "late_entry_risk_high", "penalty": 16.0})
        if trap_risk >= self.thresholds.max_trap_risk:
            penalties.append({"reason": "trap_risk_high", "penalty": 12.0})

        vol_score = volume_movement["volume_score"]
        mov_score = volume_movement["movement_score"]
        liq_score = volume_movement["liquidity_score"]
        if max(vol_score, mov_score, liq_score) < 0.35:
            penalties.append({"reason": "volume_movement_insufficient", "penalty": 14.0})

        if not risk_geometry["sl_valid"]:
            penalties.append({"reason": "no_logical_stop_loss", "penalty": 20.0})
        if signal and not risk_geometry["rr_evaluable"]:
            penalties.append({"reason": "rr_not_evaluable", "penalty": 12.0})

    def _event_allows(self, event_risk: dict[str, Any]) -> bool:
        action = str(event_risk.get("action") or "allow").lower()
        return action in {"allow", "watch"}

    def _make_decision(self, *, score: float, signal: dict[str, Any] | None,
                        event_risk: dict[str, Any], risk_geometry: dict[str, Any],
                        volume_movement: dict[str, Any], timing_assessment: dict[str, Any],
                        direction_consistency: dict[str, Any]) -> tuple[str, list[str]]:
        """Make final execution decision."""
        blockers: list[str] = []

        if event_risk.get("action") == "block":
            blockers.append("macro_event_block")

        if not risk_geometry["sl_valid"] and signal is not None:
            blockers.append("no_logical_stop_loss")

        if signal is None:
            if score >= self.thresholds.prepare_score:
                return "PREPARE", blockers
            return "WAIT", blockers + ["no_signal"]

        vol_score = volume_movement["volume_score"]
        mov_score = volume_movement["movement_score"]
        liq_score = volume_movement["liquidity_score"]

        if score >= self.thresholds.execute_score:
            if self._event_allows(event_risk) and risk_geometry["sl_valid"] and vol_score >= 0.42:
                return "EXECUTE", blockers
            if self.thresholds.armed_retest_score <= score < self.thresholds.execute_score:
                blockers.append("score_below_execute_threshold")

        if score >= self.thresholds.armed_retest_score:
            return "ARMED_RETEST", blockers

        if score >= self.thresholds.prepare_score:
            return "PREPARE", blockers

        return "WAIT", blockers + ["score_below_prepare"]

    def _build_reason(self, decision: str, score: float, blockers: list[str], penalties: list[dict[str, Any]]) -> str:
        if decision == "EXECUTE":
            return f"EXECUTE: score={score}. Confirmaciones completas validadas."
        if blockers:
            return f"{decision}: score={score}. Blockers: {', '.join(blockers[:3])}."
        if penalties:
            top = ", ".join(p["reason"] for p in penalties[:2])
            return f"{decision}: score={score}. Penalizaciones: {top}."
        return f"{decision}: score={score}. Esperando confirmaciones adicionales."

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize(value: float) -> float:
        return max(0.0, min(1.0, value))

    def _calculate_staged_exit(self, *, signal: dict[str, Any], side: str,
                                  risk_geometry: dict[str, Any]) -> dict[str, Any]:
        """Calculate staged profit taking levels."""
        entry = self._safe_float(signal.get("entry_price", 0))
        stop = self._safe_float(signal.get("stop_price", 0))
        target = self._safe_float(signal.get("target_price", 0))
        rr = self._safe_float(signal.get("selected_rr", 1.5))

        risk_per_unit = abs(entry - stop) if entry and stop else 1.0
        reward_per_unit = abs(target - entry) if target and entry else risk_per_unit * rr

        # Optimal RR based on signal quality
        optimal_rr = min(3.0, max(1.5, reward_per_unit / risk_per_unit)) if risk_per_unit > 0 else 1.5

        levels = []
        if side == "BUY":
            levels = [
                {"level": "0.5R", "price": round(entry + risk_per_unit * 0.5, 3), "close_fraction": 0.3, "reason": "Quick profit lock"},
                {"level": "0.7R", "price": round(entry + risk_per_unit * optimal_rr * 0.7, 3), "close_fraction": 0.4, "reason": "Runner portion"},
                {"level": "1.0R", "price": round(target, 3), "close_fraction": 0.3, "reason": "Full target"},
            ]
        else:
            levels = [
                {"level": "0.5R", "price": round(entry - risk_per_unit * 0.5, 3), "close_fraction": 0.3, "reason": "Quick profit lock"},
                {"level": "0.7R", "price": round(entry - risk_per_unit * optimal_rr * 0.7, 3), "close_fraction": 0.4, "reason": "Runner portion"},
                {"level": "1.0R", "price": round(target, 3), "close_fraction": 0.3, "reason": "Full target"},
            ]

        return {
            "staged_levels": levels,
            "initial_rr": round(optimal_rr, 2),
            "risk_per_unit": round(risk_per_unit, 5),
            "reward_per_unit": round(reward_per_unit, 5),
            "trailing_start_r": 0.5,
            "trail_increment": 0.25,
        }

    def _analyze_trap_risks(self, *, signal: dict[str, Any], market_state: dict[str, Any],
                             volume_movement: dict[str, Any]) -> dict[str, Any]:
        """Analyze potential trap risks in the signal."""
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        institutional = ob_families.get("institutional", {}) or {}

        trap_risks = []
        warnings = []

        # Check volume/movement consistency
        vol_score = volume_movement["volume_score"]
        mov_score = volume_movement["movement_score"]
        if vol_score < 0.42 and mov_score < 0.42:
            trap_risks.append("low_volume_low_movement")

        # Check if institutional contradicts aggressive
        if aggressive.get("active") and institutional.get("active"):
            agg_side = str(aggressive.get("side", "")).upper()
            inst_side = str(institutional.get("side", "")).upper()
            if agg_side != inst_side and agg_side in {"BUY", "SELL"} and inst_side in {"BUY", "SELL"}:
                trap_risks.append("institutional_aggresive_conflict")

        # Check trap risk score from timing
        trap_score = volume_movement.get("manipulation_risk_score", 0)
        if trap_score > 0.5:
            warnings.append(f"manipulation_risk_detected_{round(trap_score, 2)}")

        return {
            "trap_detected": bool(trap_risks),
            "trap_risks": trap_risks,
            "warnings": warnings,
            "liquidity_sweep_active": aggressive.get("checks", {}).get("supply_demand_sweep_executed", False),
            "safe_zone_valid": signal.get("stop_price") is not None and signal.get("target_price") is not None,
        }