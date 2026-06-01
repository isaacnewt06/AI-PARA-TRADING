from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.core.config import reload_settings
from src.trading.blueprint_backtester import Trade
from src.trading.paper_trading_engine import PaperTradingEngine


class _FakeBridge:
    def read_market_snapshot(self, *, symbol: str, bars_by_timeframe: dict[str, int] | None = None) -> dict:
        return {
            "symbol": symbol,
            "terminal_path": r"C:\Program Files\Exness MetaTrader 5\terminal64.exe",
            "timeframes": {
                "M1": {"bars": 10, "first_bar_time": "2026-04-24T10:00:00+00:00", "last_bar_time": "2026-04-24T10:09:00+00:00"},
                "M5": {"bars": 10, "first_bar_time": "2026-04-24T09:15:00+00:00", "last_bar_time": "2026-04-24T10:00:00+00:00"},
                "H1": {"bars": 10, "first_bar_time": "2026-04-24T00:00:00+00:00", "last_bar_time": "2026-04-24T09:00:00+00:00"},
            },
            "candles": {"M1": [], "M5": [], "H1": []},
        }


def _seed_v3_files(data_dir: Path) -> None:
    specs_dir = data_dir / "backtests" / "specs"
    strategies_dir = data_dir / "strategies"
    specs_dir.mkdir(parents=True, exist_ok=True)
    strategies_dir.mkdir(parents=True, exist_ok=True)
    spec_payload = {
        "strategy_name": "OB Rejection Short Only Trailing ATR",
        "family": "OB Rejection",
        "symbols_suggested": ["XAUUSDm"],
        "context_timeframe": ["H1"],
        "entry_timeframe": ["M5", "M1"],
        "session_filter": ["any_session"],
        "required_conditions": [],
        "confirmation_conditions": [],
        "entry_logic": {},
        "sl_logic": {},
        "tp_logic": {},
        "rr_min": 1.2,
        "risk_per_trade": 0.5,
        "invalidation_conditions": [],
        "quantifiable_condition_map": [],
        "simulation_overrides": {
            "direction_filter": "short_only",
            "exit_management": "trailing_atr_after_1r",
            "trail_atr_multiple": 1.0,
        },
        "source_traceability": {},
    }
    (specs_dir / "ob_rejection_short_only_trailing_atr.json").write_text(json.dumps(spec_payload), encoding="utf-8")
    final_candidate = {
        "selected_configuration": {
            "strategy_name": "shorttrail_v3_none_nocd_nolimit_allatr",
            "parameters": {
                "session_filter": ["any_session"],
                "rr_min": 1.2,
                "trail_atr_multiple": 1.0,
                "blocked_hours_utc": [2, 3, 12, 16, 23],
                "required_rejection_signals": ["wick_rejection"],
                "blocked_rejection_signals": [],
                "allowed_atr_bands": [],
                "blocked_atr_bands": [],
                "max_range_atr_multiple": 2.0,
            },
        }
    }
    (strategies_dir / "final_candidate_v3.json").write_text(json.dumps(final_candidate), encoding="utf-8")


def test_paper_trading_engine_loads_v3_spec(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    _seed_v3_files(settings.paths.data_dir)
    engine = PaperTradingEngine(settings, bridge=_FakeBridge())

    spec = engine._load_v3_spec("XAUUSDm")

    assert spec.strategy_name == "OB Rejection Short Only Trailing ATR v3"
    assert spec.symbols_suggested == ["XAUUSDm"]
    assert spec.simulation_overrides["direction_filter"] == "short_only"
    assert spec.simulation_overrides["required_rejection_signals"] == ["wick_rejection"]
    assert spec.simulation_overrides["blocked_hours_utc"] == [2, 3, 12, 16, 23]


def test_paper_trading_engine_writes_artifacts(monkeypatch, tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    _seed_v3_files(settings.paths.data_dir)
    engine = PaperTradingEngine(settings, bridge=_FakeBridge())

    trades = [
        Trade(
            strategy_name="OB Rejection Short Only Trailing ATR v3",
            symbol="XAUUSDm",
            direction="short",
            ob_detected=True,
            htf_bias="short",
            rejection_type="wick_rejection",
            confirmation_band="large_1.2_1.8_atr",
            atr_band="p60_80",
            hour_utc=10,
            entry_time=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 4, 24, 10, 10, tzinfo=timezone.utc),
            entry_price=3300.0,
            exit_price=3298.0,
            stop_price=3301.0,
            take_profit_price=3297.5,
            result="trailing_stop",
            pnl_r=2.0,
            rr_target=1.2,
            session="london",
            setup_time=datetime(2026, 4, 24, 9, 55, tzinfo=timezone.utc),
            context_timeframe="H1",
            entry_timeframe="M5",
            entry_reason="wick_rejection+next_open_entry",
            exit_reason="trailing_atr_stop_after_1r",
        ),
        Trade(
            strategy_name="OB Rejection Short Only Trailing ATR v3",
            symbol="XAUUSDm",
            direction="short",
            ob_detected=True,
            htf_bias="short",
            rejection_type="wick_rejection",
            confirmation_band="medium_0.8_1.2_atr",
            atr_band="p20_40",
            hour_utc=11,
            entry_time=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 4, 24, 11, 5, tzinfo=timezone.utc),
            entry_price=3297.0,
            exit_price=3297.0,
            stop_price=3298.0,
            take_profit_price=3295.8,
            result="open_to_end_of_data",
            pnl_r=0.0,
            rr_target=1.2,
            session="london",
            setup_time=datetime(2026, 4, 24, 10, 55, tzinfo=timezone.utc),
            context_timeframe="H1",
            entry_timeframe="M1",
            entry_reason="wick_rejection+next_open_entry",
            exit_reason="end_of_data_after_trailing",
        ),
    ]

    monkeypatch.setattr(engine, "_simulate_snapshot", lambda **kwargs: trades)

    summary = engine.run(symbol="XAUUSDm", dry_run=True)

    assert summary["signals_generated"] == 2
    assert summary["open_trades"] == 1
    assert summary["closed_trades"] == 1
    assert Path(summary["paths"]["signals_csv"]).exists()
    assert Path(summary["paths"]["open_trades_json"]).exists()
    assert Path(summary["paths"]["closed_trades_csv"]).exists()
    assert Path(summary["paths"]["report_md"]).exists()
    assert "wick_rejection" in Path(summary["paths"]["signals_csv"]).read_text(encoding="utf-8")
