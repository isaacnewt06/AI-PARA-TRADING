"""Run REACTION_ZONE_SCALPER multi-year research backtest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trading.reaction_zone_scalper import ReactionZoneConfig, ReactionZoneScalperBacktester


def main() -> None:
    input_dir = ROOT / "data" / "backtests" / "input"
    output_dir = ROOT / "data" / "backtests"
    config = ReactionZoneConfig()
    backtester = ReactionZoneScalperBacktester(input_dir=input_dir, output_dir=output_dir, config=config)
    payload = backtester.run_multi_year(symbol="XAUUSDm", years=[2023, 2024, 2025, 2026])
    print(
        json.dumps(
            {
                "strategy": payload["strategy"],
                "recommendation": payload["recommendation"],
                "aggregate": payload["aggregate"],
                "report": str((output_dir / "reaction_zone_scalper" / "reaction_zone_scalper_backtest_report.md").resolve()),
                "trades": str((output_dir / "reaction_zone_scalper" / "reaction_zone_scalper_trades.csv").resolve()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
