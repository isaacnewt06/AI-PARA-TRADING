"""Archive diagnostics for Windows RAR support and multipart readiness."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.db.models.file_asset import FileAsset
from src.processing.archive_groups import parse_archive_part
from src.processing.rar_support import detect_rar_backend


class ArchiveDoctorApplicationService:
    """Diagnose archive tooling and current catalog readiness."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self) -> dict:
        backend = detect_rar_backend(self.settings, refresh=True)
        rar_installed = self._rarfile_installed()
        rar_files = list(self.session.scalars(select(FileAsset).where(FileAsset.extension == ".rar")))
        multipart = [item for item in rar_files if parse_archive_part(item.file_name).is_multipart]
        inspectable = sum(
            1
            for item in rar_files
            if self._inspectable_now(item, backend_available=backend.available, rar_files=rar_files)
        )
        recommendation = self._recommendation(backend_available=backend.available, rar_count=len(rar_files))
        return {
            "rarfile_installed": rar_installed,
            "backend_detected": backend.available,
            "backend_type": backend.backend_type,
            "backend_path": backend.backend_path,
            "backend_message": backend.message,
            "rar_archives_cataloged": len(rar_files),
            "multipart_archives": len(multipart),
            "inspectable_now": inspectable,
            "recommendation": recommendation,
        }

    @staticmethod
    def _rarfile_installed() -> bool:
        try:
            import rarfile  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _recommendation(*, backend_available: bool, rar_count: int) -> str:
        if not backend_available:
            return "Run scripts/setup_rar_support.ps1 or install 7-Zip/WinRAR so inspect-archives can open RAR files."
        if rar_count == 0:
            return "No cataloged RAR files found. Sync the channel first."
        return "RAR backend ready. Run download-archives, inspect-archives, rank-archives, then process-selected-archives."

    @staticmethod
    def _inspectable_now(item: FileAsset, *, backend_available: bool, rar_files: list[FileAsset]) -> bool:
        if not backend_available:
            return False
        parsed = parse_archive_part(item.file_name)
        if not parsed.is_multipart:
            return Path(item.stored_path).exists()
        first_part = next(
            (
                sibling
                for sibling in rar_files
                if parse_archive_part(sibling.file_name).group_key == parsed.group_key
                and parse_archive_part(sibling.file_name).part_number == 1
            ),
            None,
        )
        return first_part is not None and Path(first_part.stored_path).exists()
