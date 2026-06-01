from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.application.import_manual_knowledge import ManualKnowledgeImportService
from src.core.config import get_settings, reload_settings
from src.db.models.knowledge import ContentChunk
from src.db.models.telegram_message import TelegramMessage
from src.db.session import init_db, session_scope


def test_manual_knowledge_import_creates_message_and_chunk(tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'manual_import.db').as_posix()}",
        }
    )
    init_db()
    root = tmp_path / "manual"
    root.mkdir(parents=True, exist_ok=True)
    note = root / "ob_rejection.md"
    note.write_text("# OB Rejection\nHTF bias H1\norder block\nRR 1:2\n", encoding="utf-8")

    with session_scope() as session:
        summary = ManualKnowledgeImportService(session, root).run()
        assert summary["manual_notes_imported"] == 1
        assert summary["chunks_created"] == 1

    with session_scope() as session:
        message = session.scalar(select(TelegramMessage))
        chunk = session.scalar(select(ContentChunk))
        assert message is not None
        assert chunk is not None
        assert chunk.source_type == "manual_note"
        assert chunk.quality_label == "manual_high_value"
        assert chunk.filtered_out is False
        assert chunk.file_name == "ob_rejection.md"
