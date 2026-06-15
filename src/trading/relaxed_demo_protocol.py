"""Relaxed Demo Protocol for Extended Operation Hours.

Extended operational window for AI trading opportunities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class RelaxedDemoProtocol:
    """Expanded operational hours for AI trading."""
    
    # Relaxed hours: operar desde 7am hasta 4pm NY (sesiones principales)
    OPERATIONAL_HOURS = frozenset({7, 8, 9, 10, 11, 12, 13, 14, 15, 16})
    BLOCKED_HIGH_IMPACT_EVENTS = frozenset({"BLOCK", "HIGH"})
    
    # Relaxed ATR: cualquier volatilidad
    SAFE_ATR_REGIMES = frozenset({"HIGH", "EXTREME", "NORMAL", "LOW"})
    
    def evaluate(
        self,
        *,
        symbol: str,
        hour_ny: int | None,
        atr_regime: str,
        event_action: str,
        spread: float | None,
        execution_viability: str,
    ) -> dict[str, Any]:
        blockers = []
        
        # Solo bloquear eventos de alto impacto
        if event_action and event_action.upper() in self.BLOCKED_HIGH_IMPACT_EVENTS:
            blockers.append(f"event_action_{event_action}")
        
        # Verificar viabilidad de ejecución
        if execution_viability and execution_viability.upper() == "UNSAFE":
            blockers.append("execution_viability_unsafe")
        
        # ATR ya no filtra - tomamos todo
        
        allowed = not blockers
        
        return {
            "protocol_name": "RELAXED_DEMO_PROTOCOL",
            "allowed": allowed,
            "action": "ALLOW" if allowed else "BLOCK",
            "blockers": blockers,
            "risk_mode": "standard" if allowed else "blocked",
        }


# Quick test
if __name__ == "__main__":
    protocol = RelaxedDemoProtocol()
    result = protocol.evaluate(
        symbol="XAUUSDm",
        hour_ny=10,
        atr_regime="NORMAL",
        event_action="allow",
        spread=0.30,
        execution_viability="SAFE"
    )
    print(f"Result: {result['action']} - {result['blockers']}")