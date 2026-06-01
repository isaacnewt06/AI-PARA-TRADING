"""Generate a balanced OB Rejection variant for intermediate backtesting."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.backtest_bridge import BacktestBridge
from src.trading.blueprint_builder import StrategyBlueprintBuilder
from src.trading.strategy_schemas import ExecutableBlueprintBundle, ExecutableStrategyBlueprint


class BalancedOBBacktestGenerationApplicationService:
    """Create a balanced OB Rejection blueprint and export its backtest spec."""

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
        balanced_blueprint = self._build_balanced_blueprint(base_bundle)

        blueprints = [
            blueprint
            for blueprint in base_bundle.blueprints
            if blueprint.blueprint_name != balanced_blueprint.blueprint_name
        ]
        blueprints.append(balanced_blueprint)
        merged_bundle = ExecutableBlueprintBundle(
            generated_at=base_bundle.generated_at,
            blueprints=sorted(blueprints, key=lambda item: (item.priority, item.blueprint_name.lower())),
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
        spec_path = self.settings.paths.data_dir / "backtests" / "specs" / "ob_rejection_balanced_validation.json"
        return {
            "blueprints_created": len(merged_bundle.blueprints),
            "balanced_blueprint": balanced_blueprint.blueprint_name,
            "blueprint_path": str((output_dir / "ob_rejection_balanced_validation.md").resolve()),
            "spec_path": str(spec_path.resolve()),
            "specs_exported": export_summary["specs_exported"],
        }

    def _build_balanced_blueprint(self, bundle: ExecutableBlueprintBundle) -> ExecutableStrategyBlueprint:
        primary = next((item for item in bundle.blueprints if item.blueprint_name == "OB Rejection Primary Blueprint"), None)
        if primary is None:
            primary = next((item for item in bundle.blueprints if item.strategy_family == "OB Rejection"), None)
        if primary is None:
            primary = self._fallback_primary_blueprint()

        source_traceability = dict(primary.source_traceability)
        source_traceability["derived_from_blueprint"] = primary.blueprint_name
        source_traceability["variant_type"] = "balanced_backtest_validation"

        entry_timeframes = primary.confirmation.get("timeframes") or ["M5", "M1"]
        context_timeframes = primary.context.get("timeframes") or ["H1"]
        quantifiable_conditions = [
            {
                "key": "balanced_htf_bias",
                "layer": "context",
                "timeframe": context_timeframes[0],
                "rule": "Bullish if close > EMA50 and EMA50 slope is positive. Bearish if close < EMA50 and EMA50 slope is negative.",
            },
            {
                "key": "recent_order_block_30",
                "layer": "zone",
                "timeframe": context_timeframes[0],
                "rule": "Allow a recent order block from the last 30 candles. Price must touch or enter the zone.",
            },
            {
                "key": "wick_rejection",
                "layer": "confirmation",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Rejection wick from the order block.",
            },
            {
                "key": "displacement_candle",
                "layer": "confirmation",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Directional displacement candle away from the order block.",
            },
            {
                "key": "close_back_inside_structure",
                "layer": "confirmation",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Candle closes back in trade direction inside the restored structure.",
            },
            {
                "key": "confirmation_two_of_three",
                "layer": "confirmation",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Require at least two of wick rejection, displacement candle, or close back inside structure.",
            },
            {
                "key": "next_open_entry",
                "layer": "entry",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Enter at the next candle open after confirmation.",
            },
            {
                "key": "atr_percentile_filter",
                "layer": "filter",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Reject setups when ATR(14) is below the 30th percentile of the last 100 candles.",
            },
            {
                "key": "range_spread_proxy_filter",
                "layer": "filter",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Reject setups when the confirmation candle range is abnormally large relative to ATR.",
            },
            {
                "key": "rr_15_fallback",
                "layer": "exit",
                "timeframe": context_timeframes[0],
                "rule": "Use prior liquidity if clear; otherwise target fixed RR 1.5.",
            },
        ]

        return ExecutableStrategyBlueprint(
            blueprint_id=f"{primary.blueprint_id}_balanced",
            strategy_key=primary.strategy_key,
            blueprint_name="OB Rejection Balanced Validation",
            strategy_family="OB Rejection",
            priority=max(primary.priority + 5, 10),
            execution_profile="experimental_balanced_validation",
            status="executable",
            context={
                "htf_bias": "Use H1 with balanced validation. Bullish if close > EMA50 and EMA50 slope is positive. Bearish if close < EMA50 and EMA50 slope is negative.",
                "bias_rule": "Close relationship and EMA50 slope must agree.",
                "timeframes": context_timeframes,
            },
            valid_zone={
                "zone_type": "recent_order_block",
                "rule": "Use a recent order block from the last 30 HTF candles. Price must touch or enter the zone.",
                "location_filter": "Allow mitigated zones, but still require a real interaction with the block.",
            },
            confirmation={
                "timeframes": entry_timeframes,
                "rule": "Require at least 2 of 3: wick rejection, displacement candle, close back inside structure.",
                "reject_if": "Reject if fewer than two confirmation signals are present.",
            },
            entry={
                "rule": "Enter at the open of the next candle after confirmation.",
                "entry_type": "next_open_after_confirmation",
                "direction_handling": "Mirror logic for bullish and bearish setups.",
            },
            stop_loss={
                "rule": "Place stop beyond the OB extreme with a 0.10 ATR(14) buffer.",
                "hard_invalidation": "Any decisive close beyond the buffered OB extreme invalidates the trade.",
            },
            take_profit={
                "rule": "Use prior liquidity when clear; otherwise fall back to fixed RR 1.5.",
                "rr_min": 1.5,
                "management": "Liquidity target takes precedence if it offers at least 1.5R; otherwise use fixed RR target.",
            },
            risk_management={
                "risk_percent": 0.5,
                "risk_rule": "Keep fixed 0.5% risk per trade.",
                "max_open_positions": 1,
                "session_filter": ["london", "new_york"],
            },
            operational_checklist=[
                "Confirm H1 bias with close vs EMA50 and EMA50 slope alignment.",
                "Mark a recent order block from the last 30 HTF candles.",
                "Require price to touch or enter the OB zone.",
                "Trade only during London or New York session.",
                "Require at least two of the three confirmation signals.",
                "Enter at the next candle open after confirmation.",
                "Reject low-volatility setups below the ATR percentile threshold.",
                "Reject abnormal range/spread proxy candles.",
                "Use liquidity target if clear; otherwise default to RR 1.5.",
            ],
            quantifiable_conditions=quantifiable_conditions,
            invalidation_rules=[
                "Cancel if H1 bias no longer matches EMA50 relationship and slope.",
                "Cancel if fewer than two confirmation signals are present.",
                "Cancel if ATR filter or range proxy filter fails.",
            ],
            simulation_overrides={
                "validation_profile": "balanced_ob_rejection",
                "balanced_htf_bias": True,
                "balanced_order_block": True,
                "recent_order_block_window": 30,
                "confirmation_mode": "two_of_three",
                "min_confirmation_signals": 2,
                "min_atr_percentile": 30,
                "atr_percentile_lookback": 100,
                "max_range_atr_multiple": 2.2,
                "entry_on_next_open": True,
            },
            source_traceability=source_traceability,
        )

    @staticmethod
    def _fallback_primary_blueprint() -> ExecutableStrategyBlueprint:
        return ExecutableStrategyBlueprint(
            blueprint_id="blueprint_fallback_ob_balanced_source",
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
