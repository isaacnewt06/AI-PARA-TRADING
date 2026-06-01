from __future__ import annotations

import json
from pathlib import Path

from src.core.config import reload_settings
from src.trading.annual_strategy_optimizer import AnnualOBRejectionOptimizer, AnnualOptimizationCandidate


def _seed_strategy_files(data_dir: Path) -> None:
    specs_dir = data_dir / "backtests" / "specs"
    strategies_dir = data_dir / "strategies"
    specs_dir.mkdir(parents=True, exist_ok=True)
    strategies_dir.mkdir(parents=True, exist_ok=True)
    spec_payload = {
        "strategy_name": "OB Rejection Short Only Trailing ATR",
        "family": "OB Rejection",
        "symbols_suggested": ["XAUUSDm"],
        "context_timeframe": ["H1"],
        "entry_timeframe": ["M5", "M1"],
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
    (specs_dir / "ob_rejection_short_only_trailing_atr.json").write_text(json.dumps(spec_payload), encoding="utf-8")
    final_candidate = {
        "selected_configuration": {
            "strategy_name": "shorttrail_v3_none_nocd_nolimit_allatr",
            "parameters": {
                "session_filter": ["any_session"],
                "rr_min": 1.2,
                "trail_atr_multiple": 1.0,
                "blocked_hours_utc": [2, 3, 12, 16, 23],
                "required_rejection_signals": ["wick_rejection"],
                "max_range_atr_multiple": 2.0,
            },
        }
    }
    (strategies_dir / "final_candidate_v3.json").write_text(json.dumps(final_candidate), encoding="utf-8")


def test_annual_optimizer_writes_outputs_and_marks_needs_more_data(monkeypatch, tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    _seed_strategy_files(settings.paths.data_dir)
    optimizer = AnnualOBRejectionOptimizer(settings)

    baseline_candidate = AnnualOptimizationCandidate(
        candidate_name="baseline_v3",
        allowed_hours_utc=[],
        blocked_hours_utc=[2, 3, 12, 16, 23],
        allowed_atr_bands=[],
        blocked_atr_bands=[],
        allowed_confirmation_bands=[],
        blocked_confirmation_bands=[],
        required_rejection_signals=["wick_rejection"],
        blocked_rejection_signals=[],
        trail_atr_multiple=1.0,
        break_even_trigger_r=None,
        daily_max_losses=None,
        daily_min_pnl_r=None,
        cooldown_bars_after_loss=None,
        max_trades_per_day=None,
        max_range_atr_multiple=2.0,
    )
    alt_candidate = AnnualOptimizationCandidate(
        candidate_name="hours_core",
        allowed_hours_utc=[10, 11, 13],
        blocked_hours_utc=[2, 3, 12, 16, 23],
        allowed_atr_bands=[],
        blocked_atr_bands=[],
        allowed_confirmation_bands=[],
        blocked_confirmation_bands=[],
        required_rejection_signals=["wick_rejection"],
        blocked_rejection_signals=[],
        trail_atr_multiple=1.0,
        break_even_trigger_r=None,
        daily_max_losses=None,
        daily_min_pnl_r=None,
        cooldown_bars_after_loss=None,
        max_trades_per_day=None,
        max_range_atr_multiple=2.0,
    )

    monkeypatch.setattr(optimizer, "_baseline_candidate", lambda spec: baseline_candidate)
    monkeypatch.setattr(optimizer, "_candidates", lambda: [alt_candidate])

    def fake_evaluate_candidate(*, symbol, initial_capital, candidate, base_spec):
        accepted = candidate.candidate_name == "hours_core"
        return {
            "candidate": {"candidate_name": candidate.candidate_name},
            "parameters": {"strategy_name": candidate.candidate_name},
            "year_2024": {"simulations": {"0.5": {"annual": {"profit_factor": 0.9}}}},
            "year_2025": {"simulations": {"0.5": {"annual": {"profit_factor": 1.5}}}},
            "combined": {"0.5": {"annual": {"profit_factor": 1.4, "total_trades": 180, "max_drawdown_percent": 7.0}}, "1.0": {"annual": {"max_drawdown_percent": 14.0}}},
            "acceptance": {
                "coverage_sufficient": False,
                "accepted": False if accepted else False,
                "checks": {"coverage_2024": False, "coverage_2025": True},
                "coverage_warnings": ["Entry timeframe M5 does not cover the full year."],
            },
            "score": 100.0 if accepted else 90.0,
        }

    monkeypatch.setattr(optimizer, "_evaluate_candidate", fake_evaluate_candidate)

    summary = optimizer.run()

    assert summary["decision"] == "NEEDS_MORE_DATA"
    assert Path(summary["results_json"]).exists()
    assert Path(summary["report_md"]).exists()
    assert Path(summary["top_candidates_csv"]).exists()
