"""FOLLOW on a trading calendar (ADR-DATA-002 D2c).

AAPL:NASDAQ on Twelve Data follows XNYS: Tuesday 24 and Wednesday 25 November
2026 trade 14:30-21:00 UTC, Thursday 26 (Thanksgiving) is closed. Its hours
open on the session's half hour (14:30 ... 20:30), so the interval grid's UTC
hours are not its bars. A FOLLOW run on it continues across closures exactly
like the fixed run on the same bars, and waits only for bars the calendar
expects.
"""
from __future__ import annotations

import asyncio
from itertools import cycle
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.follow_session import FollowSession, FollowSessions
from app.backtest.follow_timeline import CalendarTimeline, GridTimeline, follow_timeline
from app.data_engine.data_manager import strategy_follows as module
from app.data_engine.data_manager.models import BarData
from app.data_engine.history.calendar import AlwaysOpenCalendar
from app.data_engine.history.expected_bars import calendar_by_id
from app.data_engine.interval_policy import parse_interval_spec
from app.exchanges.plugins.twelvedata.adapter import EXCHANGE_DATE_CALENDAR_ID
from app.exchanges.plugins.twelvedata.plugin import _register_calendars
from app.market_dataset.snapshot import MarketEvent
from tests import strategy_run_oracles as oracles
from tests.test_follow_session import assert_follow_equals_fixed, chunked, definition_of
from tests.test_strategy_run_oracles import BAR, BUILTIN_SMA_REVISION, builtin_provider, service  # noqa: F401

MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR
TUE_OPEN = 1_795_530_600_000  # 2026-11-24 14:30 UTC
TUE_CLOSE = TUE_OPEN + 390 * MINUTE  # 21:00
WED_OPEN = TUE_OPEN + DAY
WED_CLOSE = WED_OPEN + 390 * MINUTE
THU = TUE_OPEN + 2 * DAY
FRI_OPEN = TUE_OPEN + 3 * DAY


@pytest.fixture(scope="module")
def xnys():
    _register_calendars()
    return calendar_by_id(EXCHANGE_DATE_CALENDAR_ID)


def timeline(interval, calendar=None):
    return follow_timeline(parse_interval_spec(interval), calendar)


def stock_bars(xnys, first_open, count, interval="1m"):
    """The oracle's bars, moved onto the market's own opens from ``first_open``."""
    line = timeline(interval, xnys)
    opens = [first_open]
    while len(opens) < count:
        opens.append(line.next_open(first_open, opens))
    events = []
    for sequence, (opened, bar) in enumerate(zip(opens, cycle(oracles.bars())), start=1):
        close = line.close(opened)
        events.append(MarketEvent(sequence, close, "BARS",
                                  {**bar.payload, "open_time_ms": opened, "close_time_ms": close, "is_closed": True}))
    return events


def test_the_grid_keeps_follows_arithmetic():
    grid = timeline("5m")
    start = 1_700_000_100_000
    assert isinstance(grid, GridTimeline) and not isinstance(grid, CalendarTimeline)
    assert timeline("1m", AlwaysOpenCalendar()).calendar is None
    assert grid.first_open(start + 1) == start + 5 * MINUTE and grid.first_open(start) == start
    assert grid.close(start) == start + 5 * MINUTE - 1
    assert grid.continues(start, start + 5 * MINUTE - 1, start + 5 * MINUTE)
    assert not grid.continues(start, start + 5 * MINUTE - 1, start + 10 * MINUTE)
    assert grid.closed_through(start + 7 * MINUTE) == start + 5 * MINUTE - 1
    assert grid.opens(start, start + 15 * MINUTE - 1) == [start, start + 5 * MINUTE, start + 10 * MINUTE]
    assert grid.next_open(start, [start, start + 5 * MINUTE]) == start + 10 * MINUTE
    assert grid.page_through(start, start + DAY, 3) == start + 15 * MINUTE - 1
    assert grid.at_least(start, start + 15 * MINUTE, 3) and not grid.at_least(start, start + 15 * MINUTE, 4)
    assert grid.start_of_last(start + 15 * MINUTE - 1, 2) == start + 5 * MINUTE


