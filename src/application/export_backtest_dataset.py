"""Application service for backtest dataset export."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.knowledge.backtest_dataset import BacktestDatasetBuilder


class BacktestDatasetApplicationService:
    """Build and optionally export a rule dataset for backtesting."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self, strategy_key: str | None = None, output_path: str | None = None) -> dict:
        return BacktestDatasetBuilder(self.session, self.settings).build(
            strategy_key=strategy_key,
            output_path=output_path,
        )
