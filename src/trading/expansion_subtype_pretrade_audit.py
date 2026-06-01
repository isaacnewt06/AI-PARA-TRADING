"""Passive pre-trade expansion subtype telemetry.

This module is intentionally decision-neutral. It classifies a narrow research
context for dry-run telemetry only and must not execute, block, resize, or alter
live trading behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FAVORABLE_RESEARCH = {"compressed_release_expansion", "liquidity_sweep_expansion"}
AVOID_RESEARCH = {"trend_acceleration_expansion", "rotational_expansion"}


@dataclass(frozen=True, slots=True)
class ExpansionSubtypePretradeAuditV1:
    """Classify NY_AM SELL m5_body_mid_5m research candidates using pre-entry data."""

    rule_name: str = "m5_body_mid_5m"
    audit_name: str = "EXPANSION_SUBTYPE_PRETRADE_AUDIT_V1"

    def from_market_state(self, market_state: dict[str, Any]) -> dict[str, Any]:
        candidate = self._candidate_from_market_state(market_state)
        if not candidate["candidate_detected"]:
            return {
                **candidate,
                "audit_name": self.audit_name,
                "rule": self.rule_name,
                "subtype": None,
                "subtype_confidence": 0.0,
                "subtype_reason": candidate["reason"],
                "expected_edge_bucket": "not_applicable",
                "historical_warning": "No NY_AM SELL m5_body_mid_5m research candidate detected.",
                "lookahead_safe": True,
                "future_variables_used": [],
            }
        subtype, confidence, reason = self.classify(candidate["features"])
        return {
            **candidate,
            "audit_name": self.audit_name,
            "rule": self.rule_name,
            "subtype": subtype,
            "subtype_confidence": confidence,
            "subtype_reason": reason,
            "expected_edge_bucket": self.expected_edge_bucket(subtype),
            "historical_warning": self.historical_warning(subtype),
            "lookahead_safe": True,
            "future_variables_used": [],
        }

    def classify(self, features: dict[str, Any]) -> tuple[str, float, str]:
        atr_bucket = str(features.get("atr_bucket") or "UNKNOWN")
        expansion_subtype = str(features.get("expansion_subtype") or "UNKNOWN")
        continuation_quality = str(features.get("continuation_quality") or "UNKNOWN")
        atr_ratio = _float(features.get("atr_ratio"))
        range_ratio = _float(features.get("range_ratio"))
        body_pct = _float(features.get("body_pct"))
        wick_rejection_pct = _float(features.get("wick_rejection_pct"))
        confidence = _float(features.get("confidence"))

        if atr_bucket == "extreme_atr" and wick_rejection_pct >= 70.0:
            return (
                "liquidity_sweep_expansion",
                _confidence_from_margins([wick_rejection_pct - 70.0, atr_ratio - 1.45]),
                "Extreme ATR with very large upper-wick rejection before entry.",
            )
        if continuation_quality == "strong" and range_ratio <= 1.15:
            return (
                "compressed_release_expansion",
                _confidence_from_margins([1.15 - range_ratio, confidence - 70.0]),
                "Strong pre-entry continuation quality while range remains controlled/compressed.",
            )
        if expansion_subtype == "clean_expansion" and body_pct >= 28.0 and wick_rejection_pct <= 50.0:
            return (
                "trend_acceleration_expansion",
                _confidence_from_margins([body_pct - 28.0, 50.0 - wick_rejection_pct]),
                "Clean expansion with large body and weaker rejection; historically vulnerable for this SELL setup.",
            )
        if continuation_quality == "weak" and range_ratio >= 1.45:
            return (
                "rotational_expansion",
                _confidence_from_margins([range_ratio - 1.45, 1.45 - min(atr_ratio, 1.45)]),
                "Weak continuation quality with wide range behavior before entry; likely rotation/chop expansion.",
            )
        return (
            "other",
            0.55,
            "Pre-entry features do not match validated favorable or avoid research buckets.",
        )

    @staticmethod
    def expected_edge_bucket(subtype: str) -> str:
        if subtype in FAVORABLE_RESEARCH:
            return "favorable_research"
        if subtype in AVOID_RESEARCH:
            return "avoid_research"
        return "unknown_research"

    @staticmethod
    def historical_warning(subtype: str) -> str:
        if subtype == "compressed_release_expansion":
            return "Research-positive but sample is small; telemetry only, not execution approval."
        if subtype == "liquidity_sweep_expansion":
            return "Research-positive sweep-like expansion; sample is small and must remain telemetry-only."
        if subtype == "trend_acceleration_expansion":
            return "Avoid research bucket; this subtype contained the largest 2025 loss."
        if subtype == "rotational_expansion":
            return "Avoid research bucket; weak continuation and rotation diluted edge."
        return "No reliable historical edge bucket yet."

    @staticmethod
    def _candidate_from_market_state(market_state: dict[str, Any]) -> dict[str, Any]:
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        aggressive_side = str(aggressive.get("side") or "").upper()
        preferred_side = str(market_state.get("preferred_side") or "").upper()
        hour_ny = market_state.get("hour_ny")
        session_tags = {str(item).lower() for item in market_state.get("session_tags", []) or []}
        candidate_setups = market_state.get("candidate_setups", {}) or {}
        side_ok = aggressive_side == "SELL" or preferred_side == "SELL" or bool(candidate_setups.get("sell_agg"))
        session_ok = hour_ny == 9 or "ny_am" in session_tags
        feature_keys = {
            "atr_ratio",
            "range_ratio",
            "body_pct",
            "wick_rejection_pct_sell",
            "expansion_subtype",
            "continuation_quality_sell",
            "atr_bucket",
            "sell_mtf_score",
            "impulse_score",
        }
        features_available = all(key in market_state for key in feature_keys)
        candidate_detected = bool(side_ok and session_ok and features_available)
        reason = "NY_AM SELL m5_body_mid_5m telemetry candidate detected." if candidate_detected else (
            "No matching NY_AM SELL m5_body_mid_5m telemetry candidate in current dry-run state."
        )
        features = {
            "side": "SELL",
            "session": "ny_am" if session_ok else None,
            "hour_ny": hour_ny,
            "expansion_subtype": market_state.get("expansion_subtype"),
            "continuation_quality": market_state.get("continuation_quality_sell"),
            "atr_bucket": market_state.get("atr_bucket"),
            "atr_ratio": market_state.get("atr_ratio"),
            "range_ratio": market_state.get("range_ratio"),
            "body_pct": market_state.get("body_pct"),
            "wick_rejection_pct": market_state.get("wick_rejection_pct_sell"),
            "confidence": market_state.get("sell_mtf_score"),
            "mtf_score": market_state.get("sell_mtf_score"),
            "impulse_score": market_state.get("impulse_score"),
            "compression_ok": market_state.get("compression_ok"),
            "micro_bos": (aggressive.get("checks") or {}).get("micro_bos_sell"),
            "continuation_momentum": (aggressive.get("checks") or {}).get("continuation_momentum_sell"),
        }
        return {
            "candidate_detected": candidate_detected,
            "candidate_scope": "NY_AM_SELL_m5_body_mid_5m",
            "reason": reason,
            "features": features,
        }


def _confidence_from_margins(margins: list[float]) -> float:
    positive_margin = sum(max(0.0, item) for item in margins)
    confidence = 0.62 + min(0.30, positive_margin / 80.0)
    return round(min(0.92, max(0.50, confidence)), 4)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
