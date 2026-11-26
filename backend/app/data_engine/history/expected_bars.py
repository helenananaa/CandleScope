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
    """The calendar when it has closures; None when the plain interval grid applies."""
    if calendar is None or isinstance(calendar, AlwaysOpenCalendar):
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


__all__ = [
    "FIXED_UTC_CALENDAR_ID",
    "bucket_end_ms",
    "calendar_by_id",
    "dataset_calendar_id",
    "expected_open_range",
    "follows",
    "opens_follow",
    "session_calendar",
]
