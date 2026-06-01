from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from src.core.config import reload_settings
from src.trading.blueprint_backtester import Trade
from src.trading.yearly_backtester import YearlyBacktester


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def _seed_strategy_files(data_dir: Path) -> None:
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
                "max_range_atr_multiple": 2.0,
            },
        }
    }
    (strategies_dir / "final_candidate_v3.json").write_text(json.dumps(final_candidate), encoding="utf-8")


def test_yearly_backtester_writes_reports(monkeypatch, tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    _seed_strategy_files(settings.paths.data_dir)
    input_dir = settings.paths.data_dir / "backtests" / "input"
    yearly_dir = settings.paths.data_dir / "backtests" / "yearly"
    sample_rows = [
        {"time": "2025-01-01T00:00:00+00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
        {"time": "2025-01-01T00:05:00+00:00", "open": 1.5, "high": 2.1, "low": 1.0, "close": 1.8, "volume": 12},
    ]
    for timeframe in ("M1", "M5", "H1"):
        _write_csv(input_dir / f"XAUUSDm_{timeframe}_2025.csv", sample_rows)

    backtester = YearlyBacktester(input_dir=input_dir, yearly_dir=yearly_dir, strategies_dir=settings.paths.data_dir / "strategies")
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
            entry_time=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2025, 1, 15, 10, 10, tzinfo=timezone.utc),
            entry_price=2700.0,
            exit_price=2697.0,
            stop_price=2701.0,
            take_profit_price=2698.8,
            result="trailing_stop",
            pnl_r=2.0,
            rr_target=1.2,
            session="london",
            setup_time=datetime(2025, 1, 15, 9, 55, tzinfo=timezone.utc),
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
            entry_time=datetime(2025, 2, 10, 11, 0, tzinfo=timezone.utc),
            exit_time=datetime(2025, 2, 10, 11, 10, tzinfo=timezone.utc),
            entry_price=2710.0,
            exit_price=2711.0,
            stop_price=2711.0,
            take_profit_price=2708.8,
            result="loss",
            pnl_r=-1.0,
            rr_target=1.2,
            session="london",
            setup_time=datetime(2025, 2, 10, 10, 55, tzinfo=timezone.utc),
            context_timeframe="H1",
            entry_timeframe="M1",
            entry_reason="wick_rejection+next_open_entry",
            exit_reason="stop_loss",
        ),
    ]
    monkeypatch.setattr(backtester, "_simulate_year_trades", lambda **kwargs: trades)

    summary = backtester.run(settings=settings, symbol="XAUUSDm", year=2025, initial_capital=500.0)

    assert Path(summary["summary_path"]).exists()
    assert Path(summary["monthly_report_path"]).exists()
    assert Path(summary["report_path"]).exists()
    payload = json.loads(Path(summary["summary_path"]).read_text(encoding="utf-8"))
    assert payload["simulations"]["0.5"]["annual"]["total_trades"] == 2
    assert payload["simulations"]["1.0"]["annual"]["initial_capital"] == 500.0
