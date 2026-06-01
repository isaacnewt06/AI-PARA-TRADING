from dataclasses import asdict

from src.processing.entity_extractor import TradingEntityExtractor


def test_entity_extractor_ignores_uppercase_product_words() -> None:
    entities = TradingEntityExtractor().extract("OPENAI TRADING BOT uses MT5 execution and risk guards")

    assert entities.asset is None


def test_entity_extractor_detects_real_trading_symbols() -> None:
    entities = TradingEntityExtractor().extract("Execution mode for XAUUSDm on H1 with liquidity sweep")

    assert entities.asset == "XAUUSDm"
    assert entities.timeframe == "H1"


def test_entity_extractor_output_is_serializable_via_asdict() -> None:
    entities = TradingEntityExtractor().extract("buy XAUUSDm M15 entry 3345 sl 3330 tp1 3360")

    payload = asdict(entities)

    assert payload["asset"] == "XAUUSDm"
    assert payload["timeframe"] == "M15"
    assert payload["direction"] == "buy"
