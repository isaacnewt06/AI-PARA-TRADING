from __future__ import annotations

import json
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
                "H4": {"bars": 1000, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": self.last_bar_time},
                "D1": {"bars": 500, "first_bar_time": "2026-01-01T00:00:00+00:00", "last_bar_time": self.last_bar_time},
            },
            "candles": {"M1": [], "M5": [], "H1": [], "H4": [], "D1": []},
        }

    def read_execution_environment(self, *, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "execution_viability": "SAFE",
            "live_spread": 0.08,
            "slippage_estimated": 0.01,
            "reason": "test execution environment is safe",
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


def test_directional_synchronization_realigns_stale_buy_watch_to_sensei_sell(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    candidate = {
        "direction": "sell",
        "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
        "manual_bias_confirmation": True,
        "sl_logical_available": True,
        "rr_evaluable": True,
        "entry_price": 4464.0,
        "stop_price": 4478.0,
        "target_price": 4436.0,
    }
    intelligence = _fake_intelligence_payload(
        action="WATCH",
        preferred_side="NEUTRAL",
        confidence=0.64,
        setup_maturity=64.0,
        harmony_score=0.48,
        operational_family="OB_REJECTION_AGGRESSIVE_WATCH",
        blockers=[],
        watch_trigger={
            "side": "NEUTRAL",
            "candidate_side": "SELL",
            "trigger_type": "neutral_observation",
            "required_conditions": ["El mercado define dirección preferida BUY o SELL."],
            "missing_for_execute": [
                "Falta señal operativa confirmada.",
                "El setup_maturity actual (64.0) aún no supera el umbral de preparacion.",
            ],
            "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH",
            "ob_rejection_families": {},
        },
    )
    ob_families = intelligence["overview"]["market_state"]["ob_rejection_families"]
    ob_families["manual_bias"] = {"active": True, "side": "SELL", "reduced_signal_candidate": candidate}
    ob_families["aggressive"] = {
        "active": True,
        "side": "SELL",
        "checks": {"sensei_manual_bias": {"active": True, "side": "SELL", "reduced_signal_candidate": candidate}},
        "reduced_signal_candidate": candidate,
    }
    active_watch = {
        "symbol": "XAUUSDm",
        "side": "BUY",
        "status": "ACTIVE",
        "trigger_type": "bullish_confirmation",
        "created_candle_time": "2026-01-01T10:00:00+00:00",
        "initial_confidence": 0.55,
        "initial_harmony_score": 0.42,
        "initial_setup_maturity": 55.0,
        "missing_for_execute": [],
    }

    result = engine._apply_directional_synchronization(
        symbol="XAUUSDm",
        intelligence=intelligence,
        active_watch=active_watch,
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.16, "BUY": -0.05}},
        market_pulse={"score": 90.0},
    )

    assert result["changed"] is True
    assert result["active_watch"]["side"] == "SELL"
    assert result["active_watch"]["trigger_type"] == "bearish_confirmation"
    assert result["intelligence"]["overview"]["market_state"]["preferred_side"] == "SELL"
    assert result["intelligence"]["execution_readiness"]["setup_maturity"] >= 69.0
    assert result["intelligence"]["execution_readiness"]["confidence"] >= 0.65
    assert result["summary"]["executable_bias_sync"] is True


