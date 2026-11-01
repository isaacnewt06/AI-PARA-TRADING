"""Retired legacy runner; shadow research cannot send MT5 orders."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class UnleashedAIContinuous:
    """Historical interface retained for compatibility, execution disabled."""
    
    CHECK_EVERY_N_SECONDS = 15
    
    def __init__(self, symbol: str = "XAUUSDm", volume: float = 0.01) -> None:
        self.symbol = symbol
        self.volume = volume
        self.last_signal_path = Path("data/demo_trading/maximo_quant_v4/latest_signal.json")
    
    def run(self) -> None:
        """Prevent the old autonomous execution loop from starting."""
        raise RuntimeError("TRADING_AUTHORITY=NONE: unleashed execution is disabled.")
    
    def _evaluate_and_execute(self) -> dict[str, Any]:
        """Evalúa señal usando protocolo unleashed."""
        from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine
        
        engine = DefinitiveExecutionConfirmationEngine()
        
        # Signal simulada basada en datos M15/H1 disponibles
        signal = self._build_signal()
        intelligence = self._build_intelligence()
        
        result = engine.evaluate(
            symbol=self.symbol,
            signal=signal,
            intelligence=intelligence,
        )
        
        return {
            "score": result.get("final_confirmation_score", 0),
            "can_execute": False,
            "signal": None,
            "blockers": ["trading_authority_locked"],
        }
    
    def _build_signal(self) -> dict[str, Any]:
        """Construye señal desde última lectura o datos disponibles."""
        # Si hay señal reciente, usarla
        if self.last_signal_path.exists():
            try:
                data = json.loads(self.last_signal_path.read_text())
                signal = data.get("signal") or {}
                if signal:
                    return signal
            except Exception:
                pass
        
        # Señal por defecto
        return {
            "direction": "BUY",
            "stop_price": 2650.0,
            "target_price": 2655.0,
            "entry_price": 2652.0,
            "selected_rr": 2.0,
            "displacement_score": 80,
            "continuation_momentum": 0.75,
        }
    
    def _build_intelligence(self) -> dict[str, Any]:
        """Construye inteligencia de mercado simulada."""
        return {
            "overview": {
                "market_state": {
                    "pulse_score": 75,
                    "clarity_score": 70,
                    "harmony_score": 0.9,
                    "setup_maturity": 0.85,
                    "ob_rejection_families": {
                        "aggressive": {"active": True, "side": "BUY", "checks": {"strong_bullish_rejection": True}},
                        "institutional": {"active": True},
                    },
                },
                "execution_readiness": {"pulse_score": 75, "setup_maturity": 0.85},
                "event_risk": {"action": "allow"},  # NUNCA BLOQUEA
            },
        }
    
    def _place_order_on_mt5(self, signal: dict) -> None:
        """Keep direct callers blocked, even if the legacy loop is bypassed."""
        raise RuntimeError("TRADING_AUTHORITY=NONE: MT5 orders are disabled.")


if __name__ == "__main__":
    ai = UnleashedAIContinuous()
    ai.run()
