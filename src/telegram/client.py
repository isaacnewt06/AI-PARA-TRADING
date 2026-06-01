"""Telethon client factory and auth helpers."""

from __future__ import annotations

from telethon import TelegramClient

from src.core.config import Settings


class TelegramClientManager:
    """Create and authenticate a Telethon client."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_client(self) -> TelegramClient:
        self.settings.require_telegram_credentials()
        return TelegramClient(
            str(self.settings.session_file),
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
        )

    async def authenticate(self) -> TelegramClient:
        client = self.build_client()
        await client.connect()
        if not await client.is_user_authorized():
            await client.start(phone=self.settings.telegram_phone)
        return client
