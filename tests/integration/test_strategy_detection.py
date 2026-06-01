from __future__ import annotations

import json

from src.application.compile_setups import SetupCompilationApplicationService
from src.application.detect_strategies import StrategyDetectionApplicationService
from src.application.normalize_rules import RuleNormalizationApplicationService
from src.application.score_rules import QualityScoringApplicationService
from src.core.config import reload_settings
from src.db.models.knowledge import ContentChunk, ExtractedRule
from src.db.session import init_db, session_scope


def test_detect_strategies_ranks_repeated_patterns(tmp_path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'strategy_detection.db').as_posix()}",
        }
    )
    init_db()

    with session_scope() as session:
        chunks = []
        for index in range(1, 4):
            chunk = ContentChunk(
                source_type="message",
                source_id=index,
                chunk_index=0,
                text=f"Chunk {index}",
                clean_text=f"Chunk {index}",
            )
            session.add(chunk)
            chunks.append(chunk)
        session.flush()

        rules = [
            ExtractedRule(
                source_chunk_id=chunks[0].id,
                rule_type="setup",
                rule_text=(
                    "Buy XAUUSD after BOS, liquidity sweep and FVG in London session. "
                    "Confirmation engulfing. SL below recent swing low. TP 1:3. Risk 1%."
                ),
                author_name="Mentor_A",
                channel_name="Cursos de Trading GRATIS",
                asset="XAUUSD",
                timeframe="H1/M15",
                direction="buy",
                context="Bullish BOS in London session",
                entry_condition="Entry in fair value gap after liquidity sweep",
                confirmation="engulfing candle",
                stop_loss="below recent swing low",
                take_profit="1:3 RR",
                risk_management="risk 1%",
                session_filter="London session",
                observations="Prioritize displacement candles.",
                concepts_json=json.dumps(["bos", "fvg", "liquidity_sweep"]),
                normalized_signature="rule_1",
                confidence=0.82,
            ),
            ExtractedRule(
                source_chunk_id=chunks[1].id,
                rule_type="setup",
                rule_text=(
                    "London liquidity sweep with FVG entry on gold after break of structure. "
                    "Wait for engulfing candle, stop below swing low and take profit 1:2."
                ),
                author_name="Mentor_B",
                channel_name="Cursos de Trading GRATIS",
                asset="gold",
                timeframe="H1/M15",
                direction="buy",
                context="Break of structure in bullish context",
                entry_condition="fair value gap entry after liquidity sweep",
                confirmation="engulfing",
                stop_loss="recent swing low",
                take_profit="1:2 RR",
                risk_management="risk 1%",
                session_filter="London open",
                observations="Only when displacement is clear.",
                concepts_json=json.dumps(["break of structure", "fair value gap", "liquidity grab"]),
                normalized_signature="rule_2",
                confidence=0.8,
            ),
            ExtractedRule(
                source_chunk_id=chunks[2].id,
                rule_type="setup",
                rule_text=(
                    "Use FVG continuation after BOS in London. "
                    "Enter after liquidity sweep confirmation and target 1:2."
                ),
                author_name="Mentor_C",
                channel_name="Cursos de Trading GRATIS",
                asset="XAUUSD",
                timeframe="M15",
                direction="buy",
                context="BOS continuation",
                entry_condition="FVG continuation entry",
                confirmation="engulfing candle",
                stop_loss="below recent swing low",
                take_profit="1:2 RR",
                risk_management="1%",
                session_filter="London session",
                observations="Use only aligned HTF bias.",
                concepts_json=json.dumps(["bos", "fvg"]),
                normalized_signature="rule_3",
                confidence=0.76,
            ),
        ]
        session.add_all(rules)
        session.flush()

        RuleNormalizationApplicationService(session).run()
        SetupCompilationApplicationService(session).run(score=True)
        QualityScoringApplicationService(session).run()

        service = StrategyDetectionApplicationService(session)
        summary = service.run()
        assert summary["top_strategies_detected"] >= 1

        ranked = service.rank(limit=5)
        assert ranked
        top = ranked[0]
        assert top["strategy_family"] == "FVG Continuation"
        assert top["rule_count"] == 3
        assert top["source_count"] == 3
        assert top["candidate_count"] >= 1
        assert top["relevance_score"] > 0.6
        assert "bos" in top["concepts"]
        assert "fvg_entry" in top["entry_types"]

        inspected = service.inspect(top["name"])
        assert inspected is not None
        assert len(inspected["evidence"]["authors"]) == 3
        assert inspected["evidence"]["source_chunk_ids"] == [chunks[0].id, chunks[1].id, chunks[2].id]
