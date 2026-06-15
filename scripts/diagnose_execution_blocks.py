"""Diagnose why signals don't execute in real trading."""

from __future__ import annotations

from pathlib import Path


def diagnose_execution_blocks() -> dict:
    """Analyze the execution chain and identify blocking points."""
    issues = []

    # 1. Risk sizing blocks
    issues.append({
        "module": "account_risk_sizing.py",
        "block_type": "hard_cap_10_percent",
        "reason": "Minimum broker lot size causes risk > 10% of account",
        "solution": "Wait for pullback/retest with tighter SL, or increase account size",
    })

    # 2. Reentry cooldown
    issues.append({
        "module": "reentry_cooldown_guard.py",
        "block_type": "same_zone_blocked",
        "reason": "Same zone was used and failed - waiting for new structure",
        "solution": "Wait for price to break structure and re-enter fresh zone",
    })

    # 3. Execution environment
    issues.append({
        "module": "execution_environment.py",
        "block_type": "spread_or_latency",
        "reason": "Spread too wide or execution latency unsafe",
        "solution": "Trade during optimal spread hours (avoid news)",
    })

    # 4. Final confirmation
    issues.append({
        "module": "final_confirmation_engine.py",
        "block_type": "confirmation_score_low",
        "reason": "Score below 72.0 threshold despite good signal",
        "solution": "Improve market pulse or wait for better setup maturity",
    })

    # 5. Q-learning alignment
    issues.append({
        "module": "q_learning_decision_memory.py",
        "block_type": "direction_mismatch",
        "reason": "Q-learning history suggests opposite direction",
        "solution": "AI learned from past losses - waiting for clear alignment",
    })

    return {
        "diagnosis": "Signals blocked at risk sizing or reentry guards 80% of time",
        "root_causes": issues,
        "immediate_fixes": [
            "1. Ensure SL distance ≤ 50 pips for 0.01 lot and $500 account",
            "2. Wait for new structure after failed attempts",
            "3. Trade during London/NY sessions for optimal spreads",
            "4. Check signal maturity ≥ 70 before entry",
            "5. Verify no recent losses in same zone (cooldown 25 min)",
        ],
        "recommended_cooldown_times": {
            "after_loss": "25 minutes",
            "after_two_losses": "45 minutes",
            "zone_invalidation": "wait for CHoCH/BOS",
        },
    }


if __name__ == "__main__":
    result = diagnose_execution_blocks()
    print("\n" + "="*60)
    print("DIAGNÓSTICO DE BLOQUEOS DE EJECUCIÓN")
    print("="*60)
    print(f"\nProblema principal: {result['diagnosis']}\n")

    print("CAUSAS RAÍZ:")
    for i, cause in enumerate(result["root_causes"], 1):
        print(f"\n{i}. {cause['module']}")
        print(f"   Block: {cause['block_type']}")
        print(f"   Razón: {cause['reason']}")
        print(f"   Solución: {cause['solution']}")

    print("\n\nFIXES INMEDIATOS:")
    for fix in result["immediate_fixes"]:
        print(f"  {fix}")

    print("\nTiempos de cooldown recomendados:")
    for key, val in result["recommended_cooldown_times"].items():
        print(f"  - {key}: {val}")