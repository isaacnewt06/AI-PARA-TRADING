from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.core.config import reload_settings
from src.trading.maximo_quant_v4_new_candle_validation import MaximoQuantV4NewCandleValidationMonitor


class _FakeBridge:
    def __init__(self, candle_times: list[datetime]) -> None:
        self.candle_times = candle_times
        self.index = 0

    def read_market_snapshot(self, *, symbol: str, bars_by_timeframe: dict[str, int] | None = None) -> dict:
        candle_time = self.candle_times[min(self.index, len(self.candle_times) - 1)]
        self.index += 1
        return {
            "symbol": symbol,
            "timeframes": {
                "M5": {
                    "bars": 3,
                    "first_bar_time": candle_time.isoformat(),
                    "last_bar_time": candle_time.isoformat(),
                }
            },
            "candles": {
                "M5": [
                    SimpleNamespace(time=candle_time),
                    SimpleNamespace(time=candle_time),
                    SimpleNamespace(time=candle_time),
                ]
            },
        }


class _FakeEngine:
    def __init__(self, tmp_path: Path, candle_times: list[datetime]) -> None:
        self.bridge = _FakeBridge(candle_times)
        self.decision_source_audit_path = tmp_path / "decision_source_audit.jsonl"
        self.run_count = 0

    def run(self, *, symbol: str, dry_run: bool, confirm_demo: bool) -> dict:
        self.run_count += 1
        audit = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "intelligence_layer": {
                "operational_family": "OB_REJECTION_AGGRESSIVE_WATCH" if self.run_count == 2 else "NONE",
                "watch_policy_action": "PREPARE_REDUCED",
                "setup_maturity": 78.0,
                "confidence": 0.78,
                "ob_rejection_families": {"active_family": "OB_REJECTION_AGGRESSIVE_WATCH" if self.run_count == 2 else "NONE"},
            },
            "decision_attribution": {"main_blocker": "allowed"},
        }
        with self.decision_source_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit) + "\n")
        signal = None
        if self.run_count == 2:
            signal = {
                "signal_type": "OB_AGGRESSIVE_REDUCED_SIGNAL",
                "active_family": "OB_REJECTION_AGGRESSIVE_WATCH",
                "risk_mode": "reduced",
                "entry_price": 4700.0,
                "stop_price": 4705.0,
                "target_price": 4694.25,
                "selected_rr": 1.15,
            }
        return {
            "execution_status": "dry_run_signal_detected" if signal else "no_signal",
            "intelligence_action": "EXECUTE" if signal else "WATCH",
            "harmony_score": 0.58,
            "signal": signal,
            "active_watch": {},
            "watch_execution_policy": {"watch_policy_action": "PREPARE_REDUCED"},
            "execution_risk_decision": {
                "allowed_risk_mode": "reduced",
                "execution_mode": "reduced_execution" if signal else "no_signal",
            },
            "expansion_subtype_pretrade_audit": {
                "candidate_detected": False,
                "expected_edge_bucket": "not_applicable",
                "lookahead_safe": True,
            },
        }


def test_new_candle_validation_counts_only_unique_closed_m5_candles(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    candle_times = [
        datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc),
    ]
    engine = _FakeEngine(tmp_path, candle_times)
    monitor = MaximoQuantV4NewCandleValidationMonitor(settings, engine=engine)  # type: ignore[arg-type]

    summary = monitor.run(
        symbol="XAUUSDm",
        target_unique_candles=2,
        max_attempts=3,
        poll_seconds=0,
        session_label="test",
    )

    assert summary["mode"] == "NEW_CANDLE_VALIDATION_MODE"
    assert summary["unique_candle_count"] == 2
    assert summary["repeated_cycle_count"] == 1
    assert summary["ob_aggressive_reduced_signal"] == 1
    assert summary["prepare_reduced"] == 2
    assert engine.run_count == 2
    events = Path(summary["events_path"]).read_text(encoding="utf-8")
    assert "repeated_candle_skip" in events


