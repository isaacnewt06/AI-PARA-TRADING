from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.application.generate_relaxed_filtered_ob_backtest import RelaxedFilteredOBBacktestGenerationApplicationService
from src.core.config import get_settings, reload_settings
from src.trading.strategy_schemas import ExecutableBlueprintBundle, ExecutableStrategyBlueprint


def test_generate_relaxed_filtered_ob_backtest_writes_variants(monkeypatch, tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'relaxed_filtered.db').as_posix()}",
        }
    )
    settings = get_settings()

    relaxed = ExecutableStrategyBlueprint(
        blueprint_id="bp_relaxed",
        strategy_key="detected_ob",
        blueprint_name="OB Rejection Relaxed Validation",
        strategy_family="OB Rejection",
        priority=20,
        execution_profile="experimental_relaxed_validation",
        context={"timeframes": ["H1"]},
        valid_zone={"rule": "zone"},
        confirmation={"timeframes": ["M5", "M1"]},
        entry={"rule": "next open"},
        stop_loss={"rule": "sl"},
        take_profit={"rule": "tp", "rr_min": 1.2},
        risk_management={"risk_percent": 0.5, "session_filter": ["any_session"]},
        operational_checklist=[],
        quantifiable_conditions=[],
        invalidation_rules=[],
        simulation_overrides={"relaxed_htf_bias": True, "relaxed_order_block": True, "relaxed_confirmation_any": True},
        source_traceability={},
    )
    bundle = ExecutableBlueprintBundle(
        generated_at="2026-04-24T00:00:00+00:00",
        blueprints=[relaxed],
        excluded_strategies=[],
    )

    monkeypatch.setattr(
        "src.application.generate_relaxed_filtered_ob_backtest.StrategyBlueprintBuilder.build",
        lambda self, prioritize_family="OB Rejection": bundle,
    )
    monkeypatch.setattr(
        "src.application.generate_relaxed_filtered_ob_backtest.BacktestBridge.export_blueprint_backtests",
        lambda self: {"specs_exported": 9},
    )

    summary = RelaxedFilteredOBBacktestGenerationApplicationService(SimpleNamespace(), settings).run()
    bundle_path = settings.paths.knowledge_dir / "strategy_blueprints" / "executable_strategy_blueprints.json"
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert summary["specs_exported"] == 9
    assert len(summary["filtered_variants"]) == 4
    assert any(item["blueprint_name"] == "OB Rejection Relaxed Filtered v1 Short Core" for item in payload["blueprints"])
