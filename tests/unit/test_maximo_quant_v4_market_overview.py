from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.core.config import reload_settings
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester, StrategyVariant
from src.trading.maximo_quant_v4_market_overview import MaximoQuantV4MarketOverviewEngine


@dataclass
class _Variant:
    code: str = "v56_aggressive_filtered_b"
    min_quant_score: int = 58


@dataclass
class _Session:
    code: str = "all"


class _FakeBridge:
    def __init__(self) -> None:
        self.last_bars_by_timeframe: dict[str, int] | None = None

    def read_market_snapshot(self, *, symbol: str, bars_by_timeframe: dict[str, int] | None = None) -> dict:
        self.last_bars_by_timeframe = bars_by_timeframe
        return {
            "symbol": symbol,
            "timeframes": {
                "M1": {"bars": 500, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": "2026-01-01T10:00:00+00:00"},
                "M5": {"bars": 5000, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": "2026-01-01T10:00:00+00:00"},
                "H1": {"bars": 2000, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": "2026-01-01T10:00:00+00:00"},
                "H4": {"bars": 1000, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": "2026-01-01T10:00:00+00:00"},
                "D1": {"bars": 500, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": "2026-01-01T10:00:00+00:00"},
            },
            "candles": {"M1": [], "M5": [], "H1": [], "H4": [], "D1": []},
        }


def test_market_overview_writes_outputs(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4MarketOverviewEngine(settings, bridge=bridge)

    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
    }
    engine._load_market_map = lambda: {"operable_situations": [], "risk_by_regime": []}  # type: ignore[method-assign]
    engine._analyze_snapshot = lambda **kwargs: {  # type: ignore[method-assign]
        "market_state": {
            "status": "ok",
            "market_regime": "NORMAL",
            "preferred_side": "BUY",
            "volatility_state": "normal",
            "hour_ny": 9,
            "buy_mtf_score": 72,
            "sell_mtf_score": 18,
            "quant_score": 80,
            "impulse_score": 65,
            "macro_bias": "BUY",
            "trend_bias": "BUY",
            "setup_bias": "BUY",
            "local_bias": "BUY",
        },
        "knowledge_alignment": {
            "matched_context_count": 2,
            "support_score": 0.61,
            "harmony": {
                "harmony_score": 0.74,
                "operating_posture": "aligned",
                "narrative": ["Todo encaja."],
            },
            "top_matching_contexts": [
                {
                    "strategy_family": "OB Rejection",
                    "market_regime": "trend",
                    "operability_label": "operable",
                    "score": 0.71,
                }
            ],
            "risk_guidance": {"market_regime": "trend", "average_risk_percent": 0.5},
        },
        "signal": {
            "direction": "buy",
            "setup_type": "AGG",
            "entry_kind": "market",
            "entry_price": 2300.0,
            "stop_price": 2298.0,
            "target_price": 2302.3,
            "confidence": 68,
            "selected_rr": 1.15,
        },
        "decision": {
            "action": "EXECUTE",
            "confidence": 0.66,
            "allowed_to_trade_now": True,
            "risk_mode": "normal",
            "watchlist_active": False,
            "setup_maturity": 88.0,
            "rationale": ["Hay señal válida."],
            "critical_blocks": [],
            "soft_flags": [],
            "blockers": [],
        },
    }

    result = engine.run(symbol="XAUUSDm")

    assert result["action"] == "EXECUTE"
    assert result["harmony_score"] == 0.74
    assert bridge.last_bars_by_timeframe == {"M1": 500, "M5": 5000, "H1": 2000, "H4": 1000, "D1": 500}
    assert engine.latest_json_path.exists()
    assert engine.latest_md_path.exists()
    assert engine.decision_log_path.exists()


def test_market_clarity_builds_sell_zone_and_trigger_plan() -> None:
    alignment = MaximoQuantV4MarketOverviewEngine._build_timeframe_alignment(
        daily_bias="SELL",
        macro_bias="SELL",
        trend_bias="SELL",
        setup_bias="SELL",
        local_bias="SELL",
        day_bias="SELL",
    )
    candle = type("Candle", (), {"close": 4500.0})()

    clarity = MaximoQuantV4MarketOverviewEngine._build_market_clarity(
        side="SELL",
        timeframe_alignment=alignment,
        candle=candle,
        atr_value=10.0,
        ema_fast_value=4505.0,
        range_high=4520.0,
        range_low=4480.0,
        market_regime="EXPANSION",
        volatility_state="expansion",
        liquidity_quality_buy=False,
        liquidity_quality_sell=True,
        continuation_quality_buy="weak",
        continuation_quality_sell="strong",
        quant_score=85,
        impulse_score=80,
    )

    assert clarity["selected_side"] == "SELL"
    assert clarity["expected_entry_zone"]["side"] == "SELL"
    assert clarity["entry_trigger_plan"]["compact_sl_reference"] > clarity["expected_entry_zone"]["to"]
    assert "Disparar SELL" in clarity["entry_trigger_plan"]["fire_when"]


def test_preferred_side_promotes_high_clarity_neutral_mtf() -> None:
    result = MaximoQuantV4MarketOverviewEngine._resolve_preferred_side_from_clarity(
        preferred_side="NEUTRAL",
        market_clarity={
            "selected_side": "SELL",
            "clarity_score": 75.8,
            "timeframe_alignment": {"alignment_score": 0.5652},
            "expected_entry_zone": {"in_zone_now": True},
        },
    )

    assert result["preferred_side"] == "SELL"
    assert result["source"] == "market_clarity_mtf_zone"


def test_preferred_side_stays_neutral_when_clarity_is_not_actionable() -> None:
    result = MaximoQuantV4MarketOverviewEngine._resolve_preferred_side_from_clarity(
        preferred_side="NEUTRAL",
        market_clarity={
            "selected_side": "SELL",
            "clarity_score": 69.9,
            "timeframe_alignment": {"alignment_score": 0.5652},
            "expected_entry_zone": {"in_zone_now": True},
        },
    )

    assert result["preferred_side"] == "NEUTRAL"
    assert result["source"] == "neutral_wait"


def test_decide_action_stands_aside_on_chop_and_neutral() -> None:
    settings = reload_settings({"DATA_DIR": "C:/temp/botextrator-market-overview"})
    engine = MaximoQuantV4MarketOverviewEngine(settings, bridge=_FakeBridge())
    decision = engine._decide_action(
        market_state={
            "status": "ok",
            "preferred_side": "NEUTRAL",
            "allowed_hour_by_strategy": False,
            "market_regime": "CHOP",
            "quant_score": 40,
            "candidate_setups": {},
        },
        knowledge_alignment={
            "support_score": 0.1,
            "harmony": {
                "harmony_score": 0.1,
                "operating_posture": "defensive",
                "narrative": [],
            },
            "top_matching_contexts": [],
        },
        strategy_variant=_Variant(),
        signal=None,
    )

    assert decision["action"] == "BLOCKED"
    assert "chop_regime" in decision["blockers"]
    assert "defensive_knowledge_posture" in decision["blockers"]


def test_overlay_strategy_variant_from_snapshot_uses_snapshot_hours() -> None:
    variant = StrategyVariant(
        code="v56_aggressive_filtered_b",
        label="Static",
        allowed_hours_ny={1, 4, 5, 9, 15, 19},
    )

    updated = MaximoQuantV4MarketOverviewEngine._overlay_strategy_variant_from_snapshot(
        strategy_variant=variant,
        snapshot={
            "parameters": {
                "allowed_hours_ny": [1, 4, 5, 9, 10, 11, 12, 13, 14, 15, 19],
                "min_quant_score": 58,
            }
        },
    )

    assert updated.allowed_hours_ny == {1, 4, 5, 9, 10, 11, 12, 13, 14, 15, 19}


def test_rd_session_windows_allow_london_and_new_york_minutes() -> None:
    snapshot = {
        "parameters": {
            "allowed_session_windows_rd": [
                {"name": "london", "start": "03:00", "end": "05:00"},
                {"name": "new_york", "start": "08:00", "end": "11:30"},
            ]
        }
    }

    assert MaximoQuantV4MarketOverviewEngine._allowed_by_session_windows_rd(
        datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
        strategy_snapshot=snapshot,
    )
    assert MaximoQuantV4MarketOverviewEngine._allowed_by_session_windows_rd(
        datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        strategy_snapshot=snapshot,
    )
    assert MaximoQuantV4MarketOverviewEngine._allowed_by_session_windows_rd(
        datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        strategy_snapshot=snapshot,
    )
    assert MaximoQuantV4MarketOverviewEngine._allowed_by_session_windows_rd(
        datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc),
        strategy_snapshot=snapshot,
    )
    assert not MaximoQuantV4MarketOverviewEngine._allowed_by_session_windows_rd(
        datetime(2026, 6, 1, 15, 31, tzinfo=timezone.utc),
        strategy_snapshot=snapshot,
    )


def test_rd_session_tags_use_configured_windows() -> None:
    snapshot = {
        "parameters": {
            "allowed_session_windows_rd": [
                {"name": "london", "start": "03:00", "end": "05:00"},
                {"name": "new_york", "start": "08:00", "end": "11:30"},
            ]
        }
    }

    assert MaximoQuantV4MarketOverviewEngine._session_tags_for_time(
        datetime(2026, 6, 1, 7, 30, tzinfo=timezone.utc),
        strategy_snapshot=snapshot,
    ) == ["london"]
    assert MaximoQuantV4MarketOverviewEngine._session_tags_for_time(
        datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
        strategy_snapshot=snapshot,
    ) == ["new_york", "ny_am"]


def test_classifies_aggressive_ob_rejection_watch_without_institutional_requirements() -> None:
    families = MaximoQuantV4MarketOverviewEngine._classify_ob_rejection_families(
        backtester=MaximoMTFQuantV4Backtester,
        index=4,
        highs=[10.0, 10.4, 10.2, 10.1, 10.05],
        lows=[9.7, 9.8, 9.75, 9.72, 9.2],
        candle_open=10.0,
        candle_close=9.35,
        body_pct=72.0,
        close_power_buy=0.12,
        close_power_sell=0.91,
        velocity=0.9,
        atr_ratio=0.92,
        range_ratio=1.1,
        local_bull=False,
        local_bear=True,
        preferred_side="SELL",
        market_regime="NORMAL",
        quant_score=80,
        impulse_score=75,
        candidate_setups={"buy_a_plus": False, "sell_a_plus": False, "buy_agg": False, "sell_agg": False},
        bull_disp_agg=False,
        bear_disp_agg=True,
        liquidity_quality_buy=False,
        liquidity_quality_sell=False,
        pullback_buy=False,
        pullback_sell=False,
        vol_ok=False,
        compression_ok=True,
    )

    assert families["active_family"] == "OB_REJECTION_AGGRESSIVE_WATCH"
    assert families["aggressive"]["active"] is True
    assert families["aggressive"]["allows_normal_risk_directly"] is False


def test_classifies_institutional_ob_rejection_without_changing_premium_candidate() -> None:
    families = MaximoQuantV4MarketOverviewEngine._classify_ob_rejection_families(
        backtester=MaximoMTFQuantV4Backtester,
        index=4,
        highs=[10.0, 10.4, 10.2, 10.1, 10.05],
        lows=[9.7, 9.8, 9.75, 9.72, 9.2],
        candle_open=10.0,
        candle_close=9.35,
        body_pct=72.0,
        close_power_buy=0.12,
        close_power_sell=0.91,
        velocity=0.9,
        atr_ratio=0.92,
        range_ratio=1.1,
        local_bull=False,
        local_bear=True,
        preferred_side="SELL",
        market_regime="EXPANSION",
        quant_score=100,
        impulse_score=100,
        candidate_setups={"buy_a_plus": False, "sell_a_plus": False, "buy_agg": False, "sell_agg": True},
        bull_disp_agg=False,
        bear_disp_agg=True,
        liquidity_quality_buy=False,
        liquidity_quality_sell=True,
        pullback_buy=False,
        pullback_sell=True,
        vol_ok=True,
        compression_ok=True,
    )

    assert families["active_family"] == "OB_REJECTION_INSTITUTIONAL_EXECUTE"
    assert families["institutional"]["active"] is True
    assert families["institutional"]["candidate_setups"]["sell_agg"] is True


def test_sensei_manual_bias_detects_bearish_liquidity_bms_displacement() -> None:
    families = MaximoQuantV4MarketOverviewEngine._classify_ob_rejection_families(
        backtester=MaximoMTFQuantV4Backtester,
        index=9,
        opens=[99.5, 99.7, 99.4, 99.6, 99.8, 99.5, 99.3, 99.0, 98.8, 98.4],
        closes=[99.7, 99.4, 99.6, 99.8, 99.5, 99.3, 99.0, 98.8, 98.4, 97.2],
        highs=[100.0, 100.05, 99.8, 100.02, 100.25, 99.7, 99.4, 99.2, 98.9, 98.5],
        lows=[99.1, 99.2, 99.0, 99.15, 99.3, 98.9, 98.5, 98.2, 97.9, 97.0],
        candle_open=98.4,
        candle_close=97.2,
        body_pct=72.0,
        close_power_buy=0.08,
        close_power_sell=0.88,
        velocity=0.95,
        atr_ratio=1.2,
        range_ratio=1.3,
        local_bull=False,
        local_bear=True,
        preferred_side="SELL",
        market_regime="EXPANSION",
        quant_score=90,
        impulse_score=86,
        candidate_setups={"buy_a_plus": False, "sell_a_plus": False, "buy_agg": False, "sell_agg": False},
        bull_disp_agg=False,
        bear_disp_agg=False,
        liquidity_quality_buy=False,
        liquidity_quality_sell=False,
        pullback_buy=False,
        pullback_sell=False,
        vol_ok=True,
        compression_ok=True,
        candle_high=98.5,
        candle_low=97.0,
        next_open=97.1,
        atr_value=1.0,
    )

    manual_bias = families["manual_bias"]
    candidate = families["aggressive"]["reduced_signal_candidate"]

    assert families["active_family"] == "OB_REJECTION_AGGRESSIVE_WATCH"
    assert manual_bias["active"] is True
    assert manual_bias["side"] == "SELL"
    assert manual_bias["checks"]["sell_liquidity"] is True
    assert candidate["signal_type"] == "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL"
    assert candidate["selected_rr"] == 2.0


def test_sensei_manual_bias_does_not_flip_against_explicit_preferred_side() -> None:
    families = MaximoQuantV4MarketOverviewEngine._classify_ob_rejection_families(
        backtester=MaximoMTFQuantV4Backtester,
        index=9,
        opens=[100.5, 100.3, 100.4, 100.2, 100.1, 100.4, 100.6, 100.9, 101.1, 101.4],
        closes=[100.3, 100.4, 100.2, 100.1, 100.4, 100.6, 100.9, 101.1, 101.4, 102.6],
        highs=[101.0, 100.8, 100.9, 100.7, 100.6, 100.9, 101.2, 101.5, 101.8, 102.8],
        lows=[100.0, 99.95, 100.1, 99.98, 99.75, 100.0, 100.4, 100.7, 101.0, 101.2],
        candle_open=101.4,
        candle_close=102.6,
        body_pct=72.0,
        close_power_buy=0.88,
        close_power_sell=0.08,
        velocity=0.95,
        atr_ratio=1.2,
        range_ratio=1.3,
        local_bull=True,
        local_bear=False,
        preferred_side="SELL",
        market_regime="EXPANSION",
        quant_score=90,
        impulse_score=86,
        candidate_setups={"buy_a_plus": False, "sell_a_plus": False, "buy_agg": False, "sell_agg": False},
        bull_disp_agg=False,
        bear_disp_agg=False,
        liquidity_quality_buy=False,
        liquidity_quality_sell=False,
        pullback_buy=False,
        pullback_sell=False,
        vol_ok=True,
        compression_ok=True,
        candle_high=102.8,
        candle_low=101.2,
        next_open=102.7,
        atr_value=1.0,
    )

    assert families["manual_bias"]["active"] is False
    assert families["aggressive"]["side"] != "BUY"