def test_directional_synchronization_does_not_boost_when_q_learning_contradicts(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    candidate = {
        "direction": "sell",
        "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
        "manual_bias_confirmation": True,
        "sl_logical_available": True,
        "rr_evaluable": True,
    }
    intelligence = _fake_intelligence_payload(
        action="WATCH",
        preferred_side="NEUTRAL",
        confidence=0.64,
        setup_maturity=64.0,
        operational_family="OB_REJECTION_AGGRESSIVE_WATCH",
        blockers=[],
        watch_trigger={"side": "NEUTRAL", "candidate_side": "SELL", "missing_for_execute": [], "required_conditions": []},
    )
    ob_families = intelligence["overview"]["market_state"]["ob_rejection_families"]
    ob_families["manual_bias"] = {"active": True, "side": "SELL", "reduced_signal_candidate": candidate}

    result = engine._apply_directional_synchronization(
        symbol="XAUUSDm",
        intelligence=intelligence,
        active_watch=None,
        q_learning_decision={"q_policy_action": "BUY", "q_values": {"SELL": -0.02, "BUY": 0.2}},
        market_pulse={"score": 90.0},
    )

    assert result["summary"]["executable_bias_sync"] is False
    assert result["intelligence"]["execution_readiness"]["setup_maturity"] == 64.0


def test_higher_timeframe_context_reads_h4_and_d1_bias(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]

    def candles(start: float, step: float, count: int = 24) -> list[dict]:
        result = []
        for index in range(count):
            close = start + (step * index)
            result.append({"open": close - (step * 0.4), "high": close + 1.0, "low": close - 1.0, "close": close})
        return result

    context = engine._build_higher_timeframe_context(
        snapshot={
            "candles": {
                "H1": candles(100.0, -0.3),
                "H4": candles(105.0, -0.6),
                "D1": candles(110.0, -0.9),
            }
        }
    )

    assert context["status"] == "available"
    assert context["major_bias"] == "SELL"
    assert context["timeframes"]["H4"]["bias"] == "SELL"
    assert context["timeframes"]["D1"]["bias"] == "SELL"
    assert context["alignment_score"] > 0.9


def test_directional_synchronization_uses_higher_timeframe_compass(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    intelligence = _fake_intelligence_payload(
        action="WATCH",
        preferred_side="NEUTRAL",
        confidence=0.61,
        setup_maturity=62.0,
        blockers=[],
        watch_trigger={"side": "NEUTRAL", "candidate_side": "NEUTRAL", "missing_for_execute": [], "required_conditions": []},
    )
    htf_context = {
        "status": "available",
        "major_bias": "SELL",
        "alignment_score": 1.0,
        "weighted_bias": {"BUY": 0.0, "SELL": 4.6},
        "conflicts": [],
        "timeframes": {
            "H1": {"bias": "SELL"},
            "H4": {"bias": "SELL"},
            "D1": {"bias": "SELL"},
        },
    }
    intelligence = engine._inject_higher_timeframe_context(
        intelligence=intelligence,
        higher_timeframe_context=htf_context,
    )

    result = engine._apply_directional_synchronization(
        symbol="XAUUSDm",
        intelligence=intelligence,
        active_watch=None,
        q_learning_decision={"q_policy_action": "SELL", "q_values": {"SELL": 0.08, "BUY": 0.01}},
        market_pulse={"score": 84.0},
    )

    summary = result["summary"]
    assert summary["higher_timeframe_major_bias"] == "SELL"
    assert summary["status"] == "synchronized"
    assert result["intelligence"]["overview"]["market_state"]["preferred_side"] == "SELL"
    assert result["intelligence"]["watch_trigger"]["trigger_type"] == "bearish_confirmation"


def test_synchronized_watch_contract_removes_opposite_side_language(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]

    required = engine._synchronized_required_conditions(
        side="BUY",
        existing=[
            "Cierre M5 bajista confirmando rechazo o continuidad a favor de SELL.",
            "higher_timeframe_bias en SELL o al menos no contradictorio.",
            "setup_maturity >= 69",
            "event_action = allow al momento del disparo.",
        ],
    )
    cancel = engine._synchronized_cancel_conditions(
        side="BUY",
        existing=[
            "El lado candidato cambia a BUY.",
            "higher_timeframe_bias cambia claramente contra SELL.",
            "harmony_score cae por debajo de 0.35.",
        ],
    )

    assert required[0] == "Cierre M5 alcista con micro BOS/continuación a favor de BUY."
    assert not any("higher_timeframe_bias en SELL" in item for item in required)
    assert "El lado candidato cambia a SELL." in cancel
    assert "higher_timeframe_bias cambia claramente contra BUY." in cancel
    assert "El lado candidato cambia a BUY." not in cancel


def test_position_management_skips_invalid_min_lot_partial_and_records_history(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    snapshot = {
        "timeframes": {"M1": {"last_bar_time": "2026-01-01T10:00:00+00:00"}, "M5": {"last_bar_time": "2026-01-01T10:00:00+00:00"}},
        "candles": {"M1": [{"open": 95.0, "high": 96.0, "low": 94.0, "close": 94.0}], "M5": [{"open": 95.0, "high": 96.0, "low": 94.0, "close": 94.0}]},
    }
    positions = [
        {
            "ticket": 3,
            "type": 1,
            "symbol": "XAUUSDm",
            "price_open": 100.0,
            "sl": 110.0,
            "tp": 85.0,
            "volume": 0.01,
            "price_current": 94.0,
            "profit": 6.0,
        }
    ]

    result = engine._manage_open_positions(symbol="XAUUSDm", positions=positions, snapshot=snapshot, dry_run=False)

    assert bridge.partial_closed == []
    assert any(action["action"] == "partial_skipped_min_lot_fallback" for action in result["actions"])
    assert any(action["action"] == "protect_sl" for action in result["actions"])
    assert result["feedback"]["invalid_partial_fallback"] is True
    lines = engine.position_management_history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2
    assert json.loads(lines[0])["action_taken"] == "partial_skipped_min_lot_fallback"


def test_position_management_fast_exits_when_profit_is_given_back_after_mfe(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    engine.position_management_state_path.write_text(
        json.dumps({"4": {"best_price": 94.0, "max_favorable_r": 0.6}}),
        encoding="utf-8",
    )
    snapshot = {
        "timeframes": {"M1": {"last_bar_time": "2026-01-01T10:00:00+00:00"}, "M5": {"last_bar_time": "2026-01-01T10:00:00+00:00"}},
        "candles": {"M1": [{"open": 99.0, "high": 101.0, "low": 98.0, "close": 101.0}], "M5": [{"open": 99.0, "high": 101.0, "low": 98.0, "close": 101.0}]},
    }
    positions = [
        {
            "ticket": 4,
            "type": 1,
            "symbol": "XAUUSDm",
            "price_open": 100.0,
            "sl": 110.0,
            "tp": 85.0,
            "volume": 0.01,
            "price_current": 101.0,
            "profit": -1.0,
        }
    ]

    result = engine._manage_open_positions(symbol="XAUUSDm", positions=positions, snapshot=snapshot, dry_run=False)

    assert result["updates_sent"] == 1
    assert bridge.partial_closed[0]["volume_lots"] == 0.01
    assert result["actions"][0]["action"] == "fast_exit"
    assert result["feedback"]["fast_exit_taken"] is True
    assert result["feedback"]["gave_back_profit"] is True
    history = [json.loads(line) for line in engine.position_management_history_path.read_text(encoding="utf-8").splitlines()]
    assert history[-1]["action_taken"] == "fast_exit"


def test_position_management_fast_exits_near_breakeven_after_early_scalp_mfe(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    engine.position_management_state_path.write_text(
        json.dumps({"44": {"best_price": 96.8, "max_favorable_r": 0.32}}),
        encoding="utf-8",
    )
    snapshot = {
        "timeframes": {"M1": {"last_bar_time": "2026-01-01T10:00:00+00:00"}, "M5": {"last_bar_time": "2026-01-01T10:00:00+00:00"}},
        "candles": {"M1": [{"open": 99.0, "high": 100.0, "low": 98.8, "close": 99.6}], "M5": [{"open": 99.0, "high": 100.0, "low": 98.8, "close": 99.6}]},
    }
    positions = [
        {
            "ticket": 44,
            "type": 1,
            "symbol": "XAUUSDm",
            "price_open": 100.0,
            "sl": 110.0,
            "tp": 85.0,
            "volume": 0.01,
            "price_current": 99.6,
            "profit": 0.4,
        }
    ]

    result = engine._manage_open_positions(symbol="XAUUSDm", positions=positions, snapshot=snapshot, dry_run=False)

    assert result["updates_sent"] == 1
    assert bridge.partial_closed[0]["volume_lots"] == 0.01
    assert result["actions"][0]["action"] == "fast_exit"
    assert "después de +0.3R" in result["actions"][0]["reason"]
    history = [json.loads(line) for line in engine.position_management_history_path.read_text(encoding="utf-8").splitlines()]
    assert history[-1]["current_r"] > 0
    assert history[-1]["action_taken"] == "fast_exit"
    state = json.loads(engine.position_management_state_path.read_text(encoding="utf-8"))
    assert state["_reentry_cooldowns"][0]["side"] == "SELL"
    assert "fast exit" in state["_reentry_cooldowns"][0]["reason"]


def test_fast_exit_state_creates_reentry_cooldown_below_old_mfe_threshold(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]

    cooldown = engine._reentry_cooldown_from_position_state(
        payload={
            "symbol": "XAUUSDm",
            "side": "BUY",
            "entry": 4508.0,
            "current": 4508.4,
            "best_price": 4514.0,
            "worst_price": 4507.5,
            "initial_stop": 4489.0,
            "initial_risk": 19.0,
            "max_favorable_r": 0.33,
            "fast_exit_taken": True,
            "closed_by_fast_exit": True,
            "closed_reason": "MAXIMO fast exit: zona perdió momentum.",
        },
        symbol="XAUUSDm",
    )

    assert cooldown is not None
    assert cooldown["side"] == "BUY"
    assert cooldown["max_favorable_r"] == 0.33
    assert "fast exit" in cooldown["reason"]


def test_position_management_uses_initial_risk_after_sl_is_protected(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    engine.position_management_state_path.write_text(
        json.dumps({"5": {"initial_stop": 95.0, "initial_risk": 5.0, "best_price": 103.0, "max_favorable_r": 0.6}}),
        encoding="utf-8",
    )
    snapshot = {
        "timeframes": {"M1": {"last_bar_time": "2026-01-01T10:00:00+00:00"}, "M5": {"last_bar_time": "2026-01-01T10:00:00+00:00"}},
        "candles": {"M1": [{"open": 102.5, "high": 103.2, "low": 102.0, "close": 103.0}], "M5": [{"open": 102.5, "high": 103.2, "low": 102.0, "close": 103.0}]},
    }
    positions = [
        {
            "ticket": 5,
            "type": 0,
            "symbol": "XAUUSDm",
            "price_open": 100.0,
            "sl": 100.1,
            "tp": 110.0,
            "volume": 0.01,
            "price_current": 103.0,
            "profit": 3.0,
        }
    ]

    result = engine._manage_open_positions(symbol="XAUUSDm", positions=positions, snapshot=snapshot, dry_run=False)

    assert result["actions"][0]["action"] != "skip"
    history = [json.loads(line) for line in engine.position_management_history_path.read_text(encoding="utf-8").splitlines()]
    assert history[-1]["mfe_r"] >= 0.6
    state = json.loads(engine.position_management_state_path.read_text(encoding="utf-8"))
    assert state["5"]["initial_risk"] == 5.0


def test_position_management_creates_reentry_cooldown_after_protected_trade_closes(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    engine.position_management_state_path.write_text(
        json.dumps(
            {
                "6": {
                    "symbol": "XAUUSDm",
                    "side": "BUY",
                    "entry": 100.0,
                    "current": 100.3,
                    "initial_stop": 95.0,
                    "initial_risk": 5.0,
                    "target": 110.0,
                    "best_price": 103.0,
                    "worst_price": 99.0,
                    "max_favorable_r": 0.6,
                    "be_applied": True,
                    "protection_level": "breakeven_after_0_5r",
                }
            }
        ),
        encoding="utf-8",
    )
    snapshot = {
        "timeframes": {"M1": {"last_bar_time": "2026-01-01T10:05:00+00:00"}},
        "candles": {"M1": [{"close": 100.3}]},
    }

    result = engine._manage_open_positions(symbol="XAUUSDm", positions=[], snapshot=snapshot, dry_run=False)

    assert result["status"] == "inactive"
    state = json.loads(engine.position_management_state_path.read_text(encoding="utf-8"))
    assert "6" not in state
    assert state["_reentry_cooldowns"][0]["side"] == "BUY"
    assert state["_reentry_cooldowns"][0]["max_favorable_r"] == 0.6


def test_reentry_cooldown_blocks_same_side_same_zone_signal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    engine.position_management_state_path.write_text(
        json.dumps(
            {
                "_reentry_cooldowns": [
                    {
                        "status": "ACTIVE",
                        "symbol": "XAUUSDm",
                        "side": "BUY",
                        "entry": 100.0,
                        "zone_low": 99.0,
                        "zone_high": 103.0,
                        "initial_risk": 5.0,
                        "expires_at": "2027-01-01T10:25:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = engine._apply_reentry_cooldown_guard(
        symbol="XAUUSDm",
        signal={"direction": "buy", "entry_price": 101.0, "stop_price": 96.0, "risk_per_unit": 5.0},
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.5},
    )

    assert result["can_execute"] is False
    assert result["execution_status"] == "blocked_by_reentry_cooldown"
    assert result["reentry_cooldown_guard"]["blocked"] is True


def test_reentry_cooldown_allows_other_side_or_fresh_zone(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    bridge = _FakeBridge()
    engine = MaximoQuantV4DemoEngine(settings, bridge=bridge)  # type: ignore[arg-type]
    engine.position_management_state_path.write_text(
        json.dumps(
            {
                "_reentry_cooldowns": [
                    {
                        "status": "ACTIVE",
                        "symbol": "XAUUSDm",
                        "side": "BUY",
                        "entry": 100.0,
                        "zone_low": 99.0,
                        "zone_high": 103.0,
                        "initial_risk": 5.0,
                        "expires_at": "2027-01-01T10:25:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    opposite_side = engine._apply_reentry_cooldown_guard(
        symbol="XAUUSDm",
        signal={"direction": "sell", "entry_price": 101.0, "stop_price": 106.0, "risk_per_unit": 5.0},
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.5},
    )
    fresh_zone = engine._apply_reentry_cooldown_guard(
        symbol="XAUUSDm",
        signal={"direction": "buy", "entry_price": 112.0, "stop_price": 107.0, "risk_per_unit": 5.0},
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.5},
    )

    assert opposite_side["can_execute"] is True
    assert fresh_zone["can_execute"] is True


def test_reduced_signal_quality_gate_blocks_wait_retest_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]

    result = engine._apply_execution_quality_gate(
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.5},
        signal={"direction": "buy", "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL"},
        positions=[],
        final_confirmation={"final_confirmation_score": 60.0},
        entry_quality={"entry_quality_score": 55.0, "decision": "WAIT_RETEST"},
        execution_readiness={"execution_readiness_score": 62.0},
        armed_retest={"action": "ARMED_RETEST_DROP"},
    )

    assert result["can_execute"] is False
    assert result["execution_status"] == "blocked_by_reduced_signal_quality_gate"


def test_reduced_signal_quality_gate_allows_clean_execution_ready(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]

    result = engine._apply_execution_quality_gate(
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.5},
        signal={"direction": "sell", "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL"},
        positions=[],
        final_confirmation={"final_confirmation_score": 78.0},
        entry_quality={"entry_quality_score": 79.0, "decision": "EXECUTION_READY"},
        execution_readiness={"execution_readiness_score": 82.0},
        armed_retest={"action": "ARMED_RETEST_DROP"},
    )

    assert result["can_execute"] is True


def test_same_cycle_fast_exit_guard_blocks_same_side_reentry(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]

    result = engine._apply_same_cycle_fast_exit_reentry_guard(
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "reduced", "max_risk_multiplier": 0.5},
        signal={"direction": "buy", "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL"},
        position_management={
            "actions": [
                {
                    "action": "fast_exit",
                    "side": "BUY",
                    "reason": "recuperó entrada/casi BE después de +0.3R",
                }
            ]
        },
    )

    assert result["can_execute"] is False
    assert result["execution_status"] == "blocked_by_same_cycle_fast_exit_reentry"


def test_market_pulse_blocks_dead_market_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    pulse = {"score": 24.0, "label": "dead_market"}

    result = engine._apply_market_pulse_risk_overlay(
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "normal", "max_risk_multiplier": 1.0},
        market_pulse=pulse,
        signal={"direction": "sell"},
    )

    assert result["can_execute"] is False
    assert result["execution_status"] == "blocked_by_market_pulse"


def test_market_pulse_reduces_weak_market_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    pulse = {"score": 44.0, "label": "observe"}

    result = engine._apply_market_pulse_risk_overlay(
        execution_risk_decision={"can_execute": True, "allowed_risk_mode": "normal", "max_risk_multiplier": 1.0},
        market_pulse=pulse,
        signal={"direction": "buy"},
    )

    assert result["allowed_risk_mode"] == "reduced"
    assert result["max_risk_multiplier"] == 0.25
    assert result["execution_mode"] == "market_pulse_reduced_execution"


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


def test_direction_consistency_guard_allows_weak_stale_q_learning_conflict(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    intelligence = _fake_intelligence_payload(
        preferred_side="BUY",
        watch_trigger={
            "side": "BUY",
            "pattern_projection": {
                "side_probability_comparison": {"selected_side": "BUY"},
                "professional_decision_matrix": {
                    "selected_side": "BUY",
                    "side_assessments": {"BUY": {"probability_to_confirm": 0.91}},
                    "layer_synchronization": {"status": "synchronized"},
                    "course_learning_sync": {"status": "aligned", "course_score": 1.0},
                },
            },
        },
    )

    result = engine._signal_direction_consistency_guard(
        signal={"direction": "buy"},
        intelligence=intelligence,
        active_watch={"side": "BUY"},
        q_learning_decision={
            "q_policy_action": "SELL",
            "value_gap": 0.05,
            "strategy_harmony_matrix": {
                "selected_side": "BUY",
                "agreement_ratio": 0.75,
                "layer_agreement_score": 1.0,
                "q_value_gap": 0.05,
                "course_status": "aligned",
                "course_score": 1.0,
                "conflicts": ["persistent_q_learning=SELL", "historical_backtest_prior=SELL"],
            },
        },
    )

    assert result["allowed"] is True
    assert result["conflicts"] == ["persistent_q_learning_policy"]


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
        signal={
            "direction": "buy",
            "setup_type": "COUNTERTREND_REVERSAL_SCALP",
            "countertrend_reversal_scalp": True,
            "liquidity_sweep": True,
            "micro_bos": True,
            "displacement_score": 82,
            "risk_mode": "reduced",
            "entry_price": 100.0,
            "stop_price": 99.7,
        },
        intelligence=intelligence,
        active_watch={"side": "SELL"},
        q_learning_decision={"q_policy_action": "BUY"},
    )

    assert result["allowed"] is True
    assert "reversal scalp" in result["reason"]


def test_direction_consistency_guard_allows_armed_retest_against_stale_q_learning(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())  # type: ignore[arg-type]
    intelligence = _fake_intelligence_payload(preferred_side="BUY")

    result = engine._signal_direction_consistency_guard(
        signal={
            "direction": "buy",
            "signal_type": "ARMED_RETEST_REDUCED_SIGNAL",
            "confidence": 78,
            "selected_rr": 1.35,
            "micro_bos": True,
            "manual_bias_confirmation": True,
            "continuation_momentum": True,
        },
        intelligence=intelligence,
        active_watch={"side": "BUY"},
        q_learning_decision={"q_policy_action": "SELL"},
    )

    assert result["allowed"] is True
    assert result["conflicts"] == ["persistent_q_learning_policy"]
    assert result["armed_retest_q_learning_override"] is True


def test_direction_consistency_guard_blocks_countertrend_without_scalp_evidence(tmp_path: Path) -> None:
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
                },
            },
        },
    )

    result = engine._signal_direction_consistency_guard(
        signal={"direction": "buy", "countertrend_reversal_scalp": True, "displacement_score": 90},
        intelligence=intelligence,
        active_watch={"side": "SELL"},
        q_learning_decision={"q_policy_action": "SELL"},
    )

    assert result["allowed"] is False
    assert "COUNTERTREND_REVERSAL_SCALP" in result["reason"]


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
    assert result["execution_recovery_plan"]["status"] == "WAIT_FOR_RETEST_WITH_COMPACT_SL"
    assert "No perseguir" in result["execution_recovery_plan"]["required_conditions"][0]
    assert result["execution_recovery_plan"]["max_risk_per_unit_for_min_lot"] > 0


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
        "micro_bos": True,
        "displacement_score": 76,
        "continuation_momentum": 0.72,
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
        "micro_bos": True,
        "displacement_score": 76,
        "continuation_momentum": 0.72,
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


def test_resolve_execution_status_uses_ai_chain_not_raw_intelligence_action() -> None:
    status = MaximoQuantV4DemoEngine._resolve_execution_status(
        signal={"entry_kind": "market", "direction": "sell"},
        positions=[],
        execution_risk_decision={
            "can_execute": False,
            "execution_status": "blocked_by_final_confirmation",
        },
        dry_run=False,
    )

    assert status == "blocked_by_final_confirmation"


def test_ai_execution_decision_label_reflects_unified_chain() -> None:
    label = MaximoQuantV4DemoEngine._ai_execution_decision_label(
        signal={"direction": "sell"},
        execution_risk_decision={"can_execute": False},
        final_confirmation={"decision": "BLOCK"},
        execution_status="blocked_by_final_confirmation",
    )

    assert label == "BLOCK"


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

    assert result["execution_status"].startswith("blocked_")
    assert result["ai_execution_decision"] == "BLOCK"
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


def test_armed_retest_signal_can_override_observe_watch_as_reduced(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={
            "signal_type": "ARMED_RETEST_REDUCED_SIGNAL",
            "active_family": "ARMED_RETEST",
            "quality": "B",
        },
        intelligence=_fake_intelligence_payload(
            action="EXECUTE",
            confidence=0.8,
            setup_maturity=82.0,
        ),
        active_watch={
            "status": "ACTIVE",
            "watch_policy_action": "OBSERVE",
            "allowed_risk_mode": "blocked",
            "max_risk_multiplier": 0.0,
            "current_confidence": 0.8,
            "current_harmony_score": 0.7,
            "current_setup_maturity": 82.0,
        },
        account_is_demo=True,
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["risk_binding_source"] == "armed_retest"


def test_armed_retest_signal_can_override_stale_drop_watch_as_reduced(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={
            "signal_type": "ARMED_RETEST_REDUCED_SIGNAL",
            "active_family": "ARMED_RETEST",
            "quality": "B",
        },
        intelligence=_fake_intelligence_payload(
            action="EXECUTE",
            confidence=0.81,
            setup_maturity=82.0,
        ),
        active_watch={
            "status": "ACTIVE",
            "watch_policy_action": "DROP",
            "allowed_risk_mode": "blocked",
            "max_risk_multiplier": 0.0,
            "current_confidence": 0.81,
            "current_harmony_score": 0.7,
            "current_setup_maturity": 82.0,
        },
        account_is_demo=True,
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["risk_binding_source"] == "armed_retest"


def test_m1_micro_trigger_can_override_observe_watch_as_reduced(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={
            "signal_type": "M1_MICRO_TRIGGER_REDUCED_SIGNAL",
            "active_family": "M1_MICRO_TRIGGER",
            "quality": "B",
        },
        intelligence=_fake_intelligence_payload(
            action="EXECUTE",
            confidence=0.78,
            setup_maturity=80.0,
        ),
        active_watch={
            "status": "ACTIVE",
            "watch_policy_action": "OBSERVE",
            "allowed_risk_mode": "blocked",
            "max_risk_multiplier": 0.0,
            "current_confidence": 0.78,
            "current_harmony_score": 0.7,
            "current_setup_maturity": 80.0,
        },
        account_is_demo=True,
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["max_risk_multiplier"] == 0.25
    assert decision["risk_binding_source"] == "m1_micro_trigger"


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


def test_sensei_manual_bias_generates_reduced_signal_without_active_aggressive_family(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candidate = _aggressive_candidate()
    candidate.update(
        {
            "setup_type": "SENSEI_BIAS_REDUCED",
            "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
            "signal_time": "2027-01-01T10:00:00+00:00",
            "manual_bias_confirmation": True,
            "selected_rr": 2.0,
        }
    )
    intelligence = _aggressive_intelligence(candidate=candidate, confidence=0.74, setup_maturity=74.0)
    intelligence["overview"]["market_state"]["operational_family"] = "NONE"
    intelligence["overview"]["market_state"]["ob_rejection_families"]["active_family"] = "NONE"
    intelligence["overview"]["market_state"]["ob_rejection_families"]["aggressive"]["active"] = False
    intelligence["overview"]["market_state"]["ob_rejection_families"]["manual_bias"] = {
        "active": True,
        "side": "SELL",
        "reduced_signal_candidate": candidate,
    }

    signal = engine._build_sensei_manual_bias_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=intelligence,
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is not None
    assert signal["direction"] == "sell"
    assert signal["signal_type"] == "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL"
    assert signal["risk_mode"] == "reduced"


def test_sensei_manual_bias_does_not_chase_stale_signal(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candidate = _aggressive_candidate()
    candidate.update(
        {
            "setup_type": "SENSEI_BIAS_REDUCED",
            "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
            "signal_time": "2020-01-01T10:00:00+00:00",
            "manual_bias_confirmation": True,
        }
    )
    intelligence = _aggressive_intelligence(candidate=candidate, confidence=0.74, setup_maturity=74.0)
    intelligence["overview"]["market_state"]["ob_rejection_families"]["manual_bias"] = {
        "active": True,
        "side": "SELL",
        "reduced_signal_candidate": candidate,
    }

    signal = engine._build_sensei_manual_bias_reduced_signal(
        symbol="XAUUSDm",
        runtime={"strategy_variant": _Variant(), "session_variant": _Session()},
        intelligence=intelligence,
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED", "allowed_risk_mode": "reduced"},
    )

    assert signal is None


def test_missed_opportunity_learning_tracks_unexecuted_sensei_candidate(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    candidate = _aggressive_candidate()
    candidate.update(
        {
            "setup_type": "SENSEI_BIAS_REDUCED",
            "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
            "signal_time": "2027-01-01T10:00:00+00:00",
            "manual_bias_confirmation": True,
            "entry_price": 100.0,
            "stop_price": 105.0,
            "target_price": 90.0,
            "risk_per_unit": 5.0,
        }
    )
    intelligence = _aggressive_intelligence(candidate=candidate, confidence=0.74, setup_maturity=74.0)
    intelligence["overview"]["market_state"]["ob_rejection_families"]["manual_bias"] = {
        "active": True,
        "side": "SELL",
        "reduced_signal_candidate": candidate,
    }
    snapshot = {"candles": {"M1": [{"close": 100.0}]}, "timeframes": {"M1": {"last_bar_time": "2027-01-01T10:00:00+00:00"}}}

    result = engine._track_missed_opportunity_learning(
        symbol="XAUUSDm",
        intelligence=intelligence,
        signal=None,
        execution_status="no_signal",
        snapshot=snapshot,
    )

    assert result["pending_count"] == 1
    assert result["latest_event"]["event"] == "MISSED_OPPORTUNITY_WATCHED"
    state = json.loads(engine.missed_opportunity_state_path.read_text(encoding="utf-8"))
    assert state["pending"][0]["side"] == "SELL"


def test_missed_opportunity_learning_confirms_one_r_move(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    engine.missed_opportunity_state_path.write_text(
        json.dumps(
            {
                "pending": [
                    {
                        "id": "XAUUSDm|SELL|SENSEI|100",
                        "symbol": "XAUUSDm",
                        "side": "SELL",
                        "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
                        "setup_type": "SENSEI_BIAS_REDUCED",
                        "entry_price": 100.0,
                        "stop_price": 105.0,
                        "target_price": 90.0,
                        "risk_per_unit": 5.0,
                        "setup_maturity": 74.0,
                        "confidence": 0.74,
                        "expires_at": "2027-01-01T10:45:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    snapshot = {"candles": {"M1": [{"close": 94.8}]}, "timeframes": {"M1": {"last_bar_time": "2027-01-01T10:10:00+00:00"}}}

    result = engine._track_missed_opportunity_learning(
        symbol="XAUUSDm",
        intelligence=_aggressive_intelligence(),
        signal=None,
        execution_status="no_signal",
        snapshot=snapshot,
    )

    assert result["confirmed_missed_count"] == 1
    assert result["latest_event"]["event"] == "MISSED_OPPORTUNITY_CONFIRMED"
    history = [json.loads(line) for line in engine.missed_opportunity_history_path.read_text(encoding="utf-8").splitlines()]
    assert history[-1]["learning_action"] == "increase_autonomous_attention"
    state = json.loads(engine.missed_opportunity_state_path.read_text(encoding="utf-8"))
    assert state["pending"] == []


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


def test_v56_supervised_signal_without_active_watch_allows_reduced_execution(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    decision = engine._execution_risk_binding(
        signal={
            "direction": "buy",
            "preferred_side": "BUY",
            "strategy_variant": "v56_aggressive_filtered_b",
            "setup_type": "AGG",
            "market_regime": "EXPANSION",
            "confidence": 0.74,
            "quant_score": 0.66,
            "impulse_score": 0.67,
            "selected_rr": 1.05,
        },
        intelligence={"execution_readiness": {"confidence": 0.74}},
        active_watch=None,
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["max_risk_multiplier"] == 0.35
    assert decision["risk_binding_source"] == "v56_supervised_without_watch"


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


def test_decision_source_audit_exposes_extracted_knowledge_brain(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    engine = MaximoQuantV4DemoEngine(settings, bridge=_FakeBridge())
    intelligence = _fake_intelligence_payload(
        action="WATCH",
        posture="selective",
        signal=None,
        preferred_side="SELL",
        blockers=[],
        watch_trigger={
            "side": "SELL",
            "pattern_projection": {
                "extracted_knowledge_operational_brain": {
                    "status": "primary_operational_brain",
                    "role": "motor_principal_de_decision",
                    "selected_side": "SELL",
                    "auto_selected_protocols": ["SENSEI_MANUAL_BIAS_PROTOCOL"],
                    "decision_impact": "Preparar SELL desde protocolo aprendido.",
                }
            },
        },
    )

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
        watch_execution_policy={"watch_policy_action": "PREPARE_REDUCED"},
        execution_risk_decision={"can_execute": False, "allowed_risk_mode": "reduced", "decision": "allowed"},
        account_status={"is_demo": True},
    )

    brain = payload["learned_knowledge"]["operational_brain"]
    assert payload["decision_attribution"]["primary_driver"] == "learned_knowledge"
    assert payload["learned_knowledge_role"] == "motor_principal"
    assert brain["role"] == "motor_principal_de_decision"
    assert "SENSEI_MANUAL_BIAS_PROTOCOL" in brain["auto_selected_protocols"]


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
            "H4": {"bars": 1000},
            "D1": {"bars": 500},
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
