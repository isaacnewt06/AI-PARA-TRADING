"""Knowledge-oriented models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin


class ContentChunk(TimestampMixin, Base):
    """Chunked text ready for retrieval and embeddings."""

    __tablename__ = "content_chunks"
    __table_args__ = (Index("ix_chunks_source", "source_type", "source_id", "chunk_index", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(nullable=False)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_messages.id"), nullable=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    clean_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    quality_score: Mapped[float | None] = mapped_column(nullable=True)
    source_weight: Mapped[float | None] = mapped_column(nullable=True)
    usefulness_score: Mapped[float | None] = mapped_column(nullable=True)
    quality_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quality_flags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    filtered_out: Mapped[bool] = mapped_column(default=False, nullable=False)


class Tag(TimestampMixin, Base):
    """Controlled vocabulary for future enrichment."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExtractedRule(TimestampMixin, Base):
    """Trading rule extracted from knowledge content."""

    __tablename__ = "extracted_rules"
    __table_args__ = (
        Index("ix_rules_chunk_signature", "source_chunk_id", "normalized_signature"),
        Index("ix_rules_strategy_author", "strategy_key", "author_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_chunk_id: Mapped[int | None] = mapped_column(ForeignKey("content_chunks.id"), nullable=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(32), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_loss: Mapped[str | None] = mapped_column(Text, nullable=True)
    take_profit: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_management: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    concepts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategy_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cluster_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    module_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    example_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)


class StrategyPlaybook(TimestampMixin, Base):
    """Materialized playbooks from extracted knowledge."""

    __tablename__ = "strategy_playbooks"
    __table_args__ = (Index("ix_playbooks_strategy", "strategy_key", "author_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    concepts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)


class ChunkEmbedding(TimestampMixin, Base):
    """Local vector representation for a content chunk."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        Index("ix_chunk_embeddings_provider", "provider"),
        Index("ix_chunk_embeddings_chunk_provider", "chunk_id", "provider", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("content_chunks.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_json: Mapped[str] = mapped_column(Text, nullable=False)
    vector_norm: Mapped[float] = mapped_column(nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuleCluster(TimestampMixin, Base):
    """Group similar rules into reusable strategy clusters."""

    __tablename__ = "rule_clusters"
    __table_args__ = (Index("ix_rule_clusters_key", "cluster_key", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_key: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(32), nullable=True)
    concept: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)


class CourseModuleSummary(TimestampMixin, Base):
    """Module-level summary for courses or long documents."""

    __tablename__ = "course_module_summaries"
    __table_args__ = (
        Index("ix_course_module_unique", "source_type", "source_id", "module_key", unique=True),
        Index("ix_course_module_course", "course_name", "author_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(nullable=False)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    course_name: Mapped[str] = mapped_column(String(255), nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    module_key: Mapped[str] = mapped_column(String(255), nullable=False)
    module_title: Mapped[str] = mapped_column(String(255), nullable=False)
    module_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_concepts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class BacktestDatasetRow(TimestampMixin, Base):
    """Structured rule row ready to become a backtesting dataset."""

    __tablename__ = "backtest_dataset_rows"
    __table_args__ = (
        Index("ix_backtest_dataset_strategy", "strategy_key", "dataset_version"),
        Index("ix_backtest_dataset_rule", "extracted_rule_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    extracted_rule_id: Mapped[int] = mapped_column(ForeignKey("extracted_rules.id"), nullable=False)
    source_chunk_id: Mapped[int | None] = mapped_column(ForeignKey("content_chunks.id"), nullable=True)
    strategy_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cluster_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(32), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_loss: Mapped[str | None] = mapped_column(Text, nullable=True)
    take_profit: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_management: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    concepts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    ready_for_backtest: Mapped[bool] = mapped_column(default=True, nullable=False)


class NormalizedRule(TimestampMixin, Base):
    """Operational normalized rule derived from extracted knowledge."""

    __tablename__ = "normalized_rules"
    __table_args__ = (
        Index("ix_normalized_rules_strategy", "strategy_family", "setup_name"),
        Index("ix_normalized_rules_source", "extracted_rule_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    extracted_rule_id: Mapped[int] = mapped_column(ForeignKey("extracted_rules.id"), nullable=False)
    strategy_family: Mapped[str] = mapped_column(String(128), nullable=False)
    setup_name: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_timeframes: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_timeframes: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_filters: Mapped[str | None] = mapped_column(Text, nullable=True)
    direction_bias: Mapped[str | None] = mapped_column(String(32), nullable=True)
    concept_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    take_profit_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rr_min: Mapped[float | None] = mapped_column(nullable=True)
    rr_target: Mapped[float | None] = mapped_column(nullable=True)
    risk_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    risk_percent: Mapped[float | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(nullable=True)
    normalization_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    traceability_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuantifiableCondition(TimestampMixin, Base):
    """Measurable proxy condition mapped from a normalized rule."""

    __tablename__ = "quantifiable_conditions"
    __table_args__ = (
        Index("ix_quant_conditions_rule", "normalized_rule_id"),
        Index("ix_quant_conditions_key", "condition_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_rule_id: Mapped[int] = mapped_column(ForeignKey("normalized_rules.id"), nullable=False)
    condition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    condition_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_function: Mapped[str] = mapped_column(String(128), nullable=False)
    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(32), nullable=True)
    threshold: Mapped[float | None] = mapped_column(nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required: Mapped[bool] = mapped_column(default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class StrategyCandidate(TimestampMixin, Base):
    """Compiled strategy candidate built from normalized rules."""

    __tablename__ = "strategy_candidates"
    __table_args__ = (
        Index("ix_strategy_candidates_setup", "setup_name", "strategy_family"),
        Index("ix_strategy_candidates_key", "candidate_key", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_key: Mapped[str] = mapped_column(String(255), nullable=False)
    setup_name: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_family: Mapped[str] = mapped_column(String(128), nullable=False)
    symbols_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_tf_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_tf_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_sessions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    optional_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidation_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_logic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sl_logic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tp_logic_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rr_constraints_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_constraints_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_traceability_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    coherence_score: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="candidate", nullable=False)


class CandidateComponent(TimestampMixin, Base):
    """Component rows that explain how a strategy candidate was assembled."""

    __tablename__ = "candidate_components"
    __table_args__ = (Index("ix_candidate_components_candidate", "strategy_candidate_id", "component_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_candidate_id: Mapped[int] = mapped_column(ForeignKey("strategy_candidates.id"), nullable=False)
    normalized_rule_id: Mapped[int | None] = mapped_column(ForeignKey("normalized_rules.id"), nullable=True)
    component_type: Mapped[str] = mapped_column(String(64), nullable=False)
    component_key: Mapped[str] = mapped_column(String(128), nullable=False)
    component_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(default=1.0, nullable=False)


class RuleQualityScore(TimestampMixin, Base):
    """Quality score for normalized or extracted rules."""

    __tablename__ = "rule_quality_scores"
    __table_args__ = (Index("ix_rule_quality_normalized", "normalized_rule_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_rule_id: Mapped[int] = mapped_column(ForeignKey("normalized_rules.id"), nullable=False)
    clarity_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    completeness_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    quantifiability_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    contradiction_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    multi_source_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    multi_author_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    semantic_repetition_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    total_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SetupQualityScore(TimestampMixin, Base):
    """Quality score for compiled strategy setups."""

    __tablename__ = "setup_quality_scores"
    __table_args__ = (Index("ix_setup_quality_candidate", "strategy_candidate_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_candidate_id: Mapped[int] = mapped_column(ForeignKey("strategy_candidates.id"), nullable=False)
    coherence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    completeness_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    quantifiability_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    traceability_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    risk_defined_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    contradiction_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    total_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class TopStrategyDetected(TimestampMixin, Base):
    """Materialized ranking of the strongest repeated strategies detected in the knowledge base."""

    __tablename__ = "top_strategies_detected"
    __table_args__ = (
        Index("ix_top_strategies_detected_key", "strategy_key", unique=True),
        Index("ix_top_strategies_detected_score", "relevance_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_family: Mapped[str | None] = mapped_column(String(128), nullable=True)
    concepts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    assets_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeframes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sessions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_types_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_setup_names_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    author_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    channel_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rule_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completeness_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    frequency_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    source_diversity_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    execution_definition_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    relevance_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="detected", nullable=False)
