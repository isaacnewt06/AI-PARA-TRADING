"""Application service for full market intelligence with MAXIMO Quant v4."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.maximo_quant_v4_market_intelligence import MaximoQuantV4MarketIntelligenceEngine


class MaximoQuantV4MarketIntelligenceApplicationService:
    """Generate a full market intelligence report from live MT5 data and learned knowledge."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, *, symbol: str) -> dict:
        return MaximoQuantV4MarketIntelligenceEngine(self.settings).run(symbol=symbol)
