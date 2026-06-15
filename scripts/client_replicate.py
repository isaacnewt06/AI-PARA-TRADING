#!/usr/bin/env python3
"""CLIENT REPLICATION SCRIPT - Run this on each client machine with MT5 installed."""

import time
import json
import urllib.request
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# CONFIGURE THESE VALUES:
API_URL = "http://127.0.0.1:8000"  # Your server URL
API_TOKEN = "REPLACE_WITH_YOUR_TOKEN"  # Get from /api/platform/register
SYMBOL = "XAUUSDm"
VOLUME = 0.01
CHECK_INTERVAL_SECONDS = 30


def fetch_signal():
    """Fetch latest AI signal from master server."""
    try:
        req = urllib.request.Request(
            f"{API_URL}/api/platform/ai/live-signal?symbol={SYMBOL}",
            headers={"Authorization": f"Bearer {API_TOKEN}"}
        )
        response = urllib.request.urlopen(req, timeout=10)
        return json.loads(response.read().decode())
    except Exception as e:
        print(f"[ERROR] Fetch signal: {e}")
        return None


def execute_on_mt5(signal_data):
    """Execute signal on local MT5."""
    try:
        from src.trading.mt5_bridge import MT5Bridge
        from src.core.config import get_settings
        
        bridge = MT5Bridge(get_settings())
        
        side = signal_data.get("direction", "buy").lower()
        entry_zone = signal_data.get("entry_zone", {})
        
        # Use staged exit logic
        if side == "BUY":
            stop = entry_zone.get("stop_price", entry_zone.get("entry_price") * 0.995)
        else:
            stop = entry_zone.get("stop_price", entry_zone.get("entry_price") * 1.005)
            
        target = entry_zone.get("target_price", entry_zone.get("entry_price") * 1.01)
        
        result = bridge.place_demo_market_order(
            symbol=SYMBOL,
            side=side,
            volume_lots=VOLUME,
            stop_loss=float(stop),
            take_profit=float(target),
            deviation_points=10,
            magic_number=560004,
            comment="AI_REPLICATION",
        )
        print(f"[OK] Executed: {result}")
        return True
    except Exception as e:
        print(f"[ERROR] MT5 execution: {e}")
        return False


def main():
    print("=" * 50)
    print("MT5 AI REPLICATION CLIENT")
    print(f"Server: {API_URL}")
    print(f"Symbol: {SYMBOL}")
    print("=" * 50)
    
    while True:
        signal = fetch_signal()
        if signal and signal.get("replication_ready"):
            print(f"\n[SIGNAL] {signal.get('direction')} {signal.get('setup_type')} @ {signal.get('entry_zone', {}).get('entry_price')}")
            execute_on_mt5(signal)
        else:
            print(f".", end="", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()