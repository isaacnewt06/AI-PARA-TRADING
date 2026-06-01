"""Master learning pipeline for a Telegram channel."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.application.build_knowledge_base import KnowledgeBuildApplicationService
from src.application.build_semantic_index import SemanticIndexApplicationService
from src.application.catalog_reports import CatalogReportService
from src.application.compile_setups import SetupCompilationApplicationService
from src.application.detect_strategies import StrategyDetectionApplicationService
from src.application.extract_trading_rules import TradingRuleExtractionApplicationService
from src.application.inspect_archives import ArchiveInspectionApplicationService
from src.application.normalize_rules import RuleNormalizationApplicationService
from src.application.process_cataloged_assets import CatalogedAssetProcessingService
from src.application.score_rules import QualityScoringApplicationService
from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import ContentChunk, ExtractedRule, TopStrategyDetected
from src.db.models.telegram_message import TelegramMessage
from src.application.ingest_channel import IngestionApplicationService
from src.telegram.sync_service import TelegramSyncOptions

logger = get_logger(__name__)


@dataclass(slots=True)
class LearnFromChannelOptions:
    """Runtime options for the master learning pipeline."""

    channel: str
    doc_limit: int = 5
    archive_limit: int = 2
    inspect_limit: int = 10


class LearnFromChannelApplicationService:
    """Run the full catalog-to-strategy learning pipeline with fault tolerance."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        ingestion_service: IngestionApplicationService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.ingestion_service = ingestion_service

    def run(self, options: LearnFromChannelOptions) -> dict[str, Any]:
        phases = self._build_phases(options)
        phase_results: list[dict[str, Any]] = []
        for phase_name, runner in phases:
            phase_results.append(self._run_phase(phase_name, runner))
        summary = self._summary()
        return {"phases": phase_results, "summary": summary}

    def _build_phases(self, options: LearnFromChannelOptions) -> list[tuple[str, Callable[[], Any]]]:
        processing_service = CatalogedAssetProcessingService(self.session, self.settings)
        archive_service = ArchiveInspectionApplicationService(self.session)
        return [
            (
                "sync-catalog",
                lambda: asyncio.run(
                    self.ingestion_service.sync(
                        channel_reference=options.channel,
                        mode="incremental",
                        options=TelegramSyncOptions(catalog_only=True, commit_every=1),
                    )
                ),
            ),
            ("catalog-report", lambda: CatalogReportService(self.session).run()),
            ("inspect-archives", lambda: archive_service.inspect(limit=options.inspect_limit)),
            ("rank-archives", lambda: archive_service.rank(limit=options.archive_limit)),
            ("select-archives", lambda: archive_service.select(limit=options.archive_limit)),
            ("rank-documents", lambda: processing_service.rank_documents(limit=options.doc_limit)),
            ("process-documents", lambda: processing_service.process_documents(limit=options.doc_limit)),
            ("process-images", lambda: processing_service.process_images(limit=options.doc_limit)),
            ("process-top-documents", lambda: processing_service.process_top_documents(limit=options.doc_limit)),
            (
                "process-selected-archives",
                lambda: processing_service.process_selected_archives(limit=options.archive_limit),
            ),
            ("rebuild-kb", lambda: KnowledgeBuildApplicationService(self.session, self.settings).run(filtered=True)),
            ("build-semantic-index", lambda: SemanticIndexApplicationService(self.session, self.settings).run(rebuild=True)),
            ("extract-rules", lambda: TradingRuleExtractionApplicationService(self.session).run()),
            ("normalize-rules", lambda: RuleNormalizationApplicationService(self.session).run()),
            ("compile-setups", lambda: SetupCompilationApplicationService(self.session).run(score=True)),
            ("score-rules", lambda: QualityScoringApplicationService(self.session).run()),
            ("detect-strategies", lambda: StrategyDetectionApplicationService(self.session).run()),
            ("rank-strategies", lambda: StrategyDetectionApplicationService(self.session).rank(limit=10)),
            ("status-final", self._summary),
        ]

    def _run_phase(self, phase_name: str, runner: Callable[[], Any]) -> dict[str, Any]:
        logger.info("learn-from-channel phase started: %s", phase_name)
        try:
            result = runner()
            self.session.commit()
            logger.info("learn-from-channel phase completed: %s", phase_name)
            return {"phase": phase_name, "status": "completed", "result": result}
        except Exception as exc:
            self.session.rollback()
            logger.warning("learn-from-channel phase failed: %s | %s", phase_name, exc, exc_info=True)
            return {"phase": phase_name, "status": "failed", "error": str(exc)}

    def _summary(self) -> dict[str, int]:
        return {
            "messages": self.session.scalar(select(func.count()).select_from(TelegramMessage)) or 0,
            "files": self.session.scalar(select(func.count()).select_from(FileAsset)) or 0,
            "chunks": self.session.scalar(select(func.count()).select_from(ContentChunk)) or 0,
            "rules": self.session.scalar(select(func.count()).select_from(ExtractedRule)) or 0,
            "strategies": self.session.scalar(select(func.count()).select_from(TopStrategyDetected)) or 0,
        }
