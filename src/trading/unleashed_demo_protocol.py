"""Legacy protocol retained for reading historical results, not execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.trading.execution_environment_policy import limits_for_symbol


@dataclass(frozen=True, slots=True)
class UnleashedDemoProtocolV1:
    """Research-only protocol; cannot grant trading authority."""
    
    name: str = "UNLEASHED_DEMO_PROTOCOL_V1"
    edge_name: str = "displacement_plus_wick_v1"
    max_risk_multiplier: float = 0.0
    
    # Legacy metadata retained for compatibility; it grants no permission.
    OPERATIONAL_HOURS_24_7 = frozenset(range(24))
    
    # Research labels only; all trading evaluations are blocked.
    SAFE_ATR_REGIMES_ALL = frozenset({"HIGH", "EXTREME", "NORMAL", "LOW"})
    
    def evaluate(
        self,
        *,
        symbol: str,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        event_risk: dict[str, Any],
        execution_environment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a fail-closed research assessment regardless of input."""
        environment = execution_environment or {}
        
        blockers: list[str] = ["trading_authority_locked"]
        
        # ONLY critical blocks
        event_action = str(event_risk.get("action") or "allow").upper()
        if event_action == "BLOCK":
            blockers.append("critical_macro_block")
        
        spread = environment.get("live_spread")
        if spread is None:
            blockers.append("spread_unavailable")
        elif spread > limits_for_symbol(symbol).hard_spread:
            blockers.append("spread_too_wide")
        
        if environment.get("execution_viability") == "UNSAFE":
            blockers.append("execution_environment_unsafe")
        
        allowed = False
        
        return {
            "protocol_name": self.name,
            "edge_name": self.edge_name,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "allowed": allowed,
            "action": "ALLOW" if allowed else "BLOCK",
            "allowed_risk_mode": "full" if allowed else "blocked",
            "risk_multiplier": 0.0,
            "blockers": sorted(set(blockers)),
            "reason": "TRADING_AUTHORITY=NONE: no orders are authorized.",
        }
