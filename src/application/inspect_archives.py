"""Application services for inspecting and ranking archives."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.file_asset import FileAsset
from src.db.repositories.archive_contents import ArchiveContentRepository
from src.processing.archive_inspector import ArchiveInspector
from src.processing.archive_selector import ArchiveSelector


class ArchiveInspectionApplicationService:
    """Inspect queued/downloaded archives without extracting them."""

    archive_extensions = {".zip", ".rar", ".7z"}

    def __init__(self, session: Session) -> None:
        self.session = session
        self.inspector = ArchiveInspector(session)
        self.content_repository = ArchiveContentRepository(session)
        self.selector = ArchiveSelector(session)

    def inspect(self, limit: int | None = None) -> dict:
        archives = self._list_archives(limit=limit)
        summaries = []
        for file_asset in archives:
            summaries.append(asdict(self.inspector.inspect_file(file_asset)))
        return {"archives_inspected": len(summaries), "summaries": summaries}

    def rank(self, limit: int = 50) -> list[dict]:
        return [asdict(item) for item in self.selector.rank(limit=limit)]

    def select(self, limit: int = 10) -> list[dict]:
        return [asdict(item) for item in self.selector.select(limit=limit)]

    def explain(self, value: str) -> dict | None:
        return self.selector.explain(value)

    def _list_archives(self, limit: int | None) -> list[FileAsset]:
        stmt = select(FileAsset).where(FileAsset.extension.in_(sorted(self.archive_extensions))).order_by(
            FileAsset.priority.asc(),
            FileAsset.id.asc(),
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))
