from datetime import datetime, timezone

from src.trading.blueprint_backtester import BlueprintBacktester
from src.trading.blueprint_backtester import Candle


def _candle(hour: int, close: float) -> Candle:
    return Candle(
        time=datetime(2025, 1, 2, hour, 0, tzinfo=timezone.utc),
        open=close - 0.2,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=10,
    )


def test_resample_groups_h1_candles_into_real_h4_buckets() -> None:
    candles = [_candle(hour, 2600 + hour) for hour in range(8)]

    resampled = BlueprintBacktester._resample(candles, "H4")

    assert len(resampled) == 2
    assert [item.time.hour for item in resampled] == [0, 4]
    assert resampled[0].open == candles[0].open
    assert resampled[0].close == candles[3].close
    assert resampled[1].open == candles[4].open
    assert resampled[1].close == candles[7].close


def test_resample_groups_h1_candles_into_daily_bucket() -> None:
    candles = [_candle(hour, 2600 + hour) for hour in range(8)]

    resampled = BlueprintBacktester._resample(candles, "D1")

    assert len(resampled) == 1
    assert resampled[0].time.hour == 0
    assert resampled[0].open == candles[0].open
    assert resampled[0].close == candles[-1].close
