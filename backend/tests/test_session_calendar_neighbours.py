"""Neighbour lookups on session calendars search near their edge.

``next_expected_open`` / ``previous_expected_open`` look across a ten-year
horizon, and chart history walks (``count_back``, range paging) call them once
per bar.  Twelve Data's US-equity calendar used to emit every minute of that
horizon per call (~0.15 s), so a 1m stock chart froze the backend.  The answers
must stay those of the full-horizon enumeration.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.data_engine.history.calendar import SessionCalendar
from app.exchanges.plugins.twelvedata.calendar import TwelveDataUsEquityCalendar

DAY = 86_400_000
MINUTE = 60_000


def ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


@pytest.fixture(scope="module")
def xnys() -> TwelveDataUsEquityCalendar:
    return TwelveDataUsEquityCalendar(calendar_id="qa.xnys")


def enumerated(calendar: SessionCalendar, start_ms: int, end_ms: int, interval: str) -> list[int]:
    return list(calendar.expected_opens(start_ms, end_ms, interval))


def oracle_previous(calendar, open_ms, interval, reach=40 * DAY):
    before = enumerated(calendar, open_ms - reach, open_ms - 1, interval)
    return before[-1] if before else None


def oracle_next(calendar, open_ms, interval, reach=40 * DAY):
    after = enumerated(calendar, open_ms + 1, open_ms + reach, interval)
    return after[0] if after else None


# Thanksgiving 2026 (Thu 26 Nov closed, Fri 27 Nov closes 13:00 ET), the
# weekend after, and the end of daylight saving time (Sun 1 Nov 2026).
POINTS = [
    "2026-11-25T20:59:00+00:00", "2026-11-25T21:00:00+00:00", "2026-11-26T12:00:00+00:00",
    "2026-11-27T14:30:00+00:00", "2026-11-27T17:59:59+00:00", "2026-11-27T18:00:00+00:00",
    "2026-11-28T09:00:00+00:00", "2026-11-30T14:29:59+00:00", "2026-11-30T14:30:00+00:00",
    "2026-10-30T19:59:00+00:00", "2026-11-02T14:30:00+00:00", "2026-11-02T14:31:00+00:00",
]


@pytest.mark.parametrize("interval", ["1m", "5m", "1h", "4h"])
@pytest.mark.parametrize("point", POINTS)
def test_twelve_data_neighbours_match_the_enumerated_sessions(xnys, interval, point):
    at = ms(point)
    assert xnys.previous_expected_open(at, interval) == oracle_previous(xnys, at, interval)
    assert xnys.next_expected_open(at, interval) == oracle_next(xnys, at, interval)


@pytest.mark.parametrize("interval", ["1m", "1h"])
def test_twelve_data_range_edges_match_the_enumerated_sessions(xnys, interval):
    start, end = ms("2026-10-20T00:00:00+00:00"), ms("2026-11-30T23:59:59+00:00")
    for low, high in [(start, end), (ms("2026-11-26T00:00:00+00:00"), ms("2026-11-27T23:59:59+00:00")),
                      (ms("2026-11-27T18:00:00+00:00"), ms("2026-11-30T14:29:59+00:00")),
                      (ms("2026-11-25T15:47:30+00:00"), ms("2026-11-25T15:47:30+00:00"))]:
        opens = enumerated(xnys, low, high, interval)
        assert xnys.first_expected_open(low, high, interval) == (opens[0] if opens else None)
        assert xnys.last_expected_open(low, high, interval) == (opens[-1] if opens else None)


def test_a_count_back_walk_steps_through_every_minute(xnys):
    end = ms("2026-11-27T17:59:00+00:00")
    opens = enumerated(xnys, end - 30 * DAY, end, "1m")
    walked = [end]
    for _ in range(4_999):
        walked.append(xnys.previous_expected_open(walked[-1], "1m"))
    assert walked[::-1] == opens[-5_000:]


def test_a_lookup_builds_days_of_sessions_not_ten_years(xnys, monkeypatch):
    spans: list[int] = []
    original = SessionCalendar._session_segments

    def observed(self, start_ms, end_ms, **kwargs):
        spans.append(end_ms - start_ms)
        return original(self, start_ms, end_ms, **kwargs)

    monkeypatch.setattr(SessionCalendar, "_session_segments", observed)
    at = ms("2026-11-30T14:30:00+00:00")  # Monday open, after Thanksgiving and a weekend
    assert xnys.previous_expected_open(at, "1m") == ms("2026-11-27T17:59:00+00:00")
    assert xnys.next_expected_open(ms("2026-11-27T17:59:00+00:00"), "1m") == at
    assert spans and max(spans) <= 8 * DAY


def test_a_closure_longer_than_the_first_window_is_crossed():
    calendar = SessionCalendar(
        calendar_id="qa.long-closure", timezone_name="UTC",
        weekly_sessions={day: (("09:00", "17:00"),) for day in range(5)},
        holidays=[f"2026-03-{day:02d}" for day in range(2, 28)],
    )
    last_before = ms("2026-02-27T16:59:00+00:00")
    first_after = ms("2026-03-30T09:00:00+00:00")
    assert calendar.previous_expected_open(first_after, "1m") == last_before
    assert calendar.next_expected_open(last_before, "1m") == first_after
    assert calendar.last_expected_open(ms("2026-01-01T00:00:00+00:00"), first_after - 1, "1m") == last_before


def test_abutting_sessions_keep_the_grid_of_their_whole_run():
    # 24-hour sessions merge into one run from the day after the holiday; a
    # 7m grid starting there does not restart at each midnight, so a search
    # window that cuts the run must look further back.
    calendar = SessionCalendar(
        calendar_id="qa.abutting", timezone_name="UTC",
        weekly_sessions={day: (("00:00", "00:00"),) for day in range(7)},
        holidays=["2026-01-01"],
    )
    for point in ["2026-02-01T00:00:00+00:00", "2026-01-20T13:07:00+00:00", "2026-01-02T00:03:00+00:00"]:
        at = ms(point)
        assert calendar.previous_expected_open(at, "7m") == oracle_previous(calendar, at, "7m", reach=60 * DAY)
        assert calendar.next_expected_open(at, "7m") == oracle_next(calendar, at, "7m")
    run_start = ms("2026-01-02T00:00:00+00:00")
    edge = ms("2026-02-01T00:00:00+00:00") - 1
    expected = run_start + ((edge - run_start) // (7 * MINUTE)) * 7 * MINUTE
    assert calendar.previous_expected_open(edge + 1, "7m") == expected


def test_empty_calendars_still_answer_none():
    calendar = SessionCalendar(calendar_id="qa.empty", timezone_name="UTC", weekly_sessions={})
    at = ms("2026-06-01T00:00:00+00:00")
    assert calendar.previous_expected_open(at, "1m") is None
    assert calendar.next_expected_open(at, "1m") is None
    assert calendar.first_expected_open(at, at + DAY, "1m") is None


def test_twelve_data_schedule_bounds_are_unchanged(xnys):
    with pytest.raises(ValueError, match="available only"):
        xnys.next_expected_open(ms("2040-01-02T15:00:00+00:00"), "1m")
    with pytest.raises(ValueError, match="available only"):
        xnys.previous_expected_open(ms("2005-01-03T15:00:00+00:00"), "1m")
    with pytest.raises(ValueError, match="available only"):
        xnys.last_expected_open(ms("1999-12-01T00:00:00+00:00"), ms("2000-01-05T00:00:00+00:00"), "1m")
