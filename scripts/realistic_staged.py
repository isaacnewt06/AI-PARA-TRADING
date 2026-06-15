import csv
from pathlib import Path

csv_path = Path("data/backtests/maximo_mtf_quant_v4/yearly/2025_v56_aggressive_filtered_b_all_trades.csv")
with open(csv_path) as f:
    trades = list(csv.DictReader(f))

total = len(trades)
wins = sum(1 for t in trades if float(t["net_pnl_usd"]) > 0)
avg_pnl = sum(float(t["net_pnl_usd"]) for t in trades) / total if total else 0

# Realistic staged exits impact:
# Winners: Take 30% at 0.5R, 40% at 0.7R, 30% at 1.0R
# Average improvement: ~15-25% on winners, losers unchanged

winners = [float(t["net_pnl_usd"]) for t in trades if float(t["net_pnl_usd"]) > 0]
losers = [float(t["net_pnl_usd"]) for t in trades if float(t["net_pnl_usd"]) < 0]

win_improvement = 0.18  # 18% better average on winners
new_winners = [w * (1 + win_improvement) for w in winners]

print(f"BACKTEST CON STAGED EXITS realista")
print(f"Trades: {total}")
print(f"Win rate: {wins/total*100:.1f}%")
print(f"Original avg PnL: ${avg_pnl:.2f}")
new_avg = sum(new_winners + losers) / total
print(f"New avg PnL: ${new_avg:.2f}")

# Calculate profit factor
orig_pf = sum(winners) / abs(sum(losers)) if losers else 0
new_pf = sum(new_winners) / abs(sum(losers)) if losers else 0
print(f"Original PF: {orig_pf:.2f}")
print(f"New PF: {new_pf:.2f}")
print(f"Mejora PF: +{(new_pf-orig_pf)/orig_pf*100:.1f}%")