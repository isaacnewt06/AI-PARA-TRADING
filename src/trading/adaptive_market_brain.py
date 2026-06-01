"""Adaptive market brain contracts for strategy selection.

This module does not execute trades. It scores strategy modules against a
market-regime snapshot and returns the best research candidate or WAIT.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MarketRegimeSnapshot:
    symbol: str
    primary_regime: str
    session: str
    volatility_bucket: str
    macro_status: str = "allow"
    spread_status: str = "normal"
    directional_bias: str = "neutral"
    structural_state: str | None = None
    confidence: float = 0.0


@dataclass(slots=True)
class StrategyModuleSpec:
    code: str
    label: str
    implementation_status: str
    research_verdict: str
    allowed_regimes: tuple[str, ...]
    blocked_regimes: tuple[str, ...]
    preferred_sessions: tuple[str, ...]
    allowed_sides: tuple[str, ...]
    risk_mode: str
    base_weight: int
    minimum_score_to_trade: int
    implementation_path: str | None = None
    evidence_path: str | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StrategyModuleSpec":
        return cls(
            code=str(payload["code"]),
            label=str(payload["label"]),
            implementation_status=str(payload["implementation_status"]),
            research_verdict=str(payload["research_verdict"]),
            allowed_regimes=tuple(payload.get("allowed_regimes") or ()),
            blocked_regimes=tuple(payload.get("blocked_regimes") or ()),
            preferred_sessions=tuple(payload.get("preferred_sessions") or ()),
            allowed_sides=tuple(payload.get("allowed_sides") or ()),
            risk_mode=str(payload["risk_mode"]),
            base_weight=int(payload.get("base_weight", 0)),
            minimum_score_to_trade=int(payload.get("minimum_score_to_trade", 100)),
            implementation_path=payload.get("implementation_path"),
            evidence_path=payload.get("evidence_path"),
            notes=str(payload.get("notes", "")),
        )


@dataclass(slots=True)
class StrategyEvaluation:
    strategy_code: str
    score: int
    action: str
    risk_mode: str
    reasons: tuple[str, ...]
    minimum_score_to_trade: int


@dataclass(slots=True)
class StrategySelection:
    selected_strategy: str
    action: str
    score: int
    risk_mode: str
    reason: str
    ranked: tuple[StrategyEvaluation, ...]


class AdaptiveStrategyLibrary:
    def __init__(self, *, strategies: list[StrategyModuleSpec], execution_enabled: bool = False) -> None:
        self.strategies = strategies
        self.execution_enabled = execution_enabled

    @classmethod
    def load(cls, path: Path) -> "AdaptiveStrategyLibrary":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            strategies=[StrategyModuleSpec.from_dict(item) for item in payload.get("strategies", [])],
            execution_enabled=bool(payload.get("execution_enabled", False)),
        )

    def by_code(self, code: str) -> StrategyModuleSpec | None:
        return next((item for item in self.strategies if item.code == code), None)


class AdaptiveStrategySelector:
    external_block_regimes = {"post_news_volatility", "no_trade", "spread_high"}

    def __init__(self, library: AdaptiveStrategyLibrary) -> None:
        self.library = library

    def evaluate_all(self, snapshot: MarketRegimeSnapshot) -> list[StrategyEvaluation]:
        evaluations = [self.evaluate_strategy(strategy, snapshot) for strategy in self.library.strategies]
        return sorted(evaluations, key=lambda item: item.score, reverse=True)

    def select(self, snapshot: MarketRegimeSnapshot) -> StrategySelection:
        ranked = self.evaluate_all(snapshot)
        no_trade = next((item for item in ranked if item.strategy_code == "no_trade_model"), None)
        if self._external_block_active(snapshot):
            fallback = no_trade or ranked[0]
            return StrategySelection(
                selected_strategy=fallback.strategy_code,
                action="BLOCKED",
                score=fallback.score,
                risk_mode="blocked",
                reason="External safety condition selected no-trade behavior.",
                ranked=tuple(ranked),
            )

        candidates = [item for item in ranked if item.strategy_code != "no_trade_model" and item.action == "SELECT"]
        if not candidates:
            fallback = no_trade or ranked[0]
            return StrategySelection(
                selected_strategy=fallback.strategy_code,
                action="WAIT",
                score=fallback.score,
                risk_mode="blocked",
                reason="No strategy exceeded its minimum score for this regime.",
                ranked=tuple(ranked),
            )
        best = candidates[0]
        return StrategySelection(
            selected_strategy=best.strategy_code,
            action="SELECT",
            score=best.score,
            risk_mode=best.risk_mode,
            reason="Highest-scoring strategy above threshold.",
            ranked=tuple(ranked),
        )

    def evaluate_strategy(self, strategy: StrategyModuleSpec, snapshot: MarketRegimeSnapshot) -> StrategyEvaluation:
        reasons: list[str] = []
        score = strategy.base_weight
        regime_tokens = {snapshot.primary_regime, snapshot.volatility_bucket}
        if snapshot.structural_state:
            regime_tokens.add(snapshot.structural_state)

        if strategy.code == "no_trade_model":
            return self._evaluate_no_trade(strategy, snapshot)

        if regime_tokens.intersection(strategy.blocked_regimes):
            return StrategyEvaluation(
                strategy_code=strategy.code,
                score=0,
                action="BLOCKED",
                risk_mode="blocked",
                reasons=("Regime is explicitly blocked for this strategy.",),
                minimum_score_to_trade=strategy.minimum_score_to_trade,
            )

        if regime_tokens.intersection(strategy.allowed_regimes):
            score += 30
            reasons.append("Regime matches strategy edge map.")
        else:
            score -= 25
            reasons.append("Regime does not match strategy edge map.")

        if strategy.preferred_sessions:
            if snapshot.session in strategy.preferred_sessions:
                score += 10
                reasons.append("Session is preferred.")
            else:
                score -= 10
                reasons.append("Session is not preferred.")

        if snapshot.directional_bias in {"buy", "sell"} and strategy.allowed_sides:
            if snapshot.directional_bias in strategy.allowed_sides:
                score += 8
                reasons.append("Directional bias is allowed.")
            else:
                score -= 12
                reasons.append("Directional bias conflicts with allowed sides.")

        score += int(max(0.0, min(snapshot.confidence, 1.0)) * 10)
        if "NEEDS" in strategy.research_verdict or "REQUIRES" in strategy.research_verdict:
            score -= 12
            reasons.append("Research verdict requires more validation.")
        if "not_implemented" in strategy.implementation_status:
            score -= 20
            reasons.append("Strategy is not implemented yet.")

        score = max(0, min(100, score))
        action = "SELECT" if score >= strategy.minimum_score_to_trade else "WAIT"
        return StrategyEvaluation(
            strategy_code=strategy.code,
            score=score,
            action=action,
            risk_mode=strategy.risk_mode if action == "SELECT" else "blocked",
            reasons=tuple(reasons),
            minimum_score_to_trade=strategy.minimum_score_to_trade,
        )

    def _evaluate_no_trade(self, strategy: StrategyModuleSpec, snapshot: MarketRegimeSnapshot) -> StrategyEvaluation:
        reasons = []
        score = strategy.base_weight
        if self._external_block_active(snapshot):
            score = 100
            reasons.append("External block active.")
        elif snapshot.primary_regime in strategy.allowed_regimes or snapshot.spread_status == "high":
            score = 90
            reasons.append("Market state maps to no-trade.")
        else:
            score = 15
            reasons.append("No-trade is fallback only.")
        return StrategyEvaluation(
            strategy_code=strategy.code,
            score=score,
            action="SELECT" if score >= 80 else "WAIT",
            risk_mode="blocked",
            reasons=tuple(reasons),
            minimum_score_to_trade=strategy.minimum_score_to_trade,
        )

    def _external_block_active(self, snapshot: MarketRegimeSnapshot) -> bool:
        return (
            snapshot.macro_status != "allow"
            or snapshot.spread_status == "high"
            or snapshot.primary_regime in self.external_block_regimes
        )

