"""Channel repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.channel import Channel


class ChannelRepository:
    """Persistence helpers for channels."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active(self) -> list[Channel]:
        stmt = select(Channel).where(Channel.is_active.is_(True)).order_by(Channel.title.asc())
        return list(self.session.scalars(stmt))

    def get_by_reference(self, reference: str) -> Channel | None:
        stmt = select(Channel).where(Channel.input_reference == reference)
        return self.session.scalar(stmt)

    def get_by_name(self, normalized_name: str) -> Channel | None:
        stmt = select(Channel).where(Channel.normalized_name == normalized_name)
        return self.session.scalar(stmt)

    def create_or_update(
        self,
        *,
        input_reference: str,
        title: str,
        normalized_name: str,
        telegram_channel_id: int | None,
    ) -> Channel:
        channel = self.get_by_reference(input_reference)
        unique_name = self._ensure_unique_name(normalized_name, telegram_channel_id, input_reference, existing=channel)
        if channel is None:
            channel = Channel(
                input_reference=input_reference,
                title=title,
                normalized_name=unique_name,
                telegram_channel_id=telegram_channel_id,
            )
            self.session.add(channel)
        else:
            channel.title = title
            channel.normalized_name = unique_name
            channel.telegram_channel_id = telegram_channel_id
        self.session.flush()
        return channel

    def _ensure_unique_name(
        self,
        normalized_name: str,
        telegram_channel_id: int | None,
        input_reference: str,
        *,
        existing: Channel | None,
    ) -> str:
        candidate = normalized_name or "channel"
        collision = self.get_by_name(candidate)
        if collision is None or (existing and collision.id == existing.id):
            return candidate

        suffix = str(telegram_channel_id or abs(hash(input_reference)) % 10_000_000)
        candidate = f"{candidate}_{suffix}"
        collision = self.get_by_name(candidate)
        if collision is None or (existing and collision.id == existing.id):
            return candidate
        return f"{candidate}_{len(input_reference)}"
