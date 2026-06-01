"""Course and document summarization by modules."""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.document import Document
from src.db.repositories.knowledge import CourseSummaryRepository, DocumentSummaryRepository
from src.knowledge.patterns import CONCEPT_PATTERNS

logger = get_logger(__name__)


class CourseSummarizerService:
    """Build module-level summaries from processed documents."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.document_repository = DocumentSummaryRepository(session)
        self.summary_repository = CourseSummaryRepository(session)

    def run(self) -> int:
        total = 0
        for document in self.document_repository.list_processed_documents():
            total += self._summarize_document(document)
        logger.info("Built %s course module summaries", total)
        return total

    def summarize_course(self, course_name: str) -> list[dict]:
        summaries = self.summary_repository.list_for_course(course_name)
        return [
            {
                "module_title": row.module_title,
                "module_order": row.module_order,
                "summary": row.summary,
                "concepts": json.loads(row.key_concepts_json) if row.key_concepts_json else [],
            }
            for row in summaries
        ]

    def _summarize_document(self, document: Document) -> int:
        sections = json.loads(document.section_index_json) if document.section_index_json else []
        if not sections:
            sections = [{"position": 0, "title": "Module 1"}]

        lines = [line.strip() for line in (document.extracted_text or "").splitlines() if line.strip()]
        payloads = []
        for index, section in enumerate(sections):
            start = section["position"]
            end = sections[index + 1]["position"] if index + 1 < len(sections) else len(lines)
            block = " ".join(lines[start:end]).strip()
            if not block:
                continue
            concepts = self._concepts(block)
            payloads.append(
                {
                    "source_type": "document",
                    "source_id": document.id,
                    "channel_id": document.file.channel_id if document.file else None,
                    "course_name": document.file.file_name if document.file else f"document_{document.id}",
                    "author_name": document.file.channel.title if document.file and document.file.channel else None,
                    "module_key": f"document_{document.id}_module_{index}",
                    "module_title": section["title"],
                    "module_order": index,
                    "summary": self._summary(block),
                    "key_concepts_json": json.dumps(concepts, ensure_ascii=False),
                    "source_file_name": document.file.file_name if document.file else None,
                }
            )
        return self.summary_repository.replace_for_source("document", document.id, payloads)

    @staticmethod
    def _summary(text: str) -> str:
        sentences = [segment.strip() for segment in text.split(".") if segment.strip()]
        return ". ".join(sentences[:4])[:700]

    @staticmethod
    def _concepts(text: str) -> list[str]:
        counts = Counter(name for name, pattern in CONCEPT_PATTERNS.items() if pattern.search(text))
        return [name for name, _ in counts.most_common(6)]
