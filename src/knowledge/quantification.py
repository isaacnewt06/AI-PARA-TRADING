"""Map normalized rules to quantifiable signal conditions."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.knowledge import NormalizedRule
from src.db.repositories.strategies import NormalizedRuleRepository, QuantifiableConditionRepository
from src.knowledge.ontology import StopModel, TakeProfitModel, TradingOntology

logger = get_logger(__name__)


class QuantificationService:
    """Create measurable condition rows from normalized rules."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.rule_repository = NormalizedRuleRepository(session)
        self.condition_repository = QuantifiableConditionRepository(session)

    def run(self) -> dict[str, int]:
        rules = self.rule_repository.list_all()
        payloads = []
        for rule in rules:
            payloads.extend(self.quantify_rule(rule))
        count = self.condition_repository.replace_for_rules(payloads)
        logger.info("Created %s quantifiable conditions", count)
        return {"quantifiable_conditions": count}

    def quantify_rule(self, rule: NormalizedRule) -> list[dict]:
        payloads: list[dict] = []
        concepts = self._json_list(rule.concept_tags)
        market_conditions = self._json_list(rule.market_conditions)
        entry_conditions = self._json_list(rule.entry_conditions)
        confirmations = self._json_list(rule.confirmation_conditions)
        sessions = self._json_list(rule.session_filters)
        context_tf = self._first(self._json_list(rule.context_timeframes))
        entry_tf = self._first(self._json_list(rule.entry_timeframes))

        for concept in concepts + market_conditions + entry_conditions:
            template = self._template_for(concept)
            if template:
                payloads.append(self._payload(rule, template, timeframe=context_tf if template.condition_type == "context" else entry_tf))

        for confirmation in confirmations:
            template = self._template_for(f"{confirmation}_confirmation") or self._template_for(confirmation)
            if template:
                payloads.append(self._payload(rule, template, timeframe=entry_tf))

        if sessions:
            template = TradingOntology.CONDITION_TEMPLATES["session_filter"]
            payload = self._payload(rule, template, timeframe=entry_tf)
            parameters = json.loads(payload["parameters_json"])
            parameters["allowed_sessions"] = sessions
            payload["parameters_json"] = json.dumps(parameters, ensure_ascii=False)
            payloads.append(payload)

        payloads.append(self._stop_payload(rule, entry_tf))
        payloads.append(self._take_profit_payload(rule, entry_tf))
        payloads.append(self._risk_payload(rule))
        return payloads

    @staticmethod
    def _payload(rule: NormalizedRule, template, timeframe: str | None) -> dict:
        return {
            "normalized_rule_id": rule.id,
            "condition_key": template.condition_key,
            "condition_type": template.condition_type,
            "signal_function": template.signal_function,
            "parameters_json": json.dumps(template.default_parameters, ensure_ascii=False),
            "operator": "equals",
            "threshold": 1.0,
            "timeframe": timeframe,
            "required": True,
            "notes": template.notes,
        }

    @staticmethod
    def _template_for(value: str):
        mapping = {
            "bos": "market_structure_break",
            "market_structure_break": "market_structure_break",
            "choch": "change_of_character",
            "change_of_character": "change_of_character",
            "liquidity_sweep": "liquidity_sweep",
            "fvg": "fair_value_gap",
            "fair_value_gap": "fair_value_gap",
            "fair_value_gap_entry": "fair_value_gap",
            "order_block": "order_block",
            "order_block_rejection": "order_block",
            "premium_discount": "premium_discount",
            "engulfing": "engulfing_confirmation",
            "engulfing_confirmation": "engulfing_confirmation",
        }
        key = mapping.get(value)
        return TradingOntology.CONDITION_TEMPLATES.get(key) if key else None

    @staticmethod
    def _stop_payload(rule: NormalizedRule, timeframe: str | None) -> dict:
        parameters = {"model": rule.stop_model or StopModel.UNKNOWN.value}
        if rule.stop_model == StopModel.RECENT_SWING_LOW.value:
            signal = "stop_below_recent_swing_low"
        elif rule.stop_model == StopModel.RECENT_SWING_HIGH.value:
            signal = "stop_above_recent_swing_high"
        else:
            signal = "derive_stop_from_model"
        return {
            "normalized_rule_id": rule.id,
            "condition_key": "stop_model",
            "condition_type": "risk",
            "signal_function": signal,
            "parameters_json": json.dumps(parameters, ensure_ascii=False),
            "operator": None,
            "threshold": None,
            "timeframe": timeframe,
            "required": True,
            "notes": "Stop model converted to execution proxy.",
        }

    @staticmethod
    def _take_profit_payload(rule: NormalizedRule, timeframe: str | None) -> dict:
        parameters = {
            "model": rule.take_profit_model or TakeProfitModel.UNKNOWN.value,
            "rr_min": rule.rr_min,
            "rr_target": rule.rr_target,
        }
        return {
            "normalized_rule_id": rule.id,
            "condition_key": "take_profit_model",
            "condition_type": "exit",
            "signal_function": "derive_take_profit_from_model",
            "parameters_json": json.dumps(parameters, ensure_ascii=False),
            "operator": "gte",
            "threshold": rule.rr_min,
            "timeframe": timeframe,
            "required": True,
            "notes": "Take profit model converted to RR/target proxy.",
        }

    @staticmethod
    def _risk_payload(rule: NormalizedRule) -> dict:
        return {
            "normalized_rule_id": rule.id,
            "condition_key": "risk_model",
            "condition_type": "risk",
            "signal_function": "apply_position_risk_model",
            "parameters_json": json.dumps(
                {"risk_model": rule.risk_model, "risk_percent": rule.risk_percent},
                ensure_ascii=False,
            ),
            "operator": "lte",
            "threshold": rule.risk_percent,
            "timeframe": None,
            "required": True,
            "notes": "Position sizing constraint.",
        }

    @staticmethod
    def _json_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return data if isinstance(data, list) else [str(data)]

    @staticmethod
    def _first(values: list[str]) -> str | None:
        return values[0] if values else None
