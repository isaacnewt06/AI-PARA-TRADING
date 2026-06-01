"""Typer CLI entrypoint."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from time import sleep
from typing import Optional

import typer
import uvicorn
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.platform_service_api import create_platform_api_app
from src.application.build_semantic_index import SemanticIndexApplicationService
from src.application.build_market_situation_map import MarketSituationMapApplicationService
from src.application.build_knowledge_base import KnowledgeBuildApplicationService
from src.application.archive_doctor import ArchiveDoctorApplicationService
from src.application.analyze_backtest_results import BacktestDiagnosticsApplicationService
from src.application.catalog_reports import CatalogReportService
from src.application.compare_knowledge import KnowledgeComparisonApplicationService
from src.application.export_backtest_dataset import BacktestDatasetApplicationService
from src.application.export_blueprint_backtests import BlueprintBacktestExportApplicationService
from src.application.export_mt5_ohlcv import MT5OHLCVExportApplicationService
from src.application.export_mt5_ohlcv_range import MT5OHLCVRangeExportApplicationService
from src.application.detect_strategies import StrategyDetectionApplicationService
from src.application.export_strategies import StrategyExportApplicationService
from src.application.extract_trading_rules import TradingRuleExtractionApplicationService
from src.application.filter_content import ContentFilteringApplicationService
from src.application.generate_playbooks import PlaybookGenerationApplicationService
from src.application.generate_executable_strategies import ExecutableStrategyGenerationApplicationService
from src.application.generate_balanced_ob_backtest import BalancedOBBacktestGenerationApplicationService
from src.application.generate_balanced_v2_ob_backtest import BalancedV2OBBacktestGenerationApplicationService
from src.application.generate_robust_ob_backtests import RobustOBBacktestGenerationApplicationService
from src.application.generate_relaxed_filtered_ob_backtest import RelaxedFilteredOBBacktestGenerationApplicationService
from src.application.generate_relaxed_ob_backtest import RelaxedOBBacktestGenerationApplicationService
from src.application.import_channels import ConfiguredChannelImportService
from src.application.import_external_bot_knowledge import ExternalBotKnowledgeImportService
from src.application.import_local_education_source import LocalEducationImportService
from src.application.import_manual_knowledge import ManualKnowledgeImportService
from src.application.ingest_signal_bot import ConfiguredSignalBotImportService, SignalBotSyncApplicationService
from src.application.ingest_channel import IngestionApplicationService
from src.application.inspect_archives import ArchiveInspectionApplicationService
from src.application.knowledge_learning_cycle import (
    KnowledgeLearningCycleApplicationService,
    KnowledgeLearningCycleOptions,
)
from src.application.learn_from_channel import LearnFromChannelApplicationService, LearnFromChannelOptions
from src.application.unlock_archives_and_learn import (
    UnlockArchivesAndLearnApplicationService,
    UnlockArchivesAndLearnOptions,
)
from src.application.compile_setups import SetupCompilationApplicationService
from src.application.normalize_rules import RuleNormalizationApplicationService
from src.application.optimize_ob_rejection import OBRejectionOptimizationApplicationService
from src.application.optimize_maximo_quant_v4 import MaximoQuantV4OptimizationApplicationService
from src.application.process_assets import ProcessingApplicationService
from src.application.process_cataloged_assets import ArchiveDownloadOptions, CatalogedAssetProcessingService
from src.application.query_knowledge import KnowledgeQueryApplicationService
from src.application.run_blueprint_backtests import BlueprintBacktestRunApplicationService
from src.application.run_maximo_br_backtest import MaximoBRBacktestApplicationService
from src.application.run_maximo_quant_v4_backtest import MaximoQuantV4BacktestApplicationService
from src.application.run_maximo_quant_v4_demo import MaximoQuantV4DemoApplicationService
from src.application.run_maximo_quant_v4_market_intelligence import MaximoQuantV4MarketIntelligenceApplicationService
from src.application.run_maximo_quant_v4_market_overview import MaximoQuantV4MarketOverviewApplicationService
from src.application.run_maximo_quant_v4_new_candle_validation import (
    MaximoQuantV4NewCandleValidationApplicationService,
)
from src.application.run_trading_service_agent import TradingServiceExecutionAgentApplicationService
from src.application.run_maximo_quant_v4_yearly_analysis import MaximoQuantV4YearlyAnalysisApplicationService
from src.application.run_spread_session_audit import SpreadSessionAuditApplicationService
from src.application.run_yearly_backtest import YearlyBacktestApplicationService
from src.application.run_paper_trading import PaperTradingApplicationService
from src.application.resume_pending_media import PendingMediaResumeApplicationService
from src.application.score_rules import QualityScoringApplicationService
from src.application.summarize_courses import CourseSummaryApplicationService
from src.application.transcribe_pending_media import PendingMediaTranscriptionApplicationService
from src.application.trading_service_platform import TradingServicePlatformApplicationService
from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import ContentChunk
from src.db.models.telegram_message import TelegramMessage
from src.db.repositories.channels import ChannelRepository
from src.db.repositories.files import FileRepository
from src.db.repositories.messages import MessageRepository
from src.db.repositories.runs import RunRepository
from src.db.session import init_db, session_scope
from src.telegram.client import TelegramClientManager
from src.telegram.sync_service import TelegramSyncOptions
from src.trading.maximo_quant_v4_market_intelligence import MaximoQuantV4MarketIntelligenceEngine
from src.trading.mt5_bridge import MT5Bridge
from src.trading.reaction_zone_demo_telemetry_validation import ReactionZoneDemoTelemetryValidation

app = typer.Typer(help="TELEGRAM_TRADING_BRAIN command line interface.")


def bootstrap() -> None:
    settings = get_settings()
    setup_logging(settings)
    init_db()


def _parse_extensions(value: str) -> set[str]:
    extensions = set()
    for item in value.split(","):
        item = item.strip().lower()
        if not item:
            continue
        extensions.add(item if item.startswith(".") else f".{item}")
    return extensions


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def build_ingestion_service(session: Session) -> IngestionApplicationService:
    settings = get_settings()
    return IngestionApplicationService(
        client_manager=TelegramClientManager(settings),
        channel_repository=ChannelRepository(session),
        message_repository=MessageRepository(session),
        file_repository=FileRepository(session),
        run_repository=RunRepository(session),
        settings=settings,
    )


@app.command()
def auth() -> None:
    """Authenticate the Telethon session."""
    bootstrap()
    with session_scope() as session:
        service = build_ingestion_service(session)
        asyncio.run(service.authenticate())
    typer.echo("Telegram authentication completed.")


@app.command("add-channel")
def add_channel(channel: str) -> None:
    """Register a Telegram channel or group."""
    bootstrap()
    with session_scope() as session:
        service = build_ingestion_service(session)
        entity = asyncio.run(service.add_channel(channel))
        typer.echo(f"Registered channel: {entity.title} ({entity.input_reference})")


@app.command("import-channels")
def import_channels(
    config_path: str = typer.Option(default="config/channels.yaml", help="YAML file with target channels."),
) -> None:
    """Import target channels from configuration without Telegram auth."""
    bootstrap()
    settings = get_settings()
    path = settings.project_root / config_path
    with session_scope() as session:
        summary = ConfiguredChannelImportService(session, path).run()
        typer.echo(f"Configured channels imported: {summary['channels_imported']}")


@app.command("import-signal-bots")
def import_signal_bots(
    config_path: str = typer.Option(default="config/bots.yaml", help="YAML file with signal bot sources."),
) -> None:
    """Import configured Telegram signal bots as logical sources."""
    bootstrap()
    settings = get_settings()
    path = settings.project_root / config_path
    with session_scope() as session:
        summary = ConfiguredSignalBotImportService(session, path).run()
        typer.echo(f"Configured signal bots imported: {summary['bots_imported']}")


@app.command("import-external-bot-info")
def import_external_bot_info(
    config_path: str = typer.Option(default="config/external_bots.yaml", help="YAML file with external bot projects."),
) -> None:
    """Import key information from existing local trading/signal bots."""
    bootstrap()
    settings = get_settings()
    path = settings.project_root / config_path
    with session_scope() as session:
        summary = ExternalBotKnowledgeImportService(session, path).run()
        typer.echo(
            f"External bot information imported: bots={summary['external_bots_imported']} "
            f"chunks={summary['chunks_created']}"
        )


@app.command("import-manual-knowledge")
def import_manual_knowledge(
    root_dir: str = typer.Option(default="data/knowledge/manual", help="Folder with manual markdown knowledge."),
) -> None:
    """Import curated manual strategy notes into the semantic knowledge base."""
    bootstrap()
    settings = get_settings()
    path = settings.project_root / root_dir
    with session_scope() as session:
        summary = ManualKnowledgeImportService(session, path).run()
        typer.echo(
            f"Manual knowledge imported: notes={summary['manual_notes_imported']} "
            f"chunks={summary['chunks_created']}"
        )


@app.command("import-local-education")
def import_local_education(
    root_dir: str = typer.Option(..., help="Folder with local educational PDFs/XLSX/TXT for trading knowledge."),
) -> None:
    """Import a local educational document folder into the knowledge base."""
    bootstrap()
    settings = get_settings()
    path = Path(root_dir)
    with session_scope() as session:
        summary = LocalEducationImportService(session, settings, path).run()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-bootstrap")
def platform_bootstrap(
    owner_email: str = typer.Option(..., help="Primary owner email for the service."),
    owner_name: str = typer.Option(..., help="Owner display name."),
    timezone_name: str = typer.Option(default="America/Santo_Domingo", help="Owner timezone."),
) -> None:
    """Bootstrap the multi-user AI trading service platform."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).bootstrap_platform(
            owner_email=owner_email,
            owner_name=owner_name,
            timezone_name=timezone_name,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-create-user")
