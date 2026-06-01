"""Stress test displacement_plus_wick_v1 without changing entries.

Research only. Uses the frozen `displacement_plus_wick_trades.csv` signals and
applies execution/cost stress assumptions to the same entries.
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
OUTPUT_DIR = ROOT / "data" / "backtests" / "reaction_zone_expansion_brain" / "displacement_plus_wick_v1_stress"


@dataclass(slots=True)
class StressScenario:
    code: str
    label: str
    fixed_cost_price: float = 0.0
    slippage_price: float = 0.0
    conflict_policy: str = "observed"
    partial_fill_factor: float = 1.0
    latency_price: float = 0.0
    dynamic_spread: bool = False


@dataclass(slots=True)
class StressedTrade:
    scenario: str
    year: int
    side: str
    session: str
    atr_bucket: str
    expansion_subtype: str
    continuation_quality: str
    risk: float
    total_cost_price: float
    cost_r: float
    effective_rr: float
    effective_mfe_r: float
    effective_mae_r: float
    conflict: bool
    result: str
    realized_r: float


SCENARIOS = [
    StressScenario("baseline_observed", "Baseline observed replay"),
    StressScenario("spread_normal", "1. Spread normal", fixed_cost_price=0.15),
    StressScenario("spread_high", "2. Spread alto", fixed_cost_price=0.45),
    StressScenario("slippage_low", "3. Slippage bajo", slippage_price=0.05),
    StressScenario("slippage_medium", "4. Slippage medio", slippage_price=0.15),
    StressScenario("slippage_high", "5. Slippage alto", slippage_price=0.30),
    StressScenario("execution_pessimistic", "6. Ejecución pesimista", fixed_cost_price=0.15, conflict_policy="stop_first"),
    StressScenario("partial_execution", "7. Ejecución parcial", partial_fill_factor=0.85),
    StressScenario("latency_simulated", "8. Latencia simulada", latency_price=0.25),
    StressScenario("tp_sl_conflict_stop_first", "9. TP/SL conflict dentro de vela", conflict_policy="stop_first"),
    StressScenario("dynamic_spread_by_session", "10. Spread dinámico por sesión", dynamic_spread=True),
]


DYNAMIC_SPREAD_BY_SESSION = {
    "ny_am": 0.16,
    "ny_pm": 0.22,
    "london": 0.18,
    "asia_open": 0.35,
    "asia_to_london": 0.28,
}


def _load_trades() -> list[dict[str, Any]]:
    with SOURCE_TRADES.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _to_float(row: dict[str, Any], key: str) -> float:
    return float(row[key])


def _scenario_cost(row: dict[str, Any], scenario: StressScenario) -> float:
    dynamic = DYNAMIC_SPREAD_BY_SESSION.get(row["session"], 0.25) if scenario.dynamic_spread else 0.0
    return scenario.fixed_cost_price + scenario.slippage_price + scenario.latency_price + dynamic


def _stress_trade(row: dict[str, Any], scenario: StressScenario) -> StressedTrade:
    risk = max(_to_float(row, "risk"), 1e-9)
    rr = _to_float(row, "rr")
    mfe = _to_float(row, "mfe_r")
    mae = _to_float(row, "mae_r")
    original_realized = _to_float(row, "realized_r")
    total_cost = _scenario_cost(row, scenario)
    cost_r = total_cost / risk
    effective_rr = max(0.05, rr - cost_r)
    effective_mfe = max(0.0, mfe - cost_r)
    effective_mae = mae + cost_r
    target_hit = effective_mfe >= effective_rr
    stop_hit = effective_mae >= 1.0 + cost_r * 0.25
    conflict = target_hit and stop_hit

    if scenario.code == "baseline_observed":
        result = row["managed_result"]
        realized = original_realized
    elif conflict and scenario.conflict_policy == "stop_first":
        result = "CONFLICT_STOP_FIRST"
        realized = -1.01 - cost_r
    elif target_hit:
        result = "TP_WITH_PARTIAL_STRESSED"
        realized = 0.5 * max(0.0, 0.5 - cost_r) + 0.5 * effective_rr
    elif stop_hit:
        if effective_mfe >= 0.8:
            result = "PROTECTED_STOP_STRESSED"
            realized = max(-1.01 - cost_r, 0.4 - 0.5 * cost_r)
        elif effective_mfe >= 0.5:
            result = "BE_AFTER_PARTIAL_STRESSED"
            realized = max(-1.01 - cost_r, 0.25 - 0.5 * cost_r)
        else:
            result = "SL_STRESSED"
            realized = -1.01 - cost_r
    else:
        result = "OPEN_UNKNOWN_STRESSED"
        realized = original_realized - cost_r

    if realized > 0 and scenario.partial_fill_factor < 1.0:
        realized *= scenario.partial_fill_factor
        result = f"{result}_PARTIAL_FILL"

    return StressedTrade(
        scenario=scenario.code,
        year=int(row["year"]),
        side=row["side"],
        session=row["session"],
        atr_bucket=row["atr_bucket"],
        expansion_subtype=row["expansion_subtype"],
        continuation_quality=row["continuation_quality"],
        risk=round(risk, 5),
        total_cost_price=round(total_cost, 5),
        cost_r=round(cost_r, 5),
        effective_rr=round(effective_rr, 5),
        effective_mfe_r=round(effective_mfe, 5),
        effective_mae_r=round(effective_mae, 5),
        conflict=conflict,
        result=result,
        realized_r=round(realized, 5),
    )


def _metrics(trades: list[StressedTrade]) -> dict[str, Any]:
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


def _breakdown(trades: list[StressedTrade], attr: str) -> dict[str, Any]:
    grouped: dict[str, list[StressedTrade]] = defaultdict(list)
    for trade in trades:
        grouped[str(getattr(trade, attr))].append(trade)
    return {key: _metrics(bucket) for key, bucket in sorted(grouped.items())}


def _degradation(base: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any]:
    base_pf = max(float(base["profit_factor"]), 1e-9)
    base_exp = max(float(base["expectancy_R"]), 1e-9)
    return {
        "pf_degradation_pct": round((base_pf - metric["profit_factor"]) / base_pf * 100.0, 2),
        "expectancy_degradation_pct": round((base_exp - metric["expectancy_R"]) / base_exp * 100.0, 2),
        "dd_change_pct": round(((metric["max_drawdown_R"] - base["max_drawdown_R"]) / max(base["max_drawdown_R"], 1e-9)) * 100.0, 2),
    }


def _classification(results: list[dict[str, Any]]) -> str:
    stressed = [item for item in results if item["scenario"]["code"] != "baseline_observed"]
    survival = sum(1 for item in stressed if item["metrics"]["profit_factor"] >= 1.2 and item["metrics"]["expectancy_R"] > 0)
    worst_pf = min(item["metrics"]["profit_factor"] for item in stressed)
    worst_dd = max(item["metrics"]["max_drawdown_R"] for item in stressed)
    if survival >= 8 and worst_pf >= 1.2 and worst_dd <= 6:
        return "ROBUST"
    if survival >= 7 and worst_pf >= 1.0 and worst_dd <= 10:
        return "MODERATELY ROBUST"
    if survival >= 4:
        return "FRAGILE"
    return "OVERFIT"


def _edge_survival(metric: dict[str, Any]) -> str:
    if metric["profit_factor"] >= 1.3 and metric["expectancy_R"] > 0 and metric["max_drawdown_R"] <= 6:
        return "survives"
    if metric["profit_factor"] >= 1.0 and metric["expectancy_R"] >= 0:
        return "thin_survival"
    return "fails"


def _row(metric: dict[str, Any]) -> str:
    return (
        f"{metric['trades']} | {metric['win_rate']} | {metric['profit_factor']} | "
        f"{metric['expectancy_R']} | {metric['net_R']} | {metric['max_drawdown_R']} | {metric['losing_streak']}"
    )


def _main_report(payload: dict[str, Any]) -> str:
    lines = [
        "# displacement_plus_wick_v1 Stress Test",
        "",
        f"- status: {payload['status']}",
        f"- frozen_candidate: `{payload['frozen_candidate']}`",
        f"- classification: `{payload['classification']}`",
        "",
        "## Scenario Summary",
        "",
        "| Scenario | PF | Exp R | DD R | WR | PF Degradation % | Exp Degradation % | Edge Survival |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in payload["results"]:
        metric = item["metrics"]
        deg = item["degradation"]
        lines.append(
            f"| {item['scenario']['label']} | {metric['profit_factor']} | {metric['expectancy_R']} | {metric['max_drawdown_R']} | "
            f"{metric['win_rate']} | {deg['pf_degradation_pct']} | {deg['expectancy_degradation_pct']} | {item['edge_survival']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Entries, displacement logic, wick logic and defensive management were kept frozen.",
            "- Stress only changes execution assumptions: spread, slippage, latency, conflict ordering, partial fill and dynamic session spread.",
            "- This is not live approval. It is execution robustness research.",
        ]
    )
    return "\n".join(lines) + "\n"


def _fragility_report(payload: dict[str, Any]) -> str:
    lines = [
        "# execution_fragility_report",
        "",
        f"- classification: `{payload['classification']}`",
        "",
        "## Yearly Survival By Scenario",
    ]
    for item in payload["results"]:
        lines.extend(
            [
                "",
                f"### {item['scenario']['label']}",
                "",
                "| Year | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak | Edge |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for year, metric in item["by_year"].items():
            lines.append(f"| {year} | {_row(metric)} | {_edge_survival(metric)} |")
    lines.extend(["", "## Session Fragility"])
    for item in payload["results"]:
        lines.extend(["", f"### {item['scenario']['label']}", "", "| Session | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak |", "|---|---:|---:|---:|---:|---:|---:|---:|"])
        for session, metric in item["by_session"].items():
            lines.append(f"| {session} | {_row(metric)} |")
    return "\n".join(lines) + "\n"


def _cost_matrix(payload: dict[str, Any]) -> str:
    lines = [
        "# cost_sensitivity_matrix",
        "",
        "| Scenario | Avg Cost R | Conflicts | Trades | WR | PF | Exp R | Net R | DD R | Losing Streak | Edge |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in payload["results"]:
        lines.append(
            f"| {item['scenario']['label']} | {item['avg_cost_r']} | {item['conflict_count']} | {_row(item['metrics'])} | {item['edge_survival']} |"
        )
    return "\n".join(lines) + "\n"


def _write_jsonl(path: Path, trades: list[StressedTrade]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for trade in trades:
            handle.write(json.dumps(asdict(trade), default=str) + "\n")


def main() -> None:
    rows = _load_trades()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scenario_results = []
    baseline_metrics = None
    for scenario in SCENARIOS:
        trades = [_stress_trade(row, scenario) for row in rows]
        metrics = _metrics(trades)
        if scenario.code == "baseline_observed":
            baseline_metrics = metrics
        assert baseline_metrics is not None
        result = {
            "scenario": asdict(scenario),
            "metrics": metrics,
            "degradation": _degradation(baseline_metrics, metrics),
            "edge_survival": _edge_survival(metrics),
            "avg_cost_r": round(sum(t.cost_r for t in trades) / len(trades), 5) if trades else 0.0,
            "conflict_count": sum(1 for t in trades if t.conflict),
            "by_year": _breakdown(trades, "year"),
            "by_session": _breakdown(trades, "session"),
            "by_atr_bucket": _breakdown(trades, "atr_bucket"),
        }
        scenario_results.append(result)
        _write_jsonl(OUTPUT_DIR / f"{scenario.code}_trades.jsonl", trades)

    payload = {
        "status": "RESEARCH_ONLY_NO_LIVE_LOGIC_CHANGE",
        "frozen_candidate": "displacement_plus_wick_v1",
        "source_trades": str(SOURCE_TRADES),
        "classification": _classification(scenario_results),
        "results": scenario_results,
    }
    (OUTPUT_DIR / "displacement_plus_wick_stress_test.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (OUTPUT_DIR / "displacement_plus_wick_stress_test.md").write_text(_main_report(payload), encoding="utf-8")
    (OUTPUT_DIR / "execution_fragility_report.md").write_text(_fragility_report(payload), encoding="utf-8")
    (OUTPUT_DIR / "cost_sensitivity_matrix.md").write_text(_cost_matrix(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "classification": payload["classification"],
                "report": str((OUTPUT_DIR / "displacement_plus_wick_stress_test.md").resolve()),
                "matrix": str((OUTPUT_DIR / "cost_sensitivity_matrix.md").resolve()),
                "fragility": str((OUTPUT_DIR / "execution_fragility_report.md").resolve()),
                "summary": {
                    item["scenario"]["code"]: {
                        "pf": item["metrics"]["profit_factor"],
                        "expectancy_R": item["metrics"]["expectancy_R"],
                        "dd_R": item["metrics"]["max_drawdown_R"],
                        "edge": item["edge_survival"],
                    }
                    for item in scenario_results
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