def test_the_calendar_knows_session_hours(xnys):
    hours = timeline("1h", xnys)
    assert hours.is_open(TUE_OPEN) and not hours.is_open(TUE_OPEN - 30 * MINUTE)
    # The day's last hour opens at 20:30 and ends with the session at 21:00.
    last = TUE_OPEN + 6 * HOUR
    assert hours.close(last) == TUE_CLOSE - 1
    assert hours.continues(last, TUE_CLOSE - 1, WED_OPEN)
    assert not hours.continues(TUE_OPEN, TUE_OPEN + HOUR - 1, TUE_OPEN + 2 * HOUR)
    assert hours.first_open(TUE_CLOSE) == WED_OPEN and hours.first_open(THU) == FRI_OPEN
    # Bars that have closed by Wednesday 15:40: Tuesday's seven and Wednesday's first.
    assert len(hours.opens(TUE_OPEN, WED_OPEN + 70 * MINUTE - 1)) == 8
    assert hours.page_through(TUE_OPEN, WED_CLOSE, 8) == WED_OPEN + HOUR - 1
    assert hours.at_least(TUE_OPEN, WED_CLOSE, 14) and not hours.at_least(TUE_OPEN, WED_CLOSE, 15)
    assert hours.start_of_last(WED_CLOSE - 1, 8) == TUE_OPEN + 6 * HOUR
    minutes = timeline("1m", xnys)
    assert minutes.next_open(TUE_OPEN, [TUE_CLOSE - MINUTE]) == WED_OPEN
    assert minutes.closed_through(THU) == THU - 1


@pytest.mark.parametrize("sizes", [(), (1, 1, 1, 1, 1), (9, 2, 7), (46,)], ids=["one-pass", "bar-by-bar-start", "uneven", "all-but-last"])
def test_follow_across_the_night_equals_the_fixed_run(service, xnys, sizes):
    events = stock_bars(xnys, TUE_CLOSE - 10 * MINUTE, len(oracles.bars()))
    assert events[10].payload["open_time_ms"] == WED_OPEN
    row = service.create_run({**BAR, "strategy_revision_id": BUILTIN_SMA_REVISION,
                              "start_time_ms": events[0].payload["open_time_ms"],
                              "end_time_ms": events[-1].payload["close_time_ms"]},
                             idempotency_key="calendar-follow", now_ms=4)
    completed = service.execute_bar_run(str(row["run_id"]), events=events, provider=builtin_provider(), now_ms=5)
    assert completed["state"] == "COMPLETED", completed
    session = FollowSession("fl_stock", definition_of(row), lambda _: builtin_provider(), interval="1m",
                            timeline=timeline("1m", xnys))
    try:
        for batch in chunked(events, sizes):
            session.extend(batch)
        assert session.through_ms == events[-1].event_time_ms
        assert_follow_equals_fixed(session.result(), completed["result"], interval="1m")
        assert session.result()["fills"], "the oracle strategy trades"
    finally:
        session.close()


def test_follow_still_refuses_a_hole_while_the_market_trades(service, xnys):
    row = service.create_run({**BAR, "strategy_revision_id": BUILTIN_SMA_REVISION}, idempotency_key="hole", now_ms=4)
    bars = stock_bars(xnys, TUE_CLOSE - 2 * MINUTE, 6)
    # Consecutive sequences, so only the times can be refused: 14:31 is missing.
    events = [MarketEvent(sequence, bar.event_time_ms, bar.role, bar.payload)
              for sequence, bar in enumerate(bars[:3] + bars[4:], start=1)]
    for line in (timeline("1m", xnys), timeline("1m")):
        session = FollowSession("fl_hole", definition_of(row), lambda _: builtin_provider(), interval="1m",
                                timeline=line)
        try:
            session.extend(events[:3])  # Tuesday 20:58, 20:59 and Wednesday 14:30 ...
            with pytest.raises(BacktestError) as refused:
                session.extend(events[3:])  # ... but not 14:32 after them.
            assert refused.value.code == "FOLLOW_INPUT_INVALID"
        except BacktestError as error:
            # The interval grid knows no night: Wednesday's open does not follow Tuesday.
            assert line.calendar is None and error.code == "FOLLOW_INPUT_INVALID"
        finally:
            session.close()


def test_a_recomputed_run_keeps_its_calendar(service, xnys):
    row = service.create_run({**BAR, "strategy_revision_id": BUILTIN_SMA_REVISION}, idempotency_key="keep", now_ms=4)
    sessions = FollowSessions(lambda _: builtin_provider(), clock=lambda: 0.0)
    line = timeline("1m", xnys)
    session, _ = sessions.open(definition_of(row), interval="1m", holder="cell", timeline=line)
    assert sessions.recompute(session.follow_id).timeline is line
    sessions.close()


