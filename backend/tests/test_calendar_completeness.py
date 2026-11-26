"""Completeness follows the series' trading calendar (ADR-DATA-002 D2a).

AAPL:NASDAQ on Twelve Data follows XNYS: 24-25 Nov 2026 are full sessions,
26 Nov is Thanksgiving and 27 Nov closes at 13:00 New York (18:00 UTC).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backtest.chart_context import ChartBacktestContextResolver
from app.backtest.runtime import _bar_execution_events
from app.data_engine.history.calendar import AlwaysOpenCalendar
from app.data_engine.history.expected_bars import (
    FIXED_UTC_CALENDAR_ID,
    calendar_by_id,
    dataset_calendar_id,
    expected_open_range,
    session_calendar,
)
from app.data_engine.interval_policy import parse_interval_spec
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.models import Requirement
from app.exchanges.plugins.twelvedata.adapter import EXCHANGE_DATE_CALENDAR_ID
from app.exchanges.plugins.twelvedata.plugin import _register_calendars
from app.local_data.service import LocalDatasetError, LocalDatasetService
from app.market_dataset.adapters.local_bar import LocalBarSnapshotProvider
from app.market_dataset.models import DatasetRef
from app.market_dataset.snapshot import MarketDatasetError, MarketEvent

MINUTE = 60_000
DAY = 86_400_000
TUE_OPEN = 1_795_530_600_000  # 2026-11-24 14:30 UTC (09:30 New York)
WED_OPEN = TUE_OPEN + DAY
FRI_OPEN = TUE_OPEN + 3 * DAY
FRI_LAST = FRI_OPEN + 210 * MINUTE - MINUTE  # 17:59 UTC, the half day's last bar
TUE_MIDNIGHT = TUE_OPEN - 14 * 3_600_000 - 30 * MINUTE
WEEK_END = TUE_MIDNIGHT + 4 * DAY - 1  # Friday 23:59:59.999 UTC


@pytest.fixture(scope="module")
def xnys():
    _register_calendars()
    return calendar_by_id(EXCHANGE_DATE_CALENDAR_ID)


def test_the_week_expects_sessions_only(xnys):
    assert xnys is not None
    assert expected_open_range(xnys, TUE_MIDNIGHT, WEEK_END, "1m") == (TUE_OPEN, FRI_LAST)
    # Two full sessions, a holiday and a half day.
    assert xnys.count_expected(TUE_OPEN, FRI_LAST, "1m") == 390 + 390 + 0 + 210
    # A range wholly inside a closure expects nothing.
    assert expected_open_range(xnys, WED_OPEN + DAY, WED_OPEN + DAY + 6 * 3_600_000, "1m") is None


def test_always_open_series_keep_the_interval_grid():
    assert session_calendar(AlwaysOpenCalendar()) is None
    assert session_calendar(None) is None
    assert calendar_by_id(FIXED_UTC_CALENDAR_ID) is None and calendar_by_id(None) is None
    assert dataset_calendar_id(AlwaysOpenCalendar()) == FIXED_UTC_CALENDAR_ID
    with pytest.raises(LookupError):
        calendar_by_id("nowhere.calendar")


def _opens(calendar, start, end, interval="1m"):
    return list(calendar.expected_opens(start, end, interval))


def _host_row(open_ms, close=350):
    return {"open_time_ms": open_ms, "open": close, "high": close, "low": close, "close": close,
            "volume": 10, "is_closed": True}


def test_a_snapshot_across_closures_freezes_with_its_calendar(tmp_path: Path, xnys):
    service = LocalDatasetService(tmp_path / "local-data")
    rows = [_host_row(open_ms) for open_ms in _opens(xnys, TUE_MIDNIGHT, WEEK_END)]
    common = dict(name="AAPL", exchange="twelvedata", market_type="stock", symbol="AAPL:NASDAQ",
                  interval="1m", chart_context_hash="sha256:" + "a" * 64)

    manifest = service.freeze_host_bars(rows, dataset_id="local-" + "1" * 32, calendar=xnys, **common)
    assert manifest["calendar_id"] == EXCHANGE_DATE_CALENDAR_ID and manifest["rows"] == 990
    # On the plain minute grid the same bars have a gap every night.
    with pytest.raises(LocalDatasetError) as gap:
        service.freeze_host_bars(rows, dataset_id="local-" + "2" * 32, **common)
    assert gap.value.code == "host_coverage_incomplete"
    # A session bar missing inside the calendar is still a gap.
    with pytest.raises(LocalDatasetError):
        service.freeze_host_bars(rows[:100] + rows[101:], dataset_id="local-" + "3" * 32, calendar=xnys, **common)

    # Opening the frozen snapshot numbers its bars by the same calendar.
    def ref(calendar_id):
        return DatasetRef(
            dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"], snapshot_hash="",
            venue="twelvedata", market_type="stock", symbol="AAPL:NASDAQ", start_time_ms=TUE_MIDNIGHT,
            end_time_ms=WEEK_END, roles=("BARS",), interval="1m", calendar_id=calendar_id,
            source="local_immutable", retention_policy="user_local")

    snapshot = LocalBarSnapshotProvider(service).open(ref(manifest["calendar_id"]))
    assert (snapshot.first_sequence, snapshot.last_sequence, snapshot.row_count) == (1, 990, 990)
    assert (snapshot.coverage_start_ms, snapshot.coverage_end_ms) == (TUE_OPEN, FRI_LAST + MINUTE - 1)
    # On the fixed UTC grid each closure (Tuesday night; Wednesday night to Friday) skips a number.
    assert LocalBarSnapshotProvider(service).open(ref(FIXED_UTC_CALENDAR_ID)).last_sequence == 992
    with pytest.raises(MarketDatasetError):
        LocalBarSnapshotProvider(service).open(ref("nowhere.calendar"))


def test_an_always_open_snapshot_records_no_calendar(tmp_path: Path):
    service = LocalDatasetService(tmp_path / "local-data")
    rows = [_host_row(TUE_MIDNIGHT + index * MINUTE) for index in range(5)]
    manifest = service.freeze_host_bars(
        rows, dataset_id="local-" + "4" * 32, name="BTC", exchange="binance", market_type="spot",
        symbol="BTCUSDT", interval="1m", chart_context_hash="sha256:" + "b" * 64, calendar=AlwaysOpenCalendar())
    assert "calendar_id" not in manifest


def test_bar_sequences_do_not_count_closures_as_missing(xnys):
    opens = [WED_OPEN + 389 * MINUTE, FRI_OPEN, FRI_OPEN + MINUTE]  # Wed close, holiday, Fri open
    events = tuple(MarketEvent(index, open_ms, "BARS", {"open_time_ms": open_ms})
                   for index, open_ms in enumerate(opens, start=1))

    assert [event.sequence for event in _bar_execution_events(
        events, interval_name="1m", calendar_id=EXCHANGE_DATE_CALENDAR_ID)] == [1, 2, 3]
    # The fixed UTC grid (every crypto snapshot) still marks the jump as missing.
    assert [event.sequence for event in _bar_execution_events(events, interval_name="1m")] == [1, 3, 4]


def _query(opens):
    return SimpleNamespace(bars=[SimpleNamespace(time=open_ms // 1000, is_closed=True) for open_ms in opens],
                           missing_ranges=[])


def test_chart_context_completeness_follows_the_calendar(xnys):
    interval = parse_interval_spec("1m")
    opens = _opens(xnys, TUE_MIDNIGHT, WEEK_END)
    complete = ChartBacktestContextResolver._host_query_is_complete

    assert complete(_query(opens), interval, TUE_MIDNIGHT, WEEK_END, calendar=xnys)
    assert not complete(_query(opens), interval, TUE_MIDNIGHT, WEEK_END)
    assert not complete(_query(opens[:-1]), interval, TUE_MIDNIGHT, WEEK_END, calendar=xnys)
    assert not complete(_query(opens[:500] + opens[501:]), interval, TUE_MIDNIGHT, WEEK_END, calendar=xnys)
    assert ChartBacktestContextResolver._expected_rows(interval, TUE_MIDNIGHT, WEEK_END, calendar=xnys) == 990

    preview = {"row_count": 990, "first_sequence": 1, "last_sequence": 990,
               "coverage_start_ms": TUE_OPEN, "coverage_end_ms": FRI_LAST + MINUTE - 1}
    assert ChartBacktestContextResolver._preview_is_complete(preview, interval, TUE_MIDNIGHT, WEEK_END, calendar=xnys)
    assert not ChartBacktestContextResolver._preview_is_complete(preview, interval, TUE_MIDNIGHT, WEEK_END)
    late = {**preview, "coverage_start_ms": TUE_OPEN + MINUTE}
    assert not ChartBacktestContextResolver._preview_is_complete(late, interval, TUE_MIDNIGHT, WEEK_END, calendar=xnys)


def test_preparation_counts_only_session_minutes(xnys):
    requirement = Requirement(exchange="twelvedata", market_type="stock", symbol="AAPL:NASDAQ",
                              start_ms=TUE_MIDNIGHT, end_ms=WEEK_END + 1)
    rows = [{"open_time": open_ms, "close_time": open_ms + MINUTE - 1, "source": "rest"}
            for open_ms in _opens(xnys, TUE_MIDNIGHT, WEEK_END)]
    complete = BarPreparationAdapter._complete

    assert complete(rows, requirement, calendar=xnys, require_trusted_source=False)
    assert not complete(rows, requirement, require_trusted_source=False)
    assert not complete(rows[:-1], requirement, calendar=xnys, require_trusted_source=False)

    adapter = BarPreparationAdapter.__new__(BarPreparationAdapter)
    adapter.calendar_for = lambda symbol, interval, **route: (
        xnys if route["exchange"] == "twelvedata" else AlwaysOpenCalendar())
    assert adapter._calendar(requirement) is xnys
    assert adapter._calendar(requirement.model_copy(update={"exchange": "binance"})) is None
