"""Continuous knowledge-to-trading-brain learning cycle."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.application.build_knowledge_base import KnowledgeBuildApplicationService
from src.application.build_market_situation_map import MarketSituationMapApplicationService
from src.application.build_semantic_index import SemanticIndexApplicationService
from src.application.catalog_reports import CatalogReportService
from src.application.compile_setups import SetupCompilationApplicationService
from src.application.detect_strategies import StrategyDetectionApplicationService
from src.application.extract_trading_rules import TradingRuleExtractionApplicationService
from src.application.generate_playbooks import PlaybookGenerationApplicationService
from src.application.import_local_education_source import LocalEducationImportService
from src.application.import_manual_knowledge import ManualKnowledgeImportService
from src.application.inspect_archives import ArchiveInspectionApplicationService
from src.application.normalize_rules import RuleNormalizationApplicationService
from src.application.process_cataloged_assets import CatalogedAssetProcessingService
from src.application.score_rules import QualityScoringApplicationService
from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import (
    ContentChunk,
    ExtractedRule,
    NormalizedRule,
    StrategyCandidate,
    StrategyPlaybook,
    TopStrategyDetected,
)
from src.db.models.platform import LearningIntegration
from src.telegram.sync_service import TelegramSyncOptions

logger = get_logger(__name__)


@dataclass(slots=True)
class KnowledgeLearningCycleOptions:
    """Controls one or more continuous learning cycles."""

    channels: list[str] | None = None
    cycles: int = 1
    sleep_seconds: int = 0
    doc_limit: int = 8
    media_limit: int = 8
    archive_limit: int = 2
    inspect_limit: int = 12
    skip_sync: bool = False
    skip_market_map: bool = False
    rebuild_semantic_index: bool = False


class KnowledgeLearningCycleApplicationService:
    """Turn raw material into auditable, applicable trading knowledge."""

    IMPORTANT_FILE_EVENTS = {
        "downloaded",
        "extracted",
        "transcribed",
        "processed",
        "completed",
        "failed",
        "queued",
        "partial",
        "skipped_by_size",
        "inspection_file_missing",
    }

    def __init__(
        self,
        session: Session,
        settings: Settings,
        ingestion_service: Any | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.ingestion_service = ingestion_service

    def run(self, options: KnowledgeLearningCycleOptions) -> dict[str, Any]:
        cycle_results: list[dict[str, Any]] = []
        cycles = max(1, options.cycles)
        for index in range(cycles):
            cycle_results.append(self.run_once(options, cycle_number=index + 1, total_cycles=cycles))
            if index < cycles - 1 and options.sleep_seconds > 0:
                sleep(options.sleep_seconds)
        return {
            "cycles_requested": cycles,
            "cycles_completed": len(cycle_results),
            "latest_report": cycle_results[-1] if cycle_results else {},
        }

    def run_once(
        self,
        options: KnowledgeLearningCycleOptions,
        *,
        cycle_number: int = 1,
        total_cycles: int = 1,
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        before = self._snapshot_counts()
        phase_results = [self._run_phase(name, runner) for name, runner in self._build_phases(options)]
        after = self._snapshot_counts()
        payload = self._build_report_payload(
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            cycle_number=cycle_number,
            total_cycles=total_cycles,
            before=before,
            after=after,
            phase_results=phase_results,
        )
        self._mark_learning_integrations_synced(payload)
        paths = self._write_reports(payload)
        self.session.commit()
        return {
            "cycle_number": cycle_number,
            "status": payload["status"],
            "knowledge_delta": payload["knowledge_delta"],
            "applicability": payload["applicable_knowledge"]["applicability"],
            "reports": paths,
        }

    def _build_phases(self, options: KnowledgeLearningCycleOptions) -> list[tuple[str, Callable[[], Any]]]:
        processing = CatalogedAssetProcessingService(self.session, self.settings)
        archive_service = ArchiveInspectionApplicationService(self.session)
        phases: list[tuple[str, Callable[[], Any]]] = []

        if not options.skip_sync:
            for channel in self._target_channels(options.channels):
                phases.append(
                    (
                        f"sync-catalog:{channel}",
                        lambda channel_ref=channel: asyncio.run(
                            self.ingestion_service.sync(
                                channel_reference=channel_ref,
                                mode="incremental",
                                options=TelegramSyncOptions(catalog_only=True, commit_every=1),
                            )
                        ),
                    )
                )

        phases.extend(self._local_knowledge_import_phases())
        phases.extend(
            [
                ("catalog-report", lambda: CatalogReportService(self.session).run()),
                ("rebuild-knowledge-base", lambda: KnowledgeBuildApplicationService(self.session, self.settings).run(filtered=True)),
                ("extract-rules", lambda: TradingRuleExtractionApplicationService(self.session).run()),
                ("normalize-rules", lambda: RuleNormalizationApplicationService(self.session).run()),
                ("generate-playbooks", lambda: PlaybookGenerationApplicationService(self.session).run()),
                ("compile-setups", lambda: SetupCompilationApplicationService(self.session).run(score=True)),
                ("score-rules", lambda: QualityScoringApplicationService(self.session).run()),
                ("detect-strategies", lambda: StrategyDetectionApplicationService(self.session).run()),
            ]
        )
        if options.doc_limit > 0:
            phases[1:1] = [
                ("rank-documents", lambda: processing.rank_documents(limit=options.doc_limit)),
                ("process-documents", lambda: processing.process_top_documents(limit=options.doc_limit)),
                ("process-external-links", lambda: processing.process_external_links(limit=options.doc_limit)),
            ]
        if options.media_limit > 0:
            insert_at = 1 + (3 if options.doc_limit > 0 else 0)
            phases[insert_at:insert_at] = [
                ("process-images", lambda: processing.process_images(limit=options.media_limit)),
                ("process-videos-audios", lambda: processing.process_videos(limit=options.media_limit)),
            ]
        if options.archive_limit > 0 or options.inspect_limit > 0:
            archive_phases: list[tuple[str, Callable[[], Any]]] = []
            if options.inspect_limit > 0:
                archive_phases.append(("inspect-archives", lambda: archive_service.inspect(limit=options.inspect_limit)))
            if options.archive_limit > 0:
                archive_phases.extend(
                    [
                        ("rank-archives", lambda: archive_service.rank(limit=options.archive_limit)),
                        ("select-archives", lambda: archive_service.select(limit=options.archive_limit)),
                        ("process-selected-archives", lambda: processing.process_selected_archives(limit=options.archive_limit)),
                    ]
                )
            insert_at = 1 + (3 if options.doc_limit > 0 else 0) + (2 if options.media_limit > 0 else 0)
            phases[insert_at:insert_at] = archive_phases
        if options.rebuild_semantic_index:
            phases.append(("build-semantic-index", lambda: SemanticIndexApplicationService(self.session, self.settings).run(rebuild=True)))
        if not options.skip_market_map:
            phases.append(("build-market-situation-map", lambda: MarketSituationMapApplicationService(self.session, self.settings).run()))
        phases.append(("cycle-status", self._snapshot_counts))
        return phases

    def _local_knowledge_import_phases(self) -> list[tuple[str, Callable[[], Any]]]:
        """Import curated non-Telegram sources without sending them through Telegram sync."""

        rows = list(
            self.session.scalars(
                select(LearningIntegration)
                .where(LearningIntegration.enabled.is_(True))
                .where(LearningIntegration.auto_sync.is_(True))
                .order_by(LearningIntegration.id.asc())
            )
        )
        phases: list[tuple[str, Callable[[], Any]]] = []
        manual_added = False
        local_paths: dict[str, Path] = {}
        for row in rows:
            if row.source_type == "manual_knowledge" and not manual_added:
                root_dir = self.settings.paths.data_dir / "knowledge" / "manual"
                phases.append(("import-manual-knowledge", lambda root_dir=root_dir: ManualKnowledgeImportService(self.session, root_dir).run()))
                manual_added = True
                continue
            if row.source_type == "local_education":
                root_dir = self._resolve_local_education_path(row.source_reference)
                local_paths[str(root_dir.resolve() if root_dir.exists() else root_dir)] = root_dir

        for root_dir in local_paths.values():
            phase_name = f"import-local-education:{root_dir.name}"
            phases.append((phase_name, lambda root_dir=root_dir: self._run_local_education_import(root_dir)))
        return phases

    def _run_local_education_import(self, root_dir: Path) -> dict[str, Any]:
        if not root_dir.exists():
            return {
                "source": str(root_dir),
                "status": "skipped_missing_path",
                "reason": "Local education source is registered, but the folder is not available on this machine.",
            }
        return LocalEducationImportService(self.session, self.settings, root_dir).run()

    def _resolve_local_education_path(self, source_reference: str | None) -> Path:
        source = (source_reference or "").replace("local-education://", "").strip()
        candidates: list[Path] = []
        if source:
            candidates.extend(
                [
                    Path(source),
                    self.settings.project_root / source,
                    self.settings.project_root / source.upper(),
                    self.settings.project_root / source.title(),
                    self.settings.paths.data_dir / "knowledge" / source,
                ]
            )
        candidates.extend(
            [
                self.settings.project_root / "TRADING EDUCATION",
                self.settings.project_root / "Trading Education",
                self.settings.paths.data_dir / "knowledge" / "local_education",
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0] if candidates else self.settings.project_root / "TRADING EDUCATION"

    def _run_phase(self, phase_name: str, runner: Callable[[], Any]) -> dict[str, Any]:
        logger.info("knowledge-learning-cycle phase started: %s", phase_name)
        try:
            result = runner()
            self.session.commit()
            logger.info("knowledge-learning-cycle phase completed: %s", phase_name)
            return {"phase": phase_name, "status": "completed", "result": result}
        except Exception as exc:
            self.session.rollback()
            logger.warning("knowledge-learning-cycle phase failed: %s | %s", phase_name, exc, exc_info=True)
            return {"phase": phase_name, "status": "failed", "error": str(exc)}

    def _target_channels(self, requested: list[str] | None) -> list[str]:
        if self.ingestion_service is None:
            return []
        if requested:
            return [item for item in requested if item and self._is_syncable_channel_reference(item)]
        rows = self.session.scalars(select(Channel).where(Channel.is_active.is_(True)).order_by(Channel.title.asc()))
        return [row.input_reference for row in rows if self._is_syncable_channel_reference(row.input_reference)]

    @staticmethod
    def _is_syncable_channel_reference(reference: str | None) -> bool:
        value = (reference or "").strip().lower()
        return value.startswith("https://t.me/") or value.startswith("http://t.me/") or value.startswith("@")

    def _snapshot_counts(self) -> dict[str, Any]:
        counts = {
            "channels": self.session.scalar(select(func.count()).select_from(Channel)) or 0,
            "messages": self._safe_count("telegram_messages"),
            "files": self.session.scalar(select(func.count()).select_from(FileAsset)) or 0,
            "chunks": self.session.scalar(select(func.count()).select_from(ContentChunk)) or 0,
            "extracted_rules": self.session.scalar(select(func.count()).select_from(ExtractedRule)) or 0,
            "normalized_rules": self.session.scalar(select(func.count()).select_from(NormalizedRule)) or 0,
            "strategy_candidates": self.session.scalar(select(func.count()).select_from(StrategyCandidate)) or 0,
            "strategy_playbooks": self.session.scalar(select(func.count()).select_from(StrategyPlaybook)) or 0,
            "top_strategies": self.session.scalar(select(func.count()).select_from(TopStrategyDetected)) or 0,
        }
        return counts | {
            "files_by_category": self._count_grouped(FileAsset.category),
            "files_by_status": self._count_grouped(FileAsset.status),
            "files_by_processing_status": self._count_grouped(FileAsset.processing_status),
        }

    def _safe_count(self, table_name: str) -> int:
        from sqlalchemy import text

        return int(self.session.scalar(text(f"select count(*) from {table_name}")) or 0)

    def _count_grouped(self, column: Any) -> dict[str, int]:
        rows = self.session.execute(select(column, func.count()).group_by(column)).all()
        return {str(key or "unknown"): int(count) for key, count in rows}

    def _build_report_payload(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        cycle_number: int,
        total_cycles: int,
        before: dict[str, Any],
        after: dict[str, Any],
        phase_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        failed = [item for item in phase_results if item["status"] == "failed"]
        applicable = self._applicable_knowledge_summary(after)
        return {
            "status": "completed_with_warnings" if failed else "completed",
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "cycle_number": cycle_number,
            "total_cycles": total_cycles,
            "phases": phase_results,
            "failed_phases": failed,
            "knowledge_before": before,
            "knowledge_after": after,
            "knowledge_delta": self._delta(before, after),
            "knowledge_change_interpretation": self._knowledge_change_interpretation(before, after),
            "applicable_knowledge": applicable,
            "risk_governance": self._risk_governance_summary(),
            "learning_principle": {
                "market_reliability": "probabilistic_not_100_percent",
                "execution_posture": "keep_watch_active_wait_for_confirmed_trigger",
                "capital_protection": "risk_is_scaled_by_quality_probability_and_context",
            },
        }

    def _applicable_knowledge_summary(self, counts: dict[str, Any]) -> dict[str, Any]:
        normalized = list(self.session.scalars(select(NormalizedRule).order_by(NormalizedRule.id.asc())))
        detected = list(self.session.scalars(select(TopStrategyDetected).order_by(TopStrategyDetected.relevance_score.desc()).limit(8)))
        family_counts = Counter(rule.strategy_family or "unknown" for rule in normalized)
        setup_counts = Counter(rule.setup_name or "unknown" for rule in normalized)
        concepts = Counter()
        regimes = Counter()
        directions = Counter()
        for rule in normalized:
            concepts.update(self._json_list(rule.concept_tags))
            regimes.update(self._json_list(rule.market_conditions) or ["mixed"])
            directions[rule.direction_bias or "both"] += 1

        pattern_coverage = min(1.0, (counts["normalized_rules"] / 150.0) * 0.45 + (counts["strategy_candidates"] / 20.0) * 0.35 + (counts["top_strategies"] / 10.0) * 0.20)
        risk_defined = self._risk_defined_ratio(normalized)
        applicability_score = round((pattern_coverage * 0.7) + (risk_defined * 0.3), 3)
        if applicability_score >= 0.75:
            level = "operationally_useful"
        elif applicability_score >= 0.45:
            level = "developing"
        else:
            level = "insufficient"

        return {
            "applicability": {"score": applicability_score, "level": level},
            "dominant_strategy_families": [{"family": name, "rules": count} for name, count in family_counts.most_common(8)],
            "dominant_setups": [{"setup": name, "rules": count} for name, count in setup_counts.most_common(8)],
            "recognized_patterns": [{"pattern": name, "count": count} for name, count in concepts.most_common(12)],
            "market_contexts": [{"context": name, "count": count} for name, count in regimes.most_common(10)],
            "directional_bias_distribution": dict(directions.most_common()),
            "strategy_combinations": self._strategy_combinations(detected, family_counts),
            "top_detected_strategies": [
                {
                    "name": item.name,
                    "family": item.strategy_family,
                    "relevance_score": item.relevance_score,
                    "rule_count": item.rule_count,
                    "candidate_count": item.candidate_count,
                }
                for item in detected
            ],
        }

    def _strategy_combinations(self, detected: list[TopStrategyDetected], family_counts: Counter[str]) -> list[dict[str, Any]]:
        combinations: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        top_families = [name for name, _ in family_counts.most_common(5)]
        for item in detected[:5]:
            family = item.strategy_family or "General"
            companion = next((name for name in top_families if name != family), None) or "risk_management"
            key = (family, companion)
            if key in seen:
                continue
            seen.add(key)
            combinations.append(
                {
                    "primary": family,
                    "secondary": companion,
                    "use_case": self._combination_use_case(family, companion),
                    "confidence_basis": {
                        "detected_strategy_score": round(float(item.relevance_score or 0), 3),
                        "supporting_rules": int(item.rule_count or 0),
                    },
                }
            )
        return combinations

    def _combination_use_case(self, primary: str, secondary: str) -> str:
        text = f"{primary} {secondary}".lower()
        if "ob" in text or "order" in text:
            return "Use order-block context as the zone, then wait for liquidity/confirmation before execution."
        if "breakout" in text or "expansion" in text:
            return "Use expansion only after momentum confirms and risk/reward remains evaluable."
        if "fvg" in text:
            return "Use imbalance continuation with reduced risk until structure confirms."
        return "Use as contextual confluence, not as a standalone reason to trade."

    def _risk_governance_summary(self) -> dict[str, Any]:
        rules = list(self.session.scalars(select(NormalizedRule).order_by(NormalizedRule.id.asc())))
        if not rules:
            return {
                "status": "needs_more_rules",
                "principles": [
                    "No execute without logical stop loss.",
                    "No execute without evaluable risk reward.",
                    "Scale risk down when probability or context quality is medium.",
                ],
            }
        raw_risk_values = [rule.risk_percent for rule in rules if rule.risk_percent is not None]
        risk_values = [value for value in raw_risk_values if 0 < value <= 5]
        rr_values = [rule.rr_target for rule in rules if rule.rr_target is not None]
        stop_defined = sum(1 for rule in rules if rule.stop_model not in {None, "", "unknown"})
        return {
            "status": "available",
            "average_risk_percent": round(sum(risk_values) / len(risk_values), 3) if risk_values else None,
            "ignored_risk_outliers": len(raw_risk_values) - len(risk_values),
            "average_rr_target": round(sum(rr_values) / len(rr_values), 2) if rr_values else None,
            "stop_model_coverage": round(stop_defined / max(len(rules), 1), 3),
            "principles": [
                "WAIT/WATCH prepares the idea; EXECUTE requires confirmed trigger.",
                "Quality A can use normal risk; quality B must remain reduced.",
                "Critical blocks always override pattern confidence.",
            ],
        }

    def _risk_defined_ratio(self, rules: list[NormalizedRule]) -> float:
        if not rules:
            return 0.0
        defined = 0
        for rule in rules:
            has_stop = rule.stop_model not in {None, "", "unknown"}
            has_tp = rule.take_profit_model not in {None, "", "unknown"} or rule.rr_target is not None
            if has_stop and has_tp:
                defined += 1
        return round(defined / len(rules), 3)

    def _delta(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
        keys = [
            "messages",
            "files",
            "chunks",
            "extracted_rules",
            "normalized_rules",
            "strategy_candidates",
            "strategy_playbooks",
            "top_strategies",
        ]
        return {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}

    def _knowledge_change_interpretation(self, before: dict[str, Any], after: dict[str, Any]) -> str:
        chunks_delta = int(after.get("chunks", 0)) - int(before.get("chunks", 0))
        rules_delta = int(after.get("extracted_rules", 0)) - int(before.get("extracted_rules", 0))
        if chunks_delta > 0 and rules_delta < 0:
            return "Knowledge base was rebuilt with more chunks while rules were de-duplicated or quality-filtered; this is cleanup, not necessarily lost learning."
        if chunks_delta > 0 or rules_delta > 0:
            return "New material was converted into structured trading knowledge."
        if chunks_delta == 0 and rules_delta == 0:
            return "No net inventory change; cycle refreshed processing, scoring, rankings and reports."
        return "Knowledge inventory changed after rebuild; inspect phase results for details."

    def _mark_learning_integrations_synced(self, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        rows = self.session.scalars(
            select(LearningIntegration).where(
                LearningIntegration.enabled.is_(True),
                LearningIntegration.auto_sync.is_(True),
            )
        )
        note = (
            f"last_cycle={payload['status']} "
            f"rules={payload['knowledge_after']['extracted_rules']} "
            f"normalized={payload['knowledge_after']['normalized_rules']} "
            f"applicability={payload['applicable_knowledge']['applicability']['level']}"
        )
        for integration in rows:
            integration.last_sync_at = now
            integration.notes = self._append_note(integration.notes, note)
            self.session.add(integration)

    def _write_reports(self, payload: dict[str, Any]) -> dict[str, str]:
        output_dir = self.settings.paths.knowledge_dir / "learning_cycle"
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "learning_cycle_report.json"
        md_path = output_dir / "learning_cycle_report.md"
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(self._render_markdown(payload), encoding="utf-8")
        return {"json": str(json_path.resolve()), "md": str(md_path.resolve())}

    def _render_markdown(self, payload: dict[str, Any]) -> str:
        applicable = payload["applicable_knowledge"]
        risk = payload["risk_governance"]
        delta = payload["knowledge_delta"]
        lines = [
            "# Knowledge Learning Cycle",
            "",
            f"- Status: `{payload['status']}`",
            f"- Finished UTC: `{payload['finished_at']}`",
            f"- Applicability: `{applicable['applicability']['level']}` ({applicable['applicability']['score']})",
            "",
            "## Knowledge Delta",
        ]
        for key, value in delta.items():
            lines.append(f"- `{key}`: {value:+d}")
        lines.append(f"- Interpretation: {payload['knowledge_change_interpretation']}")
        lines.extend(["", "## Current Knowledge Inventory"])
        for key in [
            "messages",
            "files",
            "chunks",
            "extracted_rules",
            "normalized_rules",
            "strategy_candidates",
            "strategy_playbooks",
            "top_strategies",
        ]:
            lines.append(f"- `{key}`: {payload['knowledge_after'].get(key, 0)}")
        lines.extend(["", "## Dominant Strategy Families"])
        for item in applicable["dominant_strategy_families"][:8]:
            lines.append(f"- `{item['family']}`: {item['rules']} rules")
        lines.extend(["", "## Recognized Patterns"])
        for item in applicable["recognized_patterns"][:10]:
            lines.append(f"- `{item['pattern']}`: {item['count']}")
        lines.extend(["", "## Strategy Combinations"])
        for item in applicable["strategy_combinations"][:6]:
            lines.append(f"- `{item['primary']}` + `{item['secondary']}`: {item['use_case']}")
        lines.extend(["", "## Risk Governance"])
        lines.append(f"- Status: `{risk['status']}`")
        lines.append(f"- Average risk percent: `{risk.get('average_risk_percent')}`")
        lines.append(f"- Ignored risk outliers: `{risk.get('ignored_risk_outliers')}`")
        lines.append(f"- Average RR target: `{risk.get('average_rr_target')}`")
        lines.append(f"- Stop model coverage: `{risk.get('stop_model_coverage')}`")
        for principle in risk["principles"]:
            lines.append(f"- {principle}")
        lines.extend(["", "## Failed Phases"])
        if payload["failed_phases"]:
            for item in payload["failed_phases"]:
                lines.append(f"- `{item['phase']}`: {item.get('error', '')[:180]}")
        else:
            lines.append("- None")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _append_note(current: str | None, note: str) -> str:
        if not current:
            return note
        lines = [line for line in current.splitlines() if line.strip()]
        lines.append(note)
        return "\n".join(lines[-5:])

    @staticmethod
    def _json_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(data, list):
            return [str(item) for item in data if item not in (None, "", [])]
        if data in (None, "", []):
            return []
        return [str(data)]
