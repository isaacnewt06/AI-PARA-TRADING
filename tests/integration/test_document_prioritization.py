from __future__ import annotations

from src.application.process_cataloged_assets import CatalogedAssetProcessingService
from src.core.config import get_settings, reload_settings
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.models.telegram_message import TelegramMessage
from src.db.session import init_db, session_scope


def test_rank_and_process_top_documents(tmp_path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'document_priority.db').as_posix()}",
        }
    )
    init_db()
    settings = get_settings()

    high_value_path = tmp_path / "high_value.txt"
    high_value_path.write_text(
        (
            "ICT strategy notes. BOS, FVG, liquidity sweep, London session, M15. "
            "Entry after confirmation engulfing. SL below swing low. TP 1:3. Risk 1%."
        ),
        encoding="utf-8",
    )
    low_value_path = tmp_path / "motivation.txt"
    low_value_path.write_text("Mindset motivation premium success discipline dream big.", encoding="utf-8")

    with session_scope() as session:
        channel = Channel(
            telegram_channel_id=-1002397614732,
            title="Cursos de Trading GRATIS",
            normalized_name="cursos_de_trading_gratis",
            input_reference="https://t.me/tradingcursosgratiss",
            is_active=True,
        )
        session.add(channel)
        session.flush()

        message_1 = TelegramMessage(
            channel_id=channel.id,
            telegram_message_id=1,
            content_type="document",
            text="Curso con BOS FVG y reglas claras",
            has_media=True,
        )
        message_2 = TelegramMessage(
            channel_id=channel.id,
            telegram_message_id=2,
            content_type="document",
            text="Motivacion trader premium",
            has_media=True,
        )
        session.add_all([message_1, message_2])
        session.flush()

        high_value = FileAsset(
            channel_id=channel.id,
            message_id=message_1.id,
            category="document",
            file_name="high_value.txt",
            extension=".txt",
            stored_path=str(high_value_path),
            size_bytes=high_value_path.stat().st_size,
            status="downloaded",
            processing_status="downloaded",
        )
        low_value = FileAsset(
            channel_id=channel.id,
            message_id=message_2.id,
            category="document",
            file_name="motivation.txt",
            extension=".txt",
            stored_path=str(low_value_path),
            size_bytes=low_value_path.stat().st_size,
            status="downloaded",
            processing_status="downloaded",
        )
        session.add_all([high_value, low_value])
        session.flush()

        service = CatalogedAssetProcessingService(session, settings)
        ranked = service.rank_documents(limit=2)

        assert ranked[0]["file_name"] == "high_value.txt"
        assert ranked[0]["priority_score"] > ranked[1]["priority_score"]

        summary = service.process_top_documents(limit=1)
        session.flush()
        session.expire_all()

        assert summary["processed"] == 1
        refreshed = session.get(FileAsset, high_value.id)
        assert refreshed is not None
        assert refreshed.document is not None
        assert refreshed.status == "processed"

        low_value_refreshed = session.get(FileAsset, low_value.id)
        assert low_value_refreshed is not None
        assert low_value_refreshed.document is None
