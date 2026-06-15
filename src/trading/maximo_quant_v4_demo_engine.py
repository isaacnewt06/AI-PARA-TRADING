"""Controlled MT5 demo execution for MAXIMO MTF Quant Institutional v4."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.core.config import Settings
from src.core.logging import get_logger
from src.trading.ai_harmony_auditor import AIHarmonyAuditor
from src.trading.controlled_demo_survival_protocol import ControlledDemoSurvivalProtocolV1
from src.trading.daily_demo_validation_report import DailyDemoValidationReport
from src.trading.armed_retest_engine import ArmedRetestEngine
from src.trading.entry_quality_engine import EntryQualityEngine
from src.trading.expansion_subtype_pretrade_audit import ExpansionSubtypePretradeAuditV1
from src.trading.execution_readiness_engine import ExecutionReadinessEngine
from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine
from src.trading.final_confirmation_engine import FinalConfirmationEngine
from src.trading.final_robustness_reporter import MaximoFinalRobustnessReporter
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester, StrategyVariant
from src.trading.maximo_quant_v4_market_intelligence import MaximoQuantV4MarketIntelligenceEngine
from src.trading.maximo_quant_v4_ob_aggressive_management import ob_aggressive_defensive_management_plan
from src.trading.maximo_quant_v4_yearly_analyzer import MaximoQuantV4YearlyAnalyzer
from src.trading.missed_opportunity_learning import MissedOpportunityLearning as AdvancedMissedOpportunityLearning
from src.trading.mt5_bridge import MT5Bridge
from src.trading.performance_lab import TradingAIPerformanceLab
from src.trading.q_learning_decision_memory import QLearningDecisionMemory
from src.trading.real_account_safety_gate import RealAccountSafetyGate
from src.trading.trade_experience_memory import TradeExperienceMemory

logger = get_logger(__name__)


class MaximoQuantV4DemoEngine:
    """Execute the best MAXIMO Quant v4 candidate on a demo-only MT5 account."""

    EXECUTION_MODE = "DEMO_REALISTIC_PROFIT_MODE"
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
    EARLY_SCALP_PROTECT_TRIGGER_R = 0.3
    EARLY_SCALP_ENTRY_RECOVERY_R = 0.05
    PROTECT_TRIGGER_R = 0.8
    TRAILING_TRIGGER_R = 1.0
    NEAR_TP_TRAIL_PROGRESS = 0.75
    MOMENTUM_DECAY_PROTECT_DRAWDOWN_R = 0.35
    MOMENTUM_DECAY_TRAIL_DRAWDOWN_R = 0.25
    SCALP_FAST_EXIT_MIN_R = 0.3
    MIN_POSITION_MANAGEMENT_VOLUME = 0.01
    REENTRY_COOLDOWN_MINUTES = 25
    REENTRY_COOLDOWN_MIN_MFE_R = 0.35
    REENTRY_COOLDOWN_ZONE_BUFFER_R = 0.5
    REENTRY_COOLDOWN_MIN_BUFFER_POINTS = 1.5
    REDUCED_SIGNAL_MIN_FINAL_CONFIRMATION = 75.0
    REDUCED_SIGNAL_MIN_ENTRY_QUALITY = 75.0
    REDUCED_SIGNAL_MIN_EXECUTION_READINESS = 78.0
    REDUCED_SIGNAL_TYPES = {
        "OB_AGGRESSIVE_REDUCED_SIGNAL",
        "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
        "SESSION_Q_LEARNING_REDUCED_SIGNAL",
        "ARMED_RETEST_REDUCED_SIGNAL",
        "ARMED_RETEST_CONTINUATION_REDUCED_SIGNAL",
        "M1_MICRO_TRIGGER_REDUCED_SIGNAL",
    }
    SENSEI_MANUAL_BIAS_SIGNAL_MAX_AGE_MINUTES = 12
    DAY_TRADE_MISSED_OPPORTUNITY_MAX_MINUTES = 45
    DAY_TRADE_MISSED_OPPORTUNITY_CONFIRM_R = 1.0
    DAY_TRADE_MISSED_OPPORTUNITY_FAIL_R = 0.6
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
        self.reports_dir = self.settings.paths.data_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.signal_path = self.demo_dir / "latest_signal.json"
        self.executions_path = self.demo_dir / "executions.csv"
        self.positions_path = self.demo_dir / "positions_snapshot.json"
        self.report_path = self.demo_dir / "demo_report.md"
        self.position_management_state_path = self.demo_dir / "position_management_state.json"
        self.position_management_history_path = self.demo_dir / "position_management_history.jsonl"
        self.position_management_history_path.touch(exist_ok=True)
        self.active_watch_path = self.demo_dir / "active_watch.json"
        self.active_watch_history_path = self.demo_dir / "active_watch_history.jsonl"
        self.watch_performance_report_path = self.demo_dir / "watch_performance_report.md"
        self.q_learning_table_path = self.demo_dir / "q_learning_table.json"
        self.q_learning_replay_path = self.demo_dir / "q_learning_experience_replay.jsonl"
        self.q_learning_report_path = self.demo_dir / "q_learning_report.md"
        self.missed_opportunity_state_path = self.demo_dir / "missed_opportunity_state.json"
        self.missed_opportunity_history_path = self.demo_dir / "missed_opportunity_learning.jsonl"
        self.missed_opportunity_history_path.touch(exist_ok=True)
        self.advanced_missed_opportunity_history_path = self.demo_dir / "missed_opportunities.jsonl"
        self.armed_retest_state_path = self.demo_dir / "armed_retest_state.json"
        self.armed_retest_history_path = self.demo_dir / "armed_retest_history.jsonl"
        self.best_trades_memory_path = self.demo_dir / "best_trades_memory.jsonl"
        self.worst_trades_memory_path = self.demo_dir / "worst_trades_memory.jsonl"
        self.decision_source_audit_path = self.demo_dir / "decision_source_audit.jsonl"
        self.expansion_subtype_pretrade_audit_path = self.demo_dir / "expansion_subtype_pretrade_audit_v1.jsonl"
        self.strategy_snapshot_path = self.settings.paths.data_dir / "strategies" / "maximo_quant_v4_best_current.json"
        self.market_situation_map_path = self.settings.paths.data_dir / "knowledge" / "market_situation_map.json"
        self.market_situation_map_md_path = self.settings.paths.data_dir / "knowledge" / "market_situation_map.md"
        self.market_intelligence_json_path = self.settings.paths.data_dir / "market_analysis" / "maximo_quant_v4" / "latest_market_intelligence.json"
        self.market_intelligence_engine = MaximoQuantV4MarketIntelligenceEngine(settings, bridge=self.bridge)
        self.controlled_demo_protocol = ControlledDemoSurvivalProtocolV1()
        self.expansion_subtype_pretrade_audit = ExpansionSubtypePretradeAuditV1()
        self.final_confirmation_engine = FinalConfirmationEngine()
        self.entry_quality_engine = EntryQualityEngine()
        self.execution_readiness_engine = ExecutionReadinessEngine()
        self.armed_retest_engine = ArmedRetestEngine(
            state_path=self.armed_retest_state_path,
            history_path=self.armed_retest_history_path,
        )
        self.trade_experience_memory = TradeExperienceMemory(
            best_path=self.best_trades_memory_path,
            worst_path=self.worst_trades_memory_path,
        )
        self.advanced_missed_opportunity_learning = AdvancedMissedOpportunityLearning(
            history_path=self.advanced_missed_opportunity_history_path,
            report_path=self.reports_dir / "MISSED_OPPORTUNITY_LEARNING_REPORT.md",
        )
        self.exit_quality_evaluator = ExitQualityEvaluator()
        self.performance_lab = TradingAIPerformanceLab(demo_dir=self.demo_dir, reports_dir=self.reports_dir)
        self.real_account_safety_gate = RealAccountSafetyGate(reports_dir=self.reports_dir)
        self.ai_harmony_auditor = AIHarmonyAuditor(reports_dir=self.reports_dir)
        self.final_robustness_reporter = MaximoFinalRobustnessReporter(reports_dir=self.reports_dir)
        self.daily_demo_validation_report = DailyDemoValidationReport(demo_dir=self.demo_dir, reports_dir=self.reports_dir)
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
            bars_by_timeframe={"M1": 500, "M5": 5000, "H1": 2000, "H4": 1000, "D1": 500},
        )
        higher_timeframe_context = self._build_higher_timeframe_context(snapshot=snapshot)
        intelligence = self._inject_higher_timeframe_context(
            intelligence=intelligence,
            higher_timeframe_context=higher_timeframe_context,
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
        market_pulse = self._market_pulse_score(
            intelligence=intelligence,
            execution_environment=execution_environment,
            snapshot=snapshot,
        )
        intelligence["market_pulse"] = market_pulse
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
        directional_synchronization = self._apply_directional_synchronization(
            symbol=symbol,
            intelligence=intelligence,
            active_watch=active_watch,
            q_learning_decision=q_learning_decision,
            market_pulse=market_pulse,
        )
        intelligence = directional_synchronization["intelligence"]
        active_watch = directional_synchronization["active_watch"]
        if directional_synchronization.get("changed"):
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
            q_learning_decision = self.q_learning_memory.evaluate_decision(
                symbol=symbol,
                intelligence=intelligence,
                active_watch=active_watch,
                active_watch_metrics=active_watch_metrics,
                watch_execution_policy=watch_execution_policy,
            )
            q_learning_decision["historical_seed"] = historical_q_seed
        q_learning_decision["directional_synchronization"] = directional_synchronization.get("summary", {})
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
        sensei_manual_bias_signal = self._build_sensei_manual_bias_reduced_signal(
            symbol=symbol,
            runtime=runtime,
            intelligence=intelligence,
            watch_execution_policy=watch_execution_policy,
        )
        if signal is None and sensei_manual_bias_signal is not None:
            signal = sensei_manual_bias_signal
            intelligence = self._inject_reduced_learning_signal(
                intelligence=intelligence,
                signal=sensei_manual_bias_signal,
                rationale=(
                    "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL habilita ejecución demo reducida por "
                    "liquidez + BMS/BOS + desplazamiento con SL/RR lógico."
                ),
            )
            readiness = intelligence["execution_readiness"]
            if active_watch is not None:
                active_watch["status"] = "TRIGGERED"
                active_watch["progress"] = "triggered"
                active_watch["reason"] = "Sensei manual bias confirmó trigger reducido ejecutable."
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
        m1_micro_signal = self._build_m1_micro_trigger_reduced_signal(
            symbol=symbol,
            runtime=runtime,
            intelligence=intelligence,
            snapshot=snapshot,
            market_pulse=market_pulse,
            execution_environment=execution_environment,
        )
        if signal is None and m1_micro_signal is not None:
            signal = m1_micro_signal
            intelligence = self._inject_reduced_learning_signal(
                intelligence=intelligence,
                signal=m1_micro_signal,
                rationale=(
                    "M1_MICRO_TRIGGER_REDUCED_SIGNAL habilita ejecución demo reducida: "
                    "tesis mayor + zona válida + gatillo M1 de rechazo/desplazamiento. "
                    "Sigue condicionado por FinalConfirmation, EntryQuality, ExecutionReadiness, "
                    "risk binding y guards de MT5."
                ),
            )
            readiness = intelligence["execution_readiness"]
            if active_watch is not None:
                active_watch["status"] = "TRIGGERED"
                active_watch["progress"] = "m1_micro_triggered"
                active_watch["reason"] = "M1 confirmó gatillo micro dentro de zona válida."
                self._save_active_watch(active_watch)
                self._append_active_watch_history_event(
                    symbol=symbol,
                    event="WATCH_TRIGGERED",
                    active_watch=active_watch,
                )
        armed_retest_signal = self.armed_retest_engine.build_reduced_signal_candidate(
            symbol=symbol,
            snapshot=snapshot,
            market_pulse=market_pulse,
            intelligence=intelligence,
        )
        if signal is None and armed_retest_signal is not None:
            armed_retest_signal["strategy_variant"] = runtime["strategy_variant"].code
            armed_retest_signal["session_variant"] = runtime["session_variant"].code
            signal = armed_retest_signal
            intelligence = self._inject_reduced_learning_signal(
                intelligence=intelligence,
                signal=armed_retest_signal,
                rationale=(
                    "ARMED_RETEST_REDUCED_SIGNAL habilita señal demo reducida porque el precio volvió "
                    "a la zona preparada; todavía debe pasar FinalConfirmation, EntryQuality, "
                    "ExecutionReadiness, risk binding y guards de ejecución."
                ),
            )
            readiness = intelligence["execution_readiness"]
            if active_watch is not None:
                active_watch["status"] = "TRIGGERED"
                active_watch["progress"] = "armed_retest_triggered"
                active_watch["reason"] = "ARMED_RETEST encontró retest válido y preparó señal reducida."
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
        execution_risk_decision = self._apply_market_pulse_risk_overlay(
            execution_risk_decision=execution_risk_decision,
            market_pulse=market_pulse,
            signal=signal,
        )
        direction_consistency_guard = self._signal_direction_consistency_guard(
            signal=signal,
            intelligence=intelligence,
            active_watch=active_watch,
            q_learning_decision=q_learning_decision,
        )
        if signal is not None and not positions and not direction_consistency_guard["allowed"]:
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
        final_confirmation = self.final_confirmation_engine.evaluate(
            symbol=symbol,
            signal=signal,
            intelligence=intelligence,
            active_watch=active_watch,
            market_pulse=market_pulse,
            execution_environment=execution_environment,
            q_learning_decision=q_learning_decision,
            direction_consistency_guard=direction_consistency_guard,
            snapshot=snapshot,
        )
        intelligence["final_confirmation"] = final_confirmation
        execution_risk_decision = self.final_confirmation_engine.apply_execution_guard(
            execution_risk_decision=execution_risk_decision,
            final_confirmation=final_confirmation,
            signal=signal,
        )
        if signal is not None and not positions:
            execution_risk_decision = self._apply_reentry_cooldown_guard(
                symbol=symbol,
                signal=signal,
                execution_risk_decision=execution_risk_decision,
            )
        execution_risk_decision = self._apply_account_risk_sizing(
            symbol=symbol,
            signal=signal,
            account_status=account_status,
            execution_risk_decision=execution_risk_decision,
        )
        entry_quality = self.entry_quality_engine.evaluate(
            signal=signal,
            intelligence=intelligence,
            active_watch=active_watch,
            final_confirmation=final_confirmation,
            execution_risk_decision=execution_risk_decision,
            execution_environment=execution_environment,
            market_pulse=market_pulse,
        )
        execution_readiness_quality = self.execution_readiness_engine.evaluate(
            final_confirmation=final_confirmation,
            market_pulse=market_pulse,
            direction_consistency_guard=direction_consistency_guard,
            execution_risk_decision=execution_risk_decision,
            q_learning_decision=q_learning_decision,
            intelligence=intelligence,
            entry_quality=entry_quality,
        )
        trade_experience_memory = self.trade_experience_memory.evaluate_signal(
            signal=signal,
            intelligence=intelligence,
            market_pulse=market_pulse,
            final_confirmation=final_confirmation,
            execution_readiness=execution_readiness_quality,
            entry_quality=entry_quality,
        )
        execution_risk_decision = self._apply_trade_experience_memory_guard(
            execution_risk_decision=execution_risk_decision,
            trade_experience_memory=trade_experience_memory,
            signal=signal,
        )
        armed_retest = self.armed_retest_engine.evaluate(
            symbol=symbol,
            signal=signal,
            intelligence=intelligence,
            active_watch=active_watch,
            final_confirmation=final_confirmation,
            market_pulse=market_pulse,
            execution_readiness=execution_readiness_quality,
            entry_quality=entry_quality,
            execution_risk_decision=execution_risk_decision,
            q_learning_decision=q_learning_decision,
            execution_environment=execution_environment,
            snapshot=snapshot,
        )
        execution_risk_decision = self._apply_execution_quality_gate(
            execution_risk_decision=execution_risk_decision,
            signal=signal,
            positions=positions,
            final_confirmation=final_confirmation,
            entry_quality=entry_quality,
            execution_readiness=execution_readiness_quality,
            armed_retest=armed_retest,
        )
        execution_risk_decision = self._apply_same_cycle_fast_exit_reentry_guard(
            execution_risk_decision=execution_risk_decision,
            signal=signal,
            position_management=position_management,
        )
        exit_quality = self.exit_quality_evaluator.evaluate(position_management=position_management)
        trade_experience_update = self.trade_experience_memory.record_from_position_management(
            position_management_history_path=self.position_management_history_path,
            intelligence=intelligence,
            final_confirmation=final_confirmation,
            execution_readiness=execution_readiness_quality,
            entry_quality=entry_quality,
        )
        trade_experience_memory["update"] = trade_experience_update
        trade_experience_memory["summary"] = self.trade_experience_memory.summary()
        q_learning_decision["trade_experience_memory"] = trade_experience_memory
        q_learning_decision["exit_quality_feedback"] = exit_quality
        intelligence["entry_quality"] = entry_quality
        intelligence["execution_readiness_quality"] = execution_readiness_quality
        intelligence["armed_retest"] = armed_retest
        intelligence["trade_experience_memory"] = trade_experience_memory
        intelligence["exit_quality"] = exit_quality

        execution: dict[str, Any] | None = None
        execution_status = self._resolve_execution_status(
            signal=signal,
            positions=positions,
            execution_risk_decision=execution_risk_decision,
            dry_run=dry_run,
        )
        if (
            signal is not None
            and execution_status not in {
                "no_signal",
                "position_already_open",
                "limit_signal_not_auto_executed",
                "dry_run_signal_detected",
            }
            and execution_risk_decision.get("can_execute")
            and not dry_run
        ):
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
            retcode = (execution.get("result") or {}).get("retcode") if execution else None
            execution_status = "demo_order_sent" if retcode == 10009 else f"demo_order_rejected_{retcode or 'unknown'}"

        missed_opportunity_learning = self._track_missed_opportunity_learning(
            symbol=symbol,
            intelligence=intelligence,
            signal=signal,
            execution_status=execution_status,
            snapshot=snapshot,
        )
        advanced_missed_opportunity_learning = self.advanced_missed_opportunity_learning.record_cycle(
            symbol=symbol,
            signal=signal,
            execution_status=execution_status,
            intelligence=intelligence,
            final_confirmation=final_confirmation,
            market_pulse=market_pulse,
            execution_readiness=execution_readiness_quality,
            entry_quality=entry_quality,
            armed_retest=armed_retest,
            snapshot=snapshot,
        )
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
        reasoning_snapshot["missed_opportunity_learning"] = missed_opportunity_learning
        reasoning_snapshot["advanced_missed_opportunity_learning"] = advanced_missed_opportunity_learning
        reasoning_snapshot["entry_quality"] = entry_quality
        reasoning_snapshot["execution_readiness_quality"] = execution_readiness_quality
        reasoning_snapshot["armed_retest"] = armed_retest
        reasoning_snapshot["trade_experience_memory"] = trade_experience_memory
        reasoning_snapshot["exit_quality"] = exit_quality
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
            position_management=position_management,
            final_confirmation=final_confirmation,
        )
        q_learning_decision["experience_update"] = q_learning_update
        reasoning_snapshot["q_learning_persistent_memory"]["experience_update"] = q_learning_update
        reasoning_snapshot["q_learning_persistent_memory"]["trade_experience_memory"] = trade_experience_memory
        reasoning_snapshot["q_learning_persistent_memory"]["exit_quality_feedback"] = exit_quality
        reasoning_snapshot["final_confirmation"] = final_confirmation

        performance_lab_summary = self.performance_lab.generate()
        real_account_safety_gate = self.real_account_safety_gate.evaluate(
            account_status=account_status,
            execution_environment=execution_environment,
            performance_summary=performance_lab_summary,
            latest_signal={"execution_mode": self.EXECUTION_MODE},
        )
        ai_harmony_audit = self.ai_harmony_auditor.generate(
            intelligence=intelligence,
            signal=signal,
            active_watch=active_watch,
            market_pulse=market_pulse,
            q_learning_decision=q_learning_decision,
            execution_risk_decision=execution_risk_decision,
            position_management=position_management,
            direction_consistency_guard=direction_consistency_guard,
            final_confirmation=final_confirmation,
            real_account_safety_gate=real_account_safety_gate,
        )
        final_robustness_reports = self.final_robustness_reporter.generate(
            symbol=symbol,
            execution_status=execution_status,
            intelligence=intelligence,
            final_confirmation=final_confirmation,
            execution_risk_decision=execution_risk_decision,
            performance_summary=performance_lab_summary,
            real_gate=real_account_safety_gate,
            harmony_audit=ai_harmony_audit,
            position_management=position_management,
        )
        validation_cycle_payload = self.daily_demo_validation_report.build_cycle_payload(
            symbol=symbol,
            execution_status=execution_status,
            intelligence=intelligence,
            signal=signal,
            final_confirmation=final_confirmation,
            execution_risk_decision=execution_risk_decision,
            market_pulse=market_pulse,
            position_management=position_management,
            q_learning_decision=q_learning_decision,
            open_positions=len(positions),
        )
        self.daily_demo_validation_report.append_cycle(validation_cycle_payload)

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
            final_confirmation,
            performance_lab_summary,
            real_account_safety_gate,
            ai_harmony_audit,
            final_robustness_reports,
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
            final_confirmation=final_confirmation,
            performance_lab_summary=performance_lab_summary,
            real_account_safety_gate=real_account_safety_gate,
            ai_harmony_audit=ai_harmony_audit,
            final_robustness_reports=final_robustness_reports,
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
            final_confirmation=final_confirmation,
            performance_lab_summary=performance_lab_summary,
            real_account_safety_gate=real_account_safety_gate,
            ai_harmony_audit=ai_harmony_audit,
            final_robustness_reports=final_robustness_reports,
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
            "execution_mode": self.EXECUTION_MODE,
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "dry_run": dry_run,
            "account_is_demo": account_status["is_demo"],
            "execution_status": execution_status,
            "open_positions": len(positions),
            "signal_detected": signal is not None,
            "intelligence_action": readiness.get("action"),
            "ai_execution_decision": self._ai_execution_decision_label(
                signal=signal,
                execution_risk_decision=execution_risk_decision,
                final_confirmation=final_confirmation,
                execution_status=execution_status,
            ),
            "operating_posture": posture,
            "harmony_score": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("harmony_score"),
            "higher_timeframe_context": intelligence.get("higher_timeframe_context"),
            "market_pulse": intelligence.get("market_pulse"),
            "market_clarity": intelligence["overview"]["market_state"].get("market_clarity"),
            "expected_entry_zone": intelligence["overview"]["market_state"].get("expected_entry_zone"),
            "entry_trigger_plan": intelligence["overview"]["market_state"].get("entry_trigger_plan"),
            "final_confirmation": final_confirmation,
            "final_confirmation_score": final_confirmation.get("final_confirmation_score"),
            "armed_retest": armed_retest,
            "armed_retest_status": armed_retest.get("action") or armed_retest.get("status"),
            "execution_readiness_quality": execution_readiness_quality,
            "execution_readiness_score": execution_readiness_quality.get("execution_readiness_score"),
            "entry_quality": entry_quality,
            "entry_quality_score": entry_quality.get("entry_quality_score"),
            "trade_experience_memory": trade_experience_memory,
            "memory_bias": trade_experience_memory.get("memory_bias"),
            "advanced_missed_opportunity_learning": advanced_missed_opportunity_learning,
            "missed_opportunity_learning_status": advanced_missed_opportunity_learning.get("status"),
            "exit_quality": exit_quality,
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
            "performance_lab": performance_lab_summary,
            "real_account_safety_gate": real_account_safety_gate,
            "ai_harmony_audit": ai_harmony_audit,
            "final_robustness_reports": final_robustness_reports,
            "daily_demo_validation_cycle": validation_cycle_payload,
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
                "position_management_history_jsonl": str(self.position_management_history_path.resolve()),
                "missed_opportunity_learning_jsonl": str(self.missed_opportunity_history_path.resolve()),
                "advanced_missed_opportunities_jsonl": str(self.advanced_missed_opportunity_history_path.resolve()),
                "armed_retest_history_jsonl": str(self.armed_retest_history_path.resolve()),
                "best_trades_memory_jsonl": str(self.best_trades_memory_path.resolve()),
                "worst_trades_memory_jsonl": str(self.worst_trades_memory_path.resolve()),
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
        state = self._refresh_reentry_cooldowns_from_closed_positions(
            state=state,
            current_tickets=current_tickets,
            symbol=symbol,
        )
        actions: list[dict[str, Any]] = []
        updates_sent = 0
        last_price = self._latest_snapshot_price(snapshot)
        management_feedback = {
            "be_applied": False,
            "partial_taken": False,
            "trailing_applied": False,
            "fast_exit_taken": False,
            "gave_back_profit": False,
            "momentum_decay_detected": False,
            "invalid_partial_fallback": False,
            "max_mfe_r": 0.0,
            "max_mae_r": 0.0,
            "actions_taken": [],
        }

        for position in positions:
            ticket = str(position.get("ticket") or "")
            if not ticket:
                continue
            side = self._position_side(position)
            entry = float(position.get("price_open") or 0.0)
            current = float(position.get("price_current") or last_price or entry)
            stop = float(position.get("sl") or 0.0)
            target = float(position.get("tp") or 0.0)
            volume = float(position.get("volume") or 0.0)
            profit = float(position.get("profit") or 0.0)
            position_state = state.get(ticket, {})
            initial_stop = float(position_state.get("initial_stop") or position_state.get("stop") or stop)
            risk = self._position_risk(side=side, entry=entry, stop=stop)
            initial_risk = float(position_state.get("initial_risk") or 0.0)
            if initial_risk <= 0:
                initial_risk = self._position_risk(side=side, entry=entry, stop=initial_stop)
            if risk <= 0 and initial_risk > 0:
                risk = initial_risk
            if risk <= 0:
                payload = {
                    "ticket": ticket,
                    "side": side,
                    "action": "skip",
                    "reason": "No hay SL lógico para calcular R y proteger la posición.",
                }
                actions.append(payload)
                self._append_position_management_history_event(
                    self._position_management_history_payload(
                        symbol=symbol,
                        position=position,
                        side=side,
                        entry=entry,
                        stop=stop,
                        target=target,
                        current=current,
                        profit=profit,
                        mfe_r=0.0,
                        mae_r=0.0,
                        current_r=0.0,
                        action_taken="skip",
                        reason=payload["reason"],
                    )
                )
                continue

            partial_taken = bool(position_state.get("partial_taken"))
            previous_best = float(position_state.get("best_price") or current)
            previous_worst = float(position_state.get("worst_price") or current)
            best_price = max(previous_best, current) if side == "BUY" else min(previous_best, current)
            worst_price = min(previous_worst, current) if side == "BUY" else max(previous_worst, current)
            current_favorable_r = self._favorable_r(side=side, entry=entry, price=current, risk=risk)
            current_adverse_r = max(0.0, -current_favorable_r)
            tp_progress = self._tp_progress(side=side, entry=entry, target=target, price=current)
            max_favorable_r = max(
                float(position_state.get("max_favorable_r") or 0.0),
                self._favorable_r(side=side, entry=entry, price=best_price, risk=risk),
                current_favorable_r,
            )
            max_adverse_r = max(
                float(position_state.get("max_adverse_r") or 0.0),
                max(0.0, -self._favorable_r(side=side, entry=entry, price=worst_price, risk=risk)),
                current_adverse_r,
            )
            management_feedback["max_mfe_r"] = max(float(management_feedback["max_mfe_r"]), max_favorable_r)
            management_feedback["max_mae_r"] = max(float(management_feedback["max_mae_r"]), max_adverse_r)
            momentum_decay = self._momentum_decay_detector(
                side=side,
                entry=entry,
                current=current,
                risk=risk,
                max_favorable_r=max_favorable_r,
                current_favorable_r=current_favorable_r,
                tp_progress=tp_progress,
                snapshot=snapshot,
            )
            if momentum_decay["detected"]:
                management_feedback["momentum_decay_detected"] = True
            if momentum_decay["gave_back_profit"]:
                management_feedback["gave_back_profit"] = True
            desired_sl, protection_level = self._desired_protective_stop(
                side=side,
                entry=entry,
                current=current,
                current_stop=stop,
                risk=risk,
                max_favorable_r=max_favorable_r,
                tp_progress=tp_progress,
            )
            if desired_sl is None and momentum_decay["protect_required"]:
                desired_sl, protection_level = self._forced_protective_stop(
                    side=side,
                    entry=entry,
                    current=current,
                    current_stop=stop,
                    risk=risk,
                    lock_r=0.05 if max_favorable_r < self.PROTECT_TRIGGER_R else 0.3,
                    level=momentum_decay["protection_level"],
                )
            state[ticket] = {
                **position_state,
                "symbol": position.get("symbol") or symbol,
                "side": side,
                "entry": entry,
                "current": current,
                "stop": stop,
                "initial_stop": initial_stop,
                "initial_risk": round(risk, 6),
                "target": target,
                "best_price": best_price,
                "worst_price": worst_price,
                "current_favorable_r": round(current_favorable_r, 4),
                "max_favorable_r": round(max_favorable_r, 4),
                "max_adverse_r": round(max_adverse_r, 4),
                "tp_progress": round(tp_progress, 4),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "protection_level": protection_level,
                "momentum_decay": momentum_decay,
            }

            if momentum_decay["fast_exit_required"]:
                exit_payload = {
                    "ticket": ticket,
                    "side": side,
                    "action": "fast_exit",
                    "volume_lots": volume,
                    "current_favorable_r": round(current_favorable_r, 4),
                    "max_favorable_r": round(max_favorable_r, 4),
                    "drawdown_from_mfe_r": momentum_decay["drawdown_from_mfe_r"],
                    "reason": momentum_decay["reason"],
                }
                if dry_run:
                    exit_payload["sent_to_mt5"] = False
                    exit_payload["reason"] = "Dry-run: se habría cerrado por pérdida de momentum. " + momentum_decay["reason"]
                else:
                    try:
                        close_result = self.bridge.close_position_partial(
                            symbol=str(position.get("symbol") or symbol),
                            ticket=int(position.get("ticket")),
                            side=side.lower(),
                            volume_lots=volume,
                            deviation_points=50,
                            magic_number=self.MAGIC_NUMBER,
                            comment="MAXIMO fast exit",
                        )
                        exit_payload["sent_to_mt5"] = True
                        exit_payload["mt5_result"] = close_result.get("result")
                        updates_sent += 1
                    except Exception as exc:  # pragma: no cover - broker/runtime behavior.
                        exit_payload["sent_to_mt5"] = False
                        exit_payload["error"] = str(exc)
                actions.append(exit_payload)
                management_feedback["fast_exit_taken"] = True
                management_feedback["actions_taken"].append("fast_exit")
                if dry_run or exit_payload.get("sent_to_mt5"):
                    state[ticket].update(
                        {
                            "fast_exit_taken": True,
                            "closed_by_fast_exit": True,
                            "closed_reason": exit_payload["reason"],
                            "closed_at": datetime.now(timezone.utc).isoformat(),
                            "last_action": "fast_exit",
                            "cooldown_required": True,
                        }
                    )
                    self._append_reentry_cooldown_from_position_state(
                        state=state,
                        payload=state[ticket],
                        symbol=symbol,
                    )
                self._append_position_management_history_event(
                    self._position_management_history_payload(
                        symbol=symbol,
                        position=position,
                        side=side,
                        entry=entry,
                        stop=stop,
                        target=target,
                        current=current,
                        profit=profit,
                        mfe_r=max_favorable_r,
                        mae_r=max_adverse_r,
                        current_r=current_favorable_r,
                        action_taken="fast_exit",
                        reason=exit_payload["reason"],
                        mt5_result=exit_payload.get("mt5_result"),
                        error=exit_payload.get("error"),
                    )
                )
                continue

            if not partial_taken and max_favorable_r >= self.PARTIAL_TRIGGER_R:
                partial_plan = self._partial_volume_plan(volume)
                partial_volume = partial_plan["partial_volume"]
                if partial_plan["valid"]:
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
                    management_feedback["partial_taken"] = bool(state[ticket].get("partial_taken"))
                    management_feedback["actions_taken"].append("partial_close")
                    self._append_position_management_history_event(
                        self._position_management_history_payload(
                            symbol=symbol,
                            position=position,
                            side=side,
                            entry=entry,
                            stop=stop,
                            target=target,
                            current=current,
                            profit=profit,
                            mfe_r=max_favorable_r,
                            mae_r=max_adverse_r,
                            current_r=current_favorable_r,
                            action_taken="partial_close",
                            reason=partial_payload["reason"],
                            mt5_result=partial_payload.get("mt5_result"),
                            error=partial_payload.get("error"),
                        )
                    )
                else:
                    fallback_payload = {
                        "ticket": ticket,
                        "side": side,
                        "action": "partial_skipped_min_lot_fallback",
                        "volume_lots": volume,
                        "current_favorable_r": round(current_favorable_r, 4),
                        "max_favorable_r": round(max_favorable_r, 4),
                        "reason": partial_plan["reason"],
                    }
                    actions.append(fallback_payload)
                    management_feedback["invalid_partial_fallback"] = True
                    management_feedback["actions_taken"].append("partial_skipped_min_lot_fallback")
                    self._append_position_management_history_event(
                        self._position_management_history_payload(
                            symbol=symbol,
                            position=position,
                            side=side,
                            entry=entry,
                            stop=stop,
                            target=target,
                            current=current,
                            profit=profit,
                            mfe_r=max_favorable_r,
                            mae_r=max_adverse_r,
                            current_r=current_favorable_r,
                            action_taken="partial_skipped_min_lot_fallback",
                            reason=partial_plan["reason"],
                        )
                    )
            if desired_sl is None:
                monitor_payload = {
                    "ticket": ticket,
                    "side": side,
                    "action": "monitor",
                    "current_favorable_r": round(current_favorable_r, 4),
                    "max_favorable_r": round(max_favorable_r, 4),
                    "mae_r": round(max_adverse_r, 4),
                    "tp_progress": round(tp_progress, 4),
                    "momentum_decay": momentum_decay,
                    "reason": "Aún no hay avance suficiente o el precio ya no permite mover SL sin hacerlo peor.",
                }
                actions.append(monitor_payload)
                self._append_position_management_history_event(
                    self._position_management_history_payload(
                        symbol=symbol,
                        position=position,
                        side=side,
                        entry=entry,
                        stop=stop,
                        target=target,
                        current=current,
                        profit=profit,
                        mfe_r=max_favorable_r,
                        mae_r=max_adverse_r,
                        current_r=current_favorable_r,
                        action_taken="monitor",
                        reason=monitor_payload["reason"],
                    )
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
            if protection_level.startswith("breakeven"):
                state[ticket]["be_applied"] = True
                management_feedback["be_applied"] = True
            if "trail" in protection_level or "trailing" in protection_level:
                state[ticket]["trailing_applied"] = True
                management_feedback["trailing_applied"] = True
            management_feedback["actions_taken"].append("protect_sl")
            self._append_position_management_history_event(
                self._position_management_history_payload(
                    symbol=symbol,
                    position=position,
                    side=side,
                    entry=entry,
                    stop=stop,
                    target=target,
                    current=current,
                    profit=profit,
                    mfe_r=max_favorable_r,
                    mae_r=max_adverse_r,
                    current_r=current_favorable_r,
                    action_taken="protect_sl",
                    reason=action_payload["reason"],
                    mt5_result=action_payload.get("mt5_result"),
                    error=action_payload.get("error"),
                )
            )

        cooldowns = self._active_reentry_cooldowns(state.get("_reentry_cooldowns") or [])
        if cooldowns:
            state["_reentry_cooldowns"] = cooldowns
        else:
            state.pop("_reentry_cooldowns", None)
        self._save_position_management_state(state)
        return {
            "status": "active" if positions else "inactive",
            "positions_managed": len(positions),
            "updates_sent": updates_sent,
            "dry_run": dry_run,
            "actions": actions,
            "state_path": str(self.position_management_state_path.resolve()),
            "history_path": str(self.position_management_history_path.resolve()),
            "feedback": management_feedback,
        }

    def _append_position_management_history_event(self, payload: dict[str, Any]) -> None:
        self.position_management_history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.position_management_history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _track_missed_opportunity_learning(
        self,
        *,
        symbol: str,
        intelligence: dict[str, Any],
        signal: dict[str, Any] | None,
        execution_status: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        current_price = self._latest_snapshot_price(snapshot)
        if current_price is None:
            return {"status": "no_price", "pending_count": 0, "events": []}
        state = self._load_missed_opportunity_state()
        pending = [item for item in state.get("pending", []) if isinstance(item, dict)]
        events: list[dict[str, Any]] = []
        refreshed: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for item in pending:
            side = str(item.get("side") or "").upper()
            entry = float(item.get("entry_price") or 0.0)
            risk = float(item.get("risk_per_unit") or 0.0)
            if side not in {"BUY", "SELL"} or entry <= 0 or risk <= 0:
                continue
            favorable_r = self._favorable_r(side=side, entry=entry, price=float(current_price), risk=risk)
            adverse_r = max(0.0, -favorable_r)
            expires_at = self._parse_iso_datetime(item.get("expires_at"))
            if favorable_r >= self.DAY_TRADE_MISSED_OPPORTUNITY_CONFIRM_R:
                event = self._missed_opportunity_event(
                    item=item,
                    event="MISSED_OPPORTUNITY_CONFIRMED",
                    current_price=float(current_price),
                    favorable_r=favorable_r,
                    adverse_r=adverse_r,
                    reason=(
                        "La IA dejó una oportunidad en WATCH/no_signal y el mercado avanzó >= 1R "
                        "en la dirección detectada dentro del horizonte day-trade."
                    ),
                )
                self._append_missed_opportunity_history_event(event)
                events.append(event)
            elif adverse_r >= self.DAY_TRADE_MISSED_OPPORTUNITY_FAIL_R:
                event = self._missed_opportunity_event(
                    item=item,
                    event="MISSED_OPPORTUNITY_INVALIDATED",
                    current_price=float(current_price),
                    favorable_r=favorable_r,
                    adverse_r=adverse_r,
                    reason="La idea no ejecutada fue invalidada antes de confirmar ventaja suficiente.",
                )
                self._append_missed_opportunity_history_event(event)
                events.append(event)
            elif expires_at is not None and expires_at <= now:
                event = self._missed_opportunity_event(
                    item=item,
                    event="MISSED_OPPORTUNITY_EXPIRED",
                    current_price=float(current_price),
                    favorable_r=favorable_r,
                    adverse_r=adverse_r,
                    reason="La idea no ejecutada expiró; horizonte day-trade agotado sin confirmación suficiente.",
                )
                self._append_missed_opportunity_history_event(event)
                events.append(event)
            else:
                item = dict(item)
                item["current_price"] = round(float(current_price), 3)
                item["current_favorable_r"] = round(favorable_r, 4)
                refreshed.append(item)

        candidate = self._extract_unexecuted_day_trade_candidate(
            symbol=symbol,
            intelligence=intelligence,
            signal=signal,
            execution_status=execution_status,
        )
        if candidate is not None and not self._missed_opportunity_duplicate(refreshed, candidate):
            refreshed.append(candidate)
            event = {
                "timestamp": now.isoformat(),
                "symbol": symbol,
                "event": "MISSED_OPPORTUNITY_WATCHED",
                "side": candidate.get("side"),
                "signal_type": candidate.get("signal_type"),
                "setup_type": candidate.get("setup_type"),
                "entry_price": candidate.get("entry_price"),
                "stop_price": candidate.get("stop_price"),
                "target_price": candidate.get("target_price"),
                "risk_per_unit": candidate.get("risk_per_unit"),
                "setup_maturity": candidate.get("setup_maturity"),
                "confidence": candidate.get("confidence"),
                "reason": "Candidato day-trade de alta calidad guardado para validar si la IA dejó pasar una oportunidad.",
            }
            self._append_missed_opportunity_history_event(event)
            events.append(event)

        self._save_missed_opportunity_state({"pending": refreshed})
        confirmed = [event for event in events if event.get("event") == "MISSED_OPPORTUNITY_CONFIRMED"]
        return {
            "status": "active",
            "pending_count": len(refreshed),
            "events": events[-5:],
            "confirmed_missed_count": len(confirmed),
            "latest_event": events[-1] if events else None,
            "learning_path": str(self.missed_opportunity_history_path.resolve()),
            "interpretation": (
                "La IA está auditando oportunidades no ejecutadas para autocorregir su criterio day-trade."
                if refreshed or events
                else "No hay oportunidad perdida en seguimiento."
            ),
        }

    def _extract_unexecuted_day_trade_candidate(
        self,
        *,
        symbol: str,
        intelligence: dict[str, Any],
        signal: dict[str, Any] | None,
        execution_status: str,
    ) -> dict[str, Any] | None:
        if signal is not None or execution_status != "no_signal":
            return None
        readiness = intelligence.get("execution_readiness", {}) or {}
        if str(readiness.get("action") or "").upper() != "WATCH":
            return None
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        manual_bias = ob_families.get("manual_bias", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        nested_manual_bias = (aggressive.get("checks") or {}).get("sensei_manual_bias") or {}
        candidate = (
            manual_bias.get("reduced_signal_candidate")
            or nested_manual_bias.get("reduced_signal_candidate")
            or aggressive.get("reduced_signal_candidate")
            or {}
        )
        if not candidate:
            return None
        signal_type = str(candidate.get("signal_type") or "")
        if signal_type != "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL":
            return None
        if not candidate.get("manual_bias_confirmation"):
            return None
        if not candidate.get("sl_logical_available") or not candidate.get("rr_evaluable"):
            return None
        side = str(candidate.get("direction") or "").upper()
        entry = float(candidate.get("entry_price") or 0.0)
        risk = float(candidate.get("risk_per_unit") or 0.0)
        if side not in {"BUY", "SELL"} or entry <= 0 or risk <= 0:
            return None
        setup_maturity = float(readiness.get("setup_maturity") or 0.0)
        confidence = float(readiness.get("confidence") or 0.0)
        if setup_maturity < 68.0 or confidence < 0.65:
            return None
        now = datetime.now(timezone.utc)
        return {
            "id": f"{symbol}|{side}|{signal_type}|{candidate.get('signal_time')}|{round(entry, 3)}",
            "symbol": symbol,
            "side": side,
            "signal_type": signal_type,
            "setup_type": candidate.get("setup_type") or "SENSEI_BIAS_REDUCED",
            "entry_price": round(entry, 3),
            "stop_price": round(float(candidate.get("stop_price") or 0.0), 3),
            "target_price": round(float(candidate.get("target_price") or 0.0), 3),
            "risk_per_unit": round(risk, 6),
            "selected_rr": candidate.get("selected_rr"),
            "setup_maturity": round(setup_maturity, 4),
            "confidence": round(confidence, 4),
            "harmony_score": (intelligence.get("overview", {}).get("knowledge_alignment", {}).get("harmony", {}) or {}).get("harmony_score"),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=self.DAY_TRADE_MISSED_OPPORTUNITY_MAX_MINUTES)).isoformat(),
            "source_reason": candidate.get("reduced_signal_reason"),
            "day_trade_profile": "M1/M5 session move; buscar 1R rapido, proteger BE/parcial y no sostener por horas.",
        }

    def _missed_opportunity_event(
        self,
        *,
        item: dict[str, Any],
        event: str,
        current_price: float,
        favorable_r: float,
        adverse_r: float,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": item.get("symbol"),
            "event": event,
            "side": item.get("side"),
            "signal_type": item.get("signal_type"),
            "setup_type": item.get("setup_type"),
            "entry_price": item.get("entry_price"),
            "stop_price": item.get("stop_price"),
            "target_price": item.get("target_price"),
            "current_price": round(current_price, 3),
            "favorable_r": round(favorable_r, 4),
            "adverse_r": round(adverse_r, 4),
            "setup_maturity": item.get("setup_maturity"),
            "confidence": item.get("confidence"),
            "reason": reason,
            "learning_action": "increase_autonomous_attention" if event == "MISSED_OPPORTUNITY_CONFIRMED" else "keep_observing",
        }

    def _load_missed_opportunity_state(self) -> dict[str, Any]:
        if not self.missed_opportunity_state_path.exists():
            return {"pending": []}
        try:
            payload = json.loads(self.missed_opportunity_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"pending": []}
        return payload if isinstance(payload, dict) else {"pending": []}

    def _save_missed_opportunity_state(self, state: dict[str, Any]) -> None:
        self.missed_opportunity_state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_missed_opportunity_history_event(self, payload: dict[str, Any]) -> None:
        self.missed_opportunity_history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.missed_opportunity_history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _build_higher_timeframe_context(self, *, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Build the H1/H4/D1 compass used to keep intraday entries in full-market context."""
        specs = {
            "H1": {"lookback": 20, "weight": 1.0, "role": "intraday_bias"},
            "H4": {"lookback": 18, "weight": 1.6, "role": "swing_structure"},
            "D1": {"lookback": 12, "weight": 2.0, "role": "daily_macro_bias"},
        }
        readings: dict[str, dict[str, Any]] = {}
        weighted = {"BUY": 0.0, "SELL": 0.0}
        total_directional_weight = 0.0

        for timeframe, spec in specs.items():
            candles = self._snapshot_candles(snapshot, timeframe)
            if len(candles) < 3:
                readings[timeframe] = {
                    "status": "missing",
                    "role": spec["role"],
                    "bars": len(candles),
                    "bias": "UNKNOWN",
                    "reason": f"No hay suficientes velas {timeframe} para sesgo mayor.",
                }
                continue
            lookback = min(int(spec["lookback"]), len(candles) - 1)
            latest = candles[-1]
            reference = candles[-lookback - 1]
            latest_close = self._safe_candle_value(latest, "close")
            reference_close = self._safe_candle_value(reference, "close")
            latest_open = self._safe_candle_value(latest, "open")
            recent = candles[-lookback - 1 :]
            highs = [self._safe_candle_value(item, "high") for item in recent]
            lows = [self._safe_candle_value(item, "low") for item in recent]
            if (
                latest_close is None
                or reference_close is None
                or latest_open is None
                or any(value is None for value in highs)
                or any(value is None for value in lows)
            ):
                readings[timeframe] = {
                    "status": "invalid",
                    "role": spec["role"],
                    "bars": len(candles),
                    "bias": "UNKNOWN",
                    "reason": f"Velas {timeframe} incompletas para calcular sesgo.",
                }
                continue
            recent_range = max(float(max(highs)) - float(min(lows)), 0.0)
            slope = float(latest_close) - float(reference_close)
            normalized_slope = slope / recent_range if recent_range > 0 else 0.0
            latest_body = float(latest_close) - float(latest_open)
            body_direction = "BUY" if latest_body > 0 else "SELL" if latest_body < 0 else "NEUTRAL"
            if normalized_slope >= 0.10:
                bias = "BUY"
            elif normalized_slope <= -0.10:
                bias = "SELL"
            else:
                bias = "NEUTRAL"
            if bias in weighted:
                weighted[bias] += float(spec["weight"])
                total_directional_weight += float(spec["weight"])
            readings[timeframe] = {
                "status": "available",
                "role": spec["role"],
                "bars": len(candles),
                "lookback_bars": lookback,
                "bias": bias,
                "body_direction": body_direction,
                "latest_close": round(float(latest_close), 5),
                "reference_close": round(float(reference_close), 5),
                "slope": round(slope, 5),
                "normalized_slope": round(normalized_slope, 5),
                "weight": spec["weight"],
                "reason": f"{timeframe} {bias}: cierre actual vs {lookback} velas y rango reciente.",
            }

        if total_directional_weight <= 0:
            major_bias = "NEUTRAL"
            alignment_score = 0.0
        else:
            major_bias = "BUY" if weighted["BUY"] > weighted["SELL"] else "SELL" if weighted["SELL"] > weighted["BUY"] else "NEUTRAL"
            alignment_score = abs(weighted["BUY"] - weighted["SELL"]) / total_directional_weight

        conflicts = [
            {
                "timeframe": timeframe,
                "bias": reading.get("bias"),
                "major_bias": major_bias,
                "reason": reading.get("reason"),
            }
            for timeframe, reading in readings.items()
            if major_bias in {"BUY", "SELL"} and reading.get("bias") in {"BUY", "SELL"} and reading.get("bias") != major_bias
        ]
        available = [timeframe for timeframe, reading in readings.items() if reading.get("status") == "available"]
        return {
            "status": "available" if {"H1", "H4", "D1"}.issubset(set(available)) else "partial" if available else "unavailable",
            "major_bias": major_bias,
            "alignment_score": round(alignment_score, 4),
            "weighted_bias": {side: round(value, 4) for side, value in weighted.items()},
            "available_timeframes": available,
            "conflicts": conflicts,
            "timeframes": readings,
            "reason": (
                f"Bias mayor {major_bias} con alineación {round(alignment_score, 4)} usando H1/H4/D1."
                if available
                else "No hay suficientes datos HTF para formar sesgo mayor."
            ),
        }

    def _inject_higher_timeframe_context(
        self,
        *,
        intelligence: dict[str, Any],
        higher_timeframe_context: dict[str, Any],
    ) -> dict[str, Any]:
        updated = json.loads(json.dumps(intelligence, ensure_ascii=False))
        updated["higher_timeframe_context"] = higher_timeframe_context
        market_state = updated.setdefault("overview", {}).setdefault("market_state", {})
        market_state["higher_timeframe_context"] = higher_timeframe_context
        major_bias = str(higher_timeframe_context.get("major_bias") or "NEUTRAL").upper()
        current_bias = str(market_state.get("higher_timeframe_bias") or "NEUTRAL").upper()
        market_state["major_timeframe_bias"] = major_bias
        if major_bias in {"BUY", "SELL"}:
            if current_bias not in {"BUY", "SELL"} or float(higher_timeframe_context.get("alignment_score") or 0.0) >= 0.67:
                market_state["higher_timeframe_bias"] = major_bias
            elif current_bias != major_bias:
                market_state["higher_timeframe_bias_conflict"] = {
                    "existing_bias": current_bias,
                    "h1_h4_d1_major_bias": major_bias,
                    "reason": "El sesgo interno previo no coincide con la brújula H1/H4/D1.",
                }
        watch_trigger = updated.get("watch_trigger")
        if isinstance(watch_trigger, dict):
            watch_trigger["higher_timeframe_context"] = higher_timeframe_context
            watch_bias = str(watch_trigger.get("higher_timeframe_bias") or "NEUTRAL").upper()
            if major_bias in {"BUY", "SELL"} and watch_bias not in {"BUY", "SELL"}:
                watch_trigger["higher_timeframe_bias"] = major_bias
            projection = watch_trigger.setdefault("pattern_projection", {})
            if isinstance(projection, dict):
                projection["higher_timeframe_context"] = higher_timeframe_context
                projection_bias = str(projection.get("higher_timeframe_bias") or "NEUTRAL").upper()
                if major_bias in {"BUY", "SELL"} and projection_bias not in {"BUY", "SELL"}:
                    projection["higher_timeframe_bias"] = major_bias
            updated["watch_trigger"] = watch_trigger
        return updated

    def _apply_directional_synchronization(
        self,
        *,
        symbol: str,
        intelligence: dict[str, Any],
        active_watch: dict[str, Any] | None,
        q_learning_decision: dict[str, Any],
        market_pulse: dict[str, Any],
    ) -> dict[str, Any]:
        """Synchronize directional thesis across learned layers before execution checks."""
        updated = json.loads(json.dumps(intelligence, ensure_ascii=False))
        market_state = updated.get("overview", {}).get("market_state", {}) or {}
        readiness = updated.get("execution_readiness", {}) or {}
        watch_trigger = updated.get("watch_trigger") or {}
        projection = watch_trigger.get("pattern_projection") or {}
        matrix = projection.get("professional_decision_matrix") or {}
        higher_timeframe_context = (
            market_state.get("higher_timeframe_context")
            or watch_trigger.get("higher_timeframe_context")
            or updated.get("higher_timeframe_context")
            or {}
        )
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        manual_bias = ob_families.get("manual_bias", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        nested_manual_bias = (aggressive.get("checks") or {}).get("sensei_manual_bias") or {}
        manual_candidate = (
            manual_bias.get("reduced_signal_candidate")
            or nested_manual_bias.get("reduced_signal_candidate")
            or aggressive.get("reduced_signal_candidate")
            or {}
        )

        scores = {"BUY": 0.0, "SELL": 0.0}
        evidence: dict[str, list[str]] = {"BUY": [], "SELL": []}

        def add(side_value: Any, weight: float, reason: str) -> None:
            side = str(side_value or "").upper()
            if side not in scores:
                return
            scores[side] += weight
            evidence[side].append(reason)

        preferred_side = str(market_state.get("preferred_side") or "").upper()
        if preferred_side in scores:
            add(preferred_side, 1.2, "market_state preferred_side explícito")
        add(watch_trigger.get("candidate_side"), 1.0, "watch_trigger candidate_side")
        add(projection.get("candidate_side"), 1.0, "pattern_projection candidate_side")
        add(matrix.get("selected_side"), 1.4, "professional_decision_matrix selected_side")
        if bool(manual_bias.get("active")):
            add(manual_bias.get("side"), 2.2, "Sensei/manual bias activo")
        if bool(nested_manual_bias.get("active")):
            add(nested_manual_bias.get("side"), 1.4, "Sensei/manual bias anidado en OB agresivo")
        if bool(aggressive.get("active")):
            add(aggressive.get("side"), 1.3, "OB aggressive watch activo")
        if manual_candidate and bool(manual_candidate.get("manual_bias_confirmation")):
            add(manual_candidate.get("direction"), 1.9, "candidato Sensei con liquidez+BMS/BOS+desplazamiento")
        htf_major_bias = str(higher_timeframe_context.get("major_bias") or "").upper()
        htf_alignment = float(higher_timeframe_context.get("alignment_score") or 0.0)
        htf_weights = {"H1": 0.7, "H4": 1.1, "D1": 1.3}
        if htf_major_bias in scores:
            add(
                htf_major_bias,
                0.8 + min(1.0, htf_alignment),
                "Brújula H1/H4/D1 favorece el lado mayor",
            )
        for timeframe, reading in (higher_timeframe_context.get("timeframes") or {}).items():
            tf_bias = str((reading or {}).get("bias") or "").upper()
            if tf_bias in scores:
                add(tf_bias, htf_weights.get(str(timeframe), 0.4), f"{timeframe} confirma bias {tf_bias}")

        q_policy = str(q_learning_decision.get("q_policy_action") or q_learning_decision.get("policy_action") or "").upper()
        q_values = q_learning_decision.get("q_values") or {}
        if q_policy in scores:
            add(q_policy, 1.3, "Q-learning policy favorece el lado")
        if q_values:
            q_buy = float(q_values.get("BUY") or 0.0)
            q_sell = float(q_values.get("SELL") or 0.0)
            if abs(q_buy - q_sell) >= 0.03:
                add("BUY" if q_buy > q_sell else "SELL", 0.7, "Q-table tiene ventaja relativa")

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        selected_side, selected_score = ranked[0]
        runner_up_score = ranked[1][1]
        agreement_gap = selected_score - runner_up_score
        pulse_score = float(market_pulse.get("score") or 0.0)
        current_setup = float(readiness.get("setup_maturity") or 0.0)
        current_confidence = float(readiness.get("confidence") or 0.0)
        manual_confirmed = bool(manual_candidate.get("manual_bias_confirmation"))
        has_candidate_risk = bool(manual_candidate.get("sl_logical_available") and manual_candidate.get("rr_evaluable"))
        q_contradicts = q_policy in {"BUY", "SELL"} and q_policy != selected_side
        htf_selected_conflicts = [
            f"{timeframe}:{(reading or {}).get('bias')}"
            for timeframe, reading in (higher_timeframe_context.get("timeframes") or {}).items()
            if str((reading or {}).get("bias") or "").upper() in {"BUY", "SELL"}
            and str((reading or {}).get("bias") or "").upper() != selected_side
        ]
        htf_major_contradicts = htf_major_bias in {"BUY", "SELL"} and htf_major_bias != selected_side and htf_alignment >= 0.55
        strong_sync = (
            selected_score >= 4.0
            and agreement_gap >= 1.2
            and pulse_score >= 70.0
            and (manual_confirmed or not q_contradicts)
        )
        executable_bias_sync = (
            strong_sync
            and manual_confirmed
            and has_candidate_risk
            and pulse_score >= 82.0
            and current_setup >= 62.0
            and current_confidence >= 0.62
            and not q_contradicts
            and not htf_major_contradicts
        )

        changed = False
        summary = {
            "status": "synchronized" if strong_sync else "observing",
            "selected_side": selected_side if strong_sync else "NEUTRAL",
            "scores": {side: round(value, 4) for side, value in scores.items()},
            "agreement_gap": round(agreement_gap, 4),
            "pulse_score": round(pulse_score, 4),
            "manual_bias_confirmed": manual_confirmed,
            "q_policy_action": q_policy,
            "q_contradicts": q_contradicts,
            "higher_timeframe_major_bias": htf_major_bias or "NEUTRAL",
            "higher_timeframe_alignment_score": round(htf_alignment, 4),
            "higher_timeframe_conflicts": htf_selected_conflicts,
            "higher_timeframe_context": higher_timeframe_context,
            "executable_bias_sync": executable_bias_sync,
            "evidence": evidence.get(selected_side, []) if strong_sync else [],
            "reason": (
                f"Capas sincronizadas hacia {selected_side}; se permite preparar señal reducida con guards activos."
                if executable_bias_sync
                else f"Capas favorecen {selected_side}, pero H1/H4/D1 piden más confirmación."
                if strong_sync and htf_major_contradicts
                else f"Capas favorecen {selected_side}, pero aún se observa sin elevar ejecución."
                if strong_sync
                else "No hay suficiente acuerdo direccional entre capas."
            ),
        }

        market_state["directional_synchronization"] = summary
        updated["overview"]["market_state"] = market_state
        if not strong_sync:
            return {"intelligence": updated, "active_watch": active_watch, "changed": changed, "summary": summary}

        if preferred_side not in {"BUY", "SELL"}:
            market_state["preferred_side"] = selected_side
            changed = True
        watch_trigger["candidate_side"] = selected_side
        watch_trigger["side"] = selected_side
        watch_trigger["trigger_type"] = "bullish_confirmation" if selected_side == "BUY" else "bearish_confirmation"
        watch_trigger["directional_synchronization"] = summary
        watch_trigger["required_conditions"] = self._synchronized_required_conditions(
            side=selected_side,
            existing=watch_trigger.get("required_conditions") or [],
        )
        watch_trigger["cancel_conditions"] = self._synchronized_cancel_conditions(
            side=selected_side,
            existing=watch_trigger.get("cancel_conditions") or [],
        )
        missing = [
            item
            for item in watch_trigger.get("missing_for_execute", [])
            if "define dirección" not in str(item).lower()
            and "direccion preferida" not in str(item).lower()
            and "dirección preferida" not in str(item).lower()
        ]
        if executable_bias_sync:
            boosted_setup = max(current_setup, 69.0)
            boosted_confidence = max(current_confidence, 0.65)
            readiness["setup_maturity"] = round(boosted_setup, 4)
            readiness["confidence"] = round(boosted_confidence, 4)
            readiness["risk_mode"] = "reduced"
            readiness["rationale"] = list(readiness.get("rationale", [])) + [
                "DirectionalSynchronization: Sensei/manual bias, OB rejection, Market Pulse y Q-learning quedan armonizados."
            ]
            missing = [
                item
                for item in missing
                if "setup_maturity" not in str(item)
            ]
            if "Falta señal operativa confirmada." not in missing:
                missing.insert(0, "Falta señal operativa confirmada.")
        watch_trigger["setup_maturity"] = readiness.get("setup_maturity", current_setup)
        watch_trigger["confidence"] = readiness.get("confidence", current_confidence)
        watch_trigger["missing_for_execute"] = missing
        updated["watch_trigger"] = watch_trigger
        updated["execution_readiness"] = readiness

        synced_watch = dict(active_watch) if isinstance(active_watch, dict) else None
        if synced_watch is not None and str(synced_watch.get("status") or "").upper() == "ACTIVE":
            previous_side = str(synced_watch.get("side") or "").upper()
            if previous_side in {"BUY", "SELL"} and previous_side != selected_side:
                synced_watch["side"] = selected_side
                synced_watch["trigger_type"] = watch_trigger["trigger_type"]
                synced_watch["required_conditions"] = watch_trigger.get("required_conditions", [])
                synced_watch["cancel_conditions"] = watch_trigger.get("cancel_conditions", [])
                synced_watch["missing_for_execute"] = watch_trigger.get("missing_for_execute", [])
                synced_watch["current_setup_maturity"] = readiness.get("setup_maturity", current_setup)
                synced_watch["current_confidence"] = readiness.get("confidence", current_confidence)
                synced_watch["progress"] = "realigned"
                synced_watch["reason"] = (
                    f"DirectionalSynchronization realineó active_watch de {previous_side} a {selected_side} "
                    "por consenso de Sensei/Q-learning/Market Pulse."
                )
                synced_watch["directional_synchronization"] = summary
                self._save_active_watch(synced_watch)
                self._append_active_watch_history_event(
                    symbol=symbol,
                    event="WATCH_UPDATED",
                    active_watch=synced_watch,
                )
                changed = True
        elif synced_watch is None and str(readiness.get("action") or "").upper() == "WATCH":
            synced_watch = {
                "symbol": symbol,
                "side": selected_side,
                "trigger_type": watch_trigger.get("trigger_type"),
                "operational_family": watch_trigger.get("operational_family"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_candle_time": datetime.now(timezone.utc).isoformat(),
                "expiration_candles": self.ACTIVE_WATCH_EXPIRATION_CANDLES,
                "required_conditions": watch_trigger.get("required_conditions", []),
                "cancel_conditions": watch_trigger.get("cancel_conditions", []),
                "missing_for_execute": watch_trigger.get("missing_for_execute", []),
                "initial_missing_for_execute": watch_trigger.get("missing_for_execute", []),
                "initial_confidence": readiness.get("confidence", current_confidence),
                "initial_harmony_score": (
                    updated.get("overview", {}).get("knowledge_alignment", {}).get("harmony", {}) or {}
                ).get("harmony_score", 0.0),
                "initial_setup_maturity": readiness.get("setup_maturity", current_setup),
                "current_confidence": readiness.get("confidence", current_confidence),
                "current_harmony_score": (
                    updated.get("overview", {}).get("knowledge_alignment", {}).get("harmony", {}) or {}
                ).get("harmony_score", 0.0),
                "current_setup_maturity": readiness.get("setup_maturity", current_setup),
                "status": "ACTIVE",
                "age_candles": 0,
                "progress": "synchronized",
                "reason": summary["reason"],
                "directional_synchronization": summary,
            }
            self._save_active_watch(synced_watch)
            self._append_active_watch_history_event(symbol=symbol, event="WATCH_CREATED", active_watch=synced_watch)
            changed = True
        return {"intelligence": updated, "active_watch": synced_watch, "changed": changed, "summary": summary}

    @staticmethod
    def _synchronized_required_conditions(*, side: str, existing: list[Any]) -> list[str]:
        side = str(side or "NEUTRAL").upper()
        directional = (
            "Cierre M5 alcista con micro BOS/continuación a favor de BUY."
            if side == "BUY"
            else "Cierre M5 bajista con micro BOS/continuación a favor de SELL."
        )
        opposite = "sell" if side == "BUY" else "buy"
        cleaned = []
        for item in existing:
            text = str(item)
            lowered = text.lower()
            if "define dirección" in lowered:
                continue
            if "dirección preferida" in lowered or "direccion preferida" in lowered:
                continue
            if "cierre m5" in lowered and opposite in lowered:
                continue
            if "higher_timeframe_bias" in lowered and opposite in lowered:
                continue
            if "stop loss lógico" in lowered and opposite in lowered:
                continue
            if text not in cleaned:
                cleaned.append(text)
        if directional not in cleaned:
            cleaned.insert(0, directional)
        return cleaned

    @staticmethod
    def _synchronized_cancel_conditions(*, side: str, existing: list[Any]) -> list[str]:
        side = str(side or "NEUTRAL").upper()
        if side == "BUY":
            directional = [
                "El lado candidato cambia a SELL.",
                "higher_timeframe_bias cambia claramente contra BUY.",
                "La estructura pierde intención alcista y vuelve a neutralidad fuerte.",
            ]
            opposite = "sell"
        elif side == "SELL":
            directional = [
                "El lado candidato cambia a BUY.",
                "higher_timeframe_bias cambia claramente contra SELL.",
                "La expansión se degrada a ruido o el mercado entra en zona no operable.",
            ]
            opposite = "buy"
        else:
            directional = [
                "El mercado vuelve a chop o rango no operable.",
                "La volatilidad se vuelve extrema sin estructura aprovechable.",
            ]
            opposite = ""

        cleaned = []
        for item in existing:
            text = str(item)
            lowered = text.lower()
            if "lado candidato cambia" in lowered and side.lower() in lowered:
                continue
            if opposite and "higher_timeframe_bias" in lowered and opposite in lowered:
                continue
            if side == "BUY" and "intención alcista" not in lowered and "contra sell" in lowered:
                continue
            if side == "SELL" and "contra buy" in lowered:
                continue
            if text not in cleaned:
                cleaned.append(text)

        for item in [
            "Aparece noticia macro bloqueante dentro de la ventana 5/5.",
            *directional,
            "harmony_score cae por debajo de 0.35.",
        ]:
            if item not in cleaned:
                cleaned.append(item)
        return cleaned

    @staticmethod
    def _missed_opportunity_duplicate(pending: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
        candidate_id = str(candidate.get("id") or "")
        for item in pending:
            if str(item.get("id") or "") == candidate_id:
                return True
        return False

    def _position_management_history_payload(
        self,
        *,
        symbol: str,
        position: dict[str, Any],
        side: str,
        entry: float,
        stop: float,
        target: float,
        current: float,
        profit: float,
        mfe_r: float,
        mae_r: float,
        current_r: float,
        action_taken: str,
        reason: str,
        mt5_result: Any | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ticket": str(position.get("ticket") or ""),
            "symbol": str(position.get("symbol") or symbol),
            "side": side,
            "entry": round(entry, 5),
            "sl": round(stop, 5),
            "tp": round(target, 5),
            "volume": float(position.get("volume") or 0.0),
            "current_price": round(current, 5),
            "profit": round(profit, 4),
            "mfe_r": round(mfe_r, 4),
            "mae_r": round(mae_r, 4),
            "current_r": round(current_r, 4),
            "action_taken": action_taken,
            "reason": reason,
            "mt5_result": mt5_result,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _partial_volume_plan(self, volume: float) -> dict[str, Any]:
        min_volume = self.MIN_POSITION_MANAGEMENT_VOLUME
        partial_volume = round(volume * self.PARTIAL_CLOSE_FRACTION, 2)
        remaining = round(volume - partial_volume, 2)
        if volume <= 0:
            return {"valid": False, "partial_volume": 0.0, "reason": "Volumen inválido para parcial."}
        if partial_volume < min_volume or remaining < min_volume or partial_volume >= volume:
            return {
                "valid": False,
                "partial_volume": partial_volume,
                "reason": (
                    "El lote mínimo del broker impide parcial válido; fallback: mover SL a BE/profit "
                    "o cerrar total si aparece momentum decay."
                ),
            }
        return {"valid": True, "partial_volume": partial_volume, "reason": "Parcial válido por volumen mínimo."}

    def _momentum_decay_detector(
        self,
        *,
        side: str,
        entry: float,
        current: float,
        risk: float,
        max_favorable_r: float,
        current_favorable_r: float,
        tp_progress: float,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        drawdown_from_mfe = max(0.0, max_favorable_r - current_favorable_r)
        contrary_m1 = self._strong_contrary_candle(snapshot=snapshot, timeframe="M1", side=side)
        contrary_m5 = self._strong_contrary_candle(snapshot=snapshot, timeframe="M5", side=side)
        recovered_entry = max_favorable_r >= self.BE_TRIGGER_R and current_favorable_r <= 0.05
        early_scalp_recovered_entry = (
            max_favorable_r >= self.EARLY_SCALP_PROTECT_TRIGGER_R
            and current_favorable_r <= self.EARLY_SCALP_ENTRY_RECOVERY_R
        )
        near_tp_rejection = tp_progress >= self.NEAR_TP_TRAIL_PROGRESS and drawdown_from_mfe >= self.MOMENTUM_DECAY_TRAIL_DRAWDOWN_R
        protect_required = (
            (max_favorable_r >= 0.5 and drawdown_from_mfe >= self.MOMENTUM_DECAY_PROTECT_DRAWDOWN_R)
            or (max_favorable_r >= 0.8 and drawdown_from_mfe >= self.MOMENTUM_DECAY_TRAIL_DRAWDOWN_R)
            or (max_favorable_r >= 0.5 and (contrary_m1 or contrary_m5))
            or (early_scalp_recovered_entry and (contrary_m1 or contrary_m5))
            or near_tp_rejection
        )
        fast_exit_required = (
            recovered_entry
            or early_scalp_recovered_entry
            or (max_favorable_r >= self.SCALP_FAST_EXIT_MIN_R and current_favorable_r < 0 and (contrary_m1 or contrary_m5))
        )
        reasons: list[str] = []
        if drawdown_from_mfe >= self.MOMENTUM_DECAY_PROTECT_DRAWDOWN_R:
            reasons.append("retroceso fuerte desde MFE")
        if contrary_m1:
            reasons.append("vela M1 contraria fuerte")
        if contrary_m5:
            reasons.append("vela M5 contraria fuerte")
        if recovered_entry:
            reasons.append("recuperó entrada después de +0.5R")
        if early_scalp_recovered_entry:
            reasons.append("recuperó entrada/casi BE después de +0.3R")
        if near_tp_rejection:
            reasons.append("rechazo cerca del TP")
        return {
            "detected": bool(protect_required or fast_exit_required),
            "protect_required": bool(protect_required),
            "fast_exit_required": bool(fast_exit_required),
            "gave_back_profit": bool(max_favorable_r >= 0.5 and current_favorable_r < 0.0),
            "drawdown_from_mfe_r": round(drawdown_from_mfe, 4),
            "contrary_m1": contrary_m1,
            "contrary_m5": contrary_m5,
            "recovered_entry": recovered_entry,
            "early_scalp_recovered_entry": early_scalp_recovered_entry,
            "near_tp_rejection": near_tp_rejection,
            "protection_level": "momentum_decay_be_or_profit_protection",
            "reason": "; ".join(reasons) or "Momentum estable.",
        }

    def _strong_contrary_candle(self, *, snapshot: dict[str, Any], timeframe: str, side: str) -> bool:
        candles = self._snapshot_candles(snapshot, timeframe)
        if not candles:
            return False
        candle = candles[-1]
        open_price = self._safe_candle_value(candle, "open")
        close_price = self._safe_candle_value(candle, "close")
        high = self._safe_candle_value(candle, "high")
        low = self._safe_candle_value(candle, "low")
        if open_price is None or close_price is None or high is None or low is None:
            return False
        candle_range = max(high - low, 0.0)
        if candle_range <= 0:
            return False
        body_ratio = abs(close_price - open_price) / candle_range
        if side == "BUY":
            return close_price < open_price and body_ratio >= 0.55
        return close_price > open_price and body_ratio >= 0.55

    @staticmethod
    def _safe_candle_value(candle: Any, field: str) -> float | None:
        try:
            return MaximoQuantV4DemoEngine._candle_value(candle, field)
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _forced_protective_stop(
        *,
        side: str,
        entry: float,
        current: float,
        current_stop: float,
        risk: float,
        lock_r: float,
        level: str,
    ) -> tuple[float | None, str]:
        min_distance = max(abs(entry) * 0.00005, 0.05)
        desired = entry + (risk * lock_r) if side == "BUY" else entry - (risk * lock_r)
        if side == "BUY":
            if desired >= current - min_distance or desired <= current_stop:
                return None, level
            return desired, level
        if desired <= current + min_distance or desired >= current_stop:
            return None, level
        return desired, level

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

    def _refresh_reentry_cooldowns_from_closed_positions(
        self,
        *,
        state: dict[str, Any],
        current_tickets: set[str],
        symbol: str,
    ) -> dict[str, Any]:
        cooldowns = self._active_reentry_cooldowns(state.get("_reentry_cooldowns") or [])
        for ticket, payload in state.items():
            if ticket.startswith("_") or ticket in current_tickets or not isinstance(payload, dict):
                continue
            cooldown = self._reentry_cooldown_from_position_state(payload=payload, symbol=symbol)
            if cooldown is not None and not self._reentry_cooldown_duplicate(cooldowns=cooldowns, candidate=cooldown):
                cooldowns.append(cooldown)

        refreshed = {
            ticket: payload
            for ticket, payload in state.items()
            if ticket in current_tickets and isinstance(payload, dict)
        }
        cooldowns = self._active_reentry_cooldowns(cooldowns)
        if cooldowns:
            refreshed["_reentry_cooldowns"] = cooldowns
        return refreshed

    def _append_reentry_cooldown_from_position_state(
        self,
        *,
        state: dict[str, Any],
        payload: dict[str, Any],
        symbol: str,
    ) -> None:
        cooldown = self._reentry_cooldown_from_position_state(payload=payload, symbol=symbol)
        if cooldown is None:
            return
        cooldowns = self._active_reentry_cooldowns(state.get("_reentry_cooldowns") or [])
        if not self._reentry_cooldown_duplicate(cooldowns=cooldowns, candidate=cooldown):
            cooldowns.append(cooldown)
        if cooldowns:
            state["_reentry_cooldowns"] = cooldowns

    def _reentry_cooldown_from_position_state(self, *, payload: dict[str, Any], symbol: str) -> dict[str, Any] | None:
        side = str(payload.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            return None
        entry = float(payload.get("entry") or 0.0)
        if entry <= 0:
            return None
        max_favorable_r = float(payload.get("max_favorable_r") or 0.0)
        protected = (
            bool(payload.get("be_applied"))
            or bool(payload.get("partial_taken"))
            or bool(payload.get("trailing_applied"))
            or str(payload.get("protection_level") or "").lower() not in {"", "monitoring"}
        )
        momentum_decay = payload.get("momentum_decay") or {}
        gave_back_profit = bool(momentum_decay.get("gave_back_profit"))
        closed_reason = str(payload.get("closed_reason") or "").lower()
        fast_exit_taken = (
            bool(payload.get("fast_exit_taken"))
            or bool(payload.get("closed_by_fast_exit"))
            or str(payload.get("last_action") or "").lower() == "fast_exit"
            or "fast exit" in closed_reason
            or "emergency" in closed_reason
            or "emergencia" in closed_reason
        )
        if (
            max_favorable_r < self.REENTRY_COOLDOWN_MIN_MFE_R
            and not protected
            and not gave_back_profit
            and not fast_exit_taken
        ):
            return None

        now = datetime.now(timezone.utc)
        initial_risk = float(payload.get("initial_risk") or 0.0)
        if initial_risk <= 0:
            stop = float(payload.get("initial_stop") or payload.get("stop") or 0.0)
            initial_risk = self._position_risk(side=side, entry=entry, stop=stop)
        zone_prices = [
            float(value)
            for value in [
                payload.get("entry"),
                payload.get("current"),
                payload.get("best_price"),
                payload.get("worst_price"),
            ]
            if value is not None and float(value) > 0
        ]
        if not zone_prices:
            zone_prices = [entry]
        return {
            "status": "ACTIVE",
            "symbol": str(payload.get("symbol") or symbol),
            "side": side,
            "entry": round(entry, 3),
            "zone_low": round(min(zone_prices), 3),
            "zone_high": round(max(zone_prices), 3),
            "initial_risk": round(initial_risk, 6),
            "max_favorable_r": round(max_favorable_r, 4),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=self.REENTRY_COOLDOWN_MINUTES)).isoformat(),
            "reason": (
                "La zona acaba de cerrar por fast exit/emergency exit; requiere estructura fresca "
                "antes de permitir otra entrada del mismo lado."
                if fast_exit_taken
                else "La zona ya produjo una oportunidad protegida/rechazada; requiere confirmación fresca "
                "antes de permitir otra entrada del mismo lado."
            ),
        }

    def _active_reentry_cooldowns(self, cooldowns: Any) -> list[dict[str, Any]]:
        if not isinstance(cooldowns, list):
            return []
        now = datetime.now(timezone.utc)
        active: list[dict[str, Any]] = []
        for cooldown in cooldowns:
            if not isinstance(cooldown, dict):
                continue
            if str(cooldown.get("status") or "ACTIVE").upper() != "ACTIVE":
                continue
            expires_at = self._parse_iso_datetime(cooldown.get("expires_at"))
            if expires_at is not None and expires_at <= now:
                continue
            active.append(cooldown)
        return active

    @staticmethod
    def _parse_iso_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _reentry_cooldown_duplicate(self, *, cooldowns: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
        candidate_entry = float(candidate.get("entry") or 0.0)
        candidate_risk = float(candidate.get("initial_risk") or 0.0)
        tolerance = max(self.REENTRY_COOLDOWN_MIN_BUFFER_POINTS, candidate_risk * 0.25)
        for cooldown in cooldowns:
            if str(cooldown.get("symbol") or "").lower() != str(candidate.get("symbol") or "").lower():
                continue
            if str(cooldown.get("side") or "").upper() != str(candidate.get("side") or "").upper():
                continue
            if abs(float(cooldown.get("entry") or 0.0) - candidate_entry) <= tolerance:
                return True
        return False

    def _apply_reentry_cooldown_guard(
        self,
        *,
        symbol: str,
        signal: dict[str, Any],
        execution_risk_decision: dict[str, Any],
    ) -> dict[str, Any]:
        if not execution_risk_decision.get("can_execute"):
            return execution_risk_decision
        side = str(signal.get("direction") or "").upper()
        entry = float(signal.get("entry_price") or 0.0)
        if side not in {"BUY", "SELL"} or entry <= 0:
            return execution_risk_decision
        state = self._load_position_management_state()
        cooldowns = self._active_reentry_cooldowns(state.get("_reentry_cooldowns") or [])
        if not cooldowns:
            return execution_risk_decision

        for cooldown in cooldowns:
            if str(cooldown.get("symbol") or "").lower() != symbol.lower():
                continue
            if str(cooldown.get("side") or "").upper() != side:
                continue
            if not self._signal_inside_reentry_cooldown_zone(entry=entry, signal=signal, cooldown=cooldown):
                continue
            blocked = dict(execution_risk_decision)
            reason = (
                "Bloqueado por reentry cooldown: la misma zona ya fue usada/protegida y luego rechazó. "
                "Esperar ruptura limpia, nuevo sweep/CHoCH o una estructura fresca antes de reentrar."
            )
            blocked.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_reentry_cooldown",
                    "execution_mode": "blocked_by_reentry_cooldown",
                    "risk_application_reason": reason,
                    "execution_status": "blocked_by_reentry_cooldown",
                    "reentry_cooldown_guard": {
                        "active": True,
                        "blocked": True,
                        "side": side,
                        "entry": entry,
                        "zone_low": cooldown.get("zone_low"),
                        "zone_high": cooldown.get("zone_high"),
                        "expires_at": cooldown.get("expires_at"),
                        "reason": cooldown.get("reason") or reason,
                    },
                }
            )
            return blocked
        return execution_risk_decision

    def _signal_inside_reentry_cooldown_zone(
        self,
        *,
        entry: float,
        signal: dict[str, Any],
        cooldown: dict[str, Any],
    ) -> bool:
        initial_risk = float(cooldown.get("initial_risk") or 0.0)
        signal_risk = float(signal.get("risk_per_unit") or 0.0)
        if signal_risk <= 0:
            stop = float(signal.get("stop_price") or 0.0)
            signal_risk = abs(entry - stop) if stop > 0 else 0.0
        buffer = max(
            self.REENTRY_COOLDOWN_MIN_BUFFER_POINTS,
            initial_risk * self.REENTRY_COOLDOWN_ZONE_BUFFER_R,
            signal_risk * self.REENTRY_COOLDOWN_ZONE_BUFFER_R,
            abs(entry) * 0.00015,
        )
        zone_low = float(cooldown.get("zone_low") or cooldown.get("entry") or entry) - buffer
        zone_high = float(cooldown.get("zone_high") or cooldown.get("entry") or entry) + buffer
        return zone_low <= entry <= zone_high

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
        hard_thesis_conflict = "persistent_q_learning_policy" in conflicts and any(
            item in conflicts
            for item in ["preferred_side", "watch_trigger_side", "active_watch_side", "professional_side", "probability_selected_side"]
        )
        if self._countertrend_reversal_scalp_is_valid(signal=signal, probability=probability):
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
        if hard_thesis_conflict:
            return {
                "allowed": False,
                "signal_side": signal_side,
                "expected_sides": expected,
                "conflicts": conflicts,
                "reason": (
                    f"Bloqueado: {signal_side} contradice preferred_side/Q-learning. "
                    "Solo se permite como COUNTERTREND_REVERSAL_SCALP con sweep, BOS/CHoCH, displacement, SL corto y riesgo reducido."
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
        if self._weak_persistent_q_learning_conflict_can_follow_market(
            signal_side=signal_side,
            conflicts=conflicts,
            q_learning_decision=q_learning_decision,
            layer_sync=layer_sync,
            course_sync=course_sync,
            matrix=matrix,
            probability=probability,
        ):
            return {
                "allowed": True,
                "signal_side": signal_side,
                "expected_sides": expected,
                "conflicts": conflicts,
                "reason": (
                    "Se permite ejecución reducida: Q-learning persistente es el único rezagado, "
                    "su ventaja es débil y mercado/cursos/watch están sincronizados con la señal."
                ),
            }
        if self._armed_retest_q_learning_conflict_can_follow_market(
            signal=signal,
            signal_side=signal_side,
            expected=expected,
            conflicts=conflicts,
        ):
            return {
                "allowed": True,
                "signal_side": signal_side,
                "expected_sides": expected,
                "conflicts": conflicts,
                "armed_retest_q_learning_override": True,
                "reason": (
                    "Se permite ejecución reducida: ARMED_RETEST materializó gatillo alineado con "
                    "preferred_side/market_clarity; Q-learning persistente queda como cautela, no veto."
                ),
            }
        if self._supervised_v56_direction_override_is_valid(
            signal=signal,
            signal_side=signal_side,
            expected=expected,
            conflicts=conflicts,
        ):
            return {
                "allowed": True,
                "signal_side": signal_side,
                "expected_sides": expected,
                "conflicts": conflicts,
                "supervised_v56_override": True,
                "reason": (
                    "Se permite avance reducido: señal v56/AGG históricamente rentable, "
                    "preferred_side alineado, confianza/impulso altos y único conflicto real es memoria Q-learning persistente."
                ),
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

    @staticmethod
    def _countertrend_reversal_scalp_is_valid(*, signal: dict[str, Any], probability: float) -> bool:
        if not bool(signal.get("countertrend_reversal_scalp")):
            return False
        if probability < 0.82:
            return False
        setup_type = str(signal.get("setup_type") or signal.get("signal_type") or "").upper()
        is_explicit_scalp = "COUNTERTREND_REVERSAL_SCALP" in setup_type or bool(signal.get("countertrend_reversal_scalp"))
        has_liquidity = bool(
            signal.get("liquidity_sweep")
            or signal.get("liquidity_grab")
            or signal.get("sweep_confirmed")
            or signal.get("liquidity_quality")
        )
        has_structure_shift = bool(signal.get("micro_bos") or signal.get("micro_choch") or signal.get("choch"))
        displacement = float(signal.get("displacement_score") or 0.0)
        risk_reduced = str(signal.get("risk_mode") or "reduced").lower() == "reduced"
        entry = float(signal.get("entry_price") or 0.0)
        stop = float(signal.get("stop_price") or 0.0)
        short_stop = True if entry <= 0 or stop <= 0 else abs(entry - stop) / entry <= 0.004
        return bool(is_explicit_scalp and has_liquidity and has_structure_shift and displacement >= 70 and risk_reduced and short_stop)

    @staticmethod
    def _armed_retest_q_learning_conflict_can_follow_market(
        *,
        signal: dict[str, Any],
        signal_side: str,
        expected: dict[str, str],
        conflicts: list[str],
    ) -> bool:
        if conflicts != ["persistent_q_learning_policy"]:
            return False
        signal_type = str(signal.get("signal_type") or signal.get("setup_type") or "").upper()
        if "ARMED_RETEST" not in signal_type:
            return False
        preferred_side = str(expected.get("preferred_side") or signal.get("preferred_side") or "").upper()
        clarity_aligned = preferred_side == signal_side or not preferred_side
        if not clarity_aligned:
            return False
        confidence = MaximoQuantV4DemoEngine._coerce_percent(signal.get("confidence"))
        try:
            selected_rr = float(signal.get("selected_rr") or 0.0)
        except (TypeError, ValueError):
            selected_rr = 0.0
        structure_ready = bool(signal.get("micro_bos") or signal.get("micro_choch") or signal.get("choch"))
        learned_bias_ready = bool(signal.get("manual_bias_confirmation") or signal.get("course_bias_confirmation"))
        continuation = MaximoQuantV4DemoEngine._coerce_percent(signal.get("continuation_momentum"))
        return bool(
            confidence >= 0.74
            and selected_rr >= 1.0
            and structure_ready
            and learned_bias_ready
            and continuation >= 0.55
        )

    @staticmethod
    def _supervised_v56_direction_override_is_valid(
        *,
        signal: dict[str, Any],
        signal_side: str,
        expected: dict[str, str],
        conflicts: list[str],
    ) -> bool:
        if conflicts != ["persistent_q_learning_policy"]:
            return False
        strategy_variant = str(signal.get("strategy_variant") or "").lower()
        setup_type = str(signal.get("setup_type") or signal.get("signal_type") or "").upper()
        signal_type = str(signal.get("signal_type") or "").upper()
        market_regime = str(signal.get("market_regime") or "").upper()
        preferred_side = str(expected.get("preferred_side") or signal.get("preferred_side") or "").upper()
        v56_like = (
            "v56" in strategy_variant
            or "AGG" in setup_type
            or "AGGRESSIVE" in signal_type
            or market_regime == "EXPANSION"
        )
        aggressive_family = "AGG" in setup_type or "AGGRESSIVE" in signal_type
        if not v56_like or not aggressive_family:
            return False
        if preferred_side != signal_side:
            return False
        confidence = MaximoQuantV4DemoEngine._coerce_percent(signal.get("confidence"))
        quant_score = MaximoQuantV4DemoEngine._coerce_percent(signal.get("quant_score"))
        impulse_score = MaximoQuantV4DemoEngine._coerce_percent(signal.get("impulse_score"))
        try:
            selected_rr = float(signal.get("selected_rr") or 0.0)
        except (TypeError, ValueError):
            selected_rr = 0.0
        return bool(confidence >= 0.78 and quant_score >= 0.70 and impulse_score >= 0.70 and selected_rr >= 1.2)

    @staticmethod
    def _coerce_percent(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric > 1.0:
            numeric /= 100.0
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _weak_persistent_q_learning_conflict_can_follow_market(
        *,
        signal_side: str,
        conflicts: list[str],
        q_learning_decision: dict[str, Any],
        layer_sync: dict[str, Any],
        course_sync: dict[str, Any],
        matrix: dict[str, Any],
        probability: float,
    ) -> bool:
        if conflicts != ["persistent_q_learning_policy"]:
            return False
        strategy_harmony = q_learning_decision.get("strategy_harmony_matrix") or {}
        q_policy = str(q_learning_decision.get("q_policy_action") or q_learning_decision.get("policy_action") or "").upper()
        selected_side = str(strategy_harmony.get("selected_side") or matrix.get("selected_side") or "").upper()
        if signal_side not in {"BUY", "SELL"} or selected_side != signal_side:
            return False
        if q_policy not in {"BUY", "SELL"} or q_policy == signal_side:
            return False
        try:
            q_value_gap = abs(float(strategy_harmony.get("q_value_gap") or q_learning_decision.get("value_gap") or 0.0))
        except (TypeError, ValueError):
            q_value_gap = 0.0
        try:
            agreement_ratio = float(strategy_harmony.get("agreement_ratio") or 0.0)
        except (TypeError, ValueError):
            agreement_ratio = 0.0
        try:
            layer_agreement_score = float(strategy_harmony.get("layer_agreement_score") or 0.0)
        except (TypeError, ValueError):
            layer_agreement_score = 0.0
        try:
            course_score = float(strategy_harmony.get("course_score") or course_sync.get("course_score") or 0.0)
        except (TypeError, ValueError):
            course_score = 0.0
        harmony_conflicts = [str(item) for item in (strategy_harmony.get("conflicts") or [])]
        stale_memory_only = harmony_conflicts and all(
            "persistent_q_learning" in item or "historical_backtest_prior" in item for item in harmony_conflicts
        )
        return bool(
            q_value_gap <= 0.12
            and probability >= 0.75
            and agreement_ratio >= 0.70
            and layer_agreement_score >= 0.80
            and str(layer_sync.get("status") or "") in {"synchronized", "mostly_aligned"}
            and str(strategy_harmony.get("course_status") or course_sync.get("status") or "").lower() in {"aligned", "partial"}
            and course_score >= 0.70
            and stale_memory_only
        )

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

    def _build_sensei_manual_bias_reduced_signal(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        intelligence: dict[str, Any],
        watch_execution_policy: dict[str, Any],
    ) -> dict[str, Any] | None:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        manual_bias = ob_families.get("manual_bias", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        nested_manual_bias = (aggressive.get("checks") or {}).get("sensei_manual_bias") or {}
        candidate = (
            manual_bias.get("reduced_signal_candidate")
            or nested_manual_bias.get("reduced_signal_candidate")
            or aggressive.get("reduced_signal_candidate")
            or {}
        )
        if not candidate:
            return None
        if str(candidate.get("signal_type") or "") != "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL":
            return None
        if not candidate.get("manual_bias_confirmation"):
            return None
        readiness = intelligence.get("execution_readiness", {}) or {}
        confidence = float(readiness.get("confidence") or 0.0)
        setup_maturity = float(readiness.get("setup_maturity") or 0.0)
        if watch_execution_policy.get("watch_policy_action") not in {"PREPARE_REDUCED", "PREPARE_NORMAL"}:
            return None
        if watch_execution_policy.get("allowed_risk_mode") not in {"reduced", "normal"}:
            return None
        if setup_maturity < 68.0 or confidence < 0.65:
            return None
        if not candidate.get("sl_logical_available") or not candidate.get("rr_evaluable"):
            return None
        if float(candidate.get("wick_rejection_quality") or 0.0) < 0.58:
            return None
        if float(candidate.get("displacement_score") or 0.0) < 75.0:
            return None
        if not (candidate.get("micro_bos") or candidate.get("continuation_momentum")):
            return None
        if not FinalConfirmationEngine._event_allows_final_confirmation(
            event_risk=intelligence.get("event_risk", {}) or {},
            signal={"signal_type": "M1_MICRO_TRIGGER_REDUCED_SIGNAL"},
        ):
            return None
        if not market_state.get("allowed_hour_by_strategy", False):
            return None
        if self._signal_is_stale(candidate.get("signal_time"), max_age_minutes=self.SENSEI_MANUAL_BIAS_SIGNAL_MAX_AGE_MINUTES):
            return None
        blocked = set(readiness.get("blockers", []))
        if blocked & {"high_impact_event_window", "hour_not_allowed", "chop_regime", "weak_knowledge_harmony"}:
            return None

        direction = str(candidate["direction"]).lower()
        return {
            "entry_kind": "market",
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "symbol": symbol,
            "timeframe": "M5",
            "signal_time": candidate.get("signal_time"),
            "entry_time": candidate.get("entry_time"),
            "direction": direction,
            "setup_type": candidate.get("setup_type") or "SENSEI_BIAS_REDUCED",
            "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
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
            "manual_bias_confirmation": True,
            "defensive_management_plan": ob_aggressive_defensive_management_plan(),
        }

    @classmethod
    def _signal_is_stale(cls, signal_time: Any, *, max_age_minutes: int) -> bool:
        parsed = cls._parse_iso_datetime(signal_time)
        if parsed is None:
            return False
        return datetime.now(timezone.utc) - parsed > timedelta(minutes=max_age_minutes)

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
        if not FinalConfirmationEngine._event_allows_final_confirmation(
            event_risk=intelligence.get("event_risk", {}) or {},
            signal={"signal_type": "M1_MICRO_TRIGGER_REDUCED_SIGNAL"},
        ):
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

    def _build_m1_micro_trigger_reduced_signal(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        intelligence: dict[str, Any],
        snapshot: dict[str, Any],
        market_pulse: dict[str, Any],
        execution_environment: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Translate a clear higher-timeframe thesis into a reduced M1 execution trigger.

        This is intentionally conservative: it does not invent a trade from a naked
        candle. It only acts when the bigger brain already has a side and zone, then
        M1 shows rejection, displacement, or micro-BOS with compact risk.
        """

        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        market_clarity = market_state.get("market_clarity") or {}
        readiness = intelligence.get("execution_readiness", {}) or {}
        side = str(
            market_clarity.get("selected_side")
            or market_clarity.get("preferred_side")
            or market_state.get("preferred_side")
            or market_state.get("higher_timeframe_bias")
            or ""
        ).upper()
        if side not in {"BUY", "SELL"}:
            return None
        if float(market_pulse.get("score") or 0.0) < 78.0:
            return None
        if not FinalConfirmationEngine._event_allows_final_confirmation(
            event_risk=intelligence.get("event_risk", {}) or {},
            signal={"signal_type": "M1_MICRO_TRIGGER_REDUCED_SIGNAL"},
        ):
            return None
        execution_environment = execution_environment or {}
        session_rd = str(execution_environment.get("session_rd") or execution_environment.get("session") or "")
        validated_session = session_rd in {"london_rd", "ny_rd", "pm_volatility_rd", "evening_volatility_rd"}
        if not market_state.get("allowed_hour_by_strategy", False) and not validated_session:
            return None
        blocked = set(readiness.get("blockers", []))
        if validated_session:
            blocked.discard("hour_not_allowed")
        if blocked & {"high_impact_event_window", "macro_event_not_allow", "chop_regime"}:
            return None

        expected_zone = (
            market_clarity.get("expected_entry_zone")
            or market_state.get("expected_entry_zone")
            or market_state.get("entry_trigger_plan", {}).get("expected_entry_zone")
            or {}
        )
        candles_m1 = self._snapshot_candles(snapshot, "M1")
        if len(candles_m1) < 8:
            return None
        zone_low, zone_high = self._expected_zone_bounds(expected_zone)
        if zone_low is None or zone_high is None:
            return None
        candidates: list[dict[str, Any]] = []
        lookback = min(5, len(candles_m1) - 7)
        for offset in range(lookback, 0, -1):
            trigger_index = len(candles_m1) - offset
            last = candles_m1[trigger_index]
            previous = candles_m1[max(0, trigger_index - 7) : trigger_index]
            if len(previous) < 4:
                continue
            entry = self._candle_value(last, "close")
            recent_window = candles_m1[max(0, trigger_index - 7) : trigger_index + 1]
            recent_high = max(self._candle_value(item, "high") for item in recent_window)
            recent_low = min(self._candle_value(item, "low") for item in recent_window)
            zone_buffer = max((zone_high - zone_low) * 0.15, abs(entry) * 0.00005)
            in_zone = (zone_low - zone_buffer) <= entry <= (zone_high + zone_buffer)
            if not in_zone and not expected_zone.get("in_zone_now"):
                continue

            open_price = self._candle_value(last, "open")
            high = self._candle_value(last, "high")
            low = self._candle_value(last, "low")
            candle_range = max(high - low, 0.001)
            body = abs(entry - open_price)
            body_ratio = body / candle_range
            avg_range = max(
                sum(max(self._candle_value(item, "high") - self._candle_value(item, "low"), 0.001) for item in previous)
                / max(len(previous), 1),
                0.001,
            )
            volume_ratio = self._volume_ratio(last=last, previous=previous)
            prev_high = max(self._candle_value(item, "high") for item in previous[-4:])
            prev_low = min(self._candle_value(item, "low") for item in previous[-4:])
            if side == "BUY":
                close_location = (entry - low) / candle_range
                side_candle = entry > open_price and close_location >= 0.55
                micro_bos = high > prev_high and entry > prev_high - candle_range * 0.30
                liquidity_sweep = low < prev_low and entry > prev_low
                stop = min(recent_low, zone_low) - max(avg_range * 0.25, abs(entry) * 0.00008)
                risk = entry - stop
                target = entry + risk * 1.45
                direction = "buy"
            else:
                close_location = (high - entry) / candle_range
                side_candle = entry < open_price and close_location >= 0.55
                micro_bos = low < prev_low and entry < prev_low + candle_range * 0.30
                liquidity_sweep = high > prev_high and entry < prev_high
                stop = max(recent_high, zone_high) + max(avg_range * 0.25, abs(entry) * 0.00008)
                risk = stop - entry
                target = entry - risk * 1.45
                direction = "sell"
            if risk <= 0:
                continue
            max_reasonable_risk = max(avg_range * 5.0, abs(entry) * 0.0025)
            if risk > max_reasonable_risk:
                continue

            displacement_score = min(
                95.0,
                max(
                    0.0,
                    (body_ratio * 34.0)
                    + (min(candle_range / avg_range, 2.5) * 18.0)
                    + (close_location * 22.0)
                    + (min(volume_ratio, 2.0) * 8.0)
                    + (8.0 if micro_bos else 0.0)
                    + (8.0 if liquidity_sweep else 0.0),
                ),
            )
            trigger_confirmed = side_candle and (micro_bos or liquidity_sweep or displacement_score >= 58.0)
            if not trigger_confirmed:
                continue
            candidates.append(
                {
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "risk": risk,
                    "direction": direction,
                    "in_zone": in_zone,
                    "body_ratio": body_ratio,
                    "avg_range": avg_range,
                    "candle_range": candle_range,
                    "close_location": close_location,
                    "volume_ratio": volume_ratio,
                    "micro_bos": micro_bos,
                    "liquidity_sweep": liquidity_sweep,
                    "displacement_score": displacement_score,
                    "trigger_age_bars": offset - 1,
                }
            )
        if not candidates:
            return None
        best = max(candidates, key=lambda item: (item["displacement_score"], -item["trigger_age_bars"]))
        entry = best["entry"]
        stop = best["stop"]
        target = best["target"]
        risk = best["risk"]
        direction = best["direction"]
        in_zone = best["in_zone"]
        body_ratio = best["body_ratio"]
        avg_range = best["avg_range"]
        candle_range = best["candle_range"]
        close_location = best["close_location"]
        volume_ratio = best["volume_ratio"]
        micro_bos = best["micro_bos"]
        liquidity_sweep = best["liquidity_sweep"]
        displacement_score = best["displacement_score"]
        confidence = round(min(88.0, max(70.0, float(market_pulse.get("score") or 0.0) * 0.55 + displacement_score * 0.45)))
        return {
            "entry_kind": "market",
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "symbol": symbol,
            "timeframe": "M1",
            "signal_time": self._extract_current_candle_time(snapshot),
            "entry_time": self._extract_current_candle_time(snapshot),
            "direction": direction,
            "setup_type": "M1_MICRO_TRIGGER",
            "signal_type": "M1_MICRO_TRIGGER_REDUCED_SIGNAL",
            "active_family": "M1_MICRO_TRIGGER",
            "entry_price": round(entry, 3),
            "stop_price": round(stop, 3),
            "target_price": round(target, 3),
            "risk_per_unit": round(risk, 3),
            "selected_rr": 1.45,
            "quant_score": market_state.get("quant_score"),
            "impulse_score": market_state.get("impulse_score"),
            "buy_mtf_score": market_state.get("buy_mtf_score"),
            "sell_mtf_score": market_state.get("sell_mtf_score"),
            "confidence": confidence,
            "market_regime": market_state.get("market_regime"),
            "hour_ny": market_state.get("hour_ny"),
            "preferred_side": side,
            "risk_mode": "reduced",
            "manual_bias_confirmation": True,
            "micro_bos": micro_bos,
            "micro_choch": micro_bos,
            "liquidity_sweep": liquidity_sweep,
            "continuation_momentum": round(displacement_score / 100.0, 4),
            "displacement_score": round(displacement_score, 2),
            "m1_micro_trigger": {
                "in_expected_zone": in_zone,
                "zone_low": round(zone_low, 3),
                "zone_high": round(zone_high, 3),
                "body_ratio": round(body_ratio, 4),
                "range_vs_average": round(candle_range / avg_range, 4),
                "close_location": round(close_location, 4),
                "volume_ratio": round(volume_ratio, 4),
                "micro_bos": micro_bos,
                "liquidity_sweep": liquidity_sweep,
                "trigger_age_bars": best["trigger_age_bars"],
            },
            "reduced_signal_reason": (
                "Tesis mayor clara y precio en zona; M1 confirmó rechazo/desplazamiento "
                "con SL compacto y RR evaluable."
            ),
            "defensive_management_plan": {
                "entry_management": "Entrada reducida; invalidar rápido si M1 absorbe el gatillo.",
                "profit_management": "BE obligatorio en +0.5R; si el lote no permite parcial, proteger SL.",
                "emergency_exit": "Fast exit si pierde entrada tras MFE positivo o aparece displacement contrario.",
            },
        }

    @staticmethod
    def _expected_zone_bounds(expected_zone: dict[str, Any]) -> tuple[float | None, float | None]:
        values: list[float] = []
        for key in ("from", "to", "low", "high", "lower", "upper", "zone_low", "zone_high"):
            value = expected_zone.get(key)
            if value is None:
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        if len(values) < 2:
            return None, None
        return min(values), max(values)

    @staticmethod
    def _volume_ratio(*, last: Any, previous: list[Any]) -> float:
        def volume(candle: Any) -> float:
            for field in ("volume", "tick_volume", "real_volume"):
                try:
                    return MaximoQuantV4DemoEngine._candle_value(candle, field)
                except (AttributeError, KeyError, TypeError, ValueError):
                    continue
            return 1.0

        current = max(volume(last), 1.0)
        average = max(sum(volume(item) for item in previous) / max(len(previous), 1), 1.0)
        return current / average

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
        h4 = snapshot.get("H4") or backtester._resample(h1, "H4")
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

    def _market_pulse_score(
        self,
        *,
        intelligence: dict[str, Any],
        execution_environment: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        readiness = intelligence.get("execution_readiness", {}) or {}
        event_risk = intelligence.get("event_risk", {}) or {}
        volatility = intelligence.get("volatility_intelligence", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        pattern_projection = watch_trigger.get("pattern_projection") or {}
        professional = pattern_projection.get("professional_decision_matrix") or {}
        features = self._market_pulse_candle_features(snapshot)

        components = {
            "session": 12 if self._market_pulse_session_ok(market_state) else 3,
            "spread": 12 if str(execution_environment.get("execution_viability") or "").upper() == "SAFE" else 4,
            "atr_ratio": self._market_pulse_numeric_score(market_state.get("atr_ratio") or volatility.get("atr_ratio"), ideal=1.0, weight=10),
            "range_ratio": self._market_pulse_numeric_score(market_state.get("range_ratio") or features.get("range_ratio"), ideal=1.0, weight=8),
            "impulse": min(10, max(0, float(market_state.get("impulse_score") or features.get("impulse_score") or 0.0) * 10)),
            "displacement": min(10, max(0, float(market_state.get("displacement_score") or features.get("displacement_score") or 0.0) / 10)),
            "chop": 8 if str(market_state.get("market_regime") or "").upper() not in {"CHOP", "RANGE_DEAD", "DEAD"} else 2,
            "volatility": 8 if str(volatility.get("state") or market_state.get("volatility_state") or "").lower() in {"tradable_normal", "tradable", "expansion"} else 4,
            "direction_alignment": 10 if professional.get("layer_synchronization", {}).get("status") in {"synchronized", "mostly_aligned"} else 5,
            "liquidity_sweep": 6 if self._market_pulse_has_liquidity(watch_trigger, market_state, professional) else 2,
            "continuation_quality": min(8, max(0, float(market_state.get("continuation_quality") or features.get("continuation_quality") or 0.0) * 8)),
            "execution_viability": 4 if event_risk.get("action") == "allow" else 0,
        }
        raw_score = round(sum(components.values()), 2)
        score = max(0.0, min(100.0, raw_score))
        if score <= 30:
            label = "dead_market"
            mode = "defense"
            interpretation = "Mercado pobre o inviable; no debe perseguir entradas."
        elif score <= 50:
            label = "observe"
            mode = "defense"
            interpretation = "Mercado utilizable solo para observación o riesgo mínimo."
        elif score <= 70:
            label = "normal_opportunity"
            mode = "normal"
            interpretation = "Contexto operable normal; requiere trigger y gestión estándar."
        elif score <= 85:
            label = "strong_opportunity"
            mode = "opportunity"
            interpretation = "Pulso fuerte; permite preparar ejecución si el resto de filtros acompaña."
        else:
            label = "predator_mode"
            mode = "predator"
            interpretation = "Pulso excepcional; el sistema puede actuar con máxima precisión si hay señal final válida."
        return {
            "score": score,
            "label": label,
            "mode": mode,
            "components": {key: round(value, 4) for key, value in components.items()},
            "readiness_action": readiness.get("action"),
            "risk_adjustment": "block" if score <= 30 else "reduce" if score <= 50 else "allow",
            "fast_management_if_in_trade": score <= 50,
            "interpretation": interpretation,
        }

    def _apply_market_pulse_risk_overlay(
        self,
        *,
        execution_risk_decision: dict[str, Any],
        market_pulse: dict[str, Any],
        signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        updated = dict(execution_risk_decision)
        if signal is None or not updated.get("can_execute"):
            updated["market_pulse"] = market_pulse
            return updated
        score = float(market_pulse.get("score") or 0.0)
        reason = str(updated.get("risk_application_reason") or "")
        if score <= 30:
            updated.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_market_pulse",
                    "execution_mode": "blocked_by_market_pulse",
                    "execution_status": "blocked_by_market_pulse",
                    "risk_application_reason": (
                        reason + " Market Pulse <= 30: mercado muerto/no viable para ejecución."
                    ).strip(),
                }
            )
        elif score <= 50:
            updated["allowed_risk_mode"] = "reduced"
            updated["max_risk_multiplier"] = min(float(updated.get("max_risk_multiplier") or 0.5), 0.25)
            updated["execution_mode"] = "market_pulse_reduced_execution"
            updated["risk_application_reason"] = (
                reason + " Market Pulse débil: solo riesgo reducido y gestión defensiva."
            ).strip()
        elif score >= 86 and updated.get("allowed_risk_mode") == "normal":
            updated["execution_mode"] = updated.get("execution_mode") or "predator_mode_normal_execution"
            updated["risk_application_reason"] = (
                reason + " Market Pulse predator: contexto fuerte, siempre sujeto a señal final y guardias."
            ).strip()
        updated["market_pulse"] = market_pulse
        return updated

    @staticmethod
    def _apply_trade_experience_memory_guard(
        *,
        execution_risk_decision: dict[str, Any],
        trade_experience_memory: dict[str, Any],
        signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        updated = dict(execution_risk_decision)
        updated["trade_experience_memory"] = trade_experience_memory
        if signal is None:
            return updated
        bias = str(trade_experience_memory.get("memory_bias") or "").upper()
        reason = str(updated.get("risk_application_reason") or "")
        if bias == "BLOCK" and updated.get("can_execute"):
            updated.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_trade_experience_memory",
                    "execution_mode": "blocked_by_trade_experience_memory",
                    "execution_status": "blocked_by_trade_experience_memory",
                    "risk_application_reason": (
                        reason + " TradeExperienceMemory bloquea: " + str(trade_experience_memory.get("reason"))
                    ).strip(),
                }
            )
        elif bias == "REDUCE_RISK" and updated.get("can_execute"):
            updated["allowed_risk_mode"] = "reduced"
            updated["max_risk_multiplier"] = min(float(updated.get("max_risk_multiplier") or 0.5), 0.5)
            updated["risk_application_reason"] = (
                reason + " TradeExperienceMemory exige riesgo reducido: " + str(trade_experience_memory.get("reason"))
            ).strip()
        return updated

    @classmethod
    def _apply_execution_quality_gate(
        cls,
        *,
        execution_risk_decision: dict[str, Any],
        signal: dict[str, Any] | None,
        positions: list[dict],
        final_confirmation: dict[str, Any],
        entry_quality: dict[str, Any],
        execution_readiness: dict[str, Any],
        armed_retest: dict[str, Any],
    ) -> dict[str, Any]:
        updated = dict(execution_risk_decision)
        updated["entry_quality"] = entry_quality
        updated["entry_quality_score"] = entry_quality.get("entry_quality_score")
        updated["execution_readiness_quality"] = execution_readiness
        updated["execution_readiness_score"] = execution_readiness.get("execution_readiness_score")
        updated["armed_retest"] = armed_retest
        updated["armed_retest_status"] = armed_retest.get("action") or armed_retest.get("status")
        if signal is None or positions or not updated.get("can_execute"):
            return updated

        final_score = float(final_confirmation.get("final_confirmation_score") or 0.0)
        entry_score = float(entry_quality.get("entry_quality_score") or 0.0)
        readiness_score = float(execution_readiness.get("execution_readiness_score") or 0.0)
        entry_decision = str(entry_quality.get("decision") or "")
        armed_action = str(armed_retest.get("action") or "")
        signal_type = str(signal.get("signal_type") or "").upper()
        trade_memory = updated.get("trade_experience_memory") or {}
        memory_bias = str(trade_memory.get("memory_bias") or "").upper()
        supervised_recovery = final_confirmation.get("supervised_v56_execute_recovery") or {}
        premium_discount = final_confirmation.get("premium_discount_analysis") or {}
        if armed_action in {"ARMED_RETEST_WAIT", "ARMED_RETEST_CREATED"}:
            updated.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_armed_retest_wait",
                    "execution_mode": "blocked_by_armed_retest_wait",
                    "execution_status": "blocked_by_armed_retest_wait",
                    "risk_application_reason": (
                        str(updated.get("risk_application_reason") or "")
                        + " ARMED_RETEST activo: esperar retest, SL compacto y confirmación >=75."
                    ).strip(),
                }
            )
            return updated
        reduced_signal_quality_ok = (
            final_score >= cls.REDUCED_SIGNAL_MIN_FINAL_CONFIRMATION
            and entry_score >= cls.REDUCED_SIGNAL_MIN_ENTRY_QUALITY
            and readiness_score >= cls.REDUCED_SIGNAL_MIN_EXECUTION_READINESS
            and entry_decision in {"EXECUTION_READY", "CLEAN_ENTRY"}
        )
        reduced_signal_armed_ready = armed_action == "ARMED_RETEST_EXECUTE_READY"
        reduced_signal_m1_micro_ready = (
            signal_type == "M1_MICRO_TRIGGER_REDUCED_SIGNAL"
            and final_score >= 68.0
            and entry_score >= 72.0
            and readiness_score >= 70.0
            and entry_decision in {"EXECUTION_READY", "CLEAN_ENTRY", "WAIT_RETEST"}
            and memory_bias != "BLOCK"
        )
        cautious_armed_retest_needs_maturity = (
            ("ARMED_RETEST" in signal_type or signal_type == "M1_MICRO_TRIGGER_REDUCED_SIGNAL")
            and memory_bias in {"CAUTION", "REDUCE_RISK"}
            and (final_score < 70.0 or readiness_score < 73.0)
        )
        if cautious_armed_retest_needs_maturity:
            updated.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_cautious_armed_retest_maturity",
                    "execution_mode": "blocked_by_cautious_armed_retest_maturity",
                    "execution_status": "blocked_by_cautious_armed_retest_maturity",
                    "risk_application_reason": (
                        str(updated.get("risk_application_reason") or "")
                        + " ARMED_RETEST con memoria cautelosa requiere final>=70 y readiness>=73 "
                        + f"antes de ejecutar. Actual final={final_score}, readiness={readiness_score}, "
                        + f"memory_bias={memory_bias}."
                    ).strip(),
                }
            )
            return updated
        if signal_type in cls.REDUCED_SIGNAL_TYPES and not (
            reduced_signal_quality_ok or reduced_signal_armed_ready or reduced_signal_m1_micro_ready
        ):
            updated.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_reduced_signal_quality_gate",
                    "execution_mode": "blocked_by_reduced_signal_quality_gate",
                    "execution_status": "blocked_by_reduced_signal_quality_gate",
                    "risk_application_reason": (
                        str(updated.get("risk_application_reason") or "")
                        + " Señal reducida bloqueada: requiere confirmación final >=75, "
                        + "EntryQuality >=75, ExecutionReadiness >=78, ARMED_RETEST_EXECUTE_READY "
                        + "o gatillo M1 válido con final>=68, EntryQuality>=72 y Readiness>=70. "
                        + f"Actual final={final_score}, entry={entry_score}, readiness={readiness_score}, "
                        + f"entry_decision={entry_decision}, armed={armed_action}."
                    ).strip(),
                }
            )
            return updated
        hard_entry_block = entry_decision in {"LATE_ENTRY_BLOCK", "TRAP_RISK_BLOCK", "INVALID_ZONE_BLOCK"}
        quality_context_relevant = final_score >= 60.0 or float((armed_retest.get("current_market_pulse_score") or 0.0)) >= 85.0
        readiness_entry_mismatch = quality_context_relevant and readiness_score < 78.0 and entry_score < 75.0
        supervised_poor_zone_reduced_ok = (
            bool(supervised_recovery.get("eligible"))
            and premium_discount.get("status") == "poor_premium_discount_location"
            and final_score >= 60.0
            and entry_score >= 70.0
            and readiness_score >= 73.5
            and not hard_entry_block
        )
        supervised_valid_zone_armed_ok = (
            bool(supervised_recovery.get("eligible"))
            and premium_discount.get("status") == "valid_premium_discount_location"
            and armed_action == "ARMED_RETEST_EXECUTE_READY"
            and final_score >= 70.0
            and entry_score >= 70.0
            and readiness_score >= 76.5
            and not hard_entry_block
        )
        if hard_entry_block or (
            readiness_entry_mismatch
            and not (supervised_poor_zone_reduced_ok or supervised_valid_zone_armed_ok)
        ):
            updated.update(
                {
                    "can_execute": False,
                    "allowed_risk_mode": "blocked",
                    "max_risk_multiplier": 0.0,
                    "decision": "blocked_by_execution_quality_gate",
                    "execution_mode": "blocked_by_execution_quality_gate",
                    "execution_status": "blocked_by_execution_quality_gate",
                    "risk_application_reason": (
                        str(updated.get("risk_application_reason") or "")
                        + f" QualityGate exige entrada limpia o retest armado; actual final={final_score}, "
                        + f"entry={entry_score}, readiness={readiness_score}, entry_decision={entry_decision}."
                    ).strip(),
                }
            )
        return updated

    @staticmethod
    def _apply_same_cycle_fast_exit_reentry_guard(
        *,
        execution_risk_decision: dict[str, Any],
        signal: dict[str, Any] | None,
        position_management: dict[str, Any],
    ) -> dict[str, Any]:
        updated = dict(execution_risk_decision)
        if signal is None or not updated.get("can_execute"):
            return updated
        side = str(signal.get("direction") or "").upper()
        if side not in {"BUY", "SELL"}:
            return updated
        actions = position_management.get("actions") or []
        same_side_fast_exit = [
            action
            for action in actions
            if str(action.get("action") or "") == "fast_exit"
            and str(action.get("side") or "").upper() == side
        ]
        if not same_side_fast_exit:
            return updated
        reason = (
            "Bloqueado por fast_exit del mismo ciclo: la IA acaba de salir de emergencia en el mismo lado. "
            "Debe esperar nueva estructura, retest limpio y cooldown antes de reentrar."
        )
        updated.update(
            {
                "can_execute": False,
                "allowed_risk_mode": "blocked",
                "max_risk_multiplier": 0.0,
                "decision": "blocked_by_same_cycle_fast_exit_reentry",
                "execution_mode": "blocked_by_same_cycle_fast_exit_reentry",
                "execution_status": "blocked_by_same_cycle_fast_exit_reentry",
                "risk_application_reason": (
                    str(updated.get("risk_application_reason") or "") + " " + reason
                ).strip(),
                "same_cycle_fast_exit_guard": {
                    "blocked": True,
                    "side": side,
                    "reason": reason,
                    "fast_exit_actions": same_side_fast_exit[-3:],
                },
            }
        )
        return updated

    def _market_pulse_candle_features(self, snapshot: dict[str, Any]) -> dict[str, float]:
        candles = self._snapshot_candles(snapshot, "M5") or self._snapshot_candles(snapshot, "M1")
        if len(candles) < 5:
            return {"range_ratio": 0.0, "impulse_score": 0.0, "displacement_score": 0.0, "continuation_quality": 0.0}
        ranges: list[float] = []
        bodies: list[float] = []
        directions: list[int] = []
        for candle in candles[-8:]:
            open_price = self._safe_candle_value(candle, "open")
            close_price = self._safe_candle_value(candle, "close")
            high = self._safe_candle_value(candle, "high")
            low = self._safe_candle_value(candle, "low")
            if None in {open_price, close_price, high, low}:
                continue
            ranges.append(max(float(high) - float(low), 0.0))
            bodies.append(abs(float(close_price) - float(open_price)))
            directions.append(1 if float(close_price) >= float(open_price) else -1)
        if not ranges:
            return {"range_ratio": 0.0, "impulse_score": 0.0, "displacement_score": 0.0, "continuation_quality": 0.0}
        latest_range = ranges[-1]
        avg_range = sum(ranges) / len(ranges)
        avg_body = sum(bodies) / len(bodies) if bodies else 0.0
        dominant_direction = max(directions.count(1), directions.count(-1)) / len(directions) if directions else 0.0
        return {
            "range_ratio": round(latest_range / avg_range, 4) if avg_range > 0 else 0.0,
            "impulse_score": round(min(1.0, avg_body / avg_range), 4) if avg_range > 0 else 0.0,
            "displacement_score": round(min(100.0, (latest_range / avg_range) * 50), 4) if avg_range > 0 else 0.0,
            "continuation_quality": round(dominant_direction, 4),
        }

    @staticmethod
    def _market_pulse_numeric_score(value: Any, *, ideal: float, weight: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return weight * 0.4
        if numeric <= 0:
            return weight * 0.3
        distance = abs(numeric - ideal)
        return max(weight * 0.25, weight * (1.0 - min(distance, 1.0) * 0.55))

    @staticmethod
    def _market_pulse_session_ok(market_state: dict[str, Any]) -> bool:
        if market_state.get("allowed_hour_by_strategy") is True:
            return True
        session = str(market_state.get("session") or market_state.get("session_name") or "").lower()
        return session in {"london", "new_york", "ny", "ny_am"}

    @staticmethod
    def _market_pulse_has_liquidity(
        watch_trigger: dict[str, Any],
        market_state: dict[str, Any],
        professional: dict[str, Any],
    ) -> bool:
        text = json.dumps({"watch": watch_trigger, "state": market_state, "professional": professional}, ensure_ascii=False).lower()
        return any(token in text for token in ["liquidity", "sweep", "grab", "equal high", "equal low", "order_block"])

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
        market_pulse = intelligence.get("market_pulse", {}) or {}
        higher_timeframe_context = (
            intelligence.get("higher_timeframe_context")
            or market_state.get("higher_timeframe_context")
            or watch_trigger.get("higher_timeframe_context")
            or {}
        )
        harmony = intelligence.get("overview", {}).get("knowledge_alignment", {}).get("harmony", {}) or {}
        features = expansion_subtype_pretrade_audit.get("features", {}) or {}
        protocol_env = controlled_demo_survival_protocol.get("environment", {}) or {}
        side = str(watch_trigger.get("side") or market_state.get("preferred_side") or (signal or {}).get("direction") or "NONE").upper()
        setup_maturity = float(watch_trigger.get("setup_maturity") or readiness.get("setup_maturity") or 0.0)
        confidence = float(watch_trigger.get("confidence") or readiness.get("confidence") or 0.0)
        harmony_score = float(watch_trigger.get("harmony_score") or harmony.get("harmony_score") or 0.0)
        signal_candidate_detected = signal is not None or bool(watch_trigger.get("signal_detected"))
        blocked_signal_statuses = {
            "blocked_by_direction_consistency",
            "blocked_by_final_confirmation",
            "blocked_by_min_lot_exceeds_10_percent_account_risk",
            "blocked_by_reentry_cooldown",
            "blocked_by_execution_quality_gate",
            "blocked_by_armed_retest_wait",
            "blocked_by_trade_experience_memory",
        }
        signal_detected = bool(signal_candidate_detected and execution_status not in blocked_signal_statuses)
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
        raw_htf_bias = str(watch_trigger.get("higher_timeframe_bias") or market_state.get("higher_timeframe_bias") or "UNKNOWN").upper()
        context_major_bias = str(higher_timeframe_context.get("major_bias") or "NEUTRAL").upper()
        htf_bias = context_major_bias if raw_htf_bias not in {"BUY", "SELL"} and context_major_bias in {"BUY", "SELL"} else raw_htf_bias
        htf_ok = htf_bias in {side, "BOTH", "MIXED"} or (side in {"BUY", "SELL"} and htf_bias not in {"UNKNOWN", "NEUTRAL", "BUY" if side == "SELL" else "SELL"})
        missing = list(watch_trigger.get("missing_for_execute", []))
        critical_blocks = list(readiness.get("blockers", []))
        if not spread_safe:
            missing.append(
                f"Condición de ejecución no segura: spread/slippage {execution_environment.get('live_spread')} / {execution_environment.get('slippage_estimated')}."
            )
        if controlled_demo_survival_protocol.get("applies") and not controlled_demo_survival_protocol.get("allowed"):
            missing.append("El protocolo demo controlado todavía no permite esta familia/edge.")
        recovery_plan = execution_risk_decision.get("execution_recovery_plan") or {}
        if recovery_plan:
            missing.append(str(recovery_plan.get("reason") or "La geometría de riesgo exige esperar una entrada más precisa."))
            missing.extend(str(item) for item in recovery_plan.get("required_conditions", []) if item)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "state": {
                "action": readiness.get("action"),
                "execution_status": execution_status,
                "preferred_side": side,
                "signal_detected": signal_detected,
                "signal_candidate_detected": signal_candidate_detected,
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
            "higher_timeframe_context": higher_timeframe_context,
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
                "major_timeframe_bias": higher_timeframe_context.get("major_bias"),
                "higher_timeframe_alignment_score": higher_timeframe_context.get("alignment_score"),
                "higher_timeframe_conflicts": higher_timeframe_context.get("conflicts", []),
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
                "market_pulse_score": market_pulse.get("score"),
                "market_pulse_label": market_pulse.get("label"),
                "market_pulse_mode": market_pulse.get("mode"),
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
                "armed_retest_status": (intelligence.get("armed_retest") or {}).get("action"),
                "execution_readiness_score": (intelligence.get("execution_readiness_quality") or {}).get("execution_readiness_score"),
                "entry_quality_score": (intelligence.get("entry_quality") or {}).get("entry_quality_score"),
                "memory_bias": (intelligence.get("trade_experience_memory") or {}).get("memory_bias"),
                "exit_quality_score": (intelligence.get("exit_quality") or {}).get("exit_quality_score"),
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
                "extracted_knowledge_operational_brain": pattern_projection.get("extracted_knowledge_operational_brain", {}),
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
            "execution_recovery_plan": recovery_plan,
            "market_pulse": market_pulse,
            "armed_retest": intelligence.get("armed_retest") or {},
            "execution_readiness_quality": intelligence.get("execution_readiness_quality") or {},
            "entry_quality": intelligence.get("entry_quality") or {},
            "trade_experience_memory": intelligence.get("trade_experience_memory") or {},
            "exit_quality": intelligence.get("exit_quality") or {},
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
                "status": "active" if {"M1", "M5", "H1", "H4", "D1"}.issubset(set(map(str, timeframes.keys()))) else "partial",
                "timeframes_seen": list(timeframes.keys()),
                "purpose": "M1 para timing, M5 para trigger/setup, H1 para bias intradia, H4 para estructura swing y D1 para mapa macro.",
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
            "D1": "daily_macro_map",
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
                        "H1": "Validar sesgo intradía y evitar operar contra contexto principal.",
                        "H4": "Leer estructura swing, zonas mayores y continuidad probable.",
                        "D1": "Definir mapa macro diario para no perder la visión completa.",
                    }.get(str(timeframe), "Apoyar contexto multi-timeframe."),
                }
            )
        return readings

    @staticmethod
    def _resolve_execution_status(
        *,
        signal: dict[str, Any] | None,
        positions: list[dict],
        execution_risk_decision: dict[str, Any],
        dry_run: bool,
    ) -> str:
        """Resolve execution status from the unified AI execution chain only."""
        if signal is None:
            return "no_signal"
        if positions:
            return "position_already_open"
        if not execution_risk_decision.get("can_execute"):
            return str(
                execution_risk_decision.get("execution_status")
                or execution_risk_decision.get("decision")
                or "blocked_by_ai_execution_chain"
            )
        if str(signal.get("entry_kind") or "market") != "market":
            return "limit_signal_not_auto_executed"
        if dry_run:
            return "dry_run_signal_detected"
        return "ready_for_demo_order"

    @staticmethod
    def _ai_execution_decision_label(
        *,
        signal: dict[str, Any] | None,
        execution_risk_decision: dict[str, Any],
        final_confirmation: dict[str, Any],
        execution_status: str,
    ) -> str:
        if signal is None:
            return "WATCH"
        if execution_status in {"demo_order_sent", "dry_run_signal_detected", "ready_for_demo_order"}:
            return "EXECUTE"
        if execution_risk_decision.get("can_execute"):
            return str(final_confirmation.get("decision") or "EXECUTE").upper()
        if str(execution_status).startswith("blocked_") or str(execution_status).startswith("waiting_"):
            return "BLOCK"
        return str(final_confirmation.get("decision") or "WATCH").upper()

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
        final_confirmation: dict[str, Any],
        performance_lab_summary: dict[str, Any],
        real_account_safety_gate: dict[str, Any],
        ai_harmony_audit: dict[str, Any],
        final_robustness_reports: dict[str, Any],
    ) -> None:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "execution_mode": self.EXECUTION_MODE,
            "volume_lots": volume_lots,
            "dry_run": dry_run,
            "execution_status": execution_status,
            "intelligence_action": intelligence["execution_readiness"]["action"],
            "operating_posture": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("operating_posture"),
            "harmony_score": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("harmony_score"),
            "market_pulse": intelligence.get("market_pulse"),
            "final_confirmation": final_confirmation,
            "final_confirmation_score": final_confirmation.get("final_confirmation_score"),
            "armed_retest": intelligence.get("armed_retest"),
            "armed_retest_status": (intelligence.get("armed_retest") or {}).get("action"),
            "execution_readiness_quality": intelligence.get("execution_readiness_quality"),
            "execution_readiness_score": (intelligence.get("execution_readiness_quality") or {}).get("execution_readiness_score"),
            "entry_quality": intelligence.get("entry_quality"),
            "entry_quality_score": (intelligence.get("entry_quality") or {}).get("entry_quality_score"),
            "trade_experience_memory": intelligence.get("trade_experience_memory"),
            "memory_bias": (intelligence.get("trade_experience_memory") or {}).get("memory_bias"),
            "missed_opportunity_learning_status": (
                reasoning_snapshot.get("advanced_missed_opportunity_learning", {}) or {}
            ).get("status"),
            "exit_quality": intelligence.get("exit_quality"),
            "risk_mode": execution_risk_decision.get("allowed_risk_mode"),
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
            "performance_lab": performance_lab_summary,
            "real_account_safety_gate": real_account_safety_gate,
            "ai_harmony_audit": ai_harmony_audit,
            "final_robustness_reports": final_robustness_reports,
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
        final_confirmation: dict[str, Any],
        performance_lab_summary: dict[str, Any],
        real_account_safety_gate: dict[str, Any],
        ai_harmony_audit: dict[str, Any],
        final_robustness_reports: dict[str, Any],
    ) -> None:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "execution_mode": self.EXECUTION_MODE,
            "account_status": account_status,
            "positions": positions,
            "execution": execution,
            "intelligence_action": intelligence["execution_readiness"]["action"],
            "operating_posture": intelligence["overview"]["knowledge_alignment"].get("harmony", {}).get("operating_posture"),
            "higher_timeframe_context": intelligence.get("higher_timeframe_context"),
            "market_pulse": intelligence.get("market_pulse"),
            "final_confirmation": final_confirmation,
            "armed_retest": intelligence.get("armed_retest"),
            "execution_readiness_quality": intelligence.get("execution_readiness_quality"),
            "entry_quality": intelligence.get("entry_quality"),
            "trade_experience_memory": intelligence.get("trade_experience_memory"),
            "exit_quality": intelligence.get("exit_quality"),
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
            "performance_lab": performance_lab_summary,
            "real_account_safety_gate": real_account_safety_gate,
            "ai_harmony_audit": ai_harmony_audit,
            "final_robustness_reports": final_robustness_reports,
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
            "market_pulse_score",
            "market_pulse_label",
            "final_confirmation_score",
            "final_confirmation_decision",
            "execution_readiness_score",
            "execution_readiness_classification",
            "entry_quality_score",
            "entry_quality_decision",
            "armed_retest_status",
            "memory_bias",
            "exit_quality_score",
        ]
        protocol_env = controlled_demo_survival_protocol.get("environment", {})
        market_pulse = intelligence.get("market_pulse") or {}
        final_confirmation = intelligence.get("final_confirmation") or {}
        execution_readiness_quality = intelligence.get("execution_readiness_quality") or {}
        entry_quality = intelligence.get("entry_quality") or {}
        armed_retest = intelligence.get("armed_retest") or {}
        trade_experience_memory = intelligence.get("trade_experience_memory") or {}
        exit_quality = intelligence.get("exit_quality") or {}
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
            "market_pulse_score": market_pulse.get("score"),
            "market_pulse_label": market_pulse.get("label"),
            "final_confirmation_score": final_confirmation.get("final_confirmation_score"),
            "final_confirmation_decision": final_confirmation.get("decision"),
            "execution_readiness_score": execution_readiness_quality.get("execution_readiness_score"),
            "execution_readiness_classification": execution_readiness_quality.get("classification"),
            "entry_quality_score": entry_quality.get("entry_quality_score"),
            "entry_quality_decision": entry_quality.get("decision"),
            "armed_retest_status": armed_retest.get("action") or armed_retest.get("status"),
            "memory_bias": trade_experience_memory.get("memory_bias"),
            "exit_quality_score": exit_quality.get("exit_quality_score"),
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
        execution_readiness_quality = intelligence.get("execution_readiness_quality") or {}
        entry_quality = intelligence.get("entry_quality") or {}
        armed_retest = intelligence.get("armed_retest") or {}
        trade_experience_memory = intelligence.get("trade_experience_memory") or {}
        if not account_status.get("is_demo", False):
            blockers.append("account_not_demo")
        if execution_risk_decision.get("allowed_risk_mode") == "blocked":
            blockers.append("risk_binding_blocked")
        if execution_readiness_quality.get("blockers"):
            blockers.extend(str(item) for item in execution_readiness_quality.get("blockers", []))
        if entry_quality.get("decision") in {"WAIT_RETEST", "LATE_ENTRY_BLOCK", "TRAP_RISK_BLOCK", "INVALID_ZONE_BLOCK"}:
            blockers.append(str(entry_quality.get("decision")).lower())

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
        watch_trigger = intelligence.get("watch_trigger") or {}
        projection = watch_trigger.get("pattern_projection") or {}
        extracted_brain = (
            projection.get("extracted_knowledge_operational_brain")
            or ((projection.get("professional_decision_matrix") or {}).get("extracted_knowledge_operational_brain"))
            or {}
        )
        extracted_brain_role = str(extracted_brain.get("role") or "")
        extracted_brain_status = str(extracted_brain.get("status") or "")

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
            or extracted_brain_role in {"motor_principal_de_decision", "motor_de_confirmaciones"}
            or extracted_brain_status in {"primary_operational_brain", "armed_course_protocol"}
        )
        base_driver = signal is not None or bool(market_state.get("candidate_setups", {}).get("buy_agg")) or bool(
            market_state.get("candidate_setups", {}).get("sell_agg")
        )

        if external_driver:
            primary_driver = "external_filter"
            secondary_driver = "learned_knowledge" if knowledge_driver else "base_strategy"
        elif knowledge_driver and (
            dominant_family
            or extracted_brain_role in {"motor_principal_de_decision", "motor_de_confirmaciones"}
        ):
            primary_driver = "learned_knowledge"
            secondary_driver = "base_strategy"
        else:
            primary_driver = "base_strategy"
            secondary_driver = "learned_knowledge" if knowledge_driver else "external_filter"

        family_matches_strategy = dominant_family in {"OB Rejection", "Breakout Retest", "FVG Continuation", "Session Expansion"} and "v56" in base_variant
        learned_role = (
            "motor_principal"
            if primary_driver == "learned_knowledge"
            else "motor_principal_guarded_by_external_filter"
            if extracted_brain_role == "motor_principal_de_decision"
            else "motor_de_confirmaciones"
            if extracted_brain_role == "motor_de_confirmaciones"
            else "filtro"
            if knowledge_driver
            else "minimal"
        )

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
                "operational_brain": extracted_brain,
                "source_files": [
                    str(self.market_situation_map_path.resolve()),
                    str(self.market_situation_map_md_path.resolve()),
                    str(self.market_intelligence_json_path.resolve()),
                    str((self.settings.paths.knowledge_dir / "manual" / "sensei_manual_bias_protocol.md").resolve()),
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
                "execution_readiness_score": execution_readiness_quality.get("execution_readiness_score"),
                "execution_readiness_classification": execution_readiness_quality.get("classification"),
                "entry_quality_score": entry_quality.get("entry_quality_score"),
                "entry_quality_decision": entry_quality.get("decision"),
                "armed_retest_status": armed_retest.get("action") or armed_retest.get("status"),
                "memory_bias": trade_experience_memory.get("memory_bias"),
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
                "execution_readiness_score": execution_readiness_quality.get("execution_readiness_score"),
                "entry_quality_score": entry_quality.get("entry_quality_score"),
                "armed_retest_status": armed_retest.get("action") or armed_retest.get("status"),
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
        final_confirmation: dict[str, Any],
        performance_lab_summary: dict[str, Any],
        real_account_safety_gate: dict[str, Any],
        ai_harmony_audit: dict[str, Any],
        final_robustness_reports: dict[str, Any],
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
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        market_clarity = market_state.get("market_clarity") or {}
        expected_zone = market_clarity.get("expected_entry_zone") or market_state.get("expected_entry_zone") or {}
        trigger_plan = market_clarity.get("entry_trigger_plan") or market_state.get("entry_trigger_plan") or {}
        lines = [
            "# MAXIMO Quant v4 Demo Trading",
            "",
            f"- generated_at_utc: {datetime.now(timezone.utc).isoformat()}",
            f"- symbol: {symbol}",
            f"- execution_mode: {self.EXECUTION_MODE}",
            f"- strategy_variant: {runtime['strategy_variant'].code}",
            f"- session_variant: {runtime['session_variant'].code}",
            f"- dry_run: {dry_run}",
            f"- execution_status: {execution_status}",
            f"- intelligence_action: {intelligence['execution_readiness']['action']}",
            f"- preferred_side: {intelligence['overview']['market_state'].get('preferred_side')}",
            f"- operational_family: {intelligence['overview']['market_state'].get('operational_family')}",
            f"- operating_posture: {intelligence['overview']['knowledge_alignment'].get('harmony', {}).get('operating_posture')}",
            f"- harmony_score: {intelligence['overview']['knowledge_alignment'].get('harmony', {}).get('harmony_score')}",
            f"- final_confirmation_score: {final_confirmation.get('final_confirmation_score')}",
            f"- risk_mode: {execution_risk_decision.get('allowed_risk_mode')}",
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
        htf_context = reasoning_snapshot.get("higher_timeframe_context", {}) or {}
        if htf_context:
            lines.extend(
                [
                    "",
                    "### Higher Timeframe Compass",
                    f"- status: {htf_context.get('status')}",
                    f"- major_bias: {htf_context.get('major_bias')}",
                    f"- alignment_score: {htf_context.get('alignment_score')}",
                    f"- weighted_bias: {htf_context.get('weighted_bias')}",
                    f"- reason: {htf_context.get('reason')}",
                    "- timeframes:",
                ]
            )
            for timeframe, reading in (htf_context.get("timeframes") or {}).items():
                lines.append(
                    f"  - {timeframe}: bias={reading.get('bias')} role={reading.get('role')} "
                    f"slope={reading.get('normalized_slope')} | {reading.get('reason')}"
                )
            conflicts = htf_context.get("conflicts") or []
            lines.append("- conflicts:")
            if conflicts:
                for item in conflicts:
                    lines.append(f"  - {item}")
            else:
                lines.append("  - none")
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
                f"- major_timeframe_bias: {context.get('major_timeframe_bias')}",
                f"- higher_timeframe_alignment_score: {context.get('higher_timeframe_alignment_score')}",
                f"- higher_timeframe_conflicts: {context.get('higher_timeframe_conflicts')}",
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
        if market_clarity:
            lines.extend(
                [
                    "",
                    "### Market Clarity And Entry Zone",
                    f"- selected_side: {market_clarity.get('selected_side')}",
                    f"- clarity_score: {market_clarity.get('clarity_score')}",
                    f"- primary_situation: {market_clarity.get('primary_situation')}",
                    f"- wait_reason: {market_clarity.get('wait_reason')}",
                    f"- expected_entry_zone: {expected_zone}",
                    f"- fire_when: {trigger_plan.get('fire_when')}",
                    f"- compact_sl_reference: {trigger_plan.get('compact_sl_reference')}",
                    f"- target_reference: {trigger_plan.get('target_reference')}",
                    f"- liquidity_confirmed: {trigger_plan.get('liquidity_confirmed')}",
                    f"- continuation_quality: {trigger_plan.get('continuation_quality')}",
                    "- required_confirmation:",
                ]
            )
            for item in trigger_plan.get("required_confirmation", []) or []:
                lines.append(f"  - {item}")
            lines.append("- cancel_conditions:")
            for item in market_clarity.get("cancel_conditions", []) or []:
                lines.append(f"  - {item}")
            alignment = market_clarity.get("timeframe_alignment") or {}
            if alignment:
                lines.extend(
                    [
                        "- timeframe_alignment:",
                        f"  - dominant_side: {alignment.get('dominant_side')}",
                        f"  - alignment_score: {alignment.get('alignment_score')}",
                        f"  - buy_score: {alignment.get('buy_score')}",
                        f"  - sell_score: {alignment.get('sell_score')}",
                    ]
                )
                for timeframe, reading in (alignment.get("readings") or {}).items():
                    lines.append(f"  - {timeframe}: bias={reading.get('bias')} role={reading.get('role')}")
        pulse = reasoning_snapshot.get("market_pulse", {}) or {}
        lines.extend(
            [
                "",
                "### Market Pulse Score",
                f"- score: {pulse.get('score')}",
                f"- label: {pulse.get('label')}",
                f"- mode: {pulse.get('mode')}",
                f"- risk_adjustment: {pulse.get('risk_adjustment')}",
                f"- fast_management_if_in_trade: {pulse.get('fast_management_if_in_trade')}",
                f"- interpretation: {pulse.get('interpretation')}",
                f"- components: {pulse.get('components')}",
            ]
        )
        lines.extend(
            [
                "",
                "### Final Confirmation Engine",
                f"- decision: {final_confirmation.get('decision')}",
                f"- final_confirmation_score: {final_confirmation.get('final_confirmation_score')}",
                f"- entry_timing_quality: {final_confirmation.get('entry_timing_quality')}",
                f"- trap_risk_score: {final_confirmation.get('trap_risk_score')}",
                f"- late_entry_risk: {final_confirmation.get('late_entry_risk')}",
                f"- zone_validity: {final_confirmation.get('zone_validity')}",
                f"- continuation_probability: {final_confirmation.get('continuation_probability')}",
                f"- reversal_probability: {final_confirmation.get('reversal_probability')}",
                f"- liquidity_volume_trap_analysis: {final_confirmation.get('liquidity_volume_trap_analysis')}",
                f"- blockers: {final_confirmation.get('blockers')}",
                f"- warnings: {final_confirmation.get('warnings')}",
                f"- reason: {final_confirmation.get('reason')}",
            ]
        )
        awareness = final_confirmation.get("confirmation_awareness") or {}
        if awareness:
            lines.extend(
                [
                    "",
                    "#### Entry Confirmation Awareness",
                    f"- status: {awareness.get('status')}",
                    f"- execution_allowed_by_confirmation: {awareness.get('execution_allowed_by_confirmation')}",
                    f"- confirmed: {awareness.get('confirmed')}",
                    f"- missing: {awareness.get('missing')}",
                    f"- critical_missing: {awareness.get('critical_missing')}",
                    f"- micro_structure_confirmed: {awareness.get('micro_structure_confirmed')}",
                    f"- liquidity_trigger: {awareness.get('liquidity_trigger')}",
                    f"- displacement_trigger: {awareness.get('displacement_trigger')}",
                    f"- learned_bias_trigger: {awareness.get('learned_bias_trigger')}",
                    f"- summary: {awareness.get('summary')}",
                ]
            )
        execution_readiness_quality = reasoning_snapshot.get("execution_readiness_quality", {}) or {}
        entry_quality = reasoning_snapshot.get("entry_quality", {}) or {}
        armed_retest = reasoning_snapshot.get("armed_retest", {}) or {}
        trade_memory = reasoning_snapshot.get("trade_experience_memory", {}) or {}
        exit_quality = reasoning_snapshot.get("exit_quality", {}) or {}
        lines.extend(
            [
                "",
                "### Execution Readiness Engine",
                f"- execution_readiness_score: {execution_readiness_quality.get('execution_readiness_score')}",
                f"- classification: {execution_readiness_quality.get('classification')}",
                f"- can_execute_quality_gate: {execution_readiness_quality.get('can_execute_quality_gate')}",
                f"- should_arm_retest: {execution_readiness_quality.get('should_arm_retest')}",
                f"- components: {execution_readiness_quality.get('components')}",
                f"- penalties: {execution_readiness_quality.get('penalties')}",
                f"- blockers: {execution_readiness_quality.get('blockers')}",
                f"- reason: {execution_readiness_quality.get('reason')}",
                "",
                "### Entry Quality Engine",
                f"- entry_quality_score: {entry_quality.get('entry_quality_score')}",
                f"- decision: {entry_quality.get('decision')}",
                f"- timing_quality: {entry_quality.get('timing_quality')}",
                f"- retest_quality: {entry_quality.get('retest_quality')}",
                f"- sl_quality: {entry_quality.get('sl_quality')}",
                f"- tp_quality: {entry_quality.get('tp_quality')}",
                f"- zone_quality: {entry_quality.get('zone_quality')}",
                f"- late_entry_risk: {entry_quality.get('late_entry_risk')}",
                f"- trap_risk: {entry_quality.get('trap_risk')}",
                f"- compact_sl_score: {entry_quality.get('compact_sl_score')}",
                f"- reasons: {entry_quality.get('reasons')}",
                "",
                "### ARMED_RETEST Engine",
                f"- status: {armed_retest.get('armed_retest_status') or armed_retest.get('status')}",
                f"- action: {armed_retest.get('action')}",
                f"- side: {armed_retest.get('side')}",
                f"- target_retest_zone: {armed_retest.get('target_retest_zone')}",
                f"- ideal_entry_price: {armed_retest.get('ideal_entry_price')}",
                f"- compact_sl_expected: {armed_retest.get('compact_sl_expected')}",
                f"- tp_estimated: {armed_retest.get('tp_estimated')}",
                f"- expected_rr: {armed_retest.get('expected_rr')}",
                f"- patience_score: {armed_retest.get('patience_score')}",
                f"- reason: {armed_retest.get('reason')}",
                f"- history_path: {armed_retest.get('history_path')}",
                "",
                "### Trade Experience Memory",
                f"- status: {trade_memory.get('status')}",
                f"- memory_bias: {trade_memory.get('memory_bias')}",
                f"- similarity_to_winners: {trade_memory.get('similarity_to_winners')}",
                f"- similarity_to_losers: {trade_memory.get('similarity_to_losers')}",
                f"- best_trades_count: {trade_memory.get('best_trades_count')}",
                f"- worst_trades_count: {trade_memory.get('worst_trades_count')}",
                f"- reason: {trade_memory.get('reason')}",
                "",
                "### Exit Quality Evaluator",
                f"- status: {exit_quality.get('status')}",
                f"- exit_quality_score: {exit_quality.get('exit_quality_score')}",
                f"- classification: {exit_quality.get('classification')}",
                f"- exit_lesson: {exit_quality.get('exit_lesson')}",
                f"- q_learning_feedback_adjustment: {exit_quality.get('q_learning_feedback_adjustment')}",
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
            extracted_brain = projection.get("extracted_knowledge_operational_brain") or {}
            if extracted_brain:
                lines.extend(
                    [
                        "- extracted_knowledge_operational_brain:",
                        f"  - status: {extracted_brain.get('status')}",
                        f"  - role: {extracted_brain.get('role')}",
                        f"  - selected_side: {extracted_brain.get('selected_side')}",
                        f"  - knowledge_score: {extracted_brain.get('knowledge_score')}",
                        f"  - protocol_priority: {extracted_brain.get('protocol_priority')}",
                        f"  - protocols: {extracted_brain.get('auto_selected_protocols')}",
                        f"  - decision_impact: {extracted_brain.get('decision_impact')}",
                    ]
                )
                for item in list(extracted_brain.get("confirmations_from_extracted_knowledge") or [])[:4]:
                    lines.append(f"  - extracted_confirmation: {item}")
                for item in list(extracted_brain.get("missing_knowledge_steps") or [])[:4]:
                    lines.append(f"  - missing_extracted_step: {item}")
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
                    f"- direction: {signal.get('direction')}",
                    f"- setup_type: {signal.get('setup_type')}",
                    f"- signal_type: {signal.get('signal_type')}",
                    f"- active_family: {signal.get('active_family')}",
                    f"- reduced_signal_reason: {signal.get('reduced_signal_reason')}",
                    f"- wick_rejection_quality: {signal.get('wick_rejection_quality')}",
                    f"- displacement_score: {signal.get('displacement_score')}",
                    f"- micro_bos: {signal.get('micro_bos')}",
                    f"- continuation_momentum: {signal.get('continuation_momentum')}",
                    f"- defensive_management_plan: {signal.get('defensive_management_plan')}",
                    f"- risk_mode: {signal.get('risk_mode')}",
                    f"- entry_kind: {signal.get('entry_kind')}",
                    f"- signal_time: {signal.get('signal_time')}",
                    f"- entry_time: {signal.get('entry_time')}",
                    f"- entry_price: {signal.get('entry_price')}",
                    f"- stop_price: {signal.get('stop_price')}",
                    f"- target_price: {signal.get('target_price')}",
                    f"- selected_rr: {signal.get('selected_rr')}",
                    f"- confidence: {signal.get('confidence')}",
                    f"- regime: {signal.get('market_regime')}",
                    f"- hour_ny: {signal.get('hour_ny')}",
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
                "## Autonomous Missed Opportunity Learning",
                f"- status: {reasoning_snapshot.get('missed_opportunity_learning', {}).get('status')}",
                f"- pending_count: {reasoning_snapshot.get('missed_opportunity_learning', {}).get('pending_count')}",
                f"- confirmed_missed_count: {reasoning_snapshot.get('missed_opportunity_learning', {}).get('confirmed_missed_count')}",
                f"- latest_event: {(reasoning_snapshot.get('missed_opportunity_learning', {}).get('latest_event') or {}).get('event')}",
                f"- interpretation: {reasoning_snapshot.get('missed_opportunity_learning', {}).get('interpretation')}",
                f"- learning_path: {reasoning_snapshot.get('missed_opportunity_learning', {}).get('learning_path')}",
                f"- advanced_status: {reasoning_snapshot.get('advanced_missed_opportunity_learning', {}).get('status')}",
                f"- advanced_recorded: {reasoning_snapshot.get('advanced_missed_opportunity_learning', {}).get('recorded')}",
                f"- advanced_history_path: {reasoning_snapshot.get('advanced_missed_opportunity_learning', {}).get('history_path')}",
                f"- advanced_report_path: {reasoning_snapshot.get('advanced_missed_opportunity_learning', {}).get('report_path')}",
            ]
        )
        latest_missed_event = (reasoning_snapshot.get("missed_opportunity_learning", {}) or {}).get("latest_event") or {}
        if latest_missed_event:
            lines.extend(
                [
                    f"- side: {latest_missed_event.get('side')}",
                    f"- setup_type: {latest_missed_event.get('setup_type')}",
                    f"- favorable_r: {latest_missed_event.get('favorable_r')}",
                    f"- reason: {latest_missed_event.get('reason')}",
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
                f"- history_path: {position_management.get('history_path')}",
                f"- feedback: {position_management.get('feedback')}",
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
        lines.extend(
            [
                "",
                "## AI Harmony Audit",
                f"- status: {ai_harmony_audit.get('status')}",
                f"- contradictions: {ai_harmony_audit.get('contradictions')}",
                f"- warnings: {ai_harmony_audit.get('warnings') or ai_harmony_audit.get('layer_tensions') or []}",
                f"- confirmations: {ai_harmony_audit.get('confirmations')}",
                f"- report_path: {ai_harmony_audit.get('report_path')}",
                "",
                "## Performance Lab",
                f"- classification: {performance_lab_summary.get('classification')}",
                f"- trades_observed: {performance_lab_summary.get('trades_observed')}",
                f"- profit_factor_proxy: {performance_lab_summary.get('profit_factor_proxy')}",
                f"- expectancy_r_proxy: {performance_lab_summary.get('expectancy_r_proxy')}",
                f"- trades_reached_0_5r_then_negative_unprotected: {performance_lab_summary.get('trades_reached_0_5r_then_negative_unprotected')}",
                f"- q_learning_real_feedback_events: {performance_lab_summary.get('q_learning_real_feedback_events')}",
                f"- report_path: {performance_lab_summary.get('report_path')}",
                "",
                "## Real Account Safety Gate",
                f"- status: {real_account_safety_gate.get('status')}",
                f"- real_allowed: {real_account_safety_gate.get('real_allowed')}",
                f"- execution_mode_allowed_now: {real_account_safety_gate.get('execution_mode_allowed_now')}",
                f"- blockers: {real_account_safety_gate.get('blockers')}",
                f"- report_path: {real_account_safety_gate.get('report_path')}",
                "",
                "## Final Robustness Reports",
                f"- robustness_report: {final_robustness_reports.get('robustness_report')}",
                f"- demo_realistic_profit_mode_report: {final_robustness_reports.get('demo_realistic_profit_mode_report')}",
                f"- next_3_week_demo_validation_plan: {final_robustness_reports.get('next_3_week_demo_validation_plan')}",
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
                f"- learned_brain_status: {(decision_source_audit.get('learned_knowledge', {}).get('operational_brain') or {}).get('status')}",
                f"- learned_brain_role: {(decision_source_audit.get('learned_knowledge', {}).get('operational_brain') or {}).get('role')}",
                f"- learned_brain_decision_impact: {(decision_source_audit.get('learned_knowledge', {}).get('operational_brain') or {}).get('decision_impact')}",
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
        sized["risk_percent_policy"] = "probability_adjusted_5_percent_base_per_account"
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
            direction = str(signal.get("direction") or "").upper()
            current_risk_per_unit = abs(entry - stop)
            min_volume_lots = float(volume_plan.get("volume_lots") or 0.01)
            risk_per_lot = float(volume_plan.get("risk_per_lot") or 0.0)
            max_risk_per_lot_at_cap = hard_risk_cap_amount / max(min_volume_lots, 0.0001)
            max_risk_per_unit_for_min_lot = (
                current_risk_per_unit * (max_risk_per_lot_at_cap / risk_per_lot)
                if risk_per_lot > 0 and current_risk_per_unit > 0
                else 0.0
            )
            safe_retest_entry = None
            if max_risk_per_unit_for_min_lot > 0 and direction == "SELL":
                safe_retest_entry = stop - max_risk_per_unit_for_min_lot
            elif max_risk_per_unit_for_min_lot > 0 and direction == "BUY":
                safe_retest_entry = stop + max_risk_per_unit_for_min_lot
            recovery_plan = {
                "status": "WAIT_FOR_RETEST_WITH_COMPACT_SL",
                "side": direction,
                "reason": (
                    "La idea puede ser correcta, pero la entrada de mercado llegó tarde: el SL lógico queda demasiado "
                    "amplio para el lote mínimo del broker y superaría el 10% de riesgo de cuenta."
                ),
                "current_entry": round(entry, 3),
                "current_stop": round(stop, 3),
                "current_risk_per_unit": round(current_risk_per_unit, 4),
                "max_risk_per_unit_for_min_lot": round(max_risk_per_unit_for_min_lot, 4),
                "safe_retest_entry_reference": round(safe_retest_entry, 3) if safe_retest_entry is not None else None,
                "required_conditions": [
                    "No perseguir la vela extendida.",
                    "Esperar pullback/retest hacia la zona de origen o una nueva microestructura.",
                    "Recalcular entrada con SL compacto que respete el límite duro de 10%.",
                    "Mantener direction consistency, final confirmation, macro allow y execution_viability SAFE.",
                ],
                "cancel_conditions": [
                    "La zona queda invalidada antes del retest.",
                    "El lado preferido cambia.",
                    "La confirmación final cae por debajo de PREPARE.",
                    "Aparece evento macro bloqueante o spread/latencia insegura.",
                ],
            }
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
                    "execution_recovery_plan": recovery_plan,
                    "position_sizing": {
                        **volume_plan,
                        "status": "blocked",
                        "risk_profile": risk_profile,
                        "estimated_risk_percent_of_account": round(estimated_risk_percent_of_account, 4),
                        "policy": "Hard cap: broker minimum lot must not force more than 10% account risk.",
                        "execution_recovery_plan": recovery_plan,
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
                and str(signal.get("signal_type") or "").upper() in self.REDUCED_SIGNAL_TYPES
                and (
                    "ARMED_RETEST" in str(signal.get("signal_type") or "").upper()
                    or str(signal.get("signal_type") or "").upper() == "M1_MICRO_TRIGGER_REDUCED_SIGNAL"
                )
                and allowed_risk_mode == "blocked"
                and str(active_watch.get("watch_policy_action") or "").upper() in {"", "OBSERVE", "PREPARE_REDUCED", "DROP"}
            ):
                signal_type = str(signal.get("signal_type") or "").upper()
                is_m1_micro = signal_type == "M1_MICRO_TRIGGER_REDUCED_SIGNAL"
                return {
                    "can_execute": True,
                    "allowed_risk_mode": "reduced",
                    "max_risk_multiplier": 0.25 if is_m1_micro else 0.35,
                    "watch_policy_action": active_watch.get("watch_policy_action"),
                    "risk_probability_score": self._active_watch_probability_score(active_watch=active_watch, intelligence=intelligence),
                    "risk_binding_source": "m1_micro_trigger" if is_m1_micro else "armed_retest",
                    "decision": "allowed_reduced_by_m1_micro_trigger" if is_m1_micro else "allowed_reduced_by_armed_retest",
                    "execution_mode": "reduced_execution",
                    "risk_application_reason": (
                        (
                            "M1_MICRO_TRIGGER convirtió tesis + zona en señal reducida de precisión; "
                            if is_m1_micro
                            else "ARMED_RETEST convirtió una idea WATCH/OBSERVE en señal reducida; "
                        )
                        + "la ejecución sigue condicionada por FinalConfirmation, EntryQuality, "
                        "ExecutionReadiness y guards de MT5."
                    ),
                    "execution_status": "ready",
                }
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
                "watch_policy_action": active_watch.get("watch_policy_action"),
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

        signal_side = str(signal.get("direction") or "").upper()
        expected = {"preferred_side": str(signal.get("preferred_side") or "").upper()}
        if self._supervised_v56_without_watch_is_valid(signal=signal, signal_side=signal_side, expected=expected):
            return {
                "can_execute": True,
                "allowed_risk_mode": "reduced",
                "max_risk_multiplier": 0.35,
                "risk_probability_score": max(confidence, self._coerce_percent(signal.get("confidence"))),
                "risk_binding_source": "v56_supervised_without_watch",
                "decision": "allowed_reduced_by_v56_supervised_calibration",
                "execution_mode": "v56_supervised_reduced_execution",
                "risk_application_reason": (
                    "Sin active_watch previo, pero la señal v56/AGG cumple perfil supervisado; "
                    "se permite solo riesgo reducido y queda sujeta a confirmación final/guards."
                ),
                "execution_status": "ready",
            }
        if self._supervised_v56_direction_override_is_valid(
            signal=signal,
            signal_side=signal_side,
            expected=expected,
            conflicts=["persistent_q_learning_policy"],
        ):
            return {
                "can_execute": True,
                "allowed_risk_mode": "reduced",
                "max_risk_multiplier": 0.35,
                "risk_probability_score": max(confidence, self._coerce_percent(signal.get("confidence"))),
                "risk_binding_source": "v56_supervised_without_watch",
                "decision": "allowed_reduced_by_v56_supervised_calibration",
                "execution_mode": "v56_supervised_reduced_execution",
                "risk_application_reason": (
                    "Sin active_watch previo, pero la señal v56/AGG cumple perfil supervisado; "
                    "se permite solo riesgo reducido y queda sujeta a confirmación final/guards."
                ),
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
    def _supervised_v56_without_watch_is_valid(
        *,
        signal: dict[str, Any],
        signal_side: str,
        expected: dict[str, str],
    ) -> bool:
        strategy_variant = str(signal.get("strategy_variant") or "").lower()
        setup_type = str(signal.get("setup_type") or signal.get("signal_type") or "").upper()
        market_regime = str(signal.get("market_regime") or "").upper()
        preferred_side = str(expected.get("preferred_side") or signal.get("preferred_side") or "").upper()
        v56_like = "v56" in strategy_variant or ("AGG" in setup_type and market_regime == "EXPANSION")
        if not v56_like or "AGG" not in setup_type or market_regime != "EXPANSION":
            return False
        if signal_side not in {"BUY", "SELL"}:
            return False
        if preferred_side in {"BUY", "SELL"} and preferred_side != signal_side:
            return False
        confidence = MaximoQuantV4DemoEngine._coerce_percent(signal.get("confidence"))
        quant_score = MaximoQuantV4DemoEngine._coerce_percent(signal.get("quant_score"))
        impulse_score = MaximoQuantV4DemoEngine._coerce_percent(signal.get("impulse_score"))
        try:
            selected_rr = float(signal.get("selected_rr") or 0.0)
        except (TypeError, ValueError):
            selected_rr = 0.0
        score_votes = sum(
            [
                confidence >= 0.72,
                quant_score >= 0.64,
                impulse_score >= 0.64,
                selected_rr >= 1.0,
            ]
        )
        return score_votes >= 3

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
