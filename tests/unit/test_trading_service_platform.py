from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from src.application.trading_service_platform import TradingServicePlatformApplicationService
from src.core.config import get_settings, reload_settings
from src.db.models.channel import Channel
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import ContentChunk, ExtractedRule, NormalizedRule, StrategyCandidate, TopStrategyDetected
from src.db.models.platform import (
    AccountAccessGrant,
    BrokerAccount,
    BrokerSymbolAlias,
    DeploymentExecutionReport,
    ExecutionAgent,
    ExecutionAgentRuntimeReport,
    LearningIntegration,
    PlatformUser,
    StrategyDeployment,
)
from src.db.session import init_db, session_scope


def _configure(tmp_path: Path):
    return reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'platform.db').as_posix()}",
        }
    )


def test_platform_bootstrap_seeds_learning_sources(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        session.add(
            Channel(
                input_reference="https://t.me/tradingcursosgratiss",
                title="Cursos de Trading GRATIS",
                normalized_name="cursos_de_trading_gratis",
            )
        )

    with session_scope() as session:
        summary = TradingServicePlatformApplicationService(session, settings).bootstrap_platform(
            owner_email="owner@example.com",
            owner_name="Owner",
        )
        assert summary["owner_email"] == "owner@example.com"
        assert summary["learning_integrations_seeded"] >= 2

    with session_scope() as session:
        users = list(session.scalars(select(PlatformUser)))
        integrations = list(session.scalars(select(LearningIntegration)))
        assert len(users) == 1
        assert users[0].role == "owner"
        assert any(item.source_type == "telegram_channel" for item in integrations)
        assert any(item.source_type == "manual_knowledge" for item in integrations)


def test_platform_password_login_issues_api_token(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        service.bootstrap_platform(
            owner_email="owner@example.com",
            owner_name="Owner",
            owner_password="SecurePass123!",
        )
        login = service.authenticate_user_password(
            email="owner@example.com",
            password="SecurePass123!",
        )
        authenticated = service.authenticate_user_api_credential(token=login["token"])

        assert login["user_email"] == "owner@example.com"
        assert login["role"] == "owner"
        assert login["token"].startswith("tbs_")
        assert authenticated["user_email"] == "owner@example.com"


def test_connect_broker_account_creates_deployment_and_symbol_alias(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()
    strategies_dir = Path(settings.paths.data_dir) / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    (strategies_dir / "maximo_quant_v4_best_current.json").write_text(
        json.dumps(
            {
                "strategy_name": "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
                "strategy_variant": "v56_aggressive_filtered_b",
                "session_variant": "all",
                "timeframe": "M5",
            }
        ),
        encoding="utf-8",
    )

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        service.create_user(email="owner@example.com", display_name="Owner", role="owner")
        result = service.connect_broker_account(
            owner_email="owner@example.com",
            account_label="Main Demo",
            broker_name="Exness",
            symbol_suffix="m",
            source_bots=["signal_guard"],
        )
        assert result["broker_symbol"] == "XAUUSDm"
        assert result["strategy_variant"] == "v56_aggressive_filtered_b"

    with session_scope() as session:
        account = session.scalar(select(BrokerAccount))
        grant = session.scalar(select(AccountAccessGrant))
        deployment = session.scalar(select(StrategyDeployment))
        alias = session.scalar(select(BrokerSymbolAlias))
        assert account is not None and account.is_demo is True
        assert grant is not None and grant.permission_level == "owner"
        assert deployment is not None and deployment.operation_mode == "ai_managed"
        assert alias is not None and alias.broker_symbol == "XAUUSDm"


def test_platform_grant_access_register_agent_and_status(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        service.create_user(email="owner@example.com", display_name="Owner", role="owner")
        service.create_user(email="client@example.com", display_name="Client")
        account = service.connect_broker_account(
            owner_email="owner@example.com",
            account_label="Pilot Demo",
            broker_name="Exness",
            symbol_suffix="m",
        )
        grant = service.grant_account_access(
            account_id=account["account_id"],
            grantee_email="client@example.com",
            permission_level="operator",
            can_trade=True,
        )
        agent = service.register_execution_agent(
            account_id=account["account_id"],
            agent_name="vps-exness-01",
            host_name="VPS-EXNESS-01",
        )
        deployment = service.deploy_strategy_mode(
            account_id=account["account_id"],
            strategy_key="external_signal_bot",
            strategy_variant="ob_rejection_guarded",
            operation_mode="hybrid_guarded",
            risk_mode="reduced",
            learning_mode="continuous",
            source_bots=["bot_alpha", "bot_beta"],
        )
        status = service.platform_status()

        assert grant["permission_level"] == "operator"
        assert agent["status"] == "provisioned"
        assert deployment["operation_mode"] == "hybrid_guarded"
        assert status["counts"]["users"] == 2
        assert status["counts"]["accounts"] == 1
        assert status["counts"]["agents"] == 1
        assert status["operation_modes"]["hybrid_guarded"] == 1

    with session_scope() as session:
        assert session.scalar(select(ExecutionAgent)) is not None


def test_platform_status_for_user_only_shows_authorized_accounts(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        owner = service.create_user(email="owner@example.com", display_name="Owner", role="owner")
        client = service.create_user(email="client@example.com", display_name="Client", role="client")
        first = service.connect_broker_account(
            owner_email="owner@example.com",
            account_label="Client Demo",
            broker_name="Exness",
            symbol_suffix="m",
        )
        second = service.connect_broker_account(
            owner_email="owner@example.com",
            account_label="Private Demo",
            broker_name="Exness",
            symbol_suffix="raw",
        )
        service.grant_account_access(
            account_id=first["account_id"],
            grantee_email="client@example.com",
            permission_level="operator",
            can_trade=True,
        )
        service.register_execution_agent(
            account_id=first["account_id"],
            agent_name="visible-agent",
            host_name="VPS-VISIBLE",
        )
        service.register_execution_agent(
            account_id=second["account_id"],
            agent_name="hidden-agent",
            host_name="VPS-HIDDEN",
        )

        owner_status = service.platform_status_for_user(user_id=owner["user_id"], role="owner")
        client_status = service.platform_status_for_user(user_id=client["user_id"], role="client")

        assert owner_status["counts"]["accounts"] == 2
        assert client_status["counts"]["accounts"] == 1
        assert client_status["counts"]["agents"] == 1
        assert client_status["counts"]["learning_integrations"] == 0
        assert client_status["accounts"][0]["id"] == first["account_id"]
        assert {item["agent_name"] for item in client_status["agents"]} == {"visible-agent"}
        assert client_status["permission_scope"]["visible_account_ids"] == [first["account_id"]]


def test_client_can_connect_own_exness_account_after_referral_confirmation(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        client = service.create_user(email="client@example.com", display_name="Client", role="client")
        result = service.connect_own_exness_account(
            user_id=client["user_id"],
            account_label="Client Exness Demo",
            broker_server="Exness-MT5Trial11",
            login_reference="197452102",
            symbol_suffix="m",
            referral_confirmed=True,
        )
        status = service.platform_status_for_user(user_id=client["user_id"], role="client")

        assert result["broker_name"] == "Exness"
        assert result["broker_symbol"] == "XAUUSDm"
        assert result["risk_mode"] == "reduced"
        assert result["agent_name"] == f"client-exness-{result['account_id']}"
        assert result["agent_key"]
        assert status["counts"]["accounts"] == 1
        assert status["counts"]["agents"] == 1
        assert status["accounts"][0]["id"] == result["account_id"]
        assert status["accounts"][0]["runtime_health"] == "agent_ready"
        assert status["broker_onboarding"]["primary_broker"] == "Exness"
        assert status["account_policy"]["max_broker_accounts"] == 1
        assert status["account_policy"]["remaining_slots"] == 0


def test_client_exness_connect_normalizes_symbol_and_reuses_existing_account(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        client = service.create_user(email="client@example.com", display_name="Client", role="client")
        first = service.connect_own_exness_account(
            user_id=client["user_id"],
            account_label="Client Exness Demo",
            broker_server="Exness-MT5Trial11",
            login_reference="197452102",
            symbol_suffix="XAUUSDm",
            referral_confirmed=True,
        )
        second = service.connect_own_exness_account(
            user_id=client["user_id"],
            account_label="Client Exness Demo",
            broker_server="Exness-MT5Trial11",
            login_reference="197452102",
            symbol_suffix="XAUUSDm",
            referral_confirmed=True,
        )
        status = service.platform_status_for_user(user_id=client["user_id"], role="client")

        assert first["broker_symbol"] == "XAUUSDm"
        assert second["broker_symbol"] == "XAUUSDm"
        assert second["account_id"] == first["account_id"]
        assert second["account_created"] is False
        assert status["counts"]["accounts"] == 1
        assert status["counts"]["agents"] == 1
        assert status["accounts"][0]["symbol_suffix"] == "m"


def test_client_exness_account_limit_blocks_second_account_until_owner_increases_limit(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        client = service.create_user(email="client@example.com", display_name="Client", role="client")
        service.connect_own_exness_account(
            user_id=client["user_id"],
            account_label="Primary Exness",
            broker_server="Exness-MT5Trial11",
            login_reference="197452102",
            referral_confirmed=True,
        )
        try:
            service.connect_own_exness_account(
                user_id=client["user_id"],
                account_label="Second Exness",
                broker_server="Exness-MT5Trial12",
                login_reference="197452103",
                referral_confirmed=True,
            )
        except ValueError as exc:
            assert "Account limit reached" in str(exc)
        else:
            raise AssertionError("Expected second account to be blocked by the client account limit.")

        limit = service.update_user_account_limit(user_id=client["user_id"], max_broker_accounts=2)
        second = service.connect_own_exness_account(
            user_id=client["user_id"],
            account_label="Second Exness",
            broker_server="Exness-MT5Trial12",
            login_reference="197452103",
            referral_confirmed=True,
        )
        status = service.platform_status_for_user(user_id=client["user_id"], role="client")

        assert limit["max_broker_accounts"] == 2
        assert second["account_created"] is True
        assert status["counts"]["accounts"] == 2
        assert status["account_policy"]["remaining_slots"] == 0


def test_client_can_replace_or_delete_own_exness_account_with_one_slot(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        client = service.create_user(email="client@example.com", display_name="Client", role="client")
        first = service.connect_own_exness_account(
            user_id=client["user_id"],
            account_label="Old Exness",
            broker_server="Exness-MT5Trial11",
            login_reference="197452102",
            referral_confirmed=True,
        )
        replaced = service.connect_own_exness_account(
            user_id=client["user_id"],
            replace_account_id=first["account_id"],
            account_label="New Exness",
            broker_server="Exness-MT5Trial12",
            login_reference="197452103",
            symbol_suffix="XAUUSDm",
            referral_confirmed=True,
        )
        deleted = service.deactivate_own_broker_account(
            user_id=client["user_id"],
            account_id=first["account_id"],
        )
        status_after_delete = service.platform_status_for_user(user_id=client["user_id"], role="client")
        third = service.connect_own_exness_account(
            user_id=client["user_id"],
            account_label="Fresh Exness",
            broker_server="Exness-MT5Trial13",
            login_reference="197452104",
            referral_confirmed=True,
        )

        assert replaced["account_id"] == first["account_id"]
        assert replaced["account_replaced"] is True
        assert replaced["account_created"] is False
        assert deleted["status"] == "deactivated"
        assert status_after_delete["counts"]["accounts"] == 0
        assert third["account_created"] is True
        assert third["account_id"] != first["account_id"]


def test_client_exness_connect_requires_referral_confirmation(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        client = service.create_user(email="client@example.com", display_name="Client", role="client")
        try:
            service.connect_own_exness_account(
                user_id=client["user_id"],
                account_label="Client Exness Demo",
                referral_confirmed=False,
            )
        except ValueError as exc:
            assert "referral confirmation" in str(exc)
        else:
            raise AssertionError("Expected referral confirmation to be required.")


def test_platform_readiness_reports_brain_and_execution_state(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()
    strategies_dir = Path(settings.paths.data_dir) / "strategies"
    knowledge_dir = Path(settings.paths.knowledge_dir)
    demo_dir = Path(settings.paths.data_dir) / "demo_trading" / "maximo_quant_v4"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    demo_dir.mkdir(parents=True, exist_ok=True)
    (strategies_dir / "maximo_quant_v4_best_current.json").write_text(
        json.dumps(
            {
                "strategy_key": "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
                "strategy_variant": "v56_aggressive_filtered_b",
                "session_variant": "all",
                "timeframe": "M5",
            }
        ),
        encoding="utf-8",
    )
    (knowledge_dir / "market_situation_map.json").write_text("{}", encoding="utf-8")
    (knowledge_dir / "market_situation_map.md").write_text("# map", encoding="utf-8")
    (demo_dir / "latest_signal.json").write_text("{}", encoding="utf-8")
    (demo_dir / "demo_report.md").write_text("# report", encoding="utf-8")
    (demo_dir / "decision_source_audit.jsonl").write_text("{}\n", encoding="utf-8")

    with session_scope() as session:
        channel = Channel(
            input_reference="https://t.me/example",
            title="Example Trading",
            normalized_name="example_trading",
        )
        session.add(channel)
        session.flush()
        chunk = ContentChunk(
            source_type="telegram",
            source_id=1,
            channel_id=channel.id,
            chunk_index=0,
            text="OB rejection setup with liquidity sweep.",
            clean_text="OB rejection setup with liquidity sweep.",
        )
        session.add(chunk)
        session.flush()
        rule = ExtractedRule(
            source_chunk_id=chunk.id,
            channel_id=channel.id,
            rule_type="entry",
            rule_text="Sell after order block rejection.",
            strategy_key="OB Rejection",
        )
        session.add(rule)
        session.flush()
        session.add_all(
            [
                NormalizedRule(
                    extracted_rule_id=rule.id,
                    strategy_family="OB Rejection",
                    setup_name="OB Rejection",
                ),
                StrategyCandidate(
                    candidate_key="ob_rejection_xauusd_m5",
                    setup_name="OB Rejection",
                    strategy_family="OB Rejection",
                ),
                TopStrategyDetected(
                    strategy_key="OB Rejection",
                    name="OB Rejection",
                    strategy_family="OB Rejection",
                    source_count=1,
                    rule_count=1,
                    candidate_count=1,
                ),
                FileAsset(
                    channel_id=channel.id,
                    category="document",
                    file_name="course.pdf",
                    stored_path=str(tmp_path / "course.pdf"),
                ),
            ]
        )

        service = TradingServicePlatformApplicationService(session, settings)
        service.bootstrap_platform(owner_email="owner@example.com", owner_name="Owner")
        account = service.connect_broker_account(
            owner_email="owner@example.com",
            account_label="Main Demo",
            broker_name="Exness",
            symbol_suffix="m",
        )
        service.register_execution_agent(
            account_id=account["account_id"],
            agent_name="vps-exness-01",
            host_name="VPS-EXNESS-01",
        )
        readiness = service.platform_readiness()

        assert readiness["overall_status"] in {"READY", "NEEDS_ATTENTION"}
        assert readiness["operational_clearance"] == "demo_validation_ready"
        assert readiness["knowledge_counts"]["content_chunks"] == 1
        assert readiness["raw_file_counts"]["document"] == 1
        assert readiness["critical_artifacts"]["best_current_strategy"]["required"] is True
        assert readiness["critical_artifacts"]["latest_market_intelligence_json"]["required"] is False
        assert readiness["critical_artifacts"]["latest_market_intelligence_json"]["status"] == "OPTIONAL_MISSING"
        assert readiness["critical_artifacts"]["decision_source_audit_jsonl"]["exists"] is True
        assert {item["component"] for item in readiness["checks"]} >= {
            "learned_knowledge",
            "base_strategy",
            "market_intelligence",
            "execution_shell",
        }


def test_record_execution_agent_runtime_persists_recent_activity(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        service.create_user(email="owner@example.com", display_name="Owner", role="owner")
        account = service.connect_broker_account(
            owner_email="owner@example.com",
            account_label="Main Demo",
            broker_name="Exness",
            symbol_suffix="m",
        )
        agent = service.register_execution_agent(
            account_id=account["account_id"],
            agent_name="vps-exness-01",
            host_name="VPS-EXNESS-01",
        )
        report = service.record_execution_agent_runtime(
            account_id=account["account_id"],
            agent_key=agent["agent_key"],
            cycle_status="completed",
            canonical_symbol="XAUUSD",
            broker_symbol="XAUUSDm",
            local_terminal_ready=True,
            open_positions=[],
            service_root={"service": "BOTEXTRATOR Trading Service API"},
            remote_agent={"agent_id": agent["agent_id"]},
            heartbeat={"status": "online"},
            account_status={
                "is_demo": True,
                "account_info": {
                    "balance": 1000.0,
                    "equity": 1025.5,
                    "profit": 25.5,
                    "margin": 50.0,
                    "margin_free": 975.5,
                    "currency": "USD",
                },
            },
            execution_environment={"symbol_resolved": "XAUUSDm"},
            deployment_runs=[
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
        )
        status = service.platform_status()

        assert report["deployment_reports_created"] == 1
        assert status["recent_agent_cycles"][0]["broker_symbol"] == "XAUUSDm"
        assert status["recent_deployment_runs"][0]["run_status"] == "executed"
        assert status["accounts"][0]["financial_metrics"]["balance"] == 1000.0
        assert status["accounts"][0]["financial_metrics"]["equity"] == 1025.5
        assert status["portfolio_metrics"]["total_equity"] == 1025.5
        assert status["portfolio_metrics"]["growth_percent"] == 2.55

    with session_scope() as session:
        assert session.scalar(select(ExecutionAgentRuntimeReport)) is not None
        assert session.scalar(select(DeploymentExecutionReport)) is not None


def test_account_detail_exposes_mt5_connection_mismatch_and_agent_commands(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        client = service.create_user(email="client@example.com", display_name="Client", role="client")
        connected = service.connect_own_exness_account(
            user_id=client["user_id"],
            account_label="Client Exness Demo",
            broker_server="Exness-MT5Trial11",
            login_reference="198427256",
            symbol_suffix="m",
            referral_confirmed=True,
        )
        service.record_execution_agent_runtime(
            account_id=connected["account_id"],
            agent_key=connected["agent_key"],
            cycle_status="completed",
            canonical_symbol="XAUUSD",
            broker_symbol="XAUUSDm",
            local_terminal_ready=False,
            account_status={
                "is_demo": True,
                "account_info": {
                    "login": 197452102,
                    "server": "Exness-MT5Trial11",
                    "balance": 304.29,
                    "equity": 304.29,
                    "currency": "USD",
                },
            },
            deployment_runs=[
                {
                    "strategy_key": "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
                    "strategy_variant": "v56_aggressive_filtered_b",
                    "operation_mode": "ai_managed",
                    "canonical_symbol": "XAUUSD",
                    "broker_symbol": "XAUUSDm",
                    "status": "blocked_by_terminal_account_mismatch",
                    "execution_status": "blocked_by_terminal_account_mismatch",
                    "intelligence_action": "BLOCKED",
                    "signal_detected": False,
                    "dry_run": True,
                }
            ],
        )

        detail = service.account_detail(account_id=connected["account_id"])
        status = service.platform_status_for_user(user_id=client["user_id"], role="client")

        connection = detail["agent_connection"]
        assert connection["expected"]["login_reference"] == "198427256"
        assert connection["actual"]["login"] == "197452102"
        assert connection["terminal_validation"]["status"] == "account_mismatch"
        assert "login_reference_mismatch" in connection["terminal_validation"]["blockers"]
        assert f"--account-id {connected['account_id']}" in connection["commands"]["dry_run"]
        assert "--dry-run" in connection["commands"]["dry_run"]
        assert "--no-dry-run --confirm-demo" in connection["commands"]["demo_execution"]
        assert status["accounts"][0]["runtime_health"] == "account_mismatch"
        assert status["accounts"][0]["financial_metrics"]["source"] == "terminal_account_mismatch"


def test_account_detail_and_deployment_state_update(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    init_db()

    with session_scope() as session:
        service = TradingServicePlatformApplicationService(session, settings)
        service.create_user(email="owner@example.com", display_name="Owner", role="owner")
        account = service.connect_broker_account(
            owner_email="owner@example.com",
            account_label="Main Demo",
            broker_name="Exness",
            symbol_suffix="m",
        )
        deployment = service.deploy_strategy_mode(
            account_id=account["account_id"],
            strategy_key="MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
            strategy_variant="v56_aggressive_filtered_b",
            operation_mode="ai_managed",
            risk_mode="reduced",
            learning_mode="continuous",
            deployment_status="active",
        )
        detail = service.account_detail(account_id=account["account_id"])
        updated = service.update_deployment_state(
            deployment_id=deployment["deployment_id"],
            deployment_status="paused",
        )

        assert detail["account"]["label"] == "Main Demo"
        assert detail["deployments"][0]["strategy_key"] == "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4"
        assert updated["deployment_status"] == "paused"
