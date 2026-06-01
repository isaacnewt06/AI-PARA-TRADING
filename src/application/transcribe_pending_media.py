"""Transcribe already-downloaded media assets into completed transcripts."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.file_asset import FileAsset
from src.db.models.transcript import Transcript
from src.processing.audio_processor import AudioProcessor
from src.processing.video_processor import VideoProcessor

logger = get_logger(__name__)


class PendingMediaTranscriptionApplicationService:
    """Convert downloaded media with pending transcripts into completed transcript content."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.audio_processor = AudioProcessor(session, settings)
        self.video_processor = VideoProcessor(session, settings)

    def run(self, *, limit: int = 10, categories: list[str] | None = None) -> dict[str, int]:
        categories = categories or ["video", "audio"]
        candidates = list(
            self.session.scalars(
                select(FileAsset)
                .outerjoin(Transcript, Transcript.source_file_id == FileAsset.id)
                .where(
                    FileAsset.category.in_(categories),
                    FileAsset.status.in_(["audio_extracted", "completed", "downloaded", "skipped"]),
                    or_(Transcript.id.is_(None), Transcript.status != "completed"),
                )
                .order_by(FileAsset.id.asc())
                .limit(max(limit * 20, limit))
            )
        )
        files: list[FileAsset] = []
        skipped_missing = 0
        for file_asset in candidates:
            if not file_asset.stored_path or not Path(file_asset.stored_path).exists():
                skipped_missing += 1
                continue
            files.append(file_asset)
            if len(files) >= limit:
                break
        transcribed = skipped = failed = 0
        for file_asset in files:
            transcript = file_asset.transcript
            if transcript is not None and transcript.status == "completed" and transcript.content:
                skipped += 1
                continue
            try:
                if file_asset.category == "video":
                    self.video_processor.process(file_asset)
                else:
                    self.audio_processor.process(file_asset)
                file_asset.processing_status = "transcribed"
                self.session.add(file_asset)
                self.session.flush()
                transcribed += 1
            except Exception as exc:
                failed += 1
                file_asset.notes = f"{(file_asset.notes or '').strip()}\ntranscription_failed: {exc}".strip()
                self.session.add(file_asset)
                logger.exception("Failed to transcribe media file_id=%s file=%s", file_asset.id, file_asset.file_name)
        self.session.flush()
        return {
            "selected": len(files),
            "transcribed": transcribed,
            "skipped": skipped + skipped_missing,
            "failed": failed,
        }
