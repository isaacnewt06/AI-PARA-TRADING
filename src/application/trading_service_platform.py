"""Application service for the multi-user AI trading service platform."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import (
    ChunkEmbedding,
    ContentChunk,
    ExtractedRule,
    NormalizedRule,
    StrategyCandidate,
    StrategyPlaybook,
    TopStrategyDetected,
)
from src.db.models.platform import LearningIntegration
from src.db.repositories.platform import PlatformRepository


class TradingServicePlatformApplicationService:
    """Provision the first platform layer for broker-connected AI trading."""

    DEFAULT_STRATEGY_KEY = "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4"
    DEFAULT_STRATEGY_VARIANT = "v56_aggressive_filtered_b"
    PASSWORD_SCHEME = "pbkdf2_sha256"
    PASSWORD_ITERATIONS = 210_000
    STRATEGY_KEY_ALIASES = {
        "MAXIMO MTF Quant Institutional v4": DEFAULT_STRATEGY_KEY,
        "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4": DEFAULT_STRATEGY_KEY,
    }

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = PlatformRepository(session)

    def bootstrap_platform(
        self,
        *,
        owner_email: str,
        owner_name: str,
        timezone_name: str = "America/Santo_Domingo",
        owner_password: str | None = None,
    ) -> dict:
        owner = self.repository.create_or_update_user(
            email=owner_email,
            display_name=owner_name,
            role="owner",
            status="active",
            timezone_name=timezone_name,
            password_hash=self._hash_password(owner_password) if owner_password else None,
            notes="Platform owner and service operator.",
        )

        learning_integrations = 0
        for channel in self.repository.list_active_channels():
            self.repository.upsert_learning_integration(
                owner_user_id=owner.id,
                source_type="telegram_channel",
                source_reference=channel.input_reference,
                source_label=channel.title,
                enabled=True,
                auto_sync=True,
                ingestion_mode="knowledge_first",
                sync_frequency_minutes=30,
                notes="Imported from existing channel registry.",
            )
            learning_integrations += 1

        local_education_path = self.settings.project_root / "TRADING EDUCATION"
        if local_education_path.exists():
            self.repository.upsert_learning_integration(
                owner_user_id=owner.id,
                source_type="local_education",
                source_reference=f"local-education://{local_education_path.name.lower()}",
                source_label=f"Local Education - {local_education_path.name}",
                enabled=True,
                auto_sync=True,
                ingestion_mode="knowledge_first",
                sync_frequency_minutes=120,
                notes="Continuous local course ingestion source.",
            )
            learning_integrations += 1

        manual_path = self.settings.paths.data_dir / "knowledge" / "manual"
        self.repository.upsert_learning_integration(
            owner_user_id=owner.id,
            source_type="manual_knowledge",
            source_reference="manual://knowledge",
            source_label="Manual Knowledge",
            enabled=True,
            auto_sync=True,
            ingestion_mode="knowledge_first",
            sync_frequency_minutes=240,
            notes=f"Manual notes path: {manual_path}",
        )
        learning_integrations += 1

        return {
            "owner_user_id": owner.id,
            "owner_email": owner.email,
            "learning_integrations_seeded": learning_integrations,
            "platform_status": self.repository.summarize(),
        }

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        role: str = "client",
        status: str = "active",
        timezone_name: str = "America/Santo_Domingo",
        max_broker_accounts: int = 1,
        password: str | None = None,
        notes: str | None = None,
    ) -> dict:
        user = self.repository.create_or_update_user(
            email=email,
            display_name=display_name,
            role=role,
            status=status,
            timezone_name=timezone_name,
            max_broker_accounts=max_broker_accounts,
            password_hash=self._hash_password(password) if password else None,
            notes=notes,
        )
        return {
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "status": user.status,
            "timezone_name": user.timezone_name,
            "max_broker_accounts": user.max_broker_accounts,
            "password_enabled": bool(user.password_hash),
        }

    def register_client(self, *, email: str, display_name: str, password: str, timezone_name: str = "America/Santo_Domingo") -> dict:
        user = self.repository.create_or_update_user(
            email=email,
            display_name=display_name,
            role="client",
            status="pending",
            timezone_name=timezone_name,
            max_broker_accounts=1,
            password_hash=self._hash_password(password),
            notes="Self-registered client pending owner approval.",
        )
        self._notify_owners(
            title="Nuevo cliente solicitó acceso",
            message=f"{user.display_name} ({user.email}) creó una solicitud y espera aprobación.",
            category="client_registration",
            severity="critical",
            metadata={"user_id": user.id, "email": user.email, "status": user.status},
        )
        return {
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "status": user.status,
            "max_broker_accounts": user.max_broker_accounts,
            "message": "Registro recibido. Tu acceso queda pendiente hasta que el administrador lo active.",
        }

    def update_user_status(self, *, user_id: int, status: str) -> dict:
        if status not in {"active", "pending", "suspended"}:
            raise ValueError("Invalid user status.")
        user = self.repository.update_user_status(user_id=user_id, status=status)
        if user is None:
            raise ValueError(f"User not found for user_id={user_id}")
        return {
            "user_id": user.id,
            "email": user.email,
            "role": user.role,
            "status": user.status,
        }

    def update_user_account_limit(self, *, user_id: int, max_broker_accounts: int) -> dict:
        if max_broker_accounts < 1:
            raise ValueError("Account limit must be at least 1.")
        user = self.repository.update_user_account_limit(
            user_id=user_id,
            max_broker_accounts=max_broker_accounts,
        )
        if user is None:
            raise ValueError(f"User not found for user_id={user_id}")
        active_accounts = len(self.repository.list_owner_accounts(user.id))
        return {
            "user_id": user.id,
            "email": user.email,
            "role": user.role,
            "max_broker_accounts": user.max_broker_accounts,
            "active_accounts": active_accounts,
            "remaining_slots": max(0, user.max_broker_accounts - active_accounts),
        }

    def set_user_password(self, *, user_email: str, password: str) -> dict:
        user = self._require_user(user_email)
        updated = self.repository.set_user_password_hash(
            user_id=user.id,
            password_hash=self._hash_password(password),
        )
        if updated is None:
            raise ValueError(f"User not found for email={user_email}")
        return {
            "user_id": updated.id,
            "user_email": updated.email,
            "password_enabled": True,
            "password_updated_at": updated.password_updated_at.isoformat() if updated.password_updated_at else None,
        }

    def request_password_reset(
        self,
        *,
        email: str,
        request_ip: str | None = None,
        request_user_agent: str | None = None,
        device_fingerprint: str | None = None,
        device_label: str | None = None,
    ) -> dict:
        normalized_email = email.strip().lower()
        user = self.repository.get_user_by_email(normalized_email)
        self.repository.create_security_event(
            event_type="password_reset_requested",
            status="accepted" if user else "unknown_email",
            user_id=user.id if user else None,
            email=normalized_email,
            ip_address=request_ip,
            user_agent=request_user_agent,
            device_fingerprint=device_fingerprint,
            device_label=device_label,
        )
        if user is not None:
            token = f"rst_{secrets.token_urlsafe(32)}"
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            reset = self.repository.create_password_reset_token(
                user_id=user.id,
                token=token,
                expires_at=expires_at,
                request_ip=request_ip,
                request_user_agent=request_user_agent,
                notes="Password recovery requested from public login page.",
            )
            self._notify_owners(
                title="Solicitud de recuperación de contraseña",
                message=f"{user.display_name} ({user.email}) pidió recuperar su contraseña. Token temporal: {token}",
                category="password_reset",
                severity="critical",
                metadata={
                    "user_id": user.id,
                    "email": user.email,
                    "reset_token_preview": reset.token_preview,
                    "reset_token": token,
                    "expires_at": expires_at.isoformat(),
                    "request_ip": request_ip,
                    "device_label": device_label,
                },
            )
        return {
            "status": "received",
            "message": "Si el correo existe, se generó una solicitud de recuperación y el administrador fue notificado.",
            "delivery_mode": "owner_notification",
        }

    def reset_password_with_token(self, *, email: str, token: str, new_password: str) -> dict:
        user = self.repository.get_user_by_email(email)
        reset = self.repository.get_active_password_reset_token(token=token)
        if user is None or reset is None or reset.user_id != user.id:
            self.repository.create_security_event(
                event_type="password_reset_failed",
                status="invalid_token",
                email=email,
            )
            raise ValueError("Reset token inválido o expirado.")
        self.repository.set_user_password_hash(
            user_id=user.id,
            password_hash=self._hash_password(new_password),
        )
        self.repository.mark_password_reset_token_used(token_id=reset.id)
        self.repository.create_security_event(
            event_type="password_reset_completed",
            status="success",
            user_id=user.id,
            email=user.email,
        )
        self._notify_owners(
            title="Contraseña recuperada",
            message=f"{user.display_name} ({user.email}) completó una recuperación de contraseña.",
            category="password_reset",
            severity="info",
            metadata={"user_id": user.id, "email": user.email},
        )
        return {
            "status": "password_updated",
            "user_email": user.email,
            "message": "Contraseña actualizada. Ya puedes iniciar sesión.",
        }

    def connect_broker_account(
        self,
        *,
        owner_email: str,
        account_label: str,
        broker_name: str,
        platform_type: str = "MT5",
        broker_server: str | None = None,
        login_reference: str | None = None,
        symbol_suffix: str | None = None,
        base_currency: str = "USD",
        is_demo: bool = True,
        connection_mode: str = "local_agent",
        allowed_symbols: list[str] | None = None,
        risk_profile: dict | None = None,
        notes: str | None = None,
        source_bots: list[str] | None = None,
    ) -> dict:
        owner = self._require_user(owner_email)
        account = self.repository.create_broker_account(
            owner_user_id=owner.id,
            account_label=account_label,
            broker_name=broker_name,
            platform_type=platform_type,
            broker_server=broker_server,
            login_reference=login_reference,
            symbol_suffix=symbol_suffix,
            base_currency=base_currency,
            is_demo=is_demo,
            connection_mode=connection_mode,
            allowed_symbols=allowed_symbols or ["XAUUSD"],
            risk_profile=risk_profile or {"risk_mode": "reduced", "daily_loss_limit_r": 3.0},
            notes=notes,
        )

        self.repository.upsert_account_access_grant(
            account_id=account.id,
            user_id=owner.id,
            permission_level="owner",
            can_view=True,
            can_trade=True,
            can_manage_risk=True,
            can_manage_learning=True,
            notes="Owner full access.",
        )

        best_strategy = self._load_best_current_strategy()
        deployment = self.repository.upsert_strategy_deployment(
            account_id=account.id,
            strategy_key=best_strategy["strategy_key"],
            strategy_variant=best_strategy["strategy_variant"],
            operation_mode="ai_managed",
            risk_mode="reduced",
            learning_mode="continuous",
            deployment_status="active" if is_demo else "draft",
            symbol_allowlist=allowed_symbols or ["XAUUSD"],
            source_bots=source_bots or [],
            notes="Default deployment seeded from best current strategy snapshot.",
        )

        canonical_symbol = "XAUUSD"
        broker_symbol = canonical_symbol + symbol_suffix if symbol_suffix else canonical_symbol
        alias = self.repository.upsert_symbol_alias(
            account_id=account.id,
            canonical_symbol=canonical_symbol,
            broker_symbol=broker_symbol,
            notes=f"Seeded alias for {broker_name}.",
        )

        return {
            "account_id": account.id,
            "owner_user_id": owner.id,
            "strategy_deployment_id": deployment.id,
            "symbol_alias_id": alias.id,
            "broker_symbol": alias.broker_symbol,
            "is_demo": account.is_demo,
            "strategy_variant": deployment.strategy_variant,
            "operation_mode": deployment.operation_mode,
        }

    def connect_own_exness_account(
        self,
        *,
        user_id: int,
        account_label: str,
        broker_server: str | None = None,
        login_reference: str | None = None,
        symbol_suffix: str | None = "m",
        base_currency: str = "USD",
        is_demo: bool = True,
        referral_confirmed: bool = False,
        replace_account_id: int | None = None,
        notes: str | None = None,
    ) -> dict:
        user = self.repository.get_user_by_id(user_id)
        if user is None:
            raise ValueError("Authenticated user not found.")
        if not referral_confirmed:
            raise ValueError("Exness referral confirmation is required before connecting the account.")

        normalized_suffix = self._normalize_exness_symbol_suffix(symbol_suffix)
        normalized_login = (login_reference or "").strip() or None
        normalized_server = (broker_server or "").strip() or None
        active_accounts = self.repository.list_owner_accounts(user.id)
        account = None
        replacing_account = False
        if replace_account_id is not None:
            account = self.repository.get_account(replace_account_id)
            if account is None or account.owner_user_id != user.id or not account.is_active:
                raise ValueError("Selected account cannot be replaced by this client.")
            if account.broker_name.lower() != "exness":
                raise ValueError("Only Exness accounts can be replaced from the client portal.")
            replacing_account = True
        else:
            account = self._find_reusable_client_exness_account(
                user_id=user.id,
                broker_server=normalized_server,
                login_reference=normalized_login,
                account_label=account_label,
            )
        account_notes = notes or "Client self-service Exness account connected after referral onboarding."
        if account is None:
            if len(active_accounts) >= user.max_broker_accounts:
                raise ValueError(
                    "Account limit reached. Delete or replace an account, or ask the owner to increase your limit."
                )
            account = self.repository.create_broker_account(
                owner_user_id=user.id,
                account_label=account_label,
                broker_name="Exness",
                platform_type="MT5",
                broker_server=normalized_server,
                login_reference=normalized_login,
                symbol_suffix=normalized_suffix,
                base_currency=base_currency,
                is_demo=is_demo,
                connection_mode="local_agent",
                allowed_symbols=["XAUUSD"],
                risk_profile={"risk_mode": "reduced", "daily_loss_limit_r": 3.0},
                notes=account_notes,
            )
            account_created = True
        else:
            account = self.repository.update_broker_account(
                account,
                account_label=account_label,
                broker_server=normalized_server,
                login_reference=normalized_login,
                symbol_suffix=normalized_suffix,
                base_currency=base_currency,
                is_demo=is_demo,
                allowed_symbols=["XAUUSD"],
                risk_profile={"risk_mode": "reduced", "daily_loss_limit_r": 3.0},
                notes=account_notes,
            )
            account_created = False
        self.repository.upsert_account_access_grant(
            account_id=account.id,
            user_id=user.id,
            permission_level="owner",
            can_view=True,
            can_trade=True,
            can_manage_risk=False,
            can_manage_learning=False,
            notes="Client owns this connected Exness account.",
        )

        best_strategy = self._load_best_current_strategy()
        deployment = self.repository.upsert_strategy_deployment(
            account_id=account.id,
            strategy_key=best_strategy["strategy_key"],
            strategy_variant=best_strategy["strategy_variant"],
            operation_mode="ai_managed",
            risk_mode="reduced",
            learning_mode="continuous",
            deployment_status="active" if is_demo else "draft",
            symbol_allowlist=["XAUUSD"],
            source_bots=[],
            notes="Client self-service default deployment. Demo-first risk controls required.",
        )
        broker_symbol = "XAUUSD" + normalized_suffix
        alias = self.repository.upsert_symbol_alias(
            account_id=account.id,
            canonical_symbol="XAUUSD",
            broker_symbol=broker_symbol,
            notes="Default Exness XAUUSD suffix mapping.",
        )
        agents = self.repository.list_account_agents(account.id)
        if agents:
            agent = agents[0]
            agent_created = False
        else:
            agent = self.repository.create_execution_agent(
                account_id=account.id,
                agent_name=f"client-exness-{account.id}",
                host_name="client-local-agent",
                broker_name="Exness",
                platform_type="MT5",
                capabilities={
                    "mt5_execution": True,
                    "symbol_resolution": True,
                    "demo_first": True,
                    "client_self_service": True,
                },
                notes="Auto-provisioned agent credentials for client Exness account.",
            )
            agent_created = True
        self._notify_owners(
            title="Cuenta Exness conectada por cliente",
            message=f"{user.display_name} conectó {account.account_label} ({alias.broker_symbol}).",
            category="broker_account",
            severity="warning" if account_created else "info",
            metadata={
                "user_id": user.id,
                "account_id": account.id,
                "broker": account.broker_name,
                "broker_symbol": alias.broker_symbol,
                "is_demo": account.is_demo,
                "agent_id": agent.id,
            },
        )

        return {
            "account_id": account.id,
            "account_created": account_created,
            "account_replaced": replacing_account,
            "owner_user_id": user.id,
            "owner_email": user.email,
            "account_label": account.account_label,
            "broker_name": account.broker_name,
            "platform_type": account.platform_type,
            "is_demo": account.is_demo,
            "broker_symbol": alias.broker_symbol,
            "deployment_id": deployment.id,
            "strategy_variant": deployment.strategy_variant,
            "risk_mode": deployment.risk_mode,
            "referral_confirmed": referral_confirmed,
            "agent_id": agent.id,
            "agent_name": agent.agent_name,
            "agent_key": agent.agent_key,
            "agent_created": agent_created,
            "account_limit": user.max_broker_accounts,
            "active_accounts_count": len(self.repository.list_owner_accounts(user.id)),
            "remaining_account_slots": max(0, user.max_broker_accounts - len(self.repository.list_owner_accounts(user.id))),
            "runtime_health": "agent_ready",
        }

    def deactivate_own_broker_account(self, *, user_id: int, account_id: int) -> dict:
        user = self.repository.get_user_by_id(user_id)
        if user is None:
            raise ValueError("Authenticated user not found.")
        account = self.repository.get_account(account_id)
        if account is None or account.owner_user_id != user.id or not account.is_active:
            raise ValueError("Active account not found for this client.")
        archived = self.repository.deactivate_broker_account(
            account,
            reason="Client removed account from self-service portal.",
        )
        active_accounts = len(self.repository.list_owner_accounts(user.id))
        return {
            "account_id": archived.id,
            "status": "deactivated",
            "max_broker_accounts": user.max_broker_accounts,
            "active_accounts": active_accounts,
            "remaining_slots": max(0, user.max_broker_accounts - active_accounts),
        }

    def deactivate_broker_account_as_owner(self, *, account_id: int) -> dict:
        account = self.repository.get_account(account_id)
        if account is None or not account.is_active:
            raise ValueError("Active account not found.")
        archived = self.repository.deactivate_broker_account(
            account,
            reason="Owner archived account from management panel.",
        )
        owner = self.repository.get_user_by_id(archived.owner_user_id)
        active_accounts = len(self.repository.list_owner_accounts(archived.owner_user_id))
        return {
            "account_id": archived.id,
            "status": "archived",
            "owner_user_id": archived.owner_user_id,
            "owner_email": owner.email if owner else None,
            "active_accounts_for_owner": active_accounts,
        }

    def _normalize_exness_symbol_suffix(self, symbol_suffix: str | None) -> str:
        value = (symbol_suffix or "m").strip()
        if not value:
            return "m"
        upper = value.upper()
        if upper == "XAUUSD":
            return ""
        if upper.startswith("XAUUSD"):
            return value[6:]
        return value

    def _find_reusable_client_exness_account(
        self,
        *,
        user_id: int,
        broker_server: str | None,
        login_reference: str | None,
        account_label: str,
    ):
        label_key = account_label.strip().lower()
        for account in self.repository.list_owner_accounts(user_id):
            if account.broker_name.lower() != "exness":
                continue
            if login_reference and (account.login_reference or "").strip() == login_reference:
                return account
            if broker_server and (account.broker_server or "").strip() == broker_server and account.account_label.strip().lower() == label_key:
                return account
            if not login_reference and account.account_label.strip().lower() == label_key:
                return account
        return None

    def grant_account_access(
        self,
        *,
        account_id: int,
        grantee_email: str,
        permission_level: str = "operator",
        can_trade: bool = True,
        can_manage_risk: bool = False,
        can_manage_learning: bool = False,
        notes: str | None = None,
    ) -> dict:
        user = self._require_user(grantee_email)
        grant = self.repository.upsert_account_access_grant(
            account_id=account_id,
            user_id=user.id,
            permission_level=permission_level,
            can_view=True,
            can_trade=can_trade,
            can_manage_risk=can_manage_risk,
            can_manage_learning=can_manage_learning,
            notes=notes,
        )
        return {
            "grant_id": grant.id,
            "account_id": grant.account_id,
            "user_id": grant.user_id,
            "permission_level": grant.permission_level,
            "can_trade": grant.can_trade,
        }

    def register_execution_agent(
        self,
        *,
        account_id: int,
        agent_name: str,
        host_name: str,
        broker_name: str | None = None,
        capabilities: dict | None = None,
        notes: str | None = None,
    ) -> dict:
        agent = self.repository.create_execution_agent(
            account_id=account_id,
            agent_name=agent_name,
            host_name=host_name,
            broker_name=broker_name,
            capabilities=capabilities or {
                "mt5_execution": True,
                "symbol_resolution": True,
                "demo_first": True,
            },
            notes=notes,
        )
        return {
            "agent_id": agent.id,
            "agent_key": agent.agent_key,
            "status": agent.status,
            "account_id": agent.account_id,
        }

    def deploy_strategy_mode(
        self,
        *,
        account_id: int,
        strategy_key: str,
        strategy_variant: str,
        operation_mode: str,
        risk_mode: str,
        learning_mode: str,
        deployment_status: str = "active",
        symbol_allowlist: list[str] | None = None,
        source_bots: list[str] | None = None,
        notes: str | None = None,
    ) -> dict:
        deployment = self.repository.upsert_strategy_deployment(
            account_id=account_id,
            strategy_key=strategy_key,
            strategy_variant=strategy_variant,
            operation_mode=operation_mode,
            risk_mode=risk_mode,
            learning_mode=learning_mode,
            deployment_status=deployment_status,
            symbol_allowlist=symbol_allowlist or ["XAUUSD"],
            source_bots=source_bots or [],
            notes=notes,
        )
        return {
            "deployment_id": deployment.id,
            "account_id": deployment.account_id,
            "strategy_key": deployment.strategy_key,
            "strategy_variant": deployment.strategy_variant,
            "operation_mode": deployment.operation_mode,
            "risk_mode": deployment.risk_mode,
            "learning_mode": deployment.learning_mode,
        }

    def map_broker_symbol(
        self,
        *,
        account_id: int,
        canonical_symbol: str,
        broker_symbol: str,
        notes: str | None = None,
    ) -> dict:
        alias = self.repository.upsert_symbol_alias(
            account_id=account_id,
            canonical_symbol=canonical_symbol,
            broker_symbol=broker_symbol,
            notes=notes,
        )
        return {
            "symbol_alias_id": alias.id,
            "account_id": alias.account_id,
            "canonical_symbol": alias.canonical_symbol,
            "broker_symbol": alias.broker_symbol,
        }

    def issue_user_api_credential(
        self,
        *,
        user_email: str,
        credential_label: str,
        notes: str | None = None,
    ) -> dict:
        user = self._require_user(user_email)
        token = f"tbs_{uuid4().hex}"
        credential = self.repository.create_api_credential(
            user_id=user.id,
            credential_label=credential_label,
            token=token,
            notes=notes,
        )
        return {
            "credential_id": credential.id,
            "user_id": user.id,
            "user_email": user.email,
            "credential_label": credential.credential_label,
            "token": token,
            "token_preview": credential.token_preview,
            "status": credential.status,
        }

    def authenticate_user_api_credential(self, *, token: str) -> dict:
        credential = self.repository.touch_api_credential_usage(token)
        if credential is None:
            raise ValueError("Invalid API credential token.")
        user = self.repository.get_user_by_id(credential.user_id)
        if user is None:
            raise ValueError("Credential is linked to a missing user.")
        return {
            "credential_id": credential.id,
            "user_id": user.id,
            "user_email": user.email,
            "role": user.role,
            "status": credential.status,
        }

    def authenticate_user_password(
        self,
        *,
        email: str,
        password: str,
        request_ip: str | None = None,
        request_user_agent: str | None = None,
        device_fingerprint: str | None = None,
        device_label: str | None = None,
    ) -> dict:
        user = self.repository.get_user_by_email(email)
        if user is None or user.status != "active":
            self.repository.create_security_event(
                event_type="login_failed",
                status="invalid_user_or_status",
                email=email,
                ip_address=request_ip,
                user_agent=request_user_agent,
                device_fingerprint=device_fingerprint,
                device_label=device_label,
            )
            raise ValueError("Invalid email or password.")
        if not user.password_hash or not self._verify_password(password, user.password_hash):
            self.repository.create_security_event(
                event_type="login_failed",
                status="bad_password",
                user_id=user.id,
                email=user.email,
                ip_address=request_ip,
                user_agent=request_user_agent,
                device_fingerprint=device_fingerprint,
                device_label=device_label,
            )
            raise ValueError("Invalid email or password.")
        known_device = self.repository.has_seen_device(user_id=user.id, device_fingerprint=device_fingerprint)
        self.repository.touch_user_login(user_id=user.id)
        event = self.repository.create_security_event(
            event_type="login_success",
            status="known_device" if known_device else "new_device",
            user_id=user.id,
            email=user.email,
            ip_address=request_ip,
            user_agent=request_user_agent,
            device_fingerprint=device_fingerprint,
            device_label=device_label,
            metadata={"known_device": known_device},
        )
        if not known_device or user.role != "owner":
            self._notify_owners(
                title="Acceso a la plataforma",
                message=f"{user.display_name} inició sesión desde {device_label or 'dispositivo no identificado'} ({request_ip or 'IP desconocida'}).",
                category="login",
                severity="critical" if not known_device else "info",
                metadata={
                    "user_id": user.id,
                    "email": user.email,
                    "event_id": event.id,
                    "known_device": known_device,
                    "device_label": device_label,
                    "ip": request_ip,
                },
            )
        token_payload = self.issue_user_api_credential(
            user_email=user.email,
            credential_label="web-login-session",
            notes="Issued by email/password login.",
        )
        return {
            "credential_id": token_payload["credential_id"],
            "user_id": user.id,
            "user_email": user.email,
            "role": user.role,
            "status": user.status,
            "token": token_payload["token"],
            "token_preview": token_payload["token_preview"],
            "device_status": "known_device" if known_device else "new_device",
        }

    def notification_center(self, *, user_id: int, role: str) -> dict:
        notifications = self.repository.list_notifications_for_user(user_id=user_id, role=role, limit=40)
        security_events = self.repository.list_security_events(user_id=None if role == "owner" else user_id, limit=25)
        unread = [item for item in notifications if not item.is_read]
        critical_unread = [item for item in unread if item.severity == "critical"]

        def notification_payload(item) -> dict:
            return {
                "id": item.id,
                "audience": item.audience,
                "category": item.category,
                "severity": item.severity,
                "title": item.title,
                "message": item.message,
                "metadata": self._parse_json_dict(item.metadata_json),
                "is_read": item.is_read,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "read_at": item.read_at.isoformat() if item.read_at else None,
            }

        def event_payload(item) -> dict:
            return {
                "id": item.id,
                "user_id": item.user_id,
                "email": item.email,
                "event_type": item.event_type,
                "status": item.status,
                "ip_address": item.ip_address,
                "device_label": item.device_label,
                "device_fingerprint": item.device_fingerprint,
                "user_agent": item.user_agent,
                "metadata": self._parse_json_dict(item.metadata_json),
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }

        return {
            "unread_count": len(unread),
            "critical_unread_count": len(critical_unread),
            "notifications": [notification_payload(item) for item in notifications],
            "recent_security_events": [event_payload(item) for item in security_events],
        }

    def mark_notification_read(self, *, notification_id: int, user_id: int, role: str) -> dict:
        item = self.repository.mark_notification_read(notification_id=notification_id, user_id=user_id, role=role)
        if item is None:
            raise ValueError("Notification not found or not allowed.")
        return {"notification_id": item.id, "is_read": item.is_read, "read_at": item.read_at.isoformat() if item.read_at else None}

    def authorize_owner_role(self, *, role: str) -> None:
        if role != "owner":
            raise ValueError("Owner role required for this operation.")

    def authorize_account_view(
        self,
        *,
        account_id: int,
        user_id: int,
        role: str,
    ) -> None:
        if role == "owner":
            return
        grant = self.repository.get_account_access_grant(account_id=account_id, user_id=user_id)
        if grant is None or not grant.can_view:
            raise ValueError("User is not allowed to view this account.")

    def authorize_deployment_control(
        self,
        *,
        deployment_id: int,
        user_id: int,
        role: str,
    ) -> None:
        if role == "owner":
            return
        deployment = self.repository.get_deployment(deployment_id)
        if deployment is None:
            raise ValueError(f"Strategy deployment not found for deployment_id={deployment_id}")
        grant = self.repository.get_account_access_grant(account_id=deployment.account_id, user_id=user_id)
        if grant is None or not (grant.can_trade or grant.can_manage_risk):
            raise ValueError("User is not allowed to control this deployment.")

    def authenticate_execution_agent(
        self,
        *,
        account_id: int,
        agent_key: str,
    ) -> dict:
        agent = self.repository.get_agent_by_key(account_id=account_id, agent_key=agent_key)
        if agent is None:
            raise ValueError("Execution agent credentials are invalid.")
        account = agent.account
        deployments = self.repository.list_account_deployments(account_id)
        aliases = self.repository.list_account_symbol_aliases(account_id)
        return {
            "agent_id": agent.id,
            "account_id": agent.account_id,
            "agent_name": agent.agent_name,
            "status": agent.status,
            "broker_name": account.broker_name if account else agent.broker_name,
            "platform_type": agent.platform_type,
            "is_demo": account.is_demo if account else None,
            "broker_server": account.broker_server if account else None,
            "login_reference": account.login_reference if account else None,
            "strategy_deployments": [
                {
                    "strategy_key": item.strategy_key,
                    "strategy_key_canonical": self._canonical_strategy_key(item.strategy_key),
                    "strategy_variant": item.strategy_variant,
                    "operation_mode": item.operation_mode,
                    "risk_mode": item.risk_mode,
                    "deployment_status": item.deployment_status,
                    "symbol_allowlist": self._parse_json_list(item.symbol_allowlist_json),
                    "source_bots": self._parse_json_list(item.source_bots_json),
                }
                for item in deployments
            ],
            "symbol_aliases": [
                {
                    "canonical_symbol": item.canonical_symbol,
                    "broker_symbol": item.broker_symbol,
                }
                for item in aliases
            ],
        }

    def heartbeat_execution_agent(
        self,
        *,
        account_id: int,
        agent_key: str,
        status: str = "online",
    ) -> dict:
        agent = self.repository.touch_agent_heartbeat(account_id=account_id, agent_key=agent_key, status=status)
        if agent is None:
            raise ValueError("Execution agent credentials are invalid.")
        return {
            "agent_id": agent.id,
            "account_id": agent.account_id,
            "status": agent.status,
            "last_heartbeat_at": agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None,
        }

    def record_execution_agent_runtime(
        self,
        *,
        account_id: int,
        agent_key: str,
        cycle_status: str,
        canonical_symbol: str,
        broker_symbol: str,
        local_terminal_ready: bool,
        open_positions: list[dict] | None = None,
        service_root: dict | None = None,
        remote_agent: dict | None = None,
        heartbeat: dict | None = None,
        account_status: dict | None = None,
        execution_environment: dict | None = None,
        deployment_runs: list[dict] | None = None,
        notes: str | None = None,
    ) -> dict:
        agent = self.repository.get_agent_by_key(account_id=account_id, agent_key=agent_key)
        if agent is None:
            raise ValueError("Execution agent credentials are invalid.")

        runtime_report = self.repository.create_execution_agent_runtime_report(
            agent_id=agent.id,
            account_id=account_id,
            cycle_status=cycle_status,
            canonical_symbol=canonical_symbol,
            broker_symbol=broker_symbol,
            local_terminal_ready=local_terminal_ready,
            open_positions_count=len(open_positions or []),
            service_root=service_root,
            remote_agent=remote_agent,
            heartbeat=heartbeat,
            account_status=account_status,
            execution_environment=execution_environment,
            deployment_runs=deployment_runs,
            notes=notes,
        )

        deployment_report_ids: list[int] = []
        for run in deployment_runs or []:
            report = self.repository.create_deployment_execution_report(
                agent_id=agent.id,
                account_id=account_id,
                strategy_key=str(run.get("strategy_key") or "unknown_strategy"),
                strategy_variant=self._optional_str(run.get("strategy_variant")),
                operation_mode=self._optional_str(run.get("operation_mode")),
                canonical_symbol=self._optional_str(run.get("canonical_symbol")),
                broker_symbol=self._optional_str(run.get("broker_symbol")),
                run_status=str(run.get("status") or "unknown"),
                execution_status=self._optional_str(run.get("execution_status")),
                intelligence_action=self._optional_str(run.get("intelligence_action")),
                signal_detected=self._optional_bool(run.get("signal_detected")),
                dry_run=self._optional_bool(run.get("dry_run")),
                payload=run,
            )
            deployment_report_ids.append(report.id)

        return {
            "runtime_report_id": runtime_report.id,
            "agent_id": agent.id,
            "account_id": account_id,
            "cycle_status": runtime_report.cycle_status,
            "deployment_reports_created": len(deployment_report_ids),
            "deployment_report_ids": deployment_report_ids,
        }

    def platform_status(self) -> dict:
        summary = self.repository.summarize()
        summary["service_objective"] = (
            "Multi-user broker-connected AI trading platform with continuous learning, "
            "guarded execution and account-level permissions."
        )
        summary["current_best_strategy"] = self._load_best_current_strategy()
        summary["broker_onboarding"] = self.broker_onboarding()
        summary["security_summary"] = self.notification_center(user_id=0, role="owner") | {"notifications": [], "recent_security_events": []}
        return summary

    def platform_status_for_user(self, *, user_id: int, role: str) -> dict:
        if role == "owner":
            return self.platform_status()

        grants = self.repository.list_access_grants_for_user(user_id)
        visible_account_ids = []
        for item in grants:
            account = self.repository.get_account(item.account_id)
            if item.can_view and account is not None and account.is_active:
                visible_account_ids.append(item.account_id)
        summary = self.repository.summarize(account_ids=visible_account_ids, include_learning=False)
        summary["service_objective"] = (
            "Multi-user broker-connected AI trading platform with continuous learning, "
            "guarded execution and account-level permissions."
        )
        summary["current_best_strategy"] = self._load_best_current_strategy()
        summary["broker_onboarding"] = self.broker_onboarding()
        summary["permission_scope"] = {
            "role": role,
            "visible_account_ids": visible_account_ids,
            "learning_integrations_visible": False,
        }
        user = self.repository.get_user_by_id(user_id)
        max_accounts = user.max_broker_accounts if user else 1
        summary["account_policy"] = {
            "max_broker_accounts": max_accounts,
            "active_accounts": len(visible_account_ids),
            "remaining_slots": max(0, max_accounts - len(visible_account_ids)),
            "can_add_account": len(visible_account_ids) < max_accounts,
        }
        return summary

    def broker_onboarding(self) -> dict:
        referral_url = str(self.settings.exness_referral_url or "").strip()
        configured = bool(referral_url and "CONFIGURA_TU_LINK" not in referral_url)
        return {
            "primary_broker": "Exness",
            "referral_url": referral_url,
            "referral_configured": configured,
            "supported_platform": "MT5",
            "default_canonical_symbol": "XAUUSD",
            "default_exness_symbol_suffix": "m",
        }

    def platform_readiness(self) -> dict:
        """Audit whether the platform brain and execution shell are ready."""

        checks: list[dict] = []

        def add_check(component: str, status: str, summary: str, *, details: dict | None = None, blocking: bool = False) -> None:
            checks.append(
                {
                    "component": component,
                    "status": status,
                    "summary": summary,
                    "blocking": blocking,
                    "details": details or {},
                }
            )

        platform_summary = self.repository.summarize()
        knowledge_counts = self._knowledge_inventory_counts()
        raw_file_counts = self._raw_file_counts()
        artifacts = self._readiness_artifacts()
        best_strategy = self._load_best_current_strategy()
        learning_report = self._load_json_artifact(artifacts["learning_cycle_report_json"]["path"])
        latest_signal = self._load_json_artifact(artifacts["latest_signal_json"]["path"])

        add_check(
            "database",
            "OK",
            "La base de datos responde y las tablas principales son consultables.",
            details={
                "users": platform_summary["counts"].get("users", 0),
                "accounts": platform_summary["counts"].get("accounts", 0),
                "agents": platform_summary["counts"].get("agents", 0),
                "deployments": platform_summary["counts"].get("deployments", 0),
            },
        )

        content_chunks = knowledge_counts["content_chunks"]
        extracted_rules = knowledge_counts["extracted_rules"]
        normalized_rules = knowledge_counts["normalized_rules"]
        strategy_candidates = knowledge_counts["strategy_candidates"]
        if content_chunks and extracted_rules and normalized_rules:
            knowledge_status = "OK"
            knowledge_summary = "El cerebro tiene chunks, reglas extraídas y reglas normalizadas disponibles."
        elif content_chunks and extracted_rules:
            knowledge_status = "WARN"
            knowledge_summary = "Hay conocimiento extraído, pero falta normalización completa para máxima trazabilidad."
        else:
            knowledge_status = "WARN"
            knowledge_summary = "La base de conocimiento todavía no tiene suficiente material estructurado."
        add_check(
            "learned_knowledge",
            knowledge_status,
            knowledge_summary,
            details=knowledge_counts | {"raw_files_by_category": raw_file_counts},
            blocking=False,
        )

        enabled_integrations = self.session.scalar(
            select(func.count()).select_from(LearningIntegration).where(LearningIntegration.enabled.is_(True))
        ) or 0
        add_check(
            "continuous_learning",
            "OK" if enabled_integrations else "WARN",
            "Las fuentes de aprendizaje continuo están registradas." if enabled_integrations else "No hay fuentes activas de aprendizaje continuo registradas.",
            details={
                "enabled_learning_integrations": enabled_integrations,
                "learning_cycle_report": artifacts["learning_cycle_report_md"],
            },
            blocking=False,
        )

        failed_learning_phases = list(learning_report.get("failed_phases", []) or [])
        learning_status = str(learning_report.get("status") or "missing")
        files_by_processing = (learning_report.get("knowledge_after", {}) or {}).get("files_by_processing_status", {}) or {}
        queued_files = int(files_by_processing.get("queued") or 0)
        failed_files = int(files_by_processing.get("failed") or 0)
        ffmpeg_missing = int((learning_report.get("knowledge_after", {}) or {}).get("files_by_status", {}).get("ffmpeg_not_found") or 0)
        if not learning_report:
            learning_pipeline_status = "WARN"
            learning_pipeline_summary = "No hay reporte reciente del ciclo de aprendizaje; conviene correrlo antes de sesión."
        elif failed_learning_phases:
            learning_pipeline_status = "WARN"
            learning_pipeline_summary = "El ciclo de aprendizaje completó, pero dejó fases con advertencia que pueden reducir actualización de conocimiento."
        else:
            learning_pipeline_status = "OK"
            learning_pipeline_summary = "El ciclo de aprendizaje está generando reportes sin fases fallidas."
        add_check(
            "learning_pipeline_health",
            learning_pipeline_status,
            learning_pipeline_summary,
            details={
                "status": learning_status,
                "cycle_number": learning_report.get("cycle_number"),
                "failed_phases": failed_learning_phases[:5],
                "queued_files": queued_files,
                "failed_files": failed_files,
                "ffmpeg_not_found": ffmpeg_missing,
                "knowledge_delta": learning_report.get("knowledge_delta", {}),
            },
            blocking=False,
        )

        ffmpeg_path = self._resolve_binary_path(self.settings.ffmpeg_path)
        ffprobe_path = self._resolve_binary_path(self._derived_ffprobe_path(self.settings.ffmpeg_path))
        media_status = "OK" if ffmpeg_path and ffprobe_path else "WARN"
        add_check(
            "media_extraction_tools",
            media_status,
            "FFmpeg y FFprobe están disponibles para extraer audio/video hacia conocimiento."
            if media_status == "OK"
            else "Falta FFmpeg/FFprobe completo; los videos y audios pueden quedar en cola o marcar ffmpeg_not_found.",
            details={
                "configured_ffmpeg_path": self.settings.ffmpeg_path,
                "resolved_ffmpeg_path": ffmpeg_path,
                "resolved_ffprobe_path": ffprobe_path,
                "ffmpeg_not_found_assets": ffmpeg_missing,
            },
            blocking=False,
        )

        strategy_file_exists = Path(best_strategy["source_file"]).exists()
        strategy_variant = best_strategy.get("strategy_variant")
        add_check(
            "base_strategy",
            "OK" if strategy_file_exists and strategy_variant == self.DEFAULT_STRATEGY_VARIANT else "WARN",
            "La estrategia base v56_aggressive_filtered_b está disponible como candidata principal."
            if strategy_file_exists and strategy_variant == self.DEFAULT_STRATEGY_VARIANT
            else "La plataforma está usando fallback o una variante diferente; revisar snapshot de estrategia.",
            details=best_strategy | {"source_file_exists": strategy_file_exists},
            blocking=False,
        )

        market_map_ready = artifacts["market_situation_map_json"]["exists"] and artifacts["market_situation_map_md"]["exists"]
        add_check(
            "market_situation_map",
            "OK" if market_map_ready else "WARN",
            "El mapa de situaciones de mercado está disponible para armonizar contexto."
            if market_map_ready
            else "Falta market_situation_map JSON/MD; la inteligencia puede perder contexto aprendido.",
            details={
                "json": artifacts["market_situation_map_json"],
                "md": artifacts["market_situation_map_md"],
            },
            blocking=False,
        )

        harmonizer_ready = strategy_candidates > 0 and knowledge_counts["top_strategies_detected"] > 0
        add_check(
            "market_knowledge_harmonizer",
            "OK" if harmonizer_ready else "WARN",
            "Hay candidatos y estrategias detectadas para alimentar el harmonizer."
            if harmonizer_ready
            else "El harmonizer puede operar con menos fuerza porque faltan candidatos o rankings detectados.",
            details={
                "strategy_candidates": strategy_candidates,
                "top_strategies_detected": knowledge_counts["top_strategies_detected"],
                "strategy_playbooks": knowledge_counts["strategy_playbooks"],
            },
            blocking=False,
        )

        intelligence_recent = (
            artifacts["latest_market_intelligence_json"]["exists"]
            or artifacts["latest_market_overview_json"]["exists"]
            or artifacts["latest_signal_json"]["exists"]
            or artifacts["demo_report_md"]["exists"]
        )
        add_check(
            "market_intelligence",
            "OK" if intelligence_recent else "WARN",
            "Existen salidas recientes de inteligencia/demo engine para auditoría."
            if intelligence_recent
            else "Aún no hay salida de inteligencia guardada; ejecutar ciclo demo para refrescar.",
            details={
                "latest_market_intelligence": artifacts["latest_market_intelligence_json"],
                "latest_market_overview": artifacts["latest_market_overview_json"],
                "latest_signal": artifacts["latest_signal_json"],
                "demo_report": artifacts["demo_report_md"],
            },
            blocking=False,
        )

        active_accounts = platform_summary["counts"].get("accounts", 0)
        active_deployments = platform_summary["counts"].get("deployments", 0)
        registered_agents = platform_summary["counts"].get("agents", 0)
        execution_status = "OK" if active_accounts and active_deployments and registered_agents else "WARN"
        add_check(
            "execution_shell",
            execution_status,
            "Hay cuenta, deployment y agente registrados para ejecución controlada."
            if execution_status == "OK"
            else "Falta completar cuenta, deployment o agente antes de pruebas broker-side completas.",
            details={
                "accounts": active_accounts,
                "deployments": active_deployments,
                "agents": registered_agents,
                "latest_agent_cycles": len(platform_summary.get("recent_agent_cycles", [])),
                "latest_deployment_runs": len(platform_summary.get("recent_deployment_runs", [])),
            },
            blocking=False,
        )

        audit_ready = artifacts["decision_source_audit_jsonl"]["exists"]
        add_check(
            "decision_audit",
            "OK" if audit_ready else "WARN",
            "La auditoría de fuente de decisión está persistiendo ciclos."
            if audit_ready
            else "No existe decision_source_audit.jsonl; correr ciclos demo para validar persistencia real.",
            details={"decision_source_audit": artifacts["decision_source_audit_jsonl"]},
            blocking=False,
        )

        watch_performance_text = self._read_text_artifact(artifacts["watch_performance_report_md"]["path"])
        watch_classification = self._extract_report_field(watch_performance_text, "classification") or "UNKNOWN"
        if watch_classification == "TOO_LOOSE":
            watch_status = "FAIL"
            watch_summary = "El sistema WATCH parece demasiado permisivo; no debe escalarse a real sin endurecer filtros."
            watch_blocking = True
        elif watch_classification == "TOO_STRICT":
            watch_status = "WARN"
            watch_summary = "El sistema WATCH está protegiendo capital, pero puede estar dejando pasar oportunidades; observar en demo."
            watch_blocking = False
        elif watch_classification in {"BALANCED", "INSUFFICIENT_DATA"}:
            watch_status = "OK" if watch_classification == "BALANCED" else "WARN"
            watch_summary = (
                "La política WATCH está balanceada según el reporte actual."
                if watch_classification == "BALANCED"
                else "Aún faltan eventos suficientes para concluir si WATCH está balanceado."
            )
            watch_blocking = False
        else:
            watch_status = "WARN"
            watch_summary = "No se pudo clasificar el rendimiento WATCH; mantener validación demo."
            watch_blocking = False
        add_check(
            "watch_policy_balance",
            watch_status,
            watch_summary,
            details={
                "classification": watch_classification,
                "latest_action": latest_signal.get("intelligence_action"),
                "execution_status": latest_signal.get("execution_status"),
                "watch_policy_action": (latest_signal.get("watch_execution_policy", {}) or {}).get("watch_policy_action"),
                "watch_health": (latest_signal.get("active_watch_metrics", {}) or {}).get("watch_health"),
                "watch_probability_to_execute": (latest_signal.get("active_watch_metrics", {}) or {}).get("watch_probability_to_execute"),
            },
            blocking=watch_blocking,
        )

        failed = [item for item in checks if item["status"] == "FAIL"]
        warnings = [item for item in checks if item["status"] == "WARN"]
        overall_status = "NOT_READY" if failed else ("NEEDS_ATTENTION" if warnings else "READY")
        operational_clearance = (
            "demo_validation_ready"
            if overall_status in {"READY", "NEEDS_ATTENTION"} and active_accounts and active_deployments
            else "setup_required"
        )

        return {
            "overall_status": overall_status,
            "operational_clearance": operational_clearance,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "knowledge_counts": knowledge_counts,
            "raw_file_counts": raw_file_counts,
            "critical_artifacts": artifacts,
            "current_best_strategy": best_strategy,
            "summary": {
                "ok": sum(1 for item in checks if item["status"] == "OK"),
                "warn": len(warnings),
                "fail": len(failed),
                "blocking_failures": sum(1 for item in failed if item["blocking"]),
            },
        }

    def _load_json_artifact(self, path: str | Path) -> dict:
        artifact_path = Path(path)
        if not artifact_path.exists() or artifact_path.stat().st_size <= 0:
            return {}
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _read_text_artifact(self, path: str | Path) -> str:
        artifact_path = Path(path)
        if not artifact_path.exists() or artifact_path.stat().st_size <= 0:
            return ""
        try:
            return artifact_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    @staticmethod
    def _extract_report_field(text: str, key: str) -> str | None:
        prefix = f"- {key}:"
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(prefix):
                return stripped[len(prefix) :].strip()
        return None

    @staticmethod
    def _resolve_binary_path(value: str | None) -> str | None:
        if not value:
            return None
        path = Path(value)
        if path.exists():
            return str(path)
        found = shutil.which(value)
        return found

    @staticmethod
    def _derived_ffprobe_path(ffmpeg_path: str | None) -> str:
        if not ffmpeg_path:
            return "ffprobe"
        lower_path = ffmpeg_path.lower()
        if lower_path.endswith("ffmpeg.exe"):
            return ffmpeg_path[:-10] + "ffprobe.exe"
        if lower_path.endswith("ffmpeg"):
            return ffmpeg_path[:-6] + "ffprobe"
        return "ffprobe"

    def account_detail(self, *, account_id: int) -> dict:
        account = self.repository.get_account(account_id)
        if account is None:
            raise ValueError(f"Broker account not found for account_id={account_id}")

        owner = self.repository.get_user_by_id(account.owner_user_id)
        agents = self.repository.list_account_agents(account_id)
        deployments = self.repository.list_account_deployments(account_id)
        aliases = self.repository.list_account_symbol_aliases(account_id)
        runtime_reports = self.repository.list_account_runtime_reports(account_id, limit=8)
        deployment_reports = self.repository.list_account_deployment_reports(account_id, limit=8)
        agent_connection = self._build_account_agent_connection(
            account=account,
            agents=agents,
            aliases=aliases,
            runtime_reports=runtime_reports,
            deployment_reports=deployment_reports,
        )

        return {
            "account": {
                "id": account.id,
                "label": account.account_label,
                "broker_name": account.broker_name,
                "platform_type": account.platform_type,
                "broker_server": account.broker_server,
                "login_reference": account.login_reference,
                "symbol_suffix": account.symbol_suffix,
                "base_currency": account.base_currency,
                "is_demo": account.is_demo,
                "is_active": account.is_active,
                "connection_mode": account.connection_mode,
            },
            "owner": {
                "user_id": owner.id if owner else None,
                "email": owner.email if owner else None,
                "display_name": owner.display_name if owner else None,
            },
            "agents": [
                {
                    "id": item.id,
                    "agent_name": item.agent_name,
                    "host_name": item.host_name,
                    "status": item.status,
                    "platform_type": item.platform_type,
                    "last_heartbeat_at": item.last_heartbeat_at.isoformat() if item.last_heartbeat_at else None,
                }
                for item in agents
            ],
            "deployments": [
                {
                    "id": item.id,
                    "strategy_key": item.strategy_key,
                    "strategy_variant": item.strategy_variant,
                    "operation_mode": item.operation_mode,
                    "risk_mode": item.risk_mode,
                    "learning_mode": item.learning_mode,
                    "deployment_status": item.deployment_status,
                    "symbol_allowlist": self._parse_json_list(item.symbol_allowlist_json),
                    "source_bots": self._parse_json_list(item.source_bots_json),
                }
                for item in deployments
            ],
            "symbol_aliases": [
                {
                    "canonical_symbol": item.canonical_symbol,
                    "broker_symbol": item.broker_symbol,
                    "is_active": item.is_active,
                }
                for item in aliases
            ],
            "recent_agent_cycles": [
                {
                    "id": item.id,
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
                    "strategy_key": item.strategy_key,
                    "strategy_variant": item.strategy_variant,
                    "operation_mode": item.operation_mode,
                    "run_status": item.run_status,
                    "execution_status": item.execution_status,
                    "intelligence_action": item.intelligence_action,
                    "signal_detected": item.signal_detected,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in deployment_reports
            ],
            "agent_connection": agent_connection,
        }

    def _build_account_agent_connection(
        self,
        *,
        account,
        agents: list,
        aliases: list,
        runtime_reports: list,
        deployment_reports: list,
    ) -> dict:
        active_alias = next((item for item in aliases if item.is_active), None)
        canonical_symbol = active_alias.canonical_symbol if active_alias else "XAUUSD"
        broker_symbol = active_alias.broker_symbol if active_alias else f"XAUUSD{account.symbol_suffix or ''}"
        agent = agents[0] if agents else None
        latest_cycle = runtime_reports[0] if runtime_reports else None
        latest_run = deployment_reports[0] if deployment_reports else None
        account_status = self._parse_json_dict(latest_cycle.account_status_json if latest_cycle else None)
        account_info = account_status.get("account_info") if isinstance(account_status.get("account_info"), dict) else {}

        expected_login = str(account.login_reference or "").strip()
        expected_server = str(account.broker_server or "").strip()
        actual_login = str(account_info.get("login") or "").strip()
        actual_server = str(account_info.get("server") or "").strip()
        actual_equity = account_info.get("equity") or account_info.get("balance")

        blockers: list[str] = []
        if agent is None:
            blockers.append("agent_missing")
        if latest_cycle is None:
            blockers.append("waiting_for_agent_runtime")
        if expected_login and actual_login and actual_login != expected_login:
            blockers.append("login_reference_mismatch")
        if expected_server and actual_server and actual_server.lower() != expected_server.lower():
            blockers.append("broker_server_mismatch")
        if account_status and account_status.get("is_demo") is not True:
            blockers.append("terminal_not_demo")
        if latest_run and latest_run.execution_status == "blocked_by_terminal_account_mismatch":
            if "terminal_account_mismatch" not in blockers:
                blockers.append("terminal_account_mismatch")

        terminal_valid = bool(agent is not None and latest_cycle is not None and not blockers)
        if terminal_valid:
            terminal_status = "ready"
        elif "login_reference_mismatch" in blockers or "broker_server_mismatch" in blockers or "terminal_account_mismatch" in blockers:
            terminal_status = "account_mismatch"
        elif "agent_missing" in blockers:
            terminal_status = "agent_missing"
        elif "waiting_for_agent_runtime" in blockers:
            terminal_status = "waiting_for_agent"
        else:
            terminal_status = "blocked"

        agent_key = agent.agent_key if agent else ""
        base_command = (
            "python -m src.cli.main run-trading-service-agent "
            "--api-base-url http://127.0.0.1:8000 "
            f"--account-id {account.id} "
            f"--agent-key {agent_key} "
            f"--canonical-symbol {canonical_symbol} "
        )
        return {
            "expected": {
                "login_reference": expected_login or None,
                "broker_server": expected_server or None,
                "canonical_symbol": canonical_symbol,
                "broker_symbol": broker_symbol,
                "is_demo": bool(account.is_demo),
            },
            "actual": {
                "login": actual_login or None,
                "server": actual_server or None,
                "is_demo": account_status.get("is_demo") if account_status else None,
                "balance": account_info.get("balance"),
                "equity": actual_equity,
                "currency": account_info.get("currency"),
                "reported_at": latest_cycle.created_at.isoformat() if latest_cycle and latest_cycle.created_at else None,
            },
            "agent": {
                "id": agent.id if agent else None,
                "name": agent.agent_name if agent else None,
                "status": agent.status if agent else None,
                "last_heartbeat_at": agent.last_heartbeat_at.isoformat() if agent and agent.last_heartbeat_at else None,
            },
            "terminal_validation": {
                "valid": terminal_valid,
                "status": terminal_status,
                "blockers": blockers,
                "explanation": self._terminal_validation_explanation(
                    terminal_status=terminal_status,
                    expected_login=expected_login,
                    actual_login=actual_login,
                    expected_server=expected_server,
                    actual_server=actual_server,
                ),
            },
            "commands": {
                "dry_run": f"{base_command}--dry-run --cycles 999999 --sleep-seconds 20",
                "demo_execution": f"{base_command}--no-dry-run --confirm-demo --cycles 999999 --sleep-seconds 20",
            },
            "setup_steps": [
                f"Abrir MT5 en el equipo o VPS donde esta cuenta vaya a operar.",
                f"Iniciar sesion en MT5 con login {expected_login or 'registrado'} y servidor {expected_server or 'registrado'}.",
                f"Verificar que {broker_symbol} existe en Observacion de Mercado.",
                "Ejecutar el agente de esta cuenta; si MT5 reporta otro login, la ejecucion se bloquea para proteger cuentas cruzadas.",
            ],
        }

    @staticmethod
    def _terminal_validation_explanation(
        *,
        terminal_status: str,
        expected_login: str,
        actual_login: str,
        expected_server: str,
        actual_server: str,
    ) -> str:
        if terminal_status == "ready":
            return "MT5 esta reportando la misma cuenta registrada; esta cuenta puede recibir operaciones cuando la IA habilite EXECUTE."
        if terminal_status == "account_mismatch":
            return (
                "El agente esta corriendo, pero MT5 tiene otra cuenta abierta. "
                f"Esperado: {expected_login or 'sin login'} / {expected_server or 'sin servidor'}. "
                f"Actual: {actual_login or 'sin reporte'} / {actual_server or 'sin reporte'}."
            )
        if terminal_status == "agent_missing":
            return "La cuenta aun no tiene agente MT5 registrado."
        if terminal_status == "waiting_for_agent":
            return "La cuenta tiene agente, pero todavia no hay ciclos reportados desde MT5."
        return "La cuenta no esta lista para ejecutar hasta resolver los bloqueadores del terminal."

    def update_deployment_state(
        self,
        *,
        deployment_id: int,
        deployment_status: str | None = None,
        risk_mode: str | None = None,
        notes: str | None = None,
    ) -> dict:
        deployment = self.repository.update_strategy_deployment_state(
            deployment_id=deployment_id,
            deployment_status=deployment_status,
            risk_mode=risk_mode,
            notes=notes,
        )
        if deployment is None:
            raise ValueError(f"Strategy deployment not found for deployment_id={deployment_id}")
        return {
            "deployment_id": deployment.id,
            "account_id": deployment.account_id,
            "strategy_key": deployment.strategy_key,
            "strategy_variant": deployment.strategy_variant,
            "operation_mode": deployment.operation_mode,
            "risk_mode": deployment.risk_mode,
            "deployment_status": deployment.deployment_status,
            "notes": deployment.notes,
        }

    def _require_user(self, email: str):
        user = self.repository.get_user_by_email(email)
        if user is None:
            raise ValueError(f"User not found for email={email}")
        return user

    def _load_best_current_strategy(self) -> dict:
        snapshot_path = self.settings.paths.data_dir / "strategies" / "maximo_quant_v4_best_current.json"
        if not snapshot_path.exists():
            return {
                "strategy_key": self.DEFAULT_STRATEGY_KEY,
                "strategy_variant": self.DEFAULT_STRATEGY_VARIANT,
                "source_file": str(snapshot_path),
            }
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        strategy_name = payload.get("strategy_key") or payload.get("strategy_name") or self.DEFAULT_STRATEGY_KEY
        strategy_variant = (
            payload.get("strategy_variant")
            or payload.get("best_variant_code")
            or (payload.get("parameters") or {}).get("code")
            or self.DEFAULT_STRATEGY_VARIANT
        )
        return {
            "strategy_key": self._canonical_strategy_key(strategy_name),
            "strategy_display_name": payload.get("strategy_name") or strategy_name,
            "strategy_variant": strategy_variant,
            "session_variant": payload.get("session_variant"),
            "timeframe": payload.get("timeframe"),
            "source_file": str(snapshot_path),
        }

    def _knowledge_inventory_counts(self) -> dict:
        models = {
            "content_chunks": ContentChunk,
            "chunk_embeddings": ChunkEmbedding,
            "extracted_rules": ExtractedRule,
            "normalized_rules": NormalizedRule,
            "strategy_candidates": StrategyCandidate,
            "strategy_playbooks": StrategyPlaybook,
            "top_strategies_detected": TopStrategyDetected,
        }
        return {
            key: self.session.scalar(select(func.count()).select_from(model)) or 0
            for key, model in models.items()
        }

    def _raw_file_counts(self) -> dict:
        rows = self.session.execute(
            select(FileAsset.category, func.count()).group_by(FileAsset.category).order_by(FileAsset.category.asc())
        ).all()
        return {str(category or "unknown"): int(count) for category, count in rows}

    def _readiness_artifacts(self) -> dict:
        data_dir = self.settings.paths.data_dir
        demo_dir = data_dir / "demo_trading" / "maximo_quant_v4"
        artifacts = {
            "best_current_strategy": {
                "path": data_dir / "strategies" / "maximo_quant_v4_best_current.json",
                "required": True,
                "description": "Snapshot de la mejor estrategia base actual.",
            },
            "market_situation_map_json": {
                "path": data_dir / "knowledge" / "market_situation_map.json",
                "required": True,
                "description": "Mapa estructurado de situaciones de mercado.",
            },
            "market_situation_map_md": {
                "path": data_dir / "knowledge" / "market_situation_map.md",
                "required": True,
                "description": "Versión legible del mapa de situaciones.",
            },
            "latest_signal_json": {
                "path": demo_dir / "latest_signal.json",
                "required": True,
                "description": "Última salida real del demo engine MAXIMO Quant v4.",
            },
            "demo_report_md": {
                "path": demo_dir / "demo_report.md",
                "required": True,
                "description": "Reporte operativo del último ciclo demo.",
            },
            "active_watch_history_jsonl": {
                "path": demo_dir / "active_watch_history.jsonl",
                "required": False,
                "description": "Historial de watches activos cuando el sistema entra en WATCH.",
            },
            "decision_source_audit_jsonl": {
                "path": demo_dir / "decision_source_audit.jsonl",
                "required": False,
                "description": "Auditoría de fuente de decisión, disponible tras ciclos instrumentados.",
            },
            "watch_performance_report_md": {
                "path": demo_dir / "watch_performance_report.md",
                "required": False,
                "description": "Reporte estadístico del comportamiento WATCH.",
            },
            "learning_cycle_report_md": {
                "path": data_dir / "knowledge" / "learning_cycle" / "learning_cycle_report.md",
                "required": False,
                "description": "Reporte del ciclo que convierte material crudo en conocimiento aplicable.",
            },
            "learning_cycle_report_json": {
                "path": data_dir / "knowledge" / "learning_cycle" / "learning_cycle_report.json",
                "required": False,
                "description": "Version estructurada del ciclo de aprendizaje continuo.",
            },
            "latest_market_intelligence_json": {
                "path": demo_dir / "latest_market_intelligence.json",
                "required": False,
                "description": "Salida opcional del comando market-intelligence independiente.",
            },
            "latest_market_overview_json": {
                "path": demo_dir / "latest_market_overview.json",
                "required": False,
                "description": "Salida opcional del comando market-overview independiente.",
            },
        }
        return {
            key: self._artifact_status(
                metadata["path"],
                required=bool(metadata["required"]),
                description=str(metadata["description"]),
            )
            for key, metadata in artifacts.items()
        }

    @staticmethod
    def _artifact_status(path: Path, *, required: bool, description: str) -> dict:
        exists = path.exists()
        stat = path.stat() if exists else None
        return {
            "path": str(path),
            "exists": exists,
            "required": required,
            "status": "OK" if exists else ("MISSING_REQUIRED" if required else "OPTIONAL_MISSING"),
            "description": description,
            "size_bytes": stat.st_size if stat else 0,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat() if stat else None,
        }

    def _hash_password(self, password: str) -> str:
        normalized = str(password or "")
        if len(normalized) < 8:
            raise ValueError("Password must have at least 8 characters.")
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            normalized.encode("utf-8"),
            salt.encode("utf-8"),
            self.PASSWORD_ITERATIONS,
        ).hex()
        return f"{self.PASSWORD_SCHEME}${self.PASSWORD_ITERATIONS}${salt}${digest}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            scheme, iterations_raw, salt, expected = stored_hash.split("$", 3)
            iterations = int(iterations_raw)
        except (ValueError, AttributeError):
            return False
        if scheme != self.PASSWORD_SCHEME or iterations < 100_000:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(digest, expected)

    @staticmethod
    def _parse_json_list(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        if isinstance(payload, list):
            return [str(item) for item in payload]
        return []

    @staticmethod
    def _parse_json_dict(raw_value: str | None) -> dict:
        if not raw_value:
            return {}
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _notify_owners(
        self,
        *,
        title: str,
        message: str,
        category: str,
        severity: str = "info",
        metadata: dict | None = None,
    ) -> None:
        owners = self.repository.list_owner_users()
        if owners:
            for owner in owners:
                self.repository.create_notification(
                    user_id=owner.id,
                    audience="owner",
                    category=category,
                    severity=severity,
                    title=title,
                    message=message,
                    metadata=metadata,
                )
            return
        self.repository.create_notification(
            user_id=None,
            audience="owner",
            category=category,
            severity=severity,
            title=title,
            message=message,
            metadata=metadata,
        )

    def _canonical_strategy_key(self, strategy_key: str | None) -> str:
        if not strategy_key:
            return self.DEFAULT_STRATEGY_KEY
        normalized = str(strategy_key).strip()
        return self.STRATEGY_KEY_ALIASES.get(normalized, normalized)

    @staticmethod
    def _optional_str(value) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _optional_bool(value) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        return bool(value)
