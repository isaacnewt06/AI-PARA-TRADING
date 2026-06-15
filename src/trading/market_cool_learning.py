"""Q-learning inspired market memory for historical state/action evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class CoolLearningConfig:
    window_candles: int = 12
    horizon_candles: int = 8
    max_samples: int = 1600
    max_neighbors: int = 40
    min_similarity: float = 0.70


class MarketCoolLearningMemory:
    """Evaluate BUY/SELL/WAIT from historical states similar to the current market.

    This is not a live-order trigger. It is a compact case-based/Q-value memory:
    previous market windows become states, future movement becomes reward, and
    the current state reads the weighted action values from nearest neighbors.
    """

    ACTIONS = ("BUY", "SELL", "WAIT")

    def __init__(self, config: CoolLearningConfig | None = None) -> None:
        self.config = config or CoolLearningConfig()

    def evaluate(
        self,
        *,
        snapshot: dict[str, Any],
        market_state: dict[str, Any],
        dominant_family: str,
        market_regime: str,
        preferred_side: str,
        course_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        course_alignment = self._course_alignment(
            course_context=course_context or {},
            market_state=market_state,
            dominant_family=dominant_family,
            market_regime=market_regime,
            preferred_side=preferred_side,
            policy_action="WAIT",
        )
        candles = self._snapshot_candles(snapshot, "M5")
        window = self.config.window_candles
        horizon = self.config.horizon_candles
        if len(candles) < window * 4 + horizon:
            return {
                "status": "insufficient_data",
                "learning_method": "q_learning_inspired_action_value_memory",
                "q_update_mode": "offline_historical_reward_estimation",
                "summary": "Q-learning memory no tiene suficientes velas M5 para evaluar estados historicos.",
                "sample_count": 0,
                "policy_action": "WAIT",
                "q_policy_action": "WAIT",
                "action_values": {"BUY": 0.0, "SELL": 0.0, "WAIT": 0.0},
                "q_values": {"BUY": 0.0, "SELL": 0.0, "WAIT": 0.0},
                "course_alignment": course_alignment,
            }

        current_window = candles[-window:]
        current_signature = self._window_signature(current_window)
        if not current_signature:
            return {
                "status": "insufficient_shape",
                "learning_method": "q_learning_inspired_action_value_memory",
                "q_update_mode": "offline_historical_reward_estimation",
                "summary": "Q-learning memory no pudo crear firma del estado actual.",
                "sample_count": 0,
                "policy_action": "WAIT",
                "q_policy_action": "WAIT",
                "action_values": {"BUY": 0.0, "SELL": 0.0, "WAIT": 0.0},
                "q_values": {"BUY": 0.0, "SELL": 0.0, "WAIT": 0.0},
                "course_alignment": course_alignment,
            }

        current_features = self._state_features(
            current_window,
            market_state=market_state,
            dominant_family=dominant_family,
            market_regime=market_regime,
            preferred_side=preferred_side,
        )
        neighbors: list[dict[str, Any]] = []
        last_start = len(candles) - window - horizon - window
        stride = max(1, last_start // self.config.max_samples) if last_start > self.config.max_samples else 1
        for start in range(0, max(0, last_start), stride):
            prior_window = candles[start : start + window]
            prior_signature = self._window_signature(prior_window)
            if not prior_signature:
                continue
            similarity = self._signature_similarity(current_signature, prior_signature)
            if similarity < self.config.min_similarity:
                continue
            rewards = self._action_rewards(candles=candles, start=start, window=window, horizon=horizon)
            neighbors.append(
                {
                    "start_index": start,
                    "end_index": start + window - 1,
                    "similarity": round(similarity, 4),
                    "state_key": self._state_key(prior_window, market_regime=market_regime),
                    "rewards": rewards,
                    "best_action": max(rewards, key=rewards.get),
                }
            )

        neighbors = sorted(neighbors, key=lambda item: item["similarity"], reverse=True)[: self.config.max_neighbors]
        if not neighbors:
            return {
                "status": "no_similar_state",
                "learning_method": "q_learning_inspired_action_value_memory",
                "q_update_mode": "offline_historical_reward_estimation",
                "summary": "Q-learning memory no encontro estados historicos suficientemente parecidos.",
                "state_key": self._state_key(current_window, market_regime=market_regime),
                "state_features": current_features,
                "sample_count": 0,
                "policy_action": "WAIT",
                "q_policy_action": "WAIT",
                "action_values": {"BUY": 0.0, "SELL": 0.0, "WAIT": 0.0},
                "q_values": {"BUY": 0.0, "SELL": 0.0, "WAIT": 0.0},
                "course_alignment": course_alignment,
            }

        action_values: dict[str, float] = {}
        action_win_rates: dict[str, float] = {}
        total_weight = sum(float(item["similarity"]) for item in neighbors) or 1.0
        for action in self.ACTIONS:
            weighted_value = sum(float(item["similarity"]) * float(item["rewards"][action]) for item in neighbors) / total_weight
            action_values[action] = round(weighted_value, 4)
            wins = sum(1 for item in neighbors if float(item["rewards"][action]) > 0.15)
            action_win_rates[action] = round(wins / len(neighbors), 4)

        policy_action = max(action_values, key=action_values.get)
        sorted_values = sorted(action_values.values(), reverse=True)
        value_gap = round(sorted_values[0] - sorted_values[1], 4) if len(sorted_values) >= 2 else 0.0
        confidence = round(min(1.0, max(0.0, 0.45 + value_gap * 0.55 + min(len(neighbors), 40) / 160)), 4)
        best_value = action_values[policy_action]
        if best_value < 0.12 or confidence < 0.58:
            policy_quality = "observe"
        elif best_value >= 0.45 and confidence >= 0.72:
            policy_quality = "strong"
        else:
            policy_quality = "moderate"
        course_alignment = self._course_alignment(
            course_context=course_context or {},
            market_state=market_state,
            dominant_family=dominant_family,
            market_regime=market_regime,
            preferred_side=preferred_side,
            policy_action=policy_action,
        )
        if course_alignment["status"] == "conflict":
            confidence = round(max(0.0, confidence - 0.14), 4)
            policy_quality = "observe" if policy_quality == "moderate" else policy_quality
        elif course_alignment["status"] == "weak":
            confidence = round(max(0.0, confidence - 0.07), 4)
        elif course_alignment["status"] == "aligned":
            confidence = round(min(1.0, confidence + 0.04), 4)

        summary = (
            f"Q-learning memory: estados similares={len(neighbors)}, accion={policy_action}, "
            f"Q BUY={action_values['BUY']:.2f}, SELL={action_values['SELL']:.2f}, "
            f"WAIT={action_values['WAIT']:.2f}, calidad={policy_quality}, "
            f"cursos={course_alignment['status']}."
        )
        return {
            "status": "available",
            "learning_method": "q_learning_inspired_action_value_memory",
            "q_update_mode": "offline_historical_reward_estimation",
            "summary": summary,
            "state_key": self._state_key(current_window, market_regime=market_regime),
            "state_features": current_features,
            "sample_count": len(neighbors),
            "policy_action": policy_action,
            "q_policy_action": policy_action,
            "policy_quality": policy_quality,
            "confidence": confidence,
            "value_gap": value_gap,
            "action_values": action_values,
            "q_values": action_values,
            "action_win_rates": action_win_rates,
            "course_alignment": course_alignment,
            "top_neighbors": neighbors[:5],
            "safety_note": "Q-learning memory aporta valores Q probabilisticos; no ejecuta sin trigger, SL/RR, macro y guardias validos.",
        }

    @classmethod
    def _course_alignment(
        cls,
        *,
        course_context: dict[str, Any],
        market_state: dict[str, Any],
        dominant_family: str,
        market_regime: str,
        preferred_side: str,
        policy_action: str,
    ) -> dict[str, Any]:
        """Compare the current setup with the distilled trading-course memory."""
        harmony_score = cls._safe_float(course_context.get("harmony_score"))
        support_score = cls._safe_float(course_context.get("support_score"))
        matched_count = int(cls._safe_float(course_context.get("matched_context_count")))
        contexts = list(course_context.get("top_matching_contexts") or [])
        family = str(course_context.get("dominant_family") or dominant_family or "General")
        side = str(preferred_side or "NEUTRAL").upper()
        policy = str(policy_action or "WAIT").upper()
        confirmations: list[str] = []
        missing_steps: list[str] = []
        warnings: list[str] = []
        learned_profile = cls._learned_protocol_profile(
            course_context=course_context,
            market_state=market_state,
            family=family,
            side=side,
        )
        auto_selected_protocols: list[str] = []

        score = min(0.35, harmony_score * 0.35) + min(0.2, support_score * 0.2)
        score += min(0.15, matched_count * 0.015)
        if family and family != "General":
            score += 0.1
            confirmations.append(f"Familia aprendida dominante: {family}.")
        if contexts:
            confirmations.append(f"{min(len(contexts), 5)} contextos aprendidos coinciden con el estado actual.")
        if learned_profile["applicable"]:
            auto_selected_protocols.extend(learned_profile["protocols"])
            confirmations.extend(learned_profile["confirmations"])
            missing_steps.extend(learned_profile["missing_steps"])
            warnings.extend(learned_profile["warnings"])
            score += float(learned_profile["score_bonus"])

        side_lower = side.lower()
        checks = ((market_state.get("ob_rejection_families") or {}).get("aggressive") or {}).get("checks", {}) or {}
        institutional_checks = ((market_state.get("ob_rejection_families") or {}).get("institutional") or {}).get("checks", {}) or {}
        if family == "OB Rejection" or "OB" in family:
            rejection_key = "strong_bullish_rejection" if side == "BUY" else "strong_bearish_rejection"
            displacement_key = "partial_bull_displacement" if side == "BUY" else "partial_bear_displacement"
            micro_key = "micro_bos_buy" if side == "BUY" else "micro_bos_sell"
            continuation_key = "continuation_momentum_buy" if side == "BUY" else "continuation_momentum_sell"
            liquidity_key = f"liquidity_quality_{side_lower}"
            if side not in {"BUY", "SELL"}:
                missing_steps.append("Los cursos de OB Rejection requieren elegir BUY o SELL antes de preparar entrada.")
            if checks.get(rejection_key):
                score += 0.12
                confirmations.append("Paso de curso: rechazo de order block detectado.")
            else:
                missing_steps.append("Falta rechazo claro del order block en el lado candidato.")
            if checks.get(displacement_key) or institutional_checks.get(displacement_key.replace("partial_", "")):
                score += 0.1
                confirmations.append("Paso de curso: desplazamiento/impulso a favor detectado.")
            else:
                missing_steps.append("Falta desplazamiento limpio despues del rechazo.")
            if checks.get(micro_key):
                score += 0.08
                confirmations.append("Paso de curso: micro BOS acompana el lado candidato.")
            else:
                missing_steps.append("Falta micro BOS validando la direccion.")
            if checks.get(continuation_key):
                score += 0.06
                confirmations.append("Paso de curso: momentum de continuacion presente.")
            if institutional_checks.get(liquidity_key):
                score += 0.08
                confirmations.append("Paso de curso: liquidez institucional alineada.")
            else:
                missing_steps.append("Falta barrida/reaccion de liquidez con suficiente calidad.")
        elif family == "FVG Continuation" or "FVG" in family:
            if market_state.get("expansion_subtype") in {"impulse", "continuation"} or checks.get("continuation_momentum_buy") or checks.get("continuation_momentum_sell"):
                score += 0.16
                confirmations.append("Paso de curso: continuacion/expansion compatible con FVG.")
            else:
                missing_steps.append("Falta desplazamiento que deje FVG/continuacion aprovechable.")
        elif family == "Session Expansion":
            if market_state.get("allowed_hour_by_strategy"):
                score += 0.08
                confirmations.append("Paso de curso: sesion operativa habilitada.")
            else:
                missing_steps.append("La sesion/hora aun no acompana la expansion.")
            if market_state.get("volatility_state") in {"tradable_normal", "expanding_with_force"}:
                score += 0.08
                confirmations.append("Paso de curso: volatilidad util para expansion.")
            else:
                missing_steps.append("Falta volatilidad util para expansion de sesion.")

        if policy in {"BUY", "SELL"} and side in {"BUY", "SELL"}:
            if policy == side:
                score += 0.08
                confirmations.append("Memoria historica y lado preparado coinciden.")
            else:
                warnings.append(f"Memoria historica favorece {policy}, pero el lado preparado es {side}.")
                score -= 0.12

        if str(market_regime).lower() in {"non_operable", "dead", "chop"}:
            warnings.append("El regimen actual no es ideal para aplicar el patron aprendido.")
            score -= 0.12

        score = round(max(0.0, min(1.0, score)), 4)
        if warnings and score < 0.55:
            status = "conflict"
        elif score >= 0.68:
            status = "aligned"
        elif score >= 0.5:
            status = "partial"
        else:
            status = "weak"

        if policy in {"BUY", "SELL"} and side in {"BUY", "SELL"} and policy == side and status in {"aligned", "partial"}:
            course_action = policy
        elif side in {"BUY", "SELL"} and status == "aligned":
            course_action = side
        else:
            course_action = "WAIT"

        return {
            "status": status,
            "course_score": score,
            "dominant_family": family,
            "course_recommended_action": course_action,
            "confirmations": confirmations[:8],
            "missing_steps": cls._dedupe_items(missing_steps)[:8],
            "warnings": cls._dedupe_items(warnings)[:5],
            "auto_selected_protocols": cls._dedupe_items(auto_selected_protocols),
            "learned_protocol_profile": learned_profile,
            "source_summary": {
                "harmony_score": harmony_score,
                "support_score": support_score,
                "matched_context_count": matched_count,
                "top_contexts": contexts[:3],
            },
        }

    @classmethod
    def _learned_protocol_profile(
        cls,
        *,
        course_context: dict[str, Any],
        market_state: dict[str, Any],
        family: str,
        side: str,
    ) -> dict[str, Any]:
        """Auto-select distilled course protocols from current market evidence."""
        ob_families = market_state.get("ob_rejection_families") or {}
        aggressive = ob_families.get("aggressive") or {}
        aggressive_checks = aggressive.get("checks") or {}
        institutional_checks = (ob_families.get("institutional") or {}).get("checks") or {}
        manual_bias = ob_families.get("manual_bias") or aggressive_checks.get("sensei_manual_bias") or {}
        side_lower = str(side or "").lower()
        side_upper = str(side or "NEUTRAL").upper()

        contexts = list(course_context.get("top_matching_contexts") or [])
        context_text = " ".join(
            [
                str(item.get("strategy_family") or "")
                + " "
                + str(item.get("market_regime") or "")
                + " "
                + " ".join(str(value) for value in item.get("top_entry_conditions", []) or [])
                + " "
                + " ".join(str(value) for value in item.get("top_confirmations", []) or [])
                for item in contexts
            ]
        ).lower()
        protocols: list[str] = []
        confirmations: list[str] = []
        missing_steps: list[str] = []
        warnings: list[str] = []
        score_bonus = 0.0

        family_text = str(family or "").lower()
        ob_context = "ob" in family_text or "order_block" in context_text or "order block" in context_text
        sensei_applicable = ob_context or bool(manual_bias) or "liquidity" in context_text or "liquidez" in context_text
        if sensei_applicable:
            protocols.append("SENSEI_MANUAL_BIAS_PROTOCOL")
            manual_active = bool(manual_bias.get("active"))
            manual_side = str(manual_bias.get("side") or "NEUTRAL").upper()
            manual_checks = manual_bias.get("checks") or {}
            liquidity_ok = bool(
                manual_checks.get(f"{side_lower}_liquidity")
                or institutional_checks.get(f"liquidity_quality_{side_lower}")
            )
            micro_bos_ok = bool(manual_checks.get(f"{side_lower}_micro_bos") or aggressive_checks.get(f"micro_bos_{side_lower}"))
            displacement_ok = bool(
                manual_checks.get(f"{side_lower}_displacement")
                or aggressive_checks.get("partial_bull_displacement" if side_upper == "BUY" else "partial_bear_displacement")
                or institutional_checks.get("bull_displacement" if side_upper == "BUY" else "bear_displacement")
            )
            rejection_ok = bool(
                aggressive_checks.get("strong_bullish_rejection" if side_upper == "BUY" else "strong_bearish_rejection")
            )

            if manual_active and manual_side == side_upper:
                score_bonus += 0.16
                confirmations.append("Protocolo aprendido activado automáticamente: Sensei manual bias.")
            elif side_upper in {"BUY", "SELL"}:
                missing_steps.append("Sensei: falta completar la secuencia liquidez + BMS/BOS + desplazamiento.")
            if liquidity_ok:
                score_bonus += 0.08
                confirmations.append("Sensei: liquidez/highs-lows del lado correcto reconocida.")
            else:
                missing_steps.append("Sensei: falta barrida o reacción clara en últimos highs/lows.")
            if micro_bos_ok:
                score_bonus += 0.08
                confirmations.append("Sensei: BMS/BOS acompaña el bias.")
            else:
                missing_steps.append("Sensei: falta BMS/BOS validando el movimiento.")
            if displacement_ok:
                score_bonus += 0.08
                confirmations.append("Sensei: desplazamiento a favor del bias detectado.")
            else:
                missing_steps.append("Sensei: falta desplazamiento limpio después de la reacción.")
            if rejection_ok:
                score_bonus += 0.04
                confirmations.append("Sensei: rechazo de zona/OB detectado.")

        if "fvg" in family_text or "fvg" in context_text:
            protocols.append("FVG_CONTINUATION_PROTOCOL")
        if "session" in family_text or "new_york" in context_text or "london" in context_text:
            protocols.append("SESSION_EXPANSION_PROTOCOL")
            if market_state.get("allowed_hour_by_strategy"):
                score_bonus += 0.04
                confirmations.append("Protocolo aprendido de sesión: horario operativo activo.")
            else:
                missing_steps.append("Protocolo de sesión: horario operativo aún no acompaña.")

        return {
            "applicable": bool(protocols),
            "protocols": cls._dedupe_items(protocols),
            "score_bonus": round(min(0.28, score_bonus), 4),
            "confirmations": cls._dedupe_items(confirmations)[:8],
            "missing_steps": cls._dedupe_items(missing_steps)[:8],
            "warnings": cls._dedupe_items(warnings)[:5],
            "source": "auto_detected_from_market_state_and_extracted_course_context",
        }

    @staticmethod
    def _snapshot_candles(snapshot: dict[str, Any], timeframe: str) -> list[Any]:
        candles = snapshot.get("candles", {}).get(timeframe) if isinstance(snapshot.get("candles"), dict) else None
        if candles is None:
            candles = snapshot.get(timeframe) if isinstance(snapshot, dict) else None
        return list(candles or [])

    @staticmethod
    def _candle_value(candle: Any, field: str) -> float:
        if isinstance(candle, dict):
            return float(candle[field])
        return float(getattr(candle, field))

    @classmethod
    def _window_signature(cls, candles: list[Any]) -> list[float]:
        if not candles:
            return []
        highs = [cls._candle_value(item, "high") for item in candles]
        lows = [cls._candle_value(item, "low") for item in candles]
        opens = [cls._candle_value(item, "open") for item in candles]
        closes = [cls._candle_value(item, "close") for item in candles]
        price_range = max(highs) - min(lows)
        if price_range <= 0:
            return []
        base = closes[0]
        signature: list[float] = []
        for open_price, close_price, high_price, low_price in zip(opens, closes, highs, lows):
            signature.append(round((close_price - base) / price_range, 5))
            signature.append(round((close_price - open_price) / price_range, 5))
            signature.append(round((high_price - low_price) / price_range, 5))
        return signature

    @staticmethod
    def _signature_similarity(current: list[float], prior: list[float]) -> float:
        if not current or len(current) != len(prior):
            return 0.0
        avg_abs_diff = sum(abs(a - b) for a, b in zip(current, prior)) / len(current)
        return max(0.0, min(1.0, 1.0 - avg_abs_diff))

    @classmethod
    def _action_rewards(cls, *, candles: list[Any], start: int, window: int, horizon: int) -> dict[str, float]:
        prior_window = candles[start : start + window]
        future = candles[start + window : start + window + horizon]
        entry = cls._candle_value(prior_window[-1], "close")
        window_high = max(cls._candle_value(item, "high") for item in prior_window)
        window_low = min(cls._candle_value(item, "low") for item in prior_window)
        threshold = max((window_high - window_low) * 0.35, abs(entry) * 0.0005)
        future_high = max(cls._candle_value(item, "high") for item in future)
        future_low = min(cls._candle_value(item, "low") for item in future)
        buy_reward = cls._bounded_reward((future_high - entry) / threshold, (entry - future_low) / threshold)
        sell_reward = cls._bounded_reward((entry - future_low) / threshold, (future_high - entry) / threshold)
        best_directional = max(buy_reward, sell_reward)
        wait_reward = 0.18 if best_directional < 0.18 else -0.12 if best_directional > 0.42 else 0.02
        return {
            "BUY": round(buy_reward, 4),
            "SELL": round(sell_reward, 4),
            "WAIT": round(wait_reward, 4),
        }

    @staticmethod
    def _bounded_reward(favorable_units: float, adverse_units: float) -> float:
        raw = favorable_units * 0.62 - adverse_units * 0.48
        return max(-1.0, min(1.0, raw))

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _dedupe_items(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            if item and item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    @classmethod
    def _state_features(
        cls,
        candles: list[Any],
        *,
        market_state: dict[str, Any],
        dominant_family: str,
        market_regime: str,
        preferred_side: str,
    ) -> dict[str, Any]:
        opens = [cls._candle_value(item, "open") for item in candles]
        closes = [cls._candle_value(item, "close") for item in candles]
        highs = [cls._candle_value(item, "high") for item in candles]
        lows = [cls._candle_value(item, "low") for item in candles]
        price_range = max(highs) - min(lows)
        body_average = mean(abs(close - open_) for open_, close in zip(opens, closes)) if candles else 0.0
        slope = (closes[-1] - closes[0]) / price_range if price_range else 0.0
        return {
            "dominant_family": dominant_family,
            "market_regime": market_regime,
            "preferred_side": str(preferred_side or "NEUTRAL").upper(),
            "trend_bucket": "up" if slope > 0.18 else "down" if slope < -0.18 else "flat",
            "range_bucket": "wide" if price_range > body_average * 8 else "normal" if price_range > body_average * 4 else "tight",
            "body_pressure": "strong" if body_average > price_range * 0.13 else "soft",
            "volatility_state": market_state.get("volatility_state") or "unknown",
            "buy_mtf_score": market_state.get("buy_mtf_score"),
            "sell_mtf_score": market_state.get("sell_mtf_score"),
        }

    @classmethod
    def _state_key(cls, candles: list[Any], *, market_regime: str) -> str:
        features = cls._state_features(
            candles,
            market_state={},
            dominant_family="memory",
            market_regime=market_regime,
            preferred_side="NEUTRAL",
        )
        return "|".join(
            [
                str(features["market_regime"]),
                str(features["trend_bucket"]),
                str(features["range_bucket"]),
                str(features["body_pressure"]),
            ]
        )
