"""Import configured Telegram channels without requiring a live Telegram session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from src.core.paths import sanitize_filesystem_name
from src.db.repositories.channels import ChannelRepository


class ConfiguredChannelImportService:
    """Load target channels from a YAML config file and persist them."""

    def __init__(self, session: Session, config_path: Path) -> None:
        self.session = session
        self.config_path = config_path
        self.channel_repository = ChannelRepository(session)

    def run(self) -> dict[str, int]:
        payload = self._load_payload()
        imported = 0
        for channel in payload.get("channels", []):
            reference = str(channel["input_reference"]).strip()
            title = str(channel.get("title") or reference).strip()
            normalized_name = str(
                channel.get("normalized_name") or sanitize_filesystem_name(title.lower(), fallback="channel")
            )
            telegram_channel_id = channel.get("telegram_channel_id")
            entity = self.channel_repository.create_or_update(
                input_reference=reference,
                title=title,
                normalized_name=normalized_name,
                telegram_channel_id=int(telegram_channel_id) if telegram_channel_id is not None else None,
            )
            entity.is_active = bool(channel.get("is_active", True))
            imported += 1
        self.session.flush()
        return {"channels_imported": imported}

    def _load_payload(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"channels": []}
        with self.config_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        if not isinstance(payload, dict):
            return {"channels": []}
        return payload
