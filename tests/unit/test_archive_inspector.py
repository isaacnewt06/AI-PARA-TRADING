from zipfile import ZipFile

from src.db.models.file_asset import FileAsset
from src.processing.archive_inspector import ArchiveInspector


def test_archive_inspector_scores_zip_without_extraction(tmp_path) -> None:
    archive_path = tmp_path / "course.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("module_1/lesson.pdf", b"pdf")
        archive.writestr("module_1/video_01.mp4", b"video")
        archive.writestr("module_1/video_02.mp4", b"video")
        archive.writestr("software/tool.exe", b"exe")

    file_asset = FileAsset(
        id=1,
        channel_id=1,
        category="generic",
        file_name="course.zip",
        extension=".zip",
        stored_path=str(archive_path),
        status="queued",
        priority="low",
        processing_status="queued",
    )

    inspector = ArchiveInspector(session=None)
    rows = inspector._inspect_zip(archive_path, file_id=1)
    summary = inspector._summary(file_asset=file_asset, rows=rows, status="inspected", notes=None)

    assert summary.documents == 1
    assert summary.videos == 2
    assert summary.executables == 1
    assert summary.organized_video_dirs == 1
    assert summary.estimated_value_score > 0


def test_archive_inspector_detects_duplicate_entries(tmp_path) -> None:
    archive_path = tmp_path / "dup.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("a/manual.pdf", b"same")
        archive.writestr("b/manual.pdf", b"same")

    file_asset = FileAsset(
        id=1,
        channel_id=1,
        category="generic",
        file_name="dup.zip",
        extension=".zip",
        stored_path=str(archive_path),
    )
    inspector = ArchiveInspector(session=None)
    rows = inspector._inspect_zip(archive_path, file_id=1)
    summary = inspector._summary(file_asset=file_asset, rows=rows, status="inspected", notes=None)

    assert summary.duplicates == 1
