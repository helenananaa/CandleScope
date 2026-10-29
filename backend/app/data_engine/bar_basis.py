"""Versioned candle boundary contracts shared by routing and normalization.

The canonical interval is the wire/storage identity. A readable BarBasis is
its definition, never a second independently mutable identifier.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .interval_policy import IntervalSpec, parse_interval_spec


class BoundarySchedule(Protocol):
    def floor_ms(self, timestamp_ms: int) -> int: ...
    def next_ms(self, open_ms: int) -> int: ...
    def previous_ms(self, open_ms: int) -> int: ...


@dataclass(frozen=True, slots=True)
class BarBasis:
    spec: IntervalSpec

    @classmethod
    def parse(cls, interval: str) -> BarBasis:
        spec = parse_interval_spec(interval)
        if spec is None:
            raise ValueError("bar_basis_unsupported")
        return cls(spec)

    @property
    def basis_id(self) -> str:
        return "bar-basis/1:" + self.spec.canonical

    @property
    def schedule(self) -> BoundarySchedule:
        return self.spec

    def to_dict(self) -> dict:
        spec = self.spec
        result = dict(schema_version=1, basis_id=self.basis_id, interval=spec.canonical,
                      alignment=spec.alignment.value, phase_ms=spec.phase_ms,
                      boundary_convention="[open,end)", stored_close="end-1ms")
        if spec.timezone:
            from .calendar_basis import RULES
            result.update(timezone=spec.timezone, calendar_unit=spec.calendar_unit, count=spec.count,
                          rule_version=RULES["wire_version"], tzdb_version=RULES["iana_version"],
                          min_time_ms=RULES["min_time_ms"], max_time_ms=RULES["max_time_ms"],
                          ambiguous_time="reject", nonexistent_time="reject", local_boundary="00:00")
        return result

    @classmethod
    def restore(cls, definition: dict) -> BarBasis:
        basis = cls.parse(definition["interval"])
        if basis.to_dict() != definition:
            raise ValueError("bar_basis_definition_mismatch")
        return basis


@dataclass(frozen=True, slots=True)
class NativeBarSpec:
    provider: str
    market_type: str
    channel: str
    purpose: str
    interval: str
    basis_interval: str | None
    qualification: str = "unknown"
    evidence: str | None = None
    protocol_version: str = "1"
    calendar_id: str | None = None

    def to_dict(self) -> dict:
        basis = BarBasis.parse(self.basis_interval).to_dict() if self.basis_interval else None
        protocol = None
        if self.provider == "okx":
            from app.exchanges.okx_intervals import okx_utc_interval
            value = okx_utc_interval(self.interval)
            protocol = {"rest_parameters": {"bar": value}, "ws_channel": "candle" + value,
                        "finality_evidence": "confirm=1"}
        elif self.provider in {"binance", "binanceusdm"}:
            protocol = {"rest_parameters": {"interval": self.interval},
                        "ws_channel": "{symbol}@kline_" + self.interval, "finality_evidence": "k.x=true"}
        elif self.provider == "bybit" and self.interval == "5m":
            protocol = {"rest_parameters": {"interval": "5"}, "ws_channel": "kline.5.{symbol}",
                        "finality_evidence": "confirm=true"}
        if basis and self.calendar_id:
            basis = {**basis, "basis_id": f"native-bar/1:{self.provider}:{self.market_type}:{self.interval}:{self.calendar_id}",
                     "alignment": "provider-session", "calendar_id": self.calendar_id,
                     "calendar_rule_version": "exchange_calendars-4.13.2", "label_convention": "provider-date"}
        return dict(provider=self.provider, venue=self.provider, market_type=self.market_type,
                    channel=self.channel, purpose=self.purpose, interval=self.interval,
                    basis=basis,
                    qualification=self.qualification, evidence=self.evidence,
                    protocol=protocol,
                    protocol_version=self.protocol_version, calendar_id=self.calendar_id,
                    close_convention="inclusive_ms")

    def validate(self, open_ms: int, close_ms: int) -> None:
        if self.basis_interval is None or self.qualification == "unknown":
            raise ValueError("native_bar_basis_unknown")
        schedule = BarBasis.parse(self.basis_interval).schedule
        if self.calendar_id:
            from app.data_engine.history import get_history_calendar_registry
            calendar = get_history_calendar_registry().get(self.calendar_id)
            if calendar is None:
                raise ValueError("native_bar_calendar_unavailable")
            expected = calendar.first_expected_open(open_ms, open_ms, self.interval)
            end = calendar.bucket_end_ms(open_ms, self.interval)
            if self.market_type in {"stock", "etf"} and self.interval == "1d":
                end = calendar.cash_session_end_ms(open_ms)
            if expected != open_ms or end is None or end - 1 != close_ms:
                raise ValueError("native_bar_boundary_mismatch")
            return
        if schedule.floor_ms(open_ms) != open_ms or schedule.next_ms(open_ms) - 1 != close_ms:
            raise ValueError("native_bar_boundary_mismatch")


def frozen_boundary_windows(interval: str, first_ms: int, last_ms: int) -> dict:
    """Freeze deterministic windows; projection grows in blocks for streaming.

    Definitions remain stable while a full-snapshot indicator appends bars,
    avoiding a session reset on every new candle merely for one future window.
    """
    basis = BarBasis.parse(interval)
    spec = basis.spec
    current = first_ms
    past = []
    for _ in range(500):
        try:
            previous = spec.previous_ms(current)
        except ValueError:
            break
        past.append([previous, current])
        current = previous
    windows = list(reversed(past))
    current, actual = first_ms, 0
    while current <= last_ms:
        following = spec.next_ms(current)
        windows.append([current, following])
        current, actual = following, actual + 1
    projected_count = ((actual + 499) // 1000 + 1) * 1000
    for _ in range(projected_count - actual):
        try:
            following = spec.next_ms(current)
        except ValueError:
            break
        windows.append([current, following])
        current = following
    return {"id": basis.basis_id, "definition": basis.to_dict(), "windows": windows}


def native_bar_spec(provider: str, market_type: str, interval: str, purpose: str) -> NativeBarSpec:
    """Conservative declarations, independent of generic CCXT timezone metadata.

    Adding a venue requires protocol evidence; presence in CCXT's timeframe
    list or a UTC market metadata field is deliberately insufficient.
    """
    provider = provider.lower()
    # The pinned binanceusdm driver uses the same ordinary USD-M Kline
    # endpoints as binance/futures, not continuous-contract candles. Keep its
    # vendor identity while sharing that declared boundary convention.
    known = provider in {"binance", "binanceusdm", "okx"}
    evidence = "docs/architecture/ISSUE_117_BAR_BASIS.md"
    # The official Bybit 5-minute WS fixture includes both start and end.
    # Other native periods remain unknown until independently qualified.
    bybit_fixture = provider == "bybit" and interval == "5m"
    if provider == "twelvedata" and market_type in {"stock", "etf", "forex", "commodity", "index"} and purpose == "history":
        calendar = "twelvedata.weekday.24x5.utc" if market_type in {"forex", "commodity"} else "twelvedata.exchange-date.weekdays.utc"
        return NativeBarSpec(provider, market_type, "kline", purpose, interval, interval, "declared", evidence,
                             protocol_version="twelvedata/time_series/1", calendar_id=calendar)
    return NativeBarSpec(provider, market_type, "kline", purpose, interval,
                         interval if known or bybit_fixture else None,
                         "fixture_verified" if bybit_fixture else "declared" if known else "unknown",
                         evidence if known or bybit_fixture else None,
                         protocol_version="ccxt-4.5.60/utc-v1")
