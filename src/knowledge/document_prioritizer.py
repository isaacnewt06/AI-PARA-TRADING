"""Prioritize files that are more likely to produce useful trading rules."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from src.db.models.file_asset import FileAsset
from src.db.repositories.files import FileRepository
from src.processing.document_processor import DocumentProcessor


TECHNICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bbos\b|\bbreak of structure\b", re.IGNORECASE),
    re.compile(r"\bchoch\b|\bchange of character\b", re.IGNORECASE),
    re.compile(r"\bfvg\b|\bfair value gap\b|\bimbalance\b", re.IGNORECASE),
    re.compile(r"\bob\b|\border block\b", re.IGNORECASE),
    re.compile(r"\bliquidity\b|\bsweep\b|\bgrab\b", re.IGNORECASE),
    re.compile(r"\bmarket structure\b|\bstructure\b", re.IGNORECASE),
    re.compile(r"\bmitigation\b|\bdisplacement\b", re.IGNORECASE),
    re.compile(r"\bpremium\b|\bdiscount\b", re.IGNORECASE),
    re.compile(r"\bentry\b|\bentrada\b", re.IGNORECASE),
    re.compile(r"\bconfirmation\b|\bconfirmacion\b|\bconfirmación\b", re.IGNORECASE),
    re.compile(r"\bengulfing\b|\bpin ?bar\b", re.IGNORECASE),
    re.compile(r"\bsession\b|\blondon\b|\bnew york\b|\bny\b|\bkillzone\b", re.IGNORECASE),
)
SL_TP_PATTERN = re.compile(r"\b(?:sl|stop loss|tp\d*|take profit|rr|risk reward|1:\d)\b", re.IGNORECASE)
TIMEFRAME_PATTERN = re.compile(r"\b(?:m1|m5|m15|m30|h1|h4|d1|w1|1m|5m|15m|30m|1h|4h)\b", re.IGNORECASE)
CONTEXT_PATTERN = re.compile(
    r"\b(?:context|bias|scenario|trend|session|london|new york|premium|discount|market structure|liquidity)\b",
    re.IGNORECASE,
)
STRATEGY_PATTERN = re.compile(
    r"\b(?:strategy|estrategia|setup|playbook|rules?|reglas?|model|modelo|framework|course|curso|lesson|module|clase)\b",
    re.IGNORECASE,
)
NOISE_PATTERN = re.compile(
    r"\b(?:vip|premium|promo|promocion|promoción|bonus|discount|descuento|broker|robot|ea|indicator|software|crack|installer|setup\.exe)\b",
    re.IGNORECASE,
)
EXECUTABLE_PATTERN = re.compile(r"\b(?:\.exe|\.msi|\.apk|\.dll)\b", re.IGNORECASE)

SUPPORTED_TEXT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md", ".csv", ".tsv"}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}
PRESENTATION_EXTENSIONS = {".ppt", ".pptx"}


@dataclass(slots=True)
class DocumentPriorityResult:
    """Scored prioritization row for a file asset."""

    file_id: int
    file_name: str
    category: str
    extension: str | None
    knowledge_density_score: float
    strategy_probability_score: float
    priority_score: float
    processable_now: bool
    reasons: list[str]


class KnowledgeDensityScorer:
    """Estimate how much rule-like trading knowledge a text contains."""

    @classmethod
    def score(cls, text: str) -> tuple[float, list[str]]:
        working = text or ""
        reasons: list[str] = []
        technical_hits = sum(len(pattern.findall(working)) for pattern in TECHNICAL_PATTERNS)
        technical_score = min(1.0, technical_hits / 10)
        if technical_hits:
            reasons.append(f"technical_terms:{technical_hits}")
        has_sl_tp = bool(SL_TP_PATTERN.search(working))
        if has_sl_tp:
            reasons.append("sl_tp_present")
        has_timeframe = bool(TIMEFRAME_PATTERN.search(working))
        if has_timeframe:
            reasons.append("timeframe_present")
        has_context = bool(CONTEXT_PATTERN.search(working))
        if has_context:
            reasons.append("context_present")
        score = technical_score * 0.5 + (0.2 if has_sl_tp else 0.0) + (0.15 if has_timeframe else 0.0) + (
            0.15 if has_context else 0.0
        )
        return round(min(1.0, score), 4), reasons


class DocumentPrioritizer:
    """Rank cataloged and processed files by likely value for strategy extraction."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.file_repository = FileRepository(session)

    def rank_documents(self, limit: int | None = None) -> list[DocumentPriorityResult]:
        assets = self.file_repository.list_prioritizable_documents()
        asset_by_id = {asset.id: asset for asset in assets}
        ranked = [self.score_file(asset) for asset in assets]
        ranked.sort(key=lambda item: (-item.priority_score, -item.knowledge_density_score, item.file_name.lower()))
        for item in ranked:
            self.file_repository.update_priority_scores(
                asset_by_id[item.file_id],
                knowledge_density_score=item.knowledge_density_score,
                strategy_probability_score=item.strategy_probability_score,
                priority_score=item.priority_score,
                priority_notes=json.dumps(item.reasons, ensure_ascii=False),
            )
        self.session.flush()
        return ranked[:limit] if limit is not None else ranked

    def top_processable_documents(self, limit: int = 5) -> list[FileAsset]:
        ranked = self.rank_documents()
        selected: list[FileAsset] = []
        for item in ranked:
            if not item.processable_now:
                continue
            file_asset = self.session.get(FileAsset, item.file_id)
            if file_asset is None:
                continue
            selected.append(file_asset)
            if len(selected) >= limit:
                break
        return selected

    def score_file(self, file_asset: FileAsset) -> DocumentPriorityResult:
        extension = (file_asset.extension or Path(file_asset.file_name).suffix).lower() or None
        text_basis = self._text_basis(file_asset)
        density_score, density_reasons = KnowledgeDensityScorer.score(text_basis)
        strategy_probability, strategy_reasons = self._strategy_probability(file_asset, text_basis, extension)
        size_score, size_reasons = self._size_usefulness(file_asset, extension)
        processable = self._processable_now(file_asset, extension)
        processable_bonus = 0.05 if processable else 0.0
        penalty = self._penalty(text_basis, extension)
        priority_score = min(
            1.0,
            max(
                0.0,
                density_score * 0.5 + strategy_probability * 0.35 + size_score * 0.1 + processable_bonus - penalty,
            ),
        )
        reasons = density_reasons + strategy_reasons + size_reasons
        if processable:
            reasons.append("processable_now")
        if penalty:
            reasons.append(f"penalty:{penalty:.2f}")
        return DocumentPriorityResult(
            file_id=file_asset.id,
            file_name=file_asset.file_name,
            category=file_asset.category,
            extension=extension,
            knowledge_density_score=round(density_score, 4),
            strategy_probability_score=round(strategy_probability, 4),
            priority_score=round(priority_score, 4),
            processable_now=processable,
            reasons=reasons,
        )

    @staticmethod
    def _text_basis(file_asset: FileAsset) -> str:
        parts = [file_asset.file_name or ""]
        if file_asset.message and file_asset.message.text:
            parts.append(file_asset.message.text)
        if file_asset.document and file_asset.document.summary:
            parts.append(file_asset.document.summary)
        if file_asset.document and file_asset.document.extracted_text:
            parts.append(file_asset.document.extracted_text[:4000])
        if file_asset.notes:
            parts.append(file_asset.notes[:1000])
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _strategy_probability(file_asset: FileAsset, text_basis: str, extension: str | None) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0
        strategy_hits = len(STRATEGY_PATTERN.findall(text_basis))
        if strategy_hits:
            score += min(0.35, strategy_hits * 0.07)
            reasons.append(f"strategy_terms:{strategy_hits}")
        if SL_TP_PATTERN.search(text_basis):
            score += 0.2
            reasons.append("contains_execution_levels")
        if TIMEFRAME_PATTERN.search(text_basis):
            score += 0.15
            reasons.append("contains_timeframes")
        if re.search(r"\b(?:risk|riesgo|session|london|new york|confirm|confirmation|entry|entrada)\b", text_basis, re.IGNORECASE):
            score += 0.1
            reasons.append("contains_operational_context")
        if extension in SUPPORTED_TEXT_EXTENSIONS or extension in PRESENTATION_EXTENSIONS:
            score += 0.12
            reasons.append("document_format")
        elif extension in ARCHIVE_EXTENSIONS:
            score += 0.04
            reasons.append("archive_metadata_only")
        return round(min(1.0, score), 4), reasons

    @staticmethod
    def _size_usefulness(file_asset: FileAsset, extension: str | None) -> tuple[float, list[str]]:
        reasons: list[str] = []
        if file_asset.size_bytes is None or file_asset.size_bytes <= 0:
            return 0.15, ["size_unknown"]
        size_mb = file_asset.size_bytes / (1024 * 1024)
        if extension in SUPPORTED_TEXT_EXTENSIONS or extension in PRESENTATION_EXTENSIONS:
            if 0.05 <= size_mb <= 50:
                return 0.3, [f"useful_size_mb:{size_mb:.2f}"]
            if size_mb < 0.05:
                return 0.05, [f"tiny_size_mb:{size_mb:.2f}"]
            return 0.18, [f"large_but_acceptable_mb:{size_mb:.2f}"]
        if extension in ARCHIVE_EXTENSIONS:
            if size_mb > 1024:
                return 0.02, [f"huge_archive_mb:{size_mb:.2f}"]
            return 0.08, [f"archive_mb:{size_mb:.2f}"]
        return 0.1, [f"generic_size_mb:{size_mb:.2f}"]

    @staticmethod
    def _penalty(text_basis: str, extension: str | None) -> float:
        penalty = 0.0
        noise_hits = len(NOISE_PATTERN.findall(text_basis))
        if noise_hits:
            penalty += min(0.25, noise_hits * 0.05)
        if EXECUTABLE_PATTERN.search(text_basis):
            penalty += 0.2
        if extension in ARCHIVE_EXTENSIONS:
            penalty += 0.05
        return penalty

    @staticmethod
    def _processable_now(file_asset: FileAsset, extension: str | None) -> bool:
        if extension not in SUPPORTED_TEXT_EXTENSIONS:
            return False
        if file_asset.document is not None:
            return False
        if not file_asset.stored_path:
            return False
        return Path(file_asset.stored_path).exists() and DocumentProcessor.is_supported(
            Path(file_asset.stored_path),
            file_asset.file_name,
        )
