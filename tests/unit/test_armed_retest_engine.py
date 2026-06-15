from __future__ import annotations

import json

from src.trading.armed_retest_engine import ArmedRetestEngine


def test_armed_retest_wait_creates_persistent_state(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={"direction": "SELL", "entry_price": 4500.0, "stop_price": 4504.0, "target_price": 4492.0},
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "SELL"}}},
        active_watch={"side": "SELL", "trigger_type": "liquidity_retest"},
        final_confirmation={"side": "SELL", "final_confirmation_score": 66.0, "blockers": []},
        market_pulse={"score": 91.0},
        execution_readiness={"execution_readiness_score": 74.0, "classification": "ARMED_RETEST"},
        entry_quality={"entry_quality_score": 68.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={"allowed_risk_mode": "reduced", "execution_recovery_plan": {"reason": "wait"}},
        q_learning_decision={"q_policy_action": "SELL", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"close": 4500.5}]}},
    )

    assert result["action"] == "ARMED_RETEST_WAIT"
    assert result["side"] == "SELL"
    assert (tmp_path / "armed_state.json").exists()
    events = [json.loads(line) for line in (tmp_path / "armed_history.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "ARMED_RETEST_CREATED"


def test_armed_retest_existing_state_can_become_execute_ready(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )
    engine.evaluate(
        symbol="XAUUSDm",
        signal={"direction": "BUY", "entry_price": 4500.0, "stop_price": 4497.0, "target_price": 4507.0},
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "BUY"}}},
        active_watch={"side": "BUY", "trigger_type": "retest"},
        final_confirmation={"side": "BUY", "final_confirmation_score": 65.0, "blockers": []},
        market_pulse={"score": 90.0},
        execution_readiness={"execution_readiness_score": 74.0, "classification": "ARMED_RETEST"},
        entry_quality={"entry_quality_score": 68.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={"allowed_risk_mode": "reduced", "execution_recovery_plan": {"reason": "wait"}},
        q_learning_decision={"q_policy_action": "BUY", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"close": 4500.0}]}},
    )

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={"direction": "BUY", "entry_price": 4500.0, "stop_price": 4498.5, "target_price": 4505.0},
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "BUY"}}},
        active_watch={"side": "BUY", "trigger_type": "retest"},
        final_confirmation={"side": "BUY", "final_confirmation_score": 78.0, "blockers": []},
        market_pulse={"score": 92.0},
        execution_readiness={"execution_readiness_score": 82.0, "classification": "EXECUTION_READY"},
        entry_quality={"entry_quality_score": 80.0, "decision": "EXECUTION_READY"},
        execution_risk_decision={"allowed_risk_mode": "reduced"},
        q_learning_decision={"q_policy_action": "BUY", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"close": 4500.0}]}},
    )

    assert result["action"] == "ARMED_RETEST_EXECUTE_READY"


def test_armed_retest_reduced_execute_ready_when_final_confirmation_authorizes(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )
    engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {"market_state": {"preferred_side": "BUY"}, "signal": None},
        },
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={"side": "BUY", "final_confirmation_score": 60.0, "blockers": []},
        market_pulse={"score": 90.0},
        execution_readiness={"execution_readiness_score": 71.0, "classification": "ARMED_RETEST"},
        entry_quality={"entry_quality_score": 48.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={
            "allowed_risk_mode": "blocked",
            "watch_policy_action": "OBSERVE",
            "execution_status": "no_signal",
        },
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2025-01-16T23:55:00+00:00", "close": 2714.2}]}},
    )

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={
            "direction": "BUY",
            "signal_type": "ARMED_RETEST_REDUCED_SIGNAL",
            "entry_price": 2714.27,
            "stop_price": 2711.95,
            "target_price": 2718.74,
        },
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "BUY"}}},
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={
            "side": "BUY",
            "decision": "EXECUTE",
            "final_confirmation_score": 66.83,
            "confirmation_awareness_allowed": True,
            "blockers": [],
        },
        market_pulse={"score": 86.14},
        execution_readiness={"execution_readiness_score": 71.97, "classification": "ARMED_RETEST"},
        entry_quality={"entry_quality_score": 76.46, "decision": "CLEAN_ENTRY"},
        execution_risk_decision={"allowed_risk_mode": "reduced"},
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2025-01-17T00:25:00+00:00", "close": 2714.27}]}},
    )

    assert result["action"] == "ARMED_RETEST_EXECUTE_READY"


