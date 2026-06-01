"""Temporal robustness validation for blueprint backtests."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from src.trading.blueprint_backtester import BlueprintBacktester, Candle, Trade
from src.trading.strategy_schemas import BacktestBlueprintSpec


@dataclass(slots=True)
class ValidationCandidate:
    symbol: str
    timeframe: str
    candles: list[Candle]


class BacktestValidationEngine:
    """Evaluate a spec across temporal windows beyond the default train/test split."""

    def __init__(self, backtester: BlueprintBacktester) -> None:
        self.backtester = backtester

    def validate(self, spec: BacktestBlueprintSpec) -> dict:
        baseline_train = self.backtester.evaluate_spec(spec, split="train", persist=False)
        baseline_test = self.backtester.evaluate_spec(spec, split="test", persist=False)
        baseline_full = self.backtester.evaluate_spec(spec, split="all", persist=False)
        candidate = self._validation_candidate(spec)
        monthly = self._month_by_month(baseline_full["trades"])
        rolling = self._rolling_7030(spec, candidate)
        walk_forward = self._walk_forward(spec, candidate)
        stability_by_hour = self._hour_stability(baseline_full["trades"])
        gates = self._paper_trading_gate(
            train_metrics=baseline_train["metrics"],
            test_metrics=baseline_test["metrics"],
            full_metrics=baseline_full["metrics"],
            monthly=monthly,
            stability_by_hour=stability_by_hour,
        )
        return {
            "train": baseline_train["metrics"],
            "test": baseline_test["metrics"],
            "full": baseline_full["metrics"],
            "month_by_month": monthly,
            "rolling_7030": rolling,
            "walk_forward_blocks": walk_forward,
            "stability_by_hour": stability_by_hour,
            "paper_trading_gate": gates,
        }

    def _validation_candidate(self, spec: BacktestBlueprintSpec) -> ValidationCandidate | None:
        for symbol in spec.symbols_suggested:
            resolved_symbol, timeframe = self.backtester._resolve_entry_timeframe(symbol, spec.entry_timeframe)
            if timeframe is None:
                continue
            candles = self.backtester._load_candles(self.backtester._csv_path(resolved_symbol, timeframe))
            if candles:
                return ValidationCandidate(symbol=resolved_symbol, timeframe=timeframe, candles=candles)
        return None

    def _month_by_month(self, trades: list[Trade]) -> list[dict]:
        grouped: dict[str, list[Trade]] = defaultdict(list)
        for trade in trades:
            grouped[trade.entry_time.strftime("%Y-%m")].append(trade)
        rows: list[dict] = []
        for month_key in sorted(grouped):
            month_trades = grouped[month_key]
            metrics = self.backtester._metrics(month_trades)
            net_pnl_r = round(sum(item.pnl_r for item in month_trades), 4)
            rows.append(
                {
                    "month": month_key,
                    "trades": len(month_trades),
                    "net_pnl_r": net_pnl_r,
                    "profit_factor": metrics["profit_factor"],
                    "expectancy": metrics["expectancy"],
                    "max_drawdown": metrics["max_drawdown"],
                    "losing_streak": metrics["losing_streak"],
                    "negative_month": net_pnl_r < 0,
                }
            )
        return rows

    def _rolling_7030(self, spec: BacktestBlueprintSpec, candidate: ValidationCandidate | None) -> list[dict]:
        if candidate is None or len(candidate.candles) < 120:
            return []
        blocks = self._time_blocks(candidate.candles, block_count=12)
        windows: list[dict] = []
        train_blocks = 7
        test_blocks = 3
        max_start = len(blocks) - (train_blocks + test_blocks) + 1
        for start in range(max(0, max_start)):
            train_start = blocks[start][0]
            train_end = blocks[start + train_blocks - 1][1]
            test_start = blocks[start + train_blocks][0]
            test_end = blocks[start + train_blocks + test_blocks - 1][1]
            train_eval = self.backtester.evaluate_spec(
                spec,
                persist=False,
                window_start=train_start,
                window_end=train_end,
            )
            test_eval = self.backtester.evaluate_spec(
                spec,
                persist=False,
                window_start=test_start,
                window_end=test_end,
            )
            windows.append(
                {
                    "window_index": start + 1,
                    "train_range": [train_start.isoformat(), train_end.isoformat()],
                    "test_range": [test_start.isoformat(), test_end.isoformat()],
                    "train_metrics": train_eval["metrics"],
                    "test_metrics": test_eval["metrics"],
                }
            )
        return windows

    def _walk_forward(self, spec: BacktestBlueprintSpec, candidate: ValidationCandidate | None) -> list[dict]:
        if candidate is None or len(candidate.candles) < 120:
            return []
        blocks = self._time_blocks(candidate.candles, block_count=6)
        windows: list[dict] = []
        for test_block_index in range(2, len(blocks)):
            train_start = blocks[0][0]
            train_end = blocks[test_block_index - 1][1]
            test_start = blocks[test_block_index][0]
            test_end = blocks[test_block_index][1]
            train_eval = self.backtester.evaluate_spec(
                spec,
                persist=False,
                window_start=train_start,
                window_end=train_end,
            )
            test_eval = self.backtester.evaluate_spec(
                spec,
                persist=False,
                window_start=test_start,
                window_end=test_end,
            )
            windows.append(
                {
                    "window_index": len(windows) + 1,
                    "train_range": [train_start.isoformat(), train_end.isoformat()],
                    "test_range": [test_start.isoformat(), test_end.isoformat()],
                    "train_metrics": train_eval["metrics"],
                    "test_metrics": test_eval["metrics"],
                }
            )
        return windows

    def _hour_stability(self, trades: list[Trade]) -> list[dict]:
        grouped: dict[int, list[Trade]] = defaultdict(list)
        total = len(trades) or 1
        for trade in trades:
            if trade.hour_utc is None:
                continue
            grouped[trade.hour_utc].append(trade)
        rows: list[dict] = []
        for hour in sorted(grouped):
            hour_trades = grouped[hour]
            metrics = self.backtester._metrics(hour_trades)
            rows.append(
                {
                    "hour_utc": hour,
                    "trades": len(hour_trades),
                    "trade_share": round(len(hour_trades) / total, 4),
                    "net_pnl_r": round(sum(item.pnl_r for item in hour_trades), 4),
                    "profit_factor": metrics["profit_factor"],
                    "expectancy": metrics["expectancy"],
                }
            )
        return rows

    def _paper_trading_gate(
        self,
        *,
        train_metrics: dict,
        test_metrics: dict,
        full_metrics: dict,
        monthly: list[dict],
        stability_by_hour: list[dict],
    ) -> dict:
        max_negative_streak = self._max_negative_month_streak(monthly)
        top_hour_share = max((item["trade_share"] for item in stability_by_hour), default=0.0)
        positive_hours = sum(1 for item in stability_by_hour if item["trades"] >= 10 and item["expectancy"] > 0)
        checks = {
            "test_profit_factor": test_metrics.get("profit_factor", 0.0) >= 1.20,
            "full_profit_factor": full_metrics.get("profit_factor", 0.0) >= 1.20,
            "full_trades": full_metrics.get("total_trades", 0) >= 100,
            "max_drawdown": max(test_metrics.get("max_drawdown", 999.0), full_metrics.get("max_drawdown", 999.0)) <= 12.0,
            "losing_streak": max(test_metrics.get("losing_streak", 999), full_metrics.get("losing_streak", 999)) <= 8,
            "expectancy": test_metrics.get("expectancy", -1.0) > 0 and full_metrics.get("expectancy", -1.0) > 0,
            "negative_months": max_negative_streak <= 2,
            "hour_dependency": top_hour_share <= 0.60 and positive_hours >= 2,
        }
        return {
            "passes": all(checks.values()),
            "checks": checks,
            "max_negative_months_consecutive": max_negative_streak,
            "top_hour_trade_share": round(top_hour_share, 4),
            "positive_hours_with_sample": positive_hours,
        }

    @staticmethod
    def _time_blocks(candles: list[Candle], *, block_count: int) -> list[tuple[datetime, datetime]]:
        if not candles:
            return []
        block_size = max(1, len(candles) // block_count)
        blocks: list[tuple[datetime, datetime]] = []
        for start in range(0, len(candles), block_size):
            chunk = candles[start : start + block_size]
            if not chunk:
                continue
            blocks.append((chunk[0].time, chunk[-1].time))
        return blocks[:block_count]

    @staticmethod
    def _max_negative_month_streak(monthly: list[dict]) -> int:
        max_streak = 0
        current = 0
        for row in monthly:
            if row["negative_month"]:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak
