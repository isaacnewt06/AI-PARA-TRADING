"""Message repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.telegram_message import TelegramMessage


class MessageRepository:
    """Persistence helpers for telegram messages."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_telegram_id(self, channel_id: int, telegram_message_id: int) -> TelegramMessage | None:
        stmt = select(TelegramMessage).where(
            TelegramMessage.channel_id == channel_id,
            TelegramMessage.telegram_message_id == telegram_message_id,
        )
        return self.session.scalar(stmt)

    def upsert(self, payload: dict) -> tuple[TelegramMessage, bool]:
        entity = self.get_by_telegram_id(payload["channel_id"], payload["telegram_message_id"])
        created = entity is None
        if entity is None:
            entity = TelegramMessage(**payload)
            self.session.add(entity)
        else:
            for key, value in payload.items():
                setattr(entity, key, value)
        self.session.flush()
        return entity, created

    def list_unprocessed_texts(self) -> list[TelegramMessage]:
        stmt = select(TelegramMessage).where(
            (TelegramMessage.cleaned_text.is_(None))
            | (TelegramMessage.classification.is_(None))
            | (TelegramMessage.language.is_(None))
        ).order_by(TelegramMessage.id.asc())
        return list(self.session.scalars(stmt))
