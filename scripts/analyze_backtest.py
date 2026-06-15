import csv
from pathlib import Path

csv_path = Path("data/backtests/maximo_mtf_quant_v4/yearly/2025_v56_aggressive_filtered_b_all_trades.csv")
with open(csv_path) as f:
    reader = csv.DictReader(f)
    trades = list(reader)

wins = sum(1 for t in trades if float(t["net_pnl_usd"]) > 0)
total = len(trades)
avg_pnl = sum(float(t["net_pnl_usd"]) for t in trades) / total if total else 0

print(f"BACKTEST 2025_v56 ANALISIS")
print(f"Total trades: {total}")
print(f"Win rate: {wins/total*100:.1f}%")
print(f"Avg PnL: ${avg_pnl:.2f}")

pos = sum(float(t["net_pnl_usd"]) for t in trades if float(t["net_pnl_usd"]) > 0)
neg = sum(float(t["net_pnl_usd"]) for t in trades if float(t["net_pnl_usd"]) < 0)
print(f"Profit factor: {pos/abs(neg):.2f}")