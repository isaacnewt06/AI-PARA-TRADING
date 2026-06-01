"""Spread/session execution audit for XAUUSDm demo environments.

This research tool only measures execution conditions. It does not create
signals, entries, orders or management actions.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.core.config import Settings
from src.trading.controlled_demo_survival_protocol import ControlledDemoSurvivalProtocolV1
from src.trading.maximo_quant_v4_market_intelligence import MaximoQuantV4MarketIntelligenceEngine
from src.trading.mt5_bridge import MT5Bridge

NY_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class SpreadSessionAuditPaths:
    jsonl: Path
    csv: Path
    report_md: Path
    latest_json: Path


class SpreadSessionAudit:
    """Measure whether a broker environment can support micro-scalping."""

    NAME = "SPREAD_SESSION_AUDIT"
    SPREAD_STRICT = 0.15
    SPREAD_RELAXED = 0.20

    def __init__(
        self,
        settings: Settings,
        *,
        bridge: MT5Bridge | None = None,
        intelligence_engine: MaximoQuantV4MarketIntelligenceEngine | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.bridge = bridge or MT5Bridge(settings)
        self.intelligence_engine = intelligence_engine or MaximoQuantV4MarketIntelligenceEngine(
            settings,
            bridge=self.bridge,
        )
        self.protocol = ControlledDemoSurvivalProtocolV1()
        self.output_dir = output_dir or self.settings.paths.data_dir / "demo_trading" / "spread_session_audit"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        symbol: str,
        duration_minutes: float = 240.0,
        poll_seconds: float = 60.0,
        max_samples: int | None = None,
        run_label: str = "manual",
    ) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in run_label)
        stem = f"{symbol}_{started.strftime('%Y%m%d_%H%M%S')}_{safe_label}"
        paths = SpreadSessionAuditPaths(
            jsonl=self.output_dir / f"{stem}.jsonl",
            csv=self.output_dir / f"{stem}.csv",
            report_md=self.output_dir / f"{stem}.md",
            latest_json=self.output_dir / "latest_spread_session_audit.json",
        )
        deadline = time.monotonic() + max(0.0, duration_minutes * 60.0)
        collected: list[dict[str, Any]] = []
        sample_limit = max_samples if max_samples is not None else max(1, int((duration_minutes * 60.0) / poll_seconds))
        while len(collected) < sample_limit and time.monotonic() <= deadline:
            sample = self.collect_sample(symbol=symbol)
            collected.append(sample)
            self.append_sample(paths=paths, sample=sample)
            if len(collected) >= sample_limit or time.monotonic() >= deadline:
                break
            time.sleep(max(1.0, poll_seconds))
        summary = self.write_report(paths=paths, samples=self.read_samples(paths.jsonl))
        return {
            "audit_name": self.NAME,
            "symbol": symbol,
            "run_label": run_label,
            "started_at_utc": started.isoformat(),
            "samples_collected": len(collected),
            "duration_minutes_requested": duration_minutes,
            "poll_seconds": poll_seconds,
            "summary": summary,
            "paths": {
                "jsonl": str(paths.jsonl.resolve()),
                "csv": str(paths.csv.resolve()),
                "report_md": str(paths.report_md.resolve()),
                "latest_json": str(paths.latest_json.resolve()),
            },
        }

    def collect_sample(self, *, symbol: str) -> dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        now_ny = now_utc.astimezone(NY_TZ)
        rd_tz = ZoneInfo(self.settings.market_reference_timezone)
        now_rd = now_utc.astimezone(rd_tz)
        execution_environment = self.bridge.read_execution_environment(symbol=symbol)
        intelligence = self.intelligence_engine.run_detailed(symbol=symbol)
        market_state = intelligence["overview"]["market_state"]
        event_risk = intelligence["event_risk"]
        atr_ratio = self._float_or_none(market_state.get("atr_ratio"))
        atr_regime = self.protocol._atr_regime(atr_ratio)
        market_hour_ny = self._int_or_none(market_state.get("hour_ny"))
        hour_ny = now_ny.hour
        session = self.protocol._session_label(hour_ny)
        spread = self._float_or_none(execution_environment.get("live_spread"))
        latency = self._float_or_none(execution_environment.get("live_latency"))
        slippage = self._float_or_none(execution_environment.get("slippage_estimated"))
        return {
            "timestamp_utc": now_utc.isoformat(),
            "timestamp_ny": now_ny.isoformat(),
            "timestamp_rd": now_rd.isoformat(),
            "symbol": symbol,
            "hour_ny": hour_ny,
            "hour_rd": now_rd.hour,
            "market_hour_ny": market_hour_ny,
            "session": session,
            "spread": spread,
            "spread_lte_0_15": spread is not None and spread <= self.SPREAD_STRICT,
            "spread_lte_0_20": spread is not None and spread <= self.SPREAD_RELAXED,
            "latency": latency,
            "slippage_estimated": slippage,
            "execution_environment": execution_environment.get("execution_viability"),
            "atr_ratio": atr_ratio,
            "atr_regime": atr_regime,
            "macro_status": event_risk.get("action"),
            "highest_active_impact": event_risk.get("highest_active_impact"),
            "highest_upcoming_impact": event_risk.get("highest_upcoming_impact"),
            "market_regime": market_state.get("market_regime"),
            "volatility_state": intelligence.get("volatility_intelligence", {}).get("state"),
        }

    def append_sample(self, *, paths: SpreadSessionAuditPaths, sample: dict[str, Any]) -> None:
        with paths.jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
        csv_exists = paths.csv.exists()
        with paths.csv.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(sample.keys()))
            if not csv_exists:
                writer.writeheader()
            writer.writerow(sample)

    def read_samples(self, jsonl_path: Path) -> list[dict[str, Any]]:
        if not jsonl_path.exists():
            return []
        samples: list[dict[str, Any]] = []
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    samples.append(parsed)
        return samples

    def summarize(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        spreads = [float(row["spread"]) for row in samples if isinstance(row.get("spread"), (int, float))]
        latencies = [float(row["latency"]) for row in samples if isinstance(row.get("latency"), (int, float))]
        slippages = [
            float(row["slippage_estimated"])
            for row in samples
            if isinstance(row.get("slippage_estimated"), (int, float))
        ]
        pct_015 = self._pct(sum(1 for value in spreads if value <= self.SPREAD_STRICT), len(spreads))
        pct_020 = self._pct(sum(1 for value in spreads if value <= self.SPREAD_RELAXED), len(spreads))
        by_session = self._group(samples, "session")
        by_hour_ny = self._group(samples, "hour_ny")
        by_atr_regime = self._group(samples, "atr_regime")
        by_macro = self._group(samples, "macro_status")
        summary = {
            "samples": len(samples),
            "spread_min": round(min(spreads), 5) if spreads else None,
            "spread_max": round(max(spreads), 5) if spreads else None,
            "spread_avg": round(sum(spreads) / len(spreads), 5) if spreads else None,
            "latency_avg": round(sum(latencies) / len(latencies), 5) if latencies else None,
            "latency_max": round(max(latencies), 5) if latencies else None,
            "slippage_estimated_avg": round(sum(slippages) / len(slippages), 5) if slippages else None,
            "pct_time_spread_lte_0_15": pct_015,
            "pct_time_spread_lte_0_20": pct_020,
            "by_session": by_session,
            "by_hour_ny": by_hour_ny,
            "by_atr_regime": by_atr_regime,
            "by_macro_status": by_macro,
            "best_execution_windows": self._rank_windows(by_hour_ny, reverse=True),
            "worst_execution_windows": self._rank_windows(by_hour_ny, reverse=False),
        }
        summary["conclusion"] = self._conclusion(summary)
        return summary

    def write_report(self, *, paths: SpreadSessionAuditPaths, samples: list[dict[str, Any]]) -> dict[str, Any]:
        summary = self.summarize(samples)
        latest = {
            "audit_name": self.NAME,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "paths": {
                "jsonl": str(paths.jsonl.resolve()),
                "csv": str(paths.csv.resolve()),
                "report_md": str(paths.report_md.resolve()),
            },
        }
        paths.latest_json.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# SPREAD_SESSION_AUDIT",
            "",
            f"- generated_at_utc: {latest['generated_at_utc']}",
            f"- samples: {summary['samples']}",
            f"- spread_min: {summary['spread_min']}",
            f"- spread_max: {summary['spread_max']}",
            f"- spread_avg: {summary['spread_avg']}",
            f"- latency_avg: {summary['latency_avg']}",
            f"- latency_max: {summary['latency_max']}",
            f"- slippage_estimated_avg: {summary['slippage_estimated_avg']}",
            f"- pct_time_spread_lte_0_15: {summary['pct_time_spread_lte_0_15']}%",
            f"- pct_time_spread_lte_0_20: {summary['pct_time_spread_lte_0_20']}%",
            "",
            "## By Session",
            self._markdown_table(summary["by_session"]),
            "",
            "## By NY Hour",
            self._markdown_table(summary["by_hour_ny"]),
            "",
            "## By ATR Regime",
            self._markdown_table(summary["by_atr_regime"]),
            "",
            "## By Macro Status",
            self._markdown_table(summary["by_macro_status"]),
            "",
            "## Best Execution Windows",
            self._markdown_window_list(summary["best_execution_windows"]),
            "",
            "## Worst Execution Windows",
            self._markdown_window_list(summary["worst_execution_windows"]),
            "",
            "## Conclusion",
            f"- {summary['conclusion']}",
            "",
        ]
        paths.report_md.write_text("\n".join(lines), encoding="utf-8")
        return summary

    def _group(self, samples: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in samples:
            bucket = str(row.get(key) if row.get(key) is not None else "unknown")
            grouped.setdefault(bucket, []).append(row)
        result: dict[str, dict[str, Any]] = {}
        for bucket, rows in grouped.items():
            spreads = [float(row["spread"]) for row in rows if isinstance(row.get("spread"), (int, float))]
            safe_env = sum(1 for row in rows if str(row.get("execution_environment")).upper() == "SAFE")
            result[bucket] = {
                "samples": len(rows),
                "spread_avg": round(sum(spreads) / len(spreads), 5) if spreads else None,
                "spread_min": round(min(spreads), 5) if spreads else None,
                "spread_max": round(max(spreads), 5) if spreads else None,
                "pct_spread_lte_0_15": self._pct(
                    sum(1 for value in spreads if value <= self.SPREAD_STRICT),
                    len(spreads),
                ),
                "pct_spread_lte_0_20": self._pct(
                    sum(1 for value in spreads if value <= self.SPREAD_RELAXED),
                    len(spreads),
                ),
                "pct_execution_safe": self._pct(safe_env, len(rows)),
            }
        return dict(sorted(result.items(), key=lambda item: item[0]))

    def _rank_windows(self, grouped: dict[str, dict[str, Any]], *, reverse: bool) -> list[dict[str, Any]]:
        rows = [
            {"window": key, **value}
            for key, value in grouped.items()
            if value.get("spread_avg") is not None and value.get("samples", 0) > 0
        ]
        return sorted(
            rows,
            key=lambda item: (
                float(item.get("pct_spread_lte_0_15") or 0.0),
                -float(item.get("spread_avg") or 999.0),
                float(item.get("pct_execution_safe") or 0.0),
            ),
            reverse=reverse,
        )[:5]

    def _conclusion(self, summary: dict[str, Any]) -> str:
        samples = int(summary.get("samples") or 0)
        pct_015 = float(summary.get("pct_time_spread_lte_0_15") or 0.0)
        pct_020 = float(summary.get("pct_time_spread_lte_0_20") or 0.0)
        spread_avg = summary.get("spread_avg")
        best_session_pct = max(
            (float(item.get("pct_spread_lte_0_15") or 0.0) for item in summary.get("by_session", {}).values()),
            default=0.0,
        )
        if samples >= 30 and pct_015 >= 70.0 and spread_avg is not None and float(spread_avg) <= self.SPREAD_STRICT:
            return "XAUUSDm APTO"
        if pct_020 >= 50.0 or best_session_pct >= 50.0:
            return "XAUUSDm APTO SOLO EN VENTANAS ESPECÍFICAS"
        if spread_avg is not None and (float(spread_avg) > self.SPREAD_RELAXED or pct_020 < 30.0):
            return "XAUUSDm NO APTO PARA SCALPING MICRO EN ESTA CUENTA"
        return "NECESITA OTRO SÍMBOLO / OTRO TIPO DE CUENTA"

    @staticmethod
    def _markdown_table(rows: dict[str, dict[str, Any]]) -> str:
        if not rows:
            return "No samples yet."
        lines = [
            "| Bucket | Samples | Avg Spread | Min | Max | <=0.15 | <=0.20 | SAFE |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for bucket, metrics in rows.items():
            lines.append(
                f"| {bucket} | {metrics['samples']} | {metrics['spread_avg']} | "
                f"{metrics['spread_min']} | {metrics['spread_max']} | "
                f"{metrics['pct_spread_lte_0_15']}% | {metrics['pct_spread_lte_0_20']}% | "
                f"{metrics['pct_execution_safe']}% |"
            )
        return "\n".join(lines)

    @staticmethod
    def _markdown_window_list(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "No samples yet."
        return "\n".join(
            f"- {row['window']}: avg_spread={row['spread_avg']}, <=0.15={row['pct_spread_lte_0_15']}%, "
            f"<=0.20={row['pct_spread_lte_0_20']}%, safe={row['pct_execution_safe']}%"
            for row in rows
        )

    @staticmethod
    def _pct(part: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round((part / total) * 100.0, 2)

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
