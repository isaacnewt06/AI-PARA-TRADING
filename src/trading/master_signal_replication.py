"""Master-Signal Replication System for Copy Trading.

This module allows multiple MT5 clients to replicate AI trades from a master account.

Architecture:
- Master server (you): Runs AI and generates signals
- Client terminals: Receive signals and execute on their MT5 accounts
- Central API: Distributes signals via /api/platform/accounts/{id}/copy-trading/master-signal
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from dataclasses import dataclass


@dataclass
class MasterSignal:
    symbol: str
    side: str
    entry_price: float
    stop_price: float
    target_price: float
    volume: float
    timestamp: str
    setup_type: str
    confidence: float
    staged_exits: list[dict[str, Any]]


class MasterSignalPublisher:
    """Publishes AI signals for client replication."""
    
    def __init__(self, signals_dir: Path = None) -> None:
        self.signals_dir = signals_dir or Path("data/demo_trading/maximo_quant_v4/signals_for_replication")
        self.signals_dir.mkdir(parents=True, exist_ok=True)
        self.active_signals_file = self.signals_dir / "active_signals.json"
    
    def publish_signal(self, signal: MasterSignal) -> None:
        """Write signal for client pickup."""
        payload = {
            "symbol": signal.symbol,
            "side": signal.side,
            "entry_price": signal.entry_price,
            "stop_price": signal.stop_price,
            "target_price": signal.target_price,
            "volume": signal.volume,
            "timestamp": signal.timestamp,
            "setup_type": signal.setup_type,
            "confidence": signal.confidence,
            "staged_exits": signal.staged_exits,
        }
        self.active_signals_file.write_text(json.dumps(payload, indent=2))
    
    def get_signals(self) -> list[MasterSignal]:
        """Read active signals."""
        if self.active_signals_file.exists():
            data = json.loads(self.active_signals_file.read_text())
            return [MasterSignal(**data)] if isinstance(data, dict) else []
        return []


class ClientSignalReceiver:
    """Client-side signal receiver for MT5 execution."""
    
    def __init__(self, api_url: str, token: str) -> None:
        self.api_url = api_url
        self.token = token
        self.last_signal_file = Path("last_executed_signal.json")
    
    def fetch_master_signal(self) -> MasterSignal | None:
        """Fetch signal from master server. Client needs HTTP call."""
        # This would be called by client's local script
        import urllib.request
        req = urllib.request.Request(
            f"{self.api_url}/api/platform/ai/live-signal",
            headers={"Authorization": f"Bearer {self.token}"}
        )
        try:
            response = urllib.request.urlopen(req, timeout=10)
            data = json.loads(response.read().decode())
            if data.get("replication_ready"):
                return MasterSignal(
                    symbol=data["symbol"],
                    side=data["direction"],
                    entry_price=data["entry_zone"]["entry_price"],
                    stop_price=data["entry_zone"]["stop_price"],
                    target_price=data["entry_zone"]["target_price"],
                    volume=0.01,  # Client sets their own volume
                    timestamp=data["timestamp"],
                    setup_type=data["setup_type"],
                    confidence=data["confidence"],
                    staged_exits=[],
                )
        except Exception:
            pass
        return None
    
    def execute_on_mt5(self, signal: MasterSignal) -> dict[str, Any]:
        """Execute signal on local MT5 via bridge."""
        # Client runs this on their machine with MT5 terminal
        try:
            from src.trading.mt5_bridge import MT5Bridge
            from src.core.config import get_settings
            
            bridge = MT5Bridge(get_settings())
            result = bridge.place_order(
                symbol=signal.symbol,
                side=signal.side,
                volume=signal.volume,
                price=signal.entry_price,
                stop_loss=signal.stop_price,
                take_profit=signal.target_price,
            )
            return {"executed": True, "result": result}
        except Exception as e:
            return {"executed": False, "error": str(e)}


def create_client_script() -> str:
    """Generate a client script they can run locally."""
    return '''#!/usr/bin/env python3
"""Client replication script - run this on each client machine with MT5."""

import time
import json
from pathlib import Path

API_URL = "https://your-server.com"
TOKEN = "REPLACE_WITH_CLIENT_TOKEN"

def main():
    from ai_copy_trading import ClientSignalReceiver
    
    receiver = ClientSignalReceiver(API_URL, TOKEN)
    
    while True:
        signal = receiver.fetch_master_signal()
        if signal:
            print(f"Signal received: {signal.side} {signal.symbol}")
            result = receiver.execute_on_mt5(signal)
            if result["executed"]:
                print(f"Executed: {result['result']}")
            else:
                print(f"Failed: {result['error']}")
        
        time.sleep(30)  # Check every 30 seconds

if __name__ == "__main__":
    main()
'''