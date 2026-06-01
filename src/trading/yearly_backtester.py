"""Annual capital-based backtesting for approved strategies."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.logging import get_logger
from src.trading.approved_strategy_loader import load_ob_rejection_short_trailing_atr_v3
from src.trading.blueprint_backtester import BlueprintBacktester, Candle, Trade

logger = get_logger(__name__)


@dataclass(slots=True)
class RealizedTrade:
    trade: Trade
    risk_percent: float
    risk_amount_usd: float
    pnl_usd: float
    balance_after: float
    drawdown_usd: float
    drawdown_percent: float


class YearlyBacktester:
    """Run approved strategy annual backtests with capital simulation."""

    def __init__(self, *, input_dir: Path, yearly_dir: Path, strategies_dir: Path) -> None:
        self.input_dir = input_dir
        self.yearly_dir = yearly_dir
        self.strategies_dir = strategies_dir
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.yearly_dir.mkdir(parents=True, exist_ok=True)
        self.backtester = BlueprintBacktester(
            input_dir=self.input_dir,
            results_dir=self.yearly_dir / "_results_cache",
            reports_dir=self.yearly_dir / "_reports_cache",
        )

    def evaluate(self, *, settings, symbol: str, year: int, initial_capital: float, spec=None) -> dict:
        spec = spec or load_ob_rejection_short_trailing_atr_v3(settings, symbol)
        snapshot = self._load_year_snapshot(spec=spec, symbol=symbol, year=year)
        trades = self._simulate_year_trades(spec=spec, symbol=symbol, snapshot=snapshot)
        trades.sort(key=lambda item: (item.entry_time, item.exit_time, item.entry_timeframe))
        coverage = self._coverage_summary(spec=spec, snapshot=snapshot, year=year)
        simulations = {}
        for risk_percent in (0.5, 1.0):
            realized = self._realize_trades(trades=trades, initial_capital=initial_capital, risk_percent=risk_percent)
            monthly = self._monthly_report(realized=realized, year=year, initial_capital=initial_capital)
            annual = self._annual_summary(
                realized=realized,
                monthly=monthly,
                initial_capital=initial_capital,
                risk_percent=risk_percent,
                year=year,
                symbol=symbol,
                strategy_name=spec.strategy_name,
            )
            simulations[str(risk_percent)] = {
                "risk_percent": risk_percent,
                "monthly": monthly,
                "annual": annual,
            }
        summary_payload = {
            "strategy_name": spec.strategy_name,
            "symbol": symbol,
            "year": year,
            "initial_capital": initial_capital,
            "input_files": snapshot["input_files"],
            "coverage": coverage,
            "simulations": simulations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return summary_payload

    def run(self, *, settings, symbol: str, year: int, initial_capital: float, spec=None) -> dict:
        summary_payload = self.evaluate(
            settings=settings,
            symbol=symbol,
            year=year,
            initial_capital=initial_capital,
            spec=spec,
        )
        summary_path = self.yearly_dir / f"{year}_summary.json"
        monthly_path = self.yearly_dir / f"{year}_monthly_report.csv"
        report_path = self.yearly_dir / f"{year}_report.md"
        summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_monthly_csv(monthly_path, summary_payload["simulations"])
        report_path.write_text(self._report_markdown(summary_payload), encoding="utf-8")
        comparison_path = self._write_comparison_if_possible()
        logger.info(
            "Annual backtest completed strategy=%s symbol=%s year=%s trades=%s",
            summary_payload["strategy_name"],
            symbol,
            year,
            summary_payload["simulations"]["0.5"]["annual"]["total_trades"],
        )
        return {
            "strategy_name": summary_payload["strategy_name"],
            "symbol": symbol,
            "year": year,
            "initial_capital": initial_capital,
            "simulations": {key: value["annual"] for key, value in summary_payload["simulations"].items()},
            "coverage": summary_payload["coverage"],
            "summary_path": str(summary_path.resolve()),
            "monthly_report_path": str(monthly_path.resolve()),
            "report_path": str(report_path.resolve()),
            "comparison_path": str(comparison_path.resolve()) if comparison_path else None,
        }

    def _load_year_snapshot(self, *, spec, symbol: str, year: int) -> dict:
        context_tf = spec.context_timeframe[0] if spec.context_timeframe else "H1"
        entry_tfs = set(spec.entry_timeframe)
        timeframes = {}
        candles = {}
        for timeframe in ("M1", "M5", "H1"):
            path = self.input_dir / f"{symbol}_{timeframe}_{year}.csv"
            if not path.exists():
                raise FileNotFoundError(f"Missing yearly OHLCV file: {path}")
            loaded = [candle for candle in self.backtester._load_candles(path) if candle.time.year == year]
            if timeframe == context_tf and not loaded:
                raise RuntimeError(f"Yearly context OHLCV file is empty inside requested year: {path}")
            if timeframe in entry_tfs and not loaded:
                logger.warning("Yearly entry timeframe has no rows inside requested year symbol=%s timeframe=%s", symbol, timeframe)
            candles[timeframe] = loaded
            timeframes[timeframe] = {
                "path": str(path.resolve()),
                "rows": len(loaded),
                "first_bar_time": loaded[0].time.isoformat() if loaded else None,
                "last_bar_time": loaded[-1].time.isoformat() if loaded else None,
            }
        if not any(candles.get(timeframe) for timeframe in entry_tfs):
            raise RuntimeError(f"No entry timeframe OHLCV rows available inside year {year} for symbol {symbol}.")
        return {"candles": candles, "input_files": timeframes}

    def _simulate_year_trades(self, *, spec, symbol: str, snapshot: dict) -> list[Trade]:
        context_tf = spec.context_timeframe[0] if spec.context_timeframe else "H1"
        context_candles = snapshot["candles"].get(context_tf)
        if not context_candles:
            raise RuntimeError(f"Missing context timeframe candles for {context_tf}.")
        trades: list[Trade] = []
        seen_ids: set[str] = set()
        for entry_tf in spec.entry_timeframe:
            entry_candles = snapshot["candles"].get(entry_tf)
            if not entry_candles:
                continue
            timeframe_trades = self.backtester._simulate_symbol(
                spec=spec,
                symbol=symbol,
                entry_tf=entry_tf,
                entry_candles=entry_candles,
                context_tf=context_tf,
                context_candles=context_candles,
                window_start=None,
                window_end=None,
            )
            for trade in timeframe_trades:
                trade_id = f"{trade.symbol}|{trade.entry_time.isoformat()}|{trade.direction}|{trade.entry_timeframe}|{trade.entry_reason}"
                if trade_id in seen_ids:
                    continue
                seen_ids.add(trade_id)
                trades.append(trade)
        return trades

    @staticmethod
    def _realize_trades(*, trades: list[Trade], initial_capital: float, risk_percent: float) -> list[RealizedTrade]:
        balance = initial_capital
        peak_balance = initial_capital
        realized: list[RealizedTrade] = []
        for trade in trades:
            risk_amount = balance * (risk_percent / 100.0)
            pnl_usd = risk_amount * trade.pnl_r
            balance += pnl_usd
            peak_balance = max(peak_balance, balance)
            drawdown_usd = max(0.0, peak_balance - balance)
            drawdown_percent = (drawdown_usd / peak_balance * 100.0) if peak_balance else 0.0
            realized.append(
                RealizedTrade(
                    trade=trade,
                    risk_percent=risk_percent,
                    risk_amount_usd=round(risk_amount, 4),
                    pnl_usd=round(pnl_usd, 4),
                    balance_after=round(balance, 4),
                    drawdown_usd=round(drawdown_usd, 4),
                    drawdown_percent=round(drawdown_percent, 4),
                )
            )
        return realized

    def _monthly_report(self, *, realized: list[RealizedTrade], year: int, initial_capital: float) -> list[dict]:
        months = [f"{year}-{month:02d}" for month in range(1, 13)]
        grouped: dict[str, list[RealizedTrade]] = {month: [] for month in months}
        for item in realized:
            month_key = item.trade.exit_time.strftime("%Y-%m")
            if month_key in grouped:
                grouped[month_key].append(item)
        rows: list[dict] = []
        running_balance = initial_capital
        for month_key in months:
            items = grouped[month_key]
            wins = [item for item in items if item.pnl_usd > 0]
            losses = [item for item in items if item.pnl_usd < 0]
            gross_profit = sum(item.pnl_usd for item in wins)
            gross_loss = abs(sum(item.pnl_usd for item in losses))
            net_profit = round(sum(item.pnl_usd for item in items), 4)
            ending_balance = round(running_balance + net_profit, 4)
            equity = running_balance
            peak = running_balance
            max_drawdown_usd = 0.0
            losing_streak = 0
            current_losing_streak = 0
            expectancy_r = round(sum(item.trade.pnl_r for item in items) / len(items), 4) if items else 0.0
            for item in items:
                equity += item.pnl_usd
                peak = max(peak, equity)
                max_drawdown_usd = max(max_drawdown_usd, peak - equity)
                if item.pnl_usd < 0:
                    current_losing_streak += 1
                    losing_streak = max(losing_streak, current_losing_streak)
                else:
                    current_losing_streak = 0
            row = {
                "month": month_key,
                "trades": len(items),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round((len(wins) / len(items) * 100.0), 2) if items else 0.0,
                "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4) if items else 0.0,
                "expectancy": round(net_profit / len(items), 4) if items else 0.0,
                "expectancy_r": expectancy_r,
                "net_profit_usd": net_profit,
                "ending_balance": ending_balance,
                "max_drawdown_usd": round(max_drawdown_usd, 4),
                "max_drawdown_percent": round((max_drawdown_usd / max(running_balance, 0.0001) * 100.0), 4) if items else 0.0,
                "losing_streak": losing_streak,
                "negative_month": net_profit < 0,
            }
            rows.append(row)
            running_balance = ending_balance
        return rows

    def _annual_summary(
        self,
        *,
        realized: list[RealizedTrade],
        monthly: list[dict],
        initial_capital: float,
        risk_percent: float,
        year: int,
        symbol: str,
        strategy_name: str,
    ) -> dict:
        total_trades = len(realized)
        wins = [item for item in realized if item.pnl_usd > 0]
        losses = [item for item in realized if item.pnl_usd < 0]
        gross_profit = sum(item.pnl_usd for item in wins)
        gross_loss = abs(sum(item.pnl_usd for item in losses))
        ending_balance = round(realized[-1].balance_after, 4) if realized else round(initial_capital, 4)
        total_profit = round(ending_balance - initial_capital, 4)
        max_drawdown_usd = max((item.drawdown_usd for item in realized), default=0.0)
        max_drawdown_percent = max((item.drawdown_percent for item in realized), default=0.0)
        best_month = max(monthly, key=lambda item: item["net_profit_usd"]) if monthly else None
        worst_month = min(monthly, key=lambda item: item["net_profit_usd"]) if monthly else None
        consecutive_negative_months = self._max_negative_streak(monthly)
        losing_streak = self._max_losing_streak(realized)
        return {
            "strategy_name": strategy_name,
            "symbol": symbol,
            "year": year,
            "risk_percent": risk_percent,
            "initial_capital": initial_capital,
            "ending_balance": ending_balance,
            "total_profit_usd": total_profit,
            "total_return_percent": round((total_profit / initial_capital) * 100.0, 4) if initial_capital else 0.0,
            "total_trades": total_trades,
            "win_rate": round((len(wins) / total_trades) * 100.0, 2) if total_trades else 0.0,
            "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4) if total_trades else 0.0,
            "expectancy": round(total_profit / total_trades, 4) if total_trades else 0.0,
            "expectancy_r": round(sum(item.trade.pnl_r for item in realized) / total_trades, 4) if total_trades else 0.0,
            "max_drawdown_usd": round(max_drawdown_usd, 4),
            "max_drawdown_percent": round(max_drawdown_percent, 4),
            "best_month": {
                "month": best_month["month"],
                "net_profit_usd": best_month["net_profit_usd"],
                "profit_factor": best_month["profit_factor"],
            } if best_month else None,
            "worst_month": {
                "month": worst_month["month"],
                "net_profit_usd": worst_month["net_profit_usd"],
                "profit_factor": worst_month["profit_factor"],
            } if worst_month else None,
            "consecutive_negative_months": consecutive_negative_months,
            "losing_streak": losing_streak,
            "profitable_year": ending_balance > initial_capital,
        }

    @staticmethod
    def _max_negative_streak(monthly: list[dict]) -> int:
        max_streak = 0
        current = 0
        for row in monthly:
            if row["negative_month"]:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def _max_losing_streak(realized: list[RealizedTrade]) -> int:
        max_streak = 0
        current = 0
        for item in realized:
            if item.pnl_usd < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    def _write_monthly_csv(self, path: Path, simulations: dict) -> None:
        fields = [
            "risk_percent",
            "month",
            "trades",
            "wins",
            "losses",
            "win_rate",
            "profit_factor",
            "expectancy",
            "expectancy_r",
            "net_profit_usd",
            "ending_balance",
            "max_drawdown_usd",
            "max_drawdown_percent",
            "losing_streak",
            "negative_month",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for risk_key in sorted(simulations, key=float):
                for row in simulations[risk_key]["monthly"]:
                    writer.writerow({"risk_percent": risk_key, **row})

    def _report_markdown(self, payload: dict) -> str:
        lines = [
            f"# Yearly Backtest Report - {payload['strategy_name']}",
            "",
            f"- symbol: {payload['symbol']}",
            f"- year: {payload['year']}",
            f"- initial_capital: {payload['initial_capital']}",
            "",
            "## Data Coverage",
        ]
        for timeframe, details in payload["coverage"]["timeframes"].items():
            lines.append(
                f"- {timeframe}: rows={details['rows']} first={details['first_bar_time']} last={details['last_bar_time']} complete={details['complete_for_year']}"
            )
        if payload["coverage"]["warnings"]:
            lines.extend(["", "### Coverage Warnings"])
            for item in payload["coverage"]["warnings"]:
                lines.append(f"- {item}")
        lines.append("")
        for risk_key in sorted(payload["simulations"], key=float):
            annual = payload["simulations"][risk_key]["annual"]
            lines.extend(
                [
                    f"## Risk {risk_key}%",
                    f"- ending_balance: {annual['ending_balance']}",
                    f"- total_profit_usd: {annual['total_profit_usd']}",
                    f"- total_return_percent: {annual['total_return_percent']}",
                    f"- total_trades: {annual['total_trades']}",
                    f"- win_rate: {annual['win_rate']}",
                    f"- profit_factor: {annual['profit_factor']}",
                    f"- expectancy: {annual['expectancy']}",
                    f"- max_drawdown_percent: {annual['max_drawdown_percent']}",
                    f"- losing_streak: {annual['losing_streak']}",
                    "",
                ]
            )
        return "\n".join(lines) + "\n"

    def _write_comparison_if_possible(self) -> Path | None:
        summary_2024 = self.yearly_dir / "2024_summary.json"
        summary_2025 = self.yearly_dir / "2025_summary.json"
        if not summary_2024.exists() or not summary_2025.exists():
            return None
        payload_2024 = json.loads(summary_2024.read_text(encoding="utf-8"))
        payload_2025 = json.loads(summary_2025.read_text(encoding="utf-8"))
        comparison_path = self.yearly_dir / "comparison_2024_2025.md"
        lines = [
            "# Comparison 2024 vs 2025",
            "",
            f"- strategy: {payload_2024['strategy_name']}",
            f"- symbol: {payload_2024['symbol']}",
            "",
        ]
        for risk_key in sorted(set(payload_2024["simulations"]).intersection(payload_2025["simulations"]), key=float):
            annual_2024 = payload_2024["simulations"][risk_key]["annual"]
            annual_2025 = payload_2025["simulations"][risk_key]["annual"]
            lines.extend(
                [
                    f"## Risk {risk_key}%",
                    f"- 2024 ending_balance: {annual_2024['ending_balance']}",
                    f"- 2025 ending_balance: {annual_2025['ending_balance']}",
                    f"- 2024 profit_factor: {annual_2024['profit_factor']}",
                    f"- 2025 profit_factor: {annual_2025['profit_factor']}",
                    f"- 2024 win_rate: {annual_2024['win_rate']}",
                    f"- 2025 win_rate: {annual_2025['win_rate']}",
                    f"- 2024 max_drawdown_percent: {annual_2024['max_drawdown_percent']}",
                    f"- 2025 max_drawdown_percent: {annual_2025['max_drawdown_percent']}",
                    "",
                ]
            )
        if payload_2024.get("coverage", {}).get("warnings"):
            lines.extend(["## Coverage Note 2024"])
            lines.extend(f"- {warning}" for warning in payload_2024["coverage"]["warnings"])
            lines.append("")
        if payload_2025.get("coverage", {}).get("warnings"):
            lines.extend(["## Coverage Note 2025"])
            lines.extend(f"- {warning}" for warning in payload_2025["coverage"]["warnings"])
            lines.append("")
        comparison_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return comparison_path

    @staticmethod
    def _coverage_summary(*, spec, snapshot: dict, year: int) -> dict:
        start_expected = datetime(year, 1, 1, tzinfo=timezone.utc)
        end_expected = datetime(year, 12, 31, 23, 59, tzinfo=timezone.utc)
        start_tolerance = timedelta(days=10)
        end_tolerance = timedelta(days=10)
        warnings: list[str] = []
        summary: dict[str, dict] = {}
        context_tf = spec.context_timeframe[0] if spec.context_timeframe else "H1"
        entry_tfs = set(spec.entry_timeframe)
        for timeframe, details in snapshot["input_files"].items():
            first_time = BlueprintBacktester._parse_time(details["first_bar_time"]) if details["first_bar_time"] else None
            last_time = BlueprintBacktester._parse_time(details["last_bar_time"]) if details["last_bar_time"] else None
            complete = bool(
                details["rows"]
                and first_time is not None
                and last_time is not None
                and first_time <= start_expected + start_tolerance
                and last_time >= end_expected - end_tolerance
            )
            summary[timeframe] = {**details, "complete_for_year": complete}
            if timeframe == context_tf and not complete:
                warnings.append(
                    f"Context timeframe {timeframe} does not cover the full year. First={details['first_bar_time']} Last={details['last_bar_time']}."
                )
            if timeframe in entry_tfs and details["rows"] == 0:
                warnings.append(f"Entry timeframe {timeframe} has no rows for {year}; annual test falls back to the remaining entry timeframe(s).")
            elif timeframe in entry_tfs and not complete:
                warnings.append(
                    f"Entry timeframe {timeframe} does not cover the full year. First={details['first_bar_time']} Last={details['last_bar_time']}."
                )
        return {"timeframes": summary, "warnings": warnings}
