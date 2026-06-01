"""Structured trading rule extraction from knowledge chunks."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.channel import Channel
from src.db.models.knowledge import ContentChunk, ExtractedRule
from src.db.repositories.knowledge import RuleRepository
from src.knowledge.patterns import (
    CONFIRMATION_PATTERNS,
    CONCEPT_PATTERNS,
    CONTEXT_PATTERNS,
    ENTRY_PATTERNS,
    RISK_PATTERNS,
    SESSION_PATTERNS,
    STOP_PATTERNS,
    TAKE_PROFIT_PATTERNS,
)
from src.knowledge.schemas import StructuredRuleSchema
from src.processing.entity_extractor import TradingEntityExtractor

logger = get_logger(__name__)


class RuleExtractorService:
    """Extract structured trading rules from content chunks."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.rule_repository = RuleRepository(session)
        self.entity_extractor = TradingEntityExtractor()

    def run(self) -> int:
        chunks = list(
            self.session.scalars(
                select(ContentChunk).where(ContentChunk.filtered_out.is_(False)).order_by(ContentChunk.id.asc())
            )
        )
        created = 0
        for chunk in chunks:
            created += self.extract_for_chunk(chunk)
        logger.info("Extracted %s structured trading rules", created)
        return created

    def extract_for_chunk(self, chunk: ContentChunk) -> int:
        self.rule_repository.delete_for_chunk(chunk.id)
        candidates = self._extract_candidates(chunk)
        for candidate in candidates:
            self.rule_repository.create_rule(candidate.model_dump())
        return len(candidates)

    def _extract_candidates(self, chunk: ContentChunk) -> list[StructuredRuleSchema]:
        text = chunk.clean_text
        if not text:
            return []

        metadata = self._metadata(chunk)
        entities = self.entity_extractor.extract(text)
        concepts = self._detect_concepts(text)
        lines = self._segments(text)
        entry_condition = self._first_match(lines, ENTRY_PATTERNS)
        confirmation = self._first_match(lines, CONFIRMATION_PATTERNS)
        stop_loss = self._first_match(lines, STOP_PATTERNS) or entities.stop_loss
        take_profit = self._first_match(lines, TAKE_PROFIT_PATTERNS) or ", ".join(entities.take_profits) or None
        risk_management = self._first_match(lines, RISK_PATTERNS)
        session_filter = self._first_match(lines, SESSION_PATTERNS)
        context = self._first_match(lines, CONTEXT_PATTERNS) or self._context_fallback(text, concepts)
        author_name = self._author_name(metadata)
        channel_name = metadata.get("channel_name")
        source_reference = metadata.get("source_reference")
        strategy_key = self._strategy_key(concepts, entities.asset, entities.timeframe, author_name)
        rule_type = self._rule_type(metadata.get("classification"), entry_condition, concepts)
        observations = self._observations(lines, entry_condition, confirmation, stop_loss, take_profit, risk_management)
        confidence = self._confidence(
            asset=entities.asset,
            timeframe=entities.timeframe,
            entry_condition=entry_condition,
            stop_loss=stop_loss,
            take_profit=take_profit,
            concepts=concepts,
        )
        module_name = metadata.get("module_name")
        source_file_name = metadata.get("file_name")
        example_snippet = text[:300]
        rule_text = self._compose_rule_text(
            asset=entities.asset,
            timeframe=entities.timeframe,
            direction=entities.direction,
            context=context,
            entry_condition=entry_condition,
            confirmation=confirmation,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_management=risk_management,
            session_filter=session_filter,
        )
        signature = self._signature(
            strategy_key=strategy_key,
            asset=entities.asset,
            timeframe=entities.timeframe,
            direction=entities.direction,
            entry_condition=entry_condition,
            confirmation=confirmation,
            stop_loss=stop_loss,
            take_profit=take_profit,
            concepts=concepts,
        )

        rule = StructuredRuleSchema(
            source_chunk_id=chunk.id,
            channel_id=chunk.channel_id,
            rule_type=rule_type,
            rule_text=rule_text,
            source_type=chunk.source_type,
            source_reference=source_reference,
            channel_name=channel_name,
            author_name=author_name,
            asset=entities.asset,
            timeframe=entities.timeframe,
            direction=entities.direction,
            context=context,
            entry_condition=entry_condition,
            confirmation=confirmation,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_management=risk_management,
            session_filter=session_filter,
            observations=observations,
            concepts_json=json.dumps(concepts, ensure_ascii=False),
            strategy_key=strategy_key,
            normalized_signature=signature,
            cluster_key=None,
            module_name=module_name,
            source_file_name=source_file_name,
            example_snippet=example_snippet,
            confidence=confidence,
        )
        if not any([rule.asset, rule.entry_condition, rule.confirmation, rule.context, concepts]):
            return []
        return [rule]

    @staticmethod
    def _segments(text: str) -> list[str]:
        lines = [line.strip() for line in re.split(r"[\n\r]+|(?<=[.!?])\s+", text) if line.strip()]
        return lines

    @staticmethod
    def _first_match(lines: list[str], patterns: list[re.Pattern[str]]) -> str | None:
        for line in lines:
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    group = match.group(1) if match.groups() else match.group(0)
                    return group.strip(" -:")
        return None

    def _detect_concepts(self, text: str) -> list[str]:
        found = [name for name, pattern in CONCEPT_PATTERNS.items() if pattern.search(text)]
        return found or self._concept_fallback(text)

    @staticmethod
    def _concept_fallback(text: str) -> list[str]:
        lowered = text.lower()
        concepts = []
        if "session" in lowered or "london" in lowered or "new york" in lowered:
            concepts.append("session_execution")
        if "support" in lowered or "resistance" in lowered:
            concepts.append("support_resistance")
        if "trend" in lowered:
            concepts.append("trend")
        return concepts

    @staticmethod
    def _context_fallback(text: str, concepts: list[str]) -> str | None:
        if not concepts:
            return None
        first_sentence = re.split(r"(?<=[.!?])\s+", text)[0]
        return first_sentence[:240]

    @staticmethod
    def _rule_type(classification: str | None, entry_condition: str | None, concepts: list[str]) -> str:
        if classification == "signal" or entry_condition:
            return "signal"
        if "risk_management" in concepts or classification == "gestion_riesgo":
            return "risk"
        if classification == "comentario_mercado":
            return "market_context"
        if concepts:
            return "setup"
        return "educational"

    @staticmethod
    def _compose_rule_text(**parts: str | None) -> str:
        ordered = []
        for label, value in parts.items():
            if value:
                ordered.append(f"{label.replace('_', ' ')}: {value}")
        return " | ".join(ordered)

    @staticmethod
    def _signature(**parts) -> str:
        normalized = "|".join(str(value or "").strip().lower() for value in parts.values())
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
        return digest

    @staticmethod
    def _confidence(
        *,
        asset: str | None,
        timeframe: str | None,
        entry_condition: str | None,
        stop_loss: str | None,
        take_profit: str | None,
        concepts: list[str],
    ) -> float:
        score = 0.15
        if asset:
            score += 0.15
        if timeframe:
            score += 0.1
        if entry_condition:
            score += 0.2
        if stop_loss:
            score += 0.15
        if take_profit:
            score += 0.15
        if concepts:
            score += min(0.15, 0.05 * len(concepts))
        return round(min(score, 0.95), 4)

    @staticmethod
    def _observations(
        lines: list[str],
        entry_condition: str | None,
        confirmation: str | None,
        stop_loss: str | None,
        take_profit: str | None,
        risk_management: str | None,
    ) -> str | None:
        excluded = {value for value in (entry_condition, confirmation, stop_loss, take_profit, risk_management) if value}
        leftovers = [line for line in lines if all(excluded_value not in line for excluded_value in excluded)]
        if not leftovers:
            return None
        return " ".join(leftovers[:2])[:260]

    @staticmethod
    def _strategy_key(concepts: list[str], asset: str | None, timeframe: str | None, author_name: str | None) -> str:
        primary = concepts[:2] or ["general"]
        author_part = (author_name or "unknown").lower().replace(" ", "_")
        asset_part = (asset or "asset").lower()
        tf_part = (timeframe or "multi").lower()
        return "_".join(primary + [asset_part, tf_part, author_part])

    @staticmethod
    def _author_name(metadata: dict[str, str | list[str] | None]) -> str:
        authors = metadata.get("authors")
        if isinstance(authors, list) and authors:
            return str(authors[0])
        if metadata.get("channel_name"):
            return str(metadata["channel_name"])
        return "unknown_author"

    @staticmethod
    def _metadata(chunk: ContentChunk) -> dict[str, str | list[str] | None]:
        metadata = json.loads(chunk.metadata_json) if chunk.metadata_json else {}
        metadata.setdefault("channel_name", metadata.get("channel"))
        metadata.setdefault("file_name", chunk.file_name)
        metadata.setdefault("source_reference", f"{chunk.source_type}:{chunk.source_id}")
        entities = metadata.get("entities")
        if isinstance(entities, dict):
            authors = entities.get("authors")
            if authors:
                metadata["authors"] = authors
        return metadata


