from __future__ import annotations

import json
from zipfile import ZipFile

from sqlalchemy import select

from src.application.inspect_archives import ArchiveInspectionApplicationService
from src.core.config import reload_settings
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.models.telegram_message import TelegramMessage
from src.db.session import init_db, session_scope


def _bootstrap_archive_db(tmp_path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'archive_selection.db').as_posix()}",
        }
    )
    init_db()


def _create_channel_with_message(session, *, message_text: str, message_id: int):
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
        text=message_text,
        has_media=True,
    )
    session.add(message)
    session.flush()
    return channel, message


def test_archive_selection_scores_document_bundle_high(tmp_path) -> None:
    _bootstrap_archive_db(tmp_path)
    archive_path = tmp_path / "ICT_mentorship_month_1.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("module_1/lesson_1_intro.pdf", b"pdf")
        archive.writestr("module_1/risk_management.docx", b"doc")
        archive.writestr("module_2/order_blocks.pdf", b"pdf")

    with session_scope() as session:
        channel, message = _create_channel_with_message(
            session,
            message_text="Curso completo smart money con BOS, FVG y risk management.",
            message_id=1,
        )
        file_asset = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name=archive_path.name,
            extension=".zip",
            stored_path=str(archive_path),
            size_bytes=archive_path.stat().st_size,
            status="downloaded",
            processing_status="downloaded",
        )
        session.add(file_asset)
        session.flush()

        service = ArchiveInspectionApplicationService(session)
        service.inspect(limit=10)
        ranked = service.rank(limit=10)
        top = next(item for item in ranked if item["file_id"] == file_asset.id)

        assert top["archive_usefulness_label"] in {"high_value_course", "likely_document_bundle"}
        assert top["archive_processing_recommendation"] == "process_now"
        assert top["archive_selection_score"] >= 0.6


def test_archive_selection_scores_organized_video_course(tmp_path) -> None:
    _bootstrap_archive_db(tmp_path)
    archive_path = tmp_path / "SMC_masterclass_videos.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("module_1/lesson_1_intro.mp4", b"video")
        archive.writestr("module_1/lesson_2_liquidity.mp4", b"video")
        archive.writestr("module_2/lesson_3_fvg.mp4", b"video")
        archive.writestr("module_2/lesson_4_bos.mp4", b"video")
        archive.writestr("module_3/lesson_5_setup.mp4", b"video")

    with session_scope() as session:
        channel, message = _create_channel_with_message(
            session,
            message_text="Mega carpeta de videos organizada por modulos del curso SMC.",
            message_id=2,
        )
        file_asset = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name=archive_path.name,
            extension=".zip",
            stored_path=str(archive_path),
            size_bytes=archive_path.stat().st_size,
            status="downloaded",
            processing_status="downloaded",
        )
        session.add(file_asset)
        session.flush()

        service = ArchiveInspectionApplicationService(session)
        service.inspect(limit=10)
        ranked = service.rank(limit=10)
        row = next(item for item in ranked if item["file_id"] == file_asset.id)

        assert row["archive_usefulness_label"] in {"likely_video_course", "mixed_educational", "high_value_course"}
        assert row["archive_selection_score"] >= 0.45
        assert row["archive_processing_recommendation"] in {"process_videos_later", "inspect_first"}


def test_archive_selection_penalizes_software_archives(tmp_path) -> None:
    _bootstrap_archive_db(tmp_path)
    archive_path = tmp_path / "indicator_pack_crack.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("setup.exe", b"exe")
        archive.writestr("license.dll", b"dll")
        archive.writestr("indicator.ex4", b"ind")

    with session_scope() as session:
        channel, message = _create_channel_with_message(
            session,
            message_text="Pack de indicadores crack y software premium.",
            message_id=3,
        )
        file_asset = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name=archive_path.name,
            extension=".zip",
            stored_path=str(archive_path),
            size_bytes=archive_path.stat().st_size,
            status="downloaded",
            processing_status="downloaded",
        )
        session.add(file_asset)
        session.flush()

        service = ArchiveInspectionApplicationService(session)
        service.inspect(limit=10)
        ranked = service.rank(limit=10)
        row = next(item for item in ranked if item["file_id"] == file_asset.id)

        assert row["archive_usefulness_label"] == "tooling_or_software"
        assert row["archive_processing_recommendation"] == "skip_for_now"
        assert row["archive_selection_score"] <= 0.2


