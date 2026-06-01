"""Text normalization utilities."""

from __future__ import annotations

import re


class TextCleaner:
    """Normalize text content before classification and chunking."""

    whitespace_re = re.compile(r"\s+")

    @classmethod
    def clean(cls, text: str | None) -> str:
        if not text:
            return ""
        text = text.replace("\u200b", " ").replace("\ufeff", " ")
        text = cls.whitespace_re.sub(" ", text)
        return text.strip()
