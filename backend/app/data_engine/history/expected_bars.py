"""Which bars a series should have, for code outside the data engine (ADR-DATA-002 D2).

Completeness used to mean one bar per interval. A series on a session
calendar (Twelve Data's US equities on XNYS) has no bars while its market is
closed: nights, weekends, holidays and the second half of a half day. These
helpers answer "which opens are expected" from that calendar.

Series without closures (crypto's ``crypto.24x7.utc``, or no known calendar)
get ``None`` from :func:`session_calendar`. Callers keep their plain interval
grid for them, so exchange results and hashes stay exactly as they were.
"""
from __future__ import annotations

from typing import Iterable

from app.data_engine.interval_policy import parse_interval_ms
from app.data_engine.history.calendar import (
    AlwaysOpenCalendar,
    TradingCalendar,
    containing_expected_open_ms,
    expected_bucket_end_ms,
    get_history_calendar_registry,
)

# Frozen datasets written before D2 (and every always-open series) carry this.
FIXED_UTC_CALENDAR_ID = "UTC_FIXED"


def session_calendar(calendar: TradingCalendar | None) -> TradingCalendar | None:
    """The calendar when it has closures; None when the plain interval grid applies.

    Only registered calendars qualify: a snapshot that names its calendar must
    be able to find it again by id.
    """
    if calendar is None or isinstance(calendar, AlwaysOpenCalendar):
        return None
    if get_history_calendar_registry().get(calendar.calendar_id) is None:
        return None
    return calendar


def calendar_by_id(calendar_id: str | None) -> TradingCalendar | None:
    """The registered session calendar a frozen dataset names, or None for the interval grid.

    An id that is neither the fixed UTC grid nor registered raises: a snapshot
    whose schedule is unknown must not be checked against the wrong one.
    """
    if not calendar_id or calendar_id == FIXED_UTC_CALENDAR_ID:
        return None
    registry = get_history_calendar_registry()
    calendar = registry.get(calendar_id)
    if calendar is None:
        # Exchange plugins register their calendars when they are built; a
        # worker process that reads a frozen snapshot may not have built them.
        from app.exchanges.registry import bootstrap_default_adapters

        bootstrap_default_adapters()
        calendar = registry.get(calendar_id)
    if calendar is None:
        raise LookupError(f"unknown trading calendar: {calendar_id}")
    return session_calendar(calendar)


def dataset_calendar_id(calendar: TradingCalendar | None) -> str:
    """The ``calendar_id`` a dataset reference records for ``calendar``."""
    calendar = session_calendar(calendar)
    return FIXED_UTC_CALENDAR_ID if calendar is None else calendar.calendar_id


def expected_open_range(
    calendar: TradingCalendar, start_ms: int, end_ms: int, interval: str,
) -> tuple[int, int] | None:
    """First and last expected opens a complete ``[start_ms, end_ms]`` holds.

    The first is the open whose bucket contains ``start_ms`` while the market
    trades then, otherwise the first open after it; the last is the latest open
    at or before ``end_ms``. None when the range holds no trading at all.
    """
    first = containing_expected_open_ms(calendar, start_ms, interval)
    if first is None:
        first = calendar.first_expected_open(start_ms, end_ms, interval)
    if first is None:
        return None
    last = calendar.last_expected_open(int(first), end_ms, interval)
    if last is None or last < first:
        return None
    return int(first), int(last)


def follows(calendar: TradingCalendar, interval: str, previous_open_ms: int, open_ms: int) -> bool:
    """Whether ``open_ms`` is the next expected open after ``previous_open_ms``."""
    return calendar.next_expected_open(int(previous_open_ms), interval) == int(open_ms)


def opens_follow(calendar: TradingCalendar, interval: str, opens: Iterable[int]) -> bool:
    previous: int | None = None
    for open_ms in opens:
        if previous is not None and not follows(calendar, interval, previous, open_ms):
            return False
        previous = int(open_ms)
    return True


def bucket_end_ms(calendar: TradingCalendar, open_ms: int, interval: str) -> int:
    """Exclusive end of an expected bucket (a half day's last bar may end early)."""
    return expected_bucket_end_ms(calendar, open_ms, interval)


# Searches step through bounded windows: a session calendar's own
# previous/next lookups scan years of minutes.
_FIRST_WINDOW_MS = 7 * 86_400_000
_MAX_WINDOWS = 16


def _window_ms(count: int, interval: str) -> int:
    width_ms = parse_interval_ms(interval)
    if width_ms is None or width_ms <= 0:
        raise ValueError(f"calendar walks need a fixed interval: {interval}")
    return max(_FIRST_WINDOW_MS, 4 * count * width_ms)


