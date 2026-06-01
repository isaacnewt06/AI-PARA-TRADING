"""Application service for rule/setup scoring."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.quality_scoring import QualityScoringService


class QualityScoringApplicationService:
    """Score normalized rules and compiled setups."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self) -> dict:
        return QualityScoringService(self.session).run()
