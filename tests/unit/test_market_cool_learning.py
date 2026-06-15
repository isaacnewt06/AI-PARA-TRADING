from __future__ import annotations

from src.trading.market_cool_learning import MarketCoolLearningMemory


def test_cool_learning_memory_scores_buy_sell_wait_from_similar_states() -> None:
    candles: list[dict] = []

    def add_pattern(base: float, *, future: str) -> None:
        for idx in range(12):
            open_price = base + idx * 0.35
            close_price = open_price + 0.22
            candles.append({"open": open_price, "high": close_price + 0.12, "low": open_price - 0.08, "close": close_price})
        for idx in range(8):
            if future == "BUY":
                close_price = base + 4.5 + idx * 0.5
            elif future == "SELL":
                close_price = base + 4.5 - idx * 0.5
            else:
                close_price = base + 4.5 + (0.05 if idx % 2 else -0.05)
            candles.append({"open": close_price - 0.08, "high": close_price + 0.18, "low": close_price - 0.18, "close": close_price})

    add_pattern(100.0, future="BUY")
    add_pattern(120.0, future="BUY")
    add_pattern(140.0, future="SELL")
    add_pattern(160.0, future="WAIT")
    for idx in range(12):
        open_price = 190.0 + idx * 0.35
        close_price = open_price + 0.22
        candles.append({"open": open_price, "high": close_price + 0.12, "low": open_price - 0.08, "close": close_price})

    result = MarketCoolLearningMemory().evaluate(
        snapshot={"candles": {"M5": candles}},
        market_state={"volatility_state": "normal", "buy_mtf_score": 61, "sell_mtf_score": 42},
        dominant_family="OB Rejection",
        market_regime="NORMAL",
        preferred_side="BUY",
    )

    assert result["status"] == "available"
    assert result["sample_count"] > 0
    assert set(result["action_values"]) == {"BUY", "SELL", "WAIT"}
    assert set(result["q_values"]) == {"BUY", "SELL", "WAIT"}
    assert result["policy_action"] in {"BUY", "SELL", "WAIT"}
    assert result["q_policy_action"] == result["policy_action"]
    assert result["learning_method"] == "q_learning_inspired_action_value_memory"
    assert "Q-learning memory" in result["summary"]


def test_cool_learning_memory_handles_insufficient_data() -> None:
    result = MarketCoolLearningMemory().evaluate(
        snapshot={"candles": {"M5": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5}]}},
        market_state={},
        dominant_family="General",
        market_regime="NORMAL",
        preferred_side="NEUTRAL",
    )

    assert result["status"] == "insufficient_data"
    assert result["policy_action"] == "WAIT"
    assert result["q_policy_action"] == "WAIT"


def test_cool_learning_memory_aligns_course_steps_with_current_setup() -> None:
    candles: list[dict] = []
    for pattern in range(5):
        base = 100.0 + pattern * 30.0
        for idx in range(12):
            open_price = base + idx * 0.35
            close_price = open_price + 0.22
            candles.append({"open": open_price, "high": close_price + 0.12, "low": open_price - 0.08, "close": close_price})
        for idx in range(8):
            close_price = base + 4.5 + idx * 0.5
            candles.append({"open": close_price - 0.08, "high": close_price + 0.18, "low": close_price - 0.18, "close": close_price})
    for idx in range(12):
        open_price = 280.0 + idx * 0.35
        close_price = open_price + 0.22
        candles.append({"open": open_price, "high": close_price + 0.12, "low": open_price - 0.08, "close": close_price})

    result = MarketCoolLearningMemory().evaluate(
        snapshot={"candles": {"M5": candles}},
        market_state={
            "ob_rejection_families": {
                "aggressive": {
                    "checks": {
                        "strong_bullish_rejection": True,
                        "partial_bull_displacement": True,
                        "micro_bos_buy": True,
                        "continuation_momentum_buy": True,
                    }
                },
                "institutional": {"checks": {"liquidity_quality_buy": True}},
            }
        },
        dominant_family="OB Rejection",
        market_regime="NORMAL",
        preferred_side="BUY",
        course_context={
            "dominant_family": "OB Rejection",
            "harmony_score": 0.78,
            "support_score": 0.72,
            "matched_context_count": 8,
            "top_matching_contexts": [{"strategy_family": "OB Rejection", "score": 0.8}],
        },
    )

    assert result["status"] == "available"
    assert result["course_alignment"]["status"] == "aligned"
    assert result["course_alignment"]["course_recommended_action"] in {"BUY", "WAIT"}
    assert result["course_alignment"]["confirmations"]


