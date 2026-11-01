"""Offline regression tests for retired, historically permissive entrypoints."""

from __future__ import annotations

import importlib
import runpy
from pathlib import Path

import pytest

from src.trading.controlled_demo_survival_protocol import ControlledDemoSurvivalProtocolV1
from src.trading.unleashed_demo_protocol import UnleashedDemoProtocolV1
from src.trading.unleashed_ai_continuous import UnleashedAICycle
from src.trading.unleashed_ai_operative import UnleashedAIContinuous
from src.trading.mt5_client import MT5ClientConfig, execute_ai_order_on_mt5


def test_legacy_patch_import_does_not_replace_controlled_protocol() -> None:
    import src.trading.controlled_demo_survival_protocol as controlled
    import src.trading.demo_engine_patch as patch

    importlib.reload(patch)
    assert controlled.ControlledDemoSurvivalProtocolV1 is ControlledDemoSurvivalProtocolV1
    assert controlled.ControlledDemoSurvivalProtocolV1 is not UnleashedDemoProtocolV1


def test_legacy_unleashed_protocol_never_allows_full_risk() -> None:
    decision = UnleashedDemoProtocolV1().evaluate(
        symbol="XAUUSDm",
        signal={"edge_name": "displacement_plus_wick_v1"},
        market_state={},
        event_risk={"action": "allow"},
        execution_environment={"live_spread": 0.01, "execution_viability": "SAFE"},
    )
    assert decision["allowed"] is False
    assert decision["action"] == "BLOCK"
    assert decision["allowed_risk_mode"] == "blocked"
    assert decision["risk_multiplier"] == 0.0
    assert "trading_authority_locked" in decision["blockers"]


def test_unleashed_runner_refuses_start_and_direct_order() -> None:
    runner = UnleashedAIContinuous()
    with pytest.raises(RuntimeError, match="TRADING_AUTHORITY=NONE"):
        runner.run()
    with pytest.raises(RuntimeError, match="TRADING_AUTHORITY=NONE"):
        runner._place_order_on_mt5({"direction": "BUY"})


def test_legacy_script_entrypoint_exits_before_importing_mt5() -> None:
    entry = Path(__file__).resolve().parents[2] / "run_unleashed_ai.py"
    with pytest.raises(SystemExit, match="TRADING_AUTHORITY=NONE"):
        runpy.run_path(str(entry), run_name="__main__")


def test_continuous_research_cycle_never_promotes_engine_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    cycle = UnleashedAICycle()

    class PermissiveEngine:
        def evaluate(self, **_: object) -> dict:
            return {"can_execute": True, "final_confirmation_score": 100, "decision": "EXECUTE"}

    cycle.engine = PermissiveEngine()
    monkeypatch.setattr(cycle, "_load_engine", lambda: None)
    result = cycle.run_continuous_cycle()
    assert result["can_execute"] is False
    assert "trading_authority_locked" in result["blockers"]


def test_client_replication_cannot_send_orders() -> None:
    result = execute_ai_order_on_mt5(
        {"direction": "BUY", "entry_price": 2652, "stop_price": 2650, "target_price": 2655},
        MT5ClientConfig(),
    )
    assert result["executed"] is False
    assert "TRADING_AUTHORITY=NONE" in result["error"]
