"""Inspect compressed archives without full extraction."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models.file_asset import FileAsset
from src.db.repositories.archive_contents import ArchiveContentRepository
from src.db.repositories.files import FileRepository
from src.processing.archive_groups import multipart_status, parse_archive_part
from src.processing.multipart_archives import ensure_multipart_group_root
from src.processing.rar_support import detect_rar_backend

logger = get_logger(__name__)


DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md", ".csv"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
SCRIPT_EXTENSIONS = {".py", ".mq4", ".mq5", ".ex4", ".ex5", ".js", ".bat", ".ps1", ".sh"}
EXECUTABLE_EXTENSIONS = {".exe", ".msi", ".dll", ".scr", ".apk", ".dmg", ".iso"}
MODULE_DIR_PATTERN = re.compile(r"\b(?:module|modulo|m[oó]dulo|class|clase|lesson|leccion|lección|week|semana|month|mes|session|sesion|sesión)\s*[_-]?\d+\b", re.IGNORECASE)
PEDAGOGICAL_PATTERN = re.compile(
    r"\b(?:intro|introduction|fundamentals|fundamentos|basics|risk management|gestion de riesgo|gestión de riesgo|order block|fvg|fair value gap|liquidity|setup|strategy|estrategia|mentor|masterclass|course|curso|smart money|ict|smc)\b",
    re.IGNORECASE,
)
SOFTWARE_PATTERN = re.compile(
    r"\b(?:indicator|indicador|tool|tools|software|robot|ea|expert advisor|installer|setup\.exe|crack|patched|license|activator)\b",
    re.IGNORECASE,
)
PART_SEQUENCE_PATTERN = re.compile(r"\b(?:part|parte|vol(?:ume)?|disc)\s*[_-]?\d+\b", re.IGNORECASE)


@dataclass(slots=True)
class ArchiveInspectionSummary:
    """Aggregated archive score."""

    file_id: int
    file_name: str
    entries: int
    documents: int
    videos: int
    images: int
    scripts: int
    executables: int
    duplicates: int
    organized_video_dirs: int
    module_like_directories: int
    pedagogical_entries: int
    software_like_entries: int
    part_sequence_hits: int
    internal_structure_score: float
    estimated_value_score: float
    status: str
    archive_group_key: str | None = None
    archive_part_number: int | None = None
    archive_total_parts_estimated: int | None = None
    multipart_group_status: str | None = None
    backend_type: str | None = None
    inspected_via: str | None = None
    notes: str | None = None


class ArchiveInspector:
    """List archive content and rank its knowledge value without extraction."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ArchiveContentRepository(session)
        self.file_repository = FileRepository(session)

    def inspect_file(self, file_asset: FileAsset) -> ArchiveInspectionSummary:
        path = Path(file_asset.stored_path)
        suffix = (file_asset.extension or path.suffix).lower()
        multipart = self._multipart_context(file_asset)
        file_asset.archive_group_key = multipart["group_key"]
        file_asset.archive_part_number = multipart["part_number"]
        file_asset.archive_total_parts_estimated = multipart["total_parts_estimated"]
        file_asset.multipart_group_status = multipart["group_status"]

        if not path.exists():
            summary = self._summary(
                file_asset=file_asset,
                rows=[],
                status="inspection_file_missing",
                notes="Archive file is not present on disk.",
                backend_type=None,
                inspected_via=None,
            )
            return self._persist_summary(file_asset, summary)

        if multipart["is_multipart"] and multipart["group_status"] == "multipart_incomplete":
            summary = self._summary(
                file_asset=file_asset,
                rows=[],
                status="inspection_multipart_incomplete",
                notes=f"Multipart archive group {multipart['group_key']} appears incomplete.",
                backend_type=None,
                inspected_via=None,
            )
            return self._persist_summary(file_asset, summary)

        inspect_path = path
        inspected_via = None
        if multipart["is_multipart"] and multipart["part_number"] not in {None, 1} and multipart["first_part_path"] is not None:
            inspect_path = multipart["first_part_path"]
            inspected_via = inspect_path.name
        if suffix == ".rar" and multipart["is_multipart"]:
            inspect_path = ensure_multipart_group_root(file_asset, self.file_repository)
            inspected_via = inspect_path.name

        try:
            if suffix == ".zip":
                rows = self._inspect_zip(inspect_path, file_asset.id)
                status = "inspection_success"
                notes = None
                backend_type = "zipfile"
            elif suffix in {".rar", ".7z"}:
                rows, notes, status, backend_type = self._inspect_optional(inspect_path, file_asset.id, suffix)
            else:
                rows = []
                status = "inspection_unavailable"
                notes = f"Unsupported archive extension: {suffix}"
                backend_type = None
        except Exception as exc:
            rows = []
            status = "inspection_archive_corrupt"
            notes = str(exc)
            backend_type = None

        if rows and self.session is not None:
            self.repository.replace_for_file(file_asset.id, rows)
        summary = self._summary(
            file_asset=file_asset,
            rows=rows,
            status=status,
            notes=notes,
            backend_type=backend_type,
            inspected_via=inspected_via,
        )
        return self._persist_summary(file_asset, summary)

    def _inspect_zip(self, path: Path, file_id: int) -> list[dict]:
        if not path.exists():
            return []
        try:
            with ZipFile(path) as archive:
                return [self._row(file_id=file_id, name=entry.filename, size=entry.file_size, compressed=entry.compress_size, is_dir=entry.is_dir()) for entry in archive.infolist()]
        except BadZipFile as exc:
            raise ValueError("invalid_zip_archive") from exc

    def _inspect_optional(self, path: Path, file_id: int, suffix: str) -> tuple[list[dict], str | None, str, str | None]:
        if suffix == ".rar":
            try:
                import rarfile
            except ImportError:
                return [], "Install optional dependency 'rarfile' to inspect RAR archives.", "inspection_backend_missing", None
            backend = detect_rar_backend(get_settings(), refresh=True)
            if not backend.available:
                return [], backend.message, "inspection_backend_missing", None
            with rarfile.RarFile(path) as archive:
                return [
                    self._row(file_id=file_id, name=entry.filename, size=entry.file_size, compressed=entry.compress_size, is_dir=entry.isdir())
                    for entry in archive.infolist()
                ], None, "inspection_success", backend.backend_type
        if suffix == ".7z":
            try:
                import py7zr
            except ImportError:
                return [], "Install optional dependency 'py7zr' to inspect 7z archives.", "inspection_backend_missing", None
            with py7zr.SevenZipFile(path) as archive:
                return [
                    self._row(file_id=file_id, name=item.filename, size=getattr(item, "uncompressed", None), compressed=getattr(item, "compressed", None), is_dir=item.is_directory)
                    for item in archive.list()
                ], None, "inspection_success", "py7zr"
        return [], f"Unsupported archive extension: {suffix}", "inspection_unavailable", None

    def _row(self, *, file_id: int, name: str, size: int | None, compressed: int | None, is_dir: bool) -> dict:
        internal_path = name.replace("\\", "/")
        file_name = Path(internal_path).name or internal_path.rstrip("/").split("/")[-1]
        extension = Path(file_name).suffix.lower() or None
        content_kind = self.kind_for_extension(extension, is_dir=is_dir)
        duplicate_key = f"{file_name.lower()}:{size}" if not is_dir else None
        return {
            "file_id": file_id,
            "internal_path": internal_path,
            "file_name": file_name[:255],
            "extension": extension,
            "content_kind": content_kind,
            "size_bytes": size,
            "compressed_size_bytes": compressed,
            "is_directory": is_dir,
            "duplicate_key": duplicate_key,
            "value_score": self.entry_value_score(content_kind),
        }

    @staticmethod
    def kind_for_extension(extension: str | None, *, is_dir: bool) -> str:
        if is_dir:
            return "directory"
        if extension in DOCUMENT_EXTENSIONS:
            return "document"
        if extension in VIDEO_EXTENSIONS:
            return "video"
        if extension in IMAGE_EXTENSIONS:
            return "image"
        if extension in SCRIPT_EXTENSIONS:
            return "script"
        if extension in EXECUTABLE_EXTENSIONS:
            return "executable"
        return "other"

    @staticmethod
    def entry_value_score(kind: str) -> float:
        return {
            "document": 1.0,
            "video": 0.65,
            "image": 0.35,
            "script": -0.25,
            "executable": -0.8,
            "directory": 0.0,
        }.get(kind, 0.05)

    def _summary(
        self,
        *,
        file_asset: FileAsset,
        rows: list[dict],
        status: str,
        notes: str | None,
        backend_type: str | None = None,
        inspected_via: str | None = None,
    ) -> ArchiveInspectionSummary:
        counts = Counter(row["content_kind"] for row in rows)
        duplicate_counts = Counter(row["duplicate_key"] for row in rows if row.get("duplicate_key"))
        duplicates = sum(count - 1 for count in duplicate_counts.values() if count > 1)
        organized_video_dirs = self._organized_video_dirs(rows)
        module_like_directories = self._module_like_directories(rows)
        pedagogical_entries = sum(1 for row in rows if PEDAGOGICAL_PATTERN.search(row["internal_path"]))
        software_like_entries = sum(1 for row in rows if SOFTWARE_PATTERN.search(row["internal_path"]))
        part_sequence_hits = sum(1 for row in rows if PART_SEQUENCE_PATTERN.search(row["internal_path"]))
        internal_structure_score = min(
            1.0,
            module_like_directories * 0.18
            + organized_video_dirs * 0.22
            + min(0.25, pedagogical_entries * 0.02)
            + min(0.15, part_sequence_hits * 0.03)
            - min(0.2, software_like_entries * 0.03),
        )
        score = (
            counts["document"] * 2.0
            + counts["video"] * 0.85
            + organized_video_dirs * 1.2
            + module_like_directories * 1.3
            + pedagogical_entries * 0.25
            + counts["image"] * 0.2
            - counts["script"] * 0.35
            - counts["executable"] * 1.5
            - software_like_entries * 0.25
            - duplicates * 0.25
        )
        return ArchiveInspectionSummary(
            file_id=file_asset.id,
            file_name=file_asset.file_name,
            entries=len(rows),
            documents=counts["document"],
            videos=counts["video"],
            images=counts["image"],
            scripts=counts["script"],
            executables=counts["executable"],
            duplicates=duplicates,
            organized_video_dirs=organized_video_dirs,
            module_like_directories=module_like_directories,
            pedagogical_entries=pedagogical_entries,
            software_like_entries=software_like_entries,
            part_sequence_hits=part_sequence_hits,
            internal_structure_score=round(max(0.0, internal_structure_score), 4),
            estimated_value_score=round(score, 4),
            status=status,
            archive_group_key=file_asset.archive_group_key,
            archive_part_number=file_asset.archive_part_number,
            archive_total_parts_estimated=file_asset.archive_total_parts_estimated,
            multipart_group_status=file_asset.multipart_group_status,
            backend_type=backend_type,
            inspected_via=inspected_via,
            notes=notes,
        )

    @staticmethod
    def _organized_video_dirs(rows: list[dict]) -> int:
        directories = Counter()
        for row in rows:
            if row["content_kind"] != "video":
                continue
            parent = str(Path(row["internal_path"]).parent).replace("\\", "/")
            if parent and parent != ".":
                directories[parent] += 1
        return sum(1 for count in directories.values() if count >= 2)

    @staticmethod
    def _module_like_directories(rows: list[dict]) -> int:
        directories = set()
        for row in rows:
            parts = Path(row["internal_path"]).parts[:-1]
            for part in parts:
                normalized = str(part).replace("\\", "/")
                if MODULE_DIR_PATTERN.search(normalized):
                    directories.add(normalized.lower())
        return len(directories)

    def _persist_summary(self, file_asset: FileAsset, summary: ArchiveInspectionSummary) -> ArchiveInspectionSummary:
        if self.session is not None:
            file_asset.notes = json.dumps(asdict(summary), ensure_ascii=False)
            file_asset.processing_status = summary.status
            file_asset.status = summary.status
            self.session.add(file_asset)
            self.session.flush()
        logger.info(
            "Archive inspected file_id=%s status=%s entries=%s score=%s backend=%s",
            file_asset.id,
            summary.status,
            summary.entries,
            summary.estimated_value_score,
            summary.backend_type,
        )
        return summary

    def _multipart_context(self, file_asset: FileAsset) -> dict:
        parsed = parse_archive_part(file_asset.file_name)
        result = {
            "group_key": parsed.group_key,
            "part_number": parsed.part_number,
            "is_multipart": parsed.is_multipart,
            "total_parts_estimated": None,
            "group_status": "single_archive",
            "first_part_path": None,
        }
        if not parsed.is_multipart or self.session is None:
            return result

        group_files = [
            item
            for item in self.session.query(FileAsset).filter(FileAsset.extension == ".rar").all()  # type: ignore[attr-defined]
            if parse_archive_part(item.file_name).group_key == parsed.group_key
        ]
        parts_present = {
            info.part_number
            for item in group_files
            for info in [parse_archive_part(item.file_name)]
            if info.part_number is not None
        }
        total_parts_estimated, group_status = multipart_status(parts_present)
        first_part = next(
            (
                Path(item.stored_path)
                for item in group_files
                if parse_archive_part(item.file_name).part_number == 1 and Path(item.stored_path).exists()
            ),
            None,
        )
        result.update(
            {
                "total_parts_estimated": total_parts_estimated,
                "group_status": group_status,
                "first_part_path": first_part,
            }
        )
        return result
