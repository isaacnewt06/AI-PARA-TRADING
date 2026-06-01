from __future__ import annotations

import csv
import json
from pathlib import Path

from src.application.analyze_backtest_results import BacktestDiagnosticsApplicationService
from src.core.config import get_settings, reload_settings


def _write_ohlcv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        price = 100.0
        for index in range(30):
            writer.writerow(
                {
                    "time": f"2026-04-01T{(index // 12):02d}:{(index % 12) * 5:02d}:00+00:00",
                    "open": price,
                    "high": price + 2,
                    "low": price - 2,
                    "close": price + 1,
                    "volume": 1,
                }
            )
            price += 0.5


def _write_trades(path: Path, strategy_name: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "strategy_name",
                "symbol",
                "direction",
                "entry_time",
                "exit_time",
                "entry_price",
                "exit_price",
                "stop_price",
                "take_profit_price",
                "result",
                "pnl_r",
                "rr_target",
                "session",
                "setup_time",
                "context_timeframe",
                "entry_timeframe",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "strategy_name": strategy_name,
                "symbol": "XAUUSDm",
                "direction": "long",
                "entry_time": "2026-04-01T01:05:00+00:00",
                "exit_time": "2026-04-01T01:10:00+00:00",
                "entry_price": 101.0,
                "exit_price": 102.0,
                "stop_price": 100.0,
                "take_profit_price": 102.2,
                "result": "win",
                "pnl_r": 1.0,
                "rr_target": 1.2,
                "session": "any_session",
                "setup_time": "2026-04-01T01:00:00+00:00",
                "context_timeframe": "H1",
                "entry_timeframe": "M5",
            }
        )


def _write_result(path: Path, strategy_name: str) -> None:
    payload = {
        "strategy_name": strategy_name,
        "family": "OB Rejection",
        "status": "completed",
        "metrics": {
            "total_trades": 1,
            "win_rate": 100.0,
            "profit_factor": 1.0,
            "expectancy": 1.0,
            "max_drawdown": 0.0,
            "avg_rr": 1.0,
            "losing_streak": 0,
            "best_trade": {"symbol": "XAUUSDm", "pnl_r": 1.0, "result": "win"},
            "worst_trade": {"symbol": "XAUUSDm", "pnl_r": 1.0, "result": "win"},
        },
        "source_traceability": {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_analyze_backtest_results_generates_report_and_json(tmp_path: Path) -> None:
    reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'diag.db').as_posix()}",
        }
    )
    settings = get_settings()
    input_dir = settings.paths.data_dir / "backtests" / "input"
    results_dir = settings.paths.data_dir / "backtests" / "results"
    reports_dir = settings.paths.data_dir / "backtests" / "reports"
    input_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    _write_ohlcv(input_dir / "XAUUSDm_M5.csv")
    for strategy_name in (
        "OB Rejection Relaxed Validation",
        "OB Rejection Balanced Validation",
        "OB Rejection Balanced v2 RR12",
        "OB Rejection Balanced v2 RR15",
    ):
        slug = (
            strategy_name.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace(":", "")
            .replace("|", "_")
        )
        _write_trades(results_dir / f"{slug}_trades.csv", strategy_name)
        _write_result(results_dir / f"{slug}_results.json", strategy_name)

    summary = BacktestDiagnosticsApplicationService(settings).run()

    report_path = Path(summary["report_path"])
    json_path = Path(summary["json_path"])
    assert report_path.exists()
    assert json_path.exists()
    assert "Why Relaxed Works / Why Relaxed Fails" in report_path.read_text(encoding="utf-8")
