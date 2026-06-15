"""Test staged exit and trap analysis integration."""

from __future__ import annotations

import sys
sys.path.insert(0, '.')

from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine


def test_staged_exit():
    engine = DefinitiveExecutionConfirmationEngine()

    test_intelligence = {
        "overview": {
            "market_state": {
                "preferred_side": "BUY",
                "pulse_score": 85,
                "clarity_score": 75,
                "harmony_score": 0.72,
                "setup_maturity": 78,
                "ob_rejection_families": {
                    "aggressive": {"active": True, "checks": {"strong_bullish_rejection": True}},
                    "institutional": {"active": False},
                },
            },
            "knowledge_alignment": {"harmony": {"harmony_score": 0.72}},
            "signal": {
                "direction": "BUY",
                "stop_price": 1900.0,
                "target_price": 1920.0,
                "entry_price": 1910.0,
                "selected_rr": 2.0,
            },
            "decision": {"action": "EXECUTE"},
        },
        "execution_readiness": {"action": "EXECUTE", "setup_maturity": 78},
        "event_risk": {"action": "allow"},
        "watch_trigger": {"setup_maturity": 78},
    }

    result = engine.evaluate(symbol="XAUUSDm", signal=test_intelligence["overview"]["signal"],
                             intelligence=test_intelligence, snapshot={})

    print("\n=== STAGED EXIT PLAN ===")
    staged = result.get("staged_exit_plan")
    if staged:
        print(f"Initial RR: {staged['initial_rr']}")
        for level in staged["staged_levels"]:
            print(f"  - {level['level']}: {level['price']} ({level['close_fraction']*100}% close)")
    else:
        print("No staged exit (decision not EXECUTE)")

    print("\n=== TRAP ANALYSIS ===")
    trap = result.get("trap_analysis")
    if trap:
        for key, val in trap.items():
            print(f"{key}: {val}")
    else:
        print("No trap analysis")

    print(f"\n=== DECISION: {result['decision']} (Score: {result['final_confirmation_score']}) ===")


if __name__ == "__main__":
    test_staged_exit()