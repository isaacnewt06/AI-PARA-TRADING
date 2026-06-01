"""Import local educational trading documents into the knowledge base."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.core.paths import sanitize_filesystem_name
from src.db.models.knowledge import ChunkEmbedding, ContentChunk
from src.db.models.telegram_message import TelegramMessage
from src.db.repositories.channels import ChannelRepository
from src.db.repositories.knowledge import RuleRepository
from src.db.repositories.messages import MessageRepository
from src.knowledge.schemas import ChunkPayload
from src.processing.chunker import TextChunker
from src.processing.classifier import HeuristicContentClassifier
from src.processing.document_processor import DocumentProcessor
from src.processing.text_cleaner import TextCleaner

logger = get_logger(__name__)


class LocalEducationImportService:
    """Import high-value local trading education files as durable KB chunks."""

    SUPPORTED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}
    POSITIVE_KEYWORDS = {
        "trading",
        "day trading",
        "risk reward",
        "risk",
        "reward",
        "temporalidades",
        "tendencias",
        "tendencia",
        "soportes",
        "resistencias",
        "análisis técnico",
        "analisis tecnico",
        "volatilidad",
        "volumen",
        "williams",
        "price target",
        "options",
        "covered calls",
        "cash secured",
        "kill zone",
        "silver bullet",
        "ict",
        "journal",
        "principio",
        "curso",
        "clase",
        "setup",
        "estrateg",
        "mentor",
        "conference calls",
        "pe ratio",
        "ley de 200 días",
        "ley de 200 dias",
    }
    NEGATIVE_KEYWORDS = {
        "cedula",
        "curriculum",
        "certificado",
        "encuesta",
        "perfil de riesgo",
        "copia de cedula",
        "personal",
    }

    def __init__(self, session: Session, settings: Settings, root_dir: Path) -> None:
        self.session = session
        self.settings = settings
        self.root_dir = root_dir
        self.channel_repository = ChannelRepository(session)
        self.message_repository = MessageRepository(session)
        self.rule_repository = RuleRepository(session)
        self.classifier = HeuristicContentClassifier()
        self.chunker = TextChunker(settings.tuning.chunk_size, settings.tuning.chunk_overlap)

    def run(self) -> dict[str, int | str]:
        channel = self.channel_repository.create_or_update(
            input_reference=f"local-education://{self.root_dir.name.lower()}",
            title=f"Local Education - {self.root_dir.name}",
            normalized_name=sanitize_filesystem_name(f"local_education_{self.root_dir.name}", fallback="local_education"),
            telegram_channel_id=None,
        )
        channel.is_active = True

        imported = 0
        skipped_irrelevant = 0
        failed = 0
        chunks_created = 0
        active_message_ids: set[int] = set()

        for path in self._iter_supported_files():
            relevance = self._relevance(path)
            if relevance["skip"]:
                skipped_irrelevant += 1
                logger.info("Skipping local education file as irrelevant path=%s reason=%s", path, relevance["reason"])
                continue
            try:
                extracted = self._extract_text(path)
                if self._is_code_like(path, extracted):
                    skipped_irrelevant += 1
                    logger.info("Skipping local education code-like file path=%s", path)
                    continue
                if len(extracted.strip()) < 80:
                    skipped_irrelevant += 1
                    logger.info("Skipping local education file with too little content path=%s", path)
                    continue
                cleaned = TextCleaner.clean(extracted)
                stored_text_path = self._write_extracted_text(path, cleaned)
                message, created = self.message_repository.upsert(
                    {
                        "channel_id": channel.id,
                        "telegram_message_id": self._stable_message_id(path),
                        "reply_to_message_id": None,
                        "posted_at": datetime.now(timezone.utc),
                        "content_type": "local_education_document",
                        "text": cleaned,
                        "cleaned_text": cleaned,
                        "language": "mixed",
                        "classification": self.classifier.classify(cleaned).label,
                        "has_media": True,
                        "priority": relevance["priority"],
                        "processing_status": "indexed",
                        "raw_json": json.dumps(
                            {
                                "source_kind": "local_education",
                                "file_name": path.name,
                                "path": str(path),
                                "stored_text_path": str(stored_text_path),
                                "relevance_reason": relevance["reason"],
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
                active_message_ids.add(message.id)
                if created:
                    imported += 1
                chunks_created += self._upsert_chunks(
                    channel_id=channel.id,
                    message_id=message.id,
                    path=path,
                    text=cleaned,
                    quality_score=float(relevance["quality_score"]),
                    source_weight=float(relevance["source_weight"]),
                    usefulness_score=float(relevance["usefulness_score"]),
                    relevance_reason=str(relevance["reason"]),
                )
            except Exception:
                failed += 1
                logger.exception("Failed importing local education file path=%s", path)

        self._cleanup_stale_rows(channel_id=channel.id, active_message_ids=active_message_ids)
        self.session.flush()
        return {
            "source": str(self.root_dir),
            "files_imported": imported,
            "files_skipped_irrelevant": skipped_irrelevant,
            "files_failed": failed,
            "chunks_created": chunks_created,
            "channel_name": channel.title,
        }

    def _upsert_chunks(
        self,
        *,
        channel_id: int,
        message_id: int,
        path: Path,
        text: str,
        quality_score: float,
        source_weight: float,
        usefulness_score: float,
        relevance_reason: str,
    ) -> int:
        existing_rows = list(
            self.session.scalars(
                select(ContentChunk).where(
                    ContentChunk.source_type == "local_education",
                    ContentChunk.source_id == message_id,
                )
            )
        )
        existing_by_index = {row.chunk_index: row for row in existing_rows}
        metadata = {
            "channel_name": f"Local Education - {self.root_dir.name}",
            "source_reference": f"local_education:{path.name}",
            "authors": ["local_education_source"],
            "module_name": path.stem,
            "file_name": path.name,
            "path": str(path),
            "source_kind": "local_education",
            "relevance_reason": relevance_reason,
        }
        payloads = [
            ChunkPayload(
                source_id=message_id,
                source_type="local_education",
                channel_id=channel_id,
                message_id=message_id,
                file_id=None,
                file_name=path.name,
                original_date=datetime.now(timezone.utc),
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                clean_text=TextCleaner.clean(chunk.clean_text),
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )
            for chunk in self.chunker.split(text)
        ]

        created = 0
        seen_indexes: set[int] = set()
        for payload in payloads:
            seen_indexes.add(payload.chunk_index)
            row = existing_by_index.get(payload.chunk_index)
            if row is None:
                self.session.add(
                    ContentChunk(
                        **payload.model_dump(),
                        embedding_status="pending",
                        quality_score=quality_score,
                        source_weight=source_weight,
                        usefulness_score=usefulness_score,
                        quality_label="local_education_high_value",
                        quality_flags_json=json.dumps(["local_education", "trading", "curated"], ensure_ascii=False),
                        filtered_out=False,
                    )
                )
                created += 1
                continue
            row.text = payload.text
            row.clean_text = payload.clean_text
            row.channel_id = payload.channel_id
            row.message_id = payload.message_id
            row.file_name = payload.file_name
            row.original_date = payload.original_date
            row.metadata_json = payload.metadata_json
            row.embedding_status = "pending"
            row.quality_score = quality_score
            row.source_weight = source_weight
            row.usefulness_score = usefulness_score
            row.quality_label = "local_education_high_value"
            row.quality_flags_json = json.dumps(["local_education", "trading", "curated"], ensure_ascii=False)
            row.filtered_out = False
            self.session.add(row)
            self.session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id == row.id))

        for row in existing_rows:
            if row.chunk_index not in seen_indexes:
                self.session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id == row.id))
                self.session.delete(row)
        self.session.flush()
        return created

    def _cleanup_stale_rows(self, *, channel_id: int, active_message_ids: set[int]) -> None:
        stale_chunks = list(
            self.session.scalars(
                select(ContentChunk).where(
                    ContentChunk.source_type == "local_education",
                    ContentChunk.channel_id == channel_id,
                )
            )
        )
        stale_chunk_ids = [chunk.id for chunk in stale_chunks if chunk.message_id not in active_message_ids]
        for chunk_id in stale_chunk_ids:
            self.rule_repository.delete_for_chunk(chunk_id)
            self.session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id == chunk_id))
        if stale_chunk_ids:
            self.session.execute(delete(ContentChunk).where(ContentChunk.id.in_(stale_chunk_ids)))
        if active_message_ids:
            stale_message_ids = list(
                self.session.scalars(
                    select(TelegramMessage.id).where(
                        TelegramMessage.channel_id == channel_id,
                        TelegramMessage.id.not_in(active_message_ids),
                    )
                )
            )
        else:
            stale_message_ids = list(
                self.session.scalars(
                    select(TelegramMessage.id).where(TelegramMessage.channel_id == channel_id)
                )
            )
        if stale_message_ids:
            self.session.execute(delete(TelegramMessage).where(TelegramMessage.id.in_(stale_message_ids)))
        self.session.flush()

    def _extract_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return DocumentProcessor._extract_pdf(path)
        if suffix == ".docx":
            return DocumentProcessor._extract_docx(path)
        if suffix in {".xlsx", ".xlsm"}:
            return DocumentProcessor._extract_xlsx(path)
        return TextCleaner.clean(path.read_text(encoding="utf-8", errors="ignore"))

    def _write_extracted_text(self, source_path: Path, text: str) -> Path:
        output_dir = self.settings.paths.processed_dir / "local_education"
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = sanitize_filesystem_name(source_path.stem, fallback="local_education_file")
        target = output_dir / f"{safe_name}.txt"
        target.write_text(text, encoding="utf-8")
        return target

    def _iter_supported_files(self) -> list[Path]:
        if not self.root_dir.exists():
            return []
        return sorted(
            [
                path
                for path in self.root_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in self.SUPPORTED_SUFFIXES
            ],
            key=lambda item: item.name.lower(),
        )

    def _relevance(self, path: Path) -> dict[str, str | float | bool]:
        haystack = f"{path.name} {path.stem}".lower()
        negative_hits = sum(1 for keyword in self.NEGATIVE_KEYWORDS if keyword in haystack)
        positive_hits = sum(1 for keyword in self.POSITIVE_KEYWORDS if keyword in haystack)
        if negative_hits > 0 and positive_hits == 0:
            return {
                "skip": True,
                "reason": "administrative_or_personal_document",
                "priority": "low",
                "quality_score": 0.0,
                "source_weight": 0.0,
                "usefulness_score": 0.0,
            }
        priority = "high" if positive_hits >= 2 else "medium"
        quality_score = min(0.99, 0.70 + positive_hits * 0.05)
        source_weight = min(1.0, 0.65 + positive_hits * 0.07)
        usefulness_score = min(0.99, (quality_score + source_weight) / 2.0)
        return {
            "skip": False,
            "reason": f"positive_keyword_hits={positive_hits}",
            "priority": priority,
            "quality_score": round(quality_score, 4),
            "source_weight": round(source_weight, 4),
            "usefulness_score": round(usefulness_score, 4),
        }

    @staticmethod
    def _is_code_like(path: Path, text: str) -> bool:
        if path.suffix.lower() not in {".txt", ".md"}:
            return False
        lowered = text.lower()
        code_markers = (
            "//@version",
            "indicator(",
            "strategy(",
            "plot(",
            "line.new(",
            "label.new(",
            "input.",
            "syminfo.",
            "bar_index",
            "request.security",
        )
        hits = sum(1 for marker in code_markers if marker in lowered)
        return hits >= 2

    @staticmethod
    def _stable_message_id(path: Path) -> int:
        digest = hashlib.sha1(f"local_education:{path.as_posix()}".encode("utf-8")).hexdigest()
        return int(digest[:10], 16) % 2_000_000_000