def platform_create_user(
    email: str = typer.Option(..., help="User email."),
    display_name: str = typer.Option(..., help="Display name."),
    role: str = typer.Option(default="client", help="Role: owner/admin/operator/client/viewer."),
    timezone_name: str = typer.Option(default="America/Santo_Domingo", help="User timezone."),
    notes: Optional[str] = typer.Option(default=None, help="Optional notes."),
) -> None:
    """Create or update a platform user."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).create_user(
            email=email,
            display_name=display_name,
            role=role,
            timezone_name=timezone_name,
            notes=notes,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-connect-account")
def platform_connect_account(
    owner_email: str = typer.Option(..., help="Owner user email."),
    account_label: str = typer.Option(..., help="Human friendly account label."),
    broker_name: str = typer.Option(..., help="Broker name, e.g. Exness."),
    platform_type: str = typer.Option(default="MT5", help="Broker platform type."),
    broker_server: Optional[str] = typer.Option(default=None, help="Broker server name."),
    login_reference: Optional[str] = typer.Option(default=None, help="Masked login/account reference."),
    symbol_suffix: Optional[str] = typer.Option(default="m", help="Broker symbol suffix, e.g. m."),
    base_currency: str = typer.Option(default="USD", help="Account base currency."),
    is_demo: bool = typer.Option(default=True, help="Mark the account as demo."),
    connection_mode: str = typer.Option(default="local_agent", help="Connection mode for execution."),
    allowed_symbols: str = typer.Option(default="XAUUSD", help="Comma-separated canonical symbols."),
    source_bots: str = typer.Option(default="", help="Comma-separated external bot modes to attach."),
    notes: Optional[str] = typer.Option(default=None, help="Optional notes."),
) -> None:
    """Connect a broker account and seed the default AI deployment."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).connect_broker_account(
            owner_email=owner_email,
            account_label=account_label,
            broker_name=broker_name,
            platform_type=platform_type,
            broker_server=broker_server,
            login_reference=login_reference,
            symbol_suffix=symbol_suffix,
            base_currency=base_currency,
            is_demo=is_demo,
            connection_mode=connection_mode,
            allowed_symbols=[item.strip() for item in allowed_symbols.split(",") if item.strip()],
            source_bots=[item.strip() for item in source_bots.split(",") if item.strip()],
            notes=notes,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-grant-access")
def platform_grant_access(
    account_id: int = typer.Option(..., help="Broker account id."),
    grantee_email: str = typer.Option(..., help="User email that will receive access."),
    permission_level: str = typer.Option(default="operator", help="viewer/operator/risk_manager/owner"),
    can_trade: bool = typer.Option(default=True, help="Whether the user can trade."),
    can_manage_risk: bool = typer.Option(default=False, help="Whether the user can manage risk."),
    can_manage_learning: bool = typer.Option(default=False, help="Whether the user can manage learning."),
    notes: Optional[str] = typer.Option(default=None, help="Optional notes."),
) -> None:
    """Grant account access to another approved user."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).grant_account_access(
            account_id=account_id,
            grantee_email=grantee_email,
            permission_level=permission_level,
            can_trade=can_trade,
            can_manage_risk=can_manage_risk,
            can_manage_learning=can_manage_learning,
            notes=notes,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-register-agent")
def platform_register_agent(
    account_id: int = typer.Option(..., help="Broker account id."),
    agent_name: str = typer.Option(..., help="Execution agent name."),
    host_name: str = typer.Option(..., help="Host or VPS name."),
    broker_name: Optional[str] = typer.Option(default=None, help="Broker override."),
    notes: Optional[str] = typer.Option(default=None, help="Optional notes."),
) -> None:
    """Register an execution agent for one broker account."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).register_execution_agent(
            account_id=account_id,
            agent_name=agent_name,
            host_name=host_name,
            broker_name=broker_name,
            notes=notes,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-deploy-strategy")
