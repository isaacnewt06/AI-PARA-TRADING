"""Persistent Q-learning decision memory for demo trading cycles."""

from __future__ import annotations

import json
import random
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class QLearningConfig:
    alpha: float = 0.18
    gamma: float = 0.82
    replay_batch_size: int = 32
    replay_max_events: int = 1000
    min_confidence_to_bias: float = 0.08
    historical_seed_max_rows_per_file: int = 3000


class QLearningDecisionMemory:
    """Small tabular Q-learning layer that learns from demo cycle outcomes.

    It is intentionally interpretable: state keys are market contexts, actions
    are HOLD/BUY/SELL/CLOSE, and every update is written to JSONL for audit.
    """

    ACTIONS = ("HOLD", "BUY", "SELL", "CLOSE")

    def __init__(
        self,
        *,
        table_path: Path,
        replay_path: Path,
        report_path: Path,
        config: QLearningConfig | None = None,
    ) -> None:
        self.table_path = table_path
        self.replay_path = replay_path
        self.report_path = report_path
        self.config = config or QLearningConfig()
        self.table_path.parent.mkdir(parents=True, exist_ok=True)

    def evaluate_decision(
        self,
        *,
        symbol: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        active_watch_metrics: dict[str, Any],
        watch_execution_policy: dict[str, Any],
    ) -> dict[str, Any]:
        q_table = self._load_table()
        state_key = self._state_key(
            symbol=symbol,
            intelligence=intelligence,
            active_watch=active_watch,
            watch_execution_policy=watch_execution_policy,
        )
        values = self._state_values(q_table, state_key)
        prior_values = self._historical_prior_values(
            q_table=q_table,
            symbol=symbol,
            intelligence=intelligence,
            active_watch=active_watch,
        )
        if any(abs(value) > 0 for value in prior_values.values()):
            values = {
                action: round(values[action] * 0.65 + prior_values[action] * 0.35, 4)
                for action in self.ACTIONS
            }
        policy_action = max(values, key=values.get)
        sorted_values = sorted(values.values(), reverse=True)
        value_gap = round(sorted_values[0] - sorted_values[1], 4) if len(sorted_values) > 1 else 0.0
        status = "learning" if q_table else "cold_start"
        health = str(active_watch_metrics.get("watch_health") or "inactive")
        probability = self._safe_float(active_watch_metrics.get("watch_probability_to_execute"))
        strategy_harmony = self._strategy_harmony_matrix(
            intelligence=intelligence,
            active_watch=active_watch,
            watch_execution_policy=watch_execution_policy,
            q_values=values,
            prior_values=prior_values,
            policy_action=policy_action,
            value_gap=value_gap,
        )

        risk_bias = "neutral"
        if policy_action == "HOLD" and values["HOLD"] >= max(values["BUY"], values["SELL"]) + 0.08:
            risk_bias = "protect_capital"
        elif strategy_harmony["status"] == "conflicted":
            risk_bias = "reduce_or_pause"
        elif (
            policy_action in {"BUY", "SELL"}
            and value_gap >= self.config.min_confidence_to_bias
            and health not in {"critical", "deteriorating"}
            and strategy_harmony["status"] in {"converged", "aligned", "mixed"}
        ):
            risk_bias = "support_entry"
        elif health in {"critical", "deteriorating"} or probability < 0.35:
            risk_bias = "reduce_or_pause"
        if strategy_harmony["status"] == "mixed" and risk_bias == "support_entry":
            risk_bias = "support_reduced_only"

        return {
            "status": status,
            "learning_method": "tabular_q_learning_persistent",
            "state_key": state_key,
            "q_values": values,
            "historical_prior_values": prior_values,
            "q_policy_action": policy_action,
            "value_gap": value_gap,
            "risk_bias": risk_bias,
            "strategy_harmony_matrix": strategy_harmony,
            "experience_count": int(q_table.get("_meta", {}).get("experience_count", 0)),
            "replay_count": int(q_table.get("_meta", {}).get("replay_count", 0)),
            "historical_seed": q_table.get("_meta", {}).get("historical_seed", {}),
            "reason": self._decision_reason(
                policy_action=policy_action,
                values=values,
                risk_bias=risk_bias,
                strategy_harmony=strategy_harmony,
            ),
            "safety_note": "Q-learning persistente ajusta sesgo/riesgo; no ejecuta sin señal, SL/RR, macro allow y guardias validos.",
        }

    def record_cycle(
        self,
        *,
        symbol: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        active_watch_metrics: dict[str, Any],
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        signal: dict[str, Any] | None,
        execution_status: str,
        controlled_demo_survival_protocol: dict[str, Any],
        position_management: dict[str, Any] | None = None,
        final_confirmation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state_key = self._state_key(
            symbol=symbol,
            intelligence=intelligence,
            active_watch=active_watch,
            watch_execution_policy=watch_execution_policy,
        )
        action = self._action_from_cycle(
            signal=signal,
            active_watch=active_watch,
            execution_status=execution_status,
            intelligence=intelligence,
        )
        next_state_key = state_key
        reward, reward_reason = self._cycle_reward(
            action=action,
            signal=signal,
            execution_status=execution_status,
            active_watch=active_watch,
            active_watch_metrics=active_watch_metrics,
            watch_execution_policy=watch_execution_policy,
            execution_risk_decision=execution_risk_decision,
            controlled_demo_survival_protocol=controlled_demo_survival_protocol,
            position_management=position_management,
            final_confirmation=final_confirmation,
        )
        management_feedback = (position_management or {}).get("feedback") or {}
        final_confirmation_payload = final_confirmation or {}
        experience = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "state_key": state_key,
            "action": action,
            "reward": reward,
            "reward_reason": reward_reason,
            "next_state_key": next_state_key,
            "execution_status": execution_status,
            "watch_policy_action": watch_execution_policy.get("watch_policy_action"),
            "active_watch_status": (active_watch or {}).get("status"),
            "active_watch_progress": (active_watch or {}).get("progress"),
            "watch_health": active_watch_metrics.get("watch_health"),
            "watch_probability_to_execute": active_watch_metrics.get("watch_probability_to_execute"),
            "allowed_risk_mode": execution_risk_decision.get("allowed_risk_mode"),
            "position_management_feedback": management_feedback,
            "position_management_actions": management_feedback.get("actions_taken", []),
            "final_confirmation_score": final_confirmation_payload.get("final_confirmation_score"),
            "final_confirmation_decision": final_confirmation_payload.get("decision"),
            "entry_timing_quality": final_confirmation_payload.get("entry_timing_quality"),
            "trap_risk_score": final_confirmation_payload.get("trap_risk_score"),
            "late_entry_risk": final_confirmation_payload.get("late_entry_risk"),
            "zone_validity": final_confirmation_payload.get("zone_validity"),
        }
        q_table = self._load_table()
        update = self._apply_q_update(q_table=q_table, experience=experience, replay=False)
        self._append_experience(experience)
        replay_summary = self._experience_replay(q_table)
        self._save_table(q_table)
        report = self._write_report(q_table=q_table, latest_experience=experience, update=update, replay_summary=replay_summary)
        return {
            "latest_experience": experience,
            "latest_update": update,
            "replay_summary": replay_summary,
            "report_path": str(report.resolve()),
        }

    def apply_risk_overlay(
        self,
        *,
        q_learning_decision: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        updated = dict(execution_risk_decision)
        action = str(q_learning_decision.get("q_policy_action") or "HOLD").upper()
        risk_bias = str(q_learning_decision.get("risk_bias") or "neutral")
        q_values = q_learning_decision.get("q_values") or {}
        side = str((signal or {}).get("direction") or "").upper()
        if side == "BUY":
            side_value = self._safe_float(q_values.get("BUY"))
        elif side == "SELL":
            side_value = self._safe_float(q_values.get("SELL"))
        else:
            side_value = 0.0
        hold_value = self._safe_float(q_values.get("HOLD"))
        session_pattern_signal = (
            signal is not None
            and str(signal.get("signal_type") or "") == "SESSION_Q_LEARNING_REDUCED_SIGNAL"
            and self._safe_float(signal.get("session_opportunity_score")) >= 0.68
            and bool(signal.get("q_learning_memory_alignment"))
        )

        updated["q_learning_policy_action"] = action
        updated["q_learning_risk_bias"] = risk_bias
        updated["q_learning_state_key"] = q_learning_decision.get("state_key")
        strategy_harmony = q_learning_decision.get("strategy_harmony_matrix") or {}
        updated["q_learning_strategy_harmony_score"] = strategy_harmony.get("harmony_score")
        updated["q_learning_strategy_harmony_status"] = strategy_harmony.get("status")
        if signal is not None and action == "HOLD" and hold_value > side_value + 0.18:
            if session_pattern_signal:
                updated["allowed_risk_mode"] = "reduced"
                updated["max_risk_multiplier"] = min(self._safe_float(updated.get("max_risk_multiplier"), 0.25), 0.25)
                updated["risk_application_reason"] = (
                    str(updated.get("risk_application_reason") or "")
                    + " Q-learning persistente favorece HOLD, pero la señal reducida de sesión/analogías se mantiene en modo demo con riesgo mínimo."
                ).strip()
                updated["execution_mode"] = "session_q_learning_reduced_execution"
            elif self._supervised_v56_signal_can_reduce(signal=signal):
                updated["can_execute"] = updated.get("can_execute", True)
                updated["allowed_risk_mode"] = "reduced"
                updated["max_risk_multiplier"] = min(self._safe_float(updated.get("max_risk_multiplier"), 0.5), 0.35)
                updated["risk_application_reason"] = (
                    str(updated.get("risk_application_reason") or "")
                    + " Q-learning favorece HOLD, pero señal v56/AGG calibrada permite continuar solo en riesgo reducido."
                ).strip()
                updated["execution_mode"] = "v56_supervised_q_hold_reduced_execution"
            elif self._armed_retest_signal_can_reduce(signal=signal):
                updated["can_execute"] = updated.get("can_execute", True)
                updated["allowed_risk_mode"] = "reduced"
                updated["max_risk_multiplier"] = min(self._safe_float(updated.get("max_risk_multiplier"), 0.35), 0.25)
                updated["risk_application_reason"] = (
                    str(updated.get("risk_application_reason") or "")
                    + " Q-learning favorece HOLD, pero ARMED_RETEST materializó gatillo limpio; continuar solo con riesgo reducido."
                ).strip()
                updated["execution_mode"] = "armed_retest_q_hold_reduced_execution"
            else:
                updated["can_execute"] = False
                updated["allowed_risk_mode"] = "blocked"
                updated["execution_status"] = "blocked_by_q_learning_memory"
                updated["execution_mode"] = "blocked_by_q_learning_memory"
                updated["decision"] = "blocked"
                updated["risk_application_reason"] = (
                    "Q-learning persistente favorece HOLD con ventaja suficiente; protege capital hasta nueva evidencia."
                )
                updated["max_risk_multiplier"] = 0.0
        elif signal is not None and strategy_harmony.get("status") == "conflicted":
            if self._weak_q_learning_conflict_can_reduce(
                signal_side=side,
                q_policy_action=action,
                strategy_harmony=strategy_harmony,
                q_learning_decision=q_learning_decision,
            ) or self._supervised_v56_signal_can_reduce(signal=signal) or self._armed_retest_signal_can_reduce(signal=signal):
                updated["can_execute"] = updated.get("can_execute", True)
                updated["allowed_risk_mode"] = "reduced"
                updated["max_risk_multiplier"] = min(self._safe_float(updated.get("max_risk_multiplier"), 0.5), 0.25)
                updated["execution_mode"] = "q_learning_weak_conflict_reduced_execution"
                updated["risk_application_reason"] = (
                    str(updated.get("risk_application_reason") or "")
                    + " Q-learning persistente contradice con ventaja debil, pero cursos/mercado/watch estan alineados; solo riesgo reducido."
                ).strip()
            else:
                updated["can_execute"] = False
                updated["allowed_risk_mode"] = "blocked"
                updated["execution_status"] = "blocked_by_q_learning_strategy_harmony"
                updated["execution_mode"] = "blocked_by_q_learning_strategy_harmony"
                updated["decision"] = "blocked"
                updated["risk_application_reason"] = (
                    "Q-learning detecta conflicto entre estrategia, cursos, analogías y dirección; no se permite ejecutar."
                )
                updated["max_risk_multiplier"] = 0.0
        elif signal is not None and strategy_harmony.get("status") == "mixed":
            updated["allowed_risk_mode"] = "reduced"
            updated["max_risk_multiplier"] = min(self._safe_float(updated.get("max_risk_multiplier"), 0.5), 0.35)
            updated["risk_application_reason"] = (
                str(updated.get("risk_application_reason") or "")
                + " Q-learning detecta armonía parcial; solo permite riesgo reducido."
            ).strip()
        elif signal is not None and risk_bias in {"reduce_or_pause", "support_reduced_only"}:
            updated["allowed_risk_mode"] = "reduced"
            updated["max_risk_multiplier"] = min(self._safe_float(updated.get("max_risk_multiplier"), 0.5), 0.35)
            updated["risk_application_reason"] = (
                str(updated.get("risk_application_reason") or "")
                + " Q-learning persistente exige riesgo reducido por armonía parcial, deterioro o baja probabilidad."
            ).strip()
        return updated

    @classmethod
    def _supervised_v56_signal_can_reduce(cls, *, signal: dict[str, Any]) -> bool:
        strategy_variant = str(signal.get("strategy_variant") or "").lower()
        setup_type = str(signal.get("setup_type") or signal.get("signal_type") or "").upper()
        market_regime = str(signal.get("market_regime") or "").upper()
        v56_like = "v56" in strategy_variant or ("AGG" in setup_type and market_regime == "EXPANSION")
        if not v56_like or "AGG" not in setup_type or market_regime != "EXPANSION":
            return False
        confidence = cls._safe_float(signal.get("confidence"))
        quant_score = cls._safe_float(signal.get("quant_score"))
        impulse_score = cls._safe_float(signal.get("impulse_score"))
        if confidence > 1.0:
            confidence /= 100.0
        if quant_score > 1.0:
            quant_score /= 100.0
        if impulse_score > 1.0:
            impulse_score /= 100.0
        try:
            selected_rr = float(signal.get("selected_rr") or 0.0)
        except (TypeError, ValueError):
            selected_rr = 0.0
        return bool(confidence >= 0.78 and quant_score >= 0.70 and impulse_score >= 0.70 and selected_rr >= 1.2)

    @classmethod
    def _armed_retest_signal_can_reduce(cls, *, signal: dict[str, Any]) -> bool:
        signal_type = str(signal.get("signal_type") or signal.get("setup_type") or "").upper()
        if "ARMED_RETEST" not in signal_type:
            return False
        confidence = cls._safe_float(signal.get("confidence"))
        continuation = cls._safe_float(signal.get("continuation_momentum"))
        if confidence > 1.0:
            confidence /= 100.0
        if continuation > 1.0:
            continuation /= 100.0
        try:
            selected_rr = float(signal.get("selected_rr") or 0.0)
        except (TypeError, ValueError):
            selected_rr = 0.0
        has_structure = bool(signal.get("micro_bos") or signal.get("micro_choch") or signal.get("choch"))
        has_bias = bool(signal.get("manual_bias_confirmation") or signal.get("course_bias_confirmation"))
        has_prices = bool(signal.get("entry_price") and signal.get("stop_price") and signal.get("target_price"))
        return bool(confidence >= 0.74 and selected_rr >= 1.0 and has_structure and has_bias and continuation >= 0.55 and has_prices)

    def _weak_q_learning_conflict_can_reduce(
        self,
        *,
        signal_side: str,
        q_policy_action: str,
        strategy_harmony: dict[str, Any],
        q_learning_decision: dict[str, Any],
    ) -> bool:
        """Let live consensus override stale Q-memory only with reduced risk."""
        selected_side = str(strategy_harmony.get("selected_side") or "").upper()
        if signal_side not in {"BUY", "SELL"} or selected_side != signal_side:
            return False
        if q_policy_action not in {"BUY", "SELL"} or q_policy_action == signal_side:
            return False
        q_value_gap = abs(
            self._safe_float(strategy_harmony.get("q_value_gap"), self._safe_float(q_learning_decision.get("value_gap")))
        )
        agreement_ratio = self._safe_float(strategy_harmony.get("agreement_ratio"))
        layer_agreement_score = self._safe_float(strategy_harmony.get("layer_agreement_score"))
        course_status = str(strategy_harmony.get("course_status") or "").lower()
        course_score = self._safe_float(strategy_harmony.get("course_score"))
        conflicts = [str(item) for item in (strategy_harmony.get("conflicts") or [])]
        only_persistent_memory_conflict = conflicts and all(
            "persistent_q_learning" in item or "historical_backtest_prior" in item for item in conflicts
        )
        return bool(
            q_value_gap <= 0.12
            and agreement_ratio >= 0.70
            and layer_agreement_score >= 0.80
            and course_status in {"aligned", "partial"}
            and course_score >= 0.70
            and only_persistent_memory_conflict
        )

    def ensure_historical_seed(self, *, backtest_dir: Path, symbol: str = "XAUUSDm") -> dict[str, Any]:
        files = sorted(backtest_dir.glob("*trades.csv")) if backtest_dir.exists() else []
        signature = self._historical_signature(files)
        q_table = self._load_table()
        current = (q_table.get("_meta", {}) or {}).get("historical_seed", {})
        if current.get("signature") == signature:
            return {"status": "already_seeded", **current}

        total_rows = 0
        used_files = 0
        reward_sum = 0.0
        for file_path in files:
            rows_used = 0
            strategy = file_path.stem.replace("_trades", "")
            try:
                with file_path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        if rows_used >= self.config.historical_seed_max_rows_per_file:
                            break
                        action = str(row.get("direction") or "").upper()
                        if action not in {"BUY", "SELL"}:
                            continue
                        reward = self._historical_reward(row)
                        for state_key in self._historical_prior_keys(
                            symbol=symbol,
                            strategy=strategy,
                            setup_type=str(row.get("setup_type") or "UNKNOWN"),
                            market_regime=str(row.get("market_regime") or "UNKNOWN"),
                            direction=action,
                            session_tags=self._session_tags_from_row(row),
                        ):
                            self._apply_q_update(
                                q_table=q_table,
                                experience={
                                    "state_key": state_key,
                                    "action": action,
                                    "reward": reward,
                                    "next_state_key": state_key,
                                },
                                replay=False,
                            )
                        rows_used += 1
                        total_rows += 1
                        reward_sum += reward
            except OSError:
                continue
            if rows_used:
                used_files += 1

        meta = dict(q_table.get("_meta", {}))
        meta["historical_seed"] = {
            "status": "seeded",
            "signature": signature,
            "seeded_at": datetime.now(timezone.utc).isoformat(),
            "files_used": used_files,
            "rows_used": total_rows,
            "average_reward": round(reward_sum / total_rows, 4) if total_rows else 0.0,
            "source_dir": str(backtest_dir),
            "method": "historical_backtest_trade_priors",
        }
        q_table["_meta"] = meta
        self._save_table(q_table)
        self._write_historical_seed_report(q_table=q_table, seed_summary=meta["historical_seed"])
        return meta["historical_seed"]

    def _apply_q_update(self, *, q_table: dict[str, Any], experience: dict[str, Any], replay: bool) -> dict[str, Any]:
        state = experience["state_key"]
        next_state = experience["next_state_key"]
        action = experience["action"]
        reward = self._safe_float(experience["reward"])
        values = self._state_values(q_table, state)
        next_values = self._state_values(q_table, next_state)
        old_q = self._safe_float(values.get(action))
        target = reward + self.config.gamma * max(next_values.values())
        new_q = old_q + self.config.alpha * (target - old_q)
        values[action] = round(new_q, 4)
        q_table[state] = values
        meta = dict(q_table.get("_meta", {}))
        key = "replay_count" if replay else "experience_count"
        meta[key] = int(meta.get(key, 0)) + 1
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        q_table["_meta"] = meta
        return {
            "state_key": state,
            "action": action,
            "old_q": round(old_q, 4),
            "new_q": round(new_q, 4),
            "reward": reward,
            "target": round(target, 4),
            "replay": replay,
        }

    def _experience_replay(self, q_table: dict[str, Any]) -> dict[str, Any]:
        experiences = self._read_recent_experiences(limit=self.config.replay_max_events)
        if not experiences:
            return {"samples": 0, "priority_samples": 0, "updates": 0}
        priority = [item for item in experiences if abs(self._safe_float(item.get("reward"))) >= 0.25]
        pool = priority or experiences
        sample_size = min(self.config.replay_batch_size, len(pool))
        rng = random.Random(560004)
        samples = rng.sample(pool, sample_size) if len(pool) > sample_size else list(pool)
        for item in samples:
            self._apply_q_update(q_table=q_table, experience=item, replay=True)
        return {"samples": len(samples), "priority_samples": len(priority), "updates": len(samples)}

    def _cycle_reward(
        self,
        *,
        action: str,
        signal: dict[str, Any] | None,
        execution_status: str,
        active_watch: dict[str, Any] | None,
        active_watch_metrics: dict[str, Any],
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        controlled_demo_survival_protocol: dict[str, Any],
        position_management: dict[str, Any] | None = None,
        final_confirmation: dict[str, Any] | None = None,
    ) -> tuple[float, str]:
        reward = 0.0
        reasons: list[str] = []
        status = str(execution_status)
        watch_status = str((active_watch or {}).get("status") or "")
        progress = str((active_watch or {}).get("progress") or "")
        health = str(active_watch_metrics.get("watch_health") or "inactive")
        probability = self._safe_float(active_watch_metrics.get("watch_probability_to_execute"))

        if status in {"demo_order_sent", "dry_run_signal_detected"}:
            rr = self._safe_float((signal or {}).get("selected_rr"))
            reward += min(0.45, 0.18 + max(0.0, rr - 1.0) * 0.08)
            reasons.append("senal ejecutable con RR evaluable")
        elif status in {"blocked_by_q_learning_memory", "blocked_by_controlled_demo_survival_protocol"}:
            reward += 0.08 if action == "HOLD" else -0.12
            reasons.append("proteccion de capital ante guardia activa")
        elif (status == "no_signal" or status.startswith("blocked_") or status.startswith("waiting_")) and action == "HOLD":
            reward += 0.04
            reasons.append("espera disciplinada sin trigger final")

        if watch_status == "TRIGGERED" or progress == "triggered":
            reward += 0.22
            reasons.append("watch evoluciono a trigger")
        elif watch_status == "CANCELLED":
            reward += 0.08 if action == "HOLD" else -0.18
            reasons.append("idea cancelada; premiar espera si no se forzo entrada")
        elif watch_status == "EXPIRED":
            reward += 0.04 if action == "HOLD" else -0.12
            reasons.append("idea expiro; evitar persecucion")

        policy_action = str(watch_execution_policy.get("watch_policy_action") or "")
        if policy_action == "PREPARE_NORMAL":
            reward += 0.08
            reasons.append("politica preparo riesgo normal")
        elif policy_action == "PREPARE_REDUCED":
            reward += 0.05
            reasons.append("politica preparo riesgo reducido")
        elif policy_action == "DROP":
            reward += 0.05 if action == "HOLD" else -0.1
            reasons.append("politica descarto idea debil")

        if health in {"critical", "deteriorating"}:
            reward += 0.08 if action == "HOLD" else -0.16
            reasons.append("watch con salud deteriorada")
        elif health == "improving" and probability >= 0.6 and action in {"BUY", "SELL"}:
            reward += 0.08
            reasons.append("watch mejorando con probabilidad util")

        if controlled_demo_survival_protocol.get("allowed") is False:
            reward += 0.06 if action == "HOLD" else -0.14
            reasons.append("protocolo de supervivencia no permite exposicion")
        if execution_risk_decision.get("allowed_risk_mode") == "blocked" and action in {"BUY", "SELL"}:
            reward -= 0.12
            reasons.append("riesgo bloqueado para accion direccional")

        final_payload = final_confirmation or {}
        final_score = self._safe_float(final_payload.get("final_confirmation_score"))
        final_decision = str(final_payload.get("decision") or "")
        trap_risk = self._safe_float(final_payload.get("trap_risk_score"))
        late_risk = self._safe_float(final_payload.get("late_entry_risk"))
        if final_decision == "EXECUTE" and final_score >= 72 and action in {"BUY", "SELL"}:
            reward += 0.12
            reasons.append("confirmacion final valida para ejecucion")
        elif final_decision == "BLOCK" and action in {"BUY", "SELL"}:
            reward -= 0.18
            reasons.append("accion direccional contra bloqueo de confirmacion final")
        if trap_risk >= 0.72 and action in {"BUY", "SELL"}:
            reward -= 0.1
            reasons.append("riesgo de trampa alto penaliza entrada")
        if late_risk >= 0.72 and action in {"BUY", "SELL"}:
            reward -= 0.1
            reasons.append("entrada tarde penalizada por Q-learning")

        management_feedback = (position_management or {}).get("feedback") or {}
        if management_feedback:
            if management_feedback.get("be_applied"):
                reward += 0.12
                reasons.append("gestion aplico break-even/proteccion")
            if management_feedback.get("partial_taken"):
                reward += 0.1
                reasons.append("gestion tomo parcial valido")
            if management_feedback.get("trailing_applied"):
                reward += 0.08
                reasons.append("gestion activo trailing/profit lock")
            if management_feedback.get("fast_exit_taken"):
                reward += 0.14
                reasons.append("gestion salio rapido por momentum decay")
            if management_feedback.get("invalid_partial_fallback"):
                reward += 0.04
                reasons.append("parcial invalido por lote minimo uso fallback defensivo")
            if management_feedback.get("gave_back_profit"):
                reward -= 0.32
                reasons.append("penalizacion: trade devolvio ganancia despues de MFE positivo")
            if (
                management_feedback.get("momentum_decay_detected")
                and not management_feedback.get("be_applied")
                and not management_feedback.get("fast_exit_taken")
            ):
                reward -= 0.18
                reasons.append("momentum decay detectado sin proteccion efectiva")

        reward = round(max(-1.0, min(1.0, reward)), 4)
        return reward, "; ".join(reasons) or "experiencia neutral de observacion"

    def _state_key(
        self,
        *,
        symbol: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        watch_execution_policy: dict[str, Any],
    ) -> str:
        overview = intelligence.get("overview", {}) or {}
        market_state = overview.get("market_state", {}) or {}
        harmony = (overview.get("knowledge_alignment", {}) or {}).get("harmony", {}) or {}
        event_risk = intelligence.get("event_risk", {}) or {}
        readiness = intelligence.get("execution_readiness", {}) or {}
        side = str(
            (active_watch or {}).get("side")
            or market_state.get("preferred_side")
            or "NEUTRAL"
        ).upper()
        maturity = self._bucket(self._safe_float(readiness.get("setup_maturity")), [50, 69, 75, 85], ["low", "forming", "prepare", "execute", "strong"])
        harmony_bucket = self._bucket(self._safe_float(harmony.get("harmony_score")), [0.35, 0.5, 0.68], ["weak", "partial", "aligned", "strong"])
        return "|".join(
            [
                str(symbol).upper(),
                str(market_state.get("market_regime") or "unknown"),
                str(market_state.get("operational_family") or (active_watch or {}).get("operational_family") or "NONE"),
                str(harmony.get("dominant_family") or "General"),
                side,
                self._session_key(market_state),
                str(market_state.get("higher_timeframe_bias") or (active_watch or {}).get("higher_timeframe_bias") or "NEUTRAL"),
                str(market_state.get("volatility_state") or intelligence.get("volatility_intelligence", {}).get("state") or "unknown"),
                str(event_risk.get("action") or "unknown"),
                str(watch_execution_policy.get("watch_policy_action") or "NONE"),
                maturity,
                harmony_bucket,
            ]
        )

    def _action_from_cycle(
        self,
        *,
        signal: dict[str, Any] | None,
        active_watch: dict[str, Any] | None,
        execution_status: str,
        intelligence: dict[str, Any],
    ) -> str:
        if execution_status.startswith("blocked") or intelligence.get("execution_readiness", {}).get("action") in {"WATCH", "CAUTION", "BLOCKED"}:
            if signal is None:
                return "HOLD"
        if signal is not None:
            side = str(signal.get("direction") or "").upper()
            if side in {"BUY", "SELL"}:
                return side
        side = str((active_watch or {}).get("side") or "").upper()
        return side if side in {"BUY", "SELL"} else "HOLD"

    def _state_values(self, q_table: dict[str, Any], state_key: str) -> dict[str, float]:
        raw = q_table.get(state_key) or {}
        return {action: self._safe_float(raw.get(action)) for action in self.ACTIONS}

    def _historical_prior_values(
        self,
        *,
        q_table: dict[str, Any],
        symbol: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
    ) -> dict[str, float]:
        overview = intelligence.get("overview", {}) or {}
        market_state = overview.get("market_state", {}) or {}
        side = str((active_watch or {}).get("side") or market_state.get("preferred_side") or "NEUTRAL").upper()
        setup_type = str((active_watch or {}).get("operational_family") or market_state.get("operational_family") or "UNKNOWN")
        regime = str(market_state.get("market_regime") or "UNKNOWN")
        session_tags = self._session_tags_from_market_state(market_state)
        candidate_keys: list[str] = []
        for direction in {side, "BUY", "SELL"}:
            if direction in {"BUY", "SELL"}:
                candidate_keys.extend(
                    [
                        f"HIST|{symbol.upper()}|REGIME|{regime}|{direction}",
                        f"HIST|{symbol.upper()}|SETUP|{setup_type}|{direction}",
                        f"HIST|{symbol.upper()}|DIRECTION|{direction}",
                    ]
                )
                for session_tag in session_tags:
                    candidate_keys.extend(
                        [
                            f"HIST|{symbol.upper()}|SESSION|{session_tag}|{direction}",
                            f"HIST|{symbol.upper()}|SESSION_REGIME|{session_tag}|{regime}|{direction}",
                        ]
                    )
        collected = [self._state_values(q_table, key) for key in candidate_keys if key in q_table]
        if not collected:
            return {action: 0.0 for action in self.ACTIONS}
        return {
            action: round(sum(values[action] for values in collected) / len(collected), 4)
            for action in self.ACTIONS
        }

    def _load_table(self) -> dict[str, Any]:
        if not self.table_path.exists():
            return {"_meta": {"experience_count": 0, "replay_count": 0}}
        try:
            return json.loads(self.table_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"_meta": {"experience_count": 0, "replay_count": 0, "load_warning": "table_reset_after_invalid_json"}}

    def _save_table(self, q_table: dict[str, Any]) -> None:
        self.table_path.write_text(json.dumps(q_table, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_experience(self, experience: dict[str, Any]) -> None:
        with self.replay_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(experience, ensure_ascii=False) + "\n")

    def _read_recent_experiences(self, *, limit: int) -> list[dict[str, Any]]:
        if not self.replay_path.exists():
            return []
        lines = self.replay_path.read_text(encoding="utf-8").splitlines()[-limit:]
        records: list[dict[str, Any]] = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def _write_report(
        self,
        *,
        q_table: dict[str, Any],
        latest_experience: dict[str, Any],
        update: dict[str, Any],
        replay_summary: dict[str, Any],
    ) -> Path:
        states = [key for key in q_table if key != "_meta"]
        meta = q_table.get("_meta", {})
        lines = [
            "# Q-learning Decision Memory",
            "",
            f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
            f"- states_tracked: {len(states)}",
            f"- experience_count: {meta.get('experience_count', 0)}",
            f"- replay_count: {meta.get('replay_count', 0)}",
            f"- latest_state: {latest_experience.get('state_key')}",
            f"- latest_action: {latest_experience.get('action')}",
            f"- latest_reward: {latest_experience.get('reward')}",
            f"- reward_reason: {latest_experience.get('reward_reason')}",
            f"- latest_q_update: {update}",
            f"- replay_summary: {replay_summary}",
            "",
            "## Top States",
        ]
        for key in states[-10:]:
            lines.append(f"- {key}: {q_table.get(key)}")
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.report_path

    @classmethod
    def _strategy_harmony_matrix(
        cls,
        *,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        watch_execution_policy: dict[str, Any],
        q_values: dict[str, float],
        prior_values: dict[str, float],
        policy_action: str,
        value_gap: float,
    ) -> dict[str, Any]:
        overview = intelligence.get("overview", {}) or {}
        market_state = overview.get("market_state", {}) or {}
        projection = (
            (intelligence.get("watch_trigger") or {}).get("pattern_projection")
            or overview.get("pattern_projection")
            or {}
        )
        professional = projection.get("professional_decision_matrix") or {}
        layer_sync = professional.get("layer_synchronization") or {}
        course = (
            professional.get("course_learning_sync")
            or projection.get("course_learning_sync")
            or (projection.get("cool_learning_memory") or {}).get("course_alignment")
            or {}
        )
        cool = professional.get("cool_learning_memory") or projection.get("cool_learning_memory") or {}
        side_comparison = projection.get("side_probability_comparison") or {}

        prior_policy = cls._best_direction(prior_values)
        layers = {
            "persistent_q_learning": str(policy_action or "HOLD").upper(),
            "historical_backtest_prior": prior_policy,
            "market_preferred_side": str(market_state.get("preferred_side") or "NEUTRAL").upper(),
            "active_watch_side": str((active_watch or {}).get("side") or "NEUTRAL").upper(),
            "watch_policy": str(watch_execution_policy.get("watch_policy_action") or "NONE").upper(),
            "professional_matrix": str(professional.get("selected_side") or "NEUTRAL").upper(),
            "course_memory": str(course.get("course_recommended_action") or "WAIT").upper(),
            "pattern_q_learning": str(cool.get("q_policy_action") or cool.get("policy_action") or "WAIT").upper(),
            "side_probability": str(side_comparison.get("selected_side") or "NEUTRAL").upper(),
            "higher_timeframe_bias": str(market_state.get("higher_timeframe_bias") or "NEUTRAL").upper(),
        }
        directional = {key: value for key, value in layers.items() if value in {"BUY", "SELL"}}
        counts = {
            "BUY": sum(1 for value in directional.values() if value == "BUY"),
            "SELL": sum(1 for value in directional.values() if value == "SELL"),
        }
        selected_side = "BUY" if counts["BUY"] > counts["SELL"] else "SELL" if counts["SELL"] > counts["BUY"] else "NEUTRAL"
        directional_total = max(1, len(directional))
        agreement_ratio = max(counts.values()) / directional_total if directional else 0.0
        q_action = str(policy_action or "HOLD").upper()
        q_aligned = q_action in {"HOLD", "WAIT"} or selected_side == "NEUTRAL" or q_action == selected_side
        conflicts = [
            f"{key}={value}"
            for key, value in directional.items()
            if selected_side in {"BUY", "SELL"} and value != selected_side
        ]
        layer_agreement = cls._safe_float(layer_sync.get("agreement_score"), 0.0)
        course_status = str(course.get("status") or "unknown")
        course_score = {"aligned": 1.0, "partial": 0.72, "weak": 0.38, "conflict": 0.0}.get(course_status, 0.45)
        q_gap_score = max(0.0, min(1.0, abs(float(value_gap)) / 0.28))
        harmony_score = round(
            max(
                0.0,
                min(
                    1.0,
                    agreement_ratio * 0.42
                    + layer_agreement * 0.22
                    + course_score * 0.18
                    + q_gap_score * 0.12
                    + (0.06 if q_aligned else -0.12),
                ),
            ),
            4,
        )
        if selected_side == "NEUTRAL":
            status = "observing"
        elif conflicts and not q_aligned:
            status = "conflicted"
        elif harmony_score >= 0.78 and len(conflicts) <= 1 and q_aligned:
            status = "converged"
        elif harmony_score >= 0.62 and q_aligned:
            status = "aligned"
        elif harmony_score >= 0.45:
            status = "mixed"
        else:
            status = "conflicted"
        if str(watch_execution_policy.get("watch_policy_action") or "").upper() == "DROP":
            status = "observing" if status in {"converged", "aligned"} else status

        return {
            "status": status,
            "harmony_score": harmony_score,
            "selected_side": selected_side,
            "agreement_ratio": round(agreement_ratio, 4),
            "directional_layer_count": len(directional),
            "q_aligned_with_consensus": q_aligned,
            "q_value_gap": value_gap,
            "course_status": course_status,
            "course_score": course.get("course_score"),
            "layer_agreement_score": layer_agreement,
            "layers": layers,
            "conflicts": conflicts,
            "interpretation": cls._strategy_harmony_interpretation(
                status=status,
                selected_side=selected_side,
                q_action=q_action,
                conflicts=conflicts,
            ),
        }

    @staticmethod
    def _best_direction(values: dict[str, float]) -> str:
        buy = QLearningDecisionMemory._safe_float(values.get("BUY"))
        sell = QLearningDecisionMemory._safe_float(values.get("SELL"))
        if abs(buy) < 1e-9 and abs(sell) < 1e-9:
            return "NEUTRAL"
        if buy > sell:
            return "BUY"
        if sell > buy:
            return "SELL"
        return "NEUTRAL"

    @staticmethod
    def _strategy_harmony_interpretation(*, status: str, selected_side: str, q_action: str, conflicts: list[str]) -> str:
        if status == "converged":
            return f"Q-learning y las capas operativas convergen hacia {selected_side}; se puede apoyar el trade si los guardias finales pasan."
        if status == "aligned":
            return f"Q-learning acompaña el consenso {selected_side}, pero aún requiere confirmación y gestión reducida si aplica."
        if status == "mixed":
            return f"Hay armonía parcial hacia {selected_side}; no conviene riesgo normal hasta resolver las capas mixtas."
        if status == "conflicted":
            return f"Q-learning/capas en conflicto: q={q_action}, consenso={selected_side}, conflictos={conflicts[:3]}."
        return "Sin dirección suficiente; Q-learning debe observar y recopilar más evidencia."

    def _write_historical_seed_report(self, *, q_table: dict[str, Any], seed_summary: dict[str, Any]) -> None:
        existing = self.report_path.read_text(encoding="utf-8") if self.report_path.exists() else "# Q-learning Decision Memory\n"
        lines = [
            existing.rstrip(),
            "",
            "## Historical Backtest Seed",
            f"- status: {seed_summary.get('status')}",
            f"- seeded_at: {seed_summary.get('seeded_at')}",
            f"- files_used: {seed_summary.get('files_used')}",
            f"- rows_used: {seed_summary.get('rows_used')}",
            f"- average_reward: {seed_summary.get('average_reward')}",
            f"- method: {seed_summary.get('method')}",
            f"- source_dir: {seed_summary.get('source_dir')}",
            f"- total_states_after_seed: {len([key for key in q_table if key != '_meta'])}",
        ]
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _historical_prior_keys(
        *,
        symbol: str,
        strategy: str,
        setup_type: str,
        market_regime: str,
        direction: str,
        session_tags: list[str] | None = None,
    ) -> list[str]:
        symbol_key = symbol.upper()
        direction_key = direction.upper()
        keys = [
            f"HIST|{symbol_key}|DIRECTION|{direction_key}",
            f"HIST|{symbol_key}|REGIME|{market_regime}|{direction_key}",
            f"HIST|{symbol_key}|SETUP|{setup_type}|{direction_key}",
            f"HIST|{symbol_key}|STRATEGY|{strategy}|{market_regime}|{direction_key}",
        ]
        for session_tag in session_tags or []:
            keys.extend(
                [
                    f"HIST|{symbol_key}|SESSION|{session_tag}|{direction_key}",
                    f"HIST|{symbol_key}|SESSION_REGIME|{session_tag}|{market_regime}|{direction_key}",
                ]
            )
        return keys

    @classmethod
    def _session_key(cls, market_state: dict[str, Any]) -> str:
        tags = cls._session_tags_from_market_state(market_state)
        return ",".join(tags) if tags else "off_session"

    @classmethod
    def _session_tags_from_market_state(cls, market_state: dict[str, Any]) -> list[str]:
        tags = [str(item).lower() for item in market_state.get("session_tags", []) or [] if item]
        if tags:
            return sorted(set(tags))
        hour = cls._safe_int(market_state.get("hour_ny"))
        return cls._session_tags_from_hour(hour)

    @classmethod
    def _session_tags_from_row(cls, row: dict[str, Any]) -> list[str]:
        for key in ("session", "session_tag", "session_variant"):
            value = str(row.get(key) or "").strip().lower()
            if value and value not in {"all", "any_session", "none"}:
                return [value]
        hour = cls._hour_ny_from_timestamp(row.get("entry_time") or row.get("signal_time") or row.get("time"))
        return cls._session_tags_from_hour(hour)

    @staticmethod
    def _session_tags_from_hour(hour: int | None) -> list[str]:
        if hour is None:
            return []
        tags: list[str] = []
        if 2 <= hour <= 5:
            tags.append("london")
        if 8 <= hour <= 16:
            tags.append("new_york")
        if hour == 9:
            tags.append("ny_am")
        if hour == 15:
            tags.append("ny_pm")
        return tags

    @staticmethod
    def _hour_ny_from_timestamp(value: Any) -> int | None:
        if not value:
            return None
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.astimezone(ZoneInfo("America/New_York")).hour)

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _historical_reward(cls, row: dict[str, Any]) -> float:
        net_pnl = cls._safe_float(row.get("net_pnl_usd"))
        gross_pnl = cls._safe_float(row.get("gross_pnl_usd"))
        drawdown_pct = abs(cls._safe_float(row.get("drawdown_percent")))
        pnl_basis = net_pnl if net_pnl != 0.0 else gross_pnl
        reward = max(-0.65, min(0.65, pnl_basis / 10.0))
        reward += 0.08 if pnl_basis > 0 else -0.08 if pnl_basis < 0 else 0.0
        reward -= min(0.22, drawdown_pct / 25.0)
        return round(max(-1.0, min(1.0, reward)), 4)

    @staticmethod
    def _historical_signature(files: list[Path]) -> str:
        parts = [f"{path.name}:{path.stat().st_size}:{int(path.stat().st_mtime)}" for path in files if path.exists()]
        return "|".join(parts)

    @staticmethod
    def _decision_reason(
        *,
        policy_action: str,
        values: dict[str, float],
        risk_bias: str,
        strategy_harmony: dict[str, Any] | None = None,
    ) -> str:
        harmony = strategy_harmony or {}
        return (
            f"Q-table favorece {policy_action} con valores HOLD={values['HOLD']:.3f}, "
            f"BUY={values['BUY']:.3f}, SELL={values['SELL']:.3f}, CLOSE={values['CLOSE']:.3f}; "
            f"sesgo de riesgo={risk_bias}; armonía={harmony.get('status', 'unknown')} "
            f"score={harmony.get('harmony_score', 'n/a')}."
        )

    @staticmethod
    def _bucket(value: float, thresholds: list[float], labels: list[str]) -> str:
        for idx, threshold in enumerate(thresholds):
            if value < threshold:
                return labels[idx]
        return labels[-1]

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
