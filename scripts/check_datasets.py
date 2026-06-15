"""Check available datasets."""

from pathlib import Path
from src.core.config import Settings
from src.trading.maximo_quant_v4_backtester import MaximoMTFQuantV4Backtester

settings = Settings()

bt = MaximoMTFQuantV4Backtester(
    input_dir=settings.paths.data_dir / "backtests" / "input",
    output_dir=settings.paths.data_dir / "backtests" / "maximo_mtf_quant_v4"
)

specs = list(bt._dataset_specs('XAUUSDm'))
print("Available datasets:")
for s in specs[:10]:
    print(f"  {s['label']} - {s['timeframe']} - rows: {s['coverage']['entry_rows']}")