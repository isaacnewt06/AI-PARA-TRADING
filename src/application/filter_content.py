"""Application service for content quality filtering."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.content_quality import ContentQualityFilter


class ContentFilteringApplicationService:
    """Run quality scoring and filtering for content chunks."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self) -> dict[str, int]:
        return ContentQualityFilter(self.session).run()
