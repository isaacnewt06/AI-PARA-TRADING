from __future__ import annotations

from src.trading.expansion_subtype_pretrade_audit import ExpansionSubtypePretradeAuditV1


def _base_market_state(**overrides):
    state = {
        "hour_ny": 9,
        "session_tags": ["new_york", "ny_am"],
        "preferred_side": "SELL",
        "candidate_setups": {"sell_agg": True},
        "atr_ratio": 1.52,
        "range_ratio": 1.02,
        "body_pct": 18.0,
        "wick_rejection_pct_sell": 78.0,
        "expansion_subtype": "extended_expansion",
        "continuation_quality_sell": "weak",
        "atr_bucket": "extreme_atr",
        "sell_mtf_score": 78,
        "impulse_score": 80,
        "compression_ok": True,
        "ob_rejection_families": {
            "aggressive": {
                "side": "SELL",
                "checks": {
                    "micro_bos_sell": False,
                    "continuation_momentum_sell": False,
                },
            }
        },
    }
    state.update(overrides)
    return state


def test_expansion_subtype_pretrade_audit_labels_liquidity_sweep_without_lookahead() -> None:
    audit = ExpansionSubtypePretradeAuditV1().from_market_state(_base_market_state())

    assert audit["candidate_detected"] is True
    assert audit["subtype"] == "liquidity_sweep_expansion"
    assert audit["expected_edge_bucket"] == "favorable_research"
    assert audit["lookahead_safe"] is True
    assert audit["future_variables_used"] == []


def test_expansion_subtype_pretrade_audit_labels_trend_acceleration_as_warning() -> None:
    audit = ExpansionSubtypePretradeAuditV1().from_market_state(
        _base_market_state(
            atr_ratio=1.32,
            range_ratio=1.08,
            body_pct=34.0,
            wick_rejection_pct_sell=34.0,
            expansion_subtype="clean_expansion",
            continuation_quality_sell="weak",
            atr_bucket="high_atr",
        )
    )

    assert audit["subtype"] == "trend_acceleration_expansion"
    assert audit["expected_edge_bucket"] == "avoid_research"
    assert "largest 2025 loss" in audit["historical_warning"]


def test_expansion_subtype_pretrade_audit_no_matching_candidate_is_passive() -> None:
    audit = ExpansionSubtypePretradeAuditV1().from_market_state(_base_market_state(hour_ny=4, session_tags=["london"]))

    assert audit["candidate_detected"] is False
    assert audit["expected_edge_bucket"] == "not_applicable"
    assert audit["lookahead_safe"] is True
