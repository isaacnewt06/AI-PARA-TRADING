"""Application service for controlled annual optimization of MAXIMO Quant v4."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.maximo_quant_v4_optimizer import MaximoQuantV4Optimizer


class MaximoQuantV4OptimizationApplicationService:
    """Run controlled annual optimization for MAXIMO MTF Quant Institutional v4."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, symbol: str = "XAUUSDm") -> dict:
        optimizer = MaximoQuantV4Optimizer(
            input_dir=self.settings.paths.data_dir / "backtests" / "input",
            backtests_dir=self.settings.paths.data_dir / "backtests",
            strategies_dir=self.settings.paths.data_dir / "strategies",
        )
        return optimizer.run(symbol=symbol)
