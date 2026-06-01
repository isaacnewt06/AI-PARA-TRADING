"""Pattern libraries for rule extraction and concept detection."""

from __future__ import annotations

import re

CONCEPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "market_structure": re.compile(r"\bmarket structure\b", re.IGNORECASE),
    "liquidity_sweep": re.compile(r"\bliquidity sweep\b|\bsweep\b", re.IGNORECASE),
    "order_block": re.compile(r"\border block\b|\bob\b", re.IGNORECASE),
    "fair_value_gap": re.compile(r"\bfvg\b|\bfair value gap\b", re.IGNORECASE),
    "bos": re.compile(r"\bbos\b|\bbreak of structure\b", re.IGNORECASE),
    "choch": re.compile(r"\bchoch\b|\bchange of character\b", re.IGNORECASE),
    "breakout": re.compile(r"\bbreakout\b", re.IGNORECASE),
    "pullback": re.compile(r"\bpullback\b|\bretest\b", re.IGNORECASE),
    "risk_management": re.compile(r"\brisk\b|\briesgo\b|\bcapital\b|\bdrawdown\b", re.IGNORECASE),
}

ENTRY_PATTERNS = [
    re.compile(r"\bentry[:\s-]*(.+)", re.IGNORECASE),
    re.compile(r"\benter(?:\s+\w+)?\s+(?:when|if)\s+(.+)", re.IGNORECASE),
    re.compile(r"\b(?:buy|sell)\s+(?:if|when)\s+(.+)", re.IGNORECASE),
]
CONFIRMATION_PATTERNS = [
    re.compile(r"\bconfirm(?:ation)?[:\s-]*(.+)", re.IGNORECASE),
    re.compile(r"\bwait for\s+(.+)", re.IGNORECASE),
    re.compile(r"\bclose (?:above|below)\s+(.+)", re.IGNORECASE),
]
STOP_PATTERNS = [
    re.compile(r"\b(?:sl|stop loss)[:\s-]*(.+)", re.IGNORECASE),
]
TAKE_PROFIT_PATTERNS = [
    re.compile(r"\b(?:tp\d*|take profit\d*)[:\s-]*(.+)", re.IGNORECASE),
]
RISK_PATTERNS = [
    re.compile(r"\b(?:risk|riesgo|lot size|capital|drawdown)[^.\n]*", re.IGNORECASE),
]
SESSION_PATTERNS = [
    re.compile(r"\b(?:london|new york|ny|asian|tokyo|session|killzone)[^.\n]*", re.IGNORECASE),
]
CONTEXT_PATTERNS = [
    re.compile(r"\b(?:context|bias|scenario|setup|idea)[^.\n]*", re.IGNORECASE),
]
