"""Application service for formal blueprint-driven backtesting."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.blueprint_backtester import BlueprintBacktester


class BlueprintBacktestRunApplicationService:
    """Run blueprint specs against CSV OHLCV inputs."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self) -> dict:
        backtests_root = self.settings.paths.data_dir / "backtests"
        input_dir = backtests_root / "input"
        results_dir = backtests_root / "results"
        reports_dir = backtests_root / "reports"
        specs_dir = backtests_root / "specs"
        for path in (input_dir, results_dir, reports_dir, specs_dir):
            path.mkdir(parents=True, exist_ok=True)
        return BlueprintBacktester(input_dir, results_dir, reports_dir).run_specs(specs_dir)
