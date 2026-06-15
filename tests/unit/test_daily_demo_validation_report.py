from __future__ import annotations

import json
from pathlib import Path

from src.trading.daily_demo_validation_report import DailyDemoValidationReport


def test_daily_demo_validation_report_counts_session_cycles(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo"
    reports_dir = tmp_path / "reports"
    demo_dir.mkdir()
    telemetry = [
        {
            "timestamp_utc": "2026-06-03T07:10:00+00:00",
            "timestamp_rd": "2026-06-03T03:10:00-04:00",
            "date_rd": "2026-06-03",
            "session_rd": "london_rd",
            "cycle_class": "WATCH",
            "market_pulse_score": 68.0,
            "final_confirmation_score": 52.0,
            "block_reasons": [],
        },
        {
            "timestamp_utc": "2026-06-03T12:30:00+00:00",
            "timestamp_rd": "2026-06-03T08:30:00-04:00",
            "date_rd": "2026-06-03",
            "session_rd": "ny_rd",
            "cycle_class": "BLOCK",
            "market_pulse_score": 72.0,
            "final_confirmation_score": 42.0,
            "block_reasons": ["execution_environment_not_safe"],
        },
        {
            "timestamp_utc": "2026-06-03T18:30:00+00:00",
            "timestamp_rd": "2026-06-03T14:30:00-04:00",
            "date_rd": "2026-06-03",
            "session_rd": "outside_validation_sessions",
            "cycle_class": "EXECUTE",
            "market_pulse_score": 90.0,
            "final_confirmation_score": 80.0,
            "block_reasons": [],
        },
    ]
    (demo_dir / "demo_validation_cycles.jsonl").write_text(
        "\n".join(json.dumps(item) for item in telemetry) + "\n",
        encoding="utf-8",
    )
    service = DailyDemoValidationReport(demo_dir=demo_dir, reports_dir=reports_dir)

    summary = service.generate(target_date=__import__("datetime").date(2026, 6, 3))

    assert summary["total_watch"] == 1
    assert summary["total_block"] == 1
    assert summary["total_execute"] == 0
    assert summary["block_reasons"]["execution_environment_not_safe"] == 1
    assert Path(summary["report_path"]).exists()


def test_daily_demo_validation_cycle_payload_keeps_block_reasons(tmp_path: Path) -> None:
    service = DailyDemoValidationReport(demo_dir=tmp_path / "demo", reports_dir=tmp_path / "reports")

    payload = service.build_cycle_payload(
        symbol="XAUUSDm",
        execution_status="blocked_by_final_confirmation",
        intelligence={
            "execution_readiness": {"action": "WATCH", "blockers": ["hour_not_allowed"]},
            "event_risk": {"action": "allow"},
        },
        signal=None,
        final_confirmation={
            "decision": "BLOCK",
            "final_confirmation_score": 41,
            "blockers": ["execution_environment_not_safe"],
            "reason": "blocked",
        },
        execution_risk_decision={"allowed_risk_mode": "blocked", "execution_status": "blocked_by_final_confirmation"},
        market_pulse={"score": 65, "label": "normal_opportunity"},
        position_management={"feedback": {}},
        q_learning_decision={"q_policy_action": "HOLD"},
        open_positions=0,
    )

    assert payload["cycle_class"] == "BLOCK"
    assert "execution_environment_not_safe" in payload["block_reasons"]
    assert "hour_not_allowed" in payload["block_reasons"]
