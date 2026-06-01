"""Application service for structured trading rule extraction."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.rule_extractor import RuleClusterService, RuleExtractorService


class TradingRuleExtractionApplicationService:
    """Extract and cluster structured trading rules."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self) -> dict:
        rules_created = RuleExtractorService(self.session).run()
        clusters_created = RuleClusterService(self.session).run()
        return {"rules_created": rules_created, "clusters_created": clusters_created}
