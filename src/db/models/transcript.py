"""Transcript model."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class Transcript(TimestampMixin, Base):
    """Transcribed media content."""

    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="mock", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_file = relationship("FileAsset", back_populates="transcript")
