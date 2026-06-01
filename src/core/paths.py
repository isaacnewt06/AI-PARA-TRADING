"""Workspace path management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


@dataclass(slots=True)
class ProjectPaths:
    """Centralized path resolver for the project."""

    root: Path
    data_dir: Path
    logs_dir: Path
    config_dir: Path
    docs_dir: Path
    scripts_dir: Path
    src_dir: Path
    tests_dir: Path

    @property
    def raw_telegram_dir(self) -> Path:
        return self.data_dir / "raw" / "telegram"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def summaries_dir(self) -> Path:
        return self.data_dir / "summaries"

    @property
    def knowledge_dir(self) -> Path:
        return self.data_dir / "knowledge"

    @property
    def vector_store_dir(self) -> Path:
        return self.data_dir / "vector_store"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def paper_trading_dir(self) -> Path:
        return self.data_dir / "paper_trading"

    def ensure(self) -> None:
        """Create all required directories."""
        for path in (
            self.data_dir,
            self.logs_dir,
            self.config_dir,
            self.docs_dir,
            self.scripts_dir,
            self.src_dir,
            self.tests_dir,
            self.raw_telegram_dir,
            self.processed_dir,
            self.transcripts_dir,
            self.summaries_dir,
            self.knowledge_dir,
            self.vector_store_dir,
            self.sessions_dir,
            self.paper_trading_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def channel_dir(self, channel_name: str) -> Path:
        base = self.raw_telegram_dir / self._slug(channel_name)
        for folder in ("messages", "documents", "videos", "audios", "images", "generic"):
            (base / folder).mkdir(parents=True, exist_ok=True)
        return base

    def media_dir(self, channel_name: str, content_type: str) -> Path:
        base = self.channel_dir(channel_name)
        mapping = {
            "document": "documents",
            "video": "videos",
            "audio": "audios",
            "image": "images",
            "message": "messages",
        }
        subdir = mapping.get(content_type, "generic")
        target = base / subdir
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _slug(value: str) -> str:
        return sanitize_filesystem_name(value, fallback="unknown_channel")


def build_project_paths(root: Path, data_dir: Path | None = None) -> ProjectPaths:
    """Build a `ProjectPaths` instance from the repository root."""
    return ProjectPaths(
        root=root,
        data_dir=(data_dir or root / "data").resolve(),
        logs_dir=(root / "logs").resolve(),
        config_dir=(root / "config").resolve(),
        docs_dir=(root / "docs").resolve(),
        scripts_dir=(root / "scripts").resolve(),
        src_dir=(root / "src").resolve(),
        tests_dir=(root / "tests").resolve(),
    )


def sanitize_filesystem_name(value: str, fallback: str = "item", max_length: int = 120) -> str:
    """Sanitize names for Windows and POSIX filesystems."""
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value.strip())
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip(" ._")
    if not normalized:
        normalized = fallback
    if normalized.upper() in WINDOWS_RESERVED_NAMES:
        normalized = f"{normalized}_file"
    if len(normalized) > max_length:
        normalized = normalized[:max_length].rstrip(" ._")
    return normalized or fallback
