"""Telegram message model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class TelegramMessage(TimestampMixin, Base):
    """Telegram message persisted from the source channel."""

    __tablename__ = "telegram_messages"
    __table_args__ = (Index("ix_message_channel_msg_id", "channel_id", "telegram_message_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_type: Mapped[str] = mapped_column(String(50), default="text", nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    has_media: Mapped[bool] = mapped_column(default=False, nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), default="discovered", nullable=False)
    external_links_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    channel = relationship("Channel", back_populates="messages")
    files = relationship("FileAsset", back_populates="message")
