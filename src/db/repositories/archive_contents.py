"""Repository for archive inspection inventories."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.db.models.archive_content import ArchiveContent


class ArchiveContentRepository:
    """Persistence helpers for archive content rows."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_file(self, file_id: int, rows: list[dict]) -> int:
        self.session.execute(delete(ArchiveContent).where(ArchiveContent.file_id == file_id))
        for row in rows:
            self.session.add(ArchiveContent(**row))
        self.session.flush()
        return len(rows)

    def list_for_file(self, file_id: int) -> list[ArchiveContent]:
        stmt = select(ArchiveContent).where(ArchiveContent.file_id == file_id).order_by(ArchiveContent.id.asc())
        return list(self.session.scalars(stmt))
