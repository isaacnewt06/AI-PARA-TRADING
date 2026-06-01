from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.trading.blueprint_backtester import Candle
from src.trading.maximo_quant_v4_backtester import (
    MaximoMTFQuantV4Backtester,
    PendingOrder,
)


def test_session_filter_uses_new_york_windows() -> None:
    london_time = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)  # 08:00 NY
    ny_am_time = datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc)  # 14:00 NY
    other_time = datetime(2026, 5, 1, 22, 0, tzinfo=timezone.utc)  # 18:00 NY

    london_variant = MaximoMTFQuantV4Backtester.SESSION_VARIANTS[1]
    ny_variant = MaximoMTFQuantV4Backtester.SESSION_VARIANTS[2]

    assert MaximoMTFQuantV4Backtester._session_allowed(london_time, london_variant) is True
    assert MaximoMTFQuantV4Backtester._session_allowed(ny_am_time, london_variant) is False
    assert MaximoMTFQuantV4Backtester._session_allowed(ny_am_time, ny_variant) is True
    assert MaximoMTFQuantV4Backtester._session_allowed(other_time, ny_variant) is False


def test_resolve_rr_uses_expansion_bonus() -> None:
    backtester = MaximoMTFQuantV4Backtester(Path("."), Path(".tmp_quant_v4"))

    assert backtester._resolve_rr(is_a=True, market_regime="EXPANSION", quant_score=90, impulse_score=80) == 1.75
    assert backtester._resolve_rr(is_a=False, market_regime="CHOP", quant_score=40, impulse_score=40) == 1.05
    assert backtester._resolve_rr(is_a=True, market_regime="NORMAL", quant_score=70, impulse_score=65) == 1.45


def test_try_fill_limit_order_requires_touch() -> None:
    backtester = MaximoMTFQuantV4Backtester(Path("."), Path(".tmp_quant_v4"))
    pending = PendingOrder(
        direction="buy",
        setup_type="A+",
        signal_index=5,
        signal_time=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        desired_entry=100.0,
        stop_price=99.0,
        target_price=101.45,
        risk_per_unit=1.0,
        selected_rr=1.45,
        quant_score=80,
        impulse_score=75,
        buy_mtf_score=82,
        sell_mtf_score=18,
        confidence=78,
        market_regime="EXPANSION",
        expires_index=8,
    )

    miss = Candle(time=datetime(2026, 5, 1, 12, 5, tzinfo=timezone.utc), open=100.5, high=100.8, low=100.1, close=100.7, volume=1)
    hit = Candle(time=datetime(2026, 5, 1, 12, 10, tzinfo=timezone.utc), open=100.2, high=100.6, low=99.8, close=100.4, volume=1)

    assert backtester._try_fill_limit_order(pending, miss) is None
    filled = backtester._try_fill_limit_order(pending, hit)
    assert filled is not None
    assert filled.entry_price == 100.0
    assert filled.stop_price == 99.0


def test_context_pack_marks_bullish_context_when_emas_align() -> None:
    backtester = MaximoMTFQuantV4Backtester(Path("."), Path(".tmp_quant_v4"))
    candles = [
        Candle(time=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=index), open=100 + index, high=101 + index, low=99 + index, close=100.5 + index, volume=1)
        for index in range(90)
    ]

    pack = backtester._context_pack(candles)

    assert pack["rows"][-1]["bull"] is True
    assert pack["rows"][-1]["bear"] is False


def test_variant_hour_filter_blocks_excluded_hour() -> None:
    variant = next(item for item in MaximoMTFQuantV4Backtester.STRATEGY_VARIANTS if item.code == "a_plus_focus_v41")
    assert MaximoMTFQuantV4Backtester._hour_allowed(9, variant) is True
    assert MaximoMTFQuantV4Backtester._hour_allowed(8, variant) is False


def test_variant_allows_setup_requires_preferred_side() -> None:
    variant = next(item for item in MaximoMTFQuantV4Backtester.STRATEGY_VARIANTS if item.code == "aligned_v41")
    assert MaximoMTFQuantV4Backtester._variant_allows_setup(
        strategy_variant=variant,
        direction="buy",
        setup_type="A+",
        signal_hour_ny=9,
        preferred_side="BUY",
        market_regime="NORMAL",
        quant_score=70,
        impulse_score=60,
        recent_compression=True,
        quant_expansion_ok=True,
        atr_ratio=1.0,
        range_ratio=1.0,
        current_state=True,
    ) is True
    assert MaximoMTFQuantV4Backtester._variant_allows_setup(
        strategy_variant=variant,
        direction="buy",
        setup_type="A+",
        signal_hour_ny=9,
        preferred_side="SELL",
        market_regime="NORMAL",
        quant_score=70,
        impulse_score=60,
        recent_compression=True,
        quant_expansion_ok=True,
        atr_ratio=1.0,
        range_ratio=1.0,
        current_state=True,
    ) is False


