"""MetaTrader 5 bridge for historical export and controlled demo execution."""

from __future__ import annotations

import csv
import re
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from src.core.config import Settings
from src.core.logging import get_logger
from src.trading.blueprint_backtester import Candle

logger = get_logger(__name__)


@dataclass(slots=True)
class MT5ExportArtifact:
    timeframe: str
    bars_requested: int
    bars_exported: int
    output_path: str
    first_bar_time: str | None
    last_bar_time: str | None


class MT5Bridge:
    """Adapter for MT5 historical export and controlled demo execution."""

    TIMEFRAME_MAP = {
        "M1": "TIMEFRAME_M1",
        "M5": "TIMEFRAME_M5",
        "M15": "TIMEFRAME_M15",
        "H1": "TIMEFRAME_H1",
        "H4": "TIMEFRAME_H4",
    }

    COMMON_TERMINALS = [
        Path(r"C:\Program Files\Five Percent Online MetaTrader 5\terminal64.exe"),
        Path(r"C:\Program Files\MetaTrader 5\terminal64.exe"),
        Path(r"C:\Program Files\Exness MetaTrader 5\terminal64.exe"),
        Path(r"C:\Program Files\XM MT5\terminal64.exe"),
        Path(r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe"),
    ]

    def __init__(self, settings: Settings, backend: Any | None = None) -> None:
        self.settings = settings
        self._backend = backend

    def healthcheck(self) -> dict:
        backend = self._load_backend()
        if backend is None:
            return {
                "status": "unavailable",
                "message": "MetaTrader5 package is not installed in the active Python environment.",
                "terminal_path": None,
            }
        initialized = self._initialize(backend)
        info = None
        if initialized and backend.terminal_info():
            info = backend.terminal_info()._asdict()
        result = {
            "status": "connected" if initialized else "error",
            "message": "MT5 ready for OHLCV export." if initialized else f"MT5 initialize failed: {backend.last_error()}",
            "terminal_path": info.get("path") if info else self._detect_terminal_path(),
            "terminal_info": info,
        }
        if initialized:
            backend.shutdown()
        return result

    def export_ohlcv(
        self,
        *,
        symbol: str,
        output_dir: Path,
        bars: int,
        timeframe_bars: dict[str, int] | None = None,
    ) -> dict:
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        output_dir.mkdir(parents=True, exist_ok=True)
        requested = timeframe_bars or {
            "M1": max(50_000, bars),
            "M5": max(50_000, bars),
            "H1": max(20_000, min(bars, 50_000)),
        }
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            resolved_symbol = self._resolve_symbol(backend, symbol)
            artifacts: list[MT5ExportArtifact] = []
            for timeframe, count in requested.items():
                artifact = self._export_timeframe(
                    backend=backend,
                    symbol=resolved_symbol,
                    timeframe=timeframe,
                    bars=count,
                    output_dir=output_dir,
                )
                artifacts.append(artifact)
            return {
                "symbol": resolved_symbol,
                "symbol_requested": symbol,
                "terminal_path": (backend.terminal_info().path if backend.terminal_info() else self._detect_terminal_path()),
                "artifacts": [asdict(artifact) for artifact in artifacts],
            }
        finally:
            backend.shutdown()

    def export_ohlcv_range(
        self,
        *,
        symbol: str,
        output_dir: Path,
        from_date: date,
        to_date: date,
    ) -> dict:
        """Export broker OHLCV for a specific UTC date range."""
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        output_dir.mkdir(parents=True, exist_ok=True)
        if from_date > to_date:
            raise ValueError("from_date must be less than or equal to to_date.")
        from_dt = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
        to_dt = datetime.combine(to_date, time.max, tzinfo=timezone.utc)
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            resolved_symbol = self._resolve_symbol(backend, symbol)
            artifacts: list[MT5ExportArtifact] = []
            suffix = self._range_suffix(from_date=from_date, to_date=to_date)
            for timeframe in ("M1", "M5", "H1"):
                artifact = self._export_timeframe_range(
                    backend=backend,
                    symbol=resolved_symbol,
                    timeframe=timeframe,
                    from_dt=from_dt,
                    to_dt=to_dt,
                    output_dir=output_dir,
                    suffix=suffix,
                )
                artifacts.append(artifact)
            return {
                "symbol": resolved_symbol,
                "symbol_requested": symbol,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "terminal_path": (backend.terminal_info().path if backend.terminal_info() else self._detect_terminal_path()),
                "artifacts": [asdict(artifact) for artifact in artifacts],
            }
        finally:
            backend.shutdown()

    def read_market_snapshot(
        self,
        *,
        symbol: str,
        bars_by_timeframe: dict[str, int] | None = None,
    ) -> dict:
        """Read recent OHLCV directly from MT5 without sending any orders."""
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        requested = bars_by_timeframe or {
            "M1": 5_000,
            "M5": 5_000,
            "H1": 2_000,
        }
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            resolved_symbol = self._resolve_symbol(backend, symbol)
            candles_by_timeframe: dict[str, list[Candle]] = {}
            for timeframe, count in requested.items():
                candles_by_timeframe[timeframe] = self._read_timeframe(
                    backend=backend,
                    symbol=resolved_symbol,
                    timeframe=timeframe,
                    bars=count,
                )
            terminal_info = backend.terminal_info()._asdict() if backend.terminal_info() else {}
            return {
                "symbol": resolved_symbol,
                "symbol_requested": symbol,
                "terminal_path": terminal_info.get("path") or self._detect_terminal_path(),
                "timeframes": {
                    timeframe: {
                        "bars": len(candles),
                        "first_bar_time": candles[0].time.isoformat() if candles else None,
                        "last_bar_time": candles[-1].time.isoformat() if candles else None,
                    }
                    for timeframe, candles in candles_by_timeframe.items()
                },
                "candles": candles_by_timeframe,
            }
        finally:
            backend.shutdown()

    def account_status(self) -> dict:
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            account_info = backend.account_info()
            terminal_info = backend.terminal_info()
            account = account_info._asdict() if account_info else {}
            terminal = terminal_info._asdict() if terminal_info else {}
            return {
                "terminal_path": terminal.get("path") or self._detect_terminal_path(),
                "account_info": account,
                "terminal_info": terminal,
                "is_demo": self._is_demo_account(backend, account),
            }
        finally:
            backend.shutdown()

    def read_execution_environment(self, *, symbol: str) -> dict:
        """Read live execution metrics used by controlled demo validation."""
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        start = perf_counter()
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            resolved_symbol = self._resolve_symbol(backend, symbol)
            tick = backend.symbol_info_tick(resolved_symbol)
            elapsed = perf_counter() - start
            if tick is None:
                raise RuntimeError(f"Unable to read symbol tick for {resolved_symbol}: {backend.last_error()}")
            tick_data = tick._asdict() if hasattr(tick, "_asdict") else {
                "ask": getattr(tick, "ask", None),
                "bid": getattr(tick, "bid", None),
                "time": getattr(tick, "time", None),
                "time_msc": getattr(tick, "time_msc", None),
            }
            ask = float(tick_data["ask"])
            bid = float(tick_data["bid"])
            spread = round(max(0.0, ask - bid), 5)
            return {
                "symbol_requested": symbol,
                "symbol_resolved": resolved_symbol,
                "bid": bid,
                "ask": ask,
                "live_spread": spread,
                "spread_price": spread,
                "live_latency": round(elapsed, 4),
                "latency_seconds": round(elapsed, 4),
                "slippage_estimated": spread,
                "execution_delay": None,
                "execution_viability": "SAFE" if spread <= 0.15 and elapsed <= 0.20 else "UNSAFE",
                "tick_time": tick_data.get("time"),
                "tick_time_msc": tick_data.get("time_msc"),
                "mfe": None,
                "mae": None,
                "slippage_real": None,
                "partial_fills": None,
                "trailing_quality": None,
                "time_to_be": None,
                "execution_degradation": None,
            }
        finally:
            backend.shutdown()

    def list_positions(self, *, symbol: str | None = None, magic: int | None = None) -> list[dict]:
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            resolved_symbol = self._resolve_symbol(backend, symbol) if symbol else None
            positions = backend.positions_get(symbol=resolved_symbol) if resolved_symbol else backend.positions_get()
            rows: list[dict] = []
            for position in positions or []:
                payload = position._asdict()
                if magic is not None and int(payload.get("magic", 0)) != magic:
                    continue
                rows.append(payload)
            return rows
        finally:
            backend.shutdown()

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
    ) -> dict:
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'.")
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            account_info = backend.account_info()
            account = account_info._asdict() if account_info else {}
            is_demo = self._is_demo_account(backend, account)
            if not allow_non_demo and not is_demo:
                raise RuntimeError("Refusing to send order because the connected MT5 account does not look like a demo account.")
            resolved_symbol = self._resolve_symbol(backend, symbol)
            tick = backend.symbol_info_tick(resolved_symbol)
            if tick is None:
                raise RuntimeError(f"Unable to read symbol tick for {resolved_symbol}: {backend.last_error()}")
            symbol_info = backend.symbol_info(resolved_symbol) if hasattr(backend, "symbol_info") else None
            tick_data = tick._asdict() if hasattr(tick, "_asdict") else {"ask": getattr(tick, "ask", None), "bid": getattr(tick, "bid", None)}
            price = float(tick_data["ask"] if side == "buy" else tick_data["bid"])
            normalized_volume = self._normalize_volume_lots(volume_lots, symbol_info=symbol_info)
            base_request = {
                "action": getattr(backend, "TRADE_ACTION_DEAL"),
                "symbol": resolved_symbol,
                "volume": normalized_volume,
                "type": getattr(backend, "ORDER_TYPE_BUY" if side == "buy" else "ORDER_TYPE_SELL"),
                "price": price,
                "sl": float(stop_loss),
                "tp": float(take_profit),
                "deviation": int(deviation_points),
                "magic": int(magic_number),
                "comment": self._sanitize_order_comment(comment),
                "type_time": getattr(backend, "ORDER_TIME_GTC"),
            }
            done_code = getattr(backend, "TRADE_RETCODE_DONE", None)
            last_error: Any = None
            last_payload: dict[str, Any] | None = None
            last_request: dict[str, Any] | None = None
            for filling_type in self._filling_type_candidates(backend, resolved_symbol):
                request = {**base_request, "type_filling": int(filling_type)}
                result = backend.order_send(request)
                last_request = request
                if result is None:
                    last_error = backend.last_error()
                    if "filling" in str(last_error).lower():
                        continue
                    raise RuntimeError(f"MT5 order_send returned None: {last_error}")
                result_payload = result._asdict() if hasattr(result, "_asdict") else dict(result)
                last_payload = result_payload
                retcode = int(result_payload.get("retcode", -1))
                if done_code is None or retcode == int(done_code):
                    return {
                        "request": request,
                        "result": result_payload,
                        "account_info": account,
                        "is_demo": is_demo,
                        "symbol_requested": symbol,
                        "symbol_resolved": resolved_symbol,
                    }
                broker_comment = str(result_payload.get("comment") or "")
                if retcode == 10030 or "filling" in broker_comment.lower():
                    continue
                raise RuntimeError(f"MT5 order_send failed retcode={result_payload.get('retcode')} comment={result_payload.get('comment')}")
            if last_payload is not None:
                raise RuntimeError(
                    f"MT5 order_send failed retcode={last_payload.get('retcode')} "
                    f"comment={last_payload.get('comment')} request={last_request}"
                )
            raise RuntimeError(f"MT5 order_send returned None: {last_error}")
        finally:
            backend.shutdown()

    def modify_position_sl_tp(
        self,
        *,
        symbol: str,
        ticket: int,
        stop_loss: float,
        take_profit: float,
        magic_number: int | None = None,
        comment: str = "MAXIMO protect",
    ) -> dict:
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            resolved_symbol = self._resolve_symbol(backend, symbol)
            request = {
                "action": getattr(backend, "TRADE_ACTION_SLTP"),
                "position": int(ticket),
                "symbol": resolved_symbol,
                "sl": float(stop_loss),
                "tp": float(take_profit),
                "comment": self._sanitize_order_comment(comment),
            }
            if magic_number is not None:
                request["magic"] = int(magic_number)
            result = backend.order_send(request)
            if result is None:
                raise RuntimeError(f"MT5 SL/TP modification returned None: {backend.last_error()}")
            result_payload = result._asdict() if hasattr(result, "_asdict") else dict(result)
            done_code = getattr(backend, "TRADE_RETCODE_DONE", None)
            retcode = int(result_payload.get("retcode", -1))
            if done_code is not None and retcode != int(done_code):
                raise RuntimeError(
                    f"MT5 SL/TP modification failed retcode={result_payload.get('retcode')} "
                    f"comment={result_payload.get('comment')}"
                )
            return {
                "request": request,
                "result": result_payload,
                "symbol_requested": symbol,
                "symbol_resolved": resolved_symbol,
            }
        finally:
            backend.shutdown()

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
    ) -> dict:
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        position_side = str(side).lower()
        if position_side not in {"buy", "sell"}:
            raise ValueError("side must be the open position side: 'buy' or 'sell'.")
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            resolved_symbol = self._resolve_symbol(backend, symbol)
            symbol_info = backend.symbol_info(resolved_symbol) if hasattr(backend, "symbol_info") else None
            tick = backend.symbol_info_tick(resolved_symbol)
            if tick is None:
                raise RuntimeError(f"Unable to read symbol tick for {resolved_symbol}: {backend.last_error()}")
            tick_data = tick._asdict() if hasattr(tick, "_asdict") else {"ask": getattr(tick, "ask", None), "bid": getattr(tick, "bid", None)}
            close_side = "sell" if position_side == "buy" else "buy"
            price = float(tick_data["bid"] if close_side == "sell" else tick_data["ask"])
            normalized_volume = self._normalize_volume_lots(volume_lots, symbol_info=symbol_info)
            base_request = {
                "action": getattr(backend, "TRADE_ACTION_DEAL"),
                "position": int(ticket),
                "symbol": resolved_symbol,
                "volume": normalized_volume,
                "type": getattr(backend, "ORDER_TYPE_BUY" if close_side == "buy" else "ORDER_TYPE_SELL"),
                "price": price,
                "deviation": int(deviation_points),
                "magic": int(magic_number),
                "comment": self._sanitize_order_comment(comment),
                "type_time": getattr(backend, "ORDER_TIME_GTC"),
            }
            done_code = getattr(backend, "TRADE_RETCODE_DONE", None)
            last_payload: dict[str, Any] | None = None
            last_request: dict[str, Any] | None = None
            for filling_type in self._filling_type_candidates(backend, resolved_symbol):
                request = {**base_request, "type_filling": int(filling_type)}
                result = backend.order_send(request)
                last_request = request
                if result is None:
                    last_error = backend.last_error()
                    if "filling" in str(last_error).lower():
                        continue
                    raise RuntimeError(f"MT5 partial close returned None: {last_error}")
                result_payload = result._asdict() if hasattr(result, "_asdict") else dict(result)
                last_payload = result_payload
                retcode = int(result_payload.get("retcode", -1))
                if done_code is None or retcode == int(done_code):
                    return {
                        "request": request,
                        "result": result_payload,
                        "symbol_requested": symbol,
                        "symbol_resolved": resolved_symbol,
                    }
                broker_comment = str(result_payload.get("comment") or "")
                if retcode == 10030 or "filling" in broker_comment.lower():
                    continue
                raise RuntimeError(f"MT5 partial close failed retcode={result_payload.get('retcode')} comment={result_payload.get('comment')}")
            raise RuntimeError(
                f"MT5 partial close failed retcode={(last_payload or {}).get('retcode')} "
                f"comment={(last_payload or {}).get('comment')} request={last_request}"
            )
        finally:
            backend.shutdown()

    def calculate_risk_volume_lots(
        self,
        *,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        risk_amount: float,
    ) -> dict[str, Any]:
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            resolved_symbol = self._resolve_symbol(backend, symbol)
            symbol_info = backend.symbol_info(resolved_symbol) if hasattr(backend, "symbol_info") else None
            payload = symbol_info._asdict() if symbol_info is not None and hasattr(symbol_info, "_asdict") else {}
            distance = abs(float(entry_price) - float(stop_loss))
            if distance <= 0:
                raise ValueError("entry_price and stop_loss must be different to size risk.")
            tick_size = float(payload.get("trade_tick_size") or payload.get("point") or 0.01)
            tick_value = float(payload.get("trade_tick_value") or payload.get("trade_tick_value_profit") or 0.0)
            contract_size = float(payload.get("trade_contract_size") or payload.get("contract_size") or 100.0)
            if tick_size > 0 and tick_value > 0:
                risk_per_lot = (distance / tick_size) * tick_value
                sizing_method = "tick_value"
            else:
                risk_per_lot = distance * contract_size
                sizing_method = "contract_size_fallback"
            if risk_per_lot <= 0:
                raise ValueError("Unable to calculate risk_per_lot from MT5 symbol information.")
            requested_volume = float(risk_amount) / risk_per_lot
            normalized_volume = self._normalize_volume_lots(requested_volume, symbol_info=symbol_info)
            estimated_risk = normalized_volume * risk_per_lot
            return {
                "symbol_requested": symbol,
                "symbol_resolved": resolved_symbol,
                "entry_price": float(entry_price),
                "stop_loss": float(stop_loss),
                "risk_amount": round(float(risk_amount), 4),
                "risk_per_lot": round(risk_per_lot, 6),
                "requested_volume_lots": round(requested_volume, 6),
                "volume_lots": normalized_volume,
                "estimated_risk_amount": round(estimated_risk, 4),
                "estimated_risk_percent_of_target": round(estimated_risk / max(float(risk_amount), 0.0001), 4),
                "sizing_method": sizing_method,
                "symbol_info": payload,
            }
        finally:
            backend.shutdown()

    @staticmethod
    def _sanitize_order_comment(comment: str) -> str:
        allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        clean = "".join(ch for ch in str(comment or "MAXIMO") if ch in allowed)
        if not clean:
            clean = "MAXIMO"
        return clean[:20]

    @staticmethod
    def _normalize_volume_lots(volume_lots: float, *, symbol_info: Any | None) -> float:
        payload = symbol_info._asdict() if symbol_info is not None and hasattr(symbol_info, "_asdict") else {}
        volume_min = float(payload.get("volume_min") or 0.01)
        volume_max = float(payload.get("volume_max") or 100.0)
        volume_step = float(payload.get("volume_step") or 0.01)
        volume = max(volume_min, min(float(volume_lots), volume_max))
        if volume_step > 0:
            steps = round((volume - volume_min) / volume_step)
            volume = volume_min + steps * volume_step
        decimals = 3 if volume_step < 0.01 else 2
        return round(max(volume_min, min(volume, volume_max)), decimals)

    def _export_timeframe(
        self,
        *,
        backend: Any,
        symbol: str,
        timeframe: str,
        bars: int,
        output_dir: Path,
    ) -> MT5ExportArtifact:
        timeframe_attr = self.TIMEFRAME_MAP.get(timeframe)
        if timeframe_attr is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        rates = backend.copy_rates_from_pos(symbol, getattr(backend, timeframe_attr), 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"MT5 returned no rates for {symbol} {timeframe}: {backend.last_error()}")

        path = output_dir / f"{symbol}_{timeframe}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for row in rates:
                dt = datetime.fromtimestamp(int(row["time"]), tz=timezone.utc)
                writer.writerow(
                    {
                        "time": dt.isoformat(),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["tick_volume"]),
                    }
                )
        first_time = datetime.fromtimestamp(int(rates[0]["time"]), tz=timezone.utc).isoformat() if len(rates) else None
        last_time = datetime.fromtimestamp(int(rates[-1]["time"]), tz=timezone.utc).isoformat() if len(rates) else None
        logger.info(
            "Exported MT5 OHLCV symbol=%s timeframe=%s bars=%s output=%s",
            symbol,
            timeframe,
            len(rates),
            path,
        )
        return MT5ExportArtifact(
            timeframe=timeframe,
            bars_requested=bars,
            bars_exported=len(rates),
            output_path=str(path.resolve()),
            first_bar_time=first_time,
            last_bar_time=last_time,
        )

    def _export_timeframe_range(
        self,
        *,
        backend: Any,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
        output_dir: Path,
        suffix: str,
    ) -> MT5ExportArtifact:
        timeframe_attr = self.TIMEFRAME_MAP.get(timeframe)
        if timeframe_attr is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        rates = backend.copy_rates_range(symbol, getattr(backend, timeframe_attr), from_dt, to_dt)
        if rates is None or len(rates) == 0:
            rates = self._copy_rates_range_chunked(
                backend=backend,
                symbol=symbol,
                timeframe_attr=timeframe_attr,
                timeframe=timeframe,
                from_dt=from_dt,
                to_dt=to_dt,
            )
        filtered_rates = []
        if rates is not None:
            for row in rates:
                row_time = datetime.fromtimestamp(int(row["time"]), tz=timezone.utc)
                if from_dt <= row_time <= to_dt:
                    filtered_rates.append(row)
        path = output_dir / f"{symbol}_{timeframe}_{suffix}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for row in filtered_rates:
                dt = datetime.fromtimestamp(int(row["time"]), tz=timezone.utc)
                writer.writerow(
                    {
                        "time": dt.isoformat(),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["tick_volume"]),
                    }
                )
        first_time = datetime.fromtimestamp(int(filtered_rates[0]["time"]), tz=timezone.utc).isoformat() if len(filtered_rates) else None
        last_time = datetime.fromtimestamp(int(filtered_rates[-1]["time"]), tz=timezone.utc).isoformat() if len(filtered_rates) else None
        if filtered_rates:
            logger.info(
                "Exported MT5 OHLCV range symbol=%s timeframe=%s from=%s to=%s rows=%s output=%s",
                symbol,
                timeframe,
                from_dt.date(),
                to_dt.date(),
                len(filtered_rates),
                path,
            )
        else:
            logger.warning(
                "No MT5 OHLCV rows remained inside requested range symbol=%s timeframe=%s from=%s to=%s output=%s",
                symbol,
                timeframe,
                from_dt.date(),
                to_dt.date(),
                path,
            )
        return MT5ExportArtifact(
            timeframe=timeframe,
            bars_requested=len(filtered_rates),
            bars_exported=len(filtered_rates),
            output_path=str(path.resolve()),
            first_bar_time=first_time,
            last_bar_time=last_time,
        )

    def _read_timeframe(
        self,
        *,
        backend: Any,
        symbol: str,
        timeframe: str,
        bars: int,
    ) -> list[Candle]:
        timeframe_attr = self.TIMEFRAME_MAP.get(timeframe)
        if timeframe_attr is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        rates = backend.copy_rates_from_pos(symbol, getattr(backend, timeframe_attr), 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"MT5 returned no rates for {symbol} {timeframe}: {backend.last_error()}")
        candles = [
            Candle(
                time=datetime.fromtimestamp(int(row["time"]), tz=timezone.utc),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["tick_volume"]),
            )
            for row in rates
        ]
        logger.info(
            "Read MT5 market snapshot symbol=%s timeframe=%s bars=%s",
            symbol,
            timeframe,
            len(candles),
        )
        return candles

    def _load_backend(self) -> Any | None:
        if self._backend is not None:
            return self._backend
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            return None
        self._backend = mt5
        return self._backend

    def resolve_symbol_name(self, symbol: str) -> str:
        backend = self._load_backend()
        if backend is None:
            raise RuntimeError("MetaTrader5 package is not installed.")
        if not self._initialize(backend):
            raise RuntimeError(f"Unable to initialize MT5: {backend.last_error()}")
        try:
            return self._resolve_symbol(backend, symbol)
        finally:
            backend.shutdown()

    def _initialize(self, backend: Any) -> bool:
        if backend.initialize():
            return True
        detected = self._detect_terminal_path()
        if detected and backend.initialize(path=str(detected)):
            return True
        return False

    def _resolve_symbol(self, backend: Any, requested_symbol: str | None) -> str:
        if not requested_symbol:
            raise ValueError("requested_symbol is required.")
        candidates = self._build_symbol_candidates(requested_symbol)
        for candidate in candidates:
            if backend.symbol_select(candidate, True):
                if candidate != requested_symbol:
                    logger.info("Resolved broker symbol requested=%s resolved=%s", requested_symbol, candidate)
                return candidate
        available_matches = self._find_available_symbol_matches(backend, requested_symbol)
        for candidate in available_matches:
            if backend.symbol_select(candidate, True):
                logger.info("Resolved broker symbol from available list requested=%s resolved=%s", requested_symbol, candidate)
                return candidate
        raise RuntimeError(
            f"Unable to resolve broker symbol for {requested_symbol}. Tried={candidates} "
            f"available_matches={available_matches[:10]} last_error={backend.last_error()}"
        )

    def _find_available_symbol_matches(self, backend: Any, requested_symbol: str) -> list[str]:
        if not hasattr(backend, "symbols_get"):
            return []
        symbols = backend.symbols_get()
        if not symbols:
            return []
        names = []
        for item in symbols:
            if hasattr(item, "name"):
                names.append(str(item.name))
            elif hasattr(item, "_asdict"):
                payload = item._asdict()
                if payload.get("name"):
                    names.append(str(payload["name"]))
        requested_core = self._symbol_core(requested_symbol)
        exact_ci = [name for name in names if name.lower() == requested_symbol.lower()]
        core_equal = [name for name in names if self._symbol_core(name) == requested_core]
        core_contains = [name for name in names if requested_core and requested_core in self._symbol_core(name)]
        ranked = []
        for group in (exact_ci, core_equal, core_contains):
            for name in group:
                if name not in ranked:
                    ranked.append(name)
        return ranked

    @classmethod
    def _build_symbol_candidates(cls, requested_symbol: str) -> list[str]:
        symbol = requested_symbol.strip()
        if not symbol:
            return []
        core = cls._symbol_core(symbol)
        candidates: list[str] = []

        def add(value: str) -> None:
            value = value.strip()
            if value and value not in candidates:
                candidates.append(value)

        add(symbol)
        add(symbol.upper())
        if core:
            add(core)
            for suffix in ("m", "M", ".m", "_m", "-m", "micro", ".pro", ".r", "x", "_ecn"):
                add(f"{core}{suffix}")
            for prefix in ("", "#", "i", "x"):
                if prefix:
                    add(f"{prefix}{core}")
        return candidates

    @staticmethod
    def _symbol_core(symbol: str) -> str:
        letters_only = re.sub(r"[^A-Za-z]", "", symbol or "").upper()
        for core_len in (6, 7):
            if len(letters_only) >= core_len:
                prefix = letters_only[:core_len]
                if prefix.startswith("XAUUSD") or prefix.startswith("XAGUSD"):
                    return prefix[:6]
        return letters_only[:6] if len(letters_only) >= 6 else letters_only

    def _detect_terminal_path(self) -> str | None:
        configured = (self.settings.mt5_terminal_path or "").strip()
        if configured and Path(configured).exists():
            return str(Path(configured))
        for path in self.COMMON_TERMINALS:
            if path.exists():
                return str(path)
        return None

    @staticmethod
    def _resolve_filling_type(backend: Any, symbol: str) -> int:
        symbol_info = backend.symbol_info(symbol) if hasattr(backend, "symbol_info") else None
        if symbol_info is not None:
            payload = symbol_info._asdict() if hasattr(symbol_info, "_asdict") else {}
            filling_mode = payload.get("filling_mode")
            if filling_mode is not None:
                return int(filling_mode)
        for attr in ("ORDER_FILLING_IOC", "ORDER_FILLING_FOK", "ORDER_FILLING_RETURN"):
            if hasattr(backend, attr):
                return int(getattr(backend, attr))
        return 0

    @classmethod
    def _filling_type_candidates(cls, backend: Any, symbol: str) -> list[int]:
        candidates = [cls._resolve_filling_type(backend, symbol)]
        for attr in ("ORDER_FILLING_IOC", "ORDER_FILLING_FOK", "ORDER_FILLING_RETURN"):
            if hasattr(backend, attr):
                candidates.append(int(getattr(backend, attr)))
        result: list[int] = []
        for item in candidates:
            if item not in result:
                result.append(item)
        return result or [0]

    @staticmethod
    def _is_demo_account(backend: Any, account: dict[str, Any]) -> bool:
        trade_mode = account.get("trade_mode")
        demo_mode = getattr(backend, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_mode is not None and trade_mode == demo_mode:
            return True
        if trade_mode == 0:
            return True
        text_fields = " ".join(str(account.get(key, "")) for key in ("server", "company", "name")).lower()
        return "demo" in text_fields

    def _copy_rates_range_chunked(
        self,
        *,
        backend: Any,
        symbol: str,
        timeframe_attr: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
    ):
        chunk_days = {
            "M1": 31,
            "M5": 93,
            "H1": 366,
        }.get(timeframe, 31)
        aggregated: dict[int, Any] = {}
        cursor = from_dt
        while cursor <= to_dt:
            chunk_end = min(to_dt, cursor + timedelta(days=chunk_days))
            rates = backend.copy_rates_range(symbol, getattr(backend, timeframe_attr), cursor, chunk_end)
            if rates is not None:
                for row in rates:
                    aggregated[int(row["time"])] = row
            cursor = chunk_end + timedelta(seconds=1)
        if aggregated:
            logger.info(
                "Chunked MT5 range export symbol=%s timeframe=%s rows=%s",
                symbol,
                timeframe,
                len(aggregated),
            )
        return [aggregated[key] for key in sorted(aggregated)]

    @staticmethod
    def _range_suffix(*, from_date: date, to_date: date) -> str:
        if from_date.month == 1 and from_date.day == 1 and to_date.month == 12 and to_date.day == 31 and from_date.year == to_date.year:
            return str(from_date.year)
        return f"{from_date.isoformat().replace('-', '')}_{to_date.isoformat().replace('-', '')}"
