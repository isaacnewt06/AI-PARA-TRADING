"""Ingest signal messages from Telegram Bot API updates."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.core.paths import sanitize_filesystem_name
from src.db.models.channel import Channel
from src.db.repositories.channels import ChannelRepository
from src.db.repositories.files import FileRepository
from src.db.repositories.messages import MessageRepository
from src.db.repositories.runs import RunRepository
from src.telegram.bot_api_client import TelegramBotApiClient

logger = get_logger(__name__)


class ConfiguredSignalBotImportService:
    """Register configured signal bot sources as logical channels."""

    def __init__(self, session: Session, config_path: Path) -> None:
        self.session = session
        self.config_path = config_path
        self.channel_repository = ChannelRepository(session)

    def run(self) -> dict[str, int]:
        imported = 0
        for bot in self._load_bots():
            channel = self.channel_repository.create_or_update(
                input_reference=bot["input_reference"],
                title=bot.get("title") or bot["name"],
                normalized_name=sanitize_filesystem_name(bot.get("name") or bot["title"], fallback="signal_bot"),
                telegram_channel_id=None,
            )
            channel.is_active = bool(bot.get("is_active", True))
            imported += 1
        self.session.flush()
        return {"bots_imported": imported}

    def _load_bots(self) -> list[dict[str, Any]]:
        if not self.config_path.exists():
            return []
        with self.config_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return list(payload.get("bots", []))


class SignalBotSyncApplicationService:
    """Synchronize signal bot updates into the shared knowledge ingestion tables."""

    def __init__(self, session: Session, settings: Settings, config_path: Path) -> None:
        self.session = session
        self.settings = settings
        self.config_path = config_path
        self.channel_repository = ChannelRepository(session)
        self.message_repository = MessageRepository(session)
        self.file_repository = FileRepository(session)
        self.run_repository = RunRepository(session)

    def sync(self, bot_name: str | None = None) -> dict[str, dict[str, int]]:
        bots = self._load_bots()
        if bot_name:
            bots = [bot for bot in bots if bot.get("name") == bot_name or bot.get("input_reference") == bot_name]
        results: dict[str, dict[str, int]] = {}
        for bot in bots:
            results[bot["name"]] = self._sync_one(bot)
        return results

    def _sync_one(self, bot: dict[str, Any]) -> dict[str, int]:
        token = self._resolve_token(bot)
        client = TelegramBotApiClient(token)
        me = client.get_me().get("result", {})
        title = bot.get("title") or me.get("username") or bot["name"]
        channel = self.channel_repository.create_or_update(
            input_reference=bot["input_reference"],
            title=title,
            normalized_name=sanitize_filesystem_name(bot.get("name") or title, fallback="signal_bot"),
            telegram_channel_id=me.get("id"),
        )
        channel.is_active = bool(bot.get("is_active", True))
        run = self.run_repository.start_ingestion(channel_id=channel.id, mode="bot_api_incremental")
        summary = {"updates_scanned": 0, "messages_saved": 0, "files_downloaded": 0, "errors_count": 0}
        offset = (channel.last_synced_message_id + 1) if channel.last_synced_message_id else None
        updates = client.get_updates(offset=offset, limit=100, timeout=0)
        for update in updates:
            try:
                self._persist_update(client, channel, update, download_files=bool(bot.get("download_files", True)), summary=summary)
                channel.last_synced_message_id = max(channel.last_synced_message_id or 0, int(update["update_id"]))
                channel.last_synced_at = datetime.now(timezone.utc)
            except Exception:
                summary["errors_count"] += 1
                logger.exception("Failed to ingest bot update %s", update.get("update_id"))
        run.messages_scanned = summary["updates_scanned"]
        run.messages_saved = summary["messages_saved"]
        run.files_downloaded = summary["files_downloaded"]
        run.errors_count = summary["errors_count"]
        self.run_repository.finish_ingestion(run, status="completed")
        self.session.flush()
        return summary

    def _persist_update(
        self,
        client: TelegramBotApiClient,
        channel: Channel,
        update: dict[str, Any],
        *,
        download_files: bool,
        summary: dict[str, int],
    ) -> None:
        message = self._extract_message(update)
        if not message:
            return
        summary["updates_scanned"] += 1
        update_id = int(update["update_id"])
        text = message.get("text") or message.get("caption") or ""
        posted_at = self._message_date(message)
        content_type = self._content_type(message)
        persisted, created = self.message_repository.upsert(
            {
                "channel_id": channel.id,
                "telegram_message_id": update_id,
                "reply_to_message_id": message.get("reply_to_message", {}).get("message_id"),
                "posted_at": posted_at,
                "content_type": content_type,
                "text": text,
                "has_media": content_type != "text",
                "raw_json": json.dumps(update, ensure_ascii=False),
            }
        )
        if created:
            summary["messages_saved"] += 1
        if download_files and content_type != "text":
            file_asset = self._download_media(client, channel, persisted.id, update_id, message, content_type)
            if file_asset:
                summary["files_downloaded"] += 1

    def _download_media(
        self,
        client: TelegramBotApiClient,
        channel: Channel,
        message_row_id: int,
        update_id: int,
        message: dict[str, Any],
        content_type: str,
    ):
        file_id, file_name = self._file_identity(message, content_type, update_id)
        if not file_id:
            return None
        existing = self.file_repository.find_by_telegram_file(message_id=message_row_id, telegram_file_id=file_id)
        if existing:
            return existing
        file_info = client.get_file(file_id)
        file_path = file_info.get("file_path")
        if not file_path:
            return None
        media_dir = self.settings.paths.media_dir(channel.normalized_name, content_type)
        target = media_dir / f"bot_update_{update_id}" / sanitize_filesystem_name(file_name, fallback=f"file_{update_id}")
        downloaded = client.download_file(file_path, target)
        file_hash = self._hash_file(downloaded)
        size_bytes = downloaded.stat().st_size
        duplicate = self.file_repository.find_duplicate(file_hash=file_hash, file_name=downloaded.name, size_bytes=size_bytes)
        stored_path = Path(duplicate.stored_path) if duplicate else downloaded
        if duplicate:
            downloaded.unlink(missing_ok=True)
        return self.file_repository.create(
            {
                "channel_id": channel.id,
                "message_id": message_row_id,
                "category": content_type,
                "file_name": file_name,
                "stored_path": str(stored_path.resolve()),
                "mime_type": message.get("document", {}).get("mime_type"),
                "size_bytes": size_bytes,
                "file_hash": file_hash,
                "telegram_file_id": file_id,
                "status": "duplicate-reused" if duplicate else "downloaded",
            }
        )

    @staticmethod
    def _extract_message(update: dict[str, Any]) -> dict[str, Any] | None:
        for key in ("message", "channel_post", "edited_message", "edited_channel_post"):
            if key in update:
                return dict(update[key])
        return None

    @staticmethod
    def _content_type(message: dict[str, Any]) -> str:
        if "document" in message:
            return "document"
        if "video" in message:
            return "video"
        if "audio" in message or "voice" in message:
            return "audio"
        if "photo" in message:
            return "image"
        return "text"

    @staticmethod
    def _file_identity(message: dict[str, Any], content_type: str, update_id: int) -> tuple[str | None, str]:
        if content_type == "document":
            document = message["document"]
            return document.get("file_id"), document.get("file_name") or f"document_{update_id}.bin"
        if content_type == "video":
            video = message["video"]
            return video.get("file_id"), video.get("file_name") or f"video_{update_id}.mp4"
        if content_type == "audio":
            audio = message.get("audio") or message.get("voice") or {}
            return audio.get("file_id"), audio.get("file_name") or f"audio_{update_id}.ogg"
        if content_type == "image":
            photos = message.get("photo") or []
            if not photos:
                return None, f"image_{update_id}.jpg"
            photo = sorted(photos, key=lambda item: item.get("file_size", 0))[-1]
            return photo.get("file_id"), f"image_{update_id}.jpg"
        return None, f"file_{update_id}.bin"

    @staticmethod
    def _message_date(message: dict[str, Any]) -> datetime | None:
        timestamp = message.get("date")
        if timestamp is None:
            return None
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _load_bots(self) -> list[dict[str, Any]]:
        if not self.config_path.exists():
            return []
        with self.config_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return list(payload.get("bots", []))

    def _resolve_token(self, bot: dict[str, Any]) -> str:
        token_env = bot.get("token_env", "TELEGRAM_SIGNAL_BOT_TOKEN")
        token = os.getenv(token_env) or self.settings.telegram_signal_bot_token
        if not token:
            raise ValueError(f"Missing Telegram Bot API token. Set {token_env} in .env.")
        return token