def opens_after(calendar: TradingCalendar, open_ms: int, count: int, interval: str) -> list[int]:
    """The next ``count`` expected opens strictly after ``open_ms``."""
    found: list[int] = []
    cursor = int(open_ms) + 1
    window = _window_ms(count, interval)
    for _ in range(_MAX_WINDOWS):
        try:
            values = calendar.expected_opens(cursor, cursor + window - 1, interval)
            for value in values:
                found.append(int(value))
                if len(found) == count:
                    return found
        except ValueError as exc:  # the calendar's schedule ends
            raise LookupError(f"{calendar.calendar_id} has too few opens after {open_ms}") from exc
        cursor += window
        window *= 2
    raise LookupError(f"{calendar.calendar_id} has too few opens after {open_ms}")


def opens_before(calendar: TradingCalendar, open_ms: int, count: int, interval: str) -> list[int]:
    """The ``count`` expected opens strictly before ``open_ms``, oldest first."""
    found: list[int] = []
    end = int(open_ms) - 1
    window = _window_ms(count, interval)
    for _ in range(_MAX_WINDOWS):
        start = max(0, end - window + 1)
        try:
            chunk = [int(value) for value in calendar.expected_opens(start, end, interval)]
        except ValueError as exc:  # the calendar's schedule starts later
            raise LookupError(f"{calendar.calendar_id} has too few opens before {open_ms}") from exc
        found = chunk + found
        if len(found) >= count:
            return found[-count:]
        if start == 0:
            break
        end = start - 1
        window *= 2
    raise LookupError(f"{calendar.calendar_id} has too few opens before {open_ms}")


def offset_open(calendar: TradingCalendar, open_ms: int, offset: int, interval: str) -> int:
    """The expected open ``offset`` bars after (or, negative, before) ``open_ms``."""
    if offset == 0:
        return int(open_ms)
    if offset > 0:
        return opens_after(calendar, open_ms, offset, interval)[-1]
    return opens_before(calendar, open_ms, -offset, interval)[0]


def open_at_or_after(calendar: TradingCalendar, timestamp_ms: int, interval: str) -> int:
    """The first expected open at or after ``timestamp_ms``."""
    return opens_after(calendar, int(timestamp_ms) - 1, 1, interval)[0]


def open_runs(calendar: TradingCalendar, start_ms: int, end_ms: int, interval: str) -> list[tuple[int, int]]:
    """Runs of back-to-back expected opens in ``[start_ms, end_ms]``, as (first, last)."""
    width_ms = parse_interval_ms(interval)
    if width_ms is None or width_ms <= 0:
        raise ValueError(f"calendar runs need a fixed interval: {interval}")
    runs: list[tuple[int, int]] = []
    for value in calendar.expected_opens(int(start_ms), int(end_ms), interval):
        value = int(value)
        if runs and value == runs[-1][1] + width_ms:
            runs[-1] = (runs[-1][0], value)
        else:
            runs.append((value, value))
    return runs


class ShiftedCalendar:
    """``calendar`` moved by ``delta_ms``, for replay's synthetic (blind) timelines."""

    def __init__(self, calendar: TradingCalendar, delta_ms: int) -> None:
        self.calendar = calendar
        self.delta_ms = int(delta_ms)
        self.calendar_id = calendar.calendar_id

    def expected_opens(self, start_ms: int, end_ms: int, interval: str):
        delta = self.delta_ms
        return (int(value) + delta for value in self.calendar.expected_opens(
            int(start_ms) - delta, int(end_ms) - delta, interval))

    def first_expected_open(self, start_ms: int, end_ms: int, interval: str) -> int | None:
        value = self.calendar.first_expected_open(int(start_ms) - self.delta_ms, int(end_ms) - self.delta_ms, interval)
        return None if value is None else int(value) + self.delta_ms

    def last_expected_open(self, start_ms: int, end_ms: int, interval: str) -> int | None:
        value = self.calendar.last_expected_open(int(start_ms) - self.delta_ms, int(end_ms) - self.delta_ms, interval)
        return None if value is None else int(value) + self.delta_ms

    def count_expected(self, start_ms: int, end_ms: int, interval: str) -> int:
        return self.calendar.count_expected(int(start_ms) - self.delta_ms, int(end_ms) - self.delta_ms, interval)

    def bucket_end_ms(self, open_ms: int, interval: str) -> int:
        return expected_bucket_end_ms(self.calendar, int(open_ms) - self.delta_ms, interval) + self.delta_ms


def shifted_calendar(calendar: TradingCalendar | None, delta_ms: int) -> TradingCalendar | None:
    if calendar is None or not delta_ms:
        return calendar
    return ShiftedCalendar(calendar, delta_ms)


__all__ = [
    "FIXED_UTC_CALENDAR_ID",
    "ShiftedCalendar",
    "bucket_end_ms",
    "calendar_by_id",
    "dataset_calendar_id",
    "expected_open_range",
    "follows",
    "offset_open",
    "open_at_or_after",
    "open_runs",
    "opens_after",
    "opens_before",
    "opens_follow",
    "session_calendar",
    "shifted_calendar",
]
