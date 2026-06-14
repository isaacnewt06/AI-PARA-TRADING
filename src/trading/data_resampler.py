"""Generate missing H1 and M15 data from M5 candles for execution confirmation."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def resample_to_h1_m15(input_path: Path, output_m15_path: Path, output_h1_path: Path) -> dict[str, int]:
    """Resample M5 candles to H1 and M15 resolution."""
    m5_candles = _read_csv_candles(input_path)
    if not m5_candles:
        return {"status": "no_data", "input_count": 0, "output_m15": 0, "output_h1": 0}

    m15_candles = _resample_to_interval(m5_candles, timedelta(minutes=15), "H1")
    h1_candles = _resample_to_interval(m5_candles, timedelta(hours=1), "M5")

    _write_csv_candles(output_m15_path, m15_candles)
    _write_csv_candles(output_h1_path, h1_candles)

    return {
        "status": "success",
        "input_count": len(m5_candles),
        "output_m15": len(m15_candles),
        "output_h1": len(h1_candles),
    }


def _read_csv_candles(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    candles = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                candles.append({
                    "time": row.get("time") or row.get("datetime") or row.get("timestamp"),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or row.get("tick_volume") or 0),
                })
            except (KeyError, ValueError):
                continue
    return candles


def _resample_to_interval(candles: list[dict[str, Any]], interval: timedelta, source_tf: str) -> list[dict[str, Any]]:
    if not candles:
        return []
    interval_minutes = int(interval.total_seconds() / 60)
    candles_per_bar = interval_minutes // 5
    resampled = []
    for i in range(0, len(candles), candles_per_bar):
        window = candles[i:i + candles_per_bar]
        if not window:
            continue
        aggregated = {
            "time": window[-1]["time"],
            "open": window[0]["open"],
            "high": max(c["high"] for c in window),
            "low": min(c["low"] for c in window),
            "close": window[-1]["close"],
            "volume": sum(c["volume"] for c in window),
        }
        resampled.append(aggregated)
    return resampled


def _write_csv_candles(path: Path, candles: list[dict[str, Any]]) -> None:
    if not candles:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(candles)


def generate_all_missing(input_dir: Path) -> dict[str, dict[str, int]]:
    """Generate missing H1/M15 for all symbols needing them."""
    results = {}
    for m5_file in input_dir.glob("*_M5.csv"):
        symbol = m5_file.stem.replace("_M5", "")
        m15_path = input_dir / f"{symbol}_M15.csv"
        h1_path = input_dir / f"{symbol}_H1.csv"
        if not m15_path.exists() or not h1_path.exists():
            results[symbol] = resample_to_h1_m15(m5_file, m15_path, h1_path)
    return results


if __name__ == "__main__":
    input_dir = Path("data/backtests/input")
    results = generate_all_missing(input_dir)
    print(results)