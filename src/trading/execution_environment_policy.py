"""Symbol-aware execution environment policy.

The broker execution guard should protect entries from bad costs without using
one universal spread threshold for every instrument. Gold symbols such as
XAUUSDm usually carry a wider structural spread than major FX pairs, so the
policy calibrates limits by symbol while keeping latency and hard-cost guards.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionEnvironmentLimits:
    max_spread: float
    preferred_spread: float
    hard_spread: float
    max_slippage: float
    max_latency: float = 0.20
    profile: str = "default"


@dataclass(frozen=True, slots=True)
class ExecutionEnvironmentEvaluation:
    execution_viability: str
    cost_quality: str
    limits: ExecutionEnvironmentLimits
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict:
        return {
            "execution_viability": self.execution_viability,
            "execution_cost_quality": self.cost_quality,
            "execution_policy_profile": self.limits.profile,
            "max_spread_allowed": self.limits.max_spread,
            "preferred_spread": self.limits.preferred_spread,
            "hard_spread_limit": self.limits.hard_spread,
            "max_slippage_allowed": self.limits.max_slippage,
            "max_latency_allowed": self.limits.max_latency,
            "execution_environment_blockers": list(self.blockers),
            "execution_environment_warnings": list(self.warnings),
            "execution_environment_reason": self.reason,
        }


def limits_for_symbol(symbol: str | None) -> ExecutionEnvironmentLimits:
    """Return calibrated execution limits for a broker symbol."""
    normalized = str(symbol or "").upper()
    compact = normalized.replace(".", "").replace("_", "").replace("-", "")
    if compact.startswith("XAUUSD") or "GOLD" in compact:
        return ExecutionEnvironmentLimits(
            max_spread=0.35,
            preferred_spread=0.33,
            hard_spread=0.40,
            max_slippage=0.35,
            profile="xauusd_adaptive_exness_demo",
        )
    return ExecutionEnvironmentLimits(
        max_spread=0.15,
        preferred_spread=0.12,
        hard_spread=0.20,
        max_slippage=0.20,
        profile="default_fx_strict",
    )


def evaluate_execution_environment(
    *,
    symbol: str | None,
    spread: float | None,
    latency: float | None,
    slippage: float | None = None,
) -> ExecutionEnvironmentEvaluation:
    """Evaluate whether execution costs are safe enough for demo-realistic mode."""
    limits = limits_for_symbol(symbol)
    blockers: list[str] = []
    warnings: list[str] = []

    if spread is None:
        blockers.append("live_spread_unavailable")
    elif spread > limits.hard_spread:
        blockers.append("spread_above_hard_execution_limit")
    elif spread > limits.max_spread:
        blockers.append("spread_above_adaptive_execution_limit")
    elif spread > limits.preferred_spread:
        warnings.append("spread_above_preferred_execution_band")

    if slippage is None:
        warnings.append("slippage_estimate_unavailable")
    elif slippage > limits.max_slippage:
        blockers.append("slippage_above_adaptive_execution_limit")

    if latency is None:
        blockers.append("latency_unavailable")
    elif latency > limits.max_latency:
        blockers.append("latency_unsafe")

    if blockers:
        viability = "UNSAFE"
        cost_quality = "blocked"
        reason = "Execution environment blocked: " + ", ".join(sorted(set(blockers)))
    else:
        viability = "SAFE"
        if warnings:
            cost_quality = "acceptable_with_caution"
            reason = "Execution environment safe with caution: " + ", ".join(sorted(set(warnings)))
        else:
            cost_quality = "optimal"
            reason = "Execution environment safe under calibrated symbol limits."

    return ExecutionEnvironmentEvaluation(
        execution_viability=viability,
        cost_quality=cost_quality,
        limits=limits,
        blockers=tuple(sorted(set(blockers))),
        warnings=tuple(sorted(set(warnings))),
        reason=reason,
    )
