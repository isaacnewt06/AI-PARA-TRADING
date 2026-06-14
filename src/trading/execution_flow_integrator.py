"""Integration helper for definitive execution confirmation in demo engine."""

from __future__ import annotations

from typing import Any

from src.trading.definitive_execution_confirmation import DefinitiveExecutionConfirmationEngine


def run_definitive_confirmation(*, symbol: str, intelligence: dict[str, Any],
                                  snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run definitive execution confirmation with integrated signal, direction, volume and risk validation.

    This function integrates all confirmation layers:
    1. Signal detection (señal)
    2. Direction consistency (dirección del mercado)
    3. Volume movement validation (volumen de movimiento)
    4. Risk geometry (gestión de riesgo necesaria)

    Returns a clear EXECUTE/WATCH/PREPARE/WAIT decision with full validation checklist.
    """
    engine = DefinitiveExecutionConfirmationEngine()
    return engine.evaluate(symbol=symbol, signal=intelligence.get("overview", {}).get("signal"),
                         intelligence=intelligence, snapshot=snapshot)


def validate_for_execution(*, signal: dict[str, Any] | None, intelligence: dict[str, Any],
                            snapshot: dict[str, Any] | None = None) -> bool:
    """Quick check if signal meets all execution criteria."""
    if signal is None:
        return False
    result = run_definitive_confirmation(symbol="XAUUSDm", intelligence=intelligence, snapshot=snapshot)
    return result.get("can_execute", False) and result.get("decision") == "EXECUTE"