from src.db.models.knowledge import ContentChunk
from src.knowledge.content_quality import ContentQualityFilter


def _chunk(text: str, chunk_id: int = 1) -> ContentChunk:
    return ContentChunk(
        id=chunk_id,
        source_type="message",
        source_id=chunk_id,
        chunk_index=0,
        text=text,
        clean_text=text,
    )


def test_quality_filter_keeps_structured_strategy_content() -> None:
    text = (
        "Estrategia XAUUSD H1/M15: esperar BOS y liquidity sweep en London. "
        "Entrada en FVG, confirmacion con engulfing, SL bajo swing low, TP 1:2, riesgo 1%."
    )
    result = ContentQualityFilter(session=None).score_chunk(_chunk(text))

    assert result.filtered_out is False
    assert result.usefulness_score >= 0.42
    assert "strategy_structure" in result.flags
    assert "trading_concepts" in result.flags


def test_quality_filter_rejects_promotional_noise() -> None:
    text = (
        "Unete al grupo VIP premium con descuento, señales gratis y link en Telegram. "
        "Escribeme por WhatsApp para la promocion limitada y bono especial."
    )
    result = ContentQualityFilter(session=None).score_chunk(_chunk(text))

    assert result.filtered_out is True
    assert result.quality_label == "reject_spam"


def test_quality_filter_rejects_semantic_duplicate() -> None:
    text = (
        "Setup XAUUSD M15 con order block, entrada despues de BOS, SL bajo el minimo y TP 1:2. "
        "Gestion de riesgo fija al 1% por operacion."
    )
    service = ContentQualityFilter(session=None)
    first = service.score_chunk(_chunk(text, 1), seen_signatures={}, kept_fingerprints=[])

    seen = {}
    kept = []
    assert service.score_chunk(_chunk(text, 1), seen_signatures=seen, kept_fingerprints=kept).filtered_out is False
    second = service.score_chunk(_chunk(text, 2), seen_signatures=seen, kept_fingerprints=kept)

    assert first.filtered_out is False
    assert second.filtered_out is True
    assert "exact_duplicate" in second.flags


def test_quality_filter_preserves_catalog_chunks() -> None:
    chunk = _chunk("Cataloged Telegram resource: MES_1.part1.rar category: generic priority: low", 3)
    chunk.source_type = "cataloged_file"

    result = ContentQualityFilter(session=None).score_chunk(chunk)

    assert result.filtered_out is False
    assert result.quality_label == "catalog_preserved"
    assert "knowledge_preservation" in result.flags
