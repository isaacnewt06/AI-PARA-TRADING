from __future__ import annotations

import json
from types import SimpleNamespace

from src.trading.blueprint_builder import StrategyBlueprintBuilder


def test_blueprint_builder_prioritizes_ob_rejection_and_excludes_general() -> None:
    builder = object.__new__(StrategyBlueprintBuilder)
    builder.top_strategy_repository = SimpleNamespace(
        list_ranked=lambda: [
            SimpleNamespace(
                strategy_key="ob_key",
                name="OB Rejection | order_block | any_session | H1 | order_block_rejection",
                strategy_family="OB Rejection",
                concepts_json=json.dumps(["order_block"]),
                assets_json=json.dumps([]),
                timeframes_json=json.dumps(["H1", "M5", "M1"]),
                sessions_json=json.dumps(["new_york"]),
                entry_types_json=json.dumps(["order_block_rejection"]),
                supporting_setup_names_json=json.dumps(["OB Rejection - order_block - multi_symbol - M5"]),
                source_count=3,
                author_count=1,
                channel_count=1,
                rule_count=3,
                candidate_count=1,
                completeness_score=0.6,
                frequency_score=0.7,
                source_diversity_score=0.5,
                execution_definition_score=0.9,
                relevance_score=0.8,
                summary="ob summary",
                evidence_json=json.dumps({"source_chunk_ids": [1, 2]}),
            ),
            SimpleNamespace(
                strategy_key="general_key",
                name="General | general | any_session | H1 | general_entry",
                strategy_family="General",
                concepts_json=json.dumps([]),
                assets_json=json.dumps([]),
                timeframes_json=json.dumps(["H1", "M5"]),
                sessions_json=json.dumps([]),
                entry_types_json=json.dumps([]),
                supporting_setup_names_json=json.dumps(["General - general - multi_symbol - M5"]),
                source_count=2,
                author_count=1,
                channel_count=1,
                rule_count=2,
                candidate_count=1,
                completeness_score=0.2,
                frequency_score=0.5,
                source_diversity_score=0.4,
                execution_definition_score=0.5,
                relevance_score=0.6,
                summary="general summary",
                evidence_json=json.dumps({}),
            ),
        ]
    )
    builder.candidate_repository = SimpleNamespace(
        list_candidates=lambda: [
            SimpleNamespace(
                setup_name="OB Rejection - order_block - multi_symbol - M5",
                strategy_family="OB Rejection",
                context_tf_json=json.dumps(["H1"]),
                entry_tf_json=json.dumps(["M5", "M1"]),
                allowed_sessions_json=json.dumps(["new_york"]),
                rr_constraints_json=json.dumps({"rr_min": 2.0, "rr_target": 3.0}),
                risk_constraints_json=json.dumps({"risk_percent": 0.5}),
                source_traceability_json=json.dumps({"authors": ["manual"]}),
                coherence_score=0.9,
            )
        ]
    )

    bundle = builder.build()

    assert len(bundle.blueprints) == 1
    assert bundle.blueprints[0].strategy_family == "OB Rejection"
    assert bundle.blueprints[0].priority == 1
    assert bundle.blueprints[0].take_profit["rr_min"] == 2.0
    assert any(item["key"] == "entry_trigger" for item in bundle.blueprints[0].quantifiable_conditions)
    assert len(bundle.excluded_strategies) == 1
    assert bundle.excluded_strategies[0].strategy_family == "General"
