from __future__ import annotations

from src.trading.market_knowledge_harmonizer import MarketKnowledgeHarmonizer


def test_harmonizer_reports_aligned_context() -> None:
    harmonizer = MarketKnowledgeHarmonizer()

    result = harmonizer.analyze(
        market_state={
            "market_regime": "NORMAL",
            "session_tags": ["london"],
            "preferred_side": "SELL",
            "allowed_hour_by_strategy": True,
            "volatility_state": "normal",
        },
        contexts=[
            {
                "strategy_family": "OB Rejection",
                "score": 0.78,
                "operability_label": "operable",
                "top_confirmations": ["wick_rejection"],
            },
            {
                "strategy_family": "OB Rejection",
                "score": 0.69,
                "operability_label": "operable",
                "top_confirmations": ["structure_shift"],
            },
        ],
        non_operable_situations=[],
        signal={"direction": "sell", "setup_type": "AGG"},
    )

    assert result["harmony_score"] >= 0.68
    assert result["operating_posture"] == "aligned"
    assert result["dominant_family"] == "OB Rejection"


def test_harmonizer_reports_defensive_when_context_conflicts() -> None:
    harmonizer = MarketKnowledgeHarmonizer()

    result = harmonizer.analyze(
        market_state={
            "market_regime": "CHOP",
            "session_tags": [],
            "preferred_side": "NEUTRAL",
            "allowed_hour_by_strategy": False,
            "volatility_state": "extreme",
        },
        contexts=[
            {
                "strategy_family": "General",
                "score": 0.22,
                "operability_label": "research_only",
                "top_confirmations": [],
            }
        ],
        non_operable_situations=[
            {"label": "choppy_or_range"},
            {"label": "outside_session"},
            {"label": "missing_confirmation"},
        ],
        signal=None,
    )

    assert result["harmony_score"] < 0.35
    assert result["operating_posture"] == "defensive"
    assert "chop_regime" in result["conflict_flags"]
