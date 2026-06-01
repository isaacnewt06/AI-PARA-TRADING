from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.platform_service_api import create_platform_api_app
from src.application.trading_service_platform import TradingServicePlatformApplicationService
from src.core.config import reload_settings
from src.db.session import init_db, session_scope


def _configure(tmp_path: Path):
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'platform_api.db').as_posix()}",
        }
    )
    init_db()
    return settings


def _issue_token(settings, *, user_email: str) -> str:
    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        return service.issue_user_api_credential(
            user_email=user_email,
            credential_label="test-token",
        )["token"]


def test_platform_api_bootstrap_and_status(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    client = TestClient(create_platform_api_app(settings))

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["docs_url"] == "/docs"

    response = client.post(
        "/api/platform/bootstrap",
        json={
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
            "owner_password": "SecurePass123!",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["owner_email"] == "owner@example.com"
    assert payload["platform_status"]["counts"]["users"] == 1

    token = _issue_token(settings, user_email="owner@example.com")
    status = client.get("/api/platform/status", headers={"Authorization": f"Bearer {token}"})
    assert status.status_code == 200
    assert status.json()["counts"]["users"] == 1
    assert status.json()["current_user"]["user_email"] == "owner@example.com"

    login = client.post(
        "/api/platform/auth/login",
        json={"email": "owner@example.com", "password": "SecurePass123!"},
    )
    assert login.status_code == 200
    assert login.json()["token"].startswith("tbs_")
    assert login.json()["role"] == "owner"

    readiness = client.get("/api/platform/readiness", headers={"Authorization": f"Bearer {token}"})
    assert readiness.status_code == 200
    assert "overall_status" in readiness.json()
    assert "checks" in readiness.json()

    demo_dir = settings.paths.data_dir / "demo_trading" / "maximo_quant_v4"
    demo_dir.mkdir(parents=True, exist_ok=True)
    (demo_dir / "latest_signal.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T10:00:00-04:00",
                "symbol": "XAUUSDm",
                "dry_run": False,
                "execution_status": "no_signal",
                "intelligence_action": "WATCH",
                "harmony_score": 0.58,
                "watch_trigger": {
                    "side": "BUY",
                    "candidate_side": "BUY",
                    "setup_maturity": 77.0,
                    "confidence": 0.77,
                    "macro_event_status": "allow",
                    "pattern_projection": {
                        "candidate_side": "BUY",
                        "dominant_family": "OB Rejection",
                        "probable_market_move": "continuación alcista si confirma M5",
                        "evidence": ["Micro BOS presente"],
                        "confirmation_focus": ["Cierre M5 alcista"],
                    },
                },
                "reasoning_snapshot": {
                    "state": {"summary": "Idea BUY en observación."},
                    "waiting_for": ["Falta señal final."],
                    "next_confirmation_expected": "Cierre M5 alcista.",
                },
            }
        ),
        encoding="utf-8",
    )
    ai_live = client.get("/api/platform/ai-live", headers={"Authorization": f"Bearer {token}"})
    assert ai_live.status_code == 200
    assert ai_live.json()["brain"]["action"] == "WATCH"
    assert ai_live.json()["market"]["candidate_side"] == "BUY"
    assert ai_live.json()["pattern_projection"]["probable_market_move"] == "continuación alcista si confirma M5"
    assert ai_live.json()["price_context"]["source"] == "mt5_read_only_snapshot"
    assert ai_live.json()["price_context"]["side"] == "BUY"

    me = client.get("/api/platform/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user_email"] == "owner@example.com"

    html_root = client.get("/", headers={"accept": "text/html"})
    assert html_root.status_code == 200
    assert "BOTEXTRATOR Trading Service" in html_root.text
    assert "Ciclos Recientes del Agente" in html_root.text
    assert "Operaciones Rápidas" in html_root.text
    assert "Cuenta Focus" in html_root.text
    assert "Última Acción AI" in html_root.text
    assert "AI Live Command Center" in html_root.text
    assert "Zona / precio vigilado" in html_root.text
    assert "Nivel de confirmación" in html_root.text
    assert "Radar de Entrada AI" in html_root.text
    assert "entry-radar-confirmed" in html_root.text
    assert "entry-radar-missing" in html_root.text
    assert 'class="workspace-tab active" data-view-target="ai"' in html_root.text
    assert 'data-view-target="capital"' in html_root.text
    assert 'data-view-target="accounts"' in html_root.text
    assert 'data-view-target="operations"' in html_root.text
    assert 'data-view-target="admin"' in html_root.text
    assert 'data-view="capital"' in html_root.text
    assert 'data-view="accounts"' in html_root.text
    assert "/api/platform/ai-live" in html_root.text
    assert "Inspector de Cuenta" in html_root.text
    assert "Paso 3: mantener MT5 conectado" in html_root.text
    assert "Recuperar contraseña" in html_root.text
    assert "notification-button" in html_root.text
    assert "Seguridad y Notificaciones" in html_root.text
    assert "Registrarse en Exness" in html_root.text
    assert "Registrarse en XM" not in html_root.text
    assert html_root.text.count("https://one.exnessonelink.com/a/143x3jrak4") >= 2


def test_platform_api_password_reset_notifications_and_device_events(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    client = TestClient(create_platform_api_app(settings))

    bootstrap = client.post(
        "/api/platform/bootstrap",
        json={
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
            "owner_password": "SecurePass123!",
        },
    )
    assert bootstrap.status_code == 200
    register = client.post(
        "/api/platform/register",
        json={
            "email": "client@example.com",
            "display_name": "Client",
            "password": "ClientPass123!",
        },
    )
    assert register.status_code == 200

    owner_token = _issue_token(settings, user_email="owner@example.com")
    headers = {"Authorization": f"Bearer {owner_token}"}
    activate = client.post(
        "/api/platform/users/status",
        json={"user_id": register.json()["user_id"], "status": "active"},
        headers=headers,
    )
    assert activate.status_code == 200

    reset_request = client.post(
        "/api/platform/auth/password-reset/request",
        json={
            "email": "client@example.com",
            "device_fingerprint": "phone-abc",
            "device_label": "teléfono · Android",
        },
    )
    assert reset_request.status_code == 200
    assert reset_request.json()["delivery_mode"] == "owner_notification"

    notifications = client.get("/api/platform/notifications", headers=headers)
    assert notifications.status_code == 200
    payload = notifications.json()
    assert payload["critical_unread_count"] >= 1
    reset_notifications = [item for item in payload["notifications"] if item["category"] == "password_reset"]
    assert reset_notifications
    reset_token = reset_notifications[0]["metadata"]["reset_token"]
    assert reset_token.startswith("rst_")

    confirm = client.post(
        "/api/platform/auth/password-reset/confirm",
        json={
            "email": "client@example.com",
            "token": reset_token,
            "new_password": "ClientPass456!",
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "password_updated"

    login = client.post(
        "/api/platform/auth/login",
        json={
            "email": "client@example.com",
            "password": "ClientPass456!",
            "device_fingerprint": "phone-abc",
            "device_label": "teléfono · Android",
        },
    )
    assert login.status_code == 200
    assert login.json()["device_status"] in {"known_device", "new_device"}

    notifications_after = client.get("/api/platform/notifications", headers=headers)
    assert notifications_after.status_code == 200
    events = notifications_after.json()["recent_security_events"]
    assert any(item["event_type"] == "login_success" for item in events)
    assert any(item["event_type"] == "password_reset_completed" for item in events)


def test_platform_api_account_flow(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    strategies_dir = Path(settings.paths.data_dir) / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    (strategies_dir / "maximo_quant_v4_best_current.json").write_text(
        json.dumps(
            {
                "strategy_name": "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
                "strategy_variant": "v56_aggressive_filtered_b",
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_platform_api_app(settings))

    bootstrap = client.post(
        "/api/platform/bootstrap",
        json={
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
        },
    )
    assert bootstrap.status_code == 200
    token = _issue_token(settings, user_email="owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    account = client.post(
        "/api/platform/accounts",
        json={
            "owner_email": "owner@example.com",
            "account_label": "Main Demo",
            "broker_name": "Exness",
            "symbol_suffix": "m",
            "source_bots": ["signal_guard"],
        },
        headers=headers,
    )
    assert account.status_code == 200
    account_payload = account.json()
    assert account_payload["broker_symbol"] == "XAUUSDm"
    account_id = account_payload["account_id"]

    grant = client.post(
        f"/api/platform/accounts/{account_id}/access",
        json={
            "grantee_email": "owner@example.com",
            "permission_level": "owner",
            "can_trade": True,
        },
        headers=headers,
    )
    assert grant.status_code == 200
    assert grant.json()["permission_level"] == "owner"

    agent = client.post(
        f"/api/platform/accounts/{account_id}/agents",
        json={
            "agent_name": "vps-exness-01",
            "host_name": "VPS-EXNESS-01",
        },
        headers=headers,
    )
    assert agent.status_code == 200
    agent_payload = agent.json()
    assert agent_payload["status"] == "provisioned"
    agent_key = agent_payload["agent_key"]

    credential = client.post(
        "/api/platform/users/credentials",
        json={
            "user_email": "owner@example.com",
            "credential_label": "owner-main-key",
        },
        headers=headers,
    )
    assert credential.status_code == 200
    token = credential.json()["token"]

    token_auth = client.post(
        "/api/platform/auth/token",
        json={"token": token},
    )
    assert token_auth.status_code == 200
    assert token_auth.json()["user_email"] == "owner@example.com"

    deployment = client.post(
        f"/api/platform/accounts/{account_id}/deployments",
        json={
            "strategy_key": "external_signal_bot",
            "strategy_variant": "ob_rejection_guarded",
            "operation_mode": "hybrid_guarded",
            "risk_mode": "reduced",
            "learning_mode": "continuous",
            "source_bots": ["bot_alpha"],
        },
        headers=headers,
    )
    assert deployment.status_code == 200
    assert deployment.json()["operation_mode"] == "hybrid_guarded"

    alias = client.post(
        f"/api/platform/accounts/{account_id}/symbols",
        json={
            "canonical_symbol": "BTCUSD",
            "broker_symbol": "BTCUSDm",
        },
        headers=headers,
    )
    assert alias.status_code == 200
    assert alias.json()["broker_symbol"] == "BTCUSDm"

    agent_auth = client.post(
        f"/api/platform/accounts/{account_id}/agents/authenticate",
        json={"agent_key": agent_key},
    )
    assert agent_auth.status_code == 200
    assert agent_auth.json()["is_demo"] is True
    assert agent_auth.json()["strategy_deployments"]
    assert "symbol_allowlist" in agent_auth.json()["strategy_deployments"][0]

    heartbeat = client.post(
        f"/api/platform/accounts/{account_id}/agents/heartbeat",
        json={
            "agent_key": agent_key,
            "status": "online",
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "online"

    runtime_report = client.post(
        f"/api/platform/accounts/{account_id}/agents/report",
        json={
            "agent_key": agent_key,
            "canonical_symbol": "XAUUSD",
            "broker_symbol": "XAUUSDm",
            "local_terminal_ready": True,
            "service_root": {"service": "BOTEXTRATOR Trading Service API"},
            "remote_agent": {"agent_id": agent_payload["agent_id"]},
            "heartbeat": {"status": "online"},
            "account_status": {"is_demo": True},
            "execution_environment": {"symbol_resolved": "XAUUSDm"},
            "open_positions": [],
            "deployment_runs": [
                {
                    "strategy_key": "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
                    "strategy_variant": "v56_aggressive_filtered_b",
                    "operation_mode": "ai_managed",
                    "canonical_symbol": "XAUUSD",
                    "broker_symbol": "XAUUSDm",
                    "status": "executed",
                    "execution_status": "no_signal",
                    "intelligence_action": "WATCH",
                    "signal_detected": False,
                    "dry_run": True,
                }
            ],
        },
    )
    assert runtime_report.status_code == 200
    assert runtime_report.json()["deployment_reports_created"] == 1

    refreshed_status = client.get("/api/platform/status", headers=headers)
    assert refreshed_status.status_code == 200
    assert refreshed_status.json()["recent_agent_cycles"][0]["broker_symbol"] == "XAUUSDm"
    assert refreshed_status.json()["recent_deployment_runs"][0]["run_status"] == "executed"

    account_detail = client.get(f"/api/platform/accounts/{account_id}", headers=headers)
    assert account_detail.status_code == 200
    assert account_detail.json()["account"]["label"] == "Main Demo"
    deployment_id = account_detail.json()["deployments"][0]["id"]

    deployment_state = client.post(
        f"/api/platform/deployments/{deployment_id}/status",
        json={"deployment_status": "paused"},
        headers=headers,
    )
    assert deployment_state.status_code == 200
    assert deployment_state.json()["deployment_status"] == "paused"


def test_platform_api_returns_400_for_missing_user(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    client = TestClient(create_platform_api_app(settings))

    client.post(
        "/api/platform/bootstrap",
        json={
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
        },
    )
    token = _issue_token(settings, user_email="owner@example.com")

    response = client.post(
        "/api/platform/accounts",
        json={
            "owner_email": "missing@example.com",
            "account_label": "Main Demo",
            "broker_name": "Exness",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "User not found" in response.json()["detail"]


def test_platform_api_requires_token_for_protected_status(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    client = TestClient(create_platform_api_app(settings))

    response = client.get("/api/platform/status")
    assert response.status_code == 401
    assert "Missing API token" in response.json()["detail"]


def test_platform_api_client_scope_is_limited_to_authorized_accounts(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    client = TestClient(create_platform_api_app(settings))

    bootstrap = client.post(
        "/api/platform/bootstrap",
        json={
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
        },
    )
    assert bootstrap.status_code == 200
    owner_token = _issue_token(settings, user_email="owner@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    created_user = client.post(
        "/api/platform/users",
        json={
            "email": "client@example.com",
            "display_name": "Client",
            "role": "client",
        },
        headers=owner_headers,
    )
    assert created_user.status_code == 200

    visible_account = client.post(
        "/api/platform/accounts",
        json={
            "owner_email": "owner@example.com",
            "account_label": "Visible Demo",
            "broker_name": "Exness",
            "symbol_suffix": "m",
        },
        headers=owner_headers,
    )
    hidden_account = client.post(
        "/api/platform/accounts",
        json={
            "owner_email": "owner@example.com",
            "account_label": "Hidden Demo",
            "broker_name": "Exness",
            "symbol_suffix": "raw",
        },
        headers=owner_headers,
    )
    assert visible_account.status_code == 200
    assert hidden_account.status_code == 200
    visible_account_id = visible_account.json()["account_id"]
    hidden_account_id = hidden_account.json()["account_id"]

    grant = client.post(
        f"/api/platform/accounts/{visible_account_id}/access",
        json={
            "grantee_email": "client@example.com",
            "permission_level": "operator",
            "can_trade": True,
        },
        headers=owner_headers,
    )
    assert grant.status_code == 200

    client_token = _issue_token(settings, user_email="client@example.com")
    client_headers = {"Authorization": f"Bearer {client_token}"}

    scoped_status = client.get("/api/platform/status", headers=client_headers)
    assert scoped_status.status_code == 200
    scoped_payload = scoped_status.json()
    assert scoped_payload["counts"]["accounts"] == 1
    assert scoped_payload["counts"]["learning_integrations"] == 0
    assert scoped_payload["accounts"][0]["id"] == visible_account_id
    assert scoped_payload["current_user"]["user_email"] == "client@example.com"

    client_readiness = client.get("/api/platform/readiness", headers=client_headers)
    assert client_readiness.status_code == 400
    assert "Owner role required" in client_readiness.json()["detail"]

    visible_detail = client.get(f"/api/platform/accounts/{visible_account_id}", headers=client_headers)
    assert visible_detail.status_code == 200
    deployment_id = visible_detail.json()["deployments"][0]["id"]

    hidden_detail = client.get(f"/api/platform/accounts/{hidden_account_id}", headers=client_headers)
    assert hidden_detail.status_code == 400
    assert "not allowed to view" in hidden_detail.json()["detail"]

    deployment_state = client.post(
        f"/api/platform/deployments/{deployment_id}/status",
        json={"deployment_status": "paused"},
        headers=client_headers,
    )
    assert deployment_state.status_code == 200
    assert deployment_state.json()["deployment_status"] == "paused"

    denied_account_create = client.post(
        "/api/platform/accounts",
        json={
            "owner_email": "owner@example.com",
            "account_label": "Denied Demo",
            "broker_name": "Exness",
        },
        headers=client_headers,
    )
    assert denied_account_create.status_code == 400
    assert "Owner role required" in denied_account_create.json()["detail"]


def test_platform_api_client_can_connect_own_exness_account(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    client = TestClient(create_platform_api_app(settings))

    bootstrap = client.post(
        "/api/platform/bootstrap",
        json={
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
            "owner_password": "SecurePass123!",
        },
    )
    assert bootstrap.status_code == 200
    owner_token = _issue_token(settings, user_email="owner@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    created_user = client.post(
        "/api/platform/users",
        json={
            "email": "client@example.com",
            "display_name": "Client",
            "role": "client",
            "password": "ClientPass123!",
        },
        headers=owner_headers,
    )
    assert created_user.status_code == 200

    login = client.post(
        "/api/platform/auth/login",
        json={"email": "client@example.com", "password": "ClientPass123!"},
    )
    assert login.status_code == 200
    client_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    denied = client.post(
        "/api/platform/me/accounts/exness",
        json={"account_label": "Client Exness Demo", "referral_confirmed": False},
        headers=client_headers,
    )
    assert denied.status_code == 400
    assert "referral confirmation" in denied.json()["detail"]

    connected = client.post(
        "/api/platform/me/accounts/exness",
        json={
            "account_label": "Client Exness Demo",
            "broker_server": "Exness-MT5Trial11",
            "login_reference": "197452102",
            "symbol_suffix": "m",
            "referral_confirmed": True,
        },
        headers=client_headers,
    )
    assert connected.status_code == 200
    assert connected.json()["broker_symbol"] == "XAUUSDm"

    scoped_status = client.get("/api/platform/status", headers=client_headers)
    assert scoped_status.status_code == 200
    assert scoped_status.json()["counts"]["accounts"] == 1
    assert scoped_status.json()["accounts"][0]["id"] == connected.json()["account_id"]
    assert scoped_status.json()["account_policy"]["max_broker_accounts"] == 1
    assert scoped_status.json()["broker_onboarding"]["primary_broker"] == "Exness"

    blocked_second = client.post(
        "/api/platform/me/accounts/exness",
        json={
            "account_label": "Second Exness Demo",
            "broker_server": "Exness-MT5Trial12",
            "login_reference": "197452103",
            "symbol_suffix": "m",
            "referral_confirmed": True,
        },
        headers=client_headers,
    )
    assert blocked_second.status_code == 400
    assert "Account limit reached" in blocked_second.json()["detail"]

    limit_update = client.post(
        "/api/platform/users/account-limit",
        json={"user_id": created_user.json()["user_id"], "max_broker_accounts": 2},
        headers=owner_headers,
    )
    assert limit_update.status_code == 200
    assert limit_update.json()["max_broker_accounts"] == 2

    replace = client.post(
        "/api/platform/me/accounts/exness",
        json={
            "replace_account_id": connected.json()["account_id"],
            "account_label": "Client Exness Replaced",
            "broker_server": "Exness-MT5Trial12",
            "login_reference": "197452103",
            "symbol_suffix": "XAUUSDm",
            "referral_confirmed": True,
        },
        headers=client_headers,
    )
    assert replace.status_code == 200
    assert replace.json()["account_replaced"] is True

    deleted = client.delete(
        f"/api/platform/me/accounts/{connected.json()['account_id']}",
        headers=client_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deactivated"


def test_platform_api_owner_can_archive_blocked_client_account(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    client = TestClient(create_platform_api_app(settings))

    bootstrap = client.post(
        "/api/platform/bootstrap",
        json={
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
            "owner_password": "SecurePass123!",
        },
    )
    assert bootstrap.status_code == 200
    owner_token = _issue_token(settings, user_email="owner@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    account = client.post(
        "/api/platform/accounts",
        json={
            "owner_email": "owner@example.com",
            "account_label": "Blocked Demo",
            "broker_name": "Exness",
            "symbol_suffix": "m",
        },
        headers=owner_headers,
    )
    assert account.status_code == 200

    archived = client.delete(
        f"/api/platform/accounts/{account.json()['account_id']}",
        headers=owner_headers,
    )
    status = client.get("/api/platform/status", headers=owner_headers)

    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert status.json()["counts"]["accounts"] == 0


def test_public_registration_requires_owner_approval_before_login(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    client = TestClient(create_platform_api_app(settings))

    bootstrap = client.post(
        "/api/platform/bootstrap",
        json={
            "owner_email": "owner@example.com",
            "owner_name": "Owner",
            "owner_password": "SecurePass123!",
        },
    )
    assert bootstrap.status_code == 200

    registration = client.post(
        "/api/platform/register",
        json={
            "email": "new-client@example.com",
            "display_name": "New Client",
            "password": "ClientPass123!",
        },
    )
    assert registration.status_code == 200
    assert registration.json()["status"] == "pending"

    pending_login = client.post(
        "/api/platform/auth/login",
        json={"email": "new-client@example.com", "password": "ClientPass123!"},
    )
    assert pending_login.status_code == 400
    assert "Invalid email or password" in pending_login.json()["detail"]

    owner_token = _issue_token(settings, user_email="owner@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    owner_status = client.get("/api/platform/status", headers=owner_headers)
    registered_user = next(
        item for item in owner_status.json()["users_detail"] if item["email"] == "new-client@example.com"
    )

    approval = client.post(
        "/api/platform/users/status",
        json={"user_id": registered_user["id"], "status": "active"},
        headers=owner_headers,
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "active"

    approved_login = client.post(
        "/api/platform/auth/login",
        json={"email": "new-client@example.com", "password": "ClientPass123!"},
    )
    assert approved_login.status_code == 200
    assert approved_login.json()["role"] == "client"