def platform_deploy_strategy(
    account_id: int = typer.Option(..., help="Broker account id."),
    strategy_key: str = typer.Option(..., help="Strategy key."),
    strategy_variant: str = typer.Option(..., help="Strategy variant."),
    operation_mode: str = typer.Option(default="ai_managed", help="ai_managed/signal_mirror/hybrid_guarded"),
    risk_mode: str = typer.Option(default="reduced", help="blocked/reduced/normal"),
    learning_mode: str = typer.Option(default="continuous", help="continuous/frozen"),
    deployment_status: str = typer.Option(default="active", help="draft/active/paused"),
    symbol_allowlist: str = typer.Option(default="XAUUSD", help="Comma-separated canonical symbols."),
    source_bots: str = typer.Option(default="", help="Comma-separated bot names or operation modes."),
    notes: Optional[str] = typer.Option(default=None, help="Optional notes."),
) -> None:
    """Deploy one strategy or bot-mode onto an account."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).deploy_strategy_mode(
            account_id=account_id,
            strategy_key=strategy_key,
            strategy_variant=strategy_variant,
            operation_mode=operation_mode,
            risk_mode=risk_mode,
            learning_mode=learning_mode,
            deployment_status=deployment_status,
            symbol_allowlist=[item.strip() for item in symbol_allowlist.split(",") if item.strip()],
            source_bots=[item.strip() for item in source_bots.split(",") if item.strip()],
            notes=notes,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-map-symbol")
def platform_map_symbol(
    account_id: int = typer.Option(..., help="Broker account id."),
    canonical_symbol: str = typer.Option(..., help="Canonical symbol, e.g. XAUUSD."),
    broker_symbol: str = typer.Option(..., help="Broker specific symbol, e.g. XAUUSDm."),
    notes: Optional[str] = typer.Option(default=None, help="Optional notes."),
) -> None:
    """Map one canonical symbol to a broker-specific symbol."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).map_broker_symbol(
            account_id=account_id,
            canonical_symbol=canonical_symbol,
            broker_symbol=broker_symbol,
            notes=notes,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-status")
def platform_status() -> None:
    """Show the current state of the multi-user AI trading service platform."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).platform_status()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("platform-issue-credential")
def platform_issue_credential(
    user_email: str = typer.Option(..., help="Platform user email."),
    credential_label: str = typer.Option(..., help="Credential label."),
    notes: Optional[str] = typer.Option(default=None, help="Optional notes."),
) -> None:
    """Issue a user API credential for the trading service platform."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).issue_user_api_credential(
            user_email=user_email,
            credential_label=credential_label,
            notes=notes,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("sync-signal-bots")
def sync_signal_bots(
    bot_name: Optional[str] = typer.Option(default=None, help="Optional bot name from config/bots.yaml."),
    config_path: str = typer.Option(default="config/bots.yaml", help="YAML file with signal bot sources."),
) -> None:
    """Synchronize signal updates from Telegram Bot API."""
    bootstrap()
    settings = get_settings()
    path = settings.project_root / config_path
    with session_scope() as session:
        results = SignalBotSyncApplicationService(session, settings, path).sync(bot_name=bot_name)
        if not results:
            typer.echo("No signal bot sources configured.")
            return
        for name, summary in results.items():
            typer.echo(
                f"{name}: updates={summary['updates_scanned']} saved={summary['messages_saved']} "
                f"files={summary['files_downloaded']} errors={summary['errors_count']}"
            )


@app.command()
def sync(
    channel: Optional[str] = typer.Option(default=None, help="Optional channel reference."),
    mode: str = typer.Option(default="incremental", help="Sync mode: incremental or full."),
    limit: Optional[int] = typer.Option(default=None, help="Maximum messages to scan."),
    max_file_size_mb: Optional[float] = typer.Option(default=None, help="Skip downloads above this size."),
    skip_extensions: str = typer.Option(default="", help="Comma-separated extensions to skip, e.g. .rar,.zip,.7z."),
    commit_every: int = typer.Option(default=1, help="Commit every N messages."),
) -> None:
    """Synchronize one or all registered channels."""
    if mode not in {"incremental", "full"}:
        raise typer.BadParameter("mode must be 'incremental' or 'full'")
    bootstrap()
    with session_scope() as session:
        service = build_ingestion_service(session)
        options = TelegramSyncOptions(
            limit=limit,
            max_file_size_mb=max_file_size_mb,
            skip_extensions=_parse_extensions(skip_extensions),
            commit_every=commit_every,
        )
        results = asyncio.run(service.sync(channel_reference=channel, mode=mode, options=options))
        if not results:
            typer.echo("No channels available to sync.")
            return
        for channel_name, summary in results.items():
            typer.echo(
                f"{channel_name}: scanned={summary['messages_scanned']} saved={summary['messages_saved']} "
                f"files={summary['files_downloaded']} skipped={summary.get('files_skipped', 0)} "
                f"duplicates={summary['duplicates_skipped']} "
                f"errors={summary['errors_count']}"
            )


@app.command("sync-catalog")
def sync_catalog(
    channel: str = typer.Option(..., help="Channel reference."),
    mode: str = typer.Option(default="incremental", help="Sync mode: incremental or full."),
    limit: Optional[int] = typer.Option(default=None, help="Maximum messages to catalog."),
    commit_every: int = typer.Option(default=1, help="Commit every N messages."),
) -> None:
    """Catalog messages/media/external links without downloading heavy files."""
    if mode not in {"incremental", "full"}:
        raise typer.BadParameter("mode must be 'incremental' or 'full'")
    bootstrap()
    with session_scope() as session:
        service = build_ingestion_service(session)
        options = TelegramSyncOptions(limit=limit, commit_every=commit_every, catalog_only=True)
        results = asyncio.run(service.sync(channel_reference=channel, mode=mode, options=options))
        for channel_name, summary in results.items():
            typer.echo(
                f"{channel_name}: cataloged={summary['messages_scanned']} saved={summary['messages_saved']} "
                f"queued_media={summary.get('files_skipped', 0)} errors={summary['errors_count']}"
            )


@app.command("catalog-report")
def catalog_report() -> None:
    """Report catalog composition and likely useful resources."""
    bootstrap()
    with session_scope() as session:
        typer.echo(json.dumps(CatalogReportService(session).run(), indent=2, ensure_ascii=False))


@app.command("process-documents")
def process_documents(limit: Optional[int] = typer.Option(default=None, help="Max documents to process.")) -> None:
    bootstrap()
    with session_scope() as session:
        summary = CatalogedAssetProcessingService(session, get_settings()).process_documents(limit=limit)
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("rank-documents")
def rank_documents(limit: int = typer.Option(default=20, help="Max ranked documents to show.")) -> None:
    """Rank files by knowledge density and probability of containing trading rules."""
    bootstrap()
    with session_scope() as session:
        ranked = CatalogedAssetProcessingService(session, get_settings()).rank_documents(limit=limit)
        typer.echo(json.dumps(ranked, indent=2, ensure_ascii=False))


