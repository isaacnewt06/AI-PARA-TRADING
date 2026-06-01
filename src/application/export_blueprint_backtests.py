"""Application service to export blueprint-driven backtest specs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.backtest_bridge import BacktestBridge


class BlueprintBacktestExportApplicationService:
    """Export executable blueprints into formal backtest specifications."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self, output_dir: str | None = None) -> dict:
        return BacktestBridge(self.session, self.settings).export_blueprint_backtests(output_dir)
