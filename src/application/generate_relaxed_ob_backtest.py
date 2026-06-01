"""Generate a relaxed OB Rejection variant for initial backtesting."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.backtest_bridge import BacktestBridge
from src.trading.blueprint_builder import StrategyBlueprintBuilder
from src.trading.strategy_schemas import ExecutableBlueprintBundle, ExecutableStrategyBlueprint


class RelaxedOBBacktestGenerationApplicationService:
    """Create a relaxed OB Rejection blueprint and export its backtest spec."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self) -> dict:
        output_dir = self.settings.paths.knowledge_dir / "strategy_blueprints"
        output_dir.mkdir(parents=True, exist_ok=True)

        builder = StrategyBlueprintBuilder(self.session)
        bundle_path = output_dir / "executable_strategy_blueprints.json"
        if bundle_path.exists():
            base_bundle = ExecutableBlueprintBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
        else:
            base_bundle = builder.build(prioritize_family="OB Rejection")
        relaxed_blueprint = self._build_relaxed_blueprint(base_bundle)

        blueprints = [
            blueprint
            for blueprint in base_bundle.blueprints
            if blueprint.blueprint_name != relaxed_blueprint.blueprint_name
        ]
        blueprints.append(relaxed_blueprint)
        merged_bundle = ExecutableBlueprintBundle(
            generated_at=base_bundle.generated_at,
            blueprints=blueprints,
            excluded_strategies=base_bundle.excluded_strategies,
        )

        bundle_path.write_text(merged_bundle.model_dump_json(indent=2), encoding="utf-8")

        for blueprint in merged_bundle.blueprints:
            markdown_path = output_dir / f"{builder._safe_name(blueprint.blueprint_name)}.md"
            markdown_path.write_text(builder._markdown_for_blueprint(blueprint), encoding="utf-8")

        excluded_path = output_dir / "excluded_strategies.json"
        excluded_path.write_text(
            json.dumps([item.model_dump() for item in merged_bundle.excluded_strategies], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        export_summary = BacktestBridge(self.session, self.settings).export_blueprint_backtests()
        spec_path = self.settings.paths.data_dir / "backtests" / "specs" / "ob_rejection_relaxed_validation.json"
        return {
            "blueprints_created": len(merged_bundle.blueprints),
            "relaxed_blueprint": relaxed_blueprint.blueprint_name,
            "blueprint_path": str((output_dir / "ob_rejection_relaxed_validation.md").resolve()),
            "spec_path": str(spec_path.resolve()),
            "specs_exported": export_summary["specs_exported"],
        }

    def _build_relaxed_blueprint(self, bundle: ExecutableBlueprintBundle) -> ExecutableStrategyBlueprint:
        primary = next(
            (item for item in bundle.blueprints if item.strategy_family == "OB Rejection"),
            None,
        )
        if primary is None:
            primary = self._fallback_primary_blueprint()

        source_traceability = dict(primary.source_traceability)
        source_traceability["derived_from_blueprint"] = primary.blueprint_name
        source_traceability["variant_type"] = "relaxed_backtest_validation"

        entry_timeframes = primary.confirmation.get("timeframes") or ["M5", "M1"]
        context_timeframes = primary.context.get("timeframes") or ["H1"]
        quantifiable_conditions = [
            {
                "key": "relaxed_htf_bias",
                "layer": "context",
                "timeframe": context_timeframes[0],
                "rule": "Bullish if close > EMA50 or recent swings are ascending. Bearish if close < EMA50 or recent swings are descending.",
            },
            {
                "key": "recent_order_block",
                "layer": "zone",
                "timeframe": context_timeframes[0],
                "rule": "Allow a recent order block created within the last 20 candles without requiring perfect unmitigated preservation.",
            },
            {
                "key": "strong_rejection_candle",
                "layer": "confirmation",
                "timeframe": "/".join(entry_timeframes),
                "rule": "A strong directional candle from the OB is sufficient confirmation.",
            },
            {
                "key": "wick_rejection",
                "layer": "confirmation",
                "timeframe": "/".join(entry_timeframes),
                "rule": "A rejection wick from the OB is sufficient confirmation.",
            },
            {
                "key": "displacement_candle",
                "layer": "confirmation",
                "timeframe": "/".join(entry_timeframes),
                "rule": "A displacement candle from the OB is sufficient confirmation.",
            },
            {
                "key": "next_open_entry",
                "layer": "entry",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Enter at the open of the candle immediately after the rejection candle. No retest is required.",
            },
            {
                "key": "stop_placement",
                "layer": "risk",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Stop goes beyond the OB extreme plus a 0.10 ATR(14) buffer.",
            },
            {
                "key": "rr_12_fallback",
                "layer": "exit",
                "timeframe": context_timeframes[0],
                "rule": "If there is no clear liquidity target, use RR 1.2 as the initial take profit objective.",
            },
        ]

        return ExecutableStrategyBlueprint(
            blueprint_id=f"{primary.blueprint_id}_relaxed",
            strategy_key=primary.strategy_key,
            blueprint_name="OB Rejection Relaxed Validation",
            strategy_family="OB Rejection",
            priority=max(primary.priority + 10, 20),
            execution_profile="experimental_relaxed_validation",
            status="executable",
            context={
                "htf_bias": "Use H1 with relaxed validation. Bullish if close > EMA50 or recent swings are ascending. Bearish if close < EMA50 or recent swings are descending.",
                "bias_rule": "EMA50 relationship OR simple swing progression is enough.",
                "timeframes": context_timeframes,
            },
            valid_zone={
                "zone_type": "recent_order_block",
                "rule": "Use a recent order block from the last 20 HTF candles. Do not require perfect non-mitigation.",
                "location_filter": "Prefer clear reaction zones but allow broader backtesting coverage.",
            },
            confirmation={
                "timeframes": entry_timeframes,
                "rule": "Any one of these is enough: strong rejection candle, wick rejection, or displacement candle.",
                "reject_if": "Reject only when price drifts through the block without any decisive reaction candle.",
            },
            entry={
                "rule": "Enter at the open of the next candle after the rejection. Retest is optional and not required.",
                "entry_type": "next_open_after_rejection",
                "direction_handling": "Mirror logic for bullish and bearish setups.",
            },
            stop_loss={
                "rule": "Place stop beyond the OB extreme with a 0.10 ATR(14) buffer.",
                "hard_invalidation": "Any decisive close beyond the buffered OB extreme invalidates the trade.",
            },
            take_profit={
                "rule": "Target obvious liquidity when available; otherwise use RR 1.2 as the initial objective.",
                "rr_min": 1.2,
                "management": "Use RR 1.2 fallback when liquidity is unclear.",
            },
            risk_management={
                "risk_percent": 0.5,
                "risk_rule": "Keep fixed 0.5% risk per trade for initial backtesting validation.",
                "max_open_positions": 1,
                "session_filter": ["any_session"],
            },
            operational_checklist=[
                "Check H1 bias using close vs EMA50 or simple swing direction.",
                "Mark a recent order block from the last 20 HTF candles.",
                "Allow any session for this experimental validation run.",
                "Accept any one of: strong rejection candle, wick rejection, or displacement candle.",
                "Enter at the open of the next candle after rejection.",
                "Place stop beyond the OB extreme plus 0.10 ATR(14).",
                "Use liquidity target if clear; otherwise default to RR 1.2.",
                "Keep fixed risk at 0.5% per trade.",
            ],
            quantifiable_conditions=quantifiable_conditions,
            invalidation_rules=[
                "Cancel only if the buffered OB extreme is decisively broken before target hit.",
                "Cancel if the relaxed H1 bias flips before the rejection trigger appears.",
            ],
            simulation_overrides={
                "validation_profile": "relaxed_ob_rejection",
                "relaxed_htf_bias": True,
                "relaxed_order_block": True,
                "relaxed_confirmation_any": True,
                "entry_on_next_open": True,
            },
            source_traceability=source_traceability,
        )

    @staticmethod
    def _fallback_primary_blueprint() -> ExecutableStrategyBlueprint:
        return ExecutableStrategyBlueprint(
            blueprint_id="blueprint_fallback_ob_relaxed_source",
            strategy_key="ob_rejection_fallback",
            blueprint_name="OB Rejection Primary Blueprint",
            strategy_family="OB Rejection",
            priority=1,
            execution_profile="primary",
            context={"timeframes": ["H1"]},
            valid_zone={},
            confirmation={"timeframes": ["M5", "M1"]},
            entry={},
            stop_loss={},
            take_profit={"rr_min": 2.0},
            risk_management={"risk_percent": 0.5, "session_filter": ["new_york"]},
            operational_checklist=[],
            quantifiable_conditions=[],
            invalidation_rules=[],
            simulation_overrides={},
            source_traceability={},
        )
