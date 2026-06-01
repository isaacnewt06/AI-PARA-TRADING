from __future__ import annotations

import json
from pathlib import Path

from src.application.generate_robust_ob_backtests import RobustOBBacktestGenerationApplicationService
from src.core.config import get_settings, reload_settings
from src.db.session import init_db, session_scope


def test_generate_robust_ob_backtests_writes_directional_and_managed_specs(tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'robust.db').as_posix()}",
        }
    )
    settings = get_settings()
    init_db()
    specs_dir = settings.paths.data_dir / "backtests" / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    base_spec = {
        "strategy_name": "OB Rejection Relaxed Validation",
        "family": "OB Rejection",
        "symbols_suggested": ["XAUUSDm"],
        "context_timeframe": ["H1"],
        "entry_timeframe": ["M5"],
        "session_filter": ["any_session"],
        "required_conditions": [],
        "confirmation_conditions": [],
        "entry_logic": {},
        "sl_logic": {},
        "tp_logic": {},
        "rr_min": 1.2,
        "risk_per_trade": 0.5,
        "invalidation_conditions": [],
        "quantifiable_condition_map": [],
        "simulation_overrides": {
            "relaxed_htf_bias": True,
            "relaxed_order_block": True,
            "relaxed_confirmation_any": True,
            "entry_on_next_open": True,
        },
        "source_traceability": {},
    }
    (specs_dir / "ob_rejection_relaxed_validation.json").write_text(json.dumps(base_spec), encoding="utf-8")

    with session_scope() as session:
        summary = RobustOBBacktestGenerationApplicationService(session, settings).run()

    assert summary["generated_specs"] == 8
    short_spec = specs_dir / "ob_rejection_short_only.json"
    managed_spec = specs_dir / "ob_rejection_short_only_trailing_atr.json"
    assert short_spec.exists()
    assert managed_spec.exists()
    short_payload = json.loads(short_spec.read_text(encoding="utf-8"))
    managed_payload = json.loads(managed_spec.read_text(encoding="utf-8"))
    assert short_payload["simulation_overrides"]["direction_filter"] == "short_only"
    assert managed_payload["simulation_overrides"]["exit_management"] == "trailing_atr_after_1r"
