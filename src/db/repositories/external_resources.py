"""Repository for external resources discovered in Telegram messages."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.external_resource import ExternalResource


class ExternalResourceRepository:
    """Persistence helpers for external links."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, payload: dict) -> tuple[ExternalResource, bool]:
        stmt = select(ExternalResource).where(
            ExternalResource.message_id == payload["message_id"],
            ExternalResource.url == payload["url"],
        )
        entity = self.session.scalar(stmt)
        created = entity is None
        if entity is None:
            entity = ExternalResource(**payload)
            self.session.add(entity)
        else:
            for key, value in payload.items():
                setattr(entity, key, value)
        self.session.flush()
        return entity, created

    def list_pending(self, provider: str | None = None, limit: int | None = None) -> list[ExternalResource]:
        stmt = select(ExternalResource).where(ExternalResource.status == "external_pending")
        if provider:
            stmt = stmt.where(ExternalResource.provider == provider)
        stmt = stmt.order_by(ExternalResource.priority.asc(), ExternalResource.id.asc())
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))
