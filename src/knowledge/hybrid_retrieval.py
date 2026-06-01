"""Hybrid keyword + semantic retrieval over the knowledge base."""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.db.models.channel import Channel
from src.db.models.knowledge import ChunkEmbedding, ContentChunk, ExtractedRule
from src.knowledge.embeddings import LocalHashEmbeddingClient, cosine_similarity, normalize_tokens
from src.knowledge.schemas import HybridQueryFilters, HybridQueryResult


class HybridRetrievalService:
    """Run filtered hybrid retrieval using keyword overlap and local embeddings."""

    def __init__(self, session: Session, settings: Settings, embedding_client: LocalHashEmbeddingClient | None = None) -> None:
        self.session = session
        self.settings = settings
        self.embedding_client = embedding_client or LocalHashEmbeddingClient(
            dimension=getattr(settings.tuning, "embedding_dimension", 256)
        )

    def query(self, question: str, filters: HybridQueryFilters | None = None) -> list[HybridQueryResult]:
        filters = filters or HybridQueryFilters()
        chunk_rows = self._candidate_chunks(question, filters)
        if not chunk_rows:
            return []

        query_vector = self.embedding_client.embed([question])[0]
        query_tokens = Counter(normalize_tokens(question))
        best_results: dict[int, HybridQueryResult] = {}
        for chunk, channel_name, author_name, strategy_key, concepts_json, vector in chunk_rows:
            chunk_tokens = Counter(normalize_tokens(chunk.clean_text))
            keyword_score = self._keyword_score(query_tokens, chunk_tokens, chunk.clean_text, question)
            semantic_score = cosine_similarity(query_vector, vector)
            combined_score = (keyword_score * 0.45) + (semantic_score * 0.55)
            result = HybridQueryResult(
                chunk_id=chunk.id,
                source_type=chunk.source_type,
                channel_name=channel_name,
                author_name=author_name,
                strategy_key=strategy_key,
                concepts=json.loads(concepts_json) if concepts_json else [],
                excerpt=chunk.text[:320],
                keyword_score=round(keyword_score, 6),
                semantic_score=round(semantic_score, 6),
                combined_score=round(combined_score, 6),
            )
            current = best_results.get(chunk.id)
            if current is None or result.combined_score > current.combined_score:
                best_results[chunk.id] = result

        results = list(best_results.values())
        results.sort(key=lambda row: row.combined_score, reverse=True)
        return results[: filters.limit]

    def _candidate_chunks(
        self,
        question: str,
        filters: HybridQueryFilters,
    ) -> list[tuple[ContentChunk, str | None, str | None, str | None, str | None, list[float]]]:
        stmt = (
            select(
                ContentChunk,
                Channel.title,
                ExtractedRule.author_name,
                ExtractedRule.strategy_key,
                ExtractedRule.concepts_json,
                ChunkEmbedding.vector_json,
            )
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == ContentChunk.id)
            .outerjoin(Channel, Channel.id == ContentChunk.channel_id)
            .outerjoin(ExtractedRule, ExtractedRule.source_chunk_id == ContentChunk.id)
            .where(ChunkEmbedding.provider == self.embedding_client.provider_name)
            .order_by(ContentChunk.id.desc())
            .limit(getattr(self.settings.tuning, "semantic_candidate_limit", 300))
        )

        if filters.channel:
            like = f"%{filters.channel.lower()}%"
            stmt = stmt.where(or_(Channel.title.ilike(like), Channel.normalized_name.ilike(like)))
        if filters.author:
            stmt = stmt.where(ExtractedRule.author_name.ilike(f"%{filters.author.lower()}%"))
        if filters.strategy:
            stmt = stmt.where(ExtractedRule.strategy_key.ilike(f"%{filters.strategy.lower()}%"))
        if filters.concept:
            stmt = stmt.where(
                or_(
                    ExtractedRule.concepts_json.ilike(f"%{filters.concept.lower()}%"),
                    ContentChunk.metadata_json.ilike(f"%{filters.concept.lower()}%"),
                    ContentChunk.clean_text.ilike(f"%{filters.concept.lower()}%"),
                )
            )
        if filters.topic:
            stmt = stmt.where(
                or_(
                    ContentChunk.clean_text.ilike(f"%{filters.topic.lower()}%"),
                    ContentChunk.metadata_json.ilike(f"%{filters.topic.lower()}%"),
                )
            )
        if question:
            tokens = normalize_tokens(question)
            if tokens:
                keyword_predicates = [ContentChunk.clean_text.ilike(f"%{token}%") for token in tokens[:8]]
                stmt = stmt.where(or_(*keyword_predicates))

        rows = self.session.execute(stmt).all()
        return [
            (chunk, channel_name, author_name, strategy_key, concepts_json, json.loads(vector_json))
            for chunk, channel_name, author_name, strategy_key, concepts_json, vector_json in rows
        ]

    @staticmethod
    def _keyword_score(
        query_tokens: Counter[str],
        chunk_tokens: Counter[str],
        clean_text: str,
        question: str,
    ) -> float:
        if not query_tokens:
            return 0.0
        overlap = sum(min(chunk_tokens[token], count) for token, count in query_tokens.items())
        base = overlap / max(len(query_tokens), 1)
        phrase_bonus = 0.25 if question.lower() in clean_text.lower() else 0.0
        return min(1.0, base + phrase_bonus)
