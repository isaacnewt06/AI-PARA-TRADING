"""Build executable trading blueprints from detected strategies."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from src.db.models.knowledge import StrategyCandidate
from src.db.repositories.strategies import StrategyCandidateRepository, TopStrategyDetectionRepository
from src.trading.strategy_schemas import (
    DetectedStrategySummary,
    ExecutableBlueprintBundle,
    ExecutableStrategyBlueprint,
    ExcludedStrategyBlueprint,
)


class StrategyBlueprintBuilder:
    """Convert detected strategies into executable blueprints."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.candidate_repository = StrategyCandidateRepository(session)
        self.top_strategy_repository = TopStrategyDetectionRepository(session)

    def build(self, prioritize_family: str = "OB Rejection") -> ExecutableBlueprintBundle:
        detected = [self._detected_summary(row) for row in self.top_strategy_repository.list_ranked()]
        candidates = self.candidate_repository.list_candidates()

        blueprints: list[ExecutableStrategyBlueprint] = []
        excluded: list[ExcludedStrategyBlueprint] = []
        priority_counter = 1
        prioritized = sorted(
            detected,
            key=lambda item: (
                0 if (item.strategy_family or "") == prioritize_family else 1,
                -item.relevance_score,
                item.name.lower(),
            ),
        )
        for item in prioritized:
            candidate = self._best_candidate(item, candidates)
            if not self._is_executable(item, candidate):
                excluded.append(
                    ExcludedStrategyBlueprint(
                        strategy_key=item.strategy_key,
                        name=item.name,
                        strategy_family=item.strategy_family,
                        reason="Insufficient operational specificity. Excluded instead of exporting ambiguous rules.",
                        evidence=item.evidence,
                    )
                )
                continue
            if item.strategy_family == "OB Rejection":
                blueprints.append(self._build_ob_rejection(item, candidate, priority_counter))
                priority_counter += 1
                continue
            excluded.append(
                ExcludedStrategyBlueprint(
                    strategy_key=item.strategy_key,
                    name=item.name,
                    strategy_family=item.strategy_family,
                    reason="Strategy family not yet promoted to executable blueprint template.",
                    evidence=item.evidence,
                )
            )

        return ExecutableBlueprintBundle(
            generated_at=datetime.now(timezone.utc).isoformat(),
            blueprints=blueprints,
            excluded_strategies=excluded,
        )

    def export(self, output_dir: Path, prioritize_family: str = "OB Rejection") -> dict:
        bundle = self.build(prioritize_family=prioritize_family)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "executable_strategy_blueprints.json"
        json_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")

        for blueprint in bundle.blueprints:
            md_path = output_dir / f"{self._safe_name(blueprint.blueprint_name)}.md"
            md_path.write_text(self._markdown_for_blueprint(blueprint), encoding="utf-8")

        excluded_path = output_dir / "excluded_strategies.json"
        excluded_path.write_text(
            json.dumps([item.model_dump() for item in bundle.excluded_strategies], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "blueprints_created": len(bundle.blueprints),
            "excluded_strategies": len(bundle.excluded_strategies),
            "output_dir": str(output_dir.resolve()),
            "primary_blueprint": bundle.blueprints[0].blueprint_name if bundle.blueprints else None,
        }

    @staticmethod
    def _detected_summary(row) -> DetectedStrategySummary:
        return DetectedStrategySummary(
            strategy_key=row.strategy_key,
            name=row.name,
            strategy_family=row.strategy_family,
            concepts=json.loads(row.concepts_json) if row.concepts_json else [],
            assets=json.loads(row.assets_json) if row.assets_json else [],
            timeframes=json.loads(row.timeframes_json) if row.timeframes_json else [],
            sessions=json.loads(row.sessions_json) if row.sessions_json else [],
            entry_types=json.loads(row.entry_types_json) if row.entry_types_json else [],
            supporting_setup_names=json.loads(row.supporting_setup_names_json) if row.supporting_setup_names_json else [],
            source_count=row.source_count,
            author_count=row.author_count,
            channel_count=row.channel_count,
            rule_count=row.rule_count,
            candidate_count=row.candidate_count,
            completeness_score=row.completeness_score,
            frequency_score=row.frequency_score,
            source_diversity_score=row.source_diversity_score,
            execution_definition_score=row.execution_definition_score,
            relevance_score=row.relevance_score,
            summary=row.summary,
            evidence=json.loads(row.evidence_json) if row.evidence_json else {},
        )

    @staticmethod
    def _is_executable(strategy: DetectedStrategySummary, candidate: StrategyCandidate | None) -> bool:
        if strategy.strategy_family == "General":
            return False
        if candidate is None:
            return False
        if strategy.execution_definition_score < 0.45:
            return False
        return bool(strategy.entry_types or strategy.concepts or strategy.strategy_family == "OB Rejection")

    def _best_candidate(
        self,
        strategy: DetectedStrategySummary,
        candidates: list[StrategyCandidate],
    ) -> StrategyCandidate | None:
        setup_names = set(strategy.supporting_setup_names)
        for candidate in candidates:
            if candidate.setup_name in setup_names:
                return candidate
        family_matches = [candidate for candidate in candidates if candidate.strategy_family == strategy.strategy_family]
        if not family_matches:
            return None
        if strategy.sessions:
            for candidate in family_matches:
                sessions = json.loads(candidate.allowed_sessions_json) if candidate.allowed_sessions_json else []
                if any(session in sessions for session in strategy.sessions):
                    return candidate
        return sorted(family_matches, key=lambda item: (-(item.coherence_score or 0.0), item.setup_name))[0]

    def _build_ob_rejection(
        self,
        strategy: DetectedStrategySummary,
        candidate: StrategyCandidate | None,
        priority: int,
    ) -> ExecutableStrategyBlueprint:
        context_tf = json.loads(candidate.context_tf_json) if candidate and candidate.context_tf_json else []
        entry_tf = json.loads(candidate.entry_tf_json) if candidate and candidate.entry_tf_json else []
        sessions = json.loads(candidate.allowed_sessions_json) if candidate and candidate.allowed_sessions_json else strategy.sessions
        rr_constraints = json.loads(candidate.rr_constraints_json) if candidate and candidate.rr_constraints_json else {}
        risk_constraints = json.loads(candidate.risk_constraints_json) if candidate and candidate.risk_constraints_json else {}
        source_traceability = json.loads(candidate.source_traceability_json) if candidate and candidate.source_traceability_json else strategy.evidence
        primary_context_tf = context_tf[0] if context_tf else "H1"
        primary_entry_tf = entry_tf[0] if entry_tf else ("M5" if "M5" in strategy.timeframes or not strategy.timeframes else strategy.timeframes[0])
        entry_tf_effective = entry_tf or [tf for tf in strategy.timeframes if tf in {"M5", "M1"}] or ["M5"]
        rr_min = rr_constraints.get("rr_min") or 2.0
        risk_percent = risk_constraints.get("risk_percent") or 0.5
        profile = "primary" if priority == 1 else "variant"
        blueprint_name = (
            "OB Rejection Primary Blueprint"
            if priority == 1
            else f"OB Rejection Variant {priority}"
        )
        session_label = sessions or ["london", "new_york"] if priority == 1 else sessions

        quantifiable_conditions = [
            {
                "key": "htf_bias_aligned",
                "layer": "context",
                "timeframe": primary_context_tf,
                "rule": "Trend direction valid when EMA20 is above EMA50 and EMA20 slope is positive for longs, or inverse for shorts.",
            },
            {
                "key": "market_structure_valid",
                "layer": "context",
                "timeframe": primary_context_tf,
                "rule": "Require a confirmed BOS in trade direction within the last 20 candles on HTF.",
            },
            {
                "key": "unmitigated_order_block",
                "layer": "zone",
                "timeframe": primary_context_tf,
                "rule": "Valid zone is the last displacement-origin candle before BOS that has not been fully closed through after creation.",
            },
            {
                "key": "rejection_confirmation",
                "layer": "confirmation",
                "timeframe": "/".join(entry_tf_effective),
                "rule": "At the OB, require either engulfing, displacement candle, or wick rejection with close back outside 50% of the block.",
            },
            {
                "key": "entry_trigger",
                "layer": "entry",
                "timeframe": "/".join(entry_tf_effective),
                "rule": "Enter on retest of the rejection candle 50% or immediately at rejection candle close if the next candle does not revisit entry by more than 25% of block width.",
            },
            {
                "key": "stop_placement",
                "layer": "risk",
                "timeframe": "/".join(entry_tf_effective),
                "rule": "Stop goes beyond OB extreme plus a 0.10 ATR(14) buffer on the entry timeframe.",
            },
            {
                "key": "take_profit_prior_liquidity",
                "layer": "exit",
                "timeframe": primary_context_tf,
                "rule": f"Primary target is prior opposing liquidity or swing, but trade is valid only if projected RR is at least {rr_min}:1.",
            },
            {
                "key": "session_filter",
                "layer": "filter",
                "timeframe": "/".join(entry_tf_effective),
                "rule": f"Only execute during {', '.join(session_label)}.",
            },
        ]

        if priority == 1:
            quantifiable_conditions.insert(
                3,
                {
                    "key": "ob_not_mitigated",
                    "layer": "zone",
                    "timeframe": primary_context_tf,
                    "rule": "Cancel zone if a full candle body closes through the midpoint of the OB before entry.",
                },
            )

        return ExecutableStrategyBlueprint(
            blueprint_id=self._blueprint_id(strategy.strategy_key, blueprint_name),
            strategy_key=strategy.strategy_key,
            blueprint_name=blueprint_name,
            strategy_family="OB Rejection",
            priority=priority,
            execution_profile=profile,
            context={
                "htf_bias": f"Use {primary_context_tf} to define bullish or bearish bias. Trade only in the direction of a clear trend and valid market structure.",
                "bias_rule": "Bullish if BOS up + EMA20 > EMA50. Bearish if BOS down + EMA20 < EMA50.",
                "timeframes": context_tf or [primary_context_tf],
            },
            valid_zone={
                "zone_type": "unmitigated_order_block",
                "rule": "Select the last opposing candle before displacement that caused BOS. The block remains valid only while not fully mitigated.",
                "location_filter": "Prefer blocks formed at discount for longs and premium for shorts inside the current dealing range.",
            },
            confirmation={
                "timeframes": entry_tf_effective,
                "rule": "Require a strong rejection from the block on M5 or M1 with engulfing, displacement, or rejection wick closing back in trade direction.",
                "reject_if": "No trade if price drifts inside the block without rejection impulse.",
            },
            entry={
                "rule": "Primary entry is the retest of the rejection candle or OB edge. Secondary entry is immediate reaction close when momentum leaves the block fast.",
                "entry_type": "retest_or_immediate_reaction",
                "direction_handling": "Mirror logic for bullish and bearish setups.",
            },
            stop_loss={
                "rule": "Place stop below bullish OB low or above bearish OB high with 0.10 ATR buffer.",
                "hard_invalidation": "Any close through the OB invalidation level before target hit exits the trade.",
            },
            take_profit={
                "rule": "Target previous opposing liquidity, prior swing high/low, or liquidity pool ahead of price.",
                "rr_min": rr_min,
                "management": "If first liquidity is hit before full target and RR >= 1.5, partials are allowed while trailing behind structure.",
            },
            risk_management={
                "risk_percent": risk_percent,
                "risk_rule": "Risk per trade stays fixed and must be reduced to zero if RR projection is below threshold.",
                "max_open_positions": 1,
                "session_filter": session_label,
            },
            operational_checklist=[
                f"Confirm {primary_context_tf} bias is aligned and structure is valid.",
                "Mark the freshest unmitigated order block that caused displacement.",
                f"Wait for price to tap the block during {', '.join(session_label)}.",
                f"Require M5 or M1 rejection confirmation before entry.",
                "Enter on retest or immediate reaction according to momentum behavior.",
                "Set stop beyond OB extreme plus ATR buffer.",
                f"Reject the trade if projected RR is below {rr_min}:1.",
                "Target prior liquidity and manage partials only after structure confirms.",
            ],
            quantifiable_conditions=quantifiable_conditions,
            invalidation_rules=[
                "Cancel the setup if price closes through the OB midpoint before confirmation.",
                "Cancel the setup if HTF bias flips before entry.",
                "Cancel the setup if available liquidity target does not satisfy minimum RR.",
            ],
            simulation_overrides={},
            source_traceability=source_traceability,
        )

    @staticmethod
    def _blueprint_id(strategy_key: str, blueprint_name: str) -> str:
        digest = hashlib.sha1(f"{strategy_key}|{blueprint_name}".encode("utf-8")).hexdigest()[:12]
        return f"blueprint_{digest}"

    @staticmethod
    def _safe_name(value: str) -> str:
        return (
            value.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace(":", "")
            .replace("|", "_")
        )

    @staticmethod
    def _markdown_for_blueprint(blueprint: ExecutableStrategyBlueprint) -> str:
        sections = [
            f"# {blueprint.blueprint_name}",
            "",
            f"- strategy_family: {blueprint.strategy_family}",
            f"- strategy_key: {blueprint.strategy_key}",
            f"- priority: {blueprint.priority}",
            f"- execution_profile: {blueprint.execution_profile}",
            "",
            "## Contexto HTF",
            f"- {blueprint.context.get('htf_bias')}",
            f"- bias_rule: {blueprint.context.get('bias_rule')}",
            "",
            "## Zona valida",
            f"- {blueprint.valid_zone.get('rule')}",
            f"- location_filter: {blueprint.valid_zone.get('location_filter')}",
            "",
            "## Confirmacion",
            f"- {blueprint.confirmation.get('rule')}",
            f"- reject_if: {blueprint.confirmation.get('reject_if')}",
            "",
            "## Entrada",
            f"- {blueprint.entry.get('rule')}",
            "",
            "## Stop Loss",
            f"- {blueprint.stop_loss.get('rule')}",
            "",
            "## Take Profit",
            f"- {blueprint.take_profit.get('rule')}",
            f"- rr_min: {blueprint.take_profit.get('rr_min')}",
            "",
            "## Gestion de riesgo",
            f"- risk_percent: {blueprint.risk_management.get('risk_percent')}",
            f"- {blueprint.risk_management.get('risk_rule')}",
            "",
            "## Checklist operativo",
        ]
        sections.extend(f"- {item}" for item in blueprint.operational_checklist)
        sections.extend(["", "## Condiciones cuantificables"])
        sections.extend(
            f"- {item['key']} [{item['layer']} {item['timeframe']}]: {item['rule']}"
            for item in blueprint.quantifiable_conditions
        )
        if blueprint.simulation_overrides:
            sections.extend(["", "## Backtest Overrides"])
            sections.extend(
                f"- {key}: {value}"
                for key, value in blueprint.simulation_overrides.items()
            )
        return "\n".join(sections) + "\n"
