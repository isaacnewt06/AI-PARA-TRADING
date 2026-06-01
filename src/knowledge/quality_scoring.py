"""Quality scoring for normalized rules and compiled setups."""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.knowledge import NormalizedRule, StrategyCandidate
from src.db.repositories.strategies import (
    NormalizedRuleRepository,
    QualityScoreRepository,
    QuantifiableConditionRepository,
    StrategyCandidateRepository,
)

logger = get_logger(__name__)


class QualityScoringService:
    """Score rules and setups for operational readiness."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.rule_repository = NormalizedRuleRepository(session)
        self.condition_repository = QuantifiableConditionRepository(session)
        self.candidate_repository = StrategyCandidateRepository(session)
        self.score_repository = QualityScoreRepository(session)

    def run(self) -> dict[str, int]:
        rules = self.rule_repository.list_all()
        candidates = self.candidate_repository.list_candidates()
        rule_scores = [self.score_rule(rule, rules) for rule in rules]
        setup_scores = [self.score_setup(candidate) for candidate in candidates]
        rule_count = self.score_repository.replace_rule_scores(rule_scores)
        setup_count = self.score_repository.replace_setup_scores(setup_scores)
        logger.info("Scored %s rules and %s setups", rule_count, setup_count)
        return {"rule_quality_scores": rule_count, "setup_quality_scores": setup_count}

    def score_rule(self, rule: NormalizedRule, all_rules: list[NormalizedRule]) -> dict:
        concepts = self._json_list(rule.concept_tags)
        entry_conditions = self._json_list(rule.entry_conditions)
        conditions = self.condition_repository.list_for_rule(rule.id)
        clarity = self._score_presence([rule.setup_name, concepts, entry_conditions])
        completeness = self._score_presence(
            [
                rule.symbol_scope,
                rule.context_timeframes,
                rule.entry_timeframes,
                rule.entry_conditions,
                rule.stop_model,
                rule.take_profit_model,
                rule.risk_model,
            ]
        )
        quantifiability = min(1.0, len(conditions) / 5)
        contradiction = self._contradiction_score(rule)
        multi_source = self._multi_source_score(rule, all_rules)
        multi_author = self._multi_author_score(rule, all_rules)
        repetition = self._semantic_repetition_score(rule, all_rules)
        total = (
            clarity * 0.15
            + completeness * 0.25
            + quantifiability * 0.25
            + (1 - contradiction) * 0.1
            + multi_source * 0.1
            + multi_author * 0.05
            + repetition * 0.1
        )
        return {
            "normalized_rule_id": rule.id,
            "clarity_score": round(clarity, 4),
            "completeness_score": round(completeness, 4),
            "quantifiability_score": round(quantifiability, 4),
            "contradiction_score": round(contradiction, 4),
            "multi_source_score": round(multi_source, 4),
            "multi_author_score": round(multi_author, 4),
            "semantic_repetition_score": round(repetition, 4),
            "total_score": round(total, 4),
            "notes": "Phase 3 deterministic quality score.",
        }

    def score_setup(self, candidate: StrategyCandidate) -> dict:
        required = self._json_list(candidate.required_conditions_json)
        traceability = json.loads(candidate.source_traceability_json) if candidate.source_traceability_json else {}
        coherence = candidate.coherence_score or 0.0
        completeness = self._score_presence(
            [
                candidate.symbols_json,
                candidate.context_tf_json,
                candidate.entry_tf_json,
                candidate.sl_logic_json,
                candidate.tp_logic_json,
                candidate.risk_constraints_json,
            ]
        )
        quantifiability = min(1.0, len(required) / 6)
        traceability_score = min(1.0, len(traceability.get("source_chunk_ids", [])) / 3)
        risk_defined = 1.0 if candidate.risk_constraints_json and candidate.sl_logic_json else 0.0
        contradiction = self._candidate_contradiction_score(candidate)
        total = (
            coherence * 0.25
            + completeness * 0.25
            + quantifiability * 0.2
            + traceability_score * 0.1
            + risk_defined * 0.1
            + (1 - contradiction) * 0.1
        )
        return {
            "strategy_candidate_id": candidate.id,
            "coherence_score": round(coherence, 4),
            "completeness_score": round(completeness, 4),
            "quantifiability_score": round(quantifiability, 4),
            "traceability_score": round(traceability_score, 4),
            "risk_defined_score": round(risk_defined, 4),
            "contradiction_score": round(contradiction, 4),
            "total_score": round(total, 4),
            "notes": "Phase 3 deterministic setup score.",
        }

    @staticmethod
    def _score_presence(values: list) -> float:
        if not values:
            return 0.0
        present = 0
        for value in values:
            if isinstance(value, list) and value:
                present += 1
            elif value:
                present += 1
        return present / len(values)

    @staticmethod
    def _contradiction_score(rule: NormalizedRule) -> float:
        if rule.direction_bias not in {"bullish", "bearish", None}:
            return 0.3
        if rule.stop_model == "recent_swing_low" and rule.direction_bias == "bearish":
            return 0.4
        if rule.stop_model == "recent_swing_high" and rule.direction_bias == "bullish":
            return 0.4
        return 0.0

    @staticmethod
    def _candidate_contradiction_score(candidate: StrategyCandidate) -> float:
        symbols = set(json.loads(candidate.symbols_json) if candidate.symbols_json else [])
        return 0.2 if len(symbols) > 5 else 0.0

    @staticmethod
    def _multi_source_score(rule: NormalizedRule, all_rules: list[NormalizedRule]) -> float:
        same_setup = [item for item in all_rules if item.setup_name == rule.setup_name]
        chunks = set()
        for item in same_setup:
            if item.traceability_json:
                trace = json.loads(item.traceability_json)
                if trace.get("source_chunk_id"):
                    chunks.add(trace["source_chunk_id"])
        return min(1.0, len(chunks) / 3)

    @staticmethod
    def _multi_author_score(rule: NormalizedRule, all_rules: list[NormalizedRule]) -> float:
        same_setup = [item for item in all_rules if item.setup_name == rule.setup_name]
        authors = set()
        for item in same_setup:
            if item.traceability_json:
                trace = json.loads(item.traceability_json)
                if trace.get("author_name"):
                    authors.add(trace["author_name"])
        return min(1.0, len(authors) / 2)

    @staticmethod
    def _semantic_repetition_score(rule: NormalizedRule, all_rules: list[NormalizedRule]) -> float:
        same_concepts = [
            item
            for item in all_rules
            if item.id != rule.id and item.concept_tags == rule.concept_tags and item.strategy_family == rule.strategy_family
        ]
        return min(1.0, len(same_concepts) / 3)

    @staticmethod
    def _json_list(value: str | None) -> list:
        if not value:
            return []
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return data if isinstance(data, list) else [data]
