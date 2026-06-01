"""Local embedding providers for semantic retrieval."""

from __future__ import annotations

import hashlib
import math
import re

from src.ai.interfaces import EmbeddingClient

TOKEN_RE = re.compile(r"[a-zA-Z0-9_@#.%/-]+")
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "have",
    "your",
    "about",
    "para",
    "con",
    "los",
    "las",
    "una",
    "que",
    "por",
    "del",
    "are",
    "you",
}


def normalize_tokens(text: str) -> list[str]:
    """Tokenize and normalize trading content."""
    lowered = text.lower()
    tokens = [token for token in TOKEN_RE.findall(lowered) if len(token) > 1 and token not in STOPWORDS]
    return tokens


class LocalHashEmbeddingClient(EmbeddingClient):
    """Deterministic local embedding client using the hashing trick."""

    provider_name = "local-hash-v1"

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        counts: dict[str, int] = {}
        for token in normalize_tokens(text):
            counts[token] = counts.get(token, 0) + 1
        if not counts:
            return vector

        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + math.log(count)
            vector[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [round(value / norm, 8) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Compute cosine similarity for normalized vectors."""
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))