@app.command("process-top-documents")
def process_top_documents(limit: int = typer.Option(default=5, help="Max top-ranked documents to process.")) -> None:
    """Process the highest-value rule-generating documents first."""
    bootstrap()
    with session_scope() as session:
        summary = CatalogedAssetProcessingService(session, get_settings()).process_top_documents(limit=limit)
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("process-images")
def process_images(limit: Optional[int] = typer.Option(default=None, help="Max images to process.")) -> None:
    bootstrap()
    with session_scope() as session:
        summary = CatalogedAssetProcessingService(session, get_settings()).process_images(limit=limit)
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("process-videos")
def process_videos(limit: int = typer.Option(default=20, help="Max videos/audios to process.")) -> None:
    bootstrap()
    with session_scope() as session:
        summary = CatalogedAssetProcessingService(session, get_settings()).process_videos(limit=limit)
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("resume-pending-media")
def resume_pending_media(
    limit: int = typer.Option(default=10, help="Max pending media assets to resume."),
    max_file_size_mb: Optional[float] = typer.Option(default=None, help="Skip resume above this size."),
    categories: str = typer.Option(default="video,audio,document,generic", help="Comma-separated categories."),
    statuses: str = typer.Option(default="queued,downloading,partial", help="Comma-separated statuses."),
) -> None:
    bootstrap()
    with session_scope() as session:
        summary = PendingMediaResumeApplicationService(session, get_settings()).run(
            limit=limit,
            max_file_size_mb=max_file_size_mb,
            categories=[item.strip() for item in categories.split(",") if item.strip()],
            statuses=[item.strip() for item in statuses.split(",") if item.strip()],
        )
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("transcribe-pending-media")
def transcribe_pending_media(
    limit: int = typer.Option(default=10, help="Max already-downloaded media assets to transcribe."),
    categories: str = typer.Option(default="video,audio", help="Comma-separated categories."),
) -> None:
    bootstrap()
    with session_scope() as session:
        summary = PendingMediaTranscriptionApplicationService(session, get_settings()).run(
            limit=limit,
            categories=[item.strip() for item in categories.split(",") if item.strip()],
        )
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("process-archives")
def process_archives(
    limit: int = typer.Option(default=10, help="Max archives to inspect."),
    max_size_mb: int = typer.Option(default=500, help="Skip archives above this size."),
) -> None:
    bootstrap()
    with session_scope() as session:
        summary = CatalogedAssetProcessingService(session, get_settings()).process_archives(
            limit=limit,
            max_size_mb=max_size_mb,
        )
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("process-external-links")
def process_external_links(
    provider: Optional[str] = typer.Option(default=None, help="Provider filter, e.g. mega."),
    limit: Optional[int] = typer.Option(default=None, help="Max links to queue."),
) -> None:
    bootstrap()
    with session_scope() as session:
        summary = CatalogedAssetProcessingService(session, get_settings()).process_external_links(
            provider=provider,
            limit=limit,
        )
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("generate-executable-strategies")
def generate_executable_strategies(
    output_dir: Optional[str] = typer.Option(default=None, help="Target folder for executable strategy blueprints."),
    prioritize_family: str = typer.Option(default="OB Rejection", help="Family to prioritize first."),
) -> None:
    """Generate executable strategy blueprints, checklists and quantifiable conditions."""
    bootstrap()
    with session_scope() as session:
        summary = ExecutableStrategyGenerationApplicationService(session, get_settings()).run(
            output_dir=output_dir,
            prioritize_family=prioritize_family,
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("export-blueprint-backtests")
def export_blueprint_backtests(
    output_dir: Optional[str] = typer.Option(default=None, help="Optional target folder for backtest specs."),
) -> None:
    """Export executable strategy blueprints to formal backtest spec JSON files."""
    bootstrap()
    with session_scope() as session:
        summary = BlueprintBacktestExportApplicationService(session, get_settings()).run(output_dir=output_dir)
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("generate-relaxed-ob-backtest")
def generate_relaxed_ob_backtest() -> None:
    """Create an experimental relaxed OB Rejection blueprint and export its formal backtest spec."""
    bootstrap()
    with session_scope() as session:
        summary = RelaxedOBBacktestGenerationApplicationService(session, get_settings()).run()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("generate-relaxed-filtered-ob-backtest")
def generate_relaxed_filtered_ob_backtest() -> None:
    """Create filtered relaxed OB Rejection variants and export formal backtest specs."""
    bootstrap()
    with session_scope() as session:
        summary = RelaxedFilteredOBBacktestGenerationApplicationService(session, get_settings()).run()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("generate-balanced-ob-backtest")
def generate_balanced_ob_backtest() -> None:
    """Create an experimental balanced OB Rejection blueprint and export its formal backtest spec."""
    bootstrap()
    with session_scope() as session:
        summary = BalancedOBBacktestGenerationApplicationService(session, get_settings()).run()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("generate-balanced-v2-ob-backtest")
def generate_balanced_v2_ob_backtest() -> None:
    """Create balanced v2 OB Rejection RR variants and export formal backtest specs."""
    bootstrap()
    with session_scope() as session:
        summary = BalancedV2OBBacktestGenerationApplicationService(session, get_settings()).run()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("generate-robust-ob-backtests")
def generate_robust_ob_backtests() -> None:
    """Create long/short and dynamic-exit OB Rejection robustness specs."""
    bootstrap()
    with session_scope() as session:
        summary = RobustOBBacktestGenerationApplicationService(session, get_settings()).run()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-blueprint-backtests")
def run_blueprint_backtests() -> None:
    """Run conservative formal backtests from blueprint specs using CSV OHLCV input."""
    bootstrap()
    with session_scope() as session:
        summary = BlueprintBacktestRunApplicationService(session, get_settings()).run()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("export-mt5-ohlcv")
def export_mt5_ohlcv(
    symbol: str = typer.Option(..., help="Broker symbol to export, e.g. XAUUSDm."),
    bars: int = typer.Option(default=50_000, help="Requested bars for M1/M5; H1 exports at least 20,000."),
) -> None:
    """Export historical OHLCV from MT5 into data/backtests/input for formal backtesting."""
    bootstrap()
    summary = MT5OHLCVExportApplicationService(get_settings()).run(symbol=symbol, bars=bars)
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("export-mt5-ohlcv-range")
def export_mt5_ohlcv_range(
    symbol: str = typer.Option(..., help="Broker symbol to export, e.g. XAUUSDm."),
    from_date: str = typer.Option(..., help="UTC start date in YYYY-MM-DD."),
    to_date: str = typer.Option(..., help="UTC end date in YYYY-MM-DD."),
) -> None:
    """Export historical OHLCV from MT5 into range-specific CSV files for annual studies."""
    bootstrap()
    summary = MT5OHLCVRangeExportApplicationService(get_settings()).run(
        symbol=symbol,
        from_date=_parse_iso_date(from_date),
        to_date=_parse_iso_date(to_date),
    )
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-paper-trading")
def run_paper_trading(
    symbol: str = typer.Option(..., help="Broker symbol to monitor in MT5, e.g. XAUUSDm."),
    dry_run: bool = typer.Option(default=False, help="Run one safe snapshot pass without continuous monitoring."),
) -> None:
    """Run the accepted v3 strategy as read-only paper trading against MT5 market data."""
    bootstrap()
    summary = PaperTradingApplicationService(get_settings()).run(symbol=symbol, dry_run=dry_run)
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-maximo-br-backtest")
def run_maximo_br_backtest(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to backtest, e.g. XAUUSDm."),
) -> None:
    """Run a serious research backtest for MAXIMO B&R PRO v2.0 1.3R."""
    bootstrap()
    summary = MaximoBRBacktestApplicationService(get_settings()).run(symbol=symbol)
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-maximo-quant-v4-backtest")
def run_maximo_quant_v4_backtest(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to backtest, e.g. XAUUSDm."),
) -> None:
    """Run a TradingView-derived research backtest for MAXIMO MTF Quant Institutional v4."""
    bootstrap()
    summary = MaximoQuantV4BacktestApplicationService(get_settings()).run(symbol=symbol)
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-maximo-quant-v4-yearly-analysis")
def run_maximo_quant_v4_yearly_analysis(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to analyze."),
    year: int = typer.Option(default=2025, help="Calendar year to analyze."),
    initial_capital: float = typer.Option(default=500.0, help="Initial capital in USD."),
    volume_lots: float = typer.Option(default=0.01, help="Fixed lot volume per trade."),
    strategy_variant: str = typer.Option(default="prime_hours_refined_v46", help="Stored MAXIMO Quant strategy variant code."),
    session_variant: str = typer.Option(default="london_ny_am", help="Session variant code."),
    timeframe: str = typer.Option(default="M5", help="Entry timeframe to analyze."),
) -> None:
    """Run weekly/monthly/yearly fixed-lot analysis for the best MAXIMO Quant v4 candidate."""
    bootstrap()
    summary = MaximoQuantV4YearlyAnalysisApplicationService(get_settings()).run(
        symbol=symbol,
        year=year,
        initial_capital=initial_capital,
        volume_lots=volume_lots,
        strategy_variant=strategy_variant,
        session_variant=session_variant,
        timeframe=timeframe,
    )
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-maximo-quant-v4-demo")
def run_maximo_quant_v4_demo(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to trade on the MT5 demo account."),
    volume_lots: float = typer.Option(default=0.01, help="Fixed lot size per MT5 demo order."),
    deviation_points: int = typer.Option(default=50, help="Maximum MT5 slippage/deviation in points."),
    live: bool = typer.Option(default=False, help="Actually send a market order to the MT5 demo account."),
    confirm_demo: bool = typer.Option(default=False, help="Required with --live to confirm demo-only execution."),
) -> None:
    """Run the current best MAXIMO Quant v4 candidate against MT5 and optionally place a demo order."""
    bootstrap()
    summary = MaximoQuantV4DemoApplicationService(get_settings()).run(
        symbol=symbol,
        volume_lots=volume_lots,
        deviation_points=deviation_points,
        dry_run=not live,
        confirm_demo=confirm_demo,
    )
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-maximo-quant-v4-market-overview")
def run_maximo_quant_v4_market_overview(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to analyze from MT5 market data."),
) -> None:
    """Build a current market view and action recommendation from live MT5 context plus learned knowledge."""
    bootstrap()
    summary = MaximoQuantV4MarketOverviewApplicationService(get_settings()).run(symbol=symbol)
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-maximo-quant-v4-market-intelligence")
def run_maximo_quant_v4_market_intelligence(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to analyze with full market intelligence."),
) -> None:
    """Build a full market intelligence report including context, volatility and event/news risk."""
    bootstrap()
    summary = MaximoQuantV4MarketIntelligenceApplicationService(get_settings()).run(symbol=symbol)
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("prepare-reaction-zone-demo-telemetry-validation")
def prepare_reaction_zone_demo_telemetry_validation(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to validate, e.g. XAUUSDm."),
    session: str = typer.Option(default="auto", help="Use auto, ny_am or ny_pm."),
    risk_mode: str = typer.Option(default="reduced", help="Telemetry validation only allows reduced risk."),
) -> None:
    """Prepare demo-only management telemetry gate without creating entries or orders."""
    bootstrap()
    settings = get_settings()
    bridge = MT5Bridge(settings)
    validator = ReactionZoneDemoTelemetryValidation(settings)
    intelligence_engine = MaximoQuantV4MarketIntelligenceEngine(settings, bridge=bridge)
    intelligence = intelligence_engine.run_detailed(symbol=symbol)
    market_state = intelligence["overview"]["market_state"]
    hour_ny = market_state.get("hour_ny")
    try:
        hour_ny_int = int(hour_ny) if hour_ny not in (None, "") else None
    except (TypeError, ValueError):
        hour_ny_int = None
    resolved_session = validator.session_from_hour_ny(hour_ny_int) if session == "auto" else session
    account_status = bridge.account_status()
    execution_environment = bridge.read_execution_environment(symbol=symbol)
    macro_action = str(intelligence["event_risk"].get("action") or "unknown")
    gate = validator.evaluate_gate(
        account_status=account_status,
        execution_environment=execution_environment,
        macro_action=macro_action,
        session=resolved_session,
        risk_mode=risk_mode,
    )
    latest_gate = validator.write_latest_gate(
        gate=gate,
        account_status=account_status,
        execution_environment=execution_environment,
        macro_action=macro_action,
        session=resolved_session,
        risk_mode=risk_mode,
    )
    report_summary = validator.write_report()
    typer.echo(
        json.dumps(
            {
                "strategy": validator.STRATEGY,
                "profile": validator.PROFILE,
                "symbol": symbol,
                "gate": gate.to_dict(),
                "session": resolved_session,
                "risk_mode": risk_mode,
                "macro_action": macro_action,
                "execution_environment": execution_environment,
                "account_is_demo": bool(account_status.get("is_demo", False)),
                "summary": report_summary,
                "paths": {
                    "latest_gate": str(validator.latest_gate_path.resolve()),
                    "telemetry_jsonl": str(validator.telemetry_path.resolve()),
                    "report_md": str(validator.report_path.resolve()),
                    "latest_market_intelligence": str(intelligence_engine.latest_json_path.resolve()),
                },
                "latest_gate": latest_gate,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@app.command("run-spread-session-audit")
def run_spread_session_audit(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to audit, e.g. XAUUSDm."),
    duration_minutes: float = typer.Option(default=240.0, help="How long to measure execution conditions."),
    poll_seconds: float = typer.Option(default=60.0, help="Seconds between samples."),
    max_samples: Optional[int] = typer.Option(default=None, help="Optional hard limit for samples."),
    run_label: str = typer.Option(default="manual", help="Label for the audit output files."),
) -> None:
    """Measure spread/session execution conditions without sending orders."""
    bootstrap()
    summary = SpreadSessionAuditApplicationService(get_settings()).run(
        symbol=symbol,
        duration_minutes=duration_minutes,
        poll_seconds=poll_seconds,
        max_samples=max_samples,
        run_label=run_label,
    )
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-maximo-quant-v4-new-candle-validation")
def run_maximo_quant_v4_new_candle_validation(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to validate, e.g. XAUUSDm."),
    target_unique_candles: int = typer.Option(default=50, help="Minimum unique closed M5 candles to validate."),
    max_attempts: int = typer.Option(default=5_000, help="Maximum polling attempts before stopping."),
    poll_seconds: float = typer.Option(default=10.0, help="Seconds between polling attempts."),
    session_label: str = typer.Option(default="manual", help="Human label for the validation window."),
) -> None:
    """Run dry validation only when a new closed M5 candle appears."""
    bootstrap()
    summary = MaximoQuantV4NewCandleValidationApplicationService(get_settings()).run(
        symbol=symbol,
        target_unique_candles=target_unique_candles,
        max_attempts=max_attempts,
        poll_seconds=poll_seconds,
        session_label=session_label,
    )
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-yearly-backtest")
def run_yearly_backtest(
    symbol: str = typer.Option(..., help="Broker symbol to backtest, e.g. XAUUSDm."),
    year: int = typer.Option(..., help="Calendar year to backtest."),
    initial_capital: float = typer.Option(..., help="Initial capital in USD."),
) -> None:
    """Run the approved v3 strategy over a full year using year-specific MT5 OHLCV files."""
    bootstrap()
    summary = YearlyBacktestApplicationService(get_settings()).run(
        symbol=symbol,
        year=year,
        initial_capital=initial_capital,
    )
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("analyze-backtest-results")
def analyze_backtest_results() -> None:
    """Analyze generated backtest trades/results and write diagnostics artifacts."""
    bootstrap()
    summary = BacktestDiagnosticsApplicationService(get_settings()).run()
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("optimize-ob-rejection")
def optimize_ob_rejection() -> None:
    """Run focused optimization over OB Rejection Short Only Trailing ATR."""
    bootstrap()
    summary = OBRejectionOptimizationApplicationService(get_settings()).run()
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("optimize-maximo-quant-v4")
def optimize_maximo_quant_v4(
    symbol: str = typer.Option(default="XAUUSDm", help="Broker symbol to optimize, e.g. XAUUSDm."),
) -> None:
    """Run controlled annual optimization for MAXIMO MTF Quant Institutional v4."""
    bootstrap()
    summary = MaximoQuantV4OptimizationApplicationService(get_settings()).run(symbol=symbol)
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("inspect-archives")
def inspect_archives(limit: Optional[int] = typer.Option(default=None, help="Max archives to inspect.")) -> None:
    """Inspect archive contents without extracting files."""
    bootstrap()
    with session_scope() as session:
        summary = ArchiveInspectionApplicationService(session).inspect(limit=limit)
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("rank-archives")
def rank_archives(limit: int = typer.Option(default=50, help="Max ranked archives to show.")) -> None:
    """Rank archives by advanced educational usefulness and selection score."""
    bootstrap()
    with session_scope() as session:
        ranked = ArchiveInspectionApplicationService(session).rank(limit=limit)
        typer.echo(json.dumps(ranked, indent=2, ensure_ascii=False))


@app.command("select-archives")
def select_archives(limit: int = typer.Option(default=10, help="Max selected archives to show.")) -> None:
    """Select the best archives to process first."""
    bootstrap()
    with session_scope() as session:
        selected = ArchiveInspectionApplicationService(session).select(limit=limit)
        typer.echo(json.dumps(selected, indent=2, ensure_ascii=False))


@app.command("process-selected-archives")
def process_selected_archives(
    limit: int = typer.Option(default=3, help="Max selected archives to process."),
    max_size_mb: int = typer.Option(default=500, help="Skip archives above this size."),
) -> None:
    """Process archives chosen by the advanced selector."""
    bootstrap()
    with session_scope() as session:
        summary = CatalogedAssetProcessingService(session, get_settings()).process_selected_archives(
            limit=limit,
            max_size_mb=max_size_mb,
        )
        typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command("download-archives")
def download_archives(
    limit: int = typer.Option(default=2, help="Max selected archive groups to download."),
    max_group_size_mb: int = typer.Option(default=1024, help="Max total size per archive group."),
    skip_large_groups: bool = typer.Option(default=False, help="Skip archive groups above the size limit."),
    download_only_complete_groups: bool = typer.Option(
        default=False,
        help="Only download multipart groups that appear complete in the catalog.",
    ),
    retry: int = typer.Option(default=5, help="Retry attempts for large archive downloads."),
) -> None:
    """Download the best archive groups, including all multipart parts required for inspection."""
    bootstrap()
    with session_scope() as session:
        summary = CatalogedAssetProcessingService(session, get_settings()).download_archives(
            ArchiveDownloadOptions(
                limit=limit,
                max_group_size_mb=max_group_size_mb,
                skip_large_groups=skip_large_groups,
                download_only_complete_groups=download_only_complete_groups,
                retry_attempts=retry,
            )
        )
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("explain-archive")
def explain_archive(value: str) -> None:
    """Explain why an archive was prioritized or penalized."""
    bootstrap()
    with session_scope() as session:
        result = ArchiveInspectionApplicationService(session).explain(value)
        if result is None:
            typer.echo("Archive not found.")
            return
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command("doctor-archives")
def doctor_archives() -> None:
    """Show archive backend diagnostics and multipart readiness."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        result = ArchiveDoctorApplicationService(session, settings).run()
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command()
def process() -> None:
    """Process raw messages and downloaded assets."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        service = ProcessingApplicationService(session, settings, RunRepository(session))
        summary = service.run()
        typer.echo(
            f"Processed messages={summary['messages_processed']} documents={summary['documents_processed']} "
            f"media={summary['media_processed']}"
        )


@app.command("build-kb")
def build_kb() -> None:
    """Build the initial knowledge base."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = KnowledgeBuildApplicationService(session, settings).run()
        typer.echo(
            f"Knowledge base updated: chunks={summary['chunks_created']} "
            f"rules={summary['rules_created']} playbooks={summary['playbooks_created']}"
        )


@app.command("filter-content")
def filter_content() -> None:
    """Score and filter low-value chunks before semantic/rule pipelines."""
    bootstrap()
    with session_scope() as session:
        summary = ContentFilteringApplicationService(session).run()
        typer.echo(
            f"Content filtered: scored={summary['chunks_scored']} kept={summary['chunks_kept']} "
            f"filtered={summary['chunks_filtered']} duplicates={summary['duplicates']}"
        )


@app.command("rebuild-kb")
def rebuild_kb(
    filtered: bool = typer.Option(default=False, help="Apply content quality filtering before rule extraction."),
) -> None:
    """Rebuild chunks and knowledge artifacts, optionally with quality filtering."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = KnowledgeBuildApplicationService(session, settings).run(filtered=filtered)
        typer.echo(
            f"Knowledge base rebuilt: chunks={summary['chunks_created']} scored={summary['chunks_scored']} "
            f"kept={summary['chunks_kept']} filtered={summary['chunks_filtered']} "
            f"rules={summary['rules_created']} playbooks={summary['playbooks_created']}"
        )


@app.command()
def summarize() -> None:
    """Alias for processing + KB build in phase 1."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        processing_summary = ProcessingApplicationService(session, settings, RunRepository(session)).run()
        kb_summary = KnowledgeBuildApplicationService(session, settings).run()
        typer.echo(
            f"Summarize pipeline completed. messages={processing_summary['messages_processed']} "
            f"documents={processing_summary['documents_processed']} chunks={kb_summary['chunks_created']}"
        )


@app.command()
def status() -> None:
    """Show database and ingestion status."""
    bootstrap()
    with session_scope() as session:
        channels = session.scalar(select(func.count()).select_from(Channel)) or 0
        messages = session.scalar(select(func.count()).select_from(TelegramMessage)) or 0
        files = session.scalar(select(func.count()).select_from(FileAsset)) or 0
        chunks = session.scalar(select(func.count()).select_from(ContentChunk)) or 0
        filtered_chunks = (
            session.scalar(select(func.count()).select_from(ContentChunk).where(ContentChunk.filtered_out.is_(True)))
            or 0
        )
        typer.echo(
            f"channels={channels} messages={messages} files={files} chunks={chunks} filtered_chunks={filtered_chunks}"
        )
        typer.echo("Registered channels:")
        for row in session.scalars(select(Channel).order_by(Channel.title.asc())):
            typer.echo(
                f"- {row.title} | ref={row.input_reference} | last_msg={row.last_synced_message_id or 'none'}"
            )


@app.command()
def query(question: str, limit: int = typer.Option(default=5, help="Maximum number of matches.")) -> None:
    """Query the local knowledge base."""
    bootstrap()
    with session_scope() as session:
        results = KnowledgeQueryApplicationService(session, get_settings()).run(question, limit=limit)
        if not results:
            typer.echo("No matches found.")
            return
        for result in results:
            typer.echo(f"[{result.source_type}#{result.chunk_id}] {result.text[:300]}")


@app.command("build-semantic-index")
def build_semantic_index(
    rebuild: bool = typer.Option(default=False, help="Rebuild the whole local vector index."),
) -> None:
    """Generate local embeddings and a vector index for content chunks."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = SemanticIndexApplicationService(session, settings).run(rebuild=rebuild)
        typer.echo(
            f"Semantic index ready: indexed_chunks={summary['indexed_chunks']} "
            f"provider={summary['provider']} manifest={summary['manifest']}"
        )


@app.command("semantic-query")
def semantic_query(
    question: str,
    topic: Optional[str] = typer.Option(default=None, help="Filter by topic."),
    author: Optional[str] = typer.Option(default=None, help="Filter by author."),
    channel: Optional[str] = typer.Option(default=None, help="Filter by channel."),
    strategy: Optional[str] = typer.Option(default=None, help="Filter by strategy key."),
    concept: Optional[str] = typer.Option(default=None, help="Filter by concept."),
    limit: int = typer.Option(default=5, help="Maximum number of matches."),
) -> None:
    """Run hybrid keyword + semantic retrieval."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        results = KnowledgeQueryApplicationService(session, settings).semantic(
            question,
            topic=topic,
            author=author,
            channel=channel,
            strategy=strategy,
            concept=concept,
            limit=limit,
        )
        if not results:
            typer.echo("No semantic matches found.")
            return
        for result in results:
            typer.echo(
                f"[chunk#{result.chunk_id}] score={result.combined_score:.3f} "
                f"keyword={result.keyword_score:.3f} semantic={result.semantic_score:.3f} "
                f"channel={result.channel_name or '-'} author={result.author_name or '-'} "
                f"strategy={result.strategy_key or '-'} excerpt={result.excerpt}"
            )


@app.command("extract-rules")
def extract_rules() -> None:
    """Extract structured trading rules and cluster similar ones."""
    bootstrap()
    with session_scope() as session:
        summary = TradingRuleExtractionApplicationService(session).run()
        typer.echo(
            f"Structured rules extracted: rules={summary['rules_created']} clusters={summary['clusters_created']}"
        )


@app.command("build-playbooks")
def build_playbooks() -> None:
    """Generate playbooks from extracted trading rules."""
    bootstrap()
    with session_scope() as session:
        summary = PlaybookGenerationApplicationService(session).run()
        typer.echo(f"Playbooks built: {summary['playbooks_created']}")


@app.command("summarize-course")
def summarize_course(
    course_name: Optional[str] = typer.Argument(default=None),
    rebuild: bool = typer.Option(default=False, help="Rebuild module summaries before reading."),
) -> None:
    """Build or inspect course/module summaries."""
    bootstrap()
    with session_scope() as session:
        service = CourseSummaryApplicationService(session)
        if rebuild:
            build_summary = service.build()
            typer.echo(f"Module summaries rebuilt: {build_summary['modules_created']}")
        if course_name:
            summaries = service.summarize_course(course_name)
            if not summaries:
                typer.echo("No module summaries found for that course.")
                return
            for item in summaries:
                typer.echo(
                    f"[module {item['module_order']}] {item['module_title']} | concepts={', '.join(item['concepts'])}"
                )
                typer.echo(item["summary"])


@app.command("compare-authors")
def compare_authors(author_a: str, author_b: str) -> None:
    """Compare two authors using extracted rules."""
    bootstrap()
    with session_scope() as session:
        result = KnowledgeComparisonApplicationService(session).compare_authors(author_a, author_b)
        typer.echo(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))


@app.command("compare-courses")
def compare_courses(course_a: str, course_b: str) -> None:
    """Compare two courses using module summaries."""
    bootstrap()
    with session_scope() as session:
        result = KnowledgeComparisonApplicationService(session).compare_courses(course_a, course_b)
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command("export-backtest-dataset")
def export_backtest_dataset(
    strategy_key: Optional[str] = typer.Option(default=None, help="Optional strategy key filter."),
    output: Optional[str] = typer.Option(default=None, help="Optional CSV output path."),
) -> None:
    """Export structured rules into a backtesting dataset."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = BacktestDatasetApplicationService(session, settings).run(
            strategy_key=strategy_key,
            output_path=output,
        )
        typer.echo(
            f"Backtest dataset prepared: rows={summary['rows']} output={summary['output_path'] or 'not_written'}"
        )


@app.command("normalize-rules")
def normalize_rules() -> None:
    """Normalize extracted rules and generate quantifiable conditions."""
    bootstrap()
    with session_scope() as session:
        summary = RuleNormalizationApplicationService(session).run()
        typer.echo(
            f"Rules normalized: normalized_rules={summary['normalized_rules']} "
            f"quantifiable_conditions={summary['quantifiable_conditions']}"
        )


@app.command("compile-setups")
def compile_setups() -> None:
    """Compile normalized rules into strategy candidates."""
    bootstrap()
    with session_scope() as session:
        summary = SetupCompilationApplicationService(session).run(score=True)
        typer.echo(
            f"Setups compiled: strategy_candidates={summary['strategy_candidates']} "
            f"setup_quality_scores={summary['setup_quality_scores']}"
        )


@app.command("score-rules")
def score_rules() -> None:
    """Score normalized rules and compiled setups."""
    bootstrap()
    with session_scope() as session:
        summary = QualityScoringApplicationService(session).run()
        typer.echo(
            f"Quality scores updated: rules={summary['rule_quality_scores']} setups={summary['setup_quality_scores']}"
        )


@app.command("export-strategies")
def export_strategies(
    output: str = typer.Option(..., help="Output JSON or CSV path."),
    format_name: Optional[str] = typer.Option(default=None, help="Optional format override: json or csv."),
) -> None:
    """Export compiled strategy candidates for backtesting."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = StrategyExportApplicationService(session, settings).export(output, format_name=format_name)
        typer.echo(f"Strategies exported: {summary['strategies_exported']} -> {summary['output_path']}")


@app.command("inspect-setup")
def inspect_setup(setup_name: str) -> None:
    """Inspect a compiled setup with traceability and components."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        result = StrategyExportApplicationService(session, settings).inspect(setup_name)
        if result is None:
            typer.echo("Setup not found.")
            return
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command("compare-strategies")
def compare_strategies(strategy_a: str, strategy_b: str) -> None:
    """Compare two compiled strategy candidates."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        result = StrategyExportApplicationService(session, settings).compare(strategy_a, strategy_b)
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command("detect-strategies")
def detect_strategies() -> None:
    """Detect the strongest repeated strategy patterns in the extracted knowledge base."""
    bootstrap()
    with session_scope() as session:
        summary = StrategyDetectionApplicationService(session).run()
        typer.echo(f"Top strategies detected: {summary['top_strategies_detected']}")


@app.command("rank-strategies")
def rank_strategies(limit: int = typer.Option(default=20, help="Max detected strategies to show.")) -> None:
    """Rank detected strategies by relevance score."""
    bootstrap()
    with session_scope() as session:
        ranked = StrategyDetectionApplicationService(session).rank(limit=limit)
        typer.echo(json.dumps(ranked, indent=2, ensure_ascii=False))


@app.command("inspect-strategy")
def inspect_strategy(name: str) -> None:
    """Inspect one detected strategy with evidence and traceability."""
    bootstrap()
    with session_scope() as session:
        result = StrategyDetectionApplicationService(session).inspect(name)
        if result is None:
            typer.echo("Detected strategy not found.")
            return
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command("build-market-situation-map")
def build_market_situation_map() -> None:
    """Build a market situation map for operable/non-operable contexts."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        summary = MarketSituationMapApplicationService(session, settings).run()
        typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


@app.command("run-knowledge-learning-cycle")
def run_knowledge_learning_cycle(
    channel: Optional[list[str]] = typer.Option(default=None, help="Optional channel reference. Repeat to process several."),
    cycles: int = typer.Option(default=1, help="Number of cycles to run."),
    sleep_seconds: int = typer.Option(default=0, help="Seconds to wait between cycles."),
    doc_limit: int = typer.Option(default=8, help="Max documents per cycle."),
    media_limit: int = typer.Option(default=8, help="Max images/videos/audios per cycle."),
    archive_limit: int = typer.Option(default=2, help="Max selected archives per cycle."),
    inspect_limit: int = typer.Option(default=12, help="Max archives to inspect per cycle."),
    skip_sync: bool = typer.Option(default=False, help="Do not sync Telegram; only process existing local queues."),
    skip_market_map: bool = typer.Option(default=False, help="Do not rebuild market_situation_map."),
    rebuild_semantic_index: bool = typer.Option(default=False, help="Rebuild local semantic index in the cycle."),
) -> None:
    """Run the continuous knowledge extraction -> applicable trading brain cycle."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        service = KnowledgeLearningCycleApplicationService(session, settings, build_ingestion_service(session))
        result = service.run(
            KnowledgeLearningCycleOptions(
                channels=list(channel or []),
                cycles=cycles,
                sleep_seconds=sleep_seconds,
                doc_limit=doc_limit,
                media_limit=media_limit,
                archive_limit=archive_limit,
                inspect_limit=inspect_limit,
                skip_sync=skip_sync,
                skip_market_map=skip_market_map,
                rebuild_semantic_index=rebuild_semantic_index,
            )
        )
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command("learn-from-channel")
def learn_from_channel(
    channel: str = typer.Option(..., help="Channel reference to learn from."),
    doc_limit: int = typer.Option(default=5, help="Max documents to rank/process in document phases."),
    archive_limit: int = typer.Option(default=2, help="Max archives to rank/process."),
    inspect_limit: int = typer.Option(default=10, help="Max archives to inspect before ranking."),
) -> None:
    """Run the full channel learning pipeline end-to-end with fault tolerance."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        service = LearnFromChannelApplicationService(session, settings, build_ingestion_service(session))
        result = service.run(
            LearnFromChannelOptions(
                channel=channel,
                doc_limit=doc_limit,
                archive_limit=archive_limit,
                inspect_limit=inspect_limit,
            )
        )
        typer.echo(json.dumps(result["summary"], indent=2, ensure_ascii=False))


@app.command("unlock-archives-and-learn")
def unlock_archives_and_learn(
    channel: str = typer.Option(..., help="Channel reference to continue learning from."),
    archive_limit: int = typer.Option(default=2, help="Max selected archives to process."),
    inspect_limit: int = typer.Option(default=10, help="Max archives to inspect before ranking."),
    max_group_size_mb: int = typer.Option(default=1024, help="Max total size per archive group to download."),
    skip_large_groups: bool = typer.Option(default=False, help="Skip groups above max_group_size_mb."),
    download_only_complete_groups: bool = typer.Option(
        default=False,
        help="Only download multipart groups that appear complete in the catalog.",
    ),
    retry: int = typer.Option(default=5, help="Retry attempts for large archive downloads."),
) -> None:
    """Unlock archive support, process the best archives, then continue the learning pipeline."""
    bootstrap()
    settings = get_settings()
    with session_scope() as session:
        result = UnlockArchivesAndLearnApplicationService(session, settings).run(
            UnlockArchivesAndLearnOptions(
                channel=channel,
                archive_limit=archive_limit,
                inspect_limit=inspect_limit,
                max_group_size_mb=max_group_size_mb,
                skip_large_groups=skip_large_groups,
                download_only_complete_groups=download_only_complete_groups,
                retry_attempts=retry,
            )
        )
        typer.echo(json.dumps(result["summary"], indent=2, ensure_ascii=False))


@app.command("run-trading-service-api")
def run_trading_service_api(
    host: str = typer.Option(default="127.0.0.1", help="Host interface for the API server."),
    port: int = typer.Option(default=8000, help="Port for the API server."),
) -> None:
    """Run the HTTP API for the multi-user AI trading service platform."""
    bootstrap()
    uvicorn.run(create_platform_api_app(), host=host, port=port)


@app.command("run-trading-service-agent")
def run_trading_service_agent(
    api_base_url: str = typer.Option(..., help="Base URL of the trading service API, e.g. http://127.0.0.1:8000"),
    account_id: int = typer.Option(..., help="Broker account id assigned by the platform."),
    agent_key: str = typer.Option(..., help="Execution agent key."),
    canonical_symbol: str = typer.Option(default="XAUUSD", help="Canonical symbol to prepare locally."),
    heartbeat_status: str = typer.Option(default="online", help="Heartbeat status to report."),
    dry_run: bool = typer.Option(default=True, help="Keep supported deployment execution in dry-run mode."),
    confirm_demo: bool = typer.Option(default=False, help="Required before any real demo order sending."),
    volume_lots: float = typer.Option(default=0.01, help="Base lot size for supported deployments."),
    deviation_points: int = typer.Option(default=50, help="MT5 deviation points for supported deployments."),
    cycles: int = typer.Option(default=1, help="Number of agent cycles to run."),
    sleep_seconds: int = typer.Option(default=0, help="Seconds to wait between cycles."),
) -> None:
    """Run one or more broker-side execution agent cycles against the trading service API."""
    bootstrap()
    settings = get_settings()
    service = TradingServiceExecutionAgentApplicationService(settings)
    results = []
    total_cycles = max(1, cycles)
    for index in range(total_cycles):
        try:
            summary = service.run(
                api_base_url=api_base_url,
                account_id=account_id,
                agent_key=agent_key,
                canonical_symbol=canonical_symbol,
                heartbeat_status=heartbeat_status,
                dry_run=dry_run,
                confirm_demo=confirm_demo,
                volume_lots=volume_lots,
                deviation_points=deviation_points,
            )
            results.append({"cycle": index + 1, "status": "completed", "summary": summary})
        except Exception as exc:
            results.append({"cycle": index + 1, "status": "failed", "error": str(exc)})
        if index < total_cycles - 1 and sleep_seconds > 0:
            sleep(sleep_seconds)
    payload = {
        "cycles_requested": total_cycles,
        "cycles_completed": sum(1 for item in results if item["status"] == "completed"),
        "cycles_failed": sum(1 for item in results if item["status"] == "failed"),
        "latest": results[-1] if results else None,
        "results": results if total_cycles <= 5 else results[-5:],
    }
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