def test_cool_learning_memory_detects_course_conflict() -> None:
    candles: list[dict] = []
    for pattern in range(5):
        base = 100.0 + pattern * 30.0
        for idx in range(12):
            open_price = base + idx * 0.35
            close_price = open_price + 0.22
            candles.append({"open": open_price, "high": close_price + 0.12, "low": open_price - 0.08, "close": close_price})
        for idx in range(8):
            close_price = base + 4.5 + idx * 0.5
            candles.append({"open": close_price - 0.08, "high": close_price + 0.18, "low": close_price - 0.18, "close": close_price})
    for idx in range(12):
        open_price = 280.0 + idx * 0.35
        close_price = open_price + 0.22
        candles.append({"open": open_price, "high": close_price + 0.12, "low": open_price - 0.08, "close": close_price})

    result = MarketCoolLearningMemory().evaluate(
        snapshot={"candles": {"M5": candles}},
        market_state={"ob_rejection_families": {"aggressive": {"checks": {}}, "institutional": {"checks": {}}}},
        dominant_family="OB Rejection",
        market_regime="NORMAL",
        preferred_side="SELL",
        course_context={
            "dominant_family": "OB Rejection",
            "harmony_score": 0.22,
            "support_score": 0.18,
            "matched_context_count": 1,
            "top_matching_contexts": [{"strategy_family": "OB Rejection", "score": 0.3}],
        },
    )

    assert result["course_alignment"]["status"] in {"weak", "conflict"}
    assert result["course_alignment"]["missing_steps"]


def test_cool_learning_auto_selects_sensei_protocol_from_market_state() -> None:
    result = MarketCoolLearningMemory._course_alignment(
        course_context={
            "dominant_family": "OB Rejection",
            "harmony_score": 0.7,
            "support_score": 0.68,
            "matched_context_count": 6,
            "top_matching_contexts": [
                {
                    "strategy_family": "OB Rejection",
                    "score": 0.82,
                    "top_entry_conditions": ["order_block_rejection"],
                    "top_confirmations": ["liquidity_sweep_or_grab", "BOS"],
                }
            ],
        },
        market_state={
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
        dominant_family="OB Rejection",
        market_regime="NORMAL",
        preferred_side="SELL",
        policy_action="SELL",
    )

    assert "SENSEI_MANUAL_BIAS_PROTOCOL" in result["auto_selected_protocols"]
    assert result["learned_protocol_profile"]["applicable"] is True
    assert result["course_score"] >= 0.68
    assert any("activado automáticamente" in item for item in result["confirmations"])


def test_cool_learning_does_not_let_q_policy_flip_course_bias_when_conflicting() -> None:
    result = MarketCoolLearningMemory._course_alignment(
        course_context={
            "dominant_family": "OB Rejection",
            "harmony_score": 0.7,
            "support_score": 0.68,
            "matched_context_count": 6,
            "top_matching_contexts": [{"strategy_family": "OB Rejection", "score": 0.82}],
        },
        market_state={
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
        dominant_family="OB Rejection",
        market_regime="NORMAL",
        preferred_side="SELL",
        policy_action="BUY",
    )

    assert result["status"] == "aligned"
    assert result["course_recommended_action"] == "SELL"
    assert any("Memoria historica favorece BUY" in item for item in result["warnings"])


def test_cool_learning_sensei_protocol_lists_missing_steps_without_manual_prompt() -> None:
    result = MarketCoolLearningMemory._course_alignment(
        course_context={
            "dominant_family": "OB Rejection",
            "harmony_score": 0.58,
            "support_score": 0.6,
            "matched_context_count": 4,
            "top_matching_contexts": [{"strategy_family": "OB Rejection", "score": 0.7}],
        },
        market_state={
            "ob_rejection_families": {
                "manual_bias": {
                    "active": False,
                    "side": "NEUTRAL",
                    "checks": {
                        "sell_liquidity": False,
                        "sell_micro_bos": False,
                        "sell_displacement": True,
                    },
                },
                "aggressive": {"checks": {"strong_bearish_rejection": True}},
                "institutional": {"checks": {}},
            }
        },
        dominant_family="OB Rejection",
        market_regime="NORMAL",
        preferred_side="SELL",
        policy_action="SELL",
    )

    assert "SENSEI_MANUAL_BIAS_PROTOCOL" in result["auto_selected_protocols"]
    assert any("Sensei: falta" in item for item in result["missing_steps"])
