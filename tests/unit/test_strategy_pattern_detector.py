import json

from src.db.models.knowledge import NormalizedRule
from src.knowledge.strategy_pattern_detector import StrategyPatternDetectorService


def test_strategy_pattern_detector_maps_entry_types() -> None:
    rule = NormalizedRule(
        extracted_rule_id=1,
        strategy_family="FVG Continuation",
        setup_name="FVG Continuation - fvg - XAUUSD - M15",
        entry_conditions=json.dumps(["fair_value_gap_entry", "liquidity_sweep", "entry_rule_text_present"]),
    )

    entry_types = StrategyPatternDetectorService._entry_types(rule)

    assert entry_types == ["fvg_entry", "liquidity_reversal", "rule_text_entry"]


def test_strategy_pattern_detector_builds_human_name() -> None:
    name = StrategyPatternDetectorService._display_name(
        strategy_family="Liquidity Reversal",
        concepts=["bos", "fvg", "liquidity_sweep"],
        sessions=["london"],
        timeframes=["M15", "H1"],
        entry_types=["fvg_entry"],
    )

    assert name == "Liquidity Reversal | bos + fvg + liquidity_sweep | london | M15 | fvg_entry"
