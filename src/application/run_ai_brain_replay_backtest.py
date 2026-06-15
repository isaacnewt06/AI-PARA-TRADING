"""Application service for full MAXIMO AI brain historical replay."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.core.config import Settings
from src.trading.ai_brain_replay_backtester import AIBrainReplayBacktester


class AIBrainReplayBacktestApplicationService:
    """Run MAXIMO's full decision stack over historical candles."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(
        self,
        *,
        symbol: str,
        year: int,
        initial_capital: float,
        max_cycles: int,
        step_bars: int,
        start_date: date | None = None,
        end_date: date | None = None,
        anchor_trades_csv: Path | None = None,
    ) -> dict:
        return AIBrainReplayBacktester(self.settings).run(
            symbol=symbol,
            year=year,
            initial_capital=initial_capital,
            max_cycles=max_cycles,
            step_bars=step_bars,
            start_date=start_date,
            end_date=end_date,
            anchor_trades_csv=anchor_trades_csv,
        )
