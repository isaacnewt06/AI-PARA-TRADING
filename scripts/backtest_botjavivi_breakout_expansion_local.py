"""Local multi-year replay of BOTJAVIVI BreakoutExpansionStrategy logic.

This is a safe research approximation. It does not import or execute BOTJAVIVI
live code and does not connect to MT5.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.blueprint_backtester import BlueprintBacktester, Candle


INPUT_DIR = ROOT / "data" / "backtests" / "input"
OUT_DIR = ROOT / "data" / "strategies"
OUT_JSON = OUT_DIR / "botjavivi_breakout_expansion_local_multiyear.json"
OUT_MD = OUT_DIR / "botjavivi_breakout_expansion_local_multiyear.md"
SYMBOL = "XAUUSDm"
UTC_HOURS = {19, 20}
INITIAL_BALANCE = 500.0
VOLUME_LOTS = 0.01
CONTRACT_SIZE = 100.0
COMMISSION_RATE = 0.0001
SPREAD_PRICE = 0.30
SLIPPAGE_PER_SIDE = 0.05
NY_TZ = ZoneInfo("America/New_York")


@dataclass(slots=True)
class Trade:
    year: int
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
    hour_utc: int
    hour_ny: int


def load_year(loader: BlueprintBacktester, year: int) -> list[Candle]:
    path = INPUT_DIR / f"{SYMBOL}_M1_{year}.csv"
    if not path.exists():
        return []
    return loader._load_candles(path)


def ema(values: list[float], period: int) -> list[float | None]:
    return BlueprintBacktester._ema(values, period)


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    return BlueprintBacktester._atr(candles, period)


def body_ratio(c: Candle) -> float:
    return abs(c.close - c.open) / max(c.high - c.low, 1e-9)


def simulate_year(year: int) -> dict:
    loader = BlueprintBacktester(INPUT_DIR, OUT_DIR / "loader_results", OUT_DIR / "loader_reports")
    m1 = load_year(loader, year)
    if year == 2026:
        m1 = [c for c in m1 if c.time <= datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc)]
    if not m1:
        return {"year": year, "trades": [], "metrics": metrics([])}
    m5 = BlueprintBacktester._resample(m1, "M5")
    m5_ema9 = ema([c.close for c in m5], 9)
    m5_ema21 = ema([c.close for c in m5], 21)
    m1_atr = atr(m1, 14)
    m5_map = completed_indices(m1, m5, 5)
    trades: list[Trade] = []
    open_trade = None
    i = 30
    while i < len(m1) - 1:
        c = m1[i]
        if open_trade:
            closed = maybe_close(open_trade, c, year)
            if closed:
                trades.append(closed)
                open_trade = None
            i += 1
            continue
        if c.time.hour not in UTC_HOURS:
            i += 1
            continue
        m5_idx = m5_map[i]
        if m5_idx is None or m5_ema9[m5_idx] is None or m5_ema21[m5_idx] is None:
            i += 1
            continue
        bias = "bullish" if m5_ema9[m5_idx] > m5_ema21[m5_idx] else "bearish"
        prior = m1[i - 7 : i - 1]
        recent = m1[i - 6 : i]
        if len(prior) < 6 or len(recent) < 6 or m1_atr[i] is None:
            i += 1
            continue
        current_range = c.high - c.low
        avg_prior = sum(x.high - x.low for x in prior) / len(prior)
        if avg_prior <= 0 or current_range < avg_prior * 1.7 or body_ratio(c) < 0.6:
            i += 1
            continue
        recent_high = max(x.high for x in recent)
        recent_low = min(x.low for x in recent)
        signal = None
        if c.close > recent_high and bias != "bearish":
            stop = min(c.low, recent_high) - 0.012
            risk = c.close - stop
            if risk > 0:
                target = c.close + max(risk * 2.7, m1_atr[i] * 1.4)
                signal = ("buy", stop, target)
        elif c.close < recent_low and bias != "bullish":
            stop = max(c.high, recent_low) + 0.012
            risk = stop - c.close
            if risk > 0:
                target = c.close - max(risk * 2.7, m1_atr[i] * 1.4)
                signal = ("sell", stop, target)
        if signal:
            next_c = m1[i + 1]
            direction, stop, target = signal
            open_trade = {
                "direction": direction,
                "signal_time": c.time,
                "entry_time": next_c.time,
                "entry": next_c.open,
                "stop": stop,
                "target": target,
                "risk": abs(next_c.open - stop),
            }
        i += 1
    return {"year": year, "trades": [trade_to_dict(t) for t in trades], "metrics": metrics(trades)}


def maybe_close(open_trade: dict, c: Candle, year: int) -> Trade | None:
    direction = open_trade["direction"]
    if direction == "buy":
        stop_hit = c.low <= open_trade["stop"]
        target_hit = c.high >= open_trade["target"]
        if not stop_hit and not target_hit:
            return None
        exit_price = open_trade["stop"] if stop_hit else open_trade["target"]
        gross = exit_price - open_trade["entry"]
        pnl_r = gross / max(open_trade["risk"], 1e-9)
    else:
        stop_hit = c.high >= open_trade["stop"]
        target_hit = c.low <= open_trade["target"]
        if not stop_hit and not target_hit:
            return None
        exit_price = open_trade["stop"] if stop_hit else open_trade["target"]
        gross = open_trade["entry"] - exit_price
        pnl_r = gross / max(open_trade["risk"], 1e-9)
    units = VOLUME_LOTS * CONTRACT_SIZE
    commission = ((open_trade["entry"] * units) + (exit_price * units)) * COMMISSION_RATE
    execution_cost = (SPREAD_PRICE + 2 * SLIPPAGE_PER_SIDE) * units
    net = gross * units - commission - execution_cost
    return Trade(
        year=year,
        direction=direction,
        signal_time=open_trade["signal_time"],
        entry_time=open_trade["entry_time"],
        exit_time=c.time,
        entry=round(open_trade["entry"], 5),
        stop=round(open_trade["stop"], 5),
        target=round(open_trade["target"], 5),
        exit=round(exit_price, 5),
        net=round(net, 5),
        pnl_r=round(pnl_r, 4),
        exit_reason="stop_loss_first" if stop_hit else "take_profit",
        hour_utc=open_trade["entry_time"].hour,
        hour_ny=open_trade["entry_time"].astimezone(NY_TZ).hour,
    )


def metrics(trades: list[Trade]) -> dict:
    balance = INITIAL_BALANCE
    peak = balance
    dd = 0.0
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    for t in trades:
        balance += t.net
        peak = max(peak, balance)
        dd = max(dd, peak - balance)
        if t.net > 0:
            wins += 1
            gross_profit += t.net
        elif t.net < 0:
            gross_loss += abs(t.net)
    return {
        "trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 2) if trades else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else None),
        "net_profit": round(balance - INITIAL_BALANCE, 4),
        "return_pct": round((balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 4),
        "max_drawdown_pct": round(dd / INITIAL_BALANCE * 100, 4),
        "expectancy": round((balance - INITIAL_BALANCE) / len(trades), 4) if trades else None,
    }


def completed_indices(entry: list[Candle], context: list[Candle], minutes: int) -> list[int | None]:
    out: list[int | None] = [None] * len(entry)
    pointer = -1
    for i, c in enumerate(entry):
        cutoff = c.time.timestamp() - minutes * 60
        while pointer + 1 < len(context) and context[pointer + 1].time.timestamp() <= cutoff:
            pointer += 1
        out[i] = pointer if pointer >= 0 else None
    return out


def trade_to_dict(trade: Trade) -> dict:
    item = asdict(trade)
    for key in ("signal_time", "entry_time", "exit_time"):
        item[key] = item[key].isoformat()
    return item


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    yearly = {str(year): simulate_year(year) for year in [2023, 2024, 2025, 2026]}
    all_trades = []
    for item in yearly.values():
        all_trades.extend(
            Trade(
                year=t["year"],
                direction=t["direction"],
                signal_time=datetime.fromisoformat(t["signal_time"]),
                entry_time=datetime.fromisoformat(t["entry_time"]),
                exit_time=datetime.fromisoformat(t["exit_time"]),
                entry=t["entry"],
                stop=t["stop"],
                target=t["target"],
                exit=t["exit"],
                net=t["net"],
                pnl_r=t["pnl_r"],
                exit_reason=t["exit_reason"],
                hour_utc=t["hour_utc"],
                hour_ny=t["hour_ny"],
            )
            for t in item["trades"]
        )
    payload = {
        "source": "BOTJAVIVI breakout_expansion local approximation",
        "assumptions": {
            "hours_utc": sorted(UTC_HOURS),
            "spread_price": SPREAD_PRICE,
            "slippage_per_side": SLIPPAGE_PER_SIDE,
            "commission_rate": COMMISSION_RATE,
            "bias": "closed M5 EMA9/EMA21",
        },
        "yearly": {year: item["metrics"] for year, item in yearly.items()},
        "aggregate": metrics(all_trades),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# BOTJAVIVI Breakout Expansion Local Multi-Year Audit",
        "",
        "Safe local approximation. No MT5 connection and no orders.",
        "",
        "| Year | Trades | WR% | PF | Net | DD% | Expectancy |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for year, item in payload["yearly"].items():
        lines.append(
            f"| {year} | {item['trades']} | {item['win_rate']} | {item['profit_factor']} | {item['net_profit']} | {item['max_drawdown_pct']} | {item['expectancy']} |"
        )
    agg = payload["aggregate"]
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            f"- Trades: {agg['trades']}",
            f"- Win rate: {agg['win_rate']}%",
            f"- Profit factor: {agg['profit_factor']}",
            f"- Net profit: {agg['net_profit']}",
            f"- Max DD: {agg['max_drawdown_pct']}%",
            "",
            "## Verdict",
            "",
            "Research-only. This approximation must be compared with BOTJAVIVI event-driven results before assigning live weight.",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(OUT_MD), "aggregate": agg}, indent=2))


if __name__ == "__main__":
    main()
