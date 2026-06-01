"""Generate balanced v2 OB Rejection variants for backtesting."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.backtest_bridge import BacktestBridge
from src.trading.blueprint_builder import StrategyBlueprintBuilder
from src.trading.strategy_schemas import ExecutableBlueprintBundle, ExecutableStrategyBlueprint


class BalancedV2OBBacktestGenerationApplicationService:
    """Create balanced v2 RR variants and export formal backtest specs."""

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

        rr12 = self._build_balanced_v2_blueprint(base_bundle, rr_min=1.2, priority=12)
        rr15 = self._build_balanced_v2_blueprint(base_bundle, rr_min=1.5, priority=13)

        replacement_names = {rr12.blueprint_name, rr15.blueprint_name}
        blueprints = [item for item in base_bundle.blueprints if item.blueprint_name not in replacement_names]
        blueprints.extend([rr12, rr15])

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
        return {
            "blueprints_created": len(merged_bundle.blueprints),
            "balanced_v2_blueprints": [rr12.blueprint_name, rr15.blueprint_name],
            "spec_paths": [
                str((self.settings.paths.data_dir / "backtests" / "specs" / "ob_rejection_balanced_v2_rr12.json").resolve()),
                str((self.settings.paths.data_dir / "backtests" / "specs" / "ob_rejection_balanced_v2_rr15.json").resolve()),
            ],
            "specs_exported": export_summary["specs_exported"],
        }

    def _build_balanced_v2_blueprint(
        self,
        bundle: ExecutableBlueprintBundle,
        *,
        rr_min: float,
        priority: int,
    ) -> ExecutableStrategyBlueprint:
        primary = next((item for item in bundle.blueprints if item.blueprint_name == "OB Rejection Primary Blueprint"), None)
        if primary is None:
            primary = next((item for item in bundle.blueprints if item.strategy_family == "OB Rejection"), None)
        if primary is None:
            primary = self._fallback_primary_blueprint()

        rr_suffix = "RR12" if rr_min == 1.2 else "RR15"
        source_traceability = dict(primary.source_traceability)
        source_traceability["derived_from_blueprint"] = primary.blueprint_name
        source_traceability["variant_type"] = f"balanced_v2_backtest_validation_rr_{rr_suffix.lower()}"

        entry_timeframes = primary.confirmation.get("timeframes") or ["M5", "M1"]
        context_timeframes = primary.context.get("timeframes") or ["H1"]
        rr_label = "1.2" if rr_min == 1.2 else "1.5"

        quantifiable_conditions = [
            {
                "key": "balanced_v2_htf_bias",
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
                "key": "confirmation_two_of_three_v2",
                "layer": "confirmation",
                "timeframe": "/".join(entry_timeframes),
                "rule": "Require two of three: wick rejection, displacement candle, close back inside structure. Displacement plus close-back is valid even without wick rejection.",
            },
            {
                "key": "atr_band_filter_20_90",
                "layer": "filter",
                "timeframe": "/".join(entry_timeframes),
                "rule": "ATR(14) must be between the 20th and 90th percentile of the last 100 candles.",
            },
            {
                "key": "large_confirmation_retrace",
                "layer": "entry",
                "timeframe": "/".join(entry_timeframes),
                "rule": "If the confirmation candle is very large, require at least 25% retrace before entry.",
            },
            {
                "key": "rr_fallback_v2",
                "layer": "exit",
                "timeframe": context_timeframes[0],
                "rule": f"Use prior liquidity if clear; otherwise fall back to fixed RR {rr_label}.",
            },
        ]

        return ExecutableStrategyBlueprint(
            blueprint_id=f"{primary.blueprint_id}_balanced_v2_{rr_suffix.lower()}",
            strategy_key=primary.strategy_key,
            blueprint_name=f"OB Rejection Balanced v2 {rr_suffix}",
            strategy_family="OB Rejection",
            priority=priority,
            execution_profile=f"experimental_balanced_v2_{rr_suffix.lower()}",
            status="executable",
            context={
                "htf_bias": "Use H1 with close vs EMA50 and EMA50 slope alignment.",
                "bias_rule": "Close relationship and EMA50 slope must agree.",
                "timeframes": context_timeframes,
            },
            valid_zone={
                "zone_type": "recent_order_block",
                "rule": "Use a recent order block from the last 30 HTF candles. Price must touch or enter the zone.",
                "location_filter": "Allow mitigated zones, but require a real interaction with the block.",
            },
            confirmation={
                "timeframes": entry_timeframes,
                "rule": "Require 2 of 3: wick rejection, displacement candle, close back inside structure. Displacement plus close-back is enough without wick rejection.",
                "reject_if": "Reject if fewer than two confirmation signals are present.",
            },
            entry={
                "rule": "Enter at the next candle open after confirmation. If the confirmation candle is very large, wait for at least 25% retrace before entry.",
                "entry_type": "next_open_or_retrace_after_large_confirmation",
                "direction_handling": "Mirror logic for bullish and bearish setups.",
            },
            stop_loss={
                "rule": "Place stop beyond the OB extreme with a 0.10 ATR(14) buffer.",
                "hard_invalidation": "Any decisive close beyond the buffered OB extreme invalidates the trade.",
            },
            take_profit={
                "rule": f"Use prior liquidity when clear; otherwise fall back to fixed RR {rr_label}.",
                "rr_min": rr_min,
                "management": f"Liquidity target takes precedence if it offers at least {rr_label}R; otherwise use fixed RR target.",
            },
            risk_management={
                "risk_percent": 0.5,
                "risk_rule": "Keep fixed 0.5% risk per trade.",
                "max_open_positions": 1,
                "session_filter": ["london", "new_york"],
                "priority_window": ["new_york_followthrough_hour"],
            },
            operational_checklist=[
                "Confirm H1 bias with close vs EMA50 and EMA50 slope alignment.",
                "Mark a recent order block from the last 30 HTF candles and require price interaction.",
                "Trade only during London or New York, prioritizing the hour after NY open.",
                "Require two of the three confirmation signals.",
                "If the confirmation candle is too large, require at least 25% retrace before entering.",
                "Reject ATR below percentile 20 or above percentile 90.",
                "Reject abnormally large confirmation candles relative to ATR.",
                f"Use liquidity target if clear; otherwise default to RR {rr_label}.",
            ],
            quantifiable_conditions=quantifiable_conditions,
            invalidation_rules=[
                "Cancel if H1 bias no longer matches EMA50 relationship and slope.",
                "Cancel if fewer than two confirmation signals are present.",
                "Cancel if ATR band filter fails or range proxy filter fails.",
            ],
            simulation_overrides={
                "validation_profile": f"balanced_v2_ob_rejection_{rr_suffix.lower()}",
                "balanced_htf_bias": True,
                "balanced_order_block": True,
                "recent_order_block_window": 30,
                "confirmation_mode": "two_of_three",
                "min_confirmation_signals": 2,
                "min_atr_percentile": 20,
                "max_atr_percentile": 90,
                "atr_percentile_lookback": 100,
                "max_range_atr_multiple": 2.8,
                "large_confirmation_atr_multiple": 1.8,
                "large_confirmation_retrace": 0.25,
                "entry_on_next_open": True,
                "preferred_ny_followthrough_hour": True,
            },
            source_traceability=source_traceability,
        )

    @staticmethod
    def _fallback_primary_blueprint() -> ExecutableStrategyBlueprint:
        return ExecutableStrategyBlueprint(
            blueprint_id="blueprint_fallback_ob_balanced_v2_source",
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
