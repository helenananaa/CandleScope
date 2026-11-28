"""Exchange-date calendars for imported daily bars (ADR-DATA-002 D2e).

A daily bar from these markets is labelled with its trading date: the bar
opens at 00:00 UTC on that date, as Twelve Data's daily rows already are.
Only daily bars are defined. A date that is neither a known session nor
outside the exchange's known schedule is a closure, so a missing bar on a
session date stays a real gap (for example a suspended stock).

The schedule is known only through ``known_through``. Questions about later
dates raise ``ValueError`` instead of guessing that the market is closed.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, datetime, time, timezone
from functools import lru_cache
from typing import Iterable, Sequence

from app.data_engine.history.models import TimeRange
from app.data_engine.interval_policy import parse_interval_spec


_DAY_MS = 86_400_000
CN_A_SHARE_DAILY_CALENDAR_ID = "cn.a-share.exchange-date.utc"


def _midnight_ms(value: date) -> int:
    return int(datetime.combine(value, time(0), tzinfo=timezone.utc).timestamp() * 1000)


class ExchangeDateCalendar:
    """Sessions of one exchange as daily bars opening at 00:00 UTC."""

    def __init__(
        self,
        *,
        calendar_id: str,
        sessions: Iterable[date],
        known_through: date,
        source: str,
    ) -> None:
        if not str(calendar_id or "").strip():
            raise ValueError("calendar_id must be non-empty")
        opens = sorted({_midnight_ms(item) for item in sessions})
        if not opens:
            raise ValueError("an exchange-date calendar needs at least one session")
        self.calendar_id = str(calendar_id).strip()
        self.timezone_name = "UTC"
        self.source = str(source)
        self.known_through = known_through
        self._opens: tuple[int, ...] = tuple(opens)
        self._known_end_ms = _midnight_ms(known_through) + _DAY_MS
        if self._opens[-1] >= self._known_end_ms:
            raise ValueError("a session falls after known_through")

    @property
    def known_end_ms(self) -> int:
        """Exclusive end of the known schedule: 00:00 UTC after ``known_through``."""
        return self._known_end_ms

    @property
    def first_session(self) -> date:
        return datetime.fromtimestamp(self._opens[0] / 1000, timezone.utc).date()

    def _require_daily(self, interval: str) -> None:
        spec = parse_interval_spec(str(interval))
        if spec is None or spec.canonical != "1d":
            raise ValueError(f"{self.calendar_id} defines daily (1d) bars only, not {interval!r}")

    def _require_known(self, end_ms: int) -> None:
        if int(end_ms) >= self._known_end_ms:
            raise ValueError(
                f"{self.calendar_id} is known only through {self.known_through.isoformat()}"
            )

    def is_session_open(self, open_ms: int) -> bool:
        """Whether ``open_ms`` is exactly 00:00 UTC on a known session date."""
        index = bisect_left(self._opens, int(open_ms))
        return index < len(self._opens) and self._opens[index] == int(open_ms)

    def expected_opens(self, start_ms: int, end_ms: int, interval: str) -> Iterable[int]:
        self._require_daily(interval)
        if end_ms < start_ms:
            return iter(())
        self._require_known(end_ms)
        low = bisect_left(self._opens, int(start_ms))
        high = bisect_right(self._opens, int(end_ms))
        return iter(self._opens[low:high])

    def first_expected_open(self, start_ms: int, end_ms: int, interval: str) -> int | None:
        self._require_daily(interval)
        if end_ms < start_ms:
            return None
        index = bisect_left(self._opens, int(start_ms))
        if index < len(self._opens) and self._opens[index] <= int(end_ms):
            return self._opens[index]
        # No known session in range; a range that runs past the schedule may
        # still hold one.
        self._require_known(end_ms)
        return None

    def last_expected_open(self, start_ms: int, end_ms: int, interval: str) -> int | None:
        self._require_daily(interval)
        if end_ms < start_ms:
            return None
        self._require_known(end_ms)
        index = bisect_right(self._opens, int(end_ms)) - 1
        if index >= 0 and self._opens[index] >= int(start_ms):
            return self._opens[index]
        return None

    def next_expected_open(self, open_ms: int, interval: str) -> int:
        self._require_daily(interval)
        index = bisect_right(self._opens, int(open_ms))
        if index < len(self._opens):
            return self._opens[index]
        raise ValueError(
            f"{self.calendar_id} is known only through {self.known_through.isoformat()}"
        )

    def previous_expected_open(self, open_ms: int, interval: str) -> int | None:
        self._require_daily(interval)
        self._require_known(int(open_ms) - 1)
        index = bisect_left(self._opens, int(open_ms)) - 1
        return self._opens[index] if index >= 0 else None

    def count_expected(self, start_ms: int, end_ms: int, interval: str) -> int:
        return sum(1 for _ in self.expected_opens(start_ms, end_ms, interval))

    def open_segments(self, start_ms: int, end_ms: int, interval: str) -> tuple[TimeRange, ...]:
        opens = list(self.expected_opens(start_ms, end_ms, interval))
        if not opens:
            return ()
        segments: list[TimeRange] = []
        segment_start = previous = opens[0]
        for current in opens[1:]:
            if current - previous != _DAY_MS:
                segments.append(TimeRange(segment_start, previous))
                segment_start = current
            previous = current
        segments.append(TimeRange(segment_start, previous))
        return tuple(segments)

    def bucket_end_ms(self, open_ms: int, interval: str) -> int:
        self._require_daily(interval)
        return int(open_ms) + _DAY_MS


# The Shanghai Stock Exchange opened on 1990-12-19. exchange_calendars'
# earliest bound is a little before that and lists ordinary weekdays there.
_XSHG_FIRST_SESSION = date(1990, 12, 19)


def _xshg_sessions() -> tuple[Sequence[date], date]:
    import exchange_calendars as xcals

    probe = xcals.get_calendar("XSHG")
    start = probe.bound_min().date()
    end = probe.bound_max().date()
    calendar = xcals.get_calendar("XSHG", start=start.isoformat(), end=end.isoformat())
    sessions = tuple(
        item.date() for item in calendar.sessions if item.date() >= _XSHG_FIRST_SESSION
    )
    return sessions, end


@lru_cache(maxsize=1)
def build_cn_a_share_calendar() -> ExchangeDateCalendar:
    """China A-shares: Shanghai Stock Exchange trading dates.

    Shanghai, Shenzhen and Beijing share the national holiday schedule. The
    early Shenzhen Saturday sessions of 1991-1993 are not in this schedule.
    """
    import exchange_calendars as xcals

    sessions, known_through = _xshg_sessions()
    return ExchangeDateCalendar(
        calendar_id=CN_A_SHARE_DAILY_CALENDAR_ID,
        sessions=sessions,
        known_through=known_through,
        source=f"exchange_calendars {xcals.__version__} XSHG",
    )


__all__ = [
    "CN_A_SHARE_DAILY_CALENDAR_ID",
    "ExchangeDateCalendar",
    "build_cn_a_share_calendar",
]
