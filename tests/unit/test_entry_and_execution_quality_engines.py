from __future__ import annotations

from src.trading.entry_quality_engine import EntryQualityEngine
from src.trading.execution_readiness_engine import ExecutionReadinessEngine
from src.trading.final_confirmation_engine import FinalConfirmationEngine


def test_final_confirmation_awareness_blocks_unconscious_entry_trigger():
    result = FinalConfirmationEngine().evaluate(
        symbol="XAUUSDm",
        signal={
            "direction": "SELL",
            "entry_price": 4500.0,
            "stop_price": 4504.0,
            "target_price": 4492.0,
            "selected_rr": 2.0,
            "displacement_score": 20.0,
        },
        intelligence={
            "execution_readiness": {"action": "EXECUTE", "setup_maturity": 86.0, "confidence": 0.86},
            "event_risk": {"action": "allow"},
            "overview": {
                "market_state": {"preferred_side": "SELL", "higher_timeframe_bias": "SELL"},
                "knowledge_alignment": {"harmony": {"harmony_score": 0.78}},
            },
        },
        active_watch=None,
        market_pulse={"score": 92.0},
        execution_environment={"execution_viability": "SAFE"},
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.7, "HOLD": 0.2}},
        direction_consistency_guard={"allowed": True},
    )

    awareness = result["confirmation_awareness"]
    assert result["decision"] == "BLOCK"
    assert awareness["status"] == "BLOCK_INCOMPLETE_CONFIRMATION"
    assert awareness["execution_allowed_by_confirmation"] is False
    assert "clean_structure_trigger" in awareness["critical_missing"]
    assert "displacement_confirmation" in awareness["critical_missing"]
    assert "clean_structure_trigger_missing" in result["blockers"]


def test_final_confirmation_awareness_allows_clean_conscious_entry():
    result = FinalConfirmationEngine().evaluate(
        symbol="XAUUSDm",
        signal={
            "direction": "BUY",
            "entry_price": 4500.0,
            "stop_price": 4497.0,
            "target_price": 4507.0,
            "selected_rr": 2.3,
            "micro_bos": True,
            "displacement_score": 72.0,
            "continuation_momentum": 0.7,
        },
        intelligence={
            "execution_readiness": {"action": "EXECUTE", "setup_maturity": 88.0, "confidence": 0.88},
            "event_risk": {"action": "allow"},
            "overview": {
                "market_state": {"preferred_side": "BUY", "higher_timeframe_bias": "BUY", "impulse_score": 0.7},
                "knowledge_alignment": {"harmony": {"harmony_score": 0.82}},
            },
        },
        active_watch=None,
        market_pulse={"score": 90.0},
        execution_environment={"execution_viability": "SAFE"},
        q_learning_decision={"q_policy_action": "BUY", "q_values": {"BUY": 0.8, "HOLD": 0.1}},
        direction_consistency_guard={"allowed": True},
    )

    awareness = result["confirmation_awareness"]
    assert result["decision"] == "EXECUTE"
    assert awareness["status"] == "READY_TO_EXECUTE"
    assert awareness["execution_allowed_by_confirmation"] is True
    assert awareness["micro_structure_confirmed"] is True
    assert awareness["displacement_trigger"] is True


def test_entry_quality_waits_for_retest_when_min_lot_recovery_plan_exists():
    result = EntryQualityEngine().evaluate(
        signal={"direction": "SELL", "entry_price": 4500.0, "stop_price": 4512.0, "target_price": 4488.0, "selected_rr": 1.0},
        intelligence={"overview": {"market_state": {"preferred_side": "SELL"}}, "watch_trigger": {}},
        active_watch=None,
        final_confirmation={"final_confirmation_score": 68.0, "late_entry_risk": 0.45, "trap_risk_score": 0.3, "zone_validity_score": 0.8},
        execution_risk_decision={"execution_recovery_plan": {"reason": "wait compact sl"}},
        execution_environment={"execution_viability": "SAFE"},
        market_pulse={"score": 92.0},
    )

    assert result["decision"] == "WAIT_RETEST"
    assert result["entry_quality_score"] < 75


def test_entry_quality_execution_ready_for_clean_compact_entry():
    result = EntryQualityEngine().evaluate(
        signal={"direction": "BUY", "entry_price": 4500.0, "stop_price": 4497.0, "target_price": 4507.0, "selected_rr": 2.3, "micro_bos": True},
        intelligence={"overview": {"market_state": {"preferred_side": "BUY"}}, "watch_trigger": {}},
        active_watch=None,
        final_confirmation={"final_confirmation_score": 82.0, "late_entry_risk": 0.1, "trap_risk_score": 0.15, "zone_validity_score": 0.9},
        execution_risk_decision={},
        execution_environment={"execution_viability": "SAFE"},
        market_pulse={"score": 88.0},
    )

    assert result["decision"] == "EXECUTION_READY"
    assert result["entry_quality_score"] >= 75


