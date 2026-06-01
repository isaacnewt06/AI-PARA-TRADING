"""Lightweight schema evolution helpers for SQLite deployments."""

from __future__ import annotations

import time

from sqlalchemy import Engine, inspect
from sqlalchemy.exc import SQLAlchemyError


TABLE_COLUMN_DEFINITIONS: dict[str, dict[str, str]] = {
    "platform_users": {
        "max_broker_accounts": "INTEGER NOT NULL DEFAULT 1",
        "password_hash": "TEXT",
        "password_updated_at": "DATETIME",
    },
    "content_chunks": {
        "quality_score": "FLOAT",
        "source_weight": "FLOAT",
        "usefulness_score": "FLOAT",
        "quality_label": "VARCHAR(64)",
        "quality_flags_json": "TEXT",
        "filtered_out": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "telegram_messages": {
        "priority": "VARCHAR(32) NOT NULL DEFAULT 'medium'",
        "processing_status": "VARCHAR(32) NOT NULL DEFAULT 'discovered'",
        "external_links_json": "TEXT",
    },
    "files": {
        "extension": "VARCHAR(32)",
        "priority": "VARCHAR(32) NOT NULL DEFAULT 'medium'",
        "processing_status": "VARCHAR(32) NOT NULL DEFAULT 'discovered'",
        "knowledge_density_score": "FLOAT",
        "strategy_probability_score": "FLOAT",
        "priority_score": "FLOAT",
        "priority_notes": "TEXT",
        "archive_selection_score": "FLOAT",
        "archive_usefulness_label": "VARCHAR(64)",
        "archive_selection_reason": "TEXT",
        "archive_document_count": "INTEGER",
        "archive_video_count": "INTEGER",
        "archive_image_count": "INTEGER",
        "archive_script_count": "INTEGER",
        "archive_executable_count": "INTEGER",
        "archive_duplicate_ratio": "FLOAT",
        "archive_internal_structure_score": "FLOAT",
        "archive_educational_score": "FLOAT",
        "archive_strategy_score": "FLOAT",
        "archive_processing_recommendation": "VARCHAR(64)",
        "archive_similarity_group": "VARCHAR(255)",
        "duplicate_cluster_id": "VARCHAR(255)",
        "duplicate_confidence": "FLOAT",
        "archive_group_key": "VARCHAR(255)",
        "archive_part_number": "INTEGER",
        "archive_total_parts_estimated": "INTEGER",
        "multipart_group_status": "VARCHAR(64)",
        "archive_last_ranked_at": "DATETIME",
        "notes": "TEXT",
    },
    "extracted_rules": {
        "channel_id": "INTEGER",
        "source_type": "VARCHAR(32)",
        "source_reference": "VARCHAR(255)",
        "channel_name": "VARCHAR(255)",
        "author_name": "VARCHAR(255)",
        "context": "TEXT",
        "entry_condition": "TEXT",
        "confirmation": "TEXT",
        "stop_loss": "TEXT",
        "take_profit": "TEXT",
        "risk_management": "TEXT",
        "session_filter": "TEXT",
        "observations": "TEXT",
        "concepts_json": "TEXT",
        "strategy_key": "VARCHAR(255)",
        "normalized_signature": "VARCHAR(255)",
        "cluster_key": "VARCHAR(255)",
        "module_name": "VARCHAR(255)",
        "source_file_name": "VARCHAR(255)",
        "example_snippet": "TEXT",
    },
    "strategy_playbooks": {
        "strategy_key": "VARCHAR(255)",
        "channel_id": "INTEGER",
        "author_name": "VARCHAR(255)",
        "concepts_json": "TEXT",
        "steps_json": "TEXT",
        "rules_count": "INTEGER NOT NULL DEFAULT 0",
        "confidence": "FLOAT",
    },
    "normalized_rules": {
        "traceability_json": "TEXT",
    },
    "strategy_candidates": {
        "source_traceability_json": "TEXT",
    },
}

INDEX_STATEMENTS: dict[str, str] = {
    "uq_files_message_telegram_file": (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_files_message_telegram_file "
        "ON files (message_id, telegram_file_id)"
    ),
    "ix_rules_chunk_signature": (
        "CREATE INDEX IF NOT EXISTS ix_rules_chunk_signature "
        "ON extracted_rules (source_chunk_id, normalized_signature)"
    ),
    "ix_rules_strategy_author": (
        "CREATE INDEX IF NOT EXISTS ix_rules_strategy_author "
        "ON extracted_rules (strategy_key, author_name)"
    ),
    "ix_playbooks_strategy": (
        "CREATE INDEX IF NOT EXISTS ix_playbooks_strategy "
        "ON strategy_playbooks (strategy_key, author_name)"
    ),
    "ix_normalized_rules_strategy": (
        "CREATE INDEX IF NOT EXISTS ix_normalized_rules_strategy "
        "ON normalized_rules (strategy_family, setup_name)"
    ),
    "ix_quant_conditions_key": (
        "CREATE INDEX IF NOT EXISTS ix_quant_conditions_key "
        "ON quantifiable_conditions (condition_key)"
    ),
    "ix_strategy_candidates_key": (
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_strategy_candidates_key "
        "ON strategy_candidates (candidate_key)"
    ),
    "ix_files_archive_selection_score": (
        "CREATE INDEX IF NOT EXISTS ix_files_archive_selection_score "
        "ON files (archive_selection_score)"
    ),
    "ix_files_archive_recommendation": (
        "CREATE INDEX IF NOT EXISTS ix_files_archive_recommendation "
        "ON files (archive_processing_recommendation)"
    ),
}


def ensure_schema_compatibility(engine: Engine) -> None:
    """Add missing columns/indexes for lightweight local upgrades."""
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in TABLE_COLUMN_DEFINITIONS.items():
            if not inspector.has_table(table_name):
                continue
            existing_columns = {row["name"] for row in inspector.get_columns(table_name)}
            for column_name, definition in columns.items():
                if column_name in existing_columns:
                    continue
                _exec_with_retry(
                    connection,
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}",
                )

        for statement in INDEX_STATEMENTS.values():
            try:
                _exec_with_retry(connection, statement)
            except SQLAlchemyError:
                # Keep local upgrades resilient even if legacy data violates a new uniqueness expectation.
                continue


def _exec_with_retry(connection, statement: str, attempts: int = 5) -> None:
    """Execute lightweight SQLite DDL with a small retry window for Windows file locks."""

    for attempt in range(attempts):
        try:
            connection.exec_driver_sql(statement)
            return
        except SQLAlchemyError as exc:
            if "database is locked" not in str(exc).lower() or attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
