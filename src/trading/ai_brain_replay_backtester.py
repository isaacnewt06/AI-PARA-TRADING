"""Historical replay backtest for the full MAXIMO AI decision stack."""

from __future__ import annotations

import csv
import json
import math
import shutil
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.core.config import Settings
from src.core.logging import get_logger
from src.trading.blueprint_backtester import Candle
from src.trading.maximo_quant_v4_demo_engine import MaximoQuantV4DemoEngine

logger = get_logger(__name__)


@dataclass(slots=True)
class ReplayPosition:
    ticket: int
    symbol: str
    side: str
    volume: float
    entry: float
    sl: float
    tp: float
    opened_at: datetime
    magic: int
    comment: str
    risk_per_unit: float
    be_applied: bool = False


class HistoricalAIReplayBridge:
    """Bridge that makes historical candles look like a live MT5 demo account."""

    SPREAD_PRICE = 0.30

    def __init__(
        self,
        *,
        input_dir: Path,
        symbol: str,
        year: int,
        initial_balance: float,
    ) -> None:
        self.input_dir = input_dir
        self.symbol = symbol
        self.year = int(year)
        self.initial_balance = float(initial_balance)
        self.balance = float(initial_balance)
        self.equity = float(initial_balance)
        self.cursor_time: datetime | None = None
        self.next_ticket = 900000
        self.positions: list[ReplayPosition] = []
        self.closed_trades: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.modifications: list[dict[str, Any]] = []
        self.partial_closes: list[dict[str, Any]] = []
        self.candles = {
            "M1": self._load_csv("M1"),
            "M5": self._load_csv("M5"),
            "H1": self._load_csv("H1"),
        }
        self.candles["H4"] = self._resample(self.candles["H1"], minutes=240)
        self.candles["D1"] = self._resample(self.candles["H1"], minutes=1440)
        self._times_by_timeframe = {
            timeframe: [candle.time for candle in rows]
            for timeframe, rows in self.candles.items()
        }
        self._cursor_indices = {timeframe: -1 for timeframe in self.candles}

    def set_cursor_time(self, cursor_time: datetime) -> None:
        self.cursor_time = cursor_time
        for timeframe, times in self._times_by_timeframe.items():
            self._cursor_indices[timeframe] = bisect_right(times, cursor_time) - 1
        self._mark_to_market_and_close_if_needed()

    def advance_market_until(self, target_time: datetime) -> None:
        """Move the replay clock through every M1 candle until ``target_time``.

        Anchor-mode backtests only run the AI at selected decision timestamps. Positions,
        however, must still be marked on every historical M1 candle between decisions;
        otherwise a TP touched between anchors can be missed and falsely become an SL.
        """

        if self.cursor_time is None or target_time <= self.cursor_time:
            return
        m1_times = self._times_by_timeframe.get("M1", [])
        start = bisect_right(m1_times, self.cursor_time)
        stop = bisect_right(m1_times, target_time)
        for candle_time in m1_times[start:stop]:
            self.set_cursor_time(candle_time)
            if not self.positions:
                break

    def account_status(self) -> dict[str, Any]:
        return {
            "terminal_path": "AI_BRAIN_REPLAY_SIMULATED_MT5",
            "is_demo": True,
            "account_info": {
                "login": 999000,
                "server": "Historical-Replay-Demo",
                "balance": round(self.balance, 4),
                "equity": round(self.equity, 4),
                "margin": 0.0,
                "margin_free": round(self.equity, 4),
                "currency": "USD",
            },
            "terminal_info": {"path": "AI_BRAIN_REPLAY_SIMULATED_MT5", "trade_allowed": True},
        }

    def read_market_snapshot(self, *, symbol: str, bars_by_timeframe: dict[str, int] | None = None) -> dict[str, Any]:
        if self.cursor_time is None:
            raise RuntimeError("Historical replay cursor_time is not set.")
        requested = bars_by_timeframe or {"M1": 500, "M5": 5000, "H1": 2000, "H4": 1000, "D1": 500}
        candles_by_timeframe: dict[str, list[Candle]] = {}
        for timeframe, count in requested.items():
            rows = self.candles.get(timeframe, [])
            latest_index = self._cursor_indices.get(timeframe, -1)
            if latest_index < 0:
                candles_by_timeframe[timeframe] = []
                continue
            start = max(0, latest_index + 1 - int(count))
            candles_by_timeframe[timeframe] = rows[start : latest_index + 1]
        return {
            "symbol": self.symbol,
            "symbol_requested": symbol,
            "terminal_path": "AI_BRAIN_REPLAY_SIMULATED_MT5",
            "timeframes": {
                timeframe: {
                    "bars": len(rows),
                    "first_bar_time": rows[0].time.isoformat() if rows else None,
                    "last_bar_time": rows[-1].time.isoformat() if rows else None,
                }
                for timeframe, rows in candles_by_timeframe.items()
            },
            "candles": candles_by_timeframe,
        }

    def read_execution_environment(self, *, symbol: str) -> dict[str, Any]:
        bid, ask = self._bid_ask()
        hour_rd = self._hour_rd()
        session_rd = self._session_rd(hour_rd)
        return {
            "symbol_requested": symbol,
            "symbol_resolved": self.symbol,
            "bid": bid,
            "ask": ask,
            "live_spread": self.SPREAD_PRICE,
            "spread_price": self.SPREAD_PRICE,
            "spread_p80": self.SPREAD_PRICE,
            "spread_stats": {"p50": self.SPREAD_PRICE, "p80": self.SPREAD_PRICE, "p95": self.SPREAD_PRICE},
            "live_latency": 0.02,
            "latency_seconds": 0.02,
            "slippage_estimated": self.SPREAD_PRICE,
            "hour_rd": hour_rd,
            "session_rd": session_rd,
            "server_time": self._now_iso(),
            "execution_viability": "SAFE",
            "status": "SAFE",
            "is_safe": True,
            "decision": "allow",
            "blockers": [],
            "warnings": [],
            "reason": "Historical replay simulated execution environment.",
        }

    def list_positions(self, *, symbol: str | None = None, magic: int | None = None) -> list[dict[str, Any]]:
        self._mark_to_market_and_close_if_needed()
        rows: list[dict[str, Any]] = []
        for position in self.positions:
            if symbol and position.symbol != self.symbol:
                continue
            if magic is not None and position.magic != int(magic):
                continue
            current_price = self._current_close()
            rows.append(
                {
                    "ticket": position.ticket,
                    "time": int(position.opened_at.timestamp()),
                    "time_msc": int(position.opened_at.timestamp() * 1000),
                    "type": 0 if position.side == "buy" else 1,
                    "magic": position.magic,
                    "identifier": position.ticket,
                    "reason": 3,
                    "volume": position.volume,
                    "price_open": position.entry,
                    "sl": position.sl,
                    "tp": position.tp,
                    "price_current": current_price,
                    "swap": 0.0,
                    "profit": self._floating_profit(position, current_price),
                    "symbol": position.symbol,
                    "comment": position.comment,
                }
            )
        return rows

    def place_demo_market_order(
        self,
        *,
        symbol: str,
        side: str,
        volume_lots: float,
        stop_loss: float,
        take_profit: float,
        deviation_points: int,
        magic_number: int,
        comment: str,
        allow_non_demo: bool = False,
    ) -> dict[str, Any]:
        bid, ask = self._bid_ask()
        side = str(side).lower()
        price = ask if side == "buy" else bid
        stop_loss_value = float(stop_loss)
        take_profit_value = float(take_profit)
        invalid_geometry = (
            (side == "buy" and (stop_loss_value >= price or take_profit_value <= price))
            or (side == "sell" and (stop_loss_value <= price or take_profit_value >= price))
            or side not in {"buy", "sell"}
        )
        if invalid_geometry:
            request = {
                "symbol": self.symbol,
                "side": side,
                "volume": round(float(volume_lots), 2),
                "price": float(price),
                "sl": stop_loss_value,
                "tp": take_profit_value,
                "deviation": deviation_points,
                "magic": magic_number,
                "comment": comment,
            }
            result = {
                "retcode": 10016,
                "order": 0,
                "deal": 0,
                "comment": "AI replay rejected invalid SL/TP geometry",
            }
            payload = {
                "request": request,
                "result": result,
                "is_demo": True,
                "symbol_requested": symbol,
                "symbol_resolved": self.symbol,
            }
            self.orders.append({**payload, "timestamp": self._now_iso()})
            return payload
        ticket = self.next_ticket
        self.next_ticket += 1
        position = ReplayPosition(
            ticket=ticket,
            symbol=self.symbol,
            side=side,
            volume=round(float(volume_lots), 2),
            entry=float(price),
            sl=stop_loss_value,
            tp=take_profit_value,
            opened_at=self.cursor_time or datetime.now(timezone.utc),
            magic=int(magic_number),
            comment=comment,
            risk_per_unit=abs(float(price) - stop_loss_value),
        )
        self.positions.append(position)
        request = {
            "symbol": self.symbol,
            "side": side,
            "volume": position.volume,
            "price": position.entry,
            "sl": position.sl,
            "tp": position.tp,
            "deviation": deviation_points,
            "magic": magic_number,
            "comment": comment,
        }
        result = {"retcode": 10009, "order": ticket, "deal": ticket, "comment": "AI replay filled"}
        payload = {"request": request, "result": result, "is_demo": True, "symbol_requested": symbol, "symbol_resolved": self.symbol}
        self.orders.append({**payload, "timestamp": self._now_iso()})
        return payload

    def modify_position_sl_tp(
        self,
        *,
        symbol: str,
        ticket: int,
        stop_loss: float,
        take_profit: float,
        magic_number: int | None = None,
        comment: str = "MAXIMO protect",
    ) -> dict[str, Any]:
        position = self._find_position(ticket)
        if position is None:
            return {"request": {"ticket": ticket}, "result": {"retcode": 10009, "comment": "position already closed"}}
        position.sl = float(stop_loss)
        position.tp = float(take_profit)
        payload = {
            "request": {"ticket": ticket, "symbol": self.symbol, "sl": position.sl, "tp": position.tp, "comment": comment},
            "result": {"retcode": 10009, "comment": "AI replay modified"},
            "symbol_requested": symbol,
            "symbol_resolved": self.symbol,
        }
        self.modifications.append({**payload, "timestamp": self._now_iso()})
        return payload

    def close_position_partial(
        self,
        *,
        symbol: str,
        ticket: int,
        side: str,
        volume_lots: float,
        deviation_points: int,
        magic_number: int,
        comment: str = "MAXIMO partial",
    ) -> dict[str, Any]:
        position = self._find_position(ticket)
        if position is None:
            return {"request": {"ticket": ticket}, "result": {"retcode": 10009, "comment": "position already closed"}}
        close_volume = min(float(volume_lots), position.volume)
        price = self._current_close()
        self._close_position(position, close_price=price, close_reason=comment, close_volume=close_volume)
        payload = {
            "request": {"ticket": ticket, "symbol": self.symbol, "volume": close_volume, "price": price, "comment": comment},
            "result": {"retcode": 10009, "comment": "AI replay closed"},
            "symbol_requested": symbol,
            "symbol_resolved": self.symbol,
        }
        self.partial_closes.append({**payload, "timestamp": self._now_iso()})
        return payload

    def calculate_risk_volume_lots(
        self,
        *,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        risk_amount: float,
    ) -> dict[str, Any]:
        risk_per_unit = max(abs(float(entry_price) - float(stop_loss)), 0.01)
        risk_per_lot = risk_per_unit * 100.0
        requested = max(float(risk_amount) / risk_per_lot, 0.01)
        volume = max(math.floor(requested * 100.0) / 100.0, 0.01)
        return {
            "symbol_requested": symbol,
            "symbol_resolved": self.symbol,
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "risk_amount": float(risk_amount),
            "risk_per_lot": round(risk_per_lot, 4),
            "requested_volume_lots": round(requested, 4),
            "volume_lots": round(volume, 2),
            "estimated_risk_amount": round(volume * risk_per_lot, 4),
            "estimated_risk_percent_of_target": round((volume * risk_per_lot / max(float(risk_amount), 0.01)) * 100.0, 4),
            "sizing_method": "ai_brain_replay",
            "symbol_info": {"volume_min": 0.01, "volume_step": 0.01, "trade_contract_size": 100.0},
        }

    def _load_csv(self, timeframe: str) -> list[Candle]:
        path = self.input_dir / f"{self.symbol}_{timeframe}_{self.year}.csv"
        if not path.exists():
            path = self.input_dir / f"{self.symbol}_{timeframe}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing historical CSV for {self.symbol} {timeframe}: {path}")
        candles: list[Candle] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                candles.append(
                    Candle(
                        time=datetime.fromisoformat(row["time"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume") or 0.0),
                    )
                )
        return candles

    @staticmethod
    def _resample(candles: list[Candle], *, minutes: int) -> list[Candle]:
        buckets: dict[int, list[Candle]] = {}
        for candle in candles:
            epoch_minute = int(candle.time.timestamp() // 60)
            bucket = epoch_minute - (epoch_minute % minutes)
            buckets.setdefault(bucket, []).append(candle)
        rows: list[Candle] = []
        for bucket in sorted(buckets):
            group = buckets[bucket]
            rows.append(
                Candle(
                    time=datetime.fromtimestamp(bucket * 60, tz=timezone.utc),
                    open=group[0].open,
                    high=max(item.high for item in group),
                    low=min(item.low for item in group),
                    close=group[-1].close,
                    volume=sum(item.volume for item in group),
                )
            )
        return rows

    def _current_m1(self) -> Candle:
        if self.cursor_time is None:
            raise RuntimeError("Historical replay cursor_time is not set.")
        latest_index = self._cursor_indices.get("M1", -1)
        if latest_index < 0:
            raise RuntimeError("No M1 candle available at replay cursor.")
        return self.candles["M1"][latest_index]

    def _current_close(self) -> float:
        return float(self._current_m1().close)

    def _bid_ask(self) -> tuple[float, float]:
        mid = self._current_close()
        half = self.SPREAD_PRICE / 2.0
        return round(mid - half, 3), round(mid + half, 3)

    def _hour_rd(self) -> float:
        if self.cursor_time is None:
            return 0.0
        rd_time = self.cursor_time.astimezone(timezone(timedelta(hours=-4)))
        return round(rd_time.hour + rd_time.minute / 60.0, 4)

    @staticmethod
    def _session_rd(hour_rd: float) -> str:
        if 3 <= hour_rd < 5:
            return "london_rd"
        if 8 <= hour_rd < 11.5:
            return "ny_rd"
        if 14 <= hour_rd < 16:
            return "pm_volatility_rd"
        if 20 <= hour_rd < 22:
            return "evening_volatility_rd"
        return "outside_validation_sessions"

    def _find_position(self, ticket: int) -> ReplayPosition | None:
        for position in self.positions:
            if position.ticket == int(ticket):
                return position
        return None

    def _mark_to_market_and_close_if_needed(self) -> None:
        if self.cursor_time is None:
            return
        candle = self._current_m1()
        for position in list(self.positions):
            self._apply_intracandle_protection(position, candle)
            close_price: float | None = None
            close_reason: str | None = None
            if position.side == "buy":
                if candle.low <= position.sl:
                    close_price = position.sl
                    close_reason = "BE" if abs(position.sl - position.entry) <= 0.0001 else "SL"
                elif candle.high >= position.tp:
                    close_price = position.tp
                    close_reason = "TP"
            else:
                if candle.high >= position.sl:
                    close_price = position.sl
                    close_reason = "BE" if abs(position.sl - position.entry) <= 0.0001 else "SL"
                elif candle.low <= position.tp:
                    close_price = position.tp
                    close_reason = "TP"
            if close_price is not None and close_reason is not None:
                self._close_position(position, close_price=close_price, close_reason=close_reason, close_volume=position.volume)
        self._update_equity()

    @staticmethod
    def _apply_intracandle_protection(position: ReplayPosition, candle: Candle) -> None:
        """Approximate the demo post-entry BE fallback inside historical replay.

        The live/demo engine manages positions on repeated cycles.  Replay can
        advance many M1 candles between decision cycles, so the bridge must not
        let a trade that already touched +0.5R become a full SL without at
        least simulating the mandatory BE fallback used by the runtime.
        """

        if position.be_applied or position.risk_per_unit <= 0:
            return
        if position.side == "buy":
            mfe_r = (float(candle.high) - position.entry) / position.risk_per_unit
            if mfe_r >= MaximoQuantV4DemoEngine.BE_TRIGGER_R and position.sl < position.entry:
                position.sl = position.entry
                position.be_applied = True
        elif position.side == "sell":
            mfe_r = (position.entry - float(candle.low)) / position.risk_per_unit
            if mfe_r >= MaximoQuantV4DemoEngine.BE_TRIGGER_R and position.sl > position.entry:
                position.sl = position.entry
                position.be_applied = True

    def _floating_profit(self, position: ReplayPosition, current_price: float) -> float:
        direction = 1.0 if position.side == "buy" else -1.0
        return round((current_price - position.entry) * direction * position.volume * 100.0, 4)

    def _close_position(self, position: ReplayPosition, *, close_price: float, close_reason: str, close_volume: float) -> None:
        close_volume = min(float(close_volume), position.volume)
        direction = 1.0 if position.side == "buy" else -1.0
        profit = (float(close_price) - position.entry) * direction * close_volume * 100.0
        risk_amount = max(position.risk_per_unit * close_volume * 100.0, 0.01)
        final_r = profit / risk_amount
        self.balance += profit
        self.closed_trades.append(
            {
                "ticket": position.ticket,
                "symbol": position.symbol,
                "side": position.side.upper(),
                "entry_time": position.opened_at.isoformat(),
                "exit_time": self._now_iso(),
                "entry_price": round(position.entry, 4),
                "exit_price": round(float(close_price), 4),
                "sl": round(position.sl, 4),
                "tp": round(position.tp, 4),
                "volume": round(close_volume, 2),
                "profit": round(profit, 4),
                "final_r": round(final_r, 4),
                "exit_reason": close_reason,
                "comment": position.comment,
            }
        )
        position.volume = round(position.volume - close_volume, 2)
        if position.volume <= 0.0001:
            self.positions.remove(position)
        self._update_equity()

    def _update_equity(self) -> None:
        current = self._current_close() if self.cursor_time is not None else 0.0
        floating = sum(self._floating_profit(position, current) for position in self.positions)
        self.equity = self.balance + floating

    def _now_iso(self) -> str:
        return (self.cursor_time or datetime.now(timezone.utc)).isoformat()


class AIBrainReplayBacktester:
    """Replay MAXIMO's full AI stack over historical candles."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.input_dir = settings.paths.data_dir / "backtests" / "input"
        self.output_root = settings.paths.data_dir / "backtests" / "ai_brain_replay"
        self.output_root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        symbol: str,
        year: int,
        initial_capital: float = 500.0,
        max_cycles: int = 120,
        step_bars: int = 5,
        start_date: date | None = None,
        end_date: date | None = None,
        anchor_trades_csv: Path | None = None,
    ) -> dict[str, Any]:
        bridge = HistoricalAIReplayBridge(
            input_dir=self.input_dir,
            symbol=symbol,
            year=year,
            initial_balance=initial_capital,
        )
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_dir = self.output_root / f"{symbol}_{year}_{run_id}"
        runtime_dir = output_dir / "runtime"
        output_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)

        previous_calendar_sync = self.settings.economic_calendar_auto_sync
        self.settings.economic_calendar_auto_sync = False
        try:
            engine = MaximoQuantV4DemoEngine(self.settings, bridge=bridge)  # type: ignore[arg-type]
            self._isolate_engine_outputs(engine, runtime_dir)
            self._enable_fast_replay_reports(engine, runtime_dir)
            self._enable_fast_replay_memory(engine)
            if anchor_trades_csv is not None:
                rows = self._trade_anchor_cursors(
                    bridge.candles["M5"],
                    anchor_trades_csv=anchor_trades_csv,
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                rows = self._candidate_cursors(
                    bridge.candles["M5"],
                    start_date=start_date,
                    end_date=end_date,
                    step_bars=step_bars,
                )
            max_cycle_count = int(max_cycles)
            selected_rows = rows if max_cycle_count <= 0 else rows[: max(1, max_cycle_count)]
            cycles: list[dict[str, Any]] = []
            for index, candle in enumerate(selected_rows):
                bridge.set_cursor_time(candle.time)
                result = engine.run(symbol=symbol, volume_lots=0.01, dry_run=False, confirm_demo=True)
                cycles.append(self._cycle_summary(candle.time, result))
                next_candle = selected_rows[index + 1] if index + 1 < len(selected_rows) else None
                if next_candle is not None and bridge.positions:
                    bridge.advance_market_until(next_candle.time)
            if bridge.positions and selected_rows:
                final_market_time = self._final_market_time(
                    candles=bridge.candles["M1"],
                    end_date=end_date,
                )
                if final_market_time > selected_rows[-1].time:
                    bridge.advance_market_until(final_market_time)
            self._attach_forward_market_outcomes(cycles=cycles, m5_candles=bridge.candles["M5"])
            final_rows = selected_rows or rows
            bridge.set_cursor_time(final_rows[-1].time if final_rows else bridge.candles["M5"][-1].time)
            summary = self._build_summary(
                symbol=symbol,
                year=year,
                initial_capital=initial_capital,
                output_dir=output_dir,
                cycles=cycles,
                bridge=bridge,
                available_cursors=len(rows),
                selected_cursors=len(selected_rows),
                step_bars=step_bars,
                max_cycles=max_cycles,
                anchor_trades_csv=anchor_trades_csv,
            )
            self._write_outputs(output_dir=output_dir, summary=summary, cycles=cycles, bridge=bridge)
            return summary
        finally:
            self.settings.economic_calendar_auto_sync = previous_calendar_sync

    @staticmethod
    def _candidate_cursors(
        candles: list[Candle],
        *,
        start_date: date | None,
        end_date: date | None,
        step_bars: int,
    ) -> list[Candle]:
        # The full AI brain needs enough H1 history for EMA/ATR/context rows.
        # 3000 M5 bars ~= 250 H1 bars; otherwise the first replay cycles are
        # mostly "insufficient_indicators" and do not measure real AI capacity.
        #
        # Warmup must be applied against the full historical series, not after a
        # requested date slice.  Otherwise a one- or two-day diagnostic replay is
        # reduced to one candle and cannot evaluate retests or trigger timing.
        warmup = min(3000, max(0, len(candles) - 1))
        warmed = candles[warmup:]
        rows = [
            candle
            for candle in warmed
            if (start_date is None or candle.time.date() >= start_date)
            and (end_date is None or candle.time.date() <= end_date)
        ]
        return rows[:: max(1, int(step_bars))]

    @staticmethod
    def _final_market_time(*, candles: list[Candle], end_date: date | None) -> datetime:
        if not candles:
            return datetime.now(timezone.utc)
        if end_date is None:
            return candles[-1].time
        eligible = [candle for candle in candles if candle.time.date() <= end_date]
        return eligible[-1].time if eligible else candles[-1].time

    @staticmethod
    def _trade_anchor_cursors(
        candles: list[Candle],
        *,
        anchor_trades_csv: Path,
        start_date: date | None,
        end_date: date | None,
    ) -> list[Candle]:
        """Select M5 candles nearest to exported trade entry timestamps."""
        if not anchor_trades_csv.exists():
            raise FileNotFoundError(f"Missing anchor trades CSV: {anchor_trades_csv}")
        by_time = [candle.time for candle in candles]
        selected: list[Candle] = []
        seen: set[str] = set()
        with anchor_trades_csv.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                raw_time = row.get("entry_time") or row.get("timestamp")
                if not raw_time:
                    continue
                try:
                    entry_time = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if (start_date is not None and entry_time.date() < start_date) or (
                    end_date is not None and entry_time.date() > end_date
                ):
                    continue
                idx = bisect_right(by_time, entry_time) - 1
                idx = max(0, min(idx, len(candles) - 1))
                candle = candles[idx]
                key = candle.time.isoformat()
                if key not in seen:
                    selected.append(candle)
                    seen.add(key)
        return selected

    @staticmethod
    def _isolate_engine_outputs(engine: MaximoQuantV4DemoEngine, runtime_dir: Path) -> None:
        engine.demo_dir = runtime_dir
        engine.signal_path = runtime_dir / "latest_signal.json"
        engine.executions_path = runtime_dir / "executions.csv"
        engine.positions_path = runtime_dir / "positions_snapshot.json"
        engine.report_path = runtime_dir / "demo_report.md"
        engine.position_management_state_path = runtime_dir / "position_management_state.json"
        engine.position_management_history_path = runtime_dir / "position_management_history.jsonl"
        engine.active_watch_path = runtime_dir / "active_watch.json"
        engine.active_watch_history_path = runtime_dir / "active_watch_history.jsonl"
        engine.watch_performance_report_path = runtime_dir / "watch_performance_report.md"
        engine.q_learning_table_path = runtime_dir / "q_learning_table.json"
        engine.q_learning_replay_path = runtime_dir / "q_learning_experience_replay.jsonl"
        engine.q_learning_report_path = runtime_dir / "q_learning_report.md"
        engine.missed_opportunity_state_path = runtime_dir / "missed_opportunity_state.json"
        engine.missed_opportunity_history_path = runtime_dir / "missed_opportunity_learning.jsonl"
        engine.advanced_missed_opportunity_history_path = runtime_dir / "missed_opportunities.jsonl"
        engine.armed_retest_state_path = runtime_dir / "armed_retest_state.json"
        engine.armed_retest_history_path = runtime_dir / "armed_retest_history.jsonl"
        engine.armed_retest_engine.state_path = engine.armed_retest_state_path
        engine.armed_retest_engine.history_path = engine.armed_retest_history_path
        engine.best_trades_memory_path = runtime_dir / "best_trades_memory.jsonl"
        engine.worst_trades_memory_path = runtime_dir / "worst_trades_memory.jsonl"
        engine.decision_source_audit_path = runtime_dir / "decision_source_audit.jsonl"
        engine.expansion_subtype_pretrade_audit_path = runtime_dir / "expansion_subtype_pretrade_audit_v1.jsonl"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            engine.position_management_history_path,
            engine.missed_opportunity_history_path,
            engine.advanced_missed_opportunity_history_path,
            engine.armed_retest_history_path,
            engine.best_trades_memory_path,
            engine.worst_trades_memory_path,
        ):
            path.touch(exist_ok=True)
        engine.market_intelligence_engine.output_dir = runtime_dir / "market_analysis"
        engine.market_intelligence_engine.output_dir.mkdir(parents=True, exist_ok=True)
        engine.market_intelligence_engine.latest_json_path = engine.market_intelligence_engine.output_dir / "latest_market_intelligence.json"
        engine.market_intelligence_engine.latest_md_path = engine.market_intelligence_engine.output_dir / "latest_market_intelligence.md"
        engine.market_intelligence_engine.log_path = engine.market_intelligence_engine.output_dir / "market_intelligence_log.csv"
        engine.market_intelligence_engine.events_path = engine.market_intelligence_engine.output_dir / "economic_events.json"
        engine.market_intelligence_engine.overview_engine.output_dir = engine.market_intelligence_engine.output_dir
        engine.market_intelligence_engine.overview_engine.latest_json_path = engine.market_intelligence_engine.output_dir / "latest_market_overview.json"
        engine.market_intelligence_engine.overview_engine.latest_md_path = engine.market_intelligence_engine.output_dir / "latest_market_overview.md"
        engine.market_intelligence_engine.overview_engine.decision_log_path = engine.market_intelligence_engine.output_dir / "decision_log.csv"

    @staticmethod
    def _enable_fast_replay_reports(engine: MaximoQuantV4DemoEngine, runtime_dir: Path) -> None:
        """Avoid expensive report scans on every replay candle.

        The replay still executes the decision brain, risk guards, Q-learning,
        ARMED_RETEST, entry quality and virtual MT5 bridge.  Only heavy markdown
        and aggregate report regeneration is replaced with lightweight snapshots
        so annual 2025 evaluation is practical.
        """

        def performance_summary() -> dict[str, Any]:
            return {
                "mode": "AI_BRAIN_REPLAY_FAST_REPORTS",
                "classification": "REPLAY_IN_PROGRESS",
                "trades_observed": len(getattr(engine.bridge, "closed_trades", [])),
                "profit_factor_proxy": None,
                "expectancy_r_proxy": None,
                "trades_reached_0_5r_then_negative_unprotected": 0,
                "q_learning_real_feedback_events": 0,
                "report_path": str((runtime_dir / "AI_PERFORMANCE_LAB_REPORT_SKIPPED_FOR_REPLAY.md").resolve()),
            }

        def real_gate_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "REAL_BLOCKED_REPLAY",
                "real_allowed": False,
                "execution_mode_allowed_now": "DEMO_REALISTIC_PROFIT_MODE",
                "blockers": ["historical_replay_not_live_account"],
                "report_path": str((runtime_dir / "REAL_READY_GAP_ANALYSIS_SKIPPED_FOR_REPLAY.md").resolve()),
            }

        def harmony_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
            intelligence = kwargs.get("intelligence") or {}
            final_confirmation = kwargs.get("final_confirmation") or {}
            return {
                "status": "REPLAY_HARMONY_SNAPSHOT",
                "preferred_side": (intelligence.get("overview", {}).get("market_state", {}) or {}).get("preferred_side"),
                "final_confirmation_score": final_confirmation.get("final_confirmation_score"),
                "warnings": [],
                "report_path": str((runtime_dir / "AI_HARMONY_AUDIT_SKIPPED_FOR_REPLAY.md").resolve()),
            }

        def robustness_summary(*args: Any, **kwargs: Any) -> dict[str, str]:
            return {
                "robustness_report": str((runtime_dir / "MAXIMO_FINAL_AI_ROBUSTNESS_SKIPPED_FOR_REPLAY.md").resolve()),
                "demo_realistic_profit_mode_report": str((runtime_dir / "DEMO_REALISTIC_PROFIT_MODE_SKIPPED_FOR_REPLAY.md").resolve()),
                "next_3_week_demo_validation_plan": str((runtime_dir / "NEXT_3_WEEK_DEMO_VALIDATION_PLAN_SKIPPED_FOR_REPLAY.md").resolve()),
            }

        def decision_source_audit(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "mode": "AI_BRAIN_REPLAY_FAST_REPORTS",
                "decision_attribution": {
                    "primary_driver": "full_brain_replay_cycle",
                    "secondary_driver": None,
                    "main_blocker": None,
                    "is_course_knowledge_driving": None,
                    "is_base_strategy_driving": None,
                    "is_external_filter_driving": None,
                },
                "report_skipped": True,
            }

        def noop(*args: Any, **kwargs: Any) -> None:
            return None

        engine.performance_lab.generate = performance_summary  # type: ignore[method-assign]
        engine.real_account_safety_gate.evaluate = real_gate_summary  # type: ignore[method-assign]
        engine.ai_harmony_auditor.generate = harmony_summary  # type: ignore[method-assign]
        engine.final_robustness_reporter.generate = robustness_summary  # type: ignore[method-assign]
        engine._write_signal = noop  # type: ignore[method-assign]
        engine._write_positions_snapshot = noop  # type: ignore[method-assign]
        engine._append_execution_row = noop  # type: ignore[method-assign]
        engine._append_expansion_subtype_pretrade_audit = noop  # type: ignore[method-assign]
        engine._write_report = noop  # type: ignore[method-assign]
        engine._write_watch_performance_report = noop  # type: ignore[method-assign]
        engine._append_decision_source_audit = decision_source_audit  # type: ignore[method-assign]
        engine.daily_demo_validation_report.append_cycle = noop  # type: ignore[method-assign]

    @staticmethod
    def _enable_fast_replay_memory(engine: MaximoQuantV4DemoEngine) -> None:
        """Cache invariant Q-learning seed work during historical replay.

        The live engine intentionally checks historical seed metadata on every
        cycle so demo mode can self-heal if files change.  In replay the
        backtest directory is immutable for the run, so repeating that scan on
        every M5 candle only slows autonomous opportunity discovery tests.
        """

        original_seed = engine.q_learning_memory.ensure_historical_seed
        cached_seed: dict[str, Any] | None = None

        def ensure_historical_seed_once(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal cached_seed
            if cached_seed is None:
                cached_seed = original_seed(*args, **kwargs)
            return {"status": "replay_cached_seed", **cached_seed}

        engine.q_learning_memory.ensure_historical_seed = ensure_historical_seed_once  # type: ignore[method-assign]

    @staticmethod
    def _cycle_summary(cursor_time: datetime, result: dict[str, Any]) -> dict[str, Any]:
        risk_decision = result.get("execution_risk_decision", {}) or {}
        final_confirmation = result.get("final_confirmation", {}) or {}
        entry_quality = result.get("entry_quality", {}) or {}
        readiness = result.get("execution_readiness_quality", {}) or {}
        market_pulse = result.get("market_pulse", {}) or {}
        armed_retest = result.get("armed_retest", {}) or {}
        market_clarity = result.get("market_clarity", {}) or {}
        expected_zone = result.get("expected_entry_zone", {}) or {}
        trigger_plan = result.get("entry_trigger_plan", {}) or {}
        liquidity = final_confirmation.get("liquidity_volume_trap_analysis", {}) or {}
        awareness = final_confirmation.get("confirmation_awareness", {}) or {}
        supervised_recovery = final_confirmation.get("supervised_v56_execute_recovery", {}) or {}
        armed_execute_recovery = final_confirmation.get("armed_retest_execute_recovery", {}) or {}
        session_analysis = final_confirmation.get("session_execution_analysis", {}) or {}
        execution_cost = final_confirmation.get("execution_cost_analysis", {}) or {}
        premium_discount = final_confirmation.get("premium_discount_analysis", {}) or {}
        rd_time = cursor_time.astimezone(timezone(timedelta(hours=-4)))
        hour_rd = round(rd_time.hour + rd_time.minute / 60.0, 4)
        current_price = expected_zone.get("current_price")
        final_score = (
            result.get("final_confirmation_score")
            or final_confirmation.get("final_confirmation_score")
            or armed_retest.get("current_final_confirmation_score")
            or armed_retest.get("initial_final_confirmation_score")
        )
        entry_score = (
            result.get("entry_quality_score")
            or entry_quality.get("entry_quality_score")
            or armed_retest.get("current_entry_quality_score")
            or armed_retest.get("initial_entry_quality_score")
        )
        readiness_score = (
            result.get("execution_readiness_score")
            or readiness.get("execution_readiness_score")
            or armed_retest.get("current_execution_readiness_score")
            or armed_retest.get("initial_execution_readiness_score")
        )
        signal_side = (result.get("signal") or {}).get("direction") if isinstance(result.get("signal"), dict) else None
        clarity_side = market_clarity.get("selected_side")
        armed_side = armed_retest.get("side")
        expected_side = signal_side or clarity_side or armed_side
        return {
            "time": cursor_time.isoformat(),
            "hour_rd": hour_rd,
            "session_rd": session_analysis.get("session") or HistoricalAIReplayBridge._session_rd(hour_rd),
            "session_status": session_analysis.get("status"),
            "spread": execution_cost.get("spread"),
            "spread_p80": execution_cost.get("spread_p80"),
            "premium_discount_status": premium_discount.get("status"),
            "position_in_range": premium_discount.get("position_in_range"),
            "action": result.get("intelligence_action"),
            "execution_status": result.get("execution_status"),
            "signal_detected": bool(result.get("signal_detected")),
            "side": signal_side,
            "preferred_side": expected_side,
            "market_clarity_side": clarity_side,
            "market_pulse": market_pulse.get("score"),
            "final_confirmation": final_score,
            "final_confirmation_score": final_score,
            "entry_quality": entry_score,
            "entry_quality_score": entry_score,
            "execution_readiness": readiness_score,
            "execution_readiness_score": readiness_score,
            "execution_readiness_classification": readiness.get("classification"),
            "execution_readiness_components": readiness.get("components"),
            "execution_readiness_penalties": list(readiness.get("penalties", []) or []),
            "armed_retest_context_recovery": readiness.get("armed_retest_context_recovery"),
            "market_clarity": market_clarity.get("clarity_score"),
            "clarity_side": market_clarity.get("selected_side"),
            "current_price": current_price,
            "expected_zone_from": expected_zone.get("from"),
            "expected_zone_to": expected_zone.get("to"),
            "price_in_expected_zone": expected_zone.get("in_zone_now"),
            "trigger_liquidity_confirmed": trigger_plan.get("liquidity_confirmed"),
            "trigger_continuation_quality": trigger_plan.get("continuation_quality"),
            "trigger_fire_when": trigger_plan.get("fire_when"),
            "final_confirmation_decision": final_confirmation.get("decision"),
            "final_confirmation_blockers": list(final_confirmation.get("blockers", []) or []),
            "supervised_v56_execute_recovery_eligible": supervised_recovery.get("eligible"),
            "supervised_v56_execute_recovery_reason": supervised_recovery.get("reason"),
            "armed_retest_execute_recovery_eligible": armed_execute_recovery.get("eligible"),
            "armed_retest_execute_recovery_reason": armed_execute_recovery.get("reason"),
            "confirmation_awareness_status": awareness.get("status"),
            "confirmation_awareness_allowed": awareness.get("execution_allowed_by_confirmation"),
            "confirmation_awareness_missing": list(awareness.get("missing", []) or []),
            "confirmation_awareness_critical_missing": list(awareness.get("critical_missing", []) or []),
            "confirmation_awareness_summary": awareness.get("summary"),
            "entry_quality_decision": entry_quality.get("decision"),
            "zone_validity": final_confirmation.get("zone_validity"),
            "zone_validity_score": final_confirmation.get("zone_validity_score"),
            "trap_risk_score": final_confirmation.get("trap_risk_score"),
            "late_entry_risk": final_confirmation.get("late_entry_risk"),
            "liquidity_sweep_detected": liquidity.get("liquidity_sweep_detected"),
            "opposite_liquidity_sweep": liquidity.get("opposite_liquidity_sweep"),
            "volume_confirmation_score": liquidity.get("volume_confirmation_score"),
            "movement_quality_score": liquidity.get("movement_quality_score"),
            "liquidity_readiness_score": liquidity.get("liquidity_readiness_score"),
            "manipulation_risk_score": liquidity.get("manipulation_risk_score"),
            "armed_retest_action": armed_retest.get("action") or result.get("armed_retest_status"),
            "armed_retest_reason": armed_retest.get("reason"),
            "entry_confirmation_plan": armed_retest.get("entry_confirmation_plan"),
            "memory_bias": result.get("memory_bias"),
            "risk_mode": result.get("risk_mode") or risk_decision.get("allowed_risk_mode"),
            "blocker": result.get("execution_status") if str(result.get("execution_status", "")).startswith("blocked") else None,
            "reason": risk_decision.get("risk_application_reason") or risk_decision.get("policy_reason") or "",
        }

    @staticmethod
    def _attach_forward_market_outcomes(*, cycles: list[dict[str, Any]], m5_candles: list[Candle]) -> None:
        index_by_time = {candle.time.isoformat(): idx for idx, candle in enumerate(m5_candles)}
        horizons = (10, 20, 50)
        for cycle in cycles:
            idx = index_by_time.get(str(cycle.get("time")))
            if idx is None:
                continue
            side = str(cycle.get("side") or cycle.get("clarity_side") or "").upper()
            if side not in {"BUY", "SELL"}:
                continue
            entry_price = float(cycle.get("current_price") or m5_candles[idx].close)
            for horizon in horizons:
                future = m5_candles[idx + 1 : idx + 1 + horizon]
                if not future:
                    continue
                future_close = float(future[-1].close)
                future_high = max(float(candle.high) for candle in future)
                future_low = min(float(candle.low) for candle in future)
                if side == "BUY":
                    net_move = future_close - entry_price
                    mfe = future_high - entry_price
                    mae = entry_price - future_low
                else:
                    net_move = entry_price - future_close
                    mfe = entry_price - future_low
                    mae = future_high - entry_price
                cycle[f"future_{horizon}_net_move"] = round(net_move, 4)
                cycle[f"future_{horizon}_mfe"] = round(mfe, 4)
                cycle[f"future_{horizon}_mae"] = round(mae, 4)
                cycle[f"future_{horizon}_direction_correct"] = net_move > 0

    @staticmethod
    def _build_summary(
        *,
        symbol: str,
        year: int,
        initial_capital: float,
        output_dir: Path,
        cycles: list[dict[str, Any]],
        bridge: HistoricalAIReplayBridge,
        available_cursors: int | None = None,
        selected_cursors: int | None = None,
        step_bars: int = 1,
        max_cycles: int = 0,
        anchor_trades_csv: Path | None = None,
    ) -> dict[str, Any]:
        available_cursors = len(cycles) if available_cursors is None else int(available_cursors)
        selected_cursors = len(cycles) if selected_cursors is None else int(selected_cursors)
        statuses: dict[str, int] = {}
        actions: dict[str, int] = {}
        blockers: dict[str, int] = {}
        armed_actions: dict[str, int] = {}
        for cycle in cycles:
            statuses[str(cycle.get("execution_status"))] = statuses.get(str(cycle.get("execution_status")), 0) + 1
            actions[str(cycle.get("action"))] = actions.get(str(cycle.get("action")), 0) + 1
            armed_action = str(cycle.get("armed_retest_action") or "")
            if armed_action:
                armed_actions[armed_action] = armed_actions.get(armed_action, 0) + 1
            blocker = cycle.get("blocker")
            if blocker:
                blockers[str(blocker)] = blockers.get(str(blocker), 0) + 1
        closed = bridge.closed_trades
        wins = [trade for trade in closed if float(trade.get("profit") or 0.0) > 0.0]
        losses = [trade for trade in closed if float(trade.get("profit") or 0.0) < 0.0]
        gross_win = sum(float(trade["profit"]) for trade in wins)
        gross_loss = abs(sum(float(trade["profit"]) for trade in losses))
        avg = lambda key: round(sum(float(c.get(key) or 0.0) for c in cycles) / len(cycles), 4) if cycles else 0.0
        understanding = AIBrainReplayBacktester._market_understanding_metrics(cycles)
        session_breakdown = AIBrainReplayBacktester._session_breakdown(cycles, bridge.closed_trades)
        return {
            "mode": "AI_BRAIN_REPLAY_BACKTEST",
            "symbol": symbol,
            "year": year,
            "full_brain_layers": [
                "D1/H4/H1/M5/M1 historical context",
                "Market Pulse",
                "Final Confirmation",
                "Entry Quality",
                "Execution Readiness",
                "ARMED_RETEST",
                "Q-learning decision memory",
                "Trade experience memory",
                "Risk binding",
                "Direction consistency guard",
                "Controlled demo survival protocol",
                "Post-entry management replay",
                "Missed opportunity learning",
            ],
            "initial_capital": round(initial_capital, 2),
            "ending_balance": round(bridge.balance, 4),
            "net_profit": round(bridge.balance - initial_capital, 4),
            "return_percent": round(((bridge.balance - initial_capital) / max(initial_capital, 0.01)) * 100.0, 4),
            "replay_coverage": {
                "available_m5_cursors_after_warmup": available_cursors,
                "evaluated_cycles": selected_cursors,
                "coverage_percent": round((selected_cursors / available_cursors * 100.0) if available_cursors else 0.0, 4),
                "step_bars": int(step_bars),
                "max_cycles": int(max_cycles),
                "max_cycles_0_means_all": True,
                "anchor_trades_csv": str(anchor_trades_csv.resolve()) if anchor_trades_csv else None,
                "anchor_mode": anchor_trades_csv is not None,
            },
            "cycles": len(cycles),
            "actions": actions,
            "execution_statuses": statuses,
            "armed_retest_actions": armed_actions,
            "blockers": blockers,
            "orders_opened": len(bridge.orders),
            "closed_trades": len(closed),
            "open_positions": len(bridge.positions),
            "win_rate": round((len(wins) / len(closed)) * 100.0, 2) if closed else 0.0,
            "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else (999.0 if gross_win else 0.0),
            "avg_market_pulse": avg("market_pulse"),
            "avg_final_confirmation": avg("final_confirmation"),
            "avg_entry_quality": avg("entry_quality"),
            "avg_execution_readiness": avg("execution_readiness"),
            "avg_market_clarity": avg("market_clarity"),
            "in_expected_zone_cycles": sum(1 for cycle in cycles if cycle.get("price_in_expected_zone") is True),
            "liquidity_confirmed_cycles": sum(1 for cycle in cycles if cycle.get("trigger_liquidity_confirmed") is True),
            "market_understanding": understanding,
            "session_breakdown": session_breakdown,
            "realism_notes": {
                "historical_bridge": "Simulates demo MT5 orders, SL/TP fills, spread, latency and post-entry management on historical candles.",
                "execution_environment": "Replay now supplies hour_rd, session_rd and spread_p80 to the same FinalConfirmationEngine used in demo mode.",
                "anchor_mode_warning": "If anchor_mode=true, replay evaluates v56 entry timestamps; use anchor_mode=false for free full-brain opportunity search.",
            },
            "closed_trades_path": str((output_dir / "closed_trades.csv").resolve()),
            "cycles_path": str((output_dir / "cycles.jsonl").resolve()),
            "report_path": str((output_dir / "AI_BRAIN_REPLAY_BACKTEST_REPORT.md").resolve()),
        }

    @staticmethod
    def _market_understanding_metrics(cycles: list[dict[str, Any]]) -> dict[str, Any]:
        def accuracy(key: str, rows: list[dict[str, Any]]) -> float:
            evaluated = [row for row in rows if row.get(key) is not None]
            if not evaluated:
                return 0.0
            return round(sum(1 for row in evaluated if row.get(key) is True) / len(evaluated) * 100.0, 4)

        directional_rows = [
            cycle
            for cycle in cycles
            if str(cycle.get("side") or cycle.get("clarity_side") or "").upper() in {"BUY", "SELL"}
        ]
        high_clarity_rows = [cycle for cycle in directional_rows if float(cycle.get("market_clarity") or 0.0) >= 70.0]
        in_zone_rows = [cycle for cycle in directional_rows if cycle.get("price_in_expected_zone") is True]
        liquidity_rows = [cycle for cycle in directional_rows if cycle.get("trigger_liquidity_confirmed") is True]
        strong_context_rows = [
            cycle
            for cycle in directional_rows
            if float(cycle.get("market_pulse") or 0.0) >= 80.0 and float(cycle.get("market_clarity") or 0.0) >= 70.0
        ]
        bottlenecks = {
            "pulse_high_final_low": sum(
                1
                for cycle in cycles
                if float(cycle.get("market_pulse") or 0.0) >= 80.0 and float(cycle.get("final_confirmation") or 0.0) < 60.0
            ),
            "clarity_high_readiness_low": sum(
                1
                for cycle in cycles
                if float(cycle.get("market_clarity") or 0.0) >= 70.0 and float(cycle.get("execution_readiness") or 0.0) < 50.0
            ),
            "in_zone_no_signal": sum(
                1
                for cycle in cycles
                if cycle.get("price_in_expected_zone") is True and not bool(cycle.get("signal_detected"))
            ),
            "liquidity_confirmed_no_signal": sum(
                1
                for cycle in cycles
                if cycle.get("trigger_liquidity_confirmed") is True and not bool(cycle.get("signal_detected"))
            ),
            "zone_invalid_blocks": sum(
                1
                for cycle in cycles
                if "zone_invalid_or_expired" in (cycle.get("final_confirmation_blockers") or [])
                or str(cycle.get("entry_quality_decision") or "") == "INVALID_ZONE_BLOCK"
            ),
            "armed_retest_drops": sum(1 for cycle in cycles if str(cycle.get("armed_retest_action") or "") == "ARMED_RETEST_DROP"),
        }
        avg = lambda rows, key: round(sum(float(row.get(key) or 0.0) for row in rows) / len(rows), 4) if rows else 0.0
        return {
            "directional_cycles": len(directional_rows),
            "directional_accuracy_10": accuracy("future_10_direction_correct", directional_rows),
            "directional_accuracy_20": accuracy("future_20_direction_correct", directional_rows),
            "directional_accuracy_50": accuracy("future_50_direction_correct", directional_rows),
            "high_clarity_cycles": len(high_clarity_rows),
            "high_clarity_accuracy_20": accuracy("future_20_direction_correct", high_clarity_rows),
            "in_zone_cycles": len(in_zone_rows),
            "in_zone_accuracy_20": accuracy("future_20_direction_correct", in_zone_rows),
            "liquidity_confirmed_cycles": len(liquidity_rows),
            "liquidity_confirmed_accuracy_20": accuracy("future_20_direction_correct", liquidity_rows),
            "strong_context_cycles": len(strong_context_rows),
            "strong_context_accuracy_20": accuracy("future_20_direction_correct", strong_context_rows),
            "avg_future_20_mfe": avg(directional_rows, "future_20_mfe"),
            "avg_future_20_mae": avg(directional_rows, "future_20_mae"),
            "avg_volume_confirmation_score": avg(directional_rows, "volume_confirmation_score"),
            "avg_liquidity_readiness_score": avg(directional_rows, "liquidity_readiness_score"),
            "avg_movement_quality_score": avg(directional_rows, "movement_quality_score"),
            "bottlenecks": bottlenecks,
            "interpretation": AIBrainReplayBacktester._understanding_interpretation(
                directional_accuracy_20=accuracy("future_20_direction_correct", directional_rows),
                high_clarity_accuracy_20=accuracy("future_20_direction_correct", high_clarity_rows),
                bottlenecks=bottlenecks,
            ),
        }

    @staticmethod
    def _session_breakdown(cycles: list[dict[str, Any]], closed_trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        sessions = sorted({str(cycle.get("session_rd") or "unknown") for cycle in cycles})
        trades_by_session: dict[str, list[dict[str, Any]]] = {session: [] for session in sessions}
        for trade in closed_trades:
            session = AIBrainReplayBacktester._session_from_iso_time(str(trade.get("entry_time") or ""))
            trades_by_session.setdefault(session, []).append(trade)

        breakdown: dict[str, dict[str, Any]] = {}
        for session in sorted(set(sessions) | set(trades_by_session)):
            session_cycles = [cycle for cycle in cycles if str(cycle.get("session_rd") or "unknown") == session]
            session_trades = trades_by_session.get(session, [])
            wins = [trade for trade in session_trades if float(trade.get("profit") or 0.0) > 0.0]
            losses = [trade for trade in session_trades if float(trade.get("profit") or 0.0) < 0.0]
            gross_win = sum(float(trade.get("profit") or 0.0) for trade in wins)
            gross_loss = abs(sum(float(trade.get("profit") or 0.0) for trade in losses))
            breakdown[session] = {
                "cycles": len(session_cycles),
                "execute_actions": sum(1 for cycle in session_cycles if str(cycle.get("action")) == "EXECUTE"),
                "demo_orders": sum(1 for cycle in session_cycles if str(cycle.get("execution_status")) == "demo_order_sent"),
                "closed_trades": len(session_trades),
                "net_profit": round(sum(float(trade.get("profit") or 0.0) for trade in session_trades), 4),
                "win_rate": round((len(wins) / len(session_trades) * 100.0) if session_trades else 0.0, 2),
                "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else (999.0 if gross_win else 0.0),
            }
        return breakdown

    @staticmethod
    def _session_from_iso_time(raw_time: str) -> str:
        try:
            timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            return "unknown"
        rd_time = timestamp.astimezone(timezone(timedelta(hours=-4)))
        hour_rd = rd_time.hour + rd_time.minute / 60.0
        return HistoricalAIReplayBridge._session_rd(hour_rd)

    @staticmethod
    def _understanding_interpretation(
        *,
        directional_accuracy_20: float,
        high_clarity_accuracy_20: float,
        bottlenecks: dict[str, int],
    ) -> str:
        if directional_accuracy_20 >= 58.0 and high_clarity_accuracy_20 >= 62.0:
            return "La lectura direccional tiene ventaja estadística; revisar ejecución/timing antes de relajar filtros."
        if bottlenecks.get("in_zone_no_signal", 0) > bottlenecks.get("liquidity_confirmed_no_signal", 0) * 2:
            return "La IA encuentra zonas, pero no está confirmando gatillos estructurales suficientes."
        if bottlenecks.get("pulse_high_final_low", 0) > 0:
            return "Market Pulse detecta contexto vivo, pero Final Confirmation sigue siendo el cuello principal."
        return "Datos insuficientes o lectura aún sin ventaja clara; ampliar replay y comparar por sesión/patrón."

    @staticmethod
    def _write_outputs(
        *,
        output_dir: Path,
        summary: dict[str, Any],
        cycles: list[dict[str, Any]],
        bridge: HistoricalAIReplayBridge,
    ) -> None:
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        with (output_dir / "cycles.jsonl").open("w", encoding="utf-8") as handle:
            for cycle in cycles:
                handle.write(json.dumps(cycle, ensure_ascii=False) + "\n")
        with (output_dir / "closed_trades.csv").open("w", encoding="utf-8", newline="") as handle:
            fieldnames = [
                "ticket",
                "symbol",
                "side",
                "entry_time",
                "exit_time",
                "entry_price",
                "exit_price",
                "sl",
                "tp",
                "volume",
                "profit",
                "final_r",
                "exit_reason",
                "comment",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(bridge.closed_trades)
        report = [
            "# AI Brain Replay Backtest",
            "",
            f"- mode: {summary['mode']}",
            f"- symbol: {summary['symbol']}",
            f"- year: {summary['year']}",
            f"- initial_capital: {summary['initial_capital']}",
            f"- ending_balance: {summary['ending_balance']}",
            f"- return_percent: {summary['return_percent']}",
            f"- cycles: {summary['cycles']}",
            f"- coverage_percent: {summary['replay_coverage']['coverage_percent']}",
            f"- available_m5_cursors_after_warmup: {summary['replay_coverage']['available_m5_cursors_after_warmup']}",
            f"- evaluated_cycles: {summary['replay_coverage']['evaluated_cycles']}",
            f"- step_bars: {summary['replay_coverage']['step_bars']}",
            f"- max_cycles: {summary['replay_coverage']['max_cycles']}",
            f"- orders_opened: {summary['orders_opened']}",
            f"- closed_trades: {summary['closed_trades']}",
            f"- win_rate: {summary['win_rate']}",
            f"- profit_factor: {summary['profit_factor']}",
            f"- avg_market_pulse: {summary['avg_market_pulse']}",
            f"- avg_final_confirmation: {summary['avg_final_confirmation']}",
            f"- avg_entry_quality: {summary['avg_entry_quality']}",
            f"- avg_execution_readiness: {summary['avg_execution_readiness']}",
            f"- avg_market_clarity: {summary['avg_market_clarity']}",
            f"- in_expected_zone_cycles: {summary['in_expected_zone_cycles']}",
            f"- liquidity_confirmed_cycles: {summary['liquidity_confirmed_cycles']}",
            "",
            "## Full Brain Layers Evaluated",
            "",
            *[f"- {layer}" for layer in summary.get("full_brain_layers", [])],
            "",
            "## Market Understanding Validation",
            "",
            f"- directional_cycles: {summary['market_understanding']['directional_cycles']}",
            f"- directional_accuracy_10: {summary['market_understanding']['directional_accuracy_10']}",
            f"- directional_accuracy_20: {summary['market_understanding']['directional_accuracy_20']}",
            f"- directional_accuracy_50: {summary['market_understanding']['directional_accuracy_50']}",
            f"- high_clarity_cycles: {summary['market_understanding']['high_clarity_cycles']}",
            f"- high_clarity_accuracy_20: {summary['market_understanding']['high_clarity_accuracy_20']}",
            f"- in_zone_accuracy_20: {summary['market_understanding']['in_zone_accuracy_20']}",
            f"- liquidity_confirmed_accuracy_20: {summary['market_understanding']['liquidity_confirmed_accuracy_20']}",
            f"- strong_context_accuracy_20: {summary['market_understanding']['strong_context_accuracy_20']}",
            f"- avg_future_20_mfe: {summary['market_understanding']['avg_future_20_mfe']}",
            f"- avg_future_20_mae: {summary['market_understanding']['avg_future_20_mae']}",
            f"- avg_volume_confirmation_score: {summary['market_understanding']['avg_volume_confirmation_score']}",
            f"- avg_liquidity_readiness_score: {summary['market_understanding']['avg_liquidity_readiness_score']}",
            f"- avg_movement_quality_score: {summary['market_understanding']['avg_movement_quality_score']}",
            f"- interpretation: {summary['market_understanding']['interpretation']}",
            "",
            "### Understanding Bottlenecks",
            "",
            *[
                f"- {key}: {value}"
                for key, value in sorted(
                    summary["market_understanding"]["bottlenecks"].items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "",
            "## Actions",
            "",
            *[f"- {key}: {value}" for key, value in sorted(summary["actions"].items())],
            "",
            "## Execution Statuses",
            "",
            *[f"- {key}: {value}" for key, value in sorted(summary["execution_statuses"].items())],
            "",
            "## ARMED_RETEST Actions",
            "",
            *[f"- {key}: {value}" for key, value in sorted(summary.get("armed_retest_actions", {}).items())],
            "",
            "## Session Breakdown",
            "",
            *[
                (
                    f"- {session}: cycles={values['cycles']}, execute_actions={values['execute_actions']}, "
                    f"demo_orders={values['demo_orders']}, closed_trades={values['closed_trades']}, "
                    f"net_profit={values['net_profit']}, win_rate={values['win_rate']}, "
                    f"profit_factor={values['profit_factor']}"
                )
                for session, values in sorted(summary.get("session_breakdown", {}).items())
            ],
            "",
            "## Main Blockers",
            "",
            *[f"- {key}: {value}" for key, value in sorted(summary["blockers"].items(), key=lambda item: item[1], reverse=True)[:12]],
            "",
            "## Realism Notes",
            "",
            *[f"- {key}: {value}" for key, value in summary.get("realism_notes", {}).items()],
            "",
            "## Interpretation",
            "",
            "Este reporte evalúa el cerebro completo de MAXIMO en replay histórico: Market Pulse, Final Confirmation, Entry Quality, Execution Readiness, Q-learning/memoria, guards y gestión virtual post-entrada.",
        ]
        (output_dir / "AI_BRAIN_REPLAY_BACKTEST_REPORT.md").write_text("\n".join(report), encoding="utf-8")
        latest_dir = output_dir.parent
        latest_path = latest_dir / "latest_ai_brain_replay_summary.json"
        latest_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        latest_report = latest_dir / "LATEST_AI_BRAIN_REPLAY_BACKTEST_REPORT.md"
        shutil.copyfile(output_dir / "AI_BRAIN_REPLAY_BACKTEST_REPORT.md", latest_report)
