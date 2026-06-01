from __future__ import annotations

import json
from pathlib import Path

import httpx

from src.core.config import reload_settings
from src.trading.trading_service_execution_agent import TradingServiceExecutionAgentRuntime


class _FakeBridge:
    def __init__(self) -> None:
        self.execution_symbol = None
        self.risk_calls: list[dict] = []
        self.order_calls: list[dict] = []

    def account_status(self) -> dict:
        return {
            "is_demo": True,
            "account_info": {"login": 197452102, "server": "Demo-Server", "balance": 1000.0, "equity": 1000.0},
            "terminal_path": r"C:\Program Files\Exness MetaTrader 5\terminal64.exe",
        }

    def read_execution_environment(self, *, symbol: str) -> dict:
        self.execution_symbol = symbol
        return {
            "symbol_requested": symbol,
            "symbol_resolved": symbol,
            "bid": 2350.2,
            "ask": 2350.5,
            "live_spread": 0.3,
        }

    def list_positions(self, *, symbol: str | None = None, magic: int | None = None) -> list[dict]:
        return []

    def resolve_symbol_name(self, symbol: str) -> str:
        return f"{symbol}m"

    def calculate_risk_volume_lots(self, **kwargs) -> dict:
        self.risk_calls.append(kwargs)
        risk_amount = float(kwargs["risk_amount"])
        return {
            "symbol_requested": kwargs["symbol"],
            "symbol_resolved": kwargs["symbol"],
            "entry_price": kwargs["entry_price"],
            "stop_loss": kwargs["stop_loss"],
            "risk_amount": risk_amount,
            "risk_per_lot": 100.0,
            "requested_volume_lots": risk_amount / 100.0,
            "volume_lots": round(risk_amount / 100.0, 2),
            "estimated_risk_amount": risk_amount,
            "estimated_risk_percent_of_target": 1.0,
            "sizing_method": "test",
            "symbol_info": {"volume_min": 0.01},
        }

    def place_demo_market_order(self, **kwargs) -> dict:
        self.order_calls.append(kwargs)
        return {"request": kwargs, "result": {"retcode": 10009}}


class _FakeDemoExecutor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(
        self,
        *,
        symbol: str,
        volume_lots: float = 0.01,
        deviation_points: int = 50,
        dry_run: bool = True,
        confirm_demo: bool = False,
    ) -> dict:
        self.calls.append(
            {
                "symbol": symbol,
                "volume_lots": volume_lots,
                "deviation_points": deviation_points,
                "dry_run": dry_run,
                "confirm_demo": confirm_demo,
            }
        )
        return {
            "execution_status": "dry_run_signal_detected",
            "intelligence_action": "EXECUTE",
            "signal_detected": True,
            "dry_run": dry_run,
        }


def _configure(tmp_path: Path):
    return reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'agent_runtime.db').as_posix()}",
        }
    )


