"""Application service for course/module summaries."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.course_summarizer import CourseSummarizerService


class CourseSummaryApplicationService:
    """Create and inspect module summaries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def build(self) -> dict:
        modules_created = CourseSummarizerService(self.session).run()
        return {"modules_created": modules_created}

    def summarize_course(self, course_name: str) -> list[dict]:
        return CourseSummarizerService(self.session).summarize_course(course_name)
