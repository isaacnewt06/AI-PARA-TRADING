"""CI tripwires: SHADOW mode must not contain a path to MT5 order mutations.

These checks scan production Python, not test fakes. They are intentionally
independent of the MetaTrader5 package and account credentials.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.trading.mt5_bridge import MT5Bridge
from src.trading.unleashed_ai_protocol import UnleashedAIProtocol, quick_ai_check


ROOT = Path(__file__).resolve().parents[2]
MUTATIONS = {"place_demo_market_order", "modify_position_sl_tp", "close_position_partial"}


def test_no_production_python_contains_mt5_order_send_call() -> None:
    """A fresh direct broker order call must break CI even outside the bridge."""
    violations: list[str] = []
    for path in ROOT.rglob("*.py"):
        if "tests" in path.relative_to(ROOT).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "order_send":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node.func, ast.Name) and node.func.id == "order_send":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "order_send"
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == [], f"Production MT5 order_send references reappeared: {violations}"


def test_all_mt5_mutations_unconditionally_reject_at_entry() -> None:
    tree = ast.parse((ROOT / "src/trading/mt5_bridge.py").read_text(encoding="utf-8"))
    bridge = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MT5Bridge"
    )
    for method in MUTATIONS:
        definition = next(
            node for node in bridge.body if isinstance(node, ast.FunctionDef) and node.name == method
        )
        assert len(definition.body) == 1, f"{method} has code after its safety gate"
        guard = definition.body[0]
        assert isinstance(guard, ast.Expr) and isinstance(guard.value, ast.Call)
        assert isinstance(guard.value.func, ast.Attribute)
        assert isinstance(guard.value.func.value, ast.Name)
        assert guard.value.func.value.id == "self"
        assert guard.value.func.attr == "_reject_order_mutation"


@pytest.mark.parametrize("event_action", ["ALLOW", "BLOCK", "UNKNOWN", ""])
@pytest.mark.parametrize("viability", ["SAFE", "UNSAFE", "UNKNOWN", ""])
def test_legacy_protocol_never_promotes_research_to_order_authority(
    event_action: str, viability: str
) -> None:
    decision = UnleashedAIProtocol().evaluate(
        symbol="XAUUSD", pulse_score=100.0, event_action=event_action,
        execution_viability=viability, final_confirmation_score=100.0,
    )
    allowed, blockers = quick_ai_check(
        {"event_risk": {"action": event_action},
         "execution_environment": {"execution_viability": viability}},
        {"symbol": "XAUUSD"},
    )
    assert decision["allowed"] is False
    assert decision["risk_multiplier"] == 0.0
    assert "trading_authority_locked" in decision["blockers"]
    assert allowed is False
    assert "trading_authority_locked" in blockers


def test_mt5_bridge_mutation_gate_is_not_configurable() -> None:
    with pytest.raises(RuntimeError, match="TRADING_AUTHORITY=NONE"):
        MT5Bridge._reject_order_mutation()