def test_execution_agent_runtime_authenticates_heartbeats_and_persists_snapshot(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    bridge = _FakeBridge()
    demo_executor = _FakeDemoExecutor()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(200, json={"service": "BOTEXTRATOR Trading Service API"})
        if request.method == "POST" and request.url.path == "/api/platform/accounts/7/agents/authenticate":
            payload = {
                "agent_id": 3,
                "account_id": 7,
                "agent_name": "vps-exness-01",
                "status": "provisioned",
                "broker_name": "Exness",
                "platform_type": "MT5",
                "is_demo": True,
                "broker_server": "Demo-Server",
                "login_reference": "197452102",
                "strategy_deployments": [
                    {
                        "strategy_key": "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
                        "strategy_variant": "v56_aggressive_filtered_b",
                        "operation_mode": "ai_managed",
                        "risk_mode": "reduced",
                        "deployment_status": "active",
                        "symbol_allowlist": ["XAUUSD"],
                    }
                ],
                "symbol_aliases": [
                    {"canonical_symbol": "XAUUSD", "broker_symbol": "XAUUSDm"},
                ],
            }
            return httpx.Response(200, json=payload)
        if request.method == "POST" and request.url.path == "/api/platform/accounts/7/agents/heartbeat":
            return httpx.Response(
                200,
                json={
                    "agent_id": 3,
                    "account_id": 7,
                    "status": "online",
                    "last_heartbeat_at": "2026-05-27T12:00:00+00:00",
                },
            )
        if request.method == "POST" and request.url.path == "/api/platform/accounts/7/agents/report":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["broker_symbol"] == "XAUUSDm"
            assert payload["local_terminal_ready"] is True
            assert payload["terminal_validation"]["valid"] is True
            assert payload["deployment_runs"][0]["status"] == "executed"
            return httpx.Response(
                200,
                json={
                    "runtime_report_id": 11,
                    "agent_id": 3,
                    "account_id": 7,
                    "cycle_status": "completed",
                    "deployment_reports_created": 1,
                    "deployment_report_ids": [21],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handler))
    runtime = TradingServiceExecutionAgentRuntime(
        settings,
        api_base_url="http://testserver",
        account_id=7,
        agent_key="agent-secret",
        bridge=bridge,
        http_client=client,
        demo_executor=demo_executor,
    )

    result = runtime.run_cycle(canonical_symbol="XAUUSD")

    assert result["remote_agent"]["account_id"] == 7
    assert result["heartbeat"]["status"] == "online"
    assert result["broker_symbol"] == "XAUUSDm"
    assert bridge.execution_symbol == "XAUUSDm"
    assert result["deployment_runs"][0]["status"] == "executed"
    assert result["terminal_validation"]["valid"] is True
    assert result["central_report"]["runtime_report_id"] == 11
    assert demo_executor.calls[0]["symbol"] == "XAUUSDm"
    assert runtime.runtime_snapshot_path.exists()


def test_execution_agent_runtime_falls_back_to_local_symbol_resolution(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    bridge = _FakeBridge()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(200, json={"service": "BOTEXTRATOR Trading Service API"})
        if request.method == "POST" and request.url.path.endswith("/authenticate"):
            return httpx.Response(
                200,
                json={
                    "agent_id": 4,
                    "account_id": 8,
                    "agent_name": "fallback-agent",
                    "status": "provisioned",
                    "broker_name": "Exness",
                    "platform_type": "MT5",
                    "is_demo": True,
                    "strategy_deployments": [],
                    "symbol_aliases": [],
                },
            )
        if request.method == "POST" and request.url.path.endswith("/heartbeat"):
            return httpx.Response(
                200,
                json={
                    "agent_id": 4,
                    "account_id": 8,
                    "status": "online",
                    "last_heartbeat_at": "2026-05-27T12:00:00+00:00",
                },
            )
        if request.method == "POST" and request.url.path.endswith("/report"):
            return httpx.Response(
                200,
                json={
                    "runtime_report_id": 12,
                    "agent_id": 4,
                    "account_id": 8,
                    "cycle_status": "completed",
                    "deployment_reports_created": 0,
                    "deployment_report_ids": [],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handler))
    runtime = TradingServiceExecutionAgentRuntime(
        settings,
        api_base_url="http://testserver",
        account_id=8,
        agent_key="fallback-secret",
        bridge=bridge,
        http_client=client,
    )

    result = runtime.run_cycle(canonical_symbol="BTCUSD")

    assert result["broker_symbol"] == "BTCUSDm"
    assert bridge.execution_symbol == "BTCUSDm"


def test_execution_agent_blocks_when_terminal_login_does_not_match_account(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    bridge = _FakeBridge()
    demo_executor = _FakeDemoExecutor()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(200, json={"service": "BOTEXTRATOR Trading Service API"})
        if request.method == "POST" and request.url.path.endswith("/authenticate"):
            return httpx.Response(
                200,
                json={
                    "agent_id": 6,
                    "account_id": 10,
                    "agent_name": "wrong-terminal-agent",
                    "status": "provisioned",
                    "broker_name": "Exness",
                    "platform_type": "MT5",
                    "is_demo": True,
                    "broker_server": "Demo-Server",
                    "login_reference": "999999",
                    "strategy_deployments": [
                        {
                            "strategy_key": "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
                            "strategy_variant": "v56_aggressive_filtered_b",
                            "operation_mode": "ai_managed",
                            "risk_mode": "reduced",
                            "deployment_status": "active",
                            "symbol_allowlist": ["XAUUSD"],
                        }
                    ],
                    "symbol_aliases": [{"canonical_symbol": "XAUUSD", "broker_symbol": "XAUUSDm"}],
                },
            )
        if request.method == "POST" and request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"agent_id": 6, "account_id": 10, "status": "online"})
        if request.method == "POST" and request.url.path.endswith("/report"):
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["local_terminal_ready"] is False
            assert payload["terminal_validation"]["blockers"] == ["login_reference_mismatch"]
            assert payload["deployment_runs"][0]["status"] == "blocked_by_terminal_account_mismatch"
            return httpx.Response(
                200,
                json={
                    "runtime_report_id": 14,
                    "agent_id": 6,
                    "account_id": 10,
                    "cycle_status": "completed",
                    "deployment_reports_created": 1,
                    "deployment_report_ids": [41],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handler))
    runtime = TradingServiceExecutionAgentRuntime(
        settings,
        api_base_url="http://testserver",
        account_id=10,
        agent_key="wrong-terminal-secret",
        bridge=bridge,
        http_client=client,
        demo_executor=demo_executor,
    )

    result = runtime.run_cycle(canonical_symbol="XAUUSD")

    assert result["local_terminal_ready"] is False
    assert result["terminal_validation"]["valid"] is False
    assert result["deployment_runs"][0]["execution_status"] == "blocked_by_terminal_account_mismatch"
    assert demo_executor.calls == []


def test_execution_agent_signal_mirror_waits_without_master_signal(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    bridge = _FakeBridge()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(200, json={"service": "BOTEXTRATOR Trading Service API"})
        if request.method == "POST" and request.url.path.endswith("/authenticate"):
            return httpx.Response(
                200,
                json={
                    "agent_id": 5,
                    "account_id": 9,
                    "agent_name": "hybrid-agent",
                    "status": "provisioned",
                    "broker_name": "Exness",
                    "platform_type": "MT5",
                    "is_demo": True,
                    "strategy_deployments": [
                        {
                            "strategy_key": "external_signal_bot",
                            "strategy_variant": "ob_rejection_guarded",
                            "operation_mode": "signal_mirror",
                            "risk_mode": "reduced",
                            "deployment_status": "active",
                            "symbol_allowlist": ["BTCUSD"],
                        }
                    ],
                    "symbol_aliases": [{"canonical_symbol": "BTCUSD", "broker_symbol": "BTCUSDm"}],
                },
            )
        if request.method == "POST" and request.url.path.endswith("/heartbeat"):
            return httpx.Response(
                200,
                json={
                    "agent_id": 5,
                    "account_id": 9,
                    "status": "online",
                    "last_heartbeat_at": "2026-05-27T12:00:00+00:00",
                },
            )
        if request.method == "POST" and request.url.path.endswith("/copy-trading/master-signal"):
            return httpx.Response(
                200,
                json={
                    "available": False,
                    "reason": "no_recent_copyable_owner_signal",
                    "canonical_symbol": "BTCUSD",
                    "max_age_minutes": 10,
                },
            )
        if request.method == "POST" and request.url.path.endswith("/report"):
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["deployment_runs"][0]["status"] == "no_master_signal"
            return httpx.Response(
                200,
                json={
                    "runtime_report_id": 13,
                    "agent_id": 5,
                    "account_id": 9,
                    "cycle_status": "completed",
                    "deployment_reports_created": 1,
                    "deployment_report_ids": [31],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handler))
    runtime = TradingServiceExecutionAgentRuntime(
        settings,
        api_base_url="http://testserver",
        account_id=9,
        agent_key="hybrid-secret",
        bridge=bridge,
        http_client=client,
    )

    result = runtime.run_cycle(canonical_symbol="BTCUSD")

    assert result["deployment_runs"][0]["status"] == "no_master_signal"
    assert result["central_report"]["deployment_reports_created"] == 1


def test_execution_agent_signal_mirror_copies_master_signal_with_account_risk(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    bridge = _FakeBridge()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/":
            return httpx.Response(200, json={"service": "BOTEXTRATOR Trading Service API"})
        if request.method == "POST" and request.url.path.endswith("/authenticate"):
            return httpx.Response(
                200,
                json={
                    "agent_id": 15,
                    "account_id": 19,
                    "agent_name": "client-copy-agent",
                    "status": "provisioned",
                    "broker_name": "Exness",
                    "platform_type": "MT5",
                    "is_demo": True,
                    "broker_server": "Demo-Server",
                    "login_reference": "197452102",
                    "strategy_deployments": [
                        {
                            "strategy_key": "OWNER_MASTER_COPY",
                            "strategy_variant": "owner_signal_v1",
                            "operation_mode": "signal_mirror",
                            "risk_mode": "reduced",
                            "deployment_status": "active",
                            "symbol_allowlist": ["XAUUSD"],
                        }
                    ],
                    "symbol_aliases": [{"canonical_symbol": "XAUUSD", "broker_symbol": "XAUUSDm"}],
                },
            )
        if request.method == "POST" and request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"agent_id": 15, "account_id": 19, "status": "online"})
        if request.method == "POST" and request.url.path.endswith("/copy-trading/master-signal"):
            return httpx.Response(
                200,
                json={
                    "available": True,
                    "source_report_id": 501,
                    "source_account_id": 1,
                    "age_minutes": 0.5,
                    "master_signal": {
                        "status": "copyable",
                        "canonical_symbol": "XAUUSD",
                        "broker_symbol": "XAUUSDm",
                        "side": "sell",
                        "entry_price": 4500.0,
                        "stop_loss": 4505.0,
                        "take_profit": 4485.0,
                        "source_report_id": 501,
                    },
                },
            )
        if request.method == "POST" and request.url.path.endswith("/report"):
            payload = json.loads(request.content.decode("utf-8"))
            run = payload["deployment_runs"][0]
            assert run["status"] == "copy_dry_run_signal_detected"
            assert run["source_master_report_id"] == 501
            assert run["copy_risk_plan"]["risk_amount"] == 25.0
            assert run["copy_risk_plan"]["volume_lots"] == 0.25
            return httpx.Response(
                200,
                json={
                    "runtime_report_id": 88,
                    "agent_id": 15,
                    "account_id": 19,
                    "cycle_status": "completed",
                    "deployment_reports_created": 1,
                    "deployment_report_ids": [89],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handler))
    runtime = TradingServiceExecutionAgentRuntime(
        settings,
        api_base_url="http://testserver",
        account_id=19,
        agent_key="copy-secret",
        bridge=bridge,
        http_client=client,
    )

    result = runtime.run_cycle(canonical_symbol="XAUUSD", dry_run=True)

    assert result["deployment_runs"][0]["execution_status"] == "copy_dry_run_signal_detected"
    assert bridge.risk_calls[0]["risk_amount"] == 25.0
    assert bridge.order_calls == []
