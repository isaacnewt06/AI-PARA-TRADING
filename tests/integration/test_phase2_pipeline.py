from __future__ import annotations

import json
from pathlib import Path

from src.core.config import reload_settings
from src.db.models.channel import Channel
from src.db.models.document import Document
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import ContentChunk
from src.db.models.telegram_message import TelegramMessage
from src.db.session import init_db, session_scope
from src.knowledge.backtest_dataset import BacktestDatasetBuilder
from src.knowledge.course_summarizer import CourseSummarizerService
from src.knowledge.hybrid_retrieval import HybridRetrievalService
from src.knowledge.playbook_builder import PlaybookBuilder
from src.knowledge.rule_extractor import RuleClusterService, RuleExtractorService
from src.knowledge.schemas import HybridQueryFilters
from src.knowledge.vector_index import LocalVectorIndexService


def test_phase2_semantic_rules_playbooks_pipeline(tmp_path) -> None:
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'phase2.db').as_posix()}",
        }
    )
    init_db()

    with session_scope() as session:
        channel = Channel(
            input_reference="test_channel",
            title="SMC Academy",
            normalized_name="smc_academy",
            telegram_channel_id=123456,
        )
        session.add(channel)
        session.flush()

        message = TelegramMessage(
            channel_id=channel.id,
            telegram_message_id=1,
            content_type="text",
            text="Buy XAUUSD in London session after BOS and FVG confirmation. Entry 2320 stop loss 2310 tp1 2340 risk 1%",
            cleaned_text="Buy XAUUSD in London session after BOS and FVG confirmation. Entry 2320 stop loss 2310 tp1 2340 risk 1%",
            classification="signal",
            language="en",
            has_media=False,
        )
        session.add(message)
        session.flush()

        chunk = ContentChunk(
            source_type="telegram_message",
            source_id=message.id,
            channel_id=channel.id,
            message_id=message.id,
            chunk_index=0,
            text=message.cleaned_text,
            clean_text=message.cleaned_text,
            metadata_json=json.dumps(
                {
                    "classification": "signal",
                    "channel_name": channel.title,
                    "source_reference": "telegram_message:1",
                    "entities": {"authors": ["Mentor_A"]},
                }
            ),
        )
        session.add(chunk)
        session.flush()

        index_summary = LocalVectorIndexService(session, settings).build()
        assert index_summary["indexed_chunks"] == 1

        semantic_results = HybridRetrievalService(session, settings).query(
            "BOS FVG London session gold entry",
            HybridQueryFilters(limit=3),
        )
        assert semantic_results
        assert semantic_results[0].chunk_id == chunk.id

        extracted_rules = RuleExtractorService(session).run()
        assert extracted_rules >= 1
        clusters = RuleClusterService(session).run()
        assert clusters >= 1

        playbooks = PlaybookBuilder(session).build()
        assert playbooks >= 1

        dataset_summary = BacktestDatasetBuilder(session, settings).build()
        assert dataset_summary["rows"] >= 1


def test_course_module_summary_builds_from_processed_document(tmp_path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'course.db').as_posix()}",
        }
    )
    init_db()

    with session_scope() as session:
        channel = Channel(
            input_reference="course_channel",
            title="ICT Course Hub",
            normalized_name="ict_course_hub",
            telegram_channel_id=222,
        )
        session.add(channel)
        session.flush()

        message = TelegramMessage(
            channel_id=channel.id,
            telegram_message_id=2,
            content_type="document",
            text="Course pdf",
            cleaned_text="Course pdf",
            classification="educativo",
            language="en",
            has_media=True,
        )
        session.add(message)
        session.flush()

        file_asset = FileAsset(
            channel_id=channel.id,
            message_id=message.id,
            category="document",
            file_name="ict_masterclass.pdf",
            stored_path=str((tmp_path / "data" / "raw.pdf").resolve()),
            status="processed",
        )
        session.add(file_asset)
        session.flush()

        document = Document(
            file_id=file_asset.id,
            doc_type="pdf",
            extracted_text="INTRO\nMarket Structure and BOS.\nMODULE 2\nLiquidity Sweep and FVG entry.",
            section_index_json=json.dumps(
                [
                    {"position": 0, "title": "INTRO"},
                    {"position": 2, "title": "MODULE 2"},
                ]
            ),
            summary="Course summary",
        )
        session.add(document)
        session.flush()

        total = CourseSummarizerService(session).run()
        assert total == 2
