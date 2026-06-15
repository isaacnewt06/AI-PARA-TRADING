from __future__ import annotations

from src.trading.controlled_demo_survival_protocol import ControlledDemoSurvivalProtocolV1
from src.trading.maximo_quant_v4_demo_engine import MaximoQuantV4DemoEngine


def _signal() -> dict:
    return {
        "signal_type": "DISPLACEMENT_PLUS_WICK_V1",
        "edge_name": "displacement_plus_wick_v1",
        "hour_ny": 9,
    }


def _market_state(*, hour_ny: int = 9, atr_ratio: float = 1.2) -> dict:
    return {"hour_ny": hour_ny, "atr_ratio": atr_ratio}


def _event(action: str = "allow") -> dict:
    return {"action": action}


def _environment(**overrides) -> dict:
    payload = {
        "live_spread": 0.12,
        "slippage_estimated": 0.12,
        "live_latency": 0.10,
        "execution_viability": "SAFE",
        "execution_delay": None,
        "mfe": None,
        "mae": None,
        "slippage_real": None,
        "partial_fills": None,
        "trailing_quality": None,
        "time_to_be": None,
        "execution_degradation": None,
    }
    payload.update(overrides)
    return payload


def test_protocol_allows_validated_ny_am_safe_environment() -> None:
    result = ControlledDemoSurvivalProtocolV1().evaluate(
        symbol="XAUUSDm",
        signal=_signal(),
        market_state=_market_state(hour_ny=9, atr_ratio=1.2),
        event_risk=_event("allow"),
        execution_environment=_environment(),
    )

    assert result["applies"] is True
    assert result["allowed"] is True
    assert result["allowed_risk_mode"] == "reduced"
    assert result["max_risk_multiplier"] == 0.5
    assert result["environment"]["session"] == "ny_am"
    assert result["environment"]["atr_regime"] == "HIGH"


def test_protocol_allows_validated_ny_pm_extreme_environment() -> None:
    signal = _signal()
    signal["hour_ny"] = 15
    result = ControlledDemoSurvivalProtocolV1().evaluate(
        symbol="XAUUSDm",
        signal=signal,
        market_state=_market_state(hour_ny=15, atr_ratio=1.55),
        event_risk=_event("allow"),
        execution_environment=_environment(),
    )

    assert result["allowed"] is True
    assert result["environment"]["session"] == "ny_pm"
    assert result["environment"]["atr_regime"] == "EXTREME"


def test_protocol_blocks_london_even_with_good_costs() -> None:
    signal = _signal()
    signal["hour_ny"] = 4
    result = ControlledDemoSurvivalProtocolV1().evaluate(
        symbol="XAUUSDm",
        signal=signal,
        market_state=_market_state(hour_ny=4, atr_ratio=1.2),
        event_risk=_event("allow"),
        execution_environment=_environment(),
    )

    assert result["allowed"] is False
    assert "london_blocked" in result["blockers"]
    assert "session_not_validated" in result["blockers"]


def test_protocol_blocks_high_spread_and_unsafe_latency() -> None:
    result = ControlledDemoSurvivalProtocolV1().evaluate(
        symbol="XAUUSDm",
        signal=_signal(),
        market_state=_market_state(hour_ny=9, atr_ratio=1.2),
        event_risk=_event("allow"),
        execution_environment=_environment(
            live_spread=0.42,
            slippage_estimated=0.42,
            live_latency=0.25,
            execution_viability="UNSAFE",
        ),
    )

    assert result["allowed"] is False
    assert "spread_above_survival_threshold" in result["blockers"]
    assert "latency_unsafe" in result["blockers"]
    assert "execution_viability_not_safe" in result["blockers"]


def test_protocol_blocks_normal_atr_and_macro_watch() -> None:
    result = ControlledDemoSurvivalProtocolV1().evaluate(
        symbol="XAUUSDm",
        signal=_signal(),
        market_state=_market_state(hour_ny=9, atr_ratio=1.0),
        event_risk=_event("watch"),
        execution_environment=_environment(),
    )

    assert result["allowed"] is False
    assert "atr_regime_not_safe" in result["blockers"]
    assert "macro_high_impact_or_watch" in result["blockers"]


def test_protocol_does_not_apply_to_other_signals() -> None:
    result = ControlledDemoSurvivalProtocolV1().evaluate(
        symbol="XAUUSDm",
        signal={"signal_type": "OB_AGGRESSIVE_REDUCED_SIGNAL", "hour_ny": 9},
        market_state=_market_state(hour_ny=9, atr_ratio=1.2),
        event_risk=_event("allow"),
        execution_environment=_environment(),
    )

    assert result["applies"] is False
    assert result["allowed"] is False
    assert result["blockers"] == ["protocol_not_applicable"]


def test_engine_protocol_blocks_execution_when_environment_is_not_safe() -> None:
    decision = MaximoQuantV4DemoEngine._apply_controlled_demo_survival_protocol(
        execution_risk_decision={
            "can_execute": True,
            "allowed_risk_mode": "reduced",
            "max_risk_multiplier": 0.5,
            "execution_status": "ready",
        },
        controlled_demo_survival_protocol={
            "applies": True,
            "allowed": False,
            "blockers": ["spread_above_survival_threshold"],
        },
    )

    assert decision["can_execute"] is False
    assert decision["allowed_risk_mode"] == "blocked"
    assert decision["execution_status"] == "blocked_by_controlled_demo_survival_protocol"


def test_engine_protocol_keeps_reduced_risk_when_safe() -> None:
    decision = MaximoQuantV4DemoEngine._apply_controlled_demo_survival_protocol(
        execution_risk_decision={
            "can_execute": True,
            "allowed_risk_mode": "normal",
            "max_risk_multiplier": 1.0,
            "execution_status": "ready",
        },
        controlled_demo_survival_protocol={
            "applies": True,
            "allowed": True,
            "max_risk_multiplier": 0.5,
            "blockers": [],
        },
    )

    assert decision["can_execute"] is True
    assert decision["allowed_risk_mode"] == "reduced"
    assert decision["max_risk_multiplier"] == 0.5
    assert decision["execution_mode"] == "controlled_demo_reduced_execution"
