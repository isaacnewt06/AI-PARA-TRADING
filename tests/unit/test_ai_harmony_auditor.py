from pathlib import Path

from src.trading.ai_harmony_auditor import AIHarmonyAuditor


def _base_intelligence(*, preferred_side: str = "BUY", watch_side: str = "BUY") -> dict:
    return {
        "overview": {
            "market_state": {"preferred_side": preferred_side},
        },
        "execution_readiness": {"action": "WATCH"},
        "watch_trigger": {
            "side": watch_side,
            "candidate_side": watch_side,
            "required_conditions": [
                f"higher_timeframe_bias en {watch_side} o al menos no contradictorio.",
            ],
            "cancel_conditions": [
                f"El lado candidato cambia a {'SELL' if watch_side == 'BUY' else 'BUY'}.",
            ],
            "missing_for_execute": ["Falta señal operativa confirmada."],
            "pattern_projection": {},
        },
    }


def test_ai_harmony_auditor_marks_q_learning_tension_without_signal(tmp_path: Path) -> None:
    auditor = AIHarmonyAuditor(reports_dir=tmp_path)

    result = auditor.generate(
        intelligence=_base_intelligence(preferred_side="BUY", watch_side="BUY"),
        signal=None,
        active_watch={"status": "ACTIVE", "side": "BUY"},
        market_pulse={"score": 88},
        q_learning_decision={"q_policy_action": "SELL", "experience_count": 10},
        execution_risk_decision={"can_execute": False, "allowed_risk_mode": "reduced"},
        position_management={"history_path": "history.jsonl"},
        direction_consistency_guard={"allowed": True},
        final_confirmation={"decision": "BLOCK", "final_confirmation_score": 58},
        real_account_safety_gate={"status": "REAL_BLOCKED_DEMO_ONLY"},
    )

    assert result["status"] == "HARMONIZED_WITH_WARNINGS"
    assert result["contradictions"] == []
    assert "Q-learning policy is not aligned with preferred_side" in result["warnings"][0]
    assert "Warnings / Layer Tensions" in (tmp_path / "AI_HARMONY_AUDIT_REPORT.md").read_text(encoding="utf-8")


def test_ai_harmony_auditor_detects_opposite_watch_contract(tmp_path: Path) -> None:
    auditor = AIHarmonyAuditor(reports_dir=tmp_path)
    intelligence = _base_intelligence(preferred_side="BUY", watch_side="BUY")
    intelligence["watch_trigger"]["required_conditions"] = [
        "higher_timeframe_bias en SELL o al menos no contradictorio.",
    ]
    intelligence["watch_trigger"]["cancel_conditions"] = ["El lado candidato cambia a BUY."]

    result = auditor.generate(
        intelligence=intelligence,
        signal=None,
        active_watch={"status": "ACTIVE", "side": "BUY"},
        market_pulse={"score": 88},
        q_learning_decision={"q_policy_action": "BUY", "experience_count": 10},
        execution_risk_decision={"can_execute": False, "allowed_risk_mode": "reduced"},
        position_management={"history_path": "history.jsonl"},
        direction_consistency_guard={"allowed": True},
        final_confirmation={"decision": "BLOCK", "final_confirmation_score": 58},
        real_account_safety_gate={"status": "REAL_BLOCKED_DEMO_ONLY"},
    )

    assert "Watch trigger contains higher-timeframe requirement for the opposite side." in result["contradictions"]
    assert "Watch trigger cancel condition invalidates its own side." in result["contradictions"]


def test_ai_harmony_auditor_treats_transparent_final_guard_as_warning(tmp_path: Path) -> None:
    auditor = AIHarmonyAuditor(reports_dir=tmp_path)

    result = auditor.generate(
        intelligence={
            **_base_intelligence(preferred_side="BUY", watch_side="BUY"),
            "execution_readiness": {"action": "EXECUTE"},
        },
        signal={"direction": "buy"},
        active_watch={"status": "TRIGGERED", "side": "BUY"},
        market_pulse={"score": 90},
        q_learning_decision={"q_policy_action": "SELL", "experience_count": 10},
        execution_risk_decision={"can_execute": False, "allowed_risk_mode": "blocked"},
        position_management={"history_path": "history.jsonl"},
        direction_consistency_guard={"allowed": True},
        final_confirmation={
            "decision": "BLOCK",
            "final_confirmation_score": 72,
            "blockers": ["volume_movement_not_confirmed"],
        },
        real_account_safety_gate={"status": "REAL_BLOCKED_DEMO_ONLY"},
    )

    assert result["contradictions"] == []
    assert "final confirmation correctly requires more safety" in " ".join(result["warnings"])
    assert result["status"] == "HARMONIZED_WITH_WARNINGS"
