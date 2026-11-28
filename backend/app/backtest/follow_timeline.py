"""Which chart bars a FOLLOW run expects, and when each one closes (ADR-DATA-002 D2c).

A FOLLOW run reads the chart's closed bars one after another. On an
always-open market (crypto) they sit on the interval grid: one bar per
interval, each ``step`` long. A market on a session calendar (Twelve Data's
US equities on XNYS) has bars only while it trades: its hours open at the
session's half hour (14:30, 15:30 UTC), its last bar of a day may end early,
and nights, weekends and holidays have none. A closure is not a missing bar.

:class:`GridTimeline` keeps the interval-grid arithmetic FOLLOW always used;
:class:`CalendarTimeline` asks the calendar. :func:`follow_timeline` picks one.
"""
from __future__ import annotations

from itertools import islice
from typing import Any

from app.data_engine.history.calendar import TradingCalendar
from app.data_engine.history.expected_bars import bucket_end_ms, open_at_or_after, opens_after, opens_before, session_calendar


class GridTimeline:
    """Bars on the interval grid, as FOLLOW has always read them."""

    calendar: TradingCalendar | None = None

    def __init__(self, spec: Any) -> None:
        self.spec = spec
        self.step = int(spec.nominal_ms)

    def is_open(self, at_ms: int) -> bool:
        return self.spec.floor_ms(at_ms) == at_ms

    def first_open(self, at_ms: int) -> int | None:
        """The first bar open at or after ``at_ms``."""
        first = self.spec.floor_ms(at_ms)
        return first if first == at_ms else first + self.step

    def close(self, open_ms: int) -> int:
        """The bar's last millisecond."""
        return open_ms + self.step - 1

    def continues(self, previous_open_ms: int, previous_close_ms: int, open_ms: int) -> bool:
        """Whether ``open_ms`` is the bar right after the previous one."""
        return open_ms == previous_close_ms + 1

    def closed_through(self, now_ms: int) -> int:
        """The close of the newest bar that has closed: the bar holding ``now`` is still forming."""
        return int(self.spec.floor_ms(now_ms)) - 1

    def opens(self, start_ms: int, through_ms: int) -> list[int]:
        """Opens of the bars from ``start_ms`` that have closed by ``through_ms``."""
        count = (through_ms + 1 - start_ms) // self.step
        return [start_ms + index * self.step for index in range(max(0, count))]

    def next_open(self, start_ms: int, opens_read: list[int]) -> int | None:
        """The bar after those read from ``start_ms``: the first one still missing."""
        return start_ms + len(opens_read) * self.step

    def page_through(self, cursor_ms: int, through_ms: int, bars: int) -> int:
        """The end of a read of at most ``bars`` bars from ``cursor_ms``."""
        return min(through_ms, cursor_ms + bars * self.step - 1)

    def at_least(self, start_ms: int, end_ms: int, bars: int) -> bool:
        """Whether at least ``bars`` bars open in ``[start_ms, end_ms)``."""
        return (end_ms - start_ms) // self.step >= bars

    def start_of_last(self, through_ms: int, bars: int) -> int:
        """Where a run holding the newest ``bars`` bars up to ``through_ms`` starts."""
        return through_ms + 1 - bars * self.step


class CalendarTimeline(GridTimeline):
    """Bars only while the market trades, from its session calendar."""

    def __init__(self, spec: Any, calendar: TradingCalendar) -> None:
        super().__init__(spec)
        self.calendar = calendar
        self.interval = spec.canonical

    def is_open(self, at_ms: int) -> bool:
        return self.calendar.first_expected_open(at_ms, at_ms, self.interval) == at_ms

    def first_open(self, at_ms: int) -> int | None:
        try:
            return open_at_or_after(self.calendar, at_ms, self.interval)
        except LookupError:
            return None

    def close(self, open_ms: int) -> int:
        return bucket_end_ms(self.calendar, open_ms, self.interval) - 1

    def continues(self, previous_open_ms: int, previous_close_ms: int, open_ms: int) -> bool:
        # The next expected open, searched only up to ``open_ms``: the calendar's
        # own next-open lookup scans years of sessions.
        return (open_ms > previous_open_ms
                and self.calendar.first_expected_open(previous_open_ms + 1, open_ms, self.interval) == open_ms)

    def closed_through(self, now_ms: int) -> int:
        # A bar has closed once its own (possibly early) end has passed.
        return now_ms - 1

    def opens(self, start_ms: int, through_ms: int) -> list[int]:
        found = []
        for open_ms in self.calendar.expected_opens(start_ms, through_ms, self.interval):
            if self.close(open_ms) > through_ms:
                break
            found.append(int(open_ms))
        return found

    def next_open(self, start_ms: int, opens_read: list[int]) -> int | None:
        if not opens_read:
            return self.first_open(start_ms)
        try:
            return opens_after(self.calendar, opens_read[-1], 1, self.interval)[0]
        except LookupError:
            return None

    def page_through(self, cursor_ms: int, through_ms: int, bars: int) -> int:
        try:
            last_open = opens_after(self.calendar, cursor_ms - 1, bars, self.interval)[-1]
        except LookupError:
            return through_ms
        return min(through_ms, self.close(last_open))

    def at_least(self, start_ms: int, end_ms: int, bars: int) -> bool:
        if end_ms <= start_ms:
            return bars <= 0
        opens = self.calendar.expected_opens(start_ms, end_ms - 1, self.interval)
        return sum(1 for _ in islice(opens, bars)) >= bars

    def start_of_last(self, through_ms: int, bars: int) -> int:
        try:
            return opens_before(self.calendar, through_ms + 1, bars, self.interval)[0]
        except LookupError:
            return super().start_of_last(through_ms, bars)


def follow_timeline(spec: Any, calendar: TradingCalendar | None = None) -> GridTimeline:
    """The timeline of a fixed-length chart interval; a session calendar's when it has closures."""
    calendar = session_calendar(calendar)
    return GridTimeline(spec) if calendar is None else CalendarTimeline(spec, calendar)
