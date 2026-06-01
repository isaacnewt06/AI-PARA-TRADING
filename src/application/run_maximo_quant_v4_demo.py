"""Application service for controlled MT5 demo execution of MAXIMO Quant v4."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.maximo_quant_v4_demo_engine import MaximoQuantV4DemoEngine


class MaximoQuantV4DemoApplicationService:
    """Run the current best MAXIMO Quant v4 candidate on a demo-only MT5 account."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(
        self,
        *,
        symbol: str,
        volume_lots: float = 0.01,
        deviation_points: int = 50,
        dry_run: bool = True,
        confirm_demo: bool = False,
    ) -> dict:
        return MaximoQuantV4DemoEngine(self.settings).run(
            symbol=symbol,
            volume_lots=volume_lots,
            deviation_points=deviation_points,
            dry_run=dry_run,
            confirm_demo=confirm_demo,
        )
