from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.trading.blueprint_backtester import Candle
from src.trading.maximo_br_backtester import MaximoBRProBacktester, OpenTrade


def test_confirmed_pivots_wait_for_confirmation() -> None:
    highs = [1, 2, 3, 4, 5, 6, 10, 6, 5, 4, 3, 2, 1, 1, 1]
    lows = [value - 0.5 for value in highs]
    supports, resistances = MaximoBRProBacktester._confirmed_pivots(highs, lows, pivot_len=2)

    assert resistances[7] is None
    assert resistances[8] == 10
    assert supports[8] is None


def test_session_filter_uses_new_york_windows() -> None:
    london_time = datetime(2026, 5, 1, 7, 30, tzinfo=timezone.utc)  # 03:30 NY
    ny_am_time = datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc)  # 09:00 NY
    other_time = datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc)  # 14:00 NY

    london_variant = MaximoBRProBacktester.SESSION_VARIANTS[1]
    ny_variant = MaximoBRProBacktester.SESSION_VARIANTS[2]

    assert MaximoBRProBacktester._session_allowed(london_time, london_variant) is True
    assert MaximoBRProBacktester._session_allowed(ny_am_time, london_variant) is False
    assert MaximoBRProBacktester._session_allowed(ny_am_time, ny_variant) is True
    assert MaximoBRProBacktester._session_allowed(other_time, ny_variant) is False


def test_coverage_marks_short_m1_window_insufficient(tmp_path: Path) -> None:
    start = datetime(2026, 2, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 1, tzinfo=timezone.utc)
    candles = [
        Candle(time=start, open=1, high=2, low=0.5, close=1.5, volume=1),
        Candle(time=start.replace(day=15), open=1, high=2, low=0.5, close=1.5, volume=1),
    ]
    h1 = candles

    coverage = MaximoBRProBacktester._coverage_for_timeframe(
        timeframe="M1",
        start=start,
        end=end,
        entry_candles=candles,
        htf_candles=h1,
    )

    assert coverage["sufficient"] is False


def test_lower_tf_confirmation_requires_supportive_micro_candle() -> None:
    entry_time = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    lower = [
        Candle(time=entry_time, open=10, high=10.4, low=9.8, close=10.35, volume=1),
        Candle(time=entry_time.replace(minute=1), open=10.35, high=10.42, low=10.1, close=10.2, volume=1),
    ]
    ok = MaximoBRProBacktester._lower_tf_confirmation_ok(
        index=0,
        entry_candles=[Candle(time=entry_time, open=10, high=10.5, low=9.7, close=10.3, volume=1)],
        lower_candles=lower,
        lower_ranges=[(0, 2)],
        direction="buy",
    )
    assert ok is True


def test_order_block_zones_detect_bearish_displacement_after_bullish_candle() -> None:
    candles = [
        Candle(time=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc), open=10.0, high=10.5, low=9.9, close=10.4, volume=1),
        Candle(time=datetime(2026, 5, 1, 12, 15, tzinfo=timezone.utc), open=10.35, high=10.38, low=9.5, close=9.6, volume=1),
        Candle(time=datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc), open=9.6, high=9.8, low=9.4, close=9.5, volume=1),
    ]
    bearish, bullish = MaximoBRProBacktester._order_block_zones(candles, [0.5, 0.6, 0.6])
    assert bearish[1] is not None
    assert bearish[1].direction == "sell"
    assert bearish[1].low == 10.0
    assert bearish[1].high == 10.4
    assert bullish[1] is None


def test_trigger_candle_ok_accepts_directional_rejection() -> None:
    sell_candle = Candle(
        time=datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc),
        open=10.5,
        high=10.8,
        low=10.1,
        close=10.2,
        volume=1,
    )
    assert MaximoBRProBacktester._trigger_candle_ok(sell_candle, "sell") is True


def test_trade_management_moves_short_stop_to_breakeven_and_trails() -> None:
    backtester = MaximoBRProBacktester(Path("."), Path(".tmp_maximo_test"))
    profile = next(item for item in backtester.STRATEGY_PROFILES if item.code == "aggressive_guarded_v24")
    trade = OpenTrade(
        direction="sell",
        signal_index=1,
        activation_index=2,
        breakout_time=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        signal_time=datetime(2026, 5, 1, 12, 5, tzinfo=timezone.utc),
        entry_time=datetime(2026, 5, 1, 12, 10, tzinfo=timezone.utc),
        entry_price=100.0,
        stop_price=101.0,
        initial_stop_price=101.0,
        take_profit_price=98.7,
        support_resistance_level=100.5,
        trade_day=datetime(2026, 5, 1, tzinfo=timezone.utc).date(),
        risk_amount=1.0,
        score=90,
        body_ratio=0.6,
        distance_atr_ratio=0.3,
        retest_bars_waited=2,
        trend_aligned=True,
        retest_valid=True,
        reaction_valid=True,
        distance_valid=True,
    )
    candle = Candle(
        time=datetime(2026, 5, 1, 12, 15, tzinfo=timezone.utc),
        open=100.0,
        high=100.1,
        low=98.8,
        close=99.0,
        volume=1,
    )
    backtester._apply_trade_management(open_trade=trade, candle=candle, atr_value=0.5, profile=profile)
    assert trade.stop_price <= 100.0
