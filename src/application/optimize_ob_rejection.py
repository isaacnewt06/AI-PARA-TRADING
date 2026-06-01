"""Application service for quantitative OB Rejection optimization."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.annual_strategy_optimizer import AnnualOBRejectionOptimizer


class OBRejectionOptimizationApplicationService:
    """Run controlled annual optimization over OB Rejection Short Only Trailing ATR."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self) -> dict:
        return AnnualOBRejectionOptimizer(self.settings).run()
