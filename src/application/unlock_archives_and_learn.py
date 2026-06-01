"""Master pipeline to unlock archive inspection and continue learning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.application.archive_doctor import ArchiveDoctorApplicationService
from src.application.build_knowledge_base import KnowledgeBuildApplicationService
from src.application.build_semantic_index import SemanticIndexApplicationService
from src.application.compile_setups import SetupCompilationApplicationService
from src.application.detect_strategies import StrategyDetectionApplicationService
from src.application.extract_trading_rules import TradingRuleExtractionApplicationService
from src.application.inspect_archives import ArchiveInspectionApplicationService
from src.application.normalize_rules import RuleNormalizationApplicationService
from src.application.process_cataloged_assets import ArchiveDownloadOptions, CatalogedAssetProcessingService
from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import ContentChunk, ExtractedRule, TopStrategyDetected
from src.db.models.telegram_message import TelegramMessage

logger = get_logger(__name__)


@dataclass(slots=True)
class UnlockArchivesAndLearnOptions:
    channel: str
    archive_limit: int = 2
    inspect_limit: int = 10
    max_group_size_mb: int = 1024
    skip_large_groups: bool = False
    download_only_complete_groups: bool = False
    retry_attempts: int = 5


class UnlockArchivesAndLearnApplicationService:
    """Run an archive-centric recovery and learning pipeline with fault tolerance."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self, options: UnlockArchivesAndLearnOptions) -> dict[str, Any]:
        archive_service = ArchiveInspectionApplicationService(self.session)
        processing_service = CatalogedAssetProcessingService(self.session, self.settings)
        phases: list[tuple[str, Callable[[], Any]]] = [
            ("doctor-archives", lambda: ArchiveDoctorApplicationService(self.session, self.settings).run()),
            (
                "download-archives",
                lambda: processing_service.download_archives(
                    ArchiveDownloadOptions(
                        limit=options.archive_limit,
                        max_group_size_mb=options.max_group_size_mb,
                        skip_large_groups=options.skip_large_groups,
                        download_only_complete_groups=options.download_only_complete_groups,
                        retry_attempts=options.retry_attempts,
                    )
                ),
            ),
            ("inspect-archives", lambda: archive_service.inspect(limit=options.inspect_limit)),
            ("rank-archives", lambda: archive_service.rank(limit=options.inspect_limit)),
            ("select-archives", lambda: archive_service.select(limit=options.archive_limit)),
            ("process-selected-archives", lambda: processing_service.process_selected_archives(limit=options.archive_limit)),
            ("rebuild-kb", lambda: KnowledgeBuildApplicationService(self.session, self.settings).run(filtered=True)),
            ("build-semantic-index", lambda: SemanticIndexApplicationService(self.session, self.settings).run(rebuild=True)),
            ("extract-rules", lambda: TradingRuleExtractionApplicationService(self.session).run()),
            ("normalize-rules", lambda: RuleNormalizationApplicationService(self.session).run()),
            ("compile-setups", lambda: SetupCompilationApplicationService(self.session).run(score=True)),
            ("detect-strategies", lambda: StrategyDetectionApplicationService(self.session).run()),
            ("rank-strategies", lambda: StrategyDetectionApplicationService(self.session).rank(limit=10)),
            ("status-final", self._summary),
        ]
        phase_results = [self._run_phase(name, runner) for name, runner in phases]
        return {"phases": phase_results, "summary": self._summary()}

    def _run_phase(self, phase_name: str, runner: Callable[[], Any]) -> dict[str, Any]:
        logger.info("unlock-archives-and-learn phase started: %s", phase_name)
        try:
            result = runner()
            self.session.commit()
            logger.info("unlock-archives-and-learn phase completed: %s", phase_name)
            return {"phase": phase_name, "status": "completed", "result": result}
        except Exception as exc:
            self.session.rollback()
            logger.warning("unlock-archives-and-learn phase failed: %s | %s", phase_name, exc, exc_info=True)
            return {"phase": phase_name, "status": "failed", "error": str(exc)}

    def _summary(self) -> dict[str, int]:
        return {
            "messages": self.session.scalar(select(func.count()).select_from(TelegramMessage)) or 0,
            "files": self.session.scalar(select(func.count()).select_from(FileAsset)) or 0,
            "chunks": self.session.scalar(select(func.count()).select_from(ContentChunk)) or 0,
            "rules": self.session.scalar(select(func.count()).select_from(ExtractedRule)) or 0,
            "strategies": self.session.scalar(select(func.count()).select_from(TopStrategyDetected)) or 0,
        }
