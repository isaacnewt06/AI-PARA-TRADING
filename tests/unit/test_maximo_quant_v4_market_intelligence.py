from __future__ import annotations

import json
from pathlib import Path

from src.core.config import reload_settings
from src.trading.maximo_quant_v4_market_intelligence import MaximoQuantV4MarketIntelligenceEngine


class _FakeOverviewEngine:
    def __init__(
        self,
        *,
        action: str = "EXECUTE",
        preferred_side: str | None = "SELL",
        signal: dict | None = None,
        confidence: float = 0.71,
        setup_maturity: float = 87.0,
        operational_family: str = "NONE",
    ) -> None:
        self.action = action
        self.preferred_side = preferred_side
        self.signal = signal
        self.confidence = confidence
        self.setup_maturity = setup_maturity
        self.operational_family = operational_family

    def run_detailed(self, *, symbol: str) -> dict:
        market_state = {
            "market_regime": "NORMAL",
            "preferred_side": self.preferred_side,
            "operational_family": self.operational_family,
            "ob_rejection_families": {
                "active_family": self.operational_family,
                "aggressive": {
                    "active": self.operational_family == "OB_REJECTION_AGGRESSIVE_WATCH",
                    "side": self.preferred_side or "BUY",
                    "checks": {
                        "strong_bullish_rejection": (self.preferred_side or "BUY") == "BUY",
                        "strong_bearish_rejection": self.preferred_side == "SELL",
                        "partial_bull_displacement": (self.preferred_side or "BUY") == "BUY",
                        "partial_bear_displacement": self.preferred_side == "SELL",
                        "micro_bos_buy": (self.preferred_side or "BUY") == "BUY",
                        "micro_bos_sell": self.preferred_side == "SELL",
                        "continuation_momentum_buy": (self.preferred_side or "BUY") == "BUY",
                        "continuation_momentum_sell": self.preferred_side == "SELL",
                    },
                    "reduced_signal_candidate": {
                        "direction": (self.preferred_side or "BUY").lower(),
                        "sl_logical_available": True,
                        "rr_evaluable": True,
                    },
                },
                "institutional": {
                    "active": self.operational_family == "OB_REJECTION_INSTITUTIONAL_EXECUTE",
                    "side": self.preferred_side or "NEUTRAL",
                },
            },
            "atr_ratio": 0.95,
            "range_ratio": 0.92,
            "impulse_score": 64,
            "quant_score": 78,
            "macro_bias": "SELL" if self.preferred_side == "SELL" else "BUY" if self.preferred_side == "BUY" else "NEUTRAL",
            "trend_bias": "SELL" if self.preferred_side == "SELL" else "BUY" if self.preferred_side == "BUY" else "NEUTRAL",
            "setup_bias": "SELL" if self.preferred_side == "SELL" else "BUY" if self.preferred_side == "BUY" else "NEUTRAL",
        }
        return {
            "runtime": {
                "strategy_variant": type("Variant", (), {"code": "v56_aggressive_filtered_b"})(),
                "session_variant": type("Session", (), {"code": "all"})(),
            },
            "analysis": {
                "market_state": market_state,
                "signal": self.signal,
                "knowledge_alignment": {
                    "harmony": {
                        "harmony_score": 0.72 if self.action == "EXECUTE" else 0.58,
                        "operating_posture": "aligned" if self.action == "EXECUTE" else "selective",
                        "dominant_family": "OB Rejection",
                    }
                },
                "decision": {
                    "action": self.action,
                    "confidence": self.confidence,
                    "risk_mode": "normal" if self.action == "EXECUTE" else "reduced",
                    "watchlist_active": self.action == "WATCH",
                    "setup_maturity": self.setup_maturity,
                    "critical_blocks": [],
                    "soft_flags": [],
                    "blockers": [] if self.action != "BLOCKED" else ["invalid_market_context"],
                    "rationale": ["Hay señal válida." if self.action == "EXECUTE" else "Setup en desarrollo."],
                },
            },
        }


def _allow_events(**kwargs) -> dict:
    return {
        "action": "allow",
        "highest_active_impact": "none",
        "highest_upcoming_impact": "none",
        "active_events": [],
        "upcoming_events": [],
        "sync_status": {"status": "ok"},
    }


