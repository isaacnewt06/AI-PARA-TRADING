"""Application service for yearly fixed-lot analysis of MAXIMO Quant v4."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.maximo_quant_v4_yearly_analyzer import MaximoQuantV4YearlyAnalyzer


class MaximoQuantV4YearlyAnalysisApplicationService:
    """Run 2025-style fixed-lot weekly/monthly/yearly analysis for MAXIMO Quant v4."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(
        self,
        *,
        symbol: str,
        year: int,
        initial_capital: float,
        volume_lots: float,
        strategy_variant: str = MaximoQuantV4YearlyAnalyzer.DEFAULT_VARIANT,
        session_variant: str = MaximoQuantV4YearlyAnalyzer.DEFAULT_SESSION,
        timeframe: str = MaximoQuantV4YearlyAnalyzer.DEFAULT_TIMEFRAME,
    ) -> dict:
        analyzer = MaximoQuantV4YearlyAnalyzer(
            input_dir=self.settings.paths.data_dir / "backtests" / "input",
            backtests_dir=self.settings.paths.data_dir / "backtests",
            strategies_dir=self.settings.paths.data_dir / "strategies",
        )
        return analyzer.run(
            symbol=symbol,
            year=year,
            initial_capital=initial_capital,
            volume_lots=volume_lots,
            strategy_variant_code=strategy_variant,
            session_variant_code=session_variant,
            timeframe=timeframe,
        )
