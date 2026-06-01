"""Channel registration and message extraction helpers."""

from __future__ import annotations

from telethon import TelegramClient
from telethon.tl.custom.message import Message

from src.core.logging import get_logger
from src.db.models.channel import Channel
from src.db.repositories.channels import ChannelRepository
from src.telegram.parsers import TelegramMessageParser

logger = get_logger(__name__)


class TelegramChannelRegistry:
    """Resolve channels and persist them locally."""

    def __init__(self, channel_repository: ChannelRepository) -> None:
        self.channel_repository = channel_repository

    async def register(self, client: TelegramClient, reference: str) -> Channel:
        entity = await client.get_entity(reference)
        title = getattr(entity, "title", reference)
        normalized_name = self._normalize_name(title)
        channel_id = getattr(entity, "id", None)
        channel = self.channel_repository.create_or_update(
            input_reference=reference,
            title=title,
            normalized_name=normalized_name,
            telegram_channel_id=channel_id,
        )
        logger.info("Registered channel %s (%s)", title, reference)
        return channel

    @staticmethod
    def _normalize_name(value: str) -> str:
        return "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value.lower()).strip("_")


class TelegramMessageExtractor:
    """Extract messages from Telegram with resumable iteration."""

    def __init__(self, client: TelegramClient) -> None:
        self.client = client

    async def iter_messages(self, channel: Channel, mode: str = "incremental", limit: int | None = None):
        if mode not in {"incremental", "full"}:
            raise ValueError("mode must be 'incremental' or 'full'")
        entity = await self.client.get_entity(channel.input_reference)
        min_id = channel.last_synced_message_id if mode == "incremental" and channel.last_synced_message_id else 0
        count = 0
        async for message in self.client.iter_messages(entity, reverse=True, min_id=min_id):
            if not isinstance(message, Message):
                continue
            yield message, TelegramMessageParser.serialize_message(message)
            count += 1
            if limit is not None and count >= limit:
                break
