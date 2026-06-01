"""Advanced archive selection and ranking for educational trading knowledge."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.archive_content import ArchiveContent
from src.db.models.file_asset import FileAsset
from src.db.models.knowledge import ExtractedRule
from src.db.repositories.archive_contents import ArchiveContentRepository
from src.db.repositories.files import FileRepository
from src.processing.archive_groups import multipart_status, parse_archive_part
from src.processing.archive_inspector import ArchiveInspector

EDUCATIONAL_TERMS = re.compile(
    r"\b(?:course|curso|mentor|mentorship|masterclass|class|clase|lesson|leccion|lección|module|modulo|m[oó]dulo|session|sesion|sesión|week|month|ict|smc|trading|forex|strategy|estrategia|setup|risk management|liquidity|order block|fvg|bos)\b",
    re.IGNORECASE,
)
SOFTWARE_TERMS = re.compile(
    r"\b(?:indicator|indicador|tool|tools|software|robot|ea|expert advisor|installer|crack|patched|license|dll|exe|msi)\b",
    re.IGNORECASE,
)
CLICKBAIT_TERMS = re.compile(
    r"\b(?:mega pack|pack completo|full pack|gratis|free download|vip|premium|ultimate|secret)\b",
    re.IGNORECASE,
)
MES_PATTERN = re.compile(r"\bmes[_\s-]?\d+\b", re.IGNORECASE)
STRATEGY_TERMS = re.compile(
    r"\b(?:bos|break of structure|choch|change of character|fvg|fair value gap|order block|ob|liquidity|risk management|session|london|new york|killzone|setup|entry|stop loss|take profit|rr)\b",
    re.IGNORECASE,
)
PEDAGOGICAL_VIDEO_PATTERN = re.compile(
    r"\b(?:class|clase|lesson|leccion|lección|module|modulo|m[oó]dulo|session|sesion|sesión|week|month|intro)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ArchiveSelectionResult:
    """Materialized archive ranking record."""

    file_id: int
    file_name: str
    archive_selection_score: float
    archive_usefulness_label: str
    archive_selection_reason: str
    archive_document_count: int
    archive_video_count: int
    archive_image_count: int
    archive_script_count: int
    archive_executable_count: int
    archive_duplicate_ratio: float
    archive_internal_structure_score: float
    archive_educational_score: float
    archive_strategy_score: float
    archive_processing_recommendation: str
    archive_similarity_group: str | None
    duplicate_cluster_id: str | None
    duplicate_confidence: float
    support_summary: dict


class ArchiveSelector:
    """Rank archives by likely educational trading value and processing priority."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.file_repository = FileRepository(session)
        self.content_repository = ArchiveContentRepository(session)
        self.inspector = ArchiveInspector(session)

    def rank(self, limit: int | None = None) -> list[ArchiveSelectionResult]:
        archives = self.file_repository.list_archives()
        base_records = [self._base_record(file_asset) for file_asset in archives]
        duplicate_meta = self._duplicate_meta(base_records)
        results = [self._score_record(record, duplicate_meta.get(record["file_asset"].id)) for record in base_records]
        for result in results:
            self._persist_result(result)
        self.session.flush()
        results.sort(key=lambda item: (-item.archive_selection_score, item.file_name.lower()))
        return results[:limit] if limit is not None else results

    def select(self, limit: int = 10) -> list[ArchiveSelectionResult]:
        ranked = self.rank()
        grouped_candidates: dict[str, list[ArchiveSelectionResult]] = {}
        for candidate in ranked:
            group_key = candidate.support_summary.get("archive_group_key")
            if group_key:
                grouped_candidates.setdefault(group_key, []).append(candidate)
        grouped: dict[str, ArchiveSelectionResult] = {}
        ungrouped: list[ArchiveSelectionResult] = []
        for item in ranked:
            if self._already_processed(item.file_id):
                continue
            if item.archive_processing_recommendation not in {"process_now", "process_documents_only", "inspect_first", "process_videos_later", "manual_review"}:
                continue
            group_key = item.support_summary.get("archive_group_key")
            if group_key:
                representative = self._group_anchor_candidate(grouped_candidates.get(group_key, []), fallback=item)
                current = grouped.get(group_key)
                item_preference = self._group_preference(representative)
                current_preference = self._group_preference(current) if current is not None else None
                if current is None or item_preference < current_preference or (
                    item_preference == current_preference
                    and representative.archive_selection_score > current.archive_selection_score
                ):
                    grouped[group_key] = representative
            else:
                ungrouped.append(item)
        selected = list(grouped.values()) + ungrouped
        selected.sort(
            key=lambda item: (
                self._recommendation_priority(item.archive_processing_recommendation),
                -item.archive_selection_score,
                item.file_name.lower(),
            )
        )
        return selected[:limit]

    def _already_processed(self, file_id: int) -> bool:
        file_asset = self.file_repository.get_by_id(file_id)
        if file_asset is None:
            return False
        group_files = self._group_file_assets(file_asset)
        archive_ids = {item.id for item in group_files}
        for candidate in self.session.scalars(select(FileAsset).where(FileAsset.category == "document")):
            if not candidate.notes:
                continue
            for archive_id in archive_ids:
                if f"Extracted from archive file_id={archive_id}" in candidate.notes:
                    return True
        return False

    def _group_file_assets(self, file_asset: FileAsset) -> list[FileAsset]:
        if not file_asset.archive_group_key:
            return [file_asset]
        return [
            item
            for item in self.file_repository.list_archives()
            if item.archive_group_key == file_asset.archive_group_key
        ]

    @staticmethod
    def _group_anchor_candidate(candidates: list[ArchiveSelectionResult], *, fallback: ArchiveSelectionResult) -> ArchiveSelectionResult:
        if not candidates:
            return fallback
        anchor = next(
            (
                item
                for item in candidates
                if (item.support_summary.get("archive_part_number") or 999) == 1
            ),
            None,
        )
        return anchor or fallback

    def explain(self, value: str) -> dict | None:
        file_asset = self.file_repository.get_by_id_or_name(value)
        if file_asset is None:
            return None
        ranked = self.rank()
        match = next((item for item in ranked if item.file_id == file_asset.id), None)
        if match is None:
            return None
        return {
            "file_id": match.file_id,
            "file_name": match.file_name,
            "archive_selection_score": match.archive_selection_score,
            "archive_usefulness_label": match.archive_usefulness_label,
            "archive_processing_recommendation": match.archive_processing_recommendation,
            "archive_selection_reason": match.archive_selection_reason,
            "support_summary": match.support_summary,
        }

    def _base_record(self, file_asset: FileAsset) -> dict:
        multipart = parse_archive_part(file_asset.file_name)
        if multipart.is_multipart and not file_asset.archive_group_key:
            siblings = [
                parse_archive_part(item.file_name).part_number
                for item in self.file_repository.list_archives()
                if parse_archive_part(item.file_name).group_key == multipart.group_key
            ]
            total_parts_estimated, group_status = multipart_status({part for part in siblings if part is not None})
            file_asset.archive_group_key = multipart.group_key
            file_asset.archive_part_number = multipart.part_number
            file_asset.archive_total_parts_estimated = total_parts_estimated
            file_asset.multipart_group_status = group_status
        rows = self.content_repository.list_for_file(file_asset.id)
        inspection = self._inspection_summary(file_asset, rows)
        message_text = ""
        if file_asset.message:
            message_text = " ".join(
                part
                for part in [file_asset.message.text, file_asset.message.cleaned_text, self._links_text(file_asset.message.external_links_json)]
                if part
            )
        text_context = " ".join(filter(None, [file_asset.file_name, message_text]))
        internal_paths = [row.internal_path for row in rows]
        internal_text = " ".join(internal_paths)
        return {
            "file_asset": file_asset,
            "rows": rows,
            "inspection": inspection,
            "text_context": text_context,
            "internal_text": internal_text,
            "content_signature": self._content_signature(rows),
            "theme_tokens": self._theme_tokens(text_context, internal_text),
            "size_bytes": file_asset.size_bytes or 0,
        }

    def _inspection_summary(self, file_asset: FileAsset, rows: list[ArchiveContent]) -> dict:
        parsed = self._summary_from_notes(file_asset)
        if parsed is not None:
            return parsed
        if rows:
            summary = self.inspector._summary(
                file_asset=file_asset,
                rows=[self._row_dict(row) for row in rows],
                status=file_asset.processing_status or "inspected",
                notes=None,
            )
            return asdict(summary)
        summary = self.inspector.inspect_file(file_asset)
        return asdict(summary)

    @staticmethod
    def _summary_from_notes(file_asset: FileAsset) -> dict | None:
        if not file_asset.notes:
            return None
        try:
            parsed = json.loads(file_asset.notes)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) and "estimated_value_score" in parsed else None

    @staticmethod
    def _row_dict(row: ArchiveContent) -> dict:
        return {
            "internal_path": row.internal_path,
            "content_kind": row.content_kind,
            "duplicate_key": row.duplicate_key,
        }

    def _score_record(self, record: dict, duplicate_meta: dict | None) -> ArchiveSelectionResult:
        file_asset: FileAsset = record["file_asset"]
        inspection = record["inspection"]
        text_context: str = record["text_context"]
        internal_text: str = record["internal_text"]
        educational_hits = len(EDUCATIONAL_TERMS.findall(text_context))
        strategy_hits = len(STRATEGY_TERMS.findall(" ".join([text_context, internal_text])))
        software_hits_external = len(SOFTWARE_TERMS.findall(text_context))
        clickbait_hits = len(CLICKBAIT_TERMS.findall(text_context))
        external_archive_bonus = self._external_archive_bonus(file_asset, text_context)

        document_count = int(inspection.get("documents", 0))
        video_count = int(inspection.get("videos", 0))
        image_count = int(inspection.get("images", 0))
        script_count = int(inspection.get("scripts", 0))
        executable_count = int(inspection.get("executables", 0))
        entries = max(1, int(inspection.get("entries", 0)))
        duplicate_ratio = round(int(inspection.get("duplicates", 0)) / entries, 4)
        internal_structure_score = float(inspection.get("internal_structure_score", 0.0))

        educational_score = min(
            1.0,
            document_count * 0.1
            + video_count * 0.04
            + internal_structure_score * 0.3
            + min(0.22, educational_hits * 0.045)
            + (0.08 if document_count and video_count else 0.0),
        )
        strategy_score = min(
            1.0,
            min(0.35, strategy_hits * 0.05)
            + (0.15 if document_count and strategy_hits else 0.0)
            + (0.12 if re.search(r"\b(?:sl|tp|rr|risk)\b", text_context, re.IGNORECASE) else 0.0)
            + self._kb_bonus(text_context, internal_text)
            + external_archive_bonus,
        )
        size_score = self._size_score(file_asset.size_bytes, document_count, video_count)
        material_mix_bonus = 0.08 if document_count and video_count and image_count else 0.0
        caption_bonus = 0.1 if document_count and strategy_hits and educational_hits else 0.0
        document_bundle_bonus = 0.08 if document_count >= 3 and strategy_hits >= 2 else 0.0
        video_course_bonus = 0.05 if video_count >= 5 and internal_structure_score >= 0.4 else 0.0
        software_penalty = min(0.45, executable_count * 0.08 + script_count * 0.03 + software_hits_external * 0.04)
        duplicate_penalty = min(0.3, duplicate_ratio * 0.35 + (duplicate_meta["confidence"] * 0.18 if duplicate_meta else 0.0))
        clickbait_penalty = min(0.15, clickbait_hits * 0.04)
        inspection_penalty = 0.15 if inspection.get("status") in {"inspection_unavailable", "inspection_failed"} else 0.0
        huge_penalty = 0.12 if self._is_huge_and_low_value(file_asset.size_bytes, document_count, video_count, educational_score) else 0.0

        selection_score = max(
            0.0,
            min(
                1.0,
                educational_score * 0.38
                + strategy_score * 0.25
                + internal_structure_score * 0.22
                + size_score * 0.08
                + material_mix_bonus
                + caption_bonus
                + document_bundle_bonus
                + video_course_bonus
                + external_archive_bonus
                - software_penalty
                - duplicate_penalty
                - clickbait_penalty
                - inspection_penalty
                - huge_penalty,
            ),
        )
        label = self._label(
            selection_score=selection_score,
            document_count=document_count,
            video_count=video_count,
            executable_count=executable_count,
            duplicate_ratio=duplicate_ratio,
            duplicate_confidence=duplicate_meta["confidence"] if duplicate_meta else 0.0,
            educational_score=educational_score,
            inspection_status=str(inspection.get("status")),
            size_bytes=file_asset.size_bytes,
        )
        recommendation = self._recommendation(
            label=label,
            document_count=document_count,
            video_count=video_count,
            executable_count=executable_count,
            inspection_status=str(inspection.get("status")),
            archive_group_key=file_asset.archive_group_key,
        )
        similarity_group = duplicate_meta["group_id"] if duplicate_meta else None
        duplicate_cluster_id = duplicate_meta["cluster_id"] if duplicate_meta else None
        duplicate_confidence = round(duplicate_meta["confidence"], 4) if duplicate_meta else 0.0
        reasons = self._reasons(
            document_count=document_count,
            video_count=video_count,
            image_count=image_count,
            executable_count=executable_count,
            duplicate_ratio=duplicate_ratio,
            educational_hits=educational_hits,
            strategy_hits=strategy_hits,
            internal_structure_score=internal_structure_score,
            inspection_status=str(inspection.get("status")),
            recommendation=recommendation,
            label=label,
            duplicate_confidence=duplicate_confidence,
        )

        return ArchiveSelectionResult(
            file_id=file_asset.id,
            file_name=file_asset.file_name,
            archive_selection_score=round(selection_score, 4),
            archive_usefulness_label=label,
            archive_selection_reason="; ".join(reasons),
            archive_document_count=document_count,
            archive_video_count=video_count,
            archive_image_count=image_count,
            archive_script_count=script_count,
            archive_executable_count=executable_count,
            archive_duplicate_ratio=duplicate_ratio,
            archive_internal_structure_score=round(internal_structure_score, 4),
            archive_educational_score=round(educational_score, 4),
            archive_strategy_score=round(strategy_score, 4),
            archive_processing_recommendation=recommendation,
            archive_similarity_group=similarity_group,
            duplicate_cluster_id=duplicate_cluster_id,
            duplicate_confidence=duplicate_confidence,
            support_summary={
                "archive_group_key": file_asset.archive_group_key,
                "archive_part_number": file_asset.archive_part_number,
                "archive_total_parts_estimated": file_asset.archive_total_parts_estimated,
                "multipart_group_status": file_asset.multipart_group_status,
                "inspection_status": inspection.get("status"),
                "educational_hits": educational_hits,
                "strategy_hits": strategy_hits,
                "clickbait_hits": clickbait_hits,
                "software_hits_external": software_hits_external,
                "external_archive_bonus": round(external_archive_bonus, 4),
                "estimated_value_score": inspection.get("estimated_value_score"),
                "organized_video_dirs": inspection.get("organized_video_dirs"),
                "module_like_directories": inspection.get("module_like_directories"),
                "pedagogical_entries": inspection.get("pedagogical_entries"),
                "software_like_entries": inspection.get("software_like_entries"),
                "part_sequence_hits": inspection.get("part_sequence_hits"),
            },
        )

    def _persist_result(self, result: ArchiveSelectionResult) -> None:
        file_asset = self.session.get(FileAsset, result.file_id)
        if file_asset is None:
            return
        file_asset.archive_selection_score = result.archive_selection_score
        file_asset.archive_usefulness_label = result.archive_usefulness_label
        file_asset.archive_selection_reason = result.archive_selection_reason
        file_asset.archive_document_count = result.archive_document_count
        file_asset.archive_video_count = result.archive_video_count
        file_asset.archive_image_count = result.archive_image_count
        file_asset.archive_script_count = result.archive_script_count
        file_asset.archive_executable_count = result.archive_executable_count
        file_asset.archive_duplicate_ratio = result.archive_duplicate_ratio
        file_asset.archive_internal_structure_score = result.archive_internal_structure_score
        file_asset.archive_educational_score = result.archive_educational_score
        file_asset.archive_strategy_score = result.archive_strategy_score
        file_asset.archive_processing_recommendation = result.archive_processing_recommendation
        file_asset.archive_similarity_group = result.archive_similarity_group
        file_asset.duplicate_cluster_id = result.duplicate_cluster_id
        file_asset.duplicate_confidence = result.duplicate_confidence
        file_asset.archive_group_key = result.support_summary.get("archive_group_key")
        file_asset.archive_part_number = result.support_summary.get("archive_part_number")
        file_asset.archive_total_parts_estimated = result.support_summary.get("archive_total_parts_estimated")
        file_asset.multipart_group_status = result.support_summary.get("multipart_group_status")
        file_asset.archive_last_ranked_at = datetime.now(timezone.utc)
        self.session.add(file_asset)

    def _duplicate_meta(self, records: list[dict]) -> dict[int, dict]:
        adjacency: dict[int, set[int]] = {record["file_asset"].id: set() for record in records}
        confidences: dict[tuple[int, int], float] = {}
        for index, left in enumerate(records):
            for right in records[index + 1 :]:
                left_group = left["file_asset"].archive_group_key or parse_archive_part(left["file_asset"].file_name).group_key
                right_group = right["file_asset"].archive_group_key or parse_archive_part(right["file_asset"].file_name).group_key
                if left_group and right_group and left_group == right_group:
                    continue
                confidence = self._similarity(left, right)
                if confidence >= 0.72:
                    left_id = left["file_asset"].id
                    right_id = right["file_asset"].id
                    adjacency[left_id].add(right_id)
                    adjacency[right_id].add(left_id)
                    confidences[(left_id, right_id)] = confidence
                    confidences[(right_id, left_id)] = confidence

        visited: set[int] = set()
        result: dict[int, dict] = {}
        for file_id in adjacency:
            if file_id in visited or not adjacency[file_id]:
                continue
            stack = [file_id]
            component: list[int] = []
            visited.add(file_id)
            while stack:
                current = stack.pop()
                component.append(current)
                for neighbor in adjacency[current]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
            group_seed = ",".join(str(item) for item in sorted(component))
            group_hash = hashlib.sha1(group_seed.encode("utf-8")).hexdigest()[:10]
            for current in component:
                best = max((confidences.get((current, other), 0.0) for other in component if other != current), default=0.0)
                result[current] = {
                    "group_id": f"sim_{group_hash}",
                    "cluster_id": f"dup_{group_hash}",
                    "confidence": best,
                }
        return result

    def _similarity(self, left: dict, right: dict) -> float:
        left_name = self._normalized_archive_name(left["file_asset"].file_name)
        right_name = self._normalized_archive_name(right["file_asset"].file_name)
        name_similarity = SequenceMatcher(None, left_name, right_name).ratio()
        content_similarity = self._jaccard(left["content_signature"], right["content_signature"])
        theme_similarity = self._jaccard(left["theme_tokens"], right["theme_tokens"])
        size_similarity = self._size_similarity(left["size_bytes"], right["size_bytes"])
        return max(
            content_similarity * 0.5 + theme_similarity * 0.25 + name_similarity * 0.15 + size_similarity * 0.1,
            name_similarity * 0.45 + theme_similarity * 0.25 + size_similarity * 0.3,
        )

    @staticmethod
    def _normalized_archive_name(file_name: str) -> str:
        value = Path(file_name).stem.lower()
        value = re.sub(r"\b(?:part|parte|vol(?:ume)?|disc)\s*[_-]?\d+\b", "", value)
        value = re.sub(r"[_\-.]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _content_signature(rows: list[ArchiveContent]) -> set[str]:
        signature: set[str] = set()
        for row in rows[:60]:
            suffix = row.extension or ""
            stem = Path(row.file_name).stem.lower()
            signature.add(f"{row.content_kind}:{suffix}:{stem[:32]}")
        return signature

    @staticmethod
    def _theme_tokens(*values: str) -> set[str]:
        tokens: set[str] = set()
        for value in values:
            for token in re.findall(r"[a-zA-Z0-9_]{3,}", value.lower()):
                if token not in {"part1", "part2", "part3", "zip", "rar", "7z"}:
                    tokens.add(token)
        return tokens

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left.intersection(right)) / len(left.union(right))

    @staticmethod
    def _size_similarity(left: int, right: int) -> float:
        if not left or not right:
            return 0.0
        return max(0.0, 1 - abs(left - right) / max(left, right))

    def _kb_bonus(self, text_context: str, internal_text: str) -> float:
        recurrent = self._recurrent_concepts()
        if not recurrent:
            return 0.0
        text = f"{text_context} {internal_text}".lower()
        matches = sum(1 for concept in recurrent if concept.replace("_", " ") in text or concept in text)
        return min(0.2, matches * 0.04)

    def _recurrent_concepts(self) -> set[str]:
        concepts: Counter[str] = Counter()
        rules = list(self.session.scalars(select(ExtractedRule.concepts_json).where(ExtractedRule.concepts_json.is_not(None))))
        for concepts_json in rules:
            try:
                for concept in json.loads(concepts_json):
                    concepts[str(concept)] += 1
            except json.JSONDecodeError:
                continue
        return {concept for concept, count in concepts.items() if count >= 2}

    @staticmethod
    def _size_score(size_bytes: int | None, document_count: int, video_count: int) -> float:
        if not size_bytes:
            return 0.1
        size_mb = size_bytes / (1024 * 1024)
        if document_count >= 3 and size_mb <= 900:
            return 0.2
        if video_count >= 5 and 500 <= size_mb <= 6000:
            return 0.12
        if size_mb > 2500 and document_count == 0:
            return 0.02
        return 0.08

    @staticmethod
    def _external_archive_bonus(file_asset: FileAsset, text_context: str) -> float:
        bonus = 0.0
        if MES_PATTERN.search(text_context):
            bonus += 0.05
        if file_asset.archive_group_key and file_asset.multipart_group_status == "multipart_complete_observed":
            bonus += 0.06
        elif file_asset.archive_group_key and file_asset.multipart_group_status == "multipart_single_part_observed":
            bonus += 0.02
        if re.search(r"\b(?:month|mes|mentorship|masterclass|curso|course)\b", text_context, re.IGNORECASE):
            bonus += 0.05
        if file_asset.message and file_asset.message.channel and "cursos de trading" in file_asset.message.channel.title.lower():
            bonus += 0.03
        return min(0.18, bonus)

    @staticmethod
    def _is_huge_and_low_value(size_bytes: int | None, document_count: int, video_count: int, educational_score: float) -> bool:
        if not size_bytes:
            return False
        size_gb = size_bytes / (1024 * 1024 * 1024)
        return size_gb >= 1.5 and document_count <= 1 and video_count <= 2 and educational_score < 0.45

    @staticmethod
    def _label(
        *,
        selection_score: float,
        document_count: int,
        video_count: int,
        executable_count: int,
        duplicate_ratio: float,
        duplicate_confidence: float,
        educational_score: float,
        inspection_status: str,
        size_bytes: int | None,
    ) -> str:
        size_gb = (size_bytes or 0) / (1024 * 1024 * 1024)
        if inspection_status in {"inspection_unavailable", "inspection_failed"}:
            return "unknown_needs_manual_review"
        if executable_count >= 2 and document_count == 0:
            return "tooling_or_software"
        if duplicate_ratio >= 0.3 or duplicate_confidence >= 0.82:
            return "duplicate_or_low_value"
        if size_gb >= 1.5 and selection_score < 0.45:
            return "huge_low_priority"
        if document_count >= 4 and educational_score >= 0.7:
            return "high_value_course"
        if document_count >= 3 and video_count <= 2:
            return "likely_document_bundle"
        if video_count >= 5 and (selection_score >= 0.35 or educational_score >= 0.45):
            return "likely_video_course"
        if document_count >= 1 and video_count >= 1:
            return "mixed_educational"
        return "unknown_needs_manual_review"

    @staticmethod
    def _recommendation(
        *,
        label: str,
        document_count: int,
        video_count: int,
        executable_count: int,
        inspection_status: str,
        archive_group_key: str | None,
    ) -> str:
        if inspection_status in {"inspection_unavailable", "inspection_failed"}:
            return "manual_review"
        if inspection_status == "inspection_file_missing" and label == "huge_low_priority" and not archive_group_key:
            return "skip_for_now"
        if inspection_status == "inspection_file_missing" and label not in {"tooling_or_software", "duplicate_or_low_value"}:
            return "inspect_first"
        if label in {"tooling_or_software", "duplicate_or_low_value", "huge_low_priority"}:
            return "skip_for_now"
        if label in {"high_value_course", "likely_document_bundle"} and document_count >= 3 and video_count <= 4:
            return "process_now"
        if document_count >= 1 and video_count >= 3:
            return "process_documents_only"
        if label == "likely_video_course":
            return "process_videos_later"
        if executable_count:
            return "inspect_first"
        return "inspect_first"

    @staticmethod
    def _recommendation_priority(value: str) -> int:
        return {
            "process_now": 0,
            "process_documents_only": 1,
            "inspect_first": 2,
            "process_videos_later": 3,
            "manual_review": 4,
            "skip_for_now": 5,
        }.get(value, 9)

    @staticmethod
    def _group_preference(item: ArchiveSelectionResult) -> tuple[int, int, int]:
        part_number = item.support_summary.get("archive_part_number") or 999
        recommendation = item.archive_processing_recommendation
        inspection_status = str(item.support_summary.get("inspection_status") or "")
        anchor_rank = 0 if part_number == 1 else 1
        recommendation_rank = 0 if recommendation in {"process_now", "process_documents_only", "inspect_first"} else 1
        inspection_rank = 0 if inspection_status == "inspection_success" else 1
        return (anchor_rank, recommendation_rank + inspection_rank, part_number)

    @staticmethod
    def _reasons(
        *,
        document_count: int,
        video_count: int,
        image_count: int,
        executable_count: int,
        duplicate_ratio: float,
        educational_hits: int,
        strategy_hits: int,
        internal_structure_score: float,
        inspection_status: str,
        recommendation: str,
        label: str,
        duplicate_confidence: float,
    ) -> list[str]:
        reasons = [f"label={label}", f"recommendation={recommendation}"]
        if document_count:
            reasons.append(f"documents={document_count}")
        if video_count:
            reasons.append(f"videos={video_count}")
        if image_count:
            reasons.append(f"images={image_count}")
        if educational_hits:
            reasons.append(f"educational_context_hits={educational_hits}")
        if strategy_hits:
            reasons.append(f"strategy_term_hits={strategy_hits}")
        if internal_structure_score:
            reasons.append(f"internal_structure={internal_structure_score:.2f}")
        if executable_count:
            reasons.append(f"executables={executable_count}")
        if duplicate_ratio:
            reasons.append(f"duplicate_ratio={duplicate_ratio:.2f}")
        if duplicate_confidence:
            reasons.append(f"duplicate_confidence={duplicate_confidence:.2f}")
        if inspection_status != "inspected":
            reasons.append(f"inspection_status={inspection_status}")
        return reasons

    @staticmethod
    def _links_text(external_links_json: str | None) -> str:
        if not external_links_json:
            return ""
        try:
            rows = json.loads(external_links_json)
        except json.JSONDecodeError:
            return ""
        if not isinstance(rows, list):
            return ""
        return " ".join(str(item.get("url", "")) for item in rows if isinstance(item, dict))
