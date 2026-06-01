from __future__ import annotations

import json
from pathlib import Path

from src.trading.maximo_quant_v4_ob_aggressive_management import (
    apply_ob_aggressive_defensive_management,
    summarize_ob_aggressive_management,
    write_ob_aggressive_management_replay_report,
)


def test_defensive_management_leaves_unreached_half_r_unchanged() -> None:
    managed = apply_ob_aggressive_defensive_management(
        {
            "result": "SL",
            "pnl_r": -1.0,
            "RR": 1.15,
            "max_favorable_excursion_r": 0.49,
        }
    )

    assert managed["partial_taken"] is False
    assert managed["be_moved"] is False
    assert managed["protected_at_0_8R"] is False
    assert managed["final_result_after_management"] == "SL"
    assert managed["realized_R"] == -1.0


def test_defensive_management_partial_and_be_turns_loser_positive() -> None:
    managed = apply_ob_aggressive_defensive_management(
        {
            "result": "SL",
            "pnl_r": -1.0,
            "RR": 1.15,
            "max_favorable_excursion_r": 0.55,
        }
    )

    assert managed["partial_taken"] is True
    assert managed["be_moved"] is True
    assert managed["protected_at_0_8R"] is False
    assert managed["final_result_after_management"] == "BE_AFTER_PARTIAL"
    assert managed["realized_R"] == 0.25
    assert managed["sl_reduced"] is True


def test_defensive_management_protects_remaining_after_point_eight_r() -> None:
    managed = apply_ob_aggressive_defensive_management(
        {
            "result": "SL",
            "pnl_r": -1.0,
            "RR": 1.15,
            "max_favorable_excursion_r": 0.82,
        }
    )

    assert managed["protected_at_0_8R"] is True
    assert managed["final_result_after_management"] == "PROTECTED_STOP_AFTER_0_8R"
    assert managed["realized_R"] == 0.4


def test_defensive_management_partial_reduces_full_tp_but_keeps_profit() -> None:
    managed = apply_ob_aggressive_defensive_management(
        {
            "result": "TP",
            "pnl_r": 1.15,
            "RR": 1.15,
            "max_favorable_excursion_r": 1.2,
        }
    )

    assert managed["final_result_after_management"] == "TP_WITH_PARTIAL"
    assert managed["realized_R"] == 0.825
    assert managed["full_tp_affected"] is True


def test_defensive_management_summary_improves_sample_edge() -> None:
    records = [
        {"result": "TP", "pnl_r": 1.15, "RR": 1.15, "max_favorable_excursion_r": 1.2},
        {"result": "SL", "pnl_r": -1.0, "RR": 1.15, "max_favorable_excursion_r": 0.55},
        {"result": "SL", "pnl_r": -1.0, "RR": 1.15, "max_favorable_excursion_r": 0.85},
        {"result": "SL", "pnl_r": -1.0, "RR": 1.15, "max_favorable_excursion_r": 0.2},
    ]

    summary = summarize_ob_aggressive_management(records)

    assert summary["partial_taken"] == 3
    assert summary["be_moved"] == 3
    assert summary["protected_at_0_8R"] == 2
    assert summary["sl_reduced"] == 2
    assert summary["after"]["expectancy_r"] > summary["before"]["expectancy_r"]
    assert summary["conclusion"] == "GESTIÓN MEJORA EDGE"


def test_defensive_management_replay_report_is_written(tmp_path: Path) -> None:
    input_path = tmp_path / "quality.jsonl"
    output_jsonl = tmp_path / "managed.jsonl"
    output_report = tmp_path / "report.md"
    records = [
        {"timestamp": "t1", "side": "SELL", "result": "TP", "pnl_r": 1.15, "RR": 1.15, "max_favorable_excursion_r": 1.2},
        {"timestamp": "t2", "side": "SELL", "result": "SL", "pnl_r": -1.0, "RR": 1.15, "max_favorable_excursion_r": 0.55},
    ]
    input_path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    summary = write_ob_aggressive_management_replay_report(
        input_jsonl=input_path,
        output_jsonl=output_jsonl,
        output_report=output_report,
    )

    assert output_jsonl.exists()
    assert output_report.exists()
    assert "OB Aggressive Reduced Defensive Management Replay" in output_report.read_text(encoding="utf-8")
    assert summary["after"]["net_r"] > summary["before"]["net_r"]
