"""Materialize executable strategy blueprints from detected strategies."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.blueprint_builder import StrategyBlueprintBuilder


class ExecutableStrategyGenerationApplicationService:
    """Generate executable strategy artifacts on disk."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self, output_dir: str | None = None, prioritize_family: str = "OB Rejection") -> dict:
        target = Path(output_dir) if output_dir else self.settings.paths.knowledge_dir / "strategy_blueprints"
        return StrategyBlueprintBuilder(self.session).export(target, prioritize_family=prioritize_family)
