"""Channel model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class Channel(TimestampMixin, Base):
    """Tracked Telegram channel."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_channel_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    input_reference: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages = relationship("TelegramMessage", back_populates="channel")
    files = relationship("FileAsset", back_populates="channel")
    ingestion_runs = relationship("IngestionRun", back_populates="channel")
