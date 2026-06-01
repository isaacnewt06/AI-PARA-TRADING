from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.processing.audio_processor import (
    MockTranscriptionClient,
    OpenAITranscriptionClient,
    TranscriptionResult,
    build_default_transcription_client,
)


def test_build_default_transcription_client_uses_mock_without_api_key() -> None:
    settings = SimpleNamespace(
        openai_api_key=None,
        openai_transcription_model="gpt-4o-mini-transcribe",
    )

    client = build_default_transcription_client(settings)

    assert isinstance(client, MockTranscriptionClient)


def test_openai_transcription_client_combines_chunked_transcripts(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake-audio")
    chunk_a = tmp_path / "chunk_a.mp3"
    chunk_b = tmp_path / "chunk_b.mp3"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    client = OpenAITranscriptionClient.__new__(OpenAITranscriptionClient)
    client.models = ["gpt-4o-transcribe"]
    client.ffmpeg_path = "ffmpeg"

    class _Cleanup:
        def __init__(self) -> None:
            self.cleaned = False

        def cleanup(self) -> None:
            self.cleaned = True

    cleanup = _Cleanup()

    monkeypatch.setattr(
        client,
        "_prepare_chunks",
        lambda path: ([chunk_a, chunk_b], cleanup),
    )

    def fake_transcribe_single(path: Path) -> TranscriptionResult:
        if path == chunk_a:
            return TranscriptionResult(status="completed", language="es", text="uno")
        return TranscriptionResult(status="completed", language="es", text="dos")

    monkeypatch.setattr(client, "_transcribe_single", fake_transcribe_single)

    result = client.transcribe(audio_path)

    assert result.status == "completed"
    assert result.language == "es"
    assert result.text == "uno\n\ndos"
    assert cleanup.cleaned is True
