"""Application service for comparing authors and courses."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.comparison import KnowledgeComparisonService


class KnowledgeComparisonApplicationService:
    """Compare phase 2 semantic outputs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def compare_authors(self, author_a: str, author_b: str):
        return KnowledgeComparisonService(self.session).compare_authors(author_a, author_b)

    def compare_courses(self, course_a: str, course_b: str):
        return KnowledgeComparisonService(self.session).compare_courses(course_a, course_b)
