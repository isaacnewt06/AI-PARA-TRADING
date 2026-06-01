from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from src.application.process_cataloged_assets import ArchiveDownloadOptions, CatalogedAssetProcessingService
from src.core.config import get_settings, reload_settings
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.models.telegram_message import TelegramMessage
from src.db.session import init_db, session_scope


class _FakeClient:
    async def disconnect(self) -> None:
        return None


def _bootstrap_db(tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'archive_downloads.db').as_posix()}",
        }
    )
    init_db()


def _create_message_bundle(session, *, message_id: int = 1):
    channel = session.scalar(select(Channel).where(Channel.input_reference == "https://t.me/tradingcursosgratiss"))
    if channel is None:
        channel = Channel(
            telegram_channel_id=-1002397614732,
            title="Cursos de Trading GRATIS",
            normalized_name="cursos_de_trading_gratis",
            input_reference="https://t.me/tradingcursosgratiss",
            is_active=True,
        )
        session.add(channel)
        session.flush()
    message = TelegramMessage(
        channel_id=channel.id,
        telegram_message_id=message_id,
        content_type="generic",
        text="ICT mentorship month 1",
        has_media=True,
    )
    session.add(message)
    session.flush()
    return channel, message


def test_download_archives_downloads_complete_group(monkeypatch, tmp_path: Path) -> None:
    _bootstrap_db(tmp_path)
    settings = get_settings()
    with session_scope() as session:
        channel, message = _create_message_bundle(session, message_id=11)
        part1 = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name="MES_1.part1.rar",
            extension=".rar",
            stored_path=str(tmp_path / "MES_1.part1.rar"),
            status="cataloged",
            processing_status="cataloged",
            archive_group_key="MES_1",
            archive_part_number=1,
            archive_total_parts_estimated=2,
            multipart_group_status="multipart_complete_observed",
        )
        part2 = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name="MES_1.part2.rar",
            extension=".rar",
            stored_path=str(tmp_path / "MES_1.part2.rar"),
            status="cataloged",
            processing_status="cataloged",
            archive_group_key="MES_1",
            archive_part_number=2,
            archive_total_parts_estimated=2,
            multipart_group_status="multipart_complete_observed",
        )
        session.add_all([part1, part2])
        session.flush()

        service = CatalogedAssetProcessingService(session, settings)
        monkeypatch.setattr(service.archive_selector, "select", lambda limit=1: [SimpleNamespace(file_id=part1.id)])
        monkeypatch.setattr(
            "src.application.process_cataloged_assets.TelegramClientManager.authenticate",
            lambda self: _async_result(_FakeClient()),
        )

        async def _fake_download(*, client, downloader, file_asset):
            Path(file_asset.stored_path).write_bytes(b"rar-bytes")
            file_asset.status = "downloaded"
            file_asset.processing_status = "downloaded"
            session.add(file_asset)
            return True

        monkeypatch.setattr(service, "_download_single_archive_asset", _fake_download)

        summary = service.download_archives(ArchiveDownloadOptions(limit=1))

        assert summary["groups_downloaded"] == 1
        assert summary["files_downloaded"] == 2
        assert Path(part1.stored_path).exists()
        assert Path(part2.stored_path).exists()
        assert part1.status == "downloaded"
        assert part2.status == "downloaded"


def test_download_archives_marks_incomplete_group(monkeypatch, tmp_path: Path) -> None:
    _bootstrap_db(tmp_path)
    settings = get_settings()
    with session_scope() as session:
        channel, message = _create_message_bundle(session, message_id=12)
        part2 = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name="MES_9.part2.rar",
            extension=".rar",
            stored_path=str(tmp_path / "MES_9.part2.rar"),
            status="cataloged",
            processing_status="cataloged",
            archive_group_key="MES_9",
            archive_part_number=2,
            archive_total_parts_estimated=2,
            multipart_group_status="multipart_incomplete",
        )
        session.add(part2)
        session.flush()

        service = CatalogedAssetProcessingService(session, settings)
        monkeypatch.setattr(service.archive_selector, "select", lambda limit=1: [SimpleNamespace(file_id=part2.id)])
        monkeypatch.setattr(
            "src.application.process_cataloged_assets.TelegramClientManager.authenticate",
            lambda self: _async_result(_FakeClient()),
        )

        summary = service.download_archives(
            ArchiveDownloadOptions(limit=1, download_only_complete_groups=True)
        )

        assert summary["groups_partial"] == 1
        assert part2.status == "partial"
        assert part2.processing_status == "partial"


