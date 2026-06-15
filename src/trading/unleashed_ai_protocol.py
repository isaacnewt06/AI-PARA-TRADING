"""UNLEASHED AI Protocol - No bottlenecks, full operation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class UnleashedAIProtocol:
    """AI with zero artificial restrictions - operational 24/7."""
    
    def evaluate(
        self,
        *,
        symbol: str,
        pulse_score: float,
        event_action: str,
        execution_viability: str,
        final_confirmation_score: float,
    ) -> dict[str, Any]:
        """Only block on critical safety issues, never on time or ATR."""
        
        blockers = []
        
        # ONLY critical blocks
        if event_action and str(event_action).upper() == "BLOCK":
            blockers.append("critical_macro_block")
        if execution_viability and str(execution_viability).upper() == "UNSAFE":
            blockers.append("execution_environment_unsafe")
        
        # Never block on session hours, ATR, or other artificial restrictions
        
        allowed = not blockers
        
        return {
            "protocol_name": "UNLEASHED_AI_V1",
            "allowed": allowed,
            "action": "ALLOW" if allowed else "BLOCK",
            "blockers": blockers,
            "reason": "No artificial restrictions. Operational 24/7." if allowed else "Only critical safety blocks active.",
            "risk_multiplier": 1.0 if allowed else 0.0,
        }


# Direct integration for immediate use
AI_SAFE_BLOCKERS = {"critical_macro_block", "execution_environment_unsafe"}

def quick_ai_check(intelligence: dict, signal: dict) -> tuple[bool, list[str]]:
    """Quick check without hour/ATR restrictions.
    
    Returns (allowed, blockers).
    """
    blockers = []
    
    event_action = str(intelligence.get("event_risk", {}).get("action", "allow")).upper()
    if event_action == "BLOCK":
        blockers.append("critical_macro_block")
    
    # Check execution environment
    exec_env = intelligence.get("execution_environment", {})
    viability = str(exec_env.get("execution_viability", "SAFE")).upper()
    if viability == "UNSAFE":
        blockers.append("execution_environment_unsafe")
    
    return len(blockers) == 0, blockers