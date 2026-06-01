"""Generate filtered relaxed OB Rejection variants for optimization baseline."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.backtest_bridge import BacktestBridge
from src.trading.blueprint_builder import StrategyBlueprintBuilder
from src.trading.strategy_schemas import ExecutableBlueprintBundle, ExecutableStrategyBlueprint


class RelaxedFilteredOBBacktestGenerationApplicationService:
    """Create filtered relaxed OB Rejection variants and export formal specs."""

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

        variants = [
            self._build_variant(base_bundle, name="OB Rejection Relaxed Filtered v1 LS Core", include_low_atr=False, direction_filter="both", priority=21),
            self._build_variant(base_bundle, name="OB Rejection Relaxed Filtered v1 LS WideATR", include_low_atr=True, direction_filter="both", priority=22),
            self._build_variant(base_bundle, name="OB Rejection Relaxed Filtered v1 Short Core", include_low_atr=False, direction_filter="short_only", priority=23),
            self._build_variant(base_bundle, name="OB Rejection Relaxed Filtered v1 Short WideATR", include_low_atr=True, direction_filter="short_only", priority=24),
        ]

        replacement_names = {item.blueprint_name for item in variants}
        blueprints = [item for item in base_bundle.blueprints if item.blueprint_name not in replacement_names]
        blueprints.extend(variants)
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
            "filtered_variants": [item.blueprint_name for item in variants],
            "specs_exported": export_summary["specs_exported"],
        }

    def _build_variant(
        self,
        bundle: ExecutableBlueprintBundle,
        *,
        name: str,
        include_low_atr: bool,
        direction_filter: str,
        priority: int,
    ) -> ExecutableStrategyBlueprint:
        relaxed = next((item for item in bundle.blueprints if item.blueprint_name == "OB Rejection Relaxed Validation"), None)
        if relaxed is None:
            relaxed = self._fallback_relaxed_blueprint()

        allowed_atr_bands = ["p60_80", "p80_100"]
        if include_low_atr:
            allowed_atr_bands.insert(0, "p00_20")
        direction_label = "short_only" if direction_filter == "short_only" else "both"

        source_traceability = dict(relaxed.source_traceability)
        source_traceability["derived_from_blueprint"] = relaxed.blueprint_name
        source_traceability["variant_type"] = "relaxed_filtered_v1"

        return ExecutableStrategyBlueprint(
            blueprint_id=f"{relaxed.blueprint_id}_{name.lower().replace(' ', '_')}",
            strategy_key=relaxed.strategy_key,
            blueprint_name=name,
            strategy_family="OB Rejection",
            priority=priority,
            execution_profile="experimental_relaxed_filtered_v1",
            status="executable",
            context=dict(relaxed.context),
            valid_zone=dict(relaxed.valid_zone),
            confirmation={
                "timeframes": relaxed.confirmation.get("timeframes", ["M5", "M1"]),
                "rule": "Use relaxed OB Rejection but exclude weak confirmation candles below 0.8 ATR.",
                "reject_if": "Reject small confirmation candles and ATR p20_40 conditions.",
            },
            entry=dict(relaxed.entry),
            stop_loss=dict(relaxed.stop_loss),
            take_profit=dict(relaxed.take_profit),
            risk_management={
                "risk_percent": 0.5,
                "risk_rule": "Keep fixed 0.5% risk per trade.",
                "max_open_positions": 1,
                "session_filter": ["london"],
                "direction_filter": direction_label,
            },
            operational_checklist=[
                "Use relaxed OB Rejection core logic.",
                "Trade only in London session.",
                "Allow only 08:00 and 11:00 UTC entries.",
                "Block weak hours 02:00, 12:00 and 16:00 UTC.",
                f"Allow ATR bands: {', '.join(allowed_atr_bands)}.",
                "Block ATR p20_40.",
                "Reject small confirmation candles below 0.8 ATR.",
                f"Direction filter: {direction_label}.",
            ],
            quantifiable_conditions=list(relaxed.quantifiable_conditions)
            + [
                {"key": "allowed_hours_utc", "layer": "filter", "timeframe": "M5/M1", "rule": "Allow only 08:00 and 11:00 UTC."},
                {"key": "blocked_hours_utc", "layer": "filter", "timeframe": "M5/M1", "rule": "Block 02:00, 12:00 and 16:00 UTC."},
                {"key": "atr_band_filter", "layer": "filter", "timeframe": "M5/M1", "rule": f"Allow ATR bands {', '.join(allowed_atr_bands)} and reject p20_40."},
                {"key": "confirmation_size_filter", "layer": "filter", "timeframe": "M5/M1", "rule": "Reject small confirmation candles below 0.8 ATR."},
            ],
            invalidation_rules=list(relaxed.invalidation_rules),
            simulation_overrides={
                **relaxed.simulation_overrides,
                "validation_profile": "relaxed_filtered_v1",
                "allowed_hours_utc": [8, 11],
                "blocked_hours_utc": [2, 12, 16],
                "allowed_atr_bands": allowed_atr_bands,
                "blocked_atr_bands": ["p20_40"],
                "allowed_confirmation_bands": ["medium_0.8_1.2_atr", "large_1.2_1.8_atr", "extreme_gt_1.8_atr"],
                "blocked_confirmation_bands": ["small_lt_0.8_atr"],
                "direction_filter": direction_filter,
            },
            source_traceability=source_traceability,
        )

    @staticmethod
    def _fallback_relaxed_blueprint() -> ExecutableStrategyBlueprint:
        return ExecutableStrategyBlueprint(
            blueprint_id="blueprint_fallback_relaxed_filtered_source",
            strategy_key="ob_rejection_relaxed_fallback",
            blueprint_name="OB Rejection Relaxed Validation",
            strategy_family="OB Rejection",
            priority=20,
            execution_profile="experimental_relaxed_validation",
            context={"timeframes": ["H1"]},
            valid_zone={},
            confirmation={"timeframes": ["M5", "M1"]},
            entry={"rule": "next open"},
            stop_loss={"rule": "0.10 ATR"},
            take_profit={"rr_min": 1.2},
            risk_management={"risk_percent": 0.5, "session_filter": ["any_session"]},
            operational_checklist=[],
            quantifiable_conditions=[],
            invalidation_rules=[],
            simulation_overrides={
                "relaxed_htf_bias": True,
                "relaxed_order_block": True,
                "relaxed_confirmation_any": True,
                "entry_on_next_open": True,
            },
            source_traceability={},
        )
