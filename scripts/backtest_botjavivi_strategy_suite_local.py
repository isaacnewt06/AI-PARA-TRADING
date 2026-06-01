"""Safe local replay of selected BOTJAVIVI strategy families.

This script is research-only:
- no MT5 connection
- no order execution
- closed-timeframe context only
- pessimistic TP/SL ordering when both are touched in the same M1 bar
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.blueprint_backtester import BlueprintBacktester, Candle


INPUT_DIR = ROOT / "data" / "backtests" / "input"
OUT_DIR = ROOT / "data" / "strategies"
OUT_JSON = OUT_DIR / "botjavivi_strategy_suite_local_multiyear.json"
OUT_MD = OUT_DIR / "botjavivi_strategy_suite_local_multiyear.md"
SYMBOL = "XAUUSDm"
YEARS = [2023, 2024, 2025, 2026]
INITIAL_BALANCE = 500.0
VOLUME_LOTS = 0.01
CONTRACT_SIZE = 100.0
COMMISSION_RATE = 0.0001
SPREAD_PRICE = 0.30
SLIPPAGE_PER_SIDE = 0.05
PIP = 0.1
NY_TZ = ZoneInfo("America/New_York")


@dataclass(slots=True)
class Signal:
    strategy: str
    direction: str
    signal_time: datetime
    entry: float
    stop: float
    target: float
    confidence: float
    reason: str
    market_bias: str
    hour_utc: int
    hour_ny: int


@dataclass(slots=True)
class Trade:
    year: int
    session: str
    strategy: str
    direction: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry: float
    stop: float
    target: float
    exit: float
    net: float
    pnl_r: float
    exit_reason: str
    confidence: float
    market_bias: str
    hour_utc: int
    hour_ny: int


@dataclass(slots=True)
class Context:
    symbol: str
    timestamp: datetime
    m1: list[dict]
    m5: list[dict]
    m15: list[dict]
    h1: list[dict]
    ema_9_m1: float
    ema_21_m1: float
    ema_9_m5: float
    ema_21_m5: float
    rsi_14: float
    atr_14: float
    atr_average: float
    volume_ratio: float
    market_bias: str

    @property
    def ema_diff_m1(self) -> float:
        return self.ema_9_m1 - self.ema_21_m1

    @property
    def ema_diff_m5(self) -> float:
        return self.ema_9_m5 - self.ema_21_m5

    @property
    def volatility_ratio(self) -> float:
        return self.atr_14 / self.atr_average if self.atr_average else 1.0


def candle_dict(c: Candle) -> dict:
    return {
        "time": c.time,
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "tick_volume": c.volume,
        "volume": c.volume,
    }


def load_year(loader: BlueprintBacktester, year: int) -> list[Candle]:
    path = INPUT_DIR / f"{SYMBOL}_M1_{year}.csv"
    if not path.exists():
        return []
    candles = loader._load_candles(path)
    if year == 2026:
        return [c for c in candles if c.time <= datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc)]
    return candles


def completed_indices(entry: list[Candle], context: list[Candle], minutes: int) -> list[int | None]:
    out: list[int | None] = [None] * len(entry)
    pointer = -1
    for i, c in enumerate(entry):
        cutoff = c.time.timestamp() - minutes * 60
        while pointer + 1 < len(context) and context[pointer + 1].time.timestamp() <= cutoff:
            pointer += 1
        out[i] = pointer if pointer >= 0 else None
    return out


def rsi(candles: list[Candle], period: int = 14) -> list[float | None]:
    values: list[float | None] = [None] * len(candles)
    if len(candles) < period + 1:
        return values
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(candles)):
        change = candles[i].close - candles[i - 1].close
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        if i >= period:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            values[i] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return values


def rolling_mean(values: list[float | None], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        window = [v for v in values[max(0, i - period + 1) : i + 1] if v is not None]
        if window:
            out[i] = sum(window) / len(window)
    return out


def body_ratio(c: dict) -> float:
    return abs(float(c["close"]) - float(c["open"])) / max(candle_range(c), 1e-9)


def candle_range(c: dict) -> float:
    return max(float(c["high"]) - float(c["low"]), 0.0)


def wick_top(c: dict) -> float:
    return max(float(c["high"]) - max(float(c["open"]), float(c["close"])), 0.0)


def wick_bottom(c: dict) -> float:
    return max(min(float(c["open"]), float(c["close"])) - float(c["low"]), 0.0)


def recent_high(candles: list[dict], lookback: int) -> float:
    return max(float(c["high"]) for c in candles[-lookback:])


def recent_low(candles: list[dict], lookback: int) -> float:
    return min(float(c["low"]) for c in candles[-lookback:])


def close_to_extreme_ratio(c: dict, direction: str) -> float:
    rng = max(candle_range(c), 1e-9)
    if direction == "BUY":
        return (float(c["close"]) - float(c["low"])) / rng
    return (float(c["high"]) - float(c["close"])) / rng


def make_context(
    i: int,
    m1: list[Candle],
    m5: list[Candle],
    m15: list[Candle],
    h1: list[Candle],
    maps: dict[str, list[int | None]],
    indicators: dict[str, list],
) -> Context | None:
    m5_idx = maps["m5"][i]
    m15_idx = maps["m15"][i]
    h1_idx = maps["h1"][i]
    if m5_idx is None or m15_idx is None or h1_idx is None:
        return None
    if i < 60 or m5_idx < 25 or m15_idx < 8 or h1_idx < 6:
        return None
    ema_9_m1 = indicators["ema_9_m1"][i] or 0.0
    ema_21_m1 = indicators["ema_21_m1"][i] or 0.0
    ema_9_m5 = indicators["ema_9_m5"][m5_idx] or 0.0
    ema_21_m5 = indicators["ema_21_m5"][m5_idx] or 0.0
    atr_14 = indicators["atr_m5"][m5_idx] or 0.0
    atr_average = max(indicators["atr_avg_m5"][m5_idx] or 0.0, atr_14)
    rsi_14 = indicators["rsi_m5"][m5_idx] or 50.0
    volumes = [c.volume for c in m1[max(0, i - 19) : i + 1]]
    avg_volume = mean(volumes) if volumes else 1.0
    volume_ratio = m1[i].volume / max(avg_volume, 1e-9)

    score = 0.0
    ema_diff_m5 = ema_9_m5 - ema_21_m5
    ema_diff_m1 = ema_9_m1 - ema_21_m1
    if ema_diff_m5 > atr_14 * 0.3:
        score += 1.0
    elif ema_diff_m5 < -atr_14 * 0.3:
        score -= 1.0
    if rsi_14 > 55:
        score += 1.0
    elif rsi_14 < 45:
        score -= 1.0
    if ema_diff_m1 > 0 and ema_diff_m5 > 0:
        score += 0.5
    elif ema_diff_m1 < 0 and ema_diff_m5 < 0:
        score -= 0.5
    market_bias = "BULLISH" if score >= 1 else "BEARISH" if score <= -1 else "NEUTRAL"

    return Context(
        symbol=SYMBOL,
        timestamp=m1[i].time,
        m1=[candle_dict(c) for c in m1[i - 59 : i + 1]],
        m5=[candle_dict(c) for c in m5[max(0, m5_idx - 39) : m5_idx + 1]],
        m15=[candle_dict(c) for c in m15[max(0, m15_idx - 19) : m15_idx + 1]],
        h1=[candle_dict(c) for c in h1[max(0, h1_idx - 9) : h1_idx + 1]],
        ema_9_m1=ema_9_m1,
        ema_21_m1=ema_21_m1,
        ema_9_m5=ema_9_m5,
        ema_21_m5=ema_21_m5,
        rsi_14=rsi_14,
        atr_14=atr_14,
        atr_average=atr_average,
        volume_ratio=volume_ratio,
        market_bias=market_bias,
    )


def liquidity_sweep_reversal(context: Context) -> Signal | None:
    m1 = context.m1
    if len(m1) < 12:
        return None
    current = m1[-1]
    atr = max(context.atr_14, PIP * 4)
    rh = recent_high(m1[:-1], 10)
    rl = recent_low(m1[:-1], 10)
    rng = candle_range(current)
    body = body_ratio(current)
    top_ratio = wick_top(current) / max(rng, 1e-9)
    bottom_ratio = wick_bottom(current) / max(rng, 1e-9)
    if rng < atr * 0.65 or body > 0.36:
        return None
    if float(current["high"]) > rh and float(current["close"]) < rh and top_ratio > 0.55 and float(current["high"]) - rh >= atr * 0.08:
        if float(current["close"]) >= context.ema_9_m1:
            return None
        if context.market_bias == "BULLISH" and context.rsi_14 < 66:
            return None
        entry = float(current["close"])
        stop = float(current["high"]) + PIP * 1.5
        risk = stop - entry
        if risk <= 0:
            return None
        return make_signal(context, "liquidity_sweep_reversal", "SELL", entry, stop, entry - max(risk * 3.0, atr * 1.2), 0.76)
    if float(current["low"]) < rl and float(current["close"]) > rl and bottom_ratio > 0.55 and rl - float(current["low"]) >= atr * 0.08:
        if float(current["close"]) <= context.ema_9_m1:
            return None
        if context.market_bias == "BEARISH" and context.rsi_14 > 34:
            return None
        entry = float(current["close"])
        stop = float(current["low"]) - PIP * 1.5
        risk = entry - stop
        if risk <= 0:
            return None
        return make_signal(context, "liquidity_sweep_reversal", "BUY", entry, stop, entry + max(risk * 3.0, atr * 1.2), 0.76)
    return None


def trend_pullback(context: Context) -> Signal | None:
    m1 = context.m1
    if len(m1) < 12 or context.market_bias == "NEUTRAL":
        return None
    current, prev, prev2 = m1[-1], m1[-2], m1[-3]
    atr = max(context.atr_14, PIP * 4)
    older = m1[-11:-1]
    rh = max(float(c["high"]) for c in older)
    rl = min(float(c["low"]) for c in older)
    touch_band = atr * 0.18
    rng = candle_range(current)
    body = body_ratio(current)
    rsi_value = float(context.rsi_14 or 50.0)
    bullish = context.market_bias == "BULLISH" and context.ema_diff_m5 > 0 and context.ema_diff_m1 > 0
    bearish = context.market_bias == "BEARISH" and context.ema_diff_m5 < 0 and context.ema_diff_m1 < 0
    if not bullish and not bearish:
        return None
    pullback_depth = abs(float(current["close"]) - context.ema_9_m1)
    if pullback_depth > atr * 0.65 or pullback_depth < atr * 0.08:
        return None
    if rng < atr * 0.35 or body < 0.45:
        return None
    if bullish:
        touched = min(float(prev["low"]), float(prev2["low"])) <= context.ema_9_m1 + touch_band
        resumed = float(current["close"]) > max(float(prev["high"]), float(prev2["high"]))
        if float(current["close"]) <= float(current["open"]) or not touched or not resumed:
            return None
        if rsi_value < 54 or rsi_value > 68:
            return None
        if float(current["close"]) >= rh - atr * 0.20:
            return None
        if context.ema_21_m5 and abs(float(current["close"]) - context.ema_21_m5) > atr * 1.25:
            return None
        entry = float(current["close"])
        stop = min(float(current["low"]), float(prev["low"])) - PIP * 1.5
        risk = entry - stop
        if risk <= 0:
            return None
        return make_signal(context, "trend_pullback", "BUY", entry, stop, entry + max(risk * 2.8, atr * 1.2), 0.68)
    touched = max(float(prev["high"]), float(prev2["high"])) >= context.ema_9_m1 - touch_band
    resumed = float(current["close"]) < min(float(prev["low"]), float(prev2["low"]))
    if float(current["close"]) >= float(current["open"]) or not touched or not resumed:
        return None
    if rsi_value > 46 or rsi_value < 32:
        return None
    if float(current["close"]) <= rl + atr * 0.20:
        return None
    if context.ema_21_m5 and abs(float(current["close"]) - context.ema_21_m5) > atr * 1.25:
        return None
    entry = float(current["close"])
    stop = max(float(current["high"]), float(prev["high"])) + PIP * 1.5
    risk = stop - entry
    if risk <= 0:
        return None
    return make_signal(context, "trend_pullback", "SELL", entry, stop, entry - max(risk * 2.8, atr * 1.2), 0.68)


def breakout_expansion(context: Context) -> Signal | None:
    m1 = context.m1
    if len(m1) < 12:
        return None
    current = m1[-1]
    prior = m1[-7:-1]
    atr = max(context.atr_14, PIP * 4)
    avg_prior = sum(candle_range(c) for c in prior) / max(len(prior), 1)
    rh = recent_high(m1[:-1], 6)
    rl = recent_low(m1[:-1], 6)
    rng = candle_range(current)
    if avg_prior <= 0 or rng < avg_prior * 1.7 or body_ratio(current) < 0.6:
        return None
    if float(current["close"]) > rh and context.market_bias != "BEARISH":
        entry = float(current["close"])
        stop = min(float(current["low"]), rh) - PIP * 1.2
        risk = entry - stop
        if risk <= 0:
            return None
        return make_signal(context, "breakout_expansion", "BUY", entry, stop, entry + max(risk * 2.7, atr * 1.4), 0.66)
    if float(current["close"]) < rl and context.market_bias != "BULLISH":
        entry = float(current["close"])
        stop = max(float(current["high"]), rl) + PIP * 1.2
        risk = stop - entry
        if risk <= 0:
            return None
        return make_signal(context, "breakout_expansion", "SELL", entry, stop, entry - max(risk * 2.7, atr * 1.4), 0.66)
    return None


def microimpulse_institutional(context: Context) -> Signal | None:
    structure = inspect_m5_structure(context.m5)
    if not structure:
        return None
    direction, reaction_level, choch_level = structure
    bias = micro_htf_bias(context)
    if direction == "BUY" and bias == "BEARISH":
        return None
    if direction == "SELL" and bias == "BULLISH":
        return None
    trigger = inspect_m1_trigger(context, direction)
    if not trigger:
        return None
    entry = float(trigger["close"])
    atr_value = max(float(context.atr_14 or 0.0), PIP * 2.5)
    micro_window = context.m1[-4:]
    max_sl_distance = 350 * PIP
    if direction == "BUY":
        micro_reaction = min(float(c["low"]) for c in micro_window)
        stop = max(reaction_level, micro_reaction) - PIP * 0.4
        risk = entry - stop
        if risk <= 0 or risk > max_sl_distance or risk > atr_value * 1.25:
            return None
        target = entry + max(risk * 1.2, atr_value * 0.85)
    else:
        micro_reaction = max(float(c["high"]) for c in micro_window)
        stop = min(reaction_level, micro_reaction) + PIP * 0.4
        risk = stop - entry
        if risk <= 0 or risk > max_sl_distance or risk > atr_value * 1.25:
            return None
        target = entry - max(risk * 1.2, atr_value * 0.85)
    confidence = score_micro_confidence(context, trigger, bias, choch_confirmed=True)
    if confidence < 0.70:
        return None
    return make_signal(context, "microimpulse_institutional", direction, entry, stop, target, confidence)


def micro_htf_bias(context: Context) -> str:
    def ema_from_dicts(candles: list[dict], period: int) -> float:
        prices = [float(c["close"]) for c in candles]
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        ema_value = sum(prices[:period]) / period
        multiplier = 2 / (period + 1)
        for price in prices[period:]:
            ema_value = ((price - ema_value) * multiplier) + ema_value
        return ema_value

    m15_fast = ema_from_dicts(context.m15, 5)
    m15_slow = ema_from_dicts(context.m15, 9)
    h1_fast = ema_from_dicts(context.h1, 4)
    h1_slow = ema_from_dicts(context.h1, 8)
    bullish = 0
    bearish = 0
    if m15_fast > m15_slow and float(context.m15[-1]["close"]) >= m15_fast:
        bullish += 1
    elif m15_fast < m15_slow and float(context.m15[-1]["close"]) <= m15_fast:
        bearish += 1
    if h1_fast > h1_slow and float(context.h1[-1]["close"]) >= h1_fast:
        bullish += 1
    elif h1_fast < h1_slow and float(context.h1[-1]["close"]) <= h1_fast:
        bearish += 1
    if context.market_bias == "BULLISH":
        bullish += 1
    elif context.market_bias == "BEARISH":
        bearish += 1
    if bullish >= 2 and bearish == 0:
        return "BULLISH"
    if bearish >= 2 and bullish == 0:
        return "BEARISH"
    return "NEUTRAL"


def inspect_m5_structure(m5: list[dict]) -> tuple[str, float, float] | None:
    recent = m5[-20:]
    end_index = len(recent) - 2
    start_index = max(2, len(recent) - 6)
    for idx in range(end_index, start_index - 1, -1):
        current = recent[idx]
        history = recent[max(0, idx - 20) : idx]
        follow = recent[idx + 1 :]
        if len(history) < 5 or not follow:
            continue
        rh = max(float(c["high"]) for c in history)
        rl = min(float(c["low"]) for c in history)
        close = float(current["close"])
        open_ = float(current["open"])
        high = float(current["high"])
        low = float(current["low"])
        body = body_ratio(current)
        if low < rl and close > rl and close >= open_ and body <= 0.65:
            choch_level = max(float(c["high"]) for c in recent[max(0, idx - 3) : idx + 1])
            if any(float(c["close"]) > choch_level for c in follow):
                reaction_level = min(low, min(float(c["low"]) for c in follow[:2]))
                return "BUY", reaction_level, choch_level
        if high > rh and close < rh and close <= open_ and body <= 0.65:
            choch_level = min(float(c["low"]) for c in recent[max(0, idx - 3) : idx + 1])
            if any(float(c["close"]) < choch_level for c in follow):
                reaction_level = max(high, max(float(c["high"]) for c in follow[:2]))
                return "SELL", reaction_level, choch_level
    return None


def inspect_m1_trigger(context: Context, direction: str) -> dict | None:
    m1 = context.m1[-20:]
    current = m1[-1]
    prior = m1[-11:-1]
    if len(prior) < 5:
        return None
    current_range = candle_range(current)
    avg_range = sum(candle_range(c) for c in prior) / len(prior)
    atr_value = max(float(context.atr_14 or 0.0), PIP * 2.5)
    if current_range <= 0 or avg_range <= 0:
        return None
    if body_ratio(current) < 0.60:
        return None
    if current_range < avg_range * 1.30:
        return None
    if current_range < atr_value * 0.55:
        return None
    if close_to_extreme_ratio(current, direction) < 0.72:
        return None
    rh = max(float(c["high"]) for c in prior)
    rl = min(float(c["low"]) for c in prior)
    close = float(current["close"])
    open_ = float(current["open"])
    if direction == "BUY":
        if close <= open_ or close <= rh:
            return None
    elif close >= open_ or close >= rl:
        return None
    return current


def score_micro_confidence(context: Context, trigger: dict, bias: str, choch_confirmed: bool) -> float:
    recent = context.m1[-8:-1]
    avg_range = sum(candle_range(c) for c in recent) / max(len(recent), 1)
    range_boost = min(0.12, max(0.0, (candle_range(trigger) / max(avg_range, 1e-9) - 1.0) * 0.06))
    bias_boost = 0.06 if bias != "NEUTRAL" else 0.02
    volume_boost = min(0.08, max(0.0, (float(context.volume_ratio or 1.0) - 1.0) * 0.10))
    choch_boost = 0.05 if choch_confirmed else 0.0
    return min(0.90, 0.56 + (body_ratio(trigger) - 0.60) * 0.25 + range_boost + bias_boost + volume_boost + choch_boost)


def make_signal(context: Context, strategy: str, direction: str, entry: float, stop: float, target: float, confidence: float) -> Signal:
    return Signal(
        strategy=strategy,
        direction=direction,
        signal_time=context.timestamp,
        entry=round(entry, 5),
        stop=round(stop, 5),
        target=round(target, 5),
        confidence=round(confidence, 4),
        reason=strategy.upper(),
        market_bias=context.market_bias,
        hour_utc=context.timestamp.hour,
        hour_ny=context.timestamp.astimezone(NY_TZ).hour,
    )


STRATEGIES = {
    "microimpulse_institutional": microimpulse_institutional,
    "liquidity_sweep_reversal": liquidity_sweep_reversal,
    "trend_pullback": trend_pullback,
    "breakout_expansion": breakout_expansion,
}


def simulate_signal(year: int, session: str, signal: Signal, entry_candle: Candle, future: list[Candle]) -> Trade | None:
    direction = signal.direction
    if direction == "BUY":
        entry = entry_candle.open + SPREAD_PRICE / 2 + SLIPPAGE_PER_SIDE
        risk = entry - signal.stop
    else:
        entry = entry_candle.open - SPREAD_PRICE / 2 - SLIPPAGE_PER_SIDE
        risk = signal.stop - entry
    if risk <= 0:
        return None
    for candle in future:
        if direction == "BUY":
            stop_hit = candle.low <= signal.stop
            target_hit = candle.high >= signal.target
            if not stop_hit and not target_hit:
                continue
            exit_price = signal.stop if stop_hit else signal.target
            exit_price -= SPREAD_PRICE / 2 + SLIPPAGE_PER_SIDE
            gross = exit_price - entry
        else:
            stop_hit = candle.high >= signal.stop
            target_hit = candle.low <= signal.target
            if not stop_hit and not target_hit:
                continue
            exit_price = signal.stop if stop_hit else signal.target
            exit_price += SPREAD_PRICE / 2 + SLIPPAGE_PER_SIDE
            gross = entry - exit_price
        units = VOLUME_LOTS * CONTRACT_SIZE
        commission = ((entry * units) + (exit_price * units)) * COMMISSION_RATE
        net = gross * units - commission
        return Trade(
            year=year,
            session=session,
            strategy=signal.strategy,
            direction=direction,
            signal_time=signal.signal_time,
            entry_time=entry_candle.time,
            exit_time=candle.time,
            entry=round(entry, 5),
            stop=round(signal.stop, 5),
            target=round(signal.target, 5),
            exit=round(exit_price, 5),
            net=round(net, 5),
            pnl_r=round(gross / max(risk, 1e-9), 4),
            exit_reason="stop_loss_first" if stop_hit else "take_profit",
            confidence=signal.confidence,
            market_bias=signal.market_bias,
            hour_utc=signal.hour_utc,
            hour_ny=signal.hour_ny,
        )
    return None


def simulate_year(year: int, session_name: str, allowed_hours_utc: set[int] | None) -> dict:
    loader = BlueprintBacktester(INPUT_DIR, OUT_DIR / "_loader_results", OUT_DIR / "_loader_reports")
    m1 = load_year(loader, year)
    if not m1:
        return {"trades": [], "metrics": {}}
    m5 = BlueprintBacktester._resample(m1, "M5")
    m15 = BlueprintBacktester._resample(m1, "M15")
    h1 = BlueprintBacktester._resample(m1, "H1")
    maps = {
        "m5": completed_indices(m1, m5, 5),
        "m15": completed_indices(m1, m15, 15),
        "h1": completed_indices(m1, h1, 60),
    }
    atr_m5 = BlueprintBacktester._atr(m5, 14)
    indicators = {
        "ema_9_m1": BlueprintBacktester._ema([c.close for c in m1], 9),
        "ema_21_m1": BlueprintBacktester._ema([c.close for c in m1], 21),
        "ema_9_m5": BlueprintBacktester._ema([c.close for c in m5], 9),
        "ema_21_m5": BlueprintBacktester._ema([c.close for c in m5], 21),
        "atr_m5": atr_m5,
        "atr_avg_m5": rolling_mean(atr_m5, 20),
        "rsi_m5": rsi(m5, 14),
    }
    trades: list[Trade] = []
    rejection_counts: Counter[str] = Counter()
    i = 90
    while i < len(m1) - 2:
        current = m1[i]
        if allowed_hours_utc is not None and current.time.hour not in allowed_hours_utc:
            i += 1
            continue
        context = make_context(i, m1, m5, m15, h1, maps, indicators)
        if context is None:
            i += 1
            continue
        for name, fn in STRATEGIES.items():
            signal = fn(context)
            if not signal:
                continue
            trade = simulate_signal(year, session_name, signal, m1[i + 1], m1[i + 1 : min(len(m1), i + 1 + 240)])
            if trade:
                trades.append(trade)
                rejection_counts[f"{name}_accepted"] += 1
            else:
                rejection_counts[f"{name}_invalid_or_unresolved"] += 1
        i += 1
    return {"trades": [trade_to_dict(t) for t in trades], "metrics": metrics(trades), "signals": dict(rejection_counts)}


def metrics(trades: list[Trade]) -> dict:
    balance = INITIAL_BALANCE
    peak = balance
    dd = 0.0
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    by_strategy: dict[str, list[Trade]] = defaultdict(list)
    by_side: dict[str, list[Trade]] = defaultdict(list)
    by_hour_ny: dict[str, list[Trade]] = defaultdict(list)
    for trade in sorted(trades, key=lambda t: t.exit_time):
        balance += trade.net
        peak = max(peak, balance)
        dd = max(dd, peak - balance)
        if trade.net > 0:
            wins += 1
            gross_profit += trade.net
        elif trade.net < 0:
            gross_loss += abs(trade.net)
        by_strategy[trade.strategy].append(trade)
        by_side[trade.direction].append(trade)
        by_hour_ny[str(trade.hour_ny)].append(trade)
    return {
        "trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 2) if trades else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else None),
        "net_profit": round(balance - INITIAL_BALANCE, 4),
        "return_pct": round((balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 4),
        "max_drawdown_pct": round(dd / INITIAL_BALANCE * 100, 4),
        "expectancy_cash": round((balance - INITIAL_BALANCE) / len(trades), 4) if trades else None,
        "expectancy_r": round(mean([t.pnl_r for t in trades]), 4) if trades else None,
        "by_strategy": compact_group_metrics(by_strategy),
        "by_side": compact_group_metrics(by_side),
        "by_hour_ny": compact_group_metrics(by_hour_ny),
    }


def compact_group_metrics(groups: dict[str, list[Trade]]) -> dict:
    return {
        key: {
            "trades": len(value),
            "net": round(sum(t.net for t in value), 4),
            "pf": group_pf(value),
            "wr": round(sum(1 for t in value if t.net > 0) / len(value) * 100, 2) if value else None,
            "expectancy_r": round(mean([t.pnl_r for t in value]), 4) if value else None,
        }
        for key, value in sorted(groups.items())
    }


def group_pf(trades: list[Trade]) -> float | None:
    gp = sum(t.net for t in trades if t.net > 0)
    gl = abs(sum(t.net for t in trades if t.net < 0))
    if not trades:
        return None
    return round(gp / gl, 4) if gl else (999.0 if gp else None)


def trade_to_dict(trade: Trade) -> dict:
    item = asdict(trade)
    for key in ("signal_time", "entry_time", "exit_time"):
        item[key] = item[key].isoformat()
    return item


def inflate_trade(item: dict) -> Trade:
    return Trade(
        year=item["year"],
        session=item["session"],
        strategy=item["strategy"],
        direction=item["direction"],
        signal_time=datetime.fromisoformat(item["signal_time"]),
        entry_time=datetime.fromisoformat(item["entry_time"]),
        exit_time=datetime.fromisoformat(item["exit_time"]),
        entry=item["entry"],
        stop=item["stop"],
        target=item["target"],
        exit=item["exit"],
        net=item["net"],
        pnl_r=item["pnl_r"],
        exit_reason=item["exit_reason"],
        confidence=item["confidence"],
        market_bias=item["market_bias"],
        hour_utc=item["hour_utc"],
        hour_ny=item["hour_ny"],
    )


def verdict(aggregate: dict, yearly: dict[str, dict]) -> str:
    yearly_pf = [item["metrics"].get("profit_factor") or 0.0 for item in yearly.values()]
    yearly_trades = [item["metrics"].get("trades") or 0 for item in yearly.values()]
    positive_years = sum(1 for item in yearly.values() if (item["metrics"].get("net_profit") or 0.0) > 0)
    if min(yearly_trades) < 20:
        return "NECESITA MAS DATOS"
    if aggregate.get("profit_factor", 0) >= 1.2 and positive_years >= 3 and min(yearly_pf) >= 1.05:
        return "CANDIDATO PARA DEMO SECO"
    if aggregate.get("profit_factor", 0) >= 1.0 and positive_years >= 2:
        return "REQUIERE FILTRO / SELECTOR DE REGIMEN"
    return "RECHAZADA COMO SISTEMA AUTONOMO"


def write_report(payload: dict) -> None:
    lines = [
        "# BOTJAVIVI Strategy Suite Local Multi-Year Audit",
        "",
        "Research-only replay using BOTEXTRATOR local XAUUSDm M1 data, closed M5/M15/H1 context, estimated spread/slippage/commission, and pessimistic same-bar TP/SL handling.",
        "",
        "## Assumptions",
        "",
        f"- Initial balance: ${INITIAL_BALANCE}",
        f"- Volume: {VOLUME_LOTS} lot",
        f"- Spread estimate: {SPREAD_PRICE} price units",
        f"- Slippage estimate: {SLIPPAGE_PER_SIDE} per side",
        f"- Commission rate: {COMMISSION_RATE}",
        "- Timeframes: M1 execution, M5/M15/H1 closed context only.",
        "",
    ]
    for session, session_payload in payload["sessions"].items():
        lines.extend(
            [
                f"## Session: {session}",
                "",
                "| Year | Trades | WR% | PF | Net | DD% | Expectancy R | Verdict |",
                "|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for year, item in session_payload["yearly"].items():
            m = item["metrics"]
            lines.append(
                f"| {year} | {m.get('trades')} | {m.get('win_rate')} | {m.get('profit_factor')} | {m.get('net_profit')} | {m.get('max_drawdown_pct')} | {m.get('expectancy_r')} |  |"
            )
        agg = session_payload["aggregate"]
        lines.append(
            f"| Aggregate | {agg.get('trades')} | {agg.get('win_rate')} | {agg.get('profit_factor')} | {agg.get('net_profit')} | {agg.get('max_drawdown_pct')} | {agg.get('expectancy_r')} | {session_payload['verdict']} |"
        )
        lines.extend(["", "### By Strategy", "", "| Strategy | Trades | WR% | PF | Net | Expectancy R |", "|---|---:|---:|---:|---:|---:|"])
        for strategy, item in agg.get("by_strategy", {}).items():
            lines.append(f"| {strategy} | {item['trades']} | {item['wr']} | {item['pf']} | {item['net']} | {item['expectancy_r']} |")
        lines.extend(["", "### By Side", "", "| Side | Trades | WR% | PF | Net | Expectancy R |", "|---|---:|---:|---:|---:|---:|"])
        for side, item in agg.get("by_side", {}).items():
            lines.append(f"| {side} | {item['trades']} | {item['wr']} | {item['pf']} | {item['net']} | {item['expectancy_r']} |")
        lines.append("")
    lines.extend(
        [
            "## Final Read",
            "",
            "This audit does not approve live trading. Strategies that fail as standalone modules can still become useful inside an adaptive selector if a stable regime subset is proven later.",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sessions = {
        "all_hours_research": None,
        "botjavivi_utc_19_20": {19, 20},
    }
    payload = {
        "source": "BOTJAVIVI selected strategies, local closed-timeframe replay",
        "assumptions": {
            "symbol": SYMBOL,
            "initial_balance": INITIAL_BALANCE,
            "volume_lots": VOLUME_LOTS,
            "spread_price": SPREAD_PRICE,
            "slippage_per_side": SLIPPAGE_PER_SIDE,
            "commission_rate": COMMISSION_RATE,
            "same_bar_tp_sl": "pessimistic_stop_first",
        },
        "sessions": {},
    }
    for session_name, hours in sessions.items():
        yearly = {str(year): simulate_year(year, session_name, hours) for year in YEARS}
        all_trades = [inflate_trade(trade) for item in yearly.values() for trade in item["trades"]]
        aggregate = metrics(all_trades)
        payload["sessions"][session_name] = {
            "yearly": {year: {"metrics": item["metrics"], "signals": item["signals"]} for year, item in yearly.items()},
            "aggregate": aggregate,
            "verdict": verdict(aggregate, yearly),
        }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report(payload)
    print(json.dumps({"report": str(OUT_MD), "json": str(OUT_JSON), "sessions": {k: v["aggregate"] for k, v in payload["sessions"].items()}}, indent=2))


if __name__ == "__main__":
    main()
