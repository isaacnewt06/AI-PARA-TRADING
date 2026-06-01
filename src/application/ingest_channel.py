"""Application service for Telegram ingestion."""

from __future__ import annotations

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.repositories.channels import ChannelRepository
from src.db.repositories.files import FileRepository
from src.db.repositories.messages import MessageRepository
from src.db.repositories.runs import RunRepository
from src.telegram.client import TelegramClientManager
from src.telegram.extractor import TelegramChannelRegistry, TelegramMessageExtractor
from src.telegram.sync_service import TelegramSyncOptions, TelegramSyncService

logger = get_logger(__name__)


class IngestionApplicationService:
    """Facade used by the CLI for auth, channel registration and synchronization."""

    def __init__(
        self,
        *,
        client_manager: TelegramClientManager,
        channel_repository: ChannelRepository,
        message_repository: MessageRepository,
        file_repository: FileRepository,
        run_repository: RunRepository,
        settings: Settings,
    ) -> None:
        self.client_manager = client_manager
        self.channel_repository = channel_repository
        self.message_repository = message_repository
        self.file_repository = file_repository
        self.run_repository = run_repository
        self.settings = settings

    async def authenticate(self) -> None:
        client = await self.client_manager.authenticate()
        await client.disconnect()
        logger.info("Telegram authentication completed successfully")

    async def add_channel(self, reference: str):
        client = await self.client_manager.authenticate()
        try:
            registry = TelegramChannelRegistry(self.channel_repository)
            return await registry.register(client, reference)
        finally:
            await client.disconnect()

    async def sync(
        self,
        *,
        channel_reference: str | None = None,
        mode: str = "incremental",
        options: TelegramSyncOptions | None = None,
    ) -> dict[str, dict]:
        client = await self.client_manager.authenticate()
        try:
            extractor = TelegramMessageExtractor(client)
            sync_service = TelegramSyncService(
                settings=self.settings,
                message_repository=self.message_repository,
                file_repository=self.file_repository,
                run_repository=self.run_repository,
            )
            channels = []
            if channel_reference:
                channel = self.channel_repository.get_by_reference(channel_reference)
                if channel is None:
                    channel = await TelegramChannelRegistry(self.channel_repository).register(client, channel_reference)
                channels.append(channel)
            else:
                channels = self.channel_repository.list_active()
                if not channels:
                    logger.warning("No active channels registered for sync")
                    return {}

            results: dict[str, dict] = {}
            for channel in channels:
                results[channel.title] = await sync_service.sync_channel(
                    extractor,
                    channel,
                    mode=mode,
                    options=options,
                )
            return results
        finally:
            await client.disconnect()