def test_download_archives_marks_failures(monkeypatch, tmp_path: Path) -> None:
    _bootstrap_db(tmp_path)
    settings = get_settings()
    with session_scope() as session:
        channel, message = _create_message_bundle(session, message_id=13)
        archive = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name="MES_2.rar",
            extension=".rar",
            stored_path=str(tmp_path / "MES_2.rar"),
            status="cataloged",
            processing_status="cataloged",
            multipart_group_status="single_archive",
        )
        session.add(archive)
        session.flush()

        service = CatalogedAssetProcessingService(session, settings)
        monkeypatch.setattr(service.archive_selector, "select", lambda limit=1: [SimpleNamespace(file_id=archive.id)])
        monkeypatch.setattr(
            "src.application.process_cataloged_assets.TelegramClientManager.authenticate",
            lambda self: _async_result(_FakeClient()),
        )

        async def _failed_download(*, client, downloader, file_asset):
            return False

        monkeypatch.setattr(service, "_download_single_archive_asset", _failed_download)

        summary = service.download_archives(ArchiveDownloadOptions(limit=1))

        assert summary["groups_failed"] == 1
        assert summary["files_failed"] >= 1
        assert archive.status == "failed"


def test_download_archives_resumes_existing_group(monkeypatch, tmp_path: Path) -> None:
    _bootstrap_db(tmp_path)
    settings = get_settings()
    with session_scope() as session:
        channel, message = _create_message_bundle(session, message_id=14)
        part1_path = tmp_path / "MES_3.part1.rar"
        part1_path.write_bytes(b"existing")
        part1 = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name="MES_3.part1.rar",
            extension=".rar",
            stored_path=str(part1_path),
            status="cataloged",
            processing_status="cataloged",
            archive_group_key="MES_3",
            archive_part_number=1,
            archive_total_parts_estimated=2,
            multipart_group_status="multipart_complete_observed",
        )
        part2 = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name="MES_3.part2.rar",
            extension=".rar",
            stored_path=str(tmp_path / "MES_3.part2.rar"),
            status="cataloged",
            processing_status="cataloged",
            archive_group_key="MES_3",
            archive_part_number=2,
            archive_total_parts_estimated=2,
            multipart_group_status="multipart_complete_observed",
        )
        session.add_all([part1, part2])
        session.flush()

        service = CatalogedAssetProcessingService(session, settings)
        monkeypatch.setattr(service.archive_selector, "select", lambda limit=1: [SimpleNamespace(file_id=part1.id)])
        monkeypatch.setattr(
            "src.application.process_cataloged_assets.TelegramClientManager.authenticate",
            lambda self: _async_result(_FakeClient()),
        )

        calls: list[int] = []

        async def _resume_download(*, client, downloader, file_asset):
            calls.append(file_asset.id)
            Path(file_asset.stored_path).write_bytes(b"new")
            file_asset.status = "downloaded"
            file_asset.processing_status = "downloaded"
            session.add(file_asset)
            return True

        monkeypatch.setattr(service, "_download_single_archive_asset", _resume_download)

        summary = service.download_archives(ArchiveDownloadOptions(limit=1))

        assert summary["groups_downloaded"] == 1
        assert summary["files_reused"] == 1
        assert summary["files_downloaded"] == 1
        assert calls == [part2.id]


async def _async_result(value):
    return value
