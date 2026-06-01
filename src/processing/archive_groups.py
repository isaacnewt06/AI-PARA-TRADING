"""Multipart archive grouping helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


PART_PATTERN = re.compile(r"^(?P<base>.+?)\.part(?P<part>\d+)\.rar$", re.IGNORECASE)


@dataclass(slots=True)
class ArchivePartInfo:
    """Parsed multipart info from an archive filename."""

    group_key: str | None
    part_number: int | None
    is_multipart: bool


def parse_archive_part(file_name: str) -> ArchivePartInfo:
    normalized = Path(file_name).name
    match = PART_PATTERN.match(normalized)
    if not match:
        return ArchivePartInfo(group_key=None, part_number=None, is_multipart=False)
    base = match.group("base")
    part_number = int(match.group("part"))
    return ArchivePartInfo(group_key=base, part_number=part_number, is_multipart=True)


def multipart_status(parts_present: set[int]) -> tuple[int | None, str]:
    if not parts_present:
        return None, "single_archive"
    total_estimated = max(parts_present)
    expected = set(range(1, total_estimated + 1))
    if parts_present == {1}:
        return 1, "multipart_single_part_observed"
    if parts_present == expected:
        return total_estimated, "multipart_complete_observed"
    return total_estimated, "multipart_incomplete"
