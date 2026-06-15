"""API endpoint for AI signal distribution to clients."""
from __future__ import annotations

from fastapi import FastAPI
from pathlib import Path
import json
from typing import Any


def create_ai_signal_router(app: FastAPI) -> None:
    """Add AI signal distribution endpoints."""
    
    @app.get("/api/ai/signals/live")
    def get_live_ai_signals() -> dict[str, Any]:
        """Get current AI trading signals for all connected clients."""
        q_table = json.loads(Path("data/demo_trading/maximo_quant_v4/q_learning_table.json").read_text())
        
        # Get latest signal
        latest_signal_path = Path("data/demo_trading/maximo_quant_v4/latest_signal.json")
        if latest_signal_path.exists():
            latest_signal = json.loads(latest_signal_path.read_text())
        else:
            latest_signal = {}
        
        return {
            "status": "active",
            "q_learning_experience": q_table.get("_meta", {}).get("experience_count", 0),
            "signal": latest_signal,
            "thresholds": {
                "execute": 72.0,
                "armed_retest": 71.0,
            },
            "staged_exits": {
                "levels": ["0.5R", "0.7R", "1.0R"],
                "fractions": [0.3, 0.4, 0.3],
            },
        }
    
    @app.get("/api/ai/signals/history")
    def get_signal_history(limit: int = 50) -> dict[str, Any]:
        """Get historical AI signals for backtesting."""
        history_path = Path("data/demo_trading/maximo_quant_v4/signal_history.jsonl")
        if history_path.exists():
            lines = history_path.read_text().strip().splitlines()
            return {"history": [json.loads(l) for l in lines[-limit:]]}
        return {"history": []}


# Usage in main app:
# from src.api.ai_signal_distribution import create_ai_signal_router
# create_ai_signal_router(app)