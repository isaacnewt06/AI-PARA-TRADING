"""Cataloging helpers for heavy Telegram channels."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

PROCESSING_STATES = {
    "discovered",
    "cataloged",
    "queued",
    "downloading",
    "downloaded",
    "extracted",
    "transcribed",
    "indexed",
    "skipped",
    "failed",
    "external_pending",
}

HIGH_PRIORITY_EXTENSIONS = {".pdf", ".docx", ".doc", ".ppt", ".pptx", ".xlsx", ".xlsm", ".txt", ".md", ".csv"}
MEDIUM_PRIORITY_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".mp3", ".wav", ".m4a", ".ogg", ".jpg", ".jpeg", ".png", ".webp"}
LOW_PRIORITY_EXTENSIONS = {".zip", ".rar", ".7z", ".exe", ".msi", ".iso", ".apk", ".dmg"}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}

EXTERNAL_LINK_RE = re.compile(r"https?://[^\s)>\]\"']+", re.IGNORECASE)


@dataclass(slots=True)
class ExternalLink:
    """External URL detected in message text/caption."""

    url: str
    provider: str
    file_hint: str | None
    priority: str


class TelegramCatalogClassifier:
    """Assign priorities and detect external resources before downloads."""

    @staticmethod
    def extension(file_name: str | None) -> str | None:
        if not file_name:
            return None
        suffix = Path(file_name).suffix.lower()
        return suffix or None

    @classmethod
    def priority_for_message(cls, *, text: str | None, content_type: str, file_name: str | None) -> str:
        extension = cls.extension(file_name)
        lowered = (text or "").lower()
        if extension in HIGH_PRIORITY_EXTENSIONS or content_type in {"text", "document"}:
            return "high"
        if extension in MEDIUM_PRIORITY_EXTENSIONS or content_type in {"video", "audio", "image"}:
            return "medium"
        if extension in LOW_PRIORITY_EXTENSIONS:
            return "low"
        if any(token in lowered for token in ("estrategia", "setup", "risk", "riesgo", "entrada", "fvg", "order block")):
            return "high"
        return "medium"

    @classmethod
    def priority_for_file(cls, file_name: str, category: str) -> str:
        extension = cls.extension(file_name)
        if extension in HIGH_PRIORITY_EXTENSIONS or category == "document":
            return "high"
        if extension in LOW_PRIORITY_EXTENSIONS:
            return "low"
        if category in {"video", "audio", "image"}:
            return "medium"
        return "medium"

    @classmethod
    def initial_file_status(cls, file_name: str, category: str, *, catalog_only: bool) -> str:
        extension = cls.extension(file_name)
        if extension in ARCHIVE_EXTENSIONS:
            return "queued"
        if catalog_only:
            return "queued"
        return "discovered"

    @classmethod
    def detect_external_links(cls, text: str | None) -> list[ExternalLink]:
        links: list[ExternalLink] = []
        for raw_url in EXTERNAL_LINK_RE.findall(text or ""):
            url = raw_url.rstrip(".,;")
            provider = cls.provider_for_url(url)
            file_hint = cls.file_hint(url)
            links.append(
                ExternalLink(
                    url=url,
                    provider=provider,
                    file_hint=file_hint,
                    priority="high" if provider in {"mega", "google_drive"} else "medium",
                )
            )
        return links

    @staticmethod
    def provider_for_url(url: str) -> str:
        lowered = url.lower()
        if "mega.nz" in lowered or "mega.co.nz" in lowered:
            return "mega"
        if "drive.google.com" in lowered or "docs.google.com" in lowered:
            return "google_drive"
        if "mediafire.com" in lowered:
            return "mediafire"
        if "dropbox.com" in lowered:
            return "dropbox"
        return "other"

    @staticmethod
    def file_hint(url: str) -> str | None:
        name = Path(url.split("?", 1)[0]).name
        return name[:255] if name and "." in name else None


def enrich_payload_for_catalog(payload: dict, text: str | None) -> dict:
    """Add catalog metadata to a serialized Telegram payload."""

    links = TelegramCatalogClassifier.detect_external_links(text)
    priority = TelegramCatalogClassifier.priority_for_message(
        text=text,
        content_type=payload.get("content_type", "text"),
        file_name=payload.get("file_name"),
    )
    payload["extension"] = TelegramCatalogClassifier.extension(payload.get("file_name"))
    payload["external_links"] = [asdict(link) for link in links]
    payload["priority"] = priority
    payload["processing_status"] = "cataloged"
    payload.setdefault("media_type", payload.get("content_type"))
    return payload
