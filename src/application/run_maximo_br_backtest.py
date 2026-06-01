"""Application service for MAXIMO B&R PRO v2.0 1.3R backtests."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.maximo_br_backtester import MaximoBRProBacktester


class MaximoBRBacktestApplicationService:
    """Run the dedicated MAXIMO B&R PRO v2.0 1.3R research backtest."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, *, symbol: str) -> dict:
        backtester = MaximoBRProBacktester(
            input_dir=self.settings.paths.data_dir / "backtests" / "input",
            output_dir=self.settings.paths.data_dir / "backtests" / "maximo_br_pro_v2_0",
        )
        return backtester.run(symbol=symbol)
