"""Controlled variant sweep for REACTION_ZONE_SCALPER research."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.reaction_zone_scalper import ReactionZoneConfig, ReactionZoneScalperBacktester


INPUT_DIR = ROOT / "data" / "backtests" / "input"
OUTPUT_DIR = ROOT / "data" / "backtests"
SWEEP_JSON = OUTPUT_DIR / "reaction_zone_scalper" / "reaction_zone_scalper_variant_sweep.json"
SWEEP_MD = OUTPUT_DIR / "reaction_zone_scalper" / "reaction_zone_scalper_variant_sweep.md"


def _variant_configs() -> list[ReactionZoneConfig]:
    liquid_hours = (8, 9, 10, 11, 12, 13)
    best_hours = (9, 10, 11, 12)
    return [
        ReactionZoneConfig(code="v1_baseline"),
        ReactionZoneConfig(
            code="v2_fresh_liquid",
            allowed_hours_ny=liquid_hours,
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_stop_points=2.0,
        ),
        ReactionZoneConfig(
            code="v3_fresh_expansion",
            allowed_hours_ny=liquid_hours,
            allowed_volatility_buckets=("expansion",),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_stop_points=2.0,
        ),
        ReactionZoneConfig(
            code="v4_buy_expansion",
            allowed_sides=("buy",),
            allowed_hours_ny=liquid_hours,
            allowed_volatility_buckets=("expansion",),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_stop_points=2.0,
        ),
        ReactionZoneConfig(
            code="v5_sell_expansion",
            allowed_sides=("sell",),
            allowed_hours_ny=liquid_hours,
            allowed_volatility_buckets=("expansion",),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_stop_points=2.0,
        ),
        ReactionZoneConfig(
            code="v6_strong_zone_liquid",
            allowed_hours_ny=liquid_hours,
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=72.0,
            min_stop_points=2.2,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v7_strong_best_hours",
            allowed_hours_ny=best_hours,
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=76.0,
            min_stop_points=2.5,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v8_buy_strong_best_hours",
            allowed_sides=("buy",),
            allowed_hours_ny=best_hours,
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=76.0,
            min_stop_points=2.5,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v9_expansion_rr_1_3",
            allowed_hours_ny=best_hours,
            allowed_volatility_buckets=("expansion",),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=70.0,
            min_stop_points=2.5,
            rr_target=1.30,
            partial_r=0.50,
            protection_r=0.90,
            protected_stop_r=0.35,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v10_no_quiet_rr_1_25",
            allowed_hours_ny=best_hours,
            allowed_volatility_buckets=("normal", "expansion"),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=72.0,
            min_stop_points=2.5,
            rr_target=1.25,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v11_momentum_entry",
            allowed_hours_ny=best_hours,
            allowed_volatility_buckets=("normal", "expansion"),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=72.0,
            min_entry_wick_pct=40.0,
            min_m1_range_atr=0.75,
            min_stop_points=2.5,
            rr_target=1.25,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v12_low_cost_sensitivity",
            allowed_hours_ny=best_hours,
            allowed_volatility_buckets=("normal", "expansion"),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=72.0,
            min_stop_points=2.5,
            rr_target=1.25,
            spread_price=0.15,
            slippage_per_side=0.03,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v13_buy_expansion_ultra_strong",
            allowed_sides=("buy",),
            allowed_hours_ny=(9, 10, 11, 12),
            allowed_volatility_buckets=("expansion",),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=84.0,
            min_entry_wick_pct=45.0,
            min_m1_range_atr=0.80,
            min_stop_points=3.0,
            max_stop_points=9.0,
            rr_target=1.30,
            early_exit_bars=4,
            early_exit_min_mfe_r=0.25,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v14_buy_normal_expansion_ultra",
            allowed_sides=("buy",),
            allowed_hours_ny=(9, 10, 11, 12),
            allowed_volatility_buckets=("normal", "expansion"),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=84.0,
            min_entry_wick_pct=45.0,
            min_m1_range_atr=0.80,
            min_stop_points=3.0,
            max_stop_points=9.0,
            rr_target=1.30,
            early_exit_bars=4,
            early_exit_min_mfe_r=0.25,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v15_buy_cost_scaled",
            allowed_sides=("buy",),
            allowed_hours_ny=(9, 10, 11, 12),
            allowed_volatility_buckets=("normal", "expansion"),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=80.0,
            min_entry_wick_pct=40.0,
            min_m1_range_atr=0.70,
            min_stop_points=4.0,
            max_stop_points=10.0,
            rr_target=1.35,
            partial_r=0.50,
            protection_r=0.90,
            protected_stop_r=0.35,
            early_exit_bars=4,
            early_exit_min_mfe_r=0.25,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v16_all_cost_scaled",
            allowed_hours_ny=(9, 10, 11, 12),
            allowed_volatility_buckets=("normal", "expansion"),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=82.0,
            min_entry_wick_pct=45.0,
            min_m1_range_atr=0.80,
            min_stop_points=4.0,
            max_stop_points=10.0,
            rr_target=1.35,
            protection_r=0.90,
            protected_stop_r=0.35,
            early_exit_bars=4,
            early_exit_min_mfe_r=0.25,
            require_close_outside_zone=True,
        ),
        ReactionZoneConfig(
            code="v17_low_cost_buy_cost_scaled",
            allowed_sides=("buy",),
            allowed_hours_ny=(9, 10, 11, 12),
            allowed_volatility_buckets=("normal", "expansion"),
            fresh_zones_only=True,
            max_entries_per_zone=1,
            min_zone_strength=80.0,
            min_entry_wick_pct=40.0,
            min_m1_range_atr=0.70,
            min_stop_points=4.0,
            max_stop_points=10.0,
            rr_target=1.35,
            protection_r=0.90,
            protected_stop_r=0.35,
            early_exit_bars=4,
            early_exit_min_mfe_r=0.25,
            spread_price=0.15,
            slippage_per_side=0.03,
            require_close_outside_zone=True,
        ),
    ]


def _score(yearly: dict[str, dict]) -> tuple:
    full = [yearly[str(year)] for year in (2023, 2024, 2025)]
    robust = sum(
        1
        for item in full
        if item["trades"] >= 25 and item["profit_factor"] is not None and item["profit_factor"] > 1.0 and item["max_drawdown_pct"] < 12
    )
    pf_sum = sum((item["profit_factor"] or 0) for item in full)
    net_sum = sum(item["net_profit"] for item in full)
    dd_max = max(item["max_drawdown_pct"] for item in full)
    return robust, pf_sum, net_sum, -dd_max


def main() -> None:
    OUTPUT_DIR.joinpath("reaction_zone_scalper").mkdir(parents=True, exist_ok=True)
    results = []
    for config in _variant_configs():
        backtester = ReactionZoneScalperBacktester(input_dir=INPUT_DIR, output_dir=OUTPUT_DIR, config=config)
        yearly = {}
        aggregate_trades = []
        audits = {}
        for year in [2023, 2024, 2025, 2026]:
            trades, audit = backtester.run_year(symbol="XAUUSDm", year=year)
            yearly[str(year)] = backtester._metrics(trades)
            audits[str(year)] = audit
            aggregate_trades.extend(trades)
        result = {
            "code": config.code,
            "config": asdict(config),
            "yearly": yearly,
            "aggregate": backtester._metrics(aggregate_trades),
            "audits": audits,
            "score": _score(yearly),
        }
        results.append(result)
        print(config.code, result["aggregate"])
    results.sort(key=lambda item: item["score"], reverse=True)
    payload = {"results": results}
    SWEEP_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# REACTION_ZONE_SCALPER Variant Sweep",
        "",
        "| Rank | Variant | 2023 PF/Net/DD/Trades | 2024 PF/Net/DD/Trades | 2025 PF/Net/DD/Trades | 2026 PF/Net/DD/Trades | Aggregate PF | Aggregate Net |",
        "|---:|---|---|---|---|---|---:|---:|",
    ]
    for rank, item in enumerate(results, 1):
        def cell(year: str) -> str:
            metrics = item["yearly"][year]
            return f"{metrics['profit_factor']} / {metrics['net_profit']} / {metrics['max_drawdown_pct']} / {metrics['trades']}"

        lines.append(
            f"| {rank} | {item['code']} | {cell('2023')} | {cell('2024')} | {cell('2025')} | {cell('2026')} | "
            f"{item['aggregate']['profit_factor']} | {item['aggregate']['net_profit']} |"
        )
    SWEEP_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"best": results[0]["code"], "report": str(SWEEP_MD)}, indent=2))


if __name__ == "__main__":
    main()
