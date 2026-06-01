"""Repository for the multi-user trading service platform."""

from __future__ import annotations

import json
import hashlib
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models.channel import Channel
from src.db.models.platform import (
    AccountAccessGrant,
    BrokerAccount,
    BrokerSymbolAlias,
    DeploymentExecutionReport,
    ExecutionAgent,
    ExecutionAgentRuntimeReport,
    LearningIntegration,
    PasswordResetToken,
    PlatformApiCredential,
    PlatformNotification,
    PlatformSecurityEvent,
    PlatformUser,
    StrategyDeployment,
)


class PlatformRepository:
    """Persistence helpers for users, broker accounts and agents."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_user_by_email(self, email: str) -> PlatformUser | None:
        stmt = select(PlatformUser).where(PlatformUser.email == email.strip().lower())
        return self.session.scalar(stmt)

    def get_user_by_id(self, user_id: int) -> PlatformUser | None:
        stmt = select(PlatformUser).where(PlatformUser.id == user_id)
        return self.session.scalar(stmt)

    def list_users(self, limit: int = 100) -> list[PlatformUser]:
        stmt = select(PlatformUser).order_by(PlatformUser.id.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def list_owner_users(self) -> list[PlatformUser]:
        stmt = select(PlatformUser).where(PlatformUser.role == "owner", PlatformUser.status == "active").order_by(PlatformUser.id.asc())
        return list(self.session.scalars(stmt))

    def get_agent(self, agent_id: int) -> ExecutionAgent | None:
        stmt = select(ExecutionAgent).where(ExecutionAgent.id == agent_id)
        return self.session.scalar(stmt)

    def get_account(self, account_id: int) -> BrokerAccount | None:
        stmt = select(BrokerAccount).where(BrokerAccount.id == account_id)
        return self.session.scalar(stmt)

    def get_deployment(self, deployment_id: int) -> StrategyDeployment | None:
        stmt = select(StrategyDeployment).where(StrategyDeployment.id == deployment_id)
        return self.session.scalar(stmt)

    def get_account_access_grant(self, *, account_id: int, user_id: int) -> AccountAccessGrant | None:
        stmt = select(AccountAccessGrant).where(
            AccountAccessGrant.account_id == account_id,
            AccountAccessGrant.user_id == user_id,
            AccountAccessGrant.is_active.is_(True),
        )
        return self.session.scalar(stmt)

    def list_access_grants_for_user(self, user_id: int) -> list[AccountAccessGrant]:
        stmt = (
            select(AccountAccessGrant)
            .where(
                AccountAccessGrant.user_id == user_id,
                AccountAccessGrant.is_active.is_(True),
            )
            .order_by(AccountAccessGrant.account_id.asc())
        )
        return list(self.session.scalars(stmt))

    def get_agent_by_key(self, *, account_id: int, agent_key: str) -> ExecutionAgent | None:
        stmt = select(ExecutionAgent).where(
            ExecutionAgent.account_id == account_id,
            ExecutionAgent.agent_key == agent_key,
        )
        return self.session.scalar(stmt)

    def list_account_deployments(self, account_id: int) -> list[StrategyDeployment]:
        stmt = select(StrategyDeployment).where(StrategyDeployment.account_id == account_id).order_by(StrategyDeployment.id.asc())
        return list(self.session.scalars(stmt))

    def list_account_symbol_aliases(self, account_id: int) -> list[BrokerSymbolAlias]:
        stmt = select(BrokerSymbolAlias).where(BrokerSymbolAlias.account_id == account_id).order_by(BrokerSymbolAlias.id.asc())
        return list(self.session.scalars(stmt))

    def list_recent_agent_runtime_reports(self, limit: int = 10) -> list[ExecutionAgentRuntimeReport]:
        stmt = select(ExecutionAgentRuntimeReport).order_by(ExecutionAgentRuntimeReport.id.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def list_recent_deployment_execution_reports(self, limit: int = 10) -> list[DeploymentExecutionReport]:
        stmt = select(DeploymentExecutionReport).order_by(DeploymentExecutionReport.id.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def list_account_runtime_reports(self, account_id: int, limit: int = 10) -> list[ExecutionAgentRuntimeReport]:
        stmt = (
            select(ExecutionAgentRuntimeReport)
            .where(ExecutionAgentRuntimeReport.account_id == account_id)
            .order_by(ExecutionAgentRuntimeReport.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_account_deployment_reports(self, account_id: int, limit: int = 10) -> list[DeploymentExecutionReport]:
        stmt = (
            select(DeploymentExecutionReport)
            .where(DeploymentExecutionReport.account_id == account_id)
            .order_by(DeploymentExecutionReport.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_account_agents(self, account_id: int) -> list[ExecutionAgent]:
        stmt = select(ExecutionAgent).where(ExecutionAgent.account_id == account_id).order_by(ExecutionAgent.id.asc())
        return list(self.session.scalars(stmt))

    def list_owner_accounts(self, owner_user_id: int) -> list[BrokerAccount]:
        stmt = (
            select(BrokerAccount)
            .where(BrokerAccount.owner_user_id == owner_user_id, BrokerAccount.is_active.is_(True))
            .order_by(BrokerAccount.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_active_channels(self) -> list[Channel]:
        stmt = select(Channel).where(Channel.is_active.is_(True)).order_by(Channel.id.asc())
        return list(self.session.scalars(stmt))

    def create_or_update_user(
        self,
        *,
        email: str,
        display_name: str,
        role: str = "client",
        status: str = "active",
        timezone_name: str = "America/Santo_Domingo",
        max_broker_accounts: int = 1,
        password_hash: str | None = None,
        notes: str | None = None,
    ) -> PlatformUser:
        normalized_email = email.strip().lower()
        user = self.get_user_by_email(normalized_email)
        if user is None:
            user = PlatformUser(
                email=normalized_email,
                display_name=display_name,
                role=role,
                status=status,
                timezone_name=timezone_name,
                max_broker_accounts=max(1, int(max_broker_accounts or 1)),
                password_hash=password_hash,
                password_updated_at=datetime.now(timezone.utc) if password_hash else None,
                notes=notes,
            )
            self.session.add(user)
        else:
            user.display_name = display_name
            user.role = role
            user.status = status
            user.timezone_name = timezone_name
            user.max_broker_accounts = max(1, int(max_broker_accounts or user.max_broker_accounts or 1))
            if password_hash is not None:
                user.password_hash = password_hash
                user.password_updated_at = datetime.now(timezone.utc)
            if notes is not None:
                user.notes = notes
        self.session.flush()
        return user

    def update_user_account_limit(self, *, user_id: int, max_broker_accounts: int) -> PlatformUser | None:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        user.max_broker_accounts = max(1, int(max_broker_accounts))
        self.session.flush()
        return user

    def update_user_status(self, *, user_id: int, status: str) -> PlatformUser | None:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        user.status = status
        self.session.flush()
        return user

    def set_user_password_hash(self, *, user_id: int, password_hash: str) -> PlatformUser | None:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        user.password_hash = password_hash
        user.password_updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return user

    def touch_user_login(self, *, user_id: int) -> PlatformUser | None:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        user.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return user

    def create_password_reset_token(
        self,
        *,
        user_id: int,
        token: str,
        expires_at: datetime,
        request_ip: str | None = None,
        request_user_agent: str | None = None,
        notes: str | None = None,
    ) -> PasswordResetToken:
        entity = PasswordResetToken(
            user_id=user_id,
            token_hash=self._token_hash(token),
            token_preview=token[:8],
            expires_at=expires_at,
            request_ip=request_ip,
            request_user_agent=request_user_agent,
            notes=notes,
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def get_active_password_reset_token(self, *, token: str) -> PasswordResetToken | None:
        now = datetime.now(timezone.utc)
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == self._token_hash(token),
            PasswordResetToken.status == "active",
            PasswordResetToken.expires_at > now,
        )
        return self.session.scalar(stmt)

    def mark_password_reset_token_used(self, *, token_id: int) -> PasswordResetToken | None:
        token = self.session.get(PasswordResetToken, token_id)
        if token is None:
            return None
        token.status = "used"
        token.used_at = datetime.now(timezone.utc)
        self.session.flush()
        return token

    def create_notification(
        self,
        *,
        title: str,
        message: str,
        category: str,
        severity: str = "info",
        audience: str = "owner",
        user_id: int | None = None,
        metadata: dict | None = None,
    ) -> PlatformNotification:
        entity = PlatformNotification(
            user_id=user_id,
            audience=audience,
            category=category,
            severity=severity,
            title=title,
            message=message,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def list_notifications_for_user(self, *, user_id: int, role: str, limit: int = 30) -> list[PlatformNotification]:
        if role == "owner":
            stmt = (
                select(PlatformNotification)
                .where((PlatformNotification.audience == "owner") | (PlatformNotification.user_id == user_id))
                .order_by(PlatformNotification.id.desc())
                .limit(limit)
            )
        else:
            stmt = (
                select(PlatformNotification)
                .where(PlatformNotification.user_id == user_id)
                .order_by(PlatformNotification.id.desc())
                .limit(limit)
            )
        return list(self.session.scalars(stmt))

    def mark_notification_read(self, *, notification_id: int, user_id: int, role: str) -> PlatformNotification | None:
        notification = self.session.get(PlatformNotification, notification_id)
        if notification is None:
            return None
        if role != "owner" and notification.user_id != user_id:
            return None
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        self.session.flush()
        return notification

    def create_security_event(
        self,
        *,
        event_type: str,
        status: str,
        user_id: int | None = None,
        email: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_fingerprint: str | None = None,
        device_label: str | None = None,
        metadata: dict | None = None,
    ) -> PlatformSecurityEvent:
        entity = PlatformSecurityEvent(
            user_id=user_id,
            email=(email or "").strip().lower() or None,
            event_type=event_type,
            status=status,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            device_label=device_label,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def list_security_events(self, *, user_id: int | None = None, limit: int = 25) -> list[PlatformSecurityEvent]:
        stmt = select(PlatformSecurityEvent).order_by(PlatformSecurityEvent.id.desc()).limit(limit)
        if user_id is not None:
            stmt = (
                select(PlatformSecurityEvent)
                .where(PlatformSecurityEvent.user_id == user_id)
                .order_by(PlatformSecurityEvent.id.desc())
                .limit(limit)
            )
        return list(self.session.scalars(stmt))

    def has_seen_device(self, *, user_id: int, device_fingerprint: str | None) -> bool:
        if not device_fingerprint:
            return True
        stmt = select(PlatformSecurityEvent.id).where(
            PlatformSecurityEvent.user_id == user_id,
            PlatformSecurityEvent.device_fingerprint == device_fingerprint,
            PlatformSecurityEvent.event_type == "login_success",
        ).limit(1)
        return self.session.scalar(stmt) is not None

    def create_broker_account(
        self,
        *,
        owner_user_id: int,
        account_label: str,
        broker_name: str,
        platform_type: str,
        broker_server: str | None,
        login_reference: str | None,
        symbol_suffix: str | None,
        base_currency: str,
        is_demo: bool,
        connection_mode: str,
        allowed_symbols: list[str] | None = None,
        risk_profile: dict | None = None,
        notes: str | None = None,
    ) -> BrokerAccount:
        entity = BrokerAccount(
            owner_user_id=owner_user_id,
            account_label=account_label,
            broker_name=broker_name,
            platform_type=platform_type,
            broker_server=broker_server,
            login_reference=login_reference,
            symbol_suffix=symbol_suffix,
            base_currency=base_currency,
            is_demo=is_demo,
            connection_mode=connection_mode,
            allowed_symbols_json=json.dumps(allowed_symbols or [], ensure_ascii=False),
            risk_profile_json=json.dumps(risk_profile or {}, ensure_ascii=False),
            notes=notes,
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def update_broker_account(
        self,
        account: BrokerAccount,
        *,
        account_label: str,
        broker_server: str | None,
        login_reference: str | None,
        symbol_suffix: str | None,
        base_currency: str,
        is_demo: bool,
        allowed_symbols: list[str] | None = None,
        risk_profile: dict | None = None,
        notes: str | None = None,
    ) -> BrokerAccount:
        account.account_label = account_label
        account.broker_server = broker_server
        account.login_reference = login_reference
        account.symbol_suffix = symbol_suffix
        account.base_currency = base_currency
        account.is_demo = is_demo
        account.is_active = True
        account.allowed_symbols_json = json.dumps(allowed_symbols or [], ensure_ascii=False)
        account.risk_profile_json = json.dumps(risk_profile or {}, ensure_ascii=False)
        if notes is not None:
            account.notes = notes
        self.session.flush()
        return account

    def deactivate_broker_account(self, account: BrokerAccount, *, reason: str | None = None) -> BrokerAccount:
        account.is_active = False
        if reason:
            account.notes = f"{account.notes or ''}\nArchived: {reason}".strip()
        for agent in self.list_account_agents(account.id):
            agent.status = "archived"
        for deployment in self.list_account_deployments(account.id):
            deployment.deployment_status = "archived"
        grants = self.session.scalars(
            select(AccountAccessGrant).where(AccountAccessGrant.account_id == account.id)
        )
        for grant in grants:
            grant.is_active = False
        self.session.flush()
        return account

    def upsert_account_access_grant(
        self,
        *,
        account_id: int,
        user_id: int,
        permission_level: str,
        can_view: bool,
        can_trade: bool,
        can_manage_risk: bool,
        can_manage_learning: bool,
        notes: str | None = None,
    ) -> AccountAccessGrant:
        stmt = select(AccountAccessGrant).where(
            AccountAccessGrant.account_id == account_id,
            AccountAccessGrant.user_id == user_id,
        )
        entity = self.session.scalar(stmt)
        if entity is None:
            entity = AccountAccessGrant(
                account_id=account_id,
                user_id=user_id,
                permission_level=permission_level,
                can_view=can_view,
                can_trade=can_trade,
                can_manage_risk=can_manage_risk,
                can_manage_learning=can_manage_learning,
                notes=notes,
            )
            self.session.add(entity)
        else:
            entity.permission_level = permission_level
            entity.can_view = can_view
            entity.can_trade = can_trade
            entity.can_manage_risk = can_manage_risk
            entity.can_manage_learning = can_manage_learning
            entity.is_active = True
            if notes is not None:
                entity.notes = notes
        self.session.flush()
        return entity

    def create_execution_agent(
        self,
        *,
        account_id: int,
        agent_name: str,
        host_name: str,
        broker_name: str | None,
        platform_type: str = "MT5",
        capabilities: dict | None = None,
        notes: str | None = None,
    ) -> ExecutionAgent:
        entity = ExecutionAgent(
            account_id=account_id,
            agent_name=agent_name,
            agent_key=uuid4().hex,
            host_name=host_name,
            status="provisioned",
            last_heartbeat_at=datetime.now(timezone.utc),
            broker_name=broker_name,
            platform_type=platform_type,
            capabilities_json=json.dumps(capabilities or {}, ensure_ascii=False),
            notes=notes,
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def touch_agent_heartbeat(self, *, account_id: int, agent_key: str, status: str = "online") -> ExecutionAgent | None:
        agent = self.get_agent_by_key(account_id=account_id, agent_key=agent_key)
        if agent is None:
            return None
        agent.status = status
        agent.last_heartbeat_at = datetime.now(timezone.utc)
        self.session.flush()
        return agent

    def upsert_strategy_deployment(
        self,
        *,
        account_id: int,
        strategy_key: str,
        strategy_variant: str,
        operation_mode: str,
        risk_mode: str,
        learning_mode: str,
        deployment_status: str,
        symbol_allowlist: list[str] | None = None,
        source_bots: list[str] | None = None,
        notes: str | None = None,
    ) -> StrategyDeployment:
        stmt = select(StrategyDeployment).where(
            StrategyDeployment.account_id == account_id,
            StrategyDeployment.strategy_key == strategy_key,
        )
        entity = self.session.scalar(stmt)
        if entity is None:
            entity = StrategyDeployment(
                account_id=account_id,
                strategy_key=strategy_key,
                strategy_variant=strategy_variant,
                operation_mode=operation_mode,
                risk_mode=risk_mode,
                learning_mode=learning_mode,
                deployment_status=deployment_status,
                symbol_allowlist_json=json.dumps(symbol_allowlist or [], ensure_ascii=False),
                source_bots_json=json.dumps(source_bots or [], ensure_ascii=False),
                notes=notes,
            )
            self.session.add(entity)
        else:
            entity.strategy_variant = strategy_variant
            entity.operation_mode = operation_mode
            entity.risk_mode = risk_mode
            entity.learning_mode = learning_mode
            entity.deployment_status = deployment_status
            entity.symbol_allowlist_json = json.dumps(symbol_allowlist or [], ensure_ascii=False)
            entity.source_bots_json = json.dumps(source_bots or [], ensure_ascii=False)
            if notes is not None:
                entity.notes = notes
        self.session.flush()
        return entity

    def update_strategy_deployment_state(
        self,
        *,
        deployment_id: int,
        deployment_status: str | None = None,
        risk_mode: str | None = None,
        notes: str | None = None,
    ) -> StrategyDeployment | None:
        entity = self.get_deployment(deployment_id)
        if entity is None:
            return None
        if deployment_status is not None:
            entity.deployment_status = deployment_status
        if risk_mode is not None:
            entity.risk_mode = risk_mode
        if notes is not None:
            entity.notes = notes
        self.session.flush()
        return entity

    def upsert_learning_integration(
        self,
        *,
        owner_user_id: int,
        source_type: str,
        source_reference: str,
        source_label: str,
        enabled: bool = True,
        auto_sync: bool = True,
        ingestion_mode: str = "knowledge_first",
        sync_frequency_minutes: int = 30,
        notes: str | None = None,
    ) -> LearningIntegration:
        stmt = select(LearningIntegration).where(
            LearningIntegration.owner_user_id == owner_user_id,
            LearningIntegration.source_type == source_type,
            LearningIntegration.source_reference == source_reference,
        )
        entity = self.session.scalar(stmt)
        if entity is None:
            entity = LearningIntegration(
                owner_user_id=owner_user_id,
                source_type=source_type,
                source_reference=source_reference,
                source_label=source_label,
                enabled=enabled,
                auto_sync=auto_sync,
                ingestion_mode=ingestion_mode,
                sync_frequency_minutes=sync_frequency_minutes,
                notes=notes,
            )
            self.session.add(entity)
        else:
            entity.source_label = source_label
            entity.enabled = enabled
            entity.auto_sync = auto_sync
            entity.ingestion_mode = ingestion_mode
            entity.sync_frequency_minutes = sync_frequency_minutes
            if notes is not None:
                entity.notes = notes
        self.session.flush()
        return entity

    def upsert_symbol_alias(
        self,
        *,
        account_id: int,
        canonical_symbol: str,
        broker_symbol: str,
        notes: str | None = None,
    ) -> BrokerSymbolAlias:
        stmt = select(BrokerSymbolAlias).where(
            BrokerSymbolAlias.account_id == account_id,
            BrokerSymbolAlias.canonical_symbol == canonical_symbol,
        )
        entity = self.session.scalar(stmt)
        if entity is None:
            entity = BrokerSymbolAlias(
                account_id=account_id,
                canonical_symbol=canonical_symbol,
                broker_symbol=broker_symbol,
                notes=notes,
            )
            self.session.add(entity)
        else:
            entity.broker_symbol = broker_symbol
            entity.is_active = True
            if notes is not None:
                entity.notes = notes
        self.session.flush()
        return entity

    def create_api_credential(
        self,
        *,
        user_id: int,
        credential_label: str,
        token: str,
        notes: str | None = None,
    ) -> PlatformApiCredential:
        entity = PlatformApiCredential(
            user_id=user_id,
            credential_label=credential_label,
            token_hash=self._token_hash(token),
            token_preview=token[:8],
            notes=notes,
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def create_execution_agent_runtime_report(
        self,
        *,
        agent_id: int,
        account_id: int,
        cycle_status: str,
        canonical_symbol: str,
        broker_symbol: str,
        local_terminal_ready: bool,
        open_positions_count: int,
        service_root: dict | None = None,
        remote_agent: dict | None = None,
        heartbeat: dict | None = None,
        account_status: dict | None = None,
        execution_environment: dict | None = None,
        deployment_runs: list[dict] | None = None,
        notes: str | None = None,
    ) -> ExecutionAgentRuntimeReport:
        entity = ExecutionAgentRuntimeReport(
            agent_id=agent_id,
            account_id=account_id,
            cycle_status=cycle_status,
            canonical_symbol=canonical_symbol,
            broker_symbol=broker_symbol,
            local_terminal_ready=local_terminal_ready,
            open_positions_count=open_positions_count,
            service_root_json=json.dumps(service_root or {}, ensure_ascii=False),
            remote_agent_json=json.dumps(remote_agent or {}, ensure_ascii=False),
            heartbeat_json=json.dumps(heartbeat or {}, ensure_ascii=False),
            account_status_json=json.dumps(account_status or {}, ensure_ascii=False),
            execution_environment_json=json.dumps(execution_environment or {}, ensure_ascii=False),
            deployment_runs_json=json.dumps(deployment_runs or [], ensure_ascii=False),
            notes=notes,
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def create_deployment_execution_report(
        self,
        *,
        agent_id: int,
        account_id: int,
        strategy_key: str,
        strategy_variant: str | None,
        operation_mode: str | None,
        canonical_symbol: str | None,
        broker_symbol: str | None,
        run_status: str,
        execution_status: str | None,
        intelligence_action: str | None,
        signal_detected: bool | None,
        dry_run: bool | None,
        payload: dict | None = None,
    ) -> DeploymentExecutionReport:
        entity = DeploymentExecutionReport(
            agent_id=agent_id,
            account_id=account_id,
            strategy_key=strategy_key,
            strategy_variant=strategy_variant,
            operation_mode=operation_mode,
            canonical_symbol=canonical_symbol,
            broker_symbol=broker_symbol,
            run_status=run_status,
            execution_status=execution_status,
            intelligence_action=intelligence_action,
            signal_detected=signal_detected,
            dry_run=dry_run,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def get_api_credential_by_token(self, token: str) -> PlatformApiCredential | None:
        stmt = select(PlatformApiCredential).where(
            PlatformApiCredential.token_hash == self._token_hash(token),
            PlatformApiCredential.status == "active",
        )
        return self.session.scalar(stmt)

    def touch_api_credential_usage(self, token: str) -> PlatformApiCredential | None:
        credential = self.get_api_credential_by_token(token)
        if credential is None:
            return None
        credential.last_used_at = datetime.now(timezone.utc)
        self.session.flush()
        return credential

    def summarize(self, *, account_ids: list[int] | None = None, include_learning: bool = True) -> dict:
        scoped_account_ids = set(account_ids or []) if account_ids is not None else None
        accounts_stmt = select(BrokerAccount).where(BrokerAccount.is_active.is_(True)).order_by(BrokerAccount.id.asc())
        agents_stmt = select(ExecutionAgent).order_by(ExecutionAgent.id.asc())
        deployments_stmt = select(StrategyDeployment).order_by(StrategyDeployment.id.asc())
        runtime_reports_stmt = select(ExecutionAgentRuntimeReport).order_by(ExecutionAgentRuntimeReport.id.desc()).limit(8)
        deployment_reports_stmt = select(DeploymentExecutionReport).order_by(DeploymentExecutionReport.id.desc()).limit(12)

        if scoped_account_ids is not None:
            account_id_list = sorted(scoped_account_ids)
            accounts_stmt = accounts_stmt.where(BrokerAccount.id.in_(account_id_list))
            agents_stmt = agents_stmt.where(ExecutionAgent.account_id.in_(account_id_list))
            deployments_stmt = deployments_stmt.where(StrategyDeployment.account_id.in_(account_id_list))
            runtime_reports_stmt = runtime_reports_stmt.where(ExecutionAgentRuntimeReport.account_id.in_(account_id_list))
            deployment_reports_stmt = deployment_reports_stmt.where(DeploymentExecutionReport.account_id.in_(account_id_list))

        accounts = list(self.session.scalars(accounts_stmt))
        agents = list(self.session.scalars(agents_stmt))
        deployments = list(self.session.scalars(deployments_stmt))
        runtime_reports = list(self.session.scalars(runtime_reports_stmt))
        deployment_reports = list(self.session.scalars(deployment_reports_stmt))
        learning_integrations = (
            list(self.session.scalars(select(LearningIntegration).order_by(LearningIntegration.id.asc())))
            if include_learning
            else []
        )

        visible_account_ids = {item.id for item in accounts}
        visible_owner_ids = {item.owner_user_id for item in accounts}
        agents = [item for item in agents if item.account_id in visible_account_ids]
        deployments = [item for item in deployments if item.account_id in visible_account_ids]
        runtime_reports = [item for item in runtime_reports if item.account_id in visible_account_ids]
        deployment_reports = [item for item in deployment_reports if item.account_id in visible_account_ids]
        latest_runtime_reports = runtime_reports
        latest_deployment_reports = deployment_reports
        if visible_account_ids:
            latest_runtime_subquery = (
                select(
                    ExecutionAgentRuntimeReport.account_id,
                    func.max(ExecutionAgentRuntimeReport.id).label("latest_id"),
                )
                .where(ExecutionAgentRuntimeReport.account_id.in_(sorted(visible_account_ids)))
                .group_by(ExecutionAgentRuntimeReport.account_id)
                .subquery()
            )
            latest_runtime_reports = list(
                self.session.scalars(
                    select(ExecutionAgentRuntimeReport)
                    .join(latest_runtime_subquery, ExecutionAgentRuntimeReport.id == latest_runtime_subquery.c.latest_id)
                    .order_by(ExecutionAgentRuntimeReport.id.desc())
                )
            )
            latest_deployment_subquery = (
                select(
                    DeploymentExecutionReport.account_id,
                    func.max(DeploymentExecutionReport.id).label("latest_id"),
                )
                .where(DeploymentExecutionReport.account_id.in_(sorted(visible_account_ids)))
                .group_by(DeploymentExecutionReport.account_id)
                .subquery()
            )
            latest_deployment_reports = list(
                self.session.scalars(
                    select(DeploymentExecutionReport)
                    .join(latest_deployment_subquery, DeploymentExecutionReport.id == latest_deployment_subquery.c.latest_id)
                    .order_by(DeploymentExecutionReport.id.desc())
                )
            )
        symbol_aliases_count_stmt = select(func.count()).select_from(BrokerSymbolAlias)
        if visible_account_ids:
            symbol_aliases_count_stmt = symbol_aliases_count_stmt.where(BrokerSymbolAlias.account_id.in_(sorted(visible_account_ids)))
        else:
            symbol_aliases_count_stmt = symbol_aliases_count_stmt.where(BrokerSymbolAlias.account_id == -1)

        counts = {
            "users": self.session.scalar(select(func.count()).select_from(PlatformUser)) if scoped_account_ids is None else len(visible_owner_ids),
            "accounts": len(accounts),
            "agents": len(agents),
            "deployments": len(deployments),
            "learning_integrations": len(learning_integrations),
            "symbol_aliases": self.session.scalar(symbol_aliases_count_stmt) or 0,
        }
        operation_modes = Counter(item.operation_mode for item in deployments)
        risk_modes = Counter(item.risk_mode for item in deployments)
        latest_cycle_by_account: dict[int, ExecutionAgentRuntimeReport] = {}
        latest_run_by_account: dict[int, DeploymentExecutionReport] = {}
        for item in latest_runtime_reports:
            latest_cycle_by_account.setdefault(item.account_id, item)
        for item in latest_deployment_reports:
            latest_run_by_account.setdefault(item.account_id, item)

        online_agents_count = sum(1 for item in agents if item.status == "online")
        executed_runs_count = sum(1 for item in deployment_reports if item.run_status == "executed")
        watch_runs_count = sum(1 for item in deployment_reports if item.intelligence_action == "WATCH")
        signal_runs_count = sum(1 for item in deployment_reports if item.signal_detected is True)
        latest_execution_status = deployment_reports[0].execution_status if deployment_reports else None
        latest_ai_action = deployment_reports[0].intelligence_action if deployment_reports else None
        agents_by_account: dict[int, list[ExecutionAgent]] = {}
        for agent in agents:
            agents_by_account.setdefault(agent.account_id, []).append(agent)
        users_by_id = {item.id: item for item in self.list_users(limit=500)}

        def parse_json_dict(raw_value: str | None) -> dict:
            if not raw_value:
                return {}
            try:
                payload = json.loads(raw_value)
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}

        def account_financial_metrics(account: BrokerAccount) -> dict:
            latest_cycle = latest_cycle_by_account.get(account.id)
            account_status = parse_json_dict(latest_cycle.account_status_json if latest_cycle else None)
            account_info = account_status.get("account_info") if isinstance(account_status.get("account_info"), dict) else {}
            expected_login = str(account.login_reference or "").strip()
            actual_login = str(account_info.get("login") or "").strip()
            expected_server = str(account.broker_server or "").strip().lower()
            actual_server = str(account_info.get("server") or "").strip().lower()
            mismatch = bool(
                account_info
                and (
                    (expected_login and actual_login != expected_login)
                    or (expected_server and actual_server != expected_server)
                )
            )
            if mismatch:
                return {
                    "balance": None,
                    "equity": None,
                    "profit": None,
                    "margin": None,
                    "margin_free": None,
                    "currency": str(account_info.get("currency") or "USD"),
                    "growth_amount": None,
                    "growth_percent": None,
                    "source": "terminal_account_mismatch",
                    "reported_at": latest_cycle.created_at.isoformat() if latest_cycle and latest_cycle.created_at else None,
                }
            balance = self._optional_float(account_info.get("balance"))
            equity = self._optional_float(account_info.get("equity"))
            profit = self._optional_float(account_info.get("profit"))
            margin = self._optional_float(account_info.get("margin"))
            margin_free = self._optional_float(account_info.get("margin_free"))
            currency = str(account_info.get("currency") or "USD")
            growth_amount = (equity - balance) if equity is not None and balance is not None else profit
            growth_percent = (
                (growth_amount / balance) * 100.0
                if growth_amount is not None and balance not in {None, 0.0}
                else None
            )
            return {
                "balance": round(balance, 2) if balance is not None else None,
                "equity": round(equity, 2) if equity is not None else None,
                "profit": round(profit, 2) if profit is not None else None,
                "margin": round(margin, 2) if margin is not None else None,
                "margin_free": round(margin_free, 2) if margin_free is not None else None,
                "currency": currency,
                "growth_amount": round(growth_amount, 2) if growth_amount is not None else None,
                "growth_percent": round(growth_percent, 4) if growth_percent is not None else None,
                "source": "mt5_account_status" if account_info else "not_reported",
                "reported_at": latest_cycle.created_at.isoformat() if latest_cycle and latest_cycle.created_at else None,
            }

        def account_runtime_health(account: BrokerAccount) -> str:
            latest_cycle = latest_cycle_by_account.get(account.id)
            latest_run = latest_run_by_account.get(account.id)
            if latest_run and latest_run.execution_status == "blocked_by_terminal_account_mismatch":
                return "account_mismatch"
            if latest_cycle and latest_cycle.local_terminal_ready:
                return "running"
            if latest_cycle:
                return "terminal_not_ready"
            if agents_by_account.get(account.id):
                return "agent_ready"
            return "waiting_for_agent"

        account_metrics_by_id = {item.id: account_financial_metrics(item) for item in accounts}
        reported_metrics = [item for item in account_metrics_by_id.values() if item["source"] == "mt5_account_status"]
        total_balance = sum(float(item["balance"] or 0.0) for item in reported_metrics)
        total_equity = sum(float(item["equity"] or 0.0) for item in reported_metrics)
        total_profit = sum(float(item["profit"] or 0.0) for item in reported_metrics)
        total_margin = sum(float(item["margin"] or 0.0) for item in reported_metrics)
        total_margin_free = sum(float(item["margin_free"] or 0.0) for item in reported_metrics)
        total_growth_amount = total_equity - total_balance
        total_growth_percent = (total_growth_amount / total_balance) * 100.0 if total_balance else None

        return {
            "counts": counts,
            "users_detail": [
                {
                    "id": item.id,
                    "email": item.email,
                    "display_name": item.display_name,
                    "role": item.role,
                    "status": item.status,
                    "timezone_name": item.timezone_name,
                    "max_broker_accounts": item.max_broker_accounts,
                    "password_enabled": bool(item.password_hash),
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in (self.list_users(limit=100) if scoped_account_ids is None else [])
            ],
            "accounts": [
                {
                    "id": item.id,
                    "owner_user_id": item.owner_user_id,
                    "owner_email": users_by_id.get(item.owner_user_id).email if users_by_id.get(item.owner_user_id) else None,
                    "owner_display_name": users_by_id.get(item.owner_user_id).display_name if users_by_id.get(item.owner_user_id) else None,
                    "label": item.account_label,
                    "broker_name": item.broker_name,
                    "platform_type": item.platform_type,
                    "is_demo": item.is_demo,
                    "symbol_suffix": item.symbol_suffix,
                    "connection_mode": item.connection_mode,
                    "agent_count": len(agents_by_account.get(item.id, [])),
                    "agent_status": agents_by_account.get(item.id, [None])[0].status if agents_by_account.get(item.id) else None,
                    "latest_cycle_status": latest_cycle_by_account.get(item.id).cycle_status if latest_cycle_by_account.get(item.id) else None,
                    "latest_broker_symbol": latest_cycle_by_account.get(item.id).broker_symbol if latest_cycle_by_account.get(item.id) else None,
                    "latest_terminal_ready": latest_cycle_by_account.get(item.id).local_terminal_ready if latest_cycle_by_account.get(item.id) else None,
                    "latest_ai_action": latest_run_by_account.get(item.id).intelligence_action if latest_run_by_account.get(item.id) else None,
                    "latest_execution_status": latest_run_by_account.get(item.id).execution_status if latest_run_by_account.get(item.id) else None,
                    "runtime_health": account_runtime_health(item),
                    "financial_metrics": account_metrics_by_id.get(item.id, {}),
                }
                for item in accounts
            ],
            "agents": [
                {
                    "id": item.id,
                    "account_id": item.account_id,
                    "agent_name": item.agent_name,
                    "host_name": item.host_name,
                    "status": item.status,
                    "platform_type": item.platform_type,
                    "broker_name": item.broker_name,
                    "last_heartbeat_at": item.last_heartbeat_at.isoformat() if item.last_heartbeat_at else None,
                }
                for item in agents
            ],
            "deployments": [
                {
                    "id": item.id,
                    "account_id": item.account_id,
                    "strategy_key": item.strategy_key,
                    "strategy_variant": item.strategy_variant,
                    "operation_mode": item.operation_mode,
                    "risk_mode": item.risk_mode,
                    "learning_mode": item.learning_mode,
                    "deployment_status": item.deployment_status,
                    "symbol_allowlist": json.loads(item.symbol_allowlist_json or "[]"),
                    "source_bots": json.loads(item.source_bots_json or "[]"),
                }
                for item in deployments
            ],
            "learning_integrations_detail": [
                {
                    "id": item.id,
                    "owner_user_id": item.owner_user_id,
                    "source_type": item.source_type,
                    "source_label": item.source_label,
                    "enabled": item.enabled,
                    "auto_sync": item.auto_sync,
                    "ingestion_mode": item.ingestion_mode,
                    "sync_frequency_minutes": item.sync_frequency_minutes,
                    "last_sync_at": item.last_sync_at.isoformat() if item.last_sync_at else None,
                }
                for item in learning_integrations
            ],
            "recent_agent_cycles": [
                {
                    "id": item.id,
                    "agent_id": item.agent_id,
                    "account_id": item.account_id,
                    "cycle_status": item.cycle_status,
                    "canonical_symbol": item.canonical_symbol,
                    "broker_symbol": item.broker_symbol,
                    "local_terminal_ready": item.local_terminal_ready,
                    "open_positions_count": item.open_positions_count,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in runtime_reports
            ],
            "recent_deployment_runs": [
                {
                    "id": item.id,
                    "agent_id": item.agent_id,
                    "account_id": item.account_id,
                    "strategy_key": item.strategy_key,
                    "strategy_variant": item.strategy_variant,
                    "operation_mode": item.operation_mode,
                    "canonical_symbol": item.canonical_symbol,
                    "broker_symbol": item.broker_symbol,
                    "run_status": item.run_status,
                    "execution_status": item.execution_status,
                    "intelligence_action": item.intelligence_action,
                    "signal_detected": item.signal_detected,
                    "dry_run": item.dry_run,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in deployment_reports
            ],
            "activity_summary": {
                "online_agents": online_agents_count,
                "recent_agent_cycles": len(runtime_reports),
                "recent_deployment_runs": len(deployment_reports),
                "executed_runs": executed_runs_count,
                "watch_runs": watch_runs_count,
                "signal_runs": signal_runs_count,
                "latest_execution_status": latest_execution_status,
                "latest_ai_action": latest_ai_action,
            },
            "portfolio_metrics": {
                "accounts_reported": len(reported_metrics),
                "total_balance": round(total_balance, 2),
                "total_equity": round(total_equity, 2),
                "total_profit": round(total_profit, 2),
                "total_margin": round(total_margin, 2),
                "total_margin_free": round(total_margin_free, 2),
                "growth_amount": round(total_growth_amount, 2),
                "growth_percent": round(total_growth_percent, 4) if total_growth_percent is not None else None,
                "currency": reported_metrics[0]["currency"] if reported_metrics else "USD",
                "source": "mt5_account_status",
            },
            "operation_modes": dict(operation_modes),
            "risk_modes": dict(risk_modes),
        }

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _optional_float(value) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
