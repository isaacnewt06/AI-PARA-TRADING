from __future__ import annotations

import json
from pathlib import Path

from src.application.knowledge_learning_cycle import (
    KnowledgeLearningCycleApplicationService,
    KnowledgeLearningCycleOptions,
)
from src.core.config import reload_settings
from src.db.models.channel import Channel
from src.db.models.knowledge import ExtractedRule, NormalizedRule, TopStrategyDetected
from src.db.models.platform import LearningIntegration, PlatformUser
from src.db.session import init_db, session_scope


def _configure(tmp_path: Path):
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'learning_cycle.db').as_posix()}",
        }
    )
    init_db()
    return settings


def _seed_learning_data(session) -> None:
    owner = PlatformUser(email="owner@example.com", display_name="Owner", role="owner", password_hash="x")
    session.add(owner)
    session.flush()
    session.add(
        LearningIntegration(
            owner_user_id=owner.id,
            source_type="telegram_channel",
            source_reference="https://t.me/test",
            source_label="Test Channel",
            enabled=True,
            auto_sync=True,
        )
    )
    rule = ExtractedRule(
        rule_type="entry",
        rule_text="Sell after order block rejection with liquidity sweep and defined stop.",
        strategy_key="ob_rejection",
        confidence=0.8,
    )
    session.add(rule)
    session.flush()
    session.add(
        NormalizedRule(
            extracted_rule_id=rule.id,
            strategy_family="OB Rejection",
            setup_name="OB rejection sweep",
            direction_bias="SELL",
            concept_tags=json.dumps(["order_block", "liquidity_sweep", "rejection"]),
            market_conditions=json.dumps(["expansion", "trend"]),
            entry_conditions=json.dumps(["rejection candle"]),
            confirmation_conditions=json.dumps(["bearish close"]),
            stop_model="above_swing",
            take_profit_model="rr_fixed",
            rr_target=2.0,
            risk_model="reduced_if_medium_quality",
            risk_percent=0.5,
            confidence_score=0.72,
        )
    )
    session.add(
        TopStrategyDetected(
            strategy_key="ob_rejection",
            name="OB Rejection",
            strategy_family="OB Rejection",
            relevance_score=0.84,
            rule_count=1,
            candidate_count=1,
        )
    )


def test_knowledge_learning_cycle_writes_reports_and_updates_integrations(tmp_path: Path, monkeypatch) -> None:
    settings = _configure(tmp_path)
    with session_scope() as session:
        _seed_learning_data(session)
        service = KnowledgeLearningCycleApplicationService(session, settings)
        monkeypatch.setattr(service, "_build_phases", lambda options: [("cycle-status", service._snapshot_counts)])

        result = service.run(KnowledgeLearningCycleOptions(skip_sync=True, skip_market_map=True))

        report_json = settings.paths.knowledge_dir / "learning_cycle" / "learning_cycle_report.json"
        report_md = settings.paths.knowledge_dir / "learning_cycle" / "learning_cycle_report.md"
        integration = session.query(LearningIntegration).one()

        assert result["cycles_completed"] == 1
        assert report_json.exists()
        assert report_md.exists()
        assert integration.last_sync_at is not None
        assert "applicability" in (integration.notes or "")


def test_knowledge_learning_cycle_turns_rules_into_applicable_patterns(tmp_path: Path, monkeypatch) -> None:
    settings = _configure(tmp_path)
    with session_scope() as session:
        _seed_learning_data(session)
        service = KnowledgeLearningCycleApplicationService(session, settings)
        monkeypatch.setattr(service, "_build_phases", lambda options: [("cycle-status", service._snapshot_counts)])

        service.run_once(KnowledgeLearningCycleOptions(skip_sync=True, skip_market_map=True))
        payload = json.loads((settings.paths.knowledge_dir / "learning_cycle" / "learning_cycle_report.json").read_text())

        applicable = payload["applicable_knowledge"]
        assert applicable["dominant_strategy_families"][0]["family"] == "OB Rejection"
        assert applicable["recognized_patterns"][0]["pattern"] in {"order_block", "liquidity_sweep", "rejection"}
        assert applicable["strategy_combinations"][0]["primary"] == "OB Rejection"
        assert payload["risk_governance"]["status"] == "available"


def test_knowledge_learning_cycle_continues_after_phase_failure(tmp_path: Path, monkeypatch) -> None:
    settings = _configure(tmp_path)
    with session_scope() as session:
        service = KnowledgeLearningCycleApplicationService(session, settings)

        def fail_phase() -> dict:
            raise RuntimeError("boom")

        monkeypatch.setattr(
            service,
            "_build_phases",
            lambda options: [
                ("bad-phase", fail_phase),
                ("cycle-status", service._snapshot_counts),
            ],
        )

        result = service.run_once(KnowledgeLearningCycleOptions(skip_sync=True, skip_market_map=True))
        payload = json.loads((settings.paths.knowledge_dir / "learning_cycle" / "learning_cycle_report.json").read_text())

        assert result["status"] == "completed_with_warnings"
        assert payload["failed_phases"][0]["phase"] == "bad-phase"


def test_knowledge_learning_cycle_syncs_only_telegram_channels(tmp_path: Path) -> None:
    settings = _configure(tmp_path)
    with session_scope() as session:
        session.add_all(
            [
                Channel(input_reference="https://t.me/tradingcursosgratiss", title="Telegram", normalized_name="telegram", is_active=True),
                Channel(input_reference="manual://knowledge", title="Manual", normalized_name="manual", is_active=True),
                Channel(input_reference="local-education://trading education", title="Local", normalized_name="local", is_active=True),
            ]
        )
        session.flush()
        service = KnowledgeLearningCycleApplicationService(session, settings, ingestion_service=object())

        assert service._target_channels(None) == ["https://t.me/tradingcursosgratiss"]


def test_knowledge_learning_cycle_imports_manual_knowledge_phase(tmp_path: Path, monkeypatch) -> None:
    settings = _configure(tmp_path)
    manual_dir = settings.paths.knowledge_dir / "manual"
    manual_dir.mkdir(parents=True)
    (manual_dir / "execution_protocol.md").write_text(
        "OB Rejection protocol: wait for order block rejection, liquidity sweep, confirmation candle, stop loss and RR.",
        encoding="utf-8",
    )

    with session_scope() as session:
        owner = PlatformUser(email="owner@example.com", display_name="Owner", role="owner", password_hash="x")
        session.add(owner)
        session.flush()
        session.add(
            LearningIntegration(
                owner_user_id=owner.id,
                source_type="manual_knowledge",
                source_reference="manual://knowledge",
                source_label="Manual Knowledge",
                enabled=True,
                auto_sync=True,
            )
        )
        session.flush()
        service = KnowledgeLearningCycleApplicationService(session, settings)

        phases = dict(service._local_knowledge_import_phases())
        result = phases["import-manual-knowledge"]()

        assert result["manual_notes_imported"] == 1
        assert result["chunks_created"] == 1
