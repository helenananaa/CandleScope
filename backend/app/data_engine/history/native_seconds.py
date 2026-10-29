"""Native second-candle retention and confirmed no-trade calendar evidence."""
from __future__ import annotations

import calendar
from bisect import bisect_right
from datetime import datetime, timezone
from typing import Callable

from app.data_engine.history.calendar import AlwaysOpenCalendar


def native_second_history_start(exchange: str, interval: str, now_ms: int) -> int | None:
    if exchange not in {"okx", "upbit"} or interval != "1s":
        return None
    current = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    month_index = current.year * 12 + current.month - 1 - 3
    year, month = divmod(month_index, 12)
    previous = current.replace(year=year, month=month + 1, day=min(current.day, calendar.monthrange(year, month + 1)[1]))
    return int(previous.timestamp() * 1000)


class NativeSparseSecondsCalendar(AlwaysOpenCalendar):
    """Exclude only REST-confirmed empty seconds; unknown gaps remain expected.

    Instances are short-lived read snapshots. A day-sized cache keeps adjacent
    calendar steps from issuing one SQLite query per second. Other intervals
    retain the ordinary UTC calendar.
    """

    def __init__(self, symbol: str, lookup: Callable, revision: Callable = lambda: 0):
        super().__init__(f"upbit.spot.native-seconds:{symbol}")
        self.symbol = symbol
        self._lookup = lookup
        self._revision = revision
        self._observed_revision = revision()
        self._days: dict[int, tuple[list[int], list[tuple[int, int]]]] = {}

    def _skip(self, value: int | None, direction: int, interval: str) -> int | None:
        if value is None or interval != "1s":
            return value
        revision = self._revision()
        if revision != self._observed_revision:
            self._days.clear()
            self._observed_revision = revision
        while True:
            day = value // 86_400_000
            if day not in self._days:
                spans = merge_ranges(self._lookup(self.symbol, day * 86_400_000, (day + 1) * 86_400_000 - 1))
                if len(self._days) >= 8:
                    self._days.pop(next(iter(self._days)))
                self._days[day] = ([a for a, _ in spans], spans)
            starts, spans = self._days[day]
            index = bisect_right(starts, value) - 1
            span = spans[index] if index >= 0 and spans[index][1] >= value else None
            if span is None:
                return value
            value = span[1] + 1000 if direction > 0 else span[0] - 1000

    def first_expected_open(self, start_ms, end_ms, interval):
        value = self._skip(super().first_expected_open(start_ms, end_ms, interval), 1, interval)
        return value if value is not None and value <= end_ms else None

    def last_expected_open(self, start_ms, end_ms, interval):
        value = self._skip(super().last_expected_open(start_ms, end_ms, interval), -1, interval)
        return value if value is not None and value >= start_ms else None

    def next_expected_open(self, open_ms, interval):
        return self._skip(super().next_expected_open(open_ms, interval), 1, interval)

    def previous_expected_open(self, open_ms, interval):
        return self._skip(super().previous_expected_open(open_ms, interval), -1, interval)

    def expected_opens(self, start_ms, end_ms, interval):
        current = self.first_expected_open(start_ms, end_ms, interval)
        while current is not None and current <= end_ms:
            yield current
            current = self.next_expected_open(current, interval)

    def count_expected(self, start_ms, end_ms, interval):
        if interval != "1s":
            return super().count_expected(start_ms, end_ms, interval)
        start = ((start_ms + 999) // 1000) * 1000
        end = (end_ms // 1000) * 1000
        if start > end:
            return 0
        absent = sum((min(b, end) - max(a, start)) // 1000 + 1
                     for a, b in merge_ranges(self._lookup(self.symbol, start, end)))
        return (end - start) // 1000 + 1 - absent


def merge_ranges(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1000:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged
