from pathlib import Path

from src.trading.adaptive_market_brain import (
    AdaptiveStrategyLibrary,
    AdaptiveStrategySelector,
    MarketRegimeSnapshot,
)


LIBRARY_PATH = Path("data/strategies/adaptive_strategy_library.json")


def _selector() -> AdaptiveStrategySelector:
    return AdaptiveStrategySelector(AdaptiveStrategyLibrary.load(LIBRARY_PATH))


def test_selector_prefers_institutional_ob_in_liquidity_sweep() -> None:
    selector = _selector()
    selection = selector.select(
        MarketRegimeSnapshot(
            symbol="XAUUSDm",
            primary_regime="liquidity_sweep",
            structural_state="expansion_clean",
            session="ny_am",
            volatility_bucket="expansion_clean",
            directional_bias="sell",
            confidence=0.9,
        )
    )

    assert selection.action == "SELECT"
    assert selection.selected_strategy == "ob_rejection_institutional"


def test_selector_blocks_on_macro_event() -> None:
    selector = _selector()
    selection = selector.select(
        MarketRegimeSnapshot(
            symbol="XAUUSDm",
            primary_regime="expansion_clean",
            session="ny_am",
            volatility_bucket="expansion_clean",
            macro_status="high_impact_event_window",
            confidence=1.0,
        )
    )

    assert selection.action == "BLOCKED"
    assert selection.selected_strategy == "no_trade_model"
    assert selection.risk_mode == "blocked"


def test_selector_waits_when_no_strategy_reaches_threshold() -> None:
    selector = _selector()
    selection = selector.select(
        MarketRegimeSnapshot(
            symbol="XAUUSDm",
            primary_regime="range_rotation",
            session="other",
            volatility_bucket="quiet",
            directional_bias="neutral",
            confidence=0.2,
        )
    )

    assert selection.action == "WAIT"
    assert selection.selected_strategy == "no_trade_model"


def test_reaction_zone_can_score_but_stays_research_constrained() -> None:
    selector = _selector()
    evaluations = selector.evaluate_all(
        MarketRegimeSnapshot(
            symbol="XAUUSDm",
            primary_regime="reversal_zone",
            structural_state="expansion_clean",
            session="ny_am",
            volatility_bucket="expansion_clean",
            directional_bias="buy",
            confidence=1.0,
        )
    )
    reaction = next(item for item in evaluations if item.strategy_code == "reaction_zone_scalper")

    assert reaction.score < reaction.minimum_score_to_trade
    assert reaction.action == "WAIT"

