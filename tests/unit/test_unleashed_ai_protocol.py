"""Fail-closed trading authorization tests: no MT5 or network dependency."""

from src.trading.unleashed_ai_protocol import UnleashedAIProtocol, quick_ai_check


def test_unleashed_protocol_cannot_authorize_trades() -> None:
    result = UnleashedAIProtocol().evaluate(
        symbol="XAUUSDm", pulse_score=1.0, event_action="ALLOW",
        execution_viability="SAFE", final_confirmation_score=1.0,
    )
    assert result["allowed"] is False
    assert result["action"] == "BLOCK"
    assert result["risk_multiplier"] == 0.0
    assert "trading_authority_locked" in result["blockers"]


def test_quick_ai_check_cannot_bypass_authority_lock() -> None:
    allowed, blockers = quick_ai_check(
        {"event_risk": {"action": "ALLOW"}, "execution_environment": {"execution_viability": "SAFE"}},
        {"symbol": "XAUUSDm"},
    )
    assert allowed is False
    assert "trading_authority_locked" in blockers