def test_variant_allows_setup_rejects_chop_when_configured() -> None:
    variant = next(item for item in MaximoMTFQuantV4Backtester.STRATEGY_VARIANTS if item.code == "hour_clean_trend_v44")
    assert MaximoMTFQuantV4Backtester._variant_allows_setup(
        strategy_variant=variant,
        direction="sell",
        setup_type="A+",
        signal_hour_ny=14,
        preferred_side="SELL",
        market_regime="CHOP",
        quant_score=70,
        impulse_score=60,
        recent_compression=True,
        quant_expansion_ok=True,
        atr_ratio=1.0,
        range_ratio=1.0,
        current_state=True,
    ) is False


def test_refined_prime_hours_rejects_normal_ny_window() -> None:
    variant = next(item for item in MaximoMTFQuantV4Backtester.STRATEGY_VARIANTS if item.code == "prime_hours_refined_v46")
    assert MaximoMTFQuantV4Backtester._variant_allows_setup(
        strategy_variant=variant,
        direction="buy",
        setup_type="AGG",
        signal_hour_ny=14,
        preferred_side="BUY",
        market_regime="NORMAL",
        quant_score=70,
        impulse_score=60,
        recent_compression=True,
        quant_expansion_ok=True,
        atr_ratio=1.0,
        range_ratio=1.0,
        current_state=True,
    ) is False


def test_volatility_variant_requires_expansion_and_valid_range() -> None:
    variant = next(item for item in MaximoMTFQuantV4Backtester.STRATEGY_VARIANTS if item.code == "volatility_confirmed_v50")
    assert MaximoMTFQuantV4Backtester._variant_allows_setup(
        strategy_variant=variant,
        direction="buy",
        setup_type="AGG",
        signal_hour_ny=9,
        preferred_side="BUY",
        market_regime="EXPANSION",
        quant_score=72,
        impulse_score=68,
        recent_compression=True,
        quant_expansion_ok=True,
        atr_ratio=1.05,
        range_ratio=1.10,
        current_state=True,
    ) is True
    assert MaximoMTFQuantV4Backtester._variant_allows_setup(
        strategy_variant=variant,
        direction="buy",
        setup_type="AGG",
        signal_hour_ny=9,
        preferred_side="BUY",
        market_regime="EXPANSION",
        quant_score=72,
        impulse_score=68,
        recent_compression=True,
        quant_expansion_ok=False,
        atr_ratio=0.80,
        range_ratio=0.85,
        current_state=True,
    ) is False
    assert MaximoMTFQuantV4Backtester._variant_allows_setup(
        strategy_variant=variant,
        direction="buy",
        setup_type="AGG",
        signal_hour_ny=9,
        preferred_side="BUY",
        market_regime="EXPANSION",
        quant_score=72,
        impulse_score=68,
        recent_compression=True,
        quant_expansion_ok=True,
        atr_ratio=1.10,
        range_ratio=2.20,
        current_state=True,
    ) is False


def test_prime_hours_variant_only_allows_selected_hours() -> None:
    variant = next(item for item in MaximoMTFQuantV4Backtester.STRATEGY_VARIANTS if item.code == "prime_hours_v45")
    assert MaximoMTFQuantV4Backtester._hour_allowed(9, variant) is True
    assert MaximoMTFQuantV4Backtester._hour_allowed(10, variant) is False


def test_variant_allows_direction_and_setup_type_filters() -> None:
    variant = next(item for item in MaximoMTFQuantV4Backtester.STRATEGY_VARIANTS if item.code == "aligned_v41")
    variant.allowed_directions = {"buy"}
    variant.allowed_setup_types = {"AGG"}
    try:
        assert MaximoMTFQuantV4Backtester._variant_allows_setup(
            strategy_variant=variant,
            direction="buy",
            setup_type="AGG",
            signal_hour_ny=9,
            preferred_side="BUY",
            market_regime="NORMAL",
            quant_score=70,
            impulse_score=60,
            recent_compression=True,
            quant_expansion_ok=True,
            atr_ratio=1.0,
            range_ratio=1.0,
            current_state=True,
        ) is True
        assert MaximoMTFQuantV4Backtester._variant_allows_setup(
            strategy_variant=variant,
            direction="sell",
            setup_type="AGG",
            signal_hour_ny=9,
            preferred_side="SELL",
            market_regime="NORMAL",
            quant_score=70,
            impulse_score=60,
            recent_compression=True,
            quant_expansion_ok=True,
            atr_ratio=1.0,
            range_ratio=1.0,
            current_state=True,
        ) is False
        assert MaximoMTFQuantV4Backtester._variant_allows_setup(
            strategy_variant=variant,
            direction="buy",
            setup_type="A+",
            signal_hour_ny=9,
            preferred_side="BUY",
            market_regime="NORMAL",
            quant_score=70,
            impulse_score=60,
            recent_compression=True,
            quant_expansion_ok=True,
            atr_ratio=1.0,
            range_ratio=1.0,
            current_state=True,
        ) is False
    finally:
        variant.allowed_directions = None
        variant.allowed_setup_types = None
