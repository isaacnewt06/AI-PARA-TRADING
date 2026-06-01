"""Detect repeated strategy patterns from normalized rules and compiled setups."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.knowledge import (
    ContentChunk,
    NormalizedRule,
    RuleQualityScore,
    SetupQualityScore,
    StrategyCandidate,
)
from src.db.repositories.strategies import (
    QualityScoreRepository,
    StrategyCandidateRepository,
    TopStrategyDetectionRepository,
)
from src.trading.strategy_schemas import DetectedStrategySummary

logger = get_logger(__name__)


@dataclass(slots=True)
class _RuleContext:
    """Flattened rule information used for grouping and scoring."""

    rule: NormalizedRule
    concepts: list[str]
    assets: list[str]
    context_tfs: list[str]
    entry_tfs: list[str]
    sessions: list[str]
    entry_types: list[str]
    confirmations: list[str]
    market_conditions: list[str]
    traceability: dict


class StrategyPatternDetectorService:
    """Detect strongest repeated strategy structures in the knowledge base."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.candidate_repository = StrategyCandidateRepository(session)
        self.score_repository = QualityScoreRepository(session)
        self.detection_repository = TopStrategyDetectionRepository(session)

    def run(self) -> dict[str, int]:
        detected = self._build_detected_strategies()
        payloads = [self._payload(item) for item in detected]
        count = self.detection_repository.replace_all(payloads)
        logger.info("Detected %s top strategies from normalized rules", count)
        return {"top_strategies_detected": count}

    def rank(self, limit: int = 20) -> list[DetectedStrategySummary]:
        return [self._to_summary(row) for row in self.detection_repository.list_ranked(limit=limit)]

    def inspect(self, name_or_key: str) -> DetectedStrategySummary | None:
        row = self.detection_repository.get_by_name_or_key(name_or_key)
        return self._to_summary(row) if row is not None else None

    def _build_detected_strategies(self) -> list[DetectedStrategySummary]:
        rules = self._quality_eligible_rules(
            list(self.session.scalars(select(NormalizedRule).order_by(NormalizedRule.id.asc())))
        )
        if not rules:
            return []

        candidates = self.candidate_repository.list_candidates()
        candidate_by_setup: dict[str, list[StrategyCandidate]] = defaultdict(list)
        for candidate in candidates:
            candidate_by_setup[candidate.setup_name].append(candidate)

        rule_scores = {row.normalized_rule_id: row for row in self.score_repository.list_rule_scores()}
        setup_scores = {
            row.strategy_candidate_id: row for row in self.score_repository.list_setup_scores()
        }

        grouped: dict[tuple[str, str, str, str, str], list[_RuleContext]] = defaultdict(list)
        for rule in rules:
            context = self._rule_context(rule)
            grouped[self._group_key(context)].append(context)

        detected: list[DetectedStrategySummary] = []
        for members in grouped.values():
            detected.append(
                self._summarize_group(
                    members,
                    candidate_by_setup=candidate_by_setup,
                    rule_scores=rule_scores,
                    setup_scores=setup_scores,
                )
            )

        return sorted(
            detected,
            key=lambda item: (-item.relevance_score, -item.rule_count, -item.source_count, item.name),
        )

    def _quality_eligible_rules(self, rules: list[NormalizedRule]) -> list[NormalizedRule]:
        eligible: list[NormalizedRule] = []
        for rule in rules:
            source_chunk_id = self._source_chunk_id(rule)
            if source_chunk_id is None:
                eligible.append(rule)
                continue
            chunk = self.session.get(ContentChunk, source_chunk_id)
            if chunk is None or not chunk.filtered_out:
                eligible.append(rule)
        return eligible

    def _rule_context(self, rule: NormalizedRule) -> _RuleContext:
        traceability = self._json_dict(rule.traceability_json)
        return _RuleContext(
            rule=rule,
            concepts=self._json_list(rule.concept_tags),
            assets=self._json_list(rule.symbol_scope),
            context_tfs=self._json_list(rule.context_timeframes),
            entry_tfs=self._json_list(rule.entry_timeframes),
            sessions=self._json_list(rule.session_filters),
            entry_types=self._entry_types(rule),
            confirmations=self._json_list(rule.confirmation_conditions),
            market_conditions=self._json_list(rule.market_conditions),
            traceability=traceability,
        )

    def _group_key(self, context: _RuleContext) -> tuple[str, str, str, str, str]:
        strategy_family = context.rule.strategy_family or "General"
        concepts = self._concept_signature(context)
        timeframe = context.entry_tfs[0] if context.entry_tfs else (context.context_tfs[0] if context.context_tfs else "multi_tf")
        session = context.sessions[0] if context.sessions else "any_session"
        entry_type = context.entry_types[0] if context.entry_types else "general_entry"
        return strategy_family, concepts, timeframe, session, entry_type

    def _summarize_group(
        self,
        members: list[_RuleContext],
        *,
        candidate_by_setup: dict[str, list[StrategyCandidate]],
        rule_scores: dict[int, RuleQualityScore],
        setup_scores: dict[int, SetupQualityScore],
    ) -> DetectedStrategySummary:
        first = members[0]
        concepts = self._flatten_unique(item.concepts for item in members)
        assets = self._flatten_unique(item.assets for item in members)
        timeframes = self._flatten_unique([item.context_tfs + item.entry_tfs for item in members])
        sessions = self._flatten_unique(item.sessions for item in members)
        entry_types = self._flatten_unique(item.entry_types for item in members)
        setup_names = sorted({item.rule.setup_name for item in members if item.rule.setup_name})
        candidate_rows = [candidate for setup_name in setup_names for candidate in candidate_by_setup.get(setup_name, [])]
        authors = sorted(
            {
                item.traceability.get("author_name")
                for item in members
                if item.traceability.get("author_name")
            }
        )
        channels = sorted(
            {
                item.traceability.get("channel_name")
                for item in members
                if item.traceability.get("channel_name")
            }
        )
        source_chunk_ids = sorted(
            {
                int(item.traceability.get("source_chunk_id"))
                for item in members
                if item.traceability.get("source_chunk_id") is not None
            }
        )

        completeness = self._completeness_score(members)
        frequency = min(1.0, len(members) / 4)
        source_diversity = min(
            1.0,
            min(1.0, len(source_chunk_ids) / 3) * 0.45
            + min(1.0, len(authors) / 2) * 0.3
            + min(1.0, len(channels) / 2) * 0.25,
        )
        avg_rule_quality = self._average(
            rule_scores[item.rule.id].total_score for item in members if item.rule.id in rule_scores
        )
        avg_candidate_quality = self._average(
            setup_scores[candidate.id].total_score
            for candidate in candidate_rows
            if candidate.id in setup_scores
        )
        avg_candidate_coherence = self._average(candidate.coherence_score or 0.0 for candidate in candidate_rows)
        execution_definition = min(
            1.0,
            avg_rule_quality * 0.45
            + avg_candidate_quality * 0.25
            + avg_candidate_coherence * 0.2
            + (0.1 if entry_types else 0.0),
        )
        relevance = frequency * 0.3 + source_diversity * 0.25 + completeness * 0.25 + execution_definition * 0.2
        if completeness < 0.45:
            relevance -= 0.15
        if len(source_chunk_ids) < 2:
            relevance -= 0.05
        relevance = round(max(0.0, min(1.0, relevance)), 4)

        name = self._display_name(
            strategy_family=first.rule.strategy_family,
            concepts=concepts,
            sessions=sessions,
            timeframes=timeframes,
            entry_types=entry_types,
        )
        evidence = {
            "normalized_rule_ids": [item.rule.id for item in members],
            "extracted_rule_ids": [item.rule.extracted_rule_id for item in members],
            "source_chunk_ids": source_chunk_ids,
            "authors": authors,
            "channels": channels,
            "setup_names": setup_names,
            "assets": assets,
            "timeframes": timeframes,
            "sessions": sessions,
            "entry_types": entry_types,
            "concept_frequency": dict(Counter(concept for item in members for concept in item.concepts)),
            "confirmation_frequency": dict(
                Counter(confirmation for item in members for confirmation in item.confirmations)
            ),
            "candidate_keys": [candidate.candidate_key for candidate in candidate_rows],
        }

        return DetectedStrategySummary(
            strategy_key=self._strategy_key(first.rule.strategy_family or "General", name),
            name=name,
            strategy_family=first.rule.strategy_family,
            concepts=concepts,
            assets=assets,
            timeframes=timeframes,
            sessions=sessions,
            entry_types=entry_types,
            supporting_setup_names=setup_names,
            source_count=len(source_chunk_ids),
            author_count=len(authors),
            channel_count=len(channels),
            rule_count=len(members),
            candidate_count=len(candidate_rows),
            completeness_score=round(completeness, 4),
            frequency_score=round(frequency, 4),
            source_diversity_score=round(source_diversity, 4),
            execution_definition_score=round(execution_definition, 4),
            relevance_score=relevance,
            summary=self._summary_text(
                strategy_family=first.rule.strategy_family,
                concepts=concepts,
                sessions=sessions,
                timeframes=timeframes,
                entry_types=entry_types,
                source_count=len(source_chunk_ids),
                rule_count=len(members),
                completeness=completeness,
            ),
            evidence=evidence,
        )

    @staticmethod
    def _entry_types(rule: NormalizedRule) -> list[str]:
        entry_conditions = StrategyPatternDetectorService._json_list(rule.entry_conditions)
        mapped_items: list[str] = []
        mapping = {
            "fair_value_gap_entry": "fvg_entry",
            "order_block_rejection": "order_block_rejection",
            "breakout_retest": "breakout_retest",
            "liquidity_sweep": "liquidity_reversal",
            "entry_rule_text_present": "rule_text_entry",
        }
        for item in entry_conditions:
            mapped = mapping.get(item, item)
            if mapped not in mapped_items:
                mapped_items.append(mapped)
        priority = {
            "fvg_entry": 0,
            "order_block_rejection": 1,
            "breakout_retest": 2,
            "liquidity_reversal": 3,
            "rule_text_entry": 4,
        }
        return sorted(mapped_items, key=lambda item: (priority.get(item, 99), item))

    @staticmethod
    def _concept_signature(context: _RuleContext) -> str:
        priority = {
            "bos": 0,
            "choch": 1,
            "fvg": 2,
            "order_block": 3,
            "liquidity_sweep": 4,
            "breakout": 5,
            "retest": 6,
            "trend": 7,
        }
        prioritized = sorted(
            {concept for concept in context.concepts if concept in priority},
            key=lambda item: (priority[item], item),
        )
        if "fvg" in prioritized and "bos" in prioritized:
            signature = ["bos", "fvg"]
        elif "breakout" in prioritized and "retest" in prioritized:
            signature = ["breakout", "retest"]
        elif prioritized:
            signature = prioritized[:2]
        else:
            signature = context.concepts[:2] or ["general"]
        return ",".join(signature)

    @staticmethod
    def _completeness_score(members: list[_RuleContext]) -> float:
        values = []
        for item in members:
            checks = [
                bool(item.entry_types),
                bool(item.market_conditions or item.context_tfs),
                bool(item.confirmations),
                bool(item.rule.stop_model and item.rule.stop_model != "unknown"),
                bool(item.rule.take_profit_model and item.rule.take_profit_model != "unknown"),
            ]
            values.append(sum(1 for check in checks if check) / len(checks))
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _display_name(
        *,
        strategy_family: str | None,
        concepts: list[str],
        sessions: list[str],
        timeframes: list[str],
        entry_types: list[str],
    ) -> str:
        concept_part = " + ".join(concepts[:3]) if concepts else "general"
        session_part = sessions[0] if sessions else "any_session"
        timeframe_part = timeframes[0] if timeframes else "multi_tf"
        entry_part = entry_types[0] if entry_types else "general_entry"
        return f"{strategy_family or 'General'} | {concept_part} | {session_part} | {timeframe_part} | {entry_part}"

    @staticmethod
    def _summary_text(
        *,
        strategy_family: str | None,
        concepts: list[str],
        sessions: list[str],
        timeframes: list[str],
        entry_types: list[str],
        source_count: int,
        rule_count: int,
        completeness: float,
    ) -> str:
        concept_text = ", ".join(concepts[:4]) if concepts else "conceptos generales"
        session_text = ", ".join(sessions[:2]) if sessions else "sin sesion fija"
        timeframe_text = ", ".join(timeframes[:3]) if timeframes else "multi timeframe"
        entry_text = ", ".join(entry_types[:2]) if entry_types else "entrada general"
        return (
            f"{strategy_family or 'General'} repetida en {source_count} fuentes y {rule_count} reglas. "
            f"Conceptos dominantes: {concept_text}. Timeframes: {timeframe_text}. "
            f"Sesiones: {session_text}. Entrada: {entry_text}. "
            f"Completitud operativa {completeness:.0%}."
        )

    @staticmethod
    def _strategy_key(strategy_family: str, name: str) -> str:
        digest = hashlib.sha1(f"{strategy_family}|{name}".encode("utf-8")).hexdigest()[:12]
        return f"detected_{digest}"

    @staticmethod
    def _source_chunk_id(rule: NormalizedRule) -> int | None:
        traceability = StrategyPatternDetectorService._json_dict(rule.traceability_json)
        source_chunk_id = traceability.get("source_chunk_id")
        return int(source_chunk_id) if source_chunk_id is not None else None

    @staticmethod
    def _flatten_unique(groups) -> list[str]:
        result: list[str] = []
        for group in groups:
            for item in group:
                if item and item not in result:
                    result.append(item)
        return result

    @staticmethod
    def _average(values) -> float:
        collected = [value for value in values if value is not None]
        return sum(collected) / len(collected) if collected else 0.0

    @staticmethod
    def _json_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item is not None]
        return [str(parsed)]

    @staticmethod
    def _json_dict(value: str | None) -> dict:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _payload(item: DetectedStrategySummary) -> dict:
        status = "strong" if item.relevance_score >= 0.75 else "promising" if item.relevance_score >= 0.55 else "weak"
        return {
            "strategy_key": item.strategy_key,
            "name": item.name,
            "strategy_family": item.strategy_family,
            "concepts_json": json.dumps(item.concepts, ensure_ascii=False),
            "assets_json": json.dumps(item.assets, ensure_ascii=False),
            "timeframes_json": json.dumps(item.timeframes, ensure_ascii=False),
            "sessions_json": json.dumps(item.sessions, ensure_ascii=False),
            "entry_types_json": json.dumps(item.entry_types, ensure_ascii=False),
            "supporting_setup_names_json": json.dumps(item.supporting_setup_names, ensure_ascii=False),
            "source_count": item.source_count,
            "author_count": item.author_count,
            "channel_count": item.channel_count,
            "rule_count": item.rule_count,
            "candidate_count": item.candidate_count,
            "completeness_score": item.completeness_score,
            "frequency_score": item.frequency_score,
            "source_diversity_score": item.source_diversity_score,
            "execution_definition_score": item.execution_definition_score,
            "relevance_score": item.relevance_score,
            "summary": item.summary,
            "evidence_json": json.dumps(item.evidence, ensure_ascii=False),
            "status": status,
        }

    @staticmethod
    def _to_summary(row) -> DetectedStrategySummary:
        return DetectedStrategySummary(
            strategy_key=row.strategy_key,
            name=row.name,
            strategy_family=row.strategy_family,
            concepts=StrategyPatternDetectorService._json_list(row.concepts_json),
            assets=StrategyPatternDetectorService._json_list(row.assets_json),
            timeframes=StrategyPatternDetectorService._json_list(row.timeframes_json),
            sessions=StrategyPatternDetectorService._json_list(row.sessions_json),
            entry_types=StrategyPatternDetectorService._json_list(row.entry_types_json),
            supporting_setup_names=StrategyPatternDetectorService._json_list(row.supporting_setup_names_json),
            source_count=row.source_count,
            author_count=row.author_count,
            channel_count=row.channel_count,
            rule_count=row.rule_count,
            candidate_count=row.candidate_count,
            completeness_score=row.completeness_score,
            frequency_score=row.frequency_score,
            source_diversity_score=row.source_diversity_score,
            execution_definition_score=row.execution_definition_score,
            relevance_score=row.relevance_score,
            summary=row.summary,
            evidence=StrategyPatternDetectorService._json_dict(row.evidence_json),
        )
