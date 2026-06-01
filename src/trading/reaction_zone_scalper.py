"""Reaction Zone Scalper research backtester.

This module is intentionally isolated from MAXIMO operational logic.
It tests whether violent M15 reaction zones can produce repeatable M1 scalps.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from src.trading.blueprint_backtester import BlueprintBacktester, Candle


NY_TZ = ZoneInfo("America/New_York")
RD_TZ = ZoneInfo("America/Santo_Domingo")


@dataclass(slots=True)
class ReactionZoneConfig:
    code: str = "reaction_zone_scalper_v1"
    label: str = "Reaction Zone Scalper V1"
    initial_capital: float = 500.0
    volume_lots: float = 0.01
    contract_size: float = 100.0
    commission_rate: float = 0.0001
    spread_price: float = 0.30
    slippage_per_side: float = 0.05
    m15_atr_len: int = 14
    m15_range_len: int = 20
    h1_atr_len: int = 14
    m5_atr_len: int = 14
    zone_min_range_ratio: float = 1.10
    zone_max_range_ratio: float = 3.20
    zone_min_wick_pct: float = 42.0
    zone_min_close_escape_pct: float = 48.0
    displacement_atr: float = 0.22
    min_h1_atr_ratio: float = 0.70
    max_h1_atr_ratio: float = 2.40
    min_m5_range_ratio: float = 0.55
    min_zone_strength: float = 0.0
    min_entry_wick_pct: float = 28.0
    min_m1_range_atr: float = 0.0
    require_close_outside_zone: bool = False
    allowed_hours_ny: tuple[int, ...] | None = None
    allowed_sides: tuple[str, ...] | None = None
    allowed_volatility_buckets: tuple[str, ...] | None = None
    fresh_zones_only: bool = False
    max_m1_entry_extension_r: float = 0.55
    zone_expiration_minutes: int = 24 * 60
    max_entries_per_zone: int = 2
    stop_buffer_atr_m1: float = 0.18
    min_stop_points: float = 0.60
    max_stop_points: float = 6.50
    rr_target: float = 1.05
    partial_r: float = 0.50
    protection_r: float = 0.80
    protected_stop_r: float = 0.30
    early_exit_bars: int = 8
    early_exit_min_mfe_r: float = 0.30
    min_minutes_between_zone_entries: int = 20


@dataclass(slots=True)
class ReactionZone:
    id: str
    side: str
    low: float
    high: float
    origin_time: datetime
    created_at: datetime
    expires_at: datetime
    strength: float
    tests: int = 0
    entries: int = 0
    status: str = "fresh"

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0


@dataclass(slots=True)
class ReactionTrade:
    year: int
    zone_id: str
    zone_status_at_entry: str
    side: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    risk_per_unit: float
    realized_r: float
    gross_pnl: float
    commission: float
    execution_cost: float
    net_pnl: float
    exit_reason: str
    partial_taken: bool
    be_moved: bool
    protected_at_0_8r: bool
    went_positive_then_reversed: bool
    max_favorable_r: float
    max_adverse_r: float
    session: str
    hour_ny: int
    volatility_bucket: str
    zone_strength: float
    zone_tests_before_entry: int


class ReactionZoneScalperBacktester:
    """Backtest REACTION_ZONE_SCALPER on XAUUSDm M1/M5/H1 data."""

    def __init__(self, *, input_dir: Path, output_dir: Path, config: ReactionZoneConfig | None = None) -> None:
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.config = config or ReactionZoneConfig()
        self._loader = BlueprintBacktester(
            input_dir=input_dir,
            results_dir=output_dir / "reaction_zone_scalper" / "loader_results",
            reports_dir=output_dir / "reaction_zone_scalper" / "loader_reports",
        )

    def run_multi_year(self, *, symbol: str, years: list[int]) -> dict[str, Any]:
        all_trades: list[ReactionTrade] = []
        yearly: dict[str, Any] = {}
        audits: dict[str, Any] = {}
        for year in years:
            trades, audit = self.run_year(symbol=symbol, year=year)
            yearly[str(year)] = self._metrics(trades)
            audits[str(year)] = audit
            all_trades.extend(trades)

        payload = {
            "strategy": self.config.code,
            "label": self.config.label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "config": asdict(self.config),
            "years": years,
            "yearly": yearly,
            "aggregate": self._metrics(all_trades),
            "breakdowns": self._breakdowns(all_trades),
            "audits": audits,
            "recommendation": self._recommendation(yearly, all_trades),
        }
        self._write_outputs(payload, all_trades)
        return payload

    def run_year(self, *, symbol: str, year: int) -> tuple[list[ReactionTrade], dict[str, Any]]:
        family = self._load_year_family(symbol, year)
        m1 = family.get("M1", [])
        m5 = family.get("M5", [])
        h1 = family.get("H1", [])
        if not m1 or not m5 or not h1:
            return [], {"reason": "missing_data"}
        start, end = self._period_for_year(year)
        m1 = [item for item in m1 if start <= item.time <= end]
        m5 = [item for item in m5 if start <= item.time <= end]
        h1 = [item for item in h1 if start <= item.time <= end]
        m15 = BlueprintBacktester._resample(m5, "M15")
        m1_atr = BlueprintBacktester._atr(m1, 14)
        m5_atr = BlueprintBacktester._atr(m5, self.config.m5_atr_len)
        h1_atr = BlueprintBacktester._atr(h1, self.config.h1_atr_len)
        h1_atr_mean = self._sma(h1_atr, 50)
        m5_range_mean = self._sma([item.high - item.low for item in m5], 20)
        m15_atr = BlueprintBacktester._atr(m15, self.config.m15_atr_len)
        m15_range_mean = self._sma([item.high - item.low for item in m15], self.config.m15_range_len)

        m5_index_by_time = self._completed_context_indices(m1, m5, timedelta(minutes=5))
        h1_index_by_time = self._completed_context_indices(m1, h1, timedelta(hours=1))
        zones_by_create_time = self._detect_zones(m15, m15_atr, m15_range_mean)
        zones_by_time: dict[datetime, list[ReactionZone]] = defaultdict(list)
        for zone in zones_by_create_time:
            zones_by_time[zone.created_at].append(zone)

        active_zones: list[ReactionZone] = []
        trades: list[ReactionTrade] = []
        last_entry_by_zone: dict[str, datetime] = {}
        audit_counter = Counter()
        audit_reasons = Counter()

        index = 60
        while index < len(m1) - 2:
            candle = m1[index]
            for zone in zones_by_time.get(candle.time, []):
                active_zones.append(zone)
                audit_counter["zones_created"] += 1

            self._update_zone_status(active_zones, candle)
            active_zones = [zone for zone in active_zones if zone.status not in {"invalidated", "expired", "weak"}]

            h1_index = h1_index_by_time[index]
            m5_index = m5_index_by_time[index]
            if h1_index is None or m5_index is None:
                index += 1
                continue
            h1_ok, volatility_bucket = self._h1_volatility_ok(h1_index, h1_atr, h1_atr_mean)
            if not h1_ok:
                audit_reasons["h1_volatility_filter"] += 1
                index += 1
                continue
            if self.config.allowed_volatility_buckets and volatility_bucket not in self.config.allowed_volatility_buckets:
                audit_reasons["volatility_bucket_filter"] += 1
                index += 1
                continue
            if not self._m5_activity_ok(m5_index, m5, m5_atr, m5_range_mean):
                audit_reasons["m5_activity_filter"] += 1
                index += 1
                continue
            if self.config.allowed_hours_ny and candle.time.astimezone(NY_TZ).hour not in self.config.allowed_hours_ny:
                audit_reasons["hour_filter"] += 1
                index += 1
                continue

            signal = self._find_entry_signal(
                candle=candle,
                zones=active_zones,
                m1_atr=m1_atr[index],
                last_entry_by_zone=last_entry_by_zone,
            )
            if signal is None:
                index += 1
                continue

            zone = signal["zone"]
            trade, exit_index = self._simulate_trade(
                year=year,
                zone=zone,
                signal_index=index,
                m1=m1,
                m1_atr=m1_atr,
                volatility_bucket=volatility_bucket,
            )
            if trade is None:
                audit_reasons[exit_index] += 1
                index += 1
                continue
            trades.append(trade)
            audit_counter["trades"] += 1
            zone.entries += 1
            zone.tests += 1
            zone.status = "used" if zone.entries == 1 else "weak"
            last_entry_by_zone[zone.id] = trade.entry_time
            index = max(index + 1, exit_index)

        audit = {
            "m1_rows": len(m1),
            "m5_rows": len(m5),
            "m15_rows": len(m15),
            "h1_rows": len(h1),
            "zones_created": audit_counter["zones_created"],
            "trades": len(trades),
            "dominant_blockers": dict(audit_reasons.most_common(10)),
            "data_window": {
                "start": m1[0].time.isoformat() if m1 else None,
                "end": m1[-1].time.isoformat() if m1 else None,
            },
        }
        return trades, audit

    def _detect_zones(
        self,
        m15: list[Candle],
        atr: list[float | None],
        range_mean: list[float | None],
    ) -> list[ReactionZone]:
        zones: list[ReactionZone] = []
        for index in range(20, len(m15) - 2):
            candle = m15[index]
            confirm = m15[index + 1]
            atr_value = atr[index]
            mean_range = range_mean[index]
            if atr_value is None or mean_range is None or mean_range <= 0:
                continue
            candle_range = candle.high - candle.low
            if candle_range <= 0:
                continue
            range_ratio = candle_range / mean_range
            if not (self.config.zone_min_range_ratio <= range_ratio <= self.config.zone_max_range_ratio):
                continue
            body_high = max(candle.open, candle.close)
            body_low = min(candle.open, candle.close)
            body = max(0.0001, body_high - body_low)
            upper_wick = candle.high - body_high
            lower_wick = body_low - candle.low
            close_from_low_pct = (candle.close - candle.low) / candle_range * 100.0
            close_from_high_pct = (candle.high - candle.close) / candle_range * 100.0

            lower_wick_pct = lower_wick / candle_range * 100.0
            upper_wick_pct = upper_wick / candle_range * 100.0
            bullish_displacement = confirm.close - candle.close
            bearish_displacement = candle.close - confirm.close

            if (
                lower_wick_pct >= self.config.zone_min_wick_pct
                and close_from_low_pct >= self.config.zone_min_close_escape_pct
                and bullish_displacement >= atr_value * self.config.displacement_atr
            ):
                zone_high = min(body_low, candle.low + candle_range * 0.45)
                zones.append(
                    self._make_zone(
                        side="buy",
                        low=candle.low,
                        high=max(zone_high, candle.low + atr_value * 0.10),
                        origin=candle,
                        created_at=confirm.time + timedelta(minutes=15),
                        strength=lower_wick_pct + range_ratio * 10.0 + (bullish_displacement / atr_value) * 20.0,
                    )
                )

            if (
                upper_wick_pct >= self.config.zone_min_wick_pct
                and close_from_high_pct >= self.config.zone_min_close_escape_pct
                and bearish_displacement >= atr_value * self.config.displacement_atr
            ):
                zone_low = max(body_high, candle.high - candle_range * 0.45)
                zones.append(
                    self._make_zone(
                        side="sell",
                        low=min(zone_low, candle.high - atr_value * 0.10),
                        high=candle.high,
                        origin=candle,
                        created_at=confirm.time + timedelta(minutes=15),
                        strength=upper_wick_pct + range_ratio * 10.0 + (bearish_displacement / atr_value) * 20.0,
                    )
                )
        return zones

    def _make_zone(
        self,
        *,
        side: str,
        low: float,
        high: float,
        origin: Candle,
        created_at: datetime,
        strength: float,
    ) -> ReactionZone:
        return ReactionZone(
            id=f"{side.upper()}_{origin.time.strftime('%Y%m%d%H%M')}_{round(low, 2)}_{round(high, 2)}",
            side=side,
            low=round(low, 5),
            high=round(high, 5),
            origin_time=origin.time,
            created_at=created_at,
            expires_at=created_at + timedelta(minutes=self.config.zone_expiration_minutes),
            strength=round(strength, 4),
        )

    def _find_entry_signal(
        self,
        *,
        candle: Candle,
        zones: list[ReactionZone],
        m1_atr: float | None,
        last_entry_by_zone: dict[str, datetime],
    ) -> dict[str, Any] | None:
        if m1_atr is None:
            return None
        candidates = sorted(zones, key=lambda item: (item.status != "fresh", -item.strength))
        for zone in candidates:
            if self.config.allowed_sides and zone.side not in self.config.allowed_sides:
                continue
            if self.config.fresh_zones_only and zone.status != "fresh":
                continue
            if zone.strength < self.config.min_zone_strength:
                continue
            if zone.entries >= self.config.max_entries_per_zone:
                continue
            last_entry = last_entry_by_zone.get(zone.id)
            if last_entry and candle.time - last_entry < timedelta(minutes=self.config.min_minutes_between_zone_entries):
                continue
            touched = candle.low <= zone.high and candle.high >= zone.low
            if not touched:
                continue
            candle_range = candle.high - candle.low
            if candle_range <= 0:
                continue
            if candle_range < m1_atr * self.config.min_m1_range_atr:
                continue
            body_high = max(candle.open, candle.close)
            body_low = min(candle.open, candle.close)
            lower_wick_pct = (body_low - candle.low) / candle_range * 100.0
            upper_wick_pct = (candle.high - body_high) / candle_range * 100.0
            if zone.side == "buy":
                extension = max(0.0, candle.close - zone.high)
                if extension > m1_atr * self.config.max_m1_entry_extension_r:
                    continue
                if self.config.require_close_outside_zone and candle.close <= zone.high:
                    continue
                bullish_reject = candle.close > candle.open and (
                    lower_wick_pct >= self.config.min_entry_wick_pct or candle.close >= zone.midpoint
                )
                if bullish_reject:
                    return {"zone": zone}
            else:
                extension = max(0.0, zone.low - candle.close)
                if extension > m1_atr * self.config.max_m1_entry_extension_r:
                    continue
                if self.config.require_close_outside_zone and candle.close >= zone.low:
                    continue
                bearish_reject = candle.close < candle.open and (
                    upper_wick_pct >= self.config.min_entry_wick_pct or candle.close <= zone.midpoint
                )
                if bearish_reject:
                    return {"zone": zone}
        return None

    def _simulate_trade(
        self,
        *,
        year: int,
        zone: ReactionZone,
        signal_index: int,
        m1: list[Candle],
        m1_atr: list[float | None],
        volatility_bucket: str,
    ) -> tuple[ReactionTrade | None, int | str]:
        entry_index = signal_index + 1
        if entry_index >= len(m1):
            return None, "no_next_m1"
        signal_candle = m1[signal_index]
        entry_candle = m1[entry_index]
        atr_value = m1_atr[signal_index]
        if atr_value is None:
            return None, "missing_m1_atr"

        units = self.config.volume_lots * self.config.contract_size
        if zone.side == "buy":
            raw_entry = entry_candle.open
            entry = raw_entry
            stop = min(zone.low, signal_candle.low) - atr_value * self.config.stop_buffer_atr_m1
            risk = entry - stop
            target = entry + risk * self.config.rr_target
        else:
            raw_entry = entry_candle.open
            entry = raw_entry
            stop = max(zone.high, signal_candle.high) + atr_value * self.config.stop_buffer_atr_m1
            risk = stop - entry
            target = entry - risk * self.config.rr_target
        if risk <= self.config.min_stop_points or risk > self.config.max_stop_points:
            return None, "stop_distance_invalid"

        partial_taken = False
        be_moved = False
        protected = False
        partial_realized_r = 0.0
        stop_current = stop
        max_favorable_r = 0.0
        max_adverse_r = 0.0
        exit_price = entry
        exit_reason = "unknown"
        exit_index = entry_index

        partial_price = entry + risk * self.config.partial_r if zone.side == "buy" else entry - risk * self.config.partial_r
        protect_price = entry + risk * self.config.protection_r if zone.side == "buy" else entry - risk * self.config.protection_r
        protected_stop = entry + risk * self.config.protected_stop_r if zone.side == "buy" else entry - risk * self.config.protected_stop_r

        for cursor in range(entry_index, min(len(m1), entry_index + 90)):
            candle = m1[cursor]
            if zone.side == "buy":
                favorable = (candle.high - entry) / risk
                adverse = (entry - candle.low) / risk
                stop_hit = candle.low <= stop_current
                partial_hit = candle.high >= partial_price
                protect_hit = candle.high >= protect_price
                target_hit = candle.high >= target
            else:
                favorable = (entry - candle.low) / risk
                adverse = (candle.high - entry) / risk
                stop_hit = candle.high >= stop_current
                partial_hit = candle.low <= partial_price
                protect_hit = candle.low <= protect_price
                target_hit = candle.low <= target
            max_favorable_r = max(max_favorable_r, favorable)
            max_adverse_r = max(max_adverse_r, adverse)

            if stop_hit:
                exit_price = stop_current
                exit_reason = "stop_loss" if not be_moved else "protected_stop"
                exit_index = cursor
                break

            if not partial_taken and partial_hit:
                partial_taken = True
                be_moved = True
                partial_realized_r = self.config.partial_r * 0.50
                stop_current = entry

            if partial_taken and not protected and protect_hit:
                protected = True
                stop_current = protected_stop

            if target_hit:
                exit_price = target
                exit_reason = "take_profit"
                exit_index = cursor
                break

            if cursor - entry_index >= self.config.early_exit_bars and max_favorable_r < self.config.early_exit_min_mfe_r:
                exit_price = candle.close
                exit_reason = "early_no_reaction"
                exit_index = cursor
                break
        else:
            last = m1[min(len(m1) - 1, entry_index + 89)]
            exit_price = last.close
            exit_reason = "time_exit"
            exit_index = min(len(m1) - 1, entry_index + 89)

        if zone.side == "buy":
            remaining_r = (exit_price - entry) / risk
            gross = (exit_price - entry) * units
        else:
            remaining_r = (entry - exit_price) / risk
            gross = (entry - exit_price) * units
        realized_r = partial_realized_r + (remaining_r * (0.50 if partial_taken else 1.0))
        if partial_taken:
            gross = (risk * self.config.partial_r * units * 0.50) + (gross * 0.50)
        commission = ((entry * units) + (exit_price * units)) * self.config.commission_rate
        execution_cost = (self.config.spread_price + 2 * self.config.slippage_per_side) * units
        net = gross - commission - execution_cost
        went_positive_then_reversed = max_favorable_r >= self.config.partial_r and net <= 0

        return (
            ReactionTrade(
                year=year,
                zone_id=zone.id,
                zone_status_at_entry=zone.status,
                side=zone.side,
                signal_time=signal_candle.time,
                entry_time=entry_candle.time,
                exit_time=m1[exit_index].time,
                entry_price=round(entry, 5),
                exit_price=round(exit_price, 5),
                stop_price=round(stop, 5),
                target_price=round(target, 5),
                risk_per_unit=round(risk, 5),
                realized_r=round(realized_r, 4),
                gross_pnl=round(gross, 4),
                commission=round(commission, 4),
                execution_cost=round(execution_cost, 4),
                net_pnl=round(net, 4),
                exit_reason=exit_reason,
                partial_taken=partial_taken,
                be_moved=be_moved,
                protected_at_0_8r=protected,
                went_positive_then_reversed=went_positive_then_reversed,
                max_favorable_r=round(max_favorable_r, 4),
                max_adverse_r=round(max_adverse_r, 4),
                session=self._session(entry_candle.time),
                hour_ny=entry_candle.time.astimezone(NY_TZ).hour,
                volatility_bucket=volatility_bucket,
                zone_strength=zone.strength,
                zone_tests_before_entry=zone.tests,
            ),
            exit_index,
        )

    def _update_zone_status(self, zones: list[ReactionZone], candle: Candle) -> None:
        for zone in zones:
            if candle.time > zone.expires_at:
                zone.status = "expired"
                continue
            buffer = max(0.20, (zone.high - zone.low) * 0.35)
            if zone.side == "buy" and candle.close < zone.low - buffer:
                zone.status = "invalidated"
            elif zone.side == "sell" and candle.close > zone.high + buffer:
                zone.status = "invalidated"

    def _h1_volatility_ok(
        self,
        index: int,
        atr: list[float | None],
        atr_mean: list[float | None],
    ) -> tuple[bool, str]:
        atr_value = atr[index]
        mean_value = atr_mean[index]
        if atr_value is None or mean_value is None or mean_value <= 0:
            return False, "unknown"
        ratio = atr_value / mean_value
        if ratio < self.config.min_h1_atr_ratio:
            return False, "dead"
        if ratio > self.config.max_h1_atr_ratio:
            return False, "extreme"
        if ratio >= 1.15:
            return True, "expansion"
        if ratio <= 0.85:
            return True, "quiet"
        return True, "normal"

    def _m5_activity_ok(
        self,
        index: int,
        m5: list[Candle],
        atr: list[float | None],
        range_mean: list[float | None],
    ) -> bool:
        atr_value = atr[index]
        mean_value = range_mean[index]
        if atr_value is None or mean_value is None or mean_value <= 0:
            return False
        current_range = m5[index].high - m5[index].low
        return current_range / mean_value >= self.config.min_m5_range_ratio

    def _load_year_family(self, symbol: str, year: int) -> dict[str, list[Candle]]:
        family: dict[str, list[Candle]] = {}
        for timeframe in ("M1", "M5", "H1"):
            path = self.input_dir / f"{symbol}_{timeframe}_{year}.csv"
            if path.exists():
                family[timeframe] = self._loader._load_candles(path)
        return family

    @staticmethod
    def _period_for_year(year: int) -> tuple[datetime, datetime]:
        if year == 2026:
            return datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc)
        return datetime(year, 1, 1, tzinfo=timezone.utc), datetime(year, 12, 31, 23, 59, tzinfo=timezone.utc)

    @staticmethod
    def _completed_context_indices(
        entry_candles: list[Candle],
        context_candles: list[Candle],
        duration: timedelta,
    ) -> list[int | None]:
        result: list[int | None] = [None] * len(entry_candles)
        pointer = -1
        for index, candle in enumerate(entry_candles):
            cutoff = candle.time - duration
            while pointer + 1 < len(context_candles) and context_candles[pointer + 1].time <= cutoff:
                pointer += 1
            result[index] = pointer if pointer >= 0 else None
        return result

    @staticmethod
    def _sma(values: list[float | None] | list[float], period: int) -> list[float | None]:
        result: list[float | None] = [None] * len(values)
        for index in range(len(values)):
            window = [float(value) for value in values[max(0, index - period + 1) : index + 1] if value is not None]
            if len(window) == period:
                result[index] = sum(window) / len(window)
        return result

    @staticmethod
    def _session(time_value: datetime) -> str:
        ny = time_value.astimezone(NY_TZ)
        if 2 <= ny.hour < 7:
            return "london"
        if 7 <= ny.hour < 10:
            return "london_ny_overlap"
        if 10 <= ny.hour < 14:
            return "ny_am"
        if 14 <= ny.hour < 17:
            return "ny_pm"
        return "other"

    def _metrics(self, trades: list[ReactionTrade]) -> dict[str, Any]:
        balance = self.config.initial_capital
        peak = balance
        max_dd = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        wins = 0
        days = set()
        for trade in sorted(trades, key=lambda item: (item.entry_time, item.exit_time)):
            balance += trade.net_pnl
            peak = max(peak, balance)
            max_dd = max(max_dd, peak - balance)
            days.add(trade.entry_time.date())
            if trade.net_pnl > 0:
                wins += 1
                gross_profit += trade.net_pnl
            elif trade.net_pnl < 0:
                gross_loss += abs(trade.net_pnl)
        return {
            "trades": len(trades),
            "win_rate": round(wins / len(trades) * 100.0, 2) if trades else None,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else None),
            "expectancy_usd": round((balance - self.config.initial_capital) / len(trades), 4) if trades else None,
            "expectancy_r": round(mean([trade.realized_r for trade in trades]), 4) if trades else None,
            "net_profit": round(balance - self.config.initial_capital, 4),
            "return_pct": round((balance - self.config.initial_capital) / self.config.initial_capital * 100.0, 4),
            "max_drawdown": round(max_dd, 4),
            "max_drawdown_pct": round(max_dd / self.config.initial_capital * 100.0, 4),
            "trades_per_day": round(len(trades) / len(days), 4) if days else 0.0,
            "partial_taken": sum(1 for trade in trades if trade.partial_taken),
            "be_moved": sum(1 for trade in trades if trade.be_moved),
            "protected_at_0_8r": sum(1 for trade in trades if trade.protected_at_0_8r),
            "positive_then_reversed": sum(1 for trade in trades if trade.went_positive_then_reversed),
        }

    def _breakdowns(self, trades: list[ReactionTrade]) -> dict[str, Any]:
        return {
            "by_side": self._group_metrics(trades, lambda item: item.side),
            "by_session": self._group_metrics(trades, lambda item: item.session),
            "by_hour_ny": self._group_metrics(trades, lambda item: str(item.hour_ny)),
            "by_zone_status": self._group_metrics(trades, lambda item: item.zone_status_at_entry),
            "by_volatility": self._group_metrics(trades, lambda item: item.volatility_bucket),
            "by_exit_reason": self._group_metrics(trades, lambda item: item.exit_reason),
        }

    def _group_metrics(self, trades: list[ReactionTrade], key_fn: Any) -> dict[str, Any]:
        grouped: dict[str, list[ReactionTrade]] = defaultdict(list)
        for trade in trades:
            grouped[str(key_fn(trade))].append(trade)
        return {key: self._metrics(items) for key, items in sorted(grouped.items())}

    @staticmethod
    def _recommendation(yearly: dict[str, Any], trades: list[ReactionTrade]) -> dict[str, str]:
        full_years = [metrics for year, metrics in yearly.items() if year in {"2023", "2024", "2025"}]
        robust_years = sum(
            1
            for metrics in full_years
            if metrics["trades"] >= 40
            and metrics["profit_factor"] is not None
            and metrics["profit_factor"] > 1.2
            and metrics["max_drawdown_pct"] <= 8.0
        )
        if robust_years >= 2:
            return {
                "decision": "APROBADA PARA DEMO SECO",
                "reason": "At least two full years meet PF/DD/trade-count research thresholds.",
            }
        if len(trades) < 80:
            return {
                "decision": "REQUIERE MEJORAS",
                "reason": "Not enough trades for stable multi-year judgment.",
            }
        return {
            "decision": "REQUIERE MEJORAS",
            "reason": "The first version did not prove robust PF > 1.2 across multiple full years.",
        }

    def _write_outputs(self, payload: dict[str, Any], trades: list[ReactionTrade]) -> None:
        out_dir = self.output_dir / "reaction_zone_scalper"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "reaction_zone_scalper_backtest_report.json").write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        self._write_trades_csv(out_dir / "reaction_zone_scalper_trades.csv", trades)
        (out_dir / "reaction_zone_scalper_backtest_report.md").write_text(
            self._render_markdown(payload),
            encoding="utf-8",
        )

    @staticmethod
    def _write_trades_csv(path: Path, trades: list[ReactionTrade]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(trades[0]).keys()) if trades else ["empty"])
            writer.writeheader()
            for trade in trades:
                writer.writerow(asdict(trade))

    def _render_markdown(self, payload: dict[str, Any]) -> str:
        lines = [
            "# REACTION_ZONE_SCALPER Backtest Report",
            "",
            f"Generated: {payload['generated_at']}",
            f"Strategy: `{payload['strategy']}`",
            f"Symbol: `{payload['symbol']}`",
            "",
            "## Recommendation",
            "",
            f"**{payload['recommendation']['decision']}**",
            "",
            payload["recommendation"]["reason"],
            "",
            "## Yearly Metrics",
            "",
            "| Year | Trades | WR% | PF | Expectancy $ | Expectancy R | Net | DD% | Trades/Day | Partial | BE | Protected |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for year, metrics in payload["yearly"].items():
            lines.append(
                "| "
                + " | ".join(
                    [
                        year,
                        str(metrics["trades"]),
                        str(metrics["win_rate"]),
                        str(metrics["profit_factor"]),
                        str(metrics["expectancy_usd"]),
                        str(metrics["expectancy_r"]),
                        str(metrics["net_profit"]),
                        str(metrics["max_drawdown_pct"]),
                        str(metrics["trades_per_day"]),
                        str(metrics["partial_taken"]),
                        str(metrics["be_moved"]),
                        str(metrics["protected_at_0_8r"]),
                    ]
                )
                + " |"
            )
        aggregate = payload["aggregate"]
        lines.extend(
            [
                "",
                "## Aggregate",
                "",
                f"- Trades: {aggregate['trades']}",
                f"- Win rate: {aggregate['win_rate']}%",
                f"- Profit factor: {aggregate['profit_factor']}",
                f"- Expectancy: {aggregate['expectancy_usd']} USD / {aggregate['expectancy_r']}R",
                f"- Net profit: {aggregate['net_profit']}",
                f"- Max drawdown: {aggregate['max_drawdown_pct']}%",
                f"- Trades/day: {aggregate['trades_per_day']}",
                "",
                "## Failure Audit",
                "",
            ]
        )
        for year, audit in payload["audits"].items():
            lines.append(f"### {year}")
            lines.append("")
            lines.append(f"- Zones created: {audit.get('zones_created')}")
            lines.append(f"- Trades: {audit.get('trades')}")
            lines.append(f"- Dominant blockers: `{audit.get('dominant_blockers')}`")
            lines.append("")
        lines.extend(["## Breakdowns", ""])
        for name, breakdown in payload["breakdowns"].items():
            lines.append(f"### {name}")
            lines.append("")
            lines.append("| Key | Trades | WR% | PF | Net | DD% | Partial | BE |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
            for key, metrics in breakdown.items():
                lines.append(
                    f"| {key} | {metrics['trades']} | {metrics['win_rate']} | {metrics['profit_factor']} | "
                    f"{metrics['net_profit']} | {metrics['max_drawdown_pct']} | {metrics['partial_taken']} | {metrics['be_moved']} |"
                )
            lines.append("")
        lines.extend(
            [
                "## Notes",
                "",
                "- Backtest uses closed M15/H1 context and M1 next-open entries.",
                "- Costs include estimated spread, slippage, and commission.",
                "- Same-candle execution is conservative: stop/protection is checked before target.",
                "- This is research output, not live approval.",
            ]
        )
        return "\n".join(lines)
