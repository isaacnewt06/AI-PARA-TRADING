from __future__ import annotations

import json

from src.trading.exit_quality_evaluator import ExitQualityEvaluator
from src.trading.missed_opportunity_learning import MissedOpportunityLearning
from src.trading.trade_experience_memory import TradeExperienceMemory


def test_trade_experience_memory_writes_worst_trade_after_giveback(tmp_path):
    history = tmp_path / "position_history.jsonl"
    history.write_text(
        json.dumps(
            {
                "ticket": "1",
                "symbol": "XAUUSDm",
                "side": "BUY",
                "current_r": -0.1,
                "mfe_r": 0.7,
                "action_taken": "close",
                "reason": "gave_back_profit",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    memory = TradeExperienceMemory(best_path=tmp_path / "best.jsonl", worst_path=tmp_path / "worst.jsonl")

    update = memory.record_from_position_management(
        position_management_history_path=history,
        intelligence={"overview": {"market_state": {"operational_family": "OB Rejection"}}},
        final_confirmation={"final_confirmation_score": 72.0},
        execution_readiness={"execution_readiness_score": 76.0},
        entry_quality={"entry_quality_score": 70.0},
    )

    assert update["written_worst"] == 1
    assert "Devolvió ganancia" in (tmp_path / "worst.jsonl").read_text(encoding="utf-8")


def test_trade_experience_memory_bias_blocks_similar_loser(tmp_path):
    worst = tmp_path / "worst.jsonl"
    worst.write_text(
        json.dumps(
            {
                "ticket": "1",
                "side": "SELL",
                "setup_type": "OB Rejection",
                "market_pulse": 90,
                "final_confirmation": 65,
                "execution_readiness": 72,
                "entry_quality": 60,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    memory = TradeExperienceMemory(best_path=tmp_path / "best.jsonl", worst_path=worst)

    result = memory.evaluate_signal(
        signal={"direction": "SELL", "setup_type": "OB Rejection"},
        intelligence={"overview": {"market_state": {"market_regime": None}}},
        market_pulse={"score": 91},
        final_confirmation={"side": "SELL", "final_confirmation_score": 66},
        execution_readiness={"execution_readiness_score": 73},
        entry_quality={"entry_quality_score": 62},
    )

    assert result["memory_bias"] in {"BLOCK", "REDUCE_RISK"}


def test_missed_opportunity_learning_records_high_pulse_block(tmp_path):
    learner = MissedOpportunityLearning(history_path=tmp_path / "missed.jsonl", report_path=tmp_path / "report.md")

    result = learner.record_cycle(
        symbol="XAUUSDm",
        signal=None,
        execution_status="blocked_by_execution_quality_gate",
        intelligence={"overview": {"market_state": {"preferred_side": "SELL"}}},
        final_confirmation={"side": "SELL", "final_confirmation_score": 66.0, "blockers": []},
        market_pulse={"score": 92.0},
        execution_readiness={"execution_readiness_score": 73.0, "blockers": []},
        entry_quality={"entry_quality_score": 68.0, "decision": "WAIT_RETEST"},
        armed_retest={"action": "ARMED_RETEST_WAIT"},
        snapshot={"candles": {"M1": [{"close": 4500.0}]}},
    )

    assert result["recorded"] is True
    assert (tmp_path / "missed.jsonl").read_text(encoding="utf-8").count("MISSED_OPPORTUNITY_CANDIDATE") == 1
    assert (tmp_path / "report.md").exists()


def test_exit_quality_penalizes_unprotected_trade_after_half_r():
    result = ExitQualityEvaluator().evaluate(
        position_management={
            "positions_managed": 1,
            "actions": [{"action": "hold"}],
            "feedback": {"max_mfe_r": 0.6, "be_applied": False, "partial_taken": False, "trailing_applied": False, "fast_exit_taken": False},
        }
    )

    assert result["exit_quality_score"] < 50
    assert "+0.5R" in result["exit_lesson"]
