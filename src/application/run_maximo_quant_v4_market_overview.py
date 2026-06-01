"""Application service for current market overview with MAXIMO Quant v4."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.maximo_quant_v4_market_overview import MaximoQuantV4MarketOverviewEngine


class MaximoQuantV4MarketOverviewApplicationService:
    """Generate a current market view and action recommendation from MT5 plus learned knowledge."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, *, symbol: str) -> dict:
        return MaximoQuantV4MarketOverviewEngine(self.settings).run(symbol=symbol)
