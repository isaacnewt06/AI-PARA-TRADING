"""Helpers for loading approved strategy configurations."""

from __future__ import annotations

import json

from src.core.config import Settings
from src.trading.strategy_schemas import BacktestBlueprintSpec


def load_ob_rejection_short_trailing_atr_v3(settings: Settings, symbol: str) -> BacktestBlueprintSpec:
    """Load the approved v3 short-only trailing ATR strategy as a backtest-ready spec."""
    specs_dir = settings.paths.data_dir / "backtests" / "specs"
    primary_spec_path = specs_dir / "ob_rejection_primary.json"
    fallback_spec_path = specs_dir / "ob_rejection_short_only_trailing_atr.json"
    final_candidate_path = settings.paths.data_dir / "strategies" / "final_candidate_v3.json"
    spec_path = primary_spec_path if primary_spec_path.exists() else fallback_spec_path
    if not spec_path.exists():
        raise FileNotFoundError(f"Base OB Rejection spec not found. Tried: {primary_spec_path} and {fallback_spec_path}")
    if not final_candidate_path.exists():
        raise FileNotFoundError(f"Final candidate v3 not found: {final_candidate_path}")

    base_spec = BacktestBlueprintSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    final_candidate = json.loads(final_candidate_path.read_text(encoding="utf-8"))
    parameters = final_candidate.get("selected_configuration", {}).get("parameters", {})
    simulation_overrides = dict(base_spec.simulation_overrides or {})
    simulation_overrides.update(
        {
            "direction_filter": "short_only",
            "exit_management": "trailing_atr_after_1r",
            "trail_atr_multiple": float(parameters.get("trail_atr_multiple") or simulation_overrides.get("trail_atr_multiple") or 1.0),
            "blocked_hours_utc": list(parameters.get("blocked_hours_utc") or []),
            "allowed_hours_utc": list(parameters.get("allowed_hours_utc") or []),
            "required_rejection_signals": list(parameters.get("required_rejection_signals") or ["wick_rejection"]),
            "blocked_rejection_signals": list(parameters.get("blocked_rejection_signals") or []),
            "allowed_atr_bands": list(parameters.get("allowed_atr_bands") or []),
            "blocked_atr_bands": list(parameters.get("blocked_atr_bands") or []),
            "max_range_atr_multiple": float(parameters.get("max_range_atr_multiple") or 2.0),
        }
    )
    if parameters.get("break_even_trigger_r") is not None:
        simulation_overrides["break_even_trigger_r"] = float(parameters["break_even_trigger_r"])

    payload = base_spec.model_dump()
    payload["strategy_name"] = "OB Rejection Short Only Trailing ATR v3"
    payload["symbols_suggested"] = [symbol]
    payload["session_filter"] = list(parameters.get("session_filter") or ["any_session"])
    payload["rr_min"] = float(parameters.get("rr_min") or base_spec.rr_min or 1.2)
    payload["simulation_overrides"] = simulation_overrides
    payload["source_traceability"] = {
        **(base_spec.source_traceability or {}),
        "base_spec_path": str(spec_path.resolve()),
        "base_spec_strategy_name": base_spec.strategy_name,
        "approved_strategy_reference": str(final_candidate_path.resolve()),
        "selected_configuration": final_candidate.get("selected_configuration", {}).get("strategy_name"),
    }
    return BacktestBlueprintSpec.model_validate(payload)
