"""Application service for MAXIMO Quant v4 new-candle dry validation."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.maximo_quant_v4_new_candle_validation import MaximoQuantV4NewCandleValidationMonitor


class MaximoQuantV4NewCandleValidationApplicationService:
    """Run dry validation only on newly closed M5 candles."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(
        self,
        *,
        symbol: str,
        target_unique_candles: int = 50,
        max_attempts: int = 5_000,
        poll_seconds: float = 10.0,
        session_label: str = "manual",
    ) -> dict:
        return MaximoQuantV4NewCandleValidationMonitor(self.settings).run(
            symbol=symbol,
            target_unique_candles=target_unique_candles,
            max_attempts=max_attempts,
            poll_seconds=poll_seconds,
            session_label=session_label,
        )
