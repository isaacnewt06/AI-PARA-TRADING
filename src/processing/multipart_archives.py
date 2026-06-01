"""Helpers for making multipart archives available from a single directory."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from src.core.config import get_settings
from src.core.paths import sanitize_filesystem_name
from src.db.models.file_asset import FileAsset
from src.db.repositories.files import FileRepository
from src.processing.archive_groups import parse_archive_part


def ensure_multipart_group_root(file_asset: FileAsset, file_repository: FileRepository) -> Path:
    """Ensure multipart RAR volumes are co-located for tools that require adjacent parts."""

    parsed = parse_archive_part(file_asset.file_name)
    if not parsed.is_multipart or getattr(file_repository, "session", None) is None:
        return Path(file_asset.stored_path)

    siblings = sorted(
        [
            item
            for item in file_repository.list_archives()
            if item.archive_group_key == parsed.group_key
        ],
        key=lambda item: (item.archive_part_number or 999, item.id),
    )
    if not siblings:
        return Path(file_asset.stored_path)

    settings = get_settings()
    workspace_dir = settings.paths.processed_dir / "multipart_workspaces" / sanitize_filesystem_name(parsed.group_key or "multipart")
    workspace_dir.mkdir(parents=True, exist_ok=True)

    for sibling in siblings:
        source = Path(sibling.stored_path)
        if not source.exists():
            continue
        target = workspace_dir / sibling.file_name
        if target.exists() and target.stat().st_size == source.stat().st_size:
            continue
        if target.exists():
            target.unlink()
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)

    first_part = next(
        (item for item in siblings if (item.archive_part_number or 999) == 1),
        siblings[0],
    )
    return workspace_dir / first_part.file_name
