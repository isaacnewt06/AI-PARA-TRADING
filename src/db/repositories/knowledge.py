"""Repositories for phase 2 semantic and rule entities."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.db.models.document import Document
from src.db.models.knowledge import (
    BacktestDatasetRow,
    CandidateComponent,
    ChunkEmbedding,
    ContentChunk,
    CourseModuleSummary,
    ExtractedRule,
    NormalizedRule,
    QuantifiableCondition,
    RuleQualityScore,
    RuleCluster,
    SetupQualityScore,
    StrategyCandidate,
    StrategyPlaybook,
)


class ContentChunkRepository:
    """Access content chunks for semantic indexing and retrieval."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[ContentChunk]:
        return list(self.session.scalars(select(ContentChunk).order_by(ContentChunk.id.asc())))

    def list_quality_eligible(self) -> list[ContentChunk]:
        stmt = select(ContentChunk).where(ContentChunk.filtered_out.is_(False)).order_by(ContentChunk.id.asc())
        return list(self.session.scalars(stmt))

    def list_pending_embeddings(self, provider: str) -> list[ContentChunk]:
        stmt = select(ContentChunk).where(
            ContentChunk.filtered_out.is_(False),
            (ContentChunk.embedding_status != "indexed") | (ContentChunk.embedding_provider != provider),
        ).order_by(ContentChunk.id.asc())
        return list(self.session.scalars(stmt))


class ChunkEmbeddingRepository:
    """Persistence helpers for chunk embeddings."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_chunk_and_provider(self, chunk_id: int, provider: str) -> ChunkEmbedding | None:
        stmt = select(ChunkEmbedding).where(
            ChunkEmbedding.chunk_id == chunk_id,
            ChunkEmbedding.provider == provider,
        )
        return self.session.scalar(stmt)

    def upsert(self, *, chunk_id: int, provider: str, dimension: int, vector_json: str, vector_norm: float) -> None:
        row = self.get_by_chunk_and_provider(chunk_id, provider)
        if row is None:
            row = ChunkEmbedding(
                chunk_id=chunk_id,
                provider=provider,
                dimension=dimension,
                vector_json=vector_json,
                vector_norm=vector_norm,
                indexed_at=datetime.now(timezone.utc),
            )
            self.session.add(row)
        else:
            row.dimension = dimension
            row.vector_json = vector_json
            row.vector_norm = vector_norm
            row.indexed_at = datetime.now(timezone.utc)
            self.session.add(row)
        self.session.flush()

    def list_by_provider(self, provider: str) -> list[ChunkEmbedding]:
        stmt = select(ChunkEmbedding).where(ChunkEmbedding.provider == provider).order_by(ChunkEmbedding.chunk_id.asc())
        return list(self.session.scalars(stmt))


class RuleRepository:
    """Persistence helpers for extracted rules and clusters."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def delete_for_chunk(self, chunk_id: int) -> None:
        rule_ids = list(
            self.session.scalars(select(ExtractedRule.id).where(ExtractedRule.source_chunk_id == chunk_id))
        )
        if not rule_ids:
            return
        normalized_rule_ids = list(
            self.session.scalars(select(NormalizedRule.id).where(NormalizedRule.extracted_rule_id.in_(rule_ids)))
        )
        if normalized_rule_ids:
            # Compiled candidates are materialized from normalized rules; any source rule refresh invalidates them.
            self.session.execute(delete(SetupQualityScore))
            self.session.execute(delete(CandidateComponent))
            self.session.execute(delete(StrategyCandidate))
            self.session.execute(
                delete(QuantifiableCondition).where(QuantifiableCondition.normalized_rule_id.in_(normalized_rule_ids))
            )
            self.session.execute(
                delete(RuleQualityScore).where(RuleQualityScore.normalized_rule_id.in_(normalized_rule_ids))
            )
            self.session.execute(delete(NormalizedRule).where(NormalizedRule.id.in_(normalized_rule_ids)))
        self.session.execute(delete(BacktestDatasetRow).where(BacktestDatasetRow.extracted_rule_id.in_(rule_ids)))
        self.session.execute(delete(ExtractedRule).where(ExtractedRule.source_chunk_id == chunk_id))
        self.session.flush()

    def create_rule(self, payload: dict) -> ExtractedRule:
        row = ExtractedRule(**payload)
        self.session.add(row)
        self.session.flush()
        return row

    def list_rules(self) -> list[ExtractedRule]:
        return list(self.session.scalars(select(ExtractedRule).order_by(ExtractedRule.id.asc())))

    def list_rules_by_author(self, author_name: str) -> list[ExtractedRule]:
        stmt = select(ExtractedRule).where(ExtractedRule.author_name == author_name).order_by(ExtractedRule.id.asc())
        return list(self.session.scalars(stmt))

    def replace_clusters(self, clusters: list[dict]) -> int:
        self.session.execute(delete(RuleCluster))
        for payload in clusters:
            self.session.add(RuleCluster(**payload))
        self.session.flush()
        return len(clusters)

    def list_clusters(self) -> list[RuleCluster]:
        return list(self.session.scalars(select(RuleCluster).order_by(RuleCluster.member_count.desc(), RuleCluster.id.asc())))


class PlaybookRepository:
    """Persistence helpers for generated playbooks."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_playbooks(self, payloads: list[dict]) -> int:
        self.session.execute(delete(StrategyPlaybook))
        for payload in payloads:
            self.session.add(StrategyPlaybook(**payload))
        self.session.flush()
        return len(payloads)

    def list_playbooks(self) -> list[StrategyPlaybook]:
        return list(self.session.scalars(select(StrategyPlaybook).order_by(StrategyPlaybook.rules_count.desc())))


class CourseSummaryRepository:
    """Persistence helpers for course module summaries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_source(self, source_type: str, source_id: int, payloads: list[dict]) -> int:
        self.session.execute(
            delete(CourseModuleSummary).where(
                CourseModuleSummary.source_type == source_type,
                CourseModuleSummary.source_id == source_id,
            )
        )
        for payload in payloads:
            self.session.add(CourseModuleSummary(**payload))
        self.session.flush()
        return len(payloads)

    def list_for_course(self, course_name: str) -> list[CourseModuleSummary]:
        stmt = select(CourseModuleSummary).where(CourseModuleSummary.course_name == course_name).order_by(
            CourseModuleSummary.module_order.asc()
        )
        return list(self.session.scalars(stmt))

    def list_all(self) -> list[CourseModuleSummary]:
        return list(
            self.session.scalars(
                select(CourseModuleSummary).order_by(
                    CourseModuleSummary.course_name.asc(),
                    CourseModuleSummary.module_order.asc(),
                )
            )
        )


class BacktestDatasetRepository:
    """Persistence helpers for exported backtest rows."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_rows(self, payloads: list[dict]) -> int:
        self.session.execute(delete(BacktestDatasetRow))
        for payload in payloads:
            self.session.add(BacktestDatasetRow(**payload))
        self.session.flush()
        return len(payloads)

    def list_rows(self) -> list[BacktestDatasetRow]:
        return list(self.session.scalars(select(BacktestDatasetRow).order_by(BacktestDatasetRow.id.asc())))


class DocumentSummaryRepository:
    """Read access to processed documents for course summaries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_processed_documents(self) -> list[Document]:
        stmt = select(Document).where(Document.extracted_text.is_not(None)).order_by(Document.id.asc())
        return list(self.session.scalars(stmt))
