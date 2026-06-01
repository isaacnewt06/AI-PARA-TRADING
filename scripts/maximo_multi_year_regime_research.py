from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
YEARLY_DIR = ROOT / "data" / "backtests" / "maximo_mtf_quant_v4" / "yearly"
INPUT_DIR = ROOT / "data" / "backtests" / "input"
KNOWLEDGE_DB = ROOT / "data" / "telegram_trading_brain.db"
OUT_JSON = YEARLY_DIR / "multi_year_regime_research_h4_fixed.json"
OUT_MD = YEARLY_DIR / "multi_year_regime_research_h4_fixed.md"


@dataclass(frozen=True)
class TradeSource:
    label: str
    year: int
    path: Path
    partial: bool = False


TRADE_SOURCES = [
    TradeSource("2023", 2023, YEARLY_DIR / "2023_v56_aggressive_filtered_b_all_h4_fixed_trades.csv"),
    TradeSource("2024", 2024, YEARLY_DIR / "2024_v56_aggressive_filtered_b_all_h4_fixed_trades.csv"),
    TradeSource("2025", 2025, YEARLY_DIR / "2025_v56_aggressive_filtered_b_all_trades.csv"),
    TradeSource(
        "2026_partial",
        2026,
        YEARLY_DIR / "2026_v56_aggressive_filtered_b_all_jan_mar_partial_h4_fixed_trades.csv",
        partial=True,
    ),
]


def _profit_factor(values: pd.Series) -> float:
    gross_profit = values[values > 0].sum()
    gross_loss = -values[values < 0].sum()
    if gross_loss == 0:
        return 999.0 if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def _summary(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"trades": 0, "net": 0.0, "pf": 0.0, "wr": 0.0, "expectancy": 0.0}
    pnl = frame["net_pnl_usd"]
    return {
        "trades": int(len(frame)),
        "net": round(float(pnl.sum()), 4),
        "pf": round(_profit_factor(pnl), 4),
        "wr": round(float((pnl > 0).mean() * 100), 2),
        "expectancy": round(float(pnl.mean()), 4),
    }


def _load_trades() -> pd.DataFrame:
    ny_tz = ZoneInfo("America/New_York")
    frames = []
    for source in TRADE_SOURCES:
        frame = pd.read_csv(source.path)
        frame["year_label"] = source.label
        frame["year"] = source.year
        frame["is_partial_year"] = source.partial
        frame["entry_dt"] = pd.to_datetime(frame["entry_time"], utc=True)
        frame["exit_dt"] = pd.to_datetime(frame["exit_time"], utc=True)
        frame["entry_hour_utc"] = frame["entry_dt"].dt.hour
        frame["entry_hour_ny"] = frame["entry_dt"].dt.tz_convert(ny_tz).dt.hour
        frame["weekday"] = frame["entry_dt"].dt.day_name()
        frame["month"] = frame["entry_dt"].dt.month
        frame["session_ny"] = frame["entry_hour_ny"].map(_ny_session)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _ny_session(hour: int) -> str:
    if 0 <= hour <= 2:
        return "asia_late"
    if 3 <= hour <= 6:
        return "london_open"
    if 7 <= hour <= 10:
        return "ny_am"
    if 11 <= hour <= 14:
        return "ny_midday"
    if 15 <= hour <= 17:
        return "ny_pm"
    return "off_hours"


def _load_m5(year: int) -> pd.DataFrame:
    path = INPUT_DIR / f"XAUUSDm_M5_{year}.csv"
    frame = pd.read_csv(path)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.sort_values("time").drop_duplicates("time").set_index("time")
    return frame


