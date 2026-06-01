"""Application service for the broker-side trading service execution agent."""

from __future__ import annotations

from src.core.config import Settings
from src.trading.trading_service_execution_agent import TradingServiceExecutionAgentRuntime


class TradingServiceExecutionAgentApplicationService:
    """Run one execution-agent cycle against the central trading service API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(
        self,
        *,
        api_base_url: str,
        account_id: int,
        agent_key: str,
        canonical_symbol: str = "XAUUSD",
        heartbeat_status: str = "online",
        dry_run: bool = True,
        confirm_demo: bool = False,
        volume_lots: float = 0.01,
        deviation_points: int = 50,
    ) -> dict:
        return TradingServiceExecutionAgentRuntime(
            self.settings,
            api_base_url=api_base_url,
            account_id=account_id,
            agent_key=agent_key,
        ).run_cycle(
            canonical_symbol=canonical_symbol,
            heartbeat_status=heartbeat_status,
            dry_run=dry_run,
            confirm_demo=confirm_demo,
            volume_lots=volume_lots,
            deviation_points=deviation_points,
        )
