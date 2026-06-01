"""Application service for post-backtest diagnostics."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.backtest_diagnostics import BacktestDiagnosticsBuilder


class BacktestDiagnosticsApplicationService:
    """Analyze backtest result exports and generate diagnostics artifacts."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self) -> dict:
        backtests_root = self.settings.paths.data_dir / "backtests"
        input_dir = backtests_root / "input"
        results_dir = backtests_root / "results"
        reports_dir = backtests_root / "reports"
        for path in (input_dir, results_dir, reports_dir):
            path.mkdir(parents=True, exist_ok=True)
        return BacktestDiagnosticsBuilder(results_dir, reports_dir, input_dir).build()
