from __future__ import annotations

import json
from pathlib import Path

from src.trading.strategy_optimizer import OBRejectionOptimizer


def test_strategy_optimizer_writes_outputs(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    results_dir = tmp_path / "results"
    reports_dir = tmp_path / "reports"
    optimization_dir = tmp_path / "optimization"
    specs_dir = tmp_path / "specs"
    for path in (input_dir, results_dir, reports_dir, optimization_dir, specs_dir):
        path.mkdir(parents=True, exist_ok=True)

    base_spec = {
        "strategy_name": "OB Rejection Short Only Trailing ATR",
        "family": "OB Rejection",
        "symbols_suggested": ["XAUUSDm"],
        "context_timeframe": ["H1"],
        "entry_timeframe": ["M5"],
        "session_filter": ["any_session"],
        "required_conditions": [],
        "confirmation_conditions": [],
        "entry_logic": {},
        "sl_logic": {},
        "tp_logic": {},
        "rr_min": 1.2,
        "risk_per_trade": 0.5,
        "invalidation_conditions": [],
        "quantifiable_condition_map": [],
        "simulation_overrides": {
            "direction_filter": "short_only",
            "exit_management": "trailing_atr_after_1r",
            "trail_atr_multiple": 1.0,
        },
        "source_traceability": {},
    }
    (specs_dir / "ob_rejection_short_only_trailing_atr.json").write_text(json.dumps(base_spec), encoding="utf-8")

    optimizer = OBRejectionOptimizer(input_dir, results_dir, reports_dir, optimization_dir)

    def fake_validate(spec):
        name = spec.strategy_name
        better = "dayr2" in name and "cd1" in name and "max4" in name and "allatr" in name
        return {
            "train": {
                "total_trades": 120 if better else 80,
                "win_rate": 42.0,
                "profit_factor": 1.31 if better else 1.18,
                "expectancy": 0.14 if better else 0.05,
                "max_drawdown": 8.5,
                "avg_rr": 0.12,
                "losing_streak": 5,
                "best_trade": None,
                "worst_trade": None,
            },
            "test": {
                "total_trades": 70 if better else 40,
                "win_rate": 44.0,
                "profit_factor": 1.28 if better else 1.05,
                "expectancy": 0.13 if better else 0.01,
                "max_drawdown": 7.0,
                "avg_rr": 0.11,
                "losing_streak": 4,
                "best_trade": None,
                "worst_trade": None,
            },
            "full": {
                "total_trades": 180 if better else 120,
                "win_rate": 43.0,
                "profit_factor": 1.34 if better else 1.14,
                "expectancy": 0.15 if better else 0.03,
                "max_drawdown": 8.0,
                "avg_rr": 0.12,
                "losing_streak": 5,
                "best_trade": None,
                "worst_trade": None,
            },
            "month_by_month": [
                {"month": "2026-01", "trades": 20, "net_pnl_r": 2.0, "profit_factor": 1.3, "expectancy": 0.1, "max_drawdown": 2.0, "losing_streak": 2, "negative_month": False},
                {"month": "2026-02", "trades": 20, "net_pnl_r": 1.0, "profit_factor": 1.2, "expectancy": 0.05, "max_drawdown": 1.5, "losing_streak": 2, "negative_month": False},
                {"month": "2026-03", "trades": 20, "net_pnl_r": 1.5, "profit_factor": 1.25, "expectancy": 0.08, "max_drawdown": 1.5, "losing_streak": 2, "negative_month": False},
                {"month": "2026-04", "trades": 20, "net_pnl_r": -0.2 if better else -1.0, "profit_factor": 0.98 if better else 0.7, "expectancy": -0.01 if better else -0.1, "max_drawdown": 2.0, "losing_streak": 2, "negative_month": True},
            ],
            "rolling_7030": [
                {"window_index": 1, "train_metrics": {"profit_factor": 1.2, "expectancy": 0.08, "total_trades": 30}, "test_metrics": {"profit_factor": 1.22 if better else 1.0, "expectancy": 0.07 if better else 0.0, "total_trades": 12}},
            ],
            "walk_forward_blocks": [
                {"window_index": 1, "train_metrics": {"profit_factor": 1.2, "expectancy": 0.08, "total_trades": 30}, "test_metrics": {"profit_factor": 1.21 if better else 0.98, "expectancy": 0.06 if better else -0.01, "total_trades": 10}},
            ],
            "stability_by_hour": [
                {"hour_utc": 9, "trades": 30, "trade_share": 0.25, "net_pnl_r": 3.0, "profit_factor": 1.4, "expectancy": 0.1},
                {"hour_utc": 11, "trades": 30, "trade_share": 0.25, "net_pnl_r": 3.2, "profit_factor": 1.5, "expectancy": 0.11},
            ],
            "paper_trading_gate": {
                "passes": better,
                "checks": {},
                "max_negative_months_consecutive": 0,
                "top_hour_trade_share": 0.25,
                "positive_hours_with_sample": 2,
            },
        }

    monkeypatch.setattr(optimizer.validator, "validate", fake_validate)

    summary = optimizer.run()

    assert Path(summary["results_json"]).exists()
    assert Path(summary["report_md"]).exists()
    assert Path(summary["top_candidates_csv"]).exists()
    assert Path(summary["baseline_path"]).exists()
    assert Path(summary["final_candidate_path"]).exists()
    assert Path(summary["final_validation_report_path"]).exists()
    assert summary["best_candidate"] is not None
