"""Exit quality evaluation for MAXIMO post-entry management."""

from __future__ import annotations

from typing import Any


class ExitQualityEvaluator:
    """Score whether exits/protection actions matched the trade lifecycle."""

    def evaluate(self, *, position_management: dict[str, Any]) -> dict[str, Any]:
        actions = list(position_management.get("actions", []) or [])
        feedback = position_management.get("feedback", {}) or {}
        if not actions and position_management.get("positions_managed", 0) == 0:
            return {
                "status": "inactive",
                "exit_quality_score": None,
                "exit_lesson": "No open/managed position this cycle.",
                "q_learning_feedback_adjustment": 0.0,
            }

        max_mfe = self._safe_float(feedback.get("max_mfe_r"))
        gave_back = bool(feedback.get("gave_back_profit"))
        be_applied = bool(feedback.get("be_applied"))
        partial_taken = bool(feedback.get("partial_taken"))
        trailing_applied = bool(feedback.get("trailing_applied"))
        fast_exit_taken = bool(feedback.get("fast_exit_taken"))
        momentum_decay = bool(feedback.get("momentum_decay_detected"))

        score = 62.0
        lessons: list[str] = []
        if max_mfe >= 0.5 and not (be_applied or partial_taken or trailing_applied or fast_exit_taken):
            score -= 28.0
            lessons.append("Trade superó +0.5R sin protección visible; reforzar BE/parcial/fallback.")
        if gave_back:
            score -= 18.0
            lessons.append("Hubo devolución de ganancia; vigilar momentum decay y trailing.")
        if momentum_decay and fast_exit_taken:
            score += 16.0
            lessons.append("Fast Exit respondió a pérdida de momentum.")
        elif momentum_decay and not fast_exit_taken:
            score -= 16.0
            lessons.append("Momentum decay detectado sin salida rápida.")
        if be_applied:
            score += 10.0
            lessons.append("Break-even aplicado.")
        if partial_taken:
            score += 8.0
            lessons.append("Parcial aplicado.")
        if trailing_applied:
            score += 8.0
            lessons.append("Trailing aplicado.")
        if fast_exit_taken and max_mfe < 0.25:
            score -= 8.0
            lessons.append("Fast Exit pudo ser temprano; revisar si evitó pérdida mayor.")
        score = round(max(0.0, min(100.0, score)), 2)
        adjustment = round((score - 60.0) / 100.0, 4)
        return {
            "status": "evaluated",
            "exit_quality_score": score,
            "classification": self._classification(score),
            "be_applied": be_applied,
            "partial_taken": partial_taken,
            "trailing_applied": trailing_applied,
            "fast_exit_taken": fast_exit_taken,
            "momentum_decay_detected": momentum_decay,
            "gave_back_profit": gave_back,
            "exit_lesson": " ".join(lessons) if lessons else "Gestión sin anomalías fuertes en este ciclo.",
            "q_learning_feedback_adjustment": adjustment,
        }

    @staticmethod
    def _classification(score: float) -> str:
        if score >= 80:
            return "excellent_exit_management"
        if score >= 65:
            return "acceptable_exit_management"
        if score >= 45:
            return "needs_improvement"
        return "poor_exit_management"

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
