"""Comparison utilities for authors and courses."""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy.orm import Session

from src.db.models.knowledge import CourseModuleSummary, ExtractedRule, NormalizedRule
from src.knowledge.schemas import AuthorComparisonSchema


class KnowledgeComparisonService:
    """Compare authors or courses using the structured phase 2 outputs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def compare_authors(self, author_a: str, author_b: str) -> AuthorComparisonSchema:
        rules_a = self._rules_for_author(author_a)
        rules_b = self._rules_for_author(author_b)
        normalized_a = self._normalized_for_author(author_a)
        normalized_b = self._normalized_for_author(author_b)
        shared_concepts = sorted(set(self._top_concepts(rules_a, limit=50)).intersection(self._top_concepts(rules_b, limit=50)))
        compatible_families = sorted(
            set(self._top_normalized_values(normalized_a, "strategy_family", limit=50)).intersection(
                self._top_normalized_values(normalized_b, "strategy_family", limit=50)
            )
        )
        conflicting_biases = self._conflicting_biases(normalized_a, normalized_b)
        return AuthorComparisonSchema(
            author_a=author_a,
            author_b=author_b,
            total_rules_a=len(rules_a),
            total_rules_b=len(rules_b),
            top_assets_a=self._top_values(rules_a, "asset"),
            top_assets_b=self._top_values(rules_b, "asset"),
            top_concepts_a=self._top_concepts(rules_a),
            top_concepts_b=self._top_concepts(rules_b),
            sessions_a=self._top_values(rules_a, "session_filter"),
            sessions_b=self._top_values(rules_b, "session_filter"),
            notes=(
                f"{author_a} enfatiza {', '.join(self._top_concepts(rules_a)[:3]) or 'conceptos generales'}, "
                f"mientras que {author_b} enfatiza {', '.join(self._top_concepts(rules_b)[:3]) or 'conceptos generales'}. "
                f"Coinciden en {', '.join(shared_concepts[:5]) or 'pocos conceptos'}; "
                f"familias compatibles: {', '.join(compatible_families[:5]) or 'sin datos'}; "
                f"conflictos de sesgo detectados: {conflicting_biases}."
            ),
        )

    def compare_courses(self, course_a: str, course_b: str) -> dict:
        summaries_a = self.session.query(CourseModuleSummary).filter(CourseModuleSummary.course_name == course_a).all()
        summaries_b = self.session.query(CourseModuleSummary).filter(CourseModuleSummary.course_name == course_b).all()
        concepts_a = self._top_summary_concepts(summaries_a)
        concepts_b = self._top_summary_concepts(summaries_b)
        return {
            "course_a": course_a,
            "course_b": course_b,
            "modules_a": len(summaries_a),
            "modules_b": len(summaries_b),
            "top_concepts_a": concepts_a,
            "top_concepts_b": concepts_b,
            "shared_concepts": sorted(set(concepts_a).intersection(concepts_b)),
            "notes": f"{course_a} cubre {', '.join(concepts_a[:3])}; {course_b} cubre {', '.join(concepts_b[:3])}.",
        }

    def _rules_for_author(self, author_name: str) -> list[ExtractedRule]:
        return list(self.session.query(ExtractedRule).filter(ExtractedRule.author_name == author_name).all())

    def _normalized_for_author(self, author_name: str) -> list[NormalizedRule]:
        rows = self.session.query(NormalizedRule).all()
        result = []
        for row in rows:
            if not row.traceability_json:
                continue
            trace = json.loads(row.traceability_json)
            if trace.get("author_name") == author_name:
                result.append(row)
        return result

    @staticmethod
    def _top_values(rules: list[ExtractedRule], attribute: str, limit: int = 5) -> list[str]:
        counts = Counter(getattr(rule, attribute) for rule in rules if getattr(rule, attribute))
        return [value for value, _ in counts.most_common(limit)]

    @staticmethod
    def _top_concepts(rules: list[ExtractedRule], limit: int = 5) -> list[str]:
        counts = Counter()
        for rule in rules:
            if rule.concepts_json:
                counts.update(json.loads(rule.concepts_json))
        return [value for value, _ in counts.most_common(limit)]

    @staticmethod
    def _top_summary_concepts(summaries: list[CourseModuleSummary], limit: int = 5) -> list[str]:
        counts = Counter()
        for summary in summaries:
            if summary.key_concepts_json:
                counts.update(json.loads(summary.key_concepts_json))
        return [value for value, _ in counts.most_common(limit)]

    @staticmethod
    def _top_normalized_values(rules: list[NormalizedRule], attribute: str, limit: int = 5) -> list[str]:
        counts = Counter(getattr(rule, attribute) for rule in rules if getattr(rule, attribute))
        return [value for value, _ in counts.most_common(limit)]

    @staticmethod
    def _conflicting_biases(left: list[NormalizedRule], right: list[NormalizedRule]) -> int:
        conflicts = 0
        for left_rule in left:
            for right_rule in right:
                if (
                    left_rule.setup_name == right_rule.setup_name
                    and left_rule.direction_bias
                    and right_rule.direction_bias
                    and left_rule.direction_bias != right_rule.direction_bias
                ):
                    conflicts += 1
        return conflicts
