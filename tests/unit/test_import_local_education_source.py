from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.application.import_local_education_source import LocalEducationImportService
from src.core.config import get_settings, reload_settings
from src.db.models.knowledge import ContentChunk
from src.db.models.telegram_message import TelegramMessage
from src.db.session import init_db, session_scope


def test_import_local_education_imports_relevant_and_skips_personal(tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'local_education.db').as_posix()}",
        }
    )
    settings = get_settings()
    init_db()

    root = tmp_path / "TRADING EDUCATION"
    root.mkdir(parents=True, exist_ok=True)
    (root / "Presentación Clase 13 - Day Trading for Winners I.txt").write_text(
        "Day trading strategy setup with risk reward, tendencia, temporalidades, soporte y resistencia. "
        "Entry, stop loss, take profit and management rules for trading education.",
        encoding="utf-8",
    )
    (root / "COPIA DE CEDULA.txt").write_text("Documento personal de identificación.", encoding="utf-8")

    with session_scope() as session:
        summary = LocalEducationImportService(session, settings, root).run()

    assert summary["files_imported"] == 1
    assert summary["files_skipped_irrelevant"] == 1

    with session_scope() as session:
        messages = list(session.scalars(select(TelegramMessage).order_by(TelegramMessage.id.asc())))
        chunks = list(session.scalars(select(ContentChunk).order_by(ContentChunk.id.asc())))

    assert len(messages) == 1
    assert len(chunks) >= 1
    assert messages[0].content_type == "local_education_document"
    assert chunks[0].source_type == "local_education"
    assert chunks[0].quality_label == "local_education_high_value"
