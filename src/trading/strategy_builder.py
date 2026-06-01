"""Strategy builder that compiles normalized knowledge into candidates."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.setup_compiler import SetupCompilerService
from src.knowledge.quality_scoring import QualityScoringService


class StrategyBuilder:
    """Build strategy candidates from normalized rules and quantified conditions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def build(self, score: bool = True) -> dict:
        compile_summary = SetupCompilerService(self.session).run()
        score_summary = QualityScoringService(self.session).run() if score else {
            "rule_quality_scores": 0,
            "setup_quality_scores": 0,
        }
        return {
            "strategy_candidates": compile_summary["strategy_candidates"],
            "rule_quality_scores": score_summary["rule_quality_scores"],
            "setup_quality_scores": score_summary["setup_quality_scores"],
        }
