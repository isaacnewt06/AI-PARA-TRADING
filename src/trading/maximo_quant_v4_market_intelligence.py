"""Full market intelligence layer for MAXIMO Quant v4."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import Settings
from src.trading.market_event_calendar import MarketEventCalendar
from src.trading.market_cool_learning import MarketCoolLearningMemory
from src.trading.maximo_quant_v4_market_overview import MaximoQuantV4MarketOverviewEngine
from src.trading.mt5_bridge import MT5Bridge


class MaximoQuantV4MarketIntelligenceEngine:
    """Combine learned knowledge, live market context, volatility and event risk into one decision."""

    WATCH_PREPARE_SETUP_MATURITY = 69.0

    def __init__(self, settings: Settings, *, bridge: MT5Bridge | None = None) -> None:
        self.settings = settings
        self.bridge = bridge or MT5Bridge(settings)
        self.overview_engine = MaximoQuantV4MarketOverviewEngine(settings, bridge=self.bridge)
        self.output_dir = self.settings.paths.data_dir / "market_analysis" / "maximo_quant_v4"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.latest_json_path = self.output_dir / "latest_market_intelligence.json"
        self.latest_md_path = self.output_dir / "latest_market_intelligence.md"
        self.log_path = self.output_dir / "market_intelligence_log.csv"
        self.events_path = self.output_dir / "economic_events.json"
        self.calendar = MarketEventCalendar(self.events_path)
        self.cool_learning = MarketCoolLearningMemory()

    def run(self, *, symbol: str) -> dict[str, Any]:
        payload = self.run_detailed(symbol=symbol)
        return {
            "strategy_name": payload["strategy_name"],
            "symbol": symbol,
            "strategy_variant": payload["strategy_variant"],
            "session_variant": payload["session_variant"],
            "action": payload["execution_readiness"]["action"],
            "confidence": payload["execution_readiness"]["confidence"],
            "signal_detected": payload["overview"]["signal"] is not None,
            "event_action": payload["event_risk"]["action"],
            "event_sync_status": payload["event_risk"].get("sync_status", {}).get("status"),
            "volatility_state": payload["volatility_intelligence"]["state"],
            "preferred_side": payload["overview"]["market_state"].get("preferred_side"),
            "market_regime": payload["overview"]["market_state"].get("market_regime"),
            "operational_family": payload["overview"]["market_state"].get("operational_family"),
            "harmony_score": payload["overview"]["knowledge_alignment"].get("harmony", {}).get("harmony_score"),
            "operating_posture": payload["overview"]["knowledge_alignment"].get("harmony", {}).get("operating_posture"),
            "watch_trigger": payload.get("watch_trigger"),
            "paths": {
                "latest_json": str(self.latest_json_path.resolve()),
                "latest_md": str(self.latest_md_path.resolve()),
                "log_csv": str(self.log_path.resolve()),
                "events_json": str(self.events_path.resolve()),
            },
        }

    def run_detailed(self, *, symbol: str) -> dict[str, Any]:
        detailed = self.overview_engine.run_detailed(symbol=symbol)
        event_risk = self.calendar.evaluate_for_symbol(
            symbol=symbol,
            pre_event_block_minutes=self.settings.economic_calendar_pre_event_block_minutes,
            post_event_block_minutes=self.settings.economic_calendar_post_event_block_minutes,
            upcoming_window_minutes=self.settings.economic_calendar_upcoming_watch_minutes,
            auto_sync=self.settings.economic_calendar_auto_sync,
            remote_url=self.settings.economic_calendar_url,
            timeout_seconds=self.settings.economic_calendar_timeout_seconds,
            local_timezone_name=self.settings.market_reference_timezone,
        )
        volatility = self._evaluate_volatility(detailed["analysis"]["market_state"])
        execution = self._execution_readiness(
            market_state=detailed["analysis"]["market_state"],
            overview_decision=detailed["analysis"]["decision"],
            signal=detailed["analysis"]["signal"],
            event_risk=event_risk,
            volatility=volatility,
        )
        watch_trigger = self._build_watch_trigger(
            strategy_variant_code=detailed["runtime"]["strategy_variant"].code,
            market_state=detailed["analysis"]["market_state"],
            knowledge_alignment=detailed["analysis"]["knowledge_alignment"],
            signal=detailed["analysis"]["signal"],
            event_risk=event_risk,
            volatility=volatility,
            execution=execution,
            snapshot=detailed.get("snapshot", {}),
        )
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "strategy_name": "MAXIMO MTF Quant Institutional v4",
            "strategy_variant": detailed["runtime"]["strategy_variant"].code,
            "session_variant": detailed["runtime"]["session_variant"].code,
            "overview": detailed["analysis"],
            "event_risk": event_risk,
            "volatility_intelligence": volatility,
            "execution_readiness": execution,
            "watch_trigger": watch_trigger,
        }
        self._write_outputs(payload)
        self._append_log(payload)
        return payload

    @staticmethod
    def _evaluate_volatility(market_state: dict[str, Any]) -> dict[str, Any]:
        atr_ratio = float(market_state.get("atr_ratio") or 0.0)
        range_ratio = float(market_state.get("range_ratio") or 0.0)
        impulse_score = int(market_state.get("impulse_score") or 0)
        quant_score = int(market_state.get("quant_score") or 0)

        if atr_ratio >= 1.1 and range_ratio >= 1.1 and impulse_score >= 60:
            state = "expanding_with_force"
            action = "favorable"
        elif range_ratio > 1.95:
            state = "overextended"
            action = "caution"
        elif atr_ratio < 0.85 and range_ratio < 0.85:
            state = "compressed"
            action = "watch_for_release"
        elif quant_score >= 60:
            state = "tradable_normal"
            action = "neutral_positive"
        else:
            state = "weak"
            action = "caution"

        return {
            "state": state,
            "action": action,
            "atr_ratio": atr_ratio,
            "range_ratio": range_ratio,
            "impulse_score": impulse_score,
            "quant_score": quant_score,
        }

    @staticmethod
    def _execution_readiness(
        *,
        market_state: dict[str, Any],
        overview_decision: dict[str, Any],
        signal: dict[str, Any] | None,
        event_risk: dict[str, Any],
        volatility: dict[str, Any],
    ) -> dict[str, Any]:
        blockers: list[str] = list(overview_decision.get("blockers", []))
        rationale: list[str] = list(overview_decision.get("rationale", []))

        if event_risk["action"] == "block":
            blockers.append("high_impact_event_window")
        elif event_risk["action"] == "watch":
            rationale.append("Hay evento cercano; conviene vigilancia activa.")

        if volatility["action"] == "caution":
            rationale.append("La volatilidad está exigente; si aparece entrada debe manejarse con más prudencia.")

        base_action = str(overview_decision.get("action", "CAUTION")).upper()
        action = base_action
        confidence = round(float(overview_decision.get("confidence", 0.0)), 4)
        risk_mode = str(overview_decision.get("risk_mode", "blocked"))
        watchlist_active = bool(overview_decision.get("watchlist_active", False))

        if event_risk["action"] == "block":
            action = "BLOCKED"
            confidence = 0.0
            risk_mode = "blocked"
        elif base_action == "EXECUTE" and signal is not None:
            if volatility["action"] == "caution":
                risk_mode = "reduced"
            confidence = round(
                min(
                    1.0,
                    confidence * 0.75 + (0.2 if volatility["action"] == "favorable" else 0.12),
                ),
                4,
            )
        elif base_action == "WATCH":
            watchlist_active = True
            if risk_mode == "blocked":
                risk_mode = "reduced"
        elif base_action == "CAUTION":
            risk_mode = "blocked"
        elif base_action == "BLOCKED":
            risk_mode = "blocked"

        if event_risk["active_events"]:
            rationale.append("Hay evento macro activo o en ventana de bloqueo.")
        elif event_risk["upcoming_events"]:
            rationale.append("Hay evento macro cercano; conviene prudencia.")
        rationale.append(f"La volatilidad actual está clasificada como {volatility['state']}.")

        return {
            "action": action,
            "confidence": confidence,
            "risk_mode": risk_mode,
            "watchlist_active": watchlist_active,
            "setup_maturity": overview_decision.get("setup_maturity"),
            "can_execute_demo_now": action == "EXECUTE",
            "blockers": sorted(set(blockers)),
            "rationale": rationale,
        }

    @staticmethod
    def _higher_timeframe_bias(market_state: dict[str, Any]) -> str:
        macro = str(market_state.get("macro_bias", "NEUTRAL")).upper()
        trend = str(market_state.get("trend_bias", "NEUTRAL")).upper()
        setup = str(market_state.get("setup_bias", "NEUTRAL")).upper()
        values = [macro, trend, setup]
        if values.count("SELL") >= 2:
            return "SELL"
        if values.count("BUY") >= 2:
            return "BUY"
        return "NEUTRAL"

    def _build_watch_trigger(
        self,
        *,
        strategy_variant_code: str,
        market_state: dict[str, Any],
        knowledge_alignment: dict[str, Any],
        signal: dict[str, Any] | None,
        event_risk: dict[str, Any],
        volatility: dict[str, Any],
        execution: dict[str, Any],
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if str(execution.get("action", "")).upper() != "WATCH":
            return None

        raw_preferred_side = market_state.get("preferred_side", "NEUTRAL")
        preferred_side = "NEUTRAL" if raw_preferred_side in (None, "") else str(raw_preferred_side).upper()
        higher_timeframe_bias = self._higher_timeframe_bias(market_state)
        harmony_score = float(knowledge_alignment.get("harmony", {}).get("harmony_score") or 0.0)
        setup_maturity = float(execution.get("setup_maturity") or 0.0)
        confidence = float(execution.get("confidence") or 0.0)
        signal_detected = signal is not None
        dominant_family = str(knowledge_alignment.get("harmony", {}).get("dominant_family") or "General")
        operational_family = str(market_state.get("operational_family") or "NONE")
        setup_detected = signal.get("setup_type") if signal else (
            operational_family if operational_family != "NONE" else f"{dominant_family}_developing"
        )
        volatility_state = str(volatility.get("state") or "unknown")
        event_action = str(event_risk.get("action") or "allow")
        session_tags = self._session_tags_from_market_state(market_state)

        missing_for_execute = []
        if not signal_detected:
            missing_for_execute.append("Falta señal operativa confirmada.")
        if setup_maturity < self.WATCH_PREPARE_SETUP_MATURITY:
            missing_for_execute.append(
                f"El setup_maturity actual ({setup_maturity}) aún no supera el umbral de preparacion."
            )
        if higher_timeframe_bias == "NEUTRAL":
            missing_for_execute.append("El sesgo de temporalidades mayores aún no está suficientemente definido.")
        if event_action != "allow":
            missing_for_execute.append("El contexto macro todavía no permite operar.")

        pattern_projection = self._build_pattern_projection(
            preferred_side=preferred_side,
            higher_timeframe_bias=higher_timeframe_bias,
            market_state=market_state,
            knowledge_alignment=knowledge_alignment,
            setup_maturity=setup_maturity,
            confidence=confidence,
            signal_detected=signal_detected,
            event_action=event_action,
            volatility_state=volatility_state,
            missing_for_execute=missing_for_execute,
            snapshot=snapshot,
        )
        watch_side = (
            str(pattern_projection.get("candidate_side") or preferred_side).upper()
            if preferred_side in {"BUY", "SELL"}
            else "NEUTRAL"
        )
        trigger_type, required_conditions, cancel_conditions = self._watch_trigger_contract(
            side=watch_side,
            setup_maturity_threshold=self.WATCH_PREPARE_SETUP_MATURITY,
        )

        return {
            "side": watch_side,
            "candidate_side": pattern_projection["candidate_side"],
            "trigger_type": trigger_type,
            "required_conditions": required_conditions,
            "cancel_conditions": cancel_conditions,
            "upgrade_to_execute_if": [
                "signal_detected = true",
                "setup_maturity >= 75",
                "hay stop loss lógico",
                "hay RR evaluable",
                "no existen critical_blocks",
                "event_action = allow",
                "broker/demo status válido",
            ],
            "expiration_logic": "Expira si el contexto pierde dirección, entra evento bloqueante, cae la armonía o cambia la situación del mercado antes del trigger.",
            "strategy_selected": strategy_variant_code,
            "setup_detected": setup_detected,
            "operational_family": operational_family,
            "ob_rejection_families": market_state.get("ob_rejection_families", {}),
            "market_regime": market_state.get("market_regime"),
            "harmony_score": harmony_score,
            "setup_maturity": setup_maturity,
            "confidence": confidence,
            "signal_detected": signal_detected,
            "higher_timeframe_bias": higher_timeframe_bias,
            "volatility": volatility_state,
            "macro_event_status": event_action,
            "missing_for_execute": missing_for_execute,
            "pattern_projection": pattern_projection,
        }

    @staticmethod
    def _watch_trigger_contract(*, side: str, setup_maturity_threshold: float) -> tuple[str, list[str], list[str]]:
        side = str(side or "NEUTRAL").upper()
        if side == "SELL":
            return (
                "bearish_confirmation",
                [
                    "Cierre M5 bajista confirmando rechazo o continuidad a favor de SELL.",
                    f"setup_maturity >= {setup_maturity_threshold:g}",
                    "signal_detected = true",
                    "higher_timeframe_bias en SELL o al menos no contradictorio.",
                    "stop loss lógico sobre el swing o zona invalidada.",
                    "RR evaluable y aceptable para demo.",
                    "event_action = allow al momento del disparo.",
                ],
                [
                    "Aparece noticia macro bloqueante dentro de la ventana 5/5.",
                    "El lado candidato cambia a BUY.",
                    "higher_timeframe_bias cambia claramente contra SELL.",
                    "harmony_score cae por debajo de 0.35.",
                    "La expansión se degrada a ruido o el mercado entra en zona no operable.",
                ],
            )
        if side == "BUY":
            return (
                "bullish_confirmation",
                [
                    "Cierre M5 alcista confirmando rechazo o continuidad a favor de BUY.",
                    f"setup_maturity >= {setup_maturity_threshold:g}",
                    "signal_detected = true",
                    "higher_timeframe_bias en BUY o al menos no contradictorio.",
                    "stop loss lógico bajo el swing o zona invalidada.",
                    "RR evaluable y aceptable para demo.",
                    "event_action = allow al momento del disparo.",
                ],
                [
                    "Aparece noticia macro bloqueante dentro de la ventana 5/5.",
                    "El lado candidato cambia a SELL.",
                    "higher_timeframe_bias cambia claramente contra BUY.",
                    "harmony_score cae por debajo de 0.35.",
                    "La estructura pierde intención alcista y vuelve a neutralidad fuerte.",
                ],
            )
        return (
            "neutral_observation",
            [
                "El mercado define dirección preferida BUY o SELL.",
                f"setup_maturity >= {setup_maturity_threshold:g}",
                "signal_detected = true",
                "Aparece una vela M5 de confirmación clara en la dirección elegida.",
                "stop loss lógico y RR evaluable.",
                "event_action = allow al momento del disparo.",
            ],
            [
                "Aparece noticia macro bloqueante dentro de la ventana 5/5.",
                "El mercado vuelve a chop o rango no operable.",
                "harmony_score cae por debajo de 0.35.",
                "La volatilidad se vuelve extrema sin estructura aprovechable.",
            ],
        )

    @staticmethod
    def _build_pattern_projection(
        *,
        preferred_side: str,
        higher_timeframe_bias: str,
        market_state: dict[str, Any],
        knowledge_alignment: dict[str, Any],
        setup_maturity: float,
        confidence: float,
        signal_detected: bool,
        event_action: str,
        volatility_state: str,
        missing_for_execute: list[str],
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        harmony = knowledge_alignment.get("harmony", {}) or {}
        top_contexts = list(knowledge_alignment.get("top_matching_contexts", []) or [])
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        aggressive = ob_families.get("aggressive", {}) or {}
        institutional = ob_families.get("institutional", {}) or {}
        reduced_candidate = aggressive.get("reduced_signal_candidate") or {}

        aggressive_side = str(aggressive.get("side") or "NEUTRAL").upper()
        institutional_side = str(institutional.get("side") or "NEUTRAL").upper()
        candidate_side = preferred_side
        if candidate_side not in {"BUY", "SELL"}:
            if aggressive.get("active") and aggressive_side in {"BUY", "SELL"}:
                candidate_side = aggressive_side
            elif institutional.get("active") and institutional_side in {"BUY", "SELL"}:
                candidate_side = institutional_side
            elif str(reduced_candidate.get("direction") or "").upper() in {"BUY", "SELL"}:
                candidate_side = str(reduced_candidate.get("direction")).upper()

        dominant_family = str(harmony.get("dominant_family") or "General")
        operational_family = str(market_state.get("operational_family") or ob_families.get("active_family") or "NONE")
        session_tags = MaximoQuantV4MarketIntelligenceEngine._session_tags_from_market_state(market_state)
        pattern_matches: list[str] = []
        evidence: list[str] = []
        missing_confirmations: list[str] = list(missing_for_execute)

        for context in top_contexts[:3]:
            family = context.get("strategy_family", "General")
            regime = context.get("market_regime", "mixed")
            label = context.get("operability_label", "research_only")
            score = context.get("score")
            pattern_matches.append(f"{family} en {regime} ({label}, score={score})")

        if aggressive.get("active"):
            pattern_matches.append("OB agresivo activo: rechazo/desplazamiento suficiente para vigilancia.")
            checks = aggressive.get("checks", {}) or {}
            if checks.get("strong_bullish_rejection"):
                evidence.append("Rechazo alcista fuerte detectado.")
            if checks.get("strong_bearish_rejection"):
                evidence.append("Rechazo bajista fuerte detectado.")
            if checks.get("partial_bull_displacement") or checks.get("partial_bear_displacement"):
                evidence.append("Desplazamiento parcial detectado.")
            if checks.get("micro_bos_buy") or checks.get("micro_bos_sell"):
                evidence.append("Micro BOS presente en el lado candidato.")
            if checks.get("continuation_momentum_buy") or checks.get("continuation_momentum_sell"):
                evidence.append("Momentum de continuación presente.")

        if institutional.get("active"):
            pattern_matches.append("Familia institucional activa: requiere confirmación más fuerte.")

        if reduced_candidate:
            evidence.append(
                "Existe candidato reducido con SL lógico y RR evaluable."
                if reduced_candidate.get("sl_logical_available") and reduced_candidate.get("rr_evaluable")
                else "Existe candidato reducido, pero todavía necesita validar SL/RR."
            )

        if not pattern_matches and dominant_family != "General":
            pattern_matches.append(f"Familia dominante aprendida: {dominant_family}.")

        historical_analogs = MaximoQuantV4MarketIntelligenceEngine._historical_pattern_analogs(
            snapshot=snapshot or {},
            side=candidate_side,
            dominant_family=dominant_family,
            market_regime=str(market_state.get("market_regime") or "unknown"),
        )
        side_probability_comparison = MaximoQuantV4MarketIntelligenceEngine._side_probability_comparison(
            snapshot=snapshot or {},
            preferred_side=preferred_side,
            initial_candidate_side=candidate_side,
            higher_timeframe_bias=higher_timeframe_bias,
            dominant_family=dominant_family,
            market_regime=str(market_state.get("market_regime") or "unknown"),
            setup_maturity=setup_maturity,
            confidence=confidence,
            harmony_score=float(harmony.get("harmony_score") or 0.0),
            event_action=event_action,
            volatility_state=volatility_state,
            signal_detected=signal_detected,
            session_tags=session_tags,
        )
        cool_learning_memory = MarketCoolLearningMemory().evaluate(
            snapshot=snapshot or {},
            market_state=market_state,
            dominant_family=dominant_family,
            market_regime=str(market_state.get("market_regime") or "unknown"),
            preferred_side=preferred_side,
            course_context={
                "dominant_family": dominant_family,
                "harmony_score": float(harmony.get("harmony_score") or 0.0),
                "support_score": knowledge_alignment.get("support_score"),
                "matched_context_count": knowledge_alignment.get("matched_context_count"),
                "top_matching_contexts": top_contexts,
                "operating_posture": harmony.get("operating_posture"),
            },
        )
        selected_side = str(side_probability_comparison.get("selected_side") or candidate_side).upper()
        if selected_side in {"BUY", "SELL"} and selected_side != candidate_side:
            candidate_side = selected_side
            historical_analogs = side_probability_comparison.get("sides", {}).get(selected_side, {}).get(
                "historical_analogs",
                historical_analogs,
            )
            evidence.append(
                "El comparador BUY/SELL cambió la vigilancia hacia "
                f"{selected_side}: {side_probability_comparison.get('selection_reason')}"
            )
        if historical_analogs.get("status") == "available":
            evidence.append(str(historical_analogs.get("summary")))
            if historical_analogs.get("bias") == "favorable":
                pattern_matches.append("Analogías M5 similares favorecieron este lado con frecuencia histórica suficiente.")
            elif historical_analogs.get("bias") == "unfavorable":
                missing_confirmations.append("Analogías M5 similares fallaron más de lo deseado; exigir confirmación final limpia.")
        evidence.append(str(side_probability_comparison.get("summary")))
        if cool_learning_memory.get("status") == "available":
            evidence.append(str(cool_learning_memory.get("summary")))
            course_alignment = cool_learning_memory.get("course_alignment") or {}
            if course_alignment:
                auto_protocols = list(course_alignment.get("auto_selected_protocols") or [])
                if auto_protocols:
                    pattern_matches.append(
                        "Protocolos aprendidos auto-seleccionados: " + ", ".join(auto_protocols[:3]) + "."
                    )
                    profile = course_alignment.get("learned_protocol_profile") or {}
                    evidence.append(
                        "Router de conocimiento activo: "
                        f"{profile.get('source')}; bonus={profile.get('score_bonus')}."
                    )
                evidence.append(
                    "Memoria de cursos: "
                    f"estado={course_alignment.get('status')}, "
                    f"score={course_alignment.get('course_score')}, "
                    f"accion={course_alignment.get('course_recommended_action')}."
                )
                if course_alignment.get("status") in {"aligned", "partial"}:
                    pattern_matches.extend(list(course_alignment.get("confirmations") or [])[:2])
                if course_alignment.get("status") in {"weak", "conflict"}:
                    missing_confirmations.extend(list(course_alignment.get("missing_steps") or [])[:2])
            policy_action = str(cool_learning_memory.get("policy_action") or "WAIT").upper()
            if policy_action in {"BUY", "SELL"} and policy_action != candidate_side:
                missing_confirmations.append(
                    f"Q-learning memory favorece {policy_action}; exigir confirmación extra antes de sostener {candidate_side}."
                )
            elif policy_action == candidate_side and cool_learning_memory.get("policy_quality") in {"moderate", "strong"}:
                pattern_matches.append("Q-learning historico respalda el lado candidato con estados similares.")
        professional_matrix = MaximoQuantV4MarketIntelligenceEngine._professional_decision_matrix(
            side_probability_comparison=side_probability_comparison,
            cool_learning_memory=cool_learning_memory,
            candidate_side=candidate_side,
            preferred_side=preferred_side,
            higher_timeframe_bias=higher_timeframe_bias,
            market_state=market_state,
            top_contexts=top_contexts,
            dominant_family=dominant_family,
            operational_family=operational_family,
            setup_maturity=setup_maturity,
            confidence=confidence,
            harmony_score=float(harmony.get("harmony_score") or 0.0),
            event_action=event_action,
            volatility_state=volatility_state,
            signal_detected=signal_detected,
            missing_for_execute=missing_for_execute,
            session_tags=session_tags,
        )
        evidence.append(str(professional_matrix.get("summary")))

        maturity_gap = round(max(0.0, 75.0 - setup_maturity), 2)
        near_execute = bool(
            setup_maturity >= 70.0
            and confidence >= 0.68
            and candidate_side in {"BUY", "SELL"}
            and event_action in {"allow", "watch"}
        )
        if near_execute and maturity_gap > 0:
            missing_confirmations.append(
                f"Faltan {maturity_gap} puntos de madurez para EXECUTE, pero el patrón aprendido ya merece vigilancia activa."
            )

        if candidate_side == "BUY":
            probable_move = "continuación o rebote alcista si M5 confirma cierre con intención y M1 sostiene microestructura."
            confirmation_focus = [
                "Cierre M5 alcista por encima de la zona de rechazo.",
                "M1 mantiene micro BOS/continuación sin absorber el impulso.",
                "HTF deja de estar neutral o al menos no contradice el BUY.",
            ]
        elif candidate_side == "SELL":
            probable_move = "continuación o rechazo bajista si M5 confirma cierre con intención y M1 sostiene microestructura."
            confirmation_focus = [
                "Cierre M5 bajista por debajo de la zona de rechazo.",
                "M1 mantiene micro BOS/continuación sin absorber el impulso.",
                "HTF deja de estar neutral o al menos no contradice el SELL.",
            ]
        else:
            probable_move = "definición de dirección; el mercado todavía no entregó lado dominante."
            confirmation_focus = [
                "Que el precio elija BUY o SELL con rechazo/desplazamiento claro.",
                "Que la vela M5 confirme intención y no solo ruido.",
                "Que el contexto macro y la ejecución permitan operar.",
            ]

        if signal_detected:
            confirmation_focus.append("Señal detectada: validar que ejecución, evento y riesgo sigan permitiendo entrada.")
        if event_action != "allow":
            confirmation_focus.append("Esperar que event_action vuelva a allow antes de cualquier orden.")
        if volatility_state in {"overextended", "weak"}:
            confirmation_focus.append("Evitar perseguir precio si la volatilidad no acompaña con estructura limpia.")

        return {
            "dominant_family": dominant_family,
            "operational_family": operational_family,
            "candidate_side": candidate_side,
            "preferred_side": preferred_side,
            "higher_timeframe_bias": higher_timeframe_bias,
            "probable_market_move": probable_move,
            "pattern_matches": pattern_matches[:6],
            "evidence": evidence[:8],
            "confirmation_focus": confirmation_focus,
            "missing_confirmations": MaximoQuantV4MarketIntelligenceEngine._dedupe_items(missing_confirmations),
            "near_execute_watch": near_execute,
            "maturity_gap_to_execute": maturity_gap,
            "historical_analogs": historical_analogs,
            "side_probability_comparison": side_probability_comparison,
            "cool_learning_memory": cool_learning_memory,
            "q_learning_memory": cool_learning_memory,
            "professional_decision_matrix": professional_matrix,
            "session_opportunity": professional_matrix.get("session_opportunity"),
            "interpretation": (
                "El conocimiento aprendido reconoce un patrón en desarrollo; no se debe ignorar por una pequeña diferencia numérica, "
                "pero la orden espera confirmación final y condiciones de ejecución seguras."
                if near_execute
                else "El conocimiento aprendido aporta contexto, pero el patrón todavía no está suficientemente preparado."
            ),
        }

    @staticmethod
    def _professional_decision_matrix(
        *,
        side_probability_comparison: dict[str, Any],
        cool_learning_memory: dict[str, Any] | None = None,
        candidate_side: str,
        preferred_side: str,
        higher_timeframe_bias: str,
        market_state: dict[str, Any],
        top_contexts: list[dict[str, Any]],
        dominant_family: str,
        operational_family: str,
        setup_maturity: float,
        confidence: float,
        harmony_score: float,
        event_action: str,
        volatility_state: str,
        signal_detected: bool,
        missing_for_execute: list[str],
        session_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        sides = side_probability_comparison.get("sides") or {}
        cool_learning_memory = cool_learning_memory or {}
        buy_probability = float((sides.get("BUY") or {}).get("probability_to_confirm") or 0.0)
        sell_probability = float((sides.get("SELL") or {}).get("probability_to_confirm") or 0.0)
        selected_side = str(side_probability_comparison.get("selected_side") or candidate_side or "NEUTRAL").upper()
        cool_policy = str(cool_learning_memory.get("policy_action") or "WAIT").upper()
        cool_values = cool_learning_memory.get("action_values") or {}
        course_alignment = cool_learning_memory.get("course_alignment") or {}
        if (
            cool_learning_memory.get("status") == "available"
            and cool_policy in {"BUY", "SELL"}
            and cool_policy != selected_side
            and float(cool_values.get(cool_policy, 0.0)) >= float(cool_values.get(selected_side, 0.0)) + 0.18
        ):
            selected_side = cool_policy
        probability_gap = round(abs(buy_probability - sell_probability), 4)
        market_regime = str(market_state.get("market_regime") or "unknown")
        expansion_subtype = str(market_state.get("expansion_subtype") or "none")
        active_contexts = [
            {
                "strategy_family": item.get("strategy_family"),
                "market_regime": item.get("market_regime"),
                "label": item.get("operability_label"),
                "score": item.get("score"),
            }
            for item in top_contexts[:3]
        ]
        side_assessments = {
            side: MaximoQuantV4MarketIntelligenceEngine._professional_side_assessment(
                side=side,
                side_data=sides.get(side) or {},
                selected_side=selected_side,
                preferred_side=preferred_side,
                higher_timeframe_bias=higher_timeframe_bias,
                market_state=market_state,
                event_action=event_action,
                volatility_state=volatility_state,
                signal_detected=signal_detected,
            )
            for side in ("BUY", "SELL")
        }
        if selected_side in {"BUY", "SELL"}:
            best_option_reason = side_assessments[selected_side]["professional_verdict"]
        else:
            best_option_reason = "Ningún lado tiene ventaja suficiente; esperar definición de liquidez y estructura."
        if cool_learning_memory.get("status") == "available":
            best_option_reason += (
                f" Q-learning memory propone {cool_learning_memory.get('policy_action')} "
                f"con calidad {cool_learning_memory.get('policy_quality')}."
            )
        if course_alignment:
            best_option_reason += (
                f" Cursos/reglas: {course_alignment.get('status')} "
                f"(score {course_alignment.get('course_score')})."
            )

        red_flags: list[str] = []
        if event_action != "allow":
            red_flags.append("Noticias/evento macro no permiten ejecución limpia.")
        if volatility_state in {"overextended", "weak"}:
            red_flags.append("Volatilidad no está en punto ideal para perseguir el movimiento.")
        if higher_timeframe_bias == "NEUTRAL":
            red_flags.append("HTF neutral: conviene exigir confirmación más limpia.")
        if probability_gap < 0.08:
            red_flags.append("BUY y SELL están demasiado cercanos; riesgo de chop o trampa.")
        if not signal_detected:
            red_flags.append("Todavía falta trigger final real.")
        if cool_learning_memory.get("status") == "available" and cool_policy in {"BUY", "SELL"} and cool_policy != selected_side:
            red_flags.append(f"Q-learning memory no está alineado: memoria histórica favorece {cool_policy}.")
        if course_alignment.get("status") == "conflict":
            red_flags.append("Memoria de cursos contradice la preparacion actual; esperar confirmacion superior.")
        elif course_alignment.get("status") == "weak":
            red_flags.append("Memoria de cursos reconoce pocos pasos completos del setup.")
        if missing_for_execute:
            red_flags.extend(missing_for_execute[:2])

        management_plan = MaximoQuantV4MarketIntelligenceEngine._professional_management_plan(
            selected_side=selected_side,
            setup_maturity=setup_maturity,
            confidence=confidence,
            harmony_score=harmony_score,
            event_action=event_action,
            volatility_state=volatility_state,
        )
        probability_read = "alta" if max(buy_probability, sell_probability) >= 0.78 else "media" if max(buy_probability, sell_probability) >= 0.62 else "baja"
        summary = (
            f"Matriz profesional: mejor lado {selected_side} con probabilidad {probability_read}; "
            f"BUY={buy_probability:.2f}, SELL={sell_probability:.2f}, gap={probability_gap:.2f}. "
            f"Esperar liquidez/confirmación antes de ejecutar."
        )
        session_opportunity = MaximoQuantV4MarketIntelligenceEngine._session_opportunity_score(
            selected_side=selected_side,
            session_tags=session_tags or [],
            volatility_state=volatility_state,
            event_action=event_action,
            signal_detected=signal_detected,
            probability=max(buy_probability, sell_probability),
            probability_gap=probability_gap,
            side_assessment=side_assessments.get(selected_side, {}) if selected_side in {"BUY", "SELL"} else {},
            cool_learning_memory=cool_learning_memory,
            course_alignment=course_alignment,
        )
        if session_opportunity["status"] in {"london_focus", "new_york_focus", "ny_am_focus"}:
            best_option_reason += f" Sesión activa: {session_opportunity['interpretation']}"
        layer_synchronization = MaximoQuantV4MarketIntelligenceEngine._layer_synchronization(
            selected_side=selected_side,
            preferred_side=preferred_side,
            side_probability_selected=str(side_probability_comparison.get("selected_side") or "NEUTRAL").upper(),
            cool_policy=cool_policy,
            course_alignment=course_alignment,
        )
        return {
            "summary": summary,
            "selected_side": selected_side,
            "probability_gap": probability_gap,
            "probability_quality": probability_read,
            "market_regime": market_regime,
            "expansion_subtype": expansion_subtype,
            "course_pattern_memory": {
                "dominant_family": dominant_family,
                "operational_family": operational_family,
                "top_matching_contexts": active_contexts,
                "auto_selected_protocols": list(course_alignment.get("auto_selected_protocols") or []),
                "learned_protocol_profile": course_alignment.get("learned_protocol_profile") or {},
                "role": (
                    "motor_operativo_de_confirmaciones"
                    if course_alignment.get("auto_selected_protocols")
                    else "motor_de_contexto_y_filtro_de_calidad"
                ),
            },
            "cool_learning_memory": cool_learning_memory,
            "q_learning_memory": cool_learning_memory,
            "course_learning_sync": course_alignment,
            "layer_synchronization": layer_synchronization,
            "session_opportunity": session_opportunity,
            "side_assessments": side_assessments,
            "best_option_reason": best_option_reason,
            "wait_for_liquidity_volatility": (
                "Esperar barrida/rechazo de liquidez y vela M5 con cuerpo real; evitar entrada si el movimiento ya se extendió sin pullback."
            ),
            "red_flags": MaximoQuantV4MarketIntelligenceEngine._dedupe_items(red_flags),
            "management_plan": management_plan,
            "execution_principle": (
                "La matriz decide qué oportunidad preparar; la orden solo se permite con signal_detected=true, SL lógico, RR evaluable, macro allow y broker/demo válido."
            ),
        }

    @staticmethod
    def _layer_synchronization(
        *,
        selected_side: str,
        preferred_side: str,
        side_probability_selected: str,
        cool_policy: str,
        course_alignment: dict[str, Any],
    ) -> dict[str, Any]:
        sides = {
            "professional_matrix": str(selected_side or "NEUTRAL").upper(),
            "market_preference": str(preferred_side or "NEUTRAL").upper(),
            "buy_sell_probability": str(side_probability_selected or "NEUTRAL").upper(),
            "historical_q_learning": str(cool_policy or "WAIT").upper(),
            "course_memory": str(course_alignment.get("course_recommended_action") or "WAIT").upper(),
        }
        actionable = {key: value for key, value in sides.items() if value in {"BUY", "SELL"}}
        selected = str(selected_side or "NEUTRAL").upper()
        agreements = [key for key, value in actionable.items() if value == selected]
        conflicts = [
            f"{key}={value}"
            for key, value in actionable.items()
            if selected in {"BUY", "SELL"} and value != selected
        ]
        course_status = str(course_alignment.get("status") or "unknown")
        if selected not in {"BUY", "SELL"}:
            status = "waiting_direction"
        elif conflicts and course_status == "conflict":
            status = "conflicted"
        elif len(agreements) >= 4 and course_status in {"aligned", "partial"}:
            status = "synchronized"
        elif len(agreements) >= 3:
            status = "mostly_aligned"
        else:
            status = "partial"
        return {
            "status": status,
            "agreement_score": round(len(agreements) / max(1, len(actionable)), 4),
            "selected_side": selected,
            "layers": sides,
            "agreeing_layers": agreements,
            "conflicts": conflicts,
            "course_status": course_status,
            "interpretation": (
                "Las capas principales apuntan al mismo lado; mantener vigilancia hasta trigger final."
                if status in {"synchronized", "mostly_aligned"}
                else "Las capas aun no estan completamente sincronizadas; preparar, pero no forzar entrada."
            ),
        }

    @staticmethod
    def _professional_side_assessment(
        *,
        side: str,
        side_data: dict[str, Any],
        selected_side: str,
        preferred_side: str,
        higher_timeframe_bias: str,
        market_state: dict[str, Any],
        event_action: str,
        volatility_state: str,
        signal_detected: bool,
        session_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        side_lower = side.lower()
        checks = ((market_state.get("ob_rejection_families") or {}).get("aggressive") or {}).get("checks", {}) or {}
        institutional_checks = ((market_state.get("ob_rejection_families") or {}).get("institutional") or {}).get("checks", {}) or {}
        liquidity_ok = bool(institutional_checks.get(f"liquidity_quality_{side_lower}"))
        pullback_ok = bool(institutional_checks.get(f"pullback_{side_lower}"))
        displacement_ok = bool(
            checks.get("partial_bull_displacement" if side == "BUY" else "partial_bear_displacement")
            or institutional_checks.get("bull_displacement" if side == "BUY" else "bear_displacement")
        )
        micro_bos = bool(checks.get("micro_bos_buy" if side == "BUY" else "micro_bos_sell"))
        continuation = bool(checks.get("continuation_momentum_buy" if side == "BUY" else "continuation_momentum_sell"))
        wick_quality = float(market_state.get("wick_rejection_pct_buy" if side == "BUY" else "wick_rejection_pct_sell") or 0.0)
        mtf_score = int(market_state.get("buy_mtf_score" if side == "BUY" else "sell_mtf_score") or 0)
        analogs = side_data.get("historical_analogs") or {}
        probability = float(side_data.get("probability_to_confirm") or 0.0)
        if side == selected_side:
            status = "best_candidate"
        elif probability >= 0.60:
            status = "valid_alternative_watch"
        else:
            status = "weak_alternative"

        if event_action != "allow":
            news_read = "macro_watch_or_block"
        else:
            news_read = "macro_clear"
        if volatility_state in {"tradable_normal", "expanding_with_force"}:
            volatility_timing = "usable_si_confirma_rapido"
        elif volatility_state == "overextended":
            volatility_timing = "esperar_pullback_no_perseguir"
        else:
            volatility_timing = "esperar_mas_energia"

        vulnerability = (
            "Buscar barrida de liquidez bajista y rechazo para BUY."
            if side == "BUY"
            else "Buscar barrida de liquidez alcista y rechazo para SELL."
        )
        professional_verdict = (
            f"{side} es candidato principal: prob={probability:.2f}, analog_bias={analogs.get('bias')}, "
            f"MTF={mtf_score}, liquidez={liquidity_ok}, micro_bos={micro_bos}, continuation={continuation}."
            if side == selected_side
            else f"{side} queda como alternativa: prob={probability:.2f}, necesita superar al lado principal con confirmación limpia."
        )
        blockers = []
        if higher_timeframe_bias not in {side, "NEUTRAL"}:
            blockers.append("HTF contrario.")
        if not signal_detected:
            blockers.append("Sin trigger final.")
        if event_action != "allow":
            blockers.append("Macro no allow.")

        return {
            "status": status,
            "probability_to_confirm": round(probability, 4),
            "preferred_alignment": side == preferred_side,
            "htf_alignment": higher_timeframe_bias in {side, "NEUTRAL"},
            "mtf_score": mtf_score,
            "historical_bias": analogs.get("bias"),
            "historical_win_rate": analogs.get("win_rate"),
            "historical_failure_rate": analogs.get("failure_rate"),
            "liquidity_read": {
                "liquidity_sweep_or_grab": liquidity_ok,
                "pullback_present": pullback_ok,
                "wick_rejection_quality": round(wick_quality, 4),
            },
            "structure_read": {
                "displacement": displacement_ok,
                "micro_bos": micro_bos,
                "continuation_momentum": continuation,
            },
            "volatility_timing": volatility_timing,
            "news_read": news_read,
            "vulnerability_to_attack": vulnerability,
            "confirmation_needed": list(side_data.get("confirmation_needed", [])),
            "blockers": blockers,
            "professional_verdict": professional_verdict,
        }

    @staticmethod
    def _professional_management_plan(
        *,
        selected_side: str,
        setup_maturity: float,
        confidence: float,
        harmony_score: float,
        event_action: str,
        volatility_state: str,
    ) -> dict[str, Any]:
        if selected_side not in {"BUY", "SELL"}:
            risk_mode = "blocked"
        elif setup_maturity >= 80 and confidence >= 0.78 and harmony_score >= 0.60 and event_action == "allow":
            risk_mode = "normal_candidate"
        else:
            risk_mode = "reduced_candidate"
        return {
            "risk_mode_recommendation": risk_mode,
            "entry_timing": "Entrar solo al cierre/trigger confirmado, evitando perseguir una vela extendida.",
            "emergency_exit": "Cerrar o proteger si aparece vela contraria fuerte, spread se degrada, macro cambia a block/watch o M1 invalida microestructura.",
            "take_profit_plan": "TP1 en primera liquidez/opuesto cercano; proteger parcial y dejar TP2 hacia siguiente pool si el impulso sigue limpio.",
            "trailing_plan": "Después de 0.8R-1R, mover a BE/proteger parcial; trailing detrás de estructura M1/M5 o último swing válido.",
            "time_in_trade_preference": (
                "Preferir trade corto y eficiente durante expansión limpia."
                if volatility_state in {"tradable_normal", "expanding_with_force"}
                else "Esperar mejor volatilidad; evitar permanecer mucho tiempo en mercado lento."
            ),
        }

    @staticmethod
    def _side_probability_comparison(
        *,
        snapshot: dict[str, Any],
        preferred_side: str,
        initial_candidate_side: str,
        higher_timeframe_bias: str,
        dominant_family: str,
        market_regime: str,
        setup_maturity: float,
        confidence: float,
        harmony_score: float,
        event_action: str,
        volatility_state: str,
        signal_detected: bool,
        session_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        sides: dict[str, Any] = {}
        preferred_side = str(preferred_side or "NEUTRAL").upper()
        initial_candidate_side = str(initial_candidate_side or "NEUTRAL").upper()
        higher_timeframe_bias = str(higher_timeframe_bias or "NEUTRAL").upper()

        for side in ("BUY", "SELL"):
            analogs = MaximoQuantV4MarketIntelligenceEngine._historical_pattern_analogs(
                snapshot=snapshot,
                side=side,
                dominant_family=dominant_family,
                market_regime=market_regime,
            )
            probability = MaximoQuantV4MarketIntelligenceEngine._side_probability_score(
                analogs=analogs,
                side=side,
                preferred_side=preferred_side,
                initial_candidate_side=initial_candidate_side,
                higher_timeframe_bias=higher_timeframe_bias,
                setup_maturity=setup_maturity,
                confidence=confidence,
                harmony_score=harmony_score,
                event_action=event_action,
                volatility_state=volatility_state,
                signal_detected=signal_detected,
                session_tags=session_tags or [],
            )
            sides[side] = {
                "side": side,
                "probability_to_confirm": probability,
                "historical_analogs": analogs,
                "confirmation_needed": MaximoQuantV4MarketIntelligenceEngine._side_confirmation_needed(
                    side=side,
                    higher_timeframe_bias=higher_timeframe_bias,
                    event_action=event_action,
                    signal_detected=signal_detected,
                ),
                "status": "preferred" if side == preferred_side else "alternative_watch",
            }

        buy_probability = float(sides["BUY"]["probability_to_confirm"])
        sell_probability = float(sides["SELL"]["probability_to_confirm"])
        selected_side = initial_candidate_side if initial_candidate_side in {"BUY", "SELL"} else preferred_side
        selection_reason = "Se mantiene el lado candidato/preferido porque no hay ventaja alternativa suficiente."

        if preferred_side not in {"BUY", "SELL"}:
            selected_side = "BUY" if buy_probability >= sell_probability else "SELL"
            selection_reason = "El mercado no tiene preferred_side fuerte; se elige el lado con mayor probabilidad observacional."
        else:
            opposite = "SELL" if preferred_side == "BUY" else "BUY"
            preferred_probability = float(sides[preferred_side]["probability_to_confirm"])
            opposite_probability = float(sides[opposite]["probability_to_confirm"])
            preferred_bias = str(sides[preferred_side]["historical_analogs"].get("bias") or "")
            opposite_bias = str(sides[opposite]["historical_analogs"].get("bias") or "")
            if (
                higher_timeframe_bias in {"NEUTRAL", opposite}
                and opposite_probability >= preferred_probability + 0.12
                and preferred_bias == "unfavorable"
                and opposite_bias in {"favorable", "mixed"}
            ):
                selected_side = opposite
                selection_reason = (
                    f"{opposite} supera a {preferred_side} por probabilidad/analogías y el HTF no lo invalida."
                )

        should_watch_alternative = abs(buy_probability - sell_probability) <= 0.12 or selected_side != preferred_side
        summary = (
            "Comparación dual: "
            f"BUY={buy_probability:.2f}, SELL={sell_probability:.2f}, "
            f"seleccionado={selected_side}; {selection_reason}"
        )
        return {
            "selected_side": selected_side if selected_side in {"BUY", "SELL"} else "NEUTRAL",
            "preferred_side": preferred_side,
            "should_watch_alternative": should_watch_alternative,
            "selection_reason": selection_reason,
            "summary": summary,
            "sides": sides,
        }

    @staticmethod
    def _side_probability_score(
        *,
        analogs: dict[str, Any],
        side: str,
        preferred_side: str,
        initial_candidate_side: str,
        higher_timeframe_bias: str,
        setup_maturity: float,
        confidence: float,
        harmony_score: float,
        event_action: str,
        volatility_state: str,
        signal_detected: bool,
        session_tags: list[str] | None = None,
    ) -> float:
        probability = 0.5
        if analogs.get("status") == "available":
            win_rate = float(analogs.get("win_rate") or 0.0)
            failure_rate = float(analogs.get("failure_rate") or 0.0)
            matches = int(analogs.get("matches_found") or 0)
            probability += (win_rate - failure_rate) * 0.35
            probability += min(0.08, matches * 0.006)
            if analogs.get("bias") == "favorable":
                probability += 0.06
            elif analogs.get("bias") == "unfavorable":
                probability -= 0.06
        elif analogs.get("status") in {"insufficient_data", "no_close_match"}:
            probability -= 0.03

        if side == preferred_side:
            probability += 0.12
        elif preferred_side in {"BUY", "SELL"}:
            probability -= 0.04
        if side == initial_candidate_side:
            probability += 0.04
        if side == higher_timeframe_bias:
            probability += 0.08
        elif higher_timeframe_bias in {"BUY", "SELL"}:
            probability -= 0.08

        quality_average = (min(1.0, setup_maturity / 100.0) + confidence + harmony_score) / 3.0
        probability += (quality_average - 0.5) * 0.22
        if signal_detected:
            probability += 0.07
        if event_action == "watch":
            probability -= 0.05
        elif event_action == "block":
            probability -= 0.25
        if volatility_state in {"tradable_normal", "expanding_with_force"}:
            probability += 0.04
        elif volatility_state in {"overextended", "weak"}:
            probability -= 0.06
        tags = {str(item).lower() for item in session_tags or []}
        if tags & {"london", "new_york", "ny_am", "ny_pm"}:
            if event_action == "allow" and volatility_state in {"tradable_normal", "expanding_with_force"}:
                probability += 0.05
            if analogs.get("bias") == "favorable":
                probability += 0.03

        return round(max(0.0, min(1.0, probability)), 4)

    @staticmethod
    def _session_opportunity_score(
        *,
        selected_side: str,
        session_tags: list[str],
        volatility_state: str,
        event_action: str,
        signal_detected: bool,
        probability: float,
        probability_gap: float,
        side_assessment: dict[str, Any],
        cool_learning_memory: dict[str, Any],
        course_alignment: dict[str, Any],
    ) -> dict[str, Any]:
        tags = {str(item).lower() for item in session_tags or []}
        if "ny_am" in tags:
            status = "ny_am_focus"
        elif "new_york" in tags:
            status = "new_york_focus"
        elif "london" in tags:
            status = "london_focus"
        else:
            status = "off_focus_session"
        score = 0.0
        reasons: list[str] = []
        if status != "off_focus_session":
            score += 0.22
            reasons.append("sesión de alto desplazamiento activa")
        if volatility_state in {"tradable_normal", "expanding_with_force"}:
            score += 0.18
            reasons.append("volatilidad utilizable")
        if event_action == "allow":
            score += 0.14
            reasons.append("macro permite operar")
        if selected_side in {"BUY", "SELL"}:
            score += 0.1
            reasons.append(f"lado operativo definido: {selected_side}")
        if probability >= 0.72:
            score += 0.14
            reasons.append("probabilidad observacional alta")
        if probability_gap >= 0.12:
            score += 0.08
            reasons.append("ventaja clara sobre el lado contrario")
        if side_assessment.get("historical_bias") == "favorable":
            score += 0.12
            reasons.append("analogías históricas favorables")
        if str(cool_learning_memory.get("policy_action") or "").upper() == selected_side:
            score += 0.08
            reasons.append("Q-learning de patrones coincide")
        if course_alignment.get("status") in {"aligned", "partial"}:
            score += 0.06
            reasons.append("memoria de cursos acompaña")
        if signal_detected:
            score += 0.08
            reasons.append("trigger final detectado")
        score = round(min(1.0, score), 4)
        readiness = "execute_ready" if signal_detected and score >= 0.78 else "armed" if score >= 0.68 else "forming" if score >= 0.5 else "weak"
        return {
            "status": status,
            "score": score,
            "readiness": readiness,
            "session_tags": sorted(tags),
            "reasons": reasons,
            "interpretation": (
                "Londres/Nueva York están dando contexto útil; mantener el arma cargada y exigir solo trigger limpio."
                if readiness in {"armed", "execute_ready"}
                else "La sesión aún no entrega suficiente desplazamiento o alineación para apretar el gatillo."
            ),
        }

    @staticmethod
    def _session_tags_from_market_state(market_state: dict[str, Any]) -> list[str]:
        tags = [str(item).lower() for item in market_state.get("session_tags", []) or [] if item]
        if tags:
            return sorted(set(tags))
        try:
            hour = int(market_state.get("hour_ny"))
        except (TypeError, ValueError):
            return []
        result: list[str] = []
        if 2 <= hour <= 5:
            result.append("london")
        if 8 <= hour <= 16:
            result.append("new_york")
        if hour == 9:
            result.append("ny_am")
        if hour == 15:
            result.append("ny_pm")
        return result

    @staticmethod
    def _side_confirmation_needed(
        *,
        side: str,
        higher_timeframe_bias: str,
        event_action: str,
        signal_detected: bool,
    ) -> list[str]:
        if side == "BUY":
            items = [
                "Cierre M5 alcista con cuerpo real y rechazo de la zona vigilada.",
                "M1 confirma micro BOS/continuación BUY sin absorción inmediata.",
            ]
        else:
            items = [
                "Cierre M5 bajista con cuerpo real y rechazo de la zona vigilada.",
                "M1 confirma micro BOS/continuación SELL sin absorción inmediata.",
            ]
        if higher_timeframe_bias == "NEUTRAL":
            items.append("HTF debe dejar de estar neutral o no contradecir el lado candidato.")
        elif higher_timeframe_bias not in {side, "NEUTRAL"}:
            items.append(f"HTF está contra {side}; exigir ruptura/confirmación más limpia.")
        if not signal_detected:
            items.append("Debe aparecer signal_detected=true antes de cualquier orden.")
        if event_action != "allow":
            items.append("El evento macro debe volver a allow.")
        return items

    @staticmethod
    def _historical_pattern_analogs(
        *,
        snapshot: dict[str, Any],
        side: str,
        dominant_family: str,
        market_regime: str,
        window: int = 12,
        horizon: int = 8,
        max_matches: int = 12,
    ) -> dict[str, Any]:
        """Compare the current M5 shape with prior M5 windows.

        This is read-only market memory: it informs confidence and reporting, but
        never bypasses signal, SL/RR, event, spread or demo/broker guards.
        """

        candles = MaximoQuantV4MarketIntelligenceEngine._snapshot_candles(snapshot, "M5")
        side = str(side or "NEUTRAL").upper()
        if side not in {"BUY", "SELL"}:
            return {
                "status": "no_direction",
                "summary": "No hay lado BUY/SELL definido para buscar analogías históricas.",
                "matches_found": 0,
            }
        if len(candles) < window * 4 + horizon:
            return {
                "status": "insufficient_data",
                "summary": "No hay suficientes velas M5 para comparar patrones históricos similares.",
                "matches_found": 0,
            }

        current_window = candles[-window:]
        current_signature = MaximoQuantV4MarketIntelligenceEngine._window_signature(current_window)
        if not current_signature:
            return {
                "status": "insufficient_shape",
                "summary": "La forma actual no tiene rango suficiente para crear una firma comparable.",
                "matches_found": 0,
            }

        candidates: list[dict[str, Any]] = []
        last_start = len(candles) - window - horizon - window
        for start in range(0, max(0, last_start), 3):
            prior_window = candles[start : start + window]
            prior_signature = MaximoQuantV4MarketIntelligenceEngine._window_signature(prior_window)
            if not prior_signature:
                continue
            similarity = MaximoQuantV4MarketIntelligenceEngine._signature_similarity(current_signature, prior_signature)
            if similarity < 0.72:
                continue
            outcome = MaximoQuantV4MarketIntelligenceEngine._analog_outcome(
                candles=candles,
                start=start,
                window=window,
                horizon=horizon,
                side=side,
            )
            candidates.append(
                {
                    "start_index": start,
                    "end_index": start + window - 1,
                    "similarity": round(similarity, 4),
                    **outcome,
                }
            )

        candidates = sorted(candidates, key=lambda item: item["similarity"], reverse=True)[:max_matches]
        if not candidates:
            return {
                "status": "no_close_match",
                "summary": "No aparecieron analogías M5 suficientemente parecidas en la muestra reciente.",
                "matches_found": 0,
                "dominant_family": dominant_family,
                "market_regime": market_regime,
            }

        wins = sum(1 for item in candidates if item["outcome"] == "favorable")
        failures = sum(1 for item in candidates if item["outcome"] == "failed")
        neutrals = len(candidates) - wins - failures
        win_rate = round(wins / len(candidates), 4)
        failure_rate = round(failures / len(candidates), 4)
        if win_rate >= 0.58 and wins >= failures + 1:
            bias = "favorable"
        elif failure_rate >= 0.42 and failures > wins:
            bias = "unfavorable"
        else:
            bias = "mixed"

        summary = (
            f"Analogías históricas M5 para {side}: {len(candidates)} similares, "
            f"{wins} favorables, {failures} fallidas, {neutrals} neutras; sesgo={bias}."
        )
        return {
            "status": "available",
            "dominant_family": dominant_family,
            "market_regime": market_regime,
            "side": side,
            "sample_timeframe": "M5",
            "lookback_candles": len(candles),
            "window_candles": window,
            "horizon_candles": horizon,
            "matches_found": len(candidates),
            "favorable_count": wins,
            "failed_count": failures,
            "neutral_count": neutrals,
            "win_rate": win_rate,
            "failure_rate": failure_rate,
            "bias": bias,
            "summary": summary,
            "top_matches": candidates[:5],
            "note": "Comparación observacional; no ejecuta ni desbloquea órdenes sin confirmación final.",
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

    @staticmethod
    def _window_signature(candles: list[Any]) -> list[float]:
        if not candles:
            return []
        highs = [MaximoQuantV4MarketIntelligenceEngine._candle_value(item, "high") for item in candles]
        lows = [MaximoQuantV4MarketIntelligenceEngine._candle_value(item, "low") for item in candles]
        closes = [MaximoQuantV4MarketIntelligenceEngine._candle_value(item, "close") for item in candles]
        opens = [MaximoQuantV4MarketIntelligenceEngine._candle_value(item, "open") for item in candles]
        price_range = max(highs) - min(lows)
        if price_range <= 0:
            return []
        base = closes[0]
        signature: list[float] = []
        for open_price, close_price in zip(opens, closes):
            signature.append(round((close_price - base) / price_range, 5))
            signature.append(round((close_price - open_price) / price_range, 5))
        return signature

    @staticmethod
    def _signature_similarity(current: list[float], prior: list[float]) -> float:
        if not current or len(current) != len(prior):
            return 0.0
        avg_abs_diff = sum(abs(a - b) for a, b in zip(current, prior)) / len(current)
        return max(0.0, min(1.0, 1.0 - avg_abs_diff))

    @staticmethod
    def _analog_outcome(
        *,
        candles: list[Any],
        start: int,
        window: int,
        horizon: int,
        side: str,
    ) -> dict[str, Any]:
        prior_window = candles[start : start + window]
        future = candles[start + window : start + window + horizon]
        entry = MaximoQuantV4MarketIntelligenceEngine._candle_value(prior_window[-1], "close")
        window_high = max(MaximoQuantV4MarketIntelligenceEngine._candle_value(item, "high") for item in prior_window)
        window_low = min(MaximoQuantV4MarketIntelligenceEngine._candle_value(item, "low") for item in prior_window)
        threshold = max((window_high - window_low) * 0.35, abs(entry) * 0.0005)
        future_high = max(MaximoQuantV4MarketIntelligenceEngine._candle_value(item, "high") for item in future)
        future_low = min(MaximoQuantV4MarketIntelligenceEngine._candle_value(item, "low") for item in future)
        if side == "BUY":
            favorable_move = future_high - entry
            adverse_move = entry - future_low
        else:
            favorable_move = entry - future_low
            adverse_move = future_high - entry
        if favorable_move >= threshold and favorable_move >= adverse_move:
            outcome = "favorable"
        elif adverse_move >= threshold and adverse_move > favorable_move:
            outcome = "failed"
        else:
            outcome = "neutral"
        return {
            "outcome": outcome,
            "favorable_move": round(favorable_move, 3),
            "adverse_move": round(adverse_move, 3),
            "threshold": round(threshold, 3),
        }

    @staticmethod
    def _dedupe_items(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = str(item).strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    def _write_outputs(self, payload: dict[str, Any]) -> None:
        self.latest_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# MAXIMO Quant v4 Market Intelligence",
            "",
            f"- generated_at_utc: {payload['generated_at_utc']}",
            f"- symbol: {payload['symbol']}",
            f"- strategy_variant: {payload['strategy_variant']}",
            f"- action: {payload['execution_readiness']['action']}",
            f"- confidence: {payload['execution_readiness']['confidence']}",
            "",
            "## Execution Readiness",
        ]
        for line in payload["execution_readiness"]["rationale"]:
            lines.append(f"- {line}")
        if payload["execution_readiness"]["blockers"]:
            lines.append("")
            lines.append("### Blockers")
            for blocker in payload["execution_readiness"]["blockers"]:
                lines.append(f"- {blocker}")
        lines.extend(
            [
                "",
                "## Event Risk",
                f"- action: {payload['event_risk']['action']}",
                f"- sync_status: {payload['event_risk'].get('sync_status', {}).get('status')}",
                f"- highest_active_impact: {payload['event_risk']['highest_active_impact']}",
                f"- highest_upcoming_impact: {payload['event_risk']['highest_upcoming_impact']}",
                "",
                "## Volatility Intelligence",
                f"- state: {payload['volatility_intelligence']['state']}",
                f"- action: {payload['volatility_intelligence']['action']}",
                f"- atr_ratio: {payload['volatility_intelligence']['atr_ratio']}",
                f"- range_ratio: {payload['volatility_intelligence']['range_ratio']}",
                "",
                "## Knowledge Harmony",
                f"- harmony_score: {payload['overview']['knowledge_alignment'].get('harmony', {}).get('harmony_score')}",
                f"- operating_posture: {payload['overview']['knowledge_alignment'].get('harmony', {}).get('operating_posture')}",
            ]
        )
        if payload.get("watch_trigger"):
            trigger = payload["watch_trigger"]
            lines.extend(
                [
                    "",
                    "## Watch Trigger",
                    f"- side: {trigger['side']}",
                    f"- trigger_type: {trigger['trigger_type']}",
                    f"- strategy_selected: {trigger['strategy_selected']}",
                    f"- setup_detected: {trigger['setup_detected']}",
                    f"- operational_family: {trigger.get('operational_family')}",
                ]
            )
            lines.append("- required_conditions:")
            for item in trigger["required_conditions"]:
                lines.append(f"  - {item}")
            lines.append("- cancel_conditions:")
            for item in trigger["cancel_conditions"]:
                lines.append(f"  - {item}")
            if trigger.get("missing_for_execute"):
                lines.append("- missing_for_execute:")
                for item in trigger["missing_for_execute"]:
                    lines.append(f"  - {item}")
            projection = trigger.get("pattern_projection") or {}
            if projection:
                lines.extend(
                    [
                        "",
                        "### Learned Pattern Projection",
                        f"- candidate_side: {projection.get('candidate_side')}",
                        f"- probable_market_move: {projection.get('probable_market_move')}",
                        f"- near_execute_watch: {projection.get('near_execute_watch')}",
                        f"- maturity_gap_to_execute: {projection.get('maturity_gap_to_execute')}",
                        f"- interpretation: {projection.get('interpretation')}",
                        "- pattern_matches:",
                    ]
                )
                for item in projection.get("pattern_matches", []):
                    lines.append(f"  - {item}")
                lines.append("- evidence:")
                for item in projection.get("evidence", []):
                    lines.append(f"  - {item}")
                lines.append("- confirmation_focus:")
                for item in projection.get("confirmation_focus", []):
                    lines.append(f"  - {item}")
                analogs = projection.get("historical_analogs") or {}
                if analogs:
                    lines.extend(
                        [
                            "- historical_analogs:",
                            f"  - status: {analogs.get('status')}",
                            f"  - summary: {analogs.get('summary')}",
                            f"  - bias: {analogs.get('bias')}",
                            f"  - win_rate: {analogs.get('win_rate')}",
                            f"  - failure_rate: {analogs.get('failure_rate')}",
                        ]
                    )
                comparison = projection.get("side_probability_comparison") or {}
                if comparison:
                    lines.extend(
                        [
                            "- side_probability_comparison:",
                            f"  - selected_side: {comparison.get('selected_side')}",
                            f"  - should_watch_alternative: {comparison.get('should_watch_alternative')}",
                            f"  - selection_reason: {comparison.get('selection_reason')}",
                        ]
                    )
                    for side, side_data in (comparison.get("sides") or {}).items():
                        lines.append(
                            f"  - {side}: probability={side_data.get('probability_to_confirm')} "
                            f"status={side_data.get('status')}"
                        )
                        confirmations = list(side_data.get("confirmation_needed", []) or [])
                        if confirmations:
                            lines.append(f"    - confirmation_needed: {confirmations[0]}")
                cool = projection.get("cool_learning_memory") or {}
                if cool:
                    lines.extend(
                        [
                            "- q_learning_memory:",
                            f"  - status: {cool.get('status')}",
                            f"  - learning_method: {cool.get('learning_method')}",
                            f"  - q_update_mode: {cool.get('q_update_mode')}",
                            f"  - summary: {cool.get('summary')}",
                            f"  - q_policy_action: {cool.get('q_policy_action') or cool.get('policy_action')}",
                            f"  - policy_quality: {cool.get('policy_quality')}",
                            f"  - confidence: {cool.get('confidence')}",
                            f"  - q_values: {cool.get('q_values') or cool.get('action_values')}",
                            f"  - action_win_rates: {cool.get('action_win_rates')}",
                        ]
                    )
                professional = projection.get("professional_decision_matrix") or {}
                if professional:
                    lines.extend(
                        [
                            "- professional_decision_matrix:",
                            f"  - summary: {professional.get('summary')}",
                            f"  - selected_side: {professional.get('selected_side')}",
                            f"  - probability_quality: {professional.get('probability_quality')}",
                            f"  - best_option_reason: {professional.get('best_option_reason')}",
                            f"  - wait_for_liquidity_volatility: {professional.get('wait_for_liquidity_volatility')}",
                        ]
                    )
                    management = professional.get("management_plan") or {}
                    if management:
                        lines.extend(
                            [
                                "  - management_plan:",
                                f"    - risk_mode_recommendation: {management.get('risk_mode_recommendation')}",
                                f"    - emergency_exit: {management.get('emergency_exit')}",
                                f"    - take_profit_plan: {management.get('take_profit_plan')}",
                                f"    - trailing_plan: {management.get('trailing_plan')}",
                            ]
                        )
                    for item in professional.get("red_flags", [])[:5]:
                        lines.append(f"  - red_flag: {item}")
        self.latest_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _append_log(self, payload: dict[str, Any]) -> None:
        fields = [
            "timestamp_utc",
            "symbol",
            "strategy_variant",
            "action",
            "confidence",
            "market_regime",
            "preferred_side",
            "signal_detected",
            "event_action",
            "volatility_state",
            "can_execute_demo_now",
            "blockers",
        ]
        row = {
            "timestamp_utc": payload["generated_at_utc"],
            "symbol": payload["symbol"],
            "strategy_variant": payload["strategy_variant"],
            "action": payload["execution_readiness"]["action"],
            "confidence": payload["execution_readiness"]["confidence"],
            "market_regime": payload["overview"]["market_state"].get("market_regime"),
            "preferred_side": payload["overview"]["market_state"].get("preferred_side"),
            "signal_detected": payload["overview"]["signal"] is not None,
            "event_action": payload["event_risk"]["action"],
            "volatility_state": payload["volatility_intelligence"]["state"],
            "can_execute_demo_now": payload["execution_readiness"]["can_execute_demo_now"],
            "blockers": "|".join(payload["execution_readiness"]["blockers"]),
        }
        write_header = not self.log_path.exists()
        with self.log_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
