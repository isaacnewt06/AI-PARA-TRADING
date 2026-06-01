from pathlib import Path

from src.db.models.file_asset import FileAsset
from src.db.models.telegram_message import TelegramMessage
from src.knowledge.document_prioritizer import DocumentPrioritizer, KnowledgeDensityScorer


def test_knowledge_density_scores_rule_rich_text_high() -> None:
    text = (
        "BOS, FVG and liquidity sweep in London session. "
        "Entry on M15 after confirmation engulfing. SL below swing low, TP 1:3."
    )

    score, reasons = KnowledgeDensityScorer.score(text)

    assert score >= 0.75
    assert "sl_tp_present" in reasons
    assert "timeframe_present" in reasons
    assert "context_present" in reasons


def test_document_prioritizer_prefers_strategy_document_over_promo_archive(tmp_path) -> None:
    strategy_path = tmp_path / "smart_money_notes.txt"
    strategy_path.write_text(
        "Curso de estrategia ICT. BOS, FVG, entry, confirmation, London session, SL, TP 1:2, risk 1%.",
        encoding="utf-8",
    )

    strategy_file = FileAsset(
        id=1,
        channel_id=1,
        category="document",
        file_name="smart_money_notes.txt",
        extension=".txt",
        stored_path=str(strategy_path),
        size_bytes=strategy_path.stat().st_size,
    )
    strategy_file.message = TelegramMessage(channel_id=1, telegram_message_id=100, content_type="document", text="Curso BOS FVG con reglas")
    strategy_file.notes = "BOS FVG London SL TP risk"

    archive_file = FileAsset(
        id=2,
        channel_id=1,
        category="generic",
        file_name="vip_premium_indicators.rar",
        extension=".rar",
        stored_path=str(tmp_path / "vip_premium_indicators.rar"),
        size_bytes=2 * 1024 * 1024 * 1024,
        notes="VIP premium indicator package with cracked software",
    )
    archive_file.message = TelegramMessage(channel_id=1, telegram_message_id=101, content_type="generic", text="Promo VIP premium")

    prioritizer = DocumentPrioritizer(session=None)  # type: ignore[arg-type]
    strategy_result = prioritizer.score_file(strategy_file)
    archive_result = prioritizer.score_file(archive_file)

    assert strategy_result.priority_score > archive_result.priority_score
    assert strategy_result.processable_now is True
    assert archive_result.processable_now is False
    assert strategy_result.knowledge_density_score > archive_result.knowledge_density_score