def test_armed_retest_can_be_execute_ready_on_creation(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={"direction": "BUY", "signal_type": "ARMED_RETEST_REDUCED_SIGNAL"},
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "BUY"}}},
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={"side": "BUY", "decision": "EXECUTE", "final_confirmation_score": 70.42, "blockers": []},
        market_pulse={"score": 87.72},
        execution_readiness={"execution_readiness_score": 74.47, "classification": "ARMED_RETEST"},
        entry_quality={"entry_quality_score": 81.22, "decision": "CLEAN_ENTRY"},
        execution_risk_decision={"allowed_risk_mode": "reduced"},
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2025-01-16T19:00:00+00:00", "close": 2714.27}]}},
    )

    assert result["action"] == "ARMED_RETEST_EXECUTE_READY"


def test_armed_retest_keeps_state_when_final_confirmation_is_prepare_without_blockers(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )
    engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "BUY"}}},
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={"side": "BUY", "final_confirmation_score": 62.0, "blockers": []},
        market_pulse={"score": 90.0},
        execution_readiness={"execution_readiness_score": 71.0, "classification": "ARMED_RETEST"},
        entry_quality={"entry_quality_score": 52.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={"allowed_risk_mode": "blocked", "watch_policy_action": "OBSERVE", "execution_status": "no_signal"},
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2025-01-16T23:55:00+00:00", "close": 2714.2}]}},
    )

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal={"direction": "BUY", "signal_type": "ARMED_RETEST_REDUCED_SIGNAL"},
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "BUY"}}},
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={"side": "BUY", "decision": "PREPARE", "final_confirmation_score": 59.0, "blockers": []},
        market_pulse={"score": 92.0},
        execution_readiness={"execution_readiness_score": 42.0, "classification": "NOT_READY"},
        entry_quality={"entry_quality_score": 77.0, "decision": "CLEAN_ENTRY"},
        execution_risk_decision={"allowed_risk_mode": "blocked", "execution_status": "blocked_by_final_confirmation"},
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2025-01-17T00:05:00+00:00", "close": 2714.27}]}},
    )

    assert result["action"] == "ARMED_RETEST_WAIT"
    assert (tmp_path / "armed_state.json").exists()


def test_armed_retest_can_arm_when_watch_policy_is_observe_blocked(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {"market_state": {"preferred_side": "SELL"}, "signal": None},
        },
        active_watch={"side": "SELL", "trigger_type": "bearish_retest"},
        final_confirmation={"side": "SELL", "final_confirmation_score": 64.0, "blockers": []},
        market_pulse={"score": 90.0},
        execution_readiness={"execution_readiness_score": 55.0, "classification": "WATCH_ONLY"},
        entry_quality={"entry_quality_score": 49.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={
            "allowed_risk_mode": "blocked",
            "watch_policy_action": "OBSERVE",
            "execution_status": "no_signal",
        },
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"close": 4500.0}]}},
    )

    assert result["action"] == "ARMED_RETEST_WAIT"
    assert result["side"] == "SELL"


def test_armed_retest_arms_borderline_final_confirmation_when_pulse_is_predator(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {"market_state": {"preferred_side": "BUY"}, "signal": None},
        },
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={"side": "BUY", "final_confirmation_score": 59.55, "blockers": []},
        market_pulse={"score": 86.4},
        execution_readiness={"execution_readiness_score": 13.4, "classification": "NOT_READY"},
        entry_quality={"entry_quality_score": 46.89, "decision": "WAIT_RETEST"},
        execution_risk_decision={
            "allowed_risk_mode": "blocked",
            "watch_policy_action": "OBSERVE",
            "execution_status": "no_signal",
        },
        q_learning_decision={"q_policy_action": "SELL", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"close": 4959.59}]}},
    )

    assert result["action"] == "ARMED_RETEST_WAIT"
    assert "borderline" in result["reason"]


