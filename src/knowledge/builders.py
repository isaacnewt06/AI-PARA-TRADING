"""Knowledge base construction services."""

from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.document import Document
from src.db.models.external_resource import ExternalResource
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import ContentChunk
from src.db.models.telegram_message import TelegramMessage
from src.db.models.transcript import Transcript
from src.knowledge.schemas import ChunkPayload
from src.processing.chunker import TextChunker
from src.processing.entity_extractor import TradingEntityExtractor
from src.processing.text_cleaner import TextCleaner

logger = get_logger(__name__)


class KnowledgeBaseBuilder:
    """Create durable chunks from messages and processed documents."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.chunker = TextChunker(settings.tuning.chunk_size, settings.tuning.chunk_overlap)
        self.entity_extractor = TradingEntityExtractor()

    def build(self) -> int:
        created = 0
        created += self._build_from_messages()
        created += self._build_from_cataloged_files()
        created += self._build_from_external_resources()
        created += self._build_from_documents()
        created += self._build_from_transcripts()
        logger.info("Knowledge base build created %s chunks", created)
        return created

    def _build_from_cataloged_files(self) -> int:
        files = list(self.session.scalars(select(FileAsset).order_by(FileAsset.id.asc())))
        created = 0
        for file_asset in files:
            caption = file_asset.message.cleaned_text or file_asset.message.text if file_asset.message else None
            text = TextCleaner.clean(
                "\n".join(
                    str(item)
                    for item in [
                        f"Cataloged Telegram resource: {file_asset.file_name}",
                        f"category: {file_asset.category}",
                        f"extension: {file_asset.extension}",
                        f"priority: {file_asset.priority}",
                        f"status: {file_asset.status}",
                        f"size_bytes: {file_asset.size_bytes}",
                        f"caption: {caption}" if caption else None,
                    ]
                    if item
                )
            )
            if not text:
                continue
            created += self._upsert_chunks(
                source_type="cataloged_file",
                source_id=file_asset.id,
                channel_id=file_asset.channel_id,
                message_id=file_asset.message_id,
                file_id=file_asset.id,
                file_name=file_asset.file_name,
                original_date=file_asset.message.posted_at if file_asset.message else None,
                text=text,
                metadata={
                    "channel_name": file_asset.channel.title if file_asset.channel else None,
                    "source_reference": f"cataloged_file:{file_asset.id}",
                    "file_name": file_asset.file_name,
                    "priority": file_asset.priority,
                    "status": file_asset.status,
                    "knowledge_preservation": True,
                },
            )
        return created

    def _build_from_external_resources(self) -> int:
        resources = list(self.session.scalars(select(ExternalResource).order_by(ExternalResource.id.asc())))
        created = 0
        for resource in resources:
            caption = resource.message.cleaned_text or resource.message.text if resource.message else None
            text = TextCleaner.clean(
                "\n".join(
                    str(item)
                    for item in [
                        f"External Telegram resource: {resource.url}",
                        f"provider: {resource.provider}",
                        f"file_hint: {resource.file_hint}",
                        f"priority: {resource.priority}",
                        f"status: {resource.status}",
                        f"caption: {caption}" if caption else None,
                    ]
                    if item
                )
            )
            if not text:
                continue
            created += self._upsert_chunks(
                source_type="external_resource",
                source_id=resource.id,
                channel_id=resource.message.channel_id if resource.message else None,
                message_id=resource.message_id,
                file_id=None,
                file_name=resource.file_hint,
                original_date=resource.message.posted_at if resource.message else None,
                text=text,
                metadata={
                    "source_reference": f"external_resource:{resource.id}",
                    "provider": resource.provider,
                    "priority": resource.priority,
                    "status": resource.status,
                    "knowledge_preservation": True,
                },
            )
        return created

    def _build_from_messages(self) -> int:
        stmt = select(TelegramMessage).where(TelegramMessage.cleaned_text.is_not(None))
        messages = list(self.session.scalars(stmt))
        created = 0
        for message in messages:
            created += self._upsert_chunks(
                source_type="telegram_message",
                source_id=message.id,
                channel_id=message.channel_id,
                message_id=message.id,
                file_id=None,
                file_name=None,
                original_date=message.posted_at,
                text=message.cleaned_text or "",
                metadata={
                    "classification": message.classification,
                    "channel_name": message.channel.title if message.channel else None,
                    "source_reference": f"telegram_message:{message.telegram_message_id}",
                    "entities": asdict(self.entity_extractor.extract(message.cleaned_text)),
                },
            )
        return created

    def _build_from_documents(self) -> int:
        documents = list(self.session.scalars(select(Document).where(Document.extracted_text.is_not(None))))
        created = 0
        for document in documents:
            created += self._upsert_chunks(
                source_type="document",
                source_id=document.id,
                channel_id=document.file.channel_id if document.file else None,
                message_id=document.file.message_id if document.file else None,
                file_id=document.file_id,
                file_name=document.file.file_name if document.file else None,
                original_date=document.file.message.posted_at if document.file and document.file.message else None,
                text=document.extracted_text or "",
                metadata={
                    "summary": document.summary,
                    "doc_type": document.doc_type,
                    "channel_name": document.file.channel.title if document.file and document.file.channel else None,
                    "source_reference": f"document:{document.id}",
                    "file_name": document.file.file_name if document.file else None,
                },
            )
        return created

    def _build_from_transcripts(self) -> int:
        transcripts = list(
            self.session.scalars(
                select(Transcript).where(
                    Transcript.content.is_not(None),
                    Transcript.status == "completed",
                )
            )
        )
        created = 0
        for transcript in transcripts:
            source_file = transcript.source_file
            if source_file is None or not transcript.content:
                continue
            created += self._upsert_chunks(
                source_type="transcript",
                source_id=transcript.id,
                channel_id=source_file.channel_id,
                message_id=source_file.message_id,
                file_id=source_file.id,
                file_name=source_file.file_name,
                original_date=source_file.message.posted_at if source_file.message else None,
                text=transcript.content,
                metadata={
                    "channel_name": source_file.channel.title if source_file.channel else None,
                    "source_reference": f"transcript:{transcript.id}",
                    "file_name": source_file.file_name,
                    "provider": transcript.provider,
                    "language": transcript.language,
                },
            )
        return created

    def _upsert_chunks(
        self,
        *,
        source_type: str,
        source_id: int,
        channel_id: int | None,
        message_id: int | None,
        file_id: int | None,
        file_name: str | None,
        original_date,
        text: str,
        metadata: dict,
    ) -> int:
        existing_rows = list(
            self.session.scalars(
                select(ContentChunk).where(ContentChunk.source_type == source_type, ContentChunk.source_id == source_id)
            )
        )
        existing_by_index = {row.chunk_index: row for row in existing_rows}

        payloads = [
            ChunkPayload(
                source_id=source_id,
                source_type=source_type,
                channel_id=channel_id,
                message_id=message_id,
                file_id=file_id,
                file_name=file_name,
                original_date=original_date,
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
                self.session.add(ContentChunk(**payload.model_dump()))
                created += 1
                continue
            row.text = payload.text
            row.clean_text = payload.clean_text
            row.channel_id = payload.channel_id
            row.message_id = payload.message_id
            row.file_id = payload.file_id
            row.file_name = payload.file_name
            row.original_date = payload.original_date
            row.metadata_json = payload.metadata_json
            self.session.add(row)

        for row in existing_rows:
            if row.chunk_index not in seen_indexes:
                self.session.delete(row)
        self.session.flush()
        return created
