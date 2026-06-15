from __future__ import annotations

import json
from pathlib import Path

from src.core.config import reload_settings
from src.trading.reaction_zone_demo_telemetry_validation import (
    ReactionZoneDemoTelemetryValidation,
    TELEMETRY_FIELDS,
)


def _settings(tmp_path: Path):
    return reload_settings({"DATA_DIR": str(tmp_path / "data")})


def _validator(tmp_path: Path) -> ReactionZoneDemoTelemetryValidation:
    return ReactionZoneDemoTelemetryValidation(
        _settings(tmp_path),
        output_dir=tmp_path / "telemetry",
    )


def _account(is_demo: bool = True) -> dict:
    return {"is_demo": is_demo}


def _environment(**overrides) -> dict:
    payload = {
        "execution_viability": "SAFE",
        "live_spread": 0.12,
        "live_latency": 0.10,
        "slippage_estimated": 0.12,
    }
    payload.update(overrides)
    return payload


def _allowed_gate(validator: ReactionZoneDemoTelemetryValidation):
    return validator.evaluate_gate(
        account_status=_account(),
        execution_environment=_environment(),
        macro_action="allow",
        session="ny_am",
        risk_mode="reduced",
    )


def test_gate_allows_safe_demo_reduced_environment(tmp_path: Path) -> None:
    validator = _validator(tmp_path)

    gate = _allowed_gate(validator)

    assert gate.allowed is True
    assert gate.allowed_risk_mode == "reduced"
    assert gate.blockers == []


def test_gate_blocks_non_demo_unsafe_costs_macro_session_and_risk(tmp_path: Path) -> None:
    validator = _validator(tmp_path)

    gate = validator.evaluate_gate(
        account_status=_account(is_demo=False),
        execution_environment=_environment(
            execution_viability="UNSAFE",
            live_spread=0.42,
            live_latency=0.25,
            slippage_estimated=0.42,
        ),
        macro_action="block",
        session="london",
        risk_mode="normal",
    )

    assert gate.allowed is False
    assert "account_not_demo" in gate.blockers
    assert "execution_environment_not_safe" in gate.blockers
    assert "spread_above_survival_threshold" in gate.blockers
    assert "latency_unsafe" in gate.blockers
    assert "slippage_above_survival_threshold" in gate.blockers
    assert "macro_not_allow" in gate.blockers
    assert "session_not_allowed" in gate.blockers
    assert "risk_mode_not_reduced" in gate.blockers


def test_new_trade_record_contains_required_telemetry_fields(tmp_path: Path) -> None:
    validator = _validator(tmp_path)
    gate = _allowed_gate(validator)

    record = validator.new_trade_record(
        trade_id="rz-1",
        symbol="XAUUSDm",
        side="buy",
        entry_price=2400.0,
        stop_price=2398.0,
        target_price=2402.0,
        volume_lots=0.01,
        account_is_demo=True,
        gate=gate,
        execution_environment=_environment(),
        macro_action="allow",
        session="ny_am",
        risk_mode="reduced",
    )

    assert set(TELEMETRY_FIELDS).issubset(record)
    assert record["strategy"] == "REACTION_ZONE_MANAGEMENT_OVERLAY_V1"
    assert record["profile"] == "fast_03_be_08"
    assert record["status"] == "PENDING"
    assert record["spread_at_entry"] == 0.12


def test_assess_blocks_when_required_partial_is_not_confirmed(tmp_path: Path) -> None:
    validator = _validator(tmp_path)
    record = validator.new_trade_record(
        trade_id="rz-2",
        symbol="XAUUSDm",
        side="SELL",
        entry_price=None,
        stop_price=None,
        target_price=None,
        volume_lots=0.01,
        account_is_demo=True,
        gate=_allowed_gate(validator),
        execution_environment=_environment(),
        macro_action="allow",
        session="ny_am",
        risk_mode="reduced",
    )
    record["partial_required"] = True

    assessed = validator.assess_trade_record(record)

    assert assessed["status"] == "BLOCKED"
    assert "partial_not_confirmed" in assessed["management_failure_reason"]


