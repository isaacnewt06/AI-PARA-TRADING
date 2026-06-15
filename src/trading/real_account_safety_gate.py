"""Real-account readiness gate for MAXIMO.

This module prepares the future real transition without enabling it. It is
intentionally strict: demo can operate, real stays blocked until objective
evidence exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RealAccountSafetyGate:
    """Audits whether the system is eligible for future real trading."""

    MIN_DEMO_DAYS = 21
    MIN_PROFIT_FACTOR = 1.35
    MIN_TRADES = 30
    MAX_DRAWDOWN_R = 6.0

    def __init__(self, *, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.report_path = reports_dir / "REAL_READY_GAP_ANALYSIS.md"

    def evaluate(
        self,
        *,
        account_status: dict[str, Any],
        execution_environment: dict[str, Any],
        performance_summary: dict[str, Any],
        latest_signal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        requirements: list[str] = []
        account = account_status.get("account_info", {}) or {}
        terminal = account_status.get("terminal_info", {}) or {}
        is_demo = bool(account_status.get("is_demo"))

        if is_demo:
            blockers.append("real_trading_disabled_current_account_is_demo")
        else:
            blockers.append("real_trading_disabled_until_owner_approval_and_demo_validation")
        if performance_summary.get("total_cycles", 0) < 100:
            blockers.append("insufficient_demo_cycles")
        if performance_summary.get("trades_observed", 0) < self.MIN_TRADES:
            blockers.append("insufficient_demo_trades")
        if float(performance_summary.get("profit_factor_proxy") or 0.0) < self.MIN_PROFIT_FACTOR:
            blockers.append("profit_factor_below_real_threshold")
        if float(performance_summary.get("max_drawdown_r_proxy") or 0.0) > self.MAX_DRAWDOWN_R:
            blockers.append("drawdown_above_real_threshold")
        if performance_summary.get("trades_reached_0_5r_then_negative_unprotected", 0):
            blockers.append("post_entry_protection_not_yet_consistent")
        if performance_summary.get("q_learning_real_feedback_events", 0) < max(5, performance_summary.get("trades_observed", 0)):
            blockers.append("q_learning_outcome_feedback_insufficient")
        if str(execution_environment.get("execution_viability") or "").upper() != "SAFE":
            blockers.append("execution_environment_not_safe")
        if not terminal:
            blockers.append("mt5_terminal_status_unknown")
        if latest_signal and latest_signal.get("execution_mode") != "DEMO_REALISTIC_PROFIT_MODE":
            blockers.append("execution_mode_not_demo_realistic_profit")

        requirements.extend(
            [
                "Minimum 3 weeks of consistent demo evidence.",
                "Profit factor >= 1.35 with positive expectancy.",
                "Drawdown controlled and daily loss limit respected.",
                "Post-entry management evidence: BE/partial/fast-exit/trailing logs.",
                "Q-learning feedback from closed trade outcomes.",
                "Owner emergency stop, daily/weekly limits and slippage guard.",
                "No account mismatch, no symbol mismatch, no abnormal spread/news risk.",
            ]
        )

        status = "REAL_BLOCKED_DEMO_ONLY"
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "real_allowed": False,
            "execution_mode_allowed_now": "DEMO_REALISTIC_PROFIT_MODE",
            "account_login": account.get("login"),
            "account_server": account.get("server"),
            "account_is_demo": is_demo,
            "terminal_connected": bool(terminal),
            "execution_viability": execution_environment.get("execution_viability"),
            "blockers": self._dedupe(blockers),
            "requirements": requirements,
            "performance_snapshot": {
                "total_cycles": performance_summary.get("total_cycles"),
                "trades_observed": performance_summary.get("trades_observed"),
                "profit_factor_proxy": performance_summary.get("profit_factor_proxy"),
                "expectancy_r_proxy": performance_summary.get("expectancy_r_proxy"),
                "max_drawdown_r_proxy": performance_summary.get("max_drawdown_r_proxy"),
                "q_learning_real_feedback_events": performance_summary.get("q_learning_real_feedback_events"),
            },
            "reason": "Real trading remains blocked. Demo can operate with realistic-profit rules only.",
            "report_path": str(self.report_path.resolve()),
        }
        self._write_report(payload)
        return payload

    def _write_report(self, payload: dict[str, Any]) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Real Ready Gap Analysis",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- status: {payload['status']}",
            f"- real_allowed: {payload['real_allowed']}",
            f"- execution_mode_allowed_now: {payload['execution_mode_allowed_now']}",
            f"- account_login: {payload.get('account_login')}",
            f"- account_server: {payload.get('account_server')}",
            f"- account_is_demo: {payload.get('account_is_demo')}",
            f"- terminal_connected: {payload.get('terminal_connected')}",
            f"- execution_viability: {payload.get('execution_viability')}",
            f"- reason: {payload.get('reason')}",
            "",
            "## Blockers",
        ]
        for item in payload["blockers"]:
            lines.append(f"- {item}")
        lines.extend(["", "## Requirements Before Real"])
        for item in payload["requirements"]:
            lines.append(f"- {item}")
        lines.extend(["", "## Performance Snapshot"])
        for key, value in payload["performance_snapshot"].items():
            lines.append(f"- {key}: {value}")
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
