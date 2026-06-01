from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.trading.maximo_quant_v4_backtester import ClosedTrade
from src.trading.maximo_quant_v4_yearly_analyzer import MaximoQuantV4YearlyAnalyzer


def _trade(direction: str, entry: float, exit_: float, when: datetime) -> ClosedTrade:
    return ClosedTrade(
        symbol="XAUUSDm",
        dataset_label="annual_2025_full_year_2025",
        timeframe="M5",
        session_variant="london_ny_am",
        setup_type="AGG",
        direction=direction,
        signal_time=when,
        entry_time=when,
        exit_time=when,
        entry_price=entry,
        exit_price=exit_,
        stop_price=entry - 1 if direction == "buy" else entry + 1,
        target_price=exit_,
        initial_stop_price=entry - 1 if direction == "buy" else entry + 1,
        risk_per_unit=1.0,
        selected_rr=1.5,
        quant_score=80,
        impulse_score=75,
        buy_mtf_score=80,
        sell_mtf_score=20,
        confidence=78,
        market_regime="EXPANSION",
        month=when.strftime("%Y-%m"),
        hour_ny=9,
        pnl_r=1.0,
        exit_reason="take_profit",
    )


def test_realize_trades_uses_fixed_lot_price_delta() -> None:
    analyzer = MaximoQuantV4YearlyAnalyzer(
        input_dir=Path("."),
        backtests_dir=Path(".tmp_quant_yearly"),
        strategies_dir=Path(".tmp_quant_yearly_strategies"),
    )
    realized = analyzer._realize_trades(
        trades=[_trade("buy", 100.0, 102.0, datetime(2025, 1, 1, tzinfo=timezone.utc))],
        initial_capital=500.0,
        volume_lots=0.01,
    )
    assert len(realized) == 1
    assert realized[0].gross_pnl_usd == 2.0
    assert realized[0].net_pnl_usd < 2.0
    assert realized[0].balance_after > 500.0


def test_group_report_aggregates_weeks() -> None:
    analyzer = MaximoQuantV4YearlyAnalyzer(
        input_dir=Path("."),
        backtests_dir=Path(".tmp_quant_yearly"),
        strategies_dir=Path(".tmp_quant_yearly_strategies"),
    )
    realized = analyzer._realize_trades(
        trades=[
            _trade("buy", 100.0, 101.0, datetime(2025, 1, 3, tzinfo=timezone.utc)),
            _trade("sell", 100.0, 99.0, datetime(2025, 1, 4, tzinfo=timezone.utc)),
        ],
        initial_capital=500.0,
        volume_lots=0.01,
    )
    weekly = analyzer._group_report(realized, period="week", initial_capital=500.0)
    assert len(weekly) >= 1
    assert weekly[0]["trades"] >= 1


def test_resolve_runtime_variant_loads_optimizer_candidate(tmp_path: Path) -> None:
    backtests_dir = tmp_path / "backtests"
    analyzer = MaximoQuantV4YearlyAnalyzer(
        input_dir=tmp_path / "input",
        backtests_dir=backtests_dir,
        strategies_dir=tmp_path / "strategies",
    )
    optimization_dir = backtests_dir / "yearly"
    optimization_dir.mkdir(parents=True, exist_ok=True)
    optimization_payload = {
        "baseline": {
            "config": {
                "family": "v58_rr_adaptive",
                "code": "v58_rr_adaptive_d",
                "label": "RR adaptive 4",
                "phase": "phase_3_rr",
                "session_variant": "all",
                "timeframe": "M5",
                "require_preferred_side": True,
                "allowed_directions": None,
                "allowed_setup_types": ["AGG"],
                "allowed_hours_ny": [1, 5, 9, 15, 19],
                "excluded_hours_ny": None,
                "disallow_chop": False,
                "disallow_normal_hours_ny": None,
                "require_quant_expansion": False,
                "require_recent_compression": False,
                "min_quant_score_variant": 58,
                "min_impulse_score_variant": 55,
                "min_quant_score_agg": 58,
                "min_impulse_score_agg": 55,
                "min_confidence_agg": 60,
                "min_atr_ratio": 0.85,
                "min_range_ratio": 0.85,
                "max_atr_ratio": None,
                "max_range_ratio": 1.95,
                "max_risk_atr": 1.2,
                "rr_agg": 1.2,
                "rr_a_plus": 1.55,
                "cooldown_bars": 25,
                "pause_after_loss": 10,
                "pause_after_two_losses": 18,
            }
        },
        "all_candidates": [],
    }
    (optimization_dir / "optimization_annual_results.json").write_text(
        json.dumps(optimization_payload),
        encoding="utf-8",
    )

    resolved = analyzer._resolve_runtime_variant(
        strategy_variant_code="v58_rr_adaptive_d",
        session_variant_code=MaximoQuantV4YearlyAnalyzer.DEFAULT_SESSION,
    )

    assert resolved["strategy_variant"].code == "v58_rr_adaptive_d"
    assert resolved["session_variant"].code == "all"
    assert resolved["backtester"].RR_AGG == 1.2
    assert resolved["backtester"].RR_A == 1.55
    assert resolved["backtester"].COOLDOWN_BARS == 25
    assert resolved["strategy_variant"].allowed_setup_types == {"AGG"}
