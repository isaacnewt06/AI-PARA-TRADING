"""File repository."""

from __future__ import annotations

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from src.db.models.document import Document
from src.db.models.file_asset import FileAsset
from src.db.models.media import AudioAsset, VideoAsset


class FileRepository:
    """Persistence helpers for downloaded files."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_duplicate(self, *, file_hash: str | None, file_name: str, size_bytes: int | None) -> FileAsset | None:
        return self.find_by_content_signature(file_hash=file_hash, size_bytes=size_bytes) or self.find_by_file_identity(
            file_name=file_name,
            size_bytes=size_bytes,
        )

    def find_by_content_signature(self, *, file_hash: str | None, size_bytes: int | None) -> FileAsset | None:
        if not file_hash:
            return None
        stmt = select(FileAsset).where(
            FileAsset.file_hash == file_hash,
            FileAsset.size_bytes == size_bytes,
        )
        return self.session.scalar(stmt)

    def find_by_file_identity(self, *, file_name: str, size_bytes: int | None) -> FileAsset | None:
        stmt = select(FileAsset).where(
            FileAsset.file_name == file_name,
            FileAsset.size_bytes == size_bytes,
        )
        return self.session.scalar(stmt)

    def find_by_telegram_file(self, *, message_id: int, telegram_file_id: str | None) -> FileAsset | None:
        if not telegram_file_id:
            return None
        stmt = select(FileAsset).where(
            FileAsset.message_id == message_id,
            FileAsset.telegram_file_id == telegram_file_id,
        )
        return self.session.scalar(stmt)

    def get_by_message(self, message_id: int) -> list[FileAsset]:
        stmt = select(FileAsset).where(FileAsset.message_id == message_id)
        return list(self.session.scalars(stmt))

    def find_by_stored_path(self, stored_path: str) -> FileAsset | None:
        stmt = select(FileAsset).where(FileAsset.stored_path == stored_path)
        return self.session.scalar(stmt)

    def create(self, payload: dict) -> FileAsset:
        entity = FileAsset(**payload)
        self.session.add(entity)
        self.session.flush()
        return entity

    def upsert_discovered(self, payload: dict) -> tuple[FileAsset, bool]:
        entity = self.find_by_telegram_file(
            message_id=payload["message_id"],
            telegram_file_id=payload.get("telegram_file_id"),
        )
        if entity is None:
            entity = self.find_by_stored_path(payload["stored_path"])
        created = entity is None
        if entity is None:
            entity = FileAsset(**payload)
            self.session.add(entity)
        else:
            for key, value in payload.items():
                if key in {"status", "processing_status"} and entity.status == "downloaded":
                    continue
                setattr(entity, key, value)
        self.session.flush()
        return entity, created

    def mark_status(
        self,
        file_asset: FileAsset,
        *,
        status: str,
        stored_path: str | None = None,
        size_bytes: int | None = None,
        file_hash: str | None = None,
    ) -> FileAsset:
        file_asset.status = status
        if stored_path is not None:
            file_asset.stored_path = stored_path
        if size_bytes is not None:
            file_asset.size_bytes = size_bytes
        if file_hash is not None:
            file_asset.file_hash = file_hash
        file_asset.processing_status = status
        self.session.add(file_asset)
        self.session.flush()
        return file_asset

    def list_documents_pending(self) -> list[FileAsset]:
        stmt = (
            select(FileAsset)
            .outerjoin(Document, Document.file_id == FileAsset.id)
            .where(
                FileAsset.category.in_(["document", "generic"]),
                Document.id.is_(None),
            )
            .order_by(FileAsset.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_by_category_status(
        self,
        *,
        categories: list[str],
        statuses: list[str] | None = None,
        limit: int | None = None,
    ) -> list[FileAsset]:
        stmt = select(FileAsset).where(FileAsset.category.in_(categories))
        if statuses:
            stmt = stmt.where(FileAsset.status.in_(statuses))
        stmt = stmt.order_by(FileAsset.priority.asc(), FileAsset.id.asc())
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def list_media_pending(self) -> list[FileAsset]:
        stmt = (
            select(FileAsset)
            .outerjoin(VideoAsset, VideoAsset.file_id == FileAsset.id)
            .outerjoin(AudioAsset, AudioAsset.file_id == FileAsset.id)
            .where(
                or_(
                    and_(FileAsset.category == "video", VideoAsset.id.is_(None)),
                    and_(FileAsset.category == "audio", AudioAsset.id.is_(None)),
                    and_(FileAsset.category == "image", ~FileAsset.status.like("image:%")),
                )
            )
            .order_by(FileAsset.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_archives(self, limit: int | None = None) -> list[FileAsset]:
        stmt = (
            select(FileAsset)
            .where(FileAsset.extension.in_([".zip", ".rar", ".7z"]))
            .order_by(
                desc(FileAsset.archive_selection_score),
                FileAsset.priority.asc(),
                FileAsset.id.asc(),
            )
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def list_pending_downloads(
        self,
        *,
        categories: list[str] | None = None,
        statuses: list[str] | None = None,
        limit: int | None = None,
    ) -> list[FileAsset]:
        stmt = select(FileAsset)
        if categories:
            stmt = stmt.where(FileAsset.category.in_(categories))
        if statuses:
            stmt = stmt.where(FileAsset.status.in_(statuses))
        stmt = stmt.order_by(
            FileAsset.priority.asc(),
            FileAsset.size_bytes.asc().nulls_last(),
            FileAsset.id.asc(),
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_by_id_or_name(self, value: str) -> FileAsset | None:
        stmt = select(FileAsset)
        if value.isdigit():
            entity = self.session.get(FileAsset, int(value))
            if entity is not None:
                return entity
        stmt = stmt.where((FileAsset.file_name == value) | (FileAsset.stored_path == value))
        return self.session.scalar(stmt)

    def get_by_id(self, file_id: int) -> FileAsset | None:
        return self.session.get(FileAsset, file_id)

    def list_prioritizable_documents(self, limit: int | None = None) -> list[FileAsset]:
        stmt = (
            select(FileAsset)
            .where(FileAsset.category.in_(["document", "generic"]))
            .order_by(
                desc(FileAsset.priority_score),
                desc(FileAsset.knowledge_density_score),
                desc(FileAsset.strategy_probability_score),
                FileAsset.id.asc(),
            )
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def update_priority_scores(
        self,
        file_asset: FileAsset,
        *,
        knowledge_density_score: float,
        strategy_probability_score: float,
        priority_score: float,
        priority_notes: str,
    ) -> FileAsset:
        file_asset.knowledge_density_score = knowledge_density_score
        file_asset.strategy_probability_score = strategy_probability_score
        file_asset.priority_score = priority_score
        file_asset.priority_notes = priority_notes
        self.session.add(file_asset)
        self.session.flush()
        return file_asset
