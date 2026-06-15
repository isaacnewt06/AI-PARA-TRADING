from __future__ import annotations

from src.trading.final_confirmation_engine import FinalConfirmationEngine


def _intelligence(action: str = "EXECUTE") -> dict:
    return {
        "overview": {
            "market_state": {
                "preferred_side": "SELL",
                "higher_timeframe_bias": "SELL",
                "market_regime": "TREND",
                "impulse_score": 0.8,
                "last_price": 4499.8,
            },
            "knowledge_alignment": {"harmony": {"harmony_score": 0.78}},
        },
        "execution_readiness": {"action": action, "setup_maturity": 82.0, "confidence": 0.82},
        "event_risk": {"action": "allow"},
        "watch_trigger": {
            "side": "SELL",
            "setup_maturity": 82.0,
            "confidence": 0.82,
            "missing_for_execute": [],
        },
    }


def _safe_execution_environment() -> dict:
    return {
        "execution_viability": "SAFE",
        "live_spread": 0.12,
        "spread_p80": 0.2,
        "session": "ny_rd",
        "server_time": "2026-06-10T09:15:00-04:00",
    }


def _balanced_snapshot() -> dict:
    history = [
        {"open": 4498.0, "high": 4510.0, "low": 4490.0, "close": 4500.0, "volume": 100.0}
        for _ in range(20)
    ]
    return {"candles": {"M5": history}}


def test_final_confirmation_allows_strong_execute() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "sell",
        "entry_price": 4500.0,
        "stop_price": 4505.0,
        "target_price": 4490.0,
        "selected_rr": 2.0,
        "continuation_momentum": 0.9,
        "displacement_score": 80,
        "micro_bos": True,
    }

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "side": "SELL"},
        market_pulse={"score": 78, "label": "strong_opportunity"},
        execution_environment={"execution_viability": "SAFE"},
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.5, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
    )

    assert result["decision"] == "EXECUTE"
    assert result["final_confirmation_score"] >= 72


def test_final_confirmation_blocks_invalid_zone() -> None:
    engine = FinalConfirmationEngine()

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={"direction": "buy", "entry_price": 4500.0, "stop_price": 4495.0, "target_price": 4510.0, "selected_rr": 2.0},
        intelligence=_intelligence(),
        active_watch={"status": "EXPIRED", "side": "BUY"},
        market_pulse={"score": 80},
        execution_environment={"execution_viability": "SAFE"},
        q_learning_decision={"q_policy_action": "BUY", "q_values": {"BUY": 0.4, "HOLD": 0.0}},
        direction_consistency_guard={"allowed": True},
    )

    assert result["decision"] == "BLOCK"
    assert "zone_invalid_or_expired" in result["blockers"]


def test_final_confirmation_allows_complete_armed_retest_reduced_recovery() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "buy",
        "signal_type": "ARMED_RETEST_REDUCED_SIGNAL",
        "entry_price": 4500.0,
        "stop_price": 4497.0,
        "target_price": 4504.0,
        "selected_rr": 1.33,
        "continuation_momentum": True,
        "displacement_score": 60,
        "micro_bos": True,
        "manual_bias_confirmation": True,
    }
    intelligence = _intelligence()
    intelligence["overview"]["market_state"].update(
        {
            "preferred_side": "BUY",
            "market_clarity": {"selected_side": "BUY"},
            "last_price": 4500.0,
            "recent_low": 4490.0,
            "recent_high": 4520.0,
        }
    )
    intelligence["watch_trigger"]["side"] = "BUY"

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=intelligence,
        active_watch={"status": "TRIGGERED", "side": "BUY"},
        market_pulse={"score": 90, "components": {"liquidity_sweep": 7}},
        execution_environment=_safe_execution_environment(),
        q_learning_decision={"q_policy_action": "HOLD", "q_values": {"BUY": 0.2, "HOLD": 0.22}},
        direction_consistency_guard={"allowed": True},
        snapshot=_balanced_snapshot(),
    )

    assert result["decision"] == "EXECUTE"
    assert result["armed_retest_execute_recovery"]["eligible"] is True


