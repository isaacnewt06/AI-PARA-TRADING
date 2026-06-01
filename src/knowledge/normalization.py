"""Normalize extracted trading rules into operational rules."""

from __future__ import annotations

import json
import re
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.knowledge import ExtractedRule
from src.db.repositories.strategies import NormalizedRuleRepository
from src.knowledge.ontology import RiskModel, TradingOntology
from src.knowledge.traceability import TraceabilityBuilder

logger = get_logger(__name__)


class RuleNormalizationService:
    """Convert descriptive extracted rules into normalized operational rules."""

    normalization_version = "v1"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = NormalizedRuleRepository(session)
        self.traceability = TraceabilityBuilder(session)

    def run(self) -> dict[str, int]:
        rules = list(self.session.scalars(select(ExtractedRule).order_by(ExtractedRule.id.asc())))
        payloads = [self.normalize_rule(rule) for rule in rules]
        count = self.repository.replace_all(payloads)
        logger.info("Normalized %s extracted rules into operational rules", count)
        return {"normalized_rules": count}

    def normalize_rule(self, rule: ExtractedRule) -> dict:
        concepts = self._concepts(rule)
        concepts.extend(
            concept for concept in TradingOntology.normalize_concepts(
                " ".join(
                    filter(
                        None,
                        [
                            rule.context,
                            rule.entry_condition,
                            rule.confirmation,
                            rule.stop_loss,
                            rule.take_profit,
                            rule.risk_management,
                            rule.observations,
                        ],
                    )
                )
            )
            if concept not in concepts
        )
        sessions = TradingOntology.normalize_sessions(rule.session_filter or rule.context or "")
        symbol = TradingOntology.normalize_symbol(rule.asset)
        context_tfs, entry_tfs = self._timeframes(rule)
        stop_model = TradingOntology.infer_stop_model(rule.stop_loss, rule.direction)
        take_profit_model = TradingOntology.infer_take_profit_model(rule.take_profit)
        risk_percent = self._risk_percent(rule.risk_management)
        rr_min = self._rr_value(rule.take_profit) or 2.0
        strategy_family = TradingOntology.infer_strategy_family(concepts, sessions, rule.entry_condition).value
        setup_name = self._setup_name(strategy_family, concepts, symbol, entry_tfs)
        market_conditions = self._market_conditions(rule, concepts)
        entry_conditions = self._entry_conditions(rule, concepts)
        confirmation_conditions = TradingOntology.normalize_confirmations(rule.confirmation)
        confidence = self._confidence(rule, concepts, sessions, stop_model.value, take_profit_model.value)
        traceability = self.traceability.for_extracted_rule(rule)

        return {
            "extracted_rule_id": rule.id,
            "strategy_family": strategy_family,
            "setup_name": setup_name,
            "symbol_scope": json.dumps([symbol] if symbol else [], ensure_ascii=False),
            "context_timeframes": json.dumps(context_tfs, ensure_ascii=False),
            "entry_timeframes": json.dumps(entry_tfs, ensure_ascii=False),
            "session_filters": json.dumps(sessions, ensure_ascii=False),
            "direction_bias": self._direction(rule.direction),
            "concept_tags": json.dumps(sorted(set(concepts)), ensure_ascii=False),
            "market_conditions": json.dumps(market_conditions, ensure_ascii=False),
            "entry_conditions": json.dumps(entry_conditions, ensure_ascii=False),
            "confirmation_conditions": json.dumps(confirmation_conditions, ensure_ascii=False),
            "stop_model": stop_model.value,
            "take_profit_model": take_profit_model.value,
            "rr_min": rr_min,
            "rr_target": max(rr_min, 2.0),
            "risk_model": RiskModel.FIXED_PERCENT.value if risk_percent else RiskModel.CONFIGURABLE.value,
            "risk_percent": risk_percent,
            "notes": rule.observations or rule.rule_text,
            "confidence_score": confidence,
            "normalization_version": self.normalization_version,
            "traceability_json": json.dumps(traceability, ensure_ascii=False),
        }

    @staticmethod
    def _concepts(rule: ExtractedRule) -> list[str]:
        if rule.concepts_json:
            try:
                return TradingOntology.normalize_concepts(json.loads(rule.concepts_json))
            except json.JSONDecodeError:
                return TradingOntology.normalize_concepts(rule.concepts_json)
        return []

    @staticmethod
    def _timeframes(rule: ExtractedRule) -> tuple[list[str], list[str]]:
        text = " ".join(filter(None, [rule.timeframe, rule.context, rule.entry_condition, rule.confirmation]))
        timeframes = TradingOntology.normalize_timeframes([text])
        if not timeframes:
            return ["H1"], ["M5"]
        context = [tf for tf in timeframes if tf in {"H1", "H4", "D1", "W1"}] or timeframes[:1]
        entry = [tf for tf in timeframes if tf in {"M1", "M5", "M15", "M30"}] or timeframes[-1:]
        return context, entry

    @staticmethod
    def _risk_percent(text: str | None) -> float | None:
        if not text:
            return None
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        return float(match.group(1)) if match else None

    @staticmethod
    def _rr_value(text: str | None) -> float | None:
        if not text:
            return None
        match = re.search(r"(?:rr|risk reward|r:r)?\s*(\d+(?:\.\d+)?)\s*[:x]\s*1", text, re.IGNORECASE)
        if match:
            return float(match.group(1))
        match = re.search(r"1\s*[:x]\s*(\d+(?:\.\d+)?)", text)
        return float(match.group(1)) if match else None

    @staticmethod
    def _direction(direction: str | None) -> str | None:
        if not direction:
            return None
        lowered = direction.lower()
        if lowered in {"buy", "long"}:
            return "bullish"
        if lowered in {"sell", "short"}:
            return "bearish"
        return lowered

    @staticmethod
    def _market_conditions(rule: ExtractedRule, concepts: list[str]) -> list[str]:
        conditions = []
        if "bos" in concepts:
            conditions.append("market_structure_break")
        if "choch" in concepts:
            conditions.append("change_of_character")
        if "trend" in concepts:
            conditions.append("trend_alignment")
        if rule.context:
            conditions.append("context_filter_present")
        return conditions

    @staticmethod
    def _entry_conditions(rule: ExtractedRule, concepts: list[str]) -> list[str]:
        conditions = []
        if "liquidity_sweep" in concepts:
            conditions.append("liquidity_sweep")
        if "fvg" in concepts:
            conditions.append("fair_value_gap_entry")
        if "order_block" in concepts:
            conditions.append("order_block_rejection")
        if "breakout" in concepts and "retest" in concepts:
            conditions.append("breakout_retest")
        if rule.entry_condition:
            conditions.append("entry_rule_text_present")
        return conditions

    @staticmethod
    def _setup_name(strategy_family: str, concepts: list[str], symbol: str | None, entry_tfs: list[str]) -> str:
        concept_part = concepts[0] if concepts else "general"
        symbol_part = symbol or "multi_symbol"
        tf_part = entry_tfs[0] if entry_tfs else "multi_tf"
        return f"{strategy_family} - {concept_part} - {symbol_part} - {tf_part}"

    @staticmethod
    def _confidence(rule: ExtractedRule, concepts: list[str], sessions: list[str], stop_model: str, tp_model: str) -> float:
        score = rule.confidence or 0.2
        if concepts:
            score += 0.15
        if sessions:
            score += 0.05
        if stop_model != "unknown":
            score += 0.1
        if tp_model != "unknown":
            score += 0.1
        if rule.entry_condition:
            score += 0.1
        return round(min(score, 0.98), 4)
