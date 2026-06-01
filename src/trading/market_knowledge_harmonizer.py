"""Knowledge harmony and conflict analysis for market decision orchestration."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class MarketKnowledgeHarmonizer:
    """Reconcile learned strategy knowledge with live market context."""

    def analyze(
        self,
        *,
        market_state: dict[str, Any],
        contexts: list[dict[str, Any]],
        non_operable_situations: list[dict[str, Any]],
        signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        family_support = self._family_support(contexts)
        top_family = family_support[0]["strategy_family"] if family_support else None
        top_family_share = family_support[0]["share"] if family_support else 0.0
        current_regime = str(market_state.get("market_regime", "NORMAL")).lower()
        current_sessions = set(market_state.get("session_tags", []))
        preferred_side = str(market_state.get("preferred_side", "NEUTRAL")).lower()

        operable_count = sum(1 for item in contexts if item.get("operability_label") == "operable")
        confirm_count = sum(1 for item in contexts if item.get("operability_label") == "needs_confirmation")
        research_count = sum(1 for item in contexts if item.get("operability_label") == "research_only")

        alignment_bonus = 0.0
        if signal is not None and top_family in {"OB Rejection", "Breakout Retest", "Trend Pullback", "Session Expansion"}:
            alignment_bonus += 0.08
        if market_state.get("preferred_side") in {"BUY", "SELL"}:
            alignment_bonus += 0.05
        if market_state.get("allowed_hour_by_strategy"):
            alignment_bonus += 0.04

        label_weight = (
            operable_count * 1.0
            + confirm_count * 0.85
            + research_count * 0.15
        ) / max(1, len(contexts))
        top_context_score = max((float(item.get("score") or 0.0) for item in contexts[:3]), default=0.0)
        family_consensus = self._family_consensus(family_support)
        conflict_flags = self._conflict_flags(
            market_state=market_state,
            non_operable_situations=non_operable_situations,
            contexts=contexts,
        )
        conflict_penalty = min(0.45, 0.09 * len(conflict_flags))
        concentration_penalty = 0.08 if top_family_share >= 0.78 and len(family_support) <= 1 else 0.0

        harmony_score = round(
            max(
                0.0,
                min(
                    1.0,
                    top_context_score * 0.38
                    + label_weight * 0.26
                    + family_consensus * 0.18
                    + alignment_bonus
                    - conflict_penalty
                    - concentration_penalty,
                ),
            ),
            4,
        )

        posture = "defensive"
        if harmony_score >= 0.6 and (operable_count > 0 or confirm_count > 0) and not conflict_flags:
            posture = "aligned"
        elif harmony_score >= 0.35:
            posture = "selective"

        narrative = [
            f"La familia dominante en este contexto es {top_family or 'ninguna'}.",
            f"El régimen actual {current_regime} encaja con {operable_count} contextos operables y {confirm_count} contextos que aún piden confirmación.",
        ]
        if current_sessions:
            narrative.append(f"La sesión activa reconocida es {', '.join(sorted(current_sessions))}.")
        if preferred_side in {"buy", "sell"}:
            narrative.append(f"El sesgo preferido del mercado apunta a {preferred_side.upper()}.")
        if conflict_flags:
            narrative.append(f"Se detectaron fricciones de contexto: {', '.join(conflict_flags)}.")

        return {
            "harmony_score": harmony_score,
            "operating_posture": posture,
            "dominant_family": top_family,
            "dominant_family_share": top_family_share,
            "family_support": family_support[:5],
            "family_consensus": family_consensus,
            "operable_contexts": operable_count,
            "needs_confirmation_contexts": confirm_count,
            "research_only_contexts": research_count,
            "conflict_flags": conflict_flags,
            "narrative": narrative,
        }

    @staticmethod
    def _family_support(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        totals: dict[str, float] = defaultdict(float)
        for item in contexts:
            family = str(item.get("strategy_family") or "Unknown")
            totals[family] += float(item.get("score") or 0.0)
        total_score = sum(totals.values())
        rows = []
        for family, score in totals.items():
            share = round(score / total_score, 4) if total_score > 0 else 0.0
            rows.append({"strategy_family": family, "score": round(score, 4), "share": share})
        rows.sort(key=lambda item: item["score"], reverse=True)
        return rows

    @staticmethod
    def _family_consensus(family_support: list[dict[str, Any]]) -> float:
        if not family_support:
            return 0.0
        if len(family_support) == 1:
            return min(1.0, 0.55 + family_support[0]["share"] * 0.45)
        gap = family_support[0]["share"] - family_support[1]["share"]
        return round(max(0.0, min(1.0, 0.5 + gap)), 4)

    @staticmethod
    def _conflict_flags(
        *,
        market_state: dict[str, Any],
        non_operable_situations: list[dict[str, Any]],
        contexts: list[dict[str, Any]],
    ) -> list[str]:
        flags: list[str] = []
        regime = str(market_state.get("market_regime", "")).upper()
        volatility_state = str(market_state.get("volatility_state", "")).lower()
        preferred_side = str(market_state.get("preferred_side", "NEUTRAL")).upper()
        if regime == "CHOP":
            flags.append("chop_regime")
        if volatility_state in {"extreme", "overextended"}:
            flags.append("overextended_volatility")
        if preferred_side == "NEUTRAL":
            flags.append("neutral_direction")

        labels = {str(item.get("label")) for item in non_operable_situations}
        if "choppy_or_range" in labels and regime == "CHOP":
            flags.append("knowledge_warns_chop")
        if "outside_session" in labels and not market_state.get("session_tags"):
            flags.append("outside_tracked_session")
        return sorted(set(flags))