class RuleClusterService:
    """Group similar extracted rules into strategy clusters."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.rule_repository = RuleRepository(session)

    def run(self) -> int:
        rules = self.rule_repository.list_rules()
        clusters_map: dict[str, list[ExtractedRule]] = {}
        for rule in rules:
            cluster_key = self._cluster_key(rule)
            rule.cluster_key = cluster_key
            self.session.add(rule)
            clusters_map.setdefault(cluster_key, []).append(rule)
        self.session.flush()

        payloads = []
        for cluster_key, members in clusters_map.items():
            payloads.append(self._cluster_payload(cluster_key, members))
        count = self.rule_repository.replace_clusters(payloads)
        logger.info("Grouped %s extracted rules into %s clusters", len(rules), count)
        return count

    @staticmethod
    def _cluster_key(rule: ExtractedRule) -> str:
        parts = [
            rule.strategy_key or "strategy",
            rule.asset or "asset",
            rule.timeframe or "multi",
            rule.direction or "direction",
            rule.normalized_signature or "signature",
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:18]

    @staticmethod
    def _cluster_payload(cluster_key: str, members: list[ExtractedRule]) -> dict:
        concepts = Counter()
        for member in members:
            if member.concepts_json:
                for concept in json.loads(member.concepts_json):
                    concepts[concept] += 1
        canonical_name = members[0].strategy_key or members[0].rule_type
        summary = " | ".join(
            filter(
                None,
                [
                    members[0].context,
                    members[0].entry_condition,
                    members[0].confirmation,
                    members[0].stop_loss,
                    members[0].take_profit,
                ],
            )
        )[:500]
        confidence = round(sum(member.confidence or 0.0 for member in members) / max(len(members), 1), 4)
        return {
            "cluster_key": cluster_key,
            "strategy_key": members[0].strategy_key,
            "canonical_name": canonical_name,
            "asset": members[0].asset,
            "timeframe": members[0].timeframe,
            "concept": concepts.most_common(1)[0][0] if concepts else None,
            "summary": summary,
            "member_count": len(members),
            "confidence": confidence,
        }
