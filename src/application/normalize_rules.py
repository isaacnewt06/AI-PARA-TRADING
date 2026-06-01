"""Application service for phase 3 rule normalization."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.normalization import RuleNormalizationService
from src.knowledge.quantification import QuantificationService


class RuleNormalizationApplicationService:
    """Normalize extracted rules and create quantifiable conditions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self) -> dict:
        normalized = RuleNormalizationService(self.session).run()
        quantified = QuantificationService(self.session).run()
        return {**normalized, **quantified}
