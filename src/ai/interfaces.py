"""Provider-agnostic AI interfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class LLMClient(Protocol):
    """Abstract contract for summary and reasoning providers."""

    def summarize(self, prompt: str, text: str) -> str:
        """Return a concise summary."""


class EmbeddingClient(Protocol):
    """Abstract contract for vector embedding providers."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for the provided texts."""


class TranscriptionClient(Protocol):
    """Abstract contract for audio transcription providers."""

    def transcribe(self, audio_path: Path):
        """Return a transcription result object."""
