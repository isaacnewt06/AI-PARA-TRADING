from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from src.trading.blueprint_backtester import BlueprintBacktester, Candle, Trade, Zone
from src.trading.strategy_schemas import BacktestBlueprintSpec


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def test_run_spec_skips_when_input_missing(tmp_path: Path) -> None:
    backtester = BlueprintBacktester(tmp_path / "input", tmp_path / "results", tmp_path / "reports")
    spec = BacktestBlueprintSpec(
        strategy_name="OB Rejection Primary Blueprint",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["H1"],
        entry_timeframe=["M5"],
        session_filter=["new_york"],
        required_conditions=[],
        confirmation_conditions=[],
        entry_logic={},
        sl_logic={},
        tp_logic={},
        rr_min=2.0,
        risk_per_trade=0.5,
        invalidation_conditions=[],
        quantifiable_condition_map=[],
        source_traceability={},
    )

    result = backtester.run_spec(spec)

    assert result["status"] == "skipped"


def test_run_spec_executes_and_writes_outputs(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    rows = [
        {"time": "2026-01-01T12:00:00+00:00", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1},
        {"time": "2026-01-01T12:05:00+00:00", "open": 99, "high": 100, "low": 97, "close": 98, "volume": 1},
        {"time": "2026-01-01T12:10:00+00:00", "open": 98, "high": 99, "low": 96, "close": 97, "volume": 1},
        {"time": "2026-01-01T12:15:00+00:00", "open": 97, "high": 98, "low": 95, "close": 96, "volume": 1},
        {"time": "2026-01-01T12:20:00+00:00", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 1},
        {"time": "2026-01-01T12:25:00+00:00", "open": 95, "high": 96, "low": 93, "close": 94, "volume": 1},
        {"time": "2026-01-01T12:30:00+00:00", "open": 94, "high": 110, "low": 93, "close": 109, "volume": 1},
        {"time": "2026-01-01T12:35:00+00:00", "open": 109, "high": 110, "low": 106, "close": 107, "volume": 1},
        {"time": "2026-01-01T12:40:00+00:00", "open": 107, "high": 108, "low": 104, "close": 105, "volume": 1},
        {"time": "2026-01-01T12:45:00+00:00", "open": 105, "high": 106, "low": 102, "close": 103, "volume": 1},
        {"time": "2026-01-01T12:50:00+00:00", "open": 103, "high": 104, "low": 100, "close": 101, "volume": 1},
        {"time": "2026-01-01T12:55:00+00:00", "open": 101, "high": 105, "low": 99, "close": 104, "volume": 1},
        {"time": "2026-01-01T13:00:00+00:00", "open": 104, "high": 112, "low": 103, "close": 111, "volume": 1},
        {"time": "2026-01-01T13:05:00+00:00", "open": 111, "high": 120, "low": 110, "close": 119, "volume": 1},
    ]
    _write_csv(input_dir / "XAUUSDm_M5.csv", rows)

    backtester = BlueprintBacktester(input_dir, tmp_path / "results", tmp_path / "reports")
    spec = BacktestBlueprintSpec(
        strategy_name="OB Rejection Primary Blueprint",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["H1"],
        entry_timeframe=["M5"],
        session_filter=[],
        required_conditions=[],
        confirmation_conditions=[],
        entry_logic={},
        sl_logic={},
        tp_logic={},
        rr_min=2.0,
        risk_per_trade=0.5,
        invalidation_conditions=[],
        quantifiable_condition_map=[],
        source_traceability={},
    )

    result = backtester.run_spec(spec)

    assert result["status"] == "completed"
    assert Path(result["result_path"]).exists()
    assert Path(result["trades_path"]).exists()
    assert Path(result["report_path"]).exists()


def test_run_spec_falls_back_to_non_suffix_symbol_csv(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    rows = [
        {"time": "2026-01-01T12:00:00+00:00", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1},
        {"time": "2026-01-01T12:05:00+00:00", "open": 99, "high": 100, "low": 97, "close": 98, "volume": 1},
        {"time": "2026-01-01T12:10:00+00:00", "open": 98, "high": 99, "low": 96, "close": 97, "volume": 1},
        {"time": "2026-01-01T12:15:00+00:00", "open": 97, "high": 98, "low": 95, "close": 96, "volume": 1},
        {"time": "2026-01-01T12:20:00+00:00", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 1},
        {"time": "2026-01-01T12:25:00+00:00", "open": 95, "high": 96, "low": 93, "close": 94, "volume": 1},
        {"time": "2026-01-01T12:30:00+00:00", "open": 94, "high": 110, "low": 93, "close": 109, "volume": 1},
        {"time": "2026-01-01T12:35:00+00:00", "open": 109, "high": 110, "low": 106, "close": 107, "volume": 1},
        {"time": "2026-01-01T12:40:00+00:00", "open": 107, "high": 108, "low": 104, "close": 105, "volume": 1},
        {"time": "2026-01-01T12:45:00+00:00", "open": 105, "high": 106, "low": 102, "close": 103, "volume": 1},
        {"time": "2026-01-01T12:50:00+00:00", "open": 103, "high": 104, "low": 100, "close": 101, "volume": 1},
        {"time": "2026-01-01T12:55:00+00:00", "open": 101, "high": 105, "low": 99, "close": 104, "volume": 1},
        {"time": "2026-01-01T13:00:00+00:00", "open": 104, "high": 112, "low": 103, "close": 111, "volume": 1},
        {"time": "2026-01-01T13:05:00+00:00", "open": 111, "high": 120, "low": 110, "close": 119, "volume": 1},
    ]
    _write_csv(input_dir / "XAUUSD_M5.csv", rows)

    backtester = BlueprintBacktester(input_dir, tmp_path / "results", tmp_path / "reports")
    spec = BacktestBlueprintSpec(
        strategy_name="OB Rejection Primary Blueprint",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["H1"],
        entry_timeframe=["M5"],
        session_filter=[],
        required_conditions=[],
        confirmation_conditions=[],
        entry_logic={},
        sl_logic={},
        tp_logic={},
        rr_min=2.0,
        risk_per_trade=0.5,
        invalidation_conditions=[],
        quantifiable_condition_map=[],
        source_traceability={},
    )

    result = backtester.run_spec(spec)

    assert result["status"] == "completed"


def test_run_spec_allows_any_session_filter(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    rows = [
        {"time": "2026-01-01T00:00:00+00:00", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1},
        {"time": "2026-01-01T00:05:00+00:00", "open": 99, "high": 100, "low": 97, "close": 98, "volume": 1},
        {"time": "2026-01-01T00:10:00+00:00", "open": 98, "high": 99, "low": 96, "close": 97, "volume": 1},
        {"time": "2026-01-01T00:15:00+00:00", "open": 97, "high": 98, "low": 95, "close": 96, "volume": 1},
        {"time": "2026-01-01T00:20:00+00:00", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 1},
        {"time": "2026-01-01T00:25:00+00:00", "open": 95, "high": 96, "low": 93, "close": 94, "volume": 1},
        {"time": "2026-01-01T00:30:00+00:00", "open": 94, "high": 110, "low": 93, "close": 109, "volume": 1},
        {"time": "2026-01-01T00:35:00+00:00", "open": 109, "high": 110, "low": 106, "close": 107, "volume": 1},
        {"time": "2026-01-01T00:40:00+00:00", "open": 107, "high": 108, "low": 104, "close": 105, "volume": 1},
        {"time": "2026-01-01T00:45:00+00:00", "open": 105, "high": 106, "low": 102, "close": 103, "volume": 1},
        {"time": "2026-01-01T00:50:00+00:00", "open": 103, "high": 104, "low": 100, "close": 101, "volume": 1},
        {"time": "2026-01-01T00:55:00+00:00", "open": 101, "high": 105, "low": 99, "close": 104, "volume": 1},
        {"time": "2026-01-01T01:00:00+00:00", "open": 104, "high": 112, "low": 103, "close": 111, "volume": 1},
        {"time": "2026-01-01T01:05:00+00:00", "open": 111, "high": 120, "low": 110, "close": 119, "volume": 1},
    ]
    _write_csv(input_dir / "XAUUSDm_M5.csv", rows)

    backtester = BlueprintBacktester(input_dir, tmp_path / "results", tmp_path / "reports")
    spec = BacktestBlueprintSpec(
        strategy_name="OB Rejection Relaxed Validation",
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
        simulation_overrides={"relaxed_htf_bias": True, "relaxed_order_block": True, "relaxed_confirmation_any": True},
        source_traceability={},
    )

    result = backtester.run_spec(spec)

    assert result["status"] == "completed"


def test_write_trades_csv_supports_slots_dataclass(tmp_path: Path) -> None:
    backtester = BlueprintBacktester(tmp_path / "input", tmp_path / "results", tmp_path / "reports")
    trade = Trade(
        strategy_name="OB Rejection Relaxed Validation",
        symbol="XAUUSDm",
        direction="long",
        ob_detected=True,
        htf_bias="long",
        rejection_type="wick_rejection",
        confirmation_band="large_1.2_1.8_atr",
        atr_band="p60_80",
        hour_utc=12,
        entry_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        exit_time=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_price=101.2,
        stop_price=99.0,
        take_profit_price=101.2,
        result="win",
        pnl_r=1.2,
        rr_target=1.2,
        session="any_session",
        setup_time=datetime(2026, 1, 1, 11, 55, tzinfo=timezone.utc),
        context_timeframe="H1",
        entry_timeframe="M5",
        entry_reason="wick_rejection+next_open_entry",
        exit_reason="take_profit",
    )

    output = tmp_path / "results" / "trades.csv"
    backtester._write_trades_csv(output, [trade])

    content = output.read_text(encoding="utf-8")
    assert "XAUUSDm" in content
    assert "win" in content


def test_indicator_caches_do_not_mix_distinct_candle_series() -> None:
    backtester = BlueprintBacktester(Path("."), Path("."), Path("."))
    candles_2024 = [
        Candle(time=datetime(2024, 12, 30, 0, 0, tzinfo=timezone.utc), open=100.0, high=101.0, low=99.0, close=100.5, volume=1.0),
        Candle(time=datetime(2024, 12, 30, 1, 0, tzinfo=timezone.utc), open=100.5, high=101.5, low=100.0, close=101.2, volume=1.0),
        Candle(time=datetime(2024, 12, 30, 2, 0, tzinfo=timezone.utc), open=101.2, high=102.0, low=100.8, close=101.8, volume=1.0),
    ]
    candles_2025 = [
        Candle(time=datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc), open=200.0, high=201.0, low=199.0, close=200.5, volume=1.0),
        Candle(time=datetime(2025, 1, 2, 1, 0, tzinfo=timezone.utc), open=200.5, high=202.0, low=200.0, close=201.7, volume=1.0),
        Candle(time=datetime(2025, 1, 2, 2, 0, tzinfo=timezone.utc), open=201.7, high=203.0, low=201.5, close=202.8, volume=1.0),
        Candle(time=datetime(2025, 1, 2, 3, 0, tzinfo=timezone.utc), open=202.8, high=204.0, low=202.0, close=203.6, volume=1.0),
    ]

    atr_2024 = backtester._get_atr_values(symbol="XAUUSDm", timeframe="H1", candles=candles_2024, period=2)
    atr_2025 = backtester._get_atr_values(symbol="XAUUSDm", timeframe="H1", candles=candles_2025, period=2)
    context_2024 = backtester._get_context_with_indicators(
        symbol="XAUUSDm",
        context_tf="H1",
        context_candles=candles_2024,
        bias_mode="strict",
    )
    context_2025 = backtester._get_context_with_indicators(
        symbol="XAUUSDm",
        context_tf="H1",
        context_candles=candles_2025,
        bias_mode="strict",
    )

    assert len(atr_2024) == len(candles_2024)
    assert len(atr_2025) == len(candles_2025)
    assert len(context_2024) == len(candles_2024)
    assert len(context_2025) == len(candles_2025)
    assert context_2024[0]["candle"].time.year == 2024
    assert context_2025[0]["candle"].time.year == 2025


def test_confirmation_signal_count_supports_two_of_three_logic() -> None:
    candle = Candle(
        time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        open=100.0,
        high=104.0,
        low=95.0,
        close=103.5,
        volume=1.0,
    )
    zone = Zone(
        direction="long",
        created_time=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
        low=96.0,
        high=101.0,
        midpoint=98.5,
        bias_timeframe="H1",
    )

    signal_count = BlueprintBacktester._confirmation_signal_count(candle, zone)

    assert signal_count >= 2
    assert BlueprintBacktester._is_rejection(candle, zone, mode="two_of_three", min_confirmation_signals=2) is True


def test_resolve_entry_price_requires_retrace_for_large_confirmation() -> None:
    confirmation_candle = Candle(
        time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        open=100.0,
        high=110.0,
        low=99.0,
        close=109.0,
        volume=1.0,
    )
    next_candle_without_retrace = Candle(
        time=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc),
        open=109.5,
        high=111.0,
        low=108.7,
        close=110.5,
        volume=1.0,
    )
    next_candle_with_retrace = Candle(
        time=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc),
        open=109.5,
        high=111.0,
        low=106.0,
        close=110.5,
        volume=1.0,
    )

    no_entry = BlueprintBacktester._resolve_entry_price(
        confirmation_candle=confirmation_candle,
        next_candle=next_candle_without_retrace,
        direction="long",
        atr=5.0,
        large_confirmation_atr_multiple=1.8,
        retrace_fraction=0.25,
    )
    retrace_entry = BlueprintBacktester._resolve_entry_price(
        confirmation_candle=confirmation_candle,
        next_candle=next_candle_with_retrace,
        direction="long",
        atr=5.0,
        large_confirmation_atr_multiple=1.8,
        retrace_fraction=0.25,
    )

    assert no_entry is None
    assert retrace_entry is not None


