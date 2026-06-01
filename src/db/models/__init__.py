"""ORM models registry."""

from src.db.models.channel import Channel
from src.db.models.archive_content import ArchiveContent
from src.db.models.document import Document
from src.db.models.file_asset import FileAsset
from src.db.models.external_resource import ExternalResource
from src.db.models.knowledge import (
    BacktestDatasetRow,
    CandidateComponent,
    ChunkEmbedding,
    ContentChunk,
    CourseModuleSummary,
    ExtractedRule,
    NormalizedRule,
    QuantifiableCondition,
    RuleCluster,
    RuleQualityScore,
    SetupQualityScore,
    StrategyCandidate,
    TopStrategyDetected,
    StrategyPlaybook,
    Tag,
)
from src.db.models.media import AudioAsset, VideoAsset
from src.db.models.platform import (
    AccountAccessGrant,
    BrokerAccount,
    BrokerSymbolAlias,
    ExecutionAgent,
    LearningIntegration,
    PasswordResetToken,
    PlatformApiCredential,
    PlatformNotification,
    PlatformSecurityEvent,
    PlatformUser,
    StrategyDeployment,
)
from src.db.models.run import IngestionRun, ProcessingRun
from src.db.models.telegram_message import TelegramMessage
from src.db.models.transcript import Transcript

all_models = (
    Channel,
    ArchiveContent,
    TelegramMessage,
    FileAsset,
    ExternalResource,
    Document,
    VideoAsset,
    AudioAsset,
    Transcript,
    ContentChunk,
    ChunkEmbedding,
    Tag,
    ExtractedRule,
    RuleCluster,
    StrategyPlaybook,
    CourseModuleSummary,
    BacktestDatasetRow,
    NormalizedRule,
    QuantifiableCondition,
    StrategyCandidate,
    CandidateComponent,
    RuleQualityScore,
    SetupQualityScore,
    TopStrategyDetected,
    IngestionRun,
    ProcessingRun,
    PlatformUser,
    BrokerAccount,
    AccountAccessGrant,
    ExecutionAgent,
    StrategyDeployment,
    LearningIntegration,
    BrokerSymbolAlias,
    PlatformApiCredential,
    PasswordResetToken,
    PlatformNotification,
    PlatformSecurityEvent,
)
