from pathlib import Path

from src.db.models.file_asset import FileAsset
from src.processing.archive_inspector import ArchiveInspector
from src.processing.rar_support import RarBackendInfo


class _FakeRarEntry:
    def __init__(self, filename: str, file_size: int = 100, compress_size: int = 50) -> None:
        self.filename = filename
        self.file_size = file_size
        self.compress_size = compress_size

    def isdir(self) -> bool:
        return False


class _FakeRarFile:
    def __init__(self, path) -> None:
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def infolist(self):
        return [_FakeRarEntry("module_1/lesson_1_bos.pdf"), _FakeRarEntry("module_1/video_1.mp4")]


def test_archive_inspector_marks_rar_success(monkeypatch, tmp_path) -> None:
    archive_path = tmp_path / "ICT_month_1.part1.rar"
    archive_path.write_bytes(b"fake")

    monkeypatch.setattr(
        "src.processing.archive_inspector.detect_rar_backend",
        lambda settings, refresh=True: RarBackendInfo(
            available=True,
            backend_type="sevenzip",
            backend_path=r"C:\Program Files\7-Zip\7z.exe",
            source="test",
            message="ok",
        ),
    )
    monkeypatch.setattr("rarfile.RarFile", _FakeRarFile)

    file_asset = FileAsset(
        id=1,
        channel_id=1,
        category="generic",
        file_name=archive_path.name,
        extension=".rar",
        stored_path=str(archive_path),
        status="downloaded",
        processing_status="downloaded",
    )

    inspector = ArchiveInspector(session=None)  # type: ignore[arg-type]
    summary = inspector.inspect_file(file_asset)

    assert summary.status == "inspection_success"
    assert summary.backend_type == "sevenzip"
    assert summary.documents == 1
    assert summary.videos == 1
