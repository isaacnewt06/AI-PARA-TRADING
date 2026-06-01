"""Audio and video asset models."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class VideoAsset(TimestampMixin, Base):
    """Video processing metadata."""

    __tablename__ = "video_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), unique=True, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    audio_extract_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)

    file = relationship("FileAsset", back_populates="video_asset")


class AudioAsset(TimestampMixin, Base):
    """Audio processing metadata."""

    __tablename__ = "audio_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), unique=True, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)

    file = relationship("FileAsset", back_populates="audio_asset")
