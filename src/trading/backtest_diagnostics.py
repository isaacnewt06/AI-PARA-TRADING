"""Post-backtest diagnostics and comparative analysis."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from src.trading.blueprint_backtester import Candle, SESSION_WINDOWS


@dataclass(slots=True)
class TradeDiagnosticRow:
    strategy_name: str
    symbol: str
    direction: str
    ob_detected: bool
    htf_bias: str | None
    rejection_type: str | None
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    take_profit_price: float
    result: str
    pnl_r: float
    rr_target: float
    session_label: str | None
    setup_time: datetime
    context_timeframe: str
    entry_timeframe: str
    weekday: str
    hour_utc: int
    session_bucket: str
    atr_value: float | None
    atr_percentile: float | None
    atr_band: str
    confirmation_range: float | None
    confirmation_range_atr_ratio: float | None
    confirmation_size_band: str
    rr_obtained_band: str
    entry_reason: str | None
    exit_reason: str | None


class OHLCVCache:
    """Load and cache input OHLCV files for diagnostics enrichment."""

    def __init__(self, input_dir: Path) -> None:
        self.input_dir = input_dir
        self._candles: dict[tuple[str, str], list[Candle]] = {}
        self._atr_cache: dict[tuple[str, str], list[float | None]] = {}

    def candles(self, symbol: str, timeframe: str) -> list[Candle]:
        key = (symbol, timeframe)
        if key in self._candles:
            return self._candles[key]
        path = self.input_dir / f"{symbol}_{timeframe}.csv"
        if not path.exists():
            self._candles[key] = []
            return []
        candles: list[Candle] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                raw = row["time"].strip()
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                candles.append(
                    Candle(
                        time=dt,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
        candles.sort(key=lambda item: item.time)
        self._candles[key] = candles
        return candles

    def atr14(self, symbol: str, timeframe: str) -> list[float | None]:
        key = (symbol, timeframe)
        if key in self._atr_cache:
            return self._atr_cache[key]
        candles = self.candles(symbol, timeframe)
        if not candles:
            self._atr_cache[key] = []
            return []
        tr_values: list[float] = []
        prev_close = candles[0].close
        for candle in candles:
            tr = max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close))
            tr_values.append(tr)
            prev_close = candle.close
        result: list[float | None] = [None] * len(candles)
        avg = tr_values[0]
        for index, tr in enumerate(tr_values):
            if index == 0:
                avg = tr
            else:
                avg = ((avg * 13) + tr) / 14
            result[index] = round(avg, 8)
        self._atr_cache[key] = result
        return result

    def find_index(self, symbol: str, timeframe: str, time_value: datetime) -> int | None:
        candles = self.candles(symbol, timeframe)
        for index, candle in enumerate(candles):
            if candle.time == time_value:
                return index
        return None


class BacktestDiagnosticsBuilder:
    """Build strategy-level and comparative diagnostics from backtest outputs."""

    TARGET_STRATEGIES = [
        "OB Rejection Relaxed Validation",
        "OB Rejection Balanced Validation",
        "OB Rejection Balanced v2 RR12",
        "OB Rejection Balanced v2 RR15",
        "OB Rejection Short Only Trailing ATR",
    ]

    def __init__(self, results_dir: Path, reports_dir: Path, input_dir: Path) -> None:
        self.results_dir = results_dir
        self.reports_dir = reports_dir
        self.input_dir = input_dir
        self.ohlcv = OHLCVCache(input_dir)

    def build(self) -> dict:
        results = sorted(self.results_dir.glob("*_results.json"))
        strategies: list[dict] = []
        for result_path in results:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            strategy_name = payload.get("strategy_name")
            if not strategy_name:
                continue
            trades_path = self.results_dir / f"{self._slug(strategy_name)}_trades.csv"
            trade_rows = self._load_trade_rows(trades_path)
            diagnostics = self._strategy_diagnostics(payload, trade_rows)
            strategies.append(diagnostics)

        comparison = self._comparison_summary(strategies)
        report_md = self._markdown_report(strategies, comparison)
        report_path = self.reports_dir / "backtest_diagnostics.md"
        json_path = self.results_dir / "backtest_diagnostics.json"
        report_path.write_text(report_md, encoding="utf-8")
        json_path.write_text(json.dumps({"strategies": strategies, "comparison": comparison}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "strategies_analyzed": len(strategies),
            "report_path": str(report_path.resolve()),
            "json_path": str(json_path.resolve()),
        }

    def _load_trade_rows(self, path: Path) -> list[TradeDiagnosticRow]:
        if not path.exists():
            return []
        rows: list[TradeDiagnosticRow] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                entry_time = self._parse_dt(row["entry_time"])
                setup_time = self._parse_dt(row["setup_time"])
                session_bucket = self._derive_session_bucket(entry_time)
                atr_value = None
                atr_percentile = None
                confirmation_range = None
                confirmation_ratio = None
                entry_reason = row.get("entry_reason") or row.get("entry_profile")
                exit_reason = row.get("exit_reason")
                symbol = row["symbol"]
                timeframe = row["entry_timeframe"]
                index = self.ohlcv.find_index(symbol, timeframe, setup_time)
                if index is not None:
                    candles = self.ohlcv.candles(symbol, timeframe)
                    atr_values = self.ohlcv.atr14(symbol, timeframe)
                    candle = candles[index]
                    atr_value = atr_values[index]
                    confirmation_range = candle.high - candle.low
                    if atr_value:
                        confirmation_ratio = confirmation_range / atr_value
                    atr_percentile = self._atr_percentile(atr_values, index, lookback=100)

                rows.append(
                    TradeDiagnosticRow(
                        strategy_name=row["strategy_name"],
                        symbol=symbol,
                        direction=row["direction"],
                        ob_detected=str(row.get("ob_detected", "true")).lower() == "true",
                        htf_bias=row.get("htf_bias"),
                        rejection_type=row.get("rejection_type"),
                        entry_time=entry_time,
                        exit_time=self._parse_dt(row["exit_time"]),
                        entry_price=float(row["entry_price"]),
                        exit_price=float(row["exit_price"]),
                        stop_price=float(row["stop_price"]),
                        take_profit_price=float(row["take_profit_price"]),
                        result=row["result"],
                        pnl_r=float(row["pnl_r"]),
                        rr_target=float(row["rr_target"]),
                        session_label=row.get("session"),
                        setup_time=setup_time,
                        context_timeframe=row["context_timeframe"],
                        entry_timeframe=timeframe,
                        weekday=entry_time.strftime("%A"),
                        hour_utc=entry_time.hour,
                        session_bucket=session_bucket,
                        atr_value=atr_value,
                        atr_percentile=atr_percentile,
                        atr_band=row.get("atr_band") or self._atr_band(atr_percentile),
                        confirmation_range=confirmation_range,
                        confirmation_range_atr_ratio=confirmation_ratio,
                        confirmation_size_band=row.get("confirmation_band") or self._confirmation_size_band(confirmation_ratio),
                        rr_obtained_band=self._rr_band(float(row["pnl_r"])),
                        entry_reason=entry_reason,
                        exit_reason=exit_reason,
                    )
                )
        return rows

    def _strategy_diagnostics(self, payload: dict, trades: list[TradeDiagnosticRow]) -> dict:
        metrics = payload.get("metrics", {})
        losing_streaks = self._losing_streaks(trades)
        entry_reasons = [row.entry_reason for row in trades if row.entry_reason]
        return {
            "strategy_name": payload.get("strategy_name"),
            "family": payload.get("family"),
            "status": payload.get("status"),
            "metrics": metrics,
            "group_analysis": {
                "by_session": self._group_stats(trades, lambda row: row.session_bucket),
                "by_hour_utc": self._group_stats(trades, lambda row: f"{row.hour_utc:02d}:00"),
                "by_weekday": self._group_stats(trades, lambda row: row.weekday),
                "by_direction": self._group_stats(trades, lambda row: row.direction),
                "by_htf_bias": self._group_stats(trades, lambda row: row.htf_bias or "unknown"),
                "by_rejection_type": self._group_stats(trades, lambda row: row.rejection_type or "unknown"),
                "by_month": self._group_stats(trades, lambda row: row.entry_time.strftime("%Y-%m")),
                "by_entry_timeframe": self._group_stats(trades, lambda row: row.entry_timeframe),
                "by_atr_band": self._group_stats(trades, lambda row: row.atr_band),
                "by_confirmation_size": self._group_stats(trades, lambda row: row.confirmation_size_band),
                "by_rr_obtained": self._group_stats(trades, lambda row: row.rr_obtained_band),
                "by_entry_reason": self._group_stats(
                    trades,
                    lambda row: row.entry_reason or "not_available",
                ),
                "by_exit_reason": self._group_stats(
                    trades,
                    lambda row: row.exit_reason or "not_available",
                ),
            },
            "losing_streaks": {
                "max": max(losing_streaks) if losing_streaks else 0,
                "all": losing_streaks,
            },
            "entry_reason_available": bool(entry_reasons),
            "source_traceability": payload.get("source_traceability", {}),
        }

    @staticmethod
    def _group_stats(trades: list[TradeDiagnosticRow], key_fn) -> list[dict]:
        buckets: dict[str, list[TradeDiagnosticRow]] = {}
        for trade in trades:
            key = key_fn(trade)
            buckets.setdefault(str(key), []).append(trade)
        rows: list[dict] = []
        for key, items in buckets.items():
            wins = [item for item in items if item.pnl_r > 0]
            losses = [item for item in items if item.pnl_r < 0]
            gross_profit = sum(item.pnl_r for item in wins)
            gross_loss = abs(sum(item.pnl_r for item in losses))
            rows.append(
                {
                    "bucket": key,
                    "trades": len(items),
                    "win_rate": round((len(wins) / len(items)) * 100, 2) if items else 0.0,
                    "expectancy": round(sum(item.pnl_r for item in items) / len(items), 4) if items else 0.0,
                    "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4),
                    "avg_rr": round(mean(item.pnl_r for item in items), 4) if items else 0.0,
                }
            )
        return sorted(rows, key=lambda item: (-item["trades"], item["bucket"]))

    def _comparison_summary(self, strategies: list[dict]) -> dict:
        by_name = {item["strategy_name"]: item for item in strategies}
        focus = [by_name[name] for name in self.TARGET_STRATEGIES if name in by_name]
        relaxed = by_name.get("OB Rejection Relaxed Validation")
        why_relaxed = self._why_relaxed(relaxed) if relaxed else {}
        table = [
            {
                "strategy_name": item["strategy_name"],
                "trades": item["metrics"].get("total_trades", 0),
                "win_rate": item["metrics"].get("win_rate", 0.0),
                "profit_factor": item["metrics"].get("profit_factor", 0.0),
                "expectancy": item["metrics"].get("expectancy", 0.0),
                "max_drawdown": item["metrics"].get("max_drawdown", 0.0),
                "losing_streak": item["metrics"].get("losing_streak", 0),
            }
            for item in focus
        ]
        recommendations = self._recommendations(focus, why_relaxed)
        return {
            "focus_strategies": table,
            "why_relaxed": why_relaxed,
            "recommendations": recommendations,
        }

    def _why_relaxed(self, relaxed: dict) -> dict:
        groups = relaxed["group_analysis"]
        return {
            "works": {
                "best_sessions": self._top_positive(groups["by_session"]),
                "best_hours": self._top_positive(groups["by_hour_utc"]),
                "best_directions": self._top_positive(groups["by_direction"]),
                "best_atr_bands": self._top_positive(groups["by_atr_band"]),
                "best_confirmation_sizes": self._top_positive(groups["by_confirmation_size"]),
            },
            "fails": {
                "worst_sessions": self._top_negative(groups["by_session"]),
                "worst_hours": self._top_negative(groups["by_hour_utc"]),
                "worst_directions": self._top_negative(groups["by_direction"]),
                "worst_atr_bands": self._top_negative(groups["by_atr_band"]),
                "worst_confirmation_sizes": self._top_negative(groups["by_confirmation_size"]),
                "losing_streaks": relaxed["losing_streaks"],
            },
        }

    @staticmethod
    def _top_positive(rows: list[dict], min_trades: int = 5, limit: int = 3) -> list[dict]:
        filtered = [row for row in rows if row["trades"] >= min_trades]
        return sorted(filtered, key=lambda item: (-item["expectancy"], -item["profit_factor"], -item["trades"]))[:limit]

    @staticmethod
    def _top_negative(rows: list[dict], min_trades: int = 5, limit: int = 3) -> list[dict]:
        filtered = [row for row in rows if row["trades"] >= min_trades]
        return sorted(filtered, key=lambda item: (item["expectancy"], item["profit_factor"], -item["trades"]))[:limit]

    def _recommendations(self, focus: list[dict], why_relaxed: dict) -> list[str]:
        recommendations: list[str] = []
        relaxed = next((item for item in focus if item["strategy_name"] == "OB Rejection Relaxed Validation"), None)
        balanced = next((item for item in focus if item["strategy_name"] == "OB Rejection Balanced Validation"), None)
        rr12 = next((item for item in focus if item["strategy_name"] == "OB Rejection Balanced v2 RR12"), None)
        rr15 = next((item for item in focus if item["strategy_name"] == "OB Rejection Balanced v2 RR15"), None)
        short_trailing = next((item for item in focus if item["strategy_name"] == "OB Rejection Short Only Trailing ATR"), None)

        if relaxed and balanced:
            if balanced["metrics"]["max_drawdown"] < relaxed["metrics"]["max_drawdown"]:
                recommendations.append(
                    f"Balanced reduces drawdown materially ({balanced['metrics']['max_drawdown']} vs {relaxed['metrics']['max_drawdown']}) but gives up too much edge; keep its session/volatility filters and relax only entry confirmation or target handling."
                )
        if rr12 and balanced:
            if rr12["metrics"]["profit_factor"] < balanced["metrics"]["profit_factor"]:
                recommendations.append(
                    "Balanced v2 RR1.2 did not improve profit factor versus Balanced, so lowering the RR target alone is not enough; the weak point is likely entry quality, not just exit distance."
                )
        if rr15 and rr15["metrics"]["win_rate"] == 0:
            recommendations.append(
                "Balanced v2 RR1.5 is too strict for the current dataset. The combination of ATR band, 2-of-3 confirmation, and retrace-on-large-candle is overfiltering valid follow-through."
            )
        if short_trailing:
            trailing_groups = short_trailing["group_analysis"]
            good_hours = self._top_positive(trailing_groups["by_hour_utc"])
            bad_hours = self._top_negative(trailing_groups["by_hour_utc"])
            if good_hours:
                recommendations.append(
                    f"Short Only Trailing ATR is strongest around {', '.join(item['bucket'] for item in good_hours[:2])}; optimization should stay centered around those UTC hours."
                )
            if bad_hours:
                recommendations.append(
                    f"Short Only Trailing ATR still degrades around {', '.join(item['bucket'] for item in bad_hours[:2])}; keep those hours blocked in focused optimization."
                )

        best_hours = why_relaxed.get("works", {}).get("best_hours", [])
        if best_hours:
            hours = ", ".join(item["bucket"] for item in best_hours[:2])
            recommendations.append(
                f"Relaxed performs best in specific UTC hours ({hours}); test a focused intraday window instead of full any-session coverage."
            )
        worst_atr = why_relaxed.get("fails", {}).get("worst_atr_bands", [])
        if worst_atr:
            bands = ", ".join(item["bucket"] for item in worst_atr[:2])
            recommendations.append(
                f"Relaxed loses disproportionately in ATR regimes {bands}; keep a lower volatility floor and avoid the weakest ATR buckets rather than filtering all medium volatility."
            )
        worst_sizes = why_relaxed.get("fails", {}).get("worst_confirmation_sizes", [])
        if worst_sizes:
            bands = ", ".join(item["bucket"] for item in worst_sizes[:2])
            recommendations.append(
                f"Relaxed struggles with confirmation candle sizes {bands}; keep the large-candle retrace rule, but apply it only to the worst range/ATR buckets."
            )
        return recommendations

    def _markdown_report(self, strategies: list[dict], comparison: dict) -> str:
        lines = ["# Backtest Diagnostics", ""]
        lines.append("## Comparison")
        for item in comparison["focus_strategies"]:
            lines.append(
                f"- {item['strategy_name']}: trades={item['trades']} win_rate={item['win_rate']} profit_factor={item['profit_factor']} max_drawdown={item['max_drawdown']}"
            )
        lines.extend(["", "## Why Relaxed Works / Why Relaxed Fails"])
        relaxed = comparison.get("why_relaxed", {})
        lines.append("")
        lines.append("### Why Relaxed Works")
        for title, rows in relaxed.get("works", {}).items():
            values = ", ".join(
                f"{row['bucket']} (trades={row['trades']}, expectancy={row['expectancy']}, pf={row['profit_factor']})"
                for row in rows
            ) or "No strong positive cluster detected."
            lines.append(f"- {title}: {values}")
        lines.append("")
        lines.append("### Why Relaxed Fails")
        for title, rows in relaxed.get("fails", {}).items():
            if title == "losing_streaks":
                lines.append(f"- losing_streaks: max={rows.get('max', 0)} all={rows.get('all', [])}")
                continue
            values = ", ".join(
                f"{row['bucket']} (trades={row['trades']}, expectancy={row['expectancy']}, pf={row['profit_factor']})"
                for row in rows
            ) or "No persistent weak cluster detected."
            lines.append(f"- {title}: {values}")

        lines.extend(["", "## Strategy Diagnostics"])
        for strategy in strategies:
            lines.extend(["", f"### {strategy['strategy_name']}"])
            metrics = strategy["metrics"]
            lines.append(
                f"- metrics: trades={metrics.get('total_trades', 0)} win_rate={metrics.get('win_rate', 0.0)} profit_factor={metrics.get('profit_factor', 0.0)} expectancy={metrics.get('expectancy', 0.0)} max_drawdown={metrics.get('max_drawdown', 0.0)}"
            )
            for section_name, rows in strategy["group_analysis"].items():
                sample = rows[:5]
                values = ", ".join(
                    f"{row['bucket']} (trades={row['trades']}, expectancy={row['expectancy']}, pf={row['profit_factor']})"
                    for row in sample
                ) or "no data"
                lines.append(f"- {section_name}: {values}")

        lines.extend(["", "## Recommendations"])
        for item in comparison.get("recommendations", []):
            lines.append(f"- {item}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _losing_streaks(trades: list[TradeDiagnosticRow]) -> list[int]:
        streaks: list[int] = []
        current = 0
        for trade in trades:
            if trade.pnl_r < 0:
                current += 1
            elif current:
                streaks.append(current)
                current = 0
        if current:
            streaks.append(current)
        return streaks

    @staticmethod
    def _atr_percentile(atr_values: list[float | None], index: int, lookback: int) -> float | None:
        if index < 0 or index >= len(atr_values):
            return None
        current = atr_values[index]
        if current is None:
            return None
        window = [value for value in atr_values[max(0, index - lookback + 1) : index + 1] if value is not None]
        if len(window) < 20:
            return None
        ordered = sorted(window)
        less_or_equal = sum(1 for value in ordered if value <= current)
        return round((less_or_equal / len(ordered)) * 100, 2)

    @staticmethod
    def _atr_band(percentile: float | None) -> str:
        if percentile is None:
            return "unknown"
        if percentile < 20:
            return "p00_20"
        if percentile < 40:
            return "p20_40"
        if percentile < 60:
            return "p40_60"
        if percentile < 80:
            return "p60_80"
        return "p80_100"

    @staticmethod
    def _confirmation_size_band(ratio: float | None) -> str:
        if ratio is None:
            return "unknown"
        if ratio < 0.8:
            return "small_lt_0.8_atr"
        if ratio < 1.2:
            return "medium_0.8_1.2_atr"
        if ratio < 1.8:
            return "large_1.2_1.8_atr"
        return "extreme_gt_1.8_atr"

    @staticmethod
    def _rr_band(pnl_r: float) -> str:
        if pnl_r < 0:
            return "loss_lt_0r"
        if pnl_r < 1:
            return "flat_0_1r"
        if pnl_r < 2:
            return "win_1_2r"
        return "win_gt_2r"

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _derive_session_bucket(entry_time: datetime) -> str:
        in_london = BacktestDiagnosticsBuilder._is_in_session(entry_time, "london")
        in_new_york = BacktestDiagnosticsBuilder._is_in_session(entry_time, "new_york")
        if in_london and in_new_york:
            return "london_new_york_overlap"
        if in_london:
            return "london"
        if in_new_york:
            return "new_york"
        return "other"

    @staticmethod
    def _is_in_session(entry_time: datetime, session_name: str) -> bool:
        session = SESSION_WINDOWS.get(session_name)
        if session is None:
            return False
        tz, start_hour, end_hour = session
        localized = entry_time.astimezone(tz)
        return start_hour <= localized.hour < end_hour

    @staticmethod
    def _slug(value: str) -> str:
        return (
            value.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace(":", "")
            .replace("|", "_")
        )
