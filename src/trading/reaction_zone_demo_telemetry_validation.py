"""Demo telemetry validation for REACTION_ZONE_MANAGEMENT_OVERLAY_V1.

This module does not create entries or modify live trading logic. It prepares
the gate, schema and audit trail needed to validate management execution on a
demo account.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import Settings
from src.trading.controlled_demo_survival_protocol import ControlledDemoSurvivalProtocolV1
from src.trading.execution_environment_policy import limits_for_symbol


TELEMETRY_FIELDS = [
    "timestamp_utc",
    "trade_id",
    "symbol",
    "side",
    "strategy",
    "profile",
    "account_is_demo",
    "gate_allowed",
    "gate_blockers",
    "entry_price",
    "stop_price",
    "target_price",
    "volume_lots",
    "partial_fill_confirmed",
    "time_to_partial",
    "BE_move_success",
    "BE_move_delay_ms",
    "protected_at_0_8R",
    "trailing_update_count",
    "trailing_delay_ms",
    "slippage_entry",
    "slippage_partial",
    "slippage_exit",
    "spread_at_entry",
    "spread_during_trade",
    "MFE",
    "MAE",
    "realized_R",
    "management_failure_reason",
    "execution_environment",
    "macro_action",
    "session",
    "risk_mode",
    "status",
]


@dataclass(frozen=True, slots=True)
class DemoTelemetryGateResult:
    allowed: bool
    blockers: list[str]
    allowed_risk_mode: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blockers": self.blockers,
            "allowed_risk_mode": self.allowed_risk_mode,
            "reason": self.reason,
        }


class ReactionZoneDemoTelemetryValidation:
    """Prepare and audit demo-only management telemetry."""

    STRATEGY = "REACTION_ZONE_MANAGEMENT_OVERLAY_V1"
    PROFILE = "fast_03_be_08"
    MIN_MANAGED_TRADES = 20
    OBSERVATION_DAYS = 14
    ALLOWED_SESSIONS = {"ny_am", "ny_pm"}

    def __init__(
        self,
        settings: Settings,
        *,
        protocol: ControlledDemoSurvivalProtocolV1 | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.protocol = protocol or ControlledDemoSurvivalProtocolV1()
        self.output_dir = output_dir or (
            self.settings.paths.data_dir / "demo_trading" / "reaction_zone_management_overlay_v1"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_path = self.output_dir / "demo_telemetry_validation.jsonl"
        self.report_path = self.output_dir / "demo_telemetry_validation_report.md"
        self.latest_gate_path = self.output_dir / "latest_demo_telemetry_gate.json"

    def evaluate_gate(
        self,
        *,
        account_status: dict[str, Any],
        execution_environment: dict[str, Any],
        macro_action: str,
        session: str,
        risk_mode: str,
    ) -> DemoTelemetryGateResult:
        blockers: list[str] = []
        symbol = str(execution_environment.get("symbol_resolved") or execution_environment.get("symbol") or "XAUUSDm")
        execution_limits = limits_for_symbol(symbol)
        spread = self._float_or_none(execution_environment.get("live_spread"))
        latency = self._float_or_none(execution_environment.get("live_latency"))
        viability = str(execution_environment.get("execution_viability") or "UNKNOWN").upper()
        if not bool(account_status.get("is_demo", False)):
            blockers.append("account_not_demo")
        if viability != "SAFE":
            blockers.append("execution_environment_not_safe")
        if spread is None:
            blockers.append("spread_unavailable")
        elif spread > execution_limits.max_spread:
            blockers.append("spread_above_survival_threshold")
        if latency is None:
            blockers.append("latency_unavailable")
        elif latency > execution_limits.max_latency:
            blockers.append("latency_unsafe")
        slippage = self._float_or_none(execution_environment.get("slippage_estimated"))
        if slippage is None:
            blockers.append("slippage_unavailable")
        elif slippage > execution_limits.max_slippage:
            blockers.append("slippage_above_survival_threshold")
        if str(macro_action).lower() != "allow":
            blockers.append("macro_not_allow")
        if session not in self.ALLOWED_SESSIONS:
            blockers.append("session_not_allowed")
        if str(risk_mode).lower() != "reduced":
            blockers.append("risk_mode_not_reduced")
        allowed = not blockers
        return DemoTelemetryGateResult(
            allowed=allowed,
            blockers=sorted(set(blockers)),
            allowed_risk_mode="reduced" if allowed else "blocked",
            reason=(
                "Demo telemetry validation allowed for reduced-risk management."
                if allowed
                else "Demo telemetry validation blocked until execution environment is safe."
            ),
        )

    def write_latest_gate(
        self,
        *,
        gate: DemoTelemetryGateResult,
        account_status: dict[str, Any],
        execution_environment: dict[str, Any],
        macro_action: str,
        session: str,
        risk_mode: str,
    ) -> dict[str, Any]:
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "strategy": self.STRATEGY,
            "profile": self.PROFILE,
            "gate": gate.to_dict(),
            "account_is_demo": bool(account_status.get("is_demo", False)),
            "execution_environment": execution_environment,
            "macro_action": macro_action,
            "session": session,
            "risk_mode": risk_mode,
            "telemetry_path": str(self.telemetry_path.resolve()),
            "report_path": str(self.report_path.resolve()),
        }
        self.latest_gate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def new_trade_record(
        self,
        *,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float | None,
        stop_price: float | None,
        target_price: float | None,
        volume_lots: float | None,
        account_is_demo: bool,
        gate: DemoTelemetryGateResult,
        execution_environment: dict[str, Any],
        macro_action: str,
        session: str,
        risk_mode: str,
    ) -> dict[str, Any]:
        spread = execution_environment.get("live_spread")
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side.upper(),
            "strategy": self.STRATEGY,
            "profile": self.PROFILE,
            "account_is_demo": account_is_demo,
            "gate_allowed": gate.allowed,
            "gate_blockers": gate.blockers,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "volume_lots": volume_lots,
            "partial_fill_confirmed": False,
            "time_to_partial": None,
            "BE_move_success": False,
            "BE_move_delay_ms": None,
            "protected_at_0_8R": False,
            "trailing_update_count": 0,
            "trailing_delay_ms": None,
            "slippage_entry": None,
            "slippage_partial": None,
            "slippage_exit": None,
            "spread_at_entry": spread,
            "spread_during_trade": [spread] if spread is not None else [],
            "MFE": 0.0,
            "MAE": 0.0,
            "realized_R": None,
            "management_failure_reason": [],
            "execution_environment": execution_environment.get("execution_viability"),
            "macro_action": macro_action,
            "session": session,
            "risk_mode": risk_mode,
            "status": "PENDING" if gate.allowed else "BLOCKED",
        }

    def assess_trade_record(
        self,
        record: dict[str, Any],
        *,
        execution_environment: dict[str, Any] | None = None,
        macro_action: str | None = None,
    ) -> dict[str, Any]:
        reasons = list(record.get("management_failure_reason") or [])
        spread_values = [value for value in record.get("spread_during_trade", []) if isinstance(value, (int, float))]
        if execution_environment is not None:
            symbol = str(execution_environment.get("symbol_resolved") or execution_environment.get("symbol") or record.get("symbol") or "XAUUSDm")
            execution_limits = limits_for_symbol(symbol)
            current_spread = self._float_or_none(execution_environment.get("live_spread"))
            current_latency = self._float_or_none(execution_environment.get("live_latency"))
            current_viability = str(execution_environment.get("execution_viability") or "UNKNOWN").upper()
            if current_spread is not None:
                spread_values.append(current_spread)
            if current_viability != "SAFE":
                reasons.append("execution_environment_left_safe")
            if current_spread is not None and current_spread > execution_limits.max_spread:
                reasons.append("spread_degraded_during_trade")
            if current_latency is not None and current_latency > execution_limits.max_latency:
                reasons.append("latency_degraded_during_trade")
        if macro_action is not None and str(macro_action).lower() == "block":
            reasons.append("macro_changed_to_block")
        if record.get("partial_required") and not record.get("partial_fill_confirmed"):
            reasons.append("partial_not_confirmed")
        if record.get("BE_required") and not record.get("BE_move_success"):
            reasons.append("BE_move_failed")
        record["spread_during_trade"] = spread_values
        record["management_failure_reason"] = sorted(set(reasons))
        if reasons:
            record["status"] = "BLOCKED"
        elif record.get("realized_R") is not None:
            record["status"] = "CLOSED"
        elif record.get("gate_allowed"):
            record["status"] = "MANAGING"
        return record

    def append_trade_record(self, record: dict[str, Any]) -> None:
        normalized = {field: record.get(field) for field in TELEMETRY_FIELDS}
        with self.telemetry_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")

    def read_records(self) -> list[dict[str, Any]]:
        if not self.telemetry_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.telemetry_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
        return rows

    def build_summary(self) -> dict[str, Any]:
        records = self.read_records()
        managed = [row for row in records if row.get("status") in {"MANAGING", "CLOSED"}]
        closed = [row for row in records if row.get("status") == "CLOSED"]
        blocked = [row for row in records if row.get("status") == "BLOCKED"]
        failures: dict[str, int] = {}
        for row in records:
            for reason in row.get("management_failure_reason") or []:
                failures[str(reason)] = failures.get(str(reason), 0) + 1
            for blocker in row.get("gate_blockers") or []:
                failures[str(blocker)] = failures.get(str(blocker), 0) + 1
        realized = [float(row["realized_R"]) for row in closed if isinstance(row.get("realized_R"), (int, float))]
        summary = {
            "strategy": self.STRATEGY,
            "profile": self.PROFILE,
            "managed_demo_trades": len(managed),
            "closed_demo_trades": len(closed),
            "blocked_records": len(blocked),
            "target_managed_trades": self.MIN_MANAGED_TRADES,
            "observation_days_target": self.OBSERVATION_DAYS,
            "partial_fill_confirmed": sum(1 for row in records if row.get("partial_fill_confirmed")),
            "BE_move_success": sum(1 for row in records if row.get("BE_move_success")),
            "protected_at_0_8R": sum(1 for row in records if row.get("protected_at_0_8R")),
            "avg_realized_R": round(sum(realized) / len(realized), 4) if realized else None,
            "failure_counts": failures,
            "conclusion": self._conclusion(records=records, managed=managed, failures=failures),
            "telemetry_path": str(self.telemetry_path.resolve()),
            "report_path": str(self.report_path.resolve()),
        }
        return summary

    def write_report(self) -> dict[str, Any]:
        summary = self.build_summary()
        lines = [
            "# DEMO_TELEMETRY_VALIDATION - REACTION_ZONE_MANAGEMENT_OVERLAY_V1",
            "",
            f"- generated_at_utc: {datetime.now(timezone.utc).isoformat()}",
            f"- strategy: {summary['strategy']}",
            f"- profile: {summary['profile']}",
            f"- managed_demo_trades: {summary['managed_demo_trades']}",
            f"- closed_demo_trades: {summary['closed_demo_trades']}",
            f"- blocked_records: {summary['blocked_records']}",
            f"- target_managed_trades: {summary['target_managed_trades']}",
            f"- observation_days_target: {summary['observation_days_target']}",
            f"- partial_fill_confirmed: {summary['partial_fill_confirmed']}",
            f"- BE_move_success: {summary['BE_move_success']}",
            f"- protected_at_0_8R: {summary['protected_at_0_8R']}",
            f"- avg_realized_R: {summary['avg_realized_R']}",
            "",
            "## Failure Counts",
        ]
        if summary["failure_counts"]:
            for reason, count in sorted(summary["failure_counts"].items()):
                lines.append(f"- {reason}: {count}")
        else:
            lines.append("- none")
        lines.extend(["", "## Conclusion", f"- {summary['conclusion']}", ""])
        self.report_path.write_text("\n".join(lines), encoding="utf-8")
        return summary

    @classmethod
    def session_from_hour_ny(cls, hour_ny: int | None) -> str:
        """Use the same validated session labels as the survival protocol."""
        return ControlledDemoSurvivalProtocolV1._session_label(hour_ny)

    @staticmethod
    def _conclusion(
        *,
        records: list[dict[str, Any]],
        managed: list[dict[str, Any]],
        failures: dict[str, int],
    ) -> str:
        if not records or len(managed) < ReactionZoneDemoTelemetryValidation.MIN_MANAGED_TRADES:
            if any(reason in failures for reason in ("execution_environment_not_safe", "spread_above_survival_threshold")):
                return "EXECUTION ENVIRONMENT UNSAFE"
            return "INSUFFICIENT DATA"
        if any(
            reason in failures
            for reason in (
                "partial_not_confirmed",
                "BE_move_failed",
                "execution_environment_left_safe",
                "spread_degraded_during_trade",
                "latency_degraded_during_trade",
                "macro_changed_to_block",
            )
        ):
            return "MANAGEMENT NEEDS FIX"
        return "MANAGEMENT DEMO APPROVED"

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
