"""Reports for catalog-first Telegram ingestion."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models.external_resource import ExternalResource
from src.db.models.file_asset import FileAsset
from src.db.models.telegram_message import TelegramMessage


class CatalogReportService:
    """Summarize the knowledge map before heavy processing."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self) -> dict:
        by_category = dict(
            self.session.execute(
                select(FileAsset.category, func.count(FileAsset.id)).group_by(FileAsset.category)
            ).all()
        )
        by_status = dict(
            self.session.execute(
                select(FileAsset.status, func.count(FileAsset.id)).group_by(FileAsset.status)
            ).all()
        )
        external_by_provider = dict(
            self.session.execute(
                select(ExternalResource.provider, func.count(ExternalResource.id)).group_by(ExternalResource.provider)
            ).all()
        )
        total_size = self.session.scalar(select(func.coalesce(func.sum(FileAsset.size_bytes), 0))) or 0
        top_resources = self.session.execute(
            select(FileAsset.file_name, FileAsset.category, FileAsset.priority, FileAsset.size_bytes, FileAsset.status)
            .order_by(FileAsset.priority.asc(), FileAsset.size_bytes.asc().nulls_last())
            .limit(50)
        ).all()
        messages_with_links = (
            self.session.scalar(
                select(func.count(TelegramMessage.id)).where(
                    TelegramMessage.external_links_json.is_not(None),
                    TelegramMessage.external_links_json != "[]",
                )
            )
            or 0
        )
        return {
            "documents": by_category.get("document", 0),
            "videos": by_category.get("video", 0),
            "audios": by_category.get("audio", 0),
            "images": by_category.get("image", 0),
            "archives": self._archive_count(),
            "external_links": sum(external_by_provider.values()),
            "messages_with_links": messages_with_links,
            "estimated_total_bytes": int(total_size),
            "by_status": by_status,
            "external_by_provider": external_by_provider,
            "top_resources": [
                {
                    "file_name": row.file_name,
                    "category": row.category,
                    "priority": row.priority,
                    "size_bytes": row.size_bytes,
                    "status": row.status,
                }
                for row in top_resources
            ],
        }

    def _archive_count(self) -> int:
        return (
            self.session.scalar(
                select(func.count(FileAsset.id)).where(FileAsset.extension.in_([".zip", ".rar", ".7z"]))
            )
            or 0
        )
