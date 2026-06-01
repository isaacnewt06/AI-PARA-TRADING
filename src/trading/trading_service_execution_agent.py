"""Execution agent runtime for broker-side connectivity to the trading service API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.application.run_maximo_quant_v4_demo import MaximoQuantV4DemoApplicationService
from src.core.config import Settings
from src.core.logging import get_logger
from src.trading.mt5_bridge import MT5Bridge

logger = get_logger(__name__)


class TradingServiceExecutionAgentRuntime:
    """Run a local broker-side agent that connects to the platform API."""

    COPY_MAGIC_NUMBER = 560104
    COPY_BASE_RISK_PERCENT = 5.0
    COPY_MAX_RISK_PERCENT = 10.0
    SUPPORTED_MAXIMO_KEYS = {
        "MAXIMO_MTF_QUANT_INSTITUTIONAL_V4",
        "MAXIMO MTF Quant Institutional v4",
    }

    def __init__(
        self,
        settings: Settings,
        *,
        api_base_url: str,
        account_id: int,
        agent_key: str,
        bridge: MT5Bridge | None = None,
        http_client: httpx.Client | None = None,
        demo_executor: Any | None = None,
    ) -> None:
        self.settings = settings
        self.api_base_url = api_base_url.rstrip("/")
        self.account_id = account_id
        self.agent_key = agent_key
        self.bridge = bridge or MT5Bridge(settings)
        self._http_client = http_client
        self._demo_executor = demo_executor
        self.agent_dir = self.settings.paths.data_dir / "service_agents" / f"account_{account_id}"
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_snapshot_path = self.agent_dir / "latest_agent_runtime.json"

    def run_cycle(
        self,
        *,
        canonical_symbol: str = "XAUUSD",
        heartbeat_status: str = "online",
        dry_run: bool = True,
        confirm_demo: bool = False,
        volume_lots: float = 0.01,
        deviation_points: int = 50,
    ) -> dict:
        with self._client() as client:
            root_info = client.get("/").json()
            remote_agent = client.post(
                f"/api/platform/accounts/{self.account_id}/agents/authenticate",
                json={"agent_key": self.agent_key},
            ).json()
            heartbeat = client.post(
                f"/api/platform/accounts/{self.account_id}/agents/heartbeat",
                json={"agent_key": self.agent_key, "status": heartbeat_status},
            ).json()

        resolved_symbol = self._resolve_broker_symbol(
            canonical_symbol=canonical_symbol,
            remote_agent=remote_agent,
        )
        account_status = self.bridge.account_status()
        terminal_validation = self._validate_terminal_account(
            remote_agent=remote_agent,
            account_status=account_status,
        )
        execution_environment = self.bridge.read_execution_environment(symbol=resolved_symbol)
        positions = self.bridge.list_positions(symbol=resolved_symbol)
        deployment_runs = self._run_supported_deployments(
            remote_agent=remote_agent,
            terminal_validation=terminal_validation,
            fallback_canonical_symbol=canonical_symbol,
            account_status=account_status,
            dry_run=dry_run,
            confirm_demo=confirm_demo,
            volume_lots=volume_lots,
            deviation_points=deviation_points,
        )
        central_report = self._post_runtime_report(
            service_root=root_info,
            remote_agent=remote_agent,
            heartbeat=heartbeat,
            canonical_symbol=canonical_symbol,
            broker_symbol=resolved_symbol,
            account_status=account_status,
            terminal_validation=terminal_validation,
            execution_environment=execution_environment,
            open_positions=positions,
            deployment_runs=deployment_runs,
        )

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "api_base_url": self.api_base_url,
            "service_root": root_info,
            "remote_agent": remote_agent,
            "heartbeat": heartbeat,
            "canonical_symbol": canonical_symbol,
            "broker_symbol": resolved_symbol,
            "account_status": account_status,
            "terminal_validation": terminal_validation,
            "execution_environment": execution_environment,
            "open_positions": positions,
            "deployment_runs": deployment_runs,
            "central_report": central_report,
            "local_terminal_ready": account_status.get("is_demo") is True and terminal_validation.get("valid") is True,
        }
        self.runtime_snapshot_path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "Trading service agent cycle completed account_id=%s broker_symbol=%s local_terminal_ready=%s",
            self.account_id,
            resolved_symbol,
            snapshot["local_terminal_ready"],
        )
        return snapshot

    def _run_supported_deployments(
        self,
        *,
        remote_agent: dict[str, Any],
        terminal_validation: dict[str, Any],
        fallback_canonical_symbol: str,
        account_status: dict[str, Any],
        dry_run: bool,
        confirm_demo: bool,
        volume_lots: float,
        deviation_points: int,
    ) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for deployment in remote_agent.get("strategy_deployments") or []:
            strategy_key = str(deployment.get("strategy_key") or "")
            strategy_key_canonical = str(deployment.get("strategy_key_canonical") or strategy_key)
            operation_mode = str(deployment.get("operation_mode") or "")
            deployment_status = str(deployment.get("deployment_status") or "")
            symbol_allowlist = deployment.get("symbol_allowlist") or []
            canonical_symbol = str(symbol_allowlist[0] if symbol_allowlist else fallback_canonical_symbol)
            broker_symbol = self._resolve_broker_symbol(canonical_symbol=canonical_symbol, remote_agent=remote_agent)

            terminal_blocker = self._terminal_execution_blocker(
                terminal_validation=terminal_validation,
                dry_run=dry_run,
            )
            if terminal_blocker:
                runs.append(
                    {
                        "strategy_key": strategy_key,
                        "strategy_key_canonical": strategy_key_canonical,
                        "strategy_variant": deployment.get("strategy_variant"),
                        "operation_mode": operation_mode,
                        "canonical_symbol": canonical_symbol,
                        "broker_symbol": broker_symbol,
                        "status": terminal_blocker,
                        "execution_status": terminal_blocker,
                        "intelligence_action": "BLOCKED",
                        "signal_detected": False,
                        "dry_run": dry_run,
                    }
                )
                continue

            if deployment_status != "active":
                runs.append(
                    {
                        "strategy_key": strategy_key,
                        "strategy_variant": deployment.get("strategy_variant"),
                        "operation_mode": operation_mode,
                        "canonical_symbol": canonical_symbol,
                        "broker_symbol": broker_symbol,
                        "status": "skipped_inactive",
                    }
                )
                continue

            if operation_mode == "signal_mirror":
                runs.append(
                    self._run_signal_mirror_deployment(
                        deployment=deployment,
                        strategy_key=strategy_key,
                        strategy_key_canonical=strategy_key_canonical,
                        canonical_symbol=canonical_symbol,
                        broker_symbol=broker_symbol,
                        account_status=account_status,
                        dry_run=dry_run,
                        confirm_demo=confirm_demo,
                        deviation_points=deviation_points,
                    )
                )
                continue

            if strategy_key_canonical in self.SUPPORTED_MAXIMO_KEYS and operation_mode in {"ai_managed", "hybrid_guarded"}:
                executor = self._demo_executor or MaximoQuantV4DemoApplicationService(self.settings)
                result = executor.run(
                    symbol=broker_symbol,
                    volume_lots=volume_lots,
                    deviation_points=deviation_points,
                    dry_run=dry_run,
                    confirm_demo=confirm_demo,
                )
                runs.append(
                    {
                        "strategy_key": strategy_key,
                        "strategy_key_canonical": strategy_key_canonical,
                        "strategy_variant": deployment.get("strategy_variant"),
                        "operation_mode": operation_mode,
                        "canonical_symbol": canonical_symbol,
                        "broker_symbol": broker_symbol,
                        "status": "executed",
                        "execution_status": result.get("execution_status"),
                        "intelligence_action": result.get("intelligence_action"),
                        "signal_detected": result.get("signal_detected"),
                        "dry_run": result.get("dry_run"),
                        "master_signal": self._build_master_signal(
                            result=result,
                            canonical_symbol=canonical_symbol,
                            broker_symbol=broker_symbol,
                        ),
                    }
                )
                continue

            runs.append(
                {
                    "strategy_key": strategy_key,
                    "strategy_key_canonical": strategy_key_canonical,
                    "strategy_variant": deployment.get("strategy_variant"),
                    "operation_mode": operation_mode,
                    "canonical_symbol": canonical_symbol,
                    "broker_symbol": broker_symbol,
                    "status": "skipped_unsupported",
                }
            )
        return runs

    def _run_signal_mirror_deployment(
        self,
        *,
        deployment: dict[str, Any],
        strategy_key: str,
        strategy_key_canonical: str,
        canonical_symbol: str,
        broker_symbol: str,
        account_status: dict[str, Any],
        dry_run: bool,
        confirm_demo: bool,
        deviation_points: int,
    ) -> dict[str, Any]:
        base_run = {
            "strategy_key": strategy_key,
            "strategy_key_canonical": strategy_key_canonical,
            "strategy_variant": deployment.get("strategy_variant"),
            "operation_mode": "signal_mirror",
            "canonical_symbol": canonical_symbol,
            "broker_symbol": broker_symbol,
            "dry_run": dry_run,
        }
        mirror_signal = self._fetch_copy_master_signal(canonical_symbol=canonical_symbol)
        if not mirror_signal.get("available"):
            return base_run | {
                "status": "no_master_signal",
                "execution_status": "no_master_signal",
                "intelligence_action": "WAIT",
                "signal_detected": False,
                "copy_signal_lookup": mirror_signal,
            }

        master_signal = mirror_signal.get("master_signal") or {}
        side = str(master_signal.get("side") or master_signal.get("direction") or "").lower()
        entry_price = self._optional_float(master_signal.get("entry_price"))
        stop_loss = self._optional_float(master_signal.get("stop_loss") or master_signal.get("stop_price"))
        take_profit = self._optional_float(master_signal.get("take_profit") or master_signal.get("target_price"))
        if side not in {"buy", "sell"} or entry_price is None or stop_loss is None or take_profit is None:
            return base_run | {
                "status": "blocked_invalid_master_signal",
                "execution_status": "blocked_invalid_master_signal",
                "intelligence_action": "BLOCKED",
                "signal_detected": False,
                "copy_signal_lookup": mirror_signal,
            }

        existing_positions = self.bridge.list_positions(symbol=broker_symbol, magic=self.COPY_MAGIC_NUMBER)
        if existing_positions:
            return base_run | {
                "status": "copy_position_already_open",
                "execution_status": "copy_position_already_open",
                "intelligence_action": "EXECUTE",
                "signal_detected": True,
                "source_master_report_id": mirror_signal.get("source_report_id"),
                "master_signal": master_signal,
            }

        risk_mode = str(deployment.get("risk_mode") or "reduced")
        equity = self._account_equity(account_status)
        if equity <= 0:
            return base_run | {
                "status": "blocked_missing_account_equity",
                "execution_status": "blocked_missing_account_equity",
                "intelligence_action": "BLOCKED",
                "signal_detected": True,
                "source_master_report_id": mirror_signal.get("source_report_id"),
                "master_signal": master_signal,
            }
        risk_multiplier = 1.0 if risk_mode == "normal" else (0.0 if risk_mode == "blocked" else 0.5)
        risk_amount = equity * (self.COPY_BASE_RISK_PERCENT / 100.0) * risk_multiplier
        if risk_amount <= 0:
            return base_run | {
                "status": "blocked_by_copy_risk_mode",
                "execution_status": "blocked_by_copy_risk_mode",
                "intelligence_action": "BLOCKED",
                "signal_detected": True,
                "source_master_report_id": mirror_signal.get("source_report_id"),
                "master_signal": master_signal,
            }

        volume_plan = self.bridge.calculate_risk_volume_lots(
            symbol=broker_symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_amount=risk_amount,
        )
        estimated_risk_percent = (float(volume_plan["estimated_risk_amount"]) / equity) * 100.0
        if estimated_risk_percent > self.COPY_MAX_RISK_PERCENT:
            return base_run | {
                "status": "blocked_by_copy_min_lot_exceeds_10_percent_account_risk",
                "execution_status": "blocked_by_copy_min_lot_exceeds_10_percent_account_risk",
                "intelligence_action": "BLOCKED",
                "signal_detected": True,
                "source_master_report_id": mirror_signal.get("source_report_id"),
                "master_signal": master_signal,
                "copy_risk_plan": volume_plan | {
                    "account_equity": equity,
                    "estimated_risk_percent": round(estimated_risk_percent, 4),
                    "risk_mode": risk_mode,
                },
            }

        if dry_run:
            return base_run | {
                "status": "copy_dry_run_signal_detected",
                "execution_status": "copy_dry_run_signal_detected",
                "intelligence_action": "EXECUTE",
                "signal_detected": True,
                "source_master_report_id": mirror_signal.get("source_report_id"),
                "master_signal": master_signal,
                "copy_risk_plan": volume_plan | {
                    "account_equity": equity,
                    "estimated_risk_percent": round(estimated_risk_percent, 4),
                    "risk_mode": risk_mode,
                },
            }
        if not confirm_demo:
            return base_run | {
                "status": "blocked_confirm_demo_required",
                "execution_status": "blocked_confirm_demo_required",
                "intelligence_action": "BLOCKED",
                "signal_detected": True,
                "source_master_report_id": mirror_signal.get("source_report_id"),
                "master_signal": master_signal,
            }
        execution = self.bridge.place_demo_market_order(
            symbol=broker_symbol,
            side=side,
            volume_lots=float(volume_plan["volume_lots"]),
            stop_loss=stop_loss,
            take_profit=take_profit,
            deviation_points=deviation_points,
            magic_number=self.COPY_MAGIC_NUMBER,
            comment=f"COPY{mirror_signal.get('source_report_id') or 0}",
        )
        return base_run | {
            "status": "copy_demo_order_sent",
            "execution_status": "copy_demo_order_sent",
            "intelligence_action": "EXECUTE",
            "signal_detected": True,
            "source_master_report_id": mirror_signal.get("source_report_id"),
            "master_signal": master_signal,
            "copy_risk_plan": volume_plan | {
                "account_equity": equity,
                "estimated_risk_percent": round(estimated_risk_percent, 4),
                "risk_mode": risk_mode,
            },
            "execution": execution,
        }

    def _fetch_copy_master_signal(self, *, canonical_symbol: str) -> dict[str, Any]:
        with self._client() as client:
            return client.post(
                f"/api/platform/accounts/{self.account_id}/copy-trading/master-signal",
                json={
                    "agent_key": self.agent_key,
                    "canonical_symbol": canonical_symbol,
                    "max_age_minutes": 10,
                },
            ).json()

    @staticmethod
    def _build_master_signal(*, result: dict[str, Any], canonical_symbol: str, broker_symbol: str) -> dict[str, Any] | None:
        signal = result.get("signal") if isinstance(result.get("signal"), dict) else None
        if not signal:
            return None
        execution_status = str(result.get("execution_status") or "")
        if execution_status not in {"demo_order_sent", "dry_run_signal_detected"}:
            return None
        side = str(signal.get("direction") or signal.get("side") or "").lower()
        entry_price = signal.get("entry_price")
        stop_loss = signal.get("stop_price") or signal.get("stop_loss")
        take_profit = signal.get("target_price") or signal.get("take_profit")
        if side not in {"buy", "sell"} or entry_price is None or stop_loss is None or take_profit is None:
            return None
        return {
            "status": "copyable",
            "canonical_symbol": canonical_symbol,
            "broker_symbol": broker_symbol,
            "side": side,
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "strategy_variant": result.get("strategy_variant") or signal.get("strategy_variant"),
            "source_execution_status": execution_status,
            "source_dry_run": bool(result.get("dry_run")),
            "quality": signal.get("quality"),
            "risk_mode": (result.get("execution_risk_decision") or {}).get("allowed_risk_mode"),
        }

    @staticmethod
    def _account_equity(account_status: dict[str, Any]) -> float:
        account_info = account_status.get("account_info") if isinstance(account_status.get("account_info"), dict) else {}
        for key in ("equity", "balance"):
            value = TradingServiceExecutionAgentRuntime._optional_float(account_info.get(key))
            if value is not None and value > 0:
                return value
        return 0.0

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _resolve_broker_symbol(self, *, canonical_symbol: str, remote_agent: dict[str, Any]) -> str:
        aliases = remote_agent.get("symbol_aliases") or []
        for item in aliases:
            if str(item.get("canonical_symbol", "")).upper() == canonical_symbol.upper():
                return str(item.get("broker_symbol") or canonical_symbol)
        return self.bridge.resolve_symbol_name(canonical_symbol)

    def _validate_terminal_account(
        self,
        *,
        remote_agent: dict[str, Any],
        account_status: dict[str, Any],
    ) -> dict[str, Any]:
        account_info = account_status.get("account_info") or {}
        expected_login = str(remote_agent.get("login_reference") or "").strip()
        expected_server = str(remote_agent.get("broker_server") or "").strip()
        actual_login = str(account_info.get("login") or "").strip()
        actual_server = str(account_info.get("server") or "").strip()
        blockers: list[str] = []
        if expected_login and actual_login != expected_login:
            blockers.append("login_reference_mismatch")
        if expected_server and actual_server.lower() != expected_server.lower():
            blockers.append("broker_server_mismatch")
        return {
            "valid": not blockers,
            "bound": bool(expected_login or expected_server),
            "expected_login": expected_login or None,
            "actual_login": actual_login or None,
            "expected_server": expected_server or None,
            "actual_server": actual_server or None,
            "blockers": blockers,
        }

    def _terminal_execution_blocker(self, *, terminal_validation: dict[str, Any], dry_run: bool) -> str | None:
        if terminal_validation.get("valid") is not True:
            return "blocked_by_terminal_account_mismatch"
        if not dry_run and terminal_validation.get("bound") is not True:
            return "blocked_by_unbound_terminal_account"
        return None

    def _post_runtime_report(
        self,
        *,
        service_root: dict[str, Any],
        remote_agent: dict[str, Any],
        heartbeat: dict[str, Any],
        canonical_symbol: str,
        broker_symbol: str,
        account_status: dict[str, Any],
        terminal_validation: dict[str, Any],
        execution_environment: dict[str, Any],
        open_positions: list[dict[str, Any]],
        deployment_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "agent_key": self.agent_key,
            "cycle_status": "completed",
            "canonical_symbol": canonical_symbol,
            "broker_symbol": broker_symbol,
            "local_terminal_ready": account_status.get("is_demo") is True and terminal_validation.get("valid") is True,
            "service_root": service_root,
            "remote_agent": remote_agent,
            "heartbeat": heartbeat,
            "account_status": account_status,
            "terminal_validation": terminal_validation,
            "execution_environment": execution_environment,
            "open_positions": open_positions,
            "deployment_runs": deployment_runs,
        }
        with self._client() as client:
            return client.post(
                f"/api/platform/accounts/{self.account_id}/agents/report",
                json=payload,
            ).json()

    def _client(self):
        if self._http_client is not None:
            return _NoCloseClientContext(self._http_client)
        return httpx.Client(base_url=self.api_base_url, timeout=20.0)


class _NoCloseClientContext:
    """Context adapter for injected clients in tests."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def __enter__(self) -> httpx.Client:
        return self.client

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False
