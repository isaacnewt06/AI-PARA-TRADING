from __future__ import annotations

from src.application.archive_doctor import ArchiveDoctorApplicationService
from src.core.config import get_settings, reload_settings
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.models.telegram_message import TelegramMessage
from src.db.session import init_db, session_scope
from src.processing.rar_support import RarBackendInfo


def test_doctor_archives_reports_backend_and_multipart(monkeypatch, tmp_path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'doctor_archives.db').as_posix()}",
        }
    )
    init_db()
    settings = get_settings()
    monkeypatch.setattr(
        "src.application.archive_doctor.detect_rar_backend",
        lambda settings, refresh=True: RarBackendInfo(
            available=True,
            backend_type="sevenzip",
            backend_path=r"C:\Program Files\7-Zip\7z.exe",
            source="test",
            message="ok",
        ),
    )

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
        message = TelegramMessage(channel_id=channel.id, telegram_message_id=1, content_type="generic", text="RAR set", has_media=True)
        session.add(message)
        session.flush()
        session.add_all(
            [
                FileAsset(
                    channel_id=channel.id,
                    message_id=message.id,
                    category="generic",
                    file_name="MES_1.part1.rar",
                    extension=".rar",
                    stored_path=str(tmp_path / "MES_1.part1.rar"),
                    multipart_group_status="multipart_complete_observed",
                ),
                FileAsset(
                    channel_id=channel.id,
                    message_id=message.id,
                    category="generic",
                    file_name="MES_1.part2.rar",
                    extension=".rar",
                    stored_path=str(tmp_path / "MES_1.part2.rar"),
                    multipart_group_status="multipart_complete_observed",
                ),
            ]
        )
        (tmp_path / "MES_1.part1.rar").write_text("stub", encoding="utf-8")
        (tmp_path / "MES_1.part2.rar").write_text("stub", encoding="utf-8")
        session.flush()

        result = ArchiveDoctorApplicationService(session, settings).run()

        assert result["backend_detected"] is True
        assert result["rar_archives_cataloged"] == 2
        assert result["multipart_archives"] == 2
        assert result["inspectable_now"] == 2


def test_doctor_archives_requires_local_first_part(monkeypatch, tmp_path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'doctor_archives_missing.db').as_posix()}",
        }
    )
    init_db()
    settings = get_settings()
    monkeypatch.setattr(
        "src.application.archive_doctor.detect_rar_backend",
        lambda settings, refresh=True: RarBackendInfo(
            available=True,
            backend_type="sevenzip",
            backend_path=r"C:\Program Files\7-Zip\7z.exe",
            source="test",
            message="ok",
        ),
    )

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
        message = TelegramMessage(channel_id=channel.id, telegram_message_id=2, content_type="generic", text="RAR set", has_media=True)
        session.add(message)
        session.flush()
        session.add_all(
            [
                FileAsset(
                    channel_id=channel.id,
                    message_id=message.id,
                    category="generic",
                    file_name="MES_9.part1.rar",
                    extension=".rar",
                    stored_path=str(tmp_path / "MES_9.part1.rar"),
                    multipart_group_status="multipart_complete_observed",
                ),
                FileAsset(
                    channel_id=channel.id,
                    message_id=message.id,
                    category="generic",
                    file_name="MES_9.part2.rar",
                    extension=".rar",
                    stored_path=str(tmp_path / "MES_9.part2.rar"),
                    multipart_group_status="multipart_complete_observed",
                ),
            ]
        )
        (tmp_path / "MES_9.part2.rar").write_text("stub", encoding="utf-8")
        session.flush()

        result = ArchiveDoctorApplicationService(session, settings).run()

        assert result["inspectable_now"] == 0
