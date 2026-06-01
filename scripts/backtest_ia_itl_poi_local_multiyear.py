"""Local multi-year replay of IA BOTTRADING ITL CHOCH/BOS/POI logic.

Research-only. This port intentionally avoids MT5 and uses only local CSVs.
It also confirms pivots only after right-side bars have closed, reducing
lookahead risk in the original exploratory scripts.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.blueprint_backtester import BlueprintBacktester, Candle


INPUT_DIR = ROOT / "data" / "backtests" / "input"
OUT_DIR = ROOT / "data" / "strategies"
OUT_JSON = OUT_DIR / "ia_itl_poi_local_multiyear.json"
OUT_MD = OUT_DIR / "ia_itl_poi_local_multiyear.md"
SYMBOL = "XAUUSDm"
YEARS = [2023, 2024, 2025, 2026]
SPREAD_PRICE = 0.30
SLIPPAGE_PER_SIDE = 0.05
COMMISSION_R_APPROX = 0.03


@dataclass(slots=True)
class Variant:
    name: str
    tp_r: float
    entry_mode: str = "mid"
    sl_buffer_atr_mult: float = 0.1
    lb: int = 3
    rb: int = 3
    ob_lookback: int = 8
    use_sessions: bool = True
    sessions: tuple[tuple[str, str], ...] = (("03:00", "07:00"), ("08:00", "12:00"), ("13:30", "16:30"))
    tp1_r: float = 0.0
    tp1_frac: float = 0.0
    breakeven_after_tp1: bool = False
    cooldown_bars: int = 0
    use_h1_bias: bool = False


@dataclass(slots=True)
class POI:
    idx_bos: int
    candle_idx: int
    low: float
    high: float
    direction: str
    created_time: datetime


@dataclass(slots=True)
class PendingOrder:
    poi: POI
    entry: float
    stop: float
    target: float
    risk: float
    tp1: float | None
    created_idx: int


@dataclass(slots=True)
class Trade:
    year: int
    variant: str
    direction: str
    entry_time: datetime
    exit_time: datetime
    entry: float
    stop: float
    target: float
    gross_r: float
    net_r: float
    exit_status: str
    partial_taken: bool
    poi_time: datetime
    hour_utc: int


def load_year(loader: BlueprintBacktester, year: int, timeframe: str) -> list[Candle]:
    path = INPUT_DIR / f"{SYMBOL}_{timeframe}_{year}.csv"
    if path.exists():
        candles = loader._load_candles(path)
    else:
        m1 = loader._load_candles(INPUT_DIR / f"{SYMBOL}_M1_{year}.csv")
        candles = BlueprintBacktester._resample(m1, timeframe)
    if year == 2026:
        return [c for c in candles if c.time <= datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc)]
    return candles


def to_frame(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [c.time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    )


def atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def in_sessions(ts: datetime, sessions: tuple[tuple[str, str], ...]) -> bool:
    hhmm = ts.strftime("%H:%M")
    return any(start <= hhmm <= end for start, end in sessions)


def generate_pois(df: pd.DataFrame, *, lb: int, rb: int, ob_lookback: int) -> tuple[list[POI], pd.Series]:
    highs = df["high"].to_list()
    lows = df["low"].to_list()
    closes = df["close"].to_list()
    opens = df["open"].to_list()
    times = df["time"].to_list()
    last_high: tuple[int, float] | None = None
    last_low: tuple[int, float] | None = None
    trend: str | None = None
    pending_confirm: str | None = None
    pois: list[POI] = []
    bias = pd.Series(index=df.index, dtype=object)

    for i in range(lb + rb, len(df)):
        pivot_idx = i - rb
        high_window = highs[pivot_idx - lb : pivot_idx + rb + 1]
        low_window = lows[pivot_idx - lb : pivot_idx + rb + 1]
        if highs[pivot_idx] == max(high_window):
            last_high = (pivot_idx, highs[pivot_idx])
        if lows[pivot_idx] == min(low_window):
            last_low = (pivot_idx, lows[pivot_idx])

        if last_high is None or last_low is None:
            bias.iloc[i] = trend
            continue

        direction = None
        if closes[i] > last_high[1] and i > last_high[0]:
            direction = "up"
        elif closes[i] < last_low[1] and i > last_low[0]:
            direction = "down"

        if direction is None:
            bias.iloc[i] = trend
            continue

        create_poi = False
        if trend is None:
            trend = direction
            pending_confirm = None
            create_poi = True
        elif direction == trend:
            create_poi = True
        elif pending_confirm is None:
            pending_confirm = direction
        elif pending_confirm == direction:
            trend = direction
            pending_confirm = None
            create_poi = True
        else:
            pending_confirm = direction

        if create_poi:
            ob_idx = find_last_opposite(df, i, direction, ob_lookback)
            if ob_idx is not None:
                low, high = candle_zone(opens[ob_idx], highs[ob_idx], lows[ob_idx], closes[ob_idx], direction)
                pois.append(
                    POI(
                        idx_bos=i,
                        candle_idx=ob_idx,
                        low=low,
                        high=high,
                        direction="long" if direction == "up" else "short",
                        created_time=times[i],
                    )
                )
        bias.iloc[i] = trend
    return pois, bias.ffill()


def find_last_opposite(df: pd.DataFrame, idx_bos: int, direction: str, ob_lookback: int) -> int | None:
    for j in range(idx_bos - 1, max(idx_bos - ob_lookback, 0) - 1, -1):
        bullish = df["close"].iat[j] > df["open"].iat[j]
        bearish = df["close"].iat[j] < df["open"].iat[j]
        if direction == "up" and bearish:
            return j
        if direction == "down" and bullish:
            return j
    return None


def candle_zone(open_: float, high: float, low: float, close: float, direction: str) -> tuple[float, float]:
    if direction == "up":
        body_low = min(open_, close)
        return min(body_low, low), max(body_low, low)
    body_high = max(open_, close)
    return min(body_high, high), max(body_high, high)


def build_pending_order(df: pd.DataFrame, poi: POI, idx: int, variant: Variant) -> PendingOrder:
    atr = float(df["atr"].iat[idx])
    zone_range = poi.high - poi.low
    if poi.direction == "long":
        entry = poi.low + zone_range * (0.5 if variant.entry_mode == "mid" else 1.0)
        stop = poi.low - atr * variant.sl_buffer_atr_mult
        risk = entry - stop
        target = entry + variant.tp_r * risk
        tp1 = entry + variant.tp1_r * risk if variant.tp1_frac and variant.tp1_r else None
    else:
        entry = poi.high - zone_range * (0.5 if variant.entry_mode == "mid" else 1.0)
        stop = poi.high + atr * variant.sl_buffer_atr_mult
        risk = stop - entry
        target = entry - variant.tp_r * risk
        tp1 = entry - variant.tp1_r * risk if variant.tp1_frac and variant.tp1_r else None
    return PendingOrder(poi=poi, entry=entry, stop=stop, target=target, risk=risk, tp1=tp1, created_idx=idx)


def simulate_variant(year: int, df: pd.DataFrame, h1_bias: pd.Series | None, variant: Variant) -> list[Trade]:
    pois, _bias = generate_pois(df, lb=variant.lb, rb=variant.rb, ob_lookback=variant.ob_lookback)
    poi_by_idx = {poi.idx_bos: poi for poi in pois}
    trades: list[Trade] = []
    pending: PendingOrder | None = None
    active: PendingOrder | None = None
    active_entry_idx = 0
    partial_taken = False
    remaining = 1.0
    stop = 0.0
    cooldown = 0

    for i in range(len(df)):
        ts = df["time"].iat[i]
        row = df.iloc[i]
        if cooldown > 0:
            cooldown -= 1

        if i in poi_by_idx:
            pending = build_pending_order(df, poi_by_idx[i], i, variant)

        if pending and active is None and i > pending.created_idx and cooldown == 0:
            if pending.risk <= 0:
                pending = None
            elif variant.use_sessions and not in_sessions(ts, variant.sessions):
                pass
            elif variant.use_h1_bias and h1_bias is not None:
                bias_value = h1_bias.asof(ts)
                if (pending.poi.direction == "long" and bias_value != "up") or (pending.poi.direction == "short" and bias_value != "down"):
                    pass
                elif float(row["low"]) <= pending.entry <= float(row["high"]):
                    active = pending
                    active_entry_idx = i
                    partial_taken = False
                    remaining = 1.0
                    stop = pending.stop
                    pending = None
            elif float(row["low"]) <= pending.entry <= float(row["high"]):
                active = pending
                active_entry_idx = i
                partial_taken = False
                remaining = 1.0
                stop = pending.stop
                pending = None

        if active is None:
            continue

        high = float(row["high"])
        low = float(row["low"])
        hit_sl = low <= stop if active.poi.direction == "long" else high >= stop
        hit_tp1 = (
            active.tp1 is not None
            and not partial_taken
            and (high >= active.tp1 if active.poi.direction == "long" else low <= active.tp1)
        )
        hit_tp = high >= active.target if active.poi.direction == "long" else low <= active.target

        # Conservative bar ordering: SL before favorable events if same candle.
        if hit_sl:
            gross_r = -remaining if not partial_taken else variant.tp1_r * variant.tp1_frac - remaining * (0.0 if stop == active.entry else 1.0)
            trades.append(close_trade(year, variant, active, ts, gross_r, "SL_or_BE", partial_taken, active_entry_idx))
            active = None
            cooldown = variant.cooldown_bars
            continue
        if hit_tp1:
            partial_taken = True
            remaining = max(0.0, 1.0 - variant.tp1_frac)
            if variant.breakeven_after_tp1:
                stop = active.entry
        if hit_tp:
            gross_r = variant.tp_r if not partial_taken else variant.tp1_r * variant.tp1_frac + variant.tp_r * remaining
            trades.append(close_trade(year, variant, active, ts, gross_r, "TP", partial_taken, active_entry_idx))
            active = None
            cooldown = variant.cooldown_bars
    return trades


def close_trade(year: int, variant: Variant, order: PendingOrder, exit_time: datetime, gross_r: float, status: str, partial_taken: bool, entry_idx: int) -> Trade:
    cost_r = (SPREAD_PRICE + 2 * SLIPPAGE_PER_SIDE) / max(order.risk, 1e-9) + COMMISSION_R_APPROX
    return Trade(
        year=year,
        variant=variant.name,
        direction=order.poi.direction,
        entry_time=order.poi.created_time,
        exit_time=exit_time,
        entry=round(order.entry, 5),
        stop=round(order.stop, 5),
        target=round(order.target, 5),
        gross_r=round(gross_r, 4),
        net_r=round(gross_r - cost_r, 4),
        exit_status=status,
        partial_taken=partial_taken,
        poi_time=order.poi.created_time,
        hour_utc=order.poi.created_time.hour,
    )


def simulate_year(year: int, variants: list[Variant]) -> dict:
    loader = BlueprintBacktester(INPUT_DIR, OUT_DIR / "_loader_results", OUT_DIR / "_loader_reports")
    m5 = load_year(loader, year, "M5")
    h1 = load_year(loader, year, "H1")
    if not m5:
        return {}
    df = to_frame(m5)
    df["atr"] = atr_series(df, 14)
    h1_df = to_frame(h1)
    h1_bias = None
    if not h1_df.empty:
        _pois, h1_bias_raw = generate_pois(h1_df, lb=3, rb=3, ob_lookback=8)
        h1_bias = pd.Series(h1_bias_raw.to_list(), index=pd.DatetimeIndex(h1_df["time"]))
    out = {}
    for variant in variants:
        trades = simulate_variant(year, df, h1_bias, variant)
        out[variant.name] = {"metrics": metrics(trades), "trades": [trade_to_dict(t) for t in trades[:5000]]}
    return out


def metrics(trades: list[Trade]) -> dict:
    values = [t.net_r for t in trades]
    gross_values = [t.gross_r for t in trades]
    gp = sum(v for v in values if v > 0)
    gl = -sum(v for v in values if v < 0)
    eq = 0.0
    peak = 0.0
    dd = 0.0
    by_side: dict[str, list[Trade]] = defaultdict(list)
    by_hour: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        eq += trade.net_r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
        by_side[trade.direction].append(trade)
        by_hour[str(trade.hour_utc)].append(trade)
    return {
        "trades": len(trades),
        "win_rate": round(sum(1 for v in values if v > 0) / len(values) * 100, 2) if values else None,
        "profit_factor": round(gp / gl, 4) if gl else (999.0 if gp else None),
        "total_net_r": round(sum(values), 4),
        "total_gross_r": round(sum(gross_values), 4),
        "expectancy_r": round(mean(values), 4) if values else None,
        "max_drawdown_r": round(dd, 4),
        "partials": sum(1 for t in trades if t.partial_taken),
        "by_side": compact_groups(by_side),
        "by_hour_utc": compact_groups(by_hour),
    }


def compact_groups(groups: dict[str, list[Trade]]) -> dict:
    return {key: {"trades": len(items), "net_r": round(sum(t.net_r for t in items), 4), "pf": group_pf(items)} for key, items in sorted(groups.items())}


def group_pf(trades: list[Trade]) -> float | None:
    gp = sum(t.net_r for t in trades if t.net_r > 0)
    gl = -sum(t.net_r for t in trades if t.net_r < 0)
    return round(gp / gl, 4) if gl else (999.0 if gp else None)


def trade_to_dict(trade: Trade) -> dict:
    item = asdict(trade)
    for key in ("entry_time", "exit_time", "poi_time"):
        item[key] = item[key].isoformat()
    return item


def aggregate_variant(yearly: dict, variant_name: str) -> dict:
    trades = []
    for year_payload in yearly.values():
        for item in year_payload.get(variant_name, {}).get("trades", []):
            trades.append(
                Trade(
                    year=item["year"],
                    variant=item["variant"],
                    direction=item["direction"],
                    entry_time=datetime.fromisoformat(item["entry_time"]),
                    exit_time=datetime.fromisoformat(item["exit_time"]),
                    entry=item["entry"],
                    stop=item["stop"],
                    target=item["target"],
                    gross_r=item["gross_r"],
                    net_r=item["net_r"],
                    exit_status=item["exit_status"],
                    partial_taken=item["partial_taken"],
                    poi_time=datetime.fromisoformat(item["poi_time"]),
                    hour_utc=item["hour_utc"],
                )
            )
    return metrics(trades)


def build_variants() -> list[Variant]:
    return [
        Variant(name="itl_r2_sessions", tp_r=2.0),
        Variant(name="itl_r3_sessions", tp_r=3.0),
        Variant(name="itl_r15_sessions", tp_r=1.5),
        Variant(name="itl_r3_partial_be_sessions", tp_r=3.0, tp1_r=1.0, tp1_frac=0.5, breakeven_after_tp1=True),
        Variant(name="itl_r2_all_hours", tp_r=2.0, use_sessions=False),
        Variant(name="itl_r3_all_hours", tp_r=3.0, use_sessions=False),
        Variant(name="itl_r2_h1_bias", tp_r=2.0, use_h1_bias=True),
        Variant(name="itl_r3_partial_be_h1_bias", tp_r=3.0, tp1_r=1.0, tp1_frac=0.5, breakeven_after_tp1=True, use_h1_bias=True),
        Variant(name="itl_r2_cooldown5", tp_r=2.0, cooldown_bars=5),
    ]


def write_report(payload: dict) -> None:
    lines = [
        "# IA BOTTRADING ITL POI Local Multi-Year Audit",
        "",
        "Research-only validation of CHOCH/BOS -> POI/OB retest logic on local XAUUSDm M5 data.",
        "",
        "This run uses confirmed pivots, estimated spread/slippage/commission in R, and conservative same-bar handling.",
        "",
        "| Variant | 2023 PF/R | 2024 PF/R | 2025 PF/R | 2026 PF/R | Aggregate Trades | Aggregate PF | Aggregate Net R | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for variant, agg in payload["aggregate"].items():
        cells = []
        for year in YEARS:
            m = payload["yearly"][str(year)][variant]["metrics"]
            cells.append(f"{m['profit_factor']} / {m['total_net_r']}")
        lines.append(
            f"| {variant} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {agg['trades']} | {agg['profit_factor']} | {agg['total_net_r']} | {payload['verdicts'][variant]} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "A variant only becomes useful for the adaptive brain if it survives more than one year after costs. A 2025-only edge is marked as contextual, not robust.",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def classify_variant(aggregate: dict, yearly_metrics: list[dict]) -> str:
    positive_years = sum(1 for m in yearly_metrics if (m.get("total_net_r") or 0) > 0)
    min_trades = min((m.get("trades") or 0) for m in yearly_metrics)
    if min_trades < 15:
        return "NECESITA MAS DATOS"
    if aggregate.get("profit_factor", 0) >= 1.2 and positive_years >= 3:
        return "CANDIDATO PARA SELECTOR ADAPTATIVO"
    if aggregate.get("profit_factor", 0) >= 1.0 and positive_years >= 2:
        return "EDGE CONTEXTUAL / REQUIERE REGIME FILTER"
    return "RECHAZADA MULTI-ANO"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    variants = build_variants()
    yearly = {str(year): simulate_year(year, variants) for year in YEARS}
    aggregate = {variant.name: aggregate_variant(yearly, variant.name) for variant in variants}
    verdicts = {}
    for variant in variants:
        verdicts[variant.name] = classify_variant(
            aggregate[variant.name],
            [yearly[str(year)][variant.name]["metrics"] for year in YEARS],
        )
    payload = {
        "source": "IA BOTTRADING Backtest_ITL_CHOCH_BOS_POI_FVG local port",
        "assumptions": {
            "symbol": SYMBOL,
            "timeframe": "M5",
            "pivot_confirmation": "right-bars closed before swing becomes usable",
            "spread_price": SPREAD_PRICE,
            "slippage_per_side": SLIPPAGE_PER_SIDE,
            "commission_r_approx": COMMISSION_R_APPROX,
        },
        "yearly": yearly,
        "aggregate": aggregate,
        "verdicts": verdicts,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report(payload)
    print(json.dumps({"report": str(OUT_MD), "json": str(OUT_JSON), "aggregate": aggregate, "verdicts": verdicts}, indent=2))


if __name__ == "__main__":
    main()
