from __future__ import annotations

import json

from src.application.compile_setups import SetupCompilationApplicationService
from src.application.export_strategies import StrategyExportApplicationService
from src.application.normalize_rules import RuleNormalizationApplicationService
from src.application.score_rules import QualityScoringApplicationService
from src.core.config import reload_settings
from src.db.models.knowledge import ContentChunk, ExtractedRule
from src.db.session import init_db, session_scope


def test_phase3_normalize_quantify_compile_score_export(tmp_path) -> None:
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'phase3.db').as_posix()}",
        }
    )
    init_db()

    with session_scope() as session:
        extracted = ExtractedRule(
            rule_type="signal",
            rule_text="Buy XAUUSD after BOS, liquidity sweep and FVG. Confirmation engulfing. SL below recent swing low. TP 1:3. London session risk 1%",
            author_name="Mentor_A",
            channel_name="SMC Academy",
            asset="gold",
            timeframe="H1/M5",
            direction="buy",
            context="Bullish market structure with break of structure",
            entry_condition="Entry in fair value gap after liquidity sweep",
            confirmation="engulfing candle",
            stop_loss="below recent swing low",
            take_profit="1:3 RR",
            risk_management="risk 1%",
            session_filter="London session",
            observations="Use only high probability displacement.",
            concepts_json=json.dumps(["bos", "liquidity_sweep", "fvg"]),
            strategy_key="fvg_gold_london",
            normalized_signature="abc",
            confidence=0.8,
        )
        session.add(extracted)
        session.flush()

        normalized_summary = RuleNormalizationApplicationService(session).run()
        assert normalized_summary["normalized_rules"] == 1
        assert normalized_summary["quantifiable_conditions"] >= 5

        compile_summary = SetupCompilationApplicationService(session).run(score=True)
        assert compile_summary["strategy_candidates"] == 1
        assert compile_summary["setup_quality_scores"] == 1

        score_summary = QualityScoringApplicationService(session).run()
        assert score_summary["rule_quality_scores"] == 1

        output = tmp_path / "strategies.json"
        export_summary = StrategyExportApplicationService(session, settings).export(str(output))
        assert export_summary["strategies_exported"] == 1
        exported = json.loads(output.read_text(encoding="utf-8"))
        assert exported["strategies"][0]["required_conditions"]


def test_inspect_and_compare_strategies(tmp_path) -> None:
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'phase3_compare.db').as_posix()}",
        }
    )
    init_db()

    with session_scope() as session:
        for index, direction in enumerate(["buy", "buy"], start=1):
            session.add(
                ExtractedRule(
                    rule_type="signal",
                    rule_text=f"{direction} EURUSD breakout retest London session SL swing TP 1:2",
                    author_name=f"Mentor_{index}",
                    channel_name="Breakout Course",
                    asset="EURUSD",
                    timeframe="H1/M15",
                    direction=direction,
                    context="trend breakout",
                    entry_condition="breakout retest",
                    confirmation="close above level",
                    stop_loss="recent swing low",
                    take_profit="1:2 RR",
                    risk_management="risk 1%",
                    session_filter="London open",
                    concepts_json=json.dumps(["breakout", "retest"]),
                    normalized_signature=f"sig_{index}",
                    confidence=0.7,
                )
            )
        session.flush()

        RuleNormalizationApplicationService(session).run()
        SetupCompilationApplicationService(session).run(score=True)
        service = StrategyExportApplicationService(session, settings)
        exported = service.export(str(tmp_path / "strategies.csv"), format_name="csv")
        assert exported["strategies_exported"] >= 1
        candidates = service.compare("Breakout Retest - breakout - EURUSD - M15", "Breakout Retest - breakout - EURUSD - M15")
        assert "shared_conditions" in candidates
        inspected = service.inspect("Breakout Retest - breakout - EURUSD - M15")
        assert inspected is not None


def test_setup_compiler_skips_rules_from_filtered_chunks(tmp_path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'phase3_filtered.db').as_posix()}",
        }
    )
    init_db()

    with session_scope() as session:
        chunk = ContentChunk(
            source_type="message",
            source_id=1,
            chunk_index=0,
            text="VIP promo noise",
            clean_text="VIP promo noise",
            filtered_out=True,
        )
        session.add(chunk)
        session.flush()
        session.add(
            ExtractedRule(
                source_chunk_id=chunk.id,
                rule_type="signal",
                rule_text="Buy XAUUSD after BOS and FVG. SL below low. TP 1:2.",
                author_name="Noise",
                channel_name="Promo",
                asset="XAUUSD",
                timeframe="M15",
                direction="buy",
                context="BOS",
                entry_condition="FVG",
                stop_loss="recent swing low",
                take_profit="1:2 RR",
                concepts_json=json.dumps(["bos", "fvg"]),
                normalized_signature="filtered",
                confidence=0.8,
            )
        )
        session.flush()

        RuleNormalizationApplicationService(session).run()
        compile_summary = SetupCompilationApplicationService(session).run(score=True)

        assert compile_summary["strategy_candidates"] == 0
