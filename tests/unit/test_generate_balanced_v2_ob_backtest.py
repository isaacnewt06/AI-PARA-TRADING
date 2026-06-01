from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.application.generate_balanced_v2_ob_backtest import BalancedV2OBBacktestGenerationApplicationService
from src.core.config import get_settings, reload_settings
from src.trading.strategy_schemas import ExecutableBlueprintBundle, ExecutableStrategyBlueprint


def test_generate_balanced_v2_ob_backtest_writes_two_variants(monkeypatch, tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'balanced_v2_ob.db').as_posix()}",
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
        "src.application.generate_balanced_v2_ob_backtest.StrategyBlueprintBuilder.build",
        lambda self, prioritize_family="OB Rejection": bundle,
    )
    monkeypatch.setattr(
        "src.application.generate_balanced_v2_ob_backtest.BacktestBridge.export_blueprint_backtests",
        lambda self: {"specs_exported": 8},
    )

    summary = BalancedV2OBBacktestGenerationApplicationService(SimpleNamespace(), settings).run()

    bundle_path = settings.paths.knowledge_dir / "strategy_blueprints" / "executable_strategy_blueprints.json"
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert summary["balanced_v2_blueprints"] == ["OB Rejection Balanced v2 RR12", "OB Rejection Balanced v2 RR15"]
    assert any(item["blueprint_name"] == "OB Rejection Balanced v2 RR12" for item in payload["blueprints"])
    assert any(item["blueprint_name"] == "OB Rejection Balanced v2 RR15" for item in payload["blueprints"])
    rr12 = next(item for item in payload["blueprints"] if item["blueprint_name"] == "OB Rejection Balanced v2 RR12")
    rr15 = next(item for item in payload["blueprints"] if item["blueprint_name"] == "OB Rejection Balanced v2 RR15")
    assert rr12["take_profit"]["rr_min"] == 1.2
    assert rr15["take_profit"]["rr_min"] == 1.5
    assert rr12["simulation_overrides"]["min_atr_percentile"] == 20
    assert rr12["simulation_overrides"]["max_atr_percentile"] == 90
