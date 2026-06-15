import csv
from pathlib import Path
from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine

csv_path = Path("data/backtests/maximo_mtf_quant_v4/yearly/2025_v56_aggressive_filtered_b_all_trades.csv")
with open(csv_path) as f:
    trades = list(csv.DictReader(f))

engine = DefinitiveExecutionConfirmationEngine()

# Check why rejects
scores = []
for i, t in enumerate(trades[:10]):  # First 10 trades
    signal = {
        "direction": t["direction"],
        "stop_price": float(t.get("stop_price", 0)) or float(t["entry_price"]) * 0.995,
        "target_price": float(t.get("target_price", 0)) or float(t["entry_price"]) * 1.01,
        "entry_price": float(t["entry_price"]),
        "selected_rr": 2.0,
    }
    
    intelligence = {
        "overview": {
            "market_state": {
                "pulse_score": float(t.get("pulse_score", 70)),
                "clarity_score": float(t.get("clarity_score", 70)),
            },
            "execution_readiness": {"pulse_score": float(t.get("pulse_score", 70))},
        }
    }
    
    result = engine.evaluate(symbol="XAUUSDm", signal=signal, intelligence=intelligence)
    scores.append(result.get("final_confirmation_score", 0))
    if i < 3:
        print(f"Trade {i+1}: pulse={t.get('pulse_score', 70)}, score={result.get('final_confirmation_score')}, reason={result.get('reason')[:50]}")

print(f"\nPuntajes: min={min(scores):.1f}, max={max(scores):.1f}, avg={sum(scores)/len(scores):.1f}")
print(f"Threshold EXECUTE: 72.0")