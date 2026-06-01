from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.trading.market_event_calendar import MarketEventCalendar


def test_market_event_calendar_watches_high_impact_xauusd_outside_short_block_window(tmp_path: Path) -> None:
    path = tmp_path / "events.json"
    payload = {
        "events": [
            {
                "title": "US CPI",
                "currency": "USD",
                "impact": "high",
                "start_time_utc": "2026-05-12T12:30:00+00:00",
                "end_time_utc": "2026-05-12T13:00:00+00:00",
                "source": "manual",
                "tags": ["inflation"],
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    calendar = MarketEventCalendar(path)

    result = calendar.evaluate_for_symbol(
        symbol="XAUUSDm",
        now_utc=datetime(2026, 5, 12, 12, 10, tzinfo=timezone.utc),
    )

    assert result["action"] == "watch"
    assert result["highest_upcoming_impact"] == "high"
    assert len(result["upcoming_events"]) == 1
    assert result["local_timezone"] == "America/Santo_Domingo"


def test_market_event_calendar_ignores_irrelevant_currency(tmp_path: Path) -> None:
    path = tmp_path / "events.json"
    payload = {
        "events": [
            {
                "title": "CAD Event",
                "currency": "CAD",
                "impact": "high",
                "start_time_utc": "2026-05-12T12:30:00+00:00",
                "end_time_utc": "2026-05-12T13:00:00+00:00",
                "source": "manual",
                "tags": [],
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    calendar = MarketEventCalendar(path)

    result = calendar.evaluate_for_symbol(
        symbol="XAUUSDm",
        now_utc=datetime(2026, 5, 12, 12, 10, tzinfo=timezone.utc),
    )

    assert result["action"] == "allow"
    assert result["relevant_events"] == 0


def test_market_event_calendar_falls_back_when_auto_sync_fails(tmp_path: Path) -> None:
    path = tmp_path / "events.json"
    path.write_text(json.dumps({"events": []}), encoding="utf-8")

    class _BrokenSyncCalendar(MarketEventCalendar):
        def sync_forex_factory_weekly(self, *, remote_url: str | None = None, timeout_seconds: int = 20) -> dict:
            raise RuntimeError("feed unavailable")

    calendar = _BrokenSyncCalendar(path)

    result = calendar.evaluate_for_symbol(
        symbol="XAUUSDm",
        now_utc=datetime(2026, 5, 12, 12, 10, tzinfo=timezone.utc),
        auto_sync=True,
    )

    assert result["action"] == "allow"
    assert result["sync_status"]["status"] == "error"
