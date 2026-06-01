"""Resume queued Telegram media downloads already cataloged in the database."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.file_asset import FileAsset
from src.db.repositories.files import FileRepository
from src.telegram.client import TelegramClientManager
from src.telegram.downloader import TelegramDownloader

logger = get_logger(__name__)


class PendingMediaResumeApplicationService:
    """Resume or reconcile pending Telegram media without rescanning the full channel."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.file_repository = FileRepository(session)

    def run(
        self,
        *,
        limit: int = 10,
        max_file_size_mb: float | None = None,
        categories: list[str] | None = None,
        statuses: list[str] | None = None,
    ) -> dict[str, int]:
        return asyncio.run(
            self._run_async(
                limit=limit,
                max_file_size_mb=max_file_size_mb,
                categories=categories or ["video", "audio", "document", "generic"],
                statuses=statuses or ["queued", "downloading", "partial"],
            )
        )

    async def _run_async(
        self,
        *,
        limit: int,
        max_file_size_mb: float | None,
        categories: list[str],
        statuses: list[str],
    ) -> dict[str, int]:
        selected = self.file_repository.list_pending_downloads(
            categories=categories,
            statuses=statuses,
            limit=limit,
        )
        downloader = TelegramDownloader(self.settings.paths, self.file_repository)
        client = await TelegramClientManager(self.settings).authenticate()

        resumed = reconciled = skipped = failed = 0
        try:
            for file_asset in selected:
                outcome = await self._resume_one(
                    client=client,
                    downloader=downloader,
                    file_asset=file_asset,
                    max_file_size_mb=max_file_size_mb,
                )
                if outcome == "resumed":
                    resumed += 1
                elif outcome == "reconciled":
                    reconciled += 1
                elif outcome == "skipped":
                    skipped += 1
                else:
                    failed += 1
                self.session.commit()
        finally:
            await client.disconnect()

        return {
            "selected": len(selected),
            "resumed": resumed,
            "reconciled": reconciled,
            "skipped": skipped,
            "failed": failed,
        }

    async def _resume_one(
        self,
        *,
        client,
        downloader: TelegramDownloader,
        file_asset: FileAsset,
        max_file_size_mb: float | None,
    ) -> str:
        if self._exceeds_size_limit(file_asset, max_file_size_mb):
            file_asset.notes = self._append_note(
                file_asset.notes,
                f"Resume skipped by size limit max_file_size_mb={max_file_size_mb}",
            )
            self.session.add(file_asset)
            return "skipped"

        message = file_asset.message
        channel = file_asset.channel
        if message is None or channel is None:
            file_asset.status = "failed"
            file_asset.processing_status = "failed"
            file_asset.notes = self._append_note(file_asset.notes, "Missing channel/message relationship for resume.")
            self.session.add(file_asset)
            return "failed"

        remote_message = await client.get_messages(channel.input_reference, ids=message.telegram_message_id)
        if remote_message is None or not getattr(remote_message, "media", None):
            file_asset.status = "failed"
            file_asset.processing_status = "failed"
            file_asset.notes = self._append_note(
                file_asset.notes,
                f"Telegram message {message.telegram_message_id} unavailable or has no media.",
            )
            self.session.add(file_asset)
            return "failed"

        plan = downloader.build_plan(message=remote_message, channel=channel)
        if plan.target_path.exists():
            downloader.reconcile_existing_asset(file_asset, plan)
            file_asset.notes = self._append_note(file_asset.notes, f"Reconciled existing target path {plan.target_path}.")
            self.session.add(file_asset)
            return "reconciled"

        file_asset.status = "downloading"
        file_asset.processing_status = "downloading"
        self.session.add(file_asset)
        downloaded = await downloader.download_to_asset(
            client=client,
            message=remote_message,
            file_asset=file_asset,
            plan=plan,
        )
        if downloaded is None:
            file_asset = self.file_repository.get_by_id(file_asset.id) or file_asset
            file_asset.notes = self._append_note(file_asset.notes, f"Resume failed for {file_asset.file_name}.")
            self.session.add(file_asset)
            return "failed"

        downloaded.notes = self._append_note(downloaded.notes, f"Resumed download for {downloaded.file_name}.")
        self.session.add(downloaded)
        logger.info("Resumed pending media file_id=%s file=%s", downloaded.id, downloaded.file_name)
        return "resumed"

    @staticmethod
    def _exceeds_size_limit(file_asset: FileAsset, max_file_size_mb: float | None) -> bool:
        if max_file_size_mb is None or file_asset.size_bytes is None:
            return False
        return file_asset.size_bytes > max_file_size_mb * 1024 * 1024

    @staticmethod
    def _append_note(existing: str | None, note: str) -> str:
        text = (existing or "").strip()
        return f"{text}\n{note}".strip() if text else note
