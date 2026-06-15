"""Run optimized backtest."""
from pathlib import Path
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester

backtester = MaximoMTFQuantV4Backtester(
    input_dir=Path("data/backtests/input"),
    output_dir=Path("data/backtests/maximo_mtf_quant_v4")
)

print("Ejecutando backtest v4 con ajustes optimizados...")
result = backtester.run(symbol="XAUUSDm", dataset_label="optimized_test_2025")
print(f"Trades: {result.get('trades', 0)}")
print(f"Win rate: {result.get('win_rate', 0):.1f}%")
print(f"Profit factor: {result.get('profit_factor', 0):.2f}")
print(f"Return: {result.get('net_return_pct', 0):.2f}%")
print(f"Avg R: {result.get('avg_net_r', 0):.2f}")