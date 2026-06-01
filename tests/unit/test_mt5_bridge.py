from __future__ import annotations

from datetime import date
from pathlib import Path

from src.core.config import reload_settings
from src.trading.mt5_bridge import MT5Bridge


class _TerminalInfo:
    def __init__(self, path: str) -> None:
        self.path = path

    def _asdict(self) -> dict:
        return {"path": self.path}


class _AccountInfo:
    def __init__(self, *, trade_mode: int = 0, server: str = "Demo-Server") -> None:
        self.trade_mode = trade_mode
        self.server = server
        self.company = "Test Broker"
        self.name = "Demo Account"
        self.balance = 1000.0
        self.equity = 1000.0

    def _asdict(self) -> dict:
        return {
            "trade_mode": self.trade_mode,
            "server": self.server,
            "company": self.company,
            "name": self.name,
            "balance": self.balance,
            "equity": self.equity,
        }


class _TickInfo:
    def __init__(self, *, ask: float = 2350.5, bid: float = 2350.2) -> None:
        self.ask = ask
        self.bid = bid

    def _asdict(self) -> dict:
        return {"ask": self.ask, "bid": self.bid}


class _SymbolInfo:
    def __init__(
        self,
        *,
        filling_mode: int = 1,
        volume_min: float = 0.01,
        volume_step: float = 0.01,
        volume_max: float = 100.0,
        trade_tick_size: float = 0.01,
        trade_tick_value: float = 1.0,
        trade_contract_size: float = 100.0,
    ) -> None:
        self.filling_mode = filling_mode
        self.volume_min = volume_min
        self.volume_step = volume_step
        self.volume_max = volume_max
        self.trade_tick_size = trade_tick_size
        self.trade_tick_value = trade_tick_value
        self.trade_contract_size = trade_contract_size

    def _asdict(self) -> dict:
        return {
            "filling_mode": self.filling_mode,
            "volume_min": self.volume_min,
            "volume_step": self.volume_step,
            "volume_max": self.volume_max,
            "trade_tick_size": self.trade_tick_size,
            "trade_tick_value": self.trade_tick_value,
            "trade_contract_size": self.trade_contract_size,
        }


class _MarketSymbol:
    def __init__(self, name: str) -> None:
        self.name = name

    def _asdict(self) -> dict:
        return {"name": self.name}


class _OrderResult:
    def __init__(self, *, retcode: int = 10009, order: int = 12345, deal: int = 67890, comment: str = "done") -> None:
        self.retcode = retcode
        self.order = order
        self.deal = deal
        self.comment = comment

    def _asdict(self) -> dict:
        return {
            "retcode": self.retcode,
            "order": self.order,
            "deal": self.deal,
            "comment": self.comment,
        }


class _FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240
    ACCOUNT_TRADE_MODE_DEMO = 0
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009

    def __init__(self) -> None:
        self.initialized = False
        self.last_request = None
        self.available_symbols = ["XAUUSDm", "EURUSDm", "BTCUSDm"]

    def initialize(self, path: str | None = None) -> bool:
        self.initialized = True
        return True

    def shutdown(self) -> None:
        self.initialized = False

    def last_error(self) -> tuple[int, str]:
        return (1, "Success")

    def symbol_select(self, symbol: str, visible: bool) -> bool:
        return symbol in self.available_symbols

    def symbols_get(self):
        return [_MarketSymbol(name) for name in self.available_symbols]

    def terminal_info(self) -> _TerminalInfo:
        return _TerminalInfo(r"C:\Program Files\Five Percent Online MetaTrader 5")

    def account_info(self) -> _AccountInfo:
        return _AccountInfo()

    def positions_get(self, symbol: str | None = None):
        return []

    def symbol_info_tick(self, symbol: str) -> _TickInfo:
        return _TickInfo()

    def symbol_info(self, symbol: str) -> _SymbolInfo:
        return _SymbolInfo()

    def order_send(self, request: dict):
        self.last_request = request
        return _OrderResult()

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start_pos: int, bars: int):
        return [
            {"time": 1710000000, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 10},
            {"time": 1710000060, "open": 1.5, "high": 2.2, "low": 1.2, "close": 2.0, "tick_volume": 12},
        ]

    def copy_rates_range(self, symbol: str, timeframe: int, date_from, date_to):
        return [
            {"time": 1704067200, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 10},
            {"time": 1704067260, "open": 1.5, "high": 2.2, "low": 1.2, "close": 2.0, "tick_volume": 12},
        ]


class _RetryFillingMT5(_FakeMT5):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict] = []

    def symbol_info(self, symbol: str) -> _SymbolInfo:
        return _SymbolInfo(filling_mode=self.ORDER_FILLING_IOC)

    def order_send(self, request: dict):
        self.requests.append(request)
        self.last_request = request
        if request["type_filling"] == self.ORDER_FILLING_IOC:
            return _OrderResult(retcode=10030, comment="Unsupported filling mode")
        return _OrderResult()


