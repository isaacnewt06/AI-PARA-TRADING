from __future__ import annotations

from pathlib import Path
import csv

from src.trading.q_learning_decision_memory import QLearningDecisionMemory


def _memory(tmp_path: Path) -> QLearningDecisionMemory:
    return QLearningDecisionMemory(
        table_path=tmp_path / "q_table.json",
        replay_path=tmp_path / "q_replay.jsonl",
        report_path=tmp_path / "q_report.md",
    )


def _intelligence() -> dict:
    return {
        "overview": {
            "market_state": {
                "market_regime": "NORMAL",
                "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH",
                "preferred_side": "SELL",
                "higher_timeframe_bias": "SELL",
                "volatility_state": "tradable_normal",
            },
            "knowledge_alignment": {"harmony": {"dominant_family": "OB Rejection", "harmony_score": 0.72}},
        },
        "event_risk": {"action": "allow"},
        "execution_readiness": {"action": "WATCH", "setup_maturity": 72.0},
    }


def test_q_learning_records_experience_and_updates_table(tmp_path: Path) -> None:
    memory = _memory(tmp_path)

    update = memory.record_cycle(
        symbol="XAUUSDm",
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "progress": "triggered", "side": "SELL"},
        active_watch_metrics={"watch_health": "improving", "watch_probability_to_execute": 0.72},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
        execution_risk_decision={"allowed_risk_mode": "reduced"},
        signal={"direction": "sell", "selected_rr": 1.6},
        execution_status="dry_run_signal_detected",
        controlled_demo_survival_protocol={"allowed": True},
    )
    decision = memory.evaluate_decision(
        symbol="XAUUSDm",
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "progress": "triggered", "side": "SELL"},
        active_watch_metrics={"watch_health": "improving", "watch_probability_to_execute": 0.72},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
    )

    assert update["latest_experience"]["reward"] > 0
    assert decision["experience_count"] == 1
    assert decision["q_values"]["SELL"] > 0
    assert (tmp_path / "q_replay.jsonl").exists()
    assert (tmp_path / "q_report.md").exists()


def test_q_learning_records_position_management_feedback(tmp_path: Path) -> None:
    memory = _memory(tmp_path)

    update = memory.record_cycle(
        symbol="XAUUSDm",
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "progress": "triggered", "side": "SELL"},
        active_watch_metrics={"watch_health": "improving", "watch_probability_to_execute": 0.72},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
        execution_risk_decision={"allowed_risk_mode": "reduced"},
        signal={"direction": "sell", "selected_rr": 1.6},
        execution_status="dry_run_signal_detected",
        controlled_demo_survival_protocol={"allowed": True},
        position_management={
            "feedback": {
                "be_applied": True,
                "partial_taken": False,
                "trailing_applied": False,
                "fast_exit_taken": True,
                "gave_back_profit": False,
                "momentum_decay_detected": True,
                "invalid_partial_fallback": True,
                "actions_taken": ["partial_skipped_min_lot_fallback", "fast_exit"],
            }
        },
    )

    experience = update["latest_experience"]
    assert experience["position_management_feedback"]["be_applied"] is True
    assert "fast_exit" in experience["position_management_actions"]
    assert experience["reward"] > 0.2
    assert "salio rapido" in experience["reward_reason"]


def test_q_learning_penalizes_giveback_without_protection(tmp_path: Path) -> None:
    memory = _memory(tmp_path)

    update = memory.record_cycle(
        symbol="XAUUSDm",
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "progress": "triggered", "side": "SELL"},
        active_watch_metrics={"watch_health": "deteriorating", "watch_probability_to_execute": 0.42},
        watch_execution_policy={"watch_policy_action": "OBSERVE"},
        execution_risk_decision={"allowed_risk_mode": "reduced"},
        signal={"direction": "sell", "selected_rr": 1.2},
        execution_status="dry_run_signal_detected",
        controlled_demo_survival_protocol={"allowed": True},
        position_management={
            "feedback": {
                "be_applied": False,
                "fast_exit_taken": False,
                "gave_back_profit": True,
                "momentum_decay_detected": True,
                "actions_taken": ["monitor"],
            }
        },
    )

    assert update["latest_experience"]["reward"] < 0
    assert "devolvio ganancia" in update["latest_experience"]["reward_reason"]


