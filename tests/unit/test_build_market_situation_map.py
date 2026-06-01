from __future__ import annotations

import json
from types import SimpleNamespace

from src.application.build_market_situation_map import MarketSituationMapApplicationService


def test_market_situation_map_infers_regime() -> None:
    service = MarketSituationMapApplicationService.__new__(MarketSituationMapApplicationService)
    rule = SimpleNamespace(
        concept_tags=json.dumps(["breakout", "order_block"]),
        market_conditions=json.dumps(["market_structure_break"]),
        notes="Momentum and expansion after BOS",
    )

    assert service._infer_regime(rule) == "expansion"


def test_market_situation_map_operability_label() -> None:
    service = MarketSituationMapApplicationService.__new__(MarketSituationMapApplicationService)
    members = [
        SimpleNamespace(confidence_score=0.7, stop_model="atr", take_profit_model="rr_fixed", confirmation_conditions='["close_confirm"]'),
        SimpleNamespace(confidence_score=0.62, stop_model="atr", take_profit_model="rr_fixed", confirmation_conditions='["wick_confirm"]'),
    ]

    assert service._operability_label(members) == "operable"
