"""Legacy AI protocol kept research-only while trading authority is locked."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class UnleashedAIProtocol:
    """Legacy interface, deliberately unable to grant trade authority."""
    
    def evaluate(
        self,
        *,
        symbol: str,
        pulse_score: float,
        event_action: str,
        execution_viability: str,
        final_confirmation_score: float,
    ) -> dict[str, Any]:
        """Retain safety reasons but never authorize order execution."""
        
        # Research-only: no automated trade authorization, even on safe markets.
        blockers = ["trading_authority_locked"]
        
        # ONLY critical blocks
        if event_action and str(event_action).upper() == "BLOCK":
            blockers.append("critical_macro_block")
        if execution_viability and str(execution_viability).upper() == "UNSAFE":
            blockers.append("execution_environment_unsafe")
        
        # This legacy protocol is not a substitute for a complete risk manager.
        
        return {
            "protocol_name": "UNLEASHED_AI_V1",
            "allowed": False,
            "action": "BLOCK",
            "blockers": blockers,
            "reason": "Not authorized for trading.",
            "risk_multiplier": 0.0,
        }


# Direct integration for immediate use
AI_SAFE_BLOCKERS = {"critical_macro_block", "execution_environment_unsafe", "trading_authority_locked"}

def quick_ai_check(intelligence: dict, signal: dict) -> tuple[bool, list[str]]:
    """Quick check without hour/ATR restrictions.
    
    Returns (allowed, blockers).
    """
    blockers = ["trading_authority_locked"]
    
    event_action = str(intelligence.get("event_risk", {}).get("action", "allow")).upper()
    if event_action == "BLOCK":
        blockers.append("critical_macro_block")
    
    # Check execution environment
    exec_env = intelligence.get("execution_environment", {})
    viability = str(exec_env.get("execution_viability", "SAFE")).upper()
    if viability == "UNSAFE":
        blockers.append("execution_environment_unsafe")
    
    return False, blockers
