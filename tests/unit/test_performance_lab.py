from __future__ import annotations

import json
from pathlib import Path

from src.trading.performance_lab import TradingAIPerformanceLab


def test_performance_lab_reports_insufficient_data_without_logs(tmp_path: Path) -> None:
    lab = TradingAIPerformanceLab(demo_dir=tmp_path / "demo", reports_dir=tmp_path / "reports")

    summary = lab.generate()

    assert summary["classification"] == "INSUFFICIENT_DATA"
    assert Path(summary["report_path"]).exists()


def test_performance_lab_detects_unprotected_half_r_giveback(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    event = {
        "ticket": 1,
        "action_taken": "monitor",
        "mfe_r": 0.6,
        "current_r": -0.1,
    }
    (demo_dir / "position_management_history.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    lab = TradingAIPerformanceLab(demo_dir=demo_dir, reports_dir=tmp_path / "reports")

    summary = lab.generate()

    assert summary["trades_reached_0_5r_then_negative_unprotected"] == 1
    assert summary["urgent_flags"]
