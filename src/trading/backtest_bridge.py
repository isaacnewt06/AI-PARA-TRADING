"""Backtest export bridge for phase 3 strategy candidates."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.db.models.knowledge import StrategyCandidate
from src.db.repositories.strategies import QuantifiableConditionRepository, StrategyCandidateRepository
from src.trading.strategy_schemas import (
    BacktestBlueprintSpec,
    ExecutableBlueprintBundle,
    StrategyExportBundle,
    StrategySetupDefinition,
)


class BacktestBridge:
    """Export compiled strategy candidates to structured backtesting files."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.candidate_repository = StrategyCandidateRepository(session)
        self.condition_repository = QuantifiableConditionRepository(session)

    def export_strategies(self, output_path: str, format_name: str | None = None) -> dict:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        candidates = self.candidate_repository.list_candidates()
        definitions = [self._definition_from_candidate(candidate) for candidate in candidates]
        bundle = StrategyExportBundle(strategies=definitions)

        if (format_name or output.suffix.lower().lstrip(".")) == "csv":
            self._write_csv(output, definitions)
        else:
            output.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
        return {"strategies_exported": len(definitions), "output_path": str(output.resolve())}

    def inspect_setup(self, setup_name: str) -> dict | None:
        candidate = self.candidate_repository.get_by_name_or_key(setup_name)
        if candidate is None:
            return None
        components = self.candidate_repository.list_components(candidate.id)
        definition = self._definition_from_candidate(candidate)
        return {
            "definition": definition.model_dump(),
            "components": [
                {
                    "component_type": component.component_type,
                    "component_key": component.component_key,
                    "payload": json.loads(component.component_payload_json) if component.component_payload_json else {},
                    "weight": component.weight,
                }
                for component in components
            ],
        }

    def compare_strategies(self, strategy_a: str, strategy_b: str) -> dict:
        left = self.candidate_repository.get_by_name_or_key(strategy_a)
        right = self.candidate_repository.get_by_name_or_key(strategy_b)
        if left is None or right is None:
            return {"error": "One or both strategies were not found."}
        left_def = self._definition_from_candidate(left)
        right_def = self._definition_from_candidate(right)
        return {
            "strategy_a": left_def.setup_name,
            "strategy_b": right_def.setup_name,
            "shared_symbols": sorted(set(left_def.symbols).intersection(right_def.symbols)),
            "shared_sessions": sorted(set(left_def.allowed_sessions).intersection(right_def.allowed_sessions)),
            "shared_conditions": sorted(
                {
                    item["condition_key"]
                    for item in left_def.required_conditions
                }.intersection({item["condition_key"] for item in right_def.required_conditions})
            ),
            "rr_a": left_def.rr_constraints,
            "rr_b": right_def.rr_constraints,
            "risk_a": left_def.risk_constraints,
            "risk_b": right_def.risk_constraints,
        }

    def export_blueprint_backtests(self, output_dir: str | None = None) -> dict:
        blueprint_dir = self.settings.paths.knowledge_dir / "strategy_blueprints"
        bundle_path = blueprint_dir / "executable_strategy_blueprints.json"
        if not bundle_path.exists():
            return {
                "specs_exported": 0,
                "output_dir": str((self.settings.paths.data_dir / "backtests" / "specs").resolve()),
                "error": "Blueprint bundle not found. Run generate-executable-strategies first.",
            }

        bundle = ExecutableBlueprintBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
        target_dir = Path(output_dir) if output_dir else self.settings.paths.data_dir / "backtests" / "specs"
        target_dir.mkdir(parents=True, exist_ok=True)

        exported = 0
        for blueprint in bundle.blueprints:
            markdown_path = blueprint_dir / f"{self._slugify(blueprint.blueprint_name)}.md"
            markdown_text = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
            spec = self._blueprint_spec(blueprint=blueprint, markdown_text=markdown_text)
            spec_path = target_dir / f"{self._spec_slug(blueprint.blueprint_name)}.json"
            spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
            exported += 1
        return {
            "specs_exported": exported,
            "output_dir": str(target_dir.resolve()),
            "primary_spec": str((target_dir / "ob_rejection_primary.json").resolve()),
        }

    @staticmethod
    def _definition_from_candidate(candidate: StrategyCandidate) -> StrategySetupDefinition:
        return StrategySetupDefinition(
            setup_id=candidate.candidate_key,
            setup_name=candidate.setup_name,
            strategy_family=candidate.strategy_family,
            symbols=json.loads(candidate.symbols_json) if candidate.symbols_json else [],
            context_tf=json.loads(candidate.context_tf_json) if candidate.context_tf_json else [],
            entry_tf=json.loads(candidate.entry_tf_json) if candidate.entry_tf_json else [],
            allowed_sessions=json.loads(candidate.allowed_sessions_json) if candidate.allowed_sessions_json else [],
            required_conditions=json.loads(candidate.required_conditions_json) if candidate.required_conditions_json else [],
            optional_conditions=json.loads(candidate.optional_conditions_json) if candidate.optional_conditions_json else [],
            invalidation_conditions=json.loads(candidate.invalidation_conditions_json) if candidate.invalidation_conditions_json else [],
            confirmation_logic=json.loads(candidate.confirmation_logic_json) if candidate.confirmation_logic_json else [],
            sl_logic=json.loads(candidate.sl_logic_json) if candidate.sl_logic_json else {},
            tp_logic=json.loads(candidate.tp_logic_json) if candidate.tp_logic_json else {},
            rr_constraints=json.loads(candidate.rr_constraints_json) if candidate.rr_constraints_json else {},
            risk_constraints=json.loads(candidate.risk_constraints_json) if candidate.risk_constraints_json else {},
            execution_notes=candidate.execution_notes,
            source_traceability=json.loads(candidate.source_traceability_json) if candidate.source_traceability_json else {},
        )

    @staticmethod
    def _write_csv(output: Path, definitions: list[StrategySetupDefinition]) -> None:
        fields = [
            "setup_id",
            "setup_name",
            "strategy_family",
            "symbols",
            "context_tf",
            "entry_tf",
            "allowed_sessions",
            "required_conditions",
            "sl_logic",
            "tp_logic",
            "rr_constraints",
            "risk_constraints",
            "source_traceability",
        ]
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for definition in definitions:
                row = definition.model_dump()
                writer.writerow({field: json.dumps(row.get(field), ensure_ascii=False) for field in fields})

    def _blueprint_spec(self, *, blueprint, markdown_text: str) -> BacktestBlueprintSpec:
        candidate = self._candidate_for_blueprint(blueprint)
        candidate_definition = self._definition_from_candidate(candidate) if candidate is not None else None
        context_timeframe = list(dict.fromkeys(blueprint.context.get("timeframes", []) or candidate_definition.context_tf if candidate_definition else []))
        if not context_timeframe:
            context_timeframe = ["H1"]
        entry_timeframe = list(dict.fromkeys(blueprint.confirmation.get("timeframes", []) or candidate_definition.entry_tf if candidate_definition else []))
        if not entry_timeframe:
            entry_timeframe = ["M5"]
        required_conditions = self._dedupe_conditions(
            (candidate_definition.required_conditions if candidate_definition else []) + [
                {
                    "condition_key": item["key"],
                    "condition_type": item["layer"],
                    "signal_function": item["key"],
                    "rule": item["rule"],
                    "timeframe": item["timeframe"],
                    "required": True,
                }
                for item in blueprint.quantifiable_conditions
            ]
        )
        confirmation_conditions = [
            item for item in blueprint.quantifiable_conditions if item.get("layer") == "confirmation"
        ]
        condition_map = self._quantifiable_condition_map(blueprint, candidate)
        rr_min = blueprint.take_profit.get("rr_min")
        if rr_min is None and candidate_definition is not None:
            rr_min = candidate_definition.rr_constraints.get("rr_min")
        risk_per_trade = blueprint.risk_management.get("risk_percent")
        if risk_per_trade is None and candidate_definition is not None:
            risk_per_trade = candidate_definition.risk_constraints.get("risk_percent")

        return BacktestBlueprintSpec(
            strategy_name=blueprint.blueprint_name,
            family=blueprint.strategy_family,
            symbols_suggested=self._suggest_symbols(blueprint, candidate_definition),
            context_timeframe=context_timeframe,
            entry_timeframe=entry_timeframe,
            session_filter=blueprint.risk_management.get("session_filter", []) or (candidate_definition.allowed_sessions if candidate_definition else []),
            required_conditions=required_conditions,
            confirmation_conditions=confirmation_conditions,
            entry_logic={
                "description": blueprint.entry.get("rule"),
                "entry_type": blueprint.entry.get("entry_type"),
                "direction_handling": blueprint.entry.get("direction_handling"),
                "checklist": blueprint.operational_checklist,
                "blueprint_markdown_excerpt": markdown_text[:1200],
            },
            sl_logic=blueprint.stop_loss,
            tp_logic=blueprint.take_profit,
            rr_min=rr_min,
            risk_per_trade=risk_per_trade,
            invalidation_conditions=blueprint.invalidation_rules,
            quantifiable_condition_map=condition_map,
            simulation_overrides=blueprint.simulation_overrides,
            source_traceability=blueprint.source_traceability,
        )

    def _candidate_for_blueprint(self, blueprint):
        candidate_keys = blueprint.source_traceability.get("candidate_keys") or []
        for candidate_key in candidate_keys:
            candidate = self.candidate_repository.get_by_name_or_key(candidate_key)
            if candidate is not None:
                return candidate
        setup_names = blueprint.source_traceability.get("setup_names") or []
        for setup_name in setup_names:
            candidate = self.candidate_repository.get_by_name_or_key(setup_name)
            if candidate is not None:
                return candidate
        family_matches = [
            candidate
            for candidate in self.candidate_repository.list_candidates()
            if candidate.strategy_family == blueprint.strategy_family
        ]
        return family_matches[0] if family_matches else None

    def _quantifiable_condition_map(self, blueprint, candidate: StrategyCandidate | None) -> list[dict]:
        normalized_rule_ids = blueprint.source_traceability.get("normalized_rule_ids") or []
        rows = []
        for normalized_rule_id in normalized_rule_ids:
            for condition in self.condition_repository.list_for_rule(int(normalized_rule_id)):
                rows.append(
                    {
                        "normalized_rule_id": normalized_rule_id,
                        "condition_key": condition.condition_key,
                        "condition_type": condition.condition_type,
                        "signal_function": condition.signal_function,
                        "parameters": json.loads(condition.parameters_json) if condition.parameters_json else {},
                        "operator": condition.operator,
                        "threshold": condition.threshold,
                        "timeframe": condition.timeframe,
                        "required": condition.required,
                        "notes": condition.notes,
                    }
                )
        if rows:
            return self._dedupe_conditions(rows)
        return [
            {
                "condition_key": item["key"],
                "condition_type": item["layer"],
                "signal_function": item["key"],
                "parameters": {},
                "operator": None,
                "threshold": None,
                "timeframe": item["timeframe"],
                "required": True,
                "notes": item["rule"],
            }
            for item in blueprint.quantifiable_conditions
        ]

    @staticmethod
    def _dedupe_conditions(conditions: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen: set[str] = set()
        for item in conditions:
            key = "|".join(
                str(item.get(field))
                for field in ("condition_key", "condition_type", "signal_function", "timeframe", "threshold")
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _suggest_symbols(blueprint, candidate_definition: StrategySetupDefinition | None) -> list[str]:
        if candidate_definition and candidate_definition.symbols:
            return BacktestBridge._preferred_broker_symbols(candidate_definition.symbols)
        if blueprint.strategy_family == "OB Rejection":
            return BacktestBridge._preferred_broker_symbols(["XAUUSD", "EURUSD", "GBPUSD", "NAS100"])
        return BacktestBridge._preferred_broker_symbols(["XAUUSD", "EURUSD"])

    @staticmethod
    def _preferred_broker_symbols(symbols: list[str]) -> list[str]:
        preferred: list[str] = []
        seen: set[str] = set()
        exness_suffix_supported = {"XAUUSD", "EURUSD", "GBPUSD", "BTCUSD", "XAGUSD", "NAS100", "US30"}
        for raw_symbol in symbols:
            symbol = (raw_symbol or "").strip()
            if not symbol:
                continue
            candidates: list[str]
            if symbol.endswith("m"):
                base_symbol = symbol[:-1]
                candidates = [symbol]
                if base_symbol:
                    candidates.append(base_symbol)
            elif symbol in exness_suffix_supported:
                candidates = [f"{symbol}m", symbol]
            else:
                candidates = [symbol]
            for candidate in candidates:
                if candidate not in seen:
                    seen.add(candidate)
                    preferred.append(candidate)
        return preferred

    @staticmethod
    def _slugify(value: str) -> str:
        return (
            value.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace(":", "")
            .replace("|", "_")
        )

    @classmethod
    def _spec_slug(cls, value: str) -> str:
        slug = cls._slugify(value)
        if slug.endswith("_blueprint"):
            slug = slug[: -len("_blueprint")]
        return slug
