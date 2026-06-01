"""Application service for knowledge queries."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.knowledge.hybrid_retrieval import HybridRetrievalService
from src.knowledge.retrieval import KnowledgeRetrievalService
from src.knowledge.schemas import HybridQueryFilters


class KnowledgeQueryApplicationService:
    """Facade for knowledge retrieval."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    def run(self, question: str, limit: int = 5):
        return KnowledgeRetrievalService(self.session).query(question, limit=limit)

    def semantic(
        self,
        question: str,
        *,
        topic: str | None = None,
        author: str | None = None,
        channel: str | None = None,
        strategy: str | None = None,
        concept: str | None = None,
        limit: int = 5,
    ):
        if self.settings is None:
            raise ValueError("Settings are required for semantic retrieval")
        filters = HybridQueryFilters(
            topic=topic,
            author=author,
            channel=channel,
            strategy=strategy,
            concept=concept,
            limit=limit,
        )
        return HybridRetrievalService(self.session, self.settings).query(question, filters)