def test_run_trade_supports_partial_exit_management() -> None:
    backtester = BlueprintBacktester(Path("."), Path("."), Path("."))
    spec = BacktestBlueprintSpec(
        strategy_name="Partial Variant",
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
        simulation_overrides={"exit_management": "partial_1r_then_2r"},
        source_traceability={},
    )
    candles = [
        Candle(time=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc), open=100.0, high=101.2, low=99.8, close=100.9, volume=1.0),
        Candle(time=datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc), open=100.9, high=102.1, low=100.7, close=101.9, volume=1.0),
    ]
    trade = backtester._run_trade(
        spec=spec,
        symbol="XAUUSDm",
        direction="long",
        ob_detected=True,
        htf_bias="long",
        rejection_type="wick_rejection",
        confirmation_band="large_1.2_1.8_atr",
        atr_band="p60_80",
        hour_utc=12,
        entry_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        stop_price=99.0,
        take_profit_price=103.0,
        candles=candles,
        rr_target=1.2,
        session="london",
        setup_time=datetime(2026, 1, 1, 11, 55, tzinfo=timezone.utc),
        context_timeframe="H1",
        entry_timeframe="M5",
        entry_reason="wick_rejection+next_open_entry",
        entry_atr=1.0,
        exit_management="partial_1r_then_2r",
    )

    assert trade.exit_reason == "partial_tp_1r_then_final_tp_2r"
    assert trade.pnl_r == 1.5


