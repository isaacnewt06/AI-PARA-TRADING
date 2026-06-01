"""Controlled paper trading engine for read-only MT5 market monitoring."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import Settings
from src.core.logging import get_logger
from src.trading.approved_strategy_loader import load_ob_rejection_short_trailing_atr_v3
from src.trading.blueprint_backtester import BlueprintBacktester, Candle, Trade
from src.trading.mt5_bridge import MT5Bridge
from src.trading.paper_trading_schemas import PaperSignal, PaperTradeState, PaperTradingSummary
from src.trading.strategy_schemas import BacktestBlueprintSpec

logger = get_logger(__name__)


class PaperTradingEngine:
    """Run the accepted v3 strategy against read-only MT5 market snapshots."""

    V3_STRATEGY_NAME = "OB Rejection Short Only Trailing ATR v3"
    def __init__(self, settings: Settings, *, bridge: MT5Bridge | None = None) -> None:
        self.settings = settings
        self.paper_dir = self.settings.paths.paper_trading_dir
        self.paper_dir.mkdir(parents=True, exist_ok=True)
        self.signals_path = self.paper_dir / "signals.csv"
        self.open_trades_path = self.paper_dir / "open_paper_trades.json"
        self.closed_trades_path = self.paper_dir / "closed_paper_trades.csv"
        self.report_path = self.paper_dir / "paper_report.md"
        self.bridge = bridge or MT5Bridge(settings)
        self.backtester = BlueprintBacktester(
            self.settings.paths.data_dir / "backtests" / "input",
            self.settings.paths.data_dir / "backtests" / "results",
            self.settings.paths.data_dir / "backtests" / "reports",
        )

    def run(
        self,
        *,
        symbol: str,
        dry_run: bool = True,
        bars_by_timeframe: dict[str, int] | None = None,
    ) -> dict:
        spec = self._load_v3_spec(symbol)
        snapshot = self.bridge.read_market_snapshot(symbol=symbol, bars_by_timeframe=bars_by_timeframe)
        trades = self._simulate_snapshot(spec=spec, symbol=symbol, snapshot=snapshot["candles"])
        signals = [self._build_signal(spec, trade) for trade in trades]
        open_trades = [self._build_trade_state(spec, trade, status="open") for trade in trades if trade.result == "open_to_end_of_data"]
        closed_trades = [self._build_trade_state(spec, trade, status="closed") for trade in trades if trade.result != "open_to_end_of_data"]

        self._write_signals_csv(signals)
        self._write_closed_trades_csv(closed_trades)
        self._write_open_trades_json(open_trades)
        self._write_report(
            spec=spec,
            symbol=symbol,
            snapshot=snapshot,
            signals=signals,
            open_trades=open_trades,
            closed_trades=closed_trades,
            dry_run=dry_run,
        )

        latest_signal = signals[-1].model_dump() if signals else None
        summary = PaperTradingSummary(
            strategy_name=spec.strategy_name,
            symbol=symbol,
            dry_run=dry_run,
            market_snapshot={
                key: value for key, value in snapshot.items() if key != "candles"
            },
            signals_generated=len(signals),
            open_trades=len(open_trades),
            closed_trades=len(closed_trades),
            latest_signal=latest_signal,
            paths={
                "signals_csv": str(self.signals_path.resolve()),
                "open_trades_json": str(self.open_trades_path.resolve()),
                "closed_trades_csv": str(self.closed_trades_path.resolve()),
                "report_md": str(self.report_path.resolve()),
            },
        )
        logger.info(
            "Paper trading snapshot completed strategy=%s symbol=%s signals=%s open=%s closed=%s dry_run=%s",
            spec.strategy_name,
            symbol,
            len(signals),
            len(open_trades),
            len(closed_trades),
            dry_run,
        )
        return summary.model_dump()

    def _load_v3_spec(self, symbol: str) -> BacktestBlueprintSpec:
        return load_ob_rejection_short_trailing_atr_v3(self.settings, symbol)

    def _simulate_snapshot(
        self,
        *,
        spec: BacktestBlueprintSpec,
        symbol: str,
        snapshot: dict[str, list[Candle]],
    ) -> list[Trade]:
        context_tf = spec.context_timeframe[0] if spec.context_timeframe else "H1"
        context_candles = snapshot.get(context_tf)
        if not context_candles:
            raise RuntimeError(f"Missing {context_tf} candles in MT5 snapshot.")
        trades: list[Trade] = []
        seen_ids: set[str] = set()
        for entry_tf in spec.entry_timeframe:
            entry_candles = snapshot.get(entry_tf)
            if not entry_candles:
                logger.warning("Skipping paper trading entry timeframe=%s due to missing candles.", entry_tf)
                continue
            timeframe_trades = self.backtester._simulate_symbol(
                spec=spec,
                symbol=symbol,
                entry_tf=entry_tf,
                entry_candles=entry_candles,
                context_tf=context_tf,
                context_candles=context_candles,
                window_start=None,
                window_end=entry_candles[-1].time if entry_candles else None,
            )
            for trade in timeframe_trades:
                trade_id = self._trade_id(trade)
                if trade_id in seen_ids:
                    continue
                seen_ids.add(trade_id)
                trades.append(trade)
        trades.sort(key=lambda item: (item.entry_time, item.entry_timeframe))
        return trades

    def _build_signal(self, spec: BacktestBlueprintSpec, trade: Trade) -> PaperSignal:
        return PaperSignal(
            signal_id=self._trade_id(trade),
            strategy_name=spec.strategy_name,
            timestamp=trade.entry_time.isoformat(),
            symbol=trade.symbol,
            direction=trade.direction,
            entry=round(trade.entry_price, 5),
            stop_loss=round(trade.stop_price, 5),
            take_profit_logic=trade.exit_reason or "trailing_atr_after_1r",
            reason=self._signal_reason(trade),
            confidence=self._confidence(trade),
            entry_timeframe=trade.entry_timeframe,
            context_timeframe=trade.context_timeframe,
            session=trade.session,
            hour_utc=trade.hour_utc,
            atr_band=trade.atr_band,
            confirmation_band=trade.confirmation_band,
            rejection_type=trade.rejection_type,
            status="open" if trade.result == "open_to_end_of_data" else "closed",
        )

    def _build_trade_state(self, spec: BacktestBlueprintSpec, trade: Trade, *, status: str) -> PaperTradeState:
        notes = [
            f"Strategy={spec.strategy_name}",
            "Read-only paper trade generated from MT5 market snapshot.",
        ]
        if trade.result == "open_to_end_of_data":
            notes.append("Trade remains virtual-open at the end of the latest snapshot.")
        else:
            notes.append(f"Virtual trade closed via {trade.exit_reason or trade.result}.")
        return PaperTradeState(
            signal_id=self._trade_id(trade),
            strategy_name=spec.strategy_name,
            symbol=trade.symbol,
            direction=trade.direction,
            status=status,
            entry_time=trade.entry_time.isoformat(),
            setup_time=trade.setup_time.isoformat(),
            exit_time=trade.exit_time.isoformat() if trade.exit_time else None,
            entry_price=round(trade.entry_price, 5),
            exit_price=round(trade.exit_price, 5) if trade.exit_price is not None else None,
            stop_loss=round(trade.stop_price, 5),
            take_profit_price=round(trade.take_profit_price, 5),
            rr_target=trade.rr_target,
            pnl_r=trade.pnl_r,
            result=trade.result,
            trailing_logic="trailing_atr_after_1r",
            session=trade.session,
            hour_utc=trade.hour_utc,
            atr_band=trade.atr_band,
            confirmation_band=trade.confirmation_band,
            rejection_type=trade.rejection_type,
            htf_bias=trade.htf_bias,
            ob_detected=trade.ob_detected,
            entry_reason=trade.entry_reason,
            exit_reason=trade.exit_reason,
            confidence=self._confidence(trade),
            notes=notes,
        )

    def _write_signals_csv(self, signals: list[PaperSignal]) -> None:
        fieldnames = list(PaperSignal.model_fields)
        with self.signals_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for signal in signals:
                writer.writerow(signal.model_dump())

    def _write_closed_trades_csv(self, trades: list[PaperTradeState]) -> None:
        fieldnames = list(PaperTradeState.model_fields)
        with self.closed_trades_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for trade in trades:
                writer.writerow(trade.model_dump())

    def _write_open_trades_json(self, trades: list[PaperTradeState]) -> None:
        payload = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "open_trades": [trade.model_dump() for trade in trades],
        }
        self.open_trades_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_report(
        self,
        *,
        spec: BacktestBlueprintSpec,
        symbol: str,
        snapshot: dict[str, Any],
        signals: list[PaperSignal],
        open_trades: list[PaperTradeState],
        closed_trades: list[PaperTradeState],
        dry_run: bool,
    ) -> None:
        latest_signal = signals[-1] if signals else None
        lines = [
            f"# Paper Trading Report - {spec.strategy_name}",
            "",
            f"- generated_at_utc: {datetime.now(tz=timezone.utc).isoformat()}",
            f"- symbol: {symbol}",
            f"- mode: {'dry_run' if dry_run else 'live_read_only'}",
            f"- signals_generated: {len(signals)}",
            f"- open_trades: {len(open_trades)}",
            f"- closed_trades: {len(closed_trades)}",
            "",
            "## Market Snapshot",
        ]
        for timeframe, details in snapshot["timeframes"].items():
            lines.append(
                f"- {timeframe}: bars={details['bars']} first={details['first_bar_time']} last={details['last_bar_time']}"
            )
        lines.extend(
            [
                "",
                "## Strategy Constraints",
                "- direction: short_only",
                "- exit_management: trailing_atr_after_1r",
                "- required_rejection_signals: wick_rejection",
                "- blocked_hours_utc: 02, 03, 12, 16, 23",
                "- max_range_atr_multiple: 2.0",
                "",
                "## Latest Signal",
            ]
        )
        if latest_signal is None:
            lines.append("- none")
        else:
            lines.extend(
                [
                    f"- timestamp: {latest_signal.timestamp}",
                    f"- entry: {latest_signal.entry}",
                    f"- stop_loss: {latest_signal.stop_loss}",
                    f"- confidence: {latest_signal.confidence}",
                    f"- reason: {latest_signal.reason}",
                ]
            )
        lines.extend(["", "## Open Trades"])
        if not open_trades:
            lines.append("- none")
        for trade in open_trades:
            lines.append(
                f"- {trade.signal_id}: entry={trade.entry_price} stop={trade.stop_loss} rr={trade.rr_target} reason={trade.entry_reason}"
            )
        lines.extend(["", "## Closed Trades"])
        if not closed_trades:
            lines.append("- none")
        for trade in closed_trades[-10:]:
            lines.append(
                f"- {trade.signal_id}: result={trade.result} pnl_r={trade.pnl_r} exit_reason={trade.exit_reason}"
            )
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _trade_id(trade: Trade) -> str:
        return (
            f"{trade.symbol}|{trade.entry_time.isoformat()}|{trade.direction}|"
            f"{trade.entry_timeframe}|{trade.entry_reason or 'entry'}"
        )

    @staticmethod
    def _signal_reason(trade: Trade) -> str:
        parts = [part for part in [trade.entry_reason, trade.rejection_type, trade.atr_band, trade.session] if part]
        return " | ".join(parts) if parts else "paper_signal_detected"

    @staticmethod
    def _confidence(trade: Trade) -> float:
        confidence = 0.45
        if trade.ob_detected:
            confidence += 0.1
        if trade.htf_bias == "short":
            confidence += 0.1
        if trade.rejection_type and "wick_rejection" in trade.rejection_type:
            confidence += 0.15
        if trade.confirmation_band in {"medium_0.8_1.2_atr", "large_1.2_1.8_atr"}:
            confidence += 0.1
        if trade.atr_band and trade.atr_band != "p40_60":
            confidence += 0.05
        if trade.session in {"london", "new_york"}:
            confidence += 0.05
        return round(min(0.95, confidence), 2)
