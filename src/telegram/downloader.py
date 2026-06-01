"""Media downloader with deduplication support."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
import shutil

from telethon import TelegramClient
from telethon.tl.custom.message import Message

from src.core.logging import get_logger
from src.core.paths import ProjectPaths, sanitize_filesystem_name
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.repositories.files import FileRepository
from src.processing.archive_groups import parse_archive_part
from src.telegram.catalog import TelegramCatalogClassifier
from src.telegram.parsers import TelegramMessageParser

logger = get_logger(__name__)

DEFAULT_DOWNLOAD_RETRY_ATTEMPTS = 5
DEFAULT_DOWNLOAD_RETRY_DELAY_SECONDS = 5
DEFAULT_DOWNLOAD_PART_SIZE_KB = 512
DEFAULT_PROGRESS_LOG_EVERY_BYTES = 50 * 1024 * 1024
DEFAULT_DOWNLOAD_CHUNK_TIMEOUT_SECONDS = 120


@dataclass(slots=True)
class MediaDownloadPlan:
    """Resolved media target before physical download starts."""

    category: str
    file_name: str
    target_path: Path
    temp_path: Path
    telegram_file_id: str
    mime_type: str | None
    expected_size_bytes: int | None


class TelegramDownloader:
    """Download media to the raw data lake."""

    def __init__(
        self,
        paths: ProjectPaths,
        file_repository: FileRepository,
        *,
        retry_attempts: int = DEFAULT_DOWNLOAD_RETRY_ATTEMPTS,
        retry_delay_seconds: int = DEFAULT_DOWNLOAD_RETRY_DELAY_SECONDS,
        part_size_kb: int = DEFAULT_DOWNLOAD_PART_SIZE_KB,
        chunk_timeout_seconds: int = DEFAULT_DOWNLOAD_CHUNK_TIMEOUT_SECONDS,
    ) -> None:
        self.paths = paths
        self.file_repository = file_repository
        self.retry_attempts = retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.part_size_kb = part_size_kb
        self.chunk_timeout_seconds = chunk_timeout_seconds

    async def download_media(
        self,
        *,
        client: TelegramClient,
        message: Message,
        channel: Channel,
        persisted_message_id: int,
    ) -> FileAsset | None:
        if not message.media:
            return None

        plan = self.build_plan(message=message, channel=channel)

        existing_for_message = self.file_repository.find_by_telegram_file(
            message_id=persisted_message_id,
            telegram_file_id=plan.telegram_file_id,
        )
        if existing_for_message:
            logger.debug("Skipping media download for message %s: file already persisted", message.id)
            return existing_for_message
        existing_files = self.file_repository.get_by_message(persisted_message_id)
        if existing_files:
            logger.debug("Skipping media download for message %s: message already has file rows", message.id)
            return existing_files[0]

        file_asset, _ = self.file_repository.upsert_discovered(
            self.discovered_payload(
                channel=channel,
                persisted_message_id=persisted_message_id,
                plan=plan,
                status="downloading",
            )
        )
        downloaded_path = await self._download_with_resume(client=client, message=message, plan=plan)
        if downloaded_path is None:
            partial_status = "partial" if plan.temp_path.exists() else "failed"
            self.file_repository.mark_status(file_asset, status=partial_status)
            return None

        return self.finalize_download(file_asset=file_asset, downloaded_path=Path(downloaded_path), plan=plan)

    def build_plan(self, *, message: Message, channel: Channel) -> MediaDownloadPlan:
        """Resolve target paths and metadata without touching the network."""

        category = TelegramMessageParser.detect_file_category(message)
        target_dir = self.paths.media_dir(channel.normalized_name, category)
        file_name = TelegramMessageParser.safe_filename(message)
        multipart = parse_archive_part(file_name)
        if multipart.is_multipart and multipart.group_key:
            message_dir = target_dir / f"group_{sanitize_filesystem_name(multipart.group_key, fallback='multipart')}"
        else:
            message_dir = target_dir / f"msg_{message.id}"
        message_dir.mkdir(parents=True, exist_ok=True)
        target_path = TelegramMessageParser.ensure_extension(message_dir / file_name, message)
        temp_path = target_path.with_suffix(f"{target_path.suffix}.part")
        return MediaDownloadPlan(
            category=category,
            file_name=target_path.name,
            target_path=target_path,
            temp_path=temp_path,
            telegram_file_id=self._telegram_file_id(message),
            mime_type=getattr(message.file, "mime_type", None) if message.file else None,
            expected_size_bytes=getattr(message.file, "size", None) if message.file else None,
        )

    def discovered_payload(
        self,
        *,
        channel: Channel,
        persisted_message_id: int,
        plan: MediaDownloadPlan,
        status: str = "discovered",
    ) -> dict:
        """Build a `files` row payload before download starts."""

        return {
            "channel_id": channel.id,
            "message_id": persisted_message_id,
            "category": plan.category,
            "file_name": plan.file_name,
            "extension": Path(plan.file_name).suffix.lower() or None,
            "stored_path": str(plan.target_path.resolve()),
            "mime_type": plan.mime_type,
            "size_bytes": plan.expected_size_bytes,
            "file_hash": self._hash_file(plan.target_path) if plan.target_path.exists() else None,
            "telegram_file_id": plan.telegram_file_id,
            "status": status,
            "priority": TelegramCatalogClassifier.priority_for_file(plan.file_name, plan.category),
            "processing_status": status,
        }

    async def download_to_asset(
        self,
        *,
        client: TelegramClient,
        message: Message,
        file_asset: FileAsset,
        plan: MediaDownloadPlan,
    ) -> FileAsset | None:
        """Download media for a pre-persisted file asset."""

        downloaded_path = await self._download_with_resume(client=client, message=message, plan=plan)
        if downloaded_path is None:
            partial_status = "partial" if plan.temp_path.exists() else "failed"
            self.file_repository.mark_status(file_asset, status=partial_status)
            return None
        return self.finalize_download(file_asset=file_asset, downloaded_path=Path(downloaded_path), plan=plan)

    def finalize_download(
        self,
        *,
        file_asset: FileAsset,
        downloaded_path: Path,
        plan: MediaDownloadPlan,
    ) -> FileAsset:
        """Hash, deduplicate and mark a pre-persisted asset as downloaded."""

        stored_path = downloaded_path
        file_hash = self._hash_file(stored_path)
        size_bytes = stored_path.stat().st_size
        duplicate = self.file_repository.find_duplicate(
            file_hash=file_hash,
            file_name=plan.file_name,
            size_bytes=size_bytes,
        )
        final_path = stored_path
        duplicates_skipped = False
        if duplicate and duplicate.id != file_asset.id and Path(duplicate.stored_path).resolve() != stored_path.resolve():
            stored_path.unlink(missing_ok=True)
            final_path = Path(duplicate.stored_path)
            duplicates_skipped = True
        elif stored_path.exists() and stored_path.resolve() == plan.target_path.resolve():
            final_path = stored_path
        elif plan.temp_path.exists():
            final_path = self._finalize_download(plan.temp_path, plan.target_path)
        else:
            raise FileNotFoundError(
                f"Download finalize missing both target and temp file for {plan.file_name}"
            )

        return self.file_repository.mark_status(
            file_asset,
            status="duplicate-reused" if duplicates_skipped else "downloaded",
            stored_path=str(final_path.resolve()),
            size_bytes=size_bytes,
            file_hash=file_hash,
        )

    def reconcile_existing_asset(self, file_asset: FileAsset, plan: MediaDownloadPlan) -> FileAsset:
        """Mark an existing on-disk file as downloaded without redownloading."""

        file_hash = self._hash_file(plan.target_path)
        size_bytes = plan.target_path.stat().st_size
        return self.file_repository.mark_status(
            file_asset,
            status="downloaded",
            stored_path=str(plan.target_path.resolve()),
            size_bytes=size_bytes,
            file_hash=file_hash,
        )

    @staticmethod
    def _telegram_file_id(message: Message) -> str:
        if message.document and getattr(message.document, "id", None):
            return str(message.document.id)
        if message.photo and getattr(message.photo, "id", None):
            return str(message.photo.id)
        return str(message.id)

    @staticmethod
    def _finalize_download(temp_path: Path, target_path: Path) -> Path:
        if target_path.exists():
            target_path.unlink()
        shutil.move(str(temp_path), str(target_path))
        return target_path

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    async def _download_with_resume(
        self,
        *,
        client: TelegramClient,
        message: Message,
        plan: MediaDownloadPlan,
    ) -> Path | None:
        if plan.target_path.exists():
            if plan.expected_size_bytes and plan.target_path.stat().st_size == plan.expected_size_bytes:
                logger.info("Target file already complete on disk: %s", plan.target_path)
                return plan.target_path
            plan.target_path.unlink(missing_ok=True)

        for attempt in range(1, self.retry_attempts + 1):
            resume_offset = plan.temp_path.stat().st_size if plan.temp_path.exists() else 0
            if plan.expected_size_bytes and resume_offset > plan.expected_size_bytes:
                logger.warning(
                    "Temporary file exceeds expected size. Restarting download file=%s temp_size=%s expected=%s",
                    plan.file_name,
                    resume_offset,
                    plan.expected_size_bytes,
                )
                plan.temp_path.unlink(missing_ok=True)
                resume_offset = 0
            if plan.expected_size_bytes and resume_offset == plan.expected_size_bytes:
                logger.info("[RESUME] Temporary file already complete: %s", plan.temp_path)
                return self._finalize_download(plan.temp_path, plan.target_path)

            if resume_offset:
                logger.info(
                    "[RESUME] Continuing download file=%s offset=%s/%s attempt=%s/%s",
                    plan.file_name,
                    resume_offset,
                    plan.expected_size_bytes or "?",
                    attempt,
                    self.retry_attempts,
                )
            else:
                logger.info(
                    "Starting resilient download file=%s total=%s attempt=%s/%s",
                    plan.file_name,
                    plan.expected_size_bytes or "?",
                    attempt,
                    self.retry_attempts,
                )

            try:
                await self._stream_download(
                    client=client,
                    message=message,
                    plan=plan,
                    resume_offset=resume_offset,
                )
                final_size = plan.temp_path.stat().st_size if plan.temp_path.exists() else 0
                if plan.expected_size_bytes and final_size < plan.expected_size_bytes:
                    raise IOError(
                        f"incomplete_download expected={plan.expected_size_bytes} got={final_size}"
                    )
                return self._finalize_download(plan.temp_path, plan.target_path)
            except Exception as exc:
                logger.warning(
                    "Download attempt failed file=%s attempt=%s/%s offset=%s error=%s",
                    plan.file_name,
                    attempt,
                    self.retry_attempts,
                    resume_offset,
                    exc,
                )
                if attempt >= self.retry_attempts:
                    logger.error("Exhausted download retries for %s", plan.file_name)
                    return None
                if not client.is_connected():
                    await client.connect()
                await asyncio.sleep(self.retry_delay_seconds)
        return None

    async def _stream_download(
        self,
        *,
        client: TelegramClient,
        message: Message,
        plan: MediaDownloadPlan,
        resume_offset: int,
    ) -> None:
        downloaded_bytes = resume_offset
        next_progress_mark = (
            ((downloaded_bytes // DEFAULT_PROGRESS_LOG_EVERY_BYTES) + 1) * DEFAULT_PROGRESS_LOG_EVERY_BYTES
            if downloaded_bytes
            else DEFAULT_PROGRESS_LOG_EVERY_BYTES
        )
        mode = "ab" if resume_offset else "wb"
        iterator = client._iter_download(
            message.media,
            offset=resume_offset,
            request_size=self.part_size_kb * 1024,
            chunk_size=self.part_size_kb * 1024,
            file_size=plan.expected_size_bytes,
        )
        with plan.temp_path.open(mode) as handle:
            while True:
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=self.chunk_timeout_seconds)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(
                        f"download_chunk_timeout after {self.chunk_timeout_seconds}s without progress"
                    ) from exc
                handle.write(chunk)
                downloaded_bytes += len(chunk)
                if downloaded_bytes >= next_progress_mark or (
                    plan.expected_size_bytes and downloaded_bytes >= plan.expected_size_bytes
                ):
                    logger.info(
                        "Downloading %s %s/%s",
                        plan.file_name,
                        downloaded_bytes,
                        plan.expected_size_bytes or "?",
                    )
                    next_progress_mark += DEFAULT_PROGRESS_LOG_EVERY_BYTES
            handle.flush()
