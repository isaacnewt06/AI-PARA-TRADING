"""FastAPI application for the multi-user trading service platform."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from src.api.schemas import (
    AccountAccessGrantRequest,
    BrokerAccountConnectRequest,
    ClientRegistrationRequest,
    ClientExnessAccountConnectRequest,
    CopyTradingMasterSignalRequest,
    ExecutionAgentAuthRequest,
    ExecutionAgentHeartbeatRequest,
    ExecutionAgentRuntimeReportRequest,
    ExecutionAgentRegisterRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PlatformBootstrapRequest,
    UserApiCredentialRequest,
    UserApiTokenAuthRequest,
    PlatformUserAccountLimitUpdateRequest,
    PlatformUserStatusUpdateRequest,
    UserPasswordLoginRequest,
    UserPasswordSetRequest,
    PlatformUserCreateRequest,
    StrategyDeploymentStateUpdateRequest,
    StrategyDeploymentRequest,
    SymbolAliasRequest,
)
from src.application.trading_service_platform import TradingServicePlatformApplicationService
from src.core.config import Settings, get_settings
from src.core.logging import setup_logging
from src.db.session import init_db, session_scope


def create_platform_api_app(settings: Settings | None = None) -> FastAPI:
    """Create the HTTP API over the platform application service."""

    resolved_settings = settings or get_settings()
    setup_logging(resolved_settings)
    init_db()

    app = FastAPI(
        title="BOTEXTRATOR Trading Service API",
        version="0.1.0",
        summary="Multi-user broker-connected AI trading platform API.",
    )

    @app.get("/")
    def root(request: Request):
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return HTMLResponse(_render_dashboard_html())
        return {
            "service": "BOTEXTRATOR Trading Service API",
            "status": "online",
            "docs_url": "/docs",
            "health_url": "/health",
            "platform_status_url": "/api/platform/status",
            "platform_readiness_url": "/api/platform/readiness",
            "capabilities": [
                "multi_user_accounts",
                "execution_agents",
                "strategy_deployments",
                "continuous_learning_sources",
            ],
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "trading_service_api"}

    @app.get("/api/platform/status")
    def platform_status(request: Request) -> dict:
        auth = _require_api_user(request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: service.platform_status_for_user(
                user_id=int(auth["user_id"]),
                role=str(auth.get("role") or ""),
            )
            | {"current_user": auth},
        )

    @app.get("/api/platform/me")
    def current_user(request: Request) -> dict:
        return _require_api_user(request, resolved_settings)

    @app.get("/api/platform/readiness")
    def platform_readiness(request: Request) -> dict:
        auth = _require_api_user(request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.platform_readiness(),
            ),
        )

    @app.get("/api/platform/ai-live")
    def platform_ai_live(request: Request) -> dict:
        auth = _require_api_user(request, resolved_settings)
        return _ai_live_snapshot(resolved_settings, auth=auth)

    @app.get("/api/platform/accounts/{account_id}")
    def account_detail(account_id: int, request: Request) -> dict:
        auth = _require_api_user(request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_account_detail(service, auth=auth, account_id=account_id),
        )

    @app.post("/api/platform/bootstrap")
    def platform_bootstrap(request: PlatformBootstrapRequest) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.bootstrap_platform(
                owner_email=request.owner_email,
                owner_name=request.owner_name,
                timezone_name=request.timezone_name,
                owner_password=request.owner_password,
            ),
        )

    @app.post("/api/platform/register")
    def register_client(request: ClientRegistrationRequest) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.register_client(
                email=request.email,
                display_name=request.display_name,
                password=request.password,
                timezone_name=request.timezone_name,
            ),
        )

    @app.post("/api/platform/users")
    def create_user(request: PlatformUserCreateRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.create_user(
                    email=request.email,
                    display_name=request.display_name,
                    role=request.role,
                    status=request.status,
                    timezone_name=request.timezone_name,
                    max_broker_accounts=request.max_broker_accounts,
                    password=request.password,
                    notes=request.notes,
                ),
            ),
        )

    @app.post("/api/platform/users/status")
    def update_user_status(request: PlatformUserStatusUpdateRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.update_user_status(
                    user_id=request.user_id,
                    status=request.status,
                ),
            ),
        )

    @app.post("/api/platform/users/account-limit")
    def update_user_account_limit(request: PlatformUserAccountLimitUpdateRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.update_user_account_limit(
                    user_id=request.user_id,
                    max_broker_accounts=request.max_broker_accounts,
                ),
            ),
        )

    @app.post("/api/platform/users/password")
    def set_user_password(request: UserPasswordSetRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.set_user_password(
                    user_email=request.user_email,
                    password=request.password,
                ),
            ),
        )

    @app.post("/api/platform/users/credentials")
    def issue_user_api_credential(request: UserApiCredentialRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.issue_user_api_credential(
                    user_email=request.user_email,
                    credential_label=request.credential_label,
                    notes=request.notes,
                ),
            ),
        )

    @app.post("/api/platform/auth/token")
    def authenticate_user_token(request: UserApiTokenAuthRequest) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.authenticate_user_api_credential(token=request.token),
        )

    @app.post("/api/platform/auth/login")
    def authenticate_user_password(request: UserPasswordLoginRequest, raw_request: Request) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.authenticate_user_password(
                email=request.email,
                password=request.password,
                request_ip=_client_ip(raw_request),
                request_user_agent=raw_request.headers.get("user-agent"),
                device_fingerprint=request.device_fingerprint,
                device_label=request.device_label,
            ),
        )

    @app.post("/api/platform/auth/password-reset/request")
    def request_password_reset(request: PasswordResetRequest, raw_request: Request) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.request_password_reset(
                email=request.email,
                request_ip=_client_ip(raw_request),
                request_user_agent=raw_request.headers.get("user-agent"),
                device_fingerprint=request.device_fingerprint,
                device_label=request.device_label,
            ),
        )

    @app.post("/api/platform/auth/password-reset/confirm")
    def confirm_password_reset(request: PasswordResetConfirmRequest) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.reset_password_with_token(
                email=request.email,
                token=request.token,
                new_password=request.new_password,
            ),
        )

    @app.get("/api/platform/notifications")
    def notification_center(raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: service.notification_center(
                user_id=int(auth["user_id"]),
                role=str(auth.get("role") or ""),
            ),
        )

    @app.post("/api/platform/notifications/{notification_id}/read")
    def mark_notification_read(notification_id: int, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: service.mark_notification_read(
                notification_id=notification_id,
                user_id=int(auth["user_id"]),
                role=str(auth.get("role") or ""),
            ),
        )

    @app.post("/api/platform/accounts")
    def connect_account(request: BrokerAccountConnectRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.connect_broker_account(
                    owner_email=request.owner_email,
                    account_label=request.account_label,
                    broker_name=request.broker_name,
                    platform_type=request.platform_type,
                    broker_server=request.broker_server,
                    login_reference=request.login_reference,
                    symbol_suffix=request.symbol_suffix,
                    base_currency=request.base_currency,
                    is_demo=request.is_demo,
                    connection_mode=request.connection_mode,
                    allowed_symbols=request.allowed_symbols,
                    risk_profile=request.risk_profile,
                    notes=request.notes,
                    source_bots=request.source_bots,
                ),
            ),
        )

    @app.post("/api/platform/me/accounts/exness")
    def connect_my_exness_account(request: ClientExnessAccountConnectRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: service.connect_own_exness_account(
                user_id=int(auth["user_id"]),
                account_label=request.account_label,
                broker_server=request.broker_server,
                login_reference=request.login_reference,
                symbol_suffix=request.symbol_suffix,
                base_currency=request.base_currency,
                is_demo=request.is_demo,
                referral_confirmed=request.referral_confirmed,
                replace_account_id=request.replace_account_id,
                notes=request.notes,
            ),
        )

    @app.delete("/api/platform/me/accounts/{account_id}")
    def delete_my_account(account_id: int, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: service.deactivate_own_broker_account(
                user_id=int(auth["user_id"]),
                account_id=account_id,
            ),
        )

    @app.delete("/api/platform/accounts/{account_id}")
    def delete_account_as_owner(account_id: int, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.deactivate_broker_account_as_owner(account_id=account_id),
            ),
        )

    @app.post("/api/platform/accounts/{account_id}/access")
    def grant_account_access(account_id: int, request: AccountAccessGrantRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.grant_account_access(
                    account_id=account_id,
                    grantee_email=request.grantee_email,
                    permission_level=request.permission_level,
                    can_trade=request.can_trade,
                    can_manage_risk=request.can_manage_risk,
                    can_manage_learning=request.can_manage_learning,
                    notes=request.notes,
                ),
            ),
        )

    @app.post("/api/platform/accounts/{account_id}/agents")
    def register_execution_agent(account_id: int, request: ExecutionAgentRegisterRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.register_execution_agent(
                    account_id=account_id,
                    agent_name=request.agent_name,
                    host_name=request.host_name,
                    broker_name=request.broker_name,
                    capabilities=request.capabilities,
                    notes=request.notes,
                ),
            ),
        )

    @app.post("/api/platform/accounts/{account_id}/agents/authenticate")
    def authenticate_execution_agent(account_id: int, request: ExecutionAgentAuthRequest) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.authenticate_execution_agent(
                account_id=account_id,
                agent_key=request.agent_key,
            ),
        )

    @app.post("/api/platform/accounts/{account_id}/agents/heartbeat")
    def heartbeat_execution_agent(account_id: int, request: ExecutionAgentHeartbeatRequest) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.heartbeat_execution_agent(
                account_id=account_id,
                agent_key=request.agent_key,
                status=request.status,
            ),
        )

    @app.post("/api/platform/accounts/{account_id}/agents/report")
    def record_execution_agent_runtime(account_id: int, request: ExecutionAgentRuntimeReportRequest) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.record_execution_agent_runtime(
                account_id=account_id,
                agent_key=request.agent_key,
                cycle_status=request.cycle_status,
                canonical_symbol=request.canonical_symbol,
                broker_symbol=request.broker_symbol,
                local_terminal_ready=request.local_terminal_ready,
                service_root=request.service_root,
                remote_agent=request.remote_agent,
                heartbeat=request.heartbeat,
                account_status=request.account_status,
                execution_environment=request.execution_environment,
                open_positions=request.open_positions,
                deployment_runs=request.deployment_runs,
                notes=request.notes,
            ),
        )

    @app.post("/api/platform/accounts/{account_id}/copy-trading/master-signal")
    def copy_trading_master_signal(account_id: int, request: CopyTradingMasterSignalRequest) -> dict:
        return _run_service(
            resolved_settings,
            lambda service: service.copy_trading_master_signal(
                account_id=account_id,
                agent_key=request.agent_key,
                canonical_symbol=request.canonical_symbol,
                max_age_minutes=request.max_age_minutes,
            ),
        )

    @app.post("/api/platform/accounts/{account_id}/deployments")
    def deploy_strategy(account_id: int, request: StrategyDeploymentRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.deploy_strategy_mode(
                    account_id=account_id,
                    strategy_key=request.strategy_key,
                    strategy_variant=request.strategy_variant,
                    operation_mode=request.operation_mode,
                    risk_mode=request.risk_mode,
                    learning_mode=request.learning_mode,
                    deployment_status=request.deployment_status,
                    symbol_allowlist=request.symbol_allowlist,
                    source_bots=request.source_bots,
                    notes=request.notes,
                ),
            ),
        )

    @app.post("/api/platform/deployments/{deployment_id}/status")
    def update_deployment_state(deployment_id: int, request: StrategyDeploymentStateUpdateRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_deployment_state_update(
                service,
                auth=auth,
                deployment_id=deployment_id,
                request=request,
            ),
        )

    @app.post("/api/platform/accounts/{account_id}/symbols")
    def map_symbol(account_id: int, request: SymbolAliasRequest, raw_request: Request) -> dict:
        auth = _require_api_user(raw_request, resolved_settings)
        return _run_service(
            resolved_settings,
            lambda service: _authorized_owner_action(
                service,
                auth=auth,
                action=lambda: service.map_broker_symbol(
                    account_id=account_id,
                    canonical_symbol=request.canonical_symbol,
                    broker_symbol=request.broker_symbol,
                    notes=request.notes,
                ),
            ),
        )

    return app


def _run_service(settings: Settings, operation: Callable[[TradingServicePlatformApplicationService], dict]) -> dict:
    try:
        with session_scope() as session:
            service = TradingServicePlatformApplicationService(session, settings)
            return operation(service)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    fallback = request.headers.get("x-api-token", "").strip()
    return fallback or None


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else None


def _require_api_user(request: Request, settings: Settings) -> dict:
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API token.")
    try:
        return _run_service(
            settings,
            lambda service: service.authenticate_user_api_credential(token=token),
        )
    except HTTPException as exc:
        if exc.status_code == 400:
            raise HTTPException(status_code=401, detail="Invalid API token.") from exc
        raise


def _authorized_owner_action(
    service: TradingServicePlatformApplicationService,
    *,
    auth: dict,
    action: Callable[[], dict],
) -> dict:
    service.authorize_owner_role(role=str(auth.get("role") or ""))
    return action()


def _authorized_account_detail(
    service: TradingServicePlatformApplicationService,
    *,
    auth: dict,
    account_id: int,
) -> dict:
    service.authorize_account_view(
        account_id=account_id,
        user_id=int(auth["user_id"]),
        role=str(auth.get("role") or ""),
    )
    return service.account_detail(account_id=account_id)


def _authorized_deployment_state_update(
    service: TradingServicePlatformApplicationService,
    *,
    auth: dict,
    deployment_id: int,
    request: StrategyDeploymentStateUpdateRequest,
) -> dict:
    service.authorize_deployment_control(
        deployment_id=deployment_id,
        user_id=int(auth["user_id"]),
        role=str(auth.get("role") or ""),
    )
    return service.update_deployment_state(
        deployment_id=deployment_id,
        deployment_status=request.deployment_status,
        risk_mode=request.risk_mode,
        notes=request.notes,
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _file_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "size_bytes": 0, "updated_at": None}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _last_jsonl_event(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.stat().st_size <= 0:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-80:]):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _ai_live_snapshot(settings: Settings, *, auth: dict) -> dict[str, Any]:
    data_dir = settings.paths.data_dir
    demo_dir = data_dir / "demo_trading" / "maximo_quant_v4"
    market_dir = data_dir / "market_analysis" / "maximo_quant_v4"
    learning_dir = settings.paths.knowledge_dir / "learning_cycle"

    latest_signal_path = demo_dir / "latest_signal.json"
    latest_intelligence_path = market_dir / "latest_market_intelligence.json"
    demo_report_path = demo_dir / "demo_report.md"
    active_watch_history_path = demo_dir / "active_watch_history.jsonl"
    decision_audit_path = demo_dir / "decision_source_audit.jsonl"
    learning_report_path = learning_dir / "learning_cycle_report.json"

    latest_signal = _read_json_file(latest_signal_path)
    latest_intelligence = _read_json_file(latest_intelligence_path)
    learning_report = _read_json_file(learning_report_path)
    latest_signal_status = _file_status(latest_signal_path)
    latest_signal_updated_at = latest_signal_status.get("updated_at")
    latest_signal_age_seconds = None
    if latest_signal_updated_at:
        try:
            latest_signal_age_seconds = round(
                (datetime.now(timezone.utc) - datetime.fromisoformat(str(latest_signal_updated_at))).total_seconds(),
                1,
            )
        except ValueError:
            latest_signal_age_seconds = None
    runtime_state = "fresh"
    if latest_signal_age_seconds is None:
        runtime_state = "missing"
    elif latest_signal_age_seconds > 60:
        runtime_state = "stale"

    watch_trigger = latest_signal.get("watch_trigger", {}) or {}
    reasoning = latest_signal.get("reasoning_snapshot", {}) or {}
    projection = watch_trigger.get("pattern_projection", {}) or reasoning.get("learned_pattern_projection", {}) or {}
    setup = reasoning.get("setup_assessment", {}) or {}
    market_context = reasoning.get("market_context", {}) or {}
    active_watch = latest_signal.get("active_watch", {}) or {}
    watch_policy = latest_signal.get("watch_execution_policy", {}) or {}
    risk_decision = latest_signal.get("execution_risk_decision", {}) or {}
    controlled_protocol = latest_signal.get("controlled_demo_survival_protocol", {}) or {}
    final_confirmation = latest_signal.get("final_confirmation") or reasoning.get("final_confirmation") or {}
    entry_quality = latest_signal.get("entry_quality") or reasoning.get("entry_quality") or {}
    execution_readiness_quality = (
        latest_signal.get("execution_readiness_quality")
        or reasoning.get("execution_readiness_quality")
        or reasoning.get("execution_readiness")
        or {}
    )
    market_pulse = latest_signal.get("market_pulse") or reasoning.get("market_pulse") or {}
    event_risk = latest_intelligence.get("event_risk", {}) or {}
    external_context = _build_external_market_context(event_risk)
    market_state = (latest_intelligence.get("overview", {}) or {}).get("market_state", {}) or {}
    knowledge_alignment = (latest_intelligence.get("overview", {}) or {}).get("knowledge_alignment", {}) or {}
    harmony = knowledge_alignment.get("harmony", {}) or {}
    applicable = learning_report.get("applicable_knowledge", {}) or {}
    knowledge_after = learning_report.get("knowledge_after", {}) or {}
    price_context = _build_ai_price_context(
        settings=settings,
        latest_signal=latest_signal,
        latest_intelligence=latest_intelligence,
        watch_trigger=watch_trigger,
        reasoning=reasoning,
    )
    blocked_signal_statuses = {
        "blocked_by_direction_consistency",
        "blocked_by_final_confirmation",
        "blocked_by_min_lot_exceeds_10_percent_account_risk",
        "blocked_by_reentry_cooldown",
    }
    raw_signal_detected = bool(watch_trigger.get("signal_detected") or (reasoning.get("state", {}) or {}).get("signal_detected"))
    signal_confirmed_for_execution = bool(
        raw_signal_detected and str(latest_signal.get("execution_status") or "") not in blocked_signal_statuses
    )
    session_analysis = final_confirmation.get("session_execution_analysis", {}) or {}
    execution_cost_analysis = final_confirmation.get("execution_cost_analysis", {}) or {}
    premium_discount_analysis = final_confirmation.get("premium_discount_analysis", {}) or {}
    dynamic_threshold_analysis = final_confirmation.get("dynamic_threshold_analysis", {}) or {}
    blocker_reasons = _build_ai_block_reasons(
        final_confirmation=final_confirmation,
        risk_decision=risk_decision,
        market_context=market_context,
        event_risk=event_risk,
    )
    operational_sessions = _build_operational_sessions(session_analysis)
    asset_radar = _build_asset_radar(
        symbol=latest_signal.get("symbol") or latest_intelligence.get("symbol"),
        brain_action=latest_signal.get("intelligence_action") or (latest_intelligence.get("execution_readiness", {}) or {}).get("action"),
        execution_status=latest_signal.get("execution_status"),
        market_pulse=market_pulse,
        final_confirmation=final_confirmation,
        entry_quality=entry_quality,
        execution_readiness_quality=execution_readiness_quality,
        active_watch=active_watch,
        risk_decision=risk_decision,
        blocker_reasons=blocker_reasons,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_user": {
            "user_id": auth.get("user_id"),
            "role": auth.get("role"),
            "user_email": auth.get("user_email"),
        },
        "brain": {
            "generated_at": latest_signal.get("generated_at") or latest_signal.get("generated_at_utc"),
            "artifact_updated_at": latest_signal_updated_at,
            "artifact_age_seconds": latest_signal_age_seconds,
            "runtime_state": runtime_state,
            "symbol": latest_signal.get("symbol") or latest_intelligence.get("symbol"),
            "dry_run": latest_signal.get("dry_run"),
            "action": latest_signal.get("intelligence_action") or (latest_intelligence.get("execution_readiness", {}) or {}).get("action"),
            "execution_status": latest_signal.get("execution_status"),
            "operating_posture": latest_signal.get("operating_posture") or harmony.get("operating_posture"),
            "harmony_score": latest_signal.get("harmony_score") or harmony.get("harmony_score"),
            "watch_health": (latest_signal.get("active_watch_metrics", {}) or {}).get("watch_health"),
            "watch_probability_to_execute": (latest_signal.get("active_watch_metrics", {}) or {}).get("watch_probability_to_execute"),
            "watch_policy_action": watch_policy.get("watch_policy_action"),
            "allowed_risk_mode": watch_policy.get("allowed_risk_mode") or risk_decision.get("allowed_risk_mode"),
            "max_risk_multiplier": watch_policy.get("max_risk_multiplier") or risk_decision.get("max_risk_multiplier"),
            "effective_risk": risk_decision.get("effective_risk"),
        },
        "market": {
            "preferred_side": watch_trigger.get("side") or market_state.get("preferred_side"),
            "candidate_side": watch_trigger.get("candidate_side") or projection.get("candidate_side"),
            "higher_timeframe_bias": watch_trigger.get("higher_timeframe_bias") or market_context.get("higher_timeframe_bias"),
            "market_regime": watch_trigger.get("market_regime") or market_state.get("market_regime"),
            "volatility": watch_trigger.get("volatility") or market_context.get("volatility"),
            "atr_regime": market_context.get("atr_regime"),
            "atr_ratio": market_context.get("atr_ratio") or market_state.get("atr_ratio"),
            "live_spread": market_context.get("live_spread"),
            "slippage_estimated": market_context.get("slippage_estimated"),
            "execution_viability": market_context.get("execution_viability"),
            "macro_event_action": watch_trigger.get("macro_event_status") or event_risk.get("action"),
            "active_events": event_risk.get("active_events", [])[:3],
            "upcoming_events": event_risk.get("upcoming_events", [])[:3],
        },
        "external_context": external_context,
        "pattern_projection": {
            "dominant_family": projection.get("dominant_family") or harmony.get("dominant_family"),
            "operational_family": projection.get("operational_family") or watch_trigger.get("operational_family"),
            "candidate_side": projection.get("candidate_side") or watch_trigger.get("candidate_side"),
            "probable_market_move": projection.get("probable_market_move"),
            "near_execute_watch": projection.get("near_execute_watch"),
            "maturity_gap_to_execute": projection.get("maturity_gap_to_execute"),
            "interpretation": projection.get("interpretation"),
            "pattern_matches": list(projection.get("pattern_matches", [])),
            "evidence": list(projection.get("evidence", [])),
            "confirmation_focus": list(projection.get("confirmation_focus", [])),
            "missing_confirmations": list(projection.get("missing_confirmations", [])),
            "historical_analogs": projection.get("historical_analogs", {}),
            "side_probability_comparison": projection.get("side_probability_comparison", {}),
            "cool_learning_memory": projection.get("cool_learning_memory", {}),
            "professional_decision_matrix": projection.get("professional_decision_matrix", {}),
        },
        "price_context": price_context,
        "reasoning": {
            "summary": (reasoning.get("state", {}) or {}).get("summary"),
            "next_confirmation_expected": reasoning.get("next_confirmation_expected"),
            "waiting_for": list(reasoning.get("waiting_for", []) or watch_trigger.get("missing_for_execute", [])),
            "cancel_if": list(reasoning.get("cancel_if", []) or watch_trigger.get("cancel_conditions", [])),
            "condition_checklist": list(reasoning.get("condition_checklist", [])),
            "setup_maturity": watch_trigger.get("setup_maturity") or setup.get("setup_maturity"),
            "confidence": watch_trigger.get("confidence") or setup.get("confidence"),
            "signal_detected": signal_confirmed_for_execution,
            "signal_candidate_detected": raw_signal_detected,
            "execution_recovery_plan": risk_decision.get("execution_recovery_plan")
            or reasoning.get("execution_recovery_plan")
            or {},
        },
        "execution_guard": {
            "final_confirmation_score": final_confirmation.get("final_confirmation_score"),
            "final_confirmation_decision": final_confirmation.get("decision"),
            "required_execute_score": final_confirmation.get("required_execute_score"),
            "entry_quality_score": entry_quality.get("entry_quality_score"),
            "execution_readiness_score": execution_readiness_quality.get("execution_readiness_score"),
            "market_pulse_score": market_pulse.get("score"),
            "session_analysis": session_analysis,
            "execution_cost_analysis": execution_cost_analysis,
            "premium_discount_analysis": premium_discount_analysis,
            "dynamic_threshold_analysis": dynamic_threshold_analysis,
            "blocker_reasons": blocker_reasons,
            "operational_sessions": operational_sessions,
            "asset_radar": asset_radar,
        },
        "active_watch": {
            "status": active_watch.get("status"),
            "side": active_watch.get("side"),
            "trigger_type": active_watch.get("trigger_type"),
            "age_candles": active_watch.get("age_candles"),
            "progress": active_watch.get("progress"),
            "reason": active_watch.get("reason"),
            "last_event": _last_jsonl_event(active_watch_history_path),
        },
        "learning": {
            "status": learning_report.get("status"),
            "last_cycle_at": learning_report.get("generated_at") or learning_report.get("generated_at_utc"),
            "interpretation": learning_report.get("knowledge_change_interpretation"),
            "applicability_level": (applicable.get("applicability", {}) or {}).get("level"),
            "applicability_score": (applicable.get("applicability", {}) or {}).get("score"),
            "recognized_patterns": list(applicable.get("recognized_patterns", []))[:8],
            "knowledge_counts": knowledge_after,
            "risk_governance": learning_report.get("risk_governance", {}),
        },
        "audit": {
            "last_decision_source_event": _last_jsonl_event(decision_audit_path),
            "sources": {
                "latest_signal": _file_status(latest_signal_path),
                "latest_market_intelligence": _file_status(latest_intelligence_path),
                "demo_report": _file_status(demo_report_path),
                "learning_cycle_report": _file_status(learning_report_path),
                "active_watch_history": _file_status(active_watch_history_path),
                "decision_source_audit": _file_status(decision_audit_path),
            },
        },
    }


def _build_ai_block_reasons(
    *,
    final_confirmation: dict[str, Any],
    risk_decision: dict[str, Any],
    market_context: dict[str, Any],
    event_risk: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(str(item) for item in final_confirmation.get("blockers", []) or [])
    reasons.extend(str(item) for item in risk_decision.get("blockers", []) or [])
    for key in ("execution_status", "risk_application_reason", "reason"):
        value = risk_decision.get(key)
        if value:
            reasons.append(str(value))
    if market_context.get("execution_viability") and market_context.get("execution_viability") != "SAFE":
        reasons.append(f"execution_viability={market_context.get('execution_viability')}")
    if event_risk.get("action") and event_risk.get("action") != "allow":
        reasons.append(f"macro_event_action={event_risk.get('action')}")
    seen: set[str] = set()
    clean: list[str] = []
    for item in reasons:
        text = item.strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            clean.append(text)
    return clean[:12]


def _build_operational_sessions(session_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    current = str(session_analysis.get("session") or "").lower()
    windows = [
        ("london_rd", "Londres RD", "03:00-05:00", "Alta probabilidad institucional si hay estructura y liquidez."),
        ("ny_rd", "Nueva York RD", "08:00-11:30", "Ventana principal para XAUUSDm con confirmación limpia."),
        ("pm_volatility_rd", "Tarde RD", "14:00-16:00", "Oportunidad extra: exigir confirmaciones completas y spread sano."),
        ("evening_volatility_rd", "Noche RD", "20:00-22:00", "Oportunidad extra: operar solo si el mercado muestra movimiento real."),
    ]
    return [
        {
            "code": code,
            "label": label,
            "hours": hours,
            "note": note,
            "active": current == code,
        }
        for code, label, hours, note in windows
    ]


def _build_asset_radar(
    *,
    symbol: Any,
    brain_action: Any,
    execution_status: Any,
    market_pulse: dict[str, Any],
    final_confirmation: dict[str, Any],
    entry_quality: dict[str, Any],
    execution_readiness_quality: dict[str, Any],
    active_watch: dict[str, Any],
    risk_decision: dict[str, Any],
    blocker_reasons: list[str],
) -> list[dict[str, Any]]:
    status = str(execution_status or brain_action or "WAIT").upper()
    if blocker_reasons:
        status = "BLOCK"
    elif str(final_confirmation.get("decision") or "").upper() == "EXECUTE":
        status = "EXECUTE"
    elif active_watch.get("status"):
        status = str(active_watch.get("status") or "WATCH").upper()
    return [
        {
            "symbol": symbol or "XAUUSDm",
            "status": status,
            "side": final_confirmation.get("side") or active_watch.get("side") or "NEUTRAL",
            "market_pulse": market_pulse.get("score"),
            "final_confirmation": final_confirmation.get("final_confirmation_score"),
            "entry_quality": entry_quality.get("entry_quality_score"),
            "execution_readiness": execution_readiness_quality.get("execution_readiness_score"),
            "risk_mode": risk_decision.get("allowed_risk_mode"),
            "reason": blocker_reasons[0] if blocker_reasons else final_confirmation.get("reason") or active_watch.get("reason"),
        }
    ]


def _build_external_market_context(event_risk: dict[str, Any]) -> dict[str, Any]:
    active_events = list(event_risk.get("active_events", []) or [])
    upcoming_events = list(event_risk.get("upcoming_events", []) or [])
    sync_status = event_risk.get("sync_status", {}) or {}
    action = str(event_risk.get("action") or "unknown")
    next_event = active_events[0] if active_events else (upcoming_events[0] if upcoming_events else None)
    if active_events:
        anticipation = "Evento activo: dejar que el mercado muestre dirección real antes de ejecutar."
    elif next_event:
        minutes = next_event.get("minutes_until_start")
        impact = str(next_event.get("impact") or "unknown")
        title = str(next_event.get("title") or "evento macro")
        anticipation = f"Próximo evento {impact}: {title} en {minutes} min. Preparar escenarios, no perseguir velas extendidas."
    else:
        anticipation = "Sin eventos relevantes cercanos; decidir principalmente por estructura, liquidez, momentum y spread."
    if sync_status.get("status") == "error":
        anticipation += " La fuente externa falló; se usa caché/manual hasta el próximo intento."
    return {
        "action": action,
        "highest_active_impact": event_risk.get("highest_active_impact"),
        "highest_upcoming_impact": event_risk.get("highest_upcoming_impact"),
        "sync_status": sync_status,
        "active_events": active_events[:3],
        "upcoming_events": upcoming_events[:5],
        "next_event": next_event,
        "anticipation": anticipation,
        "local_timezone": event_risk.get("local_timezone"),
        "source_path": event_risk.get("source_path"),
        "live_cache_path": event_risk.get("live_cache_path"),
    }


def _round_market_price(value: Any, digits: int = 3) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not numeric:
        return None
    return round(numeric, digits)


def _build_ai_price_context(
    *,
    settings: Settings,
    latest_signal: dict[str, Any],
    latest_intelligence: dict[str, Any],
    watch_trigger: dict[str, Any],
    reasoning: dict[str, Any],
) -> dict[str, Any]:
    """Build a read-only price map for the live AI panel.

    This is intentionally observational. It gives the user concrete levels the
    AI is watching without changing execution thresholds or trading logic.
    """

    symbol = latest_signal.get("symbol") or latest_intelligence.get("symbol") or "XAUUSD"
    side = (
        watch_trigger.get("candidate_side")
        or watch_trigger.get("side")
        or ((reasoning.get("state", {}) or {}).get("preferred_side"))
        or "NEUTRAL"
    )
    base = {
        "status": "unavailable",
        "source": "mt5_read_only_snapshot",
        "symbol": symbol,
        "side": side,
        "message": "No se pudo leer MT5 para calcular zona/precio en este ciclo.",
    }
    if not symbol:
        return base

    try:
        from src.trading.mt5_bridge import MT5Bridge

        bridge = MT5Bridge(settings)
        environment = bridge.read_execution_environment(symbol=str(symbol))
        snapshot = bridge.read_market_snapshot(
            symbol=str(symbol),
            bars_by_timeframe={"M1": 80, "M5": 80, "H1": 40},
        )
    except Exception as exc:  # pragma: no cover - depends on local MT5 availability
        return {**base, "message": f"MT5 no disponible para lectura de zona: {exc}"}

    candles = snapshot.get("candles", {})
    m5 = list(candles.get("M5", []) or [])
    m1 = list(candles.get("M1", []) or [])
    if not m5:
        return {**base, "message": "MT5 respondió, pero no devolvió velas M5 suficientes."}

    latest_m5 = m5[-1]
    recent_m5 = m5[-12:] if len(m5) >= 12 else m5
    recent_high = max(float(candle.high) for candle in recent_m5)
    recent_low = min(float(candle.low) for candle in recent_m5)
    bid = _round_market_price(environment.get("bid"))
    ask = _round_market_price(environment.get("ask"))
    current_price = _round_market_price(((bid or 0.0) + (ask or 0.0)) / 2.0) if bid and ask else _round_market_price(float(latest_m5.close))
    m1_last = m1[-1] if m1 else None

    latest_open = float(latest_m5.open)
    latest_high = float(latest_m5.high)
    latest_low = float(latest_m5.low)
    latest_close = float(latest_m5.close)
    body_high = max(latest_open, latest_close)
    body_low = min(latest_open, latest_close)
    candle_direction = "bullish" if latest_close > latest_open else "bearish" if latest_close < latest_open else "neutral"
    side_upper = str(side or "NEUTRAL").upper()

    if side_upper == "BUY":
        watch_low = min(recent_low, latest_low)
        watch_high = max(body_low, latest_low)
        confirmation_price = max(latest_high, body_high)
        invalidation_price = watch_low
        distance = (confirmation_price - current_price) if current_price is not None else None
        confirmation_rule = "Esperar cierre M5 alcista por encima del máximo/zona de rechazo y M1 sosteniendo micro BOS alcista."
        zone_label = "zona de rechazo/soporte reciente para BUY"
    elif side_upper == "SELL":
        watch_low = min(body_high, latest_high)
        watch_high = max(recent_high, latest_high)
        confirmation_price = min(latest_low, body_low)
        invalidation_price = watch_high
        distance = (current_price - confirmation_price) if current_price is not None else None
        confirmation_rule = "Esperar cierre M5 bajista por debajo del mínimo/zona de rechazo y M1 sosteniendo micro BOS bajista."
        zone_label = "zona de rechazo/resistencia reciente para SELL"
    else:
        watch_low = recent_low
        watch_high = recent_high
        confirmation_price = None
        invalidation_price = None
        distance = None
        confirmation_rule = "Esperar que el mercado defina lado operativo antes de preparar entrada."
        zone_label = "rango reciente de observación"

    return {
        "status": "ready",
        "source": "mt5_read_only_snapshot",
        "symbol": snapshot.get("symbol") or symbol,
        "side": side_upper,
        "bid": bid,
        "ask": ask,
        "current_price": current_price,
        "spread": _round_market_price(environment.get("live_spread")),
        "execution_viability": environment.get("execution_viability"),
        "reference_timeframe": "M5",
        "reference_candle_time": latest_m5.time.isoformat(),
        "latest_m5": {
            "open": _round_market_price(latest_open),
            "high": _round_market_price(latest_high),
            "low": _round_market_price(latest_low),
            "close": _round_market_price(latest_close),
            "direction": candle_direction,
        },
        "latest_m1": {
            "time": m1_last.time.isoformat(),
            "open": _round_market_price(m1_last.open),
            "high": _round_market_price(m1_last.high),
            "low": _round_market_price(m1_last.low),
            "close": _round_market_price(m1_last.close),
        } if m1_last else None,
        "watch_zone": {
            "label": zone_label,
            "low": _round_market_price(min(watch_low, watch_high)),
            "high": _round_market_price(max(watch_low, watch_high)),
        },
        "confirmation_price": _round_market_price(confirmation_price),
        "invalidation_price": _round_market_price(invalidation_price),
        "distance_to_confirmation": _round_market_price(distance),
        "confirmation_rule": confirmation_rule,
        "note": "Estos niveles son guía visual de observación; la orden solo se permite si pasan signal_detected, SL, RR, eventos, spread y risk binding.",
    }


def _render_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>BOTEXTRATOR Trading Service</title>
    <style>
      :root {
        --bg: #030712;
        --panel: rgba(11, 20, 38, .78);
        --panel-2: rgba(24, 38, 64, .72);
        --line: rgba(190, 225, 255, .13);
        --text: #f3f8ff;
        --muted: #9eb2cc;
        --accent: #21f7c4;
        --accent-2: #f7c948;
        --accent-3: #42b7ff;
        --accent-4: #ff5cc7;
        --ink: #06111b;
        --danger: #ff6e7a;
        --shadow: 0 26px 80px rgba(0,0,0,.36);
      }
      * { box-sizing: border-box; }
      html { scroll-behavior: smooth; }
      body {
        margin: 0;
        min-height: 100vh;
        font-family: "Bahnschrift", "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
        background:
          radial-gradient(circle at 12% -8%, rgba(33,247,196,.30), transparent 27%),
          radial-gradient(circle at 82% 8%, rgba(255,92,199,.22), transparent 25%),
          radial-gradient(circle at 58% 90%, rgba(66,183,255,.16), transparent 28%),
          linear-gradient(145deg, #030712 0%, #07111f 48%, #0a1322 100%);
        color: var(--text);
      }
      body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background-image:
          linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
        background-size: 52px 52px;
        mask-image: linear-gradient(180deg, rgba(0,0,0,.76), transparent 78%);
      }
      body::after {
        content: "";
        position: fixed;
        inset: -20%;
        pointer-events: none;
        background:
          radial-gradient(circle at 20% 25%, rgba(33,247,196,.12), transparent 24%),
          radial-gradient(circle at 78% 32%, rgba(255,92,199,.10), transparent 25%),
          radial-gradient(circle at 52% 82%, rgba(255,211,79,.08), transparent 22%);
        filter: blur(18px);
        opacity: .75;
        animation: ambientAurora 12s ease-in-out infinite alternate;
      }
      .shell {
        max-width: 1480px;
        margin: 0 auto;
        padding: 22px 28px 48px;
        position: relative;
        z-index: 1;
      }
      .topbar {
        position: sticky;
        top: 14px;
        z-index: 10;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
        margin-bottom: 24px;
        padding: 12px 14px;
        border: 1px solid rgba(255,255,255,.12);
        border-radius: 24px;
        background: rgba(3, 9, 20, .74);
        backdrop-filter: blur(18px);
        box-shadow: 0 18px 60px rgba(0,0,0,.30);
      }
      .brand {
        display: flex;
        align-items: center;
        gap: 12px;
        min-width: 240px;
      }
      .brand-mark {
        display: grid;
        place-items: center;
        width: 42px;
        height: 42px;
        border-radius: 16px;
        background:
          radial-gradient(circle at 28% 24%, #ffffff, transparent 17%),
          linear-gradient(135deg, var(--accent), var(--accent-3) 58%, var(--accent-4));
        color: #041017;
        font-weight: 900;
        box-shadow: 0 0 34px rgba(33,247,196,.30);
      }
      .brand strong {
        display: block;
        letter-spacing: -.03em;
      }
      .brand span {
        display: block;
        color: var(--muted);
        font-size: 12px;
        margin-top: 2px;
      }
      .nav-actions {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 10px;
        flex-wrap: wrap;
      }
      .notification-button {
        min-width: 48px;
        padding: 12px 14px;
        border-radius: 999px;
        background:
          linear-gradient(135deg, rgba(255,255,255,.14), rgba(66,183,255,.09)),
          rgba(12, 22, 40, .82);
        color: #f3f8ff;
        border: 1px solid rgba(255,255,255,.18);
        box-shadow: 0 14px 36px rgba(0,0,0,.18);
      }
      .notification-button.alert {
        background: linear-gradient(135deg, #ff3d5f, #ff9f43);
        color: #160407;
        animation: alertPulse 1.25s ease-in-out infinite;
      }
      .notification-count {
        display: inline-grid;
        place-items: center;
        min-width: 20px;
        height: 20px;
        margin-left: 6px;
        border-radius: 999px;
        background: rgba(255,255,255,.82);
        color: #160407;
        font-size: 11px;
        font-weight: 900;
      }
      .hero {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 22px;
        align-items: center;
        margin-bottom: 22px;
      }
      .hero-copy { display: grid; gap: 12px; }
      .hero-kicker {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 8px 14px;
        border-radius: 999px;
        width: fit-content;
        border: 1px solid rgba(25,240,194,.22);
        background: rgba(25,240,194,.08);
        color: #b7fff1;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .12em;
      }
      .hero h1 {
        margin: 0;
        font-size: clamp(34px, 4vw, 58px);
        line-height: 1.02;
        letter-spacing: -.04em;
      }
      .hero p {
        margin: 0;
        color: var(--muted);
        max-width: 800px;
        line-height: 1.58;
        font-size: 15px;
      }
      .badge {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 11px 15px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: rgba(255,255,255,.04);
        color: var(--text);
        font-size: 13px;
        backdrop-filter: blur(8px);
      }
      .dot {
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: var(--accent);
        box-shadow: 0 0 18px rgba(25,240,194,.9);
      }
      .grid, .highlight-grid, .spotlight-grid {
        display: grid;
        gap: 16px;
        margin-bottom: 18px;
      }
      .grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .highlight-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .spotlight-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .actions-grid {
        display: grid;
        grid-template-columns: 1.05fr .95fr;
        gap: 18px;
        margin-bottom: 18px;
      }
      .layout {
        display: grid;
        grid-template-columns: 1.3fr 1fr;
        gap: 18px;
      }
      .card, .panel, .highlight, .spotlight-card {
        border: 1px solid var(--line);
        border-radius: 22px;
        box-shadow: var(--shadow);
      }
      .card, .panel {
        padding: 18px;
        background:
          linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.028)),
          var(--panel);
        backdrop-filter: blur(18px);
      }
      .card {
        position: relative;
        overflow: hidden;
      }
      .card::after {
        content: "";
        position: absolute;
        right: -26px;
        bottom: -70px;
        width: 170px;
        height: 170px;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(25,240,194,.18), transparent 70%);
      }
      .card .label {
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .08em;
      }
      .card .value {
        font-size: 31px;
        font-weight: 800;
        margin-top: 10px;
      }
      .highlight {
        padding: 18px;
        background:
          linear-gradient(135deg, rgba(70,183,255,.13), rgba(25,240,194,.08)),
          rgba(10,17,31,.92);
      }
      .highlight .tag {
        color: #bbddff;
        text-transform: uppercase;
        letter-spacing: .1em;
        font-size: 11px;
      }
      .highlight .big {
        margin-top: 10px;
        font-size: 28px;
        font-weight: 800;
      }
      .highlight .sub {
        margin-top: 8px;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.45;
      }
      .spotlight-card {
        padding: 18px;
        min-height: 176px;
        background:
          linear-gradient(135deg, rgba(255,211,79,.11), rgba(255,92,199,.08)),
          rgba(10,17,31,.93);
      }
      .finance-grid {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 16px;
      }
      .finance-card {
        position: relative;
        overflow: hidden;
        padding: 16px;
        min-height: 118px;
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,.13);
        background:
          radial-gradient(circle at 88% 8%, rgba(255,211,79,.15), transparent 36%),
          linear-gradient(160deg, rgba(255,255,255,.075), rgba(255,255,255,.025)),
          rgba(9,20,38,.86);
        box-shadow: 0 18px 54px rgba(0,0,0,.26);
      }
      .finance-card::after {
        content: "";
        position: absolute;
        right: -34px;
        bottom: -52px;
        width: 116px;
        height: 116px;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(33,247,196,.16), transparent 68%);
      }
      .finance-card .label {
        color: var(--muted);
        font-size: 11px;
        letter-spacing: .1em;
        text-transform: uppercase;
      }
      .finance-card .amount {
        position: relative;
        z-index: 1;
        margin-top: 10px;
        font-size: clamp(21px, 2vw, 31px);
        font-weight: 900;
        letter-spacing: -.04em;
      }
      .finance-card .note {
        position: relative;
        z-index: 1;
        margin-top: 7px;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.35;
      }
      .finance-card.good .amount { color: #b7fff1; }
      .finance-card.warn .amount { color: #ffe7aa; }
      .finance-card.hot .amount { color: #ffd0ef; }
      .ai-command-center {
        position: relative;
        overflow: hidden;
        margin-bottom: 18px;
        padding: 0;
        border-color: rgba(255,92,199,.26);
        background:
          radial-gradient(circle at 18% 18%, rgba(255,92,199,.18), transparent 28%),
          radial-gradient(circle at 82% 18%, rgba(33,247,196,.16), transparent 26%),
          linear-gradient(135deg, rgba(9,14,30,.92), rgba(7,20,35,.88));
      }
      .ai-command-center::before {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background:
          linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px),
          linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px);
        background-size: 34px 34px;
        opacity: .65;
      }
      .ai-command-inner {
        position: relative;
        z-index: 1;
        padding: 20px;
      }
      .ai-command-header {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: flex-start;
        margin-bottom: 16px;
      }
      .ai-command-title {
        display: flex;
        align-items: center;
        gap: 14px;
      }
      .ai-core-orb {
        width: 62px;
        height: 62px;
        border-radius: 22px;
        background:
          radial-gradient(circle at 32% 24%, #fff, transparent 13%),
          conic-gradient(from 180deg, #21f7c4, #42b7ff, #ff5cc7, #ffd34f, #21f7c4);
        box-shadow: 0 0 34px rgba(255,92,199,.30), inset 0 0 24px rgba(0,0,0,.22);
        animation: aiPulse 2.8s ease-in-out infinite;
      }
      .ai-command-title h2 {
        margin: 0;
        font-size: clamp(24px, 3vw, 38px);
        letter-spacing: -.055em;
      }
      .ai-command-title p {
        margin: 5px 0 0;
        color: var(--muted);
        line-height: 1.45;
      }
      .ai-live-clock {
        text-align: right;
        color: #d9f7ff;
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        font-size: 12px;
      }
      .ai-live-clock strong {
        display: block;
        font-size: 20px;
        color: #fff;
        margin-bottom: 4px;
      }
      .live-state {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
        padding: 8px 10px;
        border-radius: 999px;
        border: 1px solid rgba(33,247,196,.24);
        background: rgba(33,247,196,.10);
        color: #bffff4;
        text-transform: uppercase;
        letter-spacing: .08em;
        font-weight: 900;
      }
      .live-state::before {
        content: "";
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: #21f7c4;
        box-shadow: 0 0 16px rgba(33,247,196,.85);
        animation: aiPulse 1.4s ease-in-out infinite;
      }
      .live-state.warn {
        border-color: rgba(255,211,79,.32);
        background: rgba(255,211,79,.12);
        color: #ffe6a6;
      }
      .live-state.warn::before {
        background: #ffd34f;
        box-shadow: 0 0 16px rgba(255,211,79,.85);
      }
      .live-state.hot {
        border-color: rgba(255,92,199,.36);
        background: rgba(255,92,199,.13);
        color: #ffd4f2;
      }
      .live-state.hot::before {
        background: #ff5cc7;
        box-shadow: 0 0 16px rgba(255,92,199,.85);
      }
      .ai-matrix {
        display: grid;
        grid-template-columns: 1.2fr .8fr;
        gap: 14px;
      }
      .ai-market-screen {
        min-height: 360px;
        padding: 18px;
        border-radius: 24px;
        border: 1px solid rgba(255,255,255,.13);
        background:
          radial-gradient(circle at 30% 10%, rgba(33,247,196,.09), transparent 30%),
          linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.018)),
          rgba(2, 8, 18, .78);
        box-shadow: inset 0 0 60px rgba(33,247,196,.05);
      }
      .ai-chart-area {
        position: relative;
        min-height: 210px;
        margin: 12px 0 14px;
        overflow: hidden;
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,.10);
        background:
          linear-gradient(rgba(255,255,255,.055) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,.055) 1px, transparent 1px),
          radial-gradient(circle at 28% 72%, rgba(33,247,196,.18), transparent 20%),
          radial-gradient(circle at 78% 28%, rgba(255,92,199,.16), transparent 22%),
          rgba(0,0,0,.24);
        background-size: 34px 34px, 34px 34px, auto, auto, auto;
      }
      .ai-chart-line {
        position: absolute;
        left: 5%;
        right: 5%;
        top: 26%;
        height: 56%;
        clip-path: polygon(0 78%, 9% 63%, 17% 70%, 25% 42%, 34% 50%, 43% 31%, 54% 38%, 65% 20%, 75% 28%, 86% 12%, 100% 18%, 100% 100%, 0 100%);
        background: linear-gradient(90deg, rgba(33,247,196,.08), rgba(33,247,196,.55), rgba(255,92,199,.45));
        filter: drop-shadow(0 0 14px rgba(33,247,196,.45));
      }
      .ai-price-tag {
        position: absolute;
        right: 7%;
        top: 17%;
        padding: 8px 12px;
        border-radius: 12px;
        background: linear-gradient(135deg, #ff5cc7, #ffd34f);
        color: #170513;
        font-weight: 900;
        box-shadow: 0 0 26px rgba(255,92,199,.35);
      }
      .ai-scan-dots span {
        position: absolute;
        width: 7px;
        height: 7px;
        border-radius: 999px;
        background: #21f7c4;
        box-shadow: 0 0 18px rgba(33,247,196,.9);
        animation: scanFloat 4s ease-in-out infinite;
      }
      .ai-scan-dots span:nth-child(1) { left: 18%; top: 72%; animation-delay: .1s; }
      .ai-scan-dots span:nth-child(2) { left: 41%; top: 45%; background: #ff5cc7; animation-delay: .9s; }
      .ai-scan-dots span:nth-child(3) { left: 68%; top: 31%; animation-delay: 1.5s; }
      .ai-scan-dots span:nth-child(4) { left: 82%; top: 58%; background: #ffd34f; animation-delay: 2.1s; }
      .ai-thought-feed {
        display: grid;
        gap: 10px;
      }
      .ai-thought {
        padding: 12px 13px;
        border-radius: 16px;
        background: rgba(255,255,255,.045);
        border: 1px solid rgba(255,255,255,.10);
      }
      .ai-thought strong {
        display: block;
        margin-bottom: 5px;
      }
      .ai-thought span {
        color: var(--muted);
        font-size: 13px;
        line-height: 1.45;
      }
      .ai-side-panel {
        display: grid;
        gap: 14px;
      }
      .ai-stat-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .ai-stat {
        padding: 14px;
        border-radius: 18px;
        background: rgba(255,255,255,.055);
        border: 1px solid rgba(255,255,255,.12);
      }
      .ai-stat .label {
        color: var(--muted);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: .10em;
      }
      .ai-stat .value {
        margin-top: 8px;
        font-size: 24px;
        font-weight: 900;
        letter-spacing: -.04em;
      }
      .ai-list {
        display: grid;
        gap: 8px;
      }
      .ai-list-item {
        padding: 10px 12px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,.10);
        background: rgba(255,255,255,.04);
        color: #dcecff;
        font-size: 13px;
        line-height: 1.45;
      }
      .entry-radar {
        position: relative;
        overflow: hidden;
        margin-top: 14px;
        padding: 16px;
        border-radius: 22px;
        border: 1px solid rgba(33,247,196,.22);
        background:
          radial-gradient(circle at 10% 18%, rgba(33,247,196,.18), transparent 28%),
          radial-gradient(circle at 92% 12%, rgba(255,92,199,.18), transparent 24%),
          linear-gradient(145deg, rgba(255,255,255,.075), rgba(255,255,255,.025)),
          rgba(2, 10, 20, .72);
        box-shadow: inset 0 0 48px rgba(33,247,196,.05), 0 20px 70px rgba(0,0,0,.24);
      }
      .entry-radar::before {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background:
          linear-gradient(115deg, transparent 0 36%, rgba(33,247,196,.13) 46%, transparent 56%),
          repeating-linear-gradient(90deg, rgba(255,255,255,.035) 0 1px, transparent 1px 42px);
        background-size: 180% 100%, auto;
        animation: entryScan 4.6s linear infinite;
        opacity: .65;
      }
      .entry-radar > * {
        position: relative;
        z-index: 1;
      }
      .entry-radar-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 14px;
        margin-bottom: 14px;
      }
      .entry-radar h3 {
        margin: 0;
        font-size: 19px;
        letter-spacing: -.03em;
      }
      .entry-radar p {
        margin: 5px 0 0;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.45;
      }
      .entry-score {
        min-width: 150px;
        padding: 12px;
        border-radius: 18px;
        border: 1px solid rgba(255,255,255,.14);
        background: rgba(255,255,255,.055);
      }
      .entry-score strong {
        display: block;
        font-size: 29px;
        line-height: 1;
        letter-spacing: -.05em;
      }
      .entry-score span {
        display: block;
        margin-top: 5px;
        color: var(--muted);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: .10em;
      }
      .entry-progress {
        position: relative;
        overflow: hidden;
        width: 100%;
        height: 11px;
        margin: 12px 0;
        border-radius: 999px;
        background: rgba(255,255,255,.08);
        border: 1px solid rgba(255,255,255,.12);
      }
      .entry-progress span {
        display: block;
        height: 100%;
        width: 0%;
        border-radius: inherit;
        background: linear-gradient(90deg, #21f7c4, #42b7ff 52%, #ff5cc7);
        box-shadow: 0 0 22px rgba(33,247,196,.42);
        transition: width .7s cubic-bezier(.2,.9,.2,1);
      }
      .entry-radar-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
      }
      .entry-column {
        min-height: 160px;
        padding: 12px;
        border-radius: 18px;
        border: 1px solid rgba(255,255,255,.12);
        background: rgba(255,255,255,.04);
      }
      .entry-column h4 {
        margin: 0 0 10px;
        color: #dcecff;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .10em;
      }
      .entry-signal-list {
        display: grid;
        gap: 8px;
      }
      .entry-signal-item {
        position: relative;
        padding: 10px 11px 10px 34px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,.10);
        background: rgba(255,255,255,.045);
        color: #dcecff;
        font-size: 12px;
        line-height: 1.38;
      }
      .entry-signal-item::before {
        content: "";
        position: absolute;
        left: 11px;
        top: 12px;
        width: 11px;
        height: 11px;
        border-radius: 999px;
        background: #42b7ff;
        box-shadow: 0 0 16px rgba(66,183,255,.7);
      }
      .entry-signal-item.confirmed {
        border-color: rgba(33,247,196,.24);
        background: rgba(33,247,196,.075);
      }
      .entry-signal-item.confirmed::before {
        background: #21f7c4;
        box-shadow: 0 0 18px rgba(33,247,196,.85);
      }
      .entry-signal-item.active {
        border-color: rgba(255,211,79,.27);
        background: rgba(255,211,79,.075);
      }
      .entry-signal-item.active::before {
        background: #ffd34f;
        box-shadow: 0 0 18px rgba(255,211,79,.75);
        animation: alertPulse 1.55s ease-in-out infinite;
      }
      .entry-signal-item.missing {
        border-color: rgba(255,92,199,.24);
        background: rgba(255,92,199,.065);
      }
      .entry-signal-item.missing::before {
        background: #ff5cc7;
        box-shadow: 0 0 18px rgba(255,92,199,.75);
      }
      .entry-radar-footer {
        margin-top: 12px;
        padding: 11px 12px;
        border-radius: 16px;
        border: 1px solid rgba(255,255,255,.10);
        background: rgba(0,0,0,.16);
        color: #cfe1f7;
        font-size: 13px;
        line-height: 1.45;
      }
      .control-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        margin-top: 14px;
      }
      .control-card {
        position: relative;
        overflow: hidden;
        min-height: 132px;
        padding: 14px;
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,.12);
        background:
          radial-gradient(circle at 18% 15%, rgba(66,183,255,.16), transparent 26%),
          linear-gradient(150deg, rgba(255,255,255,.065), rgba(255,255,255,.025));
      }
      .control-card::after {
        content: "";
        position: absolute;
        inset: auto -20% -35% 30%;
        height: 70px;
        background: linear-gradient(90deg, transparent, rgba(33,247,196,.18), transparent);
        transform: rotate(-8deg);
        animation: entryScan 5.2s linear infinite;
      }
      .control-card h4 {
        position: relative;
        z-index: 1;
        margin: 0 0 10px;
        color: #dcecff;
        font-size: 12px;
        letter-spacing: .11em;
        text-transform: uppercase;
      }
      .control-items {
        position: relative;
        z-index: 1;
        display: grid;
        gap: 8px;
      }
      .session-chip,
      .asset-row,
      .blocker-row {
        padding: 9px 10px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,.11);
        background: rgba(0,0,0,.14);
        color: #dcecff;
        font-size: 12px;
        line-height: 1.35;
      }
      .session-chip.active,
      .asset-row.execute {
        border-color: rgba(33,247,196,.32);
        background: rgba(33,247,196,.09);
        box-shadow: 0 0 22px rgba(33,247,196,.08);
      }
      .asset-row.block,
      .blocker-row {
        border-color: rgba(255,92,199,.25);
        background: rgba(255,92,199,.07);
      }
      .asset-row.watch,
      .asset-row.prepare,
      .asset-row.triggered {
        border-color: rgba(255,211,79,.25);
        background: rgba(255,211,79,.07);
      }
      .control-mini {
        display: block;
        margin-top: 4px;
        color: var(--muted);
        font-size: 11px;
      }
      .ai-learning-radar {
        display: grid;
        grid-template-columns: 150px 1fr;
        gap: 14px;
        align-items: center;
      }
      .radar {
        position: relative;
        width: 150px;
        height: 150px;
        border-radius: 999px;
        border: 1px solid rgba(33,247,196,.25);
        background:
          radial-gradient(circle, rgba(33,247,196,.18) 1px, transparent 2px),
          radial-gradient(circle, transparent 36%, rgba(33,247,196,.07) 37%, transparent 39%),
          radial-gradient(circle, transparent 60%, rgba(255,92,199,.07) 61%, transparent 63%),
          rgba(0,0,0,.16);
        background-size: 18px 18px, auto, auto, auto;
      }
      .radar::after {
        content: "";
        position: absolute;
        inset: 50% 50% 0 50%;
        width: 72px;
        height: 1px;
        transform-origin: left center;
        background: linear-gradient(90deg, #21f7c4, transparent);
        animation: radarSweep 2.6s linear infinite;
      }
      @keyframes aiPulse {
        0%, 100% { transform: scale(1); filter: saturate(1); }
        50% { transform: scale(1.05); filter: saturate(1.35); }
      }
      @keyframes scanFloat {
        0%, 100% { transform: translateY(0); opacity: .65; }
        50% { transform: translateY(-12px); opacity: 1; }
      }
      @keyframes radarSweep {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }
      @keyframes entryScan {
        from { background-position: 180% 0, 0 0; }
        to { background-position: -180% 0, 42px 0; }
      }
      .section-intro {
        display: flex;
        justify-content: space-between;
        align-items: end;
        gap: 16px;
        margin-bottom: 14px;
      }
      .section-intro p {
        margin: 0;
        color: var(--muted);
        max-width: 760px;
        line-height: 1.5;
        font-size: 13px;
      }
      .spotlight-card h3 {
        margin: 0 0 8px 0;
        font-size: 18px;
      }
      .spotlight-card p {
        margin: 0;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.5;
      }
      .spotlight-metric {
        margin-top: 15px;
        font-size: 27px;
        font-weight: 800;
      }
      .workspace-nav {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        margin: 2px 0 18px;
        padding: 12px;
        border-radius: 22px;
        border: 1px solid rgba(255,255,255,.13);
        background: rgba(4, 10, 22, .62);
        backdrop-filter: blur(16px);
        box-shadow: 0 18px 58px rgba(0,0,0,.26);
      }
      .workspace-tabs {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      .workspace-tab {
        border: 1px solid rgba(255,255,255,.12);
        box-shadow: none;
        background: rgba(255,255,255,.045);
        color: #dcecff;
      }
      .workspace-tab.active {
        background: linear-gradient(135deg, #21f7c4, #42b7ff);
        color: #041117;
        border-color: transparent;
        box-shadow: 0 14px 38px rgba(33,247,196,.18);
      }
      .workspace-hint {
        color: var(--muted);
        font-size: 12px;
        max-width: 420px;
        line-height: 1.45;
      }
      .view-section:not(.active-view) {
        display: none !important;
      }
      .chips {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 14px;
      }
      .panel h2 {
        margin: 0 0 14px 0;
        font-size: 18px;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
      }
      th, td {
        text-align: left;
        padding: 10px 8px;
        border-bottom: 1px solid var(--line);
        vertical-align: top;
      }
      th {
        color: var(--muted);
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .06em;
      }
      .mono {
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        font-size: 12px;
        word-break: break-word;
      }
      .pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 7px;
        min-height: 32px;
        padding: 7px 12px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 800;
        letter-spacing: -.01em;
        background:
          linear-gradient(135deg, rgba(33,247,196,.24), rgba(66,183,255,.14)),
          rgba(8, 33, 45, .78);
        color: #b7fff1;
        border: 1px solid rgba(33,247,196,.42);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 10px 28px rgba(33,247,196,.10);
      }
      .pill.warn {
        background:
          linear-gradient(135deg, rgba(255,211,79,.30), rgba(255,138,61,.14)),
          rgba(51, 40, 15, .80);
        color: #ffe7aa;
        border-color: rgba(255,211,79,.48);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 10px 28px rgba(255,211,79,.10);
      }
      .pill.hot {
        background:
          linear-gradient(135deg, rgba(255,92,199,.30), rgba(142,92,255,.18)),
          rgba(48, 20, 61, .82);
        color: #ffd0ef;
        border-color: rgba(255,92,199,.48);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 10px 28px rgba(255,92,199,.12);
      }
      .list { display: grid; gap: 12px; }
      .row {
        padding: 14px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: var(--panel-2);
      }
      .row strong { display: block; margin-bottom: 6px; }
      .row span { color: var(--muted); font-size: 13px; line-height: 1.5; }
      .form-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
      }
      .field { display: grid; gap: 6px; }
      .field label {
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .06em;
      }
      .field input, .field select {
        width: 100%;
        padding: 12px 13px;
        border-radius: 14px;
        border: 1px solid var(--line);
        background: rgba(255,255,255,.05);
        color: var(--text);
        outline: none;
      }
      .field input::placeholder { color: #6d8097; }
      .field input:focus, .field select:focus {
        border-color: rgba(70,183,255,.5);
        box-shadow: 0 0 0 4px rgba(70,183,255,.10);
      }
      .button-row {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 14px;
      }
      button {
        position: relative;
        overflow: hidden;
        border: 0;
        border-radius: 16px;
        padding: 13px 18px;
        background: linear-gradient(135deg, #19f0c2, #35a5ff);
        color: #041117;
        font-weight: 800;
        cursor: pointer;
        box-shadow: 0 14px 38px rgba(33,247,196,.18);
        transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease, filter .18s ease;
      }
      button::after {
        content: "";
        position: absolute;
        inset: -40% auto -40% -70%;
        width: 42%;
        transform: rotate(18deg);
        background: linear-gradient(90deg, transparent, rgba(255,255,255,.46), transparent);
        opacity: 0;
        transition: opacity .18s ease;
      }
      button:hover {
        transform: translateY(-2px);
        box-shadow: 0 18px 46px rgba(66,183,255,.24);
        filter: saturate(1.08);
      }
      button:hover::after {
        opacity: 1;
        animation: buttonShine .85s ease forwards;
      }
      button.secondary {
        background:
          linear-gradient(135deg, rgba(255,255,255,.14), rgba(66,183,255,.10)),
          rgba(18, 29, 49, .86);
        color: var(--text);
        border: 1px solid rgba(190,225,255,.24);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.10), 0 12px 30px rgba(0,0,0,.18);
      }
      .button-row a { display: inline-flex; }
      .cta-hot button {
        background: linear-gradient(135deg, #ffd34f, #ff8a3d);
        color: #120c03;
        box-shadow: 0 18px 48px rgba(255,138,61,.22);
      }
      .cta-ghost button {
        background:
          linear-gradient(135deg, rgba(255,255,255,.18), rgba(66,183,255,.12)),
          rgba(20, 31, 52, .90);
        color: var(--text);
        border: 1px solid rgba(255,255,255,.28);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 16px 42px rgba(0,0,0,.20);
      }
      .console {
        min-height: 240px;
        margin-top: 12px;
        padding: 14px;
        border-radius: 16px;
        background: #091018;
        border: 1px solid var(--line);
        color: #d6e6f8;
        overflow: auto;
        white-space: pre-wrap;
      }
      .detail-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 14px;
      }
      .detail-box {
        padding: 14px;
        border-radius: 16px;
        background: rgba(255,255,255,.03);
        border: 1px solid var(--line);
      }
      .detail-box h3 {
        margin: 0 0 10px 0;
        font-size: 15px;
      }
      .detail-box p {
        margin: 0;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.5;
      }
      .stack {
        display: grid;
        gap: 10px;
      }
      .footer {
        margin-top: 18px;
        color: var(--muted);
        font-size: 13px;
      }
      .landing-hero {
        display: grid;
        grid-template-columns: minmax(0, 1.08fr) minmax(360px, .92fr);
        gap: 22px;
        margin-bottom: 22px;
        align-items: stretch;
      }
      .landing-title {
        font-size: clamp(42px, 6vw, 86px);
        line-height: .88;
        margin: 0;
        letter-spacing: -.075em;
        max-width: 950px;
      }
      .landing-lead {
        color: var(--muted);
        font-size: 17px;
        line-height: 1.7;
        max-width: 760px;
      }
      .landing-copy {
        position: relative;
        overflow: hidden;
        min-height: 560px;
        padding: clamp(26px, 4vw, 48px);
        background:
          radial-gradient(circle at 78% 14%, rgba(255,211,79,.18), transparent 24%),
          radial-gradient(circle at 15% 80%, rgba(33,247,196,.18), transparent 26%),
          linear-gradient(145deg, rgba(255,255,255,.105), rgba(255,255,255,.030)),
          rgba(8,15,29,.76);
      }
      .landing-copy::after {
        content: "";
        position: absolute;
        right: -90px;
        top: -80px;
        width: 260px;
        height: 260px;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(255,92,199,.28), transparent 68%);
        filter: blur(4px);
      }
      .trust-row {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 26px;
      }
      .trust-item {
        padding: 13px;
        border-radius: 18px;
        border: 1px solid rgba(255,255,255,.12);
        background: rgba(255,255,255,.045);
      }
      .trust-item strong {
        display: block;
        font-size: 18px;
      }
      .trust-item span {
        display: block;
        margin-top: 5px;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.35;
      }
      .hero-visual {
        position: relative;
        overflow: hidden;
        min-height: 560px;
        padding: 22px;
        background:
          radial-gradient(circle at 50% 38%, rgba(33,247,196,.18), transparent 34%),
          linear-gradient(160deg, rgba(8,19,36,.95), rgba(13,24,44,.72));
      }
      .hero-visual::before {
        content: "";
        position: absolute;
        inset: 0;
        background:
          linear-gradient(90deg, transparent, rgba(33,247,196,.12), transparent),
          linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px);
        background-size: 220px 100%, 34px 34px, 34px 34px;
        opacity: .58;
        animation: heroScan 5.8s linear infinite;
      }
      .hero-visual::after {
        content: "";
        position: absolute;
        width: 10px;
        height: 10px;
        left: 18%;
        top: 18%;
        border-radius: 999px;
        background: #21f7c4;
        box-shadow:
          70px 52px 0 rgba(255,92,199,.92),
          210px 22px 0 rgba(255,211,79,.85),
          320px 160px 0 rgba(66,183,255,.88),
          118px 240px 0 rgba(33,247,196,.76),
          390px 300px 0 rgba(255,92,199,.62);
        filter: drop-shadow(0 0 14px rgba(33,247,196,.8));
        animation: particleDrift 6.4s ease-in-out infinite alternate;
      }
      .market-orb {
        position: absolute;
        inset: 54px 54px auto auto;
        width: 250px;
        height: 250px;
        border-radius: 999px;
        background:
          conic-gradient(from 220deg, var(--accent), var(--accent-3), var(--accent-4), var(--accent-2), var(--accent));
        opacity: .84;
        filter: drop-shadow(0 0 46px rgba(33,247,196,.20));
        animation: orbSpinFloat 14s linear infinite;
      }
      .market-orb::after {
        content: "";
        position: absolute;
        inset: 15px;
        border-radius: inherit;
        background: #071323;
        box-shadow: inset 0 0 44px rgba(255,255,255,.08);
      }
      .terminal-card {
        position: relative;
        z-index: 1;
        margin-top: 250px;
        padding: 18px;
        border-radius: 22px;
        border: 1px solid rgba(255,255,255,.15);
        background: rgba(3,10,20,.74);
        backdrop-filter: blur(16px);
        animation: terminalFloat 4.8s ease-in-out infinite;
      }
      .terminal-top {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .09em;
      }
      .signal-line {
        height: 92px;
        margin: 18px 0;
        border-radius: 16px;
        background:
          linear-gradient(90deg, transparent 0 8%, rgba(33,247,196,.8) 8% 9%, transparent 9% 18%, rgba(66,183,255,.9) 18% 20%, transparent 20% 31%, rgba(255,211,79,.85) 31% 32%, transparent 32% 42%, rgba(33,247,196,.9) 42% 44%, transparent 44% 53%, rgba(255,92,199,.85) 53% 55%, transparent 55% 66%, rgba(66,183,255,.85) 66% 69%, transparent 69% 82%, rgba(33,247,196,.9) 82% 84%, transparent 84%),
          repeating-linear-gradient(0deg, rgba(255,255,255,.05) 0 1px, transparent 1px 18px),
          linear-gradient(180deg, rgba(66,183,255,.11), rgba(33,247,196,.05));
        background-size: 160% 100%, 100% 100%, 100% 100%;
        animation: signalFlow 3.6s linear infinite;
      }
      .metric-stack {
        display: grid;
        gap: 10px;
      }
      .metric-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        padding: 11px 12px;
        border-radius: 14px;
        background: rgba(255,255,255,.05);
        color: var(--muted);
        font-size: 13px;
      }
      .metric-row strong { color: var(--text); }
      .feature-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
        margin-bottom: 18px;
      }
      .feature-card {
        position: relative;
        overflow: hidden;
        min-height: 212px;
        padding: 22px;
        border-radius: 24px;
        border: 1px solid var(--line);
        background:
          linear-gradient(160deg, rgba(255,255,255,.07), rgba(255,255,255,.025)),
          rgba(8,18,34,.82);
        box-shadow: var(--shadow);
      }
      .feature-card::before {
        content: "";
        position: absolute;
        right: -52px;
        top: -52px;
        width: 150px;
        height: 150px;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(66,183,255,.22), transparent 68%);
      }
      .feature-card .icon {
        width: 48px;
        height: 48px;
        display: grid;
        place-items: center;
        border-radius: 16px;
        background: rgba(33,247,196,.12);
        border: 1px solid rgba(33,247,196,.20);
        color: #b7fff1;
        font-weight: 900;
      }
      .feature-card h3 {
        margin: 18px 0 8px;
        font-size: 21px;
      }
      .feature-card p {
        margin: 0;
        color: var(--muted);
        line-height: 1.58;
        font-size: 14px;
      }
      .section-title {
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 18px;
        margin: 26px 0 14px;
      }
      .section-title h2 {
        margin: 0;
        font-size: clamp(26px, 3vw, 40px);
        letter-spacing: -.05em;
      }
      .section-title p {
        margin: 0;
        color: var(--muted);
        max-width: 620px;
        line-height: 1.55;
      }
      .process-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
        margin-bottom: 18px;
      }
      .process-card {
        padding: 18px;
        border: 1px solid var(--line);
        border-radius: 22px;
        background: rgba(255,255,255,.04);
      }
      .process-card .step {
        color: var(--accent-2);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .11em;
      }
      .process-card h3 { margin: 10px 0 8px; }
      .process-card p {
        margin: 0;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.5;
      }
      .onboarding-panel {
        background:
          radial-gradient(circle at 8% 24%, rgba(255,211,79,.13), transparent 23%),
          radial-gradient(circle at 92% 74%, rgba(33,247,196,.13), transparent 24%),
          linear-gradient(145deg, rgba(255,255,255,.075), rgba(255,255,255,.025)),
          rgba(8,18,34,.86);
      }
      @keyframes slowSpin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }
      @keyframes buttonShine {
        from { left: -70%; }
        to { left: 130%; }
      }
      @keyframes heroScan {
        from { background-position: -220px 0, 0 0, 0 0; }
        to { background-position: 620px 0, 0 34px, 34px 0; }
      }
      @keyframes particleDrift {
        from { transform: translate3d(0, 0, 0) scale(1); opacity: .72; }
        to { transform: translate3d(18px, -16px, 0) scale(1.08); opacity: 1; }
      }
      @keyframes orbSpinFloat {
        0% { transform: translateY(0) rotate(0deg) scale(1); }
        50% { transform: translateY(-14px) rotate(180deg) scale(1.04); }
        100% { transform: translateY(0) rotate(360deg) scale(1); }
      }
      @keyframes terminalFloat {
        0%, 100% { transform: translateY(0); box-shadow: 0 24px 70px rgba(0,0,0,.26); }
        50% { transform: translateY(-10px); box-shadow: 0 34px 90px rgba(33,247,196,.10); }
      }
      @keyframes signalFlow {
        from { background-position: 0 0, 0 0, 0 0; }
        to { background-position: -160% 0, 0 0, 0 0; }
      }
      @keyframes alertPulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(255,61,95,.28), 0 14px 36px rgba(0,0,0,.18); }
        50% { box-shadow: 0 0 0 8px rgba(255,61,95,.10), 0 18px 46px rgba(255,61,95,.22); }
      }
      @keyframes ambientAurora {
        0% { transform: translate3d(-1%, -1%, 0) rotate(0deg) scale(1); }
        50% { transform: translate3d(1.5%, -2%, 0) rotate(4deg) scale(1.03); }
        100% { transform: translate3d(2%, 1%, 0) rotate(-3deg) scale(1.06); }
      }
      a { color: #9fd9ff; text-decoration: none; }
      .muted { color: var(--muted); }
      .hidden { display: none !important; }
      @media (max-width: 1100px) {
        .grid, .highlight-grid, .spotlight-grid, .layout, .actions-grid, .landing-hero, .feature-grid, .process-grid { grid-template-columns: 1fr 1fr; }
        .ai-matrix { grid-template-columns: 1fr; }
        .entry-radar-grid, .control-grid { grid-template-columns: 1fr; }
        .finance-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .landing-copy, .hero-visual { min-height: auto; }
        .terminal-card { margin-top: 210px; }
      }
      @media (max-width: 760px) {
        .shell { padding: 14px 14px 34px; }
        .topbar { position: static; align-items: flex-start; }
        .brand { min-width: 0; }
        .nav-actions { justify-content: flex-start; }
        .hero, .topbar, .grid, .highlight-grid, .spotlight-grid, .layout, .actions-grid, .form-grid, .detail-grid, .landing-hero, .feature-grid, .trust-row, .process-grid, .control-grid {
          grid-template-columns: 1fr;
          display: grid;
        }
        .finance-grid { grid-template-columns: 1fr; }
        .ai-command-header, .ai-learning-radar { display: grid; grid-template-columns: 1fr; }
        .ai-live-clock { text-align: left; }
        .ai-stat-grid { grid-template-columns: 1fr; }
        .workspace-nav { display: grid; }
        .workspace-hint { max-width: none; }
        .section-intro { display: grid; }
        .landing-copy { padding: 24px; }
        .market-orb { width: 190px; height: 190px; right: 24px; top: 34px; }
        .terminal-card { margin-top: 205px; }
        .section-title { display: grid; }
        .entry-radar-head { display: grid; }
        .entry-score { min-width: 0; }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">MX</div>
          <div>
            <strong>BOTEXTRATOR</strong>
            <span>AI Trading Service para MT5</span>
          </div>
        </div>
        <div class="nav-actions public-only">
          <button type="button" class="secondary" onclick="document.getElementById('login-panel').scrollIntoView({behavior:'smooth'})">Iniciar sesión</button>
          <button type="button" onclick="document.getElementById('register-panel').scrollIntoView({behavior:'smooth'})">Crear cuenta</button>
        </div>
        <div class="nav-actions app-only hidden">
          <div class="badge"><span class="dot"></span><span id="service-status">Conectando...</span></div>
          <button type="button" class="notification-button" id="notification-button" title="Notificaciones">🔔<span class="notification-count" id="notification-count">0</span></button>
          <button type="button" class="secondary" id="logout-button">Salir</button>
        </div>
      </header>

      <section class="landing-hero public-only">
        <div class="panel landing-copy">
          <div class="hero-kicker">Trading AI para cuentas MT5</div>
          <h2 class="landing-title">Un cerebro de mercado para operar con disciplina, datos y control.</h2>
          <p class="landing-lead">BOTEXTRATOR está diseñado para analizar XAUUSD y otros instrumentos con inteligencia multi-timeframe, conocimiento aprendido, control de riesgo y seguimiento en vivo. La meta no es adivinar el mercado: es esperar oportunidades razonables, medir su calidad y ejecutar solo cuando el contexto tiene sentido.</p>
          <div class="button-row">
            <button type="button" onclick="document.getElementById('register-panel').scrollIntoView({behavior:'smooth'})">Registrarte</button>
            <button type="button" class="secondary" onclick="document.getElementById('login-panel').scrollIntoView({behavior:'smooth'})">Iniciar sesión</button>
            <a class="cta-hot" href="https://one.exnessonelink.com/a/143x3jrak4" target="_blank" rel="noopener"><button type="button">Registrarse en Exness</button></a>
            <a class="cta-ghost" href="https://www.metatrader.com/en/download" target="_blank" rel="noopener"><button type="button">Descargar MetaTrader 5</button></a>
          </div>
          <div class="trust-row">
            <div class="trust-item"><strong>Demo first</strong><span>Validación controlada antes de escalar riesgo.</span></div>
            <div class="trust-item"><strong>MT5 ready</strong><span>Preparado para Exness y símbolos con sufijo como XAUUSDm.</span></div>
            <div class="trust-item"><strong>AI guarded</strong><span>WATCH, riesgo reducido y auditoría de decisión.</span></div>
          </div>
        </div>
        <div class="panel hero-visual">
          <div class="market-orb"></div>
          <div class="terminal-card">
            <div class="terminal-top"><span>MAXIMO Quant v4</span><span>Live Watch</span></div>
            <div class="signal-line"></div>
            <div class="metric-stack">
              <div class="metric-row"><span>Acción AI</span><strong>WATCH / PREPARE</strong></div>
              <div class="metric-row"><span>Riesgo permitido</span><strong>Reduced guarded</strong></div>
              <div class="metric-row"><span>Broker</span><strong>Exness MT5</strong></div>
              <div class="metric-row"><span>Knowledge brain</span><strong>Telegram + cursos + reglas</strong></div>
            </div>
          </div>
        </div>
      </section>

      <div class="section-title public-only">
        <h2>Hecho para convertir conocimiento en decisiones operativas.</h2>
        <p>El sistema combina aprendizaje, mapa de mercado, estrategia base, validación demo y filtros externos para actuar con estructura en vez de improvisación.</p>
      </div>

      <section class="feature-grid public-only">
        <article class="feature-card">
          <div class="icon">AI</div>
          <h3>Inteligencia especializada</h3>
          <p>Usa conocimiento extraído de Telegram, cursos, PDFs, reglas y playbooks para contextualizar cada oportunidad de mercado.</p>
        </article>
        <article class="feature-card">
          <div class="icon">MT5</div>
          <h3>Conexión broker controlada</h3>
          <p>Diseñado para cuentas Exness/MT5, con reconocimiento de símbolos como XAUUSDm y separación entre owner y clientes.</p>
        </article>
        <article class="feature-card">
          <div class="icon">RM</div>
          <h3>Riesgo con guardias</h3>
          <p>El bot prepara, observa, reduce riesgo o bloquea según calidad de señal, noticias, horario, spread y estado de cuenta.</p>
        </article>
      </section>

      <div class="section-title public-only">
        <h2>Cómo empieza un cliente</h2>
        <p>Un flujo simple: abrir broker, descargar MT5, registrarse, esperar aprobación y conectar cuenta para seguimiento.</p>
      </div>

      <section class="process-grid public-only">
        <div class="process-card"><div class="step">Paso 01</div><h3>Abre tu broker</h3><p>Usa el botón de registro para crear la cuenta bajo la línea correcta del servicio.</p></div>
        <div class="process-card"><div class="step">Paso 02</div><h3>Instala MT5</h3><p>Descarga MetaTrader 5 y prepara tu login/servidor de cuenta.</p></div>
        <div class="process-card"><div class="step">Paso 03</div><h3>Solicita acceso</h3><p>Regístrate en la plataforma y espera aprobación del administrador.</p></div>
        <div class="process-card"><div class="step">Paso 04</div><h3>Conecta y observa</h3><p>Al estar aprobado, podrás conectar tu cuenta y ver métricas/resultados.</p></div>
      </section>

      <section class="panel public-only onboarding-panel" style="margin-bottom:18px;">
        <h2>Antes de conectar tu cuenta</h2>
        <div class="detail-grid">
          <div class="detail-box stack">
            <h3>Registro del broker</h3>
            <p>Para usar este servicio, primero abre tu cuenta desde el enlace configurado. Así tu cuenta queda correctamente vinculada antes de conectarla al panel.</p>
            <div class="button-row">
              <a class="cta-hot" href="https://one.exnessonelink.com/a/143x3jrak4" target="_blank" rel="noopener"><button type="button">Registrarse en Exness</button></a>
              <a class="cta-ghost" href="https://www.metatrader.com/en/download" target="_blank" rel="noopener"><button type="button">Descargar MetaTrader 5</button></a>
            </div>
            <div class="chips">
              <span class="pill">Broker conectado</span>
              <span class="pill">MT5</span>
              <span class="pill warn">Usar antes del registro</span>
            </div>
          </div>
          <div class="detail-box stack">
            <h3>Después de registrarte</h3>
            <p>Cuando tengas tu cuenta MT5, entra con tu correo y contraseña, registra la cuenta y el sistema preparará símbolos, métricas y seguimiento operativo.</p>
            <div class="chips"><span class="pill">XAUUSDm ready</span><span class="pill">Demo controlado</span><span class="pill hot">Owner approval</span></div>
          </div>
        </div>
      </section>

      <section class="panel public-only onboarding-panel" id="register-panel" style="margin-bottom:18px;">
        <h2>Crear solicitud de acceso</h2>
        <div class="detail-grid">
          <div class="detail-box stack">
            <form id="public-register-form">
              <div class="form-grid">
                <div class="field">
                  <label>Correo</label>
                  <input name="email" type="email" placeholder="cliente@ejemplo.com" required autocomplete="email" />
                </div>
                <div class="field">
                  <label>Nombre</label>
                  <input name="display_name" placeholder="Tu nombre" required />
                </div>
                <div class="field">
                  <label>Contraseña</label>
                  <input name="password" type="password" placeholder="Mínimo 8 caracteres" required autocomplete="new-password" />
                </div>
                <div class="field">
                  <label>Zona horaria</label>
                  <input name="timezone_name" value="America/Santo_Domingo" />
                </div>
              </div>
              <div class="button-row">
                <button type="submit">Enviar solicitud</button>
              </div>
              <p id="public-register-output">Tus datos quedarán pendientes para aprobación del administrador.</p>
            </form>
          </div>
          <div class="detail-box stack">
            <h3>Acceso con control del owner</h3>
            <p>Tu usuario queda guardado como solicitud pendiente. El administrador revisa tus datos y activa tu acceso cuando estés autorizado para usar la app.</p>
            <div class="chips"><span class="pill warn">Pendiente</span><span class="pill">Datos privados</span><span class="pill">Panel cliente</span></div>
          </div>
        </div>
      </section>

      <section class="panel public-only onboarding-panel" id="login-panel" style="margin-bottom:18px;">
        <h2>Iniciar sesión</h2>
        <div class="detail-grid">
          <div class="detail-box stack">
            <div class="field">
              <label>Correo</label>
              <input id="login-email-input" type="email" placeholder="owner@botextrator.local" autocomplete="username" />
            </div>
            <div class="field">
              <label>Contraseña</label>
              <input id="login-password-input" type="password" placeholder="Tu contraseña" autocomplete="current-password" />
            </div>
            <div class="button-row">
              <button type="button" id="login-button">Entrar</button>
            </div>
            <div class="detail-box stack" style="margin-top:14px;">
              <h3>Recuperar contraseña</h3>
              <p>Si olvidaste tu contraseña, solicita recuperación. El owner recibirá una alerta segura para validar tu identidad y enviarte el token temporal.</p>
              <div class="button-row">
                <button type="button" class="secondary" id="forgot-password-button">Solicitar recuperación</button>
              </div>
              <div class="form-grid" style="margin-top:10px;">
                <div class="field">
                  <label>Token temporal</label>
                  <input id="reset-token-input" placeholder="rst_..." autocomplete="one-time-code" />
                </div>
                <div class="field">
                  <label>Nueva contraseña</label>
                  <input id="reset-password-input" type="password" placeholder="Mínimo 8 caracteres" autocomplete="new-password" />
                </div>
              </div>
              <div class="button-row">
                <button type="button" class="secondary" id="reset-password-button">Cambiar contraseña</button>
              </div>
              <p id="password-reset-output">Usa el mismo correo escrito arriba para solicitar o confirmar la recuperación.</p>
            </div>
          </div>
          <div class="detail-box stack">
            <h3>Sesión Actual</h3>
            <p id="auth-status-text">No autenticado todavía.</p>
            <div class="chips" id="auth-status-chips"></div>
          </div>
        </div>
      </section>

      <nav class="workspace-nav app-only hidden">
        <div class="workspace-tabs">
          <button type="button" class="workspace-tab active" data-view-target="ai">AI en vivo</button>
          <button type="button" class="workspace-tab" data-view-target="capital">Capital</button>
          <button type="button" class="workspace-tab" data-view-target="accounts">Cuentas</button>
          <button type="button" class="workspace-tab owner-only hidden" data-view-target="operations">Operación</button>
          <button type="button" class="workspace-tab owner-only hidden" data-view-target="admin">Admin</button>
        </div>
        <div class="workspace-hint" id="workspace-hint">Vista enfocada: el cerebro AI, sus confirmaciones y su estado de ejecución.</div>
      </nav>

      <section class="panel app-only owner-only view-section hidden" data-view="admin" style="margin-bottom:18px;">
        <div class="section-intro">
          <div>
            <div class="hero-kicker">AI Trading Control Center</div>
            <h2>Resumen General de Clientes y Servicio</h2>
            <p>Ventana compacta para ver usuarios, cuentas, agentes, deployments, actividad AI y el foco operativo sin cargar toda la pantalla inicial.</p>
          </div>
          <div class="chips"><span class="pill">Owner view</span><span class="pill">General</span><span class="pill warn">No visible para clientes</span></div>
        </div>

        <div class="grid">
          <div class="card"><div class="label">Usuarios</div><div class="value" id="count-users">0</div></div>
          <div class="card"><div class="label">Cuentas</div><div class="value" id="count-accounts">0</div></div>
          <div class="card"><div class="label">Agentes</div><div class="value" id="count-agents">0</div></div>
          <div class="card"><div class="label">Deployments</div><div class="value" id="count-deployments">0</div></div>
        </div>

        <div class="highlight-grid">
          <div class="highlight">
            <div class="tag">Agentes Online</div>
            <div class="big" id="highlight-online-agents">0</div>
            <div class="sub">Agentes con heartbeat vivo en la capa central.</div>
          </div>
          <div class="highlight">
            <div class="tag">Última Acción AI</div>
            <div class="big" id="highlight-last-ai-action">—</div>
            <div class="sub">Última salida táctica del motor AI registrada por el servicio.</div>
          </div>
          <div class="highlight">
            <div class="tag">Último Estado de Ejecución</div>
            <div class="big" id="highlight-last-execution-status">—</div>
            <div class="sub">Último resultado operativo centralizado desde un deployment.</div>
          </div>
          <div class="highlight">
            <div class="tag">Señales Detectadas</div>
            <div class="big" id="highlight-signal-runs">0</div>
            <div class="sub">Runs recientes donde apareció señal operativa confirmada.</div>
          </div>
        </div>

        <div class="spotlight-grid" style="margin-bottom:0;">
          <article class="spotlight-card">
            <h3>Cuenta Focus</h3>
            <p id="spotlight-account-text">Esperando actividad de cuentas conectadas.</p>
            <div class="spotlight-metric" id="spotlight-account-symbol">—</div>
            <div class="chips" id="spotlight-account-chips"></div>
          </article>
          <article class="spotlight-card">
            <h3>Actividad Operativa</h3>
            <p>Lectura compacta del pulso reciente del sistema centralizado.</p>
            <div class="spotlight-metric" id="spotlight-cycle-count">0 ciclos</div>
            <div class="chips" id="spotlight-activity-chips"></div>
          </article>
          <article class="spotlight-card">
            <h3>Motor Estratégico</h3>
            <p id="spotlight-strategy-text">Esperando estrategia activa.</p>
            <div class="spotlight-metric" id="spotlight-strategy-key">—</div>
            <div class="chips" id="spotlight-strategy-chips"></div>
          </article>
        </div>
      </section>

      <section class="panel app-only view-section hidden" data-view="admin" style="margin-bottom:18px;">
        <div class="section-intro">
          <div>
            <h2>Seguridad y Notificaciones</h2>
            <p>Campanita roja para accesos, solicitudes de recuperación, nuevas cuentas y eventos de dispositivo.</p>
          </div>
          <div class="chips" id="security-summary-chips"></div>
        </div>
        <div class="detail-grid">
          <div class="detail-box stack">
            <h3>Notificaciones recientes</h3>
            <div id="notification-list" class="stack"><p>Cargando notificaciones...</p></div>
          </div>
          <div class="detail-box stack">
            <h3>Accesos y dispositivos</h3>
            <div id="security-events-list" class="stack"><p>Cargando eventos de seguridad...</p></div>
          </div>
        </div>
      </section>

      <section class="panel ai-command-center app-only view-section active-view hidden" data-view="ai">
        <div class="ai-command-inner">
          <div class="ai-command-header">
            <div class="ai-command-title">
              <div class="ai-core-orb"></div>
              <div>
                <h2>AI Live Command Center</h2>
                <p>Vista viva del cerebro: qué patrón compara, qué está esperando y cómo protege la cuenta antes de ejecutar.</p>
              </div>
            </div>
            <div class="ai-live-clock">
              <strong id="ai-live-action">Cargando...</strong>
              <span id="ai-live-updated">Esperando primer ciclo</span>
              <span id="ai-live-runtime-state" class="live-state warn">sin ciclo</span>
            </div>
          </div>

          <div class="ai-matrix">
            <div class="ai-market-screen">
              <div class="chips" id="ai-live-chips"></div>
              <div class="ai-chart-area">
                <div class="ai-chart-line"></div>
                <div class="ai-price-tag" id="ai-live-side-tag">—</div>
                <div class="ai-scan-dots"><span></span><span></span><span></span><span></span></div>
              </div>
              <div class="ai-thought-feed">
                <div class="ai-thought"><strong>Lectura principal</strong><span id="ai-live-summary">Cargando razonamiento de la IA...</span></div>
                <div class="ai-thought"><strong>Movimiento probable</strong><span id="ai-live-probable-move">Esperando proyección aprendida...</span></div>
                <div class="ai-thought"><strong>Contexto externo / noticias</strong><span id="ai-live-external-context">Sincronizando calendario y riesgos externos...</span></div>
                <div class="ai-thought"><strong>Zona / precio vigilado</strong><span id="ai-live-price-zone">Calculando zona activa desde MT5...</span></div>
                <div class="ai-thought"><strong>Nivel de confirmación</strong><span id="ai-live-confirmation-price">Esperando nivel numérico...</span></div>
                <div class="ai-thought"><strong>Próxima confirmación</strong><span id="ai-live-next-confirmation">Esperando checklist...</span></div>
              </div>
              <div class="entry-radar" id="entry-signal-radar">
                <div class="entry-radar-head">
                  <div>
                    <h3>Radar de Entrada AI</h3>
                    <p id="entry-radar-focus">Leyendo señales, confirmaciones, faltantes y guardias antes de procesar entrada.</p>
                  </div>
                  <div class="entry-score">
                    <strong id="entry-readiness-percent">0%</strong>
                    <span id="entry-radar-status">preparando</span>
                  </div>
                </div>
                <div class="entry-progress"><span id="entry-readiness-bar"></span></div>
                <div class="entry-radar-grid">
                  <div class="entry-column">
                    <h4>Confirmado</h4>
                    <div class="entry-signal-list" id="entry-radar-confirmed">
                      <div class="entry-signal-item confirmed">Esperando primer ciclo AI...</div>
                    </div>
                  </div>
                  <div class="entry-column">
                    <h4>Activo ahora</h4>
                    <div class="entry-signal-list" id="entry-radar-active">
                      <div class="entry-signal-item active">Buscando zona viva...</div>
                    </div>
                  </div>
                  <div class="entry-column">
                    <h4>Falta para ejecutar</h4>
                    <div class="entry-signal-list" id="entry-radar-missing">
                      <div class="entry-signal-item missing">Esperando checklist...</div>
                    </div>
                  </div>
                </div>
                <div class="entry-radar-footer" id="entry-radar-footer">La orden solo debe pasar si aparece señal final, SL lógico, RR evaluable, macro/spread permitidos y risk binding válido.</div>
              </div>
              <div class="control-grid">
                <div class="control-card">
                  <h4>Sesiones RD</h4>
                  <div class="control-items" id="ai-session-windows">
                    <div class="session-chip">Cargando ventanas operativas...</div>
                  </div>
                </div>
                <div class="control-card">
                  <h4>Radar por activo</h4>
                  <div class="control-items" id="ai-asset-radar">
                    <div class="asset-row watch">Esperando latest_signal...</div>
                  </div>
                </div>
                <div class="control-card">
                  <h4>Bloqueos / gatillo</h4>
                  <div class="control-items" id="ai-blocker-radar">
                    <div class="blocker-row">Esperando razones del motor...</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="ai-side-panel">
              <div class="ai-stat-grid">
                <div class="ai-stat"><div class="label">Madurez</div><div class="value" id="ai-live-maturity">—</div></div>
                <div class="ai-stat"><div class="label">Confianza</div><div class="value" id="ai-live-confidence">—</div></div>
                <div class="ai-stat"><div class="label">Armonía</div><div class="value" id="ai-live-harmony">—</div></div>
                <div class="ai-stat"><div class="label">Prob. Execute</div><div class="value" id="ai-live-probability">—</div></div>
              </div>
              <div class="detail-box">
                <h3>Qué está esperando</h3>
                <div class="ai-list" id="ai-live-waiting-list"><div class="ai-list-item">Cargando condiciones...</div></div>
              </div>
              <div class="detail-box">
                <h3>Evidencia aprendida</h3>
                <div class="ai-list" id="ai-live-evidence-list"><div class="ai-list-item">Cargando evidencia...</div></div>
              </div>
            </div>
          </div>

          <div class="detail-grid" style="margin-top:14px;">
            <div class="detail-box">
              <h3>Aprendizaje continuo</h3>
              <div class="ai-learning-radar">
                <div class="radar"></div>
                <div>
                  <div class="chips" id="ai-learning-chips"></div>
                  <div class="ai-list" id="ai-learning-patterns" style="margin-top:10px;"></div>
                </div>
              </div>
            </div>
            <div class="detail-box">
              <h3>Seguridad de ejecución</h3>
              <div class="ai-list" id="ai-live-risk-list"><div class="ai-list-item">Cargando guardias...</div></div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel app-only view-section hidden" data-view="capital" style="margin-bottom:18px;">
        <div class="section-intro">
          <div>
            <h2 id="capital-section-title">Capital y Resultados</h2>
            <p id="capital-section-note">Métricas reportadas por MT5. El crecimiento aquí representa P/L flotante disponible en el terminal; rendimiento cerrado requiere histórico de operaciones.</p>
          </div>
          <div class="chips" id="capital-source-chips"></div>
        </div>
        <div class="finance-grid" id="portfolio-metrics-cards"></div>
        <table>
          <thead><tr><th>Cuenta</th><th class="owner-only hidden">Cliente</th><th>Balance</th><th>Equity</th><th>P/L flotante</th><th>Crecimiento</th><th>Margen libre</th><th>Actualizado</th></tr></thead>
          <tbody id="capital-accounts-body"><tr><td colspan="8">Esperando métricas de MT5...</td></tr></tbody>
        </table>
      </section>

      <section class="panel app-only owner-only view-section hidden" data-view="admin" style="margin-bottom:18px;">
        <h2>Readiness del Cerebro AI</h2>
        <div class="detail-grid">
          <div class="detail-box stack">
            <div class="row">
              <strong id="readiness-overall">Revisando...</strong>
              <span id="readiness-clearance">Esperando auditoría interna.</span>
            </div>
            <div class="chips" id="readiness-summary-chips"></div>
            <div id="readiness-critical-list" class="stack"></div>
          </div>
          <div class="detail-box stack">
            <h3>Artefactos de Readiness</h3>
            <div id="readiness-artifacts-list" class="stack">
              <p>Se cargarán estrategia, mapa de mercado, inteligencia, auditorías y reportes.</p>
            </div>
          </div>
        </div>
      </section>

      <section class="panel app-only client-only view-section hidden" data-view="accounts" style="margin-bottom:18px;">
        <h2>Conectar Broker Exness</h2>
        <div class="detail-grid">
          <div class="detail-box stack">
            <h3>Paso 1: abrir Exness con tu enlace</h3>
            <p>Para quedar correctamente bajo la línea del servicio, primero abre Exness desde el enlace de referido configurado por el owner.</p>
            <div class="button-row">
              <a id="exness-referral-link" href="#" target="_blank" rel="noopener"><button type="button">Abrir Exness</button></a>
            </div>
            <div class="chips" id="exness-referral-status"></div>
          </div>
          <div class="detail-box stack">
            <h3>Paso 2: registrar tu cuenta MT5</h3>
            <div class="row">
              <strong>Política de cuentas</strong>
              <span id="client-account-policy">Cargando cupo permitido...</span>
            </div>
            <form id="client-exness-form">
              <div class="form-grid">
                <div class="field">
                  <label>Acción</label>
                  <select name="replace_account_id" id="client-replace-account-select">
                    <option value="">Crear cuenta nueva si hay cupo</option>
                  </select>
                </div>
                <div class="field">
                  <label>Nombre de cuenta</label>
                  <input name="account_label" placeholder="Mi Exness Demo" required />
                </div>
                <div class="field">
                  <label>Servidor MT5</label>
                  <input name="broker_server" placeholder="Exness-MT5Trial11" />
                </div>
                <div class="field">
                  <label>Login / referencia</label>
                  <input name="login_reference" placeholder="197452102" />
                </div>
                <div class="field">
                  <label>Símbolo Exness</label>
                  <input name="symbol_suffix" value="XAUUSDm" placeholder="XAUUSDm o solo m" />
                </div>
              </div>
              <label class="field" style="margin-top:12px;">
                <span><input type="checkbox" name="referral_confirmed" /> Confirmo que abrí/registré Exness usando el enlace de referido.</span>
              </label>
              <div class="button-row">
                <button type="submit">Guardar cuenta Exness</button>
              </div>
            </form>
            <div class="stack" id="client-accounts-list">
              <p>Tus cuentas conectadas aparecerán aquí.</p>
            </div>
          </div>
          <div class="detail-box stack">
            <h3>Paso 3: mantener MT5 conectado</h3>
            <p>Para que la IA pueda ejecutar en una cuenta autorizada, el cliente debe tener MetaTrader 5 abierto con la cuenta correcta y un agente local/VPS activo. El agente no decide por sí solo: recibe la decisión de la IA, verifica demo/broker/símbolo/riesgo y solo ejecuta si todos los guardias pasan.</p>
            <div class="chips">
              <span class="pill">MT5 abierto</span>
              <span class="pill">Cuenta autorizada</span>
              <span class="pill">Agente online</span>
              <span class="pill warn">Demo primero</span>
            </div>
            <p class="muted">Cuando registres o cambies tu cuenta, el sistema crea las credenciales del agente. El owner puede validar el estado desde Cuentas y Operación antes de permitir ejecución real.</p>
          </div>
        </div>
      </section>

      <section class="actions-grid app-only owner-only view-section hidden" data-view="operations">
        <section class="panel">
          <h2>Operaciones Rápidas</h2>
          <form id="user-form">
            <div class="form-grid">
              <div class="field">
                <label>Email del usuario</label>
                <input name="email" placeholder="cliente@ejemplo.com" required />
              </div>
              <div class="field">
                <label>Nombre</label>
                <input name="display_name" placeholder="Cliente 1" required />
              </div>
              <div class="field">
                <label>Rol</label>
                <select name="role">
                  <option value="client">client</option>
                  <option value="operator">operator</option>
                  <option value="owner">owner</option>
                </select>
              </div>
              <div class="field">
                <label>Zona horaria</label>
                <input name="timezone_name" value="America/Santo_Domingo" />
              </div>
              <div class="field">
                <label>Cupo de cuentas</label>
                <input name="max_broker_accounts" type="number" min="1" value="1" />
              </div>
            </div>
            <div class="button-row">
              <button type="submit">Crear usuario</button>
            </div>
          </form>

          <form id="account-form" style="margin-top:16px;">
            <div class="form-grid">
              <div class="field">
                <label>Email owner</label>
                <input name="owner_email" placeholder="owner@ejemplo.com" required />
              </div>
              <div class="field">
                <label>Cuenta / label</label>
                <input name="account_label" placeholder="Exness Demo Principal" required />
              </div>
              <div class="field">
                <label>Broker</label>
                <input name="broker_name" value="Exness" />
              </div>
              <div class="field">
                <label>Sufijo símbolo</label>
                <input name="symbol_suffix" value="m" />
              </div>
            </div>
            <div class="button-row">
              <button type="submit">Conectar cuenta</button>
            </div>
          </form>

          <form id="agent-form" style="margin-top:16px;">
            <div class="form-grid">
              <div class="field">
                <label>Account ID</label>
                <input name="account_id" type="number" placeholder="1" required />
              </div>
              <div class="field">
                <label>Agent name</label>
                <input name="agent_name" placeholder="vps-exness-01" required />
              </div>
              <div class="field">
                <label>Host</label>
                <input name="host_name" placeholder="VPS-EXNESS-01" required />
              </div>
              <div class="field">
                <label>Broker name</label>
                <input name="broker_name" value="Exness" />
              </div>
            </div>
            <div class="button-row">
              <button type="submit">Registrar agente</button>
            </div>
          </form>
        </section>

        <section class="panel">
          <h2>Deploy y Consola</h2>
          <form id="deployment-form">
            <div class="form-grid">
              <div class="field">
                <label>Account ID</label>
                <input name="account_id" type="number" placeholder="1" required />
              </div>
              <div class="field">
                <label>Strategy key</label>
                <input name="strategy_key" value="MAXIMO_MTF_QUANT_INSTITUTIONAL_V4" />
              </div>
              <div class="field">
                <label>Variant</label>
                <input name="strategy_variant" value="v56_aggressive_filtered_b" />
              </div>
              <div class="field">
                <label>Operation mode</label>
                <select name="operation_mode">
                  <option value="ai_managed">ai_managed</option>
                  <option value="hybrid_guarded">hybrid_guarded</option>
                  <option value="signal_mirror">signal_mirror</option>
                </select>
              </div>
              <div class="field">
                <label>Risk mode</label>
                <select name="risk_mode">
                  <option value="reduced">reduced</option>
                  <option value="normal">normal</option>
                  <option value="blocked">blocked</option>
                </select>
              </div>
              <div class="field">
                <label>Learning mode</label>
                <input name="learning_mode" value="continuous" />
              </div>
            </div>
            <div class="button-row">
              <button type="submit">Crear / actualizar deploy</button>
              <button type="button" class="secondary" id="refresh-button">Actualizar panel</button>
            </div>
          </form>
          <div class="console mono" id="action-output">Consola lista. Aquí irán saliendo los resultados de bootstrap, usuarios, cuentas, agentes y deployments.</div>
        </section>
      </section>

      <section class="panel app-only owner-only view-section hidden" data-view="admin" style="margin-bottom:18px;">
        <h2>Solicitudes de Clientes</h2>
        <table>
          <thead><tr><th>ID</th><th>Cliente</th><th>Rol</th><th>Estado</th><th>Cupo cuentas</th><th>Acción</th></tr></thead>
          <tbody id="users-body"><tr><td colspan="6">Cargando usuarios...</td></tr></tbody>
        </table>
      </section>

      <section class="panel app-only view-section hidden" data-view="accounts" style="margin-bottom:18px;">
        <h2>Inspector de Cuenta</h2>
        <div class="detail-grid">
          <div class="detail-box stack">
            <div class="field">
              <label>Cuenta a inspeccionar</label>
              <select id="account-selector"></select>
            </div>
            <div id="account-detail-summary" class="stack">
              <p>Selecciona una cuenta para cargar su detalle operativo.</p>
            </div>
          </div>
          <div class="detail-box stack owner-only hidden">
            <h3>Controles de Deployment</h3>
            <div id="deployment-control-list" class="stack">
              <p>Todavía no hay deployments cargados para esta cuenta.</p>
            </div>
          </div>
        </div>
      </section>

      <div class="layout app-only view-section hidden" data-view="admin">
        <section class="panel">
          <h2>Vista General</h2>
          <div class="list" id="overview-list"></div>
        </section>

        <section class="panel">
          <h2>Estrategia Activa</h2>
          <div class="row">
            <strong id="best-strategy-name">Cargando...</strong>
            <span id="best-strategy-meta">Esperando datos...</span>
          </div>
          <div class="footer">
            Documentación API: <a href="/docs" target="_blank">/docs</a>
          </div>
        </section>
      </div>

      <div class="layout app-only view-section hidden" data-view="accounts" style="margin-top:18px;">
        <section class="panel">
          <h2>Cuentas Conectadas</h2>
          <table>
            <thead><tr><th>ID</th><th>Broker</th><th>Cuenta</th><th>Modo</th><th>Estado Live</th><th class="client-account-actions">Gestión Cliente</th></tr></thead>
            <tbody id="accounts-body"><tr><td colspan="6">Cargando...</td></tr></tbody>
          </table>
        </section>

        <section class="panel">
          <h2>Agentes MT5</h2>
          <table>
            <thead><tr><th>ID</th><th>Nombre</th><th>Host</th><th>Estado</th><th>Heartbeat</th></tr></thead>
            <tbody id="agents-body"><tr><td colspan="5">Cargando...</td></tr></tbody>
          </table>
        </section>
      </div>

      <div class="layout app-only view-section hidden" data-view="operations" style="margin-top:18px;">
        <section class="panel">
          <h2>Deployments</h2>
          <table>
            <thead><tr><th>Cuenta</th><th>Estrategia</th><th>Modo</th><th>Riesgo</th><th>Estado</th></tr></thead>
            <tbody id="deployments-body"><tr><td colspan="5">Cargando...</td></tr></tbody>
          </table>
        </section>

        <section class="panel owner-only hidden">
          <h2>Aprendizaje Continuo</h2>
          <table>
            <thead><tr><th>Fuente</th><th>Tipo</th><th>Sync</th><th>Modo</th><th>Estado</th></tr></thead>
            <tbody id="learning-body"><tr><td colspan="5">Cargando...</td></tr></tbody>
          </table>
        </section>
      </div>

      <div class="layout app-only view-section hidden" data-view="operations" style="margin-top:18px;">
        <section class="panel">
          <h2>Ciclos Recientes del Agente</h2>
          <table>
            <thead><tr><th>Hora</th><th>Agente</th><th>Símbolo</th><th>Estado</th><th>Terminal</th></tr></thead>
            <tbody id="runtime-body"><tr><td colspan="5">Cargando...</td></tr></tbody>
          </table>
        </section>

        <section class="panel">
          <h2>Resultados AI Recientes</h2>
          <table>
            <thead><tr><th>Hora</th><th>Estrategia</th><th>Modo</th><th>Run</th><th>AI</th></tr></thead>
            <tbody id="run-results-body"><tr><td colspan="5">Cargando...</td></tr></tbody>
          </table>
        </section>
      </div>

      <div class="footer" id="footer-note">Actualizando estado...</div>
    </div>

    <script>
      const fmtBool = (value) => value ? 'Demo' : 'Live';
      const fmtTime = (value) => value ? new Date(value).toLocaleString() : '—';
      const fmtMoney = (value, currency = 'USD') => {
        if (value === null || value === undefined || value === '') return '—';
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return '—';
        return `${numeric.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency || 'USD'}`;
      };
      const fmtPct = (value) => {
        if (value === null || value === undefined || value === '') return '—';
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return '—';
        return `${numeric.toFixed(2)}%`;
      };
      const output = () => document.getElementById('action-output');
      const authState = {
        token: localStorage.getItem('botextrator_api_token') || '',
        currentUser: null,
      };
      const workspaceState = {
        activeView: localStorage.getItem('botextrator_active_view') || 'ai',
      };
      const workspaceHints = {
        ai: 'Vista enfocada: el cerebro AI, sus confirmaciones y su estado de ejecución.',
        capital: 'Balance, equity, margen, crecimiento y resultados reportados por MT5.',
        accounts: 'Gestión de cuentas, broker Exness, símbolos, agentes e inspector operativo.',
        operations: 'Deployments, consola, ciclos recientes y resultados internos del motor AI.',
        admin: 'Aprobación de clientes, readiness, fuentes de aprendizaje y auditoría interna.',
      };

      function getDeviceFingerprint() {
        let fingerprint = localStorage.getItem('botextrator_device_fingerprint');
        if (!fingerprint) {
          fingerprint = `dev_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
          localStorage.setItem('botextrator_device_fingerprint', fingerprint);
        }
        return fingerprint;
      }

      function getDeviceLabel() {
        const ua = navigator.userAgent || '';
        const device = /Mobi|Android|iPhone|iPad/i.test(ua) ? 'teléfono/tablet' : 'computadora';
        return `${device} · ${navigator.platform || 'web'}`;
      }

      function pill(text, style = '') {
        return `<span class="pill${style ? ` ${style}` : ''}">${text}</span>`;
      }

      function safeText(value, fallback = '—') {
        return value === null || value === undefined || value === '' ? fallback : value;
      }

      function esc(value, fallback = '—') {
        return String(safeText(value, fallback))
          .replaceAll('&', '&amp;')
          .replaceAll('<', '&lt;')
          .replaceAll('>', '&gt;')
          .replaceAll('"', '&quot;')
          .replaceAll("'", '&#039;');
      }

      function setText(id, value, fallback = '—') {
        const node = document.getElementById(id);
        if (node) {
          node.textContent = safeText(value, fallback);
        }
      }

      function formatAge(seconds) {
        const numeric = Number(seconds);
        if (!Number.isFinite(numeric)) {
          return 'sin edad';
        }
        if (numeric < 60) {
          return `${Math.max(0, Math.round(numeric))}s`;
        }
        const minutes = Math.floor(numeric / 60);
        const rest = Math.round(numeric % 60);
        return `${minutes}m ${rest}s`;
      }

      function renderRuntimeState(brain) {
        const node = document.getElementById('ai-live-runtime-state');
        if (!node) {
          return;
        }
        const state = String(brain.runtime_state || 'missing').toLowerCase();
        const age = formatAge(brain.artifact_age_seconds);
        node.className = `live-state ${state === 'fresh' ? '' : (state === 'stale' ? 'warn' : 'hot')}`;
        node.textContent = state === 'fresh'
          ? `actualizando · ${age}`
          : (state === 'stale' ? `stale · ${age}` : 'sin señal viva');
      }

      function renderAiList(id, items, fallback) {
        const node = document.getElementById(id);
        if (!node) {
          return;
        }
        const cleanItems = (items || []).filter(Boolean).slice(0, 12);
        node.innerHTML = cleanItems.length
          ? cleanItems.map(item => `<div class="ai-list-item">${esc(item)}</div>`).join('')
          : `<div class="ai-list-item">${esc(fallback)}</div>`;
      }

      function asList(value) {
        if (Array.isArray(value)) {
          return value.filter(Boolean);
        }
        if (value === null || value === undefined || value === '') {
          return [];
        }
        return [value];
      }

      function uniqueSignals(items, limit = 8) {
        const seen = new Set();
        const clean = [];
        for (const item of items || []) {
          const text = String(safeText(item, '')).trim();
          if (!text || seen.has(text.toLowerCase())) {
            continue;
          }
          seen.add(text.toLowerCase());
          clean.push(text);
          if (clean.length >= limit) {
            break;
          }
        }
        return clean;
      }

      function checklistText(item) {
        if (typeof item === 'string') {
          return item;
        }
        if (!item || typeof item !== 'object') {
          return '';
        }
        return item.label || item.name || item.condition || item.key || item.reason || JSON.stringify(item);
      }

      function checklistPassed(item) {
        if (!item || typeof item !== 'object') {
          return false;
        }
        if (item.passed === true || item.met === true || item.ok === true) {
          return true;
        }
        const status = String(item.status || item.result || '').toLowerCase();
        return ['ok', 'pass', 'passed', 'true', 'confirmed', 'ready'].includes(status);
      }

      function number01(value) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) {
          return null;
        }
        return numeric > 1 ? Math.min(1, numeric / 100) : Math.max(0, Math.min(1, numeric));
      }

      function renderEntrySignalItems(id, items, kind, fallback) {
        const node = document.getElementById(id);
        if (!node) {
          return;
        }
        const clean = uniqueSignals(items, 7);
        node.innerHTML = clean.length
          ? clean.map(item => `<div class="entry-signal-item ${kind}">${esc(item)}</div>`).join('')
          : `<div class="entry-signal-item ${kind}">${esc(fallback)}</div>`;
      }

      function renderControlCenterTiles(executionGuard) {
        const sessionsNode = document.getElementById('ai-session-windows');
        const assetNode = document.getElementById('ai-asset-radar');
        const blockerNode = document.getElementById('ai-blocker-radar');
        const sessions = executionGuard.operational_sessions || [];
        const assets = executionGuard.asset_radar || [];
        const blockers = executionGuard.blocker_reasons || [];
        if (sessionsNode) {
          sessionsNode.innerHTML = sessions.length
            ? sessions.map(item => `
              <div class="session-chip ${item.active ? 'active' : ''}">
                <strong>${esc(item.label)} · ${esc(item.hours)}</strong>
                <span class="control-mini">${esc(item.active ? 'ACTIVA AHORA' : item.note)}</span>
              </div>
            `).join('')
            : '<div class="session-chip">Sin calendario de sesiones disponible.</div>';
        }
        if (assetNode) {
          assetNode.innerHTML = assets.length
            ? assets.map(item => {
                const status = String(item.status || 'watch').toLowerCase();
                return `
                  <div class="asset-row ${esc(status)}">
                    <strong>${esc(item.symbol)} · ${esc(item.side)} · ${esc(item.status)}</strong>
                    <span class="control-mini">Pulse ${esc(item.market_pulse)} · Final ${esc(item.final_confirmation)} · EQ ${esc(item.entry_quality)} · ER ${esc(item.execution_readiness)}</span>
                    <span class="control-mini">${esc(item.reason || `riesgo ${safeText(item.risk_mode)}`)}</span>
                  </div>
                `;
              }).join('')
            : '<div class="asset-row watch">Sin activo en radar todavía.</div>';
        }
        if (blockerNode) {
          const guardLines = [
            ...(blockers.length ? blockers : ['Sin bloqueo crítico reportado. Esperando gatillo limpio.']),
            `Sesión: ${safeText((executionGuard.session_analysis || {}).session)} · ${safeText((executionGuard.session_analysis || {}).status)}`,
            `Spread: ${safeText((executionGuard.execution_cost_analysis || {}).spread)} / P80 ${safeText((executionGuard.execution_cost_analysis || {}).spread_p80)} · ${safeText((executionGuard.execution_cost_analysis || {}).status)}`,
            `Premium/Discount: ${safeText((executionGuard.premium_discount_analysis || {}).status)} · posición ${safeText((executionGuard.premium_discount_analysis || {}).position_in_range)}`,
            `Umbral Q-learning: requiere ${safeText(executionGuard.required_execute_score)} · ${safeText(((executionGuard.dynamic_threshold_analysis || {}).reasons || []).join(', '))}`,
          ];
          blockerNode.innerHTML = uniqueSignals(guardLines, 8)
            .map(item => `<div class="blocker-row">${esc(item)}</div>`)
            .join('');
        }
      }

      function renderEntrySignalRadar(data) {
        const brain = data.brain || {};
        const market = data.market || {};
        const projection = data.pattern_projection || {};
        const reasoning = data.reasoning || {};
        const executionGuard = data.execution_guard || {};
        const priceContext = data.price_context || {};
        const watchZone = priceContext.watch_zone || {};
        const activeWatch = data.active_watch || {};
        const checklist = asList(reasoning.condition_checklist);
        const passedChecklist = checklist.filter(checklistPassed).map(checklistText);
        const pendingChecklist = checklist.filter(item => !checklistPassed(item)).map(checklistText);
        const metrics = [
          number01(reasoning.setup_maturity),
          number01(reasoning.confidence),
          number01(brain.harmony_score),
          number01(brain.watch_probability_to_execute),
          number01(executionGuard.final_confirmation_score),
          number01(executionGuard.entry_quality_score),
          number01(executionGuard.execution_readiness_score),
        ].filter(value => value !== null);
        const metricScore = metrics.length
          ? metrics.reduce((total, value) => total + value, 0) / metrics.length
          : null;
        const checklistScore = checklist.length ? passedChecklist.length / checklist.length : null;
        const readiness = Math.round(((metricScore ?? checklistScore ?? 0) * 0.7 + (checklistScore ?? metricScore ?? 0) * 0.3) * 100);
        const action = String(brain.action || '').toUpperCase();
        const recoveryPlan = reasoning.execution_recovery_plan || {};
        const blocked = action === 'BLOCKED' || brain.allowed_risk_mode === 'blocked' || market.macro_event_action === 'block';
        const radarStatus = blocked
          ? 'bloqueado'
          : readiness >= 80 ? 'casi ejecutable'
          : readiness >= 60 ? 'preparar reducido'
          : readiness >= 40 ? 'watch activo'
          : 'observando';

        const confirmed = [
          ...passedChecklist,
          ...(reasoning.signal_detected ? ['Señal final detectada por el motor AI'] : []),
          ...(market.macro_event_action === 'allow' ? ['Filtro macro permite operar'] : []),
          ...(priceContext.status === 'ready' ? [`Zona calculada en ${safeText(priceContext.reference_timeframe)} con precio ${safeText(priceContext.current_price)}`] : []),
          ...(brain.allowed_risk_mode && brain.allowed_risk_mode !== 'blocked' ? [`Riesgo habilitado en modo ${brain.allowed_risk_mode}`] : []),
          ...(projection.dominant_family ? [`Familia dominante: ${projection.dominant_family}`] : []),
        ];
        const active = [
          ...(action ? [`Acción actual del cerebro: ${action}`] : []),
          ...(market.candidate_side || market.preferred_side ? [`Lado vigilado: ${market.candidate_side || market.preferred_side}`] : []),
          ...(brain.watch_policy_action ? [`Política watch: ${brain.watch_policy_action}`] : []),
          ...(activeWatch.status ? [`Active watch: ${activeWatch.status} · ${safeText(activeWatch.progress)}`] : []),
          ...(recoveryPlan.status ? [`Plan profesional: ${safeText(recoveryPlan.status)}`] : []),
          ...(projection.confirmation_focus || []),
          ...(projection.pattern_matches || []),
          ...(watchZone.low || watchZone.high ? [`Zona viva: ${safeText(watchZone.low)} - ${safeText(watchZone.high)}`] : []),
          ...(priceContext.confirmation_price ? [`Nivel de gatillo observado: ${priceContext.confirmation_price}`] : []),
          ...(recoveryPlan.safe_retest_entry_reference ? [`Referencia de retest seguro: ${safeText(recoveryPlan.safe_retest_entry_reference)}`] : []),
        ];
        const missing = [
          ...pendingChecklist,
          ...(reasoning.waiting_for || []),
          ...(projection.missing_confirmations || []),
          ...(executionGuard.blocker_reasons || []),
          ...(!reasoning.signal_detected ? ['Confirmación final signal_detected = true'] : []),
          ...(recoveryPlan.required_conditions || []),
          ...(market.macro_event_action && market.macro_event_action !== 'allow' ? [`Macro/eventos debe cambiar a allow: ${market.macro_event_action}`] : []),
          ...(market.execution_viability && market.execution_viability !== 'SAFE' ? [`Ejecución debe estar SAFE: ${market.execution_viability}`] : []),
          ...(brain.allowed_risk_mode === 'blocked' ? ['Risk binding debe permitir reduced o normal'] : []),
        ];

        setText('entry-readiness-percent', `${Math.max(0, Math.min(100, readiness))}%`);
        setText('entry-radar-status', radarStatus);
        setText(
          'entry-radar-focus',
          `${safeText(market.candidate_side || market.preferred_side || priceContext.side, 'NEUTRAL')} · ${safeText(projection.operational_family || projection.dominant_family, 'familia pendiente')} · ${safeText(priceContext.confirmation_rule, 'esperando regla de confirmación')}`
        );
        const bar = document.getElementById('entry-readiness-bar');
        if (bar) {
          bar.style.width = `${Math.max(0, Math.min(100, readiness))}%`;
        }
        renderEntrySignalItems('entry-radar-confirmed', confirmed, 'confirmed', 'Todavía no hay confirmaciones fuertes registradas.');
        renderEntrySignalItems('entry-radar-active', active, 'active', 'La IA sigue observando hasta que aparezca una zona/trigger válido.');
        renderEntrySignalItems('entry-radar-missing', missing, 'missing', 'No falta nada crítico reportado; validar guardias de ejecución.');
        renderControlCenterTiles(executionGuard);
        setText(
          'entry-radar-footer',
          `Para ejecutar: señal final ${reasoning.signal_detected ? 'OK' : 'pendiente'} · final ${safeText(executionGuard.final_confirmation_score)} / requerido ${safeText(executionGuard.required_execute_score)} · acción ${safeText(brain.action)} · execution_status ${safeText(brain.execution_status)}.`
        );
      }

      function allowedWorkspaceViews() {
        if (!authState.currentUser) {
          return [];
        }
        return authState.currentUser.role === 'owner'
          ? ['ai', 'capital', 'accounts', 'operations', 'admin']
          : ['ai', 'capital', 'accounts'];
      }

      function switchWorkspaceView(view) {
        const allowed = allowedWorkspaceViews();
        const nextView = allowed.includes(view) ? view : (allowed[0] || 'ai');
        workspaceState.activeView = nextView;
        localStorage.setItem('botextrator_active_view', nextView);
        document.querySelectorAll('.view-section').forEach((item) => {
          item.classList.toggle('active-view', item.dataset.view === nextView);
        });
        document.querySelectorAll('.workspace-tab').forEach((item) => {
          const enabled = allowed.includes(item.dataset.viewTarget);
          item.classList.toggle('hidden', !enabled);
          item.classList.toggle('active', item.dataset.viewTarget === nextView);
        });
        const hint = document.getElementById('workspace-hint');
        if (hint) {
          hint.textContent = workspaceHints[nextView] || workspaceHints.ai;
        }
      }

      function authHeaders() {
        return authState.token ? { Authorization: `Bearer ${authState.token}` } : {};
      }

      function updateAuthUi() {
        const role = authState.currentUser ? authState.currentUser.role : null;
        const text = authState.currentUser
          ? `Autenticado como ${authState.currentUser.user_email} con rol ${authState.currentUser.role}.`
          : 'No autenticado todavía.';
        document.getElementById('auth-status-text').textContent = text;
        document.getElementById('auth-status-chips').innerHTML = authState.currentUser
          ? [pill(authState.currentUser.role), pill(`user ${authState.currentUser.user_id}`)].join('')
          : pill('login requerido', 'warn');
        document.querySelectorAll('.public-only').forEach((item) => item.classList.toggle('hidden', Boolean(authState.currentUser)));
        document.querySelectorAll('.app-only').forEach((item) => item.classList.toggle('hidden', !authState.currentUser));
        document.querySelectorAll('.owner-only').forEach((item) => item.classList.toggle('hidden', role !== 'owner'));
        document.querySelectorAll('.client-only').forEach((item) => item.classList.toggle('hidden', !authState.currentUser || role === 'owner'));
        switchWorkspaceView(workspaceState.activeView);
      }

      async function authenticatedFetch(url, options = {}) {
        const headers = {
          ...(options.headers || {}),
          ...authHeaders(),
        };
        return fetch(url, { ...options, headers });
      }

      async function loadNotificationCenter() {
        if (!authState.token) {
          return null;
        }
        const res = await authenticatedFetch('/api/platform/notifications');
        const data = await res.json();
        if (!res.ok) {
          return null;
        }
        renderNotificationCenter(data);
        return data;
      }

      function renderNotificationCenter(data) {
        const unread = data.unread_count || 0;
        const critical = data.critical_unread_count || 0;
        const button = document.getElementById('notification-button');
        const count = document.getElementById('notification-count');
        if (button && count) {
          count.textContent = unread;
          button.classList.toggle('alert', critical > 0);
        }
        const chips = document.getElementById('security-summary-chips');
        if (chips) {
          chips.innerHTML = [
            pill(`${unread} sin leer`, unread ? 'warn' : ''),
            pill(`${critical} críticas`, critical ? 'hot' : ''),
            pill(`${(data.recent_security_events || []).length} eventos`),
          ].join('');
        }
        const list = document.getElementById('notification-list');
        if (list) {
          const notifications = data.notifications || [];
          list.innerHTML = notifications.length ? notifications.slice(0, 12).map(item => `
            <div class="row">
              <strong>${pill(item.severity || 'info', item.severity === 'critical' ? 'hot' : item.severity === 'warning' ? 'warn' : '')} ${esc(item.title)}</strong>
              <span>${esc(item.message)}</span>
              <span class="mono">${esc(item.category)} · ${fmtTime(item.created_at)} ${item.is_read ? '· leído' : '· pendiente'}</span>
              ${item.is_read ? '' : `<div class="button-row" style="margin-top:8px;"><button type="button" class="secondary" onclick="window.markNotificationRead(${item.id})">Marcar leído</button></div>`}
            </div>
          `).join('') : '<p>No hay notificaciones todavía.</p>';
        }
        const events = document.getElementById('security-events-list');
        if (events) {
          const rows = data.recent_security_events || [];
          events.innerHTML = rows.length ? rows.slice(0, 12).map(item => `
            <div class="row">
              <strong>${esc(item.event_type)} · ${esc(item.status)}</strong>
              <span>${esc(item.email || 'usuario desconocido')} · ${esc(item.device_label || 'dispositivo no identificado')}</span>
              <span class="mono">${esc(item.ip_address || 'IP n/a')} · ${fmtTime(item.created_at)}</span>
            </div>
          `).join('') : '<p>No hay eventos de seguridad registrados.</p>';
        }
      }

      async function loginWithPassword(email, password) {
        const res = await fetch('/api/platform/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email,
            password,
            device_fingerprint: getDeviceFingerprint(),
            device_label: getDeviceLabel(),
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || JSON.stringify(data));
        }
        authState.token = data.token;
        authState.currentUser = data;
        localStorage.setItem('botextrator_api_token', data.token);
        updateAuthUi();
        await loadStatus();
        await loadNotificationCenter();
        return data;
      }

      async function loginWithToken(token) {
        const res = await fetch('/api/platform/auth/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || JSON.stringify(data));
        }
        authState.token = token;
        authState.currentUser = data;
        localStorage.setItem('botextrator_api_token', token);
        updateAuthUi();
        await loadStatus();
        await loadNotificationCenter();
        return data;
      }

      async function loadCurrentUser() {
        if (!authState.token) {
          authState.currentUser = null;
          updateAuthUi();
          return null;
        }
        const res = await authenticatedFetch('/api/platform/me');
        const data = await res.json();
        if (!res.ok) {
          authState.token = '';
          authState.currentUser = null;
          localStorage.removeItem('botextrator_api_token');
          updateAuthUi();
          throw new Error(data.detail || JSON.stringify(data));
        }
        authState.currentUser = data;
        updateAuthUi();
        return data;
      }

      async function postJson(url, payload) {
        const res = await authenticatedFetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || JSON.stringify(data));
        }
        output().textContent = JSON.stringify(data, null, 2);
        await loadStatus();
        return data;
      }

      async function loadAccountDetail(accountId) {
        if (!accountId) {
          return;
        }
        const res = await authenticatedFetch(`/api/platform/accounts/${accountId}`);
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || JSON.stringify(data));
        }

        const account = data.account || {};
        const owner = data.owner || {};
        const latestCycle = (data.recent_agent_cycles || [])[0];
        const latestRun = (data.recent_deployment_runs || [])[0];
        const agentConnection = data.agent_connection || {};
        const expected = agentConnection.expected || {};
        const actual = agentConnection.actual || {};
        const terminalValidation = agentConnection.terminal_validation || {};
        const commands = agentConnection.commands || {};
        const setupSteps = agentConnection.setup_steps || [];
        const terminalStyle = terminalValidation.status === 'ready'
          ? ''
          : (terminalValidation.status === 'account_mismatch' ? 'hot' : 'warn');

        document.getElementById('account-detail-summary').innerHTML = `
          <div class="row"><strong>${safeText(account.label)}</strong><span>${safeText(account.broker_name)} · ${safeText(account.platform_type)} · ${account.is_demo ? 'Demo' : 'Live'}</span></div>
          <div class="row"><strong>Owner</strong><span>${safeText(owner.display_name)} · ${safeText(owner.email)}</span></div>
          <div class="row"><strong>Último ciclo</strong><span>${latestCycle ? `${safeText(latestCycle.broker_symbol)} · ${safeText(latestCycle.cycle_status)} · ${fmtTime(latestCycle.created_at)}` : 'Sin ciclos recientes'}</span></div>
          <div class="row"><strong>Último resultado AI</strong><span>${latestRun ? `${safeText(latestRun.intelligence_action)} · ${safeText(latestRun.execution_status)} · ${fmtTime(latestRun.created_at)}` : 'Sin runs recientes'}</span></div>
          <div class="row">
            <strong>Conexión MT5 por cuenta</strong>
            <span>${pill(safeText(terminalValidation.status, 'waiting_for_agent'), terminalStyle)} ${safeText(terminalValidation.explanation)}</span>
          </div>
          <div class="row">
            <strong>Cuenta esperada</strong>
            <span>login ${safeText(expected.login_reference)} · servidor ${safeText(expected.broker_server)} · símbolo ${safeText(expected.broker_symbol)}</span>
          </div>
          <div class="row">
            <strong>MT5 reportando</strong>
            <span>login ${safeText(actual.login)} · servidor ${safeText(actual.server)} · equity ${safeText(actual.equity)} ${safeText(actual.currency, 'USD')} · ${fmtTime(actual.reported_at)}</span>
          </div>
          <div class="row">
            <strong>Riesgo por capital propio</strong>
            <span>Cada cuenta calcula su lote con su propio balance/equity reportado por MT5. Si el lote mínimo supera el límite de riesgo permitido, se bloquea hasta tener SL más corto o más capital.</span>
          </div>
          <div class="row">
            <strong>Comandos del agente</strong>
            <span>El agente debe correr en el PC/VPS donde MT5 esté abierto con esa misma cuenta.</span>
            <div class="button-row">
              <button type="button" class="secondary" onclick='navigator.clipboard.writeText(${JSON.stringify(commands.dry_run || '')})'>Copiar dry-run</button>
              <button type="button" class="secondary" onclick='navigator.clipboard.writeText(${JSON.stringify(commands.demo_execution || '')})'>Copiar demo real</button>
            </div>
            <div class="mono">${safeText(commands.dry_run, 'Sin comando disponible todavía.')}</div>
          </div>
          <div class="row">
            <strong>Pasos para cliente</strong>
            <span>${setupSteps.length ? setupSteps.map(item => `• ${safeText(item)}`).join('<br>') : 'Sin pasos pendientes.'}</span>
          </div>
        `;

        const controls = (data.deployments || []).length ? (data.deployments || []).map(item => `
          <div class="row">
            <strong>${item.strategy_key}</strong>
            <span>${safeText(item.strategy_variant)} · ${safeText(item.operation_mode)} · riesgo ${safeText(item.risk_mode)} · estado ${safeText(item.deployment_status)}</span>
            <div class="button-row">
              <button type="button" onclick="window.setDeploymentState(${item.id}, 'active')">Activar</button>
              <button type="button" class="secondary" onclick="window.setDeploymentState(${item.id}, 'paused')">Pausar</button>
            </div>
          </div>
        `).join('') : '<p>Todavía no hay deployments cargados para esta cuenta.</p>';

        document.getElementById('deployment-control-list').innerHTML = controls;
        return data;
      }

      function renderBrokerOnboarding(data) {
        const onboarding = data.broker_onboarding || {};
        const link = document.getElementById('exness-referral-link');
        const status = document.getElementById('exness-referral-status');
        if (!link || !status) {
          return;
        }
        link.href = onboarding.referral_url || '#';
        status.innerHTML = [
          pill(`Broker ${safeText(onboarding.primary_broker, 'Exness')}`),
          pill(onboarding.referral_configured ? 'referido configurado' : 'falta link referido', onboarding.referral_configured ? '' : 'warn'),
          pill(`Símbolo ${safeText(onboarding.default_canonical_symbol, 'XAUUSD')}${safeText(onboarding.default_exness_symbol_suffix, 'm')}`),
        ].join('');
      }

      function renderClientAccountPolicy(data) {
        const policyNode = document.getElementById('client-account-policy');
        const replaceSelect = document.getElementById('client-replace-account-select');
        const listNode = document.getElementById('client-accounts-list');
        if (!policyNode || !replaceSelect || !listNode) {
          return;
        }
        const policy = data.account_policy || {};
        const accounts = data.accounts || [];
        const maxAccounts = policy.max_broker_accounts ?? 1;
        const activeAccounts = policy.active_accounts ?? accounts.length;
        const remaining = policy.remaining_slots ?? Math.max(0, maxAccounts - activeAccounts);
        policyNode.innerHTML = [
          pill(`${activeAccounts}/${maxAccounts} cuentas activas`, remaining > 0 ? '' : 'warn'),
          pill(remaining > 0 ? `${remaining} cupo libre` : 'sin cupo libre', remaining > 0 ? '' : 'warn'),
        ].join(' ');

        replaceSelect.innerHTML = [
          `<option value="">Crear cuenta nueva si hay cupo</option>`,
          ...accounts.map(item => `<option value="${item.id}">Cambiar/reemplazar #${item.id} · ${safeText(item.label)} · ${safeText(item.broker_name)}</option>`),
        ].join('');

        listNode.innerHTML = accounts.length ? accounts.map(item => `
          <div class="row">
            <strong>#${item.id} · ${safeText(item.label)}</strong>
            <span>${safeText(item.broker_name)} · ${fmtBool(item.is_demo)} · ${safeText(item.latest_broker_symbol, 'XAUUSD' + (item.symbol_suffix || ''))}</span>
            <div class="button-row">
              <button type="button" class="secondary" onclick="window.prefillAccountReplacement(${item.id})">Cambiar esta cuenta</button>
              <button type="button" class="secondary" onclick="window.deleteMyAccount(${item.id})">Eliminar cuenta</button>
            </div>
          </div>
        `).join('') : '<p>No tienes cuentas activas todavía. Puedes conectar una cuenta Exness demo primero.</p>';
      }

      function renderClientAccountActions(item) {
        if (!authState.currentUser) {
          return '<span class="muted">Login requerido</span>';
        }
        if (authState.currentUser.role === 'owner') {
          return `
            <div class="button-row" style="margin-top:0;">
              <button type="button" class="secondary" onclick="window.archiveAccountAsOwner(${item.id})">Archivar cuenta</button>
            </div>
            <div class="mono">Owner puede desactivar cuentas con account mismatch.</div>
          `;
        }
        return `
          <div class="button-row" style="margin-top:0;">
            <button type="button" class="secondary" onclick="window.prefillAccountReplacement(${item.id})">Cambiar</button>
            <button type="button" class="secondary" onclick="window.deleteMyAccount(${item.id})">Eliminar</button>
          </div>
          <div class="mono">Usa eliminar para liberar cupo si hay account mismatch.</div>
        `;
      }

      function renderCapitalMetrics(data) {
        const metrics = data.portfolio_metrics || {};
        const accounts = data.accounts || [];
        const currency = metrics.currency || 'USD';
        const reported = metrics.accounts_reported || 0;
        const mismatchCount = accounts.filter(item => (item.financial_metrics || {}).source === 'terminal_account_mismatch').length;
        const pendingSyncCount = accounts.filter(item => (item.financial_metrics || {}).source !== 'mt5_account_status').length;
        const growth = Number(metrics.growth_amount || 0);
        const growthStyle = growth > 0 ? 'good' : (growth < 0 ? 'hot' : 'warn');
        const cards = [
          ['Balance total', fmtMoney(metrics.total_balance, currency), `${reported} cuenta(s) reportando`, ''],
          ['Equity total', fmtMoney(metrics.total_equity, currency), 'Capital actual según MT5', growthStyle],
          ['P/L flotante', fmtMoney(metrics.total_profit, currency), 'Ganancia/pérdida abierta', growthStyle],
          ['Crecimiento', fmtPct(metrics.growth_percent), fmtMoney(metrics.growth_amount, currency), growthStyle],
          ['Margen usado', fmtMoney(metrics.total_margin, currency), 'Exposición abierta', 'warn'],
          ['Margen libre', fmtMoney(metrics.total_margin_free, currency), 'Capacidad disponible', 'good'],
        ];
        document.getElementById('portfolio-metrics-cards').innerHTML = cards.map(([label, amount, note, style]) => `
          <div class="finance-card ${style}">
            <div class="label">${label}</div>
            <div class="amount">${amount}</div>
            <div class="note">${note}</div>
          </div>
        `).join('');
        document.getElementById('capital-source-chips').innerHTML = [
          pill(`${reported} MT5 reportando`, reported ? '' : 'warn'),
          pill(`${pendingSyncCount} pendientes/mismatch`, pendingSyncCount ? 'warn' : ''),
          pill(`${mismatchCount} account mismatch`, mismatchCount ? 'hot' : ''),
          pill(authState.currentUser && authState.currentUser.role === 'owner' ? 'vista owner global' : 'vista cliente'),
          pill('no inventa histórico', 'warn'),
        ].join('');
        document.getElementById('capital-section-title').textContent =
          authState.currentUser && authState.currentUser.role === 'owner'
            ? 'Capital y Resultados de Clientes'
            : 'Mi Capital y Resultados';
        document.getElementById('capital-section-note').textContent =
          authState.currentUser && authState.currentUser.role === 'owner'
            ? 'Como owner ves el capital reportado por cada cuenta activa de clientes. Rendimiento cerrado requiere historial de operaciones; aquí se muestra balance/equity/P/L flotante real desde MT5.'
            : 'El cliente solo ve sus cuentas autorizadas. Estas métricas vienen del terminal MT5 conectado y ayudan a seguir equity, margen y P/L flotante.';

        document.getElementById('capital-accounts-body').innerHTML = accounts.length ? accounts.map(item => {
          const fm = item.financial_metrics || {};
          const rowCurrency = fm.currency || currency;
          const rowGrowth = Number(fm.growth_amount || 0);
          const rowStyle = rowGrowth > 0 ? '' : (rowGrowth < 0 ? 'hot' : 'warn');
          return `
            <tr>
              <td><div>#${item.id} · ${safeText(item.label)}</div><div class="mono">${safeText(item.broker_name)} · ${safeText(item.latest_broker_symbol, 'XAUUSD' + (item.symbol_suffix || ''))}</div></td>
              <td class="owner-only hidden"><div>${safeText(item.owner_display_name)}</div><div class="mono">${safeText(item.owner_email)}</div></td>
              <td>${fmtMoney(fm.balance, rowCurrency)}</td>
              <td>${fmtMoney(fm.equity, rowCurrency)}</td>
              <td>${pill(fmtMoney(fm.profit, rowCurrency), rowStyle)}</td>
              <td><div>${fmtPct(fm.growth_percent)}</div><div class="mono">${fmtMoney(fm.growth_amount, rowCurrency)}</div></td>
              <td>${fmtMoney(fm.margin_free, rowCurrency)}</td>
              <td><div>${
                fm.source === 'mt5_account_status'
                  ? pill('MT5')
                  : (fm.source === 'terminal_account_mismatch' ? pill('account mismatch', 'hot') : pill('sin reporte', 'warn'))
              }</div><div class="mono">${fmtTime(fm.reported_at)}</div></td>
            </tr>
          `;
        }).join('') : '<tr><td colspan="8">No hay cuentas visibles para mostrar capital.</td></tr>';

        updateAuthUi();
      }

      window.setDeploymentState = async function(deploymentId, deploymentStatus) {
        const data = await postJson(`/api/platform/deployments/${deploymentId}/status`, {
          deployment_status: deploymentStatus,
        });
        const selector = document.getElementById('account-selector');
        if (selector && selector.value) {
          await loadAccountDetail(selector.value);
        }
        output().textContent = JSON.stringify(data, null, 2);
      }

      function renderSpotlights(data) {
        const summary = data.activity_summary || {};
        const firstAccount = (data.accounts || [])[0];
        const strategy = data.current_best_strategy || {};

        document.getElementById('highlight-online-agents').textContent = summary.online_agents ?? 0;
        document.getElementById('highlight-last-ai-action').textContent = safeText(summary.latest_ai_action);
        document.getElementById('highlight-last-execution-status').textContent = safeText(summary.latest_execution_status);
        document.getElementById('highlight-signal-runs').textContent = summary.signal_runs ?? 0;

        document.getElementById('spotlight-account-text').textContent = firstAccount
          ? `${firstAccount.label} en ${firstAccount.broker_name} con modo ${fmtBool(firstAccount.is_demo)} y conexión ${firstAccount.connection_mode}.`
          : 'Todavía no hay cuentas conectadas.';
        document.getElementById('spotlight-account-symbol').textContent = firstAccount
          ? safeText(firstAccount.latest_broker_symbol, `XAUUSD${firstAccount.symbol_suffix || ''}`)
          : '—';
        document.getElementById('spotlight-account-chips').innerHTML = firstAccount ? [
          pill(firstAccount.runtime_health || 'waiting_for_agent', firstAccount.runtime_health === 'running' ? '' : 'warn'),
          pill(firstAccount.latest_terminal_ready ? 'terminal ready' : 'terminal pending', firstAccount.latest_terminal_ready ? '' : 'warn'),
          pill(safeText(firstAccount.latest_ai_action, 'sin AI'), firstAccount.latest_ai_action ? 'hot' : 'warn'),
          pill(safeText(firstAccount.latest_execution_status, 'sin ejecución')),
        ].join('') : pill('sin cuentas', 'warn');

        document.getElementById('spotlight-cycle-count').textContent = `${summary.recent_agent_cycles ?? 0} ciclos`;
        document.getElementById('spotlight-activity-chips').innerHTML = [
          pill(`${summary.recent_deployment_runs ?? 0} runs AI`),
          pill(`${summary.executed_runs ?? 0} ejecutados`, 'hot'),
          pill(`${summary.watch_runs ?? 0} WATCH`, 'warn'),
        ].join('');

        document.getElementById('spotlight-strategy-text').textContent = `La plataforma está priorizando la mejor rama actual disponible para despliegues controlados.`;
        document.getElementById('spotlight-strategy-key').textContent = safeText(strategy.strategy_key);
        document.getElementById('spotlight-strategy-chips').innerHTML = [
          pill(`variant ${safeText(strategy.strategy_variant)}`),
          pill(`TF ${safeText(strategy.timeframe)}`, 'warn'),
          pill(`session ${safeText(strategy.session_variant)}`),
        ].join('');
      }

      function renderReadiness(data) {
        const summary = data.summary || {};
        const statusStyle = data.overall_status === 'READY' ? '' : (data.overall_status === 'NEEDS_ATTENTION' ? 'warn' : 'hot');
        document.getElementById('readiness-overall').innerHTML = `${pill(data.overall_status || 'UNKNOWN', statusStyle)} Sistema de preparación`;
        document.getElementById('readiness-clearance').textContent =
          `Clearance: ${safeText(data.operational_clearance)} · chequeado: ${fmtTime(data.checked_at)}`;
        document.getElementById('readiness-summary-chips').innerHTML = [
          pill(`${summary.ok || 0} OK`),
          pill(`${summary.warn || 0} WARN`, summary.warn ? 'warn' : ''),
          pill(`${summary.fail || 0} FAIL`, summary.fail ? 'hot' : ''),
        ].join('');

        const checks = data.checks || [];
        const visibleChecks = checks.filter(item => item.status !== 'OK').slice(0, 6);
        document.getElementById('readiness-critical-list').innerHTML = visibleChecks.length ? visibleChecks.map(item => `
          <div class="row">
            <strong>${pill(item.status, item.status === 'WARN' ? 'warn' : 'hot')} ${item.component}</strong>
            <span>${item.summary}</span>
          </div>
        `).join('') : '<p>Todos los componentes principales están en OK.</p>';

        const artifacts = data.critical_artifacts || {};
        document.getElementById('readiness-artifacts-list').innerHTML = Object.entries(artifacts).slice(0, 8).map(([name, item]) => `
          <div class="row">
            <strong>${item.exists ? pill('OK') : pill(item.required ? 'missing required' : 'optional', 'warn')} ${name}</strong>
            <span>${safeText(item.description)}</span>
            <span class="mono">${safeText(item.path)} · ${item.size_bytes || 0} bytes</span>
          </div>
        `).join('') || '<p>No hay artefactos registrados todavía.</p>';
      }

      async function loadReadiness() {
        if (!authState.token) {
          return;
        }
        const res = await authenticatedFetch('/api/platform/readiness');
        const data = await res.json();
        if (!res.ok) {
          document.getElementById('readiness-overall').innerHTML = `${pill('restringido', 'warn')} Readiness`;
          document.getElementById('readiness-clearance').textContent = data.detail || 'Solo owner puede ver auditoría interna.';
          document.getElementById('readiness-summary-chips').innerHTML = pill('owner requerido', 'warn');
          return;
        }
        renderReadiness(data);
      }

      function renderAiLive(data) {
        const brain = data.brain || {};
        const market = data.market || {};
        const projection = data.pattern_projection || {};
        const sideComparison = projection.side_probability_comparison || {};
        const sideStats = sideComparison.sides || {};
        const coolMemory = projection.q_learning_memory || projection.cool_learning_memory || {};
        const proMatrix = projection.professional_decision_matrix || {};
        const courseAlignment = coolMemory.course_alignment || proMatrix.course_learning_sync || {};
        const layerSync = proMatrix.layer_synchronization || {};
        const proManagement = proMatrix.management_plan || {};
        const priceContext = data.price_context || {};
        const watchZone = priceContext.watch_zone || {};
        const reasoning = data.reasoning || {};
        const learning = data.learning || {};
        const activeWatch = data.active_watch || {};
        const externalContext = data.external_context || {};
        const audit = data.audit || {};
        const sources = audit.sources || {};

        renderEntrySignalRadar(data);
        setText('ai-live-action', `${safeText(brain.action)} · ${safeText(brain.execution_status)}`);
        setText('ai-live-updated', `Último ciclo: ${fmtTime(brain.generated_at)} · archivo: ${fmtTime(brain.artifact_updated_at)} · UI: ${fmtTime(data.generated_at)}`);
        renderRuntimeState(brain);
        setText('ai-live-side-tag', `${safeText(market.candidate_side || market.preferred_side)} ${safeText(brain.watch_policy_action)}`);
        setText('ai-live-summary', reasoning.summary || projection.interpretation || 'La IA sigue observando el mercado.');
        setText('ai-live-probable-move', projection.probable_market_move || 'Aún no hay movimiento probable definido por patrón aprendido.');
        setText(
          'ai-live-external-context',
          `${safeText(externalContext.anticipation, 'Sin contexto externo disponible.')} · sync ${safeText((externalContext.sync_status || {}).status)} · event_action ${safeText(externalContext.action)}`
        );
        setText(
          'ai-live-price-zone',
          priceContext.status === 'ready'
            ? `${safeText(watchZone.label)}: ${safeText(watchZone.low)} - ${safeText(watchZone.high)} · precio actual ${safeText(priceContext.current_price)} · spread ${safeText(priceContext.spread)}`
            : safeText(priceContext.message, 'Zona/precio pendiente de lectura MT5.')
        );
        setText(
          'ai-live-confirmation-price',
          priceContext.status === 'ready'
            ? `Confirmar ${safeText(priceContext.side)} en ${safeText(priceContext.confirmation_price)} · invalidar en ${safeText(priceContext.invalidation_price)} · distancia ${safeText(priceContext.distance_to_confirmation)}`
            : 'Esperando lectura MT5 para nivel numérico.'
        );
        setText('ai-live-next-confirmation', reasoning.next_confirmation_expected || 'Esperando confirmación final.');
        setText('ai-live-maturity', reasoning.setup_maturity !== undefined ? Number(reasoning.setup_maturity).toFixed(2) : '—');
        setText('ai-live-confidence', reasoning.confidence !== undefined ? Number(reasoning.confidence).toFixed(4) : '—');
        setText('ai-live-harmony', brain.harmony_score !== undefined ? Number(brain.harmony_score).toFixed(4) : '—');
        setText('ai-live-probability', brain.watch_probability_to_execute !== undefined ? Number(brain.watch_probability_to_execute).toFixed(2) : '—');

        document.getElementById('ai-live-chips').innerHTML = [
          pill(`símbolo ${esc(brain.symbol || market.symbol || 'XAUUSD')}`),
          pill(`lado ${esc(market.candidate_side || market.preferred_side || 'NEUTRAL')}`, market.candidate_side ? 'hot' : 'warn'),
          pill(`riesgo ${esc(brain.allowed_risk_mode || 'blocked')}`, brain.allowed_risk_mode === 'reduced' ? 'warn' : ''),
          pill(`macro ${esc(market.macro_event_action || 'unknown')}`, market.macro_event_action === 'allow' ? '' : 'warn'),
          pill(`news ${esc(externalContext.action || 'unknown')}`, externalContext.action === 'allow' ? '' : 'warn'),
          pill(`exec ${esc(market.execution_viability || 'unknown')}`, market.execution_viability === 'SAFE' ? '' : 'warn'),
          pill(`precio ${esc(priceContext.current_price || 'pendiente')}`, priceContext.status === 'ready' ? '' : 'warn'),
        ].join('');

        renderAiList('ai-live-waiting-list', reasoning.waiting_for, 'No hay condiciones pendientes fuertes ahora mismo.');
        renderAiList('ai-live-evidence-list', [
          ...(projection.pattern_matches || []),
          ...(projection.evidence || []),
          ...((projection.historical_analogs || {}).summary ? [
            `Analogías históricas: ${(projection.historical_analogs || {}).summary}`,
            `Resultado histórico: bias ${safeText((projection.historical_analogs || {}).bias)} · win_rate ${safeText((projection.historical_analogs || {}).win_rate)} · failure_rate ${safeText((projection.historical_analogs || {}).failure_rate)}`
          ] : []),
          ...(sideComparison.selected_side ? [
            `Comparación BUY/SELL: seleccionado ${safeText(sideComparison.selected_side)} · ${safeText(sideComparison.selection_reason)}`,
            `BUY prob ${safeText((sideStats.BUY || {}).probability_to_confirm)} · SELL prob ${safeText((sideStats.SELL || {}).probability_to_confirm)} · vigilar alternativa ${safeText(sideComparison.should_watch_alternative)}`
          ] : []),
          ...(coolMemory.summary ? [
            `Q-learning memory: ${safeText(coolMemory.summary)}`,
            `Q-valores: BUY ${safeText((coolMemory.q_values || coolMemory.action_values || {}).BUY)} · SELL ${safeText((coolMemory.q_values || coolMemory.action_values || {}).SELL)} · WAIT ${safeText((coolMemory.q_values || coolMemory.action_values || {}).WAIT)} · confianza ${safeText(coolMemory.confidence)}`,
          ] : []),
          ...(courseAlignment.status ? [
            `Cursos/playbooks: ${safeText(courseAlignment.status)} · score ${safeText(courseAlignment.course_score)} · acción ${safeText(courseAlignment.course_recommended_action)}`,
            `Pasos de curso pendientes: ${safeText((courseAlignment.missing_steps || []).slice(0, 2).join(' · ') || 'sin faltantes críticos')}`,
          ] : []),
          ...(layerSync.status ? [
            `Sincronización de capas: ${safeText(layerSync.status)} · acuerdo ${safeText(layerSync.agreement_score)} · lado ${safeText(layerSync.selected_side)}`,
            `Capas: ${safeText(JSON.stringify(layerSync.layers || {}))}`,
          ] : []),
          ...(proMatrix.summary ? [
            `Matriz profesional: ${safeText(proMatrix.summary)}`,
            `Mejor opción: ${safeText(proMatrix.best_option_reason)}`,
            `Esperar: ${safeText(proMatrix.wait_for_liquidity_volatility)}`,
            `Gestión: ${safeText(proManagement.take_profit_plan)} · ${safeText(proManagement.trailing_plan)}`,
          ] : []),
        ], 'Todavía no hay evidencia de patrón aprendida para este ciclo.');
        renderAiList('ai-live-risk-list', [
          `watch_health: ${safeText(brain.watch_health)}`,
          `active_watch: ${safeText(activeWatch.status)} · ${safeText(activeWatch.progress)} · edad ${safeText(activeWatch.age_candles)} velas`,
          `risk_mode: ${safeText(brain.allowed_risk_mode)} · multiplier ${safeText(brain.max_risk_multiplier)} · effective ${safeText(brain.effective_risk)}`,
          `spread/slippage: ${safeText(market.live_spread)} / ${safeText(market.slippage_estimated)}`,
          `zona vigilada: ${safeText(watchZone.low)} - ${safeText(watchZone.high)} · confirmar ${safeText(priceContext.confirmation_price)}`,
          `regla precio: ${safeText(priceContext.confirmation_rule)}`,
          `evento macro: ${safeText(market.macro_event_action)}`,
          `contexto externo: ${safeText(externalContext.anticipation)}`,
          `sync calendario: ${safeText((externalContext.sync_status || {}).status)} · ${safeText((externalContext.sync_status || {}).reason || (externalContext.sync_status || {}).fallback || '')}`,
          ...((externalContext.upcoming_events || []).slice(0, 3).map(event => `próximo evento: ${safeText(event.start_time_local)} · ${safeText(event.currency)} · ${safeText(event.impact)} · ${safeText(event.title)}`)),
          `último evento watch: ${safeText((activeWatch.last_event || {}).event)} · ${safeText((activeWatch.last_event || {}).reason)}`,
        ], 'Sin guardias reportados todavía.');

        const counts = learning.knowledge_counts || {};
        document.getElementById('ai-learning-chips').innerHTML = [
          pill(`cycle ${esc(learning.status || 'unknown')}`, learning.status ? '' : 'warn'),
          pill(`applicability ${esc(learning.applicability_level || 'pending')}`, learning.applicability_level ? '' : 'warn'),
          pill(`${esc(counts.normalized_rules || 0)} reglas normalizadas`),
          pill(`${esc(counts.strategy_candidates || 0)} candidatos`),
          pill(`${esc(counts.top_strategies || counts.top_strategies_detected || 0)} estrategias top`),
        ].join('');
        renderAiList(
          'ai-learning-patterns',
          (learning.recognized_patterns || []).map(item => `${item.pattern}: ${item.count}`),
          'El ciclo de aprendizaje todavía no reporta patrones.'
        );

        const sourceFreshness = Object.entries(sources).filter(([, item]) => item && item.exists).slice(0, 4).map(
          ([name, item]) => `${name}: ${fmtTime(item.updated_at)}`
        );
        if (sourceFreshness.length) {
          const riskNode = document.getElementById('ai-live-risk-list');
          riskNode.innerHTML += sourceFreshness.map(item => `<div class="ai-list-item mono">${esc(item)}</div>`).join('');
        }
      }

      async function loadAiLive() {
        if (!authState.token) {
          return;
        }
        const res = await authenticatedFetch('/api/platform/ai-live');
        const data = await res.json();
        if (!res.ok) {
          setText('ai-live-action', 'AI restringida');
          setText('ai-live-summary', data.detail || 'No se pudo cargar la vista viva del cerebro.');
          return;
        }
        renderAiLive(data);
      }

      async function loadStatus() {
        if (!authState.token) {
          document.getElementById('service-status').textContent = 'Login requerido';
          document.getElementById('footer-note').textContent = 'Inicia sesión o envía tu solicitud de registro para continuar.';
          return;
        }

        const res = await authenticatedFetch('/api/platform/status');
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || JSON.stringify(data));
        }

        document.getElementById('service-status').textContent = 'Servicio online';
        document.getElementById('count-users').textContent = data.counts.users;
        document.getElementById('count-accounts').textContent = data.counts.accounts;
        document.getElementById('count-agents').textContent = data.counts.agents;
        document.getElementById('count-deployments').textContent = data.counts.deployments;

        document.getElementById('best-strategy-name').textContent = data.current_best_strategy.strategy_key || 'Sin estrategia';
        document.getElementById('best-strategy-meta').textContent =
          `Variante: ${safeText(data.current_best_strategy.strategy_variant)} | TF: ${safeText(data.current_best_strategy.timeframe)} | Sesión: ${safeText(data.current_best_strategy.session_variant)}`;

        document.getElementById('overview-list').innerHTML = `
          <div class="row"><strong>Objetivo del servicio</strong><span>${data.service_objective}</span></div>
          <div class="row"><strong>Modos de operación</strong><span>${Object.keys(data.operation_modes).length ? Object.entries(data.operation_modes).map(([k,v]) => `${k} (${v})`).join(' · ') : 'Sin deployments todavía.'}</span></div>
          <div class="row"><strong>Perfiles de riesgo</strong><span>${Object.keys(data.risk_modes).length ? Object.entries(data.risk_modes).map(([k,v]) => `${k} (${v})`).join(' · ') : 'Sin perfiles cargados.'}</span></div>
        `;

        renderSpotlights(data);
        renderBrokerOnboarding(data);
        renderClientAccountPolicy(data);
        renderCapitalMetrics(data);
        await loadAiLive();

        const accounts = data.accounts || [];
        const selector = document.getElementById('account-selector');
        const currentSelection = selector.value;
        selector.innerHTML = accounts.length ? accounts.map(item => `
          <option value="${item.id}">${item.id} · ${item.label} · ${item.broker_name}</option>
        `).join('') : '<option value="">Sin cuentas</option>';
        if (accounts.length) {
          selector.value = accounts.some(item => String(item.id) === currentSelection) ? currentSelection : String(accounts[0].id);
          await loadAccountDetail(selector.value);
        } else {
          document.getElementById('account-detail-summary').innerHTML = '<p>Selecciona una cuenta para cargar su detalle operativo.</p>';
          document.getElementById('deployment-control-list').innerHTML = '<p>Todavía no hay deployments cargados para esta cuenta.</p>';
        }

        document.getElementById('accounts-body').innerHTML = accounts.length ? accounts.map(item => `
          <tr>
            <td>${item.id}</td>
            <td>${item.broker_name}</td>
            <td><div>${item.label}</div><div class="mono">${item.connection_mode}</div></td>
            <td>${fmtBool(item.is_demo)}</td>
            <td>${[
              pill(safeText(item.runtime_health, 'waiting_for_agent'), item.runtime_health === 'running' ? '' : 'warn'),
              pill(item.agent_count ? `${item.agent_count} agente` : 'sin agente', item.agent_count ? '' : 'warn'),
              pill(safeText(item.latest_broker_symbol, 'XAUUSD' + (item.symbol_suffix || ''))),
              pill(safeText(item.latest_ai_action, 'sin AI'), item.latest_ai_action ? 'hot' : 'warn'),
              pill(safeText(item.latest_execution_status, 'sin ejecución')),
            ].join(' ')}</td>
            <td>${renderClientAccountActions(item)}</td>
          </tr>`).join('') : '<tr><td colspan="6">No hay cuentas conectadas todavía.</td></tr>';

        const agents = data.agents || [];
        document.getElementById('agents-body').innerHTML = agents.length ? agents.map(item => `
          <tr>
            <td>${item.id}</td>
            <td>${item.agent_name}</td>
            <td>${item.host_name}</td>
            <td>${item.status === 'online' ? pill('online') : pill(item.status || 'unknown', 'warn')}</td>
            <td>${fmtTime(item.last_heartbeat_at)}</td>
          </tr>`).join('') : '<tr><td colspan="5">No hay agentes registrados todavía.</td></tr>';

        const deployments = data.deployments || [];
        document.getElementById('deployments-body').innerHTML = deployments.length ? deployments.map(item => `
          <tr>
            <td>${item.account_id}</td>
            <td><div>${item.strategy_key}</div><div class="mono">${item.strategy_variant}</div></td>
            <td>${item.operation_mode}</td>
            <td>${item.risk_mode}</td>
            <td>${item.deployment_status === 'active' ? pill('active') : pill(item.deployment_status, 'warn')}</td>
          </tr>`).join('') : '<tr><td colspan="5">No hay deployments activos todavía.</td></tr>';

        const learning = data.learning_integrations_detail || [];
        document.getElementById('learning-body').innerHTML = learning.length ? learning.map(item => `
          <tr>
            <td>${item.source_label}</td>
            <td>${item.source_type}</td>
            <td>${item.sync_frequency_minutes}m</td>
            <td>${item.ingestion_mode}</td>
            <td>${item.enabled ? pill(item.auto_sync ? 'auto-sync' : 'enabled') : pill('disabled', 'warn')}</td>
          </tr>`).join('') : '<tr><td colspan="5">No hay fuentes de aprendizaje registradas.</td></tr>';

        const users = data.users_detail || [];
        const usersBody = document.getElementById('users-body');
        if (usersBody) {
          usersBody.innerHTML = users.length ? users.map(item => `
            <tr>
              <td>${item.id}</td>
              <td><div>${item.display_name}</div><div class="mono">${item.email}</div></td>
              <td>${item.role}</td>
              <td>${item.status === 'active' ? pill('active') : pill(item.status || 'unknown', 'warn')}</td>
              <td>${item.role === 'owner' ? '—' : `
                <div class="button-row" style="margin-top:0;">
                  <input id="user-account-limit-${item.id}" type="number" min="1" value="${item.max_broker_accounts || 1}" style="max-width:92px;" />
                  <button type="button" class="secondary" onclick="window.setUserAccountLimit(${item.id})">Guardar cupo</button>
                </div>
              `}</td>
              <td>${item.role === 'owner' ? '—' : `
                <div class="button-row" style="margin-top:0;">
                  <button type="button" onclick="window.setUserStatus(${item.id}, 'active')">Activar</button>
                  <button type="button" class="secondary" onclick="window.setUserStatus(${item.id}, 'suspended')">Suspender</button>
                </div>
              `}</td>
            </tr>
          `).join('') : '<tr><td colspan="6">No hay usuarios registrados todavía.</td></tr>';
        }

        const runtimeCycles = data.recent_agent_cycles || [];
        document.getElementById('runtime-body').innerHTML = runtimeCycles.length ? runtimeCycles.map(item => `
          <tr>
            <td>${fmtTime(item.created_at)}</td>
            <td>#${item.agent_id}</td>
            <td><div>${item.broker_symbol}</div><div class="mono">${item.canonical_symbol}</div></td>
            <td>${item.cycle_status === 'completed' ? pill('completed') : pill(item.cycle_status || 'unknown', 'warn')}</td>
            <td>${item.local_terminal_ready ? pill('ready') : pill('not-ready', 'warn')}</td>
          </tr>`).join('') : '<tr><td colspan="5">Todavía no hay ciclos reportados por agentes.</td></tr>';

        const runResults = data.recent_deployment_runs || [];
        document.getElementById('run-results-body').innerHTML = runResults.length ? runResults.map(item => `
          <tr>
            <td>${fmtTime(item.created_at)}</td>
            <td><div>${item.strategy_key}</div><div class="mono">${safeText(item.strategy_variant)}</div></td>
            <td>${safeText(item.operation_mode)}</td>
            <td>${item.run_status === 'executed' ? pill('executed', 'hot') : pill(item.run_status || 'unknown', 'warn')}</td>
            <td><div>${safeText(item.intelligence_action)}</div><div class="mono">${safeText(item.execution_status)}</div></td>
          </tr>`).join('') : '<tr><td colspan="5">Todavía no hay resultados AI reportados.</td></tr>';

        document.getElementById('footer-note').textContent =
          `Última actualización: ${new Date().toLocaleString()} | Cuentas: ${accounts.length} | Agentes: ${agents.length} | Deployments: ${deployments.length} | Ciclos: ${runtimeCycles.length} | Resultados AI: ${runResults.length}`;
        await loadReadiness();
        await loadNotificationCenter();
      }

      document.getElementById('user-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = new FormData(event.target);
        await postJson('/api/platform/users', {
          email: form.get('email'),
          display_name: form.get('display_name'),
          role: form.get('role'),
          status: 'active',
          timezone_name: form.get('timezone_name'),
          max_broker_accounts: Number(form.get('max_broker_accounts') || 1),
        });
      });

      document.getElementById('public-register-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = new FormData(event.target);
        const res = await fetch('/api/platform/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: form.get('email'),
            display_name: form.get('display_name'),
            password: form.get('password'),
            timezone_name: form.get('timezone_name'),
          }),
        });
        const data = await res.json();
        document.getElementById('public-register-output').textContent = data.detail || data.message || JSON.stringify(data);
        if (!res.ok) {
          document.getElementById('service-status').textContent = 'Registro no completado';
          return;
        }
        event.target.reset();
        document.getElementById('service-status').textContent = 'Solicitud recibida';
      });

      window.setUserStatus = async function(userId, status) {
        const data = await postJson('/api/platform/users/status', {
          user_id: userId,
          status,
        });
        output().textContent = JSON.stringify(data, null, 2);
      }

      window.setUserAccountLimit = async function(userId) {
        const input = document.getElementById(`user-account-limit-${userId}`);
        const limit = Number(input ? input.value : 1);
        const data = await postJson('/api/platform/users/account-limit', {
          user_id: userId,
          max_broker_accounts: limit,
        });
        output().textContent = JSON.stringify(data, null, 2);
      }

      window.markNotificationRead = async function(notificationId) {
        const res = await authenticatedFetch(`/api/platform/notifications/${notificationId}/read`, { method: 'POST' });
        const data = await res.json();
        output().textContent = JSON.stringify(data, null, 2);
        await loadNotificationCenter();
      }

      window.prefillAccountReplacement = function(accountId) {
        const select = document.getElementById('client-replace-account-select');
        if (select) {
          select.value = String(accountId);
          document.getElementById('client-exness-form').scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }

      window.deleteMyAccount = async function(accountId) {
        if (!confirm('¿Seguro que quieres eliminar/desactivar esta cuenta? Podrás conectar otra si tienes cupo disponible.')) {
          return;
        }
        const res = await authenticatedFetch(`/api/platform/me/accounts/${accountId}`, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || JSON.stringify(data));
        }
        output().textContent = JSON.stringify(data, null, 2);
        await loadStatus();
      }

      window.archiveAccountAsOwner = async function(accountId) {
        if (!confirm('¿Archivar esta cuenta? Quedará inactiva, sus agentes/deployments se archivan y no aparecerá como cuenta activa.')) {
          return;
        }
        const res = await authenticatedFetch(`/api/platform/accounts/${accountId}`, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || JSON.stringify(data));
        }
        output().textContent = JSON.stringify(data, null, 2);
        await loadStatus();
      }

      document.getElementById('account-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = new FormData(event.target);
        await postJson('/api/platform/accounts', {
          owner_email: form.get('owner_email'),
          account_label: form.get('account_label'),
          broker_name: form.get('broker_name'),
          symbol_suffix: form.get('symbol_suffix'),
          platform_type: 'MT5',
          is_demo: true,
          connection_mode: 'local_agent',
          allowed_symbols: ['XAUUSD'],
          risk_profile: { risk_mode: 'reduced', daily_loss_limit_r: 3.0 },
          source_bots: [],
        });
      });

      document.getElementById('client-exness-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = new FormData(event.target);
        await postJson('/api/platform/me/accounts/exness', {
          account_label: form.get('account_label'),
          broker_server: form.get('broker_server') || null,
          login_reference: form.get('login_reference') || null,
          symbol_suffix: form.get('symbol_suffix') || 'm',
          base_currency: 'USD',
          is_demo: true,
          referral_confirmed: form.get('referral_confirmed') === 'on',
          replace_account_id: form.get('replace_account_id') ? Number(form.get('replace_account_id')) : null,
          notes: 'Cuenta conectada desde portal cliente.',
        });
      });

      document.getElementById('agent-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = new FormData(event.target);
        await postJson(`/api/platform/accounts/${form.get('account_id')}/agents`, {
          agent_name: form.get('agent_name'),
          host_name: form.get('host_name'),
          broker_name: form.get('broker_name'),
          capabilities: {
            mt5_execution: true,
            symbol_resolution: true,
            demo_first: true,
          },
        });
      });

      document.getElementById('deployment-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = new FormData(event.target);
        await postJson(`/api/platform/accounts/${form.get('account_id')}/deployments`, {
          strategy_key: form.get('strategy_key'),
          strategy_variant: form.get('strategy_variant'),
          operation_mode: form.get('operation_mode'),
          risk_mode: form.get('risk_mode'),
          learning_mode: form.get('learning_mode'),
          deployment_status: 'active',
          symbol_allowlist: ['XAUUSD'],
          source_bots: [],
        });
      });

      document.getElementById('refresh-button').addEventListener('click', async () => {
        await loadStatus();
        output().textContent = 'Panel actualizado.';
      });

      document.querySelectorAll('.workspace-tab').forEach((button) => {
        button.addEventListener('click', () => {
          switchWorkspaceView(button.dataset.viewTarget);
        });
      });

      document.getElementById('account-selector').addEventListener('change', async (event) => {
        if (event.target.value) {
          await loadAccountDetail(event.target.value);
        }
      });

      document.getElementById('login-button').addEventListener('click', async () => {
        const email = document.getElementById('login-email-input').value.trim();
        const password = document.getElementById('login-password-input').value;
        if (!email || !password) {
          output().textContent = 'Debes escribir tu correo y contraseña antes de entrar.';
          return;
        }
        try {
          const data = await loginWithPassword(email, password);
          document.getElementById('login-password-input').value = '';
          output().textContent = JSON.stringify({
            user_email: data.user_email,
            role: data.role,
            status: data.status,
            token_preview: data.token_preview,
          }, null, 2);
        } catch (error) {
          document.getElementById('service-status').textContent = 'Error autenticando';
          output().textContent = error.message;
        }
      });

      document.getElementById('forgot-password-button').addEventListener('click', async () => {
        const email = document.getElementById('login-email-input').value.trim();
        const outputNode = document.getElementById('password-reset-output');
        if (!email) {
          outputNode.textContent = 'Escribe tu correo primero.';
          return;
        }
        const res = await fetch('/api/platform/auth/password-reset/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email,
            device_fingerprint: getDeviceFingerprint(),
            device_label: getDeviceLabel(),
          }),
        });
        const data = await res.json();
        outputNode.textContent = data.message || data.detail || JSON.stringify(data);
      });

      document.getElementById('reset-password-button').addEventListener('click', async () => {
        const email = document.getElementById('login-email-input').value.trim();
        const token = document.getElementById('reset-token-input').value.trim();
        const newPassword = document.getElementById('reset-password-input').value;
        const outputNode = document.getElementById('password-reset-output');
        if (!email || !token || !newPassword) {
          outputNode.textContent = 'Correo, token y nueva contraseña son obligatorios.';
          return;
        }
        const res = await fetch('/api/platform/auth/password-reset/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, token, new_password: newPassword }),
        });
        const data = await res.json();
        outputNode.textContent = data.message || data.detail || JSON.stringify(data);
        if (res.ok) {
          document.getElementById('reset-token-input').value = '';
          document.getElementById('reset-password-input').value = '';
        }
      });

      document.getElementById('notification-button').addEventListener('click', async () => {
        if (!authState.currentUser) {
          return;
        }
        switchWorkspaceView(authState.currentUser.role === 'owner' ? 'admin' : 'accounts');
        await loadNotificationCenter();
      });

      document.getElementById('logout-button').addEventListener('click', async () => {
        authState.token = '';
        authState.currentUser = null;
        localStorage.removeItem('botextrator_api_token');
        updateAuthUi();
        document.getElementById('service-status').textContent = 'Login requerido';
        document.getElementById('footer-note').textContent = 'Sesión cerrada.';
      });

      loadCurrentUser().then(() => loadStatus()).catch((error) => {
        document.getElementById('service-status').textContent = 'Login requerido';
        document.getElementById('footer-note').textContent = error.message;
      });
      setInterval(loadStatus, 15000);
      setInterval(() => {
        if (authState.token) {
          loadAiLive().catch(() => {});
        }
      }, 5000);
    </script>
  </body>
</html>"""
