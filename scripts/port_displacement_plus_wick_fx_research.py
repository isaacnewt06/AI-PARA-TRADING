"""Port displacement_plus_wick_v1 research to FX symbols.

Research only. This script does not modify live trading logic, entries or
management. It reuses the frozen H4-fixed displacement_plus_wick candidate
logic and applies symbol-specific execution cost stress.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_reaction_zone_displacement_edge import (  # noqa: E402
    DisplacementEdgeValidator,
    EdgeTrade,
    ValidationVariant,
)


OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "cross_symbol_edge_transfer"
INPUT_DIR = ROOT / "data" / "backtests" / "input"
YEARS = (2023, 2024, 2025, 2026)
SYMBOLS = ("XAUUSDm", "EURUSDm", "GBPUSDm")
TARGET_VARIANT = ValidationVariant(
    "displacement_plus_wick",
    "displacement_plus_wick_v1 + REACTION_ZONE_MANAGEMENT_OVERLAY_V1 fast_03_be_08",
    require_wick_rejection=True,
)


SYMBOL_COSTS = {
    "XAUUSDm": {
        "spread_normal": 0.308,
        "spread_high": 0.396,
        "slippage_low": 0.05,
        "slippage_medium": 0.15,
        "slippage_high": 0.30,
        "strict_spread": 0.15,
        "relaxed_spread": 0.20,
    },
    "EURUSDm": {
        "spread_normal": 0.00008,
        "spread_high": 0.00012,
        "slippage_low": 0.00002,
        "slippage_medium": 0.00005,
        "slippage_high": 0.00010,
        "strict_spread": 0.00010,
        "relaxed_spread": 0.00015,
    },
    "GBPUSDm": {
        "spread_normal": 0.00010,
        "spread_high": 0.00016,
        "slippage_low": 0.00003,
        "slippage_medium": 0.00006,
        "slippage_high": 0.00012,
        "strict_spread": 0.00012,
        "relaxed_spread": 0.00018,
    },
}


STRESS_SCENARIOS = {
    "ideal_replay": {"spread": 0.0, "slippage": 0.0, "management_penalty_r": 0.0},
    "spread_normal": {"spread_key": "spread_normal", "slippage": 0.0, "management_penalty_r": 0.0},
    "spread_high": {"spread_key": "spread_high", "slippage": 0.0, "management_penalty_r": 0.0},
    "slippage_low": {"spread_key": "spread_normal", "slippage_key": "slippage_low", "management_penalty_r": 0.0},
    "slippage_medium": {"spread_key": "spread_normal", "slippage_key": "slippage_medium", "management_penalty_r": 0.0},
    "slippage_high": {"spread_key": "spread_normal", "slippage_key": "slippage_high", "management_penalty_r": 0.0},
    "realistic_mt5_execution": {
        "spread_key": "spread_normal",
        "slippage_key": "slippage_medium",
        "management_penalty_r": 0.05,
    },
    "pessimistic_execution": {
        "spread_key": "spread_high",
        "slippage_key": "slippage_high",
        "management_penalty_r": 0.12,
    },
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = run_research()
    (OUTPUT_DIR / "cross_symbol_edge_transfer.json").write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    for symbol, symbol_payload in payload["symbols"].items():
        filename = {
            "EURUSDm": "eurusd_displacement_validation.md",
            "GBPUSDm": "gbpusd_displacement_validation.md",
            "XAUUSDm": "xauusd_displacement_validation_reference.md",
        }[symbol]
        (OUTPUT_DIR / filename).write_text(render_symbol_report(symbol_payload), encoding="utf-8")
    (OUTPUT_DIR / "cross_symbol_edge_transfer.md").write_text(render_cross_symbol_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "classification": payload["classification"],
                "reports": {
                    "eurusd": str((OUTPUT_DIR / "eurusd_displacement_validation.md").resolve()),
                    "gbpusd": str((OUTPUT_DIR / "gbpusd_displacement_validation.md").resolve()),
                    "cross_symbol": str((OUTPUT_DIR / "cross_symbol_edge_transfer.md").resolve()),
                },
                "availability": payload["availability"],
                "ranking": payload["ranking"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def run_research() -> dict[str, Any]:
    validator = DisplacementEdgeValidator()
    symbols: dict[str, Any] = {}
    availability: dict[str, Any] = {}
    for symbol in SYMBOLS:
        symbol_payload = validate_symbol(validator, symbol)
        symbols[symbol] = symbol_payload
        availability[symbol] = symbol_payload["data_availability"]
        write_trades_csv(OUTPUT_DIR / f"{symbol}_displacement_plus_wick_trades.csv", symbol_payload["trades"])

    ranking = sorted(
        (
            {
                "symbol": symbol,
                **payload["aggregate"],
                "realistic_pf": payload["stress"]["realistic_mt5_execution"]["profit_factor"],
                "realistic_expectancy_R": payload["stress"]["realistic_mt5_execution"]["expectancy_R"],
            }
            for symbol, payload in symbols.items()
        ),
        key=lambda row: (
            row["realistic_pf"],
            row["realistic_expectancy_R"],
            -row["max_drawdown_R"],
            row["trades"],
        ),
        reverse=True,
    )
    return {
        "research": "FX_PORT_displacement_plus_wick_v1_REACTION_ZONE_MANAGEMENT_OVERLAY_V1",
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "baseline": "MTF_REAL_H4_FIXED_BASELINE",
        "management": "REACTION_ZONE_MANAGEMENT_OVERLAY_V1 fast_03_be_08",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "availability": availability,
        "ranking": ranking,
        "classification": classify_transfer(symbols),
    }


def validate_symbol(validator: DisplacementEdgeValidator, symbol: str) -> dict[str, Any]:
    yearly: dict[str, Any] = {}
    trades: list[dict[str, Any]] = []
    candidate_counts: dict[str, int] = {}
    availability = data_availability(symbol)
    for year in YEARS:
        if not availability[str(year)]["m5_h1_available"]:
            yearly[str(year)] = {
                "metrics": empty_metrics(),
                "status": "NO_DATA",
                "reason": availability[str(year)]["reason"],
            }
            candidate_counts[str(year)] = 0
            continue
        candidates = validator._candidates_for_year(symbol=symbol, year=year)
        candidate_counts[str(year)] = len(candidates)
        year_trades: list[dict[str, Any]] = []
        for candidate in candidates:
            trade = validator._apply_variant(candidate, TARGET_VARIANT)
            if trade is None:
                continue
            row = trade_row(trade=trade, candidate=candidate, symbol=symbol)
            year_trades.append(row)
            trades.append(row)
        yearly[str(year)] = {
            "metrics": metrics(year_trades),
            "status": "OK",
            "by_side": breakdown(year_trades, "side"),
            "by_session": breakdown(year_trades, "session"),
            "by_regime": breakdown(year_trades, "market_regime"),
            "by_expansion_subtype": breakdown(year_trades, "expansion_subtype"),
        }
    aggregate = metrics(trades)
    stress = stress_matrix(symbol=symbol, trades=trades)
    return {
        "symbol": symbol,
        "variant": TARGET_VARIANT.code,
        "candidate_counts": candidate_counts,
        "data_availability": availability,
        "yearly": yearly,
        "aggregate": aggregate,
        "by_side": breakdown(trades, "side"),
        "by_session": breakdown(trades, "session"),
        "by_regime": breakdown(trades, "market_regime"),
        "by_expansion_subtype": breakdown(trades, "expansion_subtype"),
        "stress": stress,
        "spread_sensitivity": spread_sensitivity(symbol=symbol, trades=trades),
        "classification": classify_symbol(symbol=symbol, aggregate=aggregate, stress=stress, availability=availability),
        "trades": trades,
    }


def data_availability(symbol: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for year in YEARS:
        files = {tf: INPUT_DIR / f"{symbol}_{tf}_{year}.csv" for tf in ("M1", "M5", "H1")}
        rows = {tf: count_csv_rows(path) for tf, path in files.items()}
        result[str(year)] = {
            "m1_rows": rows["M1"],
            "m5_rows": rows["M5"],
            "h1_rows": rows["H1"],
            "m5_h1_available": rows["M5"] > 1000 and rows["H1"] > 100,
            "m1_available_for_management": rows["M1"] > 1000,
            "reason": "OK" if rows["M5"] > 1000 and rows["H1"] > 100 else "missing_or_insufficient_M5_H1",
            "files": {tf: str(path.resolve()) for tf, path in files.items() if path.exists()},
        }
    return result


def trade_row(*, trade: EdgeTrade, candidate: dict[str, Any], symbol: str) -> dict[str, Any]:
    row = asdict(trade)
    row["symbol"] = symbol
    row["market_regime"] = candidate.get("market_regime", "UNKNOWN")
    row["compression_ok"] = bool(row["compression_ok"])
    row["continuation_momentum"] = bool(row["continuation_momentum"])
    row["micro_bos"] = bool(row["micro_bos"])
    return row


def stress_matrix(*, symbol: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    costs = SYMBOL_COSTS[symbol]
    return {
        code: metrics([stress_trade(row, costs=costs, scenario=scenario) for row in trades])
        for code, scenario in STRESS_SCENARIOS.items()
    }


def stress_trade(row: dict[str, Any], *, costs: dict[str, float], scenario: dict[str, Any]) -> dict[str, Any]:
    spread = float(scenario.get("spread", 0.0))
    if "spread_key" in scenario:
        spread += float(costs[scenario["spread_key"]])
    slippage = float(scenario.get("slippage", 0.0))
    if "slippage_key" in scenario:
        slippage += float(costs[scenario["slippage_key"]])
    risk = max(float(row["risk"]), 1e-12)
    cost_r = (spread + slippage) / risk
    stressed = dict(row)
    stressed["realized_r"] = round(float(row["realized_r"]) - cost_r - float(scenario.get("management_penalty_r", 0.0)), 4)
    stressed["cost_r"] = round(cost_r, 4)
    return stressed


def spread_sensitivity(*, symbol: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    costs = SYMBOL_COSTS[symbol]
    levels = [0.0, costs["strict_spread"], costs["relaxed_spread"], costs["spread_normal"], costs["spread_high"]]
    return {str(level): metrics([stress_trade(row, costs=costs, scenario={"spread": level}) for row in trades]) for level in sorted(set(levels))}


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return empty_metrics()
    values = [float(row["realized_r"]) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = peak = max_dd = 0.0
    losing_streak = streak = 0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if value < 0:
            streak += 1
            losing_streak = max(losing_streak, streak)
        else:
            streak = 0
    return {
        "trades": len(rows),
        "win_rate": round(len(wins) / len(rows) * 100.0, 2),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else 0.0),
        "expectancy_R": round(sum(values) / len(rows), 4),
        "net_R": round(sum(values), 4),
        "max_drawdown_R": round(max_dd, 4),
        "losing_streak": losing_streak,
        "trade_frequency_per_available_year": round(len(rows) / max(1, len({row["year"] for row in rows})), 2),
    }


def empty_metrics() -> dict[str, Any]:
    return {
        "trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "expectancy_R": 0.0,
        "net_R": 0.0,
        "max_drawdown_R": 0.0,
        "losing_streak": 0,
        "trade_frequency_per_available_year": 0.0,
    }


def breakdown(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key, "UNKNOWN"))].append(row)
    return {bucket: metrics(items) for bucket, items in sorted(grouped.items())}


def classify_symbol(*, symbol: str, aggregate: dict[str, Any], stress: dict[str, Any], availability: dict[str, Any]) -> str:
    available_years = sum(1 for item in availability.values() if item["m5_h1_available"])
    realistic = stress["realistic_mt5_execution"]
    if available_years < 2:
        return "EDGE_NOT_TRANSFERABLE_DATA_INSUFFICIENT"
    if aggregate["trades"] < 20:
        return "EDGE_NOT_TRANSFERABLE_LOW_FREQUENCY"
    if realistic["profit_factor"] >= 1.2 and realistic["expectancy_R"] > 0:
        return "SYMBOL EDGE CONFIRMED"
    if symbol != "XAUUSDm" and realistic["profit_factor"] > 1.0:
        return "EDGE IMPROVES ON FX BUT NEEDS FILTERING"
    return "EDGE NOT TRANSFERABLE"


def classify_transfer(symbols: dict[str, Any]) -> str:
    xau = symbols["XAUUSDm"]["stress"]["realistic_mt5_execution"]
    fx = [symbols[s]["stress"]["realistic_mt5_execution"] for s in ("EURUSDm", "GBPUSDm")]
    confirmed_fx = [s for s in ("EURUSDm", "GBPUSDm") if symbols[s]["classification"] == "SYMBOL EDGE CONFIRMED"]
    if confirmed_fx:
        return "EDGE IMPROVES ON FX"
    if xau["profit_factor"] >= 1.2 and all(item["profit_factor"] < 1.2 for item in fx):
        return "EDGE DEPENDENT ON XAU"
    return "EDGE NOT TRANSFERABLE"


def write_trades_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def count_csv_rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def metric_row(metric: dict[str, Any]) -> str:
    return (
        f"{metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
        f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']}"
    )


def render_symbol_report(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['symbol']} displacement_plus_wick_v1 Validation",
        "",
        "- status: RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "- baseline: `MTF_REAL_H4_FIXED_BASELINE`",
        "- management: `REACTION_ZONE_MANAGEMENT_OVERLAY_V1 fast_03_be_08`",
        f"- classification: `{payload['classification']}`",
        "",
        "## Data Availability",
        "",
        "| Year | M1 rows | M5 rows | H1 rows | M5/H1 available | M1 management available | Reason |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for year, item in payload["data_availability"].items():
        lines.append(
            f"| {year} | {item['m1_rows']} | {item['m5_rows']} | {item['h1_rows']} | "
            f"{item['m5_h1_available']} | {item['m1_available_for_management']} | {item['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Replay Multi-Year",
            "",
            "| Year | Status | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for year, item in payload["yearly"].items():
        lines.append(f"| {year} | {item['status']} | {metric_row(item['metrics'])} |")
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            "| Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |",
            "|---:|---:|---:|---:|---:|---:|---:|",
            f"| {metric_row(payload['aggregate'])} |",
            "",
            "## Stress Test Execution",
            "",
            "| Scenario | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario, metric in payload["stress"].items():
        lines.append(f"| {scenario} | {metric_row(metric)} |")
    lines.extend(["", "## Session Analysis", ""])
    lines.extend(render_breakdown(payload["by_session"]))
    lines.extend(["", "## BUY vs SELL", ""])
    lines.extend(render_breakdown(payload["by_side"]))
    lines.extend(["", "## EXPANSION vs NORMAL", ""])
    lines.extend(render_breakdown(payload["by_regime"]))
    lines.extend(["", "## Spread Sensitivity", "", "| Spread Cost | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |", "|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for cost, metric in payload["spread_sensitivity"].items():
        lines.append(f"| {cost} | {metric_row(metric)} |")
    return "\n".join(lines) + "\n"


def render_breakdown(items: dict[str, Any]) -> list[str]:
    lines = ["| Bucket | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    if not items:
        lines.append("| none | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")
        return lines
    for bucket, metric in items.items():
        lines.append(f"| {bucket} | {metric_row(metric)} |")
    return lines


def render_cross_symbol_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Cross Symbol Edge Transfer - displacement_plus_wick_v1",
        "",
        "- status: RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "- baseline: `MTF_REAL_H4_FIXED_BASELINE`",
        "- management: `REACTION_ZONE_MANAGEMENT_OVERLAY_V1 fast_03_be_08`",
        f"- classification: `{payload['classification']}`",
        "",
        "## Ranking",
        "",
        "| Symbol | Trades | PF | Exp R | DD R | Realistic PF | Realistic Exp R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in payload["ranking"]:
        lines.append(
            f"| {item['symbol']} | {item['trades']} | {item['profit_factor']} | {item['expectancy_R']} | "
            f"{item['max_drawdown_R']} | {item['realistic_pf']} | {item['realistic_expectancy_R']} |"
        )
    lines.extend(
        [
            "",
            "## Symbol Classifications",
            "",
            "| Symbol | Classification | Available Years | Aggregate PF | Realistic PF | Trade Frequency / Available Year |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for symbol, item in payload["symbols"].items():
        available_years = sum(1 for value in item["data_availability"].values() if value["m5_h1_available"])
        lines.append(
            f"| {symbol} | {item['classification']} | {available_years} | {item['aggregate']['profit_factor']} | "
            f"{item['stress']['realistic_mt5_execution']['profit_factor']} | {item['aggregate']['trade_frequency_per_available_year']} |"
        )
    lines.extend(
        [
            "",
            "## Data Limitation",
            "",
            "EURUSDm/GBPUSDm no tienen M5 disponible en esta terminal para 2023-2024. "
            "Por disciplina cuantitativa, esos años quedan marcados como NO_DATA y no se usan para afirmar robustez multi-año.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