def test_assess_blocks_when_be_move_fails_or_environment_degrades(tmp_path: Path) -> None:
    validator = _validator(tmp_path)
    record = validator.new_trade_record(
        trade_id="rz-3",
        symbol="XAUUSDm",
        side="SELL",
        entry_price=None,
        stop_price=None,
        target_price=None,
        volume_lots=0.01,
        account_is_demo=True,
        gate=_allowed_gate(validator),
        execution_environment=_environment(),
        macro_action="allow",
        session="ny_pm",
        risk_mode="reduced",
    )
    record["BE_required"] = True

    assessed = validator.assess_trade_record(
        record,
        execution_environment=_environment(
            execution_viability="UNSAFE",
            live_spread=0.42,
            live_latency=0.3,
            slippage_estimated=0.42,
        ),
        macro_action="block",
    )

    assert assessed["status"] == "BLOCKED"
    assert "BE_move_failed" in assessed["management_failure_reason"]
    assert "execution_environment_left_safe" in assessed["management_failure_reason"]
    assert "spread_degraded_during_trade" in assessed["management_failure_reason"]
    assert "latency_degraded_during_trade" in assessed["management_failure_reason"]
    assert "macro_changed_to_block" in assessed["management_failure_reason"]


def test_append_and_report_returns_insufficient_data_for_short_observation(tmp_path: Path) -> None:
    validator = _validator(tmp_path)
    record = validator.new_trade_record(
        trade_id="rz-4",
        symbol="XAUUSDm",
        side="BUY",
        entry_price=None,
        stop_price=None,
        target_price=None,
        volume_lots=0.01,
        account_is_demo=True,
        gate=_allowed_gate(validator),
        execution_environment=_environment(),
        macro_action="allow",
        session="ny_am",
        risk_mode="reduced",
    )
    validator.append_trade_record(validator.assess_trade_record(record))

    summary = validator.write_report()

    assert summary["managed_demo_trades"] == 1
    assert summary["conclusion"] == "INSUFFICIENT DATA"
    assert validator.report_path.exists()


def test_report_approves_after_20_managed_records_without_failures(tmp_path: Path) -> None:
    validator = _validator(tmp_path)
    gate = _allowed_gate(validator)
    for index in range(20):
        record = validator.new_trade_record(
            trade_id=f"rz-{index}",
            symbol="XAUUSDm",
            side="BUY",
            entry_price=2400.0,
            stop_price=2399.0,
            target_price=2401.0,
            volume_lots=0.01,
            account_is_demo=True,
            gate=gate,
            execution_environment=_environment(),
            macro_action="allow",
            session="ny_am",
            risk_mode="reduced",
        )
        record["partial_fill_confirmed"] = True
        record["BE_move_success"] = True
        record["protected_at_0_8R"] = True
        record["realized_R"] = 0.25
        validator.append_trade_record(validator.assess_trade_record(record))

    summary = validator.write_report()

    assert summary["managed_demo_trades"] == 20
    assert summary["closed_demo_trades"] == 20
    assert summary["conclusion"] == "MANAGEMENT DEMO APPROVED"


def test_latest_gate_writes_json_payload(tmp_path: Path) -> None:
    validator = _validator(tmp_path)
    gate = _allowed_gate(validator)

    payload = validator.write_latest_gate(
        gate=gate,
        account_status=_account(),
        execution_environment=_environment(),
        macro_action="allow",
        session="ny_am",
        risk_mode="reduced",
    )

    saved = json.loads(validator.latest_gate_path.read_text(encoding="utf-8"))
    assert saved["gate"]["allowed"] is True
    assert payload["telemetry_path"] == saved["telemetry_path"]