def test_run_trade_supports_break_even_after_1r() -> None:
    backtester = BlueprintBacktester(Path("."), Path("."), Path("."))
    spec = BacktestBlueprintSpec(
        strategy_name="Break Even Variant",
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
        simulation_overrides={"exit_management": "break_even_after_1r"},
        source_traceability={},
    )
    candles = [
        Candle(time=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc), open=100.0, high=101.1, low=99.8, close=100.8, volume=1.0),
        Candle(time=datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc), open=100.8, high=100.9, low=99.9, close=100.0, volume=1.0),
    ]
    trade = backtester._run_trade(
        spec=spec,
        symbol="XAUUSDm",
        direction="long",
        ob_detected=True,
        htf_bias="long",
        rejection_type="wick_rejection",
        confirmation_band="large_1.2_1.8_atr",
        atr_band="p60_80",
        hour_utc=12,
        entry_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        entry_price=100.0,
        stop_price=99.0,
        take_profit_price=101.5,
        candles=candles,
        rr_target=1.2,
        session="london",
        setup_time=datetime(2026, 1, 1, 11, 55, tzinfo=timezone.utc),
        context_timeframe="H1",
        entry_timeframe="M5",
        entry_reason="wick_rejection+next_open_entry",
        entry_atr=1.0,
        exit_management="break_even_after_1r",
    )

    assert trade.exit_reason == "break_even_after_1r"
    assert trade.pnl_r == 0.0


