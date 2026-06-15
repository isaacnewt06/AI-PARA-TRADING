from __future__ import annotations

from src.trading.execution_environment_policy import evaluate_execution_environment, limits_for_symbol


def test_xauusd_adaptive_policy_allows_observed_exness_demo_spread() -> None:
    evaluation = evaluate_execution_environment(
        symbol="XAUUSDm",
        spread=0.28,
        latency=0.04,
        slippage=0.28,
    )

    assert evaluation.execution_viability == "SAFE"
    assert evaluation.cost_quality == "optimal"
    assert evaluation.limits.profile == "xauusd_adaptive_exness_demo"
    assert evaluation.blockers == ()


def test_xauusd_adaptive_policy_blocks_hard_spread() -> None:
    evaluation = evaluate_execution_environment(
        symbol="XAUUSDm",
        spread=0.42,
        latency=0.04,
        slippage=0.42,
    )

    assert evaluation.execution_viability == "UNSAFE"
    assert "spread_above_hard_execution_limit" in evaluation.blockers
    assert "slippage_above_adaptive_execution_limit" in evaluation.blockers


def test_default_fx_policy_keeps_strict_spread_limit() -> None:
    limits = limits_for_symbol("EURUSDm")
    evaluation = evaluate_execution_environment(
        symbol="EURUSDm",
        spread=0.18,
        latency=0.04,
        slippage=0.18,
    )

    assert limits.profile == "default_fx_strict"
    assert evaluation.execution_viability == "UNSAFE"
    assert "spread_above_adaptive_execution_limit" in evaluation.blockers