def _enrich_m5(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["range"] = out["high"] - out["low"]
    out["body"] = (out["close"] - out["open"]).abs()
    out["body_pct"] = out["body"] / out["range"].clip(lower=1e-9)
    out["close_pos"] = (out["close"] - out["low"]) / out["range"].clip(lower=1e-9)
    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = tr.rolling(14, min_periods=14).mean()
    out["atr50"] = tr.rolling(50, min_periods=50).mean()
    out["atr_ratio"] = out["atr14"] / out["atr50"]
    out["range_mean20"] = out["range"].rolling(20, min_periods=20).mean()
    out["range_ratio"] = out["range"] / out["range_mean20"]
    out["direction"] = "flat"
    out.loc[out["close"] > out["open"], "direction"] = "up"
    out.loc[out["close"] < out["open"], "direction"] = "down"
    out["future_close_6"] = out["close"].shift(-6)
    out["future_high_6"] = out["high"].rolling(6, min_periods=1).max().shift(-5)
    out["future_low_6"] = out["low"].rolling(6, min_periods=1).min().shift(-5)
    out["move_20"] = (out["close"] - out["close"].shift(20)).abs()
    out["path_20"] = out["close"].diff().abs().rolling(20, min_periods=20).sum()
    out["efficiency_20"] = out["move_20"] / out["path_20"].clip(lower=1e-9)
    out["structural_state"] = out.apply(_structural_state, axis=1)
    return out


def _structural_state(row: pd.Series) -> str:
    if pd.isna(row.get("atr_ratio")) or pd.isna(row.get("range_ratio")):
        return "unknown"
    direction = row.get("direction")
    candle_range = max(float(row.get("range", 0.0)), 1e-9)
    if direction == "up":
        continuation = float(row.get("future_close_6", row["close"]) - row["close"])
        adverse = float(row["close"] - row.get("future_low_6", row["low"]))
    elif direction == "down":
        continuation = float(row["close"] - row.get("future_close_6", row["close"]))
        adverse = float(row.get("future_high_6", row["high"]) - row["close"])
    else:
        continuation = 0.0
        adverse = 0.0

    range_ratio = float(row["range_ratio"])
    atr_ratio = float(row["atr_ratio"])
    body_pct = float(row["body_pct"])
    efficiency = float(row.get("efficiency_20", 0.0) or 0.0)

    if range_ratio >= 1.5 and adverse >= candle_range:
        return "exhausted_expansion"
    if range_ratio >= 1.25 and body_pct >= 0.55 and continuation >= candle_range * 0.45 and adverse <= candle_range * 0.8:
        return "clean_expansion"
    if range_ratio >= 1.25 and adverse > max(continuation, 0.0) + candle_range * 0.35:
        return "trap_expansion"
    if atr_ratio >= 1.1 and efficiency >= 0.35:
        return "directional_expansion"
    if atr_ratio < 1.05 and efficiency < 0.28:
        return "rotational_normal"
    if atr_ratio < 0.9 and range_ratio < 0.85:
        return "compression"
    return "mixed_transition"


def _year_market_structure() -> tuple[dict, dict[int, pd.DataFrame]]:
    enriched_by_year: dict[int, pd.DataFrame] = {}
    summary = {}
    for source in TRADE_SOURCES:
        if source.year in enriched_by_year:
            continue
        m5 = _enrich_m5(_load_m5(source.year))
        enriched_by_year[source.year] = m5
        state_counts = m5["structural_state"].value_counts(normalize=True).mul(100).round(2).to_dict()
        summary[str(source.year)] = {
            "m5_rows": int(len(m5)),
            "avg_atr14": round(float(m5["atr14"].mean()), 4),
            "avg_atr_ratio": round(float(m5["atr_ratio"].mean()), 4),
            "avg_range_ratio": round(float(m5["range_ratio"].mean()), 4),
            "avg_efficiency_20": round(float(m5["efficiency_20"].mean()), 4),
            "structural_state_pct": state_counts,
        }
    return summary, enriched_by_year


def _attach_trade_structure(trades: pd.DataFrame, enriched_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for _, trade in trades.iterrows():
        m5 = enriched_by_year[int(trade["year"])]
        entry_time = trade["entry_dt"].floor("5min")
        if entry_time not in m5.index:
            nearest_pos = m5.index.get_indexer([entry_time], method="nearest")[0]
            feature = m5.iloc[nearest_pos]
        else:
            feature = m5.loc[entry_time]
        enriched = trade.to_dict()
        for col in ["atr_ratio", "range_ratio", "body_pct", "close_pos", "efficiency_20", "structural_state"]:
            value = feature[col]
            if hasattr(value, "item"):
                value = value.item()
            enriched[col] = value
        rows.append(enriched)
    out = pd.DataFrame(rows)
    out["body_bucket"] = pd.cut(
        out["body_pct"],
        bins=[-0.01, 0.35, 0.55, 0.75, 1.01],
        labels=["weak_body", "medium_body", "strong_body", "full_body"],
    ).astype(str)
    out["atr_bucket"] = pd.cut(
        out["atr_ratio"],
        bins=[-999, 0.9, 1.05, 1.2, 999],
        labels=["low_atr", "normal_atr", "high_atr", "extreme_atr"],
    ).astype(str)
    out["range_bucket"] = pd.cut(
        out["range_ratio"],
        bins=[-999, 0.85, 1.15, 1.5, 999],
        labels=["small_range", "normal_range", "expanded_range", "extreme_range"],
    ).astype(str)
    return out


def _performance_table(frame: pd.DataFrame, group_cols: list[str], min_trades: int = 1) -> list[dict]:
    rows = []
    for keys, group in frame.groupby(group_cols):
        if len(group) < min_trades:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {col: key for col, key in zip(group_cols, keys)}
        row.update(_summary(group))
        rows.append(row)
    return sorted(rows, key=lambda r: (r["net"], r["pf"]), reverse=True)


def _search_simple_rules(trades: pd.DataFrame) -> dict:
    dims = [
        "market_regime",
        "direction",
        "setup_type",
        "session_ny",
        "structural_state",
        "body_bucket",
        "atr_bucket",
        "range_bucket",
    ]
    values_by_dim = {dim: sorted(str(v) for v in trades[dim].dropna().unique()) for dim in dims}
    candidates = []
    for dim in dims:
        for value in values_by_dim[dim]:
            _score_rule(trades, [(dim, value)], candidates)
    for left_index, left_dim in enumerate(dims):
        for right_dim in dims[left_index + 1 :]:
            for left_value in values_by_dim[left_dim]:
                for right_value in values_by_dim[right_dim]:
                    _score_rule(trades, [(left_dim, left_value), (right_dim, right_value)], candidates)
    robust = [
        c
        for c in candidates
        if c["full_years_positive"] == 3
        and c["min_full_year_trades"] >= 5
        and c["min_full_year_pf"] >= 1.05
    ]
    near = [
        c
        for c in candidates
        if c["full_years_positive"] >= 2
        and c["min_full_year_trades"] >= 5
    ]
    return {
        "robust_count": len(robust),
        "top_robust": robust[:20],
        "top_near": near[:30],
        "all_candidates_tested": len(candidates),
    }


def _score_rule(trades: pd.DataFrame, predicates: list[tuple[str, str]], candidates: list[dict]) -> None:
    mask = pd.Series(True, index=trades.index)
    for dim, value in predicates:
        mask &= trades[dim].astype(str) == value
    subset = trades[mask]
    if len(subset) < 10:
        return
    by_year = {label: _summary(group) for label, group in subset.groupby("year_label")}
    if not all(label in by_year for label in ["2023", "2024", "2025"]):
        return
    full_trades = [by_year[label]["trades"] for label in ["2023", "2024", "2025"]]
    full_pfs = [by_year[label]["pf"] for label in ["2023", "2024", "2025"]]
    full_positive = sum(1 for label in ["2023", "2024", "2025"] if by_year[label]["net"] > 0)
    rule = " & ".join(f"{dim}={value}" for dim, value in predicates)
    total = _summary(subset)
    candidates.append(
        {
            "rule": rule,
            "total": total,
            "by_year": by_year,
            "full_years_positive": full_positive,
            "min_full_year_trades": min(full_trades),
            "min_full_year_pf": round(min(full_pfs), 4),
            "score": round(full_positive * 100 + min(full_pfs) * 10 + total["expectancy"], 4),
        }
    )
    candidates.sort(key=lambda item: (item["full_years_positive"], item["min_full_year_pf"], item["total"]["expectancy"]), reverse=True)


def _knowledge_summary() -> dict:
    if not KNOWLEDGE_DB.exists():
        return {}
    con = sqlite3.connect(KNOWLEDGE_DB)
    summary = {
        "normalized_rules": con.execute("select count(*) from normalized_rules").fetchone()[0],
        "strategy_playbooks": con.execute("select count(*) from strategy_playbooks").fetchone()[0],
        "transcripts": con.execute("select count(*) from transcripts").fetchone()[0],
        "top_strategy_families": [
            {"family": row[0], "rules": row[1]}
            for row in con.execute(
                """
                select strategy_family, count(*)
                from normalized_rules
                group by strategy_family
                order by count(*) desc
                limit 10
                """
            ).fetchall()
        ],
        "top_conditions": [
            {"condition": row[0], "count": row[1]}
            for row in con.execute(
                """
                select condition_key, count(*)
                from quantifiable_conditions
                group by condition_key
                order by count(*) desc
                limit 12
                """
            ).fetchall()
        ],
    }
    con.close()
    return summary


def _write_markdown(payload: dict) -> None:
    lines = [
        "# MAXIMO Multi-Year Regime Research",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Status: `{payload['decision']['status']}`",
        f"- Main finding: {payload['decision']['main_finding']}",
        f"- Next action: {payload['decision']['next_action']}",
        "",
        "## Baseline By Year",
        "",
        "| Year | Trades | Net | PF | WR | Expectancy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for year, row in payload["baseline_by_year"].items():
        lines.append(f"| {year} | {row['trades']} | {row['net']} | {row['pf']} | {row['wr']} | {row['expectancy']} |")

    lines += [
        "",
        "## Market Structure By Year",
        "",
        "| Year | M5 Rows | ATR14 Avg | ATR Ratio Avg | Range Ratio Avg | Efficiency20 Avg | Dominant States |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for year, row in payload["market_structure_by_year"].items():
        states = ", ".join(f"{key}:{value}%" for key, value in list(row["structural_state_pct"].items())[:4])
        lines.append(
            f"| {year} | {row['m5_rows']} | {row['avg_atr14']} | {row['avg_atr_ratio']} | {row['avg_range_ratio']} | {row['avg_efficiency_20']} | {states} |"
        )

    lines += [
        "",
        "## Performance By Structural State",
        "",
        "| State | Trades | Net | PF | WR | Expectancy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["performance_by_structural_state"]:
        lines.append(
            f"| {row['structural_state']} | {row['trades']} | {row['net']} | {row['pf']} | {row['wr']} | {row['expectancy']} |"
        )

    lines += [
        "",
        "## Robust Rule Search",
        "",
        f"- Simple candidates tested: `{payload['simple_rule_search']['all_candidates_tested']}`",
        f"- Robust candidates positive in 2023, 2024 and 2025: `{payload['simple_rule_search']['robust_count']}`",
        "",
        "### Top Near Candidates",
        "",
        "| Rule | Full Years Positive | Min Full-Year PF | Total Trades | Total Net | Total PF |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["simple_rule_search"]["top_near"][:12]:
        lines.append(
            f"| {row['rule']} | {row['full_years_positive']} | {row['min_full_year_pf']} | {row['total']['trades']} | {row['total']['net']} | {row['total']['pf']} |"
        )

    lines += [
        "",
        "## Knowledge Cross-Check",
        "",
        f"- Normalized rules: `{payload['knowledge_summary'].get('normalized_rules')}`",
        f"- Strategy playbooks: `{payload['knowledge_summary'].get('strategy_playbooks')}`",
        f"- Transcripts: `{payload['knowledge_summary'].get('transcripts')}`",
        "",
        "Top families:",
    ]
    for row in payload["knowledge_summary"].get("top_strategy_families", [])[:8]:
        lines.append(f"- {row['family']}: {row['rules']} rules")

    lines += [
        "",
        "## Interpretation",
        "",
        "- The current strategy is not failing because one obvious filter is missing.",
        "- `EXPANSION` is too broad: it contains clean continuation, traps, exhaustion and transition states.",
        "- The extracted knowledge emphasizes OB Rejection, Session Expansion, Breakout Retest and FVG Continuation, but the execution layer compresses those ideas into a small set of generic gates.",
        "- The next improvement should be a research candidate that separates market structure states before selecting the playbook. This is a research change first, not a live-risk change.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    trades = _load_trades()
    baseline_by_year = {label: _summary(group) for label, group in trades.groupby("year_label")}
    market_structure_by_year, enriched_by_year = _year_market_structure()
    trades_enriched = _attach_trade_structure(trades, enriched_by_year)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": {
            "status": "REGIME_GENERALIZATION_FAILURE_CONFIRMED",
            "main_finding": "No simple v56 subset is robust across 2023, 2024 and refreshed 2025; 2026 partial is severe stress failure.",
            "next_action": "Build a non-live regime research candidate that classifies clean/trap/exhausted/rotational states before playbook selection.",
        },
        "baseline_by_year": baseline_by_year,
        "market_structure_by_year": market_structure_by_year,
        "performance_by_structural_state": _performance_table(trades_enriched, ["structural_state"]),
        "performance_by_state_and_year": _performance_table(trades_enriched, ["year_label", "structural_state"]),
        "performance_by_state_regime_direction": _performance_table(
            trades_enriched, ["structural_state", "market_regime", "direction"], min_trades=3
        ),
        "simple_rule_search": _search_simple_rules(trades_enriched),
        "knowledge_summary": _knowledge_summary(),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(payload)
    print(json.dumps({"json": str(OUT_JSON), "md": str(OUT_MD), "decision": payload["decision"]}, indent=2))


if __name__ == "__main__":
    main()
