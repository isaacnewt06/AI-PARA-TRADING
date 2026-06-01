"""Inventory rows for compressed archives inspected without extraction."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class ArchiveContent(TimestampMixin, Base):
    """Single internal entry discovered inside ZIP/RAR/7z archives."""

    __tablename__ = "archive_contents"
    __table_args__ = (
        UniqueConstraint("file_id", "internal_path", name="uq_archive_contents_file_path"),
        Index("ix_archive_contents_file_kind", "file_id", "content_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), nullable=False)
    internal_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_kind: Mapped[str] = mapped_column(String(64), default="other", nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    compressed_size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    is_directory: Mapped[bool] = mapped_column(default=False, nullable=False)
    duplicate_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    file = relationship("FileAsset")
