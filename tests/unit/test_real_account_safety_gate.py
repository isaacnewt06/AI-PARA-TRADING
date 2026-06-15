from __future__ import annotations

from pathlib import Path

from src.trading.real_account_safety_gate import RealAccountSafetyGate


def test_real_account_safety_gate_blocks_without_demo_evidence(tmp_path: Path) -> None:
    gate = RealAccountSafetyGate(reports_dir=tmp_path)

    result = gate.evaluate(
        account_status={"is_demo": True, "account_info": {"login": 1, "server": "Demo"}, "terminal_info": {"path": "mt5"}},
        execution_environment={"execution_viability": "SAFE"},
        performance_summary={"total_cycles": 10, "trades_observed": 1, "profit_factor_proxy": 0.8, "max_drawdown_r_proxy": 1.0},
        latest_signal={"execution_mode": "DEMO_REALISTIC_PROFIT_MODE"},
    )

    assert result["real_allowed"] is False
    assert result["status"] == "REAL_BLOCKED_DEMO_ONLY"
    assert "insufficient_demo_cycles" in result["blockers"]
    assert (tmp_path / "REAL_READY_GAP_ANALYSIS.md").exists()
