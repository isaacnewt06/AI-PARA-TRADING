"""Final robustness reports for MAXIMO demo-realistic operation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MaximoFinalRobustnessReporter:
    """Writes high-level reports from already audited runtime data."""

    def __init__(self, *, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.robustness_path = reports_dir / "MAXIMO_FINAL_AI_ROBUSTNESS_REPORT.md"
        self.demo_mode_path = reports_dir / "DEMO_REALISTIC_PROFIT_MODE_REPORT.md"
        self.validation_plan_path = reports_dir / "NEXT_3_WEEK_DEMO_VALIDATION_PLAN.md"

    def generate(
        self,
        *,
        symbol: str,
        execution_status: str,
        intelligence: dict[str, Any],
        final_confirmation: dict[str, Any],
        execution_risk_decision: dict[str, Any],
        performance_summary: dict[str, Any],
        real_gate: dict[str, Any],
        harmony_audit: dict[str, Any],
        position_management: dict[str, Any],
    ) -> dict[str, Any]:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        pulse = intelligence.get("market_pulse") or {}
        readiness = intelligence.get("execution_readiness") or {}
        paths = {
            "robustness_report": str(self.robustness_path.resolve()),
            "demo_realistic_profit_mode_report": str(self.demo_mode_path.resolve()),
            "next_3_week_demo_validation_plan": str(self.validation_plan_path.resolve()),
        }
        self.robustness_path.write_text(
            "\n".join(
                [
                    "# MAXIMO Final AI Robustness Report",
                    "",
                    f"- generated_at_utc: {now}",
                    f"- symbol: {symbol}",
                    "- current_mode: DEMO_REALISTIC_PROFIT_MODE",
                    f"- execution_status: {execution_status}",
                    f"- intelligence_action: {readiness.get('action')}",
                    f"- market_pulse_score: {pulse.get('score')}",
                    f"- market_pulse_label: {pulse.get('label')}",
                    f"- final_confirmation_score: {final_confirmation.get('final_confirmation_score')}",
                    f"- final_confirmation_decision: {final_confirmation.get('decision')}",
                    f"- risk_mode: {execution_risk_decision.get('allowed_risk_mode')}",
                    f"- execution_mode: {execution_risk_decision.get('execution_mode')}",
                    f"- position_management_status: {position_management.get('status')}",
                    f"- q_learning_feedback_events: {performance_summary.get('q_learning_real_feedback_events')}",
                    f"- performance_classification: {performance_summary.get('classification')}",
                    f"- harmony_status: {harmony_audit.get('status')}",
                    f"- real_gate_status: {real_gate.get('status')}",
                    "",
                    "## Modules Confirmed",
                    "- Market Intelligence / Market Overview",
                    "- Market Pulse",
                    "- active_watch and watch risk binding",
                    "- FinalConfirmationEngine",
                    "- DirectionConsistencyGuard",
                    "- Q-learning persistent memory and outcome feedback",
                    "- PositionManagementHistory with BE/partial/trailing/fast-exit telemetry",
                    "- Performance Lab",
                    "- RealAccountSafetyGate",
                    "",
                    "## Current Bottlenecks",
                    f"- final_confirmation_blockers: {final_confirmation.get('blockers')}",
                    f"- execution_risk_reason: {execution_risk_decision.get('risk_application_reason')}",
                    f"- harmony_contradictions: {harmony_audit.get('contradictions')}",
                    f"- real_blockers: {real_gate.get('blockers')}",
                    "",
                    "## Technical Recommendation",
                    "- Continue demo-only validation. Do not approve real until the 3-week plan passes objective metrics.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.demo_mode_path.write_text(
            "\n".join(
                [
                    "# Demo Realistic Profit Mode Report",
                    "",
                    f"- generated_at_utc: {now}",
                    "- execution_mode: DEMO_REALISTIC_PROFIT_MODE",
                    "- real_trading: blocked",
                    "- demo_execution: allowed only when all guards pass",
                    f"- account_risk_percent: {execution_risk_decision.get('account_risk_percent')}",
                    f"- max_account_risk_percent: {execution_risk_decision.get('max_account_risk_percent')}",
                    f"- market_pulse: {pulse}",
                    f"- final_confirmation: {final_confirmation}",
                    f"- risk_decision: {execution_risk_decision}",
                    "",
                    "## Operating Rules",
                    "- No weak signals.",
                    "- No trade without SL/TP logic.",
                    "- No trade against thesis unless explicitly classified as countertrend reversal scalp.",
                    "- Protect after favorable MFE according to post-entry managers.",
                    "- Record every action as if this were real-money audit.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.validation_plan_path.write_text(
            "\n".join(
                [
                    "# Next 3 Week Demo Validation Plan",
                    "",
                    f"- generated_at_utc: {now}",
                    "- duration: 21 calendar days minimum",
                    "- instruments: XAUUSDm first, then add symbols only after stability",
                    "- sessions RD: London 03:00-05:00, New York 08:00-11:30",
                    "",
                    "## Daily Metrics",
                    "- trades taken, skipped and blocked with reason",
                    "- MFE/MAE/R final per trade",
                    "- BE, partial, trailing and fast-exit actions",
                    "- trades that reached +0.5R and ended negative",
                    "- Q-learning feedback events",
                    "- Market Pulse vs real movement",
                    "",
                    "## Real Approval Minimums",
                    "- profit_factor >= 1.35",
                    "- positive expectancy R",
                    "- no unprotected +0.5R giveback losses",
                    "- drawdown and daily loss inside owner limits",
                    "- no unexplained BUY/SELL contradictions",
                    "- RealAccountSafetyGate blockers cleared by evidence, not by force.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return paths
