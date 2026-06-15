"""MT5 Client Order Executor for AI Signal Replication."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MT5ClientConfig:
    symbol: str = "XAUUSDm"
    volume_lots: float = 0.01
    deviation_points: int = 10
    magic_number: int = 560004
    comment: str = "AI_REPLICATION"


def execute_ai_order_on_mt5(signal: dict[str, Any], config: MT5ClientConfig) -> dict[str, Any]:
    """Execute AI signal on local MT5 terminal. For client replication use.
    
    Args:
        signal: AI signal with direction, entry_price, stop_price, target_price
        config: Client configuration for order placement
        
    Returns:
        Order result or error
    """
    try:
        from src.trading.mt5_bridge import MT5Bridge
        from src.core.config import get_settings
        
        bridge = MT5Bridge(get_settings())
        
        side = signal.get("direction", "buy").lower()
        entry = float(signal.get("entry_price", 0))
        stop = float(signal.get("stop_price", 0))
        target = float(signal.get("target_price", 0))
        
        if not entry or not stop or not target:
            return {"error": "Missing price data", "executed": False}
        
        result = bridge.place_demo_market_order(
            symbol=config.symbol,
            side=side,
            volume_lots=config.volume_lots,
            stop_loss=stop,
            take_profit=target,
            deviation_points=config.deviation_points,
            magic_number=config.magic_number,
            comment=config.comment,
        )
        return {"executed": True, "result": result}
    except Exception as e:
        return {"executed": False, "error": str(e)}


def create_client_replication_script() -> str:
    """Generate client script for MT5 order replication."""
    return '''#!/usr/bin/env python3
"""Run on client machine with MT5 to replicate AI trades."""

import time
import json
import urllib.request
from pathlib import Path

# CONFIG - EDIT THESE
API_URL = "https://your-domain.com"  # Replace with your server
API_TOKEN = "YOUR_CLIENT_TOKEN"      # Get from /api/platform/register
SYMBOL = "XAUUSDm"
VOLUME = 0.01
CHECK_INTERVAL = 30

def fetch_signal():
    """Fetch latest AI signal."""
    try:
        req = urllib.request.Request(
            f"{API_URL}/api/platform/ai/live-signal?symbol={SYMBOL}",
            headers={"Authorization": f"Bearer {API_TOKEN}"}
        )
        response = urllib.request.urlopen(req, timeout=10)
        return json.loads(response.read().decode())
    except Exception as e:
        print(f"Error fetching signal: {e}")
        return None

def execute_on_mt5(signal_data):
    """Execute on local MT5."""
    try:
        from mt5_client import MT5ClientConfig, execute_ai_order_on_mt5
        
        config = MT5ClientConfig(symbol=SYMBOL, volume_lots=VOLUME)
        
        signal = {
            "direction": signal_data.get("direction"),
            "entry_price": signal_data.get("entry_zone", {}).get("entry_price"),
            "stop_price": signal_data.get("entry_zone", {}).get("stop_price"),
            "target_price": signal_data.get("entry_zone", {}).get("target_price"),
        }
        
        result = execute_ai_order_on_mt5(signal, config)
        print(f"Execution result: {result}")
    except Exception as e:
        print(f"MT5 execution error: {e}")

def main():
    print("Client replication started...")
    while True:
        signal = fetch_signal()
        if signal and signal.get("replication_ready"):
            print(f"Signal: {signal.get('direction')} {signal.get('setup_type')}")
            execute_on_mt5(signal)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
'''