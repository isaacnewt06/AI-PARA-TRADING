"""Heuristic classifier for trading-related content."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ClassificationResult:
    """Classification result with label and rationale."""

    label: str
    confidence: float


class HeuristicContentClassifier:
    """Rule-based classifier to keep Fase 1 deterministic."""

    RULES = {
        "signal": ("buy", "sell", "entry", "sl", "tp", "take profit", "stop loss"),
        "gestion_riesgo": ("risk", "riesgo", "%", "capital", "lot size", "drawdown"),
        "psicologia": ("mindset", "psicologia", "disciplina", "emociones", "patience"),
        "comentario_mercado": ("market", "cpi", "fomc", "news", "analysis", "sesion"),
        "educativo": ("lesson", "curso", "module", "concept", "explicacion", "setup"),
        "propaganda_promocion": ("vip", "promo", "join", "discount", "telegram", "suscribete"),
        "resultado_post_trade": ("resultado", "closed", "profit", "ganancia", "loss", "winrate"),
    }

    def classify(self, text: str | None) -> ClassificationResult:
        normalized = (text or "").lower()
        if not normalized:
            return ClassificationResult(label="otro", confidence=0.0)

        best_label = "otro"
        best_score = 0
        for label, keywords in self.RULES.items():
            score = sum(1 for keyword in keywords if keyword in normalized)
            if score > best_score:
                best_label = label
                best_score = score

        confidence = min(0.99, 0.15 * best_score) if best_score else 0.1
        return ClassificationResult(label=best_label, confidence=confidence)
