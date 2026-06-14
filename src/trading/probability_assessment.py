"""Probability assessment based on historical pattern similarity."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PatternProbabilityAssessor:
    """Calculate win probability from similar historical trades."""

    def __init__(self) -> None:
        self.best_patterns_path = Path("data/demo_trading/maximo_quant_v4/best_trades_memory.jsonl")
        self.worst_patterns_path = Path("data/demo_trading/maximo_quant_v4/worst_trades_memory.jsonl")
        self._best_patterns: list[dict[str, Any]] = []
        self._worst_patterns: list[dict[str, Any]] = []
        self._load_patterns()

    def _load_patterns(self) -> None:
        """Load historical pattern memory."""
        if self.best_patterns_path.exists():
            self._best_patterns = [json.loads(line) for line in self.best_patterns_path.read_text().strip().splitlines()]
        if self.worst_patterns_path.exists():
            self._worst_patterns = [json.loads(line) for line in self.worst_patterns_path.read_text().strip().splitlines()]

    def assess_probability(self, *, signal: dict[str, Any], intelligence: dict[str, Any]) -> dict[str, Any]:
        """Calculate probability score based on pattern similarity."""
        overview = intelligence.get("overview", {}) or {}
        market_state = overview.get("market_state", {}) or {}

        # Features from real memory fields
        features = {
            "pulse_score": self._safe_float(market_state.get("pulse_score", 50), 50),
            "final_confirmation": self._safe_float(market_state.get("clarity_score", 50), 50),
            "rr": self._safe_float(signal.get("selected_rr", 1.5), 1.5),
            "side": str(signal.get("direction", "BUY")).upper(),
        }

        # Calculate similarity scores
        best_similarity, worst_similarity = 0.0, 0.0

        for pattern in self._best_patterns[:20]:
            sim = self._calculate_similarity(features, pattern)
            best_similarity = max(best_similarity, sim)

        for pattern in self._worst_patterns[:10]:
            sim = self._calculate_similarity(features, pattern)
            worst_similarity = max(worst_similarity, sim)

        # Probability = weighted combination
        prob = min(0.95, max(0.40, 0.48 + 0.30 * best_similarity - 0.10 * worst_similarity))
        confidence = 0.50 + 0.45 * (best_similarity + worst_similarity)

        return {
            "win_probability": round(prob, 3),
            "confidence": round(min(0.95, confidence), 3),
            "best_similarity": round(best_similarity, 3),
            "worst_similarity": round(worst_similarity, 3),
            "should_execute": prob >= 0.50 and confidence >= 0.55,
        }

    def _calculate_similarity(self, features: dict[str, Any], pattern: dict[str, Any]) -> float:
        """Calculate feature similarity (0-1)."""
        if not pattern:
            return 0.0
        total = 0.0
        count = 0

        # Pulse similarity
        pulse = self._safe_float(features.get("pulse_score", 50), 50)
        pattern_pulse = self._safe_float(pattern.get("market_pulse", 50), 50)
        pulse_sim = 1.0 - min(1.0, abs(pulse - pattern_pulse) / 100.0)
        total += pulse_sim
        count += 1

        # Confirmation similarity
        conf = self._safe_float(features.get("final_confirmation", 50), 50)
        pattern_conf = self._safe_float(pattern.get("final_confirmation", 50), 50)
        conf_sim = 1.0 - min(1.0, abs(conf - pattern_conf) / 100.0)
        total += conf_sim
        count += 1

        # Side match
        side = features.get("side", "BUY")
        pattern_side = pattern.get("side", "BUY")
        side_sim = 1.0 if side == pattern_side else 0.0
        total += side_sim
        count += 1

        # RR factor
        rr = self._safe_float(features.get("rr", 1.5), 1.5)
        pattern_rr = self._safe_float(pattern.get("final_R", 1.5), 1.5)
        rr_sim = 1.0 - min(1.0, abs(rr - pattern_rr) / 2.0)
        total += rr_sim
        count += 1

        return total / count if count > 0 else 0.0

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default


def get_probability_overlay(engine_result: dict[str, Any], prob_result: dict[str, Any]) -> dict[str, Any]:
    """Merge probability assessment with execution engine result."""
    merged = dict(engine_result)
    merged["probability"] = prob_result
    if engine_result.get("can_execute") and prob_result.get("should_execute"):
        merged["enhanced_decision"] = "EXECUTE_PROBABLE"
        merged["confidence_tier"] = "HIGH" if prob_result["confidence"] >= 0.75 else "MEDIUM"
    return merged