"""Application service for compiling strategy setups."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.trading.strategy_builder import StrategyBuilder


class SetupCompilationApplicationService:
    """Compile normalized rules into strategy candidates."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self, score: bool = True) -> dict:
        return StrategyBuilder(self.session).build(score=score)
