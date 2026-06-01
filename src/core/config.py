"""Application configuration management."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

from src.core.exceptions import ConfigurationError
from src.core.paths import ProjectPaths, build_project_paths

_SETTINGS_OVERRIDE: Settings | None = None


class AppTuning(BaseSettings):
    """Runtime tuning loaded from YAML."""

    chunk_size: int = 1200
    chunk_overlap: int = 150
    max_sync_retries: int = 3
    retry_backoff_seconds: int = 2
    rate_limit_sleep_seconds: float = 1.0
    default_language: str = "unknown"
    transcript_provider: str = "mock"
    summary_provider: str = "local-placeholder"
    ocr_enabled: bool = False
    sync_checkpoint_interval: int = 25
    sqlite_busy_timeout_seconds: int = 30
    embedding_dimension: int = 256
    semantic_candidate_limit: int = 300
    archive_inspection_enabled: bool = True


class Settings(BaseSettings):
    """Primary environment-based settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_api_id: int | None = Field(default=None, alias="TELEGRAM_API_ID")
    telegram_api_hash: str | None = Field(default=None, alias="TELEGRAM_API_HASH")
    telegram_phone: str | None = Field(default=None, alias="TELEGRAM_PHONE")
    session_name: str = Field(default="telegram_trading_brain", alias="SESSION_NAME")
    data_dir: str = Field(default="./data", alias="DATA_DIR")
    db_url: str = Field(default="sqlite:///./data/telegram_trading_brain.db", alias="DB_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    ffmpeg_path: str = Field(default="ffmpeg", alias="FFMPEG_PATH")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_transcription_model: str = Field(
        default="gpt-4o-transcribe",
        alias="OPENAI_TRANSCRIPTION_MODEL",
    )
    economic_calendar_auto_sync: bool = Field(default=True, alias="ECONOMIC_CALENDAR_AUTO_SYNC")
    economic_calendar_url: str = Field(
        default="https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        alias="ECONOMIC_CALENDAR_URL",
    )
    economic_calendar_timeout_seconds: int = Field(default=20, alias="ECONOMIC_CALENDAR_TIMEOUT_SECONDS")
    economic_calendar_pre_event_block_minutes: int = Field(default=5, alias="ECONOMIC_CALENDAR_PRE_EVENT_BLOCK_MINUTES")
    economic_calendar_post_event_block_minutes: int = Field(default=5, alias="ECONOMIC_CALENDAR_POST_EVENT_BLOCK_MINUTES")
    economic_calendar_upcoming_watch_minutes: int = Field(default=60, alias="ECONOMIC_CALENDAR_UPCOMING_WATCH_MINUTES")
    market_reference_timezone: str = Field(default="America/Santo_Domingo", alias="MARKET_REFERENCE_TIMEZONE")
    mt5_terminal_path: str | None = Field(default=None, alias="MT5_TERMINAL_PATH")
    rar_backend_path: str | None = Field(default=None, alias="RAR_BACKEND_PATH")
    rar_backend_type: str | None = Field(default=None, alias="RAR_BACKEND_TYPE")
    archive_inspection_enabled: bool = Field(default=True, alias="ARCHIVE_INSPECTION_ENABLED")
    telegram_signal_bot_token: str | None = Field(default=None, alias="TELEGRAM_SIGNAL_BOT_TOKEN")
    telegram_signal_bot_name: str = Field(default="telegram_signal_bot", alias="TELEGRAM_SIGNAL_BOT_NAME")
    exness_referral_url: str = Field(
        default="https://one.exnessonelink.com/a/143x3jrak4",
        alias="EXNESS_REFERRAL_URL",
    )

    yaml_config_path: Path = Path("config/settings.yaml")
    tuning: AppTuning = AppTuning()

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def paths(self) -> ProjectPaths:
        return build_project_paths(self.project_root, self.resolved_data_dir)

    @property
    def session_file(self) -> Path:
        return self.paths.sessions_dir / self.session_name

    @property
    def resolved_data_dir(self) -> Path:
        raw_path = Path(self.data_dir)
        if raw_path.is_absolute():
            return raw_path.resolve()
        return (self.project_root / raw_path).resolve()

    @property
    def resolved_yaml_config_path(self) -> Path:
        raw_path = Path(self.yaml_config_path)
        if raw_path.is_absolute():
            return raw_path.resolve()
        return (self.project_root / raw_path).resolve()

    @property
    def resolved_db_url(self) -> str:
        if not self.db_url.startswith("sqlite"):
            return self.db_url
        prefix = "sqlite:///"
        if self.db_url.startswith("sqlite:///./"):
            relative = self.db_url[len("sqlite:///./") :]
            return prefix + str((self.project_root / relative).resolve()).replace("\\", "/")
        if self.db_url.startswith(prefix):
            raw_path = self.db_url[len(prefix) :]
            if raw_path.startswith("/"):
                return self.db_url
            return prefix + str((self.project_root / raw_path).resolve()).replace("\\", "/")
        return self.db_url

    def require_telegram_credentials(self) -> None:
        if not self.telegram_api_id or not self.telegram_api_hash:
            raise ConfigurationError(
                "Telegram credentials are missing. Define TELEGRAM_API_ID and TELEGRAM_API_HASH in .env."
            )

    def load_yaml_settings(self) -> None:
        yaml_path = self.resolved_yaml_config_path
        if not yaml_path.exists():
            return
        with yaml_path.open("r", encoding="utf-8") as handle:
            content = yaml.safe_load(handle) or {}
        app_section = content.get("app", {})
        self.tuning = AppTuning.model_validate(app_section)
        if "archive_inspection_enabled" not in app_section:
            self.tuning.archive_inspection_enabled = self.archive_inspection_enabled


def _load_project_env() -> None:
    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        return
    fallback_env = project_root.parent / "OPENAI TRADING BOT" / ".env"
    if fallback_env.exists():
        load_dotenv(fallback_env, override=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load, validate and cache the application settings."""
    try:
        if _SETTINGS_OVERRIDE is not None:
            _SETTINGS_OVERRIDE.paths.ensure()
            return _SETTINGS_OVERRIDE
        _load_project_env()
        settings = Settings()
        settings.load_yaml_settings()
        settings.paths.ensure()
        return settings
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc


def reload_settings(overrides: dict[str, Any] | None = None) -> Settings:
    """Reload settings for tests or scripts."""
    global _SETTINGS_OVERRIDE
    get_settings.cache_clear()
    try:
        from src.db.session import get_engine, get_session_factory

        get_engine.cache_clear()
        get_session_factory.cache_clear()
    except Exception:
        pass
    _load_project_env()
    settings = Settings(**(overrides or {}))
    settings.load_yaml_settings()
    settings.paths.ensure()
    _SETTINGS_OVERRIDE = settings
    return settings