def test_new_candle_validation_reports_market_generated_no_setups(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    candle_times = [
        datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc),
    ]
    engine = _FakeEngine(tmp_path, candle_times)

    def no_signal_run(*, symbol: str, dry_run: bool, confirm_demo: bool) -> dict:
        engine.run_count += 1
        audit = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "intelligence_layer": {
                "operational_family": "NONE",
                "watch_policy_action": "OBSERVE",
                "setup_maturity": 64.0,
                "confidence": 0.64,
                "ob_rejection_families": {"active_family": "NONE"},
            },
            "decision_attribution": {"main_blocker": "allowed"},
        }
        with engine.decision_source_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit) + "\n")
        return {
            "execution_status": "no_signal",
            "intelligence_action": "WATCH",
            "harmony_score": 0.58,
            "signal": None,
            "active_watch": {},
            "watch_execution_policy": {"watch_policy_action": "OBSERVE"},
            "execution_risk_decision": {"allowed_risk_mode": "blocked", "execution_mode": "no_signal"},
            "expansion_subtype_pretrade_audit": {
                "candidate_detected": False,
                "expected_edge_bucket": "not_applicable",
                "lookahead_safe": True,
            },
        }

    engine.run = no_signal_run  # type: ignore[method-assign]
    monitor = MaximoQuantV4NewCandleValidationMonitor(settings, engine=engine)  # type: ignore[arg-type]

    summary = monitor.run(symbol="XAUUSDm", target_unique_candles=2, max_attempts=2, poll_seconds=0)

    assert summary["unique_candle_count"] == 2
    assert summary["ob_aggressive_reduced_signal"] == 0
    assert summary["conclusion"] == "MERCADO NO GENERÓ SETUPS"


def test_new_candle_validation_counts_expansion_subtype_pretrade_telemetry(tmp_path: Path) -> None:
    settings = reload_settings({"DATA_DIR": str(tmp_path / "data")})
    candle_times = [
        datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 10, 10, tzinfo=timezone.utc),
    ]
    engine = _FakeEngine(tmp_path, candle_times)
    audits = [
        {
            "candidate_detected": True,
            "subtype": "compressed_release_expansion",
            "subtype_confidence": 0.72,
            "expected_edge_bucket": "favorable_research",
            "subtype_reason": "test favorable",
            "historical_warning": "telemetry only",
            "lookahead_safe": True,
        },
        {
            "candidate_detected": True,
            "subtype": "trend_acceleration_expansion",
            "subtype_confidence": 0.81,
            "expected_edge_bucket": "avoid_research",
            "subtype_reason": "test avoid",
            "historical_warning": "telemetry only",
            "lookahead_safe": True,
        },
        {
            "candidate_detected": True,
            "subtype": "other",
            "subtype_confidence": 0.55,
            "expected_edge_bucket": "unknown_research",
            "subtype_reason": "test unknown",
            "historical_warning": "telemetry only",
            "lookahead_safe": True,
        },
    ]

    def telemetry_run(*, symbol: str, dry_run: bool, confirm_demo: bool) -> dict:
        engine.run_count += 1
        with engine.decision_source_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "intelligence_layer": {
                            "operational_family": "NONE",
                            "watch_policy_action": "OBSERVE",
                            "setup_maturity": 64.0,
                            "confidence": 0.64,
                            "ob_rejection_families": {"active_family": "NONE"},
                        },
                        "decision_attribution": {"main_blocker": "allowed"},
                    }
                )
                + "\n"
            )
        return {
            "execution_status": "no_signal",
            "intelligence_action": "WATCH",
            "harmony_score": 0.58,
            "signal": None,
            "active_watch": {},
            "watch_execution_policy": {"watch_policy_action": "OBSERVE"},
            "execution_risk_decision": {"allowed_risk_mode": "blocked", "execution_mode": "no_signal"},
            "expansion_subtype_pretrade_audit": audits[engine.run_count - 1],
        }

    engine.run = telemetry_run  # type: ignore[method-assign]
    monitor = MaximoQuantV4NewCandleValidationMonitor(settings, engine=engine)  # type: ignore[arg-type]

    summary = monitor.run(symbol="XAUUSDm", target_unique_candles=3, max_attempts=3, poll_seconds=0)

    assert summary["expansion_subtype_pretrade_candidates"] == 3
    assert summary["expansion_favorable_research"] == 1
    assert summary["expansion_avoid_research"] == 1
    assert summary["expansion_unknown_research"] == 1
    assert summary["expansion_lookahead_risk_count"] == 0
    assert summary["expansion_telemetry_conclusion"] == "TELEMETRY_READY"
    report = Path(summary["summary_path"]).read_text(encoding="utf-8")
    assert "Expansion Subtype Pretrade Telemetry" in report
