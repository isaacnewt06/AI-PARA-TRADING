"""Platform models for multi-user broker connectivity and AI deployments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class PlatformUser(TimestampMixin, Base):
    """User allowed to manage or consume the trading intelligence service."""

    __tablename__ = "platform_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="client", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), default="America/Santo_Domingo", nullable=False)
    max_broker_accounts: Mapped[int] = mapped_column(default=1, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    owned_accounts = relationship("BrokerAccount", back_populates="owner")
    access_grants = relationship("AccountAccessGrant", back_populates="user")
    learning_integrations = relationship("LearningIntegration", back_populates="owner")
    api_credentials = relationship("PlatformApiCredential", back_populates="user")
    notifications = relationship("PlatformNotification", back_populates="user")
    security_events = relationship("PlatformSecurityEvent", back_populates="user")


class BrokerAccount(TimestampMixin, Base):
    """Broker account connected to the service."""

    __tablename__ = "broker_accounts"
    __table_args__ = (
        Index("ix_broker_accounts_owner_active", "owner_user_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False)
    account_label: Mapped[str] = mapped_column(String(255), nullable=False)
    broker_name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform_type: Mapped[str] = mapped_column(String(32), default="MT5", nullable=False)
    broker_server: Mapped[str | None] = mapped_column(String(255), nullable=True)
    login_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    symbol_suffix: Mapped[str | None] = mapped_column(String(32), nullable=True)
    base_currency: Mapped[str] = mapped_column(String(16), default="USD", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    connection_mode: Mapped[str] = mapped_column(String(32), default="local_agent", nullable=False)
    allowed_symbols_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_profile_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner = relationship("PlatformUser", back_populates="owned_accounts")
    access_grants = relationship("AccountAccessGrant", back_populates="account")
    execution_agents = relationship("ExecutionAgent", back_populates="account")
    strategy_deployments = relationship("StrategyDeployment", back_populates="account")
    symbol_aliases = relationship("BrokerSymbolAlias", back_populates="account")


class AccountAccessGrant(TimestampMixin, Base):
    """Permission record for a user over a broker account."""

    __tablename__ = "account_access_grants"
    __table_args__ = (
        UniqueConstraint("account_id", "user_id", name="uq_account_access_grants_account_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False)
    permission_level: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_trade: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_manage_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_manage_learning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    account = relationship("BrokerAccount", back_populates="access_grants")
    user = relationship("PlatformUser", back_populates="access_grants")


class ExecutionAgent(TimestampMixin, Base):
    """Agent that runs close to the broker terminal and executes decisions."""

    __tablename__ = "execution_agents"
    __table_args__ = (
        UniqueConstraint("agent_key", name="uq_execution_agents_agent_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    host_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="provisioning", nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    broker_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    platform_type: Mapped[str] = mapped_column(String(32), default="MT5", nullable=False)
    capabilities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    account = relationship("BrokerAccount", back_populates="execution_agents")
    runtime_reports = relationship("ExecutionAgentRuntimeReport", back_populates="agent")
    deployment_reports = relationship("DeploymentExecutionReport", back_populates="agent")


class StrategyDeployment(TimestampMixin, Base):
    """Strategy or bot mode deployed for one broker account."""

    __tablename__ = "strategy_deployments"
    __table_args__ = (
        Index("ix_strategy_deployments_account_active", "account_id", "deployment_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id"), nullable=False)
    strategy_key: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_variant: Mapped[str] = mapped_column(String(255), nullable=False)
    operation_mode: Mapped[str] = mapped_column(String(32), default="ai_managed", nullable=False)
    risk_mode: Mapped[str] = mapped_column(String(32), default="reduced", nullable=False)
    learning_mode: Mapped[str] = mapped_column(String(32), default="continuous", nullable=False)
    deployment_status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    symbol_allowlist_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_bots_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    account = relationship("BrokerAccount", back_populates="strategy_deployments")


class LearningIntegration(TimestampMixin, Base):
    """Learning source that keeps the AI refreshed."""

    __tablename__ = "learning_integrations"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "source_type",
            "source_reference",
            name="uq_learning_integrations_owner_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ingestion_mode: Mapped[str] = mapped_column(String(32), default="knowledge_first", nullable=False)
    sync_frequency_minutes: Mapped[int] = mapped_column(default=30, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner = relationship("PlatformUser", back_populates="learning_integrations")


class BrokerSymbolAlias(TimestampMixin, Base):
    """Canonical symbol mapping per broker account."""

    __tablename__ = "broker_symbol_aliases"
    __table_args__ = (
        UniqueConstraint("account_id", "canonical_symbol", name="uq_broker_symbol_alias_account_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id"), nullable=False)
    canonical_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    account = relationship("BrokerAccount", back_populates="symbol_aliases")


class PlatformApiCredential(TimestampMixin, Base):
    """User API credential for platform access and automation."""

    __tablename__ = "platform_api_credentials"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_platform_api_credentials_token_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False)
    credential_label: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_preview: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("PlatformUser", back_populates="api_credentials")


class PasswordResetToken(TimestampMixin, Base):
    """Short-lived password recovery token stored as a hash."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        Index("ix_password_reset_tokens_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_preview: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlatformNotification(TimestampMixin, Base):
    """Notification surfaced in the owner/client app notification center."""

    __tablename__ = "platform_notifications"
    __table_args__ = (
        Index("ix_platform_notifications_user_read", "user_id", "is_read"),
        Index("ix_platform_notifications_severity_created", "severity", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("platform_users.id"), nullable=True)
    audience: Mapped[str] = mapped_column(String(32), default="owner", nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="info", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("PlatformUser", back_populates="notifications")


class PlatformSecurityEvent(TimestampMixin, Base):
    """Audit trail for login, password recovery and device activity."""

    __tablename__ = "platform_security_events"
    __table_args__ = (
        Index("ix_platform_security_events_user_created", "user_id", "created_at"),
        Index("ix_platform_security_events_event", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("platform_users.id"), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="recorded", nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("PlatformUser", back_populates="security_events")


class ExecutionAgentRuntimeReport(TimestampMixin, Base):
    """Centralized snapshot for one execution-agent cycle."""

    __tablename__ = "execution_agent_runtime_reports"
    __table_args__ = (
        Index("ix_execution_agent_runtime_reports_agent_created", "agent_id", "created_at"),
        Index("ix_execution_agent_runtime_reports_account_created", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("execution_agents.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id"), nullable=False)
    cycle_status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    canonical_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    local_terminal_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open_positions_count: Mapped[int] = mapped_column(default=0, nullable=False)
    service_root_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_agent_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_status_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_environment_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    deployment_runs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    agent = relationship("ExecutionAgent", back_populates="runtime_reports")


class DeploymentExecutionReport(TimestampMixin, Base):
    """One strategy/deployment result emitted by an execution-agent cycle."""

    __tablename__ = "deployment_execution_reports"
    __table_args__ = (
        Index("ix_deployment_execution_reports_agent_created", "agent_id", "created_at"),
        Index("ix_deployment_execution_reports_account_created", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("execution_agents.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id"), nullable=False)
    strategy_key: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_variant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    canonical_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    broker_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    execution_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intelligence_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    signal_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dry_run: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    agent = relationship("ExecutionAgent", back_populates="deployment_reports")
