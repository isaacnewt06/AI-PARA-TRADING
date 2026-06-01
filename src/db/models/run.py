"""Run tracking models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class IngestionRun(TimestampMixin, Base):
    """Track each Telegram sync execution."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    messages_scanned: Mapped[int] = mapped_column(default=0, nullable=False)
    messages_saved: Mapped[int] = mapped_column(default=0, nullable=False)
    files_downloaded: Mapped[int] = mapped_column(default=0, nullable=False)
    duplicates_skipped: Mapped[int] = mapped_column(default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    channel = relationship("Channel", back_populates="ingestion_runs")


class ProcessingRun(TimestampMixin, Base):
    """Track content processing executions."""

    __tablename__ = "processing_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    documents_processed: Mapped[int] = mapped_column(default=0, nullable=False)
    messages_processed: Mapped[int] = mapped_column(default=0, nullable=False)
    media_processed: Mapped[int] = mapped_column(default=0, nullable=False)
    chunks_created: Mapped[int] = mapped_column(default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
