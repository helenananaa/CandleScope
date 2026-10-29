"""Versioned local-calendar boundaries, independent of the host's tzdb.

c1 is immutable IANA 2026c data for UTC, Shanghai and New York, with a
published 1970-2399 query range. Extra edge years support containing buckets.
Only local midnight is exposed; ambiguous/nonexistent local times fail closed.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path

RULES = json.loads((Path(__file__).with_name("basis_rules") / "calendar-v1.json").read_text())
ZONES = tuple(RULES["zones"])
DAY_MS = 86_400_000
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@lru_cache(maxsize=3)
def _zone(zone):
    rows = RULES["zones"][zone]
    return tuple(t * 1000 for t, _ in rows), tuple(offset * 1000 for _, offset in rows)


def offset_ms(timestamp_ms: int, zone: str) -> int:
    times, offsets = _zone(zone)
    if not times[0] <= timestamp_ms < 13_632_624_000_000:  # 2402-01-01 UTC
        raise ValueError("calendar_basis_range_unavailable: c1 supports 1970-2399")
    return offsets[bisect_right(times, timestamp_ms) - 1]


def wall_ms_to_utc(wall_ms: int, zone: str) -> int:
    _, offsets = _zone(zone)
    candidates = {wall_ms - offset for offset in offsets
                  if offset_ms(wall_ms - offset, zone) == offset}
    if len(candidates) != 1:
        raise ValueError("calendar_boundary_ambiguous_or_nonexistent")
    return candidates.pop()


def _wall_date(timestamp_ms, zone):
    return EPOCH + timedelta(milliseconds=timestamp_ms + offset_ms(timestamp_ms, zone))


def _midnight(date, zone):
    wall = date.replace(hour=0, minute=0, second=0, microsecond=0)
    return wall_ms_to_utc(int((wall - EPOCH).total_seconds() * 1000), zone)


def calendar_floor_ms(timestamp_ms: int, count: int, unit: str, zone: str) -> int:
    date = _wall_date(timestamp_ms, zone)
    if unit == "M":
        month = (date.year - 1970) * 12 + date.month - 1
        first = (month // count) * count
        date = datetime(1970 + first // 12, first % 12 + 1, 1, tzinfo=timezone.utc)
    else:
        width, anchor = (count * 7, 4) if unit == "w" else (count, 0)
        days = (date.date() - EPOCH.date()).days
        date = EPOCH + timedelta(days=anchor + ((days - anchor) // width) * width)
    return _midnight(date, zone)


def calendar_shift_ms(open_ms: int, count: int, unit: str, zone: str) -> int:
    date = _wall_date(open_ms, zone)
    if unit == "M":
        month = date.year * 12 + date.month - 1 + count
        date = datetime(month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
    else:
        date += timedelta(days=count * (7 if unit == "w" else 1))
    return _midnight(date, zone)


def calendar_maximum_ms(count: int, unit: str) -> int:
    return count * {"d": 1, "w": 7, "M": 31}[unit] * DAY_MS + 7_200_000