def test_archive_selection_detects_duplicate_clusters(tmp_path) -> None:
    _bootstrap_archive_db(tmp_path)
    archive_a = tmp_path / "ICT_month_1_part1.zip"
    archive_b = tmp_path / "ICT_month_1_copy.zip"
    for path in [archive_a, archive_b]:
        with ZipFile(path, "w") as archive:
            archive.writestr("module_1/lesson_1_intro.pdf", b"pdf")
            archive.writestr("module_1/lesson_2_bos.pdf", b"pdf")
            archive.writestr("module_2/lesson_3_fvg.pdf", b"pdf")

    with session_scope() as session:
        channel, message_1 = _create_channel_with_message(
            session,
            message_text="Curso ICT month 1.",
            message_id=4,
        )
        _, message_2 = _create_channel_with_message(
            session,
            message_text="Copia del mismo curso ICT month 1.",
            message_id=5,
        )
        files = [
            FileAsset(
                channel_id=channel.id,
                message_id=message_1.id,
                category="generic",
                file_name=archive_a.name,
                extension=".zip",
                stored_path=str(archive_a),
                size_bytes=archive_a.stat().st_size,
                status="downloaded",
                processing_status="downloaded",
            ),
            FileAsset(
                channel_id=channel.id,
                message_id=message_2.id,
                category="generic",
                file_name=archive_b.name,
                extension=".zip",
                stored_path=str(archive_b),
                size_bytes=archive_b.stat().st_size,
                status="downloaded",
                processing_status="downloaded",
            ),
        ]
        session.add_all(files)
        session.flush()

        service = ArchiveInspectionApplicationService(session)
        service.inspect(limit=10)
        ranked = service.rank(limit=10)
        duplicate_rows = [item for item in ranked if item["file_id"] in {files[0].id, files[1].id}]

        assert all(row["duplicate_confidence"] >= 0.72 for row in duplicate_rows)
        assert all(row["duplicate_cluster_id"] for row in duplicate_rows)
        assert any(row["archive_usefulness_label"] == "duplicate_or_low_value" for row in duplicate_rows)


def test_archive_selection_marks_unavailable_as_manual_review(tmp_path) -> None:
    _bootstrap_archive_db(tmp_path)

    with session_scope() as session:
        channel, message = _create_channel_with_message(
            session,
            message_text="RAR de origen desconocido.",
            message_id=6,
        )
        file_asset = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name="unknown_bundle.rar",
            extension=".rar",
            stored_path=str(tmp_path / "unknown_bundle.rar"),
            size_bytes=1234,
            status="inspection_unavailable",
            processing_status="inspection_unavailable",
            notes=json.dumps(
                {
                    "file_id": 999,
                    "file_name": "unknown_bundle.rar",
                    "entries": 0,
                    "documents": 0,
                    "videos": 0,
                    "images": 0,
                    "scripts": 0,
                    "executables": 0,
                    "duplicates": 0,
                    "organized_video_dirs": 0,
                    "module_like_directories": 0,
                    "pedagogical_entries": 0,
                    "software_like_entries": 0,
                    "part_sequence_hits": 0,
                    "internal_structure_score": 0.0,
                    "estimated_value_score": 0.0,
                    "status": "inspection_unavailable",
                    "notes": "missing backend",
                },
                ensure_ascii=False,
            ),
        )
        session.add(file_asset)
        session.flush()

        service = ArchiveInspectionApplicationService(session)
        ranked = service.rank(limit=10)
        row = next(item for item in ranked if item["file_id"] == file_asset.id)

        assert row["archive_usefulness_label"] == "unknown_needs_manual_review"
        assert row["archive_processing_recommendation"] == "manual_review"


def test_archive_selection_uses_external_signals_without_inspection(tmp_path) -> None:
    _bootstrap_archive_db(tmp_path)

    with session_scope() as session:
        channel, message = _create_channel_with_message(
            session,
            message_text="ICT mentorship month 1 curso completo smart money.",
            message_id=66,
        )
        file_asset = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="generic",
            file_name="MES_1.part1.rar",
            extension=".rar",
            stored_path=str(tmp_path / "MES_1.part1.rar"),
            size_bytes=500 * 1024 * 1024,
            status="inspection_backend_missing",
            processing_status="inspection_backend_missing",
            archive_group_key="MES_1",
            archive_part_number=1,
            archive_total_parts_estimated=2,
            multipart_group_status="multipart_complete_observed",
            notes=json.dumps(
                {
                    "file_id": 1,
                    "file_name": "MES_1.part1.rar",
                    "entries": 0,
                    "documents": 0,
                    "videos": 0,
                    "images": 0,
                    "scripts": 0,
                    "executables": 0,
                    "duplicates": 0,
                    "organized_video_dirs": 0,
                    "module_like_directories": 0,
                    "pedagogical_entries": 0,
                    "software_like_entries": 0,
                    "part_sequence_hits": 0,
                    "internal_structure_score": 0.0,
                    "estimated_value_score": 0.0,
                    "status": "inspection_backend_missing",
                    "notes": "backend missing",
                },
                ensure_ascii=False,
            ),
        )
        session.add(file_asset)
        session.flush()

        service = ArchiveInspectionApplicationService(session)
        ranked = service.rank(limit=10)
        row = next(item for item in ranked if item["file_id"] == file_asset.id)

        assert row["archive_selection_score"] > 0.0
        assert row["support_summary"]["external_archive_bonus"] > 0.0


