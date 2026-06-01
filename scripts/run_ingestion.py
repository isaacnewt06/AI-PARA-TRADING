"""Run Telegram sync from a plain script."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.ingest_channel import IngestionApplicationService
from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.repositories.channels import ChannelRepository
from src.db.repositories.files import FileRepository
from src.db.repositories.messages import MessageRepository
from src.db.repositories.runs import RunRepository
from src.db.session import init_db, session_scope
from src.telegram.client import TelegramClientManager


async def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    init_db()
    channel = sys.argv[1] if len(sys.argv) > 1 else None
    mode = sys.argv[2] if len(sys.argv) > 2 else "incremental"
    with session_scope() as session:
        service = IngestionApplicationService(
            client_manager=TelegramClientManager(settings),
            channel_repository=ChannelRepository(session),
            message_repository=MessageRepository(session),
            file_repository=FileRepository(session),
            run_repository=RunRepository(session),
            settings=settings,
        )
        results = await service.sync(channel_reference=channel, mode=mode)
        print(results)


if __name__ == "__main__":
    asyncio.run(main())