def test_market_intelligence_blocks_for_high_impact_event(tmp_path: Path) -> None:
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "ECONOMIC_CALENDAR_AUTO_SYNC": "false",
        }
    )
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine()  # type: ignore[assignment]
    engine.calendar.evaluate_for_symbol = lambda **kwargs: {  # type: ignore[method-assign]
        "action": "block",
        "highest_active_impact": "high",
        "highest_upcoming_impact": "high",
        "active_events": [{"title": "US CPI"}],
        "upcoming_events": [],
        "sync_status": {"status": "ok"},
    }

    result = engine.run(symbol="XAUUSDm")

    assert result["action"] == "BLOCKED"
    assert engine.latest_json_path.exists()
    assert engine.latest_md_path.exists()
    content = json.loads(engine.latest_json_path.read_text(encoding="utf-8"))
    assert "event_risk" in content


def test_market_intelligence_allows_operate_when_clear(tmp_path: Path) -> None:
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "ECONOMIC_CALENDAR_AUTO_SYNC": "false",
        }
    )
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine(
        action="EXECUTE",
        preferred_side="SELL",
        signal={"direction": "sell", "setup_type": "AGG", "confidence": 68},
        setup_maturity=87.0,
    )  # type: ignore[assignment]
    engine.events_path.write_text(json.dumps({"events": []}), encoding="utf-8")
    engine.calendar = engine.calendar.__class__(engine.events_path)

    result = engine.run(symbol="XAUUSDm")

    assert result["action"] == "EXECUTE"
    assert result["event_action"] == "allow"
    assert result["harmony_score"] == 0.72
    assert result["watch_trigger"] is None