def test_mt5_bridge_exports_csv(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = MT5Bridge(settings, backend=_FakeMT5())

    result = bridge.export_ohlcv(symbol="XAUUSDm", output_dir=tmp_path, bars=50_000)

    assert result["symbol"] == "XAUUSDm"
    assert len(result["artifacts"]) == 3
    assert (tmp_path / "XAUUSDm_M1.csv").exists()


def test_mt5_bridge_reads_market_snapshot(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = MT5Bridge(settings, backend=_FakeMT5())

    snapshot = bridge.read_market_snapshot(symbol="XAUUSDm", bars_by_timeframe={"M1": 2, "M5": 2, "H1": 2})

    assert snapshot["symbol"] == "XAUUSDm"
    assert set(snapshot["candles"]) == {"M1", "M5", "H1"}
    assert len(snapshot["candles"]["M5"]) == 2
    assert snapshot["timeframes"]["H1"]["bars"] == 2


def test_mt5_bridge_exports_range_csv(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = MT5Bridge(settings, backend=_FakeMT5())

    result = bridge.export_ohlcv_range(
        symbol="XAUUSDm",
        output_dir=tmp_path,
        from_date=date(2025, 1, 1),
        to_date=date(2025, 12, 31),
    )

    assert result["symbol"] == "XAUUSDm"
    assert len(result["artifacts"]) == 3
    assert (tmp_path / "XAUUSDm_M1_2025.csv").exists()


def test_mt5_bridge_reports_demo_account(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = MT5Bridge(settings, backend=_FakeMT5())

    status = bridge.account_status()

    assert status["is_demo"] is True
    assert "account_info" in status


def test_mt5_bridge_places_demo_market_order(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    backend = _FakeMT5()
    bridge = MT5Bridge(settings, backend=backend)

    result = bridge.place_demo_market_order(
        symbol="XAUUSDm",
        side="buy",
        volume_lots=0.01,
        stop_loss=2348.0,
        take_profit=2354.0,
        deviation_points=50,
        magic_number=560004,
        comment="MAXIMO demo",
    )

    assert result["is_demo"] is True
    assert backend.last_request is not None
    assert backend.last_request["symbol"] == "XAUUSDm"
    assert backend.last_request["type"] == backend.ORDER_TYPE_BUY
    assert backend.last_request["comment"] == "MAXIMOdemo"


def test_mt5_bridge_sanitizes_order_comment_for_broker_compatibility() -> None:
    assert MT5Bridge._sanitize_order_comment("MAXIMO v56_aggressive_filtered_b") == "MAXIMOv56_aggressive"
    assert MT5Bridge._sanitize_order_comment("áé test / weird") == "testweird"


def test_mt5_bridge_retries_unsupported_filling_mode(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    backend = _RetryFillingMT5()
    bridge = MT5Bridge(settings, backend=backend)

    result = bridge.place_demo_market_order(
        symbol="XAUUSDm",
        side="sell",
        volume_lots=0.01,
        stop_loss=2354.0,
        take_profit=2344.0,
        deviation_points=50,
        magic_number=560004,
        comment="MAXIMO demo",
    )

    assert result["result"]["retcode"] == backend.TRADE_RETCODE_DONE
    assert len(backend.requests) >= 2
    assert backend.requests[0]["type_filling"] == backend.ORDER_FILLING_IOC
    assert backend.last_request["type_filling"] != backend.ORDER_FILLING_IOC


def test_mt5_bridge_normalizes_volume_to_symbol_minimum(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    backend = _FakeMT5()
    bridge = MT5Bridge(settings, backend=backend)

    bridge.place_demo_market_order(
        symbol="XAUUSDm",
        side="buy",
        volume_lots=0.005,
        stop_loss=2348.0,
        take_profit=2354.0,
        deviation_points=50,
        magic_number=560004,
        comment="MAXIMO demo",
    )

    assert backend.last_request["volume"] == 0.01


def test_mt5_bridge_modifies_position_sl_tp(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    backend = _FakeMT5()
    bridge = MT5Bridge(settings, backend=backend)

    result = bridge.modify_position_sl_tp(
        symbol="XAUUSD",
        ticket=123456,
        stop_loss=2349.5,
        take_profit=2360.0,
        magic_number=560004,
        comment="MAXIMO protect",
    )

    assert result["result"]["retcode"] == backend.TRADE_RETCODE_DONE
    assert backend.last_request["action"] == backend.TRADE_ACTION_SLTP
    assert backend.last_request["position"] == 123456
    assert backend.last_request["symbol"] == "XAUUSDm"
    assert backend.last_request["sl"] == 2349.5
    assert backend.last_request["tp"] == 2360.0


def test_mt5_bridge_closes_position_partial(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    backend = _FakeMT5()
    bridge = MT5Bridge(settings, backend=backend)

    result = bridge.close_position_partial(
        symbol="XAUUSD",
        ticket=123456,
        side="buy",
        volume_lots=0.02,
        deviation_points=50,
        magic_number=560004,
        comment="MAXIMO partial",
    )

    assert result["result"]["retcode"] == backend.TRADE_RETCODE_DONE
    assert backend.last_request["action"] == backend.TRADE_ACTION_DEAL
    assert backend.last_request["position"] == 123456
    assert backend.last_request["type"] == backend.ORDER_TYPE_SELL
    assert backend.last_request["volume"] == 0.02


def test_mt5_bridge_calculates_one_percent_risk_volume(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    backend = _FakeMT5()
    bridge = MT5Bridge(settings, backend=backend)

    result = bridge.calculate_risk_volume_lots(
        symbol="XAUUSD",
        entry_price=2350.0,
        stop_loss=2348.0,
        risk_amount=10.0,
    )

    assert result["symbol_resolved"] == "XAUUSDm"
    assert result["risk_per_lot"] == 200.0
    assert result["volume_lots"] == 0.05
    assert result["estimated_risk_amount"] == 10.0


def test_mt5_bridge_resolves_requested_symbol_to_broker_suffix(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = MT5Bridge(settings, backend=_FakeMT5())

    resolved = bridge.resolve_symbol_name("XAUUSD")

    assert resolved == "XAUUSDm"


def test_mt5_bridge_snapshot_uses_resolved_symbol(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = MT5Bridge(settings, backend=_FakeMT5())

    snapshot = bridge.read_market_snapshot(symbol="XAUUSD", bars_by_timeframe={"M1": 2, "M5": 2, "H1": 2})

    assert snapshot["symbol_requested"] == "XAUUSD"
    assert snapshot["symbol"] == "XAUUSDm"
