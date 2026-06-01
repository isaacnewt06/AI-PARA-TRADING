"""Validate whether strong continuation is actually late/exhausted.

Research only. This script does not modify live logic, the frozen M5 detector,
management, or execution survival protocol.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE_RECORDS = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "wider_management_research"
    / "wider_management_research_records.csv"
)
SOURCE_TRADES = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "V1_displacement_validation"
    / "displacement_plus_wick_trades.csv"
)
INPUT_DIR = ROOT / "data" / "backtests" / "input"
OUTPUT_DIR = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "continuation_exhaustion_validation"
)

PROFILE = "fast_03_be_08"
SCENARIO = "realistic_mt5"
SESSION = "ny_am"
LOOKBACK_M5_BARS = 20
POST_ENTRY_MINUTES = 60


def _read_price_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    a = df["high"] - df["low"]
    b = (df["high"] - prev_close).abs()
    c = (df["low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def _directional_move(side: str, start: float, end: float) -> float:
    if side == "BUY":
        return end - start
    return start - end


def _mfe_mae_from_window(side: str, entry: float, highs: pd.Series, lows: pd.Series, risk: float) -> tuple[float, float]:
    if risk <= 0 or highs.empty or lows.empty:
        return 0.0, 0.0
    if side == "BUY":
        mfe = max(0.0, (float(highs.max()) - entry) / risk)
        mae = max(0.0, (entry - float(lows.min())) / risk)
    else:
        mfe = max(0.0, (entry - float(lows.min())) / risk)
        mae = max(0.0, (float(highs.max()) - entry) / risk)
    return mfe, mae


def _time_to_peak(side: str, entry: float, post_m1: pd.DataFrame, risk: float) -> float | None:
    if post_m1.empty or risk <= 0:
        return None
    if side == "BUY":
        idx = post_m1["high"].idxmax()
    else:
        idx = post_m1["low"].idxmin()
    peak_time = post_m1.loc[idx, "time"]
    entry_time = post_m1.iloc[0]["time"]
    return max(0.0, (peak_time - entry_time).total_seconds() / 60.0)


def _momentum_score(side: str, candles: pd.DataFrame) -> float:
    if candles.empty:
        return 0.0
    bodies = candles["close"] - candles["open"]
    if side == "SELL":
        bodies = -bodies
    ranges = (candles["high"] - candles["low"]).replace(0, pd.NA)
    directional_body_ratio = (bodies / ranges).fillna(0.0)
    return float(directional_body_ratio.mean())


def _wick_absorption(side: str, candle: pd.Series) -> float:
    candle_range = float(candle["high"] - candle["low"])
    if candle_range <= 0:
        return 0.0
    if side == "BUY":
        wick = min(float(candle["open"]), float(candle["close"])) - float(candle["low"])
    else:
        wick = float(candle["high"]) - max(float(candle["open"]), float(candle["close"]))
    return max(0.0, min(1.0, wick / candle_range))


def _safe_mean(values: list[float]) -> float:
    clean = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    return round(sum(clean) / len(clean), 6) if clean else 0.0


def _metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_R": 0.0,
            "net_R": 0.0,
            "max_drawdown_R": 0.0,
        }
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    profit_factor = 999.0 if gross_loss == 0 and gross_profit > 0 else (gross_profit / gross_loss if gross_loss else 0.0)
    equity = []
    running = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        running += value
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
        equity.append(running)
    return {
        "trades": len(values),
        "win_rate": round(len(wins) / len(values) * 100.0, 4),
        "profit_factor": round(profit_factor, 4),
        "expectancy_R": round(sum(values) / len(values), 6),
        "net_R": round(sum(values), 6),
        "max_drawdown_R": round(drawdown, 6),
    }


def run_research() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = pd.read_csv(SOURCE_RECORDS)
    records["signal_time"] = pd.to_datetime(records["signal_time"], utc=True)
    records["entry_time"] = pd.to_datetime(records["entry_time"], utc=True)

    # The management research records intentionally focus on execution outcome
    # and do not carry entry/stop/target prices. Join the frozen detector trade
    # records so M1/M5 distance analysis is based on actual historical prices.
    source_trades = pd.read_csv(SOURCE_TRADES)
    source_trades["signal_time"] = pd.to_datetime(source_trades["signal_time"], utc=True)
    source_trades["entry_time"] = pd.to_datetime(source_trades["entry_time"], utc=True)
    source_trade_cols = [
        "year",
        "side",
        "signal_time",
        "entry_time",
        "entry",
        "stop",
        "target",
        "rr",
    ]
    records = records.merge(
        source_trades[source_trade_cols],
        on=["year", "side", "signal_time", "entry_time"],
        how="left",
        suffixes=("", "_source"),
    )
    sample = records[
        (records["profile"] == PROFILE)
        & (records["scenario"] == SCENARIO)
        & (records["session"] == SESSION)
    ].copy()
    sample = sample.sort_values("entry_time").reset_index(drop=True)

    m1_by_year: dict[int, pd.DataFrame] = {}
    m5_by_year: dict[int, pd.DataFrame] = {}
    enriched: list[dict[str, Any]] = []

    for row in sample.to_dict("records"):
        year = int(row["year"])
        if year not in m1_by_year:
            m1_by_year[year] = _read_price_file(INPUT_DIR / f"XAUUSDm_M1_{year}.csv")
        if year not in m5_by_year:
            m5 = _read_price_file(INPUT_DIR / f"XAUUSDm_M5_{year}.csv")
            if not m5.empty:
                m5["tr"] = _true_range(m5)
                m5["atr_mean_20"] = m5["tr"].rolling(LOOKBACK_M5_BARS, min_periods=5).mean()
            m5_by_year[year] = m5

        m1 = m1_by_year[year]
        m5 = m5_by_year[year]
        signal_time = row["signal_time"]
        entry_time = row["entry_time"]
        side = row["side"]
        entry = float(row.get("entry", row.get("entry_price", 0.0)) or 0.0)
        if entry <= 0:
            raise ValueError(f"Missing entry price for {side} {entry_time.isoformat()}")
        risk = max(float(row["risk"]), 1e-9)

        signal_candles = m5[m5["time"] <= signal_time].tail(LOOKBACK_M5_BARS + 1)
        signal_candle = signal_candles[signal_candles["time"] == signal_time]
        if signal_candle.empty:
            signal_candle = signal_candles.tail(1)
        signal_candle_row = signal_candle.iloc[-1] if not signal_candle.empty else None
        atr_mean = float(signal_candle_row.get("atr_mean_20", 0.0)) if signal_candle_row is not None else 0.0
        signal_open = float(signal_candle_row["open"]) if signal_candle_row is not None else entry
        signal_close = float(signal_candle_row["close"]) if signal_candle_row is not None else entry
        signal_high = float(signal_candle_row["high"]) if signal_candle_row is not None else entry
        signal_low = float(signal_candle_row["low"]) if signal_candle_row is not None else entry

        # Pre-entry consumption: how much directional move already happened
        # from the M5 displacement origin before the actual entry.
        consumed_from_open = _directional_move(side, signal_open, entry)
        consumed_from_close = _directional_move(side, signal_close, entry)
        displacement_range = max(signal_high - signal_low, 1e-9)
        consumed_pct_signal_range = max(0.0, consumed_from_open / displacement_range)
        distance_from_local_atr_mean = consumed_from_open / atr_mean if atr_mean > 0 else 0.0

        post_end = entry_time + pd.Timedelta(minutes=POST_ENTRY_MINUTES)
        post_m1 = m1[(m1["time"] >= entry_time) & (m1["time"] <= post_end)].copy()
        first_5 = post_m1.head(5)
        first_15 = post_m1.head(15)
        pre_m1 = m1[(m1["time"] >= signal_time - pd.Timedelta(minutes=5)) & (m1["time"] < entry_time)].copy()
        entry_m1 = post_m1.head(1)

        post_mfe_r, post_mae_r = _mfe_mae_from_window(side, entry, post_m1["high"], post_m1["low"], risk)
        first_5_mfe_r, first_5_mae_r = _mfe_mae_from_window(side, entry, first_5["high"], first_5["low"], risk)
        first_15_mfe_r, first_15_mae_r = _mfe_mae_from_window(side, entry, first_15["high"], first_15["low"], risk)

        pre_momentum = _momentum_score(side, pre_m1)
        post_momentum_5 = _momentum_score(side, first_5)
        post_momentum_15 = _momentum_score(side, first_15)
        momentum_decay_5 = pre_momentum - post_momentum_5
        momentum_decay_15 = pre_momentum - post_momentum_15
        wick_absorption = _wick_absorption(side, entry_m1.iloc[0]) if not entry_m1.empty else 0.0

        final_r = float(row["realized_R"])
        reversal_flag = bool(post_mae_r >= 1.0 or final_r < 0.0)
        exhaustion_flag = bool(post_mfe_r < 0.3 or (momentum_decay_5 > 0.25 and first_5_mfe_r < 0.5) or final_r < 0.0)
        post_entry_continuation = bool(first_5_mfe_r >= 0.5 or post_mfe_r >= 0.8)

        enriched.append(
            {
                "year": year,
                "side": side,
                "signal_time": signal_time.isoformat(),
                "entry_time": entry_time.isoformat(),
                "continuation_quality": row["continuation_quality"],
                "expansion_subtype": row["expansion_subtype"],
                "atr_bucket": row["atr_bucket"],
                "realized_R": round(final_r, 6),
                "mfe_R_recorded": round(float(row["mfe_r"]), 6),
                "mae_R_recorded": round(float(row["mae_r"]), 6),
                "post_60m_mfe_R": round(post_mfe_r, 6),
                "post_60m_mae_R": round(post_mae_r, 6),
                "first_5m_mfe_R": round(first_5_mfe_r, 6),
                "first_5m_mae_R": round(first_5_mae_r, 6),
                "first_15m_mfe_R": round(first_15_mfe_r, 6),
                "first_15m_mae_R": round(first_15_mae_r, 6),
                "time_to_peak_minutes": _time_to_peak(side, entry, post_m1, risk),
                "distance_from_displacement_origin_R": round(consumed_from_open / risk, 6),
                "distance_from_displacement_close_R": round(consumed_from_close / risk, 6),
                "distance_from_local_ATR_mean": round(distance_from_local_atr_mean, 6),
                "consumed_pct_signal_range": round(consumed_pct_signal_range, 6),
                "pullback_depth_5m_R": round(first_5_mae_r, 6),
                "momentum_pre_entry": round(pre_momentum, 6),
                "momentum_post_5m": round(post_momentum_5, 6),
                "momentum_post_15m": round(post_momentum_15, 6),
                "momentum_decay_5m": round(momentum_decay_5, 6),
                "momentum_decay_15m": round(momentum_decay_15, 6),
                "wick_absorption": round(wick_absorption, 6),
                "reversal_flag": reversal_flag,
                "exhaustion_flag": exhaustion_flag,
                "post_entry_continuation": post_entry_continuation,
                "spread_cost_R": round(float(row["spread_price"]) / risk, 6),
                "slippage_cost_R": round(float(row["slippage_price"]) / risk, 6),
                "total_cost_R": round(float(row["cost_r"]), 6),
                "entry_delay_m5_bars": round((entry_time - signal_time).total_seconds() / 300.0, 3),
            }
        )

    enriched_df = pd.DataFrame(enriched)
    enriched_df.to_csv(OUTPUT_DIR / "continuation_exhaustion_validation_records.csv", index=False)

    groups: dict[str, Any] = {}
    for quality in ["strong", "medium", "weak"]:
        group = enriched_df[enriched_df["continuation_quality"] == quality]
        realized = group["realized_R"].astype(float).tolist()
        groups[quality] = {
            "metrics": _metrics(realized),
            "mfe_avg": _safe_mean(group["post_60m_mfe_R"].tolist()),
            "mae_avg": _safe_mean(group["post_60m_mae_R"].tolist()),
            "recorded_mfe_avg": _safe_mean(group["mfe_R_recorded"].tolist()),
            "recorded_mae_avg": _safe_mean(group["mae_R_recorded"].tolist()),
            "time_to_peak_avg_minutes": _safe_mean(group["time_to_peak_minutes"].dropna().tolist()),
            "distance_from_displacement_origin_R_avg": _safe_mean(group["distance_from_displacement_origin_R"].tolist()),
            "distance_from_local_ATR_mean_avg": _safe_mean(group["distance_from_local_ATR_mean"].tolist()),
            "consumed_pct_signal_range_avg": _safe_mean(group["consumed_pct_signal_range"].tolist()),
            "pullback_depth_5m_R_avg": _safe_mean(group["pullback_depth_5m_R"].tolist()),
            "momentum_decay_5m_avg": _safe_mean(group["momentum_decay_5m"].tolist()),
            "momentum_decay_15m_avg": _safe_mean(group["momentum_decay_15m"].tolist()),
            "wick_absorption_avg": _safe_mean(group["wick_absorption"].tolist()),
            "reversal_probability": round(float(group["reversal_flag"].mean() * 100.0), 4) if not group.empty else 0.0,
            "exhaustion_probability": round(float(group["exhaustion_flag"].mean() * 100.0), 4) if not group.empty else 0.0,
            "post_entry_continuation_probability": round(float(group["post_entry_continuation"].mean() * 100.0), 4) if not group.empty else 0.0,
            "spread_cost_R_avg": _safe_mean(group["spread_cost_R"].tolist()),
            "slippage_cost_R_avg": _safe_mean(group["slippage_cost_R"].tolist()),
            "years": {
                str(year): _metrics(year_group["realized_R"].astype(float).tolist())
                for year, year_group in group.groupby("year")
            },
        }

    conclusion = classify(groups)
    payload = {
        "research": "CONTINUATION_EXHAUSTION_VALIDATION_RESEARCH",
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "baseline": "MTF_REAL_H4_FIXED_BASELINE",
        "setup": "displacement_plus_wick_v1",
        "session": SESSION,
        "profile": PROFILE,
        "scenario": SCENARIO,
        "definitions": {
            "distance_from_displacement_origin_R": "directional distance from M5 signal candle open to entry, divided by trade risk",
            "distance_from_local_ATR_mean": "same directional distance divided by prior 20 M5 true-range mean",
            "consumed_pct_signal_range": "directional distance from signal open to entry divided by M5 signal candle range",
            "time_to_peak": "minutes from entry until best favorable M1 price within the first 60 minutes",
            "momentum_decay": "pre-entry directional M1 body/range momentum minus post-entry momentum",
            "reversal_probability": "percentage where MAE >= 1R or final realized_R < 0",
            "exhaustion_probability": "percentage with MFE < 0.3R, strong early momentum decay without 0.5R, or final loss",
        },
        "groups": groups,
        "classification": conclusion["classification"],
        "diagnosis": conclusion["diagnosis"],
        "records_csv": str((OUTPUT_DIR / "continuation_exhaustion_validation_records.csv").resolve()),
    }
    (OUTPUT_DIR / "continuation_exhaustion_validation_research.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "continuation_exhaustion_validation_research.md").write_text(
        render_report(payload),
        encoding="utf-8",
    )
    return payload


def classify(groups: dict[str, Any]) -> dict[str, str]:
    strong = groups.get("strong", {})
    medium = groups.get("medium", {})
    weak = groups.get("weak", {})
    strong_exp = strong.get("metrics", {}).get("expectancy_R", 0.0)
    strong_pf = strong.get("metrics", {}).get("profit_factor", 0.0)
    strong_exhaust = strong.get("exhaustion_probability", 0.0)
    medium_exp = medium.get("metrics", {}).get("expectancy_R", 0.0)
    weak_exp = weak.get("metrics", {}).get("expectancy_R", 0.0)
    medium_trades = medium.get("metrics", {}).get("trades", 0)
    weak_trades = weak.get("metrics", {}).get("trades", 0)

    if min(strong.get("metrics", {}).get("trades", 0), medium_trades, weak_trades) < 4:
        return {
            "classification": "NEEDS_MORE_DATA",
            "diagnosis": "At least one continuation bucket has fewer than 4 trades, so evidence is not statistically sufficient.",
        }
    if strong_exp < 0 and strong_pf < 1.0 and strong_exhaust >= 50.0 and (medium_exp > strong_exp or weak_exp > strong_exp):
        return {
            "classification": "CONTINUATION_EXHAUSTION_CONFIRMED",
            "diagnosis": "Strong continuation underperforms, shows high exhaustion/reversal behavior, and is worse than medium/weak buckets.",
        }
    if strong_exp < medium_exp and strong_exp < weak_exp:
        return {
            "classification": "PARTIAL_EFFECT",
            "diagnosis": "Strong continuation is weaker than the other buckets, but the sample or exhaustion markers are not decisive enough for full confirmation.",
        }
    return {
        "classification": "CONTINUATION_NOT_EXHAUSTION",
        "diagnosis": "Strong continuation does not show enough underperformance or exhaustion relative to medium/weak.",
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_report(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# CONTINUATION_EXHAUSTION_VALIDATION_RESEARCH")
    lines.append("")
    lines.append(f"- status: `{payload['status']}`")
    lines.append(f"- baseline: `{payload['baseline']}`")
    lines.append(f"- setup: `{payload['setup']}`")
    lines.append(f"- session: `{payload['session']}`")
    lines.append(f"- profile: `{payload['profile']}`")
    lines.append(f"- scenario: `{payload['scenario']}`")
    lines.append(f"- conclusion: `{payload['classification']}`")
    lines.append(f"- diagnosis: {payload['diagnosis']}")
    lines.append("")
    lines.append("## Definitions")
    lines.append("")
    for key, value in payload["definitions"].items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Continuation Quality Comparison")
    lines.append("")
    lines.append(
        "| Quality | Trades | WR | PF | Exp R | Net R | DD R | MFE Avg | MAE Avg | Time To Peak | Consumed Range | ATR Distance | Reversal % | Exhaustion % | Post-Continuation % | Momentum Decay 5m | Wick Absorption |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for quality in ["strong", "medium", "weak"]:
        data = payload["groups"][quality]
        metrics = data["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    quality,
                    str(metrics["trades"]),
                    _fmt(metrics["win_rate"], 2),
                    _fmt(metrics["profit_factor"]),
                    _fmt(metrics["expectancy_R"]),
                    _fmt(metrics["net_R"]),
                    _fmt(metrics["max_drawdown_R"]),
                    _fmt(data["mfe_avg"]),
                    _fmt(data["mae_avg"]),
                    _fmt(data["time_to_peak_avg_minutes"], 2),
                    _fmt(data["consumed_pct_signal_range_avg"]),
                    _fmt(data["distance_from_local_ATR_mean_avg"]),
                    _fmt(data["reversal_probability"], 2),
                    _fmt(data["exhaustion_probability"], 2),
                    _fmt(data["post_entry_continuation_probability"], 2),
                    _fmt(data["momentum_decay_5m_avg"]),
                    _fmt(data["wick_absorption_avg"]),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Year Stability")
    lines.append("")
    lines.append("| Quality | Year | Trades | WR | PF | Exp R | Net R | DD R |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for quality in ["strong", "medium", "weak"]:
        for year, metrics in payload["groups"][quality]["years"].items():
            lines.append(
                "| "
                + " | ".join(
                    [
                        quality,
                        year,
                        str(metrics["trades"]),
                        _fmt(metrics["win_rate"], 2),
                        _fmt(metrics["profit_factor"]),
                        _fmt(metrics["expectancy_R"]),
                        _fmt(metrics["net_R"]),
                        _fmt(metrics["max_drawdown_R"]),
                    ]
                )
                + " |"
            )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- `strong` is considered late/exhausted only if it underperforms and shows higher reversal/exhaustion behavior.")
    lines.append("- `medium` is expected to represent cleaner continuation if it has higher expectancy with lower exhaustion.")
    lines.append("- `weak` is expected to be either early reversal opportunity or noise depending on MFE/MAE and realized_R.")
    lines.append("- This report is an audit only. It does not activate gating, change entries, or alter execution.")
    lines.append("")
    lines.append(f"Records: `{payload['records_csv']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    payload = run_research()
    print(
        json.dumps(
            {
                "research": payload["research"],
                "classification": payload["classification"],
                "diagnosis": payload["diagnosis"],
                "groups": {
                    key: {
                        "trades": value["metrics"]["trades"],
                        "profit_factor": value["metrics"]["profit_factor"],
                        "expectancy_R": value["metrics"]["expectancy_R"],
                        "exhaustion_probability": value["exhaustion_probability"],
                        "reversal_probability": value["reversal_probability"],
                    }
                    for key, value in payload["groups"].items()
                },
                "report": str((OUTPUT_DIR / "continuation_exhaustion_validation_research.md").resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
