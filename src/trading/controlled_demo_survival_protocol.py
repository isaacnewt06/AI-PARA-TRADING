"""Controlled demo survival protocol for fragile research edges.

The protocol does not create entries. It only decides whether a frozen edge is
safe enough to validate in a tightly restricted demo environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.trading.execution_environment_policy import limits_for_symbol


@dataclass(frozen=True, slots=True)
class ControlledDemoSurvivalProtocolV1:
    """Gate displacement_plus_wick_v1 to safe research-demo environments only."""

    name: str = "CONTROLLED_DEMO_SURVIVAL_PROTOCOL_V1"
    edge_name: str = "displacement_plus_wick_v1"
    max_spread: float = 0.15
    max_slippage: float = 0.20
    max_latency: float = 0.20
    max_risk_multiplier: float = 0.5

    VALIDATED_NY_AM_HOURS = frozenset({9})
    VALIDATED_NY_PM_HOURS = frozenset({15})
    BLOCKED_LONDON_HOURS = frozenset({2, 3, 4, 5})
    BLOCKED_ASIA_HOURS = frozenset({0, 1, 19, 20, 21, 22, 23})
    SAFE_ATR_REGIMES = frozenset({"HIGH", "EXTREME"})

    def evaluate(
        self,
        *,
        symbol: str,
        signal: dict[str, Any] | None,
        market_state: dict[str, Any],
        event_risk: dict[str, Any],
        execution_environment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        environment = execution_environment or {}
        applies = self._applies_to_signal(signal)
        hour_ny = self._coerce_int(
            self._first_present(
                signal.get("hour_ny") if signal else None,
                market_state.get("hour_ny"),
                environment.get("hour_ny"),
            )
        )
        session = self._session_label(hour_ny)
        atr_ratio = self._coerce_float(
            self._first_present(
                market_state.get("atr_ratio"),
                environment.get("atr_ratio"),
            )
        )
        atr_regime = str(environment.get("atr_regime") or self._atr_regime(atr_ratio)).upper()
        spread = self._coerce_float(
            self._first_present(
                environment.get("live_spread"),
                environment.get("spread"),
                environment.get("spread_price"),
            )
        )
        slippage = self._coerce_float(
            self._first_present(
                environment.get("slippage_estimated"),
                environment.get("estimated_slippage"),
            )
        )
        latency = self._coerce_float(
            self._first_present(
                environment.get("live_latency"),
                environment.get("latency_seconds"),
                environment.get("latency_estimated"),
            )
        )
        event_action = str(event_risk.get("action") or environment.get("event_action") or "unknown").lower()
        execution_viability = str(environment.get("execution_viability") or "UNKNOWN").upper()
        execution_limits = limits_for_symbol(symbol)
        max_spread = execution_limits.max_spread
        max_slippage = execution_limits.max_slippage
        max_latency = execution_limits.max_latency

        blockers: list[str] = []
        if not applies:
            return self._decision(
                symbol=symbol,
                applies=False,
                allowed=False,
                blockers=["protocol_not_applicable"],
                hour_ny=hour_ny,
                session=session,
                atr_ratio=atr_ratio,
                atr_regime=atr_regime,
                spread=spread,
                slippage=slippage,
                latency=latency,
                event_action=event_action,
                execution_viability=execution_viability,
                telemetry=environment,
                reason="El protocolo solo aplica al edge congelado displacement_plus_wick_v1.",
            )

        if session not in {"ny_am", "ny_pm"}:
            blockers.append("session_not_validated")
        if hour_ny in self.BLOCKED_LONDON_HOURS:
            blockers.append("london_blocked")
        if hour_ny in self.BLOCKED_ASIA_HOURS:
            blockers.append("asia_blocked")
        if spread is None:
            blockers.append("live_spread_unavailable")
        elif spread > max_spread:
            blockers.append("spread_above_survival_threshold")
        if slippage is None:
            blockers.append("slippage_estimate_unavailable")
        elif slippage > max_slippage:
            blockers.append("slippage_above_survival_threshold")
        if latency is None:
            blockers.append("latency_estimate_unavailable")
        elif latency > max_latency:
            blockers.append("latency_unsafe")
        if atr_regime not in self.SAFE_ATR_REGIMES:
            blockers.append("atr_regime_not_safe")
        if event_action != "allow":
            blockers.append("macro_high_impact_or_watch")
        if execution_viability != "SAFE":
            blockers.append("execution_viability_not_safe")

        allowed = not blockers
        return self._decision(
            symbol=symbol,
            applies=True,
            allowed=allowed,
            blockers=blockers,
            hour_ny=hour_ny,
            session=session,
            atr_ratio=atr_ratio,
            atr_regime=atr_regime,
            spread=spread,
            slippage=slippage,
            latency=latency,
            event_action=event_action,
            execution_viability=execution_viability,
            telemetry=environment,
            reason=(
                "Ambiente SAFE para validacion demo restringida del edge displacement_plus_wick_v1."
                if allowed
                else "Ambiente bloqueado para proteger un edge fragil bajo costos/ejecucion real."
            ),
        )

    def _decision(
        self,
        *,
        symbol: str,
        applies: bool,
        allowed: bool,
        blockers: list[str],
        hour_ny: int | None,
        session: str,
        atr_ratio: float | None,
        atr_regime: str,
        spread: float | None,
        slippage: float | None,
        latency: float | None,
        event_action: str,
        execution_viability: str,
        telemetry: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "protocol_name": self.name,
            "edge_name": self.edge_name,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "applies": applies,
            "allowed": allowed,
            "action": "ALLOW_DEMO_RESEARCH" if allowed else "BLOCK_DEMO_RESEARCH",
            "allowed_risk_mode": "reduced" if allowed else "blocked",
            "max_risk_multiplier": self.max_risk_multiplier if allowed else 0.0,
            "blockers": sorted(set(blockers)),
            "reason": reason,
            "environment": {
                "hour_ny": hour_ny,
                "session": session,
                "live_spread": spread,
                "live_latency": latency,
                "execution_delay": telemetry.get("execution_delay"),
                "slippage_estimated": slippage,
                "slippage_real": telemetry.get("slippage_real"),
                "partial_fills": telemetry.get("partial_fills"),
                "mfe": telemetry.get("mfe"),
                "mae": telemetry.get("mae"),
                "trailing_quality": telemetry.get("trailing_quality"),
                "time_to_be": telemetry.get("time_to_be"),
                "execution_degradation": telemetry.get("execution_degradation"),
                "atr_ratio": atr_ratio,
                "atr_regime": atr_regime,
                "event_action": event_action,
                "execution_viability": execution_viability,
            },
            "requirements": {
                "validated_sessions": ["ny_am", "ny_pm"],
                "validated_hours_ny": sorted(self.VALIDATED_NY_AM_HOURS | self.VALIDATED_NY_PM_HOURS),
                "max_spread": limits_for_symbol(symbol).max_spread,
                "preferred_spread": limits_for_symbol(symbol).preferred_spread,
                "hard_spread_limit": limits_for_symbol(symbol).hard_spread,
                "max_slippage_estimated": limits_for_symbol(symbol).max_slippage,
                "max_latency": limits_for_symbol(symbol).max_latency,
                "execution_policy_profile": limits_for_symbol(symbol).profile,
                "atr_regimes": sorted(self.SAFE_ATR_REGIMES),
                "event_action": "allow",
                "execution_viability": "SAFE",
                "risk_mode": "reduced_only",
            },
        }

    @classmethod
    def _applies_to_signal(cls, signal: dict[str, Any] | None) -> bool:
        if signal is None:
            return False
        values = [
            signal.get("signal_type"),
            signal.get("active_family"),
            signal.get("strategy_variant"),
            signal.get("strategy_name"),
            signal.get("edge_name"),
            signal.get("research_edge"),
        ]
        normalized = " ".join(str(value).lower() for value in values if value is not None)
        return "displacement_plus_wick_v1" in normalized or "reaction_zone_expansion_brain_v1" in normalized

    @classmethod
    def _session_label(cls, hour_ny: int | None) -> str:
        if hour_ny in cls.VALIDATED_NY_AM_HOURS:
            return "ny_am"
        if hour_ny in cls.VALIDATED_NY_PM_HOURS:
            return "ny_pm"
        if hour_ny in cls.BLOCKED_LONDON_HOURS:
            return "london"
        if hour_ny in cls.BLOCKED_ASIA_HOURS:
            return "asia"
        if hour_ny is None:
            return "unknown"
        if 8 <= hour_ny <= 16:
            return "new_york_unvalidated"
        return "off_session"

    @staticmethod
    def _atr_regime(atr_ratio: float | None) -> str:
        if atr_ratio is None:
            return "UNKNOWN"
        if atr_ratio >= 1.45:
            return "EXTREME"
        if atr_ratio >= 1.10:
            return "HIGH"
        if atr_ratio >= 0.85:
            return "NORMAL"
        return "LOW"

    @staticmethod
    def _first_present(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
