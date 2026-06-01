"""Yearly fixed-lot analysis for MAXIMO MTF Quant Institutional v4 candidates."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.logging import get_logger
from src.trading.maximo_quant_v4_backtester import (
    MaximoMTFQuantV4Backtester,
    ClosedTrade,
    StrategyVariant,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class RealizedQuantTrade:
    trade: ClosedTrade
    volume_lots: float
    contract_units: float
    gross_pnl_usd: float
    commission_usd: float
    net_pnl_usd: float
    balance_after: float
    drawdown_usd: float
    drawdown_percent: float


class MaximoQuantV4YearlyAnalyzer:
    """Analyze the best MAXIMO Quant v4 strategy candidate with fixed-lot PnL."""

    DEFAULT_VARIANT = "prime_hours_refined_v46"
    DEFAULT_SESSION = "london_ny_am"
    DEFAULT_TIMEFRAME = "M5"
    CONTRACT_SIZE = 100.0
    COMMISSION_RATE = 0.0001

    def __init__(self, *, input_dir: Path, backtests_dir: Path, strategies_dir: Path) -> None:
        self.input_dir = input_dir
        self.backtests_dir = backtests_dir
        self.strategies_dir = strategies_dir
        self.yearly_dir = backtests_dir / "maximo_mtf_quant_v4" / "yearly"
        self.optimization_results_path = backtests_dir / "yearly" / "optimization_annual_results.json"
        self.yearly_dir.mkdir(parents=True, exist_ok=True)
        self.strategies_dir.mkdir(parents=True, exist_ok=True)
        self.backtester = MaximoMTFQuantV4Backtester(
            input_dir=input_dir,
            output_dir=backtests_dir / "maximo_mtf_quant_v4",
        )

    def run(
        self,
        *,
        symbol: str,
        year: int,
        initial_capital: float,
        volume_lots: float,
        strategy_variant_code: str = DEFAULT_VARIANT,
        session_variant_code: str = DEFAULT_SESSION,
        timeframe: str = DEFAULT_TIMEFRAME,
    ) -> dict:
        resolved = self._resolve_runtime_variant(
            strategy_variant_code=strategy_variant_code,
            session_variant_code=session_variant_code,
        )
        runtime_backtester = resolved["backtester"]
        strategy_variant = resolved["strategy_variant"]
        session_variant = resolved["session_variant"]
        optimizer_config = resolved["optimizer_config"]
        spec = next(
            item
            for item in runtime_backtester._dataset_specs(symbol if symbol.endswith("m") else f"{symbol}m")
            if item["label"] == f"annual_{year}_full_year_{year}" and item["timeframe"] == timeframe
        )
        trades = runtime_backtester._simulate(
            symbol=symbol if symbol.endswith("m") else f"{symbol}m",
            dataset_label=spec["label"],
            timeframe=timeframe,
            entry_candles=spec["entry_candles"],
            context=spec["context"],
            session_variant=session_variant,
            strategy_variant=strategy_variant,
        )
        realized = self._realize_trades(
            trades=trades,
            initial_capital=initial_capital,
            volume_lots=volume_lots,
        )
        daily = self._group_report(realized, period="day", initial_capital=initial_capital)
        weekly = self._group_report(realized, period="week", initial_capital=initial_capital)
        monthly = self._group_report(realized, period="month", initial_capital=initial_capital)
        annual = self._annual_summary(
            realized=realized,
            daily=daily,
            monthly=monthly,
            weekly=weekly,
            initial_capital=initial_capital,
            volume_lots=volume_lots,
            symbol=symbol,
            year=year,
            timeframe=timeframe,
            strategy_variant=strategy_variant,
            session_variant=session_variant.code,
            coverage=spec["coverage"],
        )

        payload = {
            "strategy_name": "MAXIMO MTF Quant Institutional v4",
            "symbol": symbol if symbol.endswith("m") else f"{symbol}m",
            "year": year,
            "initial_capital": initial_capital,
            "volume_lots": volume_lots,
            "contract_units": volume_lots * self.CONTRACT_SIZE,
            "strategy_variant": self._serialize_strategy_variant(strategy_variant),
            "session_variant": session_variant.code,
            "timeframe": timeframe,
            "coverage": spec["coverage"],
            "annual": annual,
            "daily": daily,
            "weekly": weekly,
            "monthly": monthly,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        slug = f"{year}_{strategy_variant.code}_{session_variant.code}".lower()
        summary_path = self.yearly_dir / f"{slug}_summary.json"
        daily_path = self.yearly_dir / f"{slug}_daily_report.csv"
        weekly_path = self.yearly_dir / f"{slug}_weekly_report.csv"
        monthly_path = self.yearly_dir / f"{slug}_monthly_report.csv"
        trades_path = self.yearly_dir / f"{slug}_trades.csv"
        report_path = self.yearly_dir / f"{slug}_report.md"
        snapshot_path = self.strategies_dir / f"maximo_quant_v4_{strategy_variant.code}_{session_variant.code}.json"
        snapshot_history_path = self.strategies_dir / f"maximo_quant_v4_{strategy_variant.code}_{session_variant.code}_{year}.json"
        best_alias_path = self.strategies_dir / "maximo_quant_v4_best_current.json"

        summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_group_csv(daily_path, daily)
        self._write_group_csv(weekly_path, weekly)
        self._write_group_csv(monthly_path, monthly)
        self._write_trades_csv(trades_path, realized)
        report_path.write_text(self._report_markdown(payload), encoding="utf-8")
        snapshot_payload = self._strategy_snapshot_payload(
            strategy_variant=strategy_variant,
            session_variant=session_variant.code,
            timeframe=timeframe,
            symbol=payload["symbol"],
            annual=annual,
            coverage=spec["coverage"],
            optimizer_config=optimizer_config,
        )
        snapshot_path.write_text(json.dumps(snapshot_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot_history_path.write_text(json.dumps(snapshot_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        best_alias_path.write_text(json.dumps(snapshot_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "strategy_name": payload["strategy_name"],
            "symbol": payload["symbol"],
            "year": year,
            "timeframe": timeframe,
            "strategy_variant": strategy_variant.code,
            "session_variant": session_variant.code,
            "annual": annual,
            "summary_path": str(summary_path.resolve()),
            "daily_report_path": str(daily_path.resolve()),
            "weekly_report_path": str(weekly_path.resolve()),
            "monthly_report_path": str(monthly_path.resolve()),
            "trades_path": str(trades_path.resolve()),
            "report_path": str(report_path.resolve()),
            "snapshot_path": str(snapshot_path.resolve()),
            "snapshot_history_path": str(snapshot_history_path.resolve()),
            "best_alias_path": str(best_alias_path.resolve()),
        }

    def _resolve_runtime_variant(
        self,
        *,
        strategy_variant_code: str,
        session_variant_code: str,
    ) -> dict[str, Any]:
        static_variant = next(
            (item for item in self.backtester.STRATEGY_VARIANTS if item.code == strategy_variant_code),
            None,
        )
        if static_variant is not None:
            session_variant = next(item for item in self.backtester.SESSION_VARIANTS if item.code == session_variant_code)
            return {
                "backtester": self.backtester,
                "strategy_variant": static_variant,
                "session_variant": session_variant,
                "optimizer_config": None,
            }

        config = self._load_optimizer_candidate_config(strategy_variant_code)
        if config is None:
            raise ValueError(f"Unknown MAXIMO Quant v4 strategy variant: {strategy_variant_code}")

        runtime_backtester = MaximoMTFQuantV4Backtester(
            input_dir=self.input_dir,
            output_dir=self.backtests_dir / "maximo_mtf_quant_v4",
        )
        runtime_backtester.MIN_QUANT_AGG = int(config["min_quant_score_agg"])
        runtime_backtester.MIN_IMPULSE_AGG = int(config["min_impulse_score_agg"])
        runtime_backtester.MIN_CONF_AGG = int(config["min_confidence_agg"])
        runtime_backtester.MAX_RISK_ATR = float(config["max_risk_atr"])
        runtime_backtester.RR_AGG = float(config["rr_agg"])
        runtime_backtester.RR_A = float(config["rr_a_plus"])
        runtime_backtester.COOLDOWN_BARS = int(config["cooldown_bars"])
        runtime_backtester.PAUSE_AFTER_LOSS = int(config["pause_after_loss"])
        runtime_backtester.PAUSE_AFTER_TWO_LOSSES = int(config["pause_after_two_losses"])

        strategy_variant = StrategyVariant(
            code=str(config["code"]),
            label=str(config["label"]),
            a_plus_only=bool(config.get("a_plus_only", False)),
            require_preferred_side=bool(config.get("require_preferred_side", False)),
            allowed_directions=set(config["allowed_directions"]) if config.get("allowed_directions") else None,
            allowed_setup_types=set(config["allowed_setup_types"]) if config.get("allowed_setup_types") else None,
            disallow_chop=bool(config.get("disallow_chop", False)),
            min_quant_score=int(config.get("min_quant_score_variant", 0)),
            min_impulse_score=int(config.get("min_impulse_score_variant", 0)),
            allowed_hours_ny=set(config["allowed_hours_ny"]) if config.get("allowed_hours_ny") else None,
            excluded_hours_ny=set(config["excluded_hours_ny"]) if config.get("excluded_hours_ny") else None,
            require_recent_compression_for_agg=bool(config.get("require_recent_compression_for_agg", False)),
            disallow_normal_hours_ny=set(config["disallow_normal_hours_ny"]) if config.get("disallow_normal_hours_ny") else None,
            require_quant_expansion=bool(config.get("require_quant_expansion", False)),
            require_recent_compression=bool(config.get("require_recent_compression", False)),
            min_atr_ratio=float(config["min_atr_ratio"]) if config.get("min_atr_ratio") is not None else None,
            min_range_ratio=float(config["min_range_ratio"]) if config.get("min_range_ratio") is not None else None,
            max_atr_ratio=float(config["max_atr_ratio"]) if config.get("max_atr_ratio") is not None else None,
            max_range_ratio=float(config["max_range_ratio"]) if config.get("max_range_ratio") is not None else None,
        )

        requested_session_code = session_variant_code
        if requested_session_code == self.DEFAULT_SESSION and config.get("session_variant"):
            requested_session_code = str(config["session_variant"])
        session_variant = next(item for item in runtime_backtester.SESSION_VARIANTS if item.code == requested_session_code)
        return {
            "backtester": runtime_backtester,
            "strategy_variant": strategy_variant,
            "session_variant": session_variant,
            "optimizer_config": config,
        }

    def _load_optimizer_candidate_config(self, strategy_variant_code: str) -> dict[str, Any] | None:
        if not self.optimization_results_path.exists():
            return None
        payload = json.loads(self.optimization_results_path.read_text(encoding="utf-8"))
        candidates: list[dict[str, Any]] = []
        if baseline := payload.get("baseline"):
            candidates.append(baseline)
        candidates.extend(payload.get("all_candidates", []))
        for candidate in candidates:
            config = candidate.get("config") if isinstance(candidate, dict) else None
            if isinstance(config, dict) and config.get("code") == strategy_variant_code:
                return config
        return None

    def _realize_trades(
        self,
        *,
        trades: list[ClosedTrade],
        initial_capital: float,
        volume_lots: float,
    ) -> list[RealizedQuantTrade]:
        units = volume_lots * self.CONTRACT_SIZE
        balance = initial_capital
        peak_balance = initial_capital
        realized: list[RealizedQuantTrade] = []
        for trade in sorted(trades, key=lambda item: (item.entry_time, item.exit_time)):
            direction_mult = 1.0 if trade.direction == "buy" else -1.0
            gross_pnl = (trade.exit_price - trade.entry_price) * units * direction_mult
            commission = ((trade.entry_price * units) + (trade.exit_price * units)) * self.COMMISSION_RATE
            net_pnl = gross_pnl - commission
            balance += net_pnl
            peak_balance = max(peak_balance, balance)
            drawdown_usd = max(0.0, peak_balance - balance)
            drawdown_percent = (drawdown_usd / peak_balance * 100.0) if peak_balance else 0.0
            realized.append(
                RealizedQuantTrade(
                    trade=trade,
                    volume_lots=volume_lots,
                    contract_units=units,
                    gross_pnl_usd=round(gross_pnl, 4),
                    commission_usd=round(commission, 4),
                    net_pnl_usd=round(net_pnl, 4),
                    balance_after=round(balance, 4),
                    drawdown_usd=round(drawdown_usd, 4),
                    drawdown_percent=round(drawdown_percent, 4),
                )
            )
        return realized

    def _group_report(self, realized: list[RealizedQuantTrade], *, period: str, initial_capital: float) -> list[dict]:
        grouped: dict[str, list[RealizedQuantTrade]] = {}
        ordered_keys: list[str] = []
        for item in realized:
            key = self._period_key(item.trade.exit_time, period)
            if key not in grouped:
                grouped[key] = []
                ordered_keys.append(key)
            grouped[key].append(item)

        rows: list[dict] = []
        running_balance = initial_capital
        for key in ordered_keys:
            items = grouped[key]
            wins = [item for item in items if item.net_pnl_usd > 0]
            losses = [item for item in items if item.net_pnl_usd < 0]
            gross_profit = sum(item.net_pnl_usd for item in wins)
            gross_loss = abs(sum(item.net_pnl_usd for item in losses))
            net_profit = round(sum(item.net_pnl_usd for item in items), 4)
            ending_balance = round(running_balance + net_profit, 4)
            local_equity = running_balance
            local_peak = running_balance
            max_drawdown = 0.0
            losing_streak = 0
            current_losing_streak = 0
            expectancy = round(net_profit / len(items), 4) if items else 0.0
            expectancy_r = round(sum(item.trade.pnl_r for item in items) / len(items), 4) if items else 0.0
            for item in items:
                local_equity += item.net_pnl_usd
                local_peak = max(local_peak, local_equity)
                max_drawdown = max(max_drawdown, local_peak - local_equity)
                if item.net_pnl_usd < 0:
                    current_losing_streak += 1
                    losing_streak = max(losing_streak, current_losing_streak)
                else:
                    current_losing_streak = 0
            rows.append(
                {
                    "period": key,
                    "trades": len(items),
                    "wins": len(wins),
                    "losses": len(losses),
                    "win_rate": round((len(wins) / len(items) * 100.0), 2) if items else 0.0,
                    "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4) if items else 0.0,
                    "expectancy_usd": expectancy,
                    "expectancy_r": expectancy_r,
                    "net_profit_usd": net_profit,
                    "ending_balance": ending_balance,
                    "max_drawdown_usd": round(max_drawdown, 4),
                    "max_drawdown_percent": round((max_drawdown / max(running_balance, 0.0001) * 100.0), 4) if items else 0.0,
                    "losing_streak": losing_streak,
                    "negative_period": net_profit < 0,
                }
            )
            running_balance = ending_balance
        return rows

    def _annual_summary(
        self,
        *,
        realized: list[RealizedQuantTrade],
        daily: list[dict],
        monthly: list[dict],
        weekly: list[dict],
        initial_capital: float,
        volume_lots: float,
        symbol: str,
        year: int,
        timeframe: str,
        strategy_variant: StrategyVariant,
        session_variant: str,
        coverage: dict,
    ) -> dict:
        total_trades = len(realized)
        wins = [item for item in realized if item.net_pnl_usd > 0]
        losses = [item for item in realized if item.net_pnl_usd < 0]
        gross_profit = sum(item.net_pnl_usd for item in wins)
        gross_loss = abs(sum(item.net_pnl_usd for item in losses))
        total_commission = sum(item.commission_usd for item in realized)
        ending_balance = round(realized[-1].balance_after, 4) if realized else round(initial_capital, 4)
        total_profit = round(ending_balance - initial_capital, 4)
        max_drawdown_usd = max((item.drawdown_usd for item in realized), default=0.0)
        max_drawdown_percent = max((item.drawdown_percent for item in realized), default=0.0)
        best_week = max(weekly, key=lambda item: item["net_profit_usd"]) if weekly else None
        worst_week = min(weekly, key=lambda item: item["net_profit_usd"]) if weekly else None
        best_month = max(monthly, key=lambda item: item["net_profit_usd"]) if monthly else None
        worst_month = min(monthly, key=lambda item: item["net_profit_usd"]) if monthly else None
        return {
            "symbol": symbol,
            "year": year,
            "timeframe": timeframe,
            "strategy_variant": strategy_variant.code,
            "session_variant": session_variant,
            "coverage": coverage,
            "initial_capital": initial_capital,
            "volume_lots": volume_lots,
            "contract_units": volume_lots * self.CONTRACT_SIZE,
            "ending_balance": ending_balance,
            "total_profit_usd": total_profit,
            "total_return_percent": round((total_profit / initial_capital) * 100.0, 4) if initial_capital else 0.0,
            "total_trades": total_trades,
            "win_rate": round((len(wins) / total_trades) * 100.0, 2) if total_trades else 0.0,
            "profit_factor": round((gross_profit / gross_loss) if gross_loss else gross_profit, 4) if total_trades else 0.0,
            "expectancy_usd": round(total_profit / total_trades, 4) if total_trades else 0.0,
            "expectancy_r": round(sum(item.trade.pnl_r for item in realized) / total_trades, 4) if total_trades else 0.0,
            "max_drawdown_usd": round(max_drawdown_usd, 4),
            "max_drawdown_percent": round(max_drawdown_percent, 4),
            "losing_streak": self._max_losing_streak(realized),
            "positive_weeks": sum(1 for row in weekly if row["net_profit_usd"] > 0),
            "negative_weeks": sum(1 for row in weekly if row["net_profit_usd"] < 0),
            "positive_days": sum(1 for row in daily if row["net_profit_usd"] > 0),
            "negative_days": sum(1 for row in daily if row["net_profit_usd"] < 0),
            "positive_months": sum(1 for row in monthly if row["net_profit_usd"] > 0),
            "negative_months": sum(1 for row in monthly if row["net_profit_usd"] < 0),
            "total_commission_usd": round(total_commission, 4),
            "best_week": best_week,
            "worst_week": worst_week,
            "best_month": best_month,
            "worst_month": worst_month,
            "profitable_year": ending_balance > initial_capital,
        }

    @staticmethod
    def _max_losing_streak(realized: list[RealizedQuantTrade]) -> int:
        max_streak = 0
        current = 0
        for item in realized:
            if item.net_pnl_usd < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def _period_key(time_value: datetime, period: str) -> str:
        if period == "day":
            return time_value.strftime("%Y-%m-%d")
        if period == "month":
            return time_value.strftime("%Y-%m")
        iso_year, iso_week, _ = time_value.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"

    def _write_group_csv(self, path: Path, rows: list[dict]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def _write_trades_csv(self, path: Path, realized: list[RealizedQuantTrade]) -> None:
        fields = [
            "entry_time",
            "exit_time",
            "setup_type",
            "market_regime",
            "direction",
            "entry_price",
            "exit_price",
            "gross_pnl_usd",
            "commission_usd",
            "net_pnl_usd",
            "balance_after",
            "drawdown_usd",
            "drawdown_percent",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in realized:
                writer.writerow(
                    {
                        "entry_time": item.trade.entry_time.isoformat(),
                        "exit_time": item.trade.exit_time.isoformat(),
                        "setup_type": item.trade.setup_type,
                        "market_regime": item.trade.market_regime,
                        "direction": item.trade.direction,
                        "entry_price": round(item.trade.entry_price, 4),
                        "exit_price": round(item.trade.exit_price, 4),
                        "gross_pnl_usd": item.gross_pnl_usd,
                        "commission_usd": item.commission_usd,
                        "net_pnl_usd": item.net_pnl_usd,
                        "balance_after": item.balance_after,
                        "drawdown_usd": item.drawdown_usd,
                        "drawdown_percent": item.drawdown_percent,
                    }
                )

    def _strategy_snapshot_payload(
        self,
        *,
        strategy_variant: StrategyVariant,
        session_variant: str,
        timeframe: str,
        symbol: str,
        annual: dict,
        coverage: dict,
        optimizer_config: dict[str, Any] | None = None,
    ) -> dict:
        payload = {
            "strategy_name": "MAXIMO MTF Quant Institutional v4",
            "best_variant_code": strategy_variant.code,
            "timeframe": timeframe,
            "session_variant": session_variant,
            "symbol": symbol,
            "source": "TradingView script derived implementation",
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "parameters": self._serialize_strategy_variant(strategy_variant),
            "annual_2025_metrics": annual,
            "coverage": coverage,
            "restore_note": "Snapshot of the current best MAXIMO Quant v4 candidate for restoration after code resets.",
        }
        if optimizer_config is not None:
            payload["optimizer_config"] = optimizer_config
        return payload

    @staticmethod
    def _serialize_strategy_variant(strategy_variant: StrategyVariant) -> dict:
        data = asdict(strategy_variant)
        for key, value in list(data.items()):
            if isinstance(value, set):
                data[key] = sorted(value)
        return data

    def _report_markdown(self, payload: dict) -> str:
        annual = payload["annual"]
        lines = [
            "# MAXIMO Quant v4 Yearly Analysis",
            "",
            f"- symbol: {payload['symbol']}",
            f"- year: {payload['year']}",
            f"- timeframe: {payload['timeframe']}",
            f"- strategy_variant: {payload['strategy_variant']['code']}",
            f"- session_variant: {payload['session_variant']}",
            f"- initial_capital: ${payload['initial_capital']}",
            f"- volume_lots: {payload['volume_lots']}",
            f"- contract_units: {payload['contract_units']}",
            "",
            "## Annual",
            f"- ending_balance: ${annual['ending_balance']}",
            f"- total_profit_usd: ${annual['total_profit_usd']}",
            f"- total_return_percent: {annual['total_return_percent']}%",
            f"- total_trades: {annual['total_trades']}",
            f"- win_rate: {annual['win_rate']}%",
            f"- profit_factor: {annual['profit_factor']}",
            f"- expectancy_usd: ${annual['expectancy_usd']}",
            f"- max_drawdown_usd: ${annual['max_drawdown_usd']}",
            f"- max_drawdown_percent: {annual['max_drawdown_percent']}%",
            f"- total_commission_usd: ${annual['total_commission_usd']}",
            f"- positive_days: {annual['positive_days']}",
            f"- negative_days: {annual['negative_days']}",
            "",
            "## Best Periods",
            f"- best_week: {annual['best_week']}",
            f"- best_month: {annual['best_month']}",
            "",
            "## Worst Periods",
            f"- worst_week: {annual['worst_week']}",
            f"- worst_month: {annual['worst_month']}",
            "",
            "## Coverage",
            f"- coverage_ratio: {payload['coverage']['coverage_ratio']}",
            f"- entry_rows: {payload['coverage']['entry_rows']}",
            f"- htf_rows: {payload['coverage']['htf_rows']}",
        ]
        return "\n".join(lines) + "\n"
