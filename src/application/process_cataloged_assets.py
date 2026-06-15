"""Batch processors for catalog-first ingestion queues."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.repositories.external_resources import ExternalResourceRepository
from src.db.repositories.files import FileRepository
from src.knowledge.document_prioritizer import DocumentPrioritizer
from src.processing.archive_extractor import ArchiveDocumentExtractor
from src.processing.document_processor import DocumentProcessor
from src.processing.archive_selector import ArchiveSelector
from src.processing.image_processor import ImageProcessor
from src.processing.video_processor import VideoProcessor
from src.processing.audio_processor import AudioProcessor
from src.telegram.client import TelegramClientManager
from src.telegram.downloader import TelegramDownloader

logger = get_logger(__name__)


@dataclass(slots=True)
class ArchiveDownloadOptions:
    """Controls smart archive downloading for multipart groups."""

    limit: int = 2
    max_group_size_mb: int = 1024
    skip_large_groups: bool = False
    download_only_complete_groups: bool = False
    retry_attempts: int = 5


class CatalogedAssetProcessingService:
    """Process selected catalog queues without blocking sync."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.file_repository = FileRepository(session)
        self.document_prioritizer = DocumentPrioritizer(session)
        self.archive_selector = ArchiveSelector(session)
        self.archive_extractor = ArchiveDocumentExtractor(session, settings)
        self.document_processor = DocumentProcessor(session, settings)
        self.image_processor = ImageProcessor(session)
        self.video_processor = VideoProcessor(session, settings)
        self.audio_processor = AudioProcessor(session, settings)

    def process_documents(self, limit: int | None = None) -> dict[str, int]:
        processed = skipped = failed = 0
        remaining = limit
        candidate_limit = None if limit is None else max(limit * 5, limit + 20)
        files = self.file_repository.list_by_category_status(
            categories=["document", "generic"],
            statuses=["downloaded", "queued", "skipped"],
            limit=candidate_limit,
        )
        for file_asset in files:
            if remaining is not None and remaining <= 0:
                break
            path = self._ensure_local_asset_path(file_asset)
            if path is None or not path.exists():
                file_asset.status = "queued"
                file_asset.processing_status = "queued"
                file_asset.notes = "Physical file is not downloaded yet."
                self.session.add(file_asset)
                continue
            if not self.document_processor.is_supported(path, file_asset.file_name):
                file_asset.processing_status = "skipped"
                file_asset.notes = f"{file_asset.notes or ''}\nUnsupported document payload skipped.".strip()
                self.session.add(file_asset)
                skipped += 1
                if remaining is not None:
                    remaining -= 1
                continue
            try:
                self._process_document(file_asset)
                processed += 1
            except Exception as exc:
                file_asset.status = "failed"
                file_asset.processing_status = "failed"
                file_asset.notes = str(exc)[:500]
                self.session.add(file_asset)
                failed += 1
                logger.exception("Failed to process cataloged asset %s", file_asset.file_name)
            if remaining is not None:
                remaining -= 1
        self.session.flush()
        return {"processed": processed, "skipped": skipped, "failed": failed}

    def rank_documents(self, limit: int | None = None) -> list[dict]:
        ranked = self.document_prioritizer.rank_documents(limit=limit)
        return [
            {
                "file_id": item.file_id,
                "file_name": item.file_name,
                "category": item.category,
                "extension": item.extension,
                "knowledge_density_score": item.knowledge_density_score,
                "strategy_probability_score": item.strategy_probability_score,
                "priority_score": item.priority_score,
                "processable_now": item.processable_now,
                "reasons": item.reasons,
            }
            for item in ranked
        ]

    def process_top_documents(self, limit: int = 5) -> dict[str, int]:
        processed = skipped = failed = 0
        selected = self.document_prioritizer.top_processable_documents(limit=limit)
        for file_asset in selected:
            try:
                self._process_document(file_asset)
                processed += 1
            except Exception as exc:
                file_asset.status = "failed"
                file_asset.processing_status = "failed"
                file_asset.notes = str(exc)[:500]
                self.session.add(file_asset)
                failed += 1
                logger.exception("Failed to process prioritized document %s", file_asset.file_name)
        skipped = max(0, limit - len(selected))
        self.session.flush()
        return {"processed": processed, "skipped": skipped, "failed": failed}

    def process_images(self, limit: int | None = None) -> dict[str, int]:
        return self._process_files(["image"], limit=limit, handler=self._process_image)

    def process_videos(self, limit: int | None = None) -> dict[str, int]:
        return self._process_files(["video", "audio"], limit=limit, handler=self._process_media)

    def process_archives(
        self,
        limit: int | None = None,
        max_size_mb: int = 500,
        file_ids: list[int] | None = None,
    ) -> dict[str, int]:
        archives = [
            file_asset
            for file_asset in self.file_repository.list_by_category_status(
                categories=["generic", "document"],
                statuses=[
                    "queued",
                    "downloaded",
                    "skipped",
                    "partial",
                    "cataloged",
                    "inspected",
                    "inspection_success",
                    "inspection_unavailable",
                    "inspection_backend_missing",
                    "inspection_multipart_incomplete",
                ],
                limit=limit,
            )
            if (file_asset.extension or Path(file_asset.file_name).suffix.lower()) in {".zip", ".rar", ".7z"}
        ]
        if file_ids is not None:
            archive_id_set = set(file_ids)
            archives = [file_asset for file_asset in archives if file_asset.id in archive_id_set]
        processed = skipped = failed = 0
        max_bytes = max_size_mb * 1024 * 1024
        for file_asset in archives:
            recommendation = file_asset.archive_processing_recommendation
            if recommendation in {"skip_for_now", "manual_review"}:
                file_asset.processing_status = "skipped"
                file_asset.notes = f"{file_asset.notes or ''}\nSelection recommendation: {recommendation}".strip()
                self.session.add(file_asset)
                skipped += 1
                continue
            group_validation = self._validate_archive_group(file_asset)
            if not group_validation["ready"]:
                file_asset.status = "partial"
                file_asset.processing_status = "multipart_incomplete"
                file_asset.notes = group_validation["reason"]
                self.session.add(file_asset)
                skipped += 1
                continue
            path = self._ensure_local_asset_path(file_asset)
            if path is None or not path.exists():
                download_result = self.download_archive_group_for_file(
                    file_asset,
                    options=ArchiveDownloadOptions(limit=1, max_group_size_mb=max_size_mb),
                )
                downloaded = download_result.get("groups_downloaded", 0) > 0 or download_result.get("files_downloaded", 0) > 0
                path = self._ensure_local_asset_path(file_asset)
                if not downloaded or path is None or not path.exists():
                    file_asset.status = "inspection_file_missing"
                    file_asset.processing_status = "inspection_file_missing"
                    file_asset.notes = "Archive was selected but is not downloaded locally."
                    self.session.add(file_asset)
                    skipped += 1
                    continue
            if file_asset.size_bytes and file_asset.size_bytes > max_bytes:
                file_asset.status = "skipped_by_size"
                file_asset.processing_status = "skipped"
                file_asset.notes = f"Archive exceeds max_size_mb={max_size_mb}"
                self.session.add(file_asset)
                skipped += 1
                continue
            try:
                extraction_summary = self._process_archive_payload(file_asset, path, recommendation)
                file_asset.notes = extraction_summary
                file_asset.status = "extracted"
                file_asset.processing_status = "extracted"
                self.session.add(file_asset)
                processed += 1
            except Exception as exc:
                file_asset.status = "failed"
                file_asset.processing_status = "failed"
                file_asset.notes = f"archive_inventory_failed: {exc}"
                self.session.add(file_asset)
                failed += 1
        self.session.flush()
        return {"processed": processed, "skipped": skipped, "failed": failed}

    def process_selected_archives(self, limit: int = 3, max_size_mb: int = 500) -> dict[str, int]:
        self.download_archives(
            ArchiveDownloadOptions(
                limit=limit,
                max_group_size_mb=max_size_mb,
                skip_large_groups=True,
                download_only_complete_groups=False,
                retry_attempts=5,
            )
        )
        selected = self.archive_selector.select(limit=limit)
        selected_ids = [
            item.file_id
            for item in selected
            if item.archive_processing_recommendation in {"process_now", "process_documents_only", "inspect_first", "process_videos_later"}
        ]
        if not selected_ids:
            fallback_ids = [
                item.file_id
                for item in selected
                if item.archive_processing_recommendation in {"manual_review"}
            ][:limit]
            selected_ids = fallback_ids
        return self.process_archives(limit=None, max_size_mb=max_size_mb, file_ids=selected_ids)

    def download_archives(self, options: ArchiveDownloadOptions) -> dict[str, Any]:
        selected = self.archive_selector.select(limit=options.limit)
        if not selected:
            return {
                "groups_selected": 0,
                "groups_downloaded": 0,
                "groups_partial": 0,
                "groups_failed": 0,
                "groups_skipped": 0,
                "files_downloaded": 0,
                "files_reused": 0,
                "files_failed": 0,
            }
        groups = self._build_archive_groups([item.file_id for item in selected])
        return asyncio.run(self._download_archive_groups(groups=groups, options=options))

    def download_archive_group_for_file(self, file_asset, *, options: ArchiveDownloadOptions | None = None) -> dict[str, Any]:
        options = options or ArchiveDownloadOptions(limit=1)
        groups = self._build_archive_groups([file_asset.id])
        if not groups:
            return {
                "groups_selected": 0,
                "groups_downloaded": 0,
                "groups_partial": 0,
                "groups_failed": 0,
                "groups_skipped": 0,
                "files_downloaded": 0,
                "files_reused": 0,
                "files_failed": 0,
            }
        return asyncio.run(self._download_archive_groups(groups=groups, options=options))

    async def _download_archive_groups(self, *, groups: list[dict[str, Any]], options: ArchiveDownloadOptions) -> dict[str, Any]:
        summary = {
            "groups_selected": len(groups),
            "groups_downloaded": 0,
            "groups_partial": 0,
            "groups_failed": 0,
            "groups_skipped": 0,
            "files_downloaded": 0,
            "files_reused": 0,
            "files_failed": 0,
        }
        if not groups:
            return summary

        client_manager = TelegramClientManager(self.settings)
        client = await client_manager.authenticate()
        downloader = TelegramDownloader(
            self.settings.paths,
            self.file_repository,
            retry_attempts=options.retry_attempts,
        )
        try:
            for group in groups:
                result = await self._download_one_archive_group(
                    client=client,
                    downloader=downloader,
                    group=group,
                    options=options,
                )
                summary["groups_downloaded"] += int(result["group_status"] == "downloaded")
                summary["groups_partial"] += int(result["group_status"] == "partial")
                summary["groups_failed"] += int(result["group_status"] == "failed")
                summary["groups_skipped"] += int(result["group_status"] == "skipped")
                summary["files_downloaded"] += result["files_downloaded"]
                summary["files_reused"] += result["files_reused"]
                summary["files_failed"] += result["files_failed"]
        finally:
            await client.disconnect()
        self.session.flush()
        return summary

    async def _download_one_archive_group(
        self,
        *,
        client,
        downloader: TelegramDownloader,
        group: dict[str, Any],
        options: ArchiveDownloadOptions,
    ) -> dict[str, Any]:
        group_key = group["group_key"]
        group_files = group["files"]
        total_size_mb = group["total_size_mb"]
        multipart_status = group["multipart_group_status"]
        if options.skip_large_groups and total_size_mb > options.max_group_size_mb:
            logger.warning("Skipping archive group %s due to size %.2f MB > %.2f MB", group_key, total_size_mb, options.max_group_size_mb)
            for file_asset in group_files:
                file_asset.status = "skipped"
                file_asset.processing_status = "skipped"
                file_asset.notes = f"Skipped by max_group_size_mb={options.max_group_size_mb}"
                self.session.add(file_asset)
            return {"group_status": "skipped", "files_downloaded": 0, "files_reused": 0, "files_failed": 0}
        if options.download_only_complete_groups and multipart_status == "multipart_incomplete":
            logger.warning("Group %s incomplete in catalog; not downloading because download_only_complete_groups is enabled", group_key)
            self._mark_group_partial(group_files, reason=f"group {group_key} incomplete in catalog")
            return {"group_status": "partial", "files_downloaded": 0, "files_reused": 0, "files_failed": 0}

        logger.info("Starting archive group download group=%s files=%s size_mb=%.2f", group_key, len(group_files), total_size_mb)
        downloaded = reused = failed = 0
        for file_asset in group_files:
            path = Path(file_asset.stored_path)
            if path.exists():
                logger.info("archive already present file=%s", file_asset.file_name)
                file_asset.status = "downloaded"
                file_asset.processing_status = "downloaded"
                self.session.add(file_asset)
                reused += 1
                continue
            logger.info("downloading %s", file_asset.file_name)
            ok = await self._download_single_archive_asset(client=client, downloader=downloader, file_asset=file_asset)
            if ok:
                downloaded += 1
            else:
                failed += 1

        validation = self._validate_group_files(group_files)
        if validation["ready"]:
            logger.info("group %s complete", group_key)
            for file_asset in group_files:
                file_asset.status = "downloaded"
                file_asset.processing_status = "downloaded"
                file_asset.multipart_group_status = validation["multipart_group_status"]
                self.session.add(file_asset)
            return {"group_status": "downloaded", "files_downloaded": downloaded, "files_reused": reused, "files_failed": failed}

        if downloaded or reused:
            logger.warning("group %s incomplete", group_key)
            self._mark_group_partial(group_files, reason=validation["reason"])
            return {"group_status": "partial", "files_downloaded": downloaded, "files_reused": reused, "files_failed": failed}

        logger.error("group %s failed", group_key)
        for file_asset in group_files:
            if not Path(file_asset.stored_path).exists():
                file_asset.status = "failed"
                file_asset.processing_status = "failed"
                file_asset.notes = validation["reason"]
                self.session.add(file_asset)
        return {"group_status": "failed", "files_downloaded": downloaded, "files_reused": reused, "files_failed": failed or len(group_files)}

    async def _download_single_archive_asset(self, *, client, downloader: TelegramDownloader, file_asset) -> bool:
        if file_asset.message is None or file_asset.message.channel is None:
            file_asset.status = "failed"
            file_asset.processing_status = "failed"
            file_asset.notes = "Archive has no Telegram message/channel relation."
            self.session.add(file_asset)
            return False
        try:
            entity = await client.get_entity(file_asset.message.channel.input_reference)
            message = await client.get_messages(entity, ids=file_asset.message.telegram_message_id)
            if message is None or not message.media:
                file_asset.status = "failed"
                file_asset.processing_status = "failed"
                file_asset.notes = "Telegram message has no downloadable media."
                self.session.add(file_asset)
                return False
            plan = downloader.build_plan(message=message, channel=file_asset.message.channel)
            self.file_repository.mark_status(file_asset, status="downloading")
            downloaded = await downloader.download_to_asset(
                client=client,
                message=message,
                file_asset=file_asset,
                plan=plan,
            )
            return downloaded is not None and Path(file_asset.stored_path).exists()
        except Exception as exc:
            logger.exception("Failed to download archive %s", file_asset.file_name)
            file_asset.status = "failed"
            file_asset.processing_status = "failed"
            file_asset.notes = str(exc)[:500]
            self.session.add(file_asset)
            return False

    def _process_archive_payload(self, file_asset, path: Path, recommendation: str | None) -> str:
        if recommendation in {"process_now", "process_documents_only"}:
            extracted_files = self.archive_extractor.extract_documents(file_asset, max_files=12)
            processed_docs = 0
            failed_docs = 0
            for extracted in extracted_files:
                if self.document_processor.is_supported(Path(extracted.stored_path), extracted.file_name):
                    try:
                        self.document_processor.process(extracted)
                        processed_docs += 1
                    except Exception as exc:
                        extracted.status = "failed"
                        extracted.processing_status = "failed"
                        extracted.notes = f"{extracted.notes or ''}\nDocument processing failed: {exc}".strip()
                        self.session.add(extracted)
                        failed_docs += 1
                        logger.warning(
                            "Skipping failed extracted document file=%s archive=%s error=%s",
                            extracted.file_name,
                            file_asset.file_name,
                            exc,
                        )
            return (
                f"archive_documents_extracted={len(extracted_files)} "
                f"archive_documents_processed={processed_docs} "
                f"archive_documents_failed={failed_docs} recommendation={recommendation}"
            )
        return self._archive_inventory(path, file_asset.file_name)

    def process_external_links(self, provider: str | None = None, limit: int | None = None) -> dict[str, int]:
        repository = ExternalResourceRepository(self.session)
        resources = repository.list_pending(provider=provider, limit=limit)
        for resource in resources:
            resource.status = "queued"
            resource.notes = "Queued for provider-specific downloader. Automatic download intentionally disabled."
            self.session.add(resource)
        self.session.flush()
        return {"queued": len(resources)}

    def _process_files(self, categories: list[str], *, limit: int | None, handler) -> dict[str, int]:
        processed = skipped = failed = 0
        files = self.file_repository.list_by_category_status(
            categories=categories,
            statuses=["downloaded", "queued", "skipped"],
            limit=limit,
        )
        for file_asset in files:
            path = self._ensure_local_asset_path(file_asset)
            if path is None or not path.exists():
                file_asset.status = "queued"
                file_asset.processing_status = "queued"
                file_asset.notes = "Physical file is not downloaded yet."
                self.session.add(file_asset)
                skipped += 1
                continue
            try:
                handler(file_asset)
                processed += 1
            except Exception as exc:
                file_asset.status = "failed"
                file_asset.processing_status = "failed"
                file_asset.notes = str(exc)[:500]
                self.session.add(file_asset)
                failed += 1
                logger.exception("Failed to process cataloged asset %s", file_asset.file_name)
        self.session.flush()
        return {"processed": processed, "skipped": skipped, "failed": failed}

    def _process_document(self, file_asset) -> None:
        self.document_processor.process(file_asset)
        file_asset.processing_status = "extracted"

    def _process_image(self, file_asset) -> None:
        self.image_processor.process(file_asset)
        file_asset.processing_status = "extracted"

    def _process_media(self, file_asset) -> None:
        if file_asset.category == "video":
            self.video_processor.process(file_asset)
            file_asset.processing_status = "transcribed"
        else:
            self.audio_processor.process(file_asset)
            file_asset.processing_status = "transcribed"

    def _ensure_local_asset_path(self, file_asset) -> Path | None:
        path = Path(file_asset.stored_path)
        if path.exists():
            if file_asset.status in {"skipped", "partial", "inspection_file_missing", "failed"}:
                file_asset.status = "downloaded"
                self.session.add(file_asset)
            return path

        raw_root = self.settings.paths.raw_telegram_dir
        if not raw_root.exists():
            return None

        matches = [candidate for candidate in raw_root.rglob(file_asset.file_name) if candidate.is_file()]
        if not matches:
            return None

        message = getattr(file_asset, "message", None)
        message_hint = f"msg_{getattr(message, 'telegram_message_id', '')}" if message else ""

        def _score(candidate: Path) -> tuple[int, int, int]:
            as_text = str(candidate)
            message_match = int(bool(message_hint and message_hint in as_text))
            category_match = int(file_asset.category in as_text)
            return (message_match, category_match, -len(as_text))

        resolved = sorted(matches, key=_score, reverse=True)[0]
        file_asset.stored_path = str(resolved.resolve())
        if file_asset.status in {"skipped", "partial", "inspection_file_missing", "failed"}:
            file_asset.status = "downloaded"
        note = (file_asset.notes or "").strip()
        reconciliation = f"Reconciled local asset path -> {resolved}"
        file_asset.notes = f"{note}\n{reconciliation}".strip() if note else reconciliation
        self.session.add(file_asset)
        return resolved

    @staticmethod
    def _archive_inventory(path: Path, file_name: str) -> str:
        suffix = path.suffix.lower()
        if suffix != ".zip":
            return f"Inventory unsupported locally for {suffix}; install provider-specific tool for {file_name}."
        try:
            with ZipFile(path) as archive:
                entries = archive.infolist()[:200]
                return "\n".join(f"{entry.filename}\t{entry.file_size}" for entry in entries)
        except BadZipFile as exc:
            raise ValueError("invalid_zip_archive") from exc

    def _build_archive_groups(self, file_ids: list[int]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        groups: list[dict[str, Any]] = []
        for file_id in file_ids:
            file_asset = self.file_repository.get_by_id(file_id)
            if file_asset is None:
                continue
            group_files = self._group_files(file_asset)
            if not group_files:
                continue
            group_key = file_asset.archive_group_key or f"file:{file_asset.id}"
            if group_key in seen:
                continue
            seen.add(group_key)
            validation = self._validate_group_files(group_files)
            groups.append(
                {
                    "group_key": group_key,
                    "files": group_files,
                    "multipart_group_status": validation["multipart_group_status"],
                    "total_size_mb": round(sum((item.size_bytes or 0) for item in group_files) / (1024 * 1024), 2),
                }
            )
        groups.sort(key=lambda item: item["group_key"])
        return groups

    def _group_files(self, file_asset) -> list:
        if not file_asset.archive_group_key:
            return [file_asset]
        return sorted(
            [
                item
                for item in self.file_repository.list_archives()
                if item.archive_group_key == file_asset.archive_group_key
            ],
            key=lambda item: (item.archive_part_number or 999, item.id),
        )

    def _validate_archive_group(self, file_asset) -> dict[str, Any]:
        return self._validate_group_files(self._group_files(file_asset))

    @staticmethod
    def _validate_group_files(group_files: list) -> dict[str, Any]:
        multipart_status = group_files[0].multipart_group_status if group_files else "single_archive"
        paths_exist = all(Path(item.stored_path).exists() for item in group_files)
        if multipart_status == "multipart_incomplete":
            return {
                "ready": False,
                "multipart_group_status": multipart_status,
                "reason": "Multipart archive group is incomplete in the catalog.",
            }
        if not paths_exist:
            return {
                "ready": False,
                "multipart_group_status": multipart_status,
                "reason": "Not all archive parts are downloaded locally.",
            }
        return {
            "ready": True,
            "multipart_group_status": multipart_status,
            "reason": "Archive group is complete.",
        }

    def _mark_group_partial(self, group_files: list, *, reason: str) -> None:
        for file_asset in group_files:
            if not Path(file_asset.stored_path).exists():
                file_asset.status = "partial"
            else:
                file_asset.status = "downloaded"
            file_asset.processing_status = "partial"
            file_asset.notes = reason
            self.session.add(file_asset)
