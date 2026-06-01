"""Pydantic request schemas for the trading service platform API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlatformBootstrapRequest(BaseModel):
    owner_email: str
    owner_name: str
    timezone_name: str = "America/Santo_Domingo"
    owner_password: str | None = None


class PlatformUserCreateRequest(BaseModel):
    email: str
    display_name: str
    role: str = "client"
    timezone_name: str = "America/Santo_Domingo"
    status: str = "active"
    max_broker_accounts: int = 1
    password: str | None = None
    notes: str | None = None


class ClientRegistrationRequest(BaseModel):
    email: str
    display_name: str
    password: str
    timezone_name: str = "America/Santo_Domingo"


class PlatformUserStatusUpdateRequest(BaseModel):
    user_id: int
    status: str


class PlatformUserAccountLimitUpdateRequest(BaseModel):
    user_id: int
    max_broker_accounts: int


class UserApiCredentialRequest(BaseModel):
    user_email: str
    credential_label: str
    notes: str | None = None


class UserApiTokenAuthRequest(BaseModel):
    token: str


class UserPasswordLoginRequest(BaseModel):
    email: str
    password: str
    device_fingerprint: str | None = None
    device_label: str | None = None


class UserPasswordSetRequest(BaseModel):
    user_email: str
    password: str


class PasswordResetRequest(BaseModel):
    email: str
    device_fingerprint: str | None = None
    device_label: str | None = None


class PasswordResetConfirmRequest(BaseModel):
    email: str
    token: str
    new_password: str


class BrokerAccountConnectRequest(BaseModel):
    owner_email: str
    account_label: str
    broker_name: str
    platform_type: str = "MT5"
    broker_server: str | None = None
    login_reference: str | None = None
    symbol_suffix: str | None = None
    base_currency: str = "USD"
    is_demo: bool = True
    connection_mode: str = "local_agent"
    allowed_symbols: list[str] = Field(default_factory=lambda: ["XAUUSD"])
    risk_profile: dict = Field(default_factory=lambda: {"risk_mode": "reduced", "daily_loss_limit_r": 3.0})
    notes: str | None = None
    source_bots: list[str] = Field(default_factory=list)


class ClientExnessAccountConnectRequest(BaseModel):
    account_label: str
    broker_server: str | None = None
    login_reference: str | None = None
    symbol_suffix: str = "m"
    base_currency: str = "USD"
    is_demo: bool = True
    referral_confirmed: bool = False
    replace_account_id: int | None = None
    notes: str | None = None


class AccountAccessGrantRequest(BaseModel):
    grantee_email: str
    permission_level: str = "operator"
    can_trade: bool = True
    can_manage_risk: bool = False
    can_manage_learning: bool = False
    notes: str | None = None


class ExecutionAgentRegisterRequest(BaseModel):
    agent_name: str
    host_name: str
    broker_name: str | None = None
    capabilities: dict = Field(
        default_factory=lambda: {
            "mt5_execution": True,
            "symbol_resolution": True,
            "demo_first": True,
        }
    )
    notes: str | None = None


class ExecutionAgentAuthRequest(BaseModel):
    agent_key: str


class ExecutionAgentHeartbeatRequest(BaseModel):
    agent_key: str
    status: str = "online"


class ExecutionAgentRuntimeReportRequest(BaseModel):
    agent_key: str
    cycle_status: str = "completed"
    canonical_symbol: str
    broker_symbol: str
    local_terminal_ready: bool
    service_root: dict = Field(default_factory=dict)
    remote_agent: dict = Field(default_factory=dict)
    heartbeat: dict = Field(default_factory=dict)
    account_status: dict = Field(default_factory=dict)
    execution_environment: dict = Field(default_factory=dict)
    open_positions: list[dict] = Field(default_factory=list)
    deployment_runs: list[dict] = Field(default_factory=list)
    notes: str | None = None


class CopyTradingMasterSignalRequest(BaseModel):
    agent_key: str
    canonical_symbol: str = "XAUUSD"
    max_age_minutes: int = 10


class StrategyDeploymentRequest(BaseModel):
    strategy_key: str
    strategy_variant: str
    operation_mode: str
    risk_mode: str
    learning_mode: str
    deployment_status: str = "active"
    symbol_allowlist: list[str] = Field(default_factory=lambda: ["XAUUSD"])
    source_bots: list[str] = Field(default_factory=list)
    notes: str | None = None


class StrategyDeploymentStateUpdateRequest(BaseModel):
    deployment_status: str | None = None
    risk_mode: str | None = None
    notes: str | None = None


class SymbolAliasRequest(BaseModel):
    canonical_symbol: str
    broker_symbol: str
    notes: str | None = None
