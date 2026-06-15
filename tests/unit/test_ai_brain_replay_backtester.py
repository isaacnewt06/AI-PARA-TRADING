from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.trading.ai_brain_replay_backtester import AIBrainReplayBacktester, HistoricalAIReplayBridge
from src.trading.execution_readiness_engine import ExecutionReadinessEngine


def _write_candles(path: Path, *, start: datetime, minutes: int, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        price = 100.0
        for index in range(rows):
            now = start + timedelta(minutes=minutes * index)
            close = price + 0.1
            writer.writerow(
                {
                    "time": now.isoformat(),
                    "open": price,
                    "high": close + 0.2,
                    "low": price - 0.2,
                    "close": close,
                    "volume": 100 + index,
                }
            )
            price = close


def _write_custom_candles(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def test_historical_ai_replay_bridge_opens_and_closes_virtual_trade(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _write_candles(input_dir / "XAUUSDm_M1_2026.csv", start=start, minutes=1, rows=600)
    _write_candles(input_dir / "XAUUSDm_M5_2026.csv", start=start, minutes=5, rows=200)
    _write_candles(input_dir / "XAUUSDm_H1_2026.csv", start=start, minutes=60, rows=80)
    bridge = HistoricalAIReplayBridge(input_dir=input_dir, symbol="XAUUSDm", year=2026, initial_balance=500.0)

    bridge.set_cursor_time(start + timedelta(minutes=300))
    environment = bridge.read_execution_environment(symbol="XAUUSDm")
    assert environment["spread_p80"] == bridge.SPREAD_PRICE
    assert environment["session_rd"] == "outside_validation_sessions"
    assert environment["hour_rd"] == 1.0

    order = bridge.place_demo_market_order(
        symbol="XAUUSDm",
        side="buy",
        volume_lots=0.01,
        stop_loss=50.0,
        take_profit=200.0,
        deviation_points=50,
        magic_number=1,
        comment="test",
    )
    assert order["result"]["retcode"] == 10009
    assert len(bridge.list_positions(symbol="XAUUSDm", magic=1)) == 1

    ticket = bridge.positions[0].ticket
    close = bridge.close_position_partial(
        symbol="XAUUSDm",
        ticket=ticket,
        side="buy",
        volume_lots=0.01,
        deviation_points=50,
        magic_number=1,
        comment="test close",
    )
    assert close["result"]["retcode"] == 10009
    assert len(bridge.closed_trades) == 1
    assert bridge.closed_trades[0]["exit_reason"] == "test close"


def test_historical_ai_replay_bridge_applies_be_after_half_r(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    start = datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    entry_mid = 100.0
    entry = entry_mid + HistoricalAIReplayBridge.SPREAD_PRICE / 2.0
    rows = [
        {
            "time": start.isoformat(),
            "open": entry_mid,
            "high": entry_mid + 0.2,
            "low": entry_mid - 0.2,
            "close": entry_mid,
            "volume": 100,
        },
        {
            "time": (start + timedelta(minutes=1)).isoformat(),
            "open": entry_mid,
            "high": entry + 1.2,
            "low": entry - 2.4,
            "close": entry - 0.3,
            "volume": 120,
        },
    ]
    _write_custom_candles(input_dir / "XAUUSDm_M1_2026.csv", rows)
    _write_custom_candles(input_dir / "XAUUSDm_M5_2026.csv", rows)
    _write_custom_candles(input_dir / "XAUUSDm_H1_2026.csv", rows)
    bridge = HistoricalAIReplayBridge(input_dir=input_dir, symbol="XAUUSDm", year=2026, initial_balance=500.0)

    bridge.set_cursor_time(start)
    order = bridge.place_demo_market_order(
        symbol="XAUUSDm",
        side="buy",
        volume_lots=0.01,
        stop_loss=entry - 2.0,
        take_profit=entry + 6.0,
        deviation_points=50,
        magic_number=1,
        comment="test be",
    )
    assert order["result"]["retcode"] == 10009

    bridge.set_cursor_time(start + timedelta(minutes=1))

    assert len(bridge.closed_trades) == 1
    assert bridge.closed_trades[0]["exit_reason"] == "BE"
    assert bridge.closed_trades[0]["final_r"] == 0.0


def test_ai_brain_replay_summary_contains_core_metrics(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    cycles = [
        {"action": "WATCH", "execution_status": "no_signal", "market_pulse": 80, "final_confirmation": 60, "entry_quality": 55, "execution_readiness": 40},
        {"action": "EXECUTE", "execution_status": "demo_order_sent", "market_pulse": 90, "final_confirmation": 80, "entry_quality": 78, "execution_readiness": 82},
    ]
    bridge = type(
        "Bridge",
        (),
        {
            "balance": 510.0,
            "positions": [],
            "orders": [{"ticket": 1}],
            "closed_trades": [{"profit": 10.0}],
        },
    )()

    summary = AIBrainReplayBacktester._build_summary(
        symbol="XAUUSDm",
        year=2026,
        initial_capital=500.0,
        output_dir=output_dir,
        cycles=cycles,
        bridge=bridge,
    )

    assert summary["mode"] == "AI_BRAIN_REPLAY_BACKTEST"
    assert summary["return_percent"] == 2.0
    assert summary["orders_opened"] == 1
    assert summary["avg_market_pulse"] == 85.0
    assert "Final Confirmation" in summary["full_brain_layers"]
    assert "unknown" in summary["session_breakdown"]
    assert summary["realism_notes"]["execution_environment"].startswith("Replay now supplies")


def test_cycle_summary_exposes_confirmation_aliases_from_armed_retest() -> None:
    cursor_time = datetime(2025, 1, 16, 19, 0, tzinfo=timezone.utc)
    result = {
        "intelligence_action": "WATCH",
        "execution_status": "no_signal",
        "market_pulse": {"score": 90.0},
        "market_clarity": {"clarity_score": 88.0, "selected_side": "BUY"},
        "expected_entry_zone": {"current_price": 2709.8, "in_zone_now": True},
        "armed_retest": {
            "action": "ARMED_RETEST_WAIT",
            "side": "BUY",
            "current_final_confirmation_score": 55.0,
            "current_entry_quality_score": 64.0,
            "current_execution_readiness_score": 32.0,
            "entry_confirmation_plan": {"status": "WAITING_PRECISE_TRIGGER"},
        },
    }

    cycle = AIBrainReplayBacktester._cycle_summary(cursor_time, result)

    assert cycle["preferred_side"] == "BUY"
    assert cycle["final_confirmation_score"] == 55.0
    assert cycle["entry_quality_score"] == 64.0
    assert cycle["execution_readiness_score"] == 32.0
    assert cycle["entry_confirmation_plan"]["status"] == "WAITING_PRECISE_TRIGGER"


def test_candidate_cursors_apply_warmup_before_date_filter() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = []
    for index in range(3200):
        candle_time = start + timedelta(minutes=index * 5)
        candles.append(type("CandleStub", (), {"time": candle_time})())
    target_date = (start + timedelta(minutes=3050 * 5)).date()

    rows = AIBrainReplayBacktester._candidate_cursors(
        candles,
        start_date=target_date,
        end_date=target_date,
        step_bars=1,
    )

    assert len(rows) > 1
    assert all(row.time.date() == target_date for row in rows)
    assert rows[0].time >= candles[3000].time


def test_execution_readiness_keeps_strong_context_in_armed_retest_band() -> None:
    engine = ExecutionReadinessEngine()

    result = engine.evaluate(
        final_confirmation={
            "final_confirmation_score": 49.6,
            "side": "BUY",
            "event_action": "watch",
            "blockers": [],
            "trap_risk_score": 0.2,
            "late_entry_risk": 0.25,
            "liquidity_volume_trap_analysis": {"liquidity_readiness_score": 0.7},
        },
        market_pulse={"score": 90.4},
        direction_consistency_guard={"allowed": True},
        execution_risk_decision={"allowed_risk_mode": "reduced", "can_execute": False},
        q_learning_decision={"q_policy_action": "HOLD"},
        intelligence={"execution_readiness": {"action": "WATCH"}},
        entry_quality={"decision": "WAIT_RETEST", "entry_quality_score": 45.0, "zone_quality": 64.0},
    )

    assert result["classification"] == "ARMED_RETEST"
    assert 71.0 <= result["execution_readiness_score"] <= 77.0
    assert result["can_execute_quality_gate"] is False
    assert result["armed_retest_context_recovery"]["eligible"] is True


def test_execution_readiness_scores_allowed_armed_retest_q_conflict_as_caution() -> None:
    engine = ExecutionReadinessEngine()

    result = engine.evaluate(
        final_confirmation={
            "final_confirmation_score": 76.0,
            "side": "BUY",
            "event_action": "allow",
            "execution_viability": "SAFE",
            "blockers": [],
            "trap_risk_score": 0.15,
            "late_entry_risk": 0.2,
            "rr_evaluable": True,
        },
        market_pulse={"score": 91.0},
        direction_consistency_guard={
            "allowed": True,
            "conflicts": ["persistent_q_learning_policy"],
            "armed_retest_q_learning_override": True,
        },
        execution_risk_decision={"allowed_risk_mode": "reduced", "can_execute": True},
        q_learning_decision={"q_policy_action": "SELL"},
        intelligence={"execution_readiness": {"action": "EXECUTE"}},
        entry_quality={"decision": "EXECUTION_READY", "entry_quality_score": 78.0, "zone_quality": 72.0, "sl_quality": 80.0, "tp_quality": 78.0},
    )

    assert result["components"]["direction_alignment_score"] == 72.0
    assert result["execution_readiness_score"] >= 70.0