def test_q_learning_records_final_confirmation_feedback(tmp_path: Path) -> None:
    memory = _memory(tmp_path)

    update = memory.record_cycle(
        symbol="XAUUSDm",
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "progress": "triggered", "side": "SELL"},
        active_watch_metrics={"watch_health": "improving", "watch_probability_to_execute": 0.72},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
        execution_risk_decision={"allowed_risk_mode": "reduced"},
        signal={"direction": "sell", "selected_rr": 1.6},
        execution_status="dry_run_signal_detected",
        controlled_demo_survival_protocol={"allowed": True},
        final_confirmation={
            "decision": "EXECUTE",
            "final_confirmation_score": 78.0,
            "entry_timing_quality": "strong",
            "trap_risk_score": 0.2,
            "late_entry_risk": 0.1,
            "zone_validity": "strong",
        },
    )

    experience = update["latest_experience"]
    assert experience["final_confirmation_score"] == 78.0
    assert experience["final_confirmation_decision"] == "EXECUTE"
    assert "confirmacion final valida" in experience["reward_reason"]


def test_q_learning_replay_uses_priority_experiences(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    for _ in range(3):
        memory.record_cycle(
            symbol="XAUUSDm",
            intelligence=_intelligence(),
            active_watch={"status": "TRIGGERED", "progress": "triggered", "side": "SELL"},
            active_watch_metrics={"watch_health": "improving", "watch_probability_to_execute": 0.8},
            watch_execution_policy={"watch_policy_action": "PREPARE_NORMAL"},
            execution_risk_decision={"allowed_risk_mode": "normal"},
            signal={"direction": "sell", "selected_rr": 2.0},
            execution_status="dry_run_signal_detected",
            controlled_demo_survival_protocol={"allowed": True},
        )

    decision = memory.evaluate_decision(
        symbol="XAUUSDm",
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "progress": "triggered", "side": "SELL"},
        active_watch_metrics={"watch_health": "improving", "watch_probability_to_execute": 0.8},
        watch_execution_policy={"watch_policy_action": "PREPARE_NORMAL"},
    )

    assert decision["replay_count"] > 0
    assert decision["q_values"]["SELL"] > 0.1


def test_q_learning_overlay_blocks_when_hold_is_much_better(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    decision = {
        "q_policy_action": "HOLD",
        "risk_bias": "protect_capital",
        "state_key": "state",
        "q_values": {"HOLD": 0.5, "BUY": 0.0, "SELL": 0.1, "CLOSE": 0.0},
    }

    result = memory.apply_risk_overlay(
        q_learning_decision=decision,
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "normal", "max_risk_multiplier": 1.0},
        signal={"direction": "sell"},
    )

    assert result["can_execute"] is False
    assert result["allowed_risk_mode"] == "blocked"
    assert result["execution_status"] == "blocked_by_q_learning_memory"


def test_q_learning_overlay_keeps_session_pattern_signal_reduced(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    decision = {
        "q_policy_action": "HOLD",
        "risk_bias": "protect_capital",
        "state_key": "state",
        "q_values": {"HOLD": 0.5, "BUY": 0.0, "SELL": 0.1, "CLOSE": 0.0},
    }

    result = memory.apply_risk_overlay(
        q_learning_decision=decision,
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.25},
        signal={
            "direction": "sell",
            "signal_type": "SESSION_Q_LEARNING_REDUCED_SIGNAL",
            "session_opportunity_score": 0.72,
            "q_learning_memory_alignment": True,
        },
    )

    assert result["can_execute"] is True
    assert result["allowed_risk_mode"] == "reduced"
    assert result["max_risk_multiplier"] == 0.25
    assert result["execution_mode"] == "session_q_learning_reduced_execution"


def test_q_learning_overlay_keeps_clean_armed_retest_signal_reduced(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    decision = {
        "q_policy_action": "HOLD",
        "risk_bias": "protect_capital",
        "state_key": "state",
        "q_values": {"HOLD": 0.5, "BUY": 0.1, "SELL": 0.0, "CLOSE": 0.0},
    }

    result = memory.apply_risk_overlay(
        q_learning_decision=decision,
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.35},
        signal={
            "direction": "buy",
            "signal_type": "ARMED_RETEST_REDUCED_SIGNAL",
            "confidence": 78,
            "selected_rr": 1.25,
            "entry_price": 4500.0,
            "stop_price": 4497.0,
            "target_price": 4504.0,
            "micro_bos": True,
            "manual_bias_confirmation": True,
            "continuation_momentum": True,
        },
    )

    assert result["can_execute"] is True
    assert result["allowed_risk_mode"] == "reduced"
    assert result["max_risk_multiplier"] == 0.25
    assert result["execution_mode"] == "armed_retest_q_hold_reduced_execution"


