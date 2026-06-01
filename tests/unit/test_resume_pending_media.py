from __future__ import annotations

from types import SimpleNamespace

from src.application.resume_pending_media import PendingMediaResumeApplicationService


def test_resume_pending_media_size_limit_check() -> None:
    asset = SimpleNamespace(size_bytes=90 * 1024 * 1024)

    assert PendingMediaResumeApplicationService._exceeds_size_limit(asset, 80) is True
    assert PendingMediaResumeApplicationService._exceeds_size_limit(asset, 100) is False
    assert PendingMediaResumeApplicationService._exceeds_size_limit(asset, None) is False


def test_resume_pending_media_append_note() -> None:
    assert PendingMediaResumeApplicationService._append_note("", "hello") == "hello"
    assert (
        PendingMediaResumeApplicationService._append_note("first", "second")
        == "first\nsecond"
    )
