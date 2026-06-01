from src.knowledge.ontology import StopModel, TechnicalConcept, TradingOntology


def test_ontology_normalizes_synonyms() -> None:
    concepts = TradingOntology.normalize_concepts("Break of Structure with liquidity grab and imbalance")
    assert TechnicalConcept.BOS.value in concepts
    assert TechnicalConcept.LIQUIDITY_SWEEP.value in concepts
    assert TechnicalConcept.FVG.value in concepts


def test_ontology_infers_stop_model_from_direction() -> None:
    assert TradingOntology.infer_stop_model(None, "buy") == StopModel.RECENT_SWING_LOW
    assert TradingOntology.infer_stop_model(None, "sell") == StopModel.RECENT_SWING_HIGH


def test_ontology_preserves_broker_micro_symbol_suffix() -> None:
    assert TradingOntology.normalize_symbol("XAUUSDm") == "XAUUSDm"