def test_q_learning_seeds_from_historical_backtest_trades(tmp_path: Path) -> None:
    backtest_dir = tmp_path / "backtests"
    backtest_dir.mkdir()
    path = backtest_dir / "2025_v56_aggressive_filtered_b_all_trades.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "entry_time",
                "exit_time",
                "setup_type",
                "market_regime",
                "direction",
                "gross_pnl_usd",
                "net_pnl_usd",
                "drawdown_percent",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "entry_time": "2025-01-01T10:00:00+00:00",
                "exit_time": "2025-01-01T10:15:00+00:00",
                "setup_type": "AGG",
                "market_regime": "EXPANSION",
                "direction": "sell",
                "gross_pnl_usd": "8",
                "net_pnl_usd": "7",
                "drawdown_percent": "0.5",
            }
        )

    memory = _memory(tmp_path)
    seed = memory.ensure_historical_seed(backtest_dir=backtest_dir, symbol="XAUUSDm")
    decision = memory.evaluate_decision(
        symbol="XAUUSDm",
        intelligence={
            "overview": {
                "market_state": {
                    "market_regime": "EXPANSION",
                    "operational_family": "AGG",
                    "preferred_side": "SELL",
                },
                "knowledge_alignment": {"harmony": {"dominant_family": "OB Rejection", "harmony_score": 0.7}},
            },
            "event_risk": {"action": "allow"},
            "execution_readiness": {"action": "WATCH", "setup_maturity": 72.0},
        },
        active_watch={"side": "SELL", "operational_family": "AGG"},
        active_watch_metrics={"watch_health": "stable", "watch_probability_to_execute": 0.6},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
    )

    assert seed["rows_used"] == 1
    assert seed["files_used"] == 1
    assert decision["historical_prior_values"]["SELL"] > 0
    assert decision["q_policy_action"] == "SELL"


def test_q_learning_historical_seed_tracks_session_priors(tmp_path: Path) -> None:
    backtest_dir = tmp_path / "backtests"
    backtest_dir.mkdir()
    path = backtest_dir / "2025_v56_aggressive_filtered_b_all_trades.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "entry_time",
                "exit_time",
                "setup_type",
                "market_regime",
                "direction",
                "gross_pnl_usd",
                "net_pnl_usd",
                "drawdown_percent",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "entry_time": "2025-06-01T13:00:00+00:00",
                "exit_time": "2025-06-01T13:20:00+00:00",
                "setup_type": "AGG",
                "market_regime": "NORMAL",
                "direction": "buy",
                "gross_pnl_usd": "9",
                "net_pnl_usd": "8",
                "drawdown_percent": "0.3",
            }
        )

    memory = _memory(tmp_path)
    memory.ensure_historical_seed(backtest_dir=backtest_dir, symbol="XAUUSDm")
    decision = memory.evaluate_decision(
        symbol="XAUUSDm",
        intelligence={
            "overview": {
                "market_state": {
                    "market_regime": "NORMAL",
                    "operational_family": "AGG",
                    "preferred_side": "BUY",
                    "hour_ny": 9,
                },
                "knowledge_alignment": {"harmony": {"dominant_family": "OB Rejection", "harmony_score": 0.7}},
            },
            "event_risk": {"action": "allow"},
            "execution_readiness": {"action": "WATCH", "setup_maturity": 72.0},
        },
        active_watch={"side": "BUY", "operational_family": "AGG"},
        active_watch_metrics={"watch_health": "stable", "watch_probability_to_execute": 0.6},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
    )

    assert "new_york" in decision["state_key"]
    assert decision["historical_prior_values"]["BUY"] > 0


