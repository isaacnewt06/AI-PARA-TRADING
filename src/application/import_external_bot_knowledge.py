"""Import key information from external trading/signal bot projects."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.core.paths import sanitize_filesystem_name
from src.db.models.knowledge import ChunkEmbedding, ContentChunk, ExtractedRule
from src.db.models.telegram_message import TelegramMessage
from src.db.repositories.channels import ChannelRepository
from src.db.repositories.messages import MessageRepository
from src.processing.classifier import HeuristicContentClassifier
from src.processing.text_cleaner import TextCleaner

logger = get_logger(__name__)


class ExternalBotKnowledgeImportService:
    """Extract non-secret operational knowledge from external bot projects."""

    CONFIG_KEY_ALIASES = {
        "api_id": "TELEGRAM_API_ID",
        "api_hash": "TELEGRAM_API_HASH",
        "session_name": "SESSION_NAME",
        "api_id_telegram": "TELEGRAM_API_ID",
        "api_hash_telegram": "TELEGRAM_API_HASH",
        "session": "SESSION_NAME",
    }

    KEY_PREFIXES = (
        "TRADING_PAIRS",
        "TIMEFRAME",
        "ANALYSIS_TIMEFRAME",
        "ENTRY_TIMEFRAME",
        "STRATEGY",
        "MIN_SIGNAL_STRENGTH",
        "INITIAL_CAPITAL",
        "RISK_PER_TRADE",
        "MAX_TRADE_NOTIONAL_PCT",
        "TESTNET",
        "ENABLE_FUTURES_LIVE_TRADING",
        "FUTURES_LEVERAGE",
        "FUTURES_MAX_MARGIN_PCT",
        "FUTURES_RISK_PER_TRADE",
        "FUTURES_MIN_SIGNAL_STRENGTH",
        "FUTURES_ATR_SL_MULTIPLIER",
        "FUTURES_RR_RATIO",
        "FUTURES_MARGIN_TYPE",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "MT5_",
        "SYMBOL",
        "LIVE_",
        "MAX_",
        "MIN_",
        "DAILY_",
        "LOT_",
        "STOP_",
        "TAKE_",
        "RR_",
        "EXECUTION_",
        "TELEGRAM_",
        "SESSION_NAME",
    )

    def __init__(self, session: Session, config_path: Path) -> None:
        self.session = session
        self.config_path = config_path
        self.channel_repository = ChannelRepository(session)
        self.message_repository = MessageRepository(session)
        self.classifier = HeuristicContentClassifier()

    def run(self) -> dict[str, int]:
        imported = 0
        chunks_created = 0
        for bot in self._load_sources():
            channel = self._upsert_channel(bot)
            key_info = self._build_key_information(bot)
            message, created = self.message_repository.upsert(
                {
                    "channel_id": channel.id,
                    "telegram_message_id": self._resolve_message_id(channel.id, bot),
                    "reply_to_message_id": None,
                    "posted_at": None,
                    "content_type": "external_bot_profile",
                    "text": key_info,
                    "cleaned_text": TextCleaner.clean(key_info),
                    "language": "es",
                    "classification": self.classifier.classify(key_info).label,
                    "has_media": False,
                    "raw_json": json.dumps({"source": bot["root_path"], "kind": "external_bot_key_information"}, ensure_ascii=False),
                }
            )
            if created:
                imported += 1
            chunks_created += self._upsert_chunk(channel.id, message.id, bot, key_info)
            self._cleanup_duplicate_profiles(channel.id, message.id, bot)
        self.session.flush()
        return {"external_bots_imported": imported, "chunks_created": chunks_created}

    def _upsert_channel(self, bot: dict[str, Any]):
        channel = self.channel_repository.create_or_update(
            input_reference=bot["input_reference"],
            title=bot["title"],
            normalized_name=sanitize_filesystem_name(bot["name"], fallback="external_bot"),
            telegram_channel_id=None,
        )
        channel.is_active = True
        return channel

    def _build_key_information(self, bot: dict[str, Any]) -> str:
        root = Path(bot["root_path"])
        secret_keys = set(bot.get("secret_keys", []))
        env_values = self._read_key_value_file(root / bot.get("env_file", ".env"), secret_keys)
        for file_name in bot.get("config_files", []):
            env_values.update(self._read_key_value_file(root / file_name, secret_keys))
        code_summary = self._extract_code_summary(root, bot.get("include_files", []), secret_keys)
        lines = [
            f"# External Trading Bot: {bot['title']}",
            f"source_path: {root}",
            "",
            "## Operational configuration",
        ]
        for key, value in env_values.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Code knowledge summary", code_summary])
        return "\n".join(lines)

    def _read_key_value_file(self, env_path: Path, secret_keys: set[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        if not env_path.exists():
            return values
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*(?:#.*)?$", line)
            if not match:
                continue
            raw_key, raw_value = match.groups()
            key = self._canonical_config_key(raw_key)
            if not self._is_simple_config_literal(raw_value):
                continue
            value = self._strip_literal(raw_value)
            if self._is_secret_key(raw_key, key, secret_keys):
                values[key] = self._mask_secret(value)
            elif key.startswith(self.KEY_PREFIXES):
                values[key] = value
        return values

    @classmethod
    def _extract_code_summary(cls, root: Path, include_files: list[str], secret_keys: set[str]) -> str:
        snippets: list[str] = []
        patterns = (
            "class ",
            "def ",
            "STRATEGY",
            "SIGNAL",
            "RISK",
            "FUTURES",
            "TIMEFRAME",
            "LEVERAGE",
            "OPENAI",
            "MT5",
            "SYMBOL",
            "EXECUTION",
            "BACKTEST",
            "PROMPT",
            "MODEL",
            "TARGET",
            "SPREAD",
            "SESSION",
            "LIQUIDITY",
            "FVG",
            "BOS",
            "CHOCH",
            "ORDER BLOCK",
        )
        for file_name in include_files:
            path = root / file_name
            if not path.exists() or path.stat().st_size > 2_000_000:
                continue
            selected = []
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if any(pattern.lower() in stripped.lower() for pattern in patterns):
                    selected.append(cls._sanitize_summary_line(stripped, secret_keys)[:220])
                if len(selected) >= 25:
                    break
            if selected:
                snippets.append(f"### {file_name}\n" + "\n".join(f"- {item}" for item in selected))
        return "\n\n".join(snippets) if snippets else "No code summary extracted."

    def _upsert_chunk(self, channel_id: int, message_id: int, bot: dict[str, Any], text: str) -> int:
        existing = (
            self.session.query(ContentChunk)
            .filter(ContentChunk.source_type == "external_bot", ContentChunk.source_id == message_id)
            .first()
        )
        metadata = {
            "channel_name": bot["title"],
            "source_reference": bot["input_reference"],
            "external_path": bot["root_path"],
            "authors": [bot["name"]],
        }
        if existing:
            existing.text = text
            existing.clean_text = TextCleaner.clean(text)
            existing.metadata_json = json.dumps(metadata, ensure_ascii=False)
            self.session.add(existing)
            return 0
        self.session.add(
            ContentChunk(
                source_type="external_bot",
                source_id=message_id,
                channel_id=channel_id,
                message_id=message_id,
                chunk_index=0,
                text=text,
                clean_text=TextCleaner.clean(text),
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )
        )
        return 1

    def _load_sources(self) -> list[dict[str, Any]]:
        if not self.config_path.exists():
            return []
        with self.config_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return list(payload.get("external_bots", []))

    def _resolve_message_id(self, channel_id: int, bot: dict[str, Any]) -> int:
        """Reuse pre-existing synthetic IDs from older importer versions."""

        root_variants = {str(Path(bot["root_path"])), str(bot["root_path"])}
        existing = (
            self.session.query(TelegramMessage)
            .filter(
                TelegramMessage.channel_id == channel_id,
                TelegramMessage.content_type == "external_bot_profile",
            )
            .order_by(TelegramMessage.id.asc())
            .all()
        )
        for candidate in existing:
            raw_json = candidate.raw_json or ""
            if any(root in raw_json for root in root_variants):
                return int(candidate.telegram_message_id)
        return self._stable_message_id(bot["name"])

    def _cleanup_duplicate_profiles(self, channel_id: int, canonical_message_id: int, bot: dict[str, Any]) -> None:
        """Remove unreferenced duplicate external-bot profiles created by older imports."""

        root_variants = {str(Path(bot["root_path"])), str(bot["root_path"])}
        candidates = (
            self.session.query(TelegramMessage)
            .filter(
                TelegramMessage.channel_id == channel_id,
                TelegramMessage.content_type == "external_bot_profile",
                TelegramMessage.id != canonical_message_id,
            )
            .all()
        )
        duplicates = [
            candidate
            for candidate in candidates
            if any(root in (candidate.raw_json or "") for root in root_variants)
        ]
        for duplicate in duplicates:
            chunks = (
                self.session.query(ContentChunk)
                .filter(ContentChunk.source_type == "external_bot", ContentChunk.source_id == duplicate.id)
                .all()
            )
            protected = False
            for chunk in chunks:
                has_rules = (
                    self.session.query(ExtractedRule)
                    .filter(ExtractedRule.source_chunk_id == chunk.id)
                    .first()
                    is not None
                )
                if has_rules:
                    protected = True
                    continue
                self.session.query(ChunkEmbedding).filter(ChunkEmbedding.chunk_id == chunk.id).delete(
                    synchronize_session=False
                )
                self.session.delete(chunk)
            if not protected:
                self.session.delete(duplicate)

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        return value[:4] + "***" + value[-3:] if len(value) > 8 else "***"

    @classmethod
    def _canonical_config_key(cls, key: str) -> str:
        return cls.CONFIG_KEY_ALIASES.get(key.strip().lower(), key.strip().upper())

    @staticmethod
    def _strip_literal(value: str) -> str:
        stripped = value.strip().rstrip(",")
        if (stripped.startswith("'") and stripped.endswith("'")) or (
            stripped.startswith('"') and stripped.endswith('"')
        ):
            return stripped[1:-1]
        return stripped

    @staticmethod
    def _is_simple_config_literal(value: str) -> bool:
        stripped = value.strip().rstrip(",")
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", stripped):
            return True
        if stripped.lower() in {"true", "false", "none", "null"}:
            return True
        if (stripped.startswith("'") and stripped.endswith("'")) or (
            stripped.startswith('"') and stripped.endswith('"')
        ):
            return True
        if stripped.startswith("[") and stripped.endswith("]") and "{" not in stripped and "(" not in stripped:
            return True
        return False

    @staticmethod
    def _is_secret_key(raw_key: str, canonical_key: str, secret_keys: set[str]) -> bool:
        secret_keys_lower = {key.lower() for key in secret_keys}
        return raw_key.lower() in secret_keys_lower or canonical_key.lower() in secret_keys_lower

    @classmethod
    def _sanitize_summary_line(cls, line: str, secret_keys: set[str]) -> str:
        safe = re.sub(r"sk-[A-Za-z0-9_\-]+", "sk-***", line)
        for key in secret_keys:
            safe = re.sub(
                rf"({re.escape(key)}\s*[=:]\s*)([^\s,`'\"]+)",
                lambda match: match.group(1) + cls._mask_secret(match.group(2)),
                safe,
                flags=re.IGNORECASE,
            )
        return safe

    @staticmethod
    def _stable_message_id(value: str) -> int:
        digest = hashlib.sha1(f"external_bot:{value}".encode("utf-8")).hexdigest()
        return int(digest[:10], 16) % 2_000_000_000
