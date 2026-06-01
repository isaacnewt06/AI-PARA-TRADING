"""Run tracking repository."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.run import IngestionRun, ProcessingRun


class RunRepository:
    """Persistence helpers for run models."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def start_ingestion(self, *, channel_id: int | None, mode: str) -> IngestionRun:
        run = IngestionRun(channel_id=channel_id, mode=mode, started_at=datetime.now(timezone.utc))
        self.session.add(run)
        self.session.flush()
        return run

    def finish_ingestion(self, run: IngestionRun, *, status: str, notes: str | None = None) -> IngestionRun:
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.notes = notes
        self.session.flush()
        return run

    def start_processing(self) -> ProcessingRun:
        run = ProcessingRun(started_at=datetime.now(timezone.utc))
        self.session.add(run)
        self.session.flush()
        return run

    def finish_processing(self, run: ProcessingRun, *, status: str, notes: str | None = None) -> ProcessingRun:
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.notes = notes
        self.session.flush()
        return run

    def latest_ingestion_runs(self, limit: int = 5) -> list[IngestionRun]:
        stmt = select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def latest_processing_runs(self, limit: int = 5) -> list[ProcessingRun]:
        stmt = select(ProcessingRun).order_by(ProcessingRun.started_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))
