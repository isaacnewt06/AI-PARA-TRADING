from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.core.config import get_settings, reload_settings
from src.trading.backtest_bridge import BacktestBridge


def test_export_blueprint_backtests_creates_spec_files(tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'blueprint_specs.db').as_posix()}",
        }
    )
    settings = get_settings()
    blueprint_dir = settings.paths.knowledge_dir / "strategy_blueprints"
    blueprint_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "schema_version": "phase3.blueprints.v1",
        "generated_at": "2026-04-24T00:00:00+00:00",
        "blueprints": [
            {
                "blueprint_id": "blueprint_1",
                "strategy_key": "detected_ob",
                "blueprint_name": "OB Rejection Primary Blueprint",
                "strategy_family": "OB Rejection",
                "priority": 1,
                "execution_profile": "primary",
                "status": "executable",
                "context": {"timeframes": ["H1"], "htf_bias": "bias"},
                "valid_zone": {"rule": "zone"},
                "confirmation": {"timeframes": ["M5", "M1"], "rule": "confirm"},
                "entry": {"rule": "entry"},
                "stop_loss": {"rule": "sl"},
                "take_profit": {"rule": "tp", "rr_min": 2.0},
                "risk_management": {"risk_percent": 0.5, "session_filter": ["new_york"]},
                "operational_checklist": ["a", "b"],
                "quantifiable_conditions": [
                    {"key": "htf_bias_aligned", "layer": "context", "timeframe": "H1", "rule": "ema rule"}
                ],
                "invalidation_rules": ["invalidate"],
                "source_traceability": {"setup_names": ["OB Rejection - order_block - multi_symbol - M5"], "normalized_rule_ids": [1]},
            }
        ],
        "excluded_strategies": [],
    }
    (blueprint_dir / "executable_strategy_blueprints.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (blueprint_dir / "ob_rejection_primary_blueprint.md").write_text("# OB Rejection Primary Blueprint", encoding="utf-8")

    bridge = BacktestBridge(session=SimpleNamespace(), settings=settings)
    bridge.candidate_repository = SimpleNamespace(
        get_by_name_or_key=lambda value: SimpleNamespace(
            candidate_key="setup_key",
            setup_name="OB Rejection - order_block - multi_symbol - M5",
            strategy_family="OB Rejection",
            symbols_json=json.dumps([]),
            context_tf_json=json.dumps(["H1"]),
            entry_tf_json=json.dumps(["M5", "M1"]),
            allowed_sessions_json=json.dumps(["new_york"]),
            required_conditions_json=json.dumps([]),
            optional_conditions_json=json.dumps([]),
            invalidation_conditions_json=json.dumps([]),
            confirmation_logic_json=json.dumps([]),
            sl_logic_json=json.dumps({"rule": "sl"}),
            tp_logic_json=json.dumps({"rule": "tp"}),
            rr_constraints_json=json.dumps({"rr_min": 2.0}),
            risk_constraints_json=json.dumps({"risk_percent": 0.5}),
            execution_notes="notes",
            source_traceability_json=json.dumps({"normalized_rule_ids": [1]}),
        ),
        list_candidates=lambda: [],
    )
    bridge.condition_repository = SimpleNamespace(
        list_for_rule=lambda normalized_rule_id: [
            SimpleNamespace(
                condition_key="htf_bias_aligned",
                condition_type="context",
                signal_function="ema_alignment",
                parameters_json=json.dumps({"ema_fast": 20}),
                operator="equals",
                threshold=1.0,
                timeframe="H1",
                required=True,
                notes="ema rule",
            )
        ]
    )

    result = bridge.export_blueprint_backtests()

    spec_path = settings.paths.data_dir / "backtests" / "specs" / "ob_rejection_primary.json"
    assert result["specs_exported"] == 1
    assert spec_path.exists()
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    assert payload["strategy_name"] == "OB Rejection Primary Blueprint"
    assert payload["family"] == "OB Rejection"
    assert payload["rr_min"] == 2.0
    assert payload["risk_per_trade"] == 0.5
    assert payload["symbols_suggested"] == ["XAUUSDm", "XAUUSD", "EURUSDm", "EURUSD", "GBPUSDm", "GBPUSD", "NAS100m", "NAS100"]
