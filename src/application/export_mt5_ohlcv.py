"""Application service for exporting MT5 historical OHLCV."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.mt5_bridge import MT5Bridge


class MT5OHLCVExportApplicationService:
    """Export broker OHLCV from MT5 into local CSV files for backtesting."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, *, symbol: str, bars: int) -> dict:
        backtests_input = self.settings.paths.data_dir / "backtests" / "input"
        backtests_input.mkdir(parents=True, exist_ok=True)
        bridge = MT5Bridge(self.settings)
        return bridge.export_ohlcv(symbol=symbol, output_dir=backtests_input, bars=bars)
