"""Keyword retrieval over the knowledge base."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models.knowledge import ContentChunk
from src.knowledge.schemas import QueryResult


class KnowledgeRetrievalService:
    """Simple LIKE-based retrieval until embeddings are added."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def query(self, question: str, limit: int = 5) -> list[QueryResult]:
        like_pattern = f"%{question.lower()}%"
        stmt = (
            select(ContentChunk)
            .where(func.lower(ContentChunk.clean_text).like(like_pattern))
            .order_by(ContentChunk.id.desc())
            .limit(limit)
        )
        results = list(self.session.scalars(stmt))
        return [
            QueryResult(chunk_id=row.id, source_type=row.source_type, text=row.text, score=1.0)
            for row in results
        ]
