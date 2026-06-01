"""Application service for controlled read-only paper trading."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.paper_trading_engine import PaperTradingEngine


class PaperTradingApplicationService:
    """Run a one-pass paper trading snapshot using read-only MT5 data."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, *, symbol: str, dry_run: bool = True) -> dict:
        return PaperTradingEngine(self.settings).run(symbol=symbol, dry_run=dry_run)