def test_backtester_deduplicates_symbol_fallback_pairs(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    rows = [
        {"time": "2026-01-01T12:00:00+00:00", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1},
        {"time": "2026-01-01T12:05:00+00:00", "open": 99, "high": 100, "low": 97, "close": 98, "volume": 1},
        {"time": "2026-01-01T12:10:00+00:00", "open": 98, "high": 99, "low": 96, "close": 97, "volume": 1},
        {"time": "2026-01-01T12:15:00+00:00", "open": 97, "high": 98, "low": 95, "close": 96, "volume": 1},
        {"time": "2026-01-01T12:20:00+00:00", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 1},
        {"time": "2026-01-01T12:25:00+00:00", "open": 95, "high": 96, "low": 93, "close": 94, "volume": 1},
        {"time": "2026-01-01T12:30:00+00:00", "open": 94, "high": 110, "low": 93, "close": 109, "volume": 1},
        {"time": "2026-01-01T12:35:00+00:00", "open": 109, "high": 110, "low": 106, "close": 107, "volume": 1},
        {"time": "2026-01-01T12:40:00+00:00", "open": 107, "high": 108, "low": 104, "close": 105, "volume": 1},
        {"time": "2026-01-01T12:45:00+00:00", "open": 105, "high": 106, "low": 102, "close": 103, "volume": 1},
        {"time": "2026-01-01T12:50:00+00:00", "open": 103, "high": 104, "low": 100, "close": 101, "volume": 1},
        {"time": "2026-01-01T12:55:00+00:00", "open": 101, "high": 105, "low": 99, "close": 104, "volume": 1},
        {"time": "2026-01-01T13:00:00+00:00", "open": 104, "high": 112, "low": 103, "close": 111, "volume": 1},
        {"time": "2026-01-01T13:05:00+00:00", "open": 111, "high": 120, "low": 110, "close": 119, "volume": 1},
    ]
    _write_csv(input_dir / "XAUUSDm_M5.csv", rows)
    backtester = BlueprintBacktester(input_dir, tmp_path / "results", tmp_path / "reports")

    single_spec = BacktestBlueprintSpec(
        strategy_name="Single",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["H1"],
        entry_timeframe=["M5"],
        session_filter=[],
        required_conditions=[],
        confirmation_conditions=[],
        entry_logic={},
        sl_logic={},
        tp_logic={},
        rr_min=2.0,
        risk_per_trade=0.5,
        invalidation_conditions=[],
        quantifiable_condition_map=[],
        source_traceability={},
    )
    dup_spec = BacktestBlueprintSpec(
        strategy_name="Dup",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm", "XAUUSD"],
        context_timeframe=["H1"],
        entry_timeframe=["M5"],
        session_filter=[],
        required_conditions=[],
        confirmation_conditions=[],
        entry_logic={},
        sl_logic={},
        tp_logic={},
        rr_min=2.0,
        risk_per_trade=0.5,
        invalidation_conditions=[],
        quantifiable_condition_map=[],
        source_traceability={},
    )

    single = backtester.evaluate_spec(single_spec, persist=False)
    duplicated = backtester.evaluate_spec(dup_spec, persist=False)

    assert single["trades_count"] == duplicated["trades_count"]


def test_run_specs_skips_non_spec_json_artifacts(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    results_dir = tmp_path / "results"
    reports_dir = tmp_path / "reports"
    specs_dir = tmp_path / "specs"
    for path in (input_dir, results_dir, reports_dir, specs_dir):
        path.mkdir(parents=True, exist_ok=True)

    rows = [
        {"time": "2026-01-01T12:00:00+00:00", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1},
        {"time": "2026-01-01T12:05:00+00:00", "open": 99, "high": 100, "low": 97, "close": 98, "volume": 1},
        {"time": "2026-01-01T12:10:00+00:00", "open": 98, "high": 99, "low": 96, "close": 97, "volume": 1},
        {"time": "2026-01-01T12:15:00+00:00", "open": 97, "high": 98, "low": 95, "close": 96, "volume": 1},
        {"time": "2026-01-01T12:20:00+00:00", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 1},
        {"time": "2026-01-01T12:25:00+00:00", "open": 95, "high": 96, "low": 93, "close": 94, "volume": 1},
        {"time": "2026-01-01T12:30:00+00:00", "open": 94, "high": 110, "low": 93, "close": 109, "volume": 1},
        {"time": "2026-01-01T12:35:00+00:00", "open": 109, "high": 110, "low": 106, "close": 107, "volume": 1},
        {"time": "2026-01-01T12:40:00+00:00", "open": 107, "high": 108, "low": 104, "close": 105, "volume": 1},
        {"time": "2026-01-01T12:45:00+00:00", "open": 105, "high": 106, "low": 102, "close": 103, "volume": 1},
        {"time": "2026-01-01T12:50:00+00:00", "open": 103, "high": 104, "low": 100, "close": 101, "volume": 1},
        {"time": "2026-01-01T12:55:00+00:00", "open": 101, "high": 105, "low": 99, "close": 104, "volume": 1},
        {"time": "2026-01-01T13:00:00+00:00", "open": 104, "high": 112, "low": 103, "close": 111, "volume": 1},
        {"time": "2026-01-01T13:05:00+00:00", "open": 111, "high": 120, "low": 110, "close": 119, "volume": 1},
    ]
    _write_csv(input_dir / "XAUUSDm_M5.csv", rows)
    spec = BacktestBlueprintSpec(
        strategy_name="Spec Artifact",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["H1"],
        entry_timeframe=["M5"],
        session_filter=[],
        required_conditions=[],
        confirmation_conditions=[],
        entry_logic={},
        sl_logic={},
        tp_logic={},
        rr_min=2.0,
        risk_per_trade=0.5,
        invalidation_conditions=[],
        quantifiable_condition_map=[],
        source_traceability={},
    )
    (specs_dir / "valid_spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    (specs_dir / "artifact_manifest.json").write_text('{"generated_specs": ["valid_spec.json"]}', encoding="utf-8")

    summary = BlueprintBacktester(input_dir, results_dir, reports_dir).run_specs(specs_dir)

    assert summary["specs_total"] == 2
    assert summary["specs_executed"] == 1


def test_simulate_symbol_respects_max_trades_per_day(monkeypatch, tmp_path: Path) -> None:
    backtester = BlueprintBacktester(tmp_path / "input", tmp_path / "results", tmp_path / "reports")
    entry_candles = [
        Candle(
            time=datetime(2026, 1, 1, 10, index * 5, tzinfo=timezone.utc),
            open=100.0 - index,
            high=101.0 - index,
            low=99.0 - index,
            close=99.5 - index,
            volume=1.0,
        )
        for index in range(8)
    ]
    zone = Zone(
        direction="short",
        created_time=entry_candles[0].time,
        low=95.0,
        high=100.0,
        midpoint=97.5,
        bias_timeframe="M5",
    )
    spec = BacktestBlueprintSpec(
        strategy_name="Control Max Trades",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["M5"],
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
        simulation_overrides={"relaxed_order_block": True, "direction_filter": "short_only", "max_trades_per_day": 1},
        source_traceability={},
    )

    monkeypatch.setattr(
        backtester,
        "_get_context_with_indicators",
        lambda **kwargs: [{"candle": candle, "bias": "short"} for candle in entry_candles],
    )
    monkeypatch.setattr(backtester, "_get_detected_zones", lambda **kwargs: [zone])
    monkeypatch.setattr(backtester, "_latest_zone", lambda *args, **kwargs: zone)
    monkeypatch.setattr(backtester, "_touches_zone", lambda *args, **kwargs: True)
    monkeypatch.setattr(backtester, "_is_rejection", lambda *args, **kwargs: True)
    monkeypatch.setattr(backtester, "_entry_reason", lambda *args, **kwargs: "wick_rejection+next_open_entry")
    monkeypatch.setattr(backtester, "_resolve_entry_price", lambda **kwargs: kwargs["next_candle"].open)
    monkeypatch.setattr(backtester, "_stop_price", lambda *args, **kwargs: 101.0)
    monkeypatch.setattr(backtester, "_liquidity_target", lambda *args, **kwargs: None)

    def fake_run_trade(**kwargs):
        entry_time = kwargs["entry_time"]
        return Trade(
            strategy_name=kwargs["spec"].strategy_name,
            symbol=kwargs["symbol"],
            direction=kwargs["direction"],
            ob_detected=True,
            htf_bias="short",
            rejection_type="wick_rejection",
            confirmation_band="medium_0.8_1.2_atr",
            atr_band="p20_40",
            hour_utc=entry_time.hour,
            entry_time=entry_time,
            exit_time=kwargs["candles"][0].time,
            entry_price=kwargs["entry_price"],
            exit_price=kwargs["entry_price"] - 1.0,
            stop_price=kwargs["stop_price"],
            take_profit_price=kwargs["take_profit_price"],
            result="win",
            pnl_r=1.0,
            rr_target=kwargs["rr_target"],
            session=kwargs["session"],
            setup_time=kwargs["setup_time"],
            context_timeframe=kwargs["context_timeframe"],
            entry_timeframe=kwargs["entry_timeframe"],
            entry_reason=kwargs["entry_reason"],
            exit_reason="take_profit",
        )

    monkeypatch.setattr(backtester, "_run_trade", fake_run_trade)

    trades = backtester._simulate_symbol(
        spec=spec,
        symbol="XAUUSDm",
        entry_tf="M5",
        entry_candles=entry_candles,
        context_tf="M5",
        context_candles=entry_candles,
    )

    assert len(trades) == 1


def test_simulate_symbol_respects_daily_loss_guard(monkeypatch, tmp_path: Path) -> None:
    backtester = BlueprintBacktester(tmp_path / "input", tmp_path / "results", tmp_path / "reports")
    entry_candles = [
        Candle(
            time=datetime(2026, 1, 1, 10, index * 5, tzinfo=timezone.utc),
            open=100.0 - index,
            high=101.0 - index,
            low=99.0 - index,
            close=99.5 - index,
            volume=1.0,
        )
        for index in range(8)
    ]
    zone = Zone(
        direction="short",
        created_time=entry_candles[0].time,
        low=95.0,
        high=100.0,
        midpoint=97.5,
        bias_timeframe="M5",
    )
    spec = BacktestBlueprintSpec(
        strategy_name="Control Daily Guard",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["M5"],
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
        simulation_overrides={"relaxed_order_block": True, "direction_filter": "short_only", "daily_max_losses": 1},
        source_traceability={},
    )

    monkeypatch.setattr(
        backtester,
        "_get_context_with_indicators",
        lambda **kwargs: [{"candle": candle, "bias": "short"} for candle in entry_candles],
    )
    monkeypatch.setattr(backtester, "_get_detected_zones", lambda **kwargs: [zone])
    monkeypatch.setattr(backtester, "_latest_zone", lambda *args, **kwargs: zone)
    monkeypatch.setattr(backtester, "_touches_zone", lambda *args, **kwargs: True)
    monkeypatch.setattr(backtester, "_is_rejection", lambda *args, **kwargs: True)
    monkeypatch.setattr(backtester, "_entry_reason", lambda *args, **kwargs: "wick_rejection+next_open_entry")
    monkeypatch.setattr(backtester, "_resolve_entry_price", lambda **kwargs: kwargs["next_candle"].open)
    monkeypatch.setattr(backtester, "_stop_price", lambda *args, **kwargs: 101.0)
    monkeypatch.setattr(backtester, "_liquidity_target", lambda *args, **kwargs: None)

    def fake_run_trade(**kwargs):
        entry_time = kwargs["entry_time"]
        return Trade(
            strategy_name=kwargs["spec"].strategy_name,
            symbol=kwargs["symbol"],
            direction=kwargs["direction"],
            ob_detected=True,
            htf_bias="short",
            rejection_type="wick_rejection",
            confirmation_band="medium_0.8_1.2_atr",
            atr_band="p20_40",
            hour_utc=entry_time.hour,
            entry_time=entry_time,
            exit_time=kwargs["candles"][0].time,
            entry_price=kwargs["entry_price"],
            exit_price=kwargs["entry_price"] + 1.0,
            stop_price=kwargs["stop_price"],
            take_profit_price=kwargs["take_profit_price"],
            result="loss",
            pnl_r=-1.0,
            rr_target=kwargs["rr_target"],
            session=kwargs["session"],
            setup_time=kwargs["setup_time"],
            context_timeframe=kwargs["context_timeframe"],
            entry_timeframe=kwargs["entry_timeframe"],
            entry_reason=kwargs["entry_reason"],
            exit_reason="stop_loss",
        )

    monkeypatch.setattr(backtester, "_run_trade", fake_run_trade)

    trades = backtester._simulate_symbol(
        spec=spec,
        symbol="XAUUSDm",
        entry_tf="M5",
        entry_candles=entry_candles,
        context_tf="M5",
        context_candles=entry_candles,
    )

    assert len(trades) == 1


def test_simulate_symbol_blocks_entry_hour_not_confirmation_hour(monkeypatch, tmp_path: Path) -> None:
    backtester = BlueprintBacktester(tmp_path / "input", tmp_path / "results", tmp_path / "reports")
    entry_candles = [
        Candle(time=datetime(2026, 1, 1, 11, 55, tzinfo=timezone.utc), open=100.0, high=101.0, low=99.0, close=99.5, volume=1.0),
        Candle(time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), open=99.5, high=100.0, low=98.5, close=99.0, volume=1.0),
        Candle(time=datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc), open=99.0, high=99.2, low=98.0, close=98.5, volume=1.0),
    ]
    zone = Zone(
        direction="short",
        created_time=entry_candles[0].time,
        low=95.0,
        high=100.0,
        midpoint=97.5,
        bias_timeframe="M5",
    )
    spec = BacktestBlueprintSpec(
        strategy_name="Control Entry Hour Block",
        family="OB Rejection",
        symbols_suggested=["XAUUSDm"],
        context_timeframe=["M5"],
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
        simulation_overrides={"relaxed_order_block": True, "direction_filter": "short_only", "blocked_hours_utc": [12]},
        source_traceability={},
    )

    monkeypatch.setattr(
        backtester,
        "_get_context_with_indicators",
        lambda **kwargs: [{"candle": candle, "bias": "short"} for candle in entry_candles],
    )
    monkeypatch.setattr(backtester, "_get_detected_zones", lambda **kwargs: [zone])
    monkeypatch.setattr(backtester, "_latest_zone", lambda *args, **kwargs: zone)
    monkeypatch.setattr(backtester, "_touches_zone", lambda *args, **kwargs: True)
    monkeypatch.setattr(backtester, "_is_rejection", lambda *args, **kwargs: True)
    monkeypatch.setattr(backtester, "_entry_reason", lambda *args, **kwargs: "wick_rejection+next_open_entry")
    monkeypatch.setattr(backtester, "_resolve_entry_price", lambda **kwargs: kwargs["next_candle"].open)
    monkeypatch.setattr(backtester, "_stop_price", lambda *args, **kwargs: 101.0)
    monkeypatch.setattr(backtester, "_liquidity_target", lambda *args, **kwargs: None)

    trades = backtester._simulate_symbol(
        spec=spec,
        symbol="XAUUSDm",
        entry_tf="M5",
        entry_candles=entry_candles,
        context_tf="M5",
        context_candles=entry_candles,
    )

    assert trades == []
