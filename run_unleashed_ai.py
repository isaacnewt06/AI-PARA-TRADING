#!/usr/bin/env python3
"""UNLEASHED AI - Continuous Operation Script"""

import sys
sys.path.insert(0, "src")

# Apply unleashed protocol FIRST
import src.trading.demo_engine_patch  # noqa: F401

from src.trading.unleashed_ai_operative import UnleashedAIContinuous

if __name__ == "__main__":
    print("=" * 60)
    print("UNLEASHED AI - CONTINUOUS OPERATION")
    print("=" * 60)
    print("Features:")
    print("  - 24/7 operation (no time blocks)")
    print("  - All ATR regimes allowed")
    print("  - Only critical macro blocks active")
    print("  - 15-second cycle")
    print("  - Real MT5 order placement")
    print("=" * 60)
    print("")
    
    ai = UnleashedAIContinuous(symbol="XAUUSDm", volume=0.01)
    ai.run()