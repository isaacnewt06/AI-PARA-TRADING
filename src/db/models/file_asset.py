"""Generic file asset model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class FileAsset(TimestampMixin, Base):
    """Downloaded file metadata."""

    __tablename__ = "files"
    __table_args__ = (
        Index("ix_files_message_id", "message_id"),
        Index("ix_files_hash_size", "file_hash", "size_bytes"),
        Index("ix_files_archive_selection_score", "archive_selection_score"),
        Index("ix_files_archive_recommendation", "archive_processing_recommendation"),
        UniqueConstraint("message_id", "telegram_file_id", name="uq_files_message_telegram_file"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_messages.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="downloaded", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), default="discovered", nullable=False)
    knowledge_density_score: Mapped[float | None] = mapped_column(nullable=True)
    strategy_probability_score: Mapped[float | None] = mapped_column(nullable=True)
    priority_score: Mapped[float | None] = mapped_column(nullable=True)
    priority_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    archive_selection_score: Mapped[float | None] = mapped_column(nullable=True)
    archive_usefulness_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archive_selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    archive_document_count: Mapped[int | None] = mapped_column(nullable=True)
    archive_video_count: Mapped[int | None] = mapped_column(nullable=True)
    archive_image_count: Mapped[int | None] = mapped_column(nullable=True)
    archive_script_count: Mapped[int | None] = mapped_column(nullable=True)
    archive_executable_count: Mapped[int | None] = mapped_column(nullable=True)
    archive_duplicate_ratio: Mapped[float | None] = mapped_column(nullable=True)
    archive_internal_structure_score: Mapped[float | None] = mapped_column(nullable=True)
    archive_educational_score: Mapped[float | None] = mapped_column(nullable=True)
    archive_strategy_score: Mapped[float | None] = mapped_column(nullable=True)
    archive_processing_recommendation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archive_similarity_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duplicate_cluster_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duplicate_confidence: Mapped[float | None] = mapped_column(nullable=True)
    archive_group_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archive_part_number: Mapped[int | None] = mapped_column(nullable=True)
    archive_total_parts_estimated: Mapped[int | None] = mapped_column(nullable=True)
    multipart_group_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archive_last_ranked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    channel = relationship("Channel", back_populates="files")
    message = relationship("TelegramMessage", back_populates="files")
    document = relationship("Document", back_populates="file", uselist=False)
    video_asset = relationship("VideoAsset", back_populates="file", uselist=False)
    audio_asset = relationship("AudioAsset", back_populates="file", uselist=False)
    transcript = relationship("Transcript", back_populates="source_file", uselist=False)
