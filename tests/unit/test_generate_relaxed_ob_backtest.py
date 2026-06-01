from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.application.generate_relaxed_ob_backtest import RelaxedOBBacktestGenerationApplicationService
from src.core.config import get_settings, reload_settings
from src.trading.strategy_schemas import ExecutableBlueprintBundle, ExecutableStrategyBlueprint


def test_generate_relaxed_ob_backtest_writes_blueprint_bundle(monkeypatch, tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'relaxed_ob.db').as_posix()}",
        }
    )
    settings = get_settings()

    primary = ExecutableStrategyBlueprint(
        blueprint_id="bp_primary",
        strategy_key="detected_ob",
        blueprint_name="OB Rejection Primary Blueprint",
        strategy_family="OB Rejection",
        priority=1,
        execution_profile="primary",
        context={"timeframes": ["H1"]},
        valid_zone={"rule": "strict ob"},
        confirmation={"timeframes": ["M5", "M1"]},
        entry={"rule": "strict entry"},
        stop_loss={"rule": "strict sl"},
        take_profit={"rule": "strict tp", "rr_min": 2.0},
        risk_management={"risk_percent": 0.5, "session_filter": ["new_york"]},
        operational_checklist=["one"],
        quantifiable_conditions=[],
        invalidation_rules=[],
        simulation_overrides={},
        source_traceability={"setup_names": ["strict_ob_setup"]},
    )
    bundle = ExecutableBlueprintBundle(
        generated_at="2026-04-24T00:00:00+00:00",
        blueprints=[primary],
        excluded_strategies=[],
    )

    monkeypatch.setattr(
        "src.application.generate_relaxed_ob_backtest.StrategyBlueprintBuilder.build",
        lambda self, prioritize_family="OB Rejection": bundle,
    )
    monkeypatch.setattr(
        "src.application.generate_relaxed_ob_backtest.BacktestBridge.export_blueprint_backtests",
        lambda self: {"specs_exported": 5},
    )

    summary = RelaxedOBBacktestGenerationApplicationService(SimpleNamespace(), settings).run()

    bundle_path = settings.paths.knowledge_dir / "strategy_blueprints" / "executable_strategy_blueprints.json"
    relaxed_md_path = settings.paths.knowledge_dir / "strategy_blueprints" / "ob_rejection_relaxed_validation.md"
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert summary["relaxed_blueprint"] == "OB Rejection Relaxed Validation"
    assert relaxed_md_path.exists()
    assert any(item["blueprint_name"] == "OB Rejection Relaxed Validation" for item in payload["blueprints"])
    relaxed = next(item for item in payload["blueprints"] if item["blueprint_name"] == "OB Rejection Relaxed Validation")
    assert relaxed["risk_management"]["session_filter"] == ["any_session"]
    assert relaxed["take_profit"]["rr_min"] == 1.2
    assert relaxed["simulation_overrides"]["relaxed_htf_bias"] is True
