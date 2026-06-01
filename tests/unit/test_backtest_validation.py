from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.trading.backtest_validation import BacktestValidationEngine
from src.trading.blueprint_backtester import BlueprintBacktester, Candle, Trade
from src.trading.strategy_schemas import BacktestBlueprintSpec


def test_backtest_validation_builds_temporal_sections(monkeypatch, tmp_path: Path) -> None:
    backtester = BlueprintBacktester(tmp_path / "input", tmp_path / "results", tmp_path / "reports")
    spec = BacktestBlueprintSpec(
        strategy_name="OB Rejection Short Only Trailing ATR",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["H1"],
        entry_timeframe=["M5"],
        session_filter=["any_session"],
        required_conditions=[],
        confirmation_conditions=[],
        entry_logic={},
        sl_logic={},
        tp_logic={},
        rr_min=1.2,
        risk_per_trade=0.5,
        invalidation_conditions=[],
        quantifiable_condition_map=[],
        simulation_overrides={"direction_filter": "short_only", "exit_management": "trailing_atr_after_1r"},
        source_traceability={},
    )

    candles = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5 * index),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1.0,
        )
        for index in range(240)
    ]

    def fake_resolve(symbol: str, preferred: list[str]):
        return "XAUUSDm", "M5"

    def fake_load(path: Path):
        return candles

    def fake_evaluate(spec_obj, *, split="all", persist=False, window_start=None, window_end=None):
        trades = [
            Trade(
                strategy_name=spec_obj.strategy_name,
                symbol="XAUUSDm",
                direction="short",
                ob_detected=True,
                htf_bias="short",
                rejection_type="wick_rejection",
                confirmation_band="large_1.2_1.8_atr",
                atr_band="p60_80",
                hour_utc=9,
                entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index * 31),
                exit_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index * 31, minutes=5),
                entry_price=100.0,
                exit_price=99.0 if index % 2 == 0 else 100.5,
                stop_price=101.0,
                take_profit_price=98.8,
                result="win" if index % 2 == 0 else "loss",
                pnl_r=1.2 if index % 2 == 0 else -0.5,
                rr_target=1.2,
                session="london",
                setup_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index * 31, minutes=-5),
                context_timeframe="H1",
                entry_timeframe="M5",
                entry_reason="wick_rejection+next_open_entry",
                exit_reason="trailing_atr_stop_after_1r" if index % 2 == 0 else "stop_loss",
            )
            for index in range(4)
        ]
        metrics = backtester._metrics(trades)
        return {"strategy_name": spec_obj.strategy_name, "status": "completed", "metrics": metrics, "trades": trades}

    monkeypatch.setattr(backtester, "_resolve_entry_timeframe", fake_resolve)
    monkeypatch.setattr(backtester, "_load_candles", fake_load)
    monkeypatch.setattr(backtester, "evaluate_spec", fake_evaluate)

    validation = BacktestValidationEngine(backtester).validate(spec)

    assert validation["month_by_month"]
    assert "passes" in validation["paper_trading_gate"]
    assert isinstance(validation["rolling_7030"], list)
    assert isinstance(validation["walk_forward_blocks"], list)