def test_final_confirmation_allows_m1_micro_trigger_reduced_recovery() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "buy",
        "signal_type": "M1_MICRO_TRIGGER_REDUCED_SIGNAL",
        "entry_price": 4500.0,
        "stop_price": 4497.5,
        "target_price": 4503.625,
        "selected_rr": 1.45,
        "continuation_momentum": 0.72,
        "displacement_score": 72,
        "micro_bos": True,
        "micro_choch": True,
        "liquidity_sweep": True,
        "manual_bias_confirmation": True,
    }
    intelligence = _intelligence()
    intelligence["overview"]["market_state"].update(
        {
            "preferred_side": "BUY",
            "higher_timeframe_bias": "BUY",
            "market_clarity": {
                "selected_side": "BUY",
                "expected_entry_zone": {"from": 4498.0, "to": 4502.0, "in_zone_now": True},
            },
            "expected_entry_zone": {"from": 4498.0, "to": 4502.0, "in_zone_now": True},
            "last_price": 4500.0,
            "recent_low": 4490.0,
            "recent_high": 4520.0,
        }
    )
    intelligence["watch_trigger"]["side"] = "BUY"

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=intelligence,
        active_watch={"status": "TRIGGERED", "side": "BUY"},
        market_pulse={"score": 88, "components": {"liquidity_sweep": 8}},
        execution_environment=_safe_execution_environment(),
        q_learning_decision={"q_policy_action": "BUY", "q_values": {"BUY": 0.35, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
        snapshot=_balanced_snapshot(),
    )

    assert result["decision"] == "EXECUTE"
    assert result["m1_micro_trigger_execute_recovery"]["eligible"] is True


def test_m1_micro_trigger_treats_empty_macro_block_as_caution() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "buy",
        "signal_type": "M1_MICRO_TRIGGER_REDUCED_SIGNAL",
        "entry_price": 4500.0,
        "stop_price": 4497.5,
        "target_price": 4503.625,
        "selected_rr": 1.45,
        "continuation_momentum": 0.72,
        "displacement_score": 72,
        "micro_bos": True,
        "liquidity_sweep": True,
        "manual_bias_confirmation": True,
    }
    intelligence = _intelligence()
    intelligence["event_risk"] = {"action": "block", "active_events": [], "upcoming_events": []}
    intelligence["overview"]["market_state"].update(
        {
            "preferred_side": "BUY",
            "market_clarity": {"selected_side": "BUY", "expected_entry_zone": {"from": 4498.0, "to": 4502.0}},
            "expected_entry_zone": {"from": 4498.0, "to": 4502.0},
            "last_price": 4500.0,
            "recent_low": 4490.0,
            "recent_high": 4520.0,
        }
    )
    intelligence["watch_trigger"]["side"] = "BUY"

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=intelligence,
        active_watch={"status": "TRIGGERED", "side": "BUY"},
        market_pulse={"score": 88, "components": {"liquidity_sweep": 8}},
        execution_environment=_safe_execution_environment(),
        q_learning_decision={"q_policy_action": "BUY", "q_values": {"BUY": 0.35, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
        snapshot=_balanced_snapshot(),
    )

    assert "macro_event_not_allow" not in result["blockers"]
    assert "macro_event_caution_reduced_signal" in result["warnings"]


def test_final_confirmation_guard_blocks_non_execute_signal() -> None:
    engine = FinalConfirmationEngine()
    decision = engine.apply_execution_guard(
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.5},
        final_confirmation={"decision": "PREPARE", "final_confirmation_score": 63, "reason": "waiting"},
        signal={"direction": "sell"},
    )

    assert decision["can_execute"] is False
    assert decision["execution_status"] == "blocked_by_final_confirmation"


def test_final_confirmation_keeps_market_clarity_side_when_preferred_side_is_neutral() -> None:
    engine = FinalConfirmationEngine()
    intelligence = _intelligence(action="WATCH")
    intelligence["overview"]["market_state"].update(
        {
            "preferred_side": "NEUTRAL",
            "market_clarity": {
                "selected_side": "SELL",
                "entry_trigger_plan": {
                    "side": "SELL",
                    "fire_when": "Disparar SELL solo si precio toca/rechaza zona y final_confirmation + entry_quality pasan.",
                },
            },
        }
    )
    intelligence["watch_trigger"] = {"missing_for_execute": []}

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence=intelligence,
        active_watch=None,
        market_pulse={"score": 83.0},
        execution_environment={"execution_viability": "SAFE"},
        q_learning_decision={"q_policy_action": "HOLD", "q_values": {"SELL": 0.2, "HOLD": 0.21}},
        direction_consistency_guard={"allowed": True},
    )

    awareness = result["confirmation_awareness"]
    assert result["side"] == "SELL"
    assert awareness["side"] == "SELL"
    assert awareness["market_clarity_side"] == "SELL"
    assert "side_defined" in awareness["confirmed"]
    assert awareness["entry_trigger_plan"]["side"] == "SELL"
    assert result["decision"] in {"WAIT", "PREPARE"}


