"""Traceability helpers for phase 3 artifacts."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.db.models.knowledge import ContentChunk, ExtractedRule, NormalizedRule, StrategyCandidate
from src.db.models.telegram_message import TelegramMessage


class TraceabilityBuilder:
    """Build traceability payloads from normalized rules back to source knowledge."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def for_extracted_rule(self, rule: ExtractedRule) -> dict:
        chunk = self.session.get(ContentChunk, rule.source_chunk_id) if rule.source_chunk_id else None
        message = self.session.get(TelegramMessage, chunk.message_id) if chunk and chunk.message_id else None
        return {
            "extracted_rule_id": rule.id,
            "source_chunk_id": rule.source_chunk_id,
            "source_type": rule.source_type,
            "source_reference": rule.source_reference,
            "channel_id": rule.channel_id,
            "channel_name": rule.channel_name,
            "author_name": rule.author_name,
            "source_file_name": rule.source_file_name,
            "message_id": message.telegram_message_id if message else None,
            "course_module": rule.module_name,
            "example_snippet": rule.example_snippet,
        }

    @staticmethod
    def for_setup(candidate: StrategyCandidate, rules: list[NormalizedRule]) -> dict:
        traces = []
        for rule in rules:
            if rule.traceability_json:
                traces.append(json.loads(rule.traceability_json))
        authors = sorted({trace.get("author_name") for trace in traces if trace.get("author_name")})
        channels = sorted({trace.get("channel_name") for trace in traces if trace.get("channel_name")})
        chunks = sorted({trace.get("source_chunk_id") for trace in traces if trace.get("source_chunk_id")})
        return {
            "strategy_candidate_id": candidate.id,
            "candidate_key": candidate.candidate_key,
            "authors": authors,
            "channels": channels,
            "source_chunk_ids": chunks,
            "rule_traces": traces,
        }
