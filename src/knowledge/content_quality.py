"""Quality filtering for knowledge chunks before embeddings and rule extraction."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.knowledge import ChunkEmbedding, ContentChunk
from src.db.repositories.knowledge import RuleRepository

logger = get_logger(__name__)


@dataclass(slots=True)
class ContentQualityResult:
    """Scoring result for a content chunk."""

    quality_score: float
    source_weight: float
    usefulness_score: float
    quality_label: str
    filtered_out: bool
    flags: list[str] = field(default_factory=list)


class ContentQualityFilter:
    """Heuristic quality gate for trading knowledge content.

    The filter is intentionally local and deterministic. It favors chunks with
    explicit trading structure and penalizes promotional, empty, generic or
    repeated material before expensive downstream stages consume it.
    """

    min_usefulness_score = 0.42
    near_duplicate_threshold = 0.92

    spam_patterns = (
        r"\b(vip|premium|señales\s+vip|grupo\s+vip|curso\s+gratis|prom[oó]ci[oó]n|descuento)\b",
        r"\b(whatsapp|telegram\s+premium|cont[aá]ctame|suscr[ií]bete|link\s+en|dm|inbox)\b",
        r"\b(bono|referral|referido|affiliate|afiliado|cup[oó]n|oferta|limited\s+time)\b",
        r"https?://|t\.me/|wa\.me/",
    )
    strategy_patterns = (
        r"\b(estrategia|strategy|setup|playbook|modelo|regla|rules?)\b",
        r"\b(entrada|entry|confirmaci[oó]n|confirmation|gatillo|trigger)\b",
        r"\b(stop\s*loss|sl\b|take\s*profit|tp\d*\b|risk|riesgo|r:r|rr)\b",
        r"\b(timeframe|temporalidad|m1|m5|m15|m30|h1|h4|d1)\b",
        r"\b(backtest|ejemplo|case study|operaci[oó]n real|trade example)\b",
    )
    concept_patterns = (
        r"\b(bos|break of structure|choch|change of character)\b",
        r"\b(fvg|fair value gap|imbalance|order block|ob\b)\b",
        r"\b(liquidity|liquidez|sweep|barrido|equal highs|equal lows)\b",
        r"\b(market structure|estructura de mercado|premium|discount)\b",
        r"\b(london|new york|ny session|killzone|sesion|sesi[oó]n)\b",
    )
    generic_patterns = (
        r"\b(motivaci[oó]n|mentalidad|disciplina|constancia|nunca te rindas)\b",
        r"\b(el trading es dif[ií]cil|cree en ti|libertad financiera)\b",
        r"\b(frase|reflexi[oó]n|inspiraci[oó]n)\b",
    )

    def __init__(self, session: Session) -> None:
        self.session = session
        self.rule_repository = RuleRepository(session) if session is not None else None

    def run(self) -> dict[str, int]:
        chunks = list(self.session.scalars(select(ContentChunk).order_by(ContentChunk.id.asc())))
        seen_signatures: dict[str, int] = {}
        kept_fingerprints: list[set[str]] = []
        updated = filtered = duplicates = 0
        for chunk in chunks:
            result = self.score_chunk(chunk, seen_signatures=seen_signatures, kept_fingerprints=kept_fingerprints)
            chunk.quality_score = result.quality_score
            chunk.source_weight = result.source_weight
            chunk.usefulness_score = result.usefulness_score
            chunk.quality_label = result.quality_label
            chunk.quality_flags_json = json.dumps(result.flags, ensure_ascii=False)
            chunk.filtered_out = result.filtered_out
            if result.filtered_out:
                chunk.embedding_status = "filtered"
                chunk.embedding_provider = None
                self._purge_downstream_artifacts(chunk.id)
                filtered += 1
            if "semantic_duplicate" in result.flags or "exact_duplicate" in result.flags:
                duplicates += 1
            self.session.add(chunk)
            updated += 1
        self.session.flush()
        logger.info("Quality-filtered %s chunks: kept=%s filtered=%s duplicates=%s", updated, updated - filtered, filtered, duplicates)
        return {"chunks_scored": updated, "chunks_kept": updated - filtered, "chunks_filtered": filtered, "duplicates": duplicates}

    def _purge_downstream_artifacts(self, chunk_id: int) -> None:
        """Remove artifacts derived from content that no longer passes the quality gate."""

        if self.session is None or self.rule_repository is None:
            return
        self.session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id == chunk_id))
        self.rule_repository.delete_for_chunk(chunk_id)

    def score_chunk(
        self,
        chunk: ContentChunk,
        *,
        seen_signatures: dict[str, int] | None = None,
        kept_fingerprints: list[set[str]] | None = None,
    ) -> ContentQualityResult:
        text = self._normalize_text(chunk.clean_text or chunk.text or "")
        flags: list[str] = []
        preservation_chunk = self._is_knowledge_preservation_chunk(chunk)
        if not text or len(text) < 80:
            flags.append("empty_or_too_short")
            if not preservation_chunk:
                return ContentQualityResult(0.0, 0.2, 0.0, "reject_empty", True, flags)

        tokens = self._tokens(text)
        if len(tokens) < 18:
            flags.append("low_information_density")

        signature = self._signature(text)
        if seen_signatures is not None:
            if signature in seen_signatures:
                flags.append("exact_duplicate")
            else:
                seen_signatures[signature] = chunk.id

        fingerprint = set(tokens)
        if kept_fingerprints is not None and self._is_near_duplicate(fingerprint, kept_fingerprints):
            flags.append("semantic_duplicate")

        spam_score = self._pattern_score(text, self.spam_patterns)
        structure_score = self._pattern_score(text, self.strategy_patterns)
        concept_score = self._pattern_score(text, self.concept_patterns)
        generic_score = self._pattern_score(text, self.generic_patterns)
        numeric_score = self._numeric_structure_score(text)

        if spam_score >= 0.35:
            flags.append("promotion_or_spam")
        if structure_score >= 0.35:
            flags.append("strategy_structure")
        if concept_score >= 0.25:
            flags.append("trading_concepts")
        if numeric_score >= 0.2:
            flags.append("concrete_examples")
        if generic_score >= 0.25:
            flags.append("generic_or_motivational")
        if preservation_chunk:
            flags.append("knowledge_preservation")

        quality_score = self._clamp(
            0.34
            + 0.26 * structure_score
            + 0.2 * concept_score
            + 0.16 * numeric_score
            - 0.28 * spam_score
            - 0.12 * generic_score
            - (0.22 if "semantic_duplicate" in flags else 0.0)
            - (0.35 if "exact_duplicate" in flags else 0.0)
            - (0.12 if "low_information_density" in flags and not preservation_chunk else 0.0)
            + (0.12 if preservation_chunk else 0.0)
        )
        source_weight = self._clamp(
            0.8
            + 0.45 * structure_score
            + 0.35 * concept_score
            + 0.25 * numeric_score
            - 0.35 * spam_score
            - 0.18 * generic_score,
            minimum=0.1,
            maximum=1.8,
        )
        usefulness_score = self._clamp((quality_score * 0.62) + ((source_weight / 1.8) * 0.38))

        filtered_out = (
            usefulness_score < self.min_usefulness_score
            or spam_score >= 0.65
            or "exact_duplicate" in flags
            or "semantic_duplicate" in flags
        )
        if preservation_chunk and spam_score < 0.65 and "exact_duplicate" not in flags and "semantic_duplicate" not in flags:
            filtered_out = False
        if not filtered_out and kept_fingerprints is not None:
            kept_fingerprints.append(fingerprint)

        label = self._label(usefulness_score, filtered_out, flags)
        return ContentQualityResult(
            quality_score=round(quality_score, 4),
            source_weight=round(source_weight, 4),
            usefulness_score=round(usefulness_score, 4),
            quality_label=label,
            filtered_out=filtered_out,
            flags=flags,
        )

    @classmethod
    def _pattern_score(cls, text: str, patterns: tuple[str, ...]) -> float:
        matches = sum(1 for pattern in patterns if re.search(pattern, text, re.IGNORECASE))
        return cls._clamp(matches / max(len(patterns), 1))

    @staticmethod
    def _numeric_structure_score(text: str) -> float:
        score = 0.0
        if re.search(r"\b(?:entry|entrada|@)\s*[:\-]?\s*\d", text, re.IGNORECASE):
            score += 0.25
        if re.search(r"\b(?:sl|stop\s*loss|s/l)\b", text, re.IGNORECASE):
            score += 0.25
        if re.search(r"\b(?:tp\d*|take\s*profit)\b", text, re.IGNORECASE):
            score += 0.25
        if re.search(r"\b\d+(?:\.\d+)?\s*%|\b1\s*:\s*\d|\b\d\s*r\b", text, re.IGNORECASE):
            score += 0.25
        return min(score, 1.0)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip().lower()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        stopwords = {"the", "and", "para", "con", "que", "los", "las", "una", "por", "del", "from", "this"}
        return [token for token in re.findall(r"[a-záéíóúñ0-9_]{3,}", text.lower()) if token not in stopwords]

    @classmethod
    def _signature(cls, text: str) -> str:
        normalized = " ".join(cls._tokens(text))
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def _is_near_duplicate(cls, fingerprint: set[str], kept_fingerprints: list[set[str]]) -> bool:
        if not fingerprint:
            return False
        for previous in kept_fingerprints[-500:]:
            union = len(fingerprint | previous)
            if union == 0:
                continue
            if len(fingerprint & previous) / union >= cls.near_duplicate_threshold:
                return True
        return False

    @staticmethod
    def _label(usefulness_score: float, filtered_out: bool, flags: list[str]) -> str:
        if filtered_out and "promotion_or_spam" in flags:
            return "reject_spam"
        if filtered_out and ("exact_duplicate" in flags or "semantic_duplicate" in flags):
            return "reject_duplicate"
        if filtered_out:
            return "reject_low_value"
        if "knowledge_preservation" in flags and usefulness_score < 0.55:
            return "catalog_preserved"
        if usefulness_score >= 0.75:
            return "high_value"
        if usefulness_score >= 0.55:
            return "useful"
        return "low_confidence_keep"

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, value))

    @staticmethod
    def _is_knowledge_preservation_chunk(chunk: ContentChunk) -> bool:
        if chunk.source_type in {"cataloged_file", "external_resource"}:
            return True
        if not chunk.metadata_json:
            return False
        try:
            return bool(json.loads(chunk.metadata_json).get("knowledge_preservation"))
        except json.JSONDecodeError:
            return False
