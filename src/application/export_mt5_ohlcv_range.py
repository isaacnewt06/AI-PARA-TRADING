"""Application service for exporting MT5 OHLCV within a UTC date range."""

from __future__ import annotations

from datetime import date

from src.core.config import Settings
from src.trading.mt5_bridge import MT5Bridge


class MT5OHLCVRangeExportApplicationService:
    """Export broker OHLCV from MT5 into year/range-specific CSV files."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, *, symbol: str, from_date: date, to_date: date) -> dict:
        backtests_input = self.settings.paths.data_dir / "backtests" / "input"
        backtests_input.mkdir(parents=True, exist_ok=True)
        bridge = MT5Bridge(self.settings)
        return bridge.export_ohlcv_range(symbol=symbol, output_dir=backtests_input, from_date=from_date, to_date=to_date)
