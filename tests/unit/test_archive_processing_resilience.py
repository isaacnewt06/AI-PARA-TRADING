from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.core.config import get_settings, reload_settings
from src.application.process_cataloged_assets import CatalogedAssetProcessingService


def test_process_archive_payload_continues_when_one_document_fails(tmp_path) -> None:
    service = object.__new__(CatalogedAssetProcessingService)
    service.session = SimpleNamespace(add=lambda obj: None)
    processed: list[str] = []

    good = SimpleNamespace(
        stored_path=str(tmp_path / "good.pdf"),
        file_name="good.pdf",
        status="downloaded",
        processing_status="downloaded",
        notes="",
    )
    bad = SimpleNamespace(
        stored_path=str(tmp_path / "bad.pdf"),
        file_name="bad.pdf",
        status="downloaded",
        processing_status="downloaded",
        notes="",
    )
    Path(good.stored_path).write_text("ok", encoding="utf-8")
    Path(bad.stored_path).write_text("bad", encoding="utf-8")

    service.archive_extractor = SimpleNamespace(extract_documents=lambda file_asset, max_files=12: [good, bad])
    service.document_processor = SimpleNamespace(
        is_supported=lambda path, file_name: True,
        process=lambda extracted: processed.append(extracted.file_name)
        if extracted.file_name == "good.pdf"
        else (_ for _ in ()).throw(ValueError("empty pdf")),
    )

    summary = service._process_archive_payload(
        SimpleNamespace(file_name="MES_X.part1.rar"),
        tmp_path / "dummy.rar",
        "process_now",
    )

    assert "archive_documents_extracted=2" in summary
    assert "archive_documents_processed=1" in summary
    assert "archive_documents_failed=1" in summary
    assert processed == ["good.pdf"]
    assert bad.status == "failed"


def test_process_documents_skips_unsupported_generic_archives(tmp_path) -> None:
    archive = SimpleNamespace(
        stored_path=str(tmp_path / "MES_9.part1.rar"),
        file_name="MES_9.part1.rar",
        status="downloaded",
        processing_status="downloaded",
        notes="",
    )
    Path(archive.stored_path).write_text("rar", encoding="utf-8")

    service = object.__new__(CatalogedAssetProcessingService)
    service.session = SimpleNamespace(add=lambda obj: None, flush=lambda: None)
    service.file_repository = SimpleNamespace(
        list_by_category_status=lambda categories, statuses, limit=None: [archive]
    )
    service.document_processor = SimpleNamespace(
        is_supported=lambda path, file_name: False,
    )
    service._process_document = lambda file_asset: (_ for _ in ()).throw(AssertionError("should not process"))

    summary = service.process_documents()

    assert summary == {"processed": 0, "skipped": 1, "failed": 0}
    assert archive.processing_status == "skipped"


def test_ensure_local_asset_path_reconciles_existing_file_and_marks_downloaded(tmp_path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'reconcile.db').as_posix()}",
        }
    )
    settings = get_settings()
    target = settings.paths.raw_telegram_dir / "cursos_de_trading_gratis" / "videos" / "msg_99"
    target.mkdir(parents=True, exist_ok=True)
    media_path = target / "clase.mp4"
    media_path.write_bytes(b"video")

    file_asset = SimpleNamespace(
        file_name="clase.mp4",
        stored_path=str(tmp_path / "missing" / "clase.mp4"),
        status="skipped",
        notes="",
        category="video",
        message=SimpleNamespace(telegram_message_id=99),
    )

    service = object.__new__(CatalogedAssetProcessingService)
    service.settings = settings
    service.session = SimpleNamespace(add=lambda obj: None)

    resolved = service._ensure_local_asset_path(file_asset)

    assert resolved == media_path
    assert file_asset.status == "downloaded"
    assert str(media_path.resolve()) == file_asset.stored_path
