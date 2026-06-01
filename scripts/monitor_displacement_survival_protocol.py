"""Dry new-candle monitor for displacement_plus_wick_v1 survival protocol."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import get_settings
from src.trading.maximo_quant_v4_demo_engine import MaximoQuantV4DemoEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--target-unique-candles", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=5000)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--session-label", default="survival_protocol")
    return parser.parse_args()


def latest_closed_m5_candle_time(engine: MaximoQuantV4DemoEngine, symbol: str) -> str | None:
    snapshot = engine.bridge.read_market_snapshot(symbol=symbol, bars_by_timeframe={"M5": 3})
    candles = snapshot.get("candles", {}).get("M5", [])
    if len(candles) >= 2:
        return candles[-2].time.isoformat()
    return snapshot.get("timeframes", {}).get("M5", {}).get("last_bar_time")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def is_displacement_plus_wick_signal(signal: dict[str, Any] | None, protocol: dict[str, Any]) -> bool:
    if protocol.get("applies") is True:
        return True
    if not signal:
        return False
    values = [
        signal.get("signal_type"),
        signal.get("edge_name"),
        signal.get("research_edge"),
        signal.get("strategy_variant"),
        signal.get("active_family"),
    ]
    normalized = " ".join(str(value).lower() for value in values if value is not None)
    return "displacement_plus_wick_v1" in normalized or "reaction_zone_expansion_brain_v1" in normalized


def conclusion(summary: dict[str, Any]) -> str:
    signals = int(summary["displacement_plus_wick_v1_signals"])
    if signals == 0:
        return "NO HAY SEÑALES"
    if int(summary["signals_allowed_by_survival_protocol"]) > 0:
        return "EDGE + AMBIENTE APTO"
    if int(summary["signals_blocked_by_spread"]) >= max(1, signals // 2):
        return "SPREAD DEL BROKER DEMASIADO ALTO"
    if summary.get("live_spread_avg") is not None and float(summary["live_spread_avg"]) > 0.15:
        return "SPREAD DEL BROKER DEMASIADO ALTO"
    return "EDGE VIVO PERO AMBIENTE NO APTO"


def render_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# displacement_plus_wick_v1 Controlled Demo Survival Monitor",
        "",
        f"- generated_at_utc: {datetime.now(timezone.utc).isoformat()}",
        f"- symbol: {summary['symbol']}",
        f"- session_label: {summary['session_label']}",
        f"- velas_M5_unicas: {summary['unique_m5_candles']}",
        f"- repeated_candle_skips: {summary['repeated_candle_skips']}",
        f"- displacement_plus_wick_v1_signals: {summary['displacement_plus_wick_v1_signals']}",
        f"- signals_blocked_by_spread: {summary['signals_blocked_by_spread']}",
        f"- signals_blocked_by_ATR: {summary['signals_blocked_by_atr']}",
        f"- signals_blocked_by_session: {summary['signals_blocked_by_session']}",
        f"- signals_blocked_by_macro: {summary['signals_blocked_by_macro']}",
        f"- signals_allowed_by_survival_protocol: {summary['signals_allowed_by_survival_protocol']}",
        f"- would_pass_to_demo_reduced: {summary['would_pass_to_demo_reduced']}",
        f"- live_spread_avg: {summary['live_spread_avg']}",
        f"- live_spread_min: {summary['live_spread_min']}",
        f"- live_spread_max: {summary['live_spread_max']}",
        f"- latency_avg: {summary['latency_avg']}",
        "",
        "## Execution Viability Distribution",
    ]
    for key, value in sorted(summary["execution_viability_distribution"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Conclusion", f"- {summary['conclusion']}", ""])
    return "\n".join(lines)


def build_summary(state: dict[str, Any], events_path: Path, summary_path: Path) -> dict[str, Any]:
    records = state["records"]
    signal_records = [item for item in records if item["is_displacement_plus_wick_v1"]]
    spreads = [float(item["live_spread"]) for item in records if isinstance(item.get("live_spread"), (int, float))]
    latencies = [float(item["live_latency"]) for item in records if isinstance(item.get("live_latency"), (int, float))]
    viability: dict[str, int] = {}
    for item in records:
        key = str(item.get("execution_viability") or "UNKNOWN")
        viability[key] = viability.get(key, 0) + 1

    summary = {
        "run_id": state["run_id"],
        "symbol": state["symbol"],
        "session_label": state["session_label"],
        "attempts": state["attempts"],
        "unique_m5_candles": state["unique_m5_candles"],
        "target_unique_candles": state["target_unique_candles"],
        "repeated_candle_skips": state["repeated_candle_skips"],
        "displacement_plus_wick_v1_signals": len(signal_records),
        "signals_blocked_by_spread": sum(
            1
            for item in signal_records
            if "spread_above_survival_threshold" in item["protocol_blockers"]
            or "live_spread_unavailable" in item["protocol_blockers"]
        ),
        "signals_blocked_by_atr": sum(1 for item in signal_records if "atr_regime_not_safe" in item["protocol_blockers"]),
        "signals_blocked_by_session": sum(
            1
            for item in signal_records
            if any(
                blocker in item["protocol_blockers"]
                for blocker in ("session_not_validated", "london_blocked", "asia_blocked")
            )
        ),
        "signals_blocked_by_macro": sum(
            1 for item in signal_records if "macro_high_impact_or_watch" in item["protocol_blockers"]
        ),
        "signals_allowed_by_survival_protocol": sum(1 for item in signal_records if item["protocol_allowed"]),
        "would_pass_to_demo_reduced": sum(
            1
            for item in signal_records
            if item["protocol_allowed"] and item.get("protocol_allowed_risk_mode") == "reduced"
        ),
        "live_spread_avg": round(sum(spreads) / len(spreads), 5) if spreads else None,
        "live_spread_min": round(min(spreads), 5) if spreads else None,
        "live_spread_max": round(max(spreads), 5) if spreads else None,
        "latency_avg": round(sum(latencies) / len(latencies), 5) if latencies else None,
        "execution_viability_distribution": viability,
        "events_path": str(events_path.resolve()),
        "summary_path": str(summary_path.resolve()),
    }
    summary["conclusion"] = conclusion(summary)
    return summary


def main() -> None:
    args = parse_args()
    settings = get_settings()
    engine = MaximoQuantV4DemoEngine(settings)
    output_dir = settings.paths.data_dir / "demo_trading" / "maximo_quant_v4"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    events_path = output_dir / f"displacement_survival_monitor_{run_id}.jsonl"
    summary_path = output_dir / f"displacement_survival_monitor_{run_id}_summary.md"
    latest_summary_path = output_dir / "displacement_survival_monitor_latest_summary.md"
    state: dict[str, Any] = {
        "run_id": run_id,
        "symbol": args.symbol,
        "session_label": args.session_label,
        "target_unique_candles": args.target_unique_candles,
        "attempts": 0,
        "unique_m5_candles": 0,
        "repeated_candle_skips": 0,
        "last_candle_time": None,
        "records": [],
    }

    while state["unique_m5_candles"] < args.target_unique_candles and state["attempts"] < args.max_attempts:
        state["attempts"] += 1
        candle_time = latest_closed_m5_candle_time(engine, args.symbol)
        if candle_time is None or candle_time == state["last_candle_time"]:
            if candle_time == state["last_candle_time"]:
                state["repeated_candle_skips"] += 1
            time.sleep(max(0.0, args.poll_seconds))
            continue

        state["last_candle_time"] = candle_time
        state["unique_m5_candles"] += 1
        result = engine.run(symbol=args.symbol, dry_run=True, confirm_demo=False)
        signal = result.get("signal")
        protocol = result.get("controlled_demo_survival_protocol") or {}
        environment = protocol.get("environment", {}) or {}
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": args.symbol,
            "unique_candle_index": state["unique_m5_candles"],
            "candle_time": candle_time,
            "execution_status": result.get("execution_status"),
            "intelligence_action": result.get("intelligence_action"),
            "signal_detected": signal is not None,
            "signal_type": signal.get("signal_type") if signal else None,
            "is_displacement_plus_wick_v1": is_displacement_plus_wick_signal(signal, protocol),
            "protocol_applies": protocol.get("applies"),
            "protocol_allowed": protocol.get("allowed"),
            "protocol_allowed_risk_mode": protocol.get("allowed_risk_mode"),
            "protocol_action": protocol.get("action"),
            "protocol_blockers": protocol.get("blockers", []),
            "live_spread": environment.get("live_spread"),
            "live_latency": environment.get("live_latency"),
            "slippage_estimated": environment.get("slippage_estimated"),
            "atr_regime": environment.get("atr_regime"),
            "atr_ratio": environment.get("atr_ratio"),
            "event_action": environment.get("event_action"),
            "execution_viability": environment.get("execution_viability"),
        }
        state["records"].append(record)
        append_jsonl(events_path, record)
        summary = build_summary(state, events_path, summary_path)
        summary_path.write_text(render_summary(summary), encoding="utf-8")
        latest_summary_path.write_text(render_summary(summary), encoding="utf-8")
        time.sleep(max(0.0, args.poll_seconds))

    summary = build_summary(state, events_path, summary_path)
    summary_path.write_text(render_summary(summary), encoding="utf-8")
    latest_summary_path.write_text(render_summary(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