def test_armed_retest_arms_strong_context_before_final_trigger(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )

    result = engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {
                "signal": None,
                "market_state": {
                    "preferred_side": "BUY",
                    "market_clarity": {
                        "selected_side": "BUY",
                        "clarity_score": 89.8,
                        "expected_entry_zone": {"in_zone_now": True},
                    },
                    "expected_entry_zone": {"in_zone_now": True},
                    "entry_trigger_plan": {"liquidity_confirmed": True},
                },
            },
        },
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={
            "side": "BUY",
            "final_confirmation_score": 49.83,
            "trap_risk_score": 0.18,
            "late_entry_risk": 0.2,
            "blockers": [],
        },
        market_pulse={"score": 90.41},
        execution_readiness={"execution_readiness_score": 0.0, "classification": "NOT_READY"},
        entry_quality={"entry_quality_score": 45.04, "decision": "WAIT_RETEST", "zone_quality": 64.0},
        execution_risk_decision={
            "allowed_risk_mode": "blocked",
            "watch_policy_action": "OBSERVE",
            "execution_status": "no_signal",
        },
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE", "session_rd": "pm_volatility_rd"},
        snapshot={"candles": {"M1": [{"time": "2025-01-16T19:00:00+00:00", "close": 4500.0}]}},
    )

    assert result["action"] == "ARMED_RETEST_WAIT"
    assert result["side"] == "BUY"
    assert "Contexto institucional fuerte" in result["reason"]
    plan = result["entry_confirmation_plan"]
    assert plan["status"] == "WAITING_PRECISE_TRIGGER"
    assert plan["where_to_enter"]["zone"]["type"] == "buy_retest_zone"
    assert "Final Confirmation >= 75" in plan["when_to_execute"]
    assert "precio persigue fuera de la zona preparada" in plan["do_not_execute_if"]
    assert (tmp_path / "armed_state.json").exists()


def test_armed_retest_builds_reduced_signal_when_price_returns_to_zone(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )
    engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {"market_state": {"preferred_side": "SELL"}, "signal": None},
        },
        active_watch={"side": "SELL", "trigger_type": "bearish_retest"},
        final_confirmation={"side": "SELL", "final_confirmation_score": 66.0, "blockers": []},
        market_pulse={"score": 91.0},
        execution_readiness={"execution_readiness_score": 55.0, "classification": "WATCH_ONLY"},
        entry_quality={"entry_quality_score": 50.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={
            "allowed_risk_mode": "blocked",
            "watch_policy_action": "OBSERVE",
            "execution_status": "no_signal",
        },
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2026-01-01T10:00:00+00:00", "close": 4500.0}]}},
    )

    candidate = engine.build_reduced_signal_candidate(
        symbol="XAUUSDm",
        snapshot={"candles": {"M1": [{"time": "2026-01-01T10:05:00+00:00", "close": 4500.2}]}},
        market_pulse={"score": 92.0},
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "SELL"}}},
    )

    assert candidate is not None
    assert candidate["signal_type"] == "ARMED_RETEST_REDUCED_SIGNAL"
    assert candidate["direction"] == "sell"
    assert candidate["risk_mode"] == "reduced"


def test_armed_retest_does_not_build_signal_outside_retest_zone(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )
    engine.evaluate(
        symbol="XAUUSDm",
        signal=None,
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {"market_state": {"preferred_side": "BUY"}, "signal": None},
        },
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={"side": "BUY", "final_confirmation_score": 66.0, "blockers": []},
        market_pulse={"score": 91.0},
        execution_readiness={"execution_readiness_score": 55.0, "classification": "WATCH_ONLY"},
        entry_quality={"entry_quality_score": 50.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={
            "allowed_risk_mode": "blocked",
            "watch_policy_action": "OBSERVE",
            "execution_status": "no_signal",
        },
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2026-01-01T10:00:00+00:00", "close": 4500.0}]}},
    )

    candidate = engine.build_reduced_signal_candidate(
        symbol="XAUUSDm",
        snapshot={"candles": {"M1": [{"time": "2026-01-01T10:05:00+00:00", "close": 4512.0}]}},
        market_pulse={"score": 92.0},
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "BUY"}}},
    )

    assert candidate is None


