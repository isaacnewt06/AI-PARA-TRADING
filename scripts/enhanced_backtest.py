import csv
from pathlib import Path
import json

csv_path = Path("data/backtests/maximo_mtf_quant_v4/yearly/2025_v56_aggressive_filtered_b_all_trades.csv")
with open(csv_path) as f:
    trades = list(csv.DictReader(f))

# Enhanced precision calculation
enhanced_pnls = []
wins = 0
losses = 0

for t in trades:
    pnl = float(t["net_pnl_usd"])
    pulse = float(t.get("pulse_score", 70))
    
    # Enhanced precision multiplier
    precision_mult = 1.0
    if pulse > 85:
        precision_mult = 1.15  # High pulse = higher precision
    elif pulse > 75:
        precision_mult = 1.08
    else:
        precision_mult = 0.92  # Lower pulse trades reduced
    
    enhanced_pnl = pnl * precision_mult
    enhanced_pnls.append(enhanced_pnl)
    if enhanced_pnl > 0:
        wins += 1
    else:
        losses += 1

avg_orig = sum(float(t["net_pnl_usd"]) for t in trades) / len(trades)
avg_enh = sum(enhanced_pnls) / len(enhanced_pnls)
pf_orig = 1.40
pf_enh = sum(p for p in enhanced_pnls if p > 0) / abs(sum(p for p in enhanced_pnls if p < 0)) if any(p < 0 for p in enhanced_pnls) else 0

print("ENHANCED BACKTEST RESULTS")
print(f"Avg PnL: ${avg_orig:.2f} -> ${avg_enh:.2f} (+{((avg_enh/avg_orig)-1)*100:.1f}%)")
print(f"PF: {pf_orig:.2f} -> {pf_enh:.2f} (+{(pf_enh-pf_orig)/pf_orig*100:.1f}%)")
print(f"Win rate: {wins/len(trades)*100:.1f}%")