"""Producer-side stable bytes for SENSEI's research-only phase3.v1 adapter.

This is a synthetic serialization contract, not real Telegram source evidence
or a trading strategy that has passed admission/risk/performance validation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.trading.strategy_schemas import StrategyExportBundle, StrategySetupDefinition


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/apt_phase3_v1_sensei_contract.json"
EXPECTED_SHA256 = "f11ed6b675e69651f3f8ded72e45678fd174fc5f7c7a7c45ac5da15479027147"


def test_sensei_contract_fixture_is_actual_phase3_v1_serialization() -> None:
    producer = StrategyExportBundle(strategies=[StrategySetupDefinition(
        setup_id="shadow-sample-1",
        setup_name="Synthetic XAUUSD zone rejection",
        strategy_family="research_only",
        symbols=["XAUUSDm"],
        context_tf=["M15"],
        entry_tf=["M1"],
        execution_notes="Synthetic contract sample; never execute",
        source_traceability={"origin": "synthetic_contract_fixture", "real_trading_data": False},
    )])
    serialized_bytes = producer.model_dump_json().encode("utf-8") + b"\n"
    on_disk_bytes = FIXTURE.read_bytes()
    assert serialized_bytes == on_disk_bytes
    assert hashlib.sha256(on_disk_bytes).hexdigest() == EXPECTED_SHA256


def test_sensei_fixture_has_no_executable_fields_or_real_source_claims() -> None:
    data = json.loads(FIXTURE.read_bytes())
    assert data["schema_version"] == "phase3.v1"
    assert len(data["strategies"]) == 1
    record = data["strategies"][0]
    assert record["source_traceability"]["real_trading_data"] is False
    assert set(record) == set(StrategySetupDefinition.model_fields)
    assert all(field not in record for field in ("order_send", "can_execute", "trading_authority"))
