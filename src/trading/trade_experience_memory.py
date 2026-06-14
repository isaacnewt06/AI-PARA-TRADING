"""Best/worst trade experience memory for MAXIMO."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


class TradeExperienceMemory:
    """Persist simple professional memory from real demo trade outcomes."""

    def __init__(self, *, best_path: Path, worst_path: Path) -> None:
        self.best_path = best_path
        self.worst_path = worst_path
        self.best_path.parent.mkdir(parents=True, exist_ok=True)
        self.worst_path.parent.mkdir(parents=True, exist_ok=True)
        self.best_path.touch(exist_ok=True)
        self.worst_path.touch(exist_ok=True)

    def evaluate_signal(
        self,
        *,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        market_pulse: dict[str, Any],
        final_confirmation: dict[str, Any],
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._context_key(
            signal=signal,
            intelligence=intelligence,
            market_pulse=market_pulse,
            final_confirmation=final_confirmation,
            execution_readiness=execution_readiness,
            entry_quality=entry_quality,
        )
        winners = self._read_jsonl(self.best_path)
        losers = self._read_jsonl(self.worst_path)
        winner_similarity = self._max_similarity(context, winners)
        loser_similarity = self._max_similarity(context, losers)
        if loser_similarity >= 0.78 and loser_similarity > winner_similarity + 0.12:
            bias = "BLOCK"
            reason = "La señal se parece demasiado a peores trades guardados."
        elif loser_similarity >= 0.62 and loser_similarity >= winner_similarity:
            bias = "REDUCE_RISK"
            reason = "La señal tiene similitud relevante con pérdidas previas; usar defensa."
        elif winner_similarity >= 0.62 and winner_similarity > loser_similarity:
            bias = "FAVOR"
            reason = "La señal se parece más a mejores trades que a pérdidas."
        else:
            bias = "CAUTION"
            reason = "Memoria insuficiente o mixta; exigir confirmación limpia."
        return {
            "status": "active" if winners or losers else "collecting",
            "memory_bias": bias,
            "similarity_to_winners": round(winner_similarity, 4),
            "similarity_to_losers": round(loser_similarity, 4),
            "best_trades_count": len(winners),
            "worst_trades_count": len(losers),
            "context_key": context,
            "reason": reason,
            "best_memory_path": str(self.best_path.resolve()),
            "worst_memory_path": str(self.worst_path.resolve()),
        }

    def record_from_position_management(
        self,
        *,
        position_management_history_path: Path,
        intelligence: dict[str, Any],
        final_confirmation: dict[str, Any],
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
    ) -> dict[str, Any]:
        events = self._read_jsonl(position_management_history_path)
        best_existing = {str(item.get("ticket")) for item in self._read_jsonl(self.best_path)}
        worst_existing = {str(item.get("ticket")) for item in self._read_jsonl(self.worst_path)}
        written_best = 0
        written_worst = 0
        for event in events[-200:]:
            ticket = str(event.get("ticket") or "")
            if not ticket:
                continue
            current_r = self._safe_float(event.get("current_r"))
            mfe_r = self._safe_float(event.get("mfe_r") or event.get("max_favorable_r"))
            action = str(event.get("action_taken") or event.get("action") or "").lower()
            is_closed_or_decisive = any(token in action for token in ("close", "fast_exit", "be", "trail", "protect"))
            if not is_closed_or_decisive and abs(current_r) < 0.75:
                continue
            memory = self._memory_payload(
                event=event,
                intelligence=intelligence,
                final_confirmation=final_confirmation,
                execution_readiness=execution_readiness,
                entry_quality=entry_quality,
                current_r=current_r,
                mfe_r=mfe_r,
            )
            if current_r > 0.25 and ticket not in best_existing:
                self._append(self.best_path, memory)
                best_existing.add(ticket)
                written_best += 1
            elif (current_r < -0.15 or (mfe_r >= 0.5 and current_r <= 0.0)) and ticket not in worst_existing:
                self._append(self.worst_path, memory)
                worst_existing.add(ticket)
                written_worst += 1
        return {
            "status": "updated",
            "written_best": written_best,
            "written_worst": written_worst,
            "best_trades_count": len(best_existing),
            "worst_trades_count": len(worst_existing),
        }

    def summary(self) -> dict[str, Any]:
        best = self._read_jsonl(self.best_path)
        worst = self._read_jsonl(self.worst_path)
        return {
            "best_trades": len(best),
            "worst_trades": len(worst),
            "top_winning_setups": Counter(str(item.get("setup_type") or "unknown") for item in best).most_common(5),
            "top_losing_setups": Counter(str(item.get("setup_type") or "unknown") for item in worst).most_common(5),
            "best_memory_path": str(self.best_path.resolve()),
            "worst_memory_path": str(self.worst_path.resolve()),
        }

    def _memory_payload(
        self,
        *,
        event: dict[str, Any],
        intelligence: dict[str, Any],
        final_confirmation: dict[str, Any],
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
        current_r: float,
        mfe_r: float,
    ) -> dict[str, Any]:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        watch_trigger = intelligence.get("watch_trigger") or {}
        won = current_r > 0
        return {
            "ticket": event.get("ticket"),
            "symbol": event.get("symbol"),
            "side": str(event.get("side") or "").upper(),
            "session": market_state.get("session") or market_state.get("session_name"),
            "setup_type": event.get("setup_type") or watch_trigger.get("setup_detected") or market_state.get("operational_family"),
            "market_pulse": (intelligence.get("market_pulse") or {}).get("score"),
            "final_confirmation": final_confirmation.get("final_confirmation_score"),
            "execution_readiness": execution_readiness.get("execution_readiness_score"),
            "entry_quality": entry_quality.get("entry_quality_score"),
            "risk_mode": event.get("risk_mode"),
            "MFE": mfe_r,
            "MAE": self._safe_float(event.get("mae_r") or event.get("max_adverse_r")),
            "final_R": current_r,
            "exit_reason": event.get("reason") or event.get("action_taken"),
            "management_actions": event.get("action_taken") or event.get("action"),
            "why_it_won": "Protección/gestión favorable y dirección respetada." if won else "",
            "why_it_lost": "" if won else self._loss_reason(event=event, mfe_r=mfe_r, current_r=current_r),
            "lesson": self._lesson(won=won, mfe_r=mfe_r, current_r=current_r),
        }

    @staticmethod
    def _context_key(
        *,
        signal: dict[str, Any] | None,
        intelligence: dict[str, Any],
        market_pulse: dict[str, Any],
        final_confirmation: dict[str, Any],
        execution_readiness: dict[str, Any],
        entry_quality: dict[str, Any],
    ) -> dict[str, Any]:
        market_state = intelligence.get("overview", {}).get("market_state", {}) or {}
        return {
            "side": str((signal or {}).get("direction") or final_confirmation.get("side") or market_state.get("preferred_side") or "NEUTRAL").upper(),
            "setup_type": (signal or {}).get("setup_type") or market_state.get("operational_family"),
            "market_regime": market_state.get("market_regime"),
            "pulse_bucket": TradeExperienceMemory._bucket(market_pulse.get("score")),
            "final_bucket": TradeExperienceMemory._bucket(final_confirmation.get("final_confirmation_score")),
            "readiness_bucket": TradeExperienceMemory._bucket(execution_readiness.get("execution_readiness_score")),
            "entry_quality_bucket": TradeExperienceMemory._bucket(entry_quality.get("entry_quality_score")),
        }

    @classmethod
    def _max_similarity(cls, context: dict[str, Any], memories: list[dict[str, Any]]) -> float:
        best = 0.0
        for memory in memories[-200:]:
            comparable = {
                "side": str(memory.get("side") or "").upper(),
                "setup_type": memory.get("setup_type"),
                "market_regime": memory.get("market_regime"),
                "pulse_bucket": cls._bucket(memory.get("market_pulse")),
                "final_bucket": cls._bucket(memory.get("final_confirmation")),
                "readiness_bucket": cls._bucket(memory.get("execution_readiness")),
                "entry_quality_bucket": cls._bucket(memory.get("entry_quality")),
            }
            matches = sum(1 for key, value in context.items() if comparable.get(key) == value)
            best = max(best, matches / max(len(context), 1))
        return best

    @staticmethod
    def _bucket(value: Any) -> str:
        numeric = TradeExperienceMemory._safe_float(value)
        if numeric >= 85:
            return "very_high"
        if numeric >= 70:
            return "high"
        if numeric >= 55:
            return "medium"
        if numeric > 0:
            return "low"
        return "unknown"

    @staticmethod
    def _loss_reason(*, event: dict[str, Any], mfe_r: float, current_r: float) -> str:
        if mfe_r >= 0.5 and current_r <= 0:
            return "Devolvió ganancia después de superar +0.5R."
        return str(event.get("reason") or "Salida negativa o gestión insuficiente.")

    @staticmethod
    def _lesson(*, won: bool, mfe_r: float, current_r: float) -> str:
        if won:
            return "Buscar setups similares y mantener gestión post-entrada."
        if mfe_r >= 0.5 and current_r <= 0:
            return "Activar BE/fast_exit antes de permitir devolución completa."
        return "Exigir mejor timing, SL compacto y confirmación limpia."

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    @staticmethod
    def _append(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