# -- the feed ---------------------------------------------------------------


class Bars:
    """The DataManager's closed bars of one series, as FOLLOW queries them."""

    def __init__(self) -> None:
        self.rows: dict[int, BarData] = {}
        self.queries: list[tuple[int, int, int, bool]] = []

    def add(self, events) -> None:
        for event in events:
            payload = event.payload
            self.rows[payload["open_time_ms"]] = BarData(
                time=payload["open_time_ms"] // 1000, open=float(payload["open"]), high=float(payload["high"]),
                low=float(payload["low"]), close=float(payload["close"]), volume=float(payload["volume"]),
                is_closed=True, source="backfill_rest_verified")

    def query(self, symbol, interval, *, start_ms, end_ms, limit, auto_backfill, **_):
        self.queries.append((start_ms, end_ms, limit, auto_backfill))
        found = [bar for opened, bar in sorted(self.rows.items()) if start_ms <= opened <= end_ms][:limit]
        return SimpleNamespace(bars=found)


class Owner:
    def __init__(self, now_ms: int) -> None:
        self.now_ms = now_ms
        self.market = SimpleNamespace(bars=Bars())
        self.notified = 0

    def clock_ms(self) -> int:
        return self.now_ms

    def notify(self, _follow_id) -> None:
        self.notified += 1


def feed_for(service, xnys, interval, from_ms, now_ms):
    row = service.create_run({**BAR, "strategy_revision_id": BUILTIN_SMA_REVISION}, idempotency_key=f"feed-{interval}",
                             now_ms=4)
    spec = parse_interval_spec(interval)
    line = follow_timeline(spec, xnys)
    session = FollowSession("fl_feed", definition_of(row), lambda _: builtin_provider(), interval=interval, timeline=line)
    owner = Owner(now_ms)
    key = SimpleNamespace(symbol="AAPL:NASDAQ", interval=interval, exchange="twelvedata", market_type="stock",
                          identity=None)
    return module._Feed(owner, session, key, from_ms, spec), owner, session


def catch_up(feed, session, now_ms=None):
    if now_ms is not None:
        feed.owner.now_ms = now_ms
    asyncio.run(feed._catch_up(session))
    return session.phase


def test_the_feed_reads_across_the_night_and_waits_out_the_holiday(service, xnys):
    feed, owner, session = feed_for(service, xnys, "1m", TUE_CLOSE - 10 * MINUTE, WED_OPEN + 5 * MINUTE)
    events = stock_bars(xnys, TUE_CLOSE - 10 * MINUTE, 400)
    owner.market.bars.add(events[:15])  # Tuesday's last ten, Wednesday 14:30-14:34
    try:
        assert catch_up(feed, session) == "LIVE"
        assert session.through_ms == WED_OPEN + 5 * MINUTE - 1
        # Wednesday's close, then Thanksgiving: nothing is expected, nothing is late.
        owner.market.bars.add(events[15:])
        assert catch_up(feed, session, THU + 3 * HOUR) == "LIVE"
        assert session.through_ms == WED_CLOSE - 1
        assert not any(backfill for *_, backfill in owner.market.bars.queries)
        # Friday opens; its first bars are late past the grace.
        assert catch_up(feed, session, FRI_OPEN + 3 * MINUTE) == "WAITING_DATA"
        assert owner.market.bars.queries[-1][0] == FRI_OPEN and owner.market.bars.queries[-1][3]
    finally:
        session.close()


def test_the_feed_follows_session_hours(service, xnys):
    feed, owner, session = feed_for(service, xnys, "1h", TUE_OPEN, WED_OPEN + 90 * MINUTE)
    owner.market.bars.add(stock_bars(xnys, TUE_OPEN, 14, "1h"))
    try:
        assert catch_up(feed, session) == "LIVE"
        # Wednesday 14:30 closed at 15:30; 15:30 is still forming at 16:00.
        assert session.through_ms == WED_OPEN + HOUR - 1
        assert catch_up(feed, session, WED_CLOSE) == "LIVE"
        # The day's last hour (20:30) closes with the session at 21:00.
        assert session.through_ms == WED_CLOSE - 1 and session.sequence == 14
    finally:
        session.close()
