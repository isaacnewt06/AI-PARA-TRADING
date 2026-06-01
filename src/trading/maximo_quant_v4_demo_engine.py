"""Controlled MT5 demo execution for MAXIMO MTF Quant Institutional v4."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import Settings
from src.core.logging import get_logger
from src.trading.controlled_demo_survival_protocol import ControlledDemoSurvivalProtocolV1
from src.trading.expansion_subtype_pretrade_audit import ExpansionSubtypePretradeAuditV1
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester, StrategyVariant
from src.trading.maximo_quant_v4_market_intelligence import MaximoQuantV4MarketIntelligenceEngine
from src.trading.maximo_quant_v4_ob_aggressive_management import ob_aggressive_defensive_management_plan
from src.trading.maximo_quant_v4_yearly_analyzer import MaximoQuantV4YearlyAnalyzer
from src.trading.mt5_bridge import MT5Bridge
from src.trading.q_learning_decision_memory import QLearningDecisionMemory

logger = get_logger(__name__)


class MaximoQuantV4DemoEngine:
    """Execute the best MAXIMO Quant v4 candidate on a demo-only MT5 account."""

    MAGIC_NUMBER = 560004
    ACTIVE_WATCH_EXPIRATION_CANDLES = 12
    ACTIVE_WATCH_OPERATIONAL_SETUP_MATURITY = 75.0
    ACTIVE_WATCH_OPERATIONAL_CONFIDENCE = 0.75
    ACTIVE_WATCH_TIMELINE_LIMIT = 5
    ACCOUNT_RISK_PERCENT_PER_TRADE = 5.0
    MAX_ACCOUNT_RISK_PERCENT_PER_TRADE = 10.0
    PARTIAL_TRIGGER_R = 0.5
    PARTIAL_CLOSE_FRACTION = 0.5
    BE_TRIGGER_R = 0.5
    PROTECT_TRIGGER_R = 0.8
    TRAILING_TRIGGER_R = 1.0
    NEAR_TP_TRAIL_PROGRESS = 0.75
    ACTIVE_WATCH_IMPORTANT_EVENTS = {
        "WATCH_CREATED",
        "WATCH_IMPROVING",
        "WATCH_DETERIORATING",
        "WATCH_TRIGGERED",
        "WATCH_CANCELLED",
        "WATCH_EXPIRED",
    }

    def __init__(self, settings: Settings, *, bridge: MT5Bridge | None = None) -> None:
        self.settings = settings
        self.bridge = bridge or MT5Bridge(settings)
        self.demo_dir = self.settings.paths.data_dir / "demo_trading" / "maximo_quant_v4"
        self.demo_dir.mkdir(parents=True, exist_ok=True)
        self.signal_path = self.demo_dir / "latest_signal.json"
        self.executions_path = self.demo_dir / "executions.csv"
        self.positions_path = self.demo_dir / "positions_snapshot.json"
        self.report_path = self.demo_dir / "demo_report.md"
        self.position_management_state_path = self.demo_dir / "position_management_state.json"
        self.active_watch_path = self.demo_dir / "active_watch.json"
        self.active_watch_history_path = self.demo_dir / "active_watch_history.jsonl"
        self.watch_performance_report_path = self.demo_dir / "watch_performance_report.md"
        self.q_learning_table_path = self.demo_dir / "q_learning_table.json"
        self.q_learning_replay_path = self.demo_dir / "q_learning_experience_replay.jsonl"
        self.q_learning_report_path = self.demo_dir / "q_learning_report.md"
        self.decision_source_audit_path = self.demo_dir / "decision_source_audit.jsonl"
        self.expansion_subtype_pretrade_audit_path = self.demo_dir / "expansion_subtype_pretrade_audit_v1.jsonl"
        self.strategy_snapshot_path = self.settings.paths.data_dir / "strategies" / "maximo_quant_v4_best_current.json"
        self.market_situation_map_path = self.settings.paths.data_dir / "knowledge" / "market_situation_map.json"
        self.market_situation_map_md_path = self.settings.paths.data_dir / "knowledge" / "market_situation_map.md"
        self.market_intelligence_json_path = self.settings.paths.data_dir / "market_analysis" / "maximo_quant_v4" / "latest_market_intelligence.json"
        self.market_intelligence_engine = MaximoQuantV4MarketIntelligenceEngine(settings, bridge=self.bridge)
        self.controlled_demo_protocol = ControlledDemoSurvivalProtocolV1()
        self.expansion_subtype_pretrade_audit = ExpansionSubtypePretradeAuditV1()
        self.q_learning_memory = QLearningDecisionMemory(
            table_path=self.q_learning_table_path,
            replay_path=self.q_learning_replay_path,
            report_path=self.q_learning_report_path,
        )

    def run(
        self,
        *,
        symbol: str,
        volume_lots: float = 0.01,
        deviation_points: int = 50,
        dry_run: bool = True,
        confirm_demo: bool = False,
    ) -> dict:
        runtime = self._load_runtime()
        intelligence = self.market_intelligence_engine.run_detailed(symbol=symbol)
        expansion_subtype_pretrade_audit = (
            self._build_expansion_subtype_pretrade_audit(symbol=symbol, intelligence=intelligence)
            if dry_run
            else self._disabled_expansion_subtype_pretrade_audit(symbol=symbol)
        )
        account_status = self.bridge.account_status()
        positions = self.bridge.list_positions(symbol=symbol, magic=self.MAGIC_NUMBER)
        snapshot = self.bridge.read_market_snapshot(
            symbol=symbol,
            bars_by_timeframe={"M1": 500, "M5": 5000, "H1": 2000},
        )
        position_management = self._manage_open_positions(
            symbol=symbol,
            positions=positions,
            snapshot=snapshot,
            dry_run=dry_run,
        )
        if position_management.get("updates_sent"):
            positions = self.bridge.list_positions(symbol=symbol, magic=self.MAGIC_NUMBER)
        execution_environment = self._read_execution_environment(symbol=symbol)
        active_watch = self._sync_active_watch(
            symbol=symbol,
            intelligence=intelligence,
            snapshot=snapshot,
            account_status=account_status,
        )
        active_watch_history = self._active_watch_history_summary()
        active_watch_metrics = self._active_watch_metrics(
            active_watch=active_watch,
            active_watch_history=active_watch_history,
        )
        watch_execution_policy = self._watch_execution_policy(
            active_watch=active_watch,
            active_watch_metrics=active_watch_metrics,
        )
        active_watch = self._bind_watch_policy(active_watch=active_watch, watch_execution_policy=watch_execution_policy)
        historical_q_seed = self.q_learning_memory.ensure_historical_seed(
            backtest_dir=self.settings.paths.data_dir / "backtests" / "maximo_mtf_quant_v4" / "yearly",
            symbol=symbol,
        )
        q_learning_decision = self.q_learning_memory.evaluate_decision(
            symbol=symbol,
            intelligence=intelligence,
            active_watch=active_watch,
            active_watch_metrics=active_watch_metrics,
            watch_execution_policy=watch_execution_policy,
        )
        q_learning_decision["historical_seed"] = historical_q_seed
        signal = intelligence["overview"]["signal"]
        readiness = intelligence["execution_readiness"]
        aggressive_reduced_signal = self._build_ob_aggressive_reduced_signal(
            symbol=symbol,
            runtime=runtime,
            intelligence=intelligence,
            active_watch=active_watch,
            watch_execution_policy=watch_execution_policy,
        )
        if signal is None and aggressive_reduced_signal is not None:
            signal = aggressive_reduced_signal
            intelligence = self._inject_ob_aggressive_reduced_signal(
                intelligence=intelligence,
                signal=aggressive_reduced_signal,
            )
            readiness = intelligence["execution_readiness"]
            if active_watch is not None:
                active_watch["status"] = "TRIGGERED"
                active_watch["progress"] = "triggered"
                active_watch["reason"] = "OB_AGGRESSIVE_REDUCED_SIGNAL habilitó EXECUTE reducido."
                self._save_active_watch(active_watch)
                self._append_active_watch_history_event(
                    symbol=symbol,
                    event="WATCH_TRIGGERED",
                    active_watch=active_watch,
                )
        session_q_signal = self._build_session_q_learning_reduced_signal(
            symbol=symbol,
            runtime=runtime,
            intelligence=intelligence,
            snapshot=snapshot,
            active_watch=active_watch,
            watch_execution_policy=watch_execution_policy,
        )
        if signal is None and session_q_signal is not None:
            signal = session_q_signal
            intelligence = self._inject_reduced_learning_signal(
                intelligence=intelligence,
                signal=session_q_signal,
                rationale="SESSION_Q_LEARNING_REDUCED_SIGNAL habilita ejecución demo reducida por sesión, analogías y memoria de cursos.",
            )
            readiness = intelligence["execution_readiness"]
            if active_watch is not None:
                active_watch["status"] = "TRIGGERED"
                active_watch["progress"] = "triggered"
                active_watch["reason"] = "Q-learning/session memory habilitó EXECUTE reducido."
                self._save_active_watch(active_watch)
                self._append_active_watch_history_event(
                    symbol=symbol,
                    event="WATCH_TRIGGERED",
                    active_watch=active_watch,
                )
        posture = intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("operating_posture")
        execution_risk_decision = self._execution_risk_binding(
            signal=signal,
            intelligence=intelligence,
            active_watch=active_watch,
            account_is_demo=bool(account_status.get("is_demo")),
        )
        controlled_demo_survival_protocol = self._evaluate_controlled_demo_survival_protocol(
            symbol=symbol,
            signal=signal,
            intelligence=intelligence,
            execution_environment=execution_environment,
        )
        execution_risk_decision = self._apply_controlled_demo_survival_protocol(
            execution_risk_decision=execution_risk_decision,
            controlled_demo_survival_protocol=controlled_demo_survival_protocol,
        )
        execution_risk_decision = self._materialize_execution_risk(
            execution_risk_decision=execution_risk_decision,
            base_risk=volume_lots,
        )
        execution_risk_decision = self.q_learning_memory.apply_risk_overlay(
            q_learning_decision=q_learning_decision,
            execution_risk_decision=execution_risk_decision,
            signal=signal,
        )
        direction_consistency_guard = self._signal_direction_consistency_guard(
            signal=signal,
            intelligence=intelligence,
            active_watch=active_watch,
            q_learning_decision=q_learning_decision,
        )
        if signal is not None and not direction_consistency_guard["allowed"]:
            execution_risk_decision = dict(execution_risk_decision)
            execution_risk_decision.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_direction_consistency",
                    "execution_mode": "blocked_by_direction_consistency",
                    "risk_application_reason": direction_consistency_guard["reason"],
                    "execution_status": "blocked_by_direction_consistency",
                }
            )
        execution_risk_decision = self._apply_account_risk_sizing(
            symbol=symbol,
            signal=signal,
            account_status=account_status,
            execution_risk_decision=execution_risk_decision,
        )

        execution: dict[str, Any] | None = None
        execution_status = "no_signal"
        if signal is None:
            execution_status = "no_signal"
        elif readiness.get("action") != "EXECUTE":
            execution_status = "blocked_by_market_intelligence"
        elif execution_risk_decision["can_execute"] is False:
            execution_status = execution_risk_decision["execution_status"]
        elif signal is not None and positions:
            execution_status = "position_already_open"
        elif signal is not None and signal["entry_kind"] != "market":
            execution_status = "limit_signal_not_auto_executed"
        elif signal is not None and dry_run:
            execution_status = "dry_run_signal_detected"
        elif signal is not None:
            if not confirm_demo:
                raise RuntimeError("confirm_demo=True is required before sending MT5 demo orders.")
            if not account_status["is_demo"]:
                raise RuntimeError("Connected MT5 account does not look like a demo account.")
            execution = self.bridge.place_demo_market_order(
                symbol=symbol,
                side=str(signal["direction"]),
                volume_lots=float(execution_risk_decision["order_volume_lots"]),
                stop_loss=float(signal["stop_price"]),
                take_profit=float(signal["target_price"]),
                deviation_points=deviation_points,
                magic_number=self.MAGIC_NUMBER,
                comment=f"MAXIMO {signal['strategy_variant']}",
            )
            execution_status = "demo_order_sent"

        reasoning_snapshot = self._build_reasoning_snapshot(
            symbol=symbol,
            snapshot=snapshot,
            signal=signal,
            execution_status=execution_status,
            intelligence=intelligence,
            active_watch=active_watch,
            active_watch_metrics=active_watch_metrics,
            watch_execution_policy=watch_execution_policy,
            execution_risk_decision=execution_risk_decision,
            controlled_demo_survival_protocol=controlled_demo_survival_protocol,
            expansion_subtype_pretrade_audit=expansion_subtype_pretrade_audit,
            execution_environment=execution_environment,
            q_learning_decision=q_learning_decision,
        )
        reasoning_snapshot["position_management"] = position_management
        reasoning_snapshot["direction_consistency_guard"] = direction_consistency_guard
        q_learning_update = self.q_learning_memory.record_cycle(
            symbol=symbol,
            intelligence=intelligence,
            active_watch=active_watch,
            active_watch_metrics=active_watch_metrics,
            watch_execution_policy=watch_execution_policy,
            execution_risk_decision=execution_risk_decision,
            signal=signal,
            execution_status=execution_status,
            controlled_demo_survival_protocol=controlled_demo_survival_protocol,
        )
        q_learning_decision["experience_update"] = q_learning_update
        reasoning_snapshot["q_learning_persistent_memory"]["experience_update"] = q_learning_update

        if signal is not None and execution_risk_decision.get("can_execute"):
            self._append_execution_risk_history_event(
                symbol=symbol,
                signal=signal,
                execution_risk_decision=execution_risk_decision,
            )

        self._write_signal(
            signal,
            runtime,
            symbol,
            volume_lots,
            dry_run,
            execution_status,
            intelligence,
            active_watch,
            active_watch_history,
            active_watch_metrics,
            watch_execution_policy,
            execution_risk_decision,
            controlled_demo_survival_protocol,
            expansion_subtype_pretrade_audit,
            q_learning_decision,
            reasoning_snapshot,
            position_management,
            direction_consistency_guard,
        )
        self._write_positions_snapshot(
            account_status=account_status,
            positions=positions,
            execution=execution,
            intelligence=intelligence,
            active_watch=active_watch,
            active_watch_history=active_watch_history,
            active_watch_metrics=active_watch_metrics,
            watch_execution_policy=watch_execution_policy,
            execution_risk_decision=execution_risk_decision,
            controlled_demo_survival_protocol=controlled_demo_survival_protocol,
            expansion_subtype_pretrade_audit=expansion_subtype_pretrade_audit,
            q_learning_decision=q_learning_decision,
            reasoning_snapshot=reasoning_snapshot,
            position_management=position_management,
            direction_consistency_guard=direction_consistency_guard,
        )
        self._append_execution_row(
            signal=signal,
            execution=execution,
            symbol=symbol,
            volume_lots=volume_lots,
            dry_run=dry_run,
            execution_status=execution_status,
            intelligence=intelligence,
            active_watch=active_watch,
            active_watch_history=active_watch_history,
            active_watch_metrics=active_watch_metrics,
            watch_execution_policy=watch_execution_policy,
            execution_risk_decision=execution_risk_decision,
            controlled_demo_survival_protocol=controlled_demo_survival_protocol,
            expansion_subtype_pretrade_audit=expansion_subtype_pretrade_audit,
            q_learning_decision=q_learning_decision,
        )
        decision_source_audit = self._append_decision_source_audit(
            symbol=symbol,
            runtime=runtime,
            signal=signal,
            execution_status=execution_status,
            intelligence=intelligence,
            active_watch=active_watch,
            watch_execution_policy=watch_execution_policy,
            execution_risk_decision=execution_risk_decision,
            account_status=account_status,
        )
        if dry_run:
            self._append_expansion_subtype_pretrade_audit(expansion_subtype_pretrade_audit)
        self._write_report(
            symbol=symbol,
            runtime=runtime,
            account_status=account_status,
            positions=positions,
            snapshot=snapshot,
            signal=signal,
            execution=execution,
            dry_run=dry_run,
            execution_status=execution_status,
            intelligence=intelligence,
            active_watch=active_watch,
            active_watch_history=active_watch_history,
            active_watch_metrics=active_watch_metrics,
            watch_execution_policy=watch_execution_policy,
            execution_risk_decision=execution_risk_decision,
            decision_source_audit=decision_source_audit,
            controlled_demo_survival_protocol=controlled_demo_survival_protocol,
            expansion_subtype_pretrade_audit=expansion_subtype_pretrade_audit,
            q_learning_decision=q_learning_decision,
            reasoning_snapshot=reasoning_snapshot,
            position_management=position_management,
            direction_consistency_guard=direction_consistency_guard,
        )
        self._write_watch_performance_report()

        logger.info(
            "MAXIMO Quant v4 demo run symbol=%s variant=%s dry_run=%s status=%s signal=%s positions=%s",
            symbol,
            runtime["strategy_variant"].code,
            dry_run,
            execution_status,
            bool(signal),
            len(positions),
        )
        return {
            "strategy_name": "MAXIMO MTF Quant Institutional v4",
            "symbol": symbol,
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "dry_run": dry_run,
            "account_is_demo": account_status["is_demo"],
            "execution_status": execution_status,
            "open_positions": len(positions),
            "signal_detected": signal is not None,
            "intelligence_action": readiness.get("action"),
            "operating_posture": posture,
            "harmony_score": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("harmony_score"),
            "watch_trigger": intelligence.get("watch_trigger"),
            "active_watch": active_watch,
            "active_watch_history": active_watch_history,
            "active_watch_metrics": active_watch_metrics,
            "watch_execution_policy": watch_execution_policy,
            "execution_risk_decision": execution_risk_decision,
            "controlled_demo_survival_protocol": controlled_demo_survival_protocol,
            "expansion_subtype_pretrade_audit": expansion_subtype_pretrade_audit,
            "q_learning_decision": q_learning_decision,
            "reasoning_snapshot": reasoning_snapshot,
            "position_management": position_management,
            "direction_consistency_guard": direction_consistency_guard,
            "signal": signal,
            "execution": execution,
            "paths": {
                "latest_signal": str(self.signal_path.resolve()),
                "executions_csv": str(self.executions_path.resolve()),
                "positions_snapshot": str(self.positions_path.resolve()),
                "report_md": str(self.report_path.resolve()),
                "active_watch_json": str(self.active_watch_path.resolve()),
                "active_watch_history_jsonl": str(self.active_watch_history_path.resolve()),
                "expansion_subtype_pretrade_audit_jsonl": str(self.expansion_subtype_pretrade_audit_path.resolve()),
                "q_learning_table": str(self.q_learning_table_path.resolve()),
                "q_learning_replay": str(self.q_learning_replay_path.resolve()),
                "q_learning_report": str(self.q_learning_report_path.resolve()),
            },
        }

    def _manage_open_positions(
        self,
        *,
        symbol: str,
        positions: list[dict],
        snapshot: dict[str, Any],
        dry_run: bool,
    ) -> dict[str, Any]:
        state = self._load_position_management_state()
        current_tickets = {str(item.get("ticket")) for item in positions if item.get("ticket") is not None}
        state = {ticket: payload for ticket, payload in state.items() if ticket in current_tickets}
        actions: list[dict[str, Any]] = []
        updates_sent = 0
        last_price = self._latest_snapshot_price(snapshot)

        for position in positions:
            ticket = str(position.get("ticket") or "")
            if not ticket:
                continue
            side = self._position_side(position)
            entry = float(position.get("price_open") or 0.0)
            current = float(position.get("price_current") or last_price or entry)
            stop = float(position.get("sl") or 0.0)
            target = float(position.get("tp") or 0.0)
            risk = self._position_risk(side=side, entry=entry, stop=stop)
            if risk <= 0:
                actions.append(
                    {
                        "ticket": ticket,
                        "side": side,
                        "action": "skip",
                        "reason": "No hay SL lógico para calcular R y proteger la posición.",
                    }
                )
                continue

            position_state = state.get(ticket, {})
            partial_taken = bool(position_state.get("partial_taken"))
            previous_best = float(position_state.get("best_price") or current)
            best_price = max(previous_best, current) if side == "BUY" else min(previous_best, current)
            current_favorable_r = self._favorable_r(side=side, entry=entry, price=current, risk=risk)
            tp_progress = self._tp_progress(side=side, entry=entry, target=target, price=current)
            max_favorable_r = max(
                float(position_state.get("max_favorable_r") or 0.0),
                self._favorable_r(side=side, entry=entry, price=best_price, risk=risk),
                current_favorable_r,
            )
            desired_sl, protection_level = self._desired_protective_stop(
                side=side,
                entry=entry,
                current=current,
                current_stop=stop,
                risk=risk,
                max_favorable_r=max_favorable_r,
                tp_progress=tp_progress,
            )
            state[ticket] = {
                **position_state,
                "symbol": position.get("symbol") or symbol,
                "side": side,
                "entry": entry,
                "current": current,
                "stop": stop,
                "target": target,
                "best_price": best_price,
                "current_favorable_r": round(current_favorable_r, 4),
                "max_favorable_r": round(max_favorable_r, 4),
                "tp_progress": round(tp_progress, 4),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "protection_level": protection_level,
            }
            if not partial_taken and max_favorable_r >= self.PARTIAL_TRIGGER_R:
                partial_volume = round(float(position.get("volume") or 0.0) * self.PARTIAL_CLOSE_FRACTION, 2)
                if partial_volume > 0:
                    partial_payload = {
                        "ticket": ticket,
                        "side": side,
                        "action": "partial_close",
                        "volume_lots": partial_volume,
                        "trigger_r": self.PARTIAL_TRIGGER_R,
                        "current_favorable_r": round(current_favorable_r, 4),
                        "max_favorable_r": round(max_favorable_r, 4),
                        "reason": "La operación alcanzó zona de beneficio; se toma parcial y se prepara BE.",
                    }
                    if dry_run:
                        partial_payload["sent_to_mt5"] = False
                        partial_payload["reason"] = "Dry-run: se habría tomado parcial, pero no se envía cierre a MT5."
                        state[ticket]["partial_taken"] = True
                    else:
                        try:
                            partial_result = self.bridge.close_position_partial(
                                symbol=str(position.get("symbol") or symbol),
                                ticket=int(position.get("ticket")),
                                side=side.lower(),
                                volume_lots=partial_volume,
                                deviation_points=50,
                                magic_number=self.MAGIC_NUMBER,
                                comment="MAXIMO partial",
                            )
                            partial_payload["sent_to_mt5"] = True
                            partial_payload["mt5_result"] = partial_result.get("result")
                            state[ticket]["partial_taken"] = True
                            updates_sent += 1
                        except Exception as exc:  # pragma: no cover - broker/runtime behavior.
                            partial_payload["sent_to_mt5"] = False
                            partial_payload["error"] = str(exc)
                    actions.append(partial_payload)
            if desired_sl is None:
                actions.append(
                    {
                        "ticket": ticket,
                        "side": side,
                        "action": "monitor",
                        "current_favorable_r": round(current_favorable_r, 4),
                        "max_favorable_r": round(max_favorable_r, 4),
                        "tp_progress": round(tp_progress, 4),
                        "reason": "Aún no hay avance suficiente o el precio ya no permite mover SL sin hacerlo peor.",
                    }
                )
                continue
            action_payload = {
                "ticket": ticket,
                "side": side,
                "action": "protect_sl",
                "current_favorable_r": round(current_favorable_r, 4),
                "max_favorable_r": round(max_favorable_r, 4),
                "old_sl": stop,
                "new_sl": round(desired_sl, 3),
                "tp": target,
                "tp_progress": round(tp_progress, 4),
                "protection_level": protection_level,
                "reason": "La operación avanzó a favor; se protege beneficio con SL dinámico.",
            }
            if dry_run:
                action_payload["sent_to_mt5"] = False
                action_payload["reason"] = "Dry-run: se habría movido el SL, pero no se envía modificación a MT5."
            else:
                try:
                    result = self.bridge.modify_position_sl_tp(
                        symbol=str(position.get("symbol") or symbol),
                        ticket=int(position.get("ticket")),
                        stop_loss=float(desired_sl),
                        take_profit=target,
                        magic_number=self.MAGIC_NUMBER,
                        comment="MAXIMO protect",
                    )
                    action_payload["sent_to_mt5"] = True
                    action_payload["mt5_result"] = result.get("result")
                    updates_sent += 1
                except Exception as exc:  # pragma: no cover - exercised against live MT5/broker behavior.
                    action_payload["sent_to_mt5"] = False
                    action_payload["error"] = str(exc)
            actions.append(action_payload)

        self._save_position_management_state(state)
        return {
            "status": "active" if positions else "inactive",
            "positions_managed": len(positions),
            "updates_sent": updates_sent,
            "dry_run": dry_run,
            "actions": actions,
            "state_path": str(self.position_management_state_path.resolve()),
        }

    def _load_position_management_state(self) -> dict[str, Any]:
        if not self.position_management_state_path.exists():
            return {}
        try:
            payload = json.loads(self.position_management_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_position_management_state(self, state: dict[str, Any]) -> None:
        self.position_management_state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _position_side(position: dict[str, Any]) -> str:
        raw_type = int(position.get("type", 0))
        return "BUY" if raw_type == 0 else "SELL"

    @staticmethod
    def _position_risk(*, side: str, entry: float, stop: float) -> float:
        if side == "BUY":
            return max(0.0, entry - stop)
        return max(0.0, stop - entry)

    @staticmethod
    def _favorable_r(*, side: str, entry: float, price: float, risk: float) -> float:
        if risk <= 0:
            return 0.0
        favorable = price - entry if side == "BUY" else entry - price
        return favorable / risk

    @staticmethod
    def _tp_progress(*, side: str, entry: float, target: float, price: float) -> float:
        distance = abs(target - entry)
        if distance <= 0:
            return 0.0
        progress = (price - entry) / distance if side == "BUY" else (entry - price) / distance
        return max(0.0, min(1.5, progress))

    @staticmethod
    def _latest_snapshot_price(snapshot: dict[str, Any]) -> float | None:
        candles = MaximoQuantV4DemoEngine._snapshot_candles(snapshot, "M1") or MaximoQuantV4DemoEngine._snapshot_candles(snapshot, "M5")
        if not candles:
            return None
        return MaximoQuantV4DemoEngine._candle_value(candles[-1], "close")

    @staticmethod
    def _desired_protective_stop(
        *,
        side: str,
        entry: float,
        current: float,
        current_stop: float,
        risk: float,
        max_favorable_r: float,
        tp_progress: float = 0.0,
    ) -> tuple[float | None, str]:
        if max_favorable_r >= MaximoQuantV4DemoEngine.TRAILING_TRIGGER_R or tp_progress >= MaximoQuantV4DemoEngine.NEAR_TP_TRAIL_PROGRESS:
            lock_r = 0.65 if tp_progress >= MaximoQuantV4DemoEngine.NEAR_TP_TRAIL_PROGRESS else 0.45
            level = "near_tp_trailing" if tp_progress >= MaximoQuantV4DemoEngine.NEAR_TP_TRAIL_PROGRESS else "trail_profit_after_1r"
        elif max_favorable_r >= MaximoQuantV4DemoEngine.PROTECT_TRIGGER_R:
            lock_r = 0.3
            level = "protect_after_0_8r"
        elif max_favorable_r >= MaximoQuantV4DemoEngine.BE_TRIGGER_R:
            lock_r = 0.05
            level = "breakeven_after_0_5r"
        else:
            return None, "monitoring"

        min_distance = max(abs(entry) * 0.00005, 0.05)
        if side == "BUY":
            desired = entry + (risk * lock_r)
            if desired >= current - min_distance or desired <= current_stop:
                return None, level
            return desired, level

        desired = entry - (risk * lock_r)
        if desired <= current + min_distance or desired >= current_stop:
            return None, level
        return desired, level

    def _signal_direction_consistency_guard(
        self,
        *,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        q_learning_decision: dict[str, Any],
    ) -> dict[str, Any]:
        if signal is None:
            return {"allowed": True, "reason": "No hay señal operativa.", "conflicts": []}
        signal_side = str(signal.get("direction") or "").upper()
        if signal_side not in {"BUY", "SELL"}:
            return {"allowed": False, "reason": "La señal no tiene dirección BUY/SELL válida.", "conflicts": ["invalid_signal_side"]}

        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        projection = watch_trigger.get("pattern_projection") or {}
        matrix = projection.get("professional_decision_matrix") or {}
        comparison = projection.get("side_probability_comparison") or {}
        layer_sync = matrix.get("layer_synchronization") or {}
        course_sync = matrix.get("course_learning_sync") or (projection.get("cool_learning_memory") or {}).get("course_alignment") or {}
        expected = {
            "preferred_side": str(market_state.get("preferred_side") or "").upper(),
            "watch_trigger_side": str(watch_trigger.get("side") or "").upper(),
            "active_watch_side": str((active_watch or {}).get("side") or "").upper(),
            "professional_side": str(matrix.get("selected_side") or "").upper(),
            "probability_selected_side": str(comparison.get("selected_side") or "").upper(),
        }
        conflicts = [name for name, side in expected.items() if side in {"BUY", "SELL"} and side != signal_side]
        q_policy = str(q_learning_decision.get("q_policy_action") or q_learning_decision.get("policy_action") or "").upper()
        if q_policy in {"BUY", "SELL"} and q_policy != signal_side:
            conflicts.append("persistent_q_learning_policy")

        if not conflicts:
            return {
                "allowed": True,
                "signal_side": signal_side,
                "expected_sides": expected,
                "conflicts": [],
                "reason": "La señal coincide con la tesis activa y las capas principales.",
            }

        probability_side = (matrix.get("side_assessments") or {}).get(signal_side) or {}
        probability = float(probability_side.get("probability_to_confirm") or 0.0)
        if signal.get("countertrend_reversal_scalp") and probability >= 0.82:
            return {
                "allowed": True,
                "signal_side": signal_side,
                "expected_sides": expected,
                "conflicts": conflicts,
                "reason": (
                    "Se permite entrada contra tesis solo como reversal scalp validado; "
                    "debe gestionarse con parcial, BE y trailing agresivo."
                ),
            }
        elite_override = (
            bool(signal.get("elite_session_alignment"))
            and probability >= 0.88
            and str(layer_sync.get("status") or "") in {"synchronized", "mostly_aligned"}
            and str(course_sync.get("status") or "") in {"aligned", "partial"}
            and len(conflicts) <= 1
        )
        if elite_override:
            return {
                "allowed": True,
                "signal_side": signal_side,
                "expected_sides": expected,
                "conflicts": conflicts,
                "reason": "Se permite cambio de lado solo por alineación élite y confirmación superior.",
            }
        return {
            "allowed": False,
            "signal_side": signal_side,
            "expected_sides": expected,
            "conflicts": conflicts,
            "reason": (
                f"Bloqueado: la señal {signal_side} contradice la tesis activa "
                f"({', '.join(conflicts)}). Esperar nuevo watch/confirmación sincronizada antes de girar el trade."
            ),
        }

    def _build_expansion_subtype_pretrade_audit(self, *, symbol: str, intelligence: dict[str, Any]) -> dict[str, Any]:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        audit = self.expansion_subtype_pretrade_audit.from_market_state(market_state)
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            **audit,
        }

    @staticmethod
    def _disabled_expansion_subtype_pretrade_audit(*, symbol: str) -> dict[str, Any]:
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "audit_name": "EXPANSION_SUBTYPE_PRETRADE_AUDIT_V1",
            "rule": "m5_body_mid_5m",
            "candidate_detected": False,
            "candidate_scope": "NY_AM_SELL_m5_body_mid_5m",
            "reason": "Expansion subtype pretrade telemetry is enabled only in dry-run mode.",
            "features": {},
            "subtype": None,
            "subtype_confidence": 0.0,
            "subtype_reason": "Telemetry disabled outside dry-run.",
            "expected_edge_bucket": "not_applicable",
            "historical_warning": "No live execution, blocking, sizing, or risk change is allowed from this telemetry.",
            "lookahead_safe": True,
            "future_variables_used": [],
        }

    def _append_expansion_subtype_pretrade_audit(self, audit: dict[str, Any]) -> None:
        with self.expansion_subtype_pretrade_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit, ensure_ascii=False) + "\n")

    @staticmethod
    def _inject_ob_aggressive_reduced_signal(
        *,
        intelligence: dict[str, Any],
        signal: dict[str, Any],
    ) -> dict[str, Any]:
        return MaximoQuantV4DemoEngine._inject_reduced_learning_signal(
            intelligence=intelligence,
            signal=signal,
            rationale="OB_AGGRESSIVE_REDUCED_SIGNAL habilita ejecución reducida sin convertirla en señal institucional.",
        )

    @staticmethod
    def _inject_reduced_learning_signal(
        *,
        intelligence: dict[str, Any],
        signal: dict[str, Any],
        rationale: str,
    ) -> dict[str, Any]:
        updated = dict(intelligence)
        overview = dict(updated["overview"])
        readiness = dict(updated["execution_readiness"])
        overview["signal"] = signal
        readiness["action"] = "EXECUTE"
        readiness["risk_mode"] = "reduced"
        readiness["can_execute_demo_now"] = True
        readiness["confidence"] = max(float(readiness.get("confidence") or 0.0), float(signal.get("confidence", 0.0)) / 100.0)
        readiness["rationale"] = list(readiness.get("rationale", [])) + [rationale]
        updated["overview"] = overview
        updated["execution_readiness"] = readiness
        return updated

    @staticmethod
    def _build_ob_aggressive_reduced_signal(
        *,
        symbol: str,
        runtime: dict[str, Any],
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        watch_execution_policy: dict[str, Any],
    ) -> dict[str, Any] | None:
        market_state = intelligence["overview"]["market_state"]
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        candidate = aggressive.get("reduced_signal_candidate") or {}
        readiness = intelligence["execution_readiness"]
        confidence = float(readiness.get("confidence") or 0.0)
        setup_maturity = float(readiness.get("setup_maturity") or 0.0)

        if market_state.get("operational_family") != "OB_REJECTION_AGGRESSIVE_WATCH":
            return None
        if active_watch is None or active_watch.get("operational_family") != "OB_REJECTION_AGGRESSIVE_WATCH":
            return None
        if watch_execution_policy.get("watch_policy_action") != "PREPARE_REDUCED":
            return None
        if watch_execution_policy.get("allowed_risk_mode") != "reduced":
            return None
        if setup_maturity < 75.0 or confidence < 0.75:
            return None
        if not candidate.get("sl_logical_available") or not candidate.get("rr_evaluable"):
            return None
        if float(candidate.get("wick_rejection_quality") or 0.0) < 0.58:
            return None
        if float(candidate.get("displacement_score") or 0.0) < 75.0:
            return None
        if not (candidate.get("micro_bos") or candidate.get("continuation_momentum")):
            return None
        if intelligence["event_risk"].get("action") != "allow":
            return None
        if not market_state.get("allowed_hour_by_strategy", False):
            return None
        blocked = set(readiness.get("blockers", []))
        if blocked & {"high_impact_event_window", "hour_not_allowed", "chop_regime", "weak_knowledge_harmony"}:
            return None

        direction = str(candidate["direction"]).lower()
        signal = {
            "entry_kind": "market",
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "symbol": symbol,
            "timeframe": "M5",
            "signal_time": candidate.get("signal_time"),
            "entry_time": candidate.get("entry_time"),
            "direction": direction,
            "setup_type": candidate.get("setup_type") or "AGG_REDUCED",
            "signal_type": candidate.get("signal_type") or "OB_AGGRESSIVE_REDUCED_SIGNAL",
            "active_family": candidate.get("active_family") or "OB_REJECTION_AGGRESSIVE_WATCH",
            "entry_price": candidate["entry_price"],
            "stop_price": candidate["stop_price"],
            "target_price": candidate["target_price"],
            "risk_per_unit": candidate["risk_per_unit"],
            "selected_rr": candidate["selected_rr"],
            "quant_score": market_state.get("quant_score"),
            "impulse_score": market_state.get("impulse_score"),
            "buy_mtf_score": market_state.get("buy_mtf_score"),
            "sell_mtf_score": market_state.get("sell_mtf_score"),
            "confidence": round(confidence * 100),
            "market_regime": market_state.get("market_regime"),
            "hour_ny": market_state.get("hour_ny"),
            "preferred_side": market_state.get("preferred_side"),
            "risk_mode": "reduced",
            "reduced_signal_reason": candidate.get("reduced_signal_reason"),
            "wick_rejection_quality": candidate.get("wick_rejection_quality"),
            "displacement_score": candidate.get("displacement_score"),
            "micro_bos": candidate.get("micro_bos"),
            "micro_choch": candidate.get("micro_choch"),
            "continuation_momentum": candidate.get("continuation_momentum"),
            "manual_bias_confirmation": candidate.get("manual_bias_confirmation", False),
            "defensive_management_plan": ob_aggressive_defensive_management_plan(),
        }
        return signal

    def _build_session_q_learning_reduced_signal(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        intelligence: dict[str, Any],
        snapshot: dict[str, Any],
        active_watch: dict[str, Any] | None,
        watch_execution_policy: dict[str, Any],
    ) -> dict[str, Any] | None:
        readiness = intelligence.get("execution_readiness", {}) or {}
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        projection = watch_trigger.get("pattern_projection") or {}
        matrix = projection.get("professional_decision_matrix") or {}
        session_opportunity = projection.get("session_opportunity") or matrix.get("session_opportunity") or {}
        side = str(matrix.get("selected_side") or watch_trigger.get("side") or market_state.get("preferred_side") or "").upper()
        if side not in {"BUY", "SELL"}:
            return None
        if active_watch is None or str(active_watch.get("status") or "").upper() not in {"ACTIVE", "TRIGGERED"}:
            return None
        active_watch_side = str(active_watch.get("side") or "").upper()
        watch_trigger_side = str(watch_trigger.get("side") or "").upper()
        market_preferred_side = str(market_state.get("preferred_side") or "").upper()
        side_mismatches = [
            name
            for name, expected_side in {
                "active_watch_side": active_watch_side,
                "watch_trigger_side": watch_trigger_side,
                "market_preferred_side": market_preferred_side,
            }.items()
            if expected_side in {"BUY", "SELL"} and expected_side != side
        ]
        if str(readiness.get("action") or "").upper() != "WATCH":
            return None
        if intelligence.get("event_risk", {}).get("action") != "allow":
            return None
        if not market_state.get("allowed_hour_by_strategy", False):
            return None
        if watch_execution_policy.get("watch_policy_action") not in {"PREPARE_REDUCED", "PREPARE_NORMAL"}:
            return None
        setup_maturity = float(readiness.get("setup_maturity") or 0.0)
        layer_sync = (matrix.get("layer_synchronization") or {})
        cool_memory = projection.get("q_learning_memory") or projection.get("cool_learning_memory") or {}
        course_sync = matrix.get("course_learning_sync") or cool_memory.get("course_alignment") or {}
        missing_for_execute = [str(item) for item in watch_trigger.get("missing_for_execute", [])]
        unresolved_blocking_missing = [
            item
            for item in missing_for_execute
            if "Falta señal operativa confirmada" not in item
        ]
        course_status = str(course_sync.get("status") or "")
        course_score = float(course_sync.get("course_score") or 0.0)
        q_policy = str(cool_memory.get("policy_action") or cool_memory.get("q_policy_action") or "").upper()
        q_quality = str(cool_memory.get("policy_quality") or "")
        layer_status = str(layer_sync.get("status") or "")
        elite_session_alignment = (
            setup_maturity >= 75.0
            and float(session_opportunity.get("score") or 0.0) >= 0.85
            and layer_status in {"synchronized", "mostly_aligned"}
            and course_status in {"aligned", "partial"}
            and course_score >= 0.6
            and q_policy == side
            and q_quality in {"moderate", "strong"}
        )
        if not elite_session_alignment:
            return None
        if unresolved_blocking_missing:
            return None
        if float(readiness.get("confidence") or 0.0) < 0.66:
            return None
        blocked = set(readiness.get("blockers", []))
        if blocked & {"high_impact_event_window", "hour_not_allowed", "chop_regime", "weak_knowledge_harmony"}:
            return None
        if str(session_opportunity.get("readiness") or "") not in {"armed", "execute_ready"}:
            return None
        if float(session_opportunity.get("score") or 0.0) < 0.68:
            return None
        side_assessment = (matrix.get("side_assessments") or {}).get(side) or {}
        if float(side_assessment.get("probability_to_confirm") or 0.0) < 0.72:
            return None
        if side_assessment.get("historical_bias") not in {"favorable", "mixed"}:
            return None
        structure = side_assessment.get("structure_read") or {}
        liquidity = side_assessment.get("liquidity_read") or {}
        micro_confirmed = bool(structure.get("micro_bos") or structure.get("micro_choch"))
        liquidity_confirmed = bool(
            liquidity.get("liquidity_sweep_or_grab")
            or float(liquidity.get("wick_rejection_quality") or 0.0) >= 60.0
        )
        if not micro_confirmed or not liquidity_confirmed:
            return None
        countertrend_scalp = self._countertrend_scalp_reversal_check(
            side=side,
            side_mismatches=side_mismatches,
            side_assessment=side_assessment,
            structure=structure,
            liquidity=liquidity,
            layer_sync=layer_sync,
            course_sync=course_sync,
            cool_memory=cool_memory,
        )
        if side_mismatches and not countertrend_scalp["valid"]:
            return None
        if not (structure.get("displacement") or structure.get("continuation_momentum")):
            return None

        candles = MaximoQuantV4DemoEngine._snapshot_candles(snapshot, "M5")
        if len(candles) < 12:
            return None
        recent = candles[-12:]
        entry = MaximoQuantV4DemoEngine._candle_value(recent[-1], "close")
        recent_high = max(MaximoQuantV4DemoEngine._candle_value(item, "high") for item in recent)
        recent_low = min(MaximoQuantV4DemoEngine._candle_value(item, "low") for item in recent)
        recent_range = max(0.001, recent_high - recent_low)
        buffer = max(recent_range * 0.08, abs(entry) * 0.00015)
        rr = 0.95 if countertrend_scalp["valid"] else 1.35 if float(side_assessment.get("probability_to_confirm") or 0.0) >= 0.8 else 1.2
        if side == "SELL":
            stop = recent_high + buffer
            risk = stop - entry
            target = entry - risk * rr
            direction = "sell"
        else:
            stop = recent_low - buffer
            risk = entry - stop
            target = entry + risk * rr
            direction = "buy"
        if risk <= 0:
            return None
        return {
            "entry_kind": "market",
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "symbol": symbol,
            "timeframe": "M5",
            "signal_time": MaximoQuantV4DemoEngine._extract_current_candle_time(snapshot),
            "entry_time": MaximoQuantV4DemoEngine._extract_current_candle_time(snapshot),
            "direction": direction,
            "setup_type": "QL_SESSION_REDUCED",
            "signal_type": "SESSION_Q_LEARNING_REDUCED_SIGNAL",
            "active_family": "Q_LEARNING_SESSION_PATTERN_MEMORY",
            "entry_price": round(entry, 3),
            "stop_price": round(stop, 3),
            "target_price": round(target, 3),
            "risk_per_unit": round(risk, 3),
            "selected_rr": round(rr, 2),
            "quant_score": market_state.get("quant_score"),
            "impulse_score": market_state.get("impulse_score"),
            "buy_mtf_score": market_state.get("buy_mtf_score"),
            "sell_mtf_score": market_state.get("sell_mtf_score"),
            "confidence": round(max(float(readiness.get("confidence") or 0.0), float(session_opportunity.get("score") or 0.0)) * 100),
            "market_regime": market_state.get("market_regime"),
            "hour_ny": market_state.get("hour_ny"),
            "session_tags": session_opportunity.get("session_tags"),
            "preferred_side": market_state.get("preferred_side"),
            "risk_mode": "reduced",
            "countertrend_reversal_scalp": countertrend_scalp["valid"],
            "countertrend_scalp_reason": countertrend_scalp["reason"],
            "session_opportunity_score": session_opportunity.get("score"),
            "elite_session_alignment": elite_session_alignment,
            "q_learning_memory_alignment": True,
            "reduced_signal_reason": (
                "Sesión London/NY con patrón preparado, analogías históricas útiles, memoria de cursos/Q-learning "
                "y SL/RR calculables desde estructura M5 reciente."
            ),
            "defensive_management_plan": {
                "entry_management": (
                    "Countertrend scalp: entrada solo con precisión de reversión y salida rápida."
                    if countertrend_scalp["valid"]
                    else "Ejecutar solo reducido; si la vela siguiente absorbe el impulso, salida defensiva."
                ),
                "profit_management": "Parcial en +0.5R, SL a BE/protección y trailing agresivo cuando se acerque al TP.",
                "emergency_exit": "Cerrar/proteger si aparece vela contraria fuerte, macro cambia o el spread/slippage se degrada.",
            },
        }

    @staticmethod
    def _countertrend_scalp_reversal_check(
        *,
        side: str,
        side_mismatches: list[str],
        side_assessment: dict[str, Any],
        structure: dict[str, Any],
        liquidity: dict[str, Any],
        layer_sync: dict[str, Any],
        course_sync: dict[str, Any],
        cool_memory: dict[str, Any],
    ) -> dict[str, Any]:
        if not side_mismatches:
            return {"valid": False, "reason": "No es una entrada contra tesis; no aplica scalp reversal."}
        probability = float(side_assessment.get("probability_to_confirm") or 0.0)
        wick_quality = float(liquidity.get("wick_rejection_quality") or 0.0)
        liquidity_sweep = bool(liquidity.get("liquidity_sweep_or_grab"))
        structure_confirmed = bool(
            structure.get("micro_bos")
            or structure.get("micro_choch")
            or structure.get("displacement")
            or structure.get("continuation_momentum")
        )
        course_status = str(course_sync.get("status") or "")
        q_policy = str(cool_memory.get("policy_action") or cool_memory.get("q_policy_action") or "").upper()
        layer_status = str(layer_sync.get("status") or "")
        valid = (
            probability >= 0.82
            and (liquidity_sweep or wick_quality >= 65.0)
            and structure_confirmed
            and side_assessment.get("historical_bias") in {"favorable", "mixed"}
            and (course_status in {"aligned", "partial"} or q_policy == side)
            and layer_status in {"synchronized", "mostly_aligned", "partial"}
        )
        if valid:
            reason = (
                "Reversión/scalp contra tesis permitida: probabilidad alta, reacción de liquidez/wick, "
                "estructura micro confirmada y memoria suficientemente alineada."
            )
        else:
            reason = (
                "Entrada contra tesis bloqueada: necesita prob>=0.82, liquidez/rechazo fuerte, "
                "micro BOS/CHOCH/desplazamiento y apoyo de cursos/Q-learning."
            )
        return {"valid": valid, "reason": reason, "mismatches": side_mismatches}

    @staticmethod
    def _snapshot_candles(snapshot: dict[str, Any], timeframe: str) -> list[Any]:
        candles = snapshot.get("candles", {}).get(timeframe) if isinstance(snapshot.get("candles"), dict) else None
        return list(candles or [])

    @staticmethod
    def _candle_value(candle: Any, field: str) -> float:
        if isinstance(candle, dict):
            return float(candle[field])
        return float(getattr(candle, field))

    def _load_runtime(self) -> dict[str, Any]:
        if not self.strategy_snapshot_path.exists():
            raise RuntimeError(f"Best strategy snapshot not found: {self.strategy_snapshot_path}")
        snapshot = json.loads(self.strategy_snapshot_path.read_text(encoding="utf-8"))
        strategy_code = str(snapshot["best_variant_code"])
        session_code = str(snapshot.get("session_variant", "all"))
        analyzer = MaximoQuantV4YearlyAnalyzer(
            input_dir=self.settings.paths.data_dir / "backtests" / "input",
            backtests_dir=self.settings.paths.data_dir / "backtests",
            strategies_dir=self.settings.paths.data_dir / "strategies",
        )
        resolved = analyzer._resolve_runtime_variant(
            strategy_variant_code=strategy_code,
            session_variant_code=session_code,
        )
        resolved["strategy_variant"] = self._overlay_strategy_variant_from_snapshot(
            strategy_variant=resolved["strategy_variant"],
            snapshot=snapshot,
        )
        resolved["snapshot"] = snapshot
        return resolved

    @staticmethod
    def _overlay_strategy_variant_from_snapshot(
        *,
        strategy_variant: StrategyVariant,
        snapshot: dict[str, Any],
    ) -> StrategyVariant:
        parameters = snapshot.get("parameters", {}) if isinstance(snapshot, dict) else {}
        if not isinstance(parameters, dict) or not parameters:
            return strategy_variant

        overrides: dict[str, Any] = {}
        scalar_keys = (
            "code",
            "label",
            "a_plus_only",
            "require_preferred_side",
            "disallow_chop",
            "min_quant_score",
            "min_impulse_score",
            "require_recent_compression_for_agg",
            "require_quant_expansion",
            "require_recent_compression",
            "min_atr_ratio",
            "min_range_ratio",
            "max_atr_ratio",
            "max_range_ratio",
        )
        for key in scalar_keys:
            if key in parameters:
                overrides[key] = parameters[key]

        set_keys = ("allowed_directions", "allowed_setup_types")
        for key in set_keys:
            if key in parameters:
                value = parameters.get(key)
                overrides[key] = set(value) if value else None

        int_set_keys = ("allowed_hours_ny", "excluded_hours_ny", "disallow_normal_hours_ny")
        for key in int_set_keys:
            if key in parameters:
                value = parameters.get(key)
                overrides[key] = {int(item) for item in value} if value else None

        return replace(strategy_variant, **overrides) if overrides else strategy_variant

    def _latest_signal(
        self,
        *,
        symbol: str,
        backtester: MaximoMTFQuantV4Backtester,
        strategy_variant: StrategyVariant,
        session_variant: Any,
        snapshot: dict[str, list[Any]],
    ) -> dict[str, Any] | None:
        m5 = snapshot.get("M5", [])
        h1 = snapshot.get("H1", [])
        if len(m5) < 250 or len(h1) < 250:
            return None
        m15 = backtester._resample(m5, "M15")
        h4 = backtester._resample(h1, "H4")
        return backtester.latest_snapshot_signal(
            symbol=symbol,
            timeframe="M5",
            entry_candles=m5,
            context={
                "macro": backtester._context_pack(h4),
                "trend": backtester._context_pack(h1),
                "setup": backtester._context_pack(m15),
            },
            session_variant=session_variant,
            strategy_variant=strategy_variant,
        )

    def _read_execution_environment(self, *, symbol: str) -> dict[str, Any]:
        if not hasattr(self.bridge, "read_execution_environment"):
            return {
                "execution_viability": "UNKNOWN",
                "reason": "Bridge does not expose read_execution_environment.",
            }
        try:
            return self.bridge.read_execution_environment(symbol=symbol)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - defensive runtime telemetry path.
            return {
                "execution_viability": "UNSAFE",
                "error": str(exc),
                "reason": "Unable to read live execution environment.",
            }

    def _evaluate_controlled_demo_survival_protocol(
        self,
        *,
        symbol: str,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        execution_environment: dict[str, Any],
    ) -> dict[str, Any]:
        return self.controlled_demo_protocol.evaluate(
            symbol=symbol,
            signal=signal,
            market_state=intelligence["overview"]["market_state"],
            event_risk=intelligence["event_risk"],
            execution_environment=execution_environment,
        )

    def _build_reasoning_snapshot(
        self,
        *,
        symbol: str,
        snapshot: dict[str, Any],
        signal: dict[str, Any] | None,
        execution_status: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        active_watch_metrics: dict[str, Any],
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        controlled_demo_survival_protocol: dict[str, Any],
        expansion_subtype_pretrade_audit: dict[str, Any],
        execution_environment: dict[str, Any],
        q_learning_decision: dict[str, Any],
    ) -> dict[str, Any]:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        readiness = intelligence.get("execution_readiness", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        pattern_projection = watch_trigger.get("pattern_projection") or {}
        event_risk = intelligence.get("event_risk", {}) or {}
        harmony = intelligence.get("overview", {}).get("knowledge_alignment", {}).get("harmony", {}) or {}
        features = expansion_subtype_pretrade_audit.get("features", {}) or {}
        protocol_env = controlled_demo_survival_protocol.get("environment", {}) or {}
        side = str(watch_trigger.get("side") or market_state.get("preferred_side") or (signal or {}).get("direction") or "NONE").upper()
        setup_maturity = float(watch_trigger.get("setup_maturity") or readiness.get("setup_maturity") or 0.0)
        confidence = float(watch_trigger.get("confidence") or readiness.get("confidence") or 0.0)
        harmony_score = float(watch_trigger.get("harmony_score") or harmony.get("harmony_score") or 0.0)
        signal_detected = signal is not None or bool(watch_trigger.get("signal_detected"))
        reduced_candidate = (
            watch_trigger.get("ob_rejection_families", {})
            .get("aggressive", {})
            .get("reduced_signal_candidate")
            if watch_trigger
            else None
        ) or {}
        logical_sl = bool((signal or {}).get("stop_price")) or bool(reduced_candidate.get("sl_logical_available"))
        rr_evaluable = bool((signal or {}).get("selected_rr")) or bool(reduced_candidate.get("rr_evaluable"))
        event_allow = event_risk.get("action") == "allow" or watch_trigger.get("macro_event_status") == "allow"
        spread_safe = execution_environment.get("execution_viability") == "SAFE"
        htf_bias = str(watch_trigger.get("higher_timeframe_bias") or market_state.get("higher_timeframe_bias") or "UNKNOWN").upper()
        htf_ok = htf_bias in {side, "BOTH", "MIXED"} or (side in {"BUY", "SELL"} and htf_bias not in {"UNKNOWN", "NEUTRAL", "BUY" if side == "SELL" else "SELL"})
        missing = list(watch_trigger.get("missing_for_execute", []))
        critical_blocks = list(readiness.get("blockers", []))
        if not spread_safe:
            missing.append(
                f"Condición de ejecución no segura: spread/slippage {execution_environment.get('live_spread')} / {execution_environment.get('slippage_estimated')}."
            )
        if controlled_demo_survival_protocol.get("applies") and not controlled_demo_survival_protocol.get("allowed"):
            missing.append("El protocolo demo controlado todavía no permite esta familia/edge.")

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "state": {
                "action": readiness.get("action"),
                "execution_status": execution_status,
                "preferred_side": side,
                "signal_detected": signal_detected,
                "operating_posture": harmony.get("operating_posture"),
                "summary": self._reasoning_summary(
                    action=str(readiness.get("action")),
                    side=side,
                    setup_maturity=setup_maturity,
                    confidence=confidence,
                    signal_detected=signal_detected,
                    execution_status=execution_status,
                ),
            },
            "timeframe_reading": self._timeframe_reasoning(snapshot),
            "market_coverage_assurance": self._market_coverage_assurance(
                snapshot=snapshot,
                intelligence=intelligence,
                watch_trigger=watch_trigger,
                pattern_projection=pattern_projection,
                q_learning_decision=q_learning_decision,
                signal=signal,
                execution_risk_decision=execution_risk_decision,
            ),
            "market_context": {
                "session": protocol_env.get("session"),
                "hour_ny": protocol_env.get("hour_ny"),
                "higher_timeframe_bias": htf_bias,
                "market_regime": watch_trigger.get("market_regime") or signal.get("market_regime") if signal else watch_trigger.get("market_regime"),
                "volatility": watch_trigger.get("volatility"),
                "atr_regime": protocol_env.get("atr_regime"),
                "atr_ratio": protocol_env.get("atr_ratio") or features.get("atr_ratio"),
                "expansion_subtype": features.get("expansion_subtype"),
                "continuation_quality": features.get("continuation_quality"),
                "macro_event_action": event_risk.get("action"),
                "execution_viability": execution_environment.get("execution_viability"),
                "live_spread": execution_environment.get("live_spread"),
                "slippage_estimated": execution_environment.get("slippage_estimated"),
            },
            "setup_assessment": {
                "setup_detected": watch_trigger.get("setup_detected") or (signal or {}).get("setup_type"),
                "operational_family": watch_trigger.get("operational_family") or (signal or {}).get("active_family"),
                "trigger_type": watch_trigger.get("trigger_type"),
                "candidate_side": pattern_projection.get("candidate_side") or watch_trigger.get("candidate_side"),
                "setup_maturity": setup_maturity,
                "confidence": confidence,
                "harmony_score": harmony_score,
                "watch_health": active_watch_metrics.get("watch_health"),
                "watch_probability_to_execute": active_watch_metrics.get("watch_probability_to_execute"),
                "watch_policy_action": watch_execution_policy.get("watch_policy_action"),
                "allowed_risk_mode": execution_risk_decision.get("allowed_risk_mode"),
                "max_risk_multiplier": execution_risk_decision.get("max_risk_multiplier"),
            },
            "q_learning_persistent_memory": {
                "status": q_learning_decision.get("status"),
                "learning_method": q_learning_decision.get("learning_method"),
                "state_key": q_learning_decision.get("state_key"),
                "q_policy_action": q_learning_decision.get("q_policy_action"),
                "q_values": q_learning_decision.get("q_values"),
                "value_gap": q_learning_decision.get("value_gap"),
                "risk_bias": q_learning_decision.get("risk_bias"),
                "experience_count": q_learning_decision.get("experience_count"),
                "replay_count": q_learning_decision.get("replay_count"),
                "reason": q_learning_decision.get("reason"),
                "safety_note": q_learning_decision.get("safety_note"),
            },
            "learned_pattern_projection": {
                "dominant_family": pattern_projection.get("dominant_family"),
                "operational_family": pattern_projection.get("operational_family"),
                "candidate_side": pattern_projection.get("candidate_side"),
                "preferred_side": pattern_projection.get("preferred_side"),
                "higher_timeframe_bias": pattern_projection.get("higher_timeframe_bias"),
                "probable_market_move": pattern_projection.get("probable_market_move"),
                "near_execute_watch": pattern_projection.get("near_execute_watch"),
                "maturity_gap_to_execute": pattern_projection.get("maturity_gap_to_execute"),
                "interpretation": pattern_projection.get("interpretation"),
                "pattern_matches": list(pattern_projection.get("pattern_matches", [])),
                "evidence": list(pattern_projection.get("evidence", [])),
                "confirmation_focus": list(pattern_projection.get("confirmation_focus", [])),
                "missing_confirmations": list(pattern_projection.get("missing_confirmations", [])),
                "historical_analogs": pattern_projection.get("historical_analogs", {}),
                "side_probability_comparison": pattern_projection.get("side_probability_comparison", {}),
                "cool_learning_memory": pattern_projection.get("cool_learning_memory", {}),
                "q_learning_memory": pattern_projection.get("q_learning_memory", pattern_projection.get("cool_learning_memory", {})),
                "professional_decision_matrix": pattern_projection.get("professional_decision_matrix", {}),
            },
            "condition_checklist": [
                self._reasoning_condition("preferred_side", side in {"BUY", "SELL"}, f"Lado preferido actual: {side}."),
                self._reasoning_condition("setup_maturity_prepare", setup_maturity >= 69, f"Madurez actual {round(setup_maturity, 2)}; PREPARE requiere 69."),
                self._reasoning_condition("setup_maturity_execute", setup_maturity >= 75, f"Madurez actual {round(setup_maturity, 2)}; EXECUTE requiere 75."),
                self._reasoning_condition("signal_detected", signal_detected, "Debe aparecer señal final confirmada."),
                self._reasoning_condition("higher_timeframe_bias", htf_ok, f"Bias mayor: {htf_bias}; lado esperado: {side}."),
                self._reasoning_condition("logical_stop_loss", logical_sl, "Debe existir stop loss lógico."),
                self._reasoning_condition("risk_reward_evaluable", rr_evaluable, "Debe existir RR evaluable."),
                self._reasoning_condition("macro_event_allow", event_allow, f"event_action={event_risk.get('action')}."),
                self._reasoning_condition("execution_viability", spread_safe, f"execution_viability={execution_environment.get('execution_viability')}."),
                self._reasoning_condition("critical_blocks_clear", not critical_blocks, f"critical_blocks={critical_blocks or []}."),
            ],
            "waiting_for": self._dedupe_reasoning_items(missing or ["Esperando nueva vela/trigger con confirmación suficiente."]),
            "cancel_if": list(watch_trigger.get("cancel_conditions", [])),
            "next_confirmation_expected": self._next_confirmation_expected(side=side, watch_trigger=watch_trigger),
        }

    def _market_coverage_assurance(
        self,
        *,
        snapshot: dict[str, Any],
        intelligence: dict[str, Any],
        watch_trigger: dict[str, Any],
        pattern_projection: dict[str, Any],
        q_learning_decision: dict[str, Any],
        signal: dict[str, Any] | None,
        execution_risk_decision: dict[str, Any],
    ) -> dict[str, Any]:
        timeframes = snapshot.get("timeframes") or {}
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        knowledge_alignment = intelligence.get("overview", {}).get("knowledge_alignment", {}) or {}
        ob_families = watch_trigger.get("ob_rejection_families") or market_state.get("ob_rejection_families") or {}
        professional = pattern_projection.get("professional_decision_matrix") or {}
        selected_side = str(
            professional.get("selected_side")
            or pattern_projection.get("candidate_side")
            or watch_trigger.get("candidate_side")
            or market_state.get("preferred_side")
            or "NONE"
        ).upper()
        side_assessment = (professional.get("side_assessments") or {}).get(selected_side, {}) or {}
        liquidity_read = side_assessment.get("liquidity_read") or {}
        structure_read = side_assessment.get("structure_read") or {}
        course = (
            pattern_projection.get("course_learning_sync")
            or (pattern_projection.get("cool_learning_memory") or {}).get("course_alignment")
            or {}
        )
        analogs = pattern_projection.get("historical_analogs") or {}
        management = professional.get("management_plan") or {}

        corners = {
            "multi_timeframe": {
                "status": "active" if {"M1", "M5", "H1"}.issubset(set(map(str, timeframes.keys()))) else "partial",
                "timeframes_seen": list(timeframes.keys()),
                "purpose": "M1 para timing, M5 para trigger/setup, H1 para sesgo mayor.",
            },
            "zones_order_blocks": {
                "status": "active" if ob_families else "watching",
                "active_family": ob_families.get("active_family") or watch_trigger.get("operational_family"),
                "setup_detected": watch_trigger.get("setup_detected") or (signal or {}).get("setup_type"),
                "dominant_family": pattern_projection.get("dominant_family"),
            },
            "liquidity_structure": {
                "status": "active" if liquidity_read or structure_read else "watching",
                "liquidity_read": liquidity_read,
                "structure_read": structure_read,
                "confirmation_focus": list(pattern_projection.get("confirmation_focus", []))[:3],
            },
            "memory_probability": {
                "status": "active" if q_learning_decision.get("q_policy_action") or analogs else "watching",
                "q_policy_action": q_learning_decision.get("q_policy_action"),
                "q_values": q_learning_decision.get("q_values"),
                "historical_bias": analogs.get("bias"),
                "historical_win_rate": analogs.get("win_rate"),
                "course_status": course.get("status"),
                "course_score": course.get("course_score"),
                "knowledge_support_score": knowledge_alignment.get("support_score"),
            },
        }
        active_count = sum(1 for corner in corners.values() if corner["status"] == "active")
        return {
            "status": "synchronized" if active_count >= 3 else "partial",
            "active_corners": active_count,
            "selected_side": selected_side,
            "probable_market_move": pattern_projection.get("probable_market_move"),
            "best_option_reason": professional.get("best_option_reason"),
            "wait_for": professional.get("wait_for_liquidity_volatility") or pattern_projection.get("missing_confirmations"),
            "management_sync": {
                "risk_mode": execution_risk_decision.get("allowed_risk_mode"),
                "target_risk_percent": execution_risk_decision.get("account_risk_percent"),
                "max_account_risk_percent": self.MAX_ACCOUNT_RISK_PERCENT_PER_TRADE,
                "sl_strategy": "logical_stop_required",
                "take_profit_plan": management.get("take_profit_plan"),
                "trailing_plan": management.get("trailing_plan"),
                "emergency_exit": management.get("emergency_exit"),
            },
            "corners": corners,
        }

    @staticmethod
    def _reasoning_condition(name: str, passed: bool, explanation: str) -> dict[str, Any]:
        return {"name": name, "status": "passed" if passed else "waiting", "passed": passed, "explanation": explanation}

    @staticmethod
    def _dedupe_reasoning_items(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = str(item).strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    @staticmethod
    def _reasoning_summary(
        *,
        action: str,
        side: str,
        setup_maturity: float,
        confidence: float,
        signal_detected: bool,
        execution_status: str,
    ) -> str:
        if signal_detected and action == "EXECUTE":
            return f"El sistema detectó señal {side} ejecutable; estado de ejecución: {execution_status}."
        if action == "WATCH":
            return (
                f"El sistema mantiene una idea {side} en observación: madurez {round(setup_maturity, 2)}, "
                f"confianza {round(confidence, 4)}; espera confirmación final."
            )
        if action == "BLOCKED":
            return "El sistema considera el contexto bloqueado; no debe preparar orden."
        return f"Estado operativo {action}; sin ejecución inmediata."

    @staticmethod
    def _next_confirmation_expected(*, side: str, watch_trigger: dict[str, Any]) -> str:
        if side == "SELL":
            return "Cierre M5 bajista con continuidad/rechazo, idealmente rompiendo microestructura o confirmando desplazamiento bajista."
        if side == "BUY":
            return "Cierre M5 alcista con continuidad/rechazo, idealmente rompiendo microestructura o confirmando desplazamiento alcista."
        required = watch_trigger.get("required_conditions", [])
        return str(required[0]) if required else "Esperar que el mercado defina lado y trigger."

    @staticmethod
    def _timeframe_reasoning(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        roles = {
            "M1": "micro_trigger_and_execution_timing",
            "M5": "entry_setup_and_confirmation",
            "M15": "setup_context",
            "H1": "higher_timeframe_bias",
            "H4": "macro_context",
        }
        readings: list[dict[str, Any]] = []
        for timeframe, details in (snapshot.get("timeframes") or {}).items():
            readings.append(
                {
                    "timeframe": timeframe,
                    "role": roles.get(str(timeframe), "context"),
                    "bars": details.get("bars"),
                    "first_bar_time": details.get("first_bar_time"),
                    "last_bar_time": details.get("last_bar_time"),
                    "what_it_is_used_for": {
                        "M1": "Afinar entrada y confirmar micro impulso.",
                        "M5": "Decidir si hay vela de confirmación y setup operativo.",
                        "H1": "Validar sesgo mayor y evitar operar contra contexto principal.",
                    }.get(str(timeframe), "Apoyar contexto multi-timeframe."),
                }
            )
        return readings

    @staticmethod
    def _apply_controlled_demo_survival_protocol(
        *,
        execution_risk_decision: dict[str, Any],
        controlled_demo_survival_protocol: dict[str, Any],
    ) -> dict[str, Any]:
        if not controlled_demo_survival_protocol.get("applies"):
            decision = dict(execution_risk_decision)
            decision["controlled_demo_survival_protocol"] = controlled_demo_survival_protocol
            return decision

        if not controlled_demo_survival_protocol.get("allowed"):
            decision = dict(execution_risk_decision)
            decision.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "risk_binding_source": "controlled_demo_survival_protocol_v1",
                    "decision": "blocked_by_controlled_demo_survival_protocol",
                    "execution_mode": "blocked_by_controlled_demo_survival_protocol",
                    "risk_application_reason": (
                        "CONTROLLED_DEMO_SURVIVAL_PROTOCOL_V1 bloqueó la validación demo: "
                        + ", ".join(controlled_demo_survival_protocol.get("blockers", []))
                    ),
                    "execution_status": "blocked_by_controlled_demo_survival_protocol",
                    "controlled_demo_survival_protocol": controlled_demo_survival_protocol,
                }
            )
            return decision

        decision = dict(execution_risk_decision)
        decision.update(
            {
                "allowed_risk_mode": "reduced",
                "max_risk_multiplier": min(
                    float(decision.get("max_risk_multiplier") or 0.5),
                    float(controlled_demo_survival_protocol.get("max_risk_multiplier") or 0.5),
                ),
                "risk_binding_source": "controlled_demo_survival_protocol_v1",
                "execution_mode": "controlled_demo_reduced_execution",
                "risk_application_reason": (
                    "CONTROLLED_DEMO_SURVIVAL_PROTOCOL_V1 permite solo validación demo con riesgo reducido."
                ),
                "controlled_demo_survival_protocol": controlled_demo_survival_protocol,
            }
        )
        return decision

    def _write_signal(
        self,
        signal: dict[str, Any] | None,
        runtime: dict[str, Any],
        symbol: str,
        volume_lots: float,
        dry_run: bool,
        execution_status: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        active_watch_history: dict[str, Any],
        active_watch_metrics: dict[str, Any],
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        controlled_demo_survival_protocol: dict[str, Any],
        expansion_subtype_pretrade_audit: dict[str, Any],
        q_learning_decision: dict[str, Any],
        reasoning_snapshot: dict[str, Any],
        position_management: dict[str, Any],
        direction_consistency_guard: dict[str, Any],
    ) -> None:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "volume_lots": volume_lots,
            "dry_run": dry_run,
            "execution_status": execution_status,
            "intelligence_action": intelligence["execution_readiness"]["action"],
            "operating_posture": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("operating_posture"),
            "harmony_score": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("harmony_score"),
            "watch_trigger": intelligence.get("watch_trigger"),
            "active_watch": active_watch,
            "active_watch_history": active_watch_history,
            "active_watch_metrics": active_watch_metrics,
            "watch_execution_policy": watch_execution_policy,
            "execution_risk_decision": execution_risk_decision,
            "controlled_demo_survival_protocol": controlled_demo_survival_protocol,
            "expansion_subtype_pretrade_audit": expansion_subtype_pretrade_audit,
            "q_learning_decision": q_learning_decision,
            "reasoning_snapshot": reasoning_snapshot,
            "position_management": position_management,
            "direction_consistency_guard": direction_consistency_guard,
            "signal": signal,
        }
        self.signal_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_positions_snapshot(
        self,
        *,
        account_status: dict,
        positions: list[dict],
        execution: dict[str, Any] | None,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        active_watch_history: dict[str, Any],
        active_watch_metrics: dict[str, Any],
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        controlled_demo_survival_protocol: dict[str, Any],
        expansion_subtype_pretrade_audit: dict[str, Any],
        q_learning_decision: dict[str, Any],
        reasoning_snapshot: dict[str, Any],
        position_management: dict[str, Any],
        direction_consistency_guard: dict[str, Any],
    ) -> None:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "account_status": account_status,
            "positions": positions,
            "execution": execution,
            "intelligence_action": intelligence["execution_readiness"]["action"],
            "operating_posture": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("operating_posture"),
            "watch_trigger": intelligence.get("watch_trigger"),
            "active_watch": active_watch,
            "active_watch_history": active_watch_history,
            "active_watch_metrics": active_watch_metrics,
            "watch_execution_policy": watch_execution_policy,
            "execution_risk_decision": execution_risk_decision,
            "controlled_demo_survival_protocol": controlled_demo_survival_protocol,
            "expansion_subtype_pretrade_audit": expansion_subtype_pretrade_audit,
            "q_learning_decision": q_learning_decision,
            "reasoning_snapshot": reasoning_snapshot,
            "position_management": position_management,
            "direction_consistency_guard": direction_consistency_guard,
        }
        self.positions_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_execution_row(
        self,
        *,
        signal: dict[str, Any] | None,
        execution: dict[str, Any] | None,
        symbol: str,
        volume_lots: float,
        dry_run: bool,
        execution_status: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        active_watch_history: dict[str, Any],
        active_watch_metrics: dict[str, Any],
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        controlled_demo_survival_protocol: dict[str, Any],
        expansion_subtype_pretrade_audit: dict[str, Any],
        q_learning_decision: dict[str, Any],
    ) -> None:
        fields = [
            "timestamp_utc",
            "symbol",
            "volume_lots",
            "dry_run",
            "execution_status",
            "intelligence_action",
            "operating_posture",
            "harmony_score",
            "strategy_variant",
            "session_variant",
            "direction",
            "setup_type",
            "signal_type",
            "active_family",
            "reduced_signal_reason",
            "wick_rejection_quality",
            "displacement_score",
            "micro_bos",
            "continuation_momentum",
            "risk_mode",
            "defensive_management_plan",
            "entry_kind",
            "entry_price",
            "stop_price",
            "target_price",
            "selected_rr",
            "confidence",
            "mt5_retcode",
            "mt5_order",
            "mt5_deal",
            "controlled_demo_protocol",
            "controlled_demo_action",
            "controlled_demo_allowed",
            "controlled_demo_blockers",
            "controlled_demo_live_spread",
            "controlled_demo_live_latency",
            "controlled_demo_slippage_estimated",
            "controlled_demo_execution_delay",
            "controlled_demo_mfe",
            "controlled_demo_mae",
            "controlled_demo_slippage_real",
            "controlled_demo_partial_fills",
            "controlled_demo_trailing_quality",
            "controlled_demo_time_to_be",
            "controlled_demo_execution_degradation",
            "expansion_pretrade_candidate_detected",
            "expansion_pretrade_subtype",
            "expansion_pretrade_confidence",
            "expansion_pretrade_expected_edge_bucket",
            "expansion_pretrade_lookahead_safe",
            "q_learning_state_key",
            "q_learning_policy_action",
            "q_learning_risk_bias",
            "q_learning_value_gap",
            "q_learning_experience_count",
        ]
        protocol_env = controlled_demo_survival_protocol.get("environment", {})
        row = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "volume_lots": volume_lots,
            "dry_run": dry_run,
            "execution_status": execution_status,
            "intelligence_action": intelligence["execution_readiness"]["action"],
            "operating_posture": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("operating_posture"),
            "harmony_score": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("harmony_score"),
            "strategy_variant": signal["strategy_variant"] if signal else None,
            "session_variant": signal["session_variant"] if signal else None,
            "direction": signal["direction"] if signal else None,
            "setup_type": signal["setup_type"] if signal else None,
            "signal_type": signal.get("signal_type") if signal else None,
            "active_family": signal.get("active_family") if signal else None,
            "reduced_signal_reason": signal.get("reduced_signal_reason") if signal else None,
            "wick_rejection_quality": signal.get("wick_rejection_quality") if signal else None,
            "displacement_score": signal.get("displacement_score") if signal else None,
            "micro_bos": signal.get("micro_bos") if signal else None,
            "continuation_momentum": signal.get("continuation_momentum") if signal else None,
            "risk_mode": signal.get("risk_mode") if signal else None,
            "defensive_management_plan": (
                json.dumps(signal.get("defensive_management_plan"), ensure_ascii=False)
                if signal and signal.get("defensive_management_plan")
                else None
            ),
            "entry_kind": signal["entry_kind"] if signal else None,
            "entry_price": signal["entry_price"] if signal else None,
            "stop_price": signal["stop_price"] if signal else None,
            "target_price": signal["target_price"] if signal else None,
            "selected_rr": signal["selected_rr"] if signal else None,
            "confidence": signal["confidence"] if signal else None,
            "mt5_retcode": execution["result"].get("retcode") if execution else None,
            "mt5_order": execution["result"].get("order") if execution else None,
            "mt5_deal": execution["result"].get("deal") if execution else None,
            "controlled_demo_protocol": controlled_demo_survival_protocol.get("protocol_name"),
            "controlled_demo_action": controlled_demo_survival_protocol.get("action"),
            "controlled_demo_allowed": controlled_demo_survival_protocol.get("allowed"),
            "controlled_demo_blockers": ",".join(controlled_demo_survival_protocol.get("blockers", [])),
            "controlled_demo_live_spread": protocol_env.get("live_spread"),
            "controlled_demo_live_latency": protocol_env.get("live_latency"),
            "controlled_demo_slippage_estimated": protocol_env.get("slippage_estimated"),
            "controlled_demo_execution_delay": protocol_env.get("execution_delay"),
            "controlled_demo_mfe": protocol_env.get("mfe"),
            "controlled_demo_mae": protocol_env.get("mae"),
            "controlled_demo_slippage_real": protocol_env.get("slippage_real"),
            "controlled_demo_partial_fills": protocol_env.get("partial_fills"),
            "controlled_demo_trailing_quality": protocol_env.get("trailing_quality"),
            "controlled_demo_time_to_be": protocol_env.get("time_to_be"),
            "controlled_demo_execution_degradation": protocol_env.get("execution_degradation"),
            "expansion_pretrade_candidate_detected": expansion_subtype_pretrade_audit.get("candidate_detected"),
            "expansion_pretrade_subtype": expansion_subtype_pretrade_audit.get("subtype"),
            "expansion_pretrade_confidence": expansion_subtype_pretrade_audit.get("subtype_confidence"),
            "expansion_pretrade_expected_edge_bucket": expansion_subtype_pretrade_audit.get("expected_edge_bucket"),
            "expansion_pretrade_lookahead_safe": expansion_subtype_pretrade_audit.get("lookahead_safe"),
            "q_learning_state_key": q_learning_decision.get("state_key"),
            "q_learning_policy_action": q_learning_decision.get("q_policy_action"),
            "q_learning_risk_bias": q_learning_decision.get("risk_bias"),
            "q_learning_value_gap": q_learning_decision.get("value_gap"),
            "q_learning_experience_count": q_learning_decision.get("experience_count"),
        }
        write_header = not self.executions_path.exists()
        with self.executions_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def _append_decision_source_audit(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        signal: dict[str, Any] | None,
        execution_status: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        account_status: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._build_decision_source_audit(
            symbol=symbol,
            runtime=runtime,
            signal=signal,
            execution_status=execution_status,
            intelligence=intelligence,
            active_watch=active_watch,
            watch_execution_policy=watch_execution_policy,
            execution_risk_decision=execution_risk_decision,
            account_status=account_status,
        )
        with self.decision_source_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload

    def _build_decision_source_audit(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        signal: dict[str, Any] | None,
        execution_status: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        account_status: dict[str, Any],
    ) -> dict[str, Any]:
        watch_trigger = intelligence.get("watch_trigger") or {}
        market_state = intelligence["overview"]["market_state"]
        knowledge_alignment = intelligence["overview"].get("knowledge_alignment", {})
        top_contexts = list(knowledge_alignment.get("top_matching_contexts", []))
        top_context = top_contexts[0] if top_contexts else {}
        harmony = knowledge_alignment.get("harmony", {})
        snapshot = runtime.get("snapshot", {})
        parameters = snapshot.get("parameters", {})
        current_hour_ny = market_state.get("hour_ny")
        runtime_hour_allowed = self._runtime_time_allowed_from_strategy_parameters(
            parameters=parameters,
            current_hour_ny=current_hour_ny,
            current_hour_rd=market_state.get("hour_rd"),
            current_minute_rd=market_state.get("minute_rd"),
        )
        market_allowed_hour = bool(market_state.get("allowed_hour_by_strategy", False))
        strategy_time_config_mismatch = bool(runtime_hour_allowed and not market_allowed_hour)

        blockers = list(intelligence["execution_readiness"].get("blockers", []))
        if not account_status.get("is_demo", False):
            blockers.append("account_not_demo")
        if execution_risk_decision.get("allowed_risk_mode") == "blocked":
            blockers.append("risk_binding_blocked")

        dominant_family = str(harmony.get("dominant_family") or top_context.get("strategy_family") or "General")
        supporting_rules_count = int(sum(int(item.get("supporting_rules", 0) or 0) for item in top_contexts[:5]))
        matched_situation = ""
        if top_context:
            sessions = ",".join(top_context.get("sessions", []) or ["any_session"])
            entry_tfs = ",".join(top_context.get("entry_timeframes", []) or ["unknown"])
            matched_situation = (
                f"{top_context.get('strategy_family', 'General')}|"
                f"{top_context.get('market_regime', 'mixed')}|"
                f"{sessions}|{entry_tfs}"
            )
        operable_label = str(top_context.get("operability_label") or "research_only")
        map_operable = operable_label == "operable"
        base_variant = runtime["strategy_variant"].code
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        operational_family = str(market_state.get("operational_family") or ob_families.get("active_family") or "NONE")

        main_blocker = (
            "strategy_time_config_mismatch"
            if strategy_time_config_mismatch
            else blockers[0]
            if blockers
            else execution_risk_decision.get("decision") or execution_status
        )
        external_driver = strategy_time_config_mismatch or any(
            item in {
                "hour_not_allowed",
                "high_impact_event_window",
                "account_not_demo",
                "risk_binding_blocked",
                "position_already_open",
            }
            for item in blockers
        ) or intelligence["event_risk"].get("action") != "allow"
        knowledge_driver = (
            float(knowledge_alignment.get("support_score") or 0.0) >= 0.45
            or float(harmony.get("harmony_score") or 0.0) >= 0.45
        )
        base_driver = signal is not None or bool(market_state.get("candidate_setups", {}).get("buy_agg")) or bool(
            market_state.get("candidate_setups", {}).get("sell_agg")
        )

        if external_driver:
            primary_driver = "external_filter"
            secondary_driver = "learned_knowledge" if knowledge_driver else "base_strategy"
        elif knowledge_driver and dominant_family:
            primary_driver = "learned_knowledge"
            secondary_driver = "base_strategy"
        else:
            primary_driver = "base_strategy"
            secondary_driver = "learned_knowledge" if knowledge_driver else "external_filter"

        family_matches_strategy = dominant_family in {"OB Rejection", "Breakout Retest", "FVG Continuation", "Session Expansion"} and "v56" in base_variant
        learned_role = "motor_principal" if primary_driver == "learned_knowledge" else "filtro" if knowledge_driver else "minimal"

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "final_action": intelligence["execution_readiness"]["action"],
            "final_execution_status": execution_status,
            "base_strategy": {
                "name": runtime.get("snapshot", {}).get("strategy_name", "MAXIMO MTF Quant Institutional v4"),
                "variant": base_variant,
                "signal": signal.get("setup_type") if signal else "none",
                "side": signal.get("direction") if signal else market_state.get("preferred_side"),
                "score": signal.get("confidence") if signal else intelligence["execution_readiness"].get("confidence"),
                "allowed_hour": market_allowed_hour,
                "source_file": str(self.strategy_snapshot_path.resolve()),
            },
            "learned_knowledge": {
                "dominant_family": dominant_family,
                "support_score": knowledge_alignment.get("support_score"),
                "harmony_score": harmony.get("harmony_score"),
                "supporting_rules_count": supporting_rules_count,
                "top_matching_contexts": top_contexts[:3],
                "source_files": [
                    str(self.market_situation_map_path.resolve()),
                    str(self.market_situation_map_md_path.resolve()),
                    str(self.market_intelligence_json_path.resolve()),
                ],
            },
            "market_situation_map": {
                "matched_situation": matched_situation,
                "operable": map_operable,
                "recommended_strategy": top_context.get("strategy_family", ""),
                "risk_mode": intelligence["execution_readiness"].get("risk_mode"),
                "source_file": str(self.market_situation_map_path.resolve()),
            },
            "intelligence_layer": {
                "action": intelligence["execution_readiness"]["action"],
                "watch_policy_action": watch_execution_policy.get("watch_policy_action"),
                "setup_maturity": intelligence["execution_readiness"].get("setup_maturity"),
                "confidence": intelligence["execution_readiness"].get("confidence"),
                "preferred_side": market_state.get("preferred_side"),
                "operational_family": operational_family,
                "ob_rejection_families": ob_families,
                "missing_for_execute": watch_trigger.get("missing_for_execute", []),
                "critical_blocks": list(intelligence["execution_readiness"].get("blockers", [])),
            },
            "execution_guard": {
                "allowed_to_execute": bool(execution_risk_decision.get("can_execute", False)),
                "blocked_by": blockers,
                "event_action": intelligence["event_risk"].get("action"),
                "hour_allowed": market_allowed_hour,
                "macro_status": watch_trigger.get("macro_event_status"),
                "risk_binding": execution_risk_decision.get("allowed_risk_mode"),
            },
            "decision_attribution": {
                "primary_driver": primary_driver,
                "secondary_driver": secondary_driver,
                "main_blocker": main_blocker,
                "is_course_knowledge_driving": knowledge_driver,
                "is_base_strategy_driving": base_driver,
                "is_external_filter_driving": external_driver,
            },
            "strategy_time_config_mismatch": strategy_time_config_mismatch,
            "family_matches_strategy": family_matches_strategy,
            "learned_knowledge_role": learned_role,
        }

    @staticmethod
    def _runtime_time_allowed_from_strategy_parameters(
        *,
        parameters: dict[str, Any],
        current_hour_ny: Any,
        current_hour_rd: Any,
        current_minute_rd: Any,
    ) -> bool:
        windows = parameters.get("allowed_session_windows_rd", []) if isinstance(parameters, dict) else []
        if isinstance(windows, list) and windows:
            try:
                current_minutes = int(current_hour_rd) * 60 + int(current_minute_rd)
            except (TypeError, ValueError):
                return False
            for window in windows:
                if not isinstance(window, dict):
                    continue
                try:
                    start_hour, start_minute = str(window.get("start")).split(":", 1)
                    end_hour, end_minute = str(window.get("end")).split(":", 1)
                    start = int(start_hour) * 60 + int(start_minute)
                    end = int(end_hour) * 60 + int(end_minute)
                except (AttributeError, TypeError, ValueError):
                    continue
                if start <= current_minutes <= end:
                    return True
            return False

        allowed_hours = set(int(item) for item in parameters.get("allowed_hours_ny", []) or [])
        return bool(current_hour_ny in allowed_hours) if allowed_hours and current_hour_ny is not None else True

    def _write_report(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        account_status: dict,
        positions: list[dict],
        snapshot: dict[str, Any],
        signal: dict[str, Any] | None,
        execution: dict[str, Any] | None,
        dry_run: bool,
        execution_status: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        active_watch_history: dict[str, Any],
        active_watch_metrics: dict[str, Any],
        watch_execution_policy: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        decision_source_audit: dict[str, Any],
        controlled_demo_survival_protocol: dict[str, Any],
        expansion_subtype_pretrade_audit: dict[str, Any],
        q_learning_decision: dict[str, Any],
        reasoning_snapshot: dict[str, Any],
        position_management: dict[str, Any],
        direction_consistency_guard: dict[str, Any],
    ) -> None:
        event_risk = intelligence.get("event_risk", {})
        active_events = event_risk.get("active_events", []) or []
        upcoming_events = event_risk.get("upcoming_events", []) or []
        macro_event = active_events[0] if active_events else (upcoming_events[0] if upcoming_events else None)
        macro_block_reason = "No relevant macro event." if macro_event is None else (
            "Active high-impact relevant event inside block window."
            if event_risk.get("action") == "block"
            else "Relevant event nearby; monitor only."
        )
        lines = [
            "# MAXIMO Quant v4 Demo Trading",
            "",
            f"- generated_at_utc: {datetime.now(timezone.utc).isoformat()}",
            f"- symbol: {symbol}",
            f"- strategy_variant: {runtime['strategy_variant'].code}",
            f"- session_variant: {runtime['session_variant'].code}",
            f"- dry_run: {dry_run}",
            f"- execution_status: {execution_status}",
            f"- intelligence_action: {intelligence['execution_readiness']['action']}",
            f"- preferred_side: {intelligence['overview']['market_state'].get('preferred_side')}",
            f"- operational_family: {intelligence['overview']['market_state'].get('operational_family')}",
            f"- operating_posture: {intelligence['overview']['knowledge_alignment'].get('harmony', {}).get('operating_posture')}",
            f"- harmony_score: {intelligence['overview']['knowledge_alignment'].get('harmony', {}).get('harmony_score')}",
            f"- account_is_demo: {account_status['is_demo']}",
            f"- open_positions_for_magic: {len(positions)}",
            "",
            "## Market Snapshot",
        ]
        for timeframe, details in snapshot["timeframes"].items():
            lines.append(
                f"- {timeframe}: bars={details['bars']} first={details['first_bar_time']} last={details['last_bar_time']}"
            )
        lines.extend(
            [
                "",
                "## Reasoning Snapshot",
                f"- summary: {reasoning_snapshot.get('state', {}).get('summary')}",
                f"- action: {reasoning_snapshot.get('state', {}).get('action')}",
                f"- preferred_side: {reasoning_snapshot.get('state', {}).get('preferred_side')}",
                f"- execution_status: {reasoning_snapshot.get('state', {}).get('execution_status')}",
                f"- next_confirmation_expected: {reasoning_snapshot.get('next_confirmation_expected')}",
                "",
                "### Timeframe Reading",
            ]
        )
        for item in reasoning_snapshot.get("timeframe_reading", []):
            lines.append(
                f"- {item.get('timeframe')}: role={item.get('role')} bars={item.get('bars')} last={item.get('last_bar_time')} | {item.get('what_it_is_used_for')}"
            )
        coverage = reasoning_snapshot.get("market_coverage_assurance", {}) or {}
        if coverage:
            lines.extend(
                [
                    "",
                    "### Market Coverage Assurance",
                    f"- status: {coverage.get('status')}",
                    f"- active_corners: {coverage.get('active_corners')}/4",
                    f"- selected_side: {coverage.get('selected_side')}",
                    f"- probable_market_move: {coverage.get('probable_market_move')}",
                    f"- best_option_reason: {coverage.get('best_option_reason')}",
                    f"- wait_for: {coverage.get('wait_for')}",
                ]
            )
            management_sync = coverage.get("management_sync") or {}
            lines.extend(
                [
                    "- management_sync:",
                    f"  - risk_mode: {management_sync.get('risk_mode')}",
                    f"  - target_risk_percent: {management_sync.get('target_risk_percent')}",
                    f"  - max_account_risk_percent: {management_sync.get('max_account_risk_percent')}",
                    f"  - sl_strategy: {management_sync.get('sl_strategy')}",
                    f"  - take_profit_plan: {management_sync.get('take_profit_plan')}",
                    f"  - trailing_plan: {management_sync.get('trailing_plan')}",
                    f"  - emergency_exit: {management_sync.get('emergency_exit')}",
                    "- four_corner_scan:",
                ]
            )
            for name, corner in (coverage.get("corners") or {}).items():
                lines.append(f"  - {name}: {corner.get('status')} | {corner}")
        context = reasoning_snapshot.get("market_context", {})
        lines.extend(
            [
                "",
                "### Market Context Reasoning",
                f"- session: {context.get('session')}",
                f"- hour_ny: {context.get('hour_ny')}",
                f"- higher_timeframe_bias: {context.get('higher_timeframe_bias')}",
                f"- market_regime: {context.get('market_regime')}",
                f"- volatility: {context.get('volatility')}",
                f"- atr_regime: {context.get('atr_regime')}",
                f"- expansion_subtype: {context.get('expansion_subtype')}",
                f"- continuation_quality: {context.get('continuation_quality')}",
                f"- macro_event_action: {context.get('macro_event_action')}",
                f"- execution_viability: {context.get('execution_viability')}",
                f"- live_spread: {context.get('live_spread')}",
                f"- slippage_estimated: {context.get('slippage_estimated')}",
            ]
        )
        setup = reasoning_snapshot.get("setup_assessment", {})
        lines.extend(
            [
                "",
                "### Setup Reasoning",
                f"- setup_detected: {setup.get('setup_detected')}",
                f"- operational_family: {setup.get('operational_family')}",
                f"- trigger_type: {setup.get('trigger_type')}",
                f"- candidate_side: {setup.get('candidate_side')}",
                f"- setup_maturity: {setup.get('setup_maturity')}",
                f"- confidence: {setup.get('confidence')}",
                f"- harmony_score: {setup.get('harmony_score')}",
                f"- watch_health: {setup.get('watch_health')}",
                f"- watch_probability_to_execute: {setup.get('watch_probability_to_execute')}",
                f"- watch_policy_action: {setup.get('watch_policy_action')}",
                f"- allowed_risk_mode: {setup.get('allowed_risk_mode')}",
                "",
                "### Confirmation Checklist",
            ]
        )
        projection = reasoning_snapshot.get("learned_pattern_projection", {}) or {}
        if projection:
            lines.extend(
                [
                    "",
                    "### Learned Pattern Projection",
                    f"- dominant_family: {projection.get('dominant_family')}",
                    f"- operational_family: {projection.get('operational_family')}",
                    f"- candidate_side: {projection.get('candidate_side')}",
                    f"- probable_market_move: {projection.get('probable_market_move')}",
                    f"- near_execute_watch: {projection.get('near_execute_watch')}",
                    f"- maturity_gap_to_execute: {projection.get('maturity_gap_to_execute')}",
                    f"- interpretation: {projection.get('interpretation')}",
                    "- pattern_matches:",
                ]
            )
            for item in projection.get("pattern_matches", []):
                lines.append(f"  - {item}")
            lines.append("- evidence:")
            for item in projection.get("evidence", []):
                lines.append(f"  - {item}")
            lines.append("- confirmation_focus:")
            for item in projection.get("confirmation_focus", []):
                lines.append(f"  - {item}")
            analogs = projection.get("historical_analogs") or {}
            if analogs:
                lines.extend(
                    [
                        "- historical_analogs:",
                        f"  - status: {analogs.get('status')}",
                        f"  - summary: {analogs.get('summary')}",
                        f"  - bias: {analogs.get('bias')}",
                        f"  - win_rate: {analogs.get('win_rate')}",
                        f"  - failure_rate: {analogs.get('failure_rate')}",
                    ]
                )
            comparison = projection.get("side_probability_comparison") or {}
            if comparison:
                lines.extend(
                    [
                        "- side_probability_comparison:",
                        f"  - selected_side: {comparison.get('selected_side')}",
                        f"  - should_watch_alternative: {comparison.get('should_watch_alternative')}",
                        f"  - selection_reason: {comparison.get('selection_reason')}",
                    ]
                )
                for side, side_data in (comparison.get("sides") or {}).items():
                    lines.append(
                        f"  - {side}: probability={side_data.get('probability_to_confirm')} "
                        f"status={side_data.get('status')}"
                    )
                    confirmations = list(side_data.get("confirmation_needed", []) or [])
                    if confirmations:
                        lines.append(f"    - confirmation_needed: {confirmations[0]}")
            cool = projection.get("cool_learning_memory") or {}
            if cool:
                course_alignment = cool.get("course_alignment") or {}
                lines.extend(
                    [
                        "- q_learning_memory:",
                        f"  - status: {cool.get('status')}",
                        f"  - learning_method: {cool.get('learning_method')}",
                        f"  - q_update_mode: {cool.get('q_update_mode')}",
                        f"  - summary: {cool.get('summary')}",
                        f"  - q_policy_action: {cool.get('q_policy_action') or cool.get('policy_action')}",
                        f"  - policy_quality: {cool.get('policy_quality')}",
                        f"  - confidence: {cool.get('confidence')}",
                        f"  - q_values: {cool.get('q_values') or cool.get('action_values')}",
                        f"  - action_win_rates: {cool.get('action_win_rates')}",
                    ]
                )
                if course_alignment:
                    lines.extend(
                        [
                            "  - course_alignment:",
                            f"    - status: {course_alignment.get('status')}",
                            f"    - course_score: {course_alignment.get('course_score')}",
                            f"    - course_recommended_action: {course_alignment.get('course_recommended_action')}",
                        ]
                    )
                    for item in list(course_alignment.get("confirmations", []) or [])[:3]:
                        lines.append(f"    - confirmation: {item}")
                    for item in list(course_alignment.get("missing_steps", []) or [])[:3]:
                        lines.append(f"    - missing_course_step: {item}")
            professional = projection.get("professional_decision_matrix") or {}
            if professional:
                sync = professional.get("layer_synchronization") or {}
                lines.extend(
                    [
                        "- professional_decision_matrix:",
                        f"  - summary: {professional.get('summary')}",
                        f"  - selected_side: {professional.get('selected_side')}",
                        f"  - probability_quality: {professional.get('probability_quality')}",
                        f"  - best_option_reason: {professional.get('best_option_reason')}",
                        f"  - wait_for_liquidity_volatility: {professional.get('wait_for_liquidity_volatility')}",
                    ]
                )
                if sync:
                    lines.extend(
                        [
                            "  - layer_synchronization:",
                            f"    - status: {sync.get('status')}",
                            f"    - agreement_score: {sync.get('agreement_score')}",
                            f"    - layers: {sync.get('layers')}",
                            f"    - conflicts: {sync.get('conflicts')}",
                            f"    - interpretation: {sync.get('interpretation')}",
                        ]
                    )
                management = professional.get("management_plan") or {}
                if management:
                    lines.extend(
                        [
                            "  - management_plan:",
                            f"    - risk_mode_recommendation: {management.get('risk_mode_recommendation')}",
                            f"    - emergency_exit: {management.get('emergency_exit')}",
                            f"    - take_profit_plan: {management.get('take_profit_plan')}",
                            f"    - trailing_plan: {management.get('trailing_plan')}",
                        ]
                    )
                for item in professional.get("red_flags", [])[:5]:
                    lines.append(f"  - red_flag: {item}")
        for item in reasoning_snapshot.get("condition_checklist", []):
            lines.append(f"- {item.get('name')}: {item.get('status')} - {item.get('explanation')}")
        lines.extend(["", "### Waiting For"])
        for item in reasoning_snapshot.get("waiting_for", []):
            lines.append(f"- {item}")
        lines.extend(["", "### Cancel If"])
        for item in reasoning_snapshot.get("cancel_if", []):
            lines.append(f"- {item}")
        lines.extend(["", "## Latest Signal"])
        if signal is None:
            lines.append("- none")
        else:
            lines.extend(
                [
                    f"- direction: {signal['direction']}",
                    f"- setup_type: {signal['setup_type']}",
                    f"- signal_type: {signal.get('signal_type')}",
                    f"- active_family: {signal.get('active_family')}",
                    f"- reduced_signal_reason: {signal.get('reduced_signal_reason')}",
                    f"- wick_rejection_quality: {signal.get('wick_rejection_quality')}",
                    f"- displacement_score: {signal.get('displacement_score')}",
                    f"- micro_bos: {signal.get('micro_bos')}",
                    f"- continuation_momentum: {signal.get('continuation_momentum')}",
                    f"- defensive_management_plan: {signal.get('defensive_management_plan')}",
                    f"- risk_mode: {signal.get('risk_mode')}",
                    f"- entry_kind: {signal['entry_kind']}",
                    f"- signal_time: {signal['signal_time']}",
                    f"- entry_time: {signal['entry_time']}",
                    f"- entry_price: {signal['entry_price']}",
                    f"- stop_price: {signal['stop_price']}",
                    f"- target_price: {signal['target_price']}",
                    f"- selected_rr: {signal['selected_rr']}",
                    f"- confidence: {signal['confidence']}",
                    f"- regime: {signal['market_regime']}",
                    f"- hour_ny: {signal['hour_ny']}",
                ]
            )
        lines.extend(["", "## Intelligence Gate"])
        lines.append(f"- action: {intelligence['execution_readiness']['action']}")
        for item in intelligence["execution_readiness"].get("rationale", []):
            lines.append(f"- {item}")
        blockers = intelligence["execution_readiness"].get("blockers", [])
        if blockers:
            lines.append("- blockers: " + ", ".join(blockers))
        ob_families = intelligence["overview"]["market_state"].get("ob_rejection_families", {}) or {}
        institutional = ob_families.get("institutional", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        lines.extend(
            [
                "",
                "## OB Rejection Families",
                f"- active_family: {ob_families.get('active_family', 'NONE')}",
                f"- institutional_active: {institutional.get('active', False)}",
                f"- institutional_side: {institutional.get('side')}",
                f"- aggressive_active: {aggressive.get('active', False)}",
                f"- aggressive_side: {aggressive.get('side')}",
                f"- aggressive_allows_prepare_reduced: {aggressive.get('allows_prepare_reduced', False)}",
                f"- aggressive_allows_normal_risk_directly: {aggressive.get('allows_normal_risk_directly', False)}",
            ]
        )
        lines.extend(
            [
                "",
                "## Expansion Subtype Pretrade Audit V1",
                f"- candidate_detected: {expansion_subtype_pretrade_audit.get('candidate_detected')}",
                f"- subtype: {expansion_subtype_pretrade_audit.get('subtype')}",
                f"- subtype_confidence: {expansion_subtype_pretrade_audit.get('subtype_confidence')}",
                f"- expected_edge_bucket: {expansion_subtype_pretrade_audit.get('expected_edge_bucket')}",
                f"- subtype_reason: {expansion_subtype_pretrade_audit.get('subtype_reason')}",
                f"- historical_warning: {expansion_subtype_pretrade_audit.get('historical_warning')}",
                f"- lookahead_safe: {expansion_subtype_pretrade_audit.get('lookahead_safe')}",
                f"- future_variables_used: {expansion_subtype_pretrade_audit.get('future_variables_used')}",
            ]
        )
        lines.extend(
            [
                "",
                "## Macro Event Audit",
                f"- macro_event_name: {macro_event.get('title') if macro_event else 'none'}",
                f"- macro_event_currency: {macro_event.get('currency') if macro_event else 'none'}",
                f"- macro_event_impact: {macro_event.get('impact') if macro_event else 'none'}",
                f"- macro_event_time_utc: {macro_event.get('start_time_utc') if macro_event else 'none'}",
                f"- macro_event_time_rd: {macro_event.get('start_time_local') if macro_event else 'none'}",
                f"- minutes_to_event: {macro_event.get('minutes_until_start') if macro_event else 'none'}",
                f"- block_window_before: {self.settings.economic_calendar_pre_event_block_minutes}",
                f"- block_window_after: {self.settings.economic_calendar_post_event_block_minutes}",
                f"- macro_block_reason: {macro_block_reason}",
            ]
        )
        watch_trigger = intelligence.get("watch_trigger")
        if watch_trigger:
            lines.extend(
                [
                    "",
                    "## Watch Trigger",
                    f"- trigger_type: {watch_trigger.get('trigger_type')}",
                    f"- operational_family: {watch_trigger.get('operational_family')}",
                    "- required_conditions:",
                ]
            )
            for item in watch_trigger.get("required_conditions", []):
                lines.append(f"  - {item}")
            lines.append("- cancel_conditions:")
            for item in watch_trigger.get("cancel_conditions", []):
                lines.append(f"  - {item}")
            missing = watch_trigger.get("missing_for_execute", [])
            lines.append("- missing_for_execute:")
            if missing:
                for item in missing:
                    lines.append(f"  - {item}")
            else:
                lines.append("  - none")
        lines.extend(["", "## Active Watch"])
        if active_watch is None:
            lines.append("- none")
        else:
            lines.extend(
                [
                    f"- status: {active_watch.get('status')}",
                    f"- age_candles: {active_watch.get('age_candles')}",
                    f"- side: {active_watch.get('side')}",
                    f"- trigger_type: {active_watch.get('trigger_type')}",
                    f"- operational_family: {active_watch.get('operational_family')}",
                    f"- progress: {active_watch.get('progress')}",
                    f"- reason: {active_watch.get('reason')}",
                    "- missing_for_execute:",
                ]
            )
            missing = active_watch.get("missing_for_execute", [])
            if missing:
                for item in missing:
                    lines.append(f"  - {item}")
            else:
                lines.append("  - none")
            lines.append("- cancel_conditions:")
            for item in active_watch.get("cancel_conditions", []):
                lines.append(f"  - {item}")
        lines.extend(["", "## Active Watch History"])
        lines.append(f"- events_recorded: {active_watch_history.get('count', 0)}")
        if active_watch_history.get("last_event") is None:
            lines.append("- last_event: none")
        else:
            last_event = active_watch_history["last_event"]
            lines.extend(
                [
                    f"- last_event: {last_event.get('event')}",
                    f"- last_transition: {last_event.get('event')}",
                    f"- trend: {last_event.get('progress')}",
                    f"- reason: {last_event.get('reason')}",
                ]
            )
        lines.extend(
            [
                "",
                "## Active Watch Metrics",
                f"- watch_health: {active_watch_metrics.get('watch_health')}",
                f"- watch_probability_to_execute: {active_watch_metrics.get('watch_probability_to_execute')}",
                f"- interpretation: {active_watch_metrics.get('short_interpretation')}",
            ]
        )
        lines.extend(
            [
                "",
                "## Watch Execution Policy",
                f"- watch_policy_action: {watch_execution_policy.get('watch_policy_action')}",
                f"- allowed_risk_mode: {watch_execution_policy.get('allowed_risk_mode')}",
                f"- max_risk_multiplier: {watch_execution_policy.get('max_risk_multiplier')}",
                f"- policy_reason: {watch_execution_policy.get('policy_reason')}",
            ]
        )
        lines.extend(
            [
                "",
                "## Persistent Q-learning Memory",
                f"- learning_method: {q_learning_decision.get('learning_method')}",
                f"- status: {q_learning_decision.get('status')}",
                f"- state_key: {q_learning_decision.get('state_key')}",
                f"- q_policy_action: {q_learning_decision.get('q_policy_action')}",
                f"- q_values: {q_learning_decision.get('q_values')}",
                f"- historical_prior_values: {q_learning_decision.get('historical_prior_values')}",
                f"- value_gap: {q_learning_decision.get('value_gap')}",
                f"- risk_bias: {q_learning_decision.get('risk_bias')}",
                f"- experience_count: {q_learning_decision.get('experience_count')}",
                f"- replay_count: {q_learning_decision.get('replay_count')}",
                f"- historical_seed: {q_learning_decision.get('historical_seed')}",
                f"- reason: {q_learning_decision.get('reason')}",
                f"- safety_note: {q_learning_decision.get('safety_note')}",
            ]
        )
        update = q_learning_decision.get("experience_update") or {}
        if update:
            lines.extend(
                [
                    f"- latest_reward: {(update.get('latest_experience') or {}).get('reward')}",
                    f"- reward_reason: {(update.get('latest_experience') or {}).get('reward_reason')}",
                    f"- latest_update: {update.get('latest_update')}",
                    f"- replay_summary: {update.get('replay_summary')}",
                ]
            )
        lines.extend(
            [
                "",
                "## Watch Risk Binding",
                f"- allowed_risk_mode: {execution_risk_decision.get('allowed_risk_mode')}",
                f"- max_risk_multiplier: {execution_risk_decision.get('max_risk_multiplier')}",
                f"- base_risk: {execution_risk_decision.get('base_risk')}",
                f"- effective_risk: {execution_risk_decision.get('effective_risk')}",
                f"- account_risk_percent: {execution_risk_decision.get('account_risk_percent')}",
                f"- account_risk_amount: {execution_risk_decision.get('account_risk_amount')}",
                f"- max_account_risk_percent: {execution_risk_decision.get('max_account_risk_percent')}",
                f"- max_account_risk_amount: {execution_risk_decision.get('max_account_risk_amount')}",
                f"- order_volume_lots: {execution_risk_decision.get('order_volume_lots')}",
                f"- estimated_order_risk_amount: {execution_risk_decision.get('estimated_order_risk_amount')}",
                f"- estimated_order_risk_percent: {execution_risk_decision.get('estimated_order_risk_percent')}",
                f"- risk_probability_score: {execution_risk_decision.get('risk_probability_score')}",
                f"- position_sizing_status: {(execution_risk_decision.get('position_sizing') or {}).get('status')}",
                f"- position_sizing_policy: {(execution_risk_decision.get('position_sizing') or {}).get('policy')}",
                f"- execution_mode: {execution_risk_decision.get('execution_mode')}",
                f"- risk_binding_source: {execution_risk_decision.get('risk_binding_source')}",
                f"- execution_risk_decision: {execution_risk_decision.get('decision')}",
                f"- risk_application_reason: {execution_risk_decision.get('risk_application_reason')}",
            ]
        )
        lines.extend(
            [
                "",
                "## Position Management",
                f"- status: {position_management.get('status')}",
                f"- positions_managed: {position_management.get('positions_managed')}",
                f"- updates_sent: {position_management.get('updates_sent')}",
                f"- dry_run: {position_management.get('dry_run')}",
            ]
        )
        for action in position_management.get("actions", [])[:5]:
            lines.append(
                "- action: {action} ticket={ticket} side={side} old_sl={old_sl} new_sl={new_sl} "
                "mfe_r={mfe} reason={reason}".format(
                    action=action.get("action"),
                    ticket=action.get("ticket"),
                    side=action.get("side"),
                    old_sl=action.get("old_sl"),
                    new_sl=action.get("new_sl"),
                    mfe=action.get("max_favorable_r"),
                    reason=action.get("reason"),
                )
            )
        lines.extend(
            [
                "",
                "## Direction Consistency Guard",
                f"- allowed: {direction_consistency_guard.get('allowed')}",
                f"- signal_side: {direction_consistency_guard.get('signal_side')}",
                f"- conflicts: {direction_consistency_guard.get('conflicts')}",
                f"- reason: {direction_consistency_guard.get('reason')}",
            ]
        )
        protocol_env = controlled_demo_survival_protocol.get("environment", {})
        lines.extend(
            [
                "",
                "## Controlled Demo Survival Protocol V1",
                f"- protocol_name: {controlled_demo_survival_protocol.get('protocol_name')}",
                f"- edge_name: {controlled_demo_survival_protocol.get('edge_name')}",
                f"- applies: {controlled_demo_survival_protocol.get('applies')}",
                f"- action: {controlled_demo_survival_protocol.get('action')}",
                f"- allowed: {controlled_demo_survival_protocol.get('allowed')}",
                f"- allowed_risk_mode: {controlled_demo_survival_protocol.get('allowed_risk_mode')}",
                f"- max_risk_multiplier: {controlled_demo_survival_protocol.get('max_risk_multiplier')}",
                f"- blockers: {', '.join(controlled_demo_survival_protocol.get('blockers', [])) or 'none'}",
                f"- reason: {controlled_demo_survival_protocol.get('reason')}",
                f"- hour_ny: {protocol_env.get('hour_ny')}",
                f"- session: {protocol_env.get('session')}",
                f"- atr_regime: {protocol_env.get('atr_regime')}",
                f"- atr_ratio: {protocol_env.get('atr_ratio')}",
                f"- live_spread: {protocol_env.get('live_spread')}",
                f"- live_latency: {protocol_env.get('live_latency')}",
                f"- execution_delay: {protocol_env.get('execution_delay')}",
                f"- slippage_estimated: {protocol_env.get('slippage_estimated')}",
                f"- slippage_real: {protocol_env.get('slippage_real')}",
                f"- partial_fills: {protocol_env.get('partial_fills')}",
                f"- MFE: {protocol_env.get('mfe')}",
                f"- MAE: {protocol_env.get('mae')}",
                f"- trailing_quality: {protocol_env.get('trailing_quality')}",
                f"- time_to_BE: {protocol_env.get('time_to_be')}",
                f"- execution_degradation: {protocol_env.get('execution_degradation')}",
                f"- event_action: {protocol_env.get('event_action')}",
                f"- execution_viability: {protocol_env.get('execution_viability')}",
            ]
        )
        lines.extend(
            [
                "",
                "## Decision Source Audit",
                f"- primary_driver: {decision_source_audit.get('decision_attribution', {}).get('primary_driver')}",
                f"- secondary_driver: {decision_source_audit.get('decision_attribution', {}).get('secondary_driver')}",
                f"- main_blocker: {decision_source_audit.get('decision_attribution', {}).get('main_blocker')}",
                f"- strategy_time_config_mismatch: {decision_source_audit.get('strategy_time_config_mismatch')}",
                f"- is_course_knowledge_driving: {decision_source_audit.get('decision_attribution', {}).get('is_course_knowledge_driving')}",
                f"- is_base_strategy_driving: {decision_source_audit.get('decision_attribution', {}).get('is_base_strategy_driving')}",
                f"- is_external_filter_driving: {decision_source_audit.get('decision_attribution', {}).get('is_external_filter_driving')}",
                f"- dominant_family: {decision_source_audit.get('learned_knowledge', {}).get('dominant_family')}",
                f"- recommended_strategy: {decision_source_audit.get('market_situation_map', {}).get('recommended_strategy')}",
                f"- family_matches_strategy: {decision_source_audit.get('family_matches_strategy')}",
                f"- learned_knowledge_role: {decision_source_audit.get('learned_knowledge_role')}",
                f"- operational_family: {decision_source_audit.get('intelligence_layer', {}).get('operational_family')}",
            ]
        )
        lines.extend(["", "## Active Watch Timeline"])
        timeline = self._active_watch_timeline_events()
        if not timeline:
            lines.append("No active watch history yet.")
        else:
            lines.extend(
                [
                    "| Time | Event | Side | Trigger | Age | Confidence | Harmony | Maturity | Reason |",
                    "|---|---|---|---|---|---|---|---|---|",
                ]
            )
            for event in timeline:
                lines.append(
                    "| {time} | {event_name} | {side} | {trigger} | {age} | {confidence} | {harmony} | {maturity} | {reason} |".format(
                        time=event.get("timestamp", ""),
                        event_name=event.get("event", ""),
                        side=event.get("side", ""),
                        trigger=event.get("trigger_type", ""),
                        age=event.get("age_candles", ""),
                        confidence=event.get("confidence", ""),
                        harmony=event.get("harmony_score", ""),
                        maturity=event.get("setup_maturity", ""),
                        reason=str(event.get("reason", "")).replace("|", "/"),
                    )
                )
        lines.extend(["", "## Execution"])
        if execution is None:
            lines.append("- no MT5 order sent")
        else:
            result = execution["result"]
            lines.extend(
                [
                    f"- retcode: {result.get('retcode')}",
                    f"- order: {result.get('order')}",
                    f"- deal: {result.get('deal')}",
                    f"- price: {execution['request'].get('price')}",
                ]
            )
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _load_active_watch(self) -> dict[str, Any] | None:
        if not self.active_watch_path.exists():
            return None
        return json.loads(self.active_watch_path.read_text(encoding="utf-8"))

    def _save_active_watch(self, active_watch: dict[str, Any] | None) -> None:
        if active_watch is None:
            if self.active_watch_path.exists():
                self.active_watch_path.unlink()
            return
        self.active_watch_path.write_text(json.dumps(active_watch, ensure_ascii=False, indent=2), encoding="utf-8")

    def _last_active_watch_history_event(self) -> dict[str, Any] | None:
        events = self._read_active_watch_history_events()
        return events[-1] if events else None

    def _active_watch_history_summary(self) -> dict[str, Any]:
        events = self._read_active_watch_history_events()
        return {"count": len(events), "last_event": events[-1] if events else None}

    def _read_active_watch_history_events(self) -> list[dict[str, Any]]:
        if not self.active_watch_history_path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.active_watch_history_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    events.append(parsed)
        return events

    def _active_watch_timeline_events(self) -> list[dict[str, Any]]:
        events = self._read_active_watch_history_events()
        if not events:
            return []
        important = [event for event in events if event.get("event") in self.ACTIVE_WATCH_IMPORTANT_EVENTS]
        selected = important if important else [event for event in events if event.get("event") == "WATCH_UPDATED"]
        return selected[-self.ACTIVE_WATCH_TIMELINE_LIMIT :]

    @staticmethod
    def _counter_top(counter: dict[str, int], default: str = "none") -> tuple[str, int]:
        if not counter:
            return default, 0
        key = max(counter, key=counter.get)
        return key, counter[key]

    def _active_watch_metrics(
        self,
        *,
        active_watch: dict[str, Any] | None,
        active_watch_history: dict[str, Any],
    ) -> dict[str, Any]:
        if active_watch is None:
            return {
                "watch_health": "inactive",
                "watch_probability_to_execute": 0.0,
                "short_interpretation": "No hay idea activa en seguimiento ahora mismo.",
            }

        status = str(active_watch.get("status") or "INACTIVE").upper()
        progress = str(active_watch.get("progress") or "stable").lower()
        if status in {"CANCELLED", "EXPIRED", "BLOCKED"}:
            return {
                "watch_health": "inactive",
                "watch_probability_to_execute": 0.0,
                "short_interpretation": "La idea ya no está operativa y no debe ejecutarse.",
            }

        confidence = float(active_watch.get("current_confidence") or active_watch.get("initial_confidence") or 0.0)
        harmony = float(active_watch.get("current_harmony_score") or active_watch.get("initial_harmony_score") or 0.0)
        maturity = float(active_watch.get("current_setup_maturity") or active_watch.get("initial_setup_maturity") or 0.0) / 100.0
        probability = (confidence + harmony + maturity) / 3.0

        last_event = active_watch_history.get("last_event") or {}
        last_event_name = str(last_event.get("event") or "")
        missing_count = len(active_watch.get("missing_for_execute", []))
        initial_missing_count = len(active_watch.get("initial_missing_for_execute", active_watch.get("missing_for_execute", [])))
        age_candles = int(active_watch.get("age_candles") or 0)
        expiration_candles = max(1, int(active_watch.get("expiration_candles") or self.ACTIVE_WATCH_EXPIRATION_CANDLES))
        age_ratio = age_candles / expiration_candles

        if last_event_name == "WATCH_IMPROVING":
            probability += 0.08
        elif last_event_name == "WATCH_DETERIORATING":
            probability -= 0.12

        if missing_count > initial_missing_count:
            probability -= min(0.15, 0.04 * (missing_count - initial_missing_count))
        elif missing_count < initial_missing_count:
            probability += min(0.08, 0.03 * (initial_missing_count - missing_count))

        if age_ratio >= 0.8:
            probability -= 0.15
        elif age_ratio >= 0.6:
            probability -= 0.08

        probability = round(max(0.0, min(1.0, probability)), 2)

        if progress == "improving":
            watch_health = "improving"
        elif progress == "deteriorating" and (probability < 0.35 or age_ratio >= 0.8):
            watch_health = "critical"
        elif progress == "deteriorating":
            watch_health = "deteriorating"
        elif status == "TRIGGERED":
            watch_health = "improving"
        else:
            watch_health = "stable"

        if watch_health == "improving":
            interpretation = "La idea está ganando calidad y puede acercarse a ejecución si confirma la señal."
        elif watch_health == "stable":
            interpretation = "La idea sigue activa, pero todavía necesita confirmaciones antes de ejecutarse."
        elif watch_health == "deteriorating":
            interpretation = "La idea sigue activa, pero está perdiendo calidad. No debe ejecutarse hasta que recupere madurez o aparezca señal fuerte."
        elif watch_health == "critical":
            interpretation = "La idea está cerca de invalidarse o expirar. Solo merece seguimiento si recupera fuerza muy pronto."
        else:
            interpretation = "No hay una idea activa utilizable en este momento."

        return {
            "watch_health": watch_health,
            "watch_probability_to_execute": probability,
            "short_interpretation": interpretation,
        }

    def _watch_execution_policy(
        self,
        *,
        active_watch: dict[str, Any] | None,
        active_watch_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        if active_watch is None:
            return {
                "watch_policy_action": "DROP",
                "allowed_risk_mode": "blocked",
                "max_risk_multiplier": 0.0,
                "policy_reason": "No hay active_watch utilizable en este momento.",
            }

        status = str(active_watch.get("status") or "INACTIVE").upper()
        probability = float(active_watch_metrics.get("watch_probability_to_execute") or 0.0)
        health = str(active_watch_metrics.get("watch_health") or "inactive").lower()
        operational_family = str(active_watch.get("operational_family") or "")

        if status in {"CANCELLED", "EXPIRED", "BLOCKED"}:
            return {
                "watch_policy_action": "DROP",
                "allowed_risk_mode": "blocked",
                "max_risk_multiplier": 0.0,
                "policy_reason": "La idea ya fue cancelada, expiró o quedó bloqueada.",
            }

        if probability < 0.35:
            action = "DROP"
            risk_mode = "blocked"
            reason = "La probabilidad actual es demasiado baja para seguir la idea."
        elif probability < 0.60:
            action = "OBSERVE"
            risk_mode = "blocked"
            reason = "La idea todavía necesita madurar; conviene solo observar."
        elif probability < 0.80:
            action = "PREPARE_REDUCED"
            risk_mode = "reduced"
            reason = "La idea tiene probabilidad aceptable, pero todavía no supera umbral de ejecución normal."
        else:
            action = "PREPARE_NORMAL"
            risk_mode = "normal"
            reason = "La idea tiene calidad suficiente para prepararse con riesgo normal si confirma trigger."

        if health == "critical" and action != "DROP":
            action = "OBSERVE"
            risk_mode = "blocked"
            reason = "La idea está en estado critical; solo se permite observación hasta que recupere calidad."
        elif health == "deteriorating" and action == "PREPARE_NORMAL":
            action = "PREPARE_REDUCED"
            risk_mode = "reduced"
            reason = "La idea tiene probabilidad alta, pero al deteriorarse solo admite preparación con riesgo reducido."
        if operational_family == "OB_REJECTION_AGGRESSIVE_WATCH" and action == "PREPARE_NORMAL":
            action = "PREPARE_REDUCED"
            risk_mode = "reduced"
            reason = "OB Rejection agresivo nunca prepara riesgo normal directamente; se limita a riesgo reducido."

        return {
            "watch_policy_action": action,
            "allowed_risk_mode": risk_mode,
            "max_risk_multiplier": 0.0 if risk_mode == "blocked" else 0.5 if risk_mode == "reduced" else 1.0,
            "policy_reason": reason,
        }

    def _bind_watch_policy(
        self,
        *,
        active_watch: dict[str, Any] | None,
        watch_execution_policy: dict[str, Any],
    ) -> dict[str, Any] | None:
        if active_watch is None:
            return None
        active_watch["watch_policy_action"] = watch_execution_policy.get("watch_policy_action")
        active_watch["allowed_risk_mode"] = watch_execution_policy.get("allowed_risk_mode")
        active_watch["max_risk_multiplier"] = watch_execution_policy.get("max_risk_multiplier")
        active_watch["policy_reason"] = watch_execution_policy.get("policy_reason")
        self._save_active_watch(active_watch)
        return active_watch

    @staticmethod
    def _materialize_execution_risk(
        *,
        execution_risk_decision: dict[str, Any],
        base_risk: float,
    ) -> dict[str, Any]:
        materialized = dict(execution_risk_decision)
        multiplier = float(materialized.get("max_risk_multiplier") or 0.0)
        materialized["base_risk"] = float(base_risk)
        materialized["effective_risk"] = round(float(base_risk) * multiplier, 4)
        return materialized

    def _apply_account_risk_sizing(
        self,
        *,
        symbol: str,
        signal: dict[str, Any] | None,
        account_status: dict[str, Any],
        execution_risk_decision: dict[str, Any],
    ) -> dict[str, Any]:
        sized = dict(execution_risk_decision)
        sized.setdefault("risk_percent_policy", "probability_adjusted_5_percent_base_per_account")
        sized.setdefault("account_risk_percent", self.ACCOUNT_RISK_PERCENT_PER_TRADE)
        sized.setdefault("order_volume_lots", sized.get("effective_risk", 0.0))
        if signal is None or not sized.get("can_execute"):
            sized["position_sizing"] = {
                "status": "not_applicable",
                "reason": "No hay señal ejecutable o el riesgo está bloqueado.",
            }
            return sized
        sized.setdefault("allowed_risk_mode", "normal")
        sized.setdefault("max_risk_multiplier", 1.0)

        account = account_status.get("account_info", {}) or {}
        equity = float(account.get("equity") or account.get("balance") or 0.0)
        if equity <= 0:
            sized["position_sizing"] = {
                "status": "fallback_lot",
                "reason": "No se pudo leer equity/balance de MT5; se conserva lote efectivo previo.",
            }
            return sized
        entry = float(signal.get("entry_price") or 0.0)
        stop = float(signal.get("stop_price") or 0.0)
        if entry <= 0 or stop <= 0 or entry == stop:
            sized.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_invalid_risk_geometry",
                    "execution_mode": "blocked_by_invalid_risk_geometry",
                    "risk_application_reason": "No se puede calcular riesgo sin entrada y SL válidos.",
                    "execution_status": "blocked_by_invalid_risk_geometry",
                    "order_volume_lots": 0.0,
                    "position_sizing": {"status": "blocked", "reason": "Entrada/SL inválidos."},
                }
            )
            return sized

        risk_profile = self._probability_adjusted_risk_profile(
            signal=signal,
            execution_risk_decision=sized,
        )
        risk_percent = risk_profile["target_risk_percent"]
        risk_amount = equity * (risk_percent / 100.0)
        hard_risk_cap_amount = equity * (self.MAX_ACCOUNT_RISK_PERCENT_PER_TRADE / 100.0)
        try:
            volume_plan = self.bridge.calculate_risk_volume_lots(
                symbol=symbol,
                entry_price=entry,
                stop_loss=stop,
                risk_amount=risk_amount,
            )
        except Exception as exc:
            sized["position_sizing"] = {
                "status": "fallback_lot",
                "reason": f"No se pudo calcular lotaje por riesgo dinámico; se conserva lote previo. Error: {exc}",
            }
            return sized

        estimated_risk_amount = float(volume_plan["estimated_risk_amount"])
        estimated_risk_percent_of_account = (
            (estimated_risk_amount / equity) * 100.0 if equity > 0 else 0.0
        )
        if estimated_risk_amount > hard_risk_cap_amount:
            sized.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_min_lot_exceeds_10_percent_account_risk",
                    "execution_mode": "blocked_by_min_lot_exceeds_10_percent_account_risk",
                    "risk_application_reason": (
                        "El lote mínimo del broker haría que la pérdida estimada supere el 10% de la cuenta. "
                        "Esperar setup con SL más corto o una cuenta con más margen de tamaño."
                    ),
                    "execution_status": "blocked_by_min_lot_exceeds_10_percent_account_risk",
                    "order_volume_lots": 0.0,
                    "account_risk_percent": risk_percent,
                    "account_risk_amount": round(risk_amount, 4),
                    "max_account_risk_percent": self.MAX_ACCOUNT_RISK_PERCENT_PER_TRADE,
                    "max_account_risk_amount": round(hard_risk_cap_amount, 4),
                    "estimated_order_risk_amount": volume_plan["estimated_risk_amount"],
                    "estimated_order_risk_percent": round(estimated_risk_percent_of_account, 4),
                    "position_sizing": {
                        **volume_plan,
                        "status": "blocked",
                        "risk_profile": risk_profile,
                        "estimated_risk_percent_of_account": round(estimated_risk_percent_of_account, 4),
                        "policy": "Hard cap: broker minimum lot must not force more than 10% account risk.",
                    },
                }
            )
            return sized

        sized["order_volume_lots"] = volume_plan["volume_lots"]
        sized["account_risk_percent"] = risk_percent
        sized["account_risk_amount"] = round(risk_amount, 4)
        sized["max_account_risk_percent"] = self.MAX_ACCOUNT_RISK_PERCENT_PER_TRADE
        sized["max_account_risk_amount"] = round(hard_risk_cap_amount, 4)
        sized["estimated_order_risk_amount"] = volume_plan["estimated_risk_amount"]
        sized["estimated_order_risk_percent"] = round(estimated_risk_percent_of_account, 4)
        sizing_status = (
            "min_lot_above_target_within_10_percent_cap"
            if estimated_risk_amount > risk_amount
            else "calculated"
        )
        sized["position_sizing"] = {
            **volume_plan,
            "status": sizing_status,
            "risk_profile": risk_profile,
            "estimated_risk_percent_of_account": round(estimated_risk_percent_of_account, 4),
            "policy": (
                "Risk is probability-adjusted from the 5% base and hard-capped at 10% account risk "
                "after live MT5 broker minimum-lot rounding."
            ),
            "note": (
                "Si el lote mínimo supera el riesgo objetivo pero permanece debajo del 10%, se permite en demo "
                "y se audita como riesgo elevado por tamaño mínimo del broker."
            ),
        }
        return sized

    def _probability_adjusted_risk_profile(
        self,
        *,
        signal: dict[str, Any],
        execution_risk_decision: dict[str, Any],
    ) -> dict[str, Any]:
        allowed_risk_mode = str(execution_risk_decision.get("allowed_risk_mode") or "blocked").lower()
        policy_multiplier = float(execution_risk_decision.get("max_risk_multiplier") or 0.0)
        probability = self._normalize_probability(
            execution_risk_decision.get("risk_probability_score")
            or signal.get("probability_to_confirm")
            or signal.get("confidence")
            or 0.0
        )
        quality = str(signal.get("quality") or "").upper()
        countertrend_scalp = bool(signal.get("countertrend_reversal_scalp"))

        if allowed_risk_mode == "blocked" or policy_multiplier <= 0:
            probability_multiplier = 0.0
        elif allowed_risk_mode == "reduced":
            probability_multiplier = 0.35
            if probability >= 0.82:
                probability_multiplier = 0.5
            if probability >= 0.92 and quality == "A" and not countertrend_scalp:
                probability_multiplier = 0.75
            probability_multiplier = min(probability_multiplier, 0.75)
        else:
            probability_multiplier = 1.0
            if probability >= 0.85:
                probability_multiplier = 1.25
            if probability >= 0.92 and quality == "A":
                probability_multiplier = 1.5
            probability_multiplier = min(probability_multiplier, 1.5)

        if countertrend_scalp:
            probability_multiplier = min(probability_multiplier, 0.5)

        target_risk_percent = min(
            self.ACCOUNT_RISK_PERCENT_PER_TRADE * probability_multiplier,
            self.MAX_ACCOUNT_RISK_PERCENT_PER_TRADE,
        )
        return {
            "base_risk_percent": self.ACCOUNT_RISK_PERCENT_PER_TRADE,
            "max_account_risk_percent": self.MAX_ACCOUNT_RISK_PERCENT_PER_TRADE,
            "allowed_risk_mode": allowed_risk_mode,
            "policy_multiplier": round(policy_multiplier, 4),
            "probability_score": round(probability, 4),
            "probability_risk_multiplier": round(probability_multiplier, 4),
            "target_risk_percent": round(target_risk_percent, 4),
            "countertrend_scalp_cap": countertrend_scalp,
            "quality": quality,
        }

    @staticmethod
    def _normalize_probability(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric > 1.0:
            numeric /= 100.0
        return max(0.0, min(1.0, numeric))

    def _append_execution_risk_history_event(
        self,
        *,
        symbol: str,
        signal: dict[str, Any],
        execution_risk_decision: dict[str, Any],
    ) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "event": "WATCH_EXECUTION_RISK_APPLIED",
            "side": str(signal.get("direction", "")).upper(),
            "trigger_type": signal.get("setup_type"),
            "allowed_risk_mode": execution_risk_decision.get("allowed_risk_mode"),
            "base_risk": execution_risk_decision.get("base_risk"),
            "max_risk_multiplier": execution_risk_decision.get("max_risk_multiplier"),
            "effective_risk": execution_risk_decision.get("effective_risk"),
            "execution_mode": execution_risk_decision.get("execution_mode"),
            "reason": execution_risk_decision.get("risk_application_reason"),
        }
        last_event = self._last_active_watch_history_event()
        if last_event is not None and last_event.get("event") == "WATCH_EXECUTION_RISK_APPLIED":
            comparable_keys = [
                "symbol",
                "side",
                "trigger_type",
                "allowed_risk_mode",
                "base_risk",
                "max_risk_multiplier",
                "effective_risk",
                "execution_mode",
                "reason",
            ]
            if all(last_event.get(key) == payload.get(key) for key in comparable_keys):
                return
        with self.active_watch_history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _watch_performance_summary(self) -> dict[str, Any]:
        events = self._read_active_watch_history_events()
        if not events:
            return {
                "classification": "INSUFFICIENT_DATA",
                "total_watch_created": 0,
                "triggered": 0,
                "cancelled": 0,
                "expired": 0,
                "conversion_rate": 0.0,
                "avg_confidence": 0.0,
                "avg_harmony_score": 0.0,
                "avg_setup_maturity": 0.0,
                "improving": 0,
                "deteriorating": 0,
                "execution_modes": {},
                "ob_aggressive_created": 0,
                "ob_aggressive_triggered": 0,
                "ob_aggressive_cancelled": 0,
                "ob_aggressive_expired": 0,
                "ob_institutional_triggered": 0,
                "cancel_reason_top": ("none", 0),
                "expire_reason_top": ("none", 0),
                "symbol_top": ("none", 0),
                "side_top": ("none", 0),
                "trigger_type_top": ("none", 0),
                "policy_assessment": "Aún no hay suficientes eventos para evaluar el sistema WATCH.",
            }

        total_watch_created = 0
        triggered = 0
        cancelled = 0
        expired = 0
        improving = 0
        deteriorating = 0
        confidence_values: list[float] = []
        harmony_values: list[float] = []
        maturity_values: list[float] = []
        execution_modes: dict[str, int] = {}
        ob_aggressive_created = 0
        ob_aggressive_triggered = 0
        ob_aggressive_cancelled = 0
        ob_aggressive_expired = 0
        ob_institutional_triggered = 0
        cancel_reasons: dict[str, int] = {}
        expire_reasons: dict[str, int] = {}
        symbols: dict[str, int] = {}
        sides: dict[str, int] = {}
        trigger_types: dict[str, int] = {}

        for event in events:
            event_name = str(event.get("event") or "")
            operational_family = str(event.get("operational_family") or "")
            symbol = str(event.get("symbol") or "unknown")
            side = str(event.get("side") or "unknown")
            trigger = str(event.get("trigger_type") or "unknown")
            symbols[symbol] = symbols.get(symbol, 0) + 1
            sides[side] = sides.get(side, 0) + 1
            trigger_types[trigger] = trigger_types.get(trigger, 0) + 1

            if event_name == "WATCH_CREATED":
                total_watch_created += 1
                if operational_family == "OB_REJECTION_AGGRESSIVE_WATCH":
                    ob_aggressive_created += 1
                confidence_values.append(float(event.get("confidence") or 0.0))
                harmony_values.append(float(event.get("harmony_score") or 0.0))
                maturity_values.append(float(event.get("setup_maturity") or 0.0))
            elif event_name == "WATCH_TRIGGERED":
                triggered += 1
                if operational_family == "OB_REJECTION_AGGRESSIVE_WATCH":
                    ob_aggressive_triggered += 1
                elif operational_family == "OB_REJECTION_INSTITUTIONAL_EXECUTE":
                    ob_institutional_triggered += 1
            elif event_name == "WATCH_CANCELLED":
                cancelled += 1
                if operational_family == "OB_REJECTION_AGGRESSIVE_WATCH":
                    ob_aggressive_cancelled += 1
                reason = str(event.get("reason") or "unknown")
                cancel_reasons[reason] = cancel_reasons.get(reason, 0) + 1
            elif event_name == "WATCH_EXPIRED":
                expired += 1
                if operational_family == "OB_REJECTION_AGGRESSIVE_WATCH":
                    ob_aggressive_expired += 1
                reason = str(event.get("reason") or "unknown")
                expire_reasons[reason] = expire_reasons.get(reason, 0) + 1
            elif event_name == "WATCH_IMPROVING":
                improving += 1
            elif event_name == "WATCH_DETERIORATING":
                deteriorating += 1
            elif event_name == "WATCH_EXECUTION_RISK_APPLIED":
                mode = str(event.get("execution_mode") or "unknown")
                execution_modes[mode] = execution_modes.get(mode, 0) + 1

        conversion_rate = round(triggered / total_watch_created, 4) if total_watch_created else 0.0
        avg_confidence = round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else 0.0
        avg_harmony = round(sum(harmony_values) / len(harmony_values), 4) if harmony_values else 0.0
        avg_maturity = round(sum(maturity_values) / len(maturity_values), 4) if maturity_values else 0.0

        if total_watch_created < 3:
            classification = "INSUFFICIENT_DATA"
            assessment = "Aún no hay suficientes eventos para concluir si WATCH está ayudando."
        elif conversion_rate < 0.2 and expired >= max(2, triggered + 1):
            classification = "TOO_STRICT"
            assessment = "Se están creando muchas ideas que no llegan a ejecución y expiran demasiado."
        elif execution_modes.get("direct_high_confidence_execution", 0) > triggered and conversion_rate > 0.7:
            classification = "TOO_LOOSE"
            assessment = "El sistema está dejando pasar demasiadas ejecuciones directas y puede estar siendo permisivo."
        else:
            classification = "BALANCED"
            assessment = "WATCH está siendo selectivo, con cancelaciones y ejecuciones que parecen razonables."

        return {
            "classification": classification,
            "total_watch_created": total_watch_created,
            "triggered": triggered,
            "cancelled": cancelled,
            "expired": expired,
            "conversion_rate": conversion_rate,
            "avg_confidence": avg_confidence,
            "avg_harmony_score": avg_harmony,
            "avg_setup_maturity": avg_maturity,
            "improving": improving,
            "deteriorating": deteriorating,
            "execution_modes": execution_modes,
            "ob_aggressive_created": ob_aggressive_created,
            "ob_aggressive_triggered": ob_aggressive_triggered,
            "ob_aggressive_cancelled": ob_aggressive_cancelled,
            "ob_aggressive_expired": ob_aggressive_expired,
            "ob_institutional_triggered": ob_institutional_triggered,
            "cancel_reason_top": self._counter_top(cancel_reasons),
            "expire_reason_top": self._counter_top(expire_reasons),
            "symbol_top": self._counter_top(symbols),
            "side_top": self._counter_top(sides),
            "trigger_type_top": self._counter_top(trigger_types),
            "policy_assessment": assessment,
        }

    def _write_watch_performance_report(self) -> None:
        summary = self._watch_performance_summary()
        lines = [
            "# Watch Performance Report",
            "",
            f"- classification: {summary['classification']}",
            f"- total_watch_created: {summary['total_watch_created']}",
            f"- watch_triggered: {summary['triggered']}",
            f"- watch_cancelled: {summary['cancelled']}",
            f"- watch_expired: {summary['expired']}",
            f"- conversion_rate: {summary['conversion_rate']}",
            f"- avg_confidence_at_creation: {summary['avg_confidence']}",
            f"- avg_harmony_score: {summary['avg_harmony_score']}",
            f"- avg_setup_maturity: {summary['avg_setup_maturity']}",
            f"- watch_improving_events: {summary['improving']}",
            f"- watch_deteriorating_events: {summary['deteriorating']}",
            f"- ob_aggressive_created: {summary['ob_aggressive_created']}",
            f"- ob_aggressive_matured_triggered: {summary['ob_aggressive_triggered']}",
            f"- ob_aggressive_cancelled: {summary['ob_aggressive_cancelled']}",
            f"- ob_aggressive_expired: {summary['ob_aggressive_expired']}",
            f"- ob_institutional_triggered: {summary['ob_institutional_triggered']}",
            "",
            "## Execution Modes",
        ]
        if summary["execution_modes"]:
            for mode, count in sorted(summary["execution_modes"].items()):
                lines.append(f"- {mode}: {count}")
        else:
            lines.append("- none")
        cancel_reason, cancel_count = summary["cancel_reason_top"]
        expire_reason, expire_count = summary["expire_reason_top"]
        symbol_top, symbol_count = summary["symbol_top"]
        side_top, side_count = summary["side_top"]
        trigger_top, trigger_count = summary["trigger_type_top"]
        lines.extend(
            [
                "",
                "## Common Reasons",
                f"- top_cancel_reason: {cancel_reason} ({cancel_count})",
                f"- top_expire_reason: {expire_reason} ({expire_count})",
                "",
                "## Frequency",
                f"- top_symbol: {symbol_top} ({symbol_count})",
                f"- top_side: {side_top} ({side_count})",
                f"- top_trigger_type: {trigger_top} ({trigger_count})",
                "",
                "## Assessment",
                f"- conclusion: {summary['classification']}",
                f"- interpretation: {summary['policy_assessment']}",
            ]
        )
        self.watch_performance_report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _execution_risk_binding(
        self,
        *,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        account_is_demo: bool = False,
    ) -> dict[str, Any]:
        readiness = intelligence["execution_readiness"]
        confidence = float(readiness.get("confidence") or 0.0)
        if active_watch is not None:
            allowed_risk_mode = str(active_watch.get("allowed_risk_mode") or "blocked")
            max_risk_multiplier = float(active_watch.get("max_risk_multiplier") or 0.0)
            if signal is not None and signal.get("active_family") == "OB_REJECTION_AGGRESSIVE_WATCH":
                if allowed_risk_mode != "blocked":
                    allowed_risk_mode = "reduced"
                    max_risk_multiplier = min(max_risk_multiplier or 0.5, 0.5)
            if (
                signal is not None
                and allowed_risk_mode == "blocked"
                and str(active_watch.get("watch_policy_action") or "").upper() == "DROP"
                and self._demo_confirmed_signal_can_override_drop(
                    signal=signal,
                    intelligence=intelligence,
                    account_is_demo=account_is_demo,
                )
            ):
                return {
                    "can_execute": True,
                    "allowed_risk_mode": "reduced",
                    "max_risk_multiplier": 0.25,
                    "risk_probability_score": float(intelligence["execution_readiness"].get("confidence") or 0.0),
                    "risk_binding_source": "demo_confirmed_signal_drop_override",
                    "decision": "allowed_reduced_by_demo_confirmed_signal",
                    "execution_mode": "demo_confirmed_signal_reduced_override",
                    "risk_application_reason": (
                        "Cuenta demo con señal EXECUTE completa; DROP del active_watch no bloquea "
                        "la oportunidad, pero se limita a riesgo reducido."
                    ),
                    "execution_status": "ready",
                }
            can_execute = allowed_risk_mode != "blocked"
            return {
                "can_execute": can_execute,
                "allowed_risk_mode": allowed_risk_mode,
                "max_risk_multiplier": max_risk_multiplier,
                "risk_probability_score": self._active_watch_probability_score(active_watch=active_watch, intelligence=intelligence),
                "risk_binding_source": "active_watch",
                "decision": "allowed" if can_execute else "blocked",
                "execution_mode": "reduced_execution" if allowed_risk_mode == "reduced" else "normal_execution" if allowed_risk_mode == "normal" else "blocked_by_watch_risk_binding",
                "risk_application_reason": "La ejecución usa el binding de riesgo del active_watch." if can_execute else "El active_watch no permite ejecución por riesgo bloqueado.",
                "execution_status": "blocked_by_watch_risk_policy" if not can_execute and signal is not None else "no_signal",
            }

        if signal is None:
            return {
                "can_execute": False,
                "allowed_risk_mode": "blocked",
                "max_risk_multiplier": 0.0,
                "risk_probability_score": float(readiness.get("confidence") or 0.0),
                "risk_binding_source": "none",
                "decision": "no_signal",
                "execution_mode": "no_signal",
                "risk_application_reason": "No hay señal operativa para aplicar riesgo.",
                "execution_status": "no_signal",
            }

        quality = str(signal.get("quality", ""))
        if confidence >= 0.85:
            return {
                "can_execute": True,
                "allowed_risk_mode": "reduced",
                "max_risk_multiplier": 0.5,
                "risk_probability_score": confidence,
                "risk_binding_source": "direct_execute_without_watch",
                "decision": "allowed",
                "execution_mode": "direct_high_confidence_execution",
                "risk_application_reason": "No había active_watch previo; se permite entrada de alta confianza con protección inicial reducida.",
                "execution_status": "ready",
            }

        if quality.upper() == "A":
            return {
                "can_execute": True,
                "allowed_risk_mode": "reduced",
                "max_risk_multiplier": 0.5,
                "risk_probability_score": confidence,
                "risk_binding_source": "direct_execute_quality_a",
                "decision": "allowed",
                "execution_mode": "direct_high_confidence_execution",
                "risk_application_reason": "No había active_watch previo; setup A se permite con protección inicial reducida.",
                "execution_status": "ready",
            }

        return {
            "can_execute": False,
            "allowed_risk_mode": "reduced",
            "max_risk_multiplier": 0.5,
            "risk_probability_score": confidence,
            "risk_binding_source": "direct_execute_degraded",
            "decision": "degraded_to_prepare_reduced",
            "execution_mode": "degraded_without_watch",
            "risk_application_reason": "Sin active_watch previo y sin confianza alta, la entrada no se autoriza todavía.",
            "execution_status": "blocked_without_active_watch",
        }

    @staticmethod
    def _active_watch_probability_score(
        *,
        active_watch: dict[str, Any],
        intelligence: dict[str, Any],
    ) -> float:
        metrics = [
            active_watch.get("current_confidence"),
            active_watch.get("current_harmony_score"),
            active_watch.get("current_setup_maturity"),
        ]
        normalized: list[float] = []
        for value in metrics:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            normalized.append(numeric / 100.0 if numeric > 1.0 else numeric)
        if normalized:
            return round(max(0.0, min(1.0, sum(normalized) / len(normalized))), 4)
        return round(float(intelligence["execution_readiness"].get("confidence") or 0.0), 4)

    @staticmethod
    def _demo_confirmed_signal_can_override_drop(
        *,
        signal: dict[str, Any],
        intelligence: dict[str, Any],
        account_is_demo: bool,
    ) -> bool:
        if not account_is_demo:
            return False
        readiness = intelligence.get("execution_readiness", {}) or {}
        if readiness.get("action") != "EXECUTE":
            return False
        if readiness.get("blockers"):
            return False
        event_risk = intelligence.get("event_risk", {}) or {}
        if event_risk.get("action") != "allow":
            return False
        if not signal.get("stop_price") or not signal.get("target_price"):
            return False
        if signal.get("selected_rr") is not None or signal.get("risk_reward") is not None:
            return True
        try:
            entry = float(signal.get("entry_price"))
            stop = float(signal.get("stop_price"))
            target = float(signal.get("target_price"))
        except (TypeError, ValueError):
            return False
        direction = str(signal.get("direction") or "").lower()
        risk = abs(entry - stop)
        reward = (target - entry) if direction == "buy" else (entry - target)
        return risk > 0 and reward > 0

    def _append_active_watch_history_event(
        self,
        *,
        symbol: str,
        event: str,
        active_watch: dict[str, Any],
    ) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "event": event,
            "side": active_watch.get("side"),
            "trigger_type": active_watch.get("trigger_type"),
            "operational_family": active_watch.get("operational_family"),
            "age_candles": active_watch.get("age_candles", 0),
            "confidence": float(active_watch.get("current_confidence") or active_watch.get("initial_confidence") or 0.0),
            "harmony_score": float(
                active_watch.get("current_harmony_score") or active_watch.get("initial_harmony_score") or 0.0
            ),
            "setup_maturity": float(
                active_watch.get("current_setup_maturity") or active_watch.get("initial_setup_maturity") or 0.0
            ),
            "progress": active_watch.get("progress"),
            "reason": active_watch.get("reason"),
            "missing_for_execute": active_watch.get("missing_for_execute", []),
            "cancel_risks": active_watch.get("cancel_conditions", []),
        }
        last_event = self._last_active_watch_history_event()
        comparable_keys = [
            "symbol",
            "event",
            "side",
            "trigger_type",
            "operational_family",
            "age_candles",
            "progress",
            "reason",
            "missing_for_execute",
            "cancel_risks",
        ]
        if last_event is not None and all(last_event.get(key) == payload.get(key) for key in comparable_keys):
            return
        with self.active_watch_history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _extract_current_candle_time(snapshot: dict[str, Any]) -> str:
        return str(snapshot["timeframes"]["M5"]["last_bar_time"])

    @staticmethod
    def _age_candles(created_candle_time: str, current_candle_time: str) -> int:
        created = datetime.fromisoformat(created_candle_time)
        current = datetime.fromisoformat(current_candle_time)
        return max(0, int((current - created).total_seconds() // 300))

    @staticmethod
    def _signal_has_executable_risk(signal: dict[str, Any] | None) -> bool:
        if signal is None:
            return False
        entry = signal.get("entry_price")
        stop = signal.get("stop_price")
        target = signal.get("target_price")
        direction = str(signal.get("direction", "")).lower()
        if entry is None or stop is None or target is None:
            return False
        entry_f = float(entry)
        stop_f = float(stop)
        target_f = float(target)
        if direction == "buy":
            risk = entry_f - stop_f
            reward = target_f - entry_f
        elif direction == "sell":
            risk = stop_f - entry_f
            reward = entry_f - target_f
        else:
            return False
        return risk > 0 and reward > 0

    def _can_trigger_active_watch(
        self,
        *,
        intelligence: dict[str, Any],
        account_status: dict[str, Any],
        active_watch: dict[str, Any],
    ) -> bool:
        signal = intelligence["overview"]["signal"]
        readiness = intelligence["execution_readiness"]
        current_harmony = float(
            intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("harmony_score") or 0.0
        )
        current_setup = float(readiness.get("setup_maturity") or 0.0)
        current_conf = float(readiness.get("confidence") or 0.0)
        initial_harmony = float(active_watch.get("initial_harmony_score") or 0.0)
        return (
            readiness.get("action") == "EXECUTE"
            and signal is not None
            and current_setup >= self.ACTIVE_WATCH_OPERATIONAL_SETUP_MATURITY
            and current_conf >= self.ACTIVE_WATCH_OPERATIONAL_CONFIDENCE
            and current_harmony >= initial_harmony - 0.08
            and self._signal_has_executable_risk(signal)
            and not readiness.get("blockers")
            and intelligence["event_risk"]["action"] == "allow"
            and bool(account_status.get("is_demo"))
        )

    def _sync_active_watch(
        self,
        *,
        symbol: str,
        intelligence: dict[str, Any],
        snapshot: dict[str, Any],
        account_status: dict[str, Any],
    ) -> dict[str, Any] | None:
        active_watch = self._load_active_watch()
        current_candle_time = self._extract_current_candle_time(snapshot)
        action = str(intelligence["execution_readiness"]["action"]).upper()
        preferred_side = intelligence["overview"]["market_state"].get("preferred_side")
        event_action = str(intelligence["event_risk"]["action"])
        market_regime = str(intelligence["overview"]["market_state"].get("market_regime") or "UNKNOWN").upper()
        current_confidence = float(intelligence["execution_readiness"].get("confidence") or 0.0)
        current_harmony = float(
            intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("harmony_score") or 0.0
        )
        current_setup_maturity = float(intelligence["execution_readiness"].get("setup_maturity") or 0.0)
        watch_trigger = intelligence.get("watch_trigger")
        current_operational_family = str(
            intelligence["overview"]["market_state"].get("operational_family")
            or (watch_trigger or {}).get("operational_family")
            or "NONE"
        )

        if active_watch and active_watch.get("symbol") != symbol and active_watch.get("status") == "ACTIVE":
            active_watch = None

        if active_watch and active_watch.get("status") == "ACTIVE":
            previous_confidence = float(
                active_watch.get("current_confidence") or active_watch.get("initial_confidence") or 0.0
            )
            previous_harmony = float(
                active_watch.get("current_harmony_score") or active_watch.get("initial_harmony_score") or 0.0
            )
            previous_setup = float(
                active_watch.get("current_setup_maturity") or active_watch.get("initial_setup_maturity") or 0.0
            )
            previous_missing_count = len(active_watch.get("missing_for_execute", []))
            age_candles = self._age_candles(str(active_watch["created_candle_time"]), current_candle_time)

            active_watch["current_confidence"] = current_confidence
            active_watch["current_harmony_score"] = current_harmony
            active_watch["current_setup_maturity"] = current_setup_maturity
            active_watch["age_candles"] = age_candles
            if watch_trigger:
                active_watch["required_conditions"] = watch_trigger.get(
                    "required_conditions", active_watch.get("required_conditions", [])
                )
                active_watch["cancel_conditions"] = watch_trigger.get(
                    "cancel_conditions", active_watch.get("cancel_conditions", [])
                )
                active_watch["missing_for_execute"] = watch_trigger.get(
                    "missing_for_execute", active_watch.get("missing_for_execute", [])
                )
                active_watch["operational_family"] = watch_trigger.get(
                    "operational_family", active_watch.get("operational_family")
                )
            elif current_operational_family == "OB_REJECTION_INSTITUTIONAL_EXECUTE":
                active_watch["operational_family"] = current_operational_family

            if age_candles >= int(active_watch.get("expiration_candles", self.ACTIVE_WATCH_EXPIRATION_CANDLES)):
                active_watch["status"] = "EXPIRED"
                active_watch["progress"] = "expired"
                active_watch["reason"] = "Expiró por exceso de velas sin activación."
                history_event = "WATCH_EXPIRED"
            elif event_action == "block":
                active_watch["status"] = "CANCELLED"
                active_watch["progress"] = "cancelled"
                active_watch["reason"] = "Se canceló por bloqueo macro activo."
                history_event = "WATCH_CANCELLED"
            elif action == "BLOCKED":
                active_watch["status"] = "CANCELLED"
                active_watch["progress"] = "cancelled"
                active_watch["reason"] = "Se canceló porque la inteligencia bloqueó el contexto."
                history_event = "WATCH_CANCELLED"
            elif preferred_side not in (None, "", "NEUTRAL") and str(preferred_side).upper() != str(active_watch.get("side")):
                active_watch["status"] = "CANCELLED"
                active_watch["progress"] = "cancelled"
                active_watch["reason"] = "Se canceló porque cambió el preferred_side."
                history_event = "WATCH_CANCELLED"
            elif market_regime in {"CHOP", "NON_OPERABLE", "DEAD"}:
                active_watch["status"] = "CANCELLED"
                active_watch["progress"] = "cancelled"
                active_watch["reason"] = "Se canceló porque el mercado pasó a régimen no operable."
                history_event = "WATCH_CANCELLED"
            elif current_harmony < max(0.35, float(active_watch.get("initial_harmony_score") or 0.0) - 0.2):
                active_watch["status"] = "CANCELLED"
                active_watch["progress"] = "cancelled"
                active_watch["reason"] = "Se canceló por deterioro fuerte de harmony_score."
                history_event = "WATCH_CANCELLED"
            elif current_setup_maturity < max(40.0, float(active_watch.get("initial_setup_maturity") or 0.0) - 15.0):
                active_watch["status"] = "CANCELLED"
                active_watch["progress"] = "cancelled"
                active_watch["reason"] = "Se canceló por deterioro fuerte de setup_maturity."
                history_event = "WATCH_CANCELLED"
            elif self._can_trigger_active_watch(
                intelligence=intelligence,
                account_status=account_status,
                active_watch=active_watch,
            ):
                active_watch["status"] = "TRIGGERED"
                active_watch["progress"] = "triggered"
                active_watch["reason"] = "La vigilancia se convirtió en EXECUTE."
                history_event = "WATCH_TRIGGERED"
            else:
                history_event = None
                if (
                    current_confidence >= previous_confidence + 0.04
                    or current_harmony >= previous_harmony + 0.05
                    or current_setup_maturity >= previous_setup + 5.0
                ):
                    active_watch["progress"] = "improving"
                    active_watch["reason"] = "El setup se está fortaleciendo."
                    history_event = "WATCH_IMPROVING"
                elif (
                    current_confidence <= previous_confidence - 0.04
                    or current_harmony <= previous_harmony - 0.05
                    or current_setup_maturity <= previous_setup - 5.0
                ):
                    active_watch["progress"] = "deteriorating"
                    active_watch["reason"] = "El setup perdió calidad, pero sigue activo."
                    history_event = "WATCH_DETERIORATING"
                else:
                    active_watch["progress"] = "stable"
                    active_watch["reason"] = "El setup sigue activo sin cambios decisivos."
                if history_event is None and watch_trigger:
                    current_missing_count = len(active_watch.get("missing_for_execute", []))
                    if current_missing_count != previous_missing_count:
                        history_event = "WATCH_UPDATED"
            self._save_active_watch(active_watch)
            if history_event is not None:
                self._append_active_watch_history_event(symbol=symbol, event=history_event, active_watch=active_watch)
            return active_watch

        if action == "WATCH" and watch_trigger:
            active_watch = {
                "symbol": symbol,
                "side": watch_trigger.get("side"),
                "trigger_type": watch_trigger.get("trigger_type"),
                "operational_family": watch_trigger.get("operational_family"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_candle_time": current_candle_time,
                "expiration_candles": self.ACTIVE_WATCH_EXPIRATION_CANDLES,
                "required_conditions": watch_trigger.get("required_conditions", []),
                "cancel_conditions": watch_trigger.get("cancel_conditions", []),
                "missing_for_execute": watch_trigger.get("missing_for_execute", []),
                "initial_missing_for_execute": watch_trigger.get("missing_for_execute", []),
                "initial_confidence": current_confidence,
                "initial_harmony_score": current_harmony,
                "initial_setup_maturity": current_setup_maturity,
                "current_confidence": current_confidence,
                "current_harmony_score": current_harmony,
                "current_setup_maturity": current_setup_maturity,
                "status": "ACTIVE",
                "age_candles": 0,
                "progress": "new",
                "reason": "Watch trigger activo; esperando confirmación operativa.",
            }
            self._save_active_watch(active_watch)
            self._append_active_watch_history_event(symbol=symbol, event="WATCH_CREATED", active_watch=active_watch)
            return active_watch

        self._save_active_watch(active_watch)
        return active_watch
