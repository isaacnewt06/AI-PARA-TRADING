"""Import manually curated high-value trading knowledge into the KB."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.core.paths import sanitize_filesystem_name
from src.db.models.knowledge import ChunkEmbedding, ContentChunk
from src.db.repositories.channels import ChannelRepository
from src.db.repositories.messages import MessageRepository
from src.processing.classifier import HeuristicContentClassifier
from src.processing.text_cleaner import TextCleaner

logger = get_logger(__name__)


class ManualKnowledgeImportService:
    """Import markdown notes as durable manual high-quality knowledge sources."""

    def __init__(self, session: Session, root_dir: Path) -> None:
        self.session = session
        self.root_dir = root_dir
        self.channel_repository = ChannelRepository(session)
        self.message_repository = MessageRepository(session)
        self.classifier = HeuristicContentClassifier()

    def run(self) -> dict[str, int]:
        imported = 0
        chunks_created = 0
        for path in self._iter_note_files():
            channel = self.channel_repository.create_or_update(
                input_reference="manual://knowledge",
                title="Manual Knowledge",
                normalized_name=sanitize_filesystem_name("manual_knowledge", fallback="manual_knowledge"),
                telegram_channel_id=None,
            )
            channel.is_active = True
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            cleaned = TextCleaner.clean(text)
            message, created = self.message_repository.upsert(
                {
                    "channel_id": channel.id,
                    "telegram_message_id": self._stable_message_id(path),
                    "reply_to_message_id": None,
                    "posted_at": datetime.now(timezone.utc),
                    "content_type": "manual_protocol",
                    "text": text,
                    "cleaned_text": cleaned,
                    "language": "en",
                    "classification": self.classifier.classify(cleaned).label,
                    "has_media": False,
                    "priority": "high",
                    "processing_status": "indexed",
                    "raw_json": json.dumps(
                        {
                            "source_kind": "manual_knowledge",
                            "path": str(path),
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            if created:
                imported += 1
            chunks_created += self._upsert_chunk(channel.id, message.id, path, text)
        self.session.flush()
        return {"manual_notes_imported": imported, "chunks_created": chunks_created}

    def _upsert_chunk(self, channel_id: int, message_id: int, path: Path, text: str) -> int:
        existing = self.session.scalar(
            select(ContentChunk).where(
                ContentChunk.source_type == "manual_note",
                ContentChunk.source_id == message_id,
                ContentChunk.chunk_index == 0,
            )
        )
        metadata = {
            "channel_name": "Manual Knowledge",
            "source_reference": f"manual_note:{path.name}",
            "authors": ["user_manual_protocol"],
            "module_name": path.stem,
            "file_name": path.name,
            "path": str(path),
            "manual_curated": True,
        }
        cleaned = TextCleaner.clean(text)
        if existing is None:
            self.session.add(
                ContentChunk(
                    source_type="manual_note",
                    source_id=message_id,
                    channel_id=channel_id,
                    message_id=message_id,
                    file_id=None,
                    file_name=path.name,
                    original_date=datetime.now(timezone.utc),
                    chunk_index=0,
                    text=text,
                    clean_text=cleaned,
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    embedding_status="pending",
                    quality_score=0.98,
                    source_weight=1.0,
                    usefulness_score=0.99,
                    quality_label="manual_high_value",
                    quality_flags_json=json.dumps(["manual", "curated", "strategy_protocol"], ensure_ascii=False),
                    filtered_out=False,
                )
            )
            return 1

        existing.text = text
        existing.clean_text = cleaned
        existing.channel_id = channel_id
        existing.message_id = message_id
        existing.file_name = path.name
        existing.metadata_json = json.dumps(metadata, ensure_ascii=False)
        existing.embedding_status = "pending"
        existing.quality_score = 0.98
        existing.source_weight = 1.0
        existing.usefulness_score = 0.99
        existing.quality_label = "manual_high_value"
        existing.quality_flags_json = json.dumps(["manual", "curated", "strategy_protocol"], ensure_ascii=False)
        existing.filtered_out = False
        self.session.add(existing)
        self.session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id == existing.id))
        return 0

    def _iter_note_files(self) -> list[Path]:
        if not self.root_dir.exists():
            return []
        paths = [
            path
            for path in self.root_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}
        ]
        return sorted(paths, key=lambda item: item.name.lower())

    @staticmethod
    def _stable_message_id(path: Path) -> int:
        digest = hashlib.sha1(f"manual_note:{path.as_posix()}".encode("utf-8")).hexdigest()
        return int(digest[:10], 16) % 2_000_000_000