def test_watch_with_sell_generates_bearish_trigger(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine(action="WATCH", preferred_side="SELL", signal=None, confidence=0.68, setup_maturity=68.0)  # type: ignore[assignment]
    engine.calendar.evaluate_for_symbol = _allow_events  # type: ignore[method-assign]

    result = engine.run(symbol="XAUUSDm")

    assert result["action"] == "WATCH"
    assert result["watch_trigger"] is not None
    assert result["watch_trigger"]["side"] == "SELL"
    assert result["watch_trigger"]["trigger_type"] == "bearish_confirmation"


def test_watch_with_buy_generates_bullish_trigger(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine(action="WATCH", preferred_side="BUY", signal=None, confidence=0.69, setup_maturity=70.0)  # type: ignore[assignment]
    engine.calendar.evaluate_for_symbol = _allow_events  # type: ignore[method-assign]

    result = engine.run(symbol="XAUUSDm")

    assert result["action"] == "WATCH"
    assert result["watch_trigger"] is not None
    assert result["watch_trigger"]["side"] == "BUY"
    assert result["watch_trigger"]["trigger_type"] == "bullish_confirmation"
    comparison = result["watch_trigger"]["pattern_projection"]["side_probability_comparison"]
    assert set(comparison["sides"]) == {"BUY", "SELL"}
    assert comparison["selected_side"] in {"BUY", "SELL", "NEUTRAL"}
    assert comparison["sides"]["BUY"]["confirmation_needed"]
    assert comparison["sides"]["SELL"]["confirmation_needed"]
    professional = result["watch_trigger"]["pattern_projection"]["professional_decision_matrix"]
    assert professional["selected_side"] in {"BUY", "SELL", "NEUTRAL"}
    assert "management_plan" in professional
    assert "emergency_exit" in professional["management_plan"]
    assert "trailing_plan" in professional["management_plan"]
    assert "course_pattern_memory" in professional
    assert "cool_learning_memory" in professional


def test_blocked_does_not_generate_operational_watch_trigger(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine(action="BLOCKED", preferred_side="SELL", signal=None, confidence=0.22, setup_maturity=30.0)  # type: ignore[assignment]
    engine.calendar.evaluate_for_symbol = _allow_events  # type: ignore[method-assign]

    result = engine.run(symbol="XAUUSDm")

    assert result["action"] == "BLOCKED"
    assert result["watch_trigger"] is None


def test_execute_does_not_depend_on_watch_trigger(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine(
        action="EXECUTE",
        preferred_side="BUY",
        signal={"direction": "buy", "setup_type": "A+", "confidence": 82},
        confidence=0.84,
        setup_maturity=92.0,
    )  # type: ignore[assignment]
    engine.calendar.evaluate_for_symbol = _allow_events  # type: ignore[method-assign]

    result = engine.run(symbol="XAUUSDm")

    assert result["action"] == "EXECUTE"
    assert result["watch_trigger"] is None


def test_watch_without_preferred_side_generates_neutral_observation_trigger(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine(action="WATCH", preferred_side=None, signal=None, confidence=0.63, setup_maturity=61.0)  # type: ignore[assignment]
    engine.calendar.evaluate_for_symbol = _allow_events  # type: ignore[method-assign]

    result = engine.run(symbol="XAUUSDm")

    assert result["action"] == "WATCH"
    assert result["watch_trigger"] is not None
    assert result["watch_trigger"]["side"] == "NEUTRAL"
    assert result["watch_trigger"]["trigger_type"] == "neutral_observation"


def test_aggressive_ob_watch_keeps_operational_family_in_trigger(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine(
        action="WATCH",
        preferred_side="SELL",
        signal=None,
        confidence=0.72,
        setup_maturity=72.0,
        operational_family="OB_REJECTION_AGGRESSIVE_WATCH",
    )  # type: ignore[assignment]
    engine.calendar.evaluate_for_symbol = _allow_events  # type: ignore[method-assign]

    result = engine.run(symbol="XAUUSDm")

    assert result["operational_family"] == "OB_REJECTION_AGGRESSIVE_WATCH"
    assert result["watch_trigger"]["setup_detected"] == "OB_REJECTION_AGGRESSIVE_WATCH"
    assert result["watch_trigger"]["operational_family"] == "OB_REJECTION_AGGRESSIVE_WATCH"


def test_watch_includes_learned_pattern_projection_for_near_miss(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    engine.overview_engine = _FakeOverviewEngine(
        action="WATCH",
        preferred_side=None,
        signal=None,
        confidence=0.73,
        setup_maturity=73.0,
        operational_family="OB_REJECTION_AGGRESSIVE_WATCH",
    )  # type: ignore[assignment]
    engine.calendar.evaluate_for_symbol = _allow_events  # type: ignore[method-assign]

    result = engine.run(symbol="XAUUSDm")

    projection = result["watch_trigger"]["pattern_projection"]
    assert projection["candidate_side"] == "BUY"
    assert projection["near_execute_watch"] is True
    assert projection["maturity_gap_to_execute"] == 2.0
    assert "conocimiento aprendido" in projection["interpretation"]
    assert "Learned Pattern Projection" in engine.latest_md_path.read_text(encoding="utf-8")


def test_historical_pattern_analogs_detect_favorable_buy_memory(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    candles: list[dict] = []

    def add_pattern(base: float, *, favorable: bool = True) -> None:
        for idx in range(12):
            open_price = base + idx * 0.5
            close_price = open_price + 0.35
            candles.append({"open": open_price, "high": close_price + 0.15, "low": open_price - 0.1, "close": close_price})
        for idx in range(8):
            close_price = base + 6.5 + idx * 0.45 if favorable else base + 5.5 - idx * 0.5
            candles.append({"open": close_price - 0.1, "high": close_price + 0.25, "low": close_price - 0.25, "close": close_price})

    add_pattern(100.0, favorable=True)
    add_pattern(120.0, favorable=True)
    add_pattern(140.0, favorable=False)
    for idx in range(12):
        open_price = 180.0 + idx * 0.5
        close_price = open_price + 0.35
        candles.append({"open": open_price, "high": close_price + 0.15, "low": open_price - 0.1, "close": close_price})

    analogs = engine._historical_pattern_analogs(
        snapshot={"candles": {"M5": candles}},
        side="BUY",
        dominant_family="OB Rejection",
        market_regime="NORMAL",
    )

    assert analogs["status"] == "available"
    assert analogs["matches_found"] >= 2
    assert analogs["favorable_count"] > analogs["failed_count"]
    assert analogs["bias"] in {"favorable", "mixed"}
    assert "Analogías M5 para BUY" in analogs["summary"]
    assert "pattern_variation_memory" in analogs


def test_historical_pattern_analogs_include_structural_variants(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    candles: list[dict] = []

    def add_variant(base: float) -> None:
        closes = [base, base + 3.0, base + 3.4, base + 3.8, base + 4.1, base + 4.4, base + 4.7, base + 5.0, base + 5.3, base + 5.6, base + 5.8, base + 6.0]
        for idx, close_price in enumerate(closes):
            open_price = close_price - (2.2 if idx == 1 else 0.18)
            candles.append({"open": open_price, "high": close_price + 0.25, "low": open_price - 0.2, "close": close_price})
        for idx in range(8):
            close_price = base + 6.2 + idx * 0.55
            candles.append({"open": close_price - 0.12, "high": close_price + 0.25, "low": close_price - 0.2, "close": close_price})

    add_variant(100.0)
    add_variant(120.0)
    for idx in range(20):
        price = 145.0 + (idx % 4) * 0.15
        candles.append({"open": price, "high": price + 0.25, "low": price - 0.25, "close": price + 0.05})
    for idx in range(12):
        open_price = 180.0 + idx * 0.45
        close_price = open_price + 0.32
        candles.append({"open": open_price, "high": close_price + 0.2, "low": open_price - 0.15, "close": close_price})

    analogs = engine._historical_pattern_analogs(
        snapshot={"candles": {"M5": candles}},
        side="BUY",
        dominant_family="OB Rejection",
        market_regime="NORMAL",
    )

    variation_memory = analogs["pattern_variation_memory"]
    assert analogs["status"] == "available"
    assert variation_memory["variant_matches_found"] > 0
    assert variation_memory["top_variant_matches"][0]["match_type"] == "structural_variant"
    assert "mismo patrón exacto" in variation_memory["interpretation"]


def test_side_probability_comparison_can_watch_sell_alternative(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    candles: list[dict] = []

    def add_sell_pattern(base: float, *, favorable: bool = True) -> None:
        for idx in range(12):
            open_price = base - idx * 0.5
            close_price = open_price - 0.35
            candles.append({"open": open_price, "high": open_price + 0.1, "low": close_price - 0.15, "close": close_price})
        for idx in range(8):
            close_price = base - 6.5 - idx * 0.45 if favorable else base - 5.5 + idx * 0.5
            candles.append({"open": close_price + 0.1, "high": close_price + 0.25, "low": close_price - 0.25, "close": close_price})

    add_sell_pattern(200.0, favorable=True)
    add_sell_pattern(180.0, favorable=True)
    add_sell_pattern(160.0, favorable=False)
    for idx in range(12):
        open_price = 130.0 - idx * 0.5
        close_price = open_price - 0.35
        candles.append({"open": open_price, "high": open_price + 0.1, "low": close_price - 0.15, "close": close_price})

    comparison = engine._side_probability_comparison(
        snapshot={"candles": {"M5": candles}},
        preferred_side="BUY",
        initial_candidate_side="BUY",
        higher_timeframe_bias="NEUTRAL",
        dominant_family="OB Rejection",
        market_regime="NORMAL",
        setup_maturity=71.0,
        confidence=0.71,
        harmony_score=0.56,
        event_action="allow",
        volatility_state="tradable_normal",
        signal_detected=False,
    )

    assert set(comparison["sides"]) == {"BUY", "SELL"}
    assert comparison["sides"]["SELL"]["historical_analogs"]["status"] == "available"
    assert comparison["sides"]["SELL"]["confirmation_needed"]
    assert "SELL" in comparison["summary"]


def test_professional_decision_matrix_explains_liquidity_news_and_management(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    result = engine._professional_decision_matrix(
        side_probability_comparison={
            "selected_side": "BUY",
            "sides": {
                "BUY": {
                    "probability_to_confirm": 0.82,
                    "historical_analogs": {"bias": "favorable", "win_rate": 0.62, "failure_rate": 0.25},
                    "confirmation_needed": ["Cierre M5 alcista"],
                },
                "SELL": {
                    "probability_to_confirm": 0.48,
                    "historical_analogs": {"bias": "unfavorable", "win_rate": 0.2, "failure_rate": 0.55},
                    "confirmation_needed": ["Cierre M5 bajista"],
                },
            },
        },
        candidate_side="BUY",
        preferred_side="BUY",
        higher_timeframe_bias="BUY",
        market_state={
            "market_regime": "NORMAL",
            "expansion_subtype": "liquidity_sweep_expansion",
            "buy_mtf_score": 72,
            "sell_mtf_score": 31,
            "wick_rejection_pct_buy": 0.61,
            "ob_rejection_families": {
                "aggressive": {
                    "checks": {
                        "partial_bull_displacement": True,
                        "micro_bos_buy": True,
                        "continuation_momentum_buy": True,
                    }
                },
                "institutional": {
                    "checks": {
                        "liquidity_quality_buy": True,
                        "pullback_buy": True,
                    }
                },
            },
        },
        top_contexts=[{"strategy_family": "OB Rejection", "market_regime": "trend", "operability_label": "operable", "score": 0.81}],
        dominant_family="OB Rejection",
        operational_family="OB_REJECTION_AGGRESSIVE_WATCH",
        setup_maturity=81.0,
        confidence=0.82,
        harmony_score=0.66,
        event_action="allow",
        volatility_state="tradable_normal",
        signal_detected=True,
        missing_for_execute=[],
    )

    assert result["probability_quality"] == "alta"
    assert result["course_pattern_memory"]["dominant_family"] == "OB Rejection"
    assert result["side_assessments"]["BUY"]["liquidity_read"]["liquidity_sweep_or_grab"] is True
    assert "TP1" in result["management_plan"]["take_profit_plan"]
    assert "trailing" in result["management_plan"]["trailing_plan"]


def test_watch_projection_includes_cool_learning_memory(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    candles: list[dict] = []

    def add_pattern(base: float, *, favorable: bool = True) -> None:
        for idx in range(12):
            open_price = base + idx * 0.4
            close_price = open_price + 0.2
            candles.append({"open": open_price, "high": close_price + 0.1, "low": open_price - 0.1, "close": close_price})
        for idx in range(8):
            close_price = base + 5.0 + idx * 0.4 if favorable else base + 4.0 - idx * 0.35
            candles.append({"open": close_price - 0.1, "high": close_price + 0.2, "low": close_price - 0.2, "close": close_price})

    add_pattern(100.0, favorable=True)
    add_pattern(120.0, favorable=True)
    add_pattern(140.0, favorable=False)
    for idx in range(12):
        open_price = 180.0 + idx * 0.4
        close_price = open_price + 0.2
        candles.append({"open": open_price, "high": close_price + 0.1, "low": open_price - 0.1, "close": close_price})

    projection = engine._build_pattern_projection(
        preferred_side="BUY",
        higher_timeframe_bias="NEUTRAL",
        market_state={
            "market_regime": "NORMAL",
            "volatility_state": "normal",
            "ob_rejection_families": {
                "aggressive": {
                    "checks": {
                        "strong_bullish_rejection": True,
                        "partial_bull_displacement": True,
                        "micro_bos_buy": True,
                    }
                },
                "institutional": {"checks": {"liquidity_quality_buy": True}},
            },
        },
        knowledge_alignment={
            "harmony": {"dominant_family": "OB Rejection", "harmony_score": 0.62},
            "support_score": 0.58,
            "matched_context_count": 5,
            "top_matching_contexts": [{"strategy_family": "OB Rejection", "score": 0.7}],
        },
        setup_maturity=72.0,
        confidence=0.72,
        signal_detected=False,
        event_action="allow",
        volatility_state="tradable_normal",
        missing_for_execute=["Falta señal operativa confirmada."],
        snapshot={"candles": {"M5": candles}},
    )

    assert projection["cool_learning_memory"]["status"] == "available"
    assert projection["q_learning_memory"]["learning_method"] == "q_learning_inspired_action_value_memory"
    assert "course_alignment" in projection["cool_learning_memory"]
    assert "layer_synchronization" in projection["professional_decision_matrix"]
    assert "cool_learning_memory" in projection["professional_decision_matrix"]
    assert "q_learning_memory" in projection["professional_decision_matrix"]
    assert "Q-learning" in " ".join(projection["evidence"])


def test_watch_projection_reports_auto_selected_course_protocol(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    candles: list[dict] = []
    for base in (100.0, 120.0, 140.0, 180.0):
        for idx in range(12):
            open_price = base - idx * 0.4
            close_price = open_price - 0.2
            candles.append({"open": open_price, "high": open_price + 0.1, "low": close_price - 0.1, "close": close_price})
        for idx in range(8):
            close_price = base - 5.0 - idx * 0.35
            candles.append({"open": close_price + 0.1, "high": close_price + 0.2, "low": close_price - 0.2, "close": close_price})

    projection = engine._build_pattern_projection(
        preferred_side="SELL",
        higher_timeframe_bias="SELL",
        market_state={
            "market_regime": "NORMAL",
            "volatility_state": "normal",
            "allowed_hour_by_strategy": True,
            "ob_rejection_families": {
                "manual_bias": {
                    "active": True,
                    "side": "SELL",
                    "checks": {
                        "sell_liquidity": True,
                        "sell_micro_bos": True,
                        "sell_displacement": True,
                    },
                },
                "aggressive": {
                    "checks": {
                        "strong_bearish_rejection": True,
                        "partial_bear_displacement": True,
                        "micro_bos_sell": True,
                    }
                },
                "institutional": {"checks": {"liquidity_quality_sell": True}},
            },
        },
        knowledge_alignment={
            "harmony": {"dominant_family": "OB Rejection", "harmony_score": 0.68},
            "support_score": 0.68,
            "matched_context_count": 6,
            "top_matching_contexts": [
                {
                    "strategy_family": "OB Rejection",
                    "score": 0.82,
                    "top_confirmations": ["liquidity_sweep_or_grab", "BOS"],
                }
            ],
        },
        setup_maturity=74.0,
        confidence=0.74,
        signal_detected=False,
        event_action="allow",
        volatility_state="tradable_normal",
        missing_for_execute=["Falta señal operativa confirmada."],
        snapshot={"candles": {"M5": candles}},
    )

    course = projection["professional_decision_matrix"]["course_pattern_memory"]
    brain = projection["extracted_knowledge_operational_brain"]
    assert "SENSEI_MANUAL_BIAS_PROTOCOL" in course["auto_selected_protocols"]
    assert "Protocolos aprendidos auto-seleccionados" in " ".join(projection["pattern_matches"])
    assert brain["status"] == "primary_operational_brain"
    assert brain["role"] == "motor_principal_de_decision"
    assert brain["protocol_priority"] == "sensei_bias_high"
    assert "SENSEI_MANUAL_BIAS_PROTOCOL" in brain["auto_selected_protocols"]
    assert "manual/sensei_manual_bias_protocol.md" in " ".join(brain["source_files"])


def test_session_opportunity_scores_london_new_york_focus(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data"), "ECONOMIC_CALENDAR_AUTO_SYNC": "false"})
    engine = MaximoQuantV4MarketIntelligenceEngine(settings)
    projection = engine._build_pattern_projection(
        preferred_side="SELL",
        higher_timeframe_bias="SELL",
        market_state={
            "market_regime": "EXPANSION",
            "hour_ny": 9,
            "session_tags": ["new_york", "ny_am"],
            "volatility_state": "tradable_normal",
            "preferred_side": "SELL",
            "sell_mtf_score": 74,
            "buy_mtf_score": 28,
            "ob_rejection_families": {
                "aggressive": {
                    "checks": {
                        "strong_bearish_rejection": True,
                        "partial_bear_displacement": True,
                        "micro_bos_sell": True,
                    }
                },
                "institutional": {"checks": {"liquidity_quality_sell": True}},
            },
        },
        knowledge_alignment={
            "harmony": {"dominant_family": "OB Rejection", "harmony_score": 0.68},
            "support_score": 0.7,
            "matched_context_count": 8,
            "top_matching_contexts": [{"strategy_family": "OB Rejection", "score": 0.82}],
        },
        setup_maturity=74.0,
        confidence=0.74,
        signal_detected=False,
        event_action="allow",
        volatility_state="tradable_normal",
        missing_for_execute=["Falta señal operativa confirmada."],
        snapshot={"candles": {"M5": []}},
    )

    session = projection["professional_decision_matrix"]["session_opportunity"]
    assert session["status"] == "ny_am_focus"
    assert session["readiness"] in {"armed", "execute_ready"}
    assert "sesión" in " ".join(session["reasons"])
