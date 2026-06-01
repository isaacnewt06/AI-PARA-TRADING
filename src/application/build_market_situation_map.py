"""Build a market situation map from absorbed trading knowledge."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.db.models.knowledge import NormalizedRule, TopStrategyDetected


class MarketSituationMapApplicationService:
    """Materialize an operable/non-operable market map from normalized rules."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self) -> dict[str, Any]:
        rules = list(self.session.scalars(select(NormalizedRule).order_by(NormalizedRule.id.asc())))
        detected = list(self.session.scalars(select(TopStrategyDetected).order_by(TopStrategyDetected.relevance_score.desc())))

        payload = {
            "summary": self._summary(rules, detected),
            "operable_situations": self._operable_situations(rules),
            "non_operable_situations": self._non_operable_situations(rules),
            "strategy_by_context": self._strategy_by_context(detected),
            "risk_by_regime": self._risk_by_regime(rules),
        }

        knowledge_dir = self.settings.paths.knowledge_dir
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        json_path = knowledge_dir / "market_situation_map.json"
        md_path = knowledge_dir / "market_situation_map.md"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(self._render_markdown(payload), encoding="utf-8")
        return {
            "normalized_rules": len(rules),
            "detected_strategies": len(detected),
            "operable_situations": len(payload["operable_situations"]),
            "non_operable_situations": len(payload["non_operable_situations"]),
            "json_path": str(json_path.resolve()),
            "md_path": str(md_path.resolve()),
        }

    def _summary(self, rules: list[NormalizedRule], detected: list[TopStrategyDetected]) -> dict[str, Any]:
        return {
            "normalized_rules": len(rules),
            "strategy_families": sorted({rule.strategy_family for rule in rules if rule.strategy_family}),
            "detected_strategy_count": len(detected),
            "top_detected": [item.name for item in detected[:10]],
        }

    def _operable_situations(self, rules: list[NormalizedRule]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str, str, str], list[NormalizedRule]] = defaultdict(list)
        for rule in rules:
            sessions = ",".join(self._json_list(rule.session_filters)) or "any_session"
            context_tf = ",".join(self._json_list(rule.context_timeframes)) or "any_context"
            entry_tf = ",".join(self._json_list(rule.entry_timeframes)) or "any_entry"
            direction = rule.direction_bias or "both"
            regime = self._infer_regime(rule)
            grouped[(rule.strategy_family, regime, sessions, context_tf, entry_tf, direction)].append(rule)

        situations: list[dict[str, Any]] = []
        for key, members in grouped.items():
            strategy_family, regime, sessions, context_tf, entry_tf, direction = key
            concepts = Counter()
            entry_conditions = Counter()
            confirmations = Counter()
            stop_models = Counter()
            tp_models = Counter()
            rr_targets: list[float] = []
            confidence: list[float] = []
            for rule in members:
                concepts.update(self._json_list(rule.concept_tags))
                entry_conditions.update(self._json_list(rule.entry_conditions))
                confirmations.update(self._json_list(rule.confirmation_conditions))
                if rule.stop_model:
                    stop_models[rule.stop_model] += 1
                if rule.take_profit_model:
                    tp_models[rule.take_profit_model] += 1
                if rule.rr_target is not None:
                    rr_targets.append(rule.rr_target)
                if rule.confidence_score is not None:
                    confidence.append(rule.confidence_score)

            situations.append(
                {
                    "situation_key": f"{strategy_family}|{regime}|{sessions}|{context_tf}|{entry_tf}|{direction}",
                    "strategy_family": strategy_family,
                    "market_regime": regime,
                    "sessions": sessions.split(",") if sessions != "any_session" else [],
                    "context_timeframes": context_tf.split(",") if context_tf != "any_context" else [],
                    "entry_timeframes": entry_tf.split(",") if entry_tf != "any_entry" else [],
                    "direction": direction,
                    "supporting_rules": len(members),
                    "top_concepts": [item for item, _ in concepts.most_common(5)],
                    "top_entry_conditions": [item for item, _ in entry_conditions.most_common(6)],
                    "top_confirmations": [item for item, _ in confirmations.most_common(6)],
                    "preferred_stop_model": stop_models.most_common(1)[0][0] if stop_models else "unknown",
                    "preferred_take_profit_model": tp_models.most_common(1)[0][0] if tp_models else "unknown",
                    "average_rr_target": round(sum(rr_targets) / len(rr_targets), 2) if rr_targets else None,
                    "average_confidence": round(sum(confidence) / len(confidence), 3) if confidence else None,
                    "operability_label": self._operability_label(members),
                }
            )
        situations.sort(key=lambda item: (-item["supporting_rules"], -(item["average_confidence"] or 0)))
        return situations

    def _non_operable_situations(self, rules: list[NormalizedRule]) -> list[dict[str, Any]]:
        counters: dict[str, dict[str, Any]] = {}
        for rule in rules:
            notes = (rule.notes or "").lower()
            market_conditions = " ".join(self._json_list(rule.market_conditions)).lower()
            source = f"{notes} {market_conditions}"
            labels = []
            if any(token in source for token in ["news", "noticia"]):
                labels.append("news_volatility")
            if any(token in source for token in ["chop", "rango", "consolid", "lateral"]):
                labels.append("choppy_or_range")
            if any(token in source for token in ["revenge", "venganza", "sobreoper", "overtrad"]):
                labels.append("emotional_or_overtrading")
            if any(token in source for token in ["fuera de sesión", "outside session", "session"]):
                labels.append("outside_session")
            if not self._json_list(rule.confirmation_conditions):
                labels.append("missing_confirmation")
            if rule.stop_model in {None, "unknown"} or rule.take_profit_model in {None, "unknown"}:
                labels.append("undefined_exit_logic")

            for label in labels:
                bucket = counters.setdefault(
                    label,
                    {
                        "label": label,
                        "supporting_rules": 0,
                        "affected_strategy_families": Counter(),
                        "common_notes": [],
                    },
                )
                bucket["supporting_rules"] += 1
                if rule.strategy_family:
                    bucket["affected_strategy_families"][rule.strategy_family] += 1
                if rule.notes and len(bucket["common_notes"]) < 5:
                    bucket["common_notes"].append(rule.notes[:220])

        results = []
        for label, bucket in counters.items():
            results.append(
                {
                    "label": label,
                    "supporting_rules": bucket["supporting_rules"],
                    "affected_strategy_families": [name for name, _ in bucket["affected_strategy_families"].most_common(5)],
                    "common_notes": bucket["common_notes"],
                }
            )
        results.sort(key=lambda item: -item["supporting_rules"])
        return results

    def _strategy_by_context(self, detected: list[TopStrategyDetected]) -> list[dict[str, Any]]:
        mapped = []
        for item in detected[:20]:
            mapped.append(
                {
                    "strategy_name": item.name,
                    "strategy_family": item.strategy_family,
                    "sessions": self._json_list(item.sessions_json),
                    "timeframes": self._json_list(item.timeframes_json),
                    "entry_types": self._json_list(item.entry_types_json),
                    "concepts": self._json_list(item.concepts_json),
                    "relevance_score": item.relevance_score,
                    "rule_count": item.rule_count,
                    "summary": item.summary,
                }
            )
        return mapped

    def _risk_by_regime(self, rules: list[NormalizedRule]) -> list[dict[str, Any]]:
        grouped: dict[str, list[NormalizedRule]] = defaultdict(list)
        for rule in rules:
            grouped[self._infer_regime(rule)].append(rule)

        rows = []
        for regime, members in grouped.items():
            risk_values = [rule.risk_percent for rule in members if rule.risk_percent is not None]
            rr_values = [rule.rr_target for rule in members if rule.rr_target is not None]
            risk_models = Counter(rule.risk_model for rule in members if rule.risk_model)
            stop_models = Counter(rule.stop_model for rule in members if rule.stop_model)
            rows.append(
                {
                    "market_regime": regime,
                    "supporting_rules": len(members),
                    "average_risk_percent": round(sum(risk_values) / len(risk_values), 3) if risk_values else None,
                    "average_rr_target": round(sum(rr_values) / len(rr_values), 2) if rr_values else None,
                    "preferred_risk_model": risk_models.most_common(1)[0][0] if risk_models else "configurable",
                    "preferred_stop_model": stop_models.most_common(1)[0][0] if stop_models else "unknown",
                }
            )
        rows.sort(key=lambda item: item["market_regime"])
        return rows

    def _infer_regime(self, rule: NormalizedRule) -> str:
        concepts = {item.lower() for item in self._json_list(rule.concept_tags)}
        market_conditions = {item.lower() for item in self._json_list(rule.market_conditions)}
        text = f"{' '.join(concepts)} {' '.join(market_conditions)} {(rule.notes or '').lower()}"
        if any(token in text for token in ["breakout", "displacement", "bos", "momentum", "expansion"]):
            return "expansion"
        if any(token in text for token in ["pullback", "retest", "trend", "mitigation", "order_block"]):
            return "trend"
        if any(token in text for token in ["range", "compression", "consolid", "lateral", "accumulation", "distribution"]):
            return "range"
        return "mixed"

    def _operability_label(self, members: list[NormalizedRule]) -> str:
        avg_conf = sum(rule.confidence_score or 0 for rule in members) / max(len(members), 1)
        missing_exits = sum(1 for rule in members if rule.stop_model in {None, "unknown"} or rule.take_profit_model in {None, "unknown"})
        missing_confirmations = sum(1 for rule in members if not self._json_list(rule.confirmation_conditions))
        if avg_conf >= 0.55 and missing_exits <= max(1, len(members) // 5) and missing_confirmations <= max(1, len(members) // 5):
            return "operable"
        if avg_conf >= 0.4:
            return "needs_confirmation"
        return "research_only"

    @staticmethod
    def _json_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(data, list):
            return [str(item) for item in data if item not in (None, "", [])]
        if data in (None, "", []):
            return []
        return [str(data)]

    def _render_markdown(self, payload: dict[str, Any]) -> str:
        lines: list[str] = []
        summary = payload["summary"]
        lines.append("# Market Situation Map")
        lines.append("")
        lines.append("## Summary")
        lines.append(f"- Normalized rules: `{summary['normalized_rules']}`")
        lines.append(f"- Detected strategies: `{summary['detected_strategy_count']}`")
        lines.append(f"- Strategy families: `{', '.join(summary['strategy_families'])}`")
        lines.append("")
        lines.append("## Operable Situations")
        for item in payload["operable_situations"][:20]:
            lines.append(
                f"- `{item['strategy_family']}` | regime `{item['market_regime']}` | sessions `{', '.join(item['sessions']) or 'any'}` | "
                f"entry TF `{', '.join(item['entry_timeframes']) or 'any'}` | rules `{item['supporting_rules']}` | label `{item['operability_label']}`"
            )
            lines.append(f"  concepts: {', '.join(item['top_concepts']) or 'n/a'}")
            lines.append(f"  entries: {', '.join(item['top_entry_conditions']) or 'n/a'}")
            lines.append(f"  confirmations: {', '.join(item['top_confirmations']) or 'n/a'}")
        lines.append("")
        lines.append("## Non-Operable Situations")
        for item in payload["non_operable_situations"][:12]:
            lines.append(f"- `{item['label']}` | rules `{item['supporting_rules']}` | families `{', '.join(item['affected_strategy_families'])}`")
        lines.append("")
        lines.append("## Strategy By Context")
        for item in payload["strategy_by_context"][:12]:
            lines.append(
                f"- `{item['strategy_name']}` | family `{item['strategy_family']}` | sessions `{', '.join(item['sessions']) or 'any'}` | "
                f"timeframes `{', '.join(item['timeframes']) or 'any'}` | relevance `{item['relevance_score']}`"
            )
        lines.append("")
        lines.append("## Risk By Regime")
        for item in payload["risk_by_regime"]:
            lines.append(
                f"- `{item['market_regime']}` | avg risk `{item['average_risk_percent']}` | avg RR `{item['average_rr_target']}` | "
                f"risk model `{item['preferred_risk_model']}` | stop `{item['preferred_stop_model']}`"
            )
        return "\n".join(lines) + "\n"
