"""Regex-based extraction of trading entities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class ExtractedEntities:
    """Normalized entities from a message."""

    asset: str | None = None
    timeframe: str | None = None
    direction: str | None = None
    entry: str | None = None
    stop_loss: str | None = None
    take_profits: list[str] = field(default_factory=list)
    risk_percent: str | None = None
    authors: list[str] = field(default_factory=list)


class TradingEntityExtractor:
    """Low-cost extractor for the first production-ready phase."""

    asset_pattern = re.compile(
        r"\b("
        r"XAUUSDm?|XAGUSDm?|BTCUSDm?|ETHUSDm?|NAS100|US30|SPX500|GER40|"
        r"[A-Z]{3}(?:USD|JPY|GBP|EUR|CAD|CHF|AUD|NZD)m?|"
        r"[A-Z]{2,5}USDT"
        r")\b",
        re.IGNORECASE,
    )
    timeframe_pattern = re.compile(r"\b(M1|M5|M15|M30|H1|H4|D1|W1)\b", re.IGNORECASE)
    direction_pattern = re.compile(r"\b(buy|sell|long|short)\b", re.IGNORECASE)
    entry_pattern = re.compile(r"\bentry[:\s]*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
    stop_pattern = re.compile(r"\b(?:sl|stop loss)[:\s]*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
    tp_pattern = re.compile(r"\b(?:tp\d*|take profit\d*)[:\s]*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
    risk_pattern = re.compile(r"\b([0-9]+(?:\.[0-9]+)?%)\s*(?:risk|riesgo)?\b", re.IGNORECASE)
    author_pattern = re.compile(r"@([A-Za-z0-9_]{3,})")

    def extract(self, text: str | None) -> ExtractedEntities:
        normalized = text or ""
        return ExtractedEntities(
            asset=self._first_group(self.asset_pattern.search(normalized)),
            timeframe=self._first_group(self.timeframe_pattern.search(normalized)),
            direction=self._first_group(self.direction_pattern.search(normalized)),
            entry=self._first_group(self.entry_pattern.search(normalized)),
            stop_loss=self._first_group(self.stop_pattern.search(normalized)),
            take_profits=self.tp_pattern.findall(normalized),
            risk_percent=self._first_group(self.risk_pattern.search(normalized)),
            authors=self.author_pattern.findall(normalized),
        )

    @staticmethod
    def _first_group(match: re.Match[str] | None) -> str | None:
        return match.group(1) if match else None
