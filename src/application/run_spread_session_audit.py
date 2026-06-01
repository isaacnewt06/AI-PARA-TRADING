"""Application service for spread/session execution audit."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.spread_session_audit import SpreadSessionAudit


class SpreadSessionAuditApplicationService:
    """Run environment-only spread/session measurements."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(
        self,
        *,
        symbol: str,
        duration_minutes: float,
        poll_seconds: float,
        max_samples: int | None,
        run_label: str,
    ) -> dict:
        return SpreadSessionAudit(self.settings).run(
            symbol=symbol,
            duration_minutes=duration_minutes,
            poll_seconds=poll_seconds,
            max_samples=max_samples,
            run_label=run_label,
        )
