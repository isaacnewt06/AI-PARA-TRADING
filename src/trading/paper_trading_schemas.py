"""Schemas for controlled paper trading artifacts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaperSignal(BaseModel):
    """Serializable paper signal generated from a live market snapshot."""

    signal_id: str
    strategy_name: str
    timestamp: str
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit_logic: str
    reason: str
    confidence: float
    entry_timeframe: str
    context_timeframe: str
    session: str | None = None
    hour_utc: int | None = None
    atr_band: str | None = None
    confirmation_band: str | None = None
    rejection_type: str | None = None
    status: str = "generated"


class PaperTradeState(BaseModel):
    """Serializable virtual trade state for paper trading."""

    signal_id: str
    strategy_name: str
    symbol: str
    direction: str
    status: str
    entry_time: str
    setup_time: str
    exit_time: str | None = None
    entry_price: float
    exit_price: float | None = None
    stop_loss: float
    take_profit_price: float
    rr_target: float
    pnl_r: float | None = None
    result: str | None = None
    trailing_logic: str
    session: str | None = None
    hour_utc: int | None = None
    atr_band: str | None = None
    confirmation_band: str | None = None
    rejection_type: str | None = None
    htf_bias: str | None = None
    ob_detected: bool = False
    entry_reason: str | None = None
    exit_reason: str | None = None
    confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)


class PaperTradingSummary(BaseModel):
    """High-level summary returned by the paper trading runner."""

    strategy_name: str
    symbol: str
    dry_run: bool = True
    market_snapshot: dict = Field(default_factory=dict)
    signals_generated: int = 0
    open_trades: int = 0
    closed_trades: int = 0
    latest_signal: dict | None = None
    paths: dict = Field(default_factory=dict)
