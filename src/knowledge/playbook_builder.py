"""Generate strategy playbooks from clustered rules."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.knowledge import ExtractedRule
from src.db.repositories.knowledge import PlaybookRepository, RuleRepository

logger = get_logger(__name__)


class PlaybookBuilder:
    """Assemble extracted rules into reusable playbooks."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.rule_repository = RuleRepository(session)
        self.playbook_repository = PlaybookRepository(session)

    def build(self) -> int:
        rules = self.rule_repository.list_rules()
        grouped: dict[str, list[ExtractedRule]] = defaultdict(list)
        for rule in rules:
            if not rule.strategy_key:
                continue
            grouped[rule.strategy_key].append(rule)

        payloads = [self._build_playbook_payload(strategy_key, members) for strategy_key, members in grouped.items()]
        count = self.playbook_repository.replace_playbooks(payloads)
        logger.info("Built %s strategy playbooks", count)
        return count

    def _build_playbook_payload(self, strategy_key: str, members: list[ExtractedRule]) -> dict:
        concepts = Counter()
        authors = Counter()
        steps = {
            "context": self._top_values(members, "context", 3),
            "entry_conditions": self._top_values(members, "entry_condition", 3),
            "confirmations": self._top_values(members, "confirmation", 3),
            "risk_management": self._top_values(members, "risk_management", 3),
            "stop_loss": self._top_values(members, "stop_loss", 3),
            "take_profit": self._top_values(members, "take_profit", 3),
            "session_filters": self._top_values(members, "session_filter", 3),
            "observations": self._top_values(members, "observations", 3),
        }
        for member in members:
            if member.author_name:
                authors[member.author_name] += 1
            if member.concepts_json:
                for concept in json.loads(member.concepts_json):
                    concepts[concept] += 1

        description = (
            f"Estrategia {strategy_key} basada en {len(members)} reglas. "
            f"Activo dominante: {self._mode(members, 'asset') or 'multi'}. "
            f"Timeframe dominante: {self._mode(members, 'timeframe') or 'multi'}."
        )
        source_summary = " ".join(
            filter(
                None,
                [
                    steps["context"][0] if steps["context"] else None,
                    steps["entry_conditions"][0] if steps["entry_conditions"] else None,
                    steps["confirmations"][0] if steps["confirmations"] else None,
                ],
            )
        )[:700]
        confidence = round(sum(member.confidence or 0.0 for member in members) / max(len(members), 1), 4)
        return {
            "name": strategy_key.replace("_", " ").title(),
            "strategy_key": strategy_key,
            "channel_id": members[0].channel_id,
            "author_name": authors.most_common(1)[0][0] if authors else None,
            "description": description,
            "source_summary": source_summary,
            "concepts_json": json.dumps([concept for concept, _ in concepts.most_common(8)], ensure_ascii=False),
            "steps_json": json.dumps(steps, ensure_ascii=False),
            "rules_count": len(members),
            "confidence": confidence,
            "status": "draft",
        }

    @staticmethod
    def _top_values(members: list[ExtractedRule], attribute: str, limit: int) -> list[str]:
        values = Counter(getattr(member, attribute) for member in members if getattr(member, attribute))
        return [value for value, _ in values.most_common(limit)]

    @staticmethod
    def _mode(members: list[ExtractedRule], attribute: str) -> str | None:
        values = Counter(getattr(member, attribute) for member in members if getattr(member, attribute))
        return values.most_common(1)[0][0] if values else None