def test_v56_supervised_gap_waits_for_armed_retest_without_execute(monkeypatch) -> None:
    import src.trading.final_confirmation_engine as module

    monkeypatch.setattr(
        module,
        "v56_thresholds",
        lambda: {
            "zone_validity_floor": 64.0,
            "max_winner_trap_risk": 0.65,
            "max_winner_late_entry_risk": 0.38,
        },
    )
    engine = FinalConfirmationEngine()
    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={
            "direction": "SELL",
            "entry_price": 4500.0,
            "stop_price": 4504.0,
            "target_price": 4492.0,
            "selected_rr": 2.0,
            "setup_type": "AGG",
            "market_regime": "EXPANSION",
            "strategy_variant": "v56_aggressive_filtered_b",
            "displacement_score": 20.0,
        },
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "side": "SELL"},
        market_pulse={"score": 92.0},
        execution_environment={"execution_viability": "SAFE"},
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.7, "HOLD": 0.2}},
        direction_consistency_guard={"allowed": True},
    )

    awareness = result["confirmation_awareness"]
    assert result["decision"] == "PREPARE"
    assert awareness["status"] == "WAIT_RETEST_CONFIRMATION"
    assert awareness["execution_allowed_by_confirmation"] is False
    assert awareness["recoverable_for_armed_retest"] is True
    assert "clean_structure_trigger_missing" not in result["blockers"]

    guarded = engine.apply_execution_guard(
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.35},
        final_confirmation=result,
        signal={"direction": "SELL"},
    )
    assert guarded["can_execute"] is False
    assert guarded["execution_status"] == "waiting_for_entry_confirmation_retest"


def test_v56_supervised_valid_setup_can_execute_reduced_below_global_threshold(monkeypatch) -> None:
    import src.trading.final_confirmation_engine as module

    monkeypatch.setattr(
        module,
        "v56_thresholds",
        lambda: {
            "zone_validity_floor": 64.0,
            "execution_readiness_recovery_floor": 70.0,
            "max_winner_trap_risk": 0.50,
            "max_winner_late_entry_risk": 0.38,
        },
    )
    engine = FinalConfirmationEngine()
    intelligence = _intelligence()
    intelligence["execution_readiness"] = {"action": "EXECUTE", "setup_maturity": 45.0, "confidence": 0.62}
    intelligence["watch_trigger"] = {"side": "SELL", "setup_maturity": 45.0, "confidence": 0.62}
    intelligence["overview"]["knowledge_alignment"]["harmony"]["harmony_score"] = 0.50

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={
            "direction": "SELL",
            "entry_price": 4500.0,
            "stop_price": 4504.0,
            "target_price": 4492.0,
            "selected_rr": 1.2,
            "setup_type": "AGG",
            "market_regime": "EXPANSION",
            "strategy_variant": "v56_aggressive_filtered_b",
            "continuation_momentum": 0.55,
            "displacement_score": 56.0,
            "micro_bos": True,
        },
        intelligence=intelligence,
        active_watch={"status": "TRIGGERED", "side": "SELL"},
        market_pulse={"score": 76.0},
        execution_environment=_safe_execution_environment(),
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.5, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
        snapshot=_balanced_snapshot(),
    )

    assert result["final_confirmation_score"] < result["required_execute_score"]
    assert result["decision"] == "EXECUTE"
    assert result["supervised_v56_execute_recovery"]["eligible"] is True
    assert result["supervised_v56_execute_recovery"]["execution_mode"] == "supervised_v56_reduced_execute_recovery"


