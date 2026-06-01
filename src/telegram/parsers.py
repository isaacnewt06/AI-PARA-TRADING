"""Helpers to normalize Telegram messages and media."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from telethon.tl.custom.message import Message

from src.core.paths import sanitize_filesystem_name
from src.telegram.catalog import enrich_payload_for_catalog


class TelegramMessageParser:
    """Normalize Telethon objects into internal payloads."""

    VIDEO_EXTENSIONS = {".mp4", ".mpeg", ".mpg", ".mkv", ".avi", ".mov", ".ts", ".webm"}
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx", ".txt", ".md", ".csv", ".tsv"}

    @staticmethod
    def detect_message_content_type(message: Message) -> str:
        if message.video:
            return "video"
        if message.audio or message.voice:
            return "audio"
        if message.photo:
            return "image"
        if message.document:
            mime = getattr(message.file, "mime_type", "") or ""
            extension = str(getattr(message.file, "ext", "") or "").lower()
            if mime.startswith("video/") or extension in TelegramMessageParser.VIDEO_EXTENSIONS:
                return "video"
            if mime.startswith("audio/") or extension in TelegramMessageParser.AUDIO_EXTENSIONS:
                return "audio"
            if mime.startswith("image/") or extension in TelegramMessageParser.IMAGE_EXTENSIONS:
                return "image"
            if any(token in mime for token in ("pdf", "word", "sheet", "excel", "officedocument", "text/")):
                return "document"
            if extension in TelegramMessageParser.DOCUMENT_EXTENSIONS:
                return "document"
            return "generic"
        return "text"

    @staticmethod
    def detect_file_category(message: Message) -> str:
        return TelegramMessageParser.detect_message_content_type(message)

    @staticmethod
    def safe_filename(message: Message) -> str:
        if message.file and getattr(message.file, "name", None):
            return sanitize_filesystem_name(message.file.name, fallback=f"message_{message.id}")
        suffix = TelegramMessageParser.extension_from_message(message)
        return f"message_{message.id}{suffix}"

    @staticmethod
    def extension_from_message(message: Message) -> str:
        if message.video:
            return ".mp4"
        if message.audio or message.voice:
            return ".mp3"
        if message.photo:
            return ".jpg"
        if message.document and message.file and getattr(message.file, "ext", None):
            return str(message.file.ext)
        return ".bin"

    @staticmethod
    def serialize_message(message: Message) -> dict[str, Any]:
        payload = {
            "id": message.id,
            "text": message.message,
            "date": message.date.isoformat() if message.date else None,
            "reply_to_msg_id": message.reply_to_msg_id,
            "has_media": bool(message.media),
            "content_type": TelegramMessageParser.detect_message_content_type(message),
            "file_name": TelegramMessageParser.safe_filename(message) if message.media else None,
            "mime_type": getattr(message.file, "mime_type", None) if message.file else None,
        }
        return enrich_payload_for_catalog(payload, message.message)

    @staticmethod
    def ensure_extension(path: Path, message: Message) -> Path:
        if path.suffix:
            return path
        return path.with_suffix(TelegramMessageParser.extension_from_message(message))

    @staticmethod
    def is_supported_document_filename(file_name: str) -> bool:
        suffix = Path(file_name).suffix.lower()
        return suffix in {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md", ".csv", ".tsv"}
