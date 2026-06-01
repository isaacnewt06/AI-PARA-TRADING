from src.processing.chunker import TextChunker


def test_chunker_creates_multiple_chunks() -> None:
    text = "A" * 3000
    chunks = TextChunker(chunk_size=1000, overlap=100).split(text)
    assert len(chunks) >= 3
    assert chunks[0].chunk_index == 0
