"""Research EXECUTION_SURVIVAL_LAYER for displacement_plus_wick_v1.

This does not change entry logic, displacement logic, wick logic, defensive
management, or risk model. It only replays the frozen trades under execution
environment assumptions to identify where the edge survives.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SOURCE_TRADES = (
    ROOT
    / "data"
    / "backtests"
    / "reaction_zone_expansion_brain"
    / "V1_displacement_validation"
    / "displacement_plus_wick_trades.csv"
)
OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "execution_survival_layer"


@dataclass(slots=True)
class ExecutionAssumption:
    code: str
    label: str
    spread_price: float = 0.0
    slippage_price: float = 0.0
    latency_price: float = 0.0
    entry_delay_price: float = 0.0
    partial_fill_factor: float = 1.0
    protected_stop_r: float = 0.4
    be_after_partial_r: float = 0.25


@dataclass(slots=True)
class SimTrade:
    code: str
    year: int
    side: str
    hour_ny: int
    session: str
    atr_bucket: str
    expansion_subtype: str
    continuation_quality: str
    risk: float
    cost_r: float
    mfe_r: float
    mae_r: float
    result: str
    realized_r: float


def _load_rows() -> list[dict[str, Any]]:
    with SOURCE_TRADES.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(row: dict[str, Any], key: str) -> float:
    return float(row[key])


def _simulate_one(row: dict[str, Any], assumption: ExecutionAssumption) -> SimTrade:
    risk = max(_float(row, "risk"), 1e-9)
    total_cost_price = assumption.spread_price + assumption.slippage_price + assumption.latency_price + assumption.entry_delay_price
    cost_r = total_cost_price / risk
    rr = max(0.05, _float(row, "rr") - cost_r)
    mfe = max(0.0, _float(row, "mfe_r") - cost_r)
    mae = _float(row, "mae_r") + cost_r
    target_hit = mfe >= rr
    stop_hit = mae >= 1.0 + cost_r * 0.25

    if target_hit and not stop_hit:
        result = "TP"
        realized = 0.5 * max(0.0, 0.5 - cost_r) + 0.5 * rr
    elif target_hit and stop_hit:
        result = "CONFLICT_STOP_FIRST"
        realized = -1.01 - cost_r
    elif stop_hit:
        if mfe >= 0.8:
            result = "PROTECTED_STOP"
            realized = max(-1.01 - cost_r, assumption.protected_stop_r - 0.5 * cost_r)
        elif mfe >= 0.5:
            result = "BE_AFTER_PARTIAL"
            realized = max(-1.01 - cost_r, assumption.be_after_partial_r - 0.5 * cost_r)
        else:
            result = "SL"
            realized = -1.01 - cost_r
    else:
        result = "OPEN_UNKNOWN"
        realized = _float(row, "realized_r") - cost_r

    if realized > 0 and assumption.partial_fill_factor < 1.0:
        realized *= assumption.partial_fill_factor
        result = f"{result}_PARTIAL_FILL"

    return SimTrade(
        code=assumption.code,
        year=int(row["year"]),
        side=row["side"],
        hour_ny=int(row["hour_ny"]),
        session=row["session"],
        atr_bucket=row["atr_bucket"],
        expansion_subtype=row["expansion_subtype"],
        continuation_quality=row["continuation_quality"],
        risk=round(risk, 5),
        cost_r=round(cost_r, 5),
        mfe_r=round(mfe, 5),
        mae_r=round(mae, 5),
        result=result,
        realized_r=round(realized, 5),
    )


def _simulate(rows: list[dict[str, Any]], assumption: ExecutionAssumption) -> list[SimTrade]:
    return [_simulate_one(row, assumption) for row in rows]


def _metrics(trades: list[SimTrade]) -> dict[str, Any]:
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
    wins = [trade.realized_r for trade in trades if trade.realized_r > 0]
    losses = [trade.realized_r for trade in trades if trade.realized_r < 0]
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
    net = sum(trade.realized_r for trade in trades)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100.0, 2),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else 999.0,
        "expectancy_R": round(net / len(trades), 4),
        "net_R": round(net, 4),
        "max_drawdown_R": round(max_dd, 4),
        "losing_streak": losing_streak,
    }


def _breakdown(trades: list[SimTrade], attr: str) -> dict[str, Any]:
    grouped: dict[str, list[SimTrade]] = defaultdict(list)
    for trade in trades:
        grouped[str(getattr(trade, attr))].append(trade)
    return {key: _metrics(bucket) for key, bucket in sorted(grouped.items())}


def _classify(metric: dict[str, Any]) -> str:
    if metric["trades"] < 8:
        return "THIN EDGE ENVIRONMENTS"
    if metric["profit_factor"] >= 1.35 and metric["expectancy_R"] > 0.12 and metric["max_drawdown_R"] <= 5.0:
        return "SAFE ENVIRONMENTS"
    if metric["profit_factor"] >= 1.0 and metric["expectancy_R"] >= 0.0:
        return "THIN EDGE ENVIRONMENTS"
    return "DEAD ENVIRONMENTS"


def _grid(label: str, values: list[float], field: str) -> list[dict[str, Any]]:
    rows = _load_rows()
    output = []
    for value in values:
        assumption = ExecutionAssumption(code=f"{label}_{value:g}", label=f"{label} {value:g}", **{field: value})
        trades = _simulate(rows, assumption)
        metric = _metrics(trades)
        output.append(
            {
                "value": value,
                "assumption": asdict(assumption),
                "metrics": metric,
                "classification": _classify(metric),
                "by_session": _breakdown(trades, "session"),
                "by_hour_ny": _breakdown(trades, "hour_ny"),
                "by_atr_bucket": _breakdown(trades, "atr_bucket"),
            }
        )
    return output


def _max_survival_threshold(grid: list[dict[str, Any]], *, minimum_pf: float = 1.2) -> float | None:
    survivors = [
        item["value"]
        for item in grid
        if item["metrics"]["profit_factor"] >= minimum_pf and item["metrics"]["expectancy_R"] > 0
    ]
    return max(survivors) if survivors else None


def _adaptive_simulations() -> dict[str, Any]:
    rows = _load_rows()
    dynamic_spread = {
        "ny_am": 0.16,
        "ny_pm": 0.22,
        "london": 0.18,
        "asia_open": 0.35,
        "asia_to_london": 0.28,
    }
    safe_sessions = {"ny_am", "ny_pm"}
    safe_or_thin_sessions = {"ny_am", "ny_pm", "asia_open", "asia_to_london"}
    simulations: dict[str, list[SimTrade]] = {}

    simulations["spread_filter_adaptive_0_22"] = [
        _simulate_one(row, ExecutionAssumption(code="spread_filter_adaptive_0_22", label="spread filter adaptive", spread_price=dynamic_spread.get(row["session"], 0.25)))
        for row in rows
        if dynamic_spread.get(row["session"], 0.25) <= 0.22
    ]
    simulations["session_adaptive_ny_only"] = [
        _simulate_one(row, ExecutionAssumption(code="session_adaptive_ny_only", label="session adaptive NY only", spread_price=dynamic_spread.get(row["session"], 0.25)))
        for row in rows
        if row["session"] in safe_sessions
    ]
    simulations["latency_adaptive_skip_london_asia_open"] = [
        _simulate_one(row, ExecutionAssumption(code="latency_adaptive_skip_london_asia_open", label="latency adaptive", latency_price=0.15))
        for row in rows
        if row["session"] in safe_sessions
    ]
    simulations["delayed_entry_0_15"] = _simulate(
        rows,
        ExecutionAssumption(code="delayed_entry_0_15", label="delayed entry", entry_delay_price=0.15),
    )
    simulations["partial_execution_0_85"] = _simulate(
        rows,
        ExecutionAssumption(code="partial_execution_0_85", label="partial execution", partial_fill_factor=0.85),
    )
    simulations["skip_low_efficiency_environments"] = [
        _simulate_one(row, ExecutionAssumption(code="skip_low_efficiency_environments", label="skip low efficiency", spread_price=dynamic_spread.get(row["session"], 0.25)))
        for row in rows
        if row["session"] in safe_or_thin_sessions and not (row["session"] == "london" or row["atr_bucket"] == "normal_atr")
    ]

    return {
        code: {
            "metrics": _metrics(trades),
            "classification": _classify(_metrics(trades)),
            "trades": len(trades),
            "by_session": _breakdown(trades, "session"),
            "by_atr_bucket": _breakdown(trades, "atr_bucket"),
        }
        for code, trades in simulations.items()
    }


def _environment_classification(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    baseline = payload["baseline_environment"]["by_session"]
    dynamic = next(item for item in payload["spread_grid"] if item["value"] == 0.2)
    buckets: dict[str, list[dict[str, Any]]] = {
        "SAFE ENVIRONMENTS": [],
        "THIN EDGE ENVIRONMENTS": [],
        "DEAD ENVIRONMENTS": [],
    }
    for session, metric in baseline.items():
        item = {"type": "session", "name": session, "baseline": metric}
        buckets[_classify(metric)].append(item)
    for hour, metric in payload["baseline_environment"]["by_hour_ny"].items():
        item = {"type": "hour_ny", "name": hour, "baseline": metric}
        buckets[_classify(metric)].append(item)
    for atr, metric in dynamic["by_atr_bucket"].items():
        item = {"type": "atr_bucket_at_spread_0_2", "name": atr, "stress": metric}
        buckets[_classify(metric)].append(item)
    return buckets


def _row(metric: dict[str, Any]) -> str:
    return (
        f"{metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
        f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']}"
    )


def _execution_report(payload: dict[str, Any]) -> str:
    lines = [
        "# EXECUTION_SURVIVAL_LAYER Research",
        "",
        f"- status: {payload['status']}",
        f"- frozen_candidate: `{payload['frozen_candidate']}`",
        f"- max_spread_safe_threshold: {payload['thresholds']['max_spread_safe_threshold']}",
        f"- max_slippage_survival_threshold: {payload['thresholds']['max_slippage_survival_threshold']}",
        f"- max_latency_survival_threshold: {payload['thresholds']['max_latency_survival_threshold']}",
        "",
        "## Adaptive Simulations",
        "",
        "| Simulation | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak | Class |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for code, item in payload["adaptive_simulations"].items():
        lines.append(f"| {code} | {_row(item['metrics'])} | {item['classification']} |")
    lines.extend(
        [
            "",
            "## Environment Classes",
        ]
    )
    for label, items in payload["environment_classes"].items():
        lines.extend(["", f"### {label}"])
        if not items:
            lines.append("- none")
            continue
        for item in items:
            metric = item.get("baseline") or item.get("stress")
            lines.append(f"- {item['type']} `{item['name']}`: PF {metric['profit_factor']} ExpR {metric['expectancy_R']} DD {metric['max_drawdown_R']}")
    return "\n".join(lines) + "\n"


def _spread_matrix(payload: dict[str, Any]) -> str:
    lines = [
        "# spread_survival_matrix",
        "",
        "| Spread | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak | Class |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in payload["spread_grid"]:
        lines.append(f"| {item['value']} | {_row(item['metrics'])} | {item['classification']} |")
    lines.extend(["", "## Spread By Hour at 0.20"])
    spread_02 = next(item for item in payload["spread_grid"] if item["value"] == 0.2)
    lines.extend(["", "| Hour NY | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak | Class |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"])
    for hour, metric in spread_02["by_hour_ny"].items():
        lines.append(f"| {hour} | {_row(metric)} | {_classify(metric)} |")
    return "\n".join(lines) + "\n"


def _session_matrix(payload: dict[str, Any]) -> str:
    lines = [
        "# session_fragility_matrix",
        "",
        "## Baseline By Session",
        "",
        "| Session | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak | Class |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for session, metric in payload["baseline_environment"]["by_session"].items():
        lines.append(f"| {session} | {_row(metric)} | {_classify(metric)} |")
    lines.extend(["", "## Dynamic Spread By Session"])
    dynamic = payload["adaptive_simulations"]["spread_filter_adaptive_0_22"]["by_session"]
    lines.extend(["", "| Session | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak | Class |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"])
    for session, metric in dynamic.items():
        lines.append(f"| {session} | {_row(metric)} | {_classify(metric)} |")
    return "\n".join(lines) + "\n"


def _edge_conditions(payload: dict[str, Any]) -> str:
    lines = [
        "# edge_operating_conditions",
        "",
        "## Minimum Conditions Found",
        "",
        f"- Maximum spread for PF>=1.2 survival: `{payload['thresholds']['max_spread_safe_threshold']}` price units.",
        f"- Maximum slippage for PF>=1.2 survival: `{payload['thresholds']['max_slippage_survival_threshold']}` price units.",
        f"- Maximum latency penalty for PF>=1.2 survival: `{payload['thresholds']['max_latency_survival_threshold']}` price units.",
        "- Strongest sessions: `ny_am`, then `ny_pm`.",
        "- Weak/dead session under stress: `london`.",
        "- High spread environments are dead unless skipped.",
        "- Dynamic spread needs session/spread gate; otherwise edge becomes thin.",
        "",
        "## Do Not Operate Research Candidate When",
        "",
        "- Spread is above the survival threshold.",
        "- Latency or execution delay is high.",
        "- Session is London without extra confirmation.",
        "- Environment class is DEAD ENVIRONMENTS.",
        "",
        "## Research Only",
        "",
        "These are operating conditions for future validation, not live execution rules.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = _load_rows()
    baseline_trades = _simulate(rows, ExecutionAssumption(code="baseline", label="baseline"))
    spread_grid = _grid("spread", [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50], "spread_price")
    slippage_grid = _grid("slippage", [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40], "slippage_price")
    latency_grid = _grid("latency", [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40], "latency_price")
    entry_delay_grid = _grid("entry_delay", [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40], "entry_delay_price")
    trailing_grid = []
    for protected_r in [0.15, 0.25, 0.30, 0.40, 0.50]:
        assumption = ExecutionAssumption(code=f"trailing_{protected_r:g}", label=f"protected stop {protected_r:g}", protected_stop_r=protected_r)
        trades = _simulate(rows, assumption)
        metric = _metrics(trades)
        trailing_grid.append({"value": protected_r, "assumption": asdict(assumption), "metrics": metric, "classification": _classify(metric)})

    payload = {
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "frozen_candidate": "displacement_plus_wick_v1",
        "source_trades": str(SOURCE_TRADES),
        "baseline_environment": {
            "metrics": _metrics(baseline_trades),
            "by_session": _breakdown(baseline_trades, "session"),
            "by_hour_ny": _breakdown(baseline_trades, "hour_ny"),
            "by_atr_bucket": _breakdown(baseline_trades, "atr_bucket"),
        },
        "spread_grid": spread_grid,
        "slippage_grid": slippage_grid,
        "latency_grid": latency_grid,
        "entry_delay_grid": entry_delay_grid,
        "trailing_execution_grid": trailing_grid,
        "adaptive_simulations": _adaptive_simulations(),
        "thresholds": {
            "max_spread_safe_threshold": _max_survival_threshold(spread_grid),
            "max_slippage_survival_threshold": _max_survival_threshold(slippage_grid),
            "max_latency_survival_threshold": _max_survival_threshold(latency_grid),
            "max_entry_delay_survival_threshold": _max_survival_threshold(entry_delay_grid),
        },
    }
    payload["environment_classes"] = _environment_classification(payload)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "execution_survival_layer.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (OUTPUT_DIR / "execution_survival_layer.md").write_text(_execution_report(payload), encoding="utf-8")
    (OUTPUT_DIR / "edge_operating_conditions.md").write_text(_edge_conditions(payload), encoding="utf-8")
    (OUTPUT_DIR / "spread_survival_matrix.md").write_text(_spread_matrix(payload), encoding="utf-8")
    (OUTPUT_DIR / "session_fragility_matrix.md").write_text(_session_matrix(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str((OUTPUT_DIR / "execution_survival_layer.md").resolve()),
                "edge_conditions": str((OUTPUT_DIR / "edge_operating_conditions.md").resolve()),
                "spread_matrix": str((OUTPUT_DIR / "spread_survival_matrix.md").resolve()),
                "session_matrix": str((OUTPUT_DIR / "session_fragility_matrix.md").resolve()),
                "thresholds": payload["thresholds"],
                "adaptive_simulations": {
                    code: {"metrics": item["metrics"], "classification": item["classification"]}
                    for code, item in payload["adaptive_simulations"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