def test_v56_supervised_recovery_does_not_bypass_q_learning_textbook_mode(monkeypatch) -> None:
    import src.trading.final_confirmation_engine as module

    monkeypatch.setattr(
        module,
        "v56_thresholds",
        lambda: {
            "zone_validity_floor": 64.0,
            "execution_readiness_recovery_floor": 70.0,
            "max_winner_trap_risk": 0.50,
            "max_winner_late_entry_risk": 0.38,
        },
    )
    engine = FinalConfirmationEngine()
    intelligence = _intelligence()
    intelligence["execution_readiness"] = {"action": "EXECUTE", "setup_maturity": 45.0, "confidence": 0.62}
    intelligence["watch_trigger"] = {"side": "SELL", "setup_maturity": 45.0, "confidence": 0.62}
    intelligence["overview"]["knowledge_alignment"]["harmony"]["harmony_score"] = 0.50

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={
            "direction": "SELL",
            "entry_price": 4500.0,
            "stop_price": 4504.0,
            "target_price": 4492.0,
            "selected_rr": 1.2,
            "setup_type": "AGG",
            "market_regime": "EXPANSION",
            "strategy_variant": "v56_aggressive_filtered_b",
            "continuation_momentum": 0.55,
            "displacement_score": 56.0,
            "micro_bos": True,
        },
        intelligence=intelligence,
        active_watch={"status": "TRIGGERED", "side": "SELL"},
        market_pulse={"score": 76.0},
        execution_environment=_safe_execution_environment(),
        q_learning_decision={
            "q_policy_action": "SELL",
            "q_values": {"SELL": 0.5, "HOLD": 0.1},
            "recent_similar_losses": 3,
        },
        direction_consistency_guard={"allowed": True},
        snapshot=_balanced_snapshot(),
    )

    assert result["required_execute_score"] == 90.0
    assert result["decision"] != "EXECUTE"
    assert result["supervised_v56_execute_recovery"]["eligible"] is False
    assert result["supervised_v56_execute_recovery"]["reason"] == "dynamic_threshold_requires_textbook_confirmation"


def test_final_confirmation_blocks_high_volume_liquidity_trap() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "sell",
        "entry_price": 100.0,
        "stop_price": 105.0,
        "target_price": 90.0,
        "selected_rr": 2.0,
        "continuation_momentum": 0.8,
        "displacement_score": 70,
        "micro_bos": True,
    }
    history = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0}
        for _ in range(20)
    ]
    trap_candle = {"open": 99.6, "high": 100.0, "low": 98.8, "close": 99.8, "volume": 240.0}

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "side": "SELL"},
        market_pulse={"score": 82, "components": {"liquidity_sweep": 6}},
        execution_environment={"execution_viability": "SAFE"},
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.5, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
        snapshot={"candles": {"M5": [*history, trap_candle]}},
    )

    assert result["decision"] == "BLOCK"
    assert "liquidity_trap_risk_too_high" in result["blockers"]
    analysis = result["liquidity_volume_trap_analysis"]
    assert analysis["opposite_liquidity_sweep"] is True
    assert analysis["manipulation_risk_score"] >= 0.78


def test_final_confirmation_recognizes_favorable_liquidity_sweep_and_volume() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "buy",
        "entry_price": 100.0,
        "stop_price": 95.0,
        "target_price": 110.0,
        "selected_rr": 2.0,
        "continuation_momentum": 0.9,
        "displacement_score": 82,
        "micro_bos": True,
        "manual_bias_confirmation": True,
    }
    history = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.2, "volume": 100.0}
        for _ in range(20)
    ]
    sweep_candle = {"open": 99.4, "high": 102.0, "low": 98.6, "close": 101.7, "volume": 165.0}

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence={
            **_intelligence(),
            "overview": {
                **_intelligence()["overview"],
                "market_state": {
                    **_intelligence()["overview"]["market_state"],
                    "preferred_side": "BUY",
                    "higher_timeframe_bias": "BUY",
                    "last_price": 100.2,
                },
            },
            "watch_trigger": {"side": "BUY", "missing_for_execute": []},
        },
        active_watch={"status": "TRIGGERED", "side": "BUY"},
        market_pulse={"score": 84, "components": {"liquidity_sweep": 8}},
        execution_environment={"execution_viability": "SAFE"},
        q_learning_decision={"q_policy_action": "BUY", "q_values": {"BUY": 0.5, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
        snapshot={"candles": {"M5": [*history, sweep_candle]}},
    )

    analysis = result["liquidity_volume_trap_analysis"]
    assert analysis["liquidity_sweep_detected"] is True
    assert analysis["volume_confirmation_score"] >= 0.62
    assert analysis["movement_quality_score"] >= 0.6
    assert "liquidity_trap_risk_too_high" not in result["blockers"]


def test_final_confirmation_blocks_spread_above_p80() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "sell",
        "entry_price": 4500.0,
        "stop_price": 4505.0,
        "target_price": 4490.0,
        "selected_rr": 2.0,
        "continuation_momentum": 0.9,
        "displacement_score": 80,
        "micro_bos": True,
    }

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "side": "SELL"},
        market_pulse={"score": 82},
        execution_environment={**_safe_execution_environment(), "live_spread": 0.31},
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.5, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
        snapshot=_balanced_snapshot(),
    )

    assert result["decision"] == "BLOCK"
    assert "spread_above_p80" in result["blockers"]
    assert result["execution_cost_analysis"]["status"] == "blocked_spread_above_p80"


