"""Persistent ARMED_RETEST state for MAXIMO demo trading."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class ArmedRetestEngine:
    """Keep a high-quality idea armed while waiting for a cleaner retest."""

    HISTORY_EVENTS = {
        "ARMED_RETEST_CREATED",
        "ARMED_RETEST_WAIT",
        "ARMED_RETEST_EXECUTE_READY",
        "ARMED_RETEST_DROP",
        "ARMED_RETEST_EXPIRED",
    }

    def __init__(
        self,
        *,
        state_path: Path,
        history_path: Path,
        expiration_candles: int = 8,
        expiration_minutes: int = 45,
    ) -> None:
        self.state_path = state_path
        self.history_path = history_path
        self.expiration_candles = expiration_candles
        self.expiration_minutes = expiration_minutes
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.touch(exist_ok=True)

    def evaluate(
        self,
        *,
        symbol: str,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        final_confirmation: dict[str, Any],
        market_pulse: dict[str, Any],
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        q_learning_decision: dict[str, Any],
        execution_environment: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        state = self._load_state()
        side = self._side(signal=signal, intelligence=intelligence, active_watch=active_watch, final_confirmation=final_confirmation)
        final_score = self._safe_float(final_confirmation.get("final_confirmation_score"))
        pulse_score = self._safe_float(market_pulse.get("score"))
        readiness_score = self._safe_float(execution_readiness.get("execution_readiness_score"))
        entry_score = self._safe_float(entry_quality.get("entry_quality_score"))
        critical_blocks = self._critical_blocks(
            final_confirmation=final_confirmation,
            execution_risk_decision=execution_risk_decision,
            execution_environment=execution_environment,
            intelligence=intelligence,
        )

        if state and state.get("symbol") == symbol:
            age_candles = int(state.get("age_candles") or 0) + 1
            state["age_candles"] = age_candles
            state["last_seen_at"] = now.isoformat()
            state["current_final_confirmation_score"] = final_score
            state["current_execution_readiness_score"] = readiness_score
            state["current_entry_quality_score"] = entry_score
            state["current_market_pulse_score"] = pulse_score
            if self._is_expired(state=state, now=now):
                return self._transition(state, "ARMED_RETEST_EXPIRED", "La idea expiró por tiempo/velas sin trigger limpio.")
            if side in {"BUY", "SELL"} and state.get("side") in {"BUY", "SELL"} and side != state.get("side"):
                return self._transition(state, "ARMED_RETEST_DROP", f"Cambió el lado esperado de {state.get('side')} a {side}.")
            if critical_blocks:
                return self._transition(state, "ARMED_RETEST_DROP", "Bloqueo crítico mientras esperaba retest: " + ", ".join(critical_blocks))
            if self._execute_ready(
                final_score=final_score,
                final_confirmation=final_confirmation,
                readiness_score=readiness_score,
                entry_score=entry_score,
                entry_quality=entry_quality,
                execution_risk_decision=execution_risk_decision,
            ):
                state["status"] = "EXECUTE_READY"
                state["action"] = "ARMED_RETEST_EXECUTE_READY"
                state["reason"] = "Retest/timing listo: confirmación, readiness y entry quality superaron umbral."
                self._save_state(state)
                self._append_event(state, "ARMED_RETEST_EXECUTE_READY", state["reason"])
                return self._result(state)
            state["status"] = "ACTIVE"
            state["action"] = "ARMED_RETEST_WAIT"
            state["reason"] = self._wait_reason(final_score=final_score, readiness_score=readiness_score, entry_score=entry_score)
            self._save_state(state)
            self._append_if_changed(state, "ARMED_RETEST_WAIT", state["reason"])
            return self._result(state)

        can_arm, arm_reason = self._can_arm(
            side=side,
            final_score=final_score,
            final_confirmation=final_confirmation,
            pulse_score=pulse_score,
            execution_readiness=execution_readiness,
            entry_quality=entry_quality,
            critical_blocks=critical_blocks,
            q_learning_decision=q_learning_decision,
            intelligence=intelligence,
            execution_environment=execution_environment,
            execution_risk_decision=execution_risk_decision,
        )
        if not can_arm:
            return {
                "status": "INACTIVE",
                "action": "ARMED_RETEST_DROP",
                "side": side,
                "reason": arm_reason,
                "history_path": str(self.history_path.resolve()),
            }

        new_state = self._build_state(
            symbol=symbol,
            side=side,
            signal=signal,
            intelligence=intelligence,
            active_watch=active_watch,
            final_confirmation=final_confirmation,
            market_pulse=market_pulse,
            execution_readiness=execution_readiness,
            entry_quality=entry_quality,
            execution_risk_decision=execution_risk_decision,
            snapshot=snapshot,
            created_at=now,
            reason=arm_reason,
        )
        if self._execute_ready(
            final_score=final_score,
            final_confirmation=final_confirmation,
            readiness_score=readiness_score,
            entry_score=entry_score,
            entry_quality=entry_quality,
            execution_risk_decision=execution_risk_decision,
        ):
            new_state["status"] = "EXECUTE_READY"
            new_state["action"] = "ARMED_RETEST_EXECUTE_READY"
            new_state["reason"] = "Retest reducido listo desde creación: FinalConfirmation autorizó EXECUTE con entrada limpia."
            self._save_state(new_state)
            self._append_event(new_state, "ARMED_RETEST_EXECUTE_READY", new_state["reason"])
            return self._result(new_state)
        self._save_state(new_state)
        self._append_event(new_state, "ARMED_RETEST_CREATED", arm_reason)
        return self._result(new_state)

    def build_reduced_signal_candidate(
        self,
        *,
        symbol: str,
        snapshot: dict[str, Any],
        market_pulse: dict[str, Any],
        intelligence: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Materialize an armed retest into a reduced candidate when price returns to the zone.

        This does not approve execution by itself.  The demo engine still sends the
        candidate through FinalConfirmation, EntryQuality, ExecutionReadiness,
        risk binding, macro/spread guards and MT5 validation.
        """
        state = self._load_state()
        if not state or state.get("symbol") != symbol:
            return None
        if self._is_expired(state=state, now=datetime.now(timezone.utc)):
            return None
        side = str(state.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            return None
        pulse_score = self._safe_float(market_pulse.get("score"))
        if pulse_score < 85.0:
            return None
        event_action = (intelligence.get("event_risk") or {}).get("action")
        if event_action not in {None, "allow"}:
            return None
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        market_clarity = market_state.get("market_clarity") or {}
        expected_zone = market_state.get("expected_entry_zone") or market_clarity.get("expected_entry_zone") or {}
        preferred_side = str(market_state.get("preferred_side") or "").upper()
        if preferred_side in {"BUY", "SELL"} and preferred_side != side:
            self._remember_materialization_block(state, "preferred_side_changed", {"preferred_side": preferred_side})
            return None

        current_price = self._latest_price(snapshot)
        if current_price <= 0:
            self._remember_materialization_block(state, "missing_current_price", {})
            return None
        zone = state.get("target_retest_zone") or {}
        lower = self._safe_float(zone.get("lower"))
        upper = self._safe_float(zone.get("upper"))
        entry = self._safe_float(state.get("ideal_entry_price")) or current_price
        stop = self._safe_float(state.get("compact_sl_expected"))
        target = self._safe_float(state.get("tp_estimated"))
        if lower <= 0 or upper <= 0 or stop <= 0 or target <= 0:
            self._remember_materialization_block(
                state,
                "invalid_prepared_geometry",
                {"lower": lower, "upper": upper, "stop": stop, "target": target},
            )
            return None
        risk = abs(entry - stop)
        if risk <= 0:
            self._remember_materialization_block(state, "invalid_risk_geometry", {"entry": entry, "stop": stop})
            return None
        if not self._directional_geometry_alive(side=side, current_price=current_price, stop=stop, target=target):
            self._remember_materialization_block(
                state,
                "directional_geometry_invalid_or_already_broken",
                {"side": side, "current_price": round(current_price, 5), "stop": stop, "target": target},
            )
            return None
        broken_context_price = self._broken_context_price(
            side=side,
            stop=stop,
            target=target,
            market_state=market_state,
            market_clarity=market_clarity,
            expected_zone=expected_zone,
        )
        if broken_context_price is not None:
            self._remember_materialization_block(
                state,
                "context_price_geometry_invalid_or_already_broken",
                {
                    "side": side,
                    "context_price": round(broken_context_price, 5),
                    "signal_price": round(current_price, 5),
                    "stop": stop,
                    "target": target,
                },
            )
            return None
        tolerance = max(risk * 0.15, 0.35)
        in_retest_zone = lower - tolerance <= current_price <= upper + tolerance
        selected_rr = abs(target - current_price) / abs(current_price - stop) if current_price != stop else 0.0
        in_expected_market_zone = expected_zone.get("in_zone_now") is True
        continuation_follow_through = self._continuation_follow_through_allowed(
            side=side,
            current_price=current_price,
            entry=entry,
            stop=stop,
            target=target,
            selected_rr=selected_rr,
            state=state,
            pulse_score=pulse_score,
        )
        if not in_retest_zone and not in_expected_market_zone and not continuation_follow_through["allowed"]:
            self._remember_materialization_block(
                state,
                str(continuation_follow_through.get("reason") or "not_in_retest_zone"),
                {
                    "current_price": round(current_price, 5),
                    "zone_lower": lower,
                    "zone_upper": upper,
                    "selected_rr": round(selected_rr, 4),
                    "in_expected_market_zone": in_expected_market_zone,
                },
            )
            return None
        minimum_rr = 1.0 if in_retest_zone or in_expected_market_zone else 1.15
        if selected_rr < minimum_rr:
            self._remember_materialization_block(
                state,
                "rr_not_enough_for_materialization",
                {"selected_rr": round(selected_rr, 4), "minimum_rr": minimum_rr},
            )
            return None
        signal_type = (
            "ARMED_RETEST_REDUCED_SIGNAL"
            if in_retest_zone or in_expected_market_zone
            else "ARMED_RETEST_CONTINUATION_REDUCED_SIGNAL"
        )
        setup_type = (
            "ARMED_RETEST_REDUCED"
            if in_retest_zone or in_expected_market_zone
            else "ARMED_RETEST_CONTINUATION_REDUCED"
        )
        materialization = (
            "retest_zone"
            if in_retest_zone
            else "market_expected_zone"
            if in_expected_market_zone
            else "continuation_follow_through"
        )

        return {
            "entry_kind": "market",
            "symbol": symbol,
            "timeframe": "M5",
            "signal_time": self._latest_candle_time(snapshot),
            "entry_time": self._latest_candle_time(snapshot),
            "direction": side.lower(),
            "setup_type": setup_type,
            "signal_type": signal_type,
            "active_family": "ARMED_RETEST",
            "entry_price": round(current_price, 5),
            "stop_price": round(stop, 5),
            "target_price": round(target, 5),
            "risk_per_unit": round(abs(current_price - stop), 5),
            "selected_rr": round(selected_rr, 4),
            "confidence": round(max(75.0, min(95.0, pulse_score * 0.55 + self._safe_float(state.get("current_final_confirmation_score")) * 0.45)), 2),
            "risk_mode": "reduced",
            "preferred_side": side,
            "armed_retest_state": {
                "created_at": state.get("created_at"),
                "age_candles": state.get("age_candles"),
                "target_retest_zone": state.get("target_retest_zone"),
                "patience_score": state.get("patience_score"),
                "reason": state.get("reason"),
                "materialization": materialization,
                "continuation_follow_through": continuation_follow_through,
            },
            "reduced_signal_reason": (
                "ARMED_RETEST encontró retest/continuación válida desde la zona preparada; "
                "la ejecución queda sujeta a confirmación final, EntryQuality, "
                "ExecutionReadiness y guards de MT5."
            ),
            "manual_bias_confirmation": True,
            "micro_bos": True,
            "continuation_momentum": True,
        }

    @classmethod
    def _continuation_follow_through_allowed(
        cls,
        *,
        side: str,
        current_price: float,
        entry: float,
        stop: float,
        target: float,
        selected_rr: float,
        state: dict[str, Any],
        pulse_score: float,
    ) -> dict[str, Any]:
        """Allow ARMED_RETEST to catch a clean continuation without chasing.

        Some institutional moves retest shallowly and then continue.  This path
        lets the AI materialize a reduced candidate only while the move is still
        early enough to preserve RR and the previous armed context was strong.
        """

        if side not in {"BUY", "SELL"} or min(current_price, entry, stop, target) <= 0:
            return {"allowed": False, "reason": "invalid_geometry"}
        if pulse_score < 90.0:
            return {"allowed": False, "reason": "pulse_below_continuation_floor"}
        initial_final = cls._safe_float(state.get("current_final_confirmation_score") or state.get("initial_final_confirmation_score"))
        patience = cls._safe_float(state.get("patience_score"))
        if initial_final < 48.0 and patience < 62.0:
            return {"allowed": False, "reason": "armed_context_not_strong_enough"}

        favorable_move = current_price - entry if side == "BUY" else entry - current_price
        total_path = abs(target - entry)
        initial_risk = abs(entry - stop)
        if favorable_move <= max(initial_risk * 0.20, 0.50):
            return {"allowed": False, "reason": "follow_through_not_confirmed"}
        if total_path <= 0:
            return {"allowed": False, "reason": "target_path_invalid"}
        progress_to_target = favorable_move / total_path
        if progress_to_target > 0.58:
            return {
                "allowed": False,
                "reason": "continuation_too_late",
                "progress_to_target": round(progress_to_target, 4),
            }
        if selected_rr < 1.15:
            return {"allowed": False, "reason": "rr_not_enough_after_follow_through"}
        return {
            "allowed": True,
            "reason": "early_follow_through_with_rr_intact",
            "favorable_move": round(favorable_move, 5),
            "progress_to_target": round(progress_to_target, 4),
            "selected_rr": round(selected_rr, 4),
        }

    @staticmethod
    def _directional_geometry_alive(*, side: str, current_price: float, stop: float, target: float) -> bool:
        """Validate that the prepared SL/TP still surrounds price correctly."""

        if min(current_price, stop, target) <= 0:
            return False
        if side == "BUY":
            return stop < current_price < target
        if side == "SELL":
            return target < current_price < stop
        return False

    @classmethod
    def _broken_context_price(
        cls,
        *,
        side: str,
        stop: float,
        target: float,
        market_state: dict[str, Any],
        market_clarity: dict[str, Any],
        expected_zone: dict[str, Any],
    ) -> float | None:
        """Return a contextual price that proves the armed geometry is broken."""

        prices: list[float] = []
        clarity_zone = market_clarity.get("expected_entry_zone") or {}
        for source in (market_state, market_clarity, expected_zone, clarity_zone):
            for key in ("current_price", "last_price", "market_price"):
                value = cls._safe_float(source.get(key) if isinstance(source, dict) else None)
                if value > 0:
                    prices.append(value)
        for price in prices:
            if not cls._directional_geometry_alive(side=side, current_price=price, stop=stop, target=target):
                return price
        return None

    def _remember_materialization_block(self, state: dict[str, Any], reason: str, details: dict[str, Any]) -> None:
        """Persist why an armed idea did not become a candidate yet.

        This keeps replay/demo honest: instead of silently returning ``None``,
        the history shows whether the AI was patient for a good reason or
        whether a threshold is too narrow.
        """

        state = dict(state)
        state["last_materialization_block"] = {"reason": reason, "details": details}
        self._save_state(state)
        self._append_if_changed(
            state,
            "ARMED_RETEST_WAIT",
            f"ARMED_RETEST materialization pending: {reason}; details={details}",
        )

    def _build_state(
        self,
        *,
        symbol: str,
        side: str,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        final_confirmation: dict[str, Any],
        market_pulse: dict[str, Any],
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        snapshot: dict[str, Any],
        created_at: datetime,
        reason: str,
    ) -> dict[str, Any]:
        current_price = self._latest_price(snapshot)
        entry = self._safe_float((signal or {}).get("entry_price")) or current_price
        stop = self._safe_float((signal or {}).get("stop_price"))
        target = self._safe_float((signal or {}).get("target_price"))
        recovery_plan = execution_risk_decision.get("execution_recovery_plan") or {}
        if recovery_plan.get("safe_retest_entry_reference"):
            entry = self._safe_float(recovery_plan.get("safe_retest_entry_reference")) or entry
        if stop <= 0 and side == "BUY":
            stop = entry - max(2.0, entry * 0.001)
        elif stop <= 0 and side == "SELL":
            stop = entry + max(2.0, entry * 0.001)
        if target <= 0 and stop > 0:
            risk = abs(entry - stop)
            target = entry + risk * 1.5 if side == "BUY" else entry - risk * 1.5
        rr = abs(target - entry) / abs(entry - stop) if entry and stop and target and entry != stop else None
        target_zone = self._target_zone(entry=entry, stop=stop, side=side)
        confirmation_plan = self._entry_confirmation_plan(
            side=side,
            target_zone=target_zone,
            entry=entry,
            stop=stop,
            target=target,
            expected_rr=rr,
            reason=reason,
        )
        return {
            "symbol": symbol,
            "status": "ACTIVE",
            "action": "ARMED_RETEST_WAIT",
            "side": side,
            "trigger_type": (active_watch or {}).get("trigger_type") or (intelligence.get("watch_trigger") or {}).get("trigger_type"),
            "created_at": created_at.isoformat(),
            "last_seen_at": created_at.isoformat(),
            "expires_at": (created_at + timedelta(minutes=self.expiration_minutes)).isoformat(),
            "expiration_candles": self.expiration_candles,
            "age_candles": 0,
            "target_retest_zone": target_zone,
            "ideal_entry_price": round(entry, 5) if entry else None,
            "compact_sl_expected": round(stop, 5) if stop else None,
            "tp_estimated": round(target, 5) if target else None,
            "expected_rr": round(rr, 4) if rr is not None else None,
            "entry_confirmation_plan": confirmation_plan,
            "armed_reason": reason,
            "reason": reason,
            "patience_score": self._patience_score(final_confirmation, market_pulse, entry_quality),
            "initial_final_confirmation_score": final_confirmation.get("final_confirmation_score"),
            "initial_execution_readiness_score": execution_readiness.get("execution_readiness_score"),
            "initial_entry_quality_score": entry_quality.get("entry_quality_score"),
            "initial_market_pulse_score": market_pulse.get("score"),
            "current_final_confirmation_score": final_confirmation.get("final_confirmation_score"),
            "current_execution_readiness_score": execution_readiness.get("execution_readiness_score"),
            "current_entry_quality_score": entry_quality.get("entry_quality_score"),
            "current_market_pulse_score": market_pulse.get("score"),
            "required_to_execute": [
                "final_confirmation_score >= 75",
                "execution_readiness_score >= 78",
                "entry_quality_score >= 75",
                "SL compacto válido",
                "dirección alineada y sin bloqueos críticos",
            ],
            "history_path": str(self.history_path.resolve()),
        }

    def _can_arm(
        self,
        *,
        side: str,
        final_score: float,
        final_confirmation: dict[str, Any],
        pulse_score: float,
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
        critical_blocks: list[str],
        q_learning_decision: dict[str, Any],
        intelligence: dict[str, Any],
        execution_environment: dict[str, Any],
        execution_risk_decision: dict[str, Any],
    ) -> tuple[bool, str]:
        if side not in {"BUY", "SELL"}:
            return False, "No hay dirección principal clara para armar retest."
        if pulse_score < 85:
            return False, f"Market Pulse {pulse_score} menor a 85."
        borderline_high_pulse = pulse_score >= 85.0 and 58.0 <= final_score < 60.0
        context_quality = self._context_quality(
            intelligence=intelligence,
            final_confirmation=final_confirmation,
            entry_quality=entry_quality,
            execution_environment=execution_environment,
            side=side,
        )
        strong_context_arm = context_quality["eligible"] and 45.0 <= final_score < 60.0
        if (
            not (60 <= final_score <= 72)
            and not borderline_high_pulse
            and not strong_context_arm
            and not execution_risk_decision.get("execution_recovery_plan")
        ):
            return False, f"Final Confirmation {final_score} no está en rango ARMED_RETEST 60-72."
        if critical_blocks:
            return False, "Bloqueo crítico: " + ", ".join(critical_blocks)
        if self._q_strongly_contradicts(side, q_learning_decision):
            return False, "Q-learning contradice fuertemente el lado esperado."
        event_action = (intelligence.get("event_risk") or {}).get("action")
        if event_action not in {None, "allow", "watch"}:
            return False, f"Evento macro no permite armar: {event_action}."
        if str(execution_environment.get("execution_viability") or "").upper() == "UNSAFE":
            return False, "Execution environment críticamente inseguro."
        classification = execution_readiness.get("classification")
        entry_decision = entry_quality.get("decision")
        if borderline_high_pulse:
            return True, (
                f"Pulso alto con confirmación borderline ({final_score}); no ejecutar, "
                f"pero armar retest para esperar timing limpio. readiness={classification}, "
                f"entry_quality={entry_decision}."
            )
        if strong_context_arm:
            return True, (
                f"Contexto institucional fuerte ({context_quality['score']}) con confirmación final "
                f"{final_score}; armar retest para esperar gatillo limpio sin ejecutar todavía. "
                f"drivers={', '.join(context_quality['drivers'])}; readiness={classification}, "
                f"entry_quality={entry_decision}."
            )
        return True, f"Pulso alto con confirmación parcial: readiness={classification}, entry_quality={entry_decision}; esperar retest limpio."

    @classmethod
    def _context_quality(
        cls,
        *,
        intelligence: dict[str, Any],
        final_confirmation: dict[str, Any],
        entry_quality: dict[str, Any],
        execution_environment: dict[str, Any],
        side: str,
    ) -> dict[str, Any]:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        market_clarity = market_state.get("market_clarity") or {}
        expected_zone = market_state.get("expected_entry_zone") or market_clarity.get("expected_entry_zone") or {}
        trigger_plan = market_state.get("entry_trigger_plan") or {}
        session = str(execution_environment.get("session_rd") or market_state.get("session_rd") or "").lower()

        drivers: list[str] = []
        score = 0.0
        clarity_score = cls._safe_float(market_clarity.get("clarity_score"))
        clarity_side = str(market_clarity.get("selected_side") or market_state.get("preferred_side") or "").upper()
        if clarity_score >= 70.0 and clarity_side == side:
            score += 28.0
            drivers.append("market_clarity_aligned")
        if expected_zone.get("in_zone_now") is True:
            score += 22.0
            drivers.append("price_in_expected_zone")
        if trigger_plan.get("liquidity_confirmed") is True:
            score += 18.0
            drivers.append("liquidity_confirmed")
        if cls._safe_float(entry_quality.get("zone_quality")) >= 45.0:
            score += 12.0
            drivers.append("zone_quality_acceptable")
        if session in {"london_rd", "ny_rd", "pm_volatility_rd", "evening_volatility_rd"}:
            score += 10.0
            drivers.append("validated_session")
        trigger_quality = str(trigger_plan.get("continuation_quality") or "").lower()
        if trigger_quality == "strong":
            score += 20.0
            drivers.append("strong_continuation_quality")
        elif trigger_quality == "medium":
            score += 14.0
            drivers.append("medium_continuation_quality")
        liquidity_volume = final_confirmation.get("liquidity_volume_trap_analysis") or {}
        movement_quality = cls._safe_float(liquidity_volume.get("movement_quality_score"))
        volume_confirmation = cls._safe_float(liquidity_volume.get("volume_confirmation_score"))
        if movement_quality >= 0.58:
            score += 10.0
            drivers.append("movement_quality_supports_setup")
        if volume_confirmation >= 0.52:
            score += 8.0
            drivers.append("volume_supports_setup")
        if cls._safe_float(final_confirmation.get("final_confirmation_score")) >= 50.0:
            score += 8.0
            drivers.append("borderline_final_confirmation")
        if cls._safe_float(final_confirmation.get("trap_risk_score")) < 0.72:
            score += 5.0
            drivers.append("trap_risk_controlled")
        if cls._safe_float(final_confirmation.get("late_entry_risk")) < 0.72:
            score += 5.0
            drivers.append("late_entry_risk_controlled")

        return {
            "score": round(min(100.0, score), 2),
            "eligible": score >= 60.0,
            "drivers": drivers,
        }

    @staticmethod
    def _critical_blocks(
        *,
        final_confirmation: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        execution_environment: dict[str, Any],
        intelligence: dict[str, Any],
    ) -> list[str]:
        critical = {
            "macro_event_not_allow",
            "execution_environment_not_safe",
            "direction_consistency_not_valid",
            "zone_invalid_or_expired",
            "trap_risk_too_high",
        }
        blockers = [str(item) for item in final_confirmation.get("blockers", []) or [] if str(item) in critical]
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        market_clarity = market_state.get("market_clarity") or {}
        expected_zone = market_state.get("expected_entry_zone") or market_clarity.get("expected_entry_zone") or {}
        has_signal = bool((intelligence.get("overview") or {}).get("signal"))
        if (
            not has_signal
            and "zone_invalid_or_expired" in blockers
            and (
                expected_zone.get("in_zone_now") is True
                or str(market_state.get("preferred_side") or "").upper() in {"BUY", "SELL"}
            )
        ):
            blockers = [item for item in blockers if item != "zone_invalid_or_expired"]
        if (intelligence.get("event_risk") or {}).get("action") == "block":
            blockers.append("macro_event_not_allow")
        if str(execution_environment.get("execution_viability") or "").upper() == "UNSAFE":
            blockers.append("execution_environment_not_safe")
        if execution_risk_decision.get("allowed_risk_mode") == "blocked" and not execution_risk_decision.get("execution_recovery_plan"):
            status = str(execution_risk_decision.get("execution_status") or "risk_blocked")
            if status in {"waiting_for_entry_confirmation_retest", "blocked_by_armed_retest_wait"}:
                return list(dict.fromkeys(blockers))
            # PREPARE/WAIT from FinalConfirmation is not a structural veto.
            # Keep the armed idea alive unless FinalConfirmation supplied an
            # actual blocker such as trap, invalid direction, unsafe execution
            # or macro risk.  Otherwise ARMED_RETEST drops the setup right
            # before the clean retest candle it was designed to wait for.
            if status == "blocked_by_final_confirmation":
                return list(dict.fromkeys(blockers))
            policy_action = str(execution_risk_decision.get("watch_policy_action") or "").upper()
            # OBSERVE/blocked means "do not execute yet"; it should not prevent
            # arming a retest idea.  ARMED_RETEST exists exactly to wait for the
            # missing timing/geometry while keeping execution blocked.
            if has_signal or policy_action not in {"OBSERVE", "DROP", ""}:
                blockers.append(status)
        return list(dict.fromkeys(blockers))

    @staticmethod
    def _execute_ready(
        *,
        final_score: float,
        final_confirmation: dict[str, Any],
        readiness_score: float,
        entry_score: float,
        entry_quality: dict[str, Any],
        execution_risk_decision: dict[str, Any],
    ) -> bool:
        strict_ready = (
            final_score >= 75.0
            and readiness_score >= 78.0
            and entry_score >= 75.0
            and entry_quality.get("decision") in {"EXECUTION_READY", "CLEAN_ENTRY"}
            and not execution_risk_decision.get("execution_recovery_plan")
        )
        if strict_ready:
            return True

        # ARMED_RETEST is a reduced-risk bridge: once FinalConfirmation already
        # authorizes EXECUTE and EntryQuality is clean, keep the trade measurable
        # in replay/demo instead of trapping it in WAIT solely because the full
        # normal-risk thresholds (75/78) were designed for stronger entries.
        final_decision = str(final_confirmation.get("decision") or "").upper()
        awareness_value = final_confirmation.get("confirmation_awareness_allowed")
        nested_awareness = (final_confirmation.get("confirmation_awareness") or {}).get(
            "execution_allowed_by_confirmation"
        )
        awareness_ok = (
            bool(awareness_value)
            or bool(nested_awareness)
            or (awareness_value is None and nested_awareness is None and final_decision == "EXECUTE")
        )
        reduced_execute_ready = (
            final_decision == "EXECUTE"
            and not final_confirmation.get("blockers")
            and awareness_ok
            and final_score >= 66.0
            and readiness_score >= 70.0
            and entry_score >= 75.0
            and entry_quality.get("decision") in {"EXECUTION_READY", "CLEAN_ENTRY"}
            and not execution_risk_decision.get("execution_recovery_plan")
        )
        if reduced_execute_ready:
            return True

        supervised_recovery = final_confirmation.get("supervised_v56_execute_recovery") or {}
        premium_discount = final_confirmation.get("premium_discount_analysis") or {}
        session_analysis = final_confirmation.get("session_execution_analysis") or {}
        liquidity_volume = final_confirmation.get("liquidity_volume_trap_analysis") or {}
        liquidity_or_flow = max(
            ArmedRetestEngine._safe_float(liquidity_volume.get("liquidity_readiness_score")),
            ArmedRetestEngine._safe_float(liquidity_volume.get("movement_quality_score")),
            ArmedRetestEngine._safe_float(liquidity_volume.get("volume_confirmation_score")),
        )
        supervised_reduced_ready = (
            bool(supervised_recovery.get("eligible"))
            and final_decision == "EXECUTE"
            and not final_confirmation.get("blockers")
            and (awareness_ok or bool(supervised_recovery.get("eligible")))
            and final_score >= 60.0
            and readiness_score >= 73.0
            and entry_score >= 70.0
            and str(session_analysis.get("session_status") or session_analysis.get("status") or "").lower()
            == "optimal_session"
            and premium_discount.get("status") != "blocked_chasing_price"
            and liquidity_or_flow >= 0.50
            and not execution_risk_decision.get("execution_recovery_plan")
        )
        return supervised_reduced_ready

    def _is_expired(self, *, state: dict[str, Any], now: datetime) -> bool:
        if int(state.get("age_candles") or 0) >= int(state.get("expiration_candles") or self.expiration_candles):
            return True
        try:
            expires_at = datetime.fromisoformat(str(state.get("expires_at")))
        except ValueError:
            return False
        return now >= expires_at

    def _transition(self, state: dict[str, Any], event: str, reason: str) -> dict[str, Any]:
        state = dict(state)
        state["status"] = event.replace("ARMED_RETEST_", "")
        state["action"] = event
        state["reason"] = reason
        if event in {"ARMED_RETEST_DROP", "ARMED_RETEST_EXPIRED"}:
            self._clear_state()
        else:
            self._save_state(state)
        self._append_event(state, event, reason)
        return self._result(state)

    def _append_if_changed(self, state: dict[str, Any], event: str, reason: str) -> None:
        last = self._last_event()
        if last and last.get("event") == event and last.get("reason") == reason and last.get("age_candles") == state.get("age_candles"):
            return
        self._append_event(state, event, reason)

    def _append_event(self, state: dict[str, Any], event: str, reason: str) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": state.get("symbol"),
            "event": event,
            "side": state.get("side"),
            "trigger_type": state.get("trigger_type"),
            "age_candles": state.get("age_candles"),
            "final_confirmation_score": state.get("current_final_confirmation_score"),
            "execution_readiness_score": state.get("current_execution_readiness_score"),
            "entry_quality_score": state.get("current_entry_quality_score"),
            "market_pulse_score": state.get("current_market_pulse_score"),
            "ideal_entry_price": state.get("ideal_entry_price"),
            "compact_sl_expected": state.get("compact_sl_expected"),
            "tp_estimated": state.get("tp_estimated"),
            "expected_rr": state.get("expected_rr"),
            "patience_score": state.get("patience_score"),
            "entry_confirmation_plan": state.get("entry_confirmation_plan"),
            "reason": reason,
        }
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _last_event(self) -> dict[str, Any] | None:
        if not self.history_path.exists():
            return None
        try:
            lines = [line for line in self.history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            return None
        if not lines:
            return None
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return None

    def _load_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) and data.get("status") == "ACTIVE" else None

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _clear_state(self) -> None:
        try:
            self.state_path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _result(state: dict[str, Any]) -> dict[str, Any]:
        result = dict(state)
        result["armed_retest_status"] = result.get("status")
        return result

    @staticmethod
    def _side(
        *,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        final_confirmation: dict[str, Any],
    ) -> str:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        return str(
            (signal or {}).get("direction")
            or final_confirmation.get("side")
            or (active_watch or {}).get("side")
            or watch_trigger.get("side")
            or market_state.get("preferred_side")
            or "NEUTRAL"
        ).upper()

    @staticmethod
    def _target_zone(*, entry: float, stop: float, side: str) -> dict[str, float | str]:
        risk = abs(entry - stop) if entry and stop else 0.0
        buffer = max(risk * 0.25, 0.5)
        if side == "BUY":
            return {"lower": round(entry - buffer, 5), "upper": round(entry + buffer * 0.35, 5), "type": "buy_retest_zone"}
        if side == "SELL":
            return {"lower": round(entry - buffer * 0.35, 5), "upper": round(entry + buffer, 5), "type": "sell_retest_zone"}
        return {"lower": round(entry - buffer, 5), "upper": round(entry + buffer, 5), "type": "neutral_observation_zone"}

    @staticmethod
    def _entry_confirmation_plan(
        *,
        side: str,
        target_zone: dict[str, float | str],
        entry: float,
        stop: float,
        target: float,
        expected_rr: float | None,
        reason: str,
    ) -> dict[str, Any]:
        side = str(side or "NEUTRAL").upper()
        direction_word = "alcista" if side == "BUY" else "bajista" if side == "SELL" else "direccional"
        return {
            "status": "WAITING_PRECISE_TRIGGER",
            "side": side,
            "where_to_enter": {
                "zone": target_zone,
                "ideal_entry_price": round(entry, 5) if entry else None,
                "instruction": "Esperar que el precio vuelva o se mantenga dentro de la zona preparada; no perseguir precio fuera de la zona.",
            },
            "risk_plan": {
                "compact_sl_expected": round(stop, 5) if stop else None,
                "tp_estimated": round(target, 5) if target else None,
                "expected_rr": round(expected_rr, 4) if expected_rr is not None else None,
                "instruction": "Solo permitir riesgo reducido hasta que el gatillo final confirme estructura limpia.",
            },
            "when_to_execute": [
                "precio dentro de target_retest_zone",
                "Final Confirmation >= 75",
                "Entry Quality >= 75",
                "Execution Readiness >= 78",
                f"vela de confirmación {direction_word} con displacement/micro BOS",
                "liquidez o retest validado, sin trampa activa",
                "spread/latencia seguros y sin evento macro bloqueante",
            ],
            "do_not_execute_if": [
                "precio persigue fuera de la zona preparada",
                "cambia preferred_side o claridad direccional",
                "aparece sweep/opposite liquidity contra la tesis",
                "SL compacto deja de ser lógico",
                "RR cae por debajo de 1.0 en señal reducida",
                "Market Pulse cae o ejecución se vuelve insegura",
            ],
            "armed_reason": reason,
        }

    @staticmethod
    def _patience_score(final_confirmation: dict[str, Any], market_pulse: dict[str, Any], entry_quality: dict[str, Any]) -> float:
        final_score = ArmedRetestEngine._safe_float(final_confirmation.get("final_confirmation_score"))
        pulse_score = ArmedRetestEngine._safe_float(market_pulse.get("score"))
        entry_score = ArmedRetestEngine._safe_float(entry_quality.get("entry_quality_score"))
        return round(max(0.0, min(100.0, pulse_score * 0.45 + final_score * 0.30 + entry_score * 0.25)), 2)

    @staticmethod
    def _wait_reason(*, final_score: float, readiness_score: float, entry_score: float) -> str:
        missing: list[str] = []
        if final_score < 75:
            missing.append(f"final_confirmation {final_score}<75")
        if readiness_score < 78:
            missing.append(f"execution_readiness {readiness_score}<78")
        if entry_score < 75:
            missing.append(f"entry_quality {entry_score}<75")
        return "ARMED_RETEST activo; falta " + ", ".join(missing) if missing else "ARMED_RETEST activo esperando tick/retest final."

    @staticmethod
    def _q_strongly_contradicts(side: str, q_learning_decision: dict[str, Any]) -> bool:
        q_policy = str(q_learning_decision.get("q_policy_action") or q_learning_decision.get("policy_action") or "HOLD").upper()
        value_gap = abs(ArmedRetestEngine._safe_float(q_learning_decision.get("value_gap")))
        return q_policy in {"BUY", "SELL"} and q_policy != side and value_gap >= 0.35

    @staticmethod
    def _latest_price(snapshot: dict[str, Any]) -> float:
        for timeframe in ("M1", "M5"):
            candles = snapshot.get("candles", {}).get(timeframe) if isinstance(snapshot.get("candles"), dict) else None
            if candles:
                candle = candles[-1]
                if isinstance(candle, dict):
                    return ArmedRetestEngine._safe_float(candle.get("close"))
                return ArmedRetestEngine._safe_float(getattr(candle, "close", 0.0))
        return 0.0

    @staticmethod
    def _latest_candle_time(snapshot: dict[str, Any]) -> str | None:
        for timeframe in ("M1", "M5"):
            candles = snapshot.get("candles", {}).get(timeframe) if isinstance(snapshot.get("candles"), dict) else None
            if candles:
                candle = candles[-1]
                if isinstance(candle, dict):
                    value = candle.get("time")
                else:
                    value = getattr(candle, "time", None)
                return str(value) if value is not None else None
        return None

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
