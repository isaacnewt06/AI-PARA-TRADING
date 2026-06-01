"""External downloadable resources discovered in Telegram content."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class ExternalResource(TimestampMixin, Base):
    """A link to a resource hosted outside Telegram."""

    __tablename__ = "external_resources"
    __table_args__ = (
        UniqueConstraint("message_id", "url", name="uq_external_resource_message_url"),
        Index("ix_external_resources_provider_status", "provider", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    file_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="external_pending", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    message = relationship("TelegramMessage")
