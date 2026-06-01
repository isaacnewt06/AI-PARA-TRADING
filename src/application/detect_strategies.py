"""Application service for detected strategy patterns."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.strategy_pattern_detector import StrategyPatternDetectorService


class StrategyDetectionApplicationService:
    """Detect, rank and inspect repeated strategies inside extracted channel knowledge."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.service = StrategyPatternDetectorService(session)

    def run(self) -> dict[str, int]:
        return self.service.run()

    def rank(self, limit: int = 20) -> list[dict]:
        return [item.model_dump() for item in self.service.rank(limit=limit)]

    def inspect(self, name_or_key: str) -> dict | None:
        result = self.service.inspect(name_or_key)
        return result.model_dump() if result is not None else None
