"""Application service for strategy export and inspection."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.backtest_bridge import BacktestBridge


class StrategyExportApplicationService:
    """Export and inspect compiled strategies."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def export(self, output_path: str, format_name: str | None = None) -> dict:
        return BacktestBridge(self.session, self.settings).export_strategies(output_path, format_name=format_name)

    def inspect(self, setup_name: str) -> dict | None:
        return BacktestBridge(self.session, self.settings).inspect_setup(setup_name)

    def compare(self, strategy_a: str, strategy_b: str) -> dict:
        return BacktestBridge(self.session, self.settings).compare_strategies(strategy_a, strategy_b)
