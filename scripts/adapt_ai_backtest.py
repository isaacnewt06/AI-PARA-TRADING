import csv
from pathlib import Path
import json
from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine

csv_path = Path("data/backtests/maximo_mtf_quant_v4/yearly/2025_v56_aggressive_filtered_b_all_trades.csv")
with open(csv_path) as f:
    trades = list(csv.DictReader(f))

engine = DefinitiveExecutionConfirmationEngine()

scores = []
approved = 0
for t in trades[:50]:  # Test first 50
    signal = {
        "direction": t["direction"],
        "stop_price": float(t.get("stop_price", 0)) or float(t["entry_price"]) * 0.995,
        "target_price": float(t.get("target_price", 0)) or float(t["entry_price"]) * 1.01,
        "entry_price": float(t["entry_price"]),
        "selected_rr": 2.0,
        "displacement_score": 85,  # Strong signal
        "continuation_momentum": 0.85,
        "micro_bos": True,
    }
    
    pulse = float(t.get("pulse_score", 70))
    intelligence = {
        "overview": {
            "market_state": {
                "pulse_score": pulse,
                "clarity_score": pulse,  # Assume clarity matches pulse
                "harmony_score": 0.85,
                "setup_maturity": 0.8,
                "daily_bias": t["direction"].upper(),
                "macro_bias": t["direction"].upper(),
                "preferred_side": t["direction"].upper(),
                "ob_rejection_families": {
                    "aggressive": {"active": True, "side": t["direction"].upper(), "checks": {"strong_bullish_rejection": True}},
                    "institutional": {"active": True, "side": t["direction"].upper()},
                },
            },
            "execution_readiness": {"pulse_score": pulse, "setup_maturity": 0.8},
            "event_risk": {},
        },
        "watch_trigger": {"setup_detected": "OB_REJECTION", "side": t["direction"].upper()},
    }
    
    result = engine.evaluate(symbol="XAUUSDm", signal=signal, intelligence=intelligence)
    scores.append(result.get("final_confirmation_score", 0))
    
    if result.get("decision") == "EXECUTE":
        approved += 1

print(f"SCORES: min={min(scores):.1f}, max={max(scores):.1f}, avg={sum(scores)/len(scores):.1f}")
print(f"APROBADOS (EXECUTE): {approved}/50 ({approved/50*100:.1f}%)")
print(f"UMBRAL EXECUTE: 72.0")