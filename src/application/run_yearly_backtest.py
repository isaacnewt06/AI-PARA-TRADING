"""Application service for annual capital-based backtesting."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.yearly_backtester import YearlyBacktester


class YearlyBacktestApplicationService:
    """Run the approved strategy over a full historical year with capital simulation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, *, symbol: str, year: int, initial_capital: float) -> dict:
        backtests_root = self.settings.paths.data_dir / "backtests"
        input_dir = backtests_root / "input"
        yearly_dir = backtests_root / "yearly"
        input_dir.mkdir(parents=True, exist_ok=True)
        yearly_dir.mkdir(parents=True, exist_ok=True)
        return YearlyBacktester(
            input_dir=input_dir,
            yearly_dir=yearly_dir,
            strategies_dir=self.settings.paths.data_dir / "strategies",
        ).run(settings=self.settings, symbol=symbol, year=year, initial_capital=initial_capital)
