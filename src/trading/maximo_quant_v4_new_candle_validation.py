"""New closed M5 candle validation monitor for MAXIMO Quant v4."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import Settings
from src.trading.maximo_quant_v4_demo_engine import MaximoQuantV4DemoEngine


class MaximoQuantV4NewCandleValidationMonitor:
    """Run dry validation only once per newly closed M5 candle.

    This monitor deliberately does not change trading rules. It only controls
    *when* a validation sample is counted so fast polling cannot inflate results
    by evaluating the same candle repeatedly.
    """

    MODE_NAME = "NEW_CANDLE_VALIDATION_MODE"

    def __init__(self, settings: Settings, *, engine: MaximoQuantV4DemoEngine | None = None) -> None:
        self.settings = settings
        self.engine = engine or MaximoQuantV4DemoEngine(settings)
        self.output_dir = self.settings.paths.data_dir / "demo_trading" / "maximo_quant_v4"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        symbol: str,
        target_unique_candles: int = 50,
        max_attempts: int = 5_000,
        poll_seconds: float = 10.0,
        session_label: str = "manual",
    ) -> dict[str, Any]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        events_path = self.output_dir / f"new_candle_validation_{run_id}.jsonl"
        summary_path = self.output_dir / f"new_candle_validation_{run_id}_summary.md"
        state: dict[str, Any] = {
            "run_id": run_id,
            "mode": self.MODE_NAME,
            "symbol": symbol,
            "session_label": session_label,
            "target_unique_candles": int(target_unique_candles),
            "unique_candle_count": 0,
            "repeated_cycle_count": 0,
            "attempt_count": 0,
            "last_counted_candle_time": None,
            "signal_state_per_candle": [],
            "managed_signals": [],
        }

        while state["unique_candle_count"] < target_unique_candles and state["attempt_count"] < max_attempts:
            state["attempt_count"] += 1
            candle_time = self._latest_closed_m5_candle_time(symbol=symbol)
            if candle_time is None:
                event = self._skip_event(state=state, symbol=symbol, reason="no_closed_m5_candle", candle_time=None)
                self._append_jsonl(events_path, event)
                self._sleep(poll_seconds)
                continue
            if candle_time == state["last_counted_candle_time"]:
                state["repeated_cycle_count"] += 1
                event = self._skip_event(
                    state=state,
                    symbol=symbol,
                    reason="repeated_candle_skip",
                    candle_time=candle_time,
                )
                self._append_jsonl(events_path, event)
                self._sleep(poll_seconds)
                continue

            state["last_counted_candle_time"] = candle_time
            result = self.engine.run(symbol=symbol, dry_run=True, confirm_demo=False)
            record = self._record_valid_candle(
                state=state,
                symbol=symbol,
                candle_time=candle_time,
                result=result,
            )
            self._append_jsonl(events_path, record)

        summary = self._build_summary(state=state, events_path=events_path, summary_path=summary_path)
        summary_path.write_text(self._render_summary(summary), encoding="utf-8")
        return summary

    def _latest_closed_m5_candle_time(self, *, symbol: str) -> str | None:
        snapshot = self.engine.bridge.read_market_snapshot(symbol=symbol, bars_by_timeframe={"M5": 3})
        candles = snapshot.get("candles", {}).get("M5", [])
        if len(candles) >= 2:
            return candles[-2].time.isoformat()
        timeframe = snapshot.get("timeframes", {}).get("M5", {})
        return timeframe.get("last_bar_time")

    def _record_valid_candle(
        self,
        *,
        state: dict[str, Any],
        symbol: str,
        candle_time: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        state["unique_candle_count"] += 1
        signal = result.get("signal") or {}
        active_watch = result.get("active_watch") or {}
        watch_policy = result.get("watch_execution_policy") or {}
        risk = result.get("execution_risk_decision") or {}
        expansion_audit = result.get("expansion_subtype_pretrade_audit") or {}
        audit = self._last_decision_source_audit()
        layer = (audit or {}).get("intelligence_layer", {})
        ob_families = layer.get("ob_rejection_families", {}) or {}
        active_family = (
            signal.get("active_family")
            or layer.get("operational_family")
            or ob_families.get("active_family")
            or active_watch.get("operational_family")
            or "NONE"
        )
        signal_type = signal.get("signal_type")
        critical_normal_risk_error = bool(
            signal_type == "OB_AGGRESSIVE_REDUCED_SIGNAL" and risk.get("allowed_risk_mode") == "normal"
        )
        record = {
            "event": "new_closed_m5_candle_validated",
            "mode": self.MODE_NAME,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "unique_candle_index": state["unique_candle_count"],
            "attempt": state["attempt_count"],
            "candle_time": candle_time,
            "execution_status": result.get("execution_status"),
            "intelligence_action": result.get("intelligence_action"),
            "signal_detected": bool(result.get("signal")),
            "signal_type": signal_type,
            "active_family": active_family,
            "watch_policy_action": watch_policy.get("watch_policy_action") or active_watch.get("watch_policy_action"),
            "risk_mode": signal.get("risk_mode"),
            "allowed_risk_mode": risk.get("allowed_risk_mode"),
            "execution_mode": risk.get("execution_mode"),
            "setup_maturity": layer.get("setup_maturity"),
            "confidence": layer.get("confidence"),
            "harmony_score": result.get("harmony_score"),
            "main_blocker": (audit or {}).get("decision_attribution", {}).get("main_blocker"),
            "partial_0_5r_simulated": False,
            "protected_0_8r_simulated": False,
            "realized_R": None,
            "critical_normal_risk_error": critical_normal_risk_error,
            "expansion_subtype_pretrade_candidate_detected": bool(expansion_audit.get("candidate_detected")),
            "expansion_subtype": expansion_audit.get("subtype"),
            "expansion_subtype_confidence": expansion_audit.get("subtype_confidence"),
            "expansion_expected_edge_bucket": expansion_audit.get("expected_edge_bucket"),
            "expansion_subtype_reason": expansion_audit.get("subtype_reason"),
            "expansion_historical_warning": expansion_audit.get("historical_warning"),
            "expansion_lookahead_safe": expansion_audit.get("lookahead_safe"),
        }
        state["signal_state_per_candle"].append(record)
        if signal_type == "OB_AGGRESSIVE_REDUCED_SIGNAL":
            state["managed_signals"].append(
                {
                    **record,
                    "entry_price": signal.get("entry_price"),
                    "stop_price": signal.get("stop_price"),
                    "target_price": signal.get("target_price"),
                    "selected_rr": signal.get("selected_rr"),
                    "final_result_after_management": "open/unknown",
                }
            )
        return record

    def _skip_event(
        self,
        *,
        state: dict[str, Any],
        symbol: str,
        reason: str,
        candle_time: str | None,
    ) -> dict[str, Any]:
        return {
            "event": reason,
            "mode": self.MODE_NAME,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "attempt": state["attempt_count"],
            "unique_candle_count": state["unique_candle_count"],
            "repeated_cycle_count": state["repeated_cycle_count"],
            "candle_time": candle_time,
        }

    def _build_summary(self, *, state: dict[str, Any], events_path: Path, summary_path: Path) -> dict[str, Any]:
        records = list(state["signal_state_per_candle"])
        managed = list(state["managed_signals"])
        realized = [float(item["realized_R"]) for item in managed if isinstance(item.get("realized_R"), (int, float))]
        active_family_counts = self._count(records, "active_family")
        policy_counts = self._count(records, "watch_policy_action")
        signal_counts = self._count(records, "signal_type")
        expansion_records = [item for item in records if item.get("expansion_subtype_pretrade_candidate_detected")]
        expansion_bucket_counts = self._count(expansion_records, "expansion_expected_edge_bucket")
        expansion_subtype_counts = self._count(expansion_records, "expansion_subtype")
        expansion_lookahead_risk_count = sum(1 for item in expansion_records if item.get("expansion_lookahead_safe") is False)
        conclusion = self._conclusion(records=records, managed=managed, realized=realized)
        return {
            "run_id": state["run_id"],
            "mode": self.MODE_NAME,
            "symbol": state["symbol"],
            "session_label": state["session_label"],
            "attempt_count": state["attempt_count"],
            "unique_candle_count": state["unique_candle_count"],
            "repeated_cycle_count": state["repeated_cycle_count"],
            "target_unique_candles": state["target_unique_candles"],
            "ob_aggressive_reduced_signal": signal_counts.get("OB_AGGRESSIVE_REDUCED_SIGNAL", 0),
            "ob_rejection_institutional_execute": active_family_counts.get("OB_REJECTION_INSTITUTIONAL_EXECUTE", 0),
            "prepare_reduced": policy_counts.get("PREPARE_REDUCED", 0),
            "execute_reduced": sum(1 for item in records if item.get("execution_mode") == "reduced_execution"),
            "execute_institutional": sum(
                1
                for item in records
                if item.get("active_family") == "OB_REJECTION_INSTITUTIONAL_EXECUTE"
                and item.get("intelligence_action") == "EXECUTE"
            ),
            "partial_0_5r": sum(1 for item in managed if item.get("partial_0_5r_simulated")),
            "protection_0_8r": sum(1 for item in managed if item.get("protected_0_8r_simulated")),
            "managed_signals_with_realized_r": len(realized),
            "expectancy_simulated_r": round(sum(realized) / len(realized), 4) if realized else None,
            "active_family_counts": active_family_counts,
            "watch_policy_action_counts": policy_counts,
            "signal_type_counts": signal_counts,
            "critical_normal_risk_errors": sum(1 for item in records if item.get("critical_normal_risk_error")),
            "expansion_subtype_pretrade_candidates": len(expansion_records),
            "expansion_favorable_research": expansion_bucket_counts.get("favorable_research", 0),
            "expansion_avoid_research": expansion_bucket_counts.get("avoid_research", 0),
            "expansion_unknown_research": expansion_bucket_counts.get("unknown_research", 0),
            "expansion_lookahead_risk_count": expansion_lookahead_risk_count,
            "expansion_expected_edge_bucket_counts": expansion_bucket_counts,
            "expansion_subtype_counts": expansion_subtype_counts,
            "expansion_telemetry_conclusion": self._expansion_telemetry_conclusion(
                candidates=len(expansion_records),
                lookahead_risk_count=expansion_lookahead_risk_count,
                bucket_counts=expansion_bucket_counts,
            ),
            "conclusion": conclusion,
            "events_path": str(events_path.resolve()),
            "summary_path": str(summary_path.resolve()),
        }

    @staticmethod
    def _conclusion(*, records: list[dict[str, Any]], managed: list[dict[str, Any]], realized: list[float]) -> str:
        if not records:
            return "NECESITA MÁS DATOS"
        if any(item.get("critical_normal_risk_error") for item in records):
            return "EDGE INSUFICIENTE"
        setup_records = [
            item
            for item in records
            if item.get("signal_type") == "OB_AGGRESSIVE_REDUCED_SIGNAL"
            or item.get("active_family") == "OB_REJECTION_INSTITUTIONAL_EXECUTE"
        ]
        if not setup_records:
            return "MERCADO NO GENERÓ SETUPS"
        if len(realized) < 5:
            return "NECESITA MÁS DATOS"
        expectancy = sum(realized) / len(realized)
        return "EDGE CONFIRMADO" if expectancy > 0 else "EDGE INSUFICIENTE"

    @staticmethod
    def _expansion_telemetry_conclusion(*, candidates: int, lookahead_risk_count: int, bucket_counts: dict[str, int]) -> str:
        if lookahead_risk_count > 0:
            return "LOOKAHEAD_RISK"
        if candidates == 0:
            return "NEEDS_MORE_DATA"
        bucketed = (
            bucket_counts.get("favorable_research", 0)
            + bucket_counts.get("avoid_research", 0)
            + bucket_counts.get("unknown_research", 0)
        )
        if bucketed < candidates:
            return "CLASSIFIER_UNSTABLE"
        return "TELEMETRY_READY"

    def _last_decision_source_audit(self) -> dict[str, Any] | None:
        path = self.engine.decision_source_audit_path
        if not path.exists():
            return None
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        try:
            parsed = json.loads(lines[-1])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _count(records: list[dict[str, Any]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in records:
            value = str(record.get(key) or "NONE")
            counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _sleep(seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    @staticmethod
    def _render_summary(summary: dict[str, Any]) -> str:
        lines = [
            "# MAXIMO Quant v4 New Candle Validation",
            "",
            f"- mode: {summary['mode']}",
            f"- symbol: {summary['symbol']}",
            f"- session_label: {summary['session_label']}",
            f"- attempt_count: {summary['attempt_count']}",
            f"- unique_candle_count: {summary['unique_candle_count']}",
            f"- repeated_cycle_count: {summary['repeated_cycle_count']}",
            f"- target_unique_candles: {summary['target_unique_candles']}",
            f"- OB_AGGRESSIVE_REDUCED_SIGNAL: {summary['ob_aggressive_reduced_signal']}",
            f"- OB_REJECTION_INSTITUTIONAL_EXECUTE: {summary['ob_rejection_institutional_execute']}",
            f"- PREPARE_REDUCED: {summary['prepare_reduced']}",
            f"- EXECUTE reducido: {summary['execute_reduced']}",
            f"- EXECUTE institucional: {summary['execute_institutional']}",
            f"- partial_0_5R: {summary['partial_0_5r']}",
            f"- protection_0_8R: {summary['protection_0_8r']}",
            f"- managed_signals_with_realized_R: {summary['managed_signals_with_realized_r']}",
            f"- expectancy_simulated_R: {summary['expectancy_simulated_r']}",
            f"- critical_normal_risk_errors: {summary['critical_normal_risk_errors']}",
            f"- expansion_subtype_pretrade_candidates: {summary['expansion_subtype_pretrade_candidates']}",
            f"- expansion_favorable_research: {summary['expansion_favorable_research']}",
            f"- expansion_avoid_research: {summary['expansion_avoid_research']}",
            f"- expansion_unknown_research: {summary['expansion_unknown_research']}",
            f"- expansion_lookahead_risk_count: {summary['expansion_lookahead_risk_count']}",
            f"- expansion_telemetry_conclusion: {summary['expansion_telemetry_conclusion']}",
            "",
            "## Active Family",
        ]
        for key, value in sorted(summary["active_family_counts"].items()):
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Watch Policy"])
        for key, value in sorted(summary["watch_policy_action_counts"].items()):
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Expansion Subtype Pretrade Telemetry", "### Expected Edge Buckets"])
        for key, value in sorted(summary["expansion_expected_edge_bucket_counts"].items()):
            lines.append(f"- {key}: {value}")
        lines.append("### Subtypes")
        for key, value in sorted(summary["expansion_subtype_counts"].items()):
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Conclusion", f"- {summary['conclusion']}", ""])
        return "\n".join(lines)
