from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.telegram.downloader import MediaDownloadPlan, TelegramDownloader


class _FakeFileRepository:
    def __init__(self) -> None:
        self.last_status: dict | None = None

    def find_duplicate(self, *, file_hash: str, file_name: str, size_bytes: int):
        return None

    def mark_status(self, file_asset, **kwargs):
        self.last_status = kwargs
        return file_asset


class _FakeClient:
    def __init__(self, chunks, *, fail_once: bool = False) -> None:
        self.chunks = chunks
        self.payload = b"".join(chunks)
        self.fail_once = fail_once
        self.calls: list[int] = []
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    def _iter_download(self, media, *, offset: int = 0, request_size: int = 0, chunk_size: int = 0, file_size: int = 0):
        self.calls.append(offset)

        async def _gen():
            if self.fail_once:
                self.fail_once = False
                self.connected = False
                raise RuntimeError("network cut")
            step = chunk_size or request_size or len(self.payload)
            for index in range(offset, len(self.payload), step):
                yield self.payload[index : index + step]

        return _gen()


def _plan(tmp_path: Path, *, name: str = "bigfile.rar", size: int = 12) -> MediaDownloadPlan:
    target = tmp_path / name
    temp = tmp_path / f"{name}.part"
    return MediaDownloadPlan(
        category="generic",
        file_name=name,
        target_path=target,
        temp_path=temp,
        telegram_file_id="123",
        mime_type="application/vnd.rar",
        expected_size_bytes=size,
    )


@pytest.mark.asyncio
async def test_download_with_resume_retries_and_finalizes(tmp_path: Path) -> None:
    downloader = TelegramDownloader(paths=SimpleNamespace(), file_repository=_FakeFileRepository(), retry_attempts=3)  # type: ignore[arg-type]
    plan = _plan(tmp_path, size=12)
    plan.temp_path.write_bytes(b"abcd")
    client = _FakeClient([b"abcdefgh", b"ijkl"], fail_once=True)
    message = SimpleNamespace(media=object())

    result = await downloader._download_with_resume(client=client, message=message, plan=plan)

    assert result == plan.target_path
    assert plan.target_path.read_bytes() == b"abcdefghijkl"
    assert client.calls[:2] == [4, 4]


@pytest.mark.asyncio
async def test_download_with_resume_returns_none_after_exhausting_retries(tmp_path: Path) -> None:
    downloader = TelegramDownloader(paths=SimpleNamespace(), file_repository=_FakeFileRepository(), retry_attempts=2)  # type: ignore[arg-type]
    plan = _plan(tmp_path, size=8)

    class _AlwaysFailClient(_FakeClient):
        def _iter_download(self, media, *, offset: int = 0, request_size: int = 0, chunk_size: int = 0, file_size: int = 0):
            self.calls.append(offset)

            async def _gen():
                raise RuntimeError("still failing")
                yield b""

            return _gen()

    client = _AlwaysFailClient([b"abcdefgh"])
    message = SimpleNamespace(media=object())

    result = await downloader._download_with_resume(client=client, message=message, plan=plan)

    assert result is None
    assert not plan.target_path.exists()


def test_finalize_download_does_not_re_finalize_completed_target(tmp_path: Path) -> None:
    repository = _FakeFileRepository()
    downloader = TelegramDownloader(paths=SimpleNamespace(), file_repository=repository)  # type: ignore[arg-type]
    plan = _plan(tmp_path, size=12)
    plan.target_path.write_bytes(b"abcdefghijkl")
    file_asset = SimpleNamespace(id=1, stored_path=str(plan.target_path))

    downloader.finalize_download(file_asset=file_asset, downloaded_path=plan.target_path, plan=plan)

    assert plan.target_path.exists()
    assert plan.target_path.read_bytes() == b"abcdefghijkl"
    assert repository.last_status is not None
    assert repository.last_status["status"] == "downloaded"
