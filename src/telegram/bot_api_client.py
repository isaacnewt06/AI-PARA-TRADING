"""Telegram Bot API client for signal bot ingestion."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class TelegramBotApiError(RuntimeError):
    """Raised when Telegram Bot API returns an error."""


class TelegramBotApiClient:
    """Small dependency-free Telegram Bot API client."""

    def __init__(self, token: str, timeout_seconds: int = 60) -> None:
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{token}"

    def get_me(self) -> dict[str, Any]:
        return self._request_json("getMe")

    def get_updates(self, *, offset: int | None = None, limit: int = 100, timeout: int = 0) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        payload = self._request_json("getUpdates", params=params)
        return list(payload.get("result", []))

    def get_file(self, file_id: str) -> dict[str, Any]:
        payload = self._request_json("getFile", params={"file_id": file_id})
        return dict(payload.get("result", {}))

    def download_file(self, file_path: str, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.file_base_url}/{file_path}"
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
            target_path.write_bytes(response.read())
        return target_path

    def _request_json(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{method}"
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise TelegramBotApiError(str(payload))
        return payload
