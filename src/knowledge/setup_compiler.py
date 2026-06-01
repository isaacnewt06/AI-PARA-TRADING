"""Compile normalized rules and conditions into setup definitions."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.knowledge import ContentChunk, NormalizedRule, QuantifiableCondition
from src.db.repositories.strategies import (
    NormalizedRuleRepository,
    QuantifiableConditionRepository,
    StrategyCandidateRepository,
)
from src.trading.strategy_schemas import StrategySetupDefinition

logger = get_logger(__name__)


class SetupCompilerService:
    """Compile compatible normalized rules into candidate setups."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.rule_repository = NormalizedRuleRepository(session)
        self.condition_repository = QuantifiableConditionRepository(session)
        self.candidate_repository = StrategyCandidateRepository(session)

    def run(self) -> dict[str, int]:
        rules = self._quality_eligible_rules(self.rule_repository.list_all())
        groups: dict[tuple[str, str], list[NormalizedRule]] = defaultdict(list)
        for rule in rules:
            groups[(rule.strategy_family, rule.setup_name)].append(rule)

        candidate_payloads = []
        component_payloads = []
        for (strategy_family, setup_name), members in groups.items():
            setup = self.compile_setup(strategy_family, setup_name, members)
            candidate_payloads.append(self._candidate_payload(setup))
            component_payloads.extend(self._component_payloads(setup, members))

        count = self.candidate_repository.replace_candidates(candidate_payloads, component_payloads)
        logger.info("Compiled %s strategy setup candidates", count)
        return {"strategy_candidates": count}

    def _quality_eligible_rules(self, rules: list[NormalizedRule]) -> list[NormalizedRule]:
        eligible = []
        for rule in rules:
            source_chunk_id = self._source_chunk_id(rule)
            if source_chunk_id is None:
                eligible.append(rule)
                continue
            chunk = self.session.get(ContentChunk, source_chunk_id)
            if chunk is None or not chunk.filtered_out:
                eligible.append(rule)
        return eligible

    @staticmethod
    def _source_chunk_id(rule: NormalizedRule) -> int | None:
        if not rule.traceability_json:
            return None
        try:
            value = json.loads(rule.traceability_json).get("source_chunk_id")
        except json.JSONDecodeError:
            return None
        return int(value) if value is not None else None

    def compile_setup(
        self,
        strategy_family: str,
        setup_name: str,
        rules: list[NormalizedRule],
    ) -> StrategySetupDefinition:
        conditions = []
        for rule in rules:
            conditions.extend(self.condition_repository.list_for_rule(rule.id))

        symbols = self._merge_json_lists(rule.symbol_scope for rule in rules)
        context_tf = self._merge_json_lists(rule.context_timeframes for rule in rules)
        entry_tf = self._merge_json_lists(rule.entry_timeframes for rule in rules)
        sessions = self._merge_json_lists(rule.session_filters for rule in rules)
        required = [self._condition_dict(condition) for condition in conditions if condition.required]
        optional = [self._condition_dict(condition) for condition in conditions if not condition.required]
        confirmations = [row for row in required if row["condition_type"] == "confirmation"]
        sl_logic = self._first_condition(required, "stop_model")
        tp_logic = self._first_condition(required, "take_profit_model")
        rr_min = max((rule.rr_min or 0 for rule in rules), default=0.0)
        rr_target = max((rule.rr_target or 0 for rule in rules), default=0.0)
        risk_percent_values = [rule.risk_percent for rule in rules if rule.risk_percent is not None]
        risk_percent = min(risk_percent_values) if risk_percent_values else None
        traceability = self._traceability(rules)
        setup_id = self._setup_id(strategy_family, setup_name, symbols, entry_tf)
        return StrategySetupDefinition(
            setup_id=setup_id,
            setup_name=setup_name,
            strategy_family=strategy_family,
            symbols=symbols,
            context_tf=context_tf,
            entry_tf=entry_tf,
            allowed_sessions=sessions,
            required_conditions=required,
            optional_conditions=optional,
            invalidation_conditions=self._invalidation_conditions(rules),
            confirmation_logic=confirmations,
            sl_logic=sl_logic,
            tp_logic=tp_logic,
            rr_constraints={"rr_min": rr_min or None, "rr_target": rr_target or None},
            risk_constraints={"risk_percent": risk_percent, "risk_models": self._unique(rule.risk_model for rule in rules)},
            execution_notes="Compiled from normalized rules. Validate against historical OHLCV before execution.",
            source_traceability=traceability,
        )

    @staticmethod
    def _candidate_payload(setup: StrategySetupDefinition) -> dict:
        coherence_score = min(
            1.0,
            0.2
            + (0.15 if setup.symbols else 0)
            + (0.15 if setup.context_tf else 0)
            + (0.15 if setup.entry_tf else 0)
            + (0.15 if setup.confirmation_logic else 0)
            + (0.1 if setup.sl_logic else 0)
            + (0.1 if setup.tp_logic else 0)
            + (0.1 if setup.source_traceability.get("authors") else 0),
        )
        return {
            "candidate_key": setup.setup_id,
            "setup_name": setup.setup_name,
            "strategy_family": setup.strategy_family,
            "symbols_json": json.dumps(setup.symbols, ensure_ascii=False),
            "context_tf_json": json.dumps(setup.context_tf, ensure_ascii=False),
            "entry_tf_json": json.dumps(setup.entry_tf, ensure_ascii=False),
            "allowed_sessions_json": json.dumps(setup.allowed_sessions, ensure_ascii=False),
            "required_conditions_json": json.dumps(setup.required_conditions, ensure_ascii=False),
            "optional_conditions_json": json.dumps(setup.optional_conditions, ensure_ascii=False),
            "invalidation_conditions_json": json.dumps(setup.invalidation_conditions, ensure_ascii=False),
            "confirmation_logic_json": json.dumps(setup.confirmation_logic, ensure_ascii=False),
            "sl_logic_json": json.dumps(setup.sl_logic, ensure_ascii=False),
            "tp_logic_json": json.dumps(setup.tp_logic, ensure_ascii=False),
            "rr_constraints_json": json.dumps(setup.rr_constraints, ensure_ascii=False),
            "risk_constraints_json": json.dumps(setup.risk_constraints, ensure_ascii=False),
            "execution_notes": setup.execution_notes,
            "source_traceability_json": json.dumps(setup.source_traceability, ensure_ascii=False),
            "coherence_score": round(coherence_score, 4),
            "status": "candidate",
        }

    @staticmethod
    def _component_payloads(setup: StrategySetupDefinition, rules: list[NormalizedRule]) -> list[dict]:
        payloads = []
        for rule in rules:
            payloads.append(
                {
                    "_candidate_key": setup.setup_id,
                    "normalized_rule_id": rule.id,
                    "component_type": "normalized_rule",
                    "component_key": str(rule.id),
                    "component_payload_json": json.dumps(
                        {
                            "setup_name": rule.setup_name,
                            "concept_tags": rule.concept_tags,
                            "traceability": rule.traceability_json,
                        },
                        ensure_ascii=False,
                    ),
                    "weight": rule.confidence_score or 0.5,
                }
            )
        return payloads

    @staticmethod
    def _merge_json_lists(values) -> list[str]:
        result: list[str] = []
        for value in values:
            if not value:
                continue
            try:
                items = json.loads(value)
            except json.JSONDecodeError:
                items = [value]
            for item in items:
                if item and item not in result:
                    result.append(item)
        return result

    @staticmethod
    def _unique(values) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _condition_dict(condition: QuantifiableCondition) -> dict:
        return {
            "condition_key": condition.condition_key,
            "condition_type": condition.condition_type,
            "signal_function": condition.signal_function,
            "parameters": json.loads(condition.parameters_json) if condition.parameters_json else {},
            "operator": condition.operator,
            "threshold": condition.threshold,
            "timeframe": condition.timeframe,
            "required": condition.required,
        }

    @staticmethod
    def _first_condition(conditions: list[dict], condition_key: str) -> dict:
        for condition in conditions:
            if condition["condition_key"] == condition_key:
                return condition
        return {}

    @staticmethod
    def _invalidation_conditions(rules: list[NormalizedRule]) -> list[dict]:
        invalidations = []
        for rule in rules:
            if rule.stop_model:
                invalidations.append({"type": "stop_model_invalidated", "model": rule.stop_model})
        return invalidations[:3]

    @staticmethod
    def _traceability(rules: list[NormalizedRule]) -> dict:
        traces = [json.loads(rule.traceability_json) for rule in rules if rule.traceability_json]
        return {
            "normalized_rule_ids": [rule.id for rule in rules],
            "extracted_rule_ids": [rule.extracted_rule_id for rule in rules],
            "authors": sorted({trace.get("author_name") for trace in traces if trace.get("author_name")}),
            "channels": sorted({trace.get("channel_name") for trace in traces if trace.get("channel_name")}),
            "source_chunk_ids": sorted({trace.get("source_chunk_id") for trace in traces if trace.get("source_chunk_id")}),
            "sources": traces,
        }

    @staticmethod
    def _setup_id(strategy_family: str, setup_name: str, symbols: list[str], entry_tf: list[str]) -> str:
        raw = "|".join([strategy_family, setup_name, ",".join(symbols), ",".join(entry_tf)])
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"setup_{digest}"