def test_armed_retest_does_not_build_buy_when_price_already_broke_stop(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )
    engine.evaluate(
        symbol="XAUUSDm",
        signal={"direction": "BUY", "entry_price": 4245.0, "stop_price": 4241.0, "target_price": 4252.0},
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {"market_state": {"preferred_side": "BUY"}, "signal": None},
        },
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={"side": "BUY", "final_confirmation_score": 66.0, "blockers": []},
        market_pulse={"score": 91.0},
        execution_readiness={"execution_readiness_score": 55.0, "classification": "WATCH_ONLY"},
        entry_quality={"entry_quality_score": 50.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={
            "allowed_risk_mode": "blocked",
            "watch_policy_action": "OBSERVE",
            "execution_status": "no_signal",
        },
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2026-01-01T10:00:00+00:00", "close": 4245.0}]}},
    )

    candidate = engine.build_reduced_signal_candidate(
        symbol="XAUUSDm",
        snapshot={"candles": {"M1": [{"time": "2026-01-01T10:05:00+00:00", "close": 4239.8}]}},
        market_pulse={"score": 92.0},
        intelligence={"event_risk": {"action": "allow"}, "overview": {"market_state": {"preferred_side": "BUY"}}},
    )

    assert candidate is None
    history = (tmp_path / "armed_history.jsonl").read_text(encoding="utf-8")
    assert "directional_geometry_invalid_or_already_broken" in history


def test_armed_retest_does_not_build_when_context_price_broke_stop(tmp_path):
    engine = ArmedRetestEngine(
        state_path=tmp_path / "armed_state.json",
        history_path=tmp_path / "armed_history.jsonl",
    )
    engine.evaluate(
        symbol="XAUUSDm",
        signal={"direction": "BUY", "entry_price": 4245.0, "stop_price": 4241.0, "target_price": 4252.0},
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {
                "market_state": {
                    "preferred_side": "BUY",
                    "expected_entry_zone": {"current_price": 4245.0, "in_zone_now": True},
                },
                "signal": None,
            },
        },
        active_watch={"side": "BUY", "trigger_type": "bullish_retest"},
        final_confirmation={"side": "BUY", "final_confirmation_score": 66.0, "blockers": []},
        market_pulse={"score": 91.0},
        execution_readiness={"execution_readiness_score": 55.0, "classification": "WATCH_ONLY"},
        entry_quality={"entry_quality_score": 50.0, "decision": "WAIT_RETEST"},
        execution_risk_decision={
            "allowed_risk_mode": "blocked",
            "watch_policy_action": "OBSERVE",
            "execution_status": "no_signal",
        },
        q_learning_decision={"q_policy_action": "HOLD", "value_gap": 0.1},
        execution_environment={"execution_viability": "SAFE"},
        snapshot={"candles": {"M1": [{"time": "2026-01-01T10:00:00+00:00", "close": 4245.0}]}},
    )

    candidate = engine.build_reduced_signal_candidate(
        symbol="XAUUSDm",
        snapshot={"candles": {"M1": [{"time": "2026-01-01T10:05:00+00:00", "close": 4243.8}]}},
        market_pulse={"score": 92.0},
        intelligence={
            "event_risk": {"action": "allow"},
            "overview": {
                "market_state": {
                    "preferred_side": "BUY",
                    "expected_entry_zone": {"current_price": 4239.8, "in_zone_now": True},
                }
            },
        },
    )

    assert candidate is None
    history = (tmp_path / "armed_history.jsonl").read_text(encoding="utf-8")
    assert "context_price_geometry_invalid_or_already_broken" in history
