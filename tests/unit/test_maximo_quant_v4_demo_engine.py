from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.config import reload_settings
from src.trading.maximo_quant_v4_backtester import StrategyVariant
from src.trading.maximo_quant_v4_demo_engine import MaximoQuantV4DemoEngine


@dataclass
class _Variant:
    code: str = "v56_aggressive_filtered_b"


@dataclass
class _Session:
    code: str = "all"


class _FakeBridge:
    def __init__(self) -> None:
        self.sent = None
        self.modified = []
        self.partial_closed = []
        self.last_bar_time = "2026-01-01T10:00:00+00:00"

    def account_status(self) -> dict:
        return {"is_demo": True, "account_info": {"server": "Demo", "balance": 1000.0, "equity": 1000.0}, "terminal_info": {"path": "mt5"}}

    def list_positions(self, *, symbol: str | None = None, magic: int | None = None) -> list[dict]:
        return []

    def read_market_snapshot(self, *, symbol: str, bars_by_timeframe: dict[str, int] | None = None) -> dict:
        return {
            "symbol": symbol,
            "timeframes": {
                "M1": {"bars": 500, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": self.last_bar_time},
                "M5": {"bars": 5000, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": self.last_bar_time},
                "H1": {"bars": 2000, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": self.last_bar_time},
            },
            "candles": {"M1": [], "M5": [], "H1": []},
        }

    def place_demo_market_order(self, **kwargs) -> dict:
        self.sent = kwargs
        return {"request": kwargs, "result": {"retcode": 10009, "order": 1, "deal": 2}, "is_demo": True}

    def modify_position_sl_tp(self, **kwargs) -> dict:
        self.modified.append(kwargs)
        return {"request": kwargs, "result": {"retcode": 10009}}

    def close_position_partial(self, **kwargs) -> dict:
        self.partial_closed.append(kwargs)
        return {"request": kwargs, "result": {"retcode": 10009}}

    def calculate_risk_volume_lots(self, **kwargs) -> dict:
        risk_amount = float(kwargs["risk_amount"])
        entry = float(kwargs["entry_price"])
        stop = float(kwargs["stop_loss"])
        risk_per_lot = abs(entry - stop) * 100.0
        volume = max(round(risk_amount / risk_per_lot, 2), 0.01)
        return {
            "symbol_requested": kwargs["symbol"],
            "symbol_resolved": "XAUUSDm",
            "entry_price": entry,
            "stop_loss": stop,
            "risk_amount": risk_amount,
            "risk_per_lot": risk_per_lot,
            "requested_volume_lots": volume,
            "volume_lots": volume,
            "estimated_risk_amount": round(volume * risk_per_lot, 4),
            "estimated_risk_percent_of_target": 1.0,
            "sizing_method": "test",
            "symbol_info": {},
        }


def _fake_intelligence_payload(
    *,
    action: str = "EXECUTE",
    posture: str = "aligned",
    signal: dict | None = None,
    preferred_side: str = "BUY",
    watch_trigger: dict | None = None,
    confidence: float | None = None,
    setup_maturity: float | None = None,
    harmony_score: float | None = None,
    event_action: str = "allow",
    market_regime: str = "EXPANSION",
    blockers: list[str] | None = None,
    operational_family: str = "NONE",
) -> dict:
    return {
        "strategy_name": "MAXIMO MTF Quant Institutional v4",
        "symbol": "XAUUSDm",
        "strategy_variant": "v56_aggressive_filtered_b",
        "session_variant": "all",
        "overview": {
            "market_state": {
                "market_regime": market_regime,
                "preferred_side": preferred_side,
                "hour_ny": 9,
                "allowed_hour_by_strategy": True,
                "candidate_setups": {"buy_agg": False, "sell_agg": True},
                "operational_family": operational_family,
                "ob_rejection_families": {
                    "active_family": operational_family,
                    "aggressive": {"active": operational_family == "OB_REJECTION_AGGRESSIVE_WATCH"},
                    "institutional": {"active": operational_family == "OB_REJECTION_INSTITUTIONAL_EXECUTE"},
                },
            },
            "knowledge_alignment": {
                "support_score": 0.62,
                "top_matching_contexts": [
                    {
                        "strategy_family": "OB Rejection",
                        "market_regime": "trend",
                        "sessions": ["new_york"],
                        "entry_timeframes": ["M5"],
                        "supporting_rules": 34,
                        "operability_label": "needs_confirmation",
                    }
                ],
                "harmony": {
                    "harmony_score": harmony_score if harmony_score is not None else (0.74 if posture == "aligned" else 0.22),
                    "operating_posture": posture,
                    "dominant_family": "OB Rejection",
                }
            },
            "signal": signal,
        },
        "event_risk": {"action": event_action},
        "volatility_intelligence": {"state": "tradable_normal"},
        "execution_readiness": {
            "action": action,
            "confidence": confidence if confidence is not None else (0.77 if action == "EXECUTE" else 0.41),
            "risk_mode": "normal" if action == "EXECUTE" else "reduced",
            "watchlist_active": action == "WATCH",
            "setup_maturity": setup_maturity if setup_maturity is not None else (86.0 if action == "EXECUTE" else 62.0),
            "can_execute_demo_now": action == "EXECUTE",
            "blockers": blockers if blockers is not None else ([] if action == "EXECUTE" else ["defensive_knowledge_posture"]),
            "rationale": ["Simulated intelligence."],
        },
        "watch_trigger": watch_trigger,
    }


def test_position_management_moves_short_sl_to_protect_profit(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    snapshot = {
        "timeframes": {"M1": {"last_bar_time": "2026-01-01T10:00:00+00:00"}, "M5": {"last_bar_time": "2026-01-01T10:00:00+00:00"}},
        "candles": {"M1": [{"close": 94.0}], "M5": [{"close": 94.0}]},
    }
    positions = [
        {
            "ticket": 1,
            "type": 1,
            "symbol": "XAUUSDm",
            "price_open": 100.0,
            "sl": 110.0,
            "tp": 85.0,
            "volume": 0.02,
            "price_current": 88.0,
        }
    ]

    result = engine._manage_open_positions(symbol="XAUUSDm", positions=positions, snapshot=snapshot, dry_run=False)

    assert result["updates_sent"] == 2
    assert bridge.partial_closed[0]["ticket"] == 1
    assert bridge.modified[0]["ticket"] == 1
    assert bridge.modified[0]["stop_loss"] < 100.0
    assert result["actions"][1]["protection_level"] == "near_tp_trailing"


def test_position_management_does_not_move_sl_without_enough_profit(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    snapshot = {
        "timeframes": {"M1": {"last_bar_time": "2026-01-01T10:00:00+00:00"}, "M5": {"last_bar_time": "2026-01-01T10:00:00+00:00"}},
        "candles": {"M1": [{"close": 98.0}], "M5": [{"close": 98.0}]},
    }
    positions = [
        {
            "ticket": 2,
            "type": 1,
            "symbol": "XAUUSDm",
            "price_open": 100.0,
            "sl": 110.0,
            "tp": 85.0,
            "price_current": 98.0,
        }
    ]

    result = engine._manage_open_positions(symbol="XAUUSDm", positions=positions, snapshot=snapshot, dry_run=False)

    assert result["updates_sent"] == 0
    assert bridge.modified == []
    assert result["actions"][0]["action"] == "monitor"


def test_direction_consistency_guard_blocks_buy_against_sell_thesis(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    intelligence = _fake_intelligence_payload(
        preferred_side="SELL",
        watch_trigger={
            "side": "SELL",
            "pattern_projection": {
                "side_probability_comparison": {"selected_side": "SELL"},
                "professional_decision_matrix": {
                    "selected_side": "SELL",
                    "side_assessments": {"BUY": {"probability_to_confirm": 0.59}},
                    "layer_synchronization": {"status": "conflicted"},
                    "course_learning_sync": {"status": "conflict"},
                },
            },
        },
    )
    signal = {"direction": "buy", "elite_session_alignment": False}
    active_watch = {"side": "SELL"}

    result = engine._signal_direction_consistency_guard(
        signal=signal,
        intelligence=intelligence,
        active_watch=active_watch,
        q_learning_decision={"q_policy_action": "BUY"},
    )

    assert result["allowed"] is False
    assert "active_watch_side" in result["conflicts"]


def test_direction_consistency_guard_allows_aligned_sell(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    intelligence = _fake_intelligence_payload(
        preferred_side="SELL",
        watch_trigger={
            "side": "SELL",
            "pattern_projection": {
                "side_probability_comparison": {"selected_side": "SELL"},
                "professional_decision_matrix": {"selected_side": "SELL"},
            },
        },
    )

    result = engine._signal_direction_consistency_guard(
        signal={"direction": "sell"},
        intelligence=intelligence,
        active_watch={"side": "SELL"},
        q_learning_decision={"q_policy_action": "SELL"},
    )

    assert result["allowed"] is True
    assert result["conflicts"] == []


def test_direction_consistency_guard_allows_valid_countertrend_scalp(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    intelligence = _fake_intelligence_payload(
        preferred_side="SELL",
        watch_trigger={
            "side": "SELL",
            "pattern_projection": {
                "side_probability_comparison": {"selected_side": "SELL"},
                "professional_decision_matrix": {
                    "selected_side": "SELL",
                    "side_assessments": {"BUY": {"probability_to_confirm": 0.9}},
                    "layer_synchronization": {"status": "mostly_aligned"},
                    "course_learning_sync": {"status": "partial"},
                },
            },
        },
    )

    result = engine._signal_direction_consistency_guard(
        signal={"direction": "buy", "countertrend_reversal_scalp": True},
        intelligence=intelligence,
        active_watch={"side": "SELL"},
        q_learning_decision={"q_policy_action": "BUY"},
    )

    assert result["allowed"] is True
    assert "reversal scalp" in result["reason"]


def test_account_risk_sizing_uses_five_percent_base_account_risk(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    signal = {"entry_price": 100.0, "stop_price": 98.0}

    result = engine._apply_account_risk_sizing(
        symbol="XAUUSDm",
        signal=signal,
        account_status=bridge.account_status(),
        execution_risk_decision={"can_execute": True, "effective_risk": 0.01},
    )

    assert result["account_risk_percent"] == 5.0
    assert result["account_risk_amount"] == 50.0
    assert result["order_volume_lots"] == 0.25
    assert result["risk_percent_policy"] == "probability_adjusted_5_percent_base_per_account"
    assert result["position_sizing"]["status"] == "calculated"


def test_account_risk_sizing_allows_min_lot_above_target_inside_ten_percent_cap(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    signal = {"entry_price": 100.0, "stop_price": 80.0}

    result = engine._apply_account_risk_sizing(
        symbol="XAUUSDm",
        signal=signal,
        account_status=bridge.account_status(),
        execution_risk_decision={"can_execute": True, "effective_risk": 0.01},
    )

    assert result["can_execute"] is True
    assert result["estimated_order_risk_percent"] == 6.0
    assert result["position_sizing"]["status"] == "min_lot_above_target_within_10_percent_cap"


def test_account_risk_sizing_blocks_when_min_lot_exceeds_ten_percent(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    signal = {"entry_price": 200.0, "stop_price": 90.0}

    result = engine._apply_account_risk_sizing(
        symbol="XAUUSDm",
        signal=signal,
        account_status=bridge.account_status(),
        execution_risk_decision={"can_execute": True, "effective_risk": 0.01},
    )

    assert result["can_execute"] is False
    assert result["execution_status"] == "blocked_by_min_lot_exceeds_10_percent_account_risk"
    assert result["estimated_order_risk_percent"] == 11.0
    assert result["position_sizing"]["status"] == "blocked"


def test_account_risk_sizing_adjusts_target_by_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    signal = {"entry_price": 100.0, "stop_price": 98.0, "quality": "A"}

    result = engine._apply_account_risk_sizing(
        symbol="XAUUSDm",
        signal=signal,
        account_status=bridge.account_status(),
        execution_risk_decision={
            "can_execute": True,
            "allowed_risk_mode": "normal",
            "max_risk_multiplier": 1.0,
            "risk_probability_score": 0.94,
            "effective_risk": 0.01,
        },
    )

    assert result["account_risk_percent"] == 7.5
    assert result["account_risk_amount"] == 75.0
    assert result["position_sizing"]["risk_profile"]["probability_risk_multiplier"] == 1.5


def test_demo_runtime_overlay_uses_snapshot_hours() -> None:
    variant = StrategyVariant(
        code="v56_aggressive_filtered_b",
        label="Static",
        allowed_hours_ny={1, 4, 5, 9, 15, 19},
    )

    updated = MaximoQuantV4DemoEngine._overlay_strategy_variant_from_snapshot(
        strategy_variant=variant,
        snapshot={
            "parameters": {
                "allowed_hours_ny": [1, 4, 5, 9, 10, 11, 12, 13, 14, 15, 19],
            }
        },
    )

    assert updated.allowed_hours_ny == {1, 4, 5, 9, 10, 11, 12, 13, 14, 15, 19}


def test_demo_engine_dry_run_writes_signal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)

    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    signal = {
        "entry_kind": "market",
        "strategy_variant": "v56_aggressive_filtered_b",
        "session_variant": "all",
        "symbol": "XAUUSDm",
        "timeframe": "M5",
        "signal_time": "2026-05-08T00:00:00+00:00",
        "entry_time": "2026-05-08T00:05:00+00:00",
        "direction": "buy",
        "setup_type": "AGG",
        "entry_price": 2350.0,
        "stop_price": 2348.0,
        "target_price": 2353.0,
        "risk_per_unit": 2.0,
        "selected_rr": 1.5,
        "quant_score": 80,
        "impulse_score": 75,
        "buy_mtf_score": 78,
        "sell_mtf_score": 15,
        "confidence": 70,
        "market_regime": "EXPANSION",
        "hour_ny": 9,
        "preferred_side": "BUY",
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="EXECUTE",
        posture="aligned",
        signal=signal,
        preferred_side="BUY",
        confidence=0.9,
    )

    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["execution_status"] == "dry_run_signal_detected"
    assert result["signal_detected"] is True
    assert result["intelligence_action"] == "EXECUTE"
    assert bridge.sent is None
    assert engine.signal_path.exists()
    assert engine.executions_path.exists()


def test_demo_engine_live_requires_confirm_demo(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)

    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    signal = {
        "entry_kind": "market",
        "strategy_variant": "v56_aggressive_filtered_b",
        "session_variant": "all",
        "symbol": "XAUUSDm",
        "timeframe": "M5",
        "signal_time": "2026-05-08T00:00:00+00:00",
        "entry_time": "2026-05-08T00:05:00+00:00",
        "direction": "sell",
        "setup_type": "AGG",
        "entry_price": 2350.0,
        "stop_price": 2352.0,
        "target_price": 2347.0,
        "risk_per_unit": 2.0,
        "selected_rr": 1.5,
        "quant_score": 80,
        "impulse_score": 75,
        "buy_mtf_score": 15,
        "sell_mtf_score": 78,
        "confidence": 70,
        "market_regime": "EXPANSION",
        "hour_ny": 9,
        "preferred_side": "SELL",
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="EXECUTE",
        posture="aligned",
        signal=signal,
        preferred_side="SELL",
        confidence=0.9,
    )

    try:
        engine.run(symbol="XAUUSDm", dry_run=False, confirm_demo=False)
        assert False, "Expected confirm_demo guard to raise."
    except RuntimeError as exc:
        assert "confirm_demo" in str(exc)


def test_demo_engine_blocks_when_market_intelligence_is_defensive(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)

    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    signal = {
        "entry_kind": "market",
        "strategy_variant": "v56_aggressive_filtered_b",
        "session_variant": "all",
        "symbol": "XAUUSDm",
        "timeframe": "M5",
        "signal_time": "2026-05-08T00:00:00+00:00",
        "entry_time": "2026-05-08T00:05:00+00:00",
        "direction": "sell",
        "setup_type": "AGG",
        "entry_price": 2350.0,
        "stop_price": 2352.0,
        "target_price": 2347.0,
        "risk_per_unit": 2.0,
        "selected_rr": 1.5,
        "quant_score": 80,
        "impulse_score": 75,
        "buy_mtf_score": 15,
        "sell_mtf_score": 78,
        "confidence": 70,
        "market_regime": "EXPANSION",
        "hour_ny": 9,
        "preferred_side": "SELL",
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="defensive",
        signal=signal,
    )

    result = engine.run(symbol="XAUUSDm", dry_run=False, confirm_demo=True)

    assert result["execution_status"] == "blocked_by_market_intelligence"
    assert result["operating_posture"] == "defensive"
    assert bridge.sent is None


def test_demo_engine_watch_report_includes_trigger_details(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)

    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista.", "setup_maturity >= 75"],
        "cancel_conditions": ["Noticia bloqueante.", "preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal operativa confirmada."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
    )

    result = engine.run(symbol="XAUUSDm", dry_run=True)
    report = engine.report_path.read_text(encoding="utf-8")
    latest_signal = engine.signal_path.read_text(encoding="utf-8")

    assert result["intelligence_action"] == "WATCH"
    assert result["watch_trigger"]["trigger_type"] == "bearish_confirmation"
    assert "preferred_side: SELL" in report
    assert "trigger_type: bearish_confirmation" in report
    assert "Falta señal operativa confirmada." in report
    assert '"watch_trigger"' in latest_signal


def test_watch_creates_active_watch(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.68,
        setup_maturity=68.0,
        harmony_score=0.58,
    )

    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["active_watch"]["status"] == "ACTIVE"
    assert result["active_watch"]["side"] == "SELL"
    assert engine.active_watch_path.exists()
    history_lines = engine.active_watch_history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(history_lines) == 1
    assert '"event": "WATCH_CREATED"' in history_lines[0]


def test_watch_updates_existing_active_watch(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.62,
        setup_maturity=62.0,
        harmony_score=0.56,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    bridge.last_bar_time = "2026-01-01T10:10:00+00:00"
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.74,
        setup_maturity=75.0,
        harmony_score=0.64,
    )
    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["active_watch"]["status"] == "ACTIVE"
    assert result["active_watch"]["progress"] == "improving"
    assert result["active_watch"]["age_candles"] == 2
    history_lines = engine.active_watch_history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(history_lines) == 2
    assert '"event": "WATCH_IMPROVING"' in history_lines[-1]


def test_signal_strong_converts_active_watch_to_triggered(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.68,
        setup_maturity=68.0,
        harmony_score=0.58,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    bridge.last_bar_time = "2026-01-01T10:05:00+00:00"
    signal = {
        "entry_kind": "market",
        "strategy_variant": "v56_aggressive_filtered_b",
        "session_variant": "all",
        "symbol": "XAUUSDm",
        "timeframe": "M5",
        "signal_time": "2026-05-08T00:00:00+00:00",
        "entry_time": "2026-05-08T00:05:00+00:00",
        "direction": "sell",
        "setup_type": "AGG",
        "entry_price": 2350.0,
        "stop_price": 2352.0,
        "target_price": 2347.0,
        "selected_rr": 1.5,
        "confidence": 82,
        "market_regime": "EXPANSION",
        "hour_ny": 9,
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="EXECUTE",
        posture="aligned",
        signal=signal,
        preferred_side="SELL",
        confidence=0.82,
        setup_maturity=86.0,
        harmony_score=0.71,
        blockers=[],
    )
    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["active_watch"]["status"] == "TRIGGERED"
    assert result["intelligence_action"] == "EXECUTE"
    history_lines = engine.active_watch_history_path.read_text(encoding="utf-8").strip().splitlines()
    assert any('"event": "WATCH_TRIGGERED"' in line for line in history_lines)


def test_side_change_cancels_active_watch(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    bridge.last_bar_time = "2026-01-01T10:05:00+00:00"
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="BUY",
        watch_trigger={
            **watch_trigger,
            "side": "BUY",
            "trigger_type": "bullish_confirmation",
        },
    )
    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["active_watch"]["status"] == "CANCELLED"
    assert "preferred_side" in result["active_watch"]["reason"]
    history_lines = engine.active_watch_history_path.read_text(encoding="utf-8").strip().splitlines()
    assert '"event": "WATCH_CANCELLED"' in history_lines[-1]


def test_macro_block_cancels_active_watch(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["Noticia bloqueante."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    bridge.last_bar_time = "2026-01-01T10:05:00+00:00"
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="BLOCKED",
        posture="defensive",
        signal=None,
        preferred_side="SELL",
        event_action="block",
        blockers=["high_impact_event_window"],
    )
    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["active_watch"]["status"] == "CANCELLED"
    assert "bloqueo macro" in result["active_watch"]["reason"]
    history_lines = engine.active_watch_history_path.read_text(encoding="utf-8").strip().splitlines()
    assert '"event": "WATCH_CANCELLED"' in history_lines[-1]


def test_expiration_by_candles_marks_expired(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    bridge.last_bar_time = "2026-01-01T11:05:00+00:00"
    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["active_watch"]["status"] == "EXPIRED"
    history_lines = engine.active_watch_history_path.read_text(encoding="utf-8").strip().splitlines()
    assert '"event": "WATCH_EXPIRED"' in history_lines[-1]


def test_deterioration_cancels_active_watch(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["harmony/setup se deteriora."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.68,
        setup_maturity=70.0,
        harmony_score=0.60,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    bridge.last_bar_time = "2026-01-01T10:05:00+00:00"
    result = engine.run(symbol="XAUUSDm", dry_run=True)
    assert result["active_watch"]["status"] == "ACTIVE"

    bridge.last_bar_time = "2026-01-01T10:10:00+00:00"
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="CAUTION",
        posture="defensive",
        signal=None,
        preferred_side="SELL",
        confidence=0.40,
        setup_maturity=45.0,
        harmony_score=0.30,
    )
    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["active_watch"]["status"] == "CANCELLED"
    history_lines = engine.active_watch_history_path.read_text(encoding="utf-8").strip().splitlines()
    assert '"event": "WATCH_DETERIORATING"' in history_lines[-1] or '"event": "WATCH_CANCELLED"' in history_lines[-1]


def test_blocked_does_not_create_active_watch(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="BLOCKED",
        posture="defensive",
        signal=None,
        preferred_side="SELL",
        event_action="block",
        blockers=["high_impact_event_window"],
    )

    result = engine.run(symbol="XAUUSDm", dry_run=True)

    assert result["active_watch"] is None
    assert not engine.active_watch_path.exists()
    assert not engine.active_watch_history_path.exists()


def test_watch_does_not_duplicate_identical_history_event(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.68,
        setup_maturity=68.0,
        harmony_score=0.58,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)
    bridge.last_bar_time = "2026-01-01T10:00:00+00:00"
    engine.run(symbol="XAUUSDm", dry_run=True)

    history_lines = engine.active_watch_history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(history_lines) == 1


def test_demo_report_shows_last_transition(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.68,
        setup_maturity=68.0,
        harmony_score=0.58,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)
    bridge.last_bar_time = "2026-01-01T10:10:00+00:00"
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.74,
        setup_maturity=75.0,
        harmony_score=0.64,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    report = engine.report_path.read_text(encoding="utf-8")
    assert "## Active Watch History" in report
    assert "events_recorded: 2" in report
    assert "last_event: WATCH_IMPROVING" in report


def test_timeline_with_five_events(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    history_events = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "event": "WATCH_CREATED", "side": "SELL", "trigger_type": "bearish_confirmation", "age_candles": 0, "confidence": 0.6, "harmony_score": 0.5, "setup_maturity": 60.0, "reason": "created"},
        {"timestamp": "2026-01-01T10:05:00+00:00", "event": "WATCH_IMPROVING", "side": "SELL", "trigger_type": "bearish_confirmation", "age_candles": 1, "confidence": 0.65, "harmony_score": 0.55, "setup_maturity": 66.0, "reason": "improving"},
        {"timestamp": "2026-01-01T10:10:00+00:00", "event": "WATCH_DETERIORATING", "side": "SELL", "trigger_type": "bearish_confirmation", "age_candles": 2, "confidence": 0.58, "harmony_score": 0.5, "setup_maturity": 61.0, "reason": "deteriorating"},
        {"timestamp": "2026-01-01T10:15:00+00:00", "event": "WATCH_IMPROVING", "side": "SELL", "trigger_type": "bearish_confirmation", "age_candles": 3, "confidence": 0.7, "harmony_score": 0.6, "setup_maturity": 70.0, "reason": "improving again"},
        {"timestamp": "2026-01-01T10:20:00+00:00", "event": "WATCH_TRIGGERED", "side": "SELL", "trigger_type": "bearish_confirmation", "age_candles": 4, "confidence": 0.8, "harmony_score": 0.7, "setup_maturity": 82.0, "reason": "triggered"},
    ]
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in history_events:
            handle.write(__import__("json").dumps(event) + "\n")

    timeline = engine._active_watch_timeline_events()

    assert len(timeline) == 5
    assert timeline[-1]["event"] == "WATCH_TRIGGERED"


def test_timeline_without_file(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())

    timeline = engine._active_watch_timeline_events()

    assert timeline == []


def test_timeline_with_empty_jsonl(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    engine.active_watch_history_path.write_text("", encoding="utf-8")

    timeline = engine._active_watch_timeline_events()

    assert timeline == []


def test_timeline_ignores_invalid_json(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    engine.active_watch_history_path.write_text(
        "{invalid json}\n"
        + __import__("json").dumps(
            {
                "timestamp": "2026-01-01T10:20:00+00:00",
                "event": "WATCH_TRIGGERED",
                "side": "SELL",
                "trigger_type": "bearish_confirmation",
                "age_candles": 4,
                "confidence": 0.8,
                "harmony_score": 0.7,
                "setup_maturity": 82.0,
                "reason": "triggered",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    timeline = engine._active_watch_timeline_events()

    assert len(timeline) == 1
    assert timeline[0]["event"] == "WATCH_TRIGGERED"


def test_timeline_prioritizes_important_events_over_watch_updated(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    history_events = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "event": "WATCH_UPDATED", "side": "SELL", "trigger_type": "bearish_confirmation", "age_candles": 0, "confidence": 0.6, "harmony_score": 0.5, "setup_maturity": 60.0, "reason": "updated"},
        {"timestamp": "2026-01-01T10:05:00+00:00", "event": "WATCH_IMPROVING", "side": "SELL", "trigger_type": "bearish_confirmation", "age_candles": 1, "confidence": 0.65, "harmony_score": 0.55, "setup_maturity": 66.0, "reason": "improving"},
    ]
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in history_events:
            handle.write(__import__("json").dumps(event) + "\n")

    timeline = engine._active_watch_timeline_events()

    assert len(timeline) == 1
    assert timeline[0]["event"] == "WATCH_IMPROVING"


def test_improving_increases_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    improving_metrics = engine._active_watch_metrics(
        active_watch={
            "status": "ACTIVE",
            "progress": "improving",
            "current_confidence": 0.72,
            "current_harmony_score": 0.66,
            "current_setup_maturity": 78.0,
            "initial_missing_for_execute": ["a", "b", "c"],
            "missing_for_execute": ["a"],
            "age_candles": 2,
            "expiration_candles": 12,
        },
        active_watch_history={"count": 2, "last_event": {"event": "WATCH_IMPROVING"}},
    )
    stable_metrics = engine._active_watch_metrics(
        active_watch={
            "status": "ACTIVE",
            "progress": "stable",
            "current_confidence": 0.72,
            "current_harmony_score": 0.66,
            "current_setup_maturity": 78.0,
            "initial_missing_for_execute": ["a", "b", "c"],
            "missing_for_execute": ["a", "b"],
            "age_candles": 2,
            "expiration_candles": 12,
        },
        active_watch_history={"count": 1, "last_event": {"event": "WATCH_CREATED"}},
    )

    assert improving_metrics["watch_health"] == "improving"
    assert improving_metrics["watch_probability_to_execute"] > stable_metrics["watch_probability_to_execute"]


def test_deteriorating_reduces_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    deteriorating_metrics = engine._active_watch_metrics(
        active_watch={
            "status": "ACTIVE",
            "progress": "deteriorating",
            "current_confidence": 0.55,
            "current_harmony_score": 0.44,
            "current_setup_maturity": 58.0,
            "initial_missing_for_execute": ["a"],
            "missing_for_execute": ["a", "b", "c"],
            "age_candles": 6,
            "expiration_candles": 12,
        },
        active_watch_history={"count": 2, "last_event": {"event": "WATCH_DETERIORATING"}},
    )
    stable_metrics = engine._active_watch_metrics(
        active_watch={
            "status": "ACTIVE",
            "progress": "stable",
            "current_confidence": 0.55,
            "current_harmony_score": 0.44,
            "current_setup_maturity": 58.0,
            "initial_missing_for_execute": ["a"],
            "missing_for_execute": ["a"],
            "age_candles": 1,
            "expiration_candles": 12,
        },
        active_watch_history={"count": 1, "last_event": {"event": "WATCH_CREATED"}},
    )

    assert deteriorating_metrics["watch_health"] in {"deteriorating", "critical"}
    assert deteriorating_metrics["watch_probability_to_execute"] < stable_metrics["watch_probability_to_execute"]


def test_expired_returns_zero_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    metrics = engine._active_watch_metrics(
        active_watch={"status": "EXPIRED", "progress": "expired"},
        active_watch_history={"count": 1, "last_event": {"event": "WATCH_EXPIRED"}},
    )

    assert metrics["watch_health"] == "inactive"
    assert metrics["watch_probability_to_execute"] == 0.0


def test_cancelled_returns_zero_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    metrics = engine._active_watch_metrics(
        active_watch={"status": "CANCELLED", "progress": "cancelled"},
        active_watch_history={"count": 1, "last_event": {"event": "WATCH_CANCELLED"}},
    )

    assert metrics["watch_health"] == "inactive"
    assert metrics["watch_probability_to_execute"] == 0.0


def test_missing_for_execute_high_reduces_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    lower_missing = engine._active_watch_metrics(
        active_watch={
            "status": "ACTIVE",
            "progress": "stable",
            "current_confidence": 0.7,
            "current_harmony_score": 0.65,
            "current_setup_maturity": 74.0,
            "initial_missing_for_execute": ["a", "b", "c"],
            "missing_for_execute": ["a"],
            "age_candles": 1,
            "expiration_candles": 12,
        },
        active_watch_history={"count": 1, "last_event": {"event": "WATCH_CREATED"}},
    )
    higher_missing = engine._active_watch_metrics(
        active_watch={
            "status": "ACTIVE",
            "progress": "stable",
            "current_confidence": 0.7,
            "current_harmony_score": 0.65,
            "current_setup_maturity": 74.0,
            "initial_missing_for_execute": ["a"],
            "missing_for_execute": ["a", "b", "c", "d"],
            "age_candles": 1,
            "expiration_candles": 12,
        },
        active_watch_history={"count": 1, "last_event": {"event": "WATCH_CREATED"}},
    )

    assert higher_missing["watch_probability_to_execute"] < lower_missing["watch_probability_to_execute"]


def test_age_near_expiration_reduces_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    young = engine._active_watch_metrics(
        active_watch={
            "status": "ACTIVE",
            "progress": "stable",
            "current_confidence": 0.72,
            "current_harmony_score": 0.66,
            "current_setup_maturity": 76.0,
            "initial_missing_for_execute": ["a", "b"],
            "missing_for_execute": ["a", "b"],
            "age_candles": 2,
            "expiration_candles": 12,
        },
        active_watch_history={"count": 1, "last_event": {"event": "WATCH_CREATED"}},
    )
    old = engine._active_watch_metrics(
        active_watch={
            "status": "ACTIVE",
            "progress": "stable",
            "current_confidence": 0.72,
            "current_harmony_score": 0.66,
            "current_setup_maturity": 76.0,
            "initial_missing_for_execute": ["a", "b"],
            "missing_for_execute": ["a", "b"],
            "age_candles": 10,
            "expiration_candles": 12,
        },
        active_watch_history={"count": 1, "last_event": {"event": "WATCH_CREATED"}},
    )

    assert old["watch_probability_to_execute"] < young["watch_probability_to_execute"]


def test_demo_report_shows_health_and_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.74,
        setup_maturity=75.0,
        harmony_score=0.64,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    report = engine.report_path.read_text(encoding="utf-8")
    assert "## Active Watch Metrics" in report
    assert "watch_health:" in report
    assert "watch_probability_to_execute:" in report
    assert "interpretation:" in report


def test_policy_low_probability_produces_drop(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    policy = engine._watch_execution_policy(
        active_watch={"status": "ACTIVE"},
        active_watch_metrics={"watch_health": "stable", "watch_probability_to_execute": 0.2},
    )

    assert policy["watch_policy_action"] == "DROP"
    assert policy["allowed_risk_mode"] == "blocked"


def test_policy_medium_probability_produces_observe(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    policy = engine._watch_execution_policy(
        active_watch={"status": "ACTIVE"},
        active_watch_metrics={"watch_health": "stable", "watch_probability_to_execute": 0.5},
    )

    assert policy["watch_policy_action"] == "OBSERVE"


def test_policy_prepare_reduced_range(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    policy = engine._watch_execution_policy(
        active_watch={"status": "ACTIVE"},
        active_watch_metrics={"watch_health": "stable", "watch_probability_to_execute": 0.7},
    )

    assert policy["watch_policy_action"] == "PREPARE_REDUCED"
    assert policy["allowed_risk_mode"] == "reduced"


def test_policy_prepare_normal_when_high_probability(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    policy = engine._watch_execution_policy(
        active_watch={"status": "ACTIVE"},
        active_watch_metrics={"watch_health": "stable", "watch_probability_to_execute": 0.85},
    )

    assert policy["watch_policy_action"] == "PREPARE_NORMAL"
    assert policy["allowed_risk_mode"] == "normal"


def test_aggressive_ob_watch_policy_never_prepares_normal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    policy = engine._watch_execution_policy(
        active_watch={"status": "ACTIVE", "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
        active_watch_metrics={"watch_health": "improving", "watch_probability_to_execute": 0.91},
    )

    assert policy["watch_policy_action"] == "PREPARE_REDUCED"
    assert policy["allowed_risk_mode"] == "reduced"


def _aggressive_candidate() -> dict:
    return {
        "entry_kind": "market",
        "signal_time": "2026-01-01T10:00:00+00:00",
        "entry_time": "2026-01-01T10:05:00+00:00",
        "direction": "sell",
        "setup_type": "AGG_REDUCED",
        "signal_type": "OB_AGGRESSIVE_REDUCED_SIGNAL",
        "active_family": "OB_REJECTION_AGGRESSIVE_WATCH",
        "entry_price": 4700.0,
        "stop_price": 4704.0,
        "target_price": 4695.4,
        "risk_per_unit": 4.0,
        "selected_rr": 1.15,
        "sl_logical_available": True,
        "rr_evaluable": True,
        "wick_rejection_quality": 0.82,
        "displacement_score": 100,
        "micro_bos": True,
        "micro_choch": False,
        "continuation_momentum": True,
        "reduced_signal_reason": "test",
    }


def _aggressive_intelligence(**overrides) -> dict:
    payload = _fake_intelligence_payload(
        action="WATCH",
        posture="aligned",
        signal=None,
        preferred_side="SELL",
        confidence=overrides.pop("confidence", 0.78),
        setup_maturity=overrides.pop("setup_maturity", 78.0),
        blockers=overrides.pop("blockers", []),
        operational_family="OB_REJECTION_AGGRESSIVE_WATCH",
    )
    candidate = overrides.pop("candidate", _aggressive_candidate())
    payload["overview"]["market_state"]["operational_family"] = "OB_REJECTION_AGGRESSIVE_WATCH"
    payload["overview"]["market_state"]["allowed_hour_by_strategy"] = overrides.pop("allowed_hour", True)
    payload["overview"]["market_state"]["quant_score"] = 100
    payload["overview"]["market_state"]["impulse_score"] = 100
    payload["overview"]["market_state"]["buy_mtf_score"] = 15
    payload["overview"]["market_state"]["sell_mtf_score"] = 73
    payload["overview"]["market_state"]["ob_rejection_families"] = {
        "active_family": "OB_REJECTION_AGGRESSIVE_WATCH",
        "institutional": {"active": False},
        "aggressive": {
            "active": True,
            "side": "SELL",
            "allows_normal_risk_directly": False,
            "reduced_signal_candidate": candidate,
        },
    }
    payload["event_risk"]["action"] = overrides.pop("event_action", "allow")
    return payload


def test_aggressive_ob_can_generate_reduced_signal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())

    signal = engine._build_ob_aggressive_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=_aggressive_intelligence(),
        active_watch={"operational_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is not None
    assert signal["signal_type"] == "OB_AGGRESSIVE_REDUCED_SIGNAL"
    assert signal["risk_mode"] == "reduced"


def test_aggressive_ob_preserves_sensei_manual_bias_signal_identity(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candidate = _aggressive_candidate()
    candidate["setup_type"] = "SENSEI_BIAS_REDUCED"
    candidate["signal_type"] = "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL"
    candidate["selected_rr"] = 2.0
    candidate["manual_bias_confirmation"] = True

    signal = engine._build_ob_aggressive_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=_aggressive_intelligence(candidate=candidate),
        active_watch={"operational_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is not None
    assert signal["setup_type"] == "SENSEI_BIAS_REDUCED"
    assert signal["signal_type"] == "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL"
    assert signal["selected_rr"] == 2.0
    assert signal["manual_bias_confirmation"] is True


def test_aggressive_ob_signal_forces_reduced_risk_even_if_watch_is_normal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    signal = {"active_family": "OB_REJECTION_AGGRESSIVE_WATCH"}

    decision = engine._execution_risk_binding(
        signal=signal,
        intelligence=_aggressive_intelligence(),
        active_watch={"allowed_risk_mode": "normal", "max_risk_multiplier": 1.0},
    )

    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["max_risk_multiplier"] == 0.5


def test_institutional_risk_binding_stays_intact(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())

    decision = engine._execution_risk_binding(
        signal={"active_family": "OB_REJECTION_INSTITUTIONAL_EXECUTE"},
        intelligence=_fake_intelligence_payload(action="EXECUTE", signal={"direction": "sell"}),
        active_watch={"allowed_risk_mode": "normal", "max_risk_multiplier": 1.0},
    )

    assert decision["allowed_risk_mode"] == "normal"
    assert decision["max_risk_multiplier"] == 1.0


def test_aggressive_ob_without_sl_rr_does_not_generate_signal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candidate = _aggressive_candidate()
    candidate["sl_logical_available"] = False
    candidate["rr_evaluable"] = False

    signal = engine._build_ob_aggressive_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=_aggressive_intelligence(candidate=candidate),
        active_watch={"operational_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is None


def test_session_q_learning_reduced_signal_uses_london_ny_memory(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candles = [
        {"open": 4500.0 + idx, "high": 4501.5 + idx, "low": 4499.2 + idx, "close": 4500.8 + idx}
        for idx in range(12)
    ]
    intelligence = _fake_intelligence_payload(
        action="WATCH",
        preferred_side="BUY",
        confidence=0.72,
        setup_maturity=78.0,
        blockers=[],
    )
    intelligence["overview"]["market_state"].update(
        {
            "hour_ny": 9,
            "session_tags": ["new_york", "ny_am"],
            "allowed_hour_by_strategy": True,
            "buy_mtf_score": 72,
            "sell_mtf_score": 34,
        }
    )
    intelligence["watch_trigger"] = {
        "side": "BUY",
        "missing_for_execute": ["Falta señal operativa confirmada."],
        "pattern_projection": {
            "session_opportunity": {
                "score": 0.88,
                "readiness": "armed",
                "session_tags": ["new_york", "ny_am"],
            },
            "q_learning_memory": {
                "policy_action": "BUY",
                "policy_quality": "moderate",
                "course_alignment": {"status": "aligned", "course_score": 0.82},
            },
            "professional_decision_matrix": {
                "selected_side": "BUY",
                "layer_synchronization": {"status": "synchronized"},
                "side_assessments": {
                    "BUY": {
                        "probability_to_confirm": 0.81,
                        "historical_bias": "favorable",
                        "structure_read": {
                            "displacement": True,
                            "micro_bos": True,
                            "continuation_momentum": False,
                        },
                        "liquidity_read": {"wick_rejection_quality": 65.0},
                    }
                },
            },
        },
    }

    signal = engine._build_session_q_learning_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=intelligence,
        snapshot={
            "timeframes": {"M5": {"last_bar_time": "2026-01-01T09:00:00+00:00"}},
            "candles": {"M5": candles},
        },
        active_watch={"status": "ACTIVE", "side": "BUY"},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is not None
    assert signal["signal_type"] == "SESSION_Q_LEARNING_REDUCED_SIGNAL"
    assert signal["direction"] == "buy"
    assert signal["selected_rr"] >= 1.2
    assert signal["stop_price"] < signal["entry_price"] < signal["target_price"]


def test_session_q_learning_reduced_signal_blocks_course_q_conflict(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candles = [
        {"open": 4500.0 + idx, "high": 4501.5 + idx, "low": 4499.2 + idx, "close": 4500.8 + idx}
        for idx in range(12)
    ]
    intelligence = _fake_intelligence_payload(
        action="WATCH",
        preferred_side="SELL",
        confidence=0.82,
        setup_maturity=82.0,
        blockers=[],
    )
    intelligence["overview"]["market_state"].update({"allowed_hour_by_strategy": True})
    intelligence["watch_trigger"] = {
        "side": "SELL",
        "missing_for_execute": ["Falta señal operativa confirmada."],
        "pattern_projection": {
            "session_opportunity": {"score": 0.9, "readiness": "armed"},
            "q_learning_memory": {
                "policy_action": "BUY",
                "policy_quality": "observe",
                "course_alignment": {"status": "conflict", "course_score": 0.42},
            },
            "professional_decision_matrix": {
                "selected_side": "SELL",
                "layer_synchronization": {"status": "conflicted"},
                "side_assessments": {
                    "SELL": {
                        "probability_to_confirm": 0.91,
                        "historical_bias": "mixed",
                        "structure_read": {"displacement": True, "micro_bos": True, "continuation_momentum": True},
                        "liquidity_read": {"wick_rejection_quality": 72.0},
                    }
                },
            },
        },
    }

    signal = engine._build_session_q_learning_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=intelligence,
        snapshot={"timeframes": {"M5": {"last_bar_time": "2026-01-01T09:00:00+00:00"}}, "candles": {"M5": candles}},
        active_watch={"status": "ACTIVE", "side": "SELL"},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is None


def test_session_q_learning_reduced_signal_blocks_unresolved_confirmations(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candles = [
        {"open": 4500.0 + idx, "high": 4501.5 + idx, "low": 4499.2 + idx, "close": 4500.8 + idx}
        for idx in range(12)
    ]
    intelligence = _fake_intelligence_payload(
        action="WATCH",
        preferred_side="SELL",
        confidence=0.82,
        setup_maturity=82.0,
        blockers=[],
    )
    intelligence["overview"]["market_state"].update({"allowed_hour_by_strategy": True})
    intelligence["watch_trigger"] = {
        "side": "SELL",
        "missing_for_execute": [
            "Falta señal operativa confirmada.",
            "El sesgo de temporalidades mayores aún no está suficientemente definido.",
        ],
        "pattern_projection": {
            "session_opportunity": {"score": 0.9, "readiness": "armed"},
            "q_learning_memory": {
                "policy_action": "SELL",
                "policy_quality": "moderate",
                "course_alignment": {"status": "aligned", "course_score": 0.82},
            },
            "professional_decision_matrix": {
                "selected_side": "SELL",
                "layer_synchronization": {"status": "synchronized"},
                "side_assessments": {
                    "SELL": {
                        "probability_to_confirm": 0.91,
                        "historical_bias": "favorable",
                        "structure_read": {"displacement": True, "micro_bos": True, "continuation_momentum": True},
                        "liquidity_read": {"wick_rejection_quality": 72.0},
                    }
                },
            },
        },
    }

    signal = engine._build_session_q_learning_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=intelligence,
        snapshot={"timeframes": {"M5": {"last_bar_time": "2026-01-01T09:00:00+00:00"}}, "candles": {"M5": candles}},
        active_watch={"status": "ACTIVE", "side": "SELL"},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is None


def test_aggressive_ob_without_micro_bos_or_continuation_does_not_generate_signal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candidate = _aggressive_candidate()
    candidate["micro_bos"] = False
    candidate["continuation_momentum"] = False

    signal = engine._build_ob_aggressive_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=_aggressive_intelligence(candidate=candidate),
        active_watch={"operational_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is None


def test_institutional_family_does_not_use_aggressive_reduced_signal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    intelligence = _aggressive_intelligence()
    intelligence["overview"]["market_state"]["operational_family"] = "OB_REJECTION_INSTITUTIONAL_EXECUTE"
    intelligence["overview"]["market_state"]["ob_rejection_families"]["active_family"] = "OB_REJECTION_INSTITUTIONAL_EXECUTE"
    intelligence["overview"]["market_state"]["ob_rejection_families"]["institutional"] = {"active": True}

    signal = engine._build_ob_aggressive_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=intelligence,
        active_watch={"operational_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is None


def test_policy_critical_limits_to_observe(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    policy = engine._watch_execution_policy(
        active_watch={"status": "ACTIVE"},
        active_watch_metrics={"watch_health": "critical", "watch_probability_to_execute": 0.9},
    )

    assert policy["watch_policy_action"] == "OBSERVE"
    assert policy["allowed_risk_mode"] == "blocked"


def test_policy_deteriorating_limits_to_prepare_reduced(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    policy = engine._watch_execution_policy(
        active_watch={"status": "ACTIVE"},
        active_watch_metrics={"watch_health": "deteriorating", "watch_probability_to_execute": 0.9},
    )

    assert policy["watch_policy_action"] == "PREPARE_REDUCED"
    assert policy["allowed_risk_mode"] == "reduced"


def test_policy_cancelled_or_expired_produces_drop(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    cancelled = engine._watch_execution_policy(
        active_watch={"status": "CANCELLED"},
        active_watch_metrics={"watch_health": "inactive", "watch_probability_to_execute": 0.9},
    )
    expired = engine._watch_execution_policy(
        active_watch={"status": "EXPIRED"},
        active_watch_metrics={"watch_health": "inactive", "watch_probability_to_execute": 0.9},
    )

    assert cancelled["watch_policy_action"] == "DROP"
    assert expired["watch_policy_action"] == "DROP"


def test_demo_report_shows_watch_policy(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.74,
        setup_maturity=75.0,
        harmony_score=0.64,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    report = engine.report_path.read_text(encoding="utf-8")
    assert "## Watch Execution Policy" in report
    assert "watch_policy_action:" in report
    assert "allowed_risk_mode:" in report
    assert "policy_reason:" in report


def test_drop_blocks_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={"direction": "buy"},
        intelligence={"execution_readiness": {"confidence": 0.9}},
        active_watch={
            "allowed_risk_mode": "blocked",
            "max_risk_multiplier": 0.0,
            "watch_policy_action": "DROP",
        },
    )

    assert decision["can_execute"] is False
    assert decision["allowed_risk_mode"] == "blocked"


def test_demo_confirmed_execute_signal_overrides_drop_with_reduced_risk(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())

    decision = engine._execution_risk_binding(
        signal={
            "direction": "sell",
            "entry_price": 4518.0,
            "stop_price": 4528.0,
            "target_price": 4498.0,
            "selected_rr": 2.0,
        },
        intelligence=_fake_intelligence_payload(action="EXECUTE", blockers=[]),
        active_watch={
            "allowed_risk_mode": "blocked",
            "max_risk_multiplier": 0.0,
            "watch_policy_action": "DROP",
        },
        account_is_demo=True,
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["max_risk_multiplier"] == 0.25
    assert decision["risk_binding_source"] == "demo_confirmed_signal_drop_override"


def test_demo_drop_override_still_respects_macro_blocks(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())

    decision = engine._execution_risk_binding(
        signal={
            "direction": "buy",
            "entry_price": 4518.0,
            "stop_price": 4508.0,
            "target_price": 4538.0,
            "selected_rr": 2.0,
        },
        intelligence=_fake_intelligence_payload(action="EXECUTE", blockers=[], event_action="block"),
        active_watch={
            "allowed_risk_mode": "blocked",
            "max_risk_multiplier": 0.0,
            "watch_policy_action": "DROP",
        },
        account_is_demo=True,
    )

    assert decision["can_execute"] is False
    assert decision["allowed_risk_mode"] == "blocked"


def test_drop_override_requires_demo_account(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())

    decision = engine._execution_risk_binding(
        signal={
            "direction": "sell",
            "entry_price": 4518.0,
            "stop_price": 4528.0,
            "target_price": 4498.0,
            "selected_rr": 2.0,
        },
        intelligence=_fake_intelligence_payload(action="EXECUTE", blockers=[]),
        active_watch={
            "allowed_risk_mode": "blocked",
            "max_risk_multiplier": 0.0,
            "watch_policy_action": "DROP",
        },
        account_is_demo=False,
    )

    assert decision["can_execute"] is False
    assert decision["allowed_risk_mode"] == "blocked"


def test_observe_blocks_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={"direction": "buy"},
        intelligence={"execution_readiness": {"confidence": 0.9}},
        active_watch={
            "allowed_risk_mode": "blocked",
            "max_risk_multiplier": 0.0,
            "watch_policy_action": "OBSERVE",
        },
    )

    assert decision["can_execute"] is False
    assert decision["allowed_risk_mode"] == "blocked"


def test_prepare_reduced_allows_reduced_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={"direction": "sell"},
        intelligence={"execution_readiness": {"confidence": 0.82}},
        active_watch={
            "allowed_risk_mode": "reduced",
            "max_risk_multiplier": 0.5,
            "watch_policy_action": "PREPARE_REDUCED",
        },
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["max_risk_multiplier"] == 0.5
    materialized = engine._materialize_execution_risk(execution_risk_decision=decision, base_risk=0.01)
    assert materialized["effective_risk"] == 0.005


def test_prepare_normal_allows_normal_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={"direction": "sell"},
        intelligence={"execution_readiness": {"confidence": 0.9}},
        active_watch={
            "allowed_risk_mode": "normal",
            "max_risk_multiplier": 1.0,
            "watch_policy_action": "PREPARE_NORMAL",
        },
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "normal"
    assert decision["max_risk_multiplier"] == 1.0
    materialized = engine._materialize_execution_risk(execution_risk_decision=decision, base_risk=0.01)
    assert materialized["effective_risk"] == 0.01


def test_execute_without_active_watch_and_low_confidence_does_not_execute(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={"direction": "buy"},
        intelligence={"execution_readiness": {"confidence": 0.78}},
        active_watch=None,
    )

    assert decision["can_execute"] is False
    assert decision["decision"] == "degraded_to_prepare_reduced"


def test_execute_without_active_watch_and_high_confidence_allows_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={"direction": "buy"},
        intelligence={"execution_readiness": {"confidence": 0.9}},
        active_watch=None,
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["max_risk_multiplier"] == 0.5
    assert decision["execution_mode"] == "direct_high_confidence_execution"


def test_demo_report_shows_risk_binding(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
        confidence=0.9,
        setup_maturity=90.0,
        harmony_score=0.8,
    )
    engine.run(symbol="XAUUSDm", dry_run=True)

    report = engine.report_path.read_text(encoding="utf-8")
    assert "## Watch Risk Binding" in report
    assert "allowed_risk_mode:" in report
    assert "max_risk_multiplier:" in report
    assert "effective_risk:" in report
    assert "execution_mode:" in report
    assert "risk_binding_source:" in report
    assert "execution_risk_decision:" in report


def test_watch_performance_report_without_history(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())

    engine._write_watch_performance_report()
    report = engine.watch_performance_report_path.read_text(encoding="utf-8")

    assert "classification: INSUFFICIENT_DATA" in report
    assert "total_watch_created: 0" in report


def test_watch_performance_report_with_watch_created(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    engine.active_watch_history_path.write_text(
        __import__("json").dumps(
            {
                "timestamp": "2026-01-01T10:00:00+00:00",
                "symbol": "XAUUSDm",
                "event": "WATCH_CREATED",
                "side": "SELL",
                "trigger_type": "bearish_confirmation",
                "confidence": 0.61,
                "harmony_score": 0.55,
                "setup_maturity": 68.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = engine._watch_performance_summary()

    assert summary["total_watch_created"] == 1
    assert summary["avg_confidence"] == 0.61


def test_watch_performance_counts_aggressive_ob_family(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    events = [
        {
            "timestamp": "2026-01-01T10:00:00+00:00",
            "symbol": "XAUUSDm",
            "event": "WATCH_CREATED",
            "side": "SELL",
            "trigger_type": "bearish_confirmation",
            "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH",
            "confidence": 0.7,
            "harmony_score": 0.6,
            "setup_maturity": 72.0,
        },
        {
            "timestamp": "2026-01-01T10:05:00+00:00",
            "symbol": "XAUUSDm",
            "event": "WATCH_TRIGGERED",
            "side": "SELL",
            "trigger_type": "bearish_confirmation",
            "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH",
        },
    ]
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(__import__("json").dumps(event) + "\n")

    summary = engine._watch_performance_summary()

    assert summary["ob_aggressive_created"] == 1
    assert summary["ob_aggressive_triggered"] == 1


def test_watch_performance_report_with_triggered(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    events = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CREATED", "side": "SELL", "trigger_type": "bearish_confirmation", "confidence": 0.7, "harmony_score": 0.6, "setup_maturity": 72.0},
        {"timestamp": "2026-01-01T10:05:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_TRIGGERED", "side": "SELL", "trigger_type": "bearish_confirmation"},
    ]
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(__import__("json").dumps(event) + "\n")

    summary = engine._watch_performance_summary()

    assert summary["triggered"] == 1
    assert summary["conversion_rate"] == 1.0


def test_watch_performance_report_with_cancelled(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    events = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CREATED", "side": "SELL", "trigger_type": "bearish_confirmation", "confidence": 0.7, "harmony_score": 0.6, "setup_maturity": 72.0},
        {"timestamp": "2026-01-01T10:05:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CANCELLED", "side": "SELL", "trigger_type": "bearish_confirmation", "reason": "macro block"},
    ]
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(__import__("json").dumps(event) + "\n")

    summary = engine._watch_performance_summary()

    assert summary["cancelled"] == 1
    assert summary["cancel_reason_top"][0] == "macro block"


def test_watch_performance_report_with_expired(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    events = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CREATED", "side": "SELL", "trigger_type": "bearish_confirmation", "confidence": 0.7, "harmony_score": 0.6, "setup_maturity": 72.0},
        {"timestamp": "2026-01-01T11:00:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_EXPIRED", "side": "SELL", "trigger_type": "bearish_confirmation", "reason": "timeout"},
    ]
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(__import__("json").dumps(event) + "\n")

    summary = engine._watch_performance_summary()

    assert summary["expired"] == 1
    assert summary["expire_reason_top"][0] == "timeout"


def test_watch_performance_report_classifies_too_strict(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    events = []
    for idx in range(5):
        events.append({"timestamp": f"2026-01-01T10:0{idx}:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CREATED", "side": "SELL", "trigger_type": "bearish_confirmation", "confidence": 0.6, "harmony_score": 0.55, "setup_maturity": 65.0})
    for idx in range(4):
        events.append({"timestamp": f"2026-01-01T11:0{idx}:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_EXPIRED", "side": "SELL", "trigger_type": "bearish_confirmation", "reason": "timeout"})
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(__import__("json").dumps(event) + "\n")

    summary = engine._watch_performance_summary()

    assert summary["classification"] == "TOO_STRICT"


def test_watch_performance_report_classifies_balanced(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    events = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CREATED", "side": "SELL", "trigger_type": "bearish_confirmation", "confidence": 0.7, "harmony_score": 0.6, "setup_maturity": 72.0},
        {"timestamp": "2026-01-01T10:05:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_TRIGGERED", "side": "SELL", "trigger_type": "bearish_confirmation"},
        {"timestamp": "2026-01-01T10:10:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CREATED", "side": "BUY", "trigger_type": "bullish_confirmation", "confidence": 0.69, "harmony_score": 0.61, "setup_maturity": 70.0},
        {"timestamp": "2026-01-01T10:15:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CANCELLED", "side": "BUY", "trigger_type": "bullish_confirmation", "reason": "side flip"},
        {"timestamp": "2026-01-01T10:20:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CREATED", "side": "SELL", "trigger_type": "bearish_confirmation", "confidence": 0.71, "harmony_score": 0.63, "setup_maturity": 74.0},
        {"timestamp": "2026-01-01T10:25:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_IMPROVING", "side": "SELL", "trigger_type": "bearish_confirmation"},
    ]
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(__import__("json").dumps(event) + "\n")

    summary = engine._watch_performance_summary()

    assert summary["classification"] == "BALANCED"


def test_watch_performance_report_classifies_insufficient_data(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    events = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_CREATED", "side": "SELL", "trigger_type": "bearish_confirmation", "confidence": 0.7, "harmony_score": 0.6, "setup_maturity": 72.0},
        {"timestamp": "2026-01-01T10:05:00+00:00", "symbol": "XAUUSDm", "event": "WATCH_IMPROVING", "side": "SELL", "trigger_type": "bearish_confirmation"},
    ]
    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.active_watch_history_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(__import__("json").dumps(event) + "\n")

    summary = engine._watch_performance_summary()

    assert summary["classification"] == "INSUFFICIENT_DATA"


def test_decision_source_audit_registers_complete_decision(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {"strategy_name": "MAXIMO MTF Quant Institutional v4", "parameters": {"allowed_hours_ny": [9]}},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
    )

    engine.run(symbol="XAUUSDm", dry_run=True)

    line = engine.decision_source_audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = __import__("json").loads(line)
    assert payload["symbol"] == "XAUUSDm"
    assert payload["base_strategy"]["variant"] == "v56_aggressive_filtered_b"
    assert payload["learned_knowledge"]["dominant_family"] == "OB Rejection"
    assert "decision_attribution" in payload


def test_decision_source_audit_detects_learned_knowledge_dominance(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    payload = engine._build_decision_source_audit(
        symbol="XAUUSDm",
        runtime={
            "strategy_variant": _Variant(),
            "snapshot": {"strategy_name": "MAXIMO", "parameters": {"allowed_hours_ny": [9]}},
        },
        signal=None,
        execution_status="no_signal",
        intelligence=_fake_intelligence_payload(action="WATCH", posture="aligned", signal=None, blockers=[]),
        active_watch=None,
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
        execution_risk_decision={"can_execute": False, "allowed_risk_mode": "reduced", "decision": "allowed"},
        account_status={"is_demo": True},
    )

    assert payload["decision_attribution"]["primary_driver"] == "learned_knowledge"


def test_decision_source_audit_detects_base_strategy_dominance(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    signal = {
        "direction": "sell",
        "setup_type": "AGG",
        "strategy_variant": "v56_aggressive_filtered_b",
        "session_variant": "all",
        "entry_kind": "market",
        "entry_price": 1.0,
        "stop_price": 2.0,
        "target_price": 0.5,
        "selected_rr": 1.5,
        "confidence": 80,
        "market_regime": "EXPANSION",
        "hour_ny": 9,
    }
    payload = engine._build_decision_source_audit(
        symbol="XAUUSDm",
        runtime={
            "strategy_variant": _Variant(),
            "snapshot": {"strategy_name": "MAXIMO", "parameters": {"allowed_hours_ny": [9]}},
        },
        signal=signal,
        execution_status="dry_run_signal_detected",
        intelligence=_fake_intelligence_payload(action="EXECUTE", posture="aligned", signal=signal, blockers=[]),
        active_watch=None,
        watch_execution_policy={"watch_policy_action": "PREPARE_NORMAL"},
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "normal", "decision": "allowed"},
        account_status={"is_demo": True},
    )

    assert payload["decision_attribution"]["is_base_strategy_driving"] is True


def test_decision_source_audit_detects_external_filter_dominance(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    intelligence = _fake_intelligence_payload(action="WATCH", posture="selective", signal=None, blockers=["hour_not_allowed"])
    intelligence["event_risk"]["action"] = "watch"
    payload = engine._build_decision_source_audit(
        symbol="XAUUSDm",
        runtime={
            "strategy_variant": _Variant(),
            "snapshot": {"strategy_name": "MAXIMO", "parameters": {"allowed_hours_ny": [9]}},
        },
        signal=None,
        execution_status="no_signal",
        intelligence=intelligence,
        active_watch=None,
        watch_execution_policy={"watch_policy_action": "OBSERVE"},
        execution_risk_decision={"can_execute": False, "allowed_risk_mode": "blocked", "decision": "blocked"},
        account_status={"is_demo": True},
    )

    assert payload["decision_attribution"]["primary_driver"] == "external_filter"


def test_decision_source_audit_detects_hour_mismatch(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    intelligence = _fake_intelligence_payload(action="WATCH", posture="selective", signal=None, blockers=["hour_not_allowed"])
    intelligence["overview"]["market_state"]["allowed_hour_by_strategy"] = False
    payload = engine._build_decision_source_audit(
        symbol="XAUUSDm",
        runtime={
            "strategy_variant": _Variant(),
            "snapshot": {"strategy_name": "MAXIMO", "parameters": {"allowed_hours_ny": [9, 10, 11]}},
        },
        signal=None,
        execution_status="no_signal",
        intelligence=intelligence,
        active_watch=None,
        watch_execution_policy={"watch_policy_action": "OBSERVE"},
        execution_risk_decision={"can_execute": False, "allowed_risk_mode": "blocked", "decision": "blocked"},
        account_status={"is_demo": True},
    )

    assert payload["strategy_time_config_mismatch"] is True


def test_demo_report_shows_decision_source_audit_summary(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    engine._load_runtime = lambda: {  # type: ignore[method-assign]
        "backtester": object(),
        "strategy_variant": _Variant(),
        "session_variant": _Session(),
        "snapshot": {"strategy_name": "MAXIMO MTF Quant Institutional v4", "parameters": {"allowed_hours_ny": [9]}},
    }
    watch_trigger = {
        "side": "SELL",
        "trigger_type": "bearish_confirmation",
        "required_conditions": ["Cierre M5 bajista."],
        "cancel_conditions": ["preferred_side cambia a BUY."],
        "upgrade_to_execute_if": ["signal_detected = true"],
        "expiration_logic": "Expira si el contexto cambia.",
        "missing_for_execute": ["Falta señal."],
    }
    engine.market_intelligence_engine.run_detailed = lambda symbol: _fake_intelligence_payload(  # type: ignore[method-assign]
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        watch_trigger=watch_trigger,
    )

    engine.run(symbol="XAUUSDm", dry_run=True)
    report = engine.report_path.read_text(encoding="utf-8")
    latest_signal = engine.signal_path.read_text(encoding="utf-8")

    assert "## Decision Source Audit" in report
    assert "primary_driver:" in report
    assert "strategy_time_config_mismatch:" in report
    assert "## Reasoning Snapshot" in report
    assert "### Market Coverage Assurance" in report
    assert "four_corner_scan:" in report
    assert "### Confirmation Checklist" in report
    assert '"reasoning_snapshot"' in latest_signal


def test_market_coverage_assurance_tracks_four_analysis_corners(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    snapshot = {
        "timeframes": {
            "M1": {"bars": 500},
            "M5": {"bars": 5000},
            "H1": {"bars": 2000},
        }
    }
    pattern_projection = {
        "dominant_family": "OB Rejection",
        "candidate_side": "SELL",
        "probable_market_move": "continuación bajista si confirma M5.",
        "historical_analogs": {"bias": "favorable", "win_rate": 0.62},
        "professional_decision_matrix": {
            "selected_side": "SELL",
            "best_option_reason": "SELL tiene mejor probabilidad.",
            "wait_for_liquidity_volatility": "Esperar barrida y cierre M5.",
            "side_assessments": {
                "SELL": {
                    "liquidity_read": {"liquidity_sweep_or_grab": True},
                    "structure_read": {"micro_bos": True},
                }
            },
            "management_plan": {
                "take_profit_plan": "Parcial en primera liquidez.",
                "trailing_plan": "Trailing detrás de estructura M1/M5.",
                "emergency_exit": "Salir si invalida microestructura.",
            },
        },
        "course_learning_sync": {"status": "aligned", "course_score": 0.9},
    }

    result = engine._market_coverage_assurance(
        snapshot=snapshot,
        intelligence=_fake_intelligence_payload(preferred_side="SELL"),
        watch_trigger={
            "candidate_side": "SELL",
            "setup_detected": "OB_REJECTION_AGGRESSIVE_WATCH",
            "ob_rejection_families": {"active_family": "OB_REJECTION_AGGRESSIVE_WATCH"},
        },
        pattern_projection=pattern_projection,
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.2, "BUY": -0.1}},
        signal=None,
        execution_risk_decision={"allowed_risk_mode": "reduced", "account_risk_percent": 5.0},
    )

    assert result["status"] == "synchronized"
    assert result["active_corners"] == 4
    assert result["corners"]["multi_timeframe"]["status"] == "active"
    assert result["corners"]["zones_order_blocks"]["status"] == "active"
    assert result["corners"]["liquidity_structure"]["status"] == "active"
    assert result["corners"]["memory_probability"]["status"] == "active"


def test_execution_risk_applied_history_event_is_recorded(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)
    signal = {"direction": "sell", "setup_type": "AGG"}
    decision = engine._materialize_execution_risk(
        execution_risk_decision={
            "allowed_risk_mode": "reduced",
            "max_risk_multiplier": 0.5,
            "execution_mode": "reduced_execution",
            "risk_application_reason": "test",
        },
        base_risk=0.01,
    )

    engine.active_watch_history_path.parent.mkdir(parents=True, exist_ok=True)
    engine._append_execution_risk_history_event(
        symbol="XAUUSDm",
        signal=signal,
        execution_risk_decision=decision,
    )

    content = engine.active_watch_history_path.read_text(encoding="utf-8")
    assert '"event": "WATCH_EXECUTION_RISK_APPLIED"' in content
    assert '"effective_risk": 0.005' in content
