"""Repositories for phase 3 operational strategy entities."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.db.models.knowledge import (
    CandidateComponent,
    NormalizedRule,
    QuantifiableCondition,
    RuleQualityScore,
    SetupQualityScore,
    StrategyCandidate,
    TopStrategyDetected,
)


class NormalizedRuleRepository:
    """Persistence helpers for normalized rules."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_all(self, payloads: list[dict]) -> int:
        self.session.execute(delete(QuantifiableCondition))
        self.session.execute(delete(RuleQualityScore))
        self.session.execute(delete(CandidateComponent))
        self.session.execute(delete(SetupQualityScore))
        self.session.execute(delete(StrategyCandidate))
        self.session.execute(delete(NormalizedRule))
        for payload in payloads:
            self.session.add(NormalizedRule(**payload))
        self.session.flush()
        return len(payloads)

    def list_all(self) -> list[NormalizedRule]:
        return list(self.session.scalars(select(NormalizedRule).order_by(NormalizedRule.id.asc())))

    def get_by_id(self, normalized_rule_id: int) -> NormalizedRule | None:
        return self.session.get(NormalizedRule, normalized_rule_id)


class QuantifiableConditionRepository:
    """Persistence helpers for quantifiable conditions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_rules(self, payloads: list[dict]) -> int:
        self.session.execute(delete(QuantifiableCondition))
        for payload in payloads:
            self.session.add(QuantifiableCondition(**payload))
        self.session.flush()
        return len(payloads)

    def list_all(self) -> list[QuantifiableCondition]:
        return list(self.session.scalars(select(QuantifiableCondition).order_by(QuantifiableCondition.id.asc())))

    def list_for_rule(self, normalized_rule_id: int) -> list[QuantifiableCondition]:
        stmt = select(QuantifiableCondition).where(
            QuantifiableCondition.normalized_rule_id == normalized_rule_id
        ).order_by(QuantifiableCondition.id.asc())
        return list(self.session.scalars(stmt))


class StrategyCandidateRepository:
    """Persistence helpers for strategy candidates and components."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_candidates(self, candidates: list[dict], components: list[dict]) -> int:
        self.session.execute(delete(SetupQualityScore))
        self.session.execute(delete(CandidateComponent))
        self.session.execute(delete(StrategyCandidate))
        key_to_id: dict[str, int] = {}
        for payload in candidates:
            row = StrategyCandidate(**payload)
            self.session.add(row)
            self.session.flush()
            key_to_id[row.candidate_key] = row.id
        for payload in components:
            candidate_key = payload.pop("_candidate_key")
            payload["strategy_candidate_id"] = key_to_id[candidate_key]
            self.session.add(CandidateComponent(**payload))
        self.session.flush()
        return len(candidates)

    def list_candidates(self) -> list[StrategyCandidate]:
        stmt = select(StrategyCandidate).order_by(StrategyCandidate.coherence_score.desc(), StrategyCandidate.id.asc())
        return list(self.session.scalars(stmt))

    def get_by_name_or_key(self, value: str) -> StrategyCandidate | None:
        stmt = select(StrategyCandidate).where(
            (StrategyCandidate.setup_name == value) | (StrategyCandidate.candidate_key == value)
        )
        return self.session.scalar(stmt)

    def list_components(self, candidate_id: int) -> list[CandidateComponent]:
        stmt = select(CandidateComponent).where(CandidateComponent.strategy_candidate_id == candidate_id).order_by(
            CandidateComponent.component_type.asc(),
            CandidateComponent.id.asc(),
        )
        return list(self.session.scalars(stmt))


class QualityScoreRepository:
    """Persistence helpers for rule and setup quality scores."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_rule_scores(self, payloads: list[dict]) -> int:
        self.session.execute(delete(RuleQualityScore))
        for payload in payloads:
            self.session.add(RuleQualityScore(**payload))
        self.session.flush()
        return len(payloads)

    def replace_setup_scores(self, payloads: list[dict]) -> int:
        self.session.execute(delete(SetupQualityScore))
        for payload in payloads:
            self.session.add(SetupQualityScore(**payload))
        self.session.flush()
        return len(payloads)

    def list_rule_scores(self) -> list[RuleQualityScore]:
        return list(self.session.scalars(select(RuleQualityScore).order_by(RuleQualityScore.total_score.desc())))

    def list_setup_scores(self) -> list[SetupQualityScore]:
        return list(self.session.scalars(select(SetupQualityScore).order_by(SetupQualityScore.total_score.desc())))


class TopStrategyDetectionRepository:
    """Persistence helpers for detected top strategies."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_all(self, payloads: list[dict]) -> int:
        self.session.execute(delete(TopStrategyDetected))
        for payload in payloads:
            self.session.add(TopStrategyDetected(**payload))
        self.session.flush()
        return len(payloads)

    def list_ranked(self, limit: int | None = None) -> list[TopStrategyDetected]:
        stmt = select(TopStrategyDetected).order_by(
            TopStrategyDetected.relevance_score.desc(),
            TopStrategyDetected.rule_count.desc(),
            TopStrategyDetected.id.asc(),
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_by_name_or_key(self, value: str) -> TopStrategyDetected | None:
        stmt = select(TopStrategyDetected).where(
            (TopStrategyDetected.name == value) | (TopStrategyDetected.strategy_key == value)
        )
        return self.session.scalar(stmt)
