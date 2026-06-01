"""Replay REACTION_ZONE_EXPANSION_BRAIN_V0 under the H4-fixed baseline.

Research-only script. It does not alter operational MAXIMO logic.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.blueprint_backtester import Candle
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester, NY_TZ


INPUT_DIR = ROOT / "data" / "backtests" / "input"
OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain"
YEARLY_DIR = ROOT / "data" / "backtests" / "maximo_mtf_quant_v4" / "yearly"


@dataclass(slots=True)
class ReplayVariant:
    code: str
    label: str
    compression_mode: str
    selected_missing_filters: set[str]


@dataclass(slots=True)
class CandidateTrade:
    year: int
    signal_time: datetime
    entry_time: datetime
    side: str
    missing_filter: str
    session: str
    atr_bucket: str
    compression_ok: bool
    displacement_agg: bool
    cluster_id: str
    hour_ny: int
    entry: float
    stop: float
    target: float
    risk: float
    rr: float
    raw_result: str
    raw_r: float
    managed_result: str
    realized_r: float
    mfe_r: float
    mae_r: float
    confidence: int
    mtf_score: int
    quant_score: int
    impulse_score: int
    atr_ratio: float
    range_ratio: float
    body_pct: float


class ReactionZoneExpansionBrainReplay:
    """Replay a narrow BUY/EXPANSION/AGG near-candidate edge."""

    allowed_hours_ny = {1, 4, 5, 9, 15, 19}

    def __init__(self, variant: ReplayVariant | None = None) -> None:
        self.variant = variant or ReplayVariant(
            code="v0_actual",
            label="V0 actual",
            compression_mode="blocker",
            selected_missing_filters={"displacement_AGG", "compression_ok"},
        )
        self.bt = MaximoMTFQuantV4Backtester(INPUT_DIR, OUTPUT_DIR)

    def run(self, symbol: str = "XAUUSDm", years: tuple[int, ...] = (2023, 2024, 2025, 2026)) -> dict[str, Any]:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        yearly: dict[str, Any] = {}
        all_trades: list[CandidateTrade] = []
        for year in years:
            trades, audit = self.run_year(symbol=symbol, year=year)
            yearly[str(year)] = {
                "metrics": self._metrics(trades),
                "audit": audit,
                "by_missing_filter": self._breakdown(trades, "missing_filter"),
                "by_hour_ny": self._breakdown(trades, "hour_ny"),
            }
            all_trades.extend(trades)
            self._write_jsonl(OUTPUT_DIR / f"{year}_reaction_zone_expansion_brain_replay.jsonl", trades)

        payload = {
            "strategy": "REACTION_ZONE_EXPANSION_BRAIN_V0",
            "variant": asdict(self.variant),
            "status": "RESEARCH_ONLY_NO_OPERATIONAL_CHANGE",
            "baseline": "MTF_REAL_H4_FIXED_BASELINE",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "rules": {
                "direction": "BUY only",
                "regime": "EXPANSION only",
                "setup_family": "AGG near candidate only",
                "selected_missing_filters": sorted(self.variant.selected_missing_filters),
                "compression_mode": self.variant.compression_mode,
                "allowed_hours_ny": sorted(self.allowed_hours_ny),
                "risk_mode": "reduced_only",
                "management": "partial 0.5R, BE, protect 0.8R at +0.3R",
            },
            "yearly": yearly,
            "aggregate": self._metrics(all_trades),
            "aggregate_by_missing_filter": self._breakdown(all_trades, "missing_filter"),
            "aggregate_by_session": self._breakdown(all_trades, "session"),
            "aggregate_by_atr_bucket": self._breakdown(all_trades, "atr_bucket"),
            "aggregate_by_displacement_agg": self._breakdown(all_trades, "displacement_agg"),
            "aggregate_by_year": {str(year): yearly[str(year)]["metrics"] for year in years},
            "decision": self._decision(yearly),
        }
        json_path = OUTPUT_DIR / f"{self.variant.code}_reaction_zone_expansion_brain_replay.json"
        md_path = OUTPUT_DIR / f"{self.variant.code}_reaction_zone_expansion_brain_replay.md"
        csv_path = OUTPUT_DIR / f"{self.variant.code}_reaction_zone_expansion_brain_trades.csv"
        json_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        md_path.write_text(self._markdown(payload), encoding="utf-8")
        self._write_csv(csv_path, all_trades)
        if self.variant.code == "v0_actual":
            (OUTPUT_DIR / "reaction_zone_expansion_brain_replay.json").write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
            (OUTPUT_DIR / "reaction_zone_expansion_brain_replay.md").write_text(self._markdown(payload), encoding="utf-8")
            self._write_csv(OUTPUT_DIR / "reaction_zone_expansion_brain_trades.csv", all_trades)
        return payload

    def run_year(self, *, symbol: str, year: int) -> tuple[list[CandidateTrade], dict[str, Any]]:
        family = self.bt._load_year_family(symbol, year)
        if not family.get("M5") or not family.get("H1"):
            return [], {"reason": "missing_m5_or_h1"}
        start, end = self._year_period(year)
        m5 = [c for c in family["M5"] if start <= c.time <= end]
        h1 = [c for c in family["H1"] if start <= c.time <= end]
        m15 = self.bt._resample(m5, "M15")
        h4 = self.bt._resample(h1, "H4")
        context = {
            "macro": self.bt._context_pack(h4),
            "trend": self.bt._context_pack(h1),
            "setup": self.bt._context_pack(m15),
        }
        candidates, audit = self._find_candidates(year=year, entry_candles=m5, context=context)
        representatives = self._cluster_representatives(candidates)
        real_trade_times = self._real_trade_signal_times(year)
        filtered = [item for item in representatives if item["time"] not in real_trade_times]
        trades = [trade for item in filtered if (trade := self._simulate_candidate(year=year, entry_candles=m5, item=item)) is not None]
        audit.update(
            {
                "candidates": len(candidates),
                "clusters": len(representatives),
                "overlap_excluded": len(representatives) - len(filtered),
                "simulated_trades": len(trades),
            }
        )
        return trades, audit

    def _find_candidates(self, *, year: int, entry_candles: list[Candle], context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        closes = [c.close for c in entry_candles]
        highs = [c.high for c in entry_candles]
        lows = [c.low for c in entry_candles]
        volumes = [c.volume for c in entry_candles]
        ema_fast = self.bt._ema(closes, self.bt.FAST_LEN)
        ema_slow = self.bt._ema(closes, self.bt.SLOW_LEN)
        atr_now = self.bt._atr(entry_candles, self.bt.ATR_LEN)
        atr_mean = self.bt._sma(atr_now, self.bt.ATR_MA_LEN)
        bar_range = [c.high - c.low for c in entry_candles]
        range_mean = self.bt._sma(bar_range, self.bt.RANGE_AVG_LEN)
        vol_mean = self.bt._sma(volumes, self.bt.VOL_LEN)
        body_abs = [abs(c.close - c.open) for c in entry_candles]
        body_avg = self.bt._sma(body_abs, self.bt.RANGE_AVG_LEN)
        latest_highs, latest_lows = self.bt._latest_swings(highs, lows, self.bt.SWING_LEN)
        daily_open_map = self.bt._daily_open_map(entry_candles)
        macro_map = self.bt._map_completed_indices(entry_candles, context["macro"]["candles"], timedelta(hours=4))
        trend_map = self.bt._map_completed_indices(entry_candles, context["trend"]["candles"], timedelta(hours=1))
        setup_map = self.bt._map_completed_indices(entry_candles, context["setup"]["candles"], timedelta(minutes=15))

        candidates: list[dict[str, Any]] = []
        audit = Counter()
        for index in range(250, len(entry_candles) - 2):
            candle = entry_candles[index]
            hour_ny = candle.time.astimezone(NY_TZ).hour
            if hour_ny not in self.allowed_hours_ny:
                audit["hour_filtered"] += 1
                continue
            values = {
                "atr": atr_now[index],
                "ema_fast": ema_fast[index],
                "ema_slow": ema_slow[index],
                "atr_mean": atr_mean[index],
                "range_mean": range_mean[index],
                "body_avg": body_avg[index],
                "macro_idx": macro_map[index],
                "trend_idx": trend_map[index],
                "setup_idx": setup_map[index],
            }
            if any(value is None for value in values.values()):
                audit["warmup_or_context_missing"] += 1
                continue
            features = self._features(
                index=index,
                candle=candle,
                entry_candles=entry_candles,
                closes=closes,
                highs=highs,
                lows=lows,
                ema_fast=ema_fast,
                ema_slow=ema_slow,
                atr_now=atr_now,
                atr_mean=atr_mean,
                bar_range=bar_range,
                range_mean=range_mean,
                vol_mean=vol_mean,
                body_avg=body_avg,
                latest_highs=latest_highs,
                latest_lows=latest_lows,
                daily_open_map=daily_open_map,
                context=context,
                macro_idx=macro_map[index],
                trend_idx=trend_map[index],
                setup_idx=setup_map[index],
            )
            if features["market_regime"] != "EXPANSION":
                audit["not_expansion"] += 1
                continue
            conditions = {
                "pullback_valid": features["pullback_buy"],
                "displacement_AGG": features["bull_disp_agg"],
                "mtf_score_58": features["buy_mtf_score"] >= self.bt.MIN_QUANT_AGG,
                "quant_ok": features["quant_ok"],
                "compression_ok": features["compression_ok"],
                "impulse_ok": features["impulse_score"] >= self.bt.MIN_IMPULSE_AGG,
                "quant_score_ok": features["quant_score"] >= self.bt.MIN_QUANT_AGG,
                "confidence_AGG": features["buy_conf_agg"] >= self.bt.MIN_CONF_AGG,
                "preferred_side_not_opposite": features["preferred_side"] != "SELL",
            }
            compression_value = bool(conditions["compression_ok"])
            if self.variant.compression_mode == "quality":
                conditions.pop("compression_ok")
            missing = [key for key, ok in conditions.items() if not ok]
            if self.variant.compression_mode == "quality" and not missing:
                missing_filter = "compression_quality_only" if not compression_value else "fully_valid_non_overlap"
            elif len(missing) != 1:
                audit[f"missing_count_{len(missing)}"] += 1
                continue
            else:
                missing_filter = missing[0]
            if missing_filter not in self.variant.selected_missing_filters and not (
                self.variant.compression_mode == "quality"
                and missing_filter in {"compression_quality_only", "fully_valid_non_overlap"}
            ):
                audit[f"missing_{missing_filter}"] += 1
                continue
            minimum_passed = len(conditions) if missing_filter in {"compression_quality_only", "fully_valid_non_overlap"} else len(conditions) - 1
            if sum(1 for ok in conditions.values() if ok) < minimum_passed:
                audit["low_pass_count"] += 1
                continue
            risk = features["next_open"] - features["stop_price"]
            if risk <= 0 or risk > features["atr"] * self.bt.MAX_RISK_ATR * 1.25:
                audit["invalid_risk"] += 1
                continue
            candidates.append(
                {
                    **features,
                    "year": year,
                    "index": index,
                    "time": candle.time,
                    "hour_ny": hour_ny,
                    "session": self._session(hour_ny),
                    "atr_bucket": self._atr_bucket(features["atr_ratio"]),
                    "compression_ok": compression_value,
                    "displacement_agg": bool(features["bull_disp_agg"]),
                    "missing_filter": missing_filter,
                    "risk": risk,
                    "entry": features["next_open"],
                    "target": features["next_open"] + risk * features["rr"],
                }
            )
        return candidates, dict(audit)

    def _features(self, **kwargs: Any) -> dict[str, Any]:
        index = kwargs["index"]
        candle: Candle = kwargs["candle"]
        entry_candles: list[Candle] = kwargs["entry_candles"]
        closes = kwargs["closes"]
        highs = kwargs["highs"]
        lows = kwargs["lows"]
        ema_fast = kwargs["ema_fast"]
        ema_slow = kwargs["ema_slow"]
        atr_now = kwargs["atr_now"]
        atr_mean = kwargs["atr_mean"]
        bar_range = kwargs["bar_range"]
        range_mean = kwargs["range_mean"]
        vol_mean = kwargs["vol_mean"]
        body_avg = kwargs["body_avg"]
        latest_highs = kwargs["latest_highs"]
        latest_lows = kwargs["latest_lows"]
        daily_open_map = kwargs["daily_open_map"]
        context = kwargs["context"]
        atr_value = atr_now[index]
        ema_fast_value = ema_fast[index]
        ema_slow_value = ema_slow[index]
        atr_mean_value = atr_mean[index]
        range_mean_value = range_mean[index]
        body_avg_value = body_avg[index]

        candle_range = max(candle.high - candle.low, 1e-9)
        body_pct = abs(candle.close - candle.open) / candle_range * 100.0
        atr_ratio = atr_value / atr_mean_value if atr_mean_value else 1.0
        range_ratio = candle_range / range_mean_value if range_mean_value else 1.0
        local_bull = ema_fast_value > ema_slow_value and candle.close > ema_fast_value
        ema_spread_atr = abs(ema_fast_value - ema_slow_value) / max(atr_value, 1e-9)
        ema_fast_prev_3 = ema_fast[index - 3] if index >= 3 and ema_fast[index - 3] is not None else ema_fast_value
        ema_slope_atr = abs(ema_fast_value - ema_fast_prev_3) / max(atr_value, 1e-9)
        local_slope_up = index > 0 and ema_fast[index - 1] is not None and ema_fast_value > ema_fast[index - 1]
        chop_ratio = body_avg_value / range_mean_value if range_mean_value else 1.0
        quant_expansion_ok = atr_ratio >= self.bt.MIN_ATR_EXPANSION or range_ratio >= self.bt.MIN_RANGE_EXPANSION
        quant_trend_ok = ema_spread_atr >= self.bt.MIN_EMA_SPREAD_ATR and ema_slope_atr >= self.bt.MIN_SLOPE_ATR
        quant_chop_ok = chop_ratio <= self.bt.MAX_CHOP_RATIO or range_ratio >= 1.20
        quant_ok = quant_expansion_ok and quant_trend_ok and quant_chop_ok

        macro_row = context["macro"]["rows"][kwargs["macro_idx"]]
        trend_row = context["trend"]["rows"][kwargs["trend_idx"]]
        setup_row = context["setup"]["rows"][kwargs["setup_idx"]]
        day_open = daily_open_map.get(candle.time.date(), candle.open)
        buy_mtf_score, sell_mtf_score = self.bt._mtf_scores(
            local_bull=local_bull,
            local_bear=False,
            macro_row=macro_row,
            trend_row=trend_row,
            setup_row=setup_row,
            day_bull=candle.close > day_open,
            day_bear=candle.close < day_open,
        )
        close_power_buy = (candle.close - candle.low) / candle_range
        recent_compression = self.bt._recent_compression(index, atr_now, atr_mean, bar_range, range_mean)
        compression_ok = recent_compression or atr_ratio >= 1.10 or range_ratio >= 1.20
        velocity_ref = closes[index - self.bt.VELOCITY_LEN] if index >= self.bt.VELOCITY_LEN else closes[0]
        velocity = abs(candle.close - velocity_ref) / max(atr_value, 1e-9)
        impulse_score = 0
        impulse_score += 20 if body_pct >= self.bt.BODY_MIN_AGG else 0
        impulse_score += 20 if range_ratio >= self.bt.MIN_RANGE_EXPANSION else 0
        impulse_score += 20 if velocity >= 0.35 else 0
        impulse_score += 20 if ema_slope_atr >= self.bt.MIN_SLOPE_ATR else 0
        impulse_score += 20 if compression_ok else 0
        impulse_score = min(100, impulse_score)
        quant_score = 0
        quant_score += 20 if atr_ratio >= self.bt.MIN_ATR_EXPANSION else 0
        quant_score += 20 if range_ratio >= self.bt.MIN_RANGE_EXPANSION else 0
        quant_score += 20 if ema_spread_atr >= self.bt.MIN_EMA_SPREAD_ATR else 0
        quant_score += 20 if ema_slope_atr >= self.bt.MIN_SLOPE_ATR else 0
        quant_score += 20 if quant_chop_ok else 0
        quant_score += self.bt.COMPRESSION_BONUS if recent_compression else 0
        quant_score = min(100, quant_score)
        range_high = max(highs[max(0, index - self.bt.RANGE_LEN + 1) : index + 1])
        range_low = min(lows[max(0, index - self.bt.RANGE_LEN + 1) : index + 1])
        eq = (range_high + range_low) / 2.0
        pd_buy_ok = candle.close <= eq or macro_row["discount"] or trend_row["discount"]
        swing_low = latest_lows[index]
        liq_low = min(lows[max(0, index - self.bt.LIQUIDITY_LOOKBACK) : index]) if index > 0 else candle.low
        liquidity_quality_buy = (swing_low is not None and candle.low < swing_low and candle.close > swing_low) or (
            candle.low < liq_low and candle.close > liq_low
        )
        bull_disp_a = candle.close > candle.open and body_pct >= self.bt.BODY_MIN_A and close_power_buy >= 0.60
        bull_disp_agg = candle.close > candle.open and body_pct >= self.bt.BODY_MIN_AGG and close_power_buy >= 0.52
        pullback_buy = (
            local_bull
            and local_slope_up
            and candle.low <= ema_fast_value + atr_value * self.bt.PULLBACK_ATR_PCT
            and candle.close > ema_fast_value
            and candle.close > candle.open
        )
        trend_quality_buy = (20 if local_bull else 0) + (15 if local_slope_up else 0) + (15 if ema_spread_atr >= self.bt.MIN_EMA_SPREAD_ATR else 0)
        structure_quality_buy = (20 if liquidity_quality_buy else 0) + (15 if bull_disp_a else 8 if bull_disp_agg else 0) + (10 if pd_buy_ok else 0)
        continuation_quality_buy = (25 if pullback_buy else 0) + (10 if bull_disp_agg else 0)
        buy_conf_agg = min(100, round((buy_mtf_score * 0.28) + (quant_score * 0.25) + (impulse_score * 0.22) + (trend_quality_buy * 0.15) + (continuation_quality_buy * 0.10)))
        market_regime = "EXPANSION" if quant_score >= 75 and impulse_score >= 65 and buy_mtf_score >= 65 else "NORMAL" if quant_score >= 55 else "CHOP"
        preferred_side = "BUY" if buy_mtf_score > sell_mtf_score + 15 else "SELL" if sell_mtf_score > buy_mtf_score + 15 else "NEUTRAL"
        rr = self.bt._resolve_rr(is_a=False, market_regime=market_regime, quant_score=quant_score, impulse_score=impulse_score)
        stop_price = min(candle.low, ema_slow_value - atr_value * self.bt.SL_ATR_PCT)
        return {
            "atr": atr_value,
            "atr_ratio": atr_ratio,
            "range_ratio": range_ratio,
            "body_pct": body_pct,
            "quant_ok": quant_ok,
            "compression_ok": compression_ok,
            "pullback_buy": pullback_buy,
            "bull_disp_agg": bull_disp_agg,
            "buy_mtf_score": buy_mtf_score,
            "sell_mtf_score": sell_mtf_score,
            "impulse_score": impulse_score,
            "quant_score": quant_score,
            "buy_conf_agg": buy_conf_agg,
            "market_regime": market_regime,
            "preferred_side": preferred_side,
            "next_open": entry_candles[index + 1].open,
            "entry_index": index + 1,
            "entry_time": entry_candles[index + 1].time,
            "stop_price": stop_price,
            "rr": rr,
        }

    def _cluster_representatives(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        representatives: list[dict[str, Any]] = []
        cluster: list[dict[str, Any]] = []
        for item in candidates:
            if not cluster or item["time"] - cluster[-1]["time"] <= timedelta(minutes=20):
                cluster.append(item)
                continue
            representatives.append(self._select_cluster_rep(cluster))
            cluster = [item]
        if cluster:
            representatives.append(self._select_cluster_rep(cluster))
        return representatives

    @staticmethod
    def _select_cluster_rep(cluster: list[dict[str, Any]]) -> dict[str, Any]:
        def score(item: dict[str, Any]) -> tuple[float, float, float]:
            return (item["buy_conf_agg"], item["buy_mtf_score"], -item["risk"])

        chosen = max(cluster, key=score)
        chosen["cluster_id"] = f"{cluster[0]['time'].isoformat()}->{cluster[-1]['time'].isoformat()}"
        chosen["cluster_bars"] = len(cluster)
        return chosen

    def _simulate_candidate(self, *, year: int, entry_candles: list[Candle], item: dict[str, Any]) -> CandidateTrade | None:
        entry_index = item["entry_index"]
        entry = item["entry"]
        stop = item["stop_price"]
        target = item["target"]
        risk = item["risk"]
        if risk <= 0:
            return None
        max_scan = min(len(entry_candles), entry_index + 80)
        mfe = 0.0
        mae = 0.0
        partial_taken = False
        protected = False
        raw_result = "OPEN_UNKNOWN"
        raw_r = 0.0
        managed_result = "OPEN_UNKNOWN"
        realized_r = 0.0
        exit_time = entry_candles[max_scan - 1].time
        for idx in range(entry_index, max_scan):
            candle = entry_candles[idx]
            favorable = (candle.high - entry) / risk
            adverse = (entry - candle.low) / risk
            mfe = max(mfe, favorable)
            mae = max(mae, adverse)
            stop_hit = candle.low <= stop
            target_hit = candle.high >= target
            if favorable >= 0.5:
                partial_taken = True
            if favorable >= 0.8:
                protected = True
            if stop_hit or target_hit:
                exit_time = candle.time
                if stop_hit:
                    raw_result = "SL"
                    raw_r = -1.01
                    if protected:
                        managed_result = "PROTECTED_STOP_AFTER_0_8R"
                        realized_r = 0.4
                    elif partial_taken:
                        managed_result = "BE_AFTER_PARTIAL"
                        realized_r = 0.25
                    else:
                        managed_result = "SL"
                        realized_r = -1.01
                else:
                    raw_result = "TP"
                    raw_r = item["rr"] - 0.01
                    managed_result = "TP_WITH_PARTIAL"
                    realized_r = 0.25 + (item["rr"] * 0.5)
                break
        else:
            close = entry_candles[max_scan - 1].close
            raw_r = (close - entry) / risk
            raw_result = "OPEN_UNKNOWN_WIN" if raw_r > 0 else "OPEN_UNKNOWN_LOSS"
            if protected:
                managed_result = "PROTECTED_OPEN"
                realized_r = max(0.4, raw_r)
            elif partial_taken:
                managed_result = "PARTIAL_OPEN"
                realized_r = max(0.25, raw_r * 0.5 + 0.25)
            else:
                managed_result = raw_result
                realized_r = raw_r
        return CandidateTrade(
            year=year,
            signal_time=item["time"],
            entry_time=item["entry_time"],
            side="BUY",
            missing_filter=item["missing_filter"],
            session=item["session"],
            atr_bucket=item["atr_bucket"],
            compression_ok=item["compression_ok"],
            displacement_agg=item["displacement_agg"],
            cluster_id=item["cluster_id"],
            hour_ny=item["hour_ny"],
            entry=round(entry, 5),
            stop=round(stop, 5),
            target=round(target, 5),
            risk=round(risk, 5),
            rr=round(item["rr"], 4),
            raw_result=raw_result,
            raw_r=round(raw_r, 4),
            managed_result=managed_result,
            realized_r=round(realized_r, 4),
            mfe_r=round(mfe, 4),
            mae_r=round(mae, 4),
            confidence=item["buy_conf_agg"],
            mtf_score=item["buy_mtf_score"],
            quant_score=item["quant_score"],
            impulse_score=item["impulse_score"],
            atr_ratio=round(item["atr_ratio"], 4),
            range_ratio=round(item["range_ratio"], 4),
            body_pct=round(item["body_pct"], 4),
        )

    @staticmethod
    def _year_period(year: int) -> tuple[datetime, datetime]:
        if year == 2026:
            return datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc)
        return datetime(year, 1, 1, tzinfo=timezone.utc), datetime(year, 12, 31, 23, 59, tzinfo=timezone.utc)

    @staticmethod
    def _metrics(trades: list[CandidateTrade]) -> dict[str, Any]:
        if not trades:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy_R": 0.0,
                "net_R": 0.0,
                "max_drawdown_R": 0.0,
                "losing_streak": 0,
            }
        wins = [t.realized_r for t in trades if t.realized_r > 0]
        losses = [t.realized_r for t in trades if t.realized_r < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        equity = peak = max_dd = 0.0
        streak = losing_streak = 0
        for trade in trades:
            equity += trade.realized_r
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if trade.realized_r < 0:
                streak += 1
                losing_streak = max(losing_streak, streak)
            else:
                streak = 0
        net = sum(t.realized_r for t in trades)
        return {
            "trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100.0, 2),
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else 999.0,
            "expectancy_R": round(net / len(trades), 4),
            "net_R": round(net, 4),
            "max_drawdown_R": round(max_dd, 4),
            "losing_streak": losing_streak,
        }

    def _breakdown(self, trades: list[CandidateTrade], attr: str) -> dict[str, Any]:
        grouped: dict[str, list[CandidateTrade]] = defaultdict(list)
        for trade in trades:
            grouped[str(getattr(trade, attr))].append(trade)
        return {key: self._metrics(bucket) for key, bucket in sorted(grouped.items())}

    @staticmethod
    def _session(hour_ny: int) -> str:
        if hour_ny in {1}:
            return "asia_to_london"
        if hour_ny in {4, 5}:
            return "london"
        if hour_ny in {9}:
            return "ny_am"
        if hour_ny in {15}:
            return "ny_pm"
        if hour_ny in {19}:
            return "asia_open"
        return "other"

    @staticmethod
    def _atr_bucket(atr_ratio: float) -> str:
        if atr_ratio < 0.85:
            return "low_atr"
        if atr_ratio < 1.10:
            return "normal_atr"
        if atr_ratio < 1.45:
            return "high_atr"
        return "extreme_atr"

    def _real_trade_signal_times(self, year: int) -> set[datetime]:
        candidates = [
            YEARLY_DIR / f"{year}_v56_aggressive_filtered_b_all_h4_fixed_trades.csv",
            YEARLY_DIR / f"{year}_v56_aggressive_filtered_b_all_jan_mar_partial_h4_fixed_trades.csv",
            YEARLY_DIR / "2025_v56_aggressive_filtered_b_all_trades.csv",
        ]
        path = next((item for item in candidates if item.exists()), None)
        if path is None:
            return set()
        result: set[datetime] = set()
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                value = row.get("signal_time") or row.get("entry_time")
                if not value:
                    continue
                result.add(datetime.fromisoformat(value))
        return result

    @staticmethod
    def _write_jsonl(path: Path, trades: list[CandidateTrade]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for trade in trades:
                handle.write(json.dumps(asdict(trade), default=str) + "\n")

    @staticmethod
    def _write_csv(path: Path, trades: list[CandidateTrade]) -> None:
        if not trades:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(trades[0]).keys()))
            writer.writeheader()
            for trade in trades:
                writer.writerow(asdict(trade))

    @staticmethod
    def _decision(yearly: dict[str, Any]) -> str:
        full_years = [yearly[key]["metrics"] for key in ("2023", "2024", "2025")]
        positive = [item for item in full_years if item["trades"] >= 20 and item["profit_factor"] >= 1.2 and item["expectancy_R"] > 0]
        if len(positive) >= 2 and all(item["max_drawdown_R"] <= 8 for item in positive):
            return "PROMISING_RESEARCH_KEEP_TESTING"
        if len(positive) == 1:
            return "NEEDS_REDESIGN_OR_MORE_FILTERING"
        return "REJECT_CURRENT_FORM"

    @staticmethod
    def _markdown(payload: dict[str, Any]) -> str:
        lines = [
            "# REACTION_ZONE_EXPANSION_BRAIN Replay",
            "",
            f"- variant: `{payload['variant']['code']}`",
            f"- status: {payload['status']}",
            f"- baseline: `{payload['baseline']}`",
            f"- decision: `{payload['decision']}`",
            "",
            "## Rules",
        ]
        for key, value in payload["rules"].items():
            lines.append(f"- {key}: {value}")
        lines.extend(
            [
                "",
                "## Yearly Metrics",
                "",
                "| Year | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for year, item in payload["yearly"].items():
            metric = item["metrics"]
            lines.append(
                f"| {year} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']} |"
            )
        lines.extend(
            [
                "",
                "## Aggregate By Missing Filter",
                "",
                "| Missing Filter | Trades | WR | PF | Exp R | Net R | DD R |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for missing_filter, metric in payload["aggregate_by_missing_filter"].items():
            lines.append(
                f"| {missing_filter} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
        lines.extend(
            [
                "",
                "## Aggregate By Session",
                "",
                "| Session | Trades | WR | PF | Exp R | Net R | DD R |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for session, metric in payload["aggregate_by_session"].items():
            lines.append(
                f"| {session} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
        lines.extend(
            [
                "",
                "## Aggregate By ATR Bucket",
                "",
                "| ATR Bucket | Trades | WR | PF | Exp R | Net R | DD R |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for bucket, metric in payload["aggregate_by_atr_bucket"].items():
            lines.append(
                f"| {bucket} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
        lines.extend(
            [
                "",
                "## Aggregate By Displacement_AGG",
                "",
                "| displacement_AGG | Trades | WR | PF | Exp R | Net R | DD R |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for state, metric in payload["aggregate_by_displacement_agg"].items():
            lines.append(
                f"| {state} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
            )
        lines.extend(["", "## Yearly By Missing Filter"])
        for year, item in payload["yearly"].items():
            lines.extend(
                [
                    "",
                    f"### {year}",
                    "",
                    "| Missing Filter | Trades | WR | PF | Exp R | Net R | DD R |",
                    "|---|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for missing_filter, metric in item["by_missing_filter"].items():
                lines.append(
                    f"| {missing_filter} | {metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
                    f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} |"
                )
        aggregate = payload["aggregate"]
        lines.extend(
            [
                "",
                "## Aggregate",
                "",
                f"- trades: {aggregate['trades']}",
                f"- win_rate: {aggregate['win_rate']}",
                f"- profit_factor: {aggregate['profit_factor']}",
                f"- expectancy_R: {aggregate['expectancy_R']}",
                f"- net_R: {aggregate['net_R']}",
                f"- max_drawdown_R: {aggregate['max_drawdown_R']}",
                "",
                "## Read",
                "",
                "- If a year has PF < 1.2 or negative expectancy, this candidate is not robust enough for operational use.",
                "- This replay is stricter than broad reaction-zone scalping and does not change live/demo execution.",
            ]
        )
        return "\n".join(lines) + "\n"


def main() -> None:
    payload = ReactionZoneExpansionBrainReplay().run()
    print(
        json.dumps(
            {
                "strategy": payload["strategy"],
                "decision": payload["decision"],
                "aggregate": payload["aggregate"],
                "report": str((OUTPUT_DIR / "reaction_zone_expansion_brain_replay.md").resolve()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
