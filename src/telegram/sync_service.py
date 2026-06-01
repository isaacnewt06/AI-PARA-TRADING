"""Telegram synchronization orchestration."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telethon.errors import FloodWaitError
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.repositories.external_resources import ExternalResourceRepository
from src.db.repositories.files import FileRepository
from src.db.repositories.messages import MessageRepository
from src.db.repositories.runs import RunRepository
from src.telegram.downloader import TelegramDownloader
from src.telegram.extractor import TelegramMessageExtractor

logger = get_logger(__name__)


@dataclass(slots=True)
class TelegramSyncOptions:
    """Runtime options for bounded/resumable sync runs."""

    limit: int | None = None
    max_file_size_mb: float | None = None
    skip_extensions: set[str] = field(default_factory=set)
    commit_every: int = 1
    debug: bool = False
    catalog_only: bool = False


class TelegramSyncService:
    """Coordinate resumable Telegram synchronization."""

    def __init__(
        self,
        *,
        settings: Settings,
        message_repository: MessageRepository,
        file_repository: FileRepository,
        run_repository: RunRepository,
    ) -> None:
        self.settings = settings
        self.message_repository = message_repository
        self.file_repository = file_repository
        self.external_resource_repository = ExternalResourceRepository(file_repository.session)
        self.run_repository = run_repository

    async def sync_channel(
        self,
        extractor: TelegramMessageExtractor,
        channel: Channel,
        mode: str = "incremental",
        options: TelegramSyncOptions | None = None,
    ) -> dict[str, Any]:
        options = options or TelegramSyncOptions(commit_every=self.settings.tuning.sync_checkpoint_interval)
        options.commit_every = max(1, options.commit_every)
        downloader = TelegramDownloader(self.settings.paths, self.file_repository)
        run = self.run_repository.start_ingestion(channel_id=channel.id, mode=mode)
        session = self.message_repository.session
        self._checkpoint(session=session, channel=channel, run=run, summary=self._empty_summary())
        logger.info("Starting %s sync for channel %s", mode, channel.title)
        summary = self._empty_summary()
        pending_since_checkpoint = 0

        try:
            async for message, payload in extractor.iter_messages(channel, mode=mode, limit=options.limit):
                try:
                    logger.info("processing message_id=%s channel=%s", message.id, channel.title)
                    message_result = await self._process_message(
                        extractor=extractor,
                        downloader=downloader,
                        channel=channel,
                        message=message,
                        payload=payload,
                        options=options,
                    )
                    summary["messages_scanned"] += 1
                    summary["messages_saved"] += 1 if message_result["message_created"] else 0
                    summary["files_downloaded"] += message_result["files_downloaded"]
                    summary["files_skipped"] += message_result["files_skipped"]
                    summary["duplicates_skipped"] += message_result["duplicates_skipped"]
                    if message_result["errors_count"]:
                        summary["errors_count"] += message_result["errors_count"]
                    channel.last_synced_message_id = max(channel.last_synced_message_id or 0, message.id)
                    channel.last_synced_at = datetime.now(timezone.utc)
                    pending_since_checkpoint += 1
                except Exception as message_exc:
                    session.rollback()
                    channel = session.merge(channel)
                    run = session.merge(run)
                    summary["errors_count"] += 1
                    summary["messages_scanned"] += 1
                    channel.last_synced_message_id = max(channel.last_synced_message_id or 0, message.id)
                    channel.last_synced_at = datetime.now(timezone.utc)
                    logger.exception("Failed to ingest message %s from %s", message.id, channel.title)
                    pending_since_checkpoint += 1

                if pending_since_checkpoint >= options.commit_every:
                    self._checkpoint(session=session, channel=channel, run=run, summary=summary)
                    logger.info("committed sync checkpoint channel=%s scanned=%s", channel.title, summary["messages_scanned"])
                    pending_since_checkpoint = 0
                await asyncio.sleep(self.settings.tuning.rate_limit_sleep_seconds)

            self.run_repository.finish_ingestion(run, status="completed")
            self._checkpoint(session=session, channel=channel, run=run, summary=summary)
            logger.info(
                "Sync finished for %s | scanned=%s saved=%s files=%s duplicates=%s errors=%s",
                channel.title,
                summary["messages_scanned"],
                summary["messages_saved"],
                summary["files_downloaded"],
                summary["duplicates_skipped"],
                summary["errors_count"],
            )
            return summary
        except Exception as exc:
            session.rollback()
            channel = session.merge(channel)
            run = session.merge(run)
            summary["errors_count"] += 1
            self.run_repository.finish_ingestion(run, status="failed", notes=str(exc))
            self._checkpoint(session=session, channel=channel, run=run, summary=summary)
            logger.exception("Sync failed for channel %s", channel.title)
            raise

    async def _process_message(
        self,
        *,
        extractor: TelegramMessageExtractor,
        downloader: TelegramDownloader,
        channel: Channel,
        message,
        payload: dict[str, Any],
        options: TelegramSyncOptions,
    ) -> dict[str, int | bool]:
        persisted_message, created = self.message_repository.upsert(
            {
                "channel_id": channel.id,
                "telegram_message_id": payload["id"],
                "reply_to_message_id": payload["reply_to_msg_id"],
                "posted_at": message.date,
                "content_type": payload["content_type"],
                "text": payload["text"],
                "has_media": payload["has_media"],
                "priority": payload.get("priority", "medium"),
                "processing_status": payload.get("processing_status", "cataloged"),
                "external_links_json": json.dumps(payload.get("external_links", []), ensure_ascii=False),
                "raw_json": json.dumps(payload, ensure_ascii=False),
            }
        )
        logger.info("persisted message_id=%s db_id=%s created=%s", payload["id"], persisted_message.id, created)
        external_count = self._persist_external_links(persisted_message.id, payload.get("external_links", []))
        if external_count:
            logger.info("persisted external_resources message_id=%s count=%s", payload["id"], external_count)
        self.message_repository.session.commit()
        files_downloaded = 0
        files_skipped = 0
        duplicates_skipped = 0
        errors_count = 0
        if message.media:
            plan = downloader.build_plan(message=message, channel=channel)
            logger.info(
                "discovered media message_id=%s filename=%s size=%s mime=%s",
                message.id,
                plan.file_name,
                plan.expected_size_bytes,
                plan.mime_type,
            )
            file_entity, _ = self.file_repository.upsert_discovered(
                downloader.discovered_payload(
                    channel=channel,
                    persisted_message_id=persisted_message.id,
                    plan=plan,
                    status="queued" if options.catalog_only else "discovered",
                )
            )
            logger.info("persisted file_asset_id=%s status=%s", file_entity.id, file_entity.status)
            self.file_repository.session.commit()

            if options.catalog_only:
                self.file_repository.mark_status(file_entity, status="queued")
                logger.info("cataloged queued file_asset_id=%s filename=%s", file_entity.id, plan.file_name)
                self.file_repository.session.commit()
                return {
                    "message_created": created,
                    "files_downloaded": 0,
                    "files_skipped": 1,
                    "duplicates_skipped": 0,
                    "errors_count": 0,
                }

            skip_reason = self._skip_reason(plan=plan, options=options)
            if skip_reason:
                self.file_repository.mark_status(file_entity, status="skipped")
                logger.info("marked skipped file_asset_id=%s reason=%s", file_entity.id, skip_reason)
                self.file_repository.session.commit()
                return {
                    "message_created": created,
                    "files_downloaded": 0,
                    "files_skipped": 1,
                    "duplicates_skipped": 0,
                    "errors_count": 0,
                }

            if plan.target_path.exists():
                file_entity = downloader.reconcile_existing_asset(file_entity, plan)
                logger.info("marked downloaded existing file_asset_id=%s path=%s", file_entity.id, plan.target_path)
                self.file_repository.session.commit()
                return {
                    "message_created": created,
                    "files_downloaded": 0,
                    "files_skipped": 1,
                    "duplicates_skipped": 0,
                    "errors_count": 0,
                }

            self.file_repository.mark_status(file_entity, status="downloading")
            logger.info("download started file_asset_id=%s path=%s", file_entity.id, plan.target_path)
            self.file_repository.session.commit()
            file_entity = await self._download_with_retries(
                downloader=downloader,
                extractor=extractor,
                message=message,
                file_asset_id=file_entity.id,
                plan=plan,
            )
            if file_entity:
                files_downloaded = 1
                if file_entity.status == "duplicate-reused":
                    duplicates_skipped = 1
                logger.info("download completed file_asset_id=%s status=%s", file_entity.id, file_entity.status)
                self.file_repository.session.commit()
            else:
                errors_count = 1
                file_entity = self.file_repository.session.get(FileAsset, file_entity.id) if file_entity else None

        return {
            "message_created": created,
            "files_downloaded": files_downloaded,
            "files_skipped": files_skipped,
            "duplicates_skipped": duplicates_skipped,
            "errors_count": errors_count,
        }

    def _persist_external_links(self, message_db_id: int, links: list[dict]) -> int:
        count = 0
        for link in links:
            self.external_resource_repository.upsert(
                {
                    "message_id": message_db_id,
                    "url": link["url"],
                    "provider": link["provider"],
                    "file_hint": link.get("file_hint"),
                    "priority": link.get("priority", "medium"),
                    "status": "external_pending",
                    "notes": "Cataloged from Telegram message text/caption.",
                }
            )
            count += 1
        return count

    async def _download_with_retries(
        self,
        *,
        downloader: TelegramDownloader,
        extractor: TelegramMessageExtractor,
        message,
        file_asset_id: int,
        plan,
    ) -> FileAsset | None:
        retries = self.settings.tuning.max_sync_retries
        for attempt in range(1, retries + 1):
            try:
                file_asset = self.file_repository.session.get(FileAsset, file_asset_id)
                if file_asset is None:
                    return None
                return await downloader.download_to_asset(
                    client=extractor.client,
                    message=message,
                    file_asset=file_asset,
                    plan=plan,
                )
            except FloodWaitError as exc:
                logger.warning("Flood wait triggered for %s seconds", exc.seconds)
                await asyncio.sleep(exc.seconds)
            except Exception:
                logger.exception("Download error on attempt %s/%s for message %s", attempt, retries, message.id)
                await asyncio.sleep(self.settings.tuning.retry_backoff_seconds * attempt)
        file_asset = self.file_repository.session.get(FileAsset, file_asset_id)
        if file_asset is not None:
            self.file_repository.mark_status(file_asset, status="failed")
            logger.info("marked failed file_asset_id=%s message_id=%s", file_asset.id, message.id)
            self.file_repository.session.commit()
        return None

    @staticmethod
    def _skip_reason(*, plan, options: TelegramSyncOptions) -> str | None:
        extension = Path(plan.file_name).suffix.lower()
        if extension and extension in options.skip_extensions:
            return f"extension:{extension}"
        if options.max_file_size_mb is not None and plan.expected_size_bytes is not None:
            max_bytes = int(options.max_file_size_mb * 1024 * 1024)
            if plan.expected_size_bytes > max_bytes:
                return f"size:{plan.expected_size_bytes}>{max_bytes}"
        return None

    @staticmethod
    def _empty_summary() -> dict[str, int]:
        return {
            "messages_scanned": 0,
            "messages_saved": 0,
            "files_downloaded": 0,
            "files_skipped": 0,
            "duplicates_skipped": 0,
            "errors_count": 0,
        }

    @staticmethod
    def _checkpoint(*, session: Session, channel: Channel, run, summary: dict[str, int]) -> None:
        run.messages_scanned = summary["messages_scanned"]
        run.messages_saved = summary["messages_saved"]
        run.files_downloaded = summary["files_downloaded"]
        run.duplicates_skipped = summary["duplicates_skipped"]
        run.errors_count = summary["errors_count"]
        channel.last_synced_at = channel.last_synced_at or datetime.now(timezone.utc)
        session.commit()