def test_final_confirmation_blocks_outside_optimal_session_with_server_time() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "sell",
        "entry_price": 4500.0,
        "stop_price": 4505.0,
        "target_price": 4490.0,
        "selected_rr": 2.0,
        "continuation_momentum": 0.9,
        "displacement_score": 80,
        "micro_bos": True,
    }

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "side": "SELL"},
        market_pulse={"score": 82},
        execution_environment={**_safe_execution_environment(), "session": "asian_dead_zone"},
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.5, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
        snapshot=_balanced_snapshot(),
    )

    assert result["decision"] == "BLOCK"
    assert "outside_optimal_session" in result["blockers"]
    assert result["session_execution_analysis"]["server_time"] == "2026-06-10T09:15:00-04:00"


def test_final_confirmation_accepts_rd_pm_volatility_windows() -> None:
    engine = FinalConfirmationEngine()

    afternoon = engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence=_intelligence(action="WATCH"),
        active_watch=None,
        market_pulse={"score": 60},
        execution_environment={**_safe_execution_environment(), "hour_rd": 14.5},
        q_learning_decision={"q_policy_action": "HOLD", "q_values": {"HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
    )
    evening = engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence=_intelligence(action="WATCH"),
        active_watch=None,
        market_pulse={"score": 60},
        execution_environment={**_safe_execution_environment(), "hour_rd": 20.25},
        q_learning_decision={"q_policy_action": "HOLD", "q_values": {"HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
    )

    assert afternoon["session_execution_analysis"]["session"] == "pm_volatility_rd"
    assert afternoon["session_execution_analysis"]["status"] == "optimal_session"
    assert evening["session_execution_analysis"]["session"] == "evening_volatility_rd"
    assert evening["session_execution_analysis"]["status"] == "optimal_session"


def test_final_confirmation_blocks_frozen_operating_range_without_crashing() -> None:
    engine = FinalConfirmationEngine()
    frozen_history = [
        {"open": 4500.0, "high": 4500.0, "low": 4500.0, "close": 4500.0, "volume": 100.0}
        for _ in range(20)
    ]
    signal = {
        "direction": "buy",
        "entry_price": 4500.0,
        "stop_price": 4495.0,
        "target_price": 4510.0,
        "selected_rr": 2.0,
        "continuation_momentum": 0.9,
        "displacement_score": 80,
        "micro_bos": True,
    }
    intelligence = _intelligence()
    intelligence["overview"]["market_state"].update(
        {"preferred_side": "BUY", "higher_timeframe_bias": "BUY", "last_price": 4500.0}
    )
    intelligence["watch_trigger"] = {"side": "BUY", "missing_for_execute": []}

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=intelligence,
        active_watch={"status": "TRIGGERED", "side": "BUY"},
        market_pulse={"score": 82},
        execution_environment=_safe_execution_environment(),
        q_learning_decision={"q_policy_action": "BUY", "q_values": {"BUY": 0.5, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
        snapshot={"candles": {"M5": frozen_history}},
    )

    assert result["decision"] == "BLOCK"
    assert "operating_range_unavailable" in result["blockers"]
    assert result["premium_discount_analysis"]["status"] == "operating_range_unavailable"


def test_final_confirmation_requires_90_after_recent_similar_losses() -> None:
    engine = FinalConfirmationEngine()
    signal = {
        "direction": "sell",
        "entry_price": 4500.0,
        "stop_price": 4505.0,
        "target_price": 4490.0,
        "selected_rr": 2.0,
        "continuation_momentum": 0.8,
        "displacement_score": 72,
        "micro_bos": True,
    }

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=signal,
        intelligence=_intelligence(),
        active_watch={"status": "TRIGGERED", "side": "SELL"},
        market_pulse={"score": 78},
        execution_environment=_safe_execution_environment(),
        q_learning_decision={
            "q_policy_action": "SELL",
            "q_values": {"SELL": 0.5, "HOLD": 0.1},
            "recent_similar_losses": 3,
        },
        direction_consistency_guard={"allowed": True},
        snapshot=_balanced_snapshot(),
    )

    assert result["required_execute_score"] == 90.0
    assert result["decision"] != "EXECUTE"
    assert "recent_similar_loss_streak_requires_textbook_confirmation" in result["dynamic_threshold_analysis"]["reasons"]