def test_select_archives_orders_best_candidates_first(tmp_path) -> None:
    _bootstrap_archive_db(tmp_path)
    course_archive = tmp_path / "curso_smart_money.zip"
    software_archive = tmp_path / "tool_pack.zip"
    with ZipFile(course_archive, "w") as archive:
        archive.writestr("module_1/risk_management.pdf", b"pdf")
        archive.writestr("module_2/liquidity.pdf", b"pdf")
        archive.writestr("module_3/fvg.pdf", b"pdf")
    with ZipFile(software_archive, "w") as archive:
        archive.writestr("setup.exe", b"exe")
        archive.writestr("license.dll", b"dll")

    with session_scope() as session:
        channel, course_message = _create_channel_with_message(
            session,
            message_text="Curso completo trading strategy con BOS y FVG.",
            message_id=7,
        )
        _, software_message = _create_channel_with_message(
            session,
            message_text="Pack de software premium.",
            message_id=8,
        )
        course_file = FileAsset(
            channel_id=channel.id,
            message_id=course_message.id,
            category="generic",
            file_name=course_archive.name,
            extension=".zip",
            stored_path=str(course_archive),
            size_bytes=course_archive.stat().st_size,
            status="downloaded",
            processing_status="downloaded",
        )
        software_file = FileAsset(
            channel_id=channel.id,
            message_id=software_message.id,
            category="generic",
            file_name=software_archive.name,
            extension=".zip",
            stored_path=str(software_archive),
            size_bytes=software_archive.stat().st_size,
            status="downloaded",
            processing_status="downloaded",
        )
        session.add_all([course_file, software_file])
        session.flush()

        service = ArchiveInspectionApplicationService(session)
        service.inspect(limit=20)
        selected = service.select(limit=10)

        assert selected
        assert selected[0]["file_name"] == course_archive.name
        explanation = service.explain(course_archive.name)
        assert explanation is not None
        assert "recommendation=" in explanation["archive_selection_reason"]


def test_select_archives_prefers_part1_for_multipart_group(tmp_path) -> None:
    _bootstrap_archive_db(tmp_path)

    with session_scope() as session:
        channel, message = _create_channel_with_message(
            session,
            message_text="ICT mentorship month 1 curso completo smart money.",
            message_id=88,
        )
        session.add_all(
            [
                FileAsset(
                    channel_id=channel.id,
                    message_id=message.id,
                    category="generic",
                    file_name="MES_1.part1.rar",
                    extension=".rar",
                    stored_path=str(tmp_path / "MES_1.part1.rar"),
                    size_bytes=500 * 1024 * 1024,
                    status="inspection_file_missing",
                    processing_status="inspection_file_missing",
                    archive_group_key="MES_1",
                    archive_part_number=1,
                    archive_total_parts_estimated=2,
                    multipart_group_status="multipart_complete_observed",
                    notes=json.dumps(
                        {
                            "file_id": 1,
                            "file_name": "MES_1.part1.rar",
                            "entries": 0,
                            "documents": 0,
                            "videos": 0,
                            "images": 0,
                            "scripts": 0,
                            "executables": 0,
                            "duplicates": 0,
                            "organized_video_dirs": 0,
                            "module_like_directories": 0,
                            "pedagogical_entries": 0,
                            "software_like_entries": 0,
                            "part_sequence_hits": 0,
                            "internal_structure_score": 0.0,
                            "estimated_value_score": 0.0,
                            "status": "inspection_file_missing",
                            "notes": "missing file",
                        },
                        ensure_ascii=False,
                    ),
                ),
                FileAsset(
                    channel_id=channel.id,
                    message_id=message.id,
                    category="generic",
                    file_name="MES_1.part2.rar",
                    extension=".rar",
                    stored_path=str(tmp_path / "MES_1.part2.rar"),
                    size_bytes=500 * 1024 * 1024,
                    status="inspection_file_missing",
                    processing_status="inspection_file_missing",
                    archive_group_key="MES_1",
                    archive_part_number=2,
                    archive_total_parts_estimated=2,
                    multipart_group_status="multipart_complete_observed",
                    notes=json.dumps(
                        {
                            "file_id": 2,
                            "file_name": "MES_1.part2.rar",
                            "entries": 0,
                            "documents": 0,
                            "videos": 0,
                            "images": 0,
                            "scripts": 0,
                            "executables": 0,
                            "duplicates": 0,
                            "organized_video_dirs": 0,
                            "module_like_directories": 0,
                            "pedagogical_entries": 0,
                            "software_like_entries": 0,
                            "part_sequence_hits": 0,
                            "internal_structure_score": 0.0,
                            "estimated_value_score": 0.0,
                            "status": "inspection_file_missing",
                            "notes": "missing file",
                        },
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
        session.flush()

        service = ArchiveInspectionApplicationService(session)
        selected = service.select(limit=1)

        assert selected
        assert selected[0]["file_name"] == "MES_1.part1.rar"
