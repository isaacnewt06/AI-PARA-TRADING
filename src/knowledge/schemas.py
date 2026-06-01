"""Pydantic schemas for the knowledge pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChunkPayload(BaseModel):
    """Payload ready to be stored as a content chunk."""

    source_id: int
    source_type: str
    channel_id: int | None = None
    message_id: int | None = None
    file_id: int | None = None
    file_name: str | None = None
    original_date: datetime | None = None
    chunk_index: int
    text: str
    clean_text: str
    metadata_json: str | None = None


class QueryResult(BaseModel):
    """Knowledge query response."""

    chunk_id: int
    source_type: str
    text: str
    score: float


class HybridQueryFilters(BaseModel):
    """Structured filters for hybrid knowledge retrieval."""

    topic: str | None = None
    author: str | None = None
    channel: str | None = None
    strategy: str | None = None
    concept: str | None = None
    limit: int = 5


class HybridQueryResult(BaseModel):
    """Ranked result for keyword + semantic retrieval."""

    chunk_id: int
    source_type: str
    channel_name: str | None = None
    author_name: str | None = None
    strategy_key: str | None = None
    concepts: list[str] = Field(default_factory=list)
    excerpt: str
    keyword_score: float
    semantic_score: float
    combined_score: float


class StructuredRuleSchema(BaseModel):
    """Structured trading rule extracted from a chunk."""

    source_chunk_id: int
    channel_id: int | None = None
    rule_type: Literal["signal", "educational", "market_context", "risk", "setup"] = "educational"
    rule_text: str
    source_type: str | None = None
    source_reference: str | None = None
    channel_name: str | None = None
    author_name: str | None = None
    asset: str | None = None
    timeframe: str | None = None
    direction: str | None = None
    context: str | None = None
    entry_condition: str | None = None
    confirmation: str | None = None
    stop_loss: str | None = None
    take_profit: str | None = None
    risk_management: str | None = None
    session_filter: str | None = None
    observations: str | None = None
    concepts_json: str | None = None
    strategy_key: str | None = None
    normalized_signature: str | None = None
    cluster_key: str | None = None
    module_name: str | None = None
    source_file_name: str | None = None
    example_snippet: str | None = None
    confidence: float | None = None


class AuthorComparisonSchema(BaseModel):
    """Comparison between two authors."""

    author_a: str
    author_b: str
    total_rules_a: int
    total_rules_b: int
    top_assets_a: list[str]
    top_assets_b: list[str]
    top_concepts_a: list[str]
    top_concepts_b: list[str]
    sessions_a: list[str]
    sessions_b: list[str]
    notes: str