def test_q_learning_reports_converged_strategy_harmony(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    intelligence = _intelligence()
    intelligence["watch_trigger"] = {
        "pattern_projection": {
            "side_probability_comparison": {"selected_side": "SELL"},
            "cool_learning_memory": {"policy_action": "SELL"},
            "professional_decision_matrix": {
                "selected_side": "SELL",
                "layer_synchronization": {"agreement_score": 1.0},
                "course_learning_sync": {
                    "status": "aligned",
                    "course_score": 0.84,
                    "course_recommended_action": "SELL",
                },
            },
        }
    }
    memory._save_table(  # type: ignore[attr-defined]
        {
            "_meta": {"experience_count": 5, "replay_count": 0},
            memory._state_key(  # type: ignore[attr-defined]
                symbol="XAUUSDm",
                intelligence=intelligence,
                active_watch={"side": "SELL", "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
                watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
            ): {"HOLD": 0.0, "BUY": -0.2, "SELL": 0.45, "CLOSE": 0.0},
        }
    )

    decision = memory.evaluate_decision(
        symbol="XAUUSDm",
        intelligence=intelligence,
        active_watch={"side": "SELL", "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
        active_watch_metrics={"watch_health": "stable", "watch_probability_to_execute": 0.72},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
    )

    harmony = decision["strategy_harmony_matrix"]
    assert harmony["status"] in {"converged", "aligned"}
    assert harmony["selected_side"] == "SELL"
    assert harmony["q_aligned_with_consensus"] is True
    assert decision["risk_bias"] == "support_entry"


def test_q_learning_strategy_harmony_conflict_blocks_signal(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    decision = {
        "q_policy_action": "BUY",
        "risk_bias": "reduce_or_pause",
        "state_key": "state",
        "q_values": {"HOLD": 0.0, "BUY": 0.35, "SELL": -0.1, "CLOSE": 0.0},
        "strategy_harmony_matrix": {
            "status": "conflicted",
            "harmony_score": 0.31,
            "selected_side": "SELL",
            "conflicts": ["persistent_q_learning=BUY"],
        },
    }

    result = memory.apply_risk_overlay(
        q_learning_decision=decision,
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "normal", "max_risk_multiplier": 1.0},
        signal={"direction": "sell"},
    )

    assert result["can_execute"] is False
    assert result["execution_status"] == "blocked_by_q_learning_strategy_harmony"
    assert result["allowed_risk_mode"] == "blocked"


def test_q_learning_weak_stale_memory_conflict_allows_reduced_risk(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    decision = {
        "q_policy_action": "SELL",
        "risk_bias": "reduce_or_pause",
        "state_key": "state",
        "value_gap": 0.05,
        "q_values": {"HOLD": 0.0, "BUY": -0.04, "SELL": 0.05, "CLOSE": 0.0},
        "strategy_harmony_matrix": {
            "status": "conflicted",
            "harmony_score": 0.62,
            "selected_side": "BUY",
            "agreement_ratio": 0.75,
            "layer_agreement_score": 1.0,
            "q_value_gap": 0.05,
            "course_status": "aligned",
            "course_score": 1.0,
            "conflicts": ["persistent_q_learning=SELL", "historical_backtest_prior=SELL"],
        },
    }

    result = memory.apply_risk_overlay(
        q_learning_decision=decision,
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "normal", "max_risk_multiplier": 1.0},
        signal={"direction": "buy"},
    )

    assert result["can_execute"] is True
    assert result["allowed_risk_mode"] == "reduced"
    assert result["max_risk_multiplier"] == 0.25
    assert result["execution_mode"] == "q_learning_weak_conflict_reduced_execution"


def test_q_learning_mixed_strategy_harmony_forces_reduced_risk(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    decision = {
        "q_policy_action": "SELL",
        "risk_bias": "support_reduced_only",
        "state_key": "state",
        "q_values": {"HOLD": 0.0, "BUY": 0.05, "SELL": 0.21, "CLOSE": 0.0},
        "strategy_harmony_matrix": {
            "status": "mixed",
            "harmony_score": 0.54,
            "selected_side": "SELL",
            "conflicts": ["course_memory=WAIT"],
        },
    }

    result = memory.apply_risk_overlay(
        q_learning_decision=decision,
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "normal", "max_risk_multiplier": 1.0},
        signal={"direction": "sell"},
    )

    assert result["can_execute"] is True
    assert result["allowed_risk_mode"] == "reduced"
    assert result["max_risk_multiplier"] == 0.35
