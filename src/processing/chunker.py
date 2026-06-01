"""Configurable chunking for long-form content."""

from __future__ import annotations

from dataclasses import dataclass

from src.processing.text_cleaner import TextCleaner


@dataclass(slots=True)
class Chunk:
    """Chunk payload used before persistence."""

    chunk_index: int
    text: str
    clean_text: str


class TextChunker:
    """Split long text into overlapping chunks."""

    def __init__(self, chunk_size: int = 1200, overlap: int = 150) -> None:
        if overlap >= chunk_size:
            raise ValueError("chunk overlap must be smaller than chunk size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, text: str | None) -> list[Chunk]:
        cleaned = TextCleaner.clean(text)
        if not cleaned:
            return []
        if len(cleaned) <= self.chunk_size:
            return [Chunk(chunk_index=0, text=cleaned, clean_text=cleaned)]

        chunks: list[Chunk] = []
        start = 0
        index = 0
        while start < len(cleaned):
            end = start + self.chunk_size
            segment = cleaned[start:end]
            chunks.append(Chunk(chunk_index=index, text=segment, clean_text=segment))
            if end >= len(cleaned):
                break
            start = end - self.overlap
            index += 1
        return chunks
