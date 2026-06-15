import csv
from pathlib import Path
from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine

csv_path = Path("data/backtests/maximo_mtf_quant_v4/yearly/2025_v56_aggressive_filtered_b_all_trades.csv")
with open(csv_path) as f:
    trades = list(csv.DictReader(f))

engine = DefinitiveExecutionConfirmationEngine()

for i, t in enumerate(trades[:5]):
    signal = {
        "direction": t["direction"],
        "stop_price": float(t["entry_price"]) * 0.995,
        "target_price": float(t["entry_price"]) * 1.01,
        "entry_price": float(t["entry_price"]),
        "selected_rr": 2.5,
        "displacement_score": 85,
        "continuation_momentum": 0.85,
        "micro_bos": True,
    }
    
    pulse = float(t.get("pulse_score", 70))
    intelligence = {
        "overview": {
            "market_state": {
                "pulse_score": pulse + 10,
                "clarity_score": pulse + 10,
                "harmony_score": 0.9,
                "setup_maturity": 0.85,
                "daily_bias": t["direction"].upper(),
                "macro_bias": t["direction"].upper(),
                "preferred_side": t["direction"].upper(),
                "ob_rejection_families": {
                    "aggressive": {"active": True, "side": t["direction"].upper(), "checks": {"strong_bullish_rejection": True}},
                    "institutional": {"active": True},
                },
            },
            "execution_readiness": {"pulse_score": pulse + 10, "setup_maturity": 0.85},
            "event_risk": {},
        },
        "watch_trigger": {"setup_detected": "OB_REJECTION", "side": t["direction"].upper()},
    }
    
    result = engine.evaluate(symbol="XAUUSDm", signal=signal, intelligence=intelligence)
    print(f"Trade {i+1}: score={result.get('final_confirmation_score')}, decision={result.get('decision')}")
    print(f"  Checklist: pulse={result['confirmation_checklist']['pulse_strong']}, volume={result['confirmation_checklist']['volume_confirmed']}")