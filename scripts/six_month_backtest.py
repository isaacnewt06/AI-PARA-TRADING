"""Run 6-month backtest analysis for MAXIMO Quant v4."""

from __future__ import annotations

from pathlib import Path
from src.core.config import Settings
from src.trading.maximo_quant_v4_yearly_analyzer import MaximoQuantV4YearlyAnalyzer


def run_six_month_backtest() -> None:
    """Run backtest analysis for last 6 months (Dec 2025 - Jun 2026)."""
    settings = Settings()

    input_dir = settings.paths.data_dir / "backtests" / "input"
    backtests_dir = settings.paths.data_dir / "backtests"
    strategies_dir = settings.paths.data_dir / "strategies"

    analyzer = MaximoQuantV4YearlyAnalyzer(
        input_dir=input_dir,
        backtests_dir=backtests_dir,
        strategies_dir=strategies_dir,
    )

    # Load the best strategy snapshot
    snapshot_path = strategies_dir / "maximo_quant_v4_best_current.json"
    if not snapshot_path.exists():
        print("ERROR: No best strategy snapshot found. Run yearly optimizer first.")
        return

    import json
    snapshot = json.loads(snapshot_path.read_text())

    print("\n=== BACKTEST 6 MESES - DICIEMBRE 2025 A JUNIO 2026 ===\n")
    print(f"Estrategia: {snapshot['best_variant_code']}")
    print(f"Símbolo: {snapshot.get('symbol', 'XAUUSDm')}")

    result = analyzer.run(
        symbol="XAUUSDm",
        year=2025,
        initial_capital=500.0,
        volume_lots=0.01,
        strategy_variant_code=snapshot["best_variant_code"],
        session_variant_code=snapshot.get("session_variant", "all"),
        timeframe="M5",
    )

    print(f"\nResultados:")
    print(f"- Trades totales: {result['annual']['total_trades']}")
    print(f"- Win rate: {result['annual']['win_rate']}%")
    print(f"- Profit factor: {result['annual']['profit_factor']}")
    print(f"- Return: {result['annual']['total_return_percent']}%")
    print(f"- Max DD: {result['annual']['max_drawdown_percent']}%")
    print(f"- Profit: ${result['annual']['total_profit_usd']}")
    print(f"- Expectancy: ${result['annual']['expectancy_usd']}")

    print(f"\nPaths:")
    print(f"- Report: {result['report_path']}")
    print(f"- Trades: {result['trades_path']}")


if __name__ == "__main__":
    run_six_month_backtest()