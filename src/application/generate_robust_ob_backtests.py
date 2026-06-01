"""Generate directional and dynamic-exit OB Rejection backtest specs."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.trading.strategy_schemas import BacktestBlueprintSpec


class RobustOBBacktestGenerationApplicationService:
    """Create targeted long/short and exit-management OB Rejection specs."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self) -> dict:
        specs_dir = self.settings.paths.data_dir / "backtests" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        docs_dir = self.settings.paths.knowledge_dir / "strategy_blueprints"
        docs_dir.mkdir(parents=True, exist_ok=True)

        primary_base_path = specs_dir / "ob_rejection_primary.json"
        relaxed_base_path = specs_dir / "ob_rejection_relaxed_validation.json"
        base_path = primary_base_path if primary_base_path.exists() else relaxed_base_path
        if not base_path.exists():
            raise FileNotFoundError(
                "Expected a base OB Rejection spec at "
                f"{primary_base_path} or fallback {relaxed_base_path}."
            )
        base_spec = BacktestBlueprintSpec.model_validate_json(base_path.read_text(encoding="utf-8"))

        variants = [
            self._directional_variant(base_spec, name="OB Rejection Short Only", direction_filter="short_only"),
            self._directional_variant(base_spec, name="OB Rejection Long Only", direction_filter="long_only"),
            self._managed_variant(
                base_spec,
                name="OB Rejection Short Only Partial 1R 2R",
                direction_filter="short_only",
                exit_management="partial_1r_then_2r",
                rr_min=1.2,
            ),
            self._managed_variant(
                base_spec,
                name="OB Rejection Short Only Break Even",
                direction_filter="short_only",
                exit_management="break_even_after_1r",
                rr_min=1.2,
            ),
            self._managed_variant(
                base_spec,
                name="OB Rejection Short Only Trailing ATR",
                direction_filter="short_only",
                exit_management="trailing_atr_after_1r",
                rr_min=1.2,
            ),
            self._managed_variant(
                base_spec,
                name="OB Rejection Long Only Partial 1R 2R",
                direction_filter="long_only",
                exit_management="partial_1r_then_2r",
                rr_min=1.2,
            ),
            self._managed_variant(
                base_spec,
                name="OB Rejection Long Only Break Even",
                direction_filter="long_only",
                exit_management="break_even_after_1r",
                rr_min=1.2,
            ),
            self._managed_variant(
                base_spec,
                name="OB Rejection Long Only Trailing ATR",
                direction_filter="long_only",
                exit_management="trailing_atr_after_1r",
                rr_min=1.2,
            ),
        ]

        written_specs: list[str] = []
        for variant in variants:
            spec_path = specs_dir / f"{self._slug(variant.strategy_name)}.json"
            spec_path.write_text(variant.model_dump_json(indent=2), encoding="utf-8")
            written_specs.append(str(spec_path.resolve()))
            doc_path = docs_dir / f"{self._slug(variant.strategy_name)}.md"
            doc_path.write_text(self._markdown_for_variant(variant), encoding="utf-8")

        manifest_path = specs_dir / "ob_rejection_robustness_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "base_spec": str(base_path.resolve()),
                    "generated_specs": written_specs,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "generated_specs": len(written_specs),
            "manifest_path": str(manifest_path.resolve()),
            "spec_paths": written_specs,
        }

    def _directional_variant(self, base_spec: BacktestBlueprintSpec, *, name: str, direction_filter: str) -> BacktestBlueprintSpec:
        payload = base_spec.model_dump()
        overrides = dict(payload.get("simulation_overrides") or {})
        overrides.update(
            {
                "validation_profile": "directional_ob_rejection",
                "direction_filter": direction_filter,
                "exit_management": "static",
                "required_rejection_signals": ["wick_rejection"],
                "blocked_hours_utc": [2, 3, 12, 16, 23],
                "max_range_atr_multiple": 2.0,
            }
        )
        payload["strategy_name"] = name
        payload["simulation_overrides"] = overrides
        traceability = dict(payload.get("source_traceability") or {})
        traceability["derived_from_spec"] = base_spec.strategy_name
        traceability["variant_type"] = "directional_only"
        payload["source_traceability"] = traceability
        return BacktestBlueprintSpec.model_validate(payload)

    def _managed_variant(
        self,
        base_spec: BacktestBlueprintSpec,
        *,
        name: str,
        direction_filter: str,
        exit_management: str,
        rr_min: float,
    ) -> BacktestBlueprintSpec:
        payload = base_spec.model_dump()
        overrides = dict(payload.get("simulation_overrides") or {})
        overrides.update(
            {
                "validation_profile": "directional_dynamic_exit_ob_rejection",
                "direction_filter": direction_filter,
                "exit_management": exit_management,
                "trail_atr_multiple": 1.0,
                "required_rejection_signals": ["wick_rejection"],
                "blocked_hours_utc": [2, 3, 12, 16, 23],
                "max_range_atr_multiple": 2.0,
            }
        )
        payload["strategy_name"] = name
        payload["rr_min"] = rr_min
        payload["simulation_overrides"] = overrides
        traceability = dict(payload.get("source_traceability") or {})
        traceability["derived_from_spec"] = base_spec.strategy_name
        traceability["variant_type"] = exit_management
        payload["source_traceability"] = traceability
        return BacktestBlueprintSpec.model_validate(payload)

    @staticmethod
    def _markdown_for_variant(spec: BacktestBlueprintSpec) -> str:
        overrides = spec.simulation_overrides or {}
        lines = [
            f"# {spec.strategy_name}",
            "",
            f"- family: {spec.family}",
            f"- sessions: {', '.join(spec.session_filter) if spec.session_filter else 'any_session'}",
            f"- rr_min: {spec.rr_min}",
            f"- direction_filter: {overrides.get('direction_filter', 'both')}",
            f"- exit_management: {overrides.get('exit_management', 'static')}",
            "",
            "## Notes",
            "- Generated for robustness validation outside the broad Relaxed profile.",
            "- This variant preserves OB Rejection core logic and changes only direction and/or exit management.",
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _slug(value: str) -> str:
        return (
            value.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace(":", "")
            .replace("|", "_")
        )
