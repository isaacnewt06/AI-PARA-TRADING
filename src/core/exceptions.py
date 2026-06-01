"""Custom exception hierarchy for the platform."""


class TradingBrainError(Exception):
    """Base application exception."""


class ConfigurationError(TradingBrainError):
    """Raised when the application configuration is invalid."""


class TelegramSyncError(TradingBrainError):
    """Raised when a Telegram synchronization operation fails."""


class ProcessingError(TradingBrainError):
    """Raised when an asset processing step fails."""
