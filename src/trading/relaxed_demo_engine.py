"""Relaxed Demo Engine - Extended hours for more opportunities."""
from __future__ import annotations

from pathlib import Path
import json
from typing import Any

# Import existing engine components
from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine
from src.trading.q_learning_decision_memory import QLearningDecisionMemory


class RelaxedDemoEngine:
    """Demo engine with extended operational hours and relaxed blockers."""
    
    def __init__(self, settings=None) -> None:
        self.engine = DefinitiveExecutionConfirmationEngine()
        
    def evaluate_signal(self, signal: dict[str, Any], intelligence: dict[str, Any]) -> dict[str, Any]:
        """Evaluate signal with relaxed criteria."""
        # Use standard engine but with relaxed context
        result = self.engine.evaluate(
            symbol=signal.get("symbol", "XAUUSDm"),
            signal=signal.get("signal"),
            intelligence=intelligence,
        )
        
        # Override blockers for extended hours
        original_blockers = result.get("blockers", [])
        relaxed_blockers = [
            b for b in original_blockers 
            if "session_not_validated" not in str(b)
            and "london_blocked" not in str(b)
            and "asia_blocked" not in str(b)
        ]
        
        result["blockers"] = relaxed_blockers
        result["decision"] = "EXECUTE" if result.get("final_confirmation_score", 0) >= 72 else result.get("decision")
        result["can_execute"] = result["decision"] == "EXECUTE"
        
        return result


if __name__ == "__main__":
    # Quick test
    engine = RelaxedDemoEngine()
    signal = {"symbol": "XAUUSDm", "signal": None}
    intelligence = {"overview": {"market_state": {"pulse_score": 75}}}
    result = engine.evaluate_signal(signal, intelligence)
    print(f"Decision: {result['decision']}, Score: {result.get('final_confirmation_score')}")