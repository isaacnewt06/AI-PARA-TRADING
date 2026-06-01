"""Application service to build the initial knowledge base."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.application.extract_trading_rules import TradingRuleExtractionApplicationService
from src.application.filter_content import ContentFilteringApplicationService
from src.application.generate_playbooks import PlaybookGenerationApplicationService
from src.knowledge.builders import KnowledgeBaseBuilder


class KnowledgeBuildApplicationService:
    """Coordinate chunk creation and future enrichment hooks."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self, filtered: bool = False) -> dict:
        chunk_builder = KnowledgeBaseBuilder(self.session, self.settings)
        chunks_created = chunk_builder.build()
        filter_summary = (
            ContentFilteringApplicationService(self.session).run()
            if filtered
            else {"chunks_scored": 0, "chunks_kept": 0, "chunks_filtered": 0, "duplicates": 0}
        )
        rule_summary = TradingRuleExtractionApplicationService(self.session).run()
        playbook_summary = PlaybookGenerationApplicationService(self.session).run()
        return {
            "chunks_created": chunks_created,
            "chunks_scored": filter_summary["chunks_scored"],
            "chunks_kept": filter_summary["chunks_kept"],
            "chunks_filtered": filter_summary["chunks_filtered"],
            "duplicates": filter_summary["duplicates"],
            "rules_created": rule_summary["rules_created"],
            "clusters_created": rule_summary["clusters_created"],
            "playbooks_created": playbook_summary["playbooks_created"],
        }
