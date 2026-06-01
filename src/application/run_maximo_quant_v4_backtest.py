"""Application service for MAXIMO MTF Quant Institutional v4 backtests."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester


class MaximoQuantV4BacktestApplicationService:
    """Run the dedicated TradingView-derived MAXIMO Quant v4 research backtest."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, *, symbol: str) -> dict:
        backtester = MaximoMTFQuantV4Backtester(
            input_dir=self.settings.paths.data_dir / "backtests" / "input",
            output_dir=self.settings.paths.data_dir / "backtests" / "maximo_mtf_quant_v4",
        )
        return backtester.run(symbol=symbol)
