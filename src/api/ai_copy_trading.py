"""Copy trading signal relay for AI operations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine


def integrate_ai_signals(app: FastAPI) -> None:
    """Integrate AI signal distribution into the platform API."""
    
    @app.get("/api/platform/ai/live-signal")
    def get_ai_live_signal(symbol: str = "XAUUSDm") -> dict[str, Any]:
        """Get current AI signal for replication."""
        # Load latest market data
        latest_signal_path = Path("data/demo_trading/maximo_quant_v4/latest_signal.json")
        if latest_signal_path.exists():
            signal = json.loads(latest_signal_path.read_text())
        else:
            signal = {}
        
        return {
            "symbol": symbol,
            "timestamp": signal.get("generated_at"),
            "direction": signal.get("watch_trigger", {}).get("side"),
            "setup_type": signal.get("watch_trigger", {}).get("setup_detected"),
            "confidence": signal.get("watch_trigger", {}).get("confidence"),
            "entry_zone": {
                "entry_price": signal.get("reasoning_snapshot", {}).get("entry_zone", {}).get("entry_price"),
                "stop_price": signal.get("reasoning_snapshot", {}).get("entry_zone", {}).get("stop_price"),
                "target_price": signal.get("reasoning_snapshot", {}).get("entry_zone", {}).get("target_price"),
            },
            "thresholds": {
                "min_score": 72.0,
                "armed_retest": 71.0,
            },
            "replication_ready": True,
        }
    
    @app.post("/api/platform/ai/evaluate-replication")
    def evaluate_replication(signal: dict[str, Any]) -> dict[str, Any]:
        """Evaluate if a signal qualifies for replication."""
        engine = DefinitiveExecutionConfirmationEngine()
        result = engine.evaluate(
            symbol=signal.get("symbol", "XAUUSDm"),
            signal=signal.get("signal"),
            intelligence=signal.get("intelligence"),
        )
        return {
            "decision": result.get("decision"),
            "score": result.get("final_confirmation_score"),
            "can_execute": result.get("can_execute"),
            "staged_exit_plan": result.get("staged_exit_plan"),
            "probability": result.get("probability"),
        }