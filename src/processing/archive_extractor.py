"""Controlled extraction of document-like files from selected archives."""

from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.core.paths import sanitize_filesystem_name
from src.db.models.file_asset import FileAsset
from src.db.repositories.files import FileRepository
from src.processing.archive_groups import parse_archive_part
from src.processing.multipart_archives import ensure_multipart_group_root
from src.processing.rar_support import detect_rar_backend

DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".xlsm", ".txt", ".md", ".csv", ".tsv"}
logger = get_logger(__name__)


class ArchiveDocumentExtractor:
    """Extract supported educational documents from selected archives."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.file_repository = FileRepository(session)

    def extract_documents(self, file_asset: FileAsset, max_files: int = 12) -> list[FileAsset]:
        archive_path = Path(file_asset.stored_path)
        extension = (file_asset.extension or archive_path.suffix).lower()
        destination_root = self.settings.paths.processed_dir / "archive_extracted" / f"archive_{file_asset.id}"
        destination_root.mkdir(parents=True, exist_ok=True)

        if extension == ".zip":
            extracted_paths = self._extract_zip(archive_path, destination_root, max_files=max_files)
        elif extension == ".rar":
            extracted_paths = self._extract_rar(file_asset, destination_root, max_files=max_files)
        elif extension == ".7z":
            extracted_paths = self._extract_7z(archive_path, destination_root, max_files=max_files)
        else:
            extracted_paths = []

        result: list[FileAsset] = []
        for path in extracted_paths:
            if not path.exists() or path.stat().st_size <= 0:
                logger.warning("Skipping empty extracted document path=%s archive=%s", path, file_asset.file_name)
                path.unlink(missing_ok=True)
                continue
            payload = {
                "channel_id": file_asset.channel_id,
                "message_id": file_asset.message_id,
                "category": "document",
                "file_name": path.name,
                "extension": path.suffix.lower(),
                "stored_path": str(path.resolve()),
                "mime_type": None,
                "size_bytes": path.stat().st_size if path.exists() else None,
                "file_hash": None,
                "telegram_file_id": None,
                "status": "downloaded",
                "priority": "high",
                "processing_status": "downloaded",
                "notes": f"Extracted from archive file_id={file_asset.id} source={file_asset.file_name}",
            }
            entity, _ = self.file_repository.upsert_discovered(payload)
            result.append(entity)
        return result

    def _extract_zip(self, archive_path: Path, destination_root: Path, *, max_files: int) -> list[Path]:
        extracted: list[Path] = []
        with ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                if len(extracted) >= max_files:
                    break
                internal_path = Path(entry.filename)
                if internal_path.suffix.lower() not in DOCUMENT_EXTENSIONS:
                    continue
                target = self._safe_target(destination_root, internal_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
                extracted.append(target)
        return extracted

    def _extract_rar(self, file_asset: FileAsset, destination_root: Path, *, max_files: int) -> list[Path]:
        import rarfile

        backend = detect_rar_backend(self.settings, refresh=True)
        if not backend.available:
            return []
        archive_path = self._rar_root_path(file_asset)
        extracted: list[Path] = []
        with rarfile.RarFile(archive_path) as archive:
            for entry in archive.infolist():
                if entry.isdir():
                    continue
                if len(extracted) >= max_files:
                    break
                internal_path = Path(entry.filename)
                if internal_path.suffix.lower() not in DOCUMENT_EXTENSIONS:
                    continue
                target = self._safe_target(destination_root, internal_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
                extracted.append(target)
        return extracted

    def _extract_7z(self, archive_path: Path, destination_root: Path, *, max_files: int) -> list[Path]:
        import py7zr

        extracted: list[Path] = []
        with py7zr.SevenZipFile(archive_path) as archive:
            names = [
                name
                for name in archive.getnames()
                if Path(name).suffix.lower() in DOCUMENT_EXTENSIONS
            ][:max_files]
            if not names:
                return []
            archive.extract(path=destination_root, targets=names)
        for name in names:
            target = self._safe_target(destination_root, Path(name))
            if target.exists():
                extracted.append(target)
        return extracted

    def _rar_root_path(self, file_asset: FileAsset) -> Path:
        return ensure_multipart_group_root(file_asset, self.file_repository)

    @staticmethod
    def _safe_target(destination_root: Path, internal_path: Path) -> Path:
        parts = [sanitize_filesystem_name(part, fallback="item") for part in internal_path.parts[:-1]]
        file_name = sanitize_filesystem_name(internal_path.name, fallback="document")
        target = destination_root
        for part in parts:
            target = target / part
        return target / file_name
