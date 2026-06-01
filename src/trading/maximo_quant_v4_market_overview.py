"""Market overview and decision orchestration for MAXIMO MTF Quant v4."""

from __future__ import annotations

import csv
from dataclasses import replace
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.core.config import Settings
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester, NY_TZ, StrategyVariant
from src.trading.market_knowledge_harmonizer import MarketKnowledgeHarmonizer
from src.trading.maximo_quant_v4_yearly_analyzer import MaximoQuantV4YearlyAnalyzer
from src.trading.mt5_bridge import MT5Bridge

RD_TZ = ZoneInfo("America/Santo_Domingo")


class MaximoQuantV4MarketOverviewEngine:
    """Build a current market view and trading decision from live MT5 data plus learned knowledge."""

    def __init__(self, settings: Settings, *, bridge: MT5Bridge | None = None) -> None:
        self.settings = settings
        self.bridge = bridge or MT5Bridge(settings)
        self.output_dir = self.settings.paths.data_dir / "market_analysis" / "maximo_quant_v4"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.latest_json_path = self.output_dir / "latest_market_overview.json"
        self.latest_md_path = self.output_dir / "latest_market_overview.md"
        self.decision_log_path = self.output_dir / "decision_log.csv"
        self.strategy_snapshot_path = self.settings.paths.data_dir / "strategies" / "maximo_quant_v4_best_current.json"
        self.market_map_path = self.settings.paths.knowledge_dir / "market_situation_map.json"
        self.harmonizer = MarketKnowledgeHarmonizer()

    def run(self, *, symbol: str) -> dict[str, Any]:
        payload = self.run_detailed(symbol=symbol)
        analysis = payload["analysis"]
        runtime = payload["runtime"]
        return {
            "strategy_name": "MAXIMO MTF Quant Institutional v4",
            "symbol": symbol,
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "action": analysis["decision"]["action"],
            "decision_confidence": analysis["decision"]["confidence"],
            "market_regime": analysis["market_state"]["market_regime"],
            "preferred_side": analysis["market_state"]["preferred_side"],
            "signal_detected": analysis["signal"] is not None,
            "top_strategy_family": analysis["knowledge_alignment"]["top_matching_contexts"][0]["strategy_family"]
            if analysis["knowledge_alignment"]["top_matching_contexts"]
            else None,
            "harmony_score": analysis["knowledge_alignment"].get("harmony", {}).get("harmony_score"),
            "operating_posture": analysis["knowledge_alignment"].get("harmony", {}).get("operating_posture"),
            "paths": {
                "latest_json": str(self.latest_json_path.resolve()),
                "latest_md": str(self.latest_md_path.resolve()),
                "decision_log_csv": str(self.decision_log_path.resolve()),
            },
        }

    def run_detailed(self, *, symbol: str) -> dict[str, Any]:
        runtime = self._load_runtime()
        market_map = self._load_market_map()
        snapshot = self.bridge.read_market_snapshot(
            symbol=symbol,
            bars_by_timeframe={"M1": 500, "M5": 5000, "H1": 2000},
        )
        analysis = self._analyze_snapshot(
            symbol=symbol,
            runtime=runtime,
            market_map=market_map,
            snapshot=snapshot["candles"],
        )
        self._write_outputs(symbol=symbol, runtime=runtime, snapshot=snapshot, analysis=analysis)
        self._append_decision_log(symbol=symbol, runtime=runtime, analysis=analysis)
        return {
            "runtime": runtime,
            "snapshot": snapshot,
            "analysis": analysis,
            "symbol": symbol,
        }

    def _load_runtime(self) -> dict[str, Any]:
        if not self.strategy_snapshot_path.exists():
            raise RuntimeError(f"Best strategy snapshot not found: {self.strategy_snapshot_path}")
        snapshot = json.loads(self.strategy_snapshot_path.read_text(encoding="utf-8"))
        analyzer = MaximoQuantV4YearlyAnalyzer(
            input_dir=self.settings.paths.data_dir / "backtests" / "input",
            backtests_dir=self.settings.paths.data_dir / "backtests",
            strategies_dir=self.settings.paths.data_dir / "strategies",
        )
        resolved = analyzer._resolve_runtime_variant(
            strategy_variant_code=str(snapshot["best_variant_code"]),
            session_variant_code=str(snapshot.get("session_variant", "all")),
        )
        resolved["strategy_variant"] = self._overlay_strategy_variant_from_snapshot(
            strategy_variant=resolved["strategy_variant"],
            snapshot=snapshot,
        )
        resolved["snapshot"] = snapshot
        return resolved

    @staticmethod
    def _overlay_strategy_variant_from_snapshot(
        *,
        strategy_variant: StrategyVariant,
        snapshot: dict[str, Any],
    ) -> StrategyVariant:
        parameters = snapshot.get("parameters", {}) if isinstance(snapshot, dict) else {}
        if not isinstance(parameters, dict) or not parameters:
            return strategy_variant

        overrides: dict[str, Any] = {}
        scalar_keys = (
            "code",
            "label",
            "a_plus_only",
            "require_preferred_side",
            "disallow_chop",
            "min_quant_score",
            "min_impulse_score",
            "require_recent_compression_for_agg",
            "require_quant_expansion",
            "require_recent_compression",
            "min_atr_ratio",
            "min_range_ratio",
            "max_atr_ratio",
            "max_range_ratio",
        )
        for key in scalar_keys:
            if key in parameters:
                overrides[key] = parameters[key]

        set_keys = ("allowed_directions", "allowed_setup_types")
        for key in set_keys:
            if key in parameters:
                value = parameters.get(key)
                overrides[key] = set(value) if value else None

        int_set_keys = ("allowed_hours_ny", "excluded_hours_ny", "disallow_normal_hours_ny")
        for key in int_set_keys:
            if key in parameters:
                value = parameters.get(key)
                overrides[key] = {int(item) for item in value} if value else None

        return replace(strategy_variant, **overrides) if overrides else strategy_variant

    def _load_market_map(self) -> dict[str, Any]:
        if not self.market_map_path.exists():
            raise RuntimeError(f"Market situation map not found: {self.market_map_path}")
        return json.loads(self.market_map_path.read_text(encoding="utf-8"))

    def _analyze_snapshot(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        market_map: dict[str, Any],
        snapshot: dict[str, list[Any]],
    ) -> dict[str, Any]:
        backtester: MaximoMTFQuantV4Backtester = runtime["backtester"]
        strategy_variant: StrategyVariant = runtime["strategy_variant"]
        session_variant = runtime["session_variant"]
        m5 = snapshot.get("M5", [])
        h1 = snapshot.get("H1", [])
        if len(m5) < 250 or len(h1) < 250:
            market_state = {
                "status": "insufficient_data",
                "entry_timeframe": "M5",
                "context_timeframes": ["H4", "H1", "M15"],
            }
            knowledge_alignment = {
                "matched_context_count": 0,
                "support_score": 0.0,
                "top_matching_contexts": [],
                "current_session_tags": [],
                "risk_guidance": None,
            }
            decision = {
                "action": "stand_aside",
                "confidence": 0.0,
                "allowed_to_trade_now": False,
                "rationale": ["No hay suficientes velas M5/H1 para evaluar el mercado correctamente."],
                "blockers": ["insufficient_data"],
            }
            return {
                "market_state": market_state,
                "knowledge_alignment": knowledge_alignment,
                "signal": None,
                "decision": decision,
            }

        m15 = backtester._resample(m5, "M15")
        h4 = backtester._resample(h1, "H4")
        context = {
            "macro": backtester._context_pack(h4),
            "trend": backtester._context_pack(h1),
            "setup": backtester._context_pack(m15),
        }
        signal = backtester.latest_snapshot_signal(
            symbol=symbol,
            timeframe="M5",
            entry_candles=m5,
            context=context,
            session_variant=session_variant,
            strategy_variant=strategy_variant,
        )
        market_state = self._evaluate_market_state(
            backtester=backtester,
            entry_candles=m5,
            context=context,
            strategy_variant=strategy_variant,
            symbol=symbol,
            strategy_snapshot=runtime.get("snapshot"),
        )
        knowledge_alignment = self._match_knowledge(
            market_map=market_map,
            market_state=market_state,
            strategy_variant=strategy_variant,
            runtime=runtime,
            signal=signal,
        )
        decision = self._decide_action(
            market_state=market_state,
            knowledge_alignment=knowledge_alignment,
            strategy_variant=strategy_variant,
            signal=signal,
        )
        return {
            "market_state": market_state,
            "knowledge_alignment": knowledge_alignment,
            "signal": signal,
            "decision": decision,
        }

    def _evaluate_market_state(
        self,
        *,
        backtester: MaximoMTFQuantV4Backtester,
        entry_candles: list[Any],
        context: dict[str, Any],
        strategy_variant: StrategyVariant,
        symbol: str,
        strategy_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        closes = [c.close for c in entry_candles]
        highs = [c.high for c in entry_candles]
        lows = [c.low for c in entry_candles]
        volumes = [c.volume for c in entry_candles]
        ema_fast = backtester._ema(closes, backtester.FAST_LEN)
        ema_slow = backtester._ema(closes, backtester.SLOW_LEN)
        atr_now = backtester._atr(entry_candles, backtester.ATR_LEN)
        atr_mean = backtester._sma(atr_now, backtester.ATR_MA_LEN)
        bar_range = [c.high - c.low for c in entry_candles]
        range_mean = backtester._sma(bar_range, backtester.RANGE_AVG_LEN)
        vol_mean = backtester._sma(volumes, backtester.VOL_LEN)
        body_abs = [abs(c.close - c.open) for c in entry_candles]
        body_avg = backtester._sma(body_abs, backtester.RANGE_AVG_LEN)
        latest_highs, latest_lows = backtester._latest_swings(highs, lows, backtester.SWING_LEN)
        daily_open_map = backtester._daily_open_map(entry_candles)

        macro = context["macro"]
        trend = context["trend"]
        setup = context["setup"]
        macro_map = backtester._map_completed_indices(entry_candles, macro["candles"], timedelta(hours=4))
        trend_map = backtester._map_completed_indices(entry_candles, trend["candles"], timedelta(hours=1))
        setup_map = backtester._map_completed_indices(entry_candles, setup["candles"], timedelta(minutes=15))

        index = len(entry_candles) - 2
        candle = entry_candles[index]
        local_ny = candle.time.astimezone(NY_TZ)
        local_rd = candle.time.astimezone(RD_TZ)
        hour_ny = local_ny.hour
        hour_rd = local_rd.hour
        minute_rd = local_rd.minute
        atr_value = atr_now[index]
        ema_fast_value = ema_fast[index]
        ema_slow_value = ema_slow[index]
        atr_mean_value = atr_mean[index]
        range_mean_value = range_mean[index]
        body_avg_value = body_avg[index]
        macro_idx = macro_map[index]
        trend_idx = trend_map[index]
        setup_idx = setup_map[index]
        if None in {
            atr_value,
            ema_fast_value,
            ema_slow_value,
            atr_mean_value,
            range_mean_value,
            body_avg_value,
            macro_idx,
            trend_idx,
            setup_idx,
        }:
            return {
                "status": "insufficient_indicators",
                "symbol": symbol,
                "entry_timeframe": "M5",
                "context_timeframes": ["H4", "H1", "M15"],
            }

        candle_range = max(candle.high - candle.low, 1e-9)
        candle_body = abs(candle.close - candle.open)
        body_pct = candle_body / candle_range * 100.0
        atr_ratio = atr_value / atr_mean_value if atr_mean_value else 1.0
        range_ratio = candle_range / range_mean_value if range_mean_value else 1.0
        vol_ok = vol_mean[index] is None or candle.volume >= (vol_mean[index] * 1.05)
        local_bull = ema_fast_value > ema_slow_value and candle.close > ema_fast_value
        local_bear = ema_fast_value < ema_slow_value and candle.close < ema_fast_value
        ema_spread_atr = abs(ema_fast_value - ema_slow_value) / max(atr_value, 1e-9)
        ema_fast_prev_3 = ema_fast[index - 3] if index >= 3 and ema_fast[index - 3] is not None else ema_fast_value
        ema_slope_atr = abs(ema_fast_value - ema_fast_prev_3) / max(atr_value, 1e-9)
        local_slope_up = index > 0 and ema_fast[index - 1] is not None and ema_fast_value > ema_fast[index - 1]
        local_slope_down = index > 0 and ema_fast[index - 1] is not None and ema_fast_value < ema_fast[index - 1]
        chop_ratio = body_avg_value / range_mean_value if range_mean_value else 1.0

        quant_expansion_ok = atr_ratio >= backtester.MIN_ATR_EXPANSION or range_ratio >= backtester.MIN_RANGE_EXPANSION
        quant_trend_ok = ema_spread_atr >= backtester.MIN_EMA_SPREAD_ATR and ema_slope_atr >= backtester.MIN_SLOPE_ATR
        quant_chop_ok = chop_ratio <= backtester.MAX_CHOP_RATIO or range_ratio >= 1.20
        quant_ok = quant_expansion_ok and quant_trend_ok and quant_chop_ok

        macro_row = macro["rows"][macro_idx]
        trend_row = trend["rows"][trend_idx]
        setup_row = setup["rows"][setup_idx]
        day_open = daily_open_map.get(candle.time.date(), candle.open)
        buy_mtf_score, sell_mtf_score = backtester._mtf_scores(
            local_bull=local_bull,
            local_bear=local_bear,
            macro_row=macro_row,
            trend_row=trend_row,
            setup_row=setup_row,
            day_bull=candle.close > day_open,
            day_bear=candle.close < day_open,
        )

        close_near_high = (candle.high - candle.close) <= candle_range * (backtester.CLOSE_EXTREME_PCT / 100.0)
        close_near_low = (candle.close - candle.low) <= candle_range * (backtester.CLOSE_EXTREME_PCT / 100.0)
        close_power_buy = (candle.close - candle.low) / candle_range
        close_power_sell = (candle.high - candle.close) / candle_range
        lower_wick_pct = (min(candle.open, candle.close) - candle.low) / candle_range * 100.0
        upper_wick_pct = (candle.high - max(candle.open, candle.close)) / candle_range * 100.0

        recent_compression = backtester._recent_compression(index, atr_now, atr_mean, bar_range, range_mean)
        compression_ok = recent_compression or atr_ratio >= 1.10 or range_ratio >= 1.20

        velocity_ref = closes[index - backtester.VELOCITY_LEN] if index >= backtester.VELOCITY_LEN else closes[0]
        velocity = abs(candle.close - velocity_ref) / max(atr_value, 1e-9)
        impulse_score = 0
        impulse_score += 20 if body_pct >= backtester.BODY_MIN_AGG else 0
        impulse_score += 20 if range_ratio >= backtester.MIN_RANGE_EXPANSION else 0
        impulse_score += 20 if velocity >= 0.35 else 0
        impulse_score += 20 if ema_slope_atr >= backtester.MIN_SLOPE_ATR else 0
        impulse_score += 20 if compression_ok else 0
        impulse_score = min(100, impulse_score)

        quant_score = 0
        quant_score += 20 if atr_ratio >= backtester.MIN_ATR_EXPANSION else 0
        quant_score += 20 if range_ratio >= backtester.MIN_RANGE_EXPANSION else 0
        quant_score += 20 if ema_spread_atr >= backtester.MIN_EMA_SPREAD_ATR else 0
        quant_score += 20 if ema_slope_atr >= backtester.MIN_SLOPE_ATR else 0
        quant_score += 20 if quant_chop_ok else 0
        quant_score += backtester.COMPRESSION_BONUS if recent_compression else 0
        quant_score = min(100, quant_score)

        range_high = max(highs[max(0, index - backtester.RANGE_LEN + 1) : index + 1])
        range_low = min(lows[max(0, index - backtester.RANGE_LEN + 1) : index + 1])
        eq = (range_high + range_low) / 2.0
        pd_buy_ok = candle.close <= eq or macro_row["discount"] or trend_row["discount"]
        pd_sell_ok = candle.close >= eq or macro_row["premium"] or trend_row["premium"]

        swing_low = latest_lows[index]
        swing_high = latest_highs[index]
        sell_side_sweep = swing_low is not None and candle.low < swing_low and candle.close > swing_low
        buy_side_sweep = swing_high is not None and candle.high > swing_high and candle.close < swing_high
        liq_high = max(highs[max(0, index - backtester.LIQUIDITY_LOOKBACK) : index]) if index > 0 else candle.high
        liq_low = min(lows[max(0, index - backtester.LIQUIDITY_LOOKBACK) : index]) if index > 0 else candle.low
        liquidity_grab_buy = candle.low < liq_low and candle.close > liq_low
        liquidity_grab_sell = candle.high > liq_high and candle.close < liq_high
        liquidity_quality_buy = sell_side_sweep or liquidity_grab_buy
        liquidity_quality_sell = buy_side_sweep or liquidity_grab_sell

        bull_disp_a = candle.close > candle.open and body_pct >= backtester.BODY_MIN_A and close_near_high and close_power_buy >= 0.60
        bear_disp_a = candle.close < candle.open and body_pct >= backtester.BODY_MIN_A and close_near_low and close_power_sell >= 0.60
        bull_disp_agg = candle.close > candle.open and body_pct >= backtester.BODY_MIN_AGG and close_power_buy >= 0.52
        bear_disp_agg = candle.close < candle.open and body_pct >= backtester.BODY_MIN_AGG and close_power_sell >= 0.52
        pullback_buy = local_bull and local_slope_up and candle.low <= ema_fast_value + atr_value * backtester.PULLBACK_ATR_PCT and candle.close > ema_fast_value and candle.close > candle.open
        pullback_sell = local_bear and local_slope_down and candle.high >= ema_fast_value - atr_value * backtester.PULLBACK_ATR_PCT and candle.close < ema_fast_value and candle.close < candle.open

        market_regime = "EXPANSION" if quant_score >= 75 and impulse_score >= 65 and (buy_mtf_score >= 65 or sell_mtf_score >= 65) else "NORMAL" if quant_score >= 55 else "CHOP"
        preferred_side = "BUY" if buy_mtf_score > sell_mtf_score + 15 else "SELL" if sell_mtf_score > buy_mtf_score + 15 else "NEUTRAL"

        setup_buy_a = all([
            liquidity_quality_buy,
            bull_disp_a,
            buy_mtf_score >= backtester.MIN_QUANT_A,
            pd_buy_ok,
            vol_ok,
            quant_ok,
            compression_ok,
            impulse_score >= backtester.MIN_IMPULSE_A,
            quant_score >= backtester.MIN_QUANT_A,
        ])
        setup_sell_a = all([
            liquidity_quality_sell,
            bear_disp_a,
            sell_mtf_score >= backtester.MIN_QUANT_A,
            pd_sell_ok,
            vol_ok,
            quant_ok,
            compression_ok,
            impulse_score >= backtester.MIN_IMPULSE_A,
            quant_score >= backtester.MIN_QUANT_A,
        ])
        setup_buy_agg = all([
            pullback_buy,
            bull_disp_agg,
            buy_mtf_score >= backtester.MIN_QUANT_AGG,
            quant_ok,
            compression_ok,
            impulse_score >= backtester.MIN_IMPULSE_AGG,
            quant_score >= backtester.MIN_QUANT_AGG,
            preferred_side != "SELL",
        ])
        setup_sell_agg = all([
            pullback_sell,
            bear_disp_agg,
            sell_mtf_score >= backtester.MIN_QUANT_AGG,
            quant_ok,
            compression_ok,
            impulse_score >= backtester.MIN_IMPULSE_AGG,
            quant_score >= backtester.MIN_QUANT_AGG,
            preferred_side != "BUY",
        ])

        candidate_setups = {
            "buy_a_plus": backtester._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="buy",
                setup_type="A+",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_buy_a,
            ),
            "sell_a_plus": backtester._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="sell",
                setup_type="A+",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_sell_a,
            ),
            "buy_agg": backtester._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="buy",
                setup_type="AGG",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_buy_agg,
            ),
            "sell_agg": backtester._variant_allows_setup(
                strategy_variant=strategy_variant,
                direction="sell",
                setup_type="AGG",
                signal_hour_ny=hour_ny,
                preferred_side=preferred_side,
                market_regime=market_regime,
                quant_score=quant_score,
                impulse_score=impulse_score,
                recent_compression=recent_compression,
                quant_expansion_ok=quant_expansion_ok,
                atr_ratio=atr_ratio,
                range_ratio=range_ratio,
                current_state=setup_sell_agg,
            ),
        }

        ob_rejection_families = self._classify_ob_rejection_families(
            backtester=backtester,
            index=index,
            opens=[c.open for c in entry_candles],
            closes=closes,
            highs=highs,
            lows=lows,
            candle_high=candle.high,
            candle_low=candle.low,
            candle_time=candle.time.isoformat(),
            next_open=entry_candles[index + 1].open if index + 1 < len(entry_candles) else candle.close,
            next_time=entry_candles[index + 1].time.isoformat() if index + 1 < len(entry_candles) else candle.time.isoformat(),
            atr_value=atr_value,
            candle_open=candle.open,
            candle_close=candle.close,
            body_pct=body_pct,
            close_power_buy=close_power_buy,
            close_power_sell=close_power_sell,
            velocity=velocity,
            atr_ratio=atr_ratio,
            range_ratio=range_ratio,
            local_bull=local_bull,
            local_bear=local_bear,
            preferred_side=preferred_side,
            market_regime=market_regime,
            quant_score=quant_score,
            impulse_score=impulse_score,
            candidate_setups=candidate_setups,
            bull_disp_agg=bull_disp_agg,
            bear_disp_agg=bear_disp_agg,
            liquidity_quality_buy=liquidity_quality_buy,
            liquidity_quality_sell=liquidity_quality_sell,
            pullback_buy=pullback_buy,
            pullback_sell=pullback_sell,
            vol_ok=vol_ok,
            compression_ok=compression_ok,
        )

        if range_ratio > (strategy_variant.max_range_ratio or 9.0):
            volatility_state = "extreme"
        elif quant_expansion_ok and (atr_ratio >= 1.10 or range_ratio >= 1.20):
            volatility_state = "expansion"
        elif recent_compression:
            volatility_state = "compression"
        else:
            volatility_state = "normal"

        expansion_subtype = self._expansion_subtype(
            atr_ratio=atr_ratio,
            range_ratio=range_ratio,
            quant_score=quant_score,
            impulse_score=impulse_score,
        )
        continuation_quality_buy = self._continuation_quality(
            continuation=ob_rejection_families["aggressive"]["checks"].get("continuation_momentum_buy", False),
            micro_bos=ob_rejection_families["aggressive"]["checks"].get("micro_bos_buy", False),
            wick_pct=lower_wick_pct,
        )
        continuation_quality_sell = self._continuation_quality(
            continuation=ob_rejection_families["aggressive"]["checks"].get("continuation_momentum_sell", False),
            micro_bos=ob_rejection_families["aggressive"]["checks"].get("micro_bos_sell", False),
            wick_pct=upper_wick_pct,
        )

        return {
            "status": "ok",
            "symbol": symbol,
            "entry_timeframe": "M5",
            "context_timeframes": ["H4", "H1", "M15"],
            "candle_time_utc": candle.time.isoformat(),
            "hour_ny": hour_ny,
            "hour_rd": hour_rd,
            "minute_rd": minute_rd,
            "local_time_rd": local_rd.strftime("%H:%M"),
            "session_tags": self._session_tags_for_time(candle.time, strategy_snapshot=strategy_snapshot),
            "allowed_hour_by_strategy": self._allowed_by_strategy_time(
                candle.time,
                strategy_variant=strategy_variant,
                strategy_snapshot=strategy_snapshot,
                backtester=backtester,
            ),
            "macro_bias": self._bias_from_row(macro_row),
            "trend_bias": self._bias_from_row(trend_row),
            "setup_bias": self._bias_from_row(setup_row),
            "local_bias": "BUY" if local_bull else "SELL" if local_bear else "NEUTRAL",
            "day_bias": "BUY" if candle.close > day_open else "SELL" if candle.close < day_open else "NEUTRAL",
            "buy_mtf_score": buy_mtf_score,
            "sell_mtf_score": sell_mtf_score,
            "preferred_side": preferred_side,
            "market_regime": market_regime,
            "volatility_state": volatility_state,
            "quant_score": quant_score,
            "impulse_score": impulse_score,
            "atr_ratio": round(atr_ratio, 4),
            "range_ratio": round(range_ratio, 4),
            "body_pct": round(body_pct, 4),
            "wick_rejection_pct_buy": round(lower_wick_pct, 4),
            "wick_rejection_pct_sell": round(upper_wick_pct, 4),
            "expansion_subtype": expansion_subtype,
            "atr_bucket": self._atr_bucket(atr_ratio),
            "continuation_quality_buy": continuation_quality_buy,
            "continuation_quality_sell": continuation_quality_sell,
            "ema_spread_atr": round(ema_spread_atr, 4),
            "ema_slope_atr": round(ema_slope_atr, 4),
            "chop_ratio": round(chop_ratio, 4),
            "quant_ok": quant_ok,
            "quant_expansion_ok": quant_expansion_ok,
            "recent_compression": recent_compression,
            "compression_ok": compression_ok,
            "vol_ok": vol_ok,
            "candidate_setups": candidate_setups,
            "ob_rejection_families": ob_rejection_families,
            "operational_family": ob_rejection_families["active_family"],
        }

    @staticmethod
    def _classify_ob_rejection_families(
        *,
        backtester: MaximoMTFQuantV4Backtester,
        index: int,
        opens: list[float] | None = None,
        closes: list[float] | None = None,
        highs: list[float],
        lows: list[float],
        candle_open: float,
        candle_close: float,
        body_pct: float,
        close_power_buy: float,
        close_power_sell: float,
        velocity: float,
        atr_ratio: float,
        range_ratio: float,
        local_bull: bool,
        local_bear: bool,
        preferred_side: str,
        market_regime: str,
        quant_score: int,
        impulse_score: int,
        candidate_setups: dict[str, bool],
        bull_disp_agg: bool,
        bear_disp_agg: bool,
        liquidity_quality_buy: bool,
        liquidity_quality_sell: bool,
        pullback_buy: bool,
        pullback_sell: bool,
        vol_ok: bool,
        compression_ok: bool,
        candle_high: float | None = None,
        candle_low: float | None = None,
        candle_time: str | None = None,
        next_open: float | None = None,
        next_time: str | None = None,
        atr_value: float | None = None,
    ) -> dict[str, Any]:
        institutional_buy = bool(candidate_setups.get("buy_a_plus") or candidate_setups.get("buy_agg"))
        institutional_sell = bool(candidate_setups.get("sell_a_plus") or candidate_setups.get("sell_agg"))
        institutional_active = institutional_buy or institutional_sell
        institutional_side = "BUY" if institutional_buy else "SELL" if institutional_sell else preferred_side

        previous_high = max(highs[max(0, index - 3) : index]) if index > 0 else highs[index]
        previous_low = min(lows[max(0, index - 3) : index]) if index > 0 else lows[index]
        micro_bos_buy = candle_close > previous_high
        micro_bos_sell = candle_close < previous_low
        micro_choch_buy = micro_bos_buy and local_bear
        micro_choch_sell = micro_bos_sell and local_bull
        bullish_rejection = candle_close > candle_open and (body_pct >= 35.0 or close_power_buy >= 0.58)
        bearish_rejection = candle_close < candle_open and (body_pct >= 35.0 or close_power_sell >= 0.58)
        partial_bull_displacement = candle_close > candle_open and body_pct >= 30.0 and velocity >= 0.35 and (range_ratio >= 0.75 or atr_ratio >= 0.80)
        partial_bear_displacement = candle_close < candle_open and body_pct >= 30.0 and velocity >= 0.35 and (range_ratio >= 0.75 or atr_ratio >= 0.80)
        continuation_buy = local_bull and candle_close > candle_open and velocity >= 0.35 and range_ratio >= 0.75
        continuation_sell = local_bear and candle_close < candle_open and velocity >= 0.35 and range_ratio >= 0.75
        base_quality_ok = market_regime != "CHOP" and quant_score >= backtester.MIN_QUANT_AGG and impulse_score >= backtester.MIN_IMPULSE_AGG
        manual_bias = MaximoQuantV4MarketOverviewEngine._sensei_manual_bias_confirmation(
            backtester=backtester,
            index=index,
            opens=opens or [],
            closes=closes or [],
            highs=highs,
            lows=lows,
            preferred_side=preferred_side,
            local_bull=local_bull,
            local_bear=local_bear,
            micro_bos_buy=micro_bos_buy,
            micro_bos_sell=micro_bos_sell,
            bullish_rejection=bullish_rejection,
            bearish_rejection=bearish_rejection,
            partial_bull_displacement=partial_bull_displacement,
            partial_bear_displacement=partial_bear_displacement,
            close_power_buy=close_power_buy,
            close_power_sell=close_power_sell,
            market_regime=market_regime,
            quant_score=quant_score,
            impulse_score=impulse_score,
            atr_value=atr_value,
            candle_high=candle_high,
            candle_low=candle_low,
            next_open=next_open,
            candle_time=candle_time,
            next_time=next_time,
        )

        aggressive_buy = (
            not institutional_active
            and preferred_side != "SELL"
            and base_quality_ok
            and (bullish_rejection or manual_bias["side"] == "BUY")
            and (partial_bull_displacement or bull_disp_agg or micro_bos_buy or continuation_buy)
        )
        aggressive_sell = (
            not institutional_active
            and preferred_side != "BUY"
            and base_quality_ok
            and (bearish_rejection or manual_bias["side"] == "SELL")
            and (partial_bear_displacement or bear_disp_agg or micro_bos_sell or continuation_sell)
        )
        manual_side_allowed = preferred_side not in {"BUY", "SELL"} or manual_bias["side"] == preferred_side
        if manual_bias["active"] and not institutional_active and base_quality_ok and manual_side_allowed:
            aggressive_buy = aggressive_buy or manual_bias["side"] == "BUY"
            aggressive_sell = aggressive_sell or manual_bias["side"] == "SELL"
        aggressive_active = aggressive_buy or aggressive_sell
        aggressive_side = "BUY" if aggressive_buy else "SELL" if aggressive_sell else preferred_side
        wick_rejection_quality = close_power_buy if aggressive_side == "BUY" else close_power_sell
        displacement_score = 0
        displacement_score += 25 if body_pct >= 30.0 else 0
        displacement_score += 25 if velocity >= 0.35 else 0
        displacement_score += 25 if (range_ratio >= 0.75 or atr_ratio >= 0.80) else 0
        displacement_score += 25 if (
            (aggressive_side == "BUY" and candle_close > candle_open)
            or (aggressive_side == "SELL" and candle_close < candle_open)
        ) else 0
        micro_bos = micro_bos_buy if aggressive_side == "BUY" else micro_bos_sell
        micro_choch = micro_choch_buy if aggressive_side == "BUY" else micro_choch_sell
        continuation_momentum = continuation_buy if aggressive_side == "BUY" else continuation_sell
        reduced_signal_candidate = None
        manual_signal_candidate = manual_bias.get("reduced_signal_candidate")
        if (
            aggressive_active
            and candle_high is not None
            and candle_low is not None
            and next_open is not None
            and atr_value is not None
        ):
            if manual_signal_candidate:
                reduced_signal_candidate = manual_signal_candidate
            else:
                rr = 1.15
                if aggressive_side == "SELL":
                    stop_price = float(candle_high) + float(atr_value) * 0.10
                    risk_per_unit = stop_price - float(next_open)
                    target_price = float(next_open) - risk_per_unit * rr
                else:
                    stop_price = float(candle_low) - float(atr_value) * 0.10
                    risk_per_unit = float(next_open) - stop_price
                    target_price = float(next_open) + risk_per_unit * rr
                reward_per_unit = abs(float(next_open) - target_price)
                sl_logical_available = risk_per_unit > 0
                rr_evaluable = risk_per_unit > 0 and reward_per_unit > 0
                reduced_signal_candidate = {
                    "entry_kind": "market",
                    "signal_time": candle_time,
                    "entry_time": next_time,
                    "direction": aggressive_side.lower(),
                    "setup_type": "AGG_REDUCED",
                    "signal_type": "OB_AGGRESSIVE_REDUCED_SIGNAL",
                    "active_family": "OB_REJECTION_AGGRESSIVE_WATCH",
                    "entry_price": round(float(next_open), 3),
                    "stop_price": round(stop_price, 3),
                    "target_price": round(target_price, 3),
                    "risk_per_unit": round(risk_per_unit, 6),
                    "selected_rr": rr,
                    "sl_logical_available": sl_logical_available,
                    "rr_evaluable": rr_evaluable,
                    "wick_rejection_quality": round(wick_rejection_quality, 4),
                    "displacement_score": displacement_score,
                    "micro_bos": micro_bos,
                    "micro_choch": micro_choch,
                    "continuation_momentum": continuation_momentum,
                    "reduced_signal_reason": (
                        "OB agresivo con rechazo/desplazamiento suficiente; no exige sweep/pullback institucional."
                    ),
                }

        active_family = (
            "OB_REJECTION_INSTITUTIONAL_EXECUTE"
            if institutional_active
            else "OB_REJECTION_AGGRESSIVE_WATCH"
            if aggressive_active
            else "NONE"
        )
        return {
            "active_family": active_family,
            "institutional": {
                "family": "OB_REJECTION_INSTITUTIONAL_EXECUTE",
                "active": institutional_active,
                "side": institutional_side,
                "requires": [
                    "liquidity_sweep_or_grab",
                    "pullback",
                    "displacement",
                    "strong_mtf_alignment",
                    "volume_confirmation",
                    "compression_validation",
                    "institutional_rr",
                ],
                "candidate_setups": candidate_setups,
                "checks": {
                    "liquidity_quality_buy": liquidity_quality_buy,
                    "liquidity_quality_sell": liquidity_quality_sell,
                    "pullback_buy": pullback_buy,
                    "pullback_sell": pullback_sell,
                    "bull_displacement": bull_disp_agg,
                    "bear_displacement": bear_disp_agg,
                    "volume_confirmation": vol_ok,
                    "compression_validation": compression_ok,
                },
            },
            "manual_bias": manual_bias,
            "aggressive": {
                "family": "OB_REJECTION_AGGRESSIVE_WATCH",
                "active": aggressive_active,
                "side": aggressive_side,
                "allows_prepare_reduced": aggressive_active,
                "allows_normal_risk_directly": False,
                "checks": {
                    "strong_bullish_rejection": bullish_rejection,
                    "strong_bearish_rejection": bearish_rejection,
                    "partial_bull_displacement": partial_bull_displacement,
                    "partial_bear_displacement": partial_bear_displacement,
                    "wick_rejection_buy": close_power_buy >= 0.58,
                    "wick_rejection_sell": close_power_sell >= 0.58,
                    "micro_bos_buy": micro_bos_buy,
                    "micro_bos_sell": micro_bos_sell,
                    "micro_choch_buy": micro_choch_buy,
                    "micro_choch_sell": micro_choch_sell,
                    "continuation_momentum_buy": continuation_buy,
                    "continuation_momentum_sell": continuation_sell,
                    "wick_rejection_quality": round(wick_rejection_quality, 4),
                    "displacement_score": displacement_score,
                    "base_quality_ok": base_quality_ok,
                    "sensei_manual_bias": manual_bias,
                },
                "reduced_signal_candidate": reduced_signal_candidate,
            },
        }

    @staticmethod
    def _sensei_manual_bias_confirmation(
        *,
        backtester: MaximoMTFQuantV4Backtester,
        index: int,
        opens: list[float],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        preferred_side: str,
        local_bull: bool,
        local_bear: bool,
        micro_bos_buy: bool,
        micro_bos_sell: bool,
        bullish_rejection: bool,
        bearish_rejection: bool,
        partial_bull_displacement: bool,
        partial_bear_displacement: bool,
        close_power_buy: float,
        close_power_sell: float,
        market_regime: str,
        quant_score: int,
        impulse_score: int,
        atr_value: float | None,
        candle_high: float | None,
        candle_low: float | None,
        next_open: float | None,
        candle_time: str | None,
        next_time: str | None,
    ) -> dict[str, Any]:
        empty = {
            "active": False,
            "side": "NEUTRAL",
            "score": 0,
            "checks": {},
            "reduced_signal_candidate": None,
            "reason": "Sensei manual bias no confirmado.",
        }
        if index < 8 or not opens or not closes or len(closes) <= index:
            return empty

        lookback_start = max(0, index - 18)
        recent_highs = highs[lookback_start:index]
        recent_lows = lows[lookback_start:index]
        if not recent_highs or not recent_lows:
            return empty

        atr = float(atr_value or 0.0)
        current_close = float(closes[index])
        tolerance = max(atr * 0.18, abs(current_close) * 0.00018, 0.05)
        recent_high = max(recent_highs)
        recent_low = min(recent_lows)
        equal_highs = sum(1 for value in recent_highs if abs(value - recent_high) <= tolerance) >= 2
        equal_lows = sum(1 for value in recent_lows if abs(value - recent_low) <= tolerance) >= 2

        sweep_high = False
        sweep_low = False
        for cursor in range(max(lookback_start + 3, index - 10), index + 1):
            left_start = max(lookback_start, cursor - 8)
            if cursor <= left_start:
                continue
            prior_high = max(highs[left_start:cursor])
            prior_low = min(lows[left_start:cursor])
            close_value = closes[cursor]
            sweep_high = sweep_high or (highs[cursor] > prior_high + tolerance * 0.15 and close_value < prior_high)
            sweep_low = sweep_low or (lows[cursor] < prior_low - tolerance * 0.15 and close_value > prior_low)

        explicit_side = preferred_side in {"BUY", "SELL"}
        sell_bias = preferred_side == "SELL" or (not explicit_side and local_bear)
        buy_bias = preferred_side == "BUY" or (not explicit_side and local_bull)
        sell_displacement = bearish_rejection and (partial_bear_displacement or close_power_sell >= 0.62)
        buy_displacement = bullish_rejection and (partial_bull_displacement or close_power_buy >= 0.62)
        sell_liquidity = sweep_high or equal_highs
        buy_liquidity = sweep_low or equal_lows
        quality_ok = market_regime != "CHOP" and quant_score >= backtester.MIN_QUANT_AGG and impulse_score >= backtester.MIN_IMPULSE_AGG

        sell_score = sum([sell_bias, sell_liquidity, micro_bos_sell, sell_displacement, quality_ok])
        buy_score = sum([buy_bias, buy_liquidity, micro_bos_buy, buy_displacement, quality_ok])
        if sell_score < 4 and buy_score < 4:
            return {
                **empty,
                "score": max(sell_score, buy_score),
                "checks": {
                    "sell_bias": sell_bias,
                    "sell_liquidity": sell_liquidity,
                    "sell_micro_bos": micro_bos_sell,
                    "sell_displacement": sell_displacement,
                    "buy_bias": buy_bias,
                    "buy_liquidity": buy_liquidity,
                    "buy_micro_bos": micro_bos_buy,
                    "buy_displacement": buy_displacement,
                    "quality_ok": quality_ok,
                },
            }

        side = "SELL" if sell_score >= buy_score else "BUY"
        entry = float(next_open if next_open is not None else current_close)
        if explicit_side and side != preferred_side:
            return {
                **empty,
                "score": max(sell_score, buy_score),
                "checks": {
                    "equal_highs": equal_highs,
                    "equal_lows": equal_lows,
                    "sweep_high": sweep_high,
                    "sweep_low": sweep_low,
                    "sell_bias": sell_bias,
                    "sell_liquidity": sell_liquidity,
                    "sell_micro_bos": micro_bos_sell,
                    "sell_displacement": sell_displacement,
                    "buy_bias": buy_bias,
                    "buy_liquidity": buy_liquidity,
                    "buy_micro_bos": micro_bos_buy,
                    "buy_displacement": buy_displacement,
                    "quality_ok": quality_ok,
                    "side_conflict_with_preferred_bias": True,
                },
                "reason": (
                    "Sensei manual bias no confirmado porque el trigger local va contra el preferred_side "
                    "sin contexto de reversión aprobado."
                ),
            }

        if side == "SELL":
            stop = max(recent_high, float(candle_high or recent_high)) + max(atr * 0.12, tolerance)
            risk = stop - entry
            target = entry - risk * 2.0
            direction = "sell"
            wick_quality = max(close_power_sell, 0.65)
            displacement_score = 100 if sell_displacement and micro_bos_sell else 75
        else:
            stop = min(recent_low, float(candle_low or recent_low)) - max(atr * 0.12, tolerance)
            risk = entry - stop
            target = entry + risk * 2.0
            direction = "buy"
            wick_quality = max(close_power_buy, 0.65)
            displacement_score = 100 if buy_displacement and micro_bos_buy else 75
        candidate = None
        if risk > 0:
            candidate = {
                "entry_kind": "market",
                "signal_time": candle_time,
                "entry_time": next_time,
                "direction": direction,
                "setup_type": "SENSEI_BIAS_REDUCED",
                "signal_type": "SENSEI_MANUAL_BIAS_REDUCED_SIGNAL",
                "active_family": "OB_REJECTION_AGGRESSIVE_WATCH",
                "entry_price": round(entry, 3),
                "stop_price": round(stop, 3),
                "target_price": round(target, 3),
                "risk_per_unit": round(risk, 6),
                "selected_rr": 2.0,
                "sl_logical_available": True,
                "rr_evaluable": True,
                "wick_rejection_quality": round(wick_quality, 4),
                "displacement_score": displacement_score,
                "micro_bos": micro_bos_sell if side == "SELL" else micro_bos_buy,
                "micro_choch": False,
                "continuation_momentum": sell_displacement if side == "SELL" else buy_displacement,
                "manual_bias_confirmation": True,
                "reduced_signal_reason": (
                    "Sensei manual bias: bias, liquidez del último high/low, BMS/BOS y desplazamiento "
                    "confirman entrada reducida antes de evento mientras macro siga allow."
                ),
            }

        return {
            "active": candidate is not None,
            "side": side,
            "score": max(sell_score, buy_score),
            "checks": {
                "equal_highs": equal_highs,
                "equal_lows": equal_lows,
                "sweep_high": sweep_high,
                "sweep_low": sweep_low,
                "sell_bias": sell_bias,
                "sell_liquidity": sell_liquidity,
                "sell_micro_bos": micro_bos_sell,
                "sell_displacement": sell_displacement,
                "buy_bias": buy_bias,
                "buy_liquidity": buy_liquidity,
                "buy_micro_bos": micro_bos_buy,
                "buy_displacement": buy_displacement,
                "quality_ok": quality_ok,
            },
            "reduced_signal_candidate": candidate,
            "reason": "Sensei manual bias confirmado: liquidez, BMS/BOS y desplazamiento encajan.",
        }

    def _match_knowledge(
        self,
        *,
        market_map: dict[str, Any],
        market_state: dict[str, Any],
        strategy_variant: StrategyVariant,
        runtime: dict[str, Any],
        signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        regime_map = {
            "EXPANSION": {"expansion", "trend", "mixed"},
            "NORMAL": {"trend", "mixed", "range"},
            "CHOP": {"range", "mixed"},
        }
        desired_regimes = regime_map.get(market_state.get("market_regime"), {"mixed"})
        current_sessions = set(market_state.get("session_tags", []))
        preferred_side = str(market_state.get("preferred_side", "NEUTRAL")).lower()
        entry_tf = str(market_state.get("entry_timeframe", "M5"))
        contexts = []
        for item in market_map.get("operable_situations", []):
            sessions = set(item.get("sessions", []))
            if sessions and not (sessions & current_sessions):
                continue
            entry_timeframes = set(item.get("entry_timeframes", []))
            if entry_timeframes and entry_tf not in entry_timeframes:
                continue
            item_regime = str(item.get("market_regime", "mixed")).lower()
            if item_regime not in desired_regimes:
                continue
            direction = str(item.get("direction", "both")).lower()
            if preferred_side in {"buy", "sell"} and direction not in {"both", preferred_side}:
                continue
            label = str(item.get("operability_label", "research_only"))
            label_score = {"operable": 1.0, "needs_confirmation": 0.65, "research_only": 0.3}.get(label, 0.3)
            support_score = min(1.0, item.get("supporting_rules", 0) / 25.0)
            confidence_score = float(item.get("average_confidence") or 0.0)
            family_bonus = 0.1 if signal and item.get("strategy_family") in {"OB Rejection", "Breakout Retest", "Session Expansion", "Trend Pullback"} else 0.0
            score = round(label_score * 0.5 + support_score * 0.3 + confidence_score * 0.2 + family_bonus, 4)
            contexts.append(
                {
                    "strategy_family": item.get("strategy_family"),
                    "market_regime": item.get("market_regime"),
                    "direction": item.get("direction"),
                    "sessions": item.get("sessions", []),
                    "entry_timeframes": item.get("entry_timeframes", []),
                    "supporting_rules": item.get("supporting_rules", 0),
                    "average_confidence": item.get("average_confidence"),
                    "operability_label": label,
                    "score": score,
                    "top_entry_conditions": item.get("top_entry_conditions", []),
                    "top_confirmations": item.get("top_confirmations", []),
                }
            )
        contexts.sort(key=lambda item: (item["score"], item["supporting_rules"], item["average_confidence"] or 0), reverse=True)
        support_score = round(sum(item["score"] for item in contexts[:3]) / max(1, min(3, len(contexts))), 4) if contexts else 0.0
        risk_guidance = self._risk_guidance_for_regime(
            regime=market_state.get("market_regime", "NORMAL"),
            market_map=market_map,
        )
        harmony = self.harmonizer.analyze(
            market_state=market_state,
            contexts=contexts,
            non_operable_situations=market_map.get("non_operable_situations", []),
            signal=signal,
        )
        return {
            "matched_context_count": len(contexts),
            "support_score": support_score,
            "top_matching_contexts": contexts[:5],
            "current_session_tags": sorted(current_sessions),
            "risk_guidance": risk_guidance,
            "active_strategy_variant": runtime["strategy_variant"].code,
            "harmony": harmony,
        }

    def _decide_action(
        self,
        *,
        market_state: dict[str, Any],
        knowledge_alignment: dict[str, Any],
        strategy_variant: StrategyVariant,
        signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        critical_blocks: list[str] = []
        soft_flags: list[str] = []
        rationale: list[str] = []
        if market_state.get("status") != "ok":
            critical_blocks.append(str(market_state.get("status")))
        if not market_state.get("allowed_hour_by_strategy", False):
            soft_flags.append("hour_not_allowed")
        if market_state.get("market_regime") == "CHOP":
            critical_blocks.append("chop_regime")
        if market_state.get("quant_score", 0) < strategy_variant.min_quant_score:
            soft_flags.append("quant_below_variant_threshold")
        if knowledge_alignment.get("support_score", 0.0) < 0.25:
            soft_flags.append("weak_knowledge_alignment")
        harmony = knowledge_alignment.get("harmony") or {}
        harmony_score = float(harmony.get("harmony_score", 0.0))
        if harmony_score < 0.22:
            critical_blocks.append("weak_knowledge_harmony")
        elif harmony_score < 0.4:
            soft_flags.append("weak_knowledge_harmony")
        if harmony.get("operating_posture") == "defensive":
            if harmony_score < 0.22:
                critical_blocks.append("defensive_knowledge_posture")
            else:
                soft_flags.append("defensive_knowledge_posture")
        if market_state.get("preferred_side") == "NEUTRAL":
            soft_flags.append("neutral_direction")

        if signal is not None:
            rationale.append(
                f"Hay señal {signal['setup_type']} {signal['direction']} con confianza {signal['confidence']} y RR {signal['selected_rr']}."
            )
        if market_state.get("preferred_side") in {"BUY", "SELL"}:
            rationale.append(
                f"El sesgo dominante es {market_state['preferred_side']} con scores MTF {market_state['buy_mtf_score']}/{market_state['sell_mtf_score']}."
            )
        if knowledge_alignment.get("top_matching_contexts"):
            top = knowledge_alignment["top_matching_contexts"][0]
            rationale.append(
                f"El conocimiento aprendido favorece {top['strategy_family']} en régimen {top['market_regime']} con label {top['operability_label']}."
            )
        if harmony.get("narrative"):
            rationale.extend(harmony["narrative"][:3])
        if market_state.get("volatility_state"):
            rationale.append(f"La volatilidad actual se clasifica como {market_state['volatility_state']}.")
        ob_families = market_state.get("ob_rejection_families", {}) or {}
        active_ob_family = str(ob_families.get("active_family") or "NONE")
        if active_ob_family == "OB_REJECTION_AGGRESSIVE_WATCH":
            rationale.append("Se detecta OB Rejection agresivo en desarrollo; solo puede pasar por WATCH/PREPARE_REDUCED.")
        elif active_ob_family == "OB_REJECTION_INSTITUTIONAL_EXECUTE":
            rationale.append("Se detecta OB Rejection institucional completo bajo la lógica premium actual.")

        candidate_count = sum(1 for value in market_state.get("candidate_setups", {}).values() if value)
        if candidate_count:
            rationale.append(f"Hay {candidate_count} configuraciones de entrada activables en el candle evaluado.")

        setup_maturity = round(
            min(
                100.0,
                knowledge_alignment.get("support_score", 0.0) * 30.0
                + harmony_score * 20.0
                + (market_state.get("quant_score", 0) * 0.15)
                + (market_state.get("impulse_score", 0) * 0.10)
                + min(15.0, candidate_count * 7.0)
                + min(8.0, knowledge_alignment.get("matched_context_count", 0) * 0.5)
                + (5.0 if market_state.get("allowed_hour_by_strategy", False) else 0.0)
                + (5.0 if market_state.get("market_regime") in {"NORMAL", "EXPANSION"} else 0.0)
                + (5.0 if market_state.get("preferred_side") in {"BUY", "SELL"} else 0.0)
                + (10.0 if signal is not None else 0.0),
            ),
            2,
        )

        action = "CAUTION"
        allowed_to_trade_now = False
        confidence = round(min(0.95, setup_maturity / 100.0), 4)
        risk_mode = "blocked"
        watchlist_active = False

        if critical_blocks:
            action = "BLOCKED"
            confidence = 0.0
            risk_mode = "blocked"
        elif signal is not None and setup_maturity >= 85:
            action = "EXECUTE"
            allowed_to_trade_now = True
            risk_mode = "normal"
            confidence = round(min(1.0, max(confidence, 0.8)), 4)
        elif signal is not None and setup_maturity >= 65:
            action = "EXECUTE"
            allowed_to_trade_now = True
            risk_mode = "reduced"
            confidence = round(min(0.92, max(confidence, 0.65)), 4)
        elif setup_maturity >= 50:
            action = "WATCH"
            watchlist_active = True
            risk_mode = "reduced"
            confidence = round(min(0.89, max(confidence, 0.5)), 4)
        else:
            action = "CAUTION"
            risk_mode = "blocked"

        return {
            "action": action,
            "confidence": confidence,
            "allowed_to_trade_now": allowed_to_trade_now,
            "risk_mode": risk_mode,
            "watchlist_active": watchlist_active,
            "setup_maturity": setup_maturity,
            "rationale": rationale,
            "critical_blocks": sorted(set(critical_blocks)),
            "soft_flags": sorted(set(soft_flags)),
            "blockers": sorted(set(critical_blocks + soft_flags)),
        }

    def _risk_guidance_for_regime(self, *, regime: str, market_map: dict[str, Any]) -> dict[str, Any] | None:
        normalized = regime.lower()
        lookup = {
            "expansion": "expansion",
            "normal": "trend",
            "chop": "range",
        }
        wanted = lookup.get(normalized, "mixed")
        default_recommended = {
            "expansion": 0.75,
            "normal": 0.5,
            "chop": 0.25,
        }.get(normalized, 0.5)
        for row in market_map.get("risk_by_regime", []):
            if str(row.get("market_regime", "")).lower() != wanted:
                continue
            avg_risk = row.get("average_risk_percent")
            sanitized_average = None
            if isinstance(avg_risk, (int, float)) and 0 < float(avg_risk) <= 5:
                sanitized_average = round(float(avg_risk), 3)
            return {
                **row,
                "knowledge_average_risk_percent": sanitized_average,
                "recommended_risk_percent": sanitized_average or default_recommended,
            }
        return None

    @staticmethod
    def _session_tags(hour_ny: int) -> list[str]:
        tags: list[str] = []
        if 2 <= hour_ny <= 5:
            tags.append("london")
        if 8 <= hour_ny <= 16:
            tags.append("new_york")
        if hour_ny == 9:
            tags.append("ny_am")
        if hour_ny == 15:
            tags.append("ny_pm")
        return tags

    @staticmethod
    def _default_session_windows_rd() -> list[dict[str, str]]:
        return [
            {"name": "london", "start": "03:00", "end": "05:00"},
            {"name": "new_york", "start": "08:00", "end": "11:30"},
        ]

    @staticmethod
    def _window_minutes(value: str) -> int:
        hour, minute = str(value).split(":", 1)
        return int(hour) * 60 + int(minute)

    @classmethod
    def _session_windows_from_snapshot(cls, strategy_snapshot: dict[str, Any] | None) -> list[dict[str, str]]:
        parameters = (strategy_snapshot or {}).get("parameters", {}) if isinstance(strategy_snapshot, dict) else {}
        windows = parameters.get("allowed_session_windows_rd") if isinstance(parameters, dict) else None
        if isinstance(windows, list) and windows:
            normalized = []
            for item in windows:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "session")
                start = str(item.get("start") or "")
                end = str(item.get("end") or "")
                if ":" in start and ":" in end:
                    normalized.append({"name": name, "start": start, "end": end})
            if normalized:
                return normalized
        return cls._default_session_windows_rd()

    @classmethod
    def _allowed_by_session_windows_rd(
        cls,
        time_value: datetime,
        *,
        strategy_snapshot: dict[str, Any] | None,
    ) -> bool:
        local_rd = time_value.astimezone(RD_TZ)
        current_minutes = local_rd.hour * 60 + local_rd.minute
        for window in cls._session_windows_from_snapshot(strategy_snapshot):
            start = cls._window_minutes(window["start"])
            end = cls._window_minutes(window["end"])
            if start <= current_minutes <= end:
                return True
        return False

    @classmethod
    def _session_tags_for_time(cls, time_value: datetime, *, strategy_snapshot: dict[str, Any] | None) -> list[str]:
        local_rd = time_value.astimezone(RD_TZ)
        current_minutes = local_rd.hour * 60 + local_rd.minute
        tags: list[str] = []
        for window in cls._session_windows_from_snapshot(strategy_snapshot):
            start = cls._window_minutes(window["start"])
            end = cls._window_minutes(window["end"])
            if start <= current_minutes <= end:
                name = str(window.get("name") or "session").lower()
                tags.append(name)
                if name == "new_york":
                    tags.append("ny_am")
        return sorted(set(tags))

    @classmethod
    def _allowed_by_strategy_time(
        cls,
        time_value: datetime,
        *,
        strategy_variant: StrategyVariant,
        strategy_snapshot: dict[str, Any] | None,
        backtester: MaximoMTFQuantV4Backtester,
    ) -> bool:
        parameters = (strategy_snapshot or {}).get("parameters", {}) if isinstance(strategy_snapshot, dict) else {}
        if isinstance(parameters, dict) and parameters.get("allowed_session_windows_rd"):
            return cls._allowed_by_session_windows_rd(time_value, strategy_snapshot=strategy_snapshot)
        return backtester._hour_allowed(time_value.astimezone(NY_TZ).hour, strategy_variant)

    @staticmethod
    def _atr_bucket(atr_ratio: float) -> str:
        if atr_ratio < 0.85:
            return "low_atr"
        if atr_ratio < 1.10:
            return "normal_atr"
        if atr_ratio < 1.45:
            return "high_atr"
        return "extreme_atr"

    @staticmethod
    def _expansion_subtype(*, atr_ratio: float, range_ratio: float, quant_score: int, impulse_score: int) -> str:
        if atr_ratio >= 1.45 or range_ratio >= 1.75:
            return "extended_expansion"
        if quant_score >= 88 and impulse_score >= 80:
            return "clean_expansion"
        if atr_ratio < 0.85:
            return "thin_expansion"
        return "standard_expansion"

    @staticmethod
    def _continuation_quality(*, continuation: bool, micro_bos: bool, wick_pct: float) -> str:
        score = int(continuation) + int(micro_bos) + int(wick_pct >= 28.0)
        if score >= 3:
            return "strong"
        if score == 2:
            return "medium"
        return "weak"

    @staticmethod
    def _bias_from_row(row: dict[str, Any]) -> str:
        if row.get("bull"):
            return "BUY"
        if row.get("bear"):
            return "SELL"
        return "NEUTRAL"

    def _write_outputs(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        snapshot: dict[str, Any],
        analysis: dict[str, Any],
    ) -> None:
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "strategy_name": "MAXIMO MTF Quant Institutional v4",
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "snapshot": snapshot["timeframes"],
            "market_state": analysis["market_state"],
            "knowledge_alignment": analysis["knowledge_alignment"],
            "signal": analysis["signal"],
            "decision": analysis["decision"],
        }
        self.latest_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# MAXIMO Quant v4 Market Overview",
            "",
            f"- generated_at_utc: {payload['generated_at_utc']}",
            f"- symbol: {symbol}",
            f"- strategy_variant: {runtime['strategy_variant'].code}",
            f"- session_variant: {runtime['session_variant'].code}",
            f"- action: {analysis['decision']['action']}",
            f"- confidence: {analysis['decision']['confidence']}",
            "",
            "## Market State",
        ]
        for key in (
            "market_regime",
            "preferred_side",
            "volatility_state",
            "hour_ny",
            "hour_rd",
            "minute_rd",
            "local_time_rd",
            "session_tags",
            "allowed_hour_by_strategy",
            "macro_bias",
            "trend_bias",
            "setup_bias",
            "local_bias",
            "buy_mtf_score",
            "sell_mtf_score",
            "quant_score",
            "impulse_score",
            "atr_ratio",
            "range_ratio",
            "chop_ratio",
        ):
            if key in analysis["market_state"]:
                lines.append(f"- {key}: {analysis['market_state'][key]}")
        lines.extend(["", "## Knowledge Alignment"])
        lines.append(f"- matched_context_count: {analysis['knowledge_alignment']['matched_context_count']}")
        lines.append(f"- support_score: {analysis['knowledge_alignment']['support_score']}")
        lines.append(f"- harmony_score: {analysis['knowledge_alignment'].get('harmony', {}).get('harmony_score')}")
        lines.append(f"- operating_posture: {analysis['knowledge_alignment'].get('harmony', {}).get('operating_posture')}")
        top_contexts = analysis["knowledge_alignment"]["top_matching_contexts"]
        if top_contexts:
            for item in top_contexts[:3]:
                lines.append(
                    f"- {item['strategy_family']} | regime {item['market_regime']} | label {item['operability_label']} | score {item['score']}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "## Decision"])
        for line in analysis["decision"]["rationale"]:
            lines.append(f"- {line}")
        if analysis["decision"]["blockers"]:
            lines.append("")
            lines.append("### Blockers")
            for blocker in analysis["decision"]["blockers"]:
                lines.append(f"- {blocker}")
        lines.extend(["", "## Signal"])
        if analysis["signal"] is None:
            lines.append("- none")
        else:
            for key in ("direction", "setup_type", "entry_kind", "entry_price", "stop_price", "target_price", "confidence"):
                lines.append(f"- {key}: {analysis['signal'][key]}")
        self.latest_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _append_decision_log(
        self,
        *,
        symbol: str,
        runtime: dict[str, Any],
        analysis: dict[str, Any],
    ) -> None:
        fields = [
            "timestamp_utc",
            "symbol",
            "strategy_variant",
            "session_variant",
            "action",
            "decision_confidence",
            "market_regime",
            "preferred_side",
            "volatility_state",
            "hour_ny",
            "signal_detected",
            "signal_direction",
            "signal_setup_type",
            "knowledge_support_score",
            "matched_context_count",
            "harmony_score",
            "operating_posture",
            "blockers",
        ]
        row = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "strategy_variant": runtime["strategy_variant"].code,
            "session_variant": runtime["session_variant"].code,
            "action": analysis["decision"]["action"],
            "decision_confidence": analysis["decision"]["confidence"],
            "market_regime": analysis["market_state"].get("market_regime"),
            "preferred_side": analysis["market_state"].get("preferred_side"),
            "volatility_state": analysis["market_state"].get("volatility_state"),
            "hour_ny": analysis["market_state"].get("hour_ny"),
            "signal_detected": analysis["signal"] is not None,
            "signal_direction": analysis["signal"].get("direction") if analysis["signal"] else None,
            "signal_setup_type": analysis["signal"].get("setup_type") if analysis["signal"] else None,
            "knowledge_support_score": analysis["knowledge_alignment"].get("support_score"),
            "matched_context_count": analysis["knowledge_alignment"].get("matched_context_count"),
            "harmony_score": analysis["knowledge_alignment"].get("harmony", {}).get("harmony_score"),
            "operating_posture": analysis["knowledge_alignment"].get("harmony", {}).get("operating_posture"),
            "blockers": "|".join(analysis["decision"].get("blockers", [])),
        }
        write_header = not self.decision_log_path.exists()
        with self.decision_log_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
