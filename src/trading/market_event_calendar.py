"""Economic event calendar support for market intelligence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


@dataclass(slots=True)
class MarketEvent:
    title: str
    currency: str
    impact: str
    start_time_utc: datetime
    end_time_utc: datetime
    source: str = "manual"
    tags: tuple[str, ...] = ()

    @property
    def normalized_impact(self) -> str:
        return self.impact.strip().lower()


class MarketEventCalendar:
    """Load and evaluate a local economic calendar feed for XAUUSD-sensitive events."""

    DEFAULT_FOREX_FACTORY_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    DEFAULT_TEMPLATE = {
        "events": [
            {
                "title": "US CPI",
                "currency": "USD",
                "impact": "high",
                "start_time_utc": "2026-05-13T12:30:00+00:00",
                "end_time_utc": "2026-05-13T13:15:00+00:00",
                "source": "manual",
                "tags": ["inflation", "macro"],
            }
        ]
    }

    def __init__(self, path: Path) -> None:
        self.path = path
        self.live_cache_path = self.path.with_name(f"{self.path.stem}_live_cache.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps(self.DEFAULT_TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, *, auto_sync: bool = False, remote_url: str | None = None, timeout_seconds: int = 20) -> list[MarketEvent]:
        if auto_sync:
            self.sync_forex_factory_weekly(remote_url=remote_url, timeout_seconds=timeout_seconds)
        manual_events = self._load_file(self.path)
        cached_events = self._load_file(self.live_cache_path)
        merged: dict[tuple[str, str, str], MarketEvent] = {}
        for event in [*cached_events, *manual_events]:
            key = (event.title, event.currency, event.start_time_utc.isoformat())
            merged[key] = event
        events = sorted(merged.values(), key=lambda item: item.start_time_utc)
        return events

    def _load_file(self, path: Path) -> list[MarketEvent]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        events = []
        for item in payload.get("events", []):
            try:
                start = datetime.fromisoformat(str(item["start_time_utc"]))
                end = datetime.fromisoformat(str(item.get("end_time_utc") or item["start_time_utc"]))
            except Exception:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            events.append(
                MarketEvent(
                    title=str(item.get("title", "Unnamed Event")),
                    currency=str(item.get("currency", "USD")).upper(),
                    impact=str(item.get("impact", "medium")),
                    start_time_utc=start.astimezone(timezone.utc),
                    end_time_utc=end.astimezone(timezone.utc),
                    source=str(item.get("source", "manual")),
                    tags=tuple(str(tag) for tag in item.get("tags", [])),
                )
            )
        events.sort(key=lambda event: event.start_time_utc)
        return events

    def sync_forex_factory_weekly(self, *, remote_url: str | None = None, timeout_seconds: int = 20) -> dict[str, Any]:
        url = remote_url or self.DEFAULT_FOREX_FACTORY_JSON_URL
        request = Request(
            url,
            headers={
                "User-Agent": "BOTEXTRATOR/1.0 (+market-intelligence)",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
        events = []
        for item in payload:
            try:
                start = datetime.fromisoformat(str(item["date"]))
            except Exception:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            end = start + timedelta(minutes=30)
            events.append(
                {
                    "title": str(item.get("title", "Unnamed Event")),
                    "currency": str(item.get("country", "USD")).upper(),
                    "impact": str(item.get("impact", "medium")).lower(),
                    "start_time_utc": start.astimezone(timezone.utc).isoformat(),
                    "end_time_utc": end.astimezone(timezone.utc).isoformat(),
                    "source": "forex_factory_weekly_json",
                    "tags": self._infer_tags(str(item.get("title", ""))),
                }
            )
        cache_payload = {
            "synced_at_utc": datetime.now(timezone.utc).isoformat(),
            "provider": "forex_factory_weekly_json",
            "url": url,
            "events": events,
        }
        self.live_cache_path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "provider": "forex_factory_weekly_json",
            "events_synced": len(events),
            "cache_path": str(self.live_cache_path.resolve()),
        }

    def evaluate_for_symbol(
        self,
        *,
        symbol: str,
        now_utc: datetime | None = None,
        pre_event_block_minutes: int = 5,
        post_event_block_minutes: int = 5,
        upcoming_window_minutes: int = 60,
        auto_sync: bool = False,
        remote_url: str | None = None,
        timeout_seconds: int = 20,
        local_timezone_name: str = "America/Santo_Domingo",
    ) -> dict[str, Any]:
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        local_tz = ZoneInfo(local_timezone_name)
        sync_status: dict[str, Any] = {
            "attempted": auto_sync,
            "status": "disabled" if not auto_sync else "pending",
        }
        if auto_sync:
            try:
                sync_status = {
                    "attempted": True,
                    "status": "ok",
                    **self.sync_forex_factory_weekly(
                        remote_url=remote_url,
                        timeout_seconds=timeout_seconds,
                    ),
                }
            except Exception as exc:
                sync_status = {
                    "attempted": True,
                    "status": "error",
                    "error": str(exc),
                }
        relevant = [
            event
            for event in self.load()
            if self._is_relevant(symbol=symbol, event=event)
        ]
        active: list[MarketEvent] = []
        upcoming: list[MarketEvent] = []
        for event in relevant:
            blocked_start = event.start_time_utc - timedelta(minutes=pre_event_block_minutes)
            blocked_end = event.end_time_utc + timedelta(minutes=post_event_block_minutes)
            if blocked_start <= now <= blocked_end:
                active.append(event)
            elif now < blocked_start <= now + timedelta(minutes=upcoming_window_minutes):
                upcoming.append(event)
        active.sort(key=lambda event: event.start_time_utc)
        upcoming.sort(key=lambda event: event.start_time_utc)
        highest_active = self._highest_impact(active)
        highest_upcoming = self._highest_impact(upcoming)
        action = "allow"
        if highest_active == "high":
            action = "block"
        elif highest_active == "medium" or highest_upcoming == "high":
            action = "watch"
        return {
            "source_path": str(self.path.resolve()),
            "live_cache_path": str(self.live_cache_path.resolve()),
            "relevant_events": len(relevant),
            "active_events": [self._serialize(event, now, local_tz) for event in active[:5]],
            "upcoming_events": [self._serialize(event, now, local_tz) for event in upcoming[:5]],
            "highest_active_impact": highest_active,
            "highest_upcoming_impact": highest_upcoming,
            "action": action,
            "sync_status": sync_status,
            "local_timezone": local_timezone_name,
        }

    @staticmethod
    def _infer_tags(title: str) -> list[str]:
        lower = title.lower()
        tags: list[str] = []
        if "cpi" in lower or "inflation" in lower or "ppi" in lower:
            tags.append("inflation")
        if "fomc" in lower or "fed" in lower:
            tags.append("fed")
        if "non-farm" in lower or "employment" in lower or "claims" in lower:
            tags.append("labor")
        if "retail sales" in lower:
            tags.append("consumer")
        if "gdp" in lower:
            tags.append("growth")
        return tags

    @staticmethod
    def _is_relevant(*, symbol: str, event: MarketEvent) -> bool:
        upper_symbol = symbol.upper()
        if "XAU" in upper_symbol:
            return event.currency in {"USD", "XAU"} or any(tag.lower() in {"fed", "rates", "inflation", "nfp"} for tag in event.tags)
        return event.currency in upper_symbol

    @staticmethod
    def _impact_rank(impact: str) -> int:
        normalized = impact.lower()
        if normalized == "high":
            return 3
        if normalized == "medium":
            return 2
        if normalized == "low":
            return 1
        return 0

    def _highest_impact(self, events: list[MarketEvent]) -> str | None:
        if not events:
            return None
        return max(events, key=lambda item: self._impact_rank(item.normalized_impact)).normalized_impact

    def _serialize(self, event: MarketEvent, now: datetime, local_tz: ZoneInfo) -> dict[str, Any]:
        minutes_until = int((event.start_time_utc - now).total_seconds() // 60)
        return {
            "title": event.title,
            "currency": event.currency,
            "impact": event.normalized_impact,
            "start_time_utc": event.start_time_utc.isoformat(),
            "end_time_utc": event.end_time_utc.isoformat(),
            "start_time_local": event.start_time_utc.astimezone(local_tz).isoformat(),
            "end_time_local": event.end_time_utc.astimezone(local_tz).isoformat(),
            "minutes_until_start": minutes_until,
            "source": event.source,
            "tags": list(event.tags),
        }
