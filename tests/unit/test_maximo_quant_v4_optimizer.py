from __future__ import annotations

from pathlib import Path

from src.trading.maximo_quant_v4_optimizer import MaximoQuantV4Optimizer


def test_optimizer_acceptance_rejects_curve_fit_like_candidate() -> None:
    optimizer = MaximoQuantV4Optimizer(
        input_dir=Path("."),
        backtests_dir=Path(".tmp_quant_opt"),
        strategies_dir=Path(".tmp_quant_opt_strategies"),
    )
    acceptance = optimizer._acceptance(
        annual_2025={"total_trades": 55, "max_drawdown_r": 3.5, "expectancy_r": 0.2},
        in_sample_2025={"profit_factor": 2.4},
        out_of_sample_2025={"profit_factor": 0.8, "expectancy_r": -0.1},
        combined={"expectancy_r": 0.1},
        hourly=[{"total_trades": 30}],
        monthly=[
            {"net_profit_r": 1.0},
            {"net_profit_r": -1.0},
            {"net_profit_r": -1.0},
            {"net_profit_r": -1.0},
        ],
        coverage_2024={"sufficient": True},
    )
    assert acceptance["accepted"] is False
    assert "possible_curve_fitting" in acceptance["reasons"]
    assert "oos_profit_factor_below_1_3" in acceptance["reasons"]


def test_optimizer_score_rewards_stable_candidate() -> None:
    score = MaximoQuantV4Optimizer._score(
        annual_2025={
            "profit_factor": 1.8,
            "win_rate": 59.0,
            "total_trades": 80,
            "max_drawdown_r": 3.0,
        },
        out_of_sample_2025={"profit_factor": 1.55},
        combined={"expectancy_r": 0.35},
        acceptance={"status": "accepted", "dominant_hour_trade_share": 0.25, "reasons": []},
        hourly=[{"total_trades": 20}, {"total_trades": 18}],
    )
    assert score > 0