def test_entry_quality_uses_aligned_course_knowledge_without_bypassing_guards():
    intelligence = {
        "overview": {
            "market_state": {
                "preferred_side": "SELL",
                "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH",
                "ob_rejection_families": {
                    "active_family": "OB_REJECTION_AGGRESSIVE_WATCH",
                    "manual_bias": {"active": True, "side": "SELL"},
                },
            },
            "knowledge_alignment": {
                "support_score": 0.72,
                "harmony": {"harmony_score": 0.74},
            },
        },
        "watch_trigger": {
            "pattern_projection": {
                "historical_analogs": {"bias": "favorable"},
                "cool_learning_memory": {
                    "policy_action": "SELL",
                    "course_alignment": {
                        "status": "aligned",
                        "course_recommended_action": "SELL",
                        "auto_selected_protocols": ["SENSEI_MANUAL_BIAS_PROTOCOL"],
                    },
                },
                "professional_decision_matrix": {"selected_side": "SELL"},
                "extracted_knowledge_operational_brain": {
                    "status": "primary_operational_brain",
                    "role": "motor_principal_de_decision",
                    "protocol_priority": "sensei_bias_high",
                },
            }
        },
    }

    result = EntryQualityEngine().evaluate(
        signal={
            "direction": "SELL",
            "entry_price": 4500.0,
            "stop_price": 4503.0,
            "target_price": 4493.0,
            "selected_rr": 2.3,
            "manual_bias_confirmation": True,
        },
        intelligence=intelligence,
        active_watch=None,
        final_confirmation={
            "final_confirmation_score": 72.5,
            "late_entry_risk": 0.2,
            "trap_risk_score": 0.2,
            "zone_validity_score": 0.78,
        },
        execution_risk_decision={},
        execution_environment={"execution_viability": "SAFE"},
        market_pulse={"score": 91.0},
    )

    assert result["decision"] == "EXECUTION_READY"
    assert result["learned_knowledge_entry_score"] >= 75
    assert result["learned_knowledge_entry_boost"] > 0


def test_entry_quality_course_knowledge_does_not_override_invalid_zone():
    result = EntryQualityEngine().evaluate(
        signal={
            "direction": "BUY",
            "entry_price": 4500.0,
            "stop_price": 4497.0,
            "target_price": 4507.0,
            "selected_rr": 2.3,
            "manual_bias_confirmation": True,
        },
        intelligence={
            "overview": {
                "market_state": {"preferred_side": "BUY"},
                "knowledge_alignment": {"support_score": 0.9, "harmony": {"harmony_score": 0.9}},
            },
            "watch_trigger": {
                "pattern_projection": {
                    "extracted_knowledge_operational_brain": {
                        "status": "primary_operational_brain",
                        "protocol_priority": "sensei_bias_high",
                    },
                    "cool_learning_memory": {
                        "policy_action": "BUY",
                        "course_alignment": {"status": "aligned", "auto_selected_protocols": ["SENSEI_MANUAL_BIAS_PROTOCOL"]},
                    },
                }
            },
        },
        active_watch=None,
        final_confirmation={
            "final_confirmation_score": 82.0,
            "late_entry_risk": 0.1,
            "trap_risk_score": 0.15,
            "zone_validity_score": 0.3,
        },
        execution_risk_decision={},
        execution_environment={"execution_viability": "SAFE"},
        market_pulse={"score": 92.0},
    )

    assert result["decision"] == "INVALID_ZONE_BLOCK"
    assert result["learned_knowledge_entry_score"] < 75


def test_execution_readiness_classifies_armed_retest_zone():
    result = ExecutionReadinessEngine().evaluate(
        final_confirmation={"side": "SELL", "final_confirmation_score": 69.0, "blockers": [], "warnings": [], "q_learning_alignment": 0.7, "event_action": "allow", "execution_viability": "SAFE"},
        market_pulse={"score": 91.0},
        direction_consistency_guard={"allowed": True},
        execution_risk_decision={"allowed_risk_mode": "reduced", "execution_recovery_plan": {"reason": "wait"}},
        q_learning_decision={"q_policy_action": "SELL"},
        intelligence={"execution_readiness": {"action": "EXECUTE"}},
        entry_quality={"entry_quality_score": 68.0, "sl_quality": 45.0, "tp_quality": 80.0},
    )

    assert result["classification"] in {"WATCH_ONLY", "ARMED_RETEST"}
    assert result["execution_readiness_score"] < 78


def test_execution_readiness_allows_clean_execution_ready():
    result = ExecutionReadinessEngine().evaluate(
        final_confirmation={"side": "BUY", "final_confirmation_score": 82.0, "blockers": [], "warnings": [], "q_learning_alignment": 0.9, "event_action": "allow", "execution_viability": "SAFE", "rr_evaluable": True},
        market_pulse={"score": 90.0},
        direction_consistency_guard={"allowed": True},
        execution_risk_decision={"allowed_risk_mode": "normal", "can_execute": True},
        q_learning_decision={"q_policy_action": "BUY"},
        intelligence={"execution_readiness": {"action": "EXECUTE"}},
        entry_quality={"entry_quality_score": 84.0, "sl_quality": 85.0, "tp_quality": 90.0},
    )

    assert result["classification"] == "EXECUTION_READY"
    assert result["can_execute_quality_gate"] is True
