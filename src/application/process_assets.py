"""Application service for processing assets."""

from __future__ import annotations

from pathlib import Path

from langdetect import DetectorFactory, LangDetectException, detect
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.repositories.files import FileRepository
from src.db.repositories.messages import MessageRepository
from src.db.repositories.runs import RunRepository
from src.processing.audio_processor import AudioProcessor
from src.processing.classifier import HeuristicContentClassifier
from src.processing.document_processor import DocumentProcessor
from src.processing.image_processor import ImageProcessor
from src.processing.text_cleaner import TextCleaner
from src.processing.video_processor import VideoProcessor

logger = get_logger(__name__)
DetectorFactory.seed = 0


class ProcessingApplicationService:
    """Process raw messages and downloaded assets."""

    def __init__(self, session: Session, settings: Settings, run_repository: RunRepository) -> None:
        self.session = session
        self.settings = settings
        self.run_repository = run_repository
        self.message_repository = MessageRepository(session)
        self.file_repository = FileRepository(session)
        self.classifier = HeuristicContentClassifier()
        self.document_processor = DocumentProcessor(session, settings)
        self.video_processor = VideoProcessor(session, settings)
        self.audio_processor = AudioProcessor(session, settings)
        self.image_processor = ImageProcessor(session)

    def run(self) -> dict:
        run = self.run_repository.start_processing()
        summary = {
            "messages_processed": 0,
            "documents_processed": 0,
            "media_processed": 0,
            "chunks_created": 0,
            "errors_count": 0,
        }
        try:
            summary["messages_processed"], message_errors = self._process_messages()
            summary["documents_processed"], document_errors = self._process_documents()
            summary["media_processed"], media_errors = self._process_media()
            summary["errors_count"] = message_errors + document_errors + media_errors
            run.messages_processed = summary["messages_processed"]
            run.documents_processed = summary["documents_processed"]
            run.media_processed = summary["media_processed"]
            run.chunks_created = summary["chunks_created"]
            run.errors_count = summary["errors_count"]
            self.run_repository.finish_processing(run, status="completed")
            return summary
        except Exception as exc:
            summary["errors_count"] += 1
            run.messages_processed = summary["messages_processed"]
            run.documents_processed = summary["documents_processed"]
            run.media_processed = summary["media_processed"]
            run.chunks_created = summary["chunks_created"]
            run.errors_count = summary["errors_count"]
            self.run_repository.finish_processing(run, status="failed", notes=str(exc))
            logger.exception("Processing run failed")
            raise

    def _process_messages(self) -> tuple[int, int]:
        count = 0
        errors = 0
        messages = self.message_repository.list_unprocessed_texts()
        for message in messages:
            try:
                if not message.text:
                    continue
                cleaned = TextCleaner.clean(message.text)
                if message.cleaned_text == cleaned and message.classification and message.language:
                    continue
                message.cleaned_text = cleaned
                message.classification = self.classifier.classify(cleaned).label
                message.language = self._detect_language(cleaned)
                self.session.add(message)
                count += 1
            except Exception:
                errors += 1
                logger.exception("Failed to process message id=%s", message.id)
        self.session.flush()
        return count, errors

    def _process_documents(self) -> tuple[int, int]:
        count = 0
        errors = 0
        for file_asset in self.file_repository.list_documents_pending():
            try:
                if not self.document_processor.is_supported(Path(file_asset.stored_path), file_asset.file_name):
                    file_asset.status = "unsupported_document_type"
                    self.session.add(file_asset)
                    continue
                self.document_processor.process(file_asset)
                count += 1
            except Exception:
                errors += 1
                file_asset.status = "processing_failed"
                self.session.add(file_asset)
                logger.exception("Failed to process document %s", file_asset.file_name)
        return count, errors

    def _process_media(self) -> tuple[int, int]:
        count = 0
        errors = 0
        for file_asset in self.file_repository.list_media_pending():
            try:
                if file_asset.category == "video" and not file_asset.video_asset:
                    self.video_processor.process(file_asset)
                    count += 1
                elif file_asset.category == "audio" and not file_asset.audio_asset:
                    self.audio_processor.process(file_asset)
                    count += 1
                elif file_asset.category == "image" and not str(file_asset.status).startswith("image:"):
                    self.image_processor.process(file_asset)
                    count += 1
            except Exception:
                errors += 1
                file_asset.status = "processing_failed"
                self.session.add(file_asset)
                logger.exception("Failed to process media asset %s", file_asset.file_name)
        return count, errors

    def _detect_language(self, text: str) -> str:
        if not text:
            return self.settings.tuning.default_language
        try:
            return detect(text)
        except LangDetectException:
            return self.settings.tuning.default_language
