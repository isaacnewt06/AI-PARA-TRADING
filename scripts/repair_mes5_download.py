"""Resume and verify the MES_5 Telegram archive group.

This is intentionally targeted. It does not select other archive groups.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.process_cataloged_assets import ArchiveDownloadOptions, CatalogedAssetProcessingService
from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.session import session_scope
from src.db.session import init_db
from src.db.models.file_asset import FileAsset


GROUP_KEY = "MES_5"


def file_status(path_text: str | None) -> dict:
    if not path_text:
        return {"exists": False, "size_bytes": 0}
    path = Path(path_text)
    partial = Path(f"{path}.part")
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "partial_path": str(partial),
        "partial_exists": partial.exists(),
        "partial_size_bytes": partial.stat().st_size if partial.exists() else 0,
    }


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    init_db()
    with session_scope() as session:
        files = (
            session.query(FileAsset)
            .filter(FileAsset.archive_group_key == GROUP_KEY)
            .order_by(FileAsset.archive_part_number.asc())
            .all()
        )
        if not files:
            print(json.dumps({"status": "not_found", "group": GROUP_KEY}, indent=2))
            return

        before = [
            {
                "id": item.id,
                "file_name": item.file_name,
                "expected_size_bytes": item.size_bytes,
                "status": item.status,
                "processing_status": item.processing_status,
                **file_status(item.stored_path),
            }
            for item in files
        ]

        service = CatalogedAssetProcessingService(session, settings)
        result = service.download_archive_group_for_file(
            files[0],
            options=ArchiveDownloadOptions(
                limit=1,
                max_group_size_mb=4096,
                skip_large_groups=False,
                download_only_complete_groups=True,
                retry_attempts=8,
            ),
        )
        session.flush()

        refreshed = (
            session.query(FileAsset)
            .filter(FileAsset.archive_group_key == GROUP_KEY)
            .order_by(FileAsset.archive_part_number.asc())
            .all()
        )
        after = [
            {
                "id": item.id,
                "file_name": item.file_name,
                "expected_size_bytes": item.size_bytes,
                "status": item.status,
                "processing_status": item.processing_status,
                "multipart_group_status": item.multipart_group_status,
                **file_status(item.stored_path),
            }
            for item in refreshed
        ]
        print(
            json.dumps(
                {
                    "group": GROUP_KEY,
                    "download_result": result,
                    "before": before,
                    "after": after,
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
