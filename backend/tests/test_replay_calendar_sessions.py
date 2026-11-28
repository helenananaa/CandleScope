"""Replay over a market that closes (ADR-DATA-002 D2b, D2b2).

AAPL:NASDAQ on Twelve Data follows XNYS: 24-25 Nov 2026 are full sessions
(14:30-21:00 UTC), 26 Nov is Thanksgiving.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.data_preparation import router
from app.data_engine.history.expected_bars import calendar_by_id
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.replay_context import ReplayHistoryContext
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.exchanges.plugins.twelvedata.adapter import EXCHANGE_DATE_CALENDAR_ID
from app.exchanges.plugins.twelvedata.plugin import _register_calendars
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.constants import CommandType
from app.replay.history_archive import ReplayHistoryRepository
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.indicator.warmup import replay_display_warmup_bars
from app.replay.training.errors import TrainingRunError
from app.replay.training.indicator_viewport import math_parameters
from tests.fixtures.replay.service_fakes import replay_settings
from tests.test_data_preparation import async_test, terminal
from tests.test_replay_indicator_prefix import lines, reference
from tests.test_replay_service import _command
from tests.test_replay_v2_run_centric import _setup_payload

MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR
TUE_OPEN = 1_795_530_600_000  # 2026-11-24 14:30 UTC
WED_OPEN = TUE_OPEN + 86_400_000
TUE_LAST = TUE_OPEN + 389 * MINUTE  # 20:59 UTC
STOCK = {"provider_id": "twelvedata", "venue": "xngs", "asset_class": "stock", "series_variant": "ohlcv",
         "price_adjustment": "raw", "session_variant": "regular", "volume_semantics": "shares"}


@pytest.fixture(scope="module")
def xnys():
    _register_calendars()
    return calendar_by_id(EXCHANGE_DATE_CALENDAR_ID)


def _row(open_ms):
    price = 350 + (open_ms - TUE_OPEN) // MINUTE % 7
    return {"open_time": open_ms, "close_time": open_ms + MINUTE - 1, "open": price, "high": price + 1,
            "low": price - 1, "close": price, "volume": 3, "source": "backfill"}


def _connected(page, before_ms):
    """The chart client's rule: every gap between bars, and up to its cursor, is declared.

    Closures are declared as closures, never as source gaps.
    """
    ranges = sorted(page["excluded_ranges"], key=lambda item: item["start_ms"])
    assert {item["reason"] for item in ranges} <= {"market_closed"}

    def declared(start, end):
        for item in ranges:
            if item["start_ms"] <= start <= item["end_ms"]:
                start = item["end_ms"] + 1
        return start > end

    bars = page["bars"]
    gaps = [(earlier["close_time_ms"] + 1, later["open_time_ms"] - 1) for earlier, later in zip(bars, bars[1:])]
    for start, end in [*gaps, (bars[-1]["close_time_ms"] + 1, before_ms - 1)]:
        assert start > end or declared(start, end), (start, end)
    return [item for item in ranges if item["reason"] == "market_closed"]


def _replay(tmp_path):
    archive = tmp_path / "archive"
    return ReplayService(settings=replace(replay_settings(tmp_path / "replay.db"),
        replay_history_archive_dir=archive, controller_ttl_seconds=10),
        store=ReplaySQLiteStore(tmp_path / "replay.db"), repository=ReplayHistoryRepository(archive),
        native_intervals=lambda _: ("1m",))


@asynccontextmanager
async def _stock_run(tmp_path, xnys, *, disclosure="NONE", progressive=False, origin=None):
    """An AAPL run from five bars before Tuesday's close, stepped ten bars into Wednesday.

    Yields (replay, preparation, session, shift, after): ``shift`` is the blind
    clock's offset and ``after`` the state once stepped.
    """
    replay = _replay(tmp_path)
    await replay.start()
    values = {}

    class Coordinator:
        async def request_and_wait(self, repair):
            for open_ms in xnys.expected_opens(repair.start_ms, repair.end_ms, "1m"):
                values[open_ms] = _row(open_ms)

    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
        query=lambda *args, **kw: [values[t] for t in sorted(values) if kw["start_ms"] <= t <= kw["end_ms"]],
        calendar_for=lambda symbol, interval, **route: xnys)
    preparation = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await preparation.start()
    if origin is not None:
        replay.history_context = ReplayHistoryContext(preparation, origin_resolver=origin)
    try:
        # Five bars before Tuesday's close; 30 forward bars reach 25 into Wednesday.
        setup = {**_setup_payload(), "settlement_asset": "USD", "requested_start_ms": TUE_LAST - 4 * MINUTE,
                 "indicator_warmup_bars": 90, "forward_cache_ms": 30 * MINUTE,
                 "visible_history_lookback": {"mode": "ALL_AVAILABLE", "duration_ms": None},
                 "time_disclosure_policy": disclosure}
        app = FastAPI(); app.state.data_preparation_service = preparation; app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/replay", json={
                "idempotency_key": "stock-overnight", "setup": setup, "identity": STOCK,
                "exchange": "twelvedata", "market_type": "stock", "symbol": "AAPL:NASDAQ",
                "progressive": progressive})
        assert response.status_code == 202, response.text
        job = await terminal(preparation, response.json()["id"])
        assert job["state"] == "READY", {k: job.get(k) for k in ("error", "result", "chunks")}
        # A progressive request is prepared whole: the feed publishes fixed minute ranges.
        assert job["request"]["progressive"] is False
        session = job["result"]["run"]["adapter_session_id"]
        state = await replay.get_session_state(session)
        start = state["cursor"]["virtual_time_ms"]
        # A blind run shows a shifted clock; the bars and the closure keep their spacing.
        shift = start - (TUE_LAST - 4 * MINUTE)
        assert (shift == 0) == (disclosure == "NONE")
        acquired = await replay.command(session, _command("owner", CommandType.ACQUIRE_CONTROLLER,
                                                          revision=state["revision"]))
        await replay.command(session, _command("cross", CommandType.STEP,
                                               revision=acquired["revision"], payload={"count": 10}))
        after = await replay.get_session_state(session)
        # Five bars finish Tuesday; the next five are Wednesday's first.
        assert after["cursor"]["virtual_time_ms"] - shift == WED_OPEN + 5 * MINUTE - 1
        yield replay, preparation, session, shift, after
    finally:
        await preparation.shutdown(); await replay.shutdown()


@async_test
@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("disclosure", ["NONE", "HIDE_ALL"])
async def test_a_stock_replay_steps_over_the_overnight_closure(tmp_path, xnys, disclosure, progressive):
    async with _stock_run(tmp_path, xnys, disclosure=disclosure, progressive=progressive) as run:
        replay, preparation, session, shift, after = run
        boundary = after["cursor"]["virtual_time_ms"]

        # The revealed chart: Wednesday's first minutes follow Tuesday's close directly.
        args = dict(track_id="track-1", revealed_boundary_ms=boundary, data_epoch=after["data_epoch"])
        page = await replay.training.history_page(session, before_ms=boundary + 1, limit=12, history_epoch=None,
                                                  display_interval="1m", **args)
        opens = [bar["open_time_ms"] - shift for bar in page["bars"]]
        assert opens[-6:] == [TUE_LAST] + [WED_OPEN + index * MINUTE for index in range(5)]
        [overnight] = _connected(page, boundary + 1)
        assert (overnight["start_ms"] - shift, overnight["end_ms"] - shift) == (TUE_LAST + MINUTE, WED_OPEN - 1)
        # A 1h chart: Tuesday's last hour is closed; Wednesday's 14:00 UTC hour
        # (trading from 14:30) forms from its first five bars.
        hourly = await replay.training.display_projection(session, limit=4, display_interval="1h", **args)
        previous, tail = hourly["bars"][-2:]
        assert previous["is_closed"] and previous["component_count"] == previous["expected_components"] == 60
        assert not tail["is_closed"] and tail["component_count"] == 5 and tail["expected_components"] == 30
        assert tail["open_time_ms"] - previous["open_time_ms"] == 18 * 3_600_000
        assert tail["first_base_open_ms"] - tail["open_time_ms"] == 30 * MINUTE
        if disclosure == "NONE":
            assert tail["open_time_ms"] == WED_OPEN - 30 * MINUTE

        # Older chart history comes from the market's own series, closures skipped.
        replay.history_context = ReplayHistoryContext(preparation)
        older = await replay.training.history_page(session, before_ms=boundary + 1, limit=500, history_epoch=None,
                                                   display_interval="1m", **args)
        opens = [bar["open_time_ms"] - shift for bar in older["bars"]]
        assert len(opens) == 500 and opens == sorted(opens) and older["has_more"]
        assert all(xnys.count_expected(open_ms, open_ms, "1m") == 1 for open_ms in opens)
        assert opens[opens.index(TUE_OPEN) - 1] == TUE_LAST - DAY
        assert len(_connected(older, boundary + 1)) == 2
        # Hours before the replay: Monday's last hour sits right before Tuesday's
        # 14:00 UTC hour, which trades from 14:30.
        hours = await replay.training.history_page(session, before_ms=tail["open_time_ms"], limit=10,
                                                   history_epoch=None, display_interval="1h", **args)
        bars = hours["bars"]
        assert len(bars) == 10 and all(bar["is_closed"] for bar in bars)
        # Monday night, and Tuesday night up to the forming Wednesday hour.
        assert len(_connected(hours, tail["open_time_ms"])) == 2
        steps = [later["open_time_ms"] - earlier["open_time_ms"] for earlier, later in zip(bars, bars[1:])]
        assert sorted(set(steps)) == [HOUR, 18 * HOUR] and steps.count(18 * HOUR) == 1
        opening = bars[steps.index(18 * HOUR) + 1]
        assert opening["component_count"] == opening["expected_components"] == 30
        assert opening["first_base_open_ms"] - opening["open_time_ms"] == 30 * MINUTE
        assert all(bar["component_count"] == bar["expected_components"] == 60
                   for bar in bars if bar is not opening)
        if disclosure == "NONE":
            # The forming week counts only the minutes it trades: Thanksgiving
            # and Friday's early close are not missing bars.
            weekly = await replay.training.display_projection(session, limit=4, display_interval="1w", **args)
            week = weekly["bars"][-1]
            assert not week["is_closed"] and week["component_count"] == 2 * 390 + 5
            assert week["expected_components"] == xnys.count_expected(
                week["open_time_ms"], week["close_time_ms"], "1m") < 5 * 390
        revision = after["revision"]

    # A reopened run rebuilds the same calendar schedule and keeps stepping.
    replay = _replay(tmp_path)
    await replay.start()
    try:
        reopened = await replay.get_session_state(session)
        assert reopened["cursor"]["virtual_time_ms"] == boundary
        acquired = await replay.command(session, _command("owner-2", CommandType.ACQUIRE_CONTROLLER,
                                                          revision=reopened["revision"]))
        await replay.command(session, _command("more", CommandType.STEP,
                                               revision=acquired["revision"], payload={"count": 5}))
        assert (await replay.get_session_state(session))["cursor"]["virtual_time_ms"] - shift == WED_OPEN + 10 * MINUTE - 1
        assert revision <= acquired["revision"]
    finally:
        await replay.shutdown()


@async_test
@pytest.mark.parametrize("display_math", ["canonical", "viewport-v1"])
@pytest.mark.parametrize("interval", ["1m", "1h"])
@pytest.mark.parametrize("disclosure", ["NONE", "HIDE_ALL"])
async def test_indicators_carry_on_across_closures(tmp_path, xnys, interval, display_math, disclosure):
    """ADR-DATA-002 D2b2: an RSI or MA over traded bars never restarts at a closure."""
    async def monday_open(identity, frozen_start):
        return TUE_OPEN - DAY

    async with _stock_run(tmp_path, xnys, disclosure=disclosure, origin=monday_open) as run:
        replay, _, session, shift, after = run
        boundary = after["cursor"]["virtual_time_ms"]
        args = dict(track_id="track-1", revealed_boundary_ms=boundary, data_epoch=after["data_epoch"],
                    display_interval=interval)
        cursor = boundary + 1
        if interval == "1h":
            projection = await replay.training.display_projection(session, limit=1, **args)
            cursor = projection["bars"][-1]["open_time_ms"]
        # The chart's window straddles a closure: Tuesday night for 1m, Monday night for 1h.
        recent = await replay.training.history_page(session, before_ms=cursor, limit=20, history_epoch=None, **args)
        window = recent["bars"][-13:] if interval == "1m" else recent["bars"][-9:]
        steps = {later["open_time_ms"] - earlier["close_time_ms"] for earlier, later in zip(window, window[1:])}
        assert len(steps) == 2 and 1 in steps
        # The first computation pins the origin; the chart then reloads its history.
        with pytest.raises(TrainingRunError) as reload:
            await replay.training.canonical_indicator_compute(
                session, name="RSI", params={"period": 5}, bars=window, display_math=display_math, **args)
        assert reload.value.details["reload_history"] is True
        recent = await replay.training.history_page(session, before_ms=cursor, limit=20, history_epoch=None, **args)
        assert recent["history_epoch"] == reload.value.details["history_epoch"]
        assert recent["bars"][-len(window):] == window
        results = {}
        for name, params in [("RSI", {"period": 5}), ("MA", {"period": 6})]:
            async def compute():
                return await replay.training.canonical_indicator_compute(
                    session, name=name, params=params, bars=window, display_math=display_math,
                    history_epoch=recent["history_epoch"], **args)
            result = await compute()
            for _ in range(16):
                if result["status"] == "ready":
                    break
                result = await compute()
            assert result["status"] == "ready", result
            results[name] = (params, result)
        # Canonical math seeds from the market's origin (Monday's open, pinned by
        # computing); viewport math from a fixed warmup of traded bars. Either
        # way the reference input is the chart's own closed bars, closures skipped.
        canonical = display_math == "canonical"
        warmup = max(replay_display_warmup_bars(name, math_parameters(name, params))
                     for name, (params, _) in results.items())
        history, epoch = [], None
        for _ in range(8):
            page = await replay.training.history_page(session, before_ms=cursor, limit=1000,
                                                      history_epoch=epoch, **args)
            epoch = page["history_epoch"]
            history = page["bars"] + history
            if not page["has_more"] or (not canonical and len(history) > len(window) + warmup):
                break
            assert page["next_before_ms"] < cursor
            cursor = page["next_before_ms"]
        else:
            raise AssertionError("history did not reach its origin")
        if canonical and (disclosure == "NONE" or interval == "1m"):
            # Monday's 14:00 UTC hour holds the origin, so the first full hour is 15:00.
            # (Blind hours map through their own bucket anchor, not the 1m clock shift.)
            first = TUE_OPEN - DAY + (30 * MINUTE if interval == "1h" else 0)
            assert history[0]["open_time_ms"] - shift == first
        assert history[-len(window):] == window
        times = {bar["open_time_ms"] // 1000 for bar in window}
        for name, (params, result) in results.items():
            inputs = history
            if canonical:
                assert result["seed"]["origin_ms"] == history[0]["open_time_ms"]
            else:
                inputs = history[-(len(window) + replay_display_warmup_bars(name, math_parameters(name, params))):]
            expected = reference(name, params, [ReplayDisplayBar.from_dict(bar) for bar in inputs])
            assert lines(result["payload"]) == [
                (line, [point for point in points if point["time"] in times]) for line, points in lines(expected)
            ], (name, params)


# --- the pieces underneath -------------------------------------------------

def _apple():
    from app.data_engine.series_identity import identity_from_mapping
    from app.replay.catalog import ReplaySeriesIdentity
    return ReplaySeriesIdentity("twelvedata", "stock", "AAPL:NASDAQ",
                                series=identity_from_mapping("twelvedata", STOCK))


def _archive_batch(opens, key):
    from app.replay.history_archive import ReplayHistoryImportBatch
    from tests.fixtures.replay.fakes import make_bar
    return ReplayHistoryImportBatch(rows=[make_bar(open_ms, source="twelvedata") for open_ms in opens],
                                    source_provider="automatic_host_history_snapshot",
                                    source_object_key=key, source_period=key)


def test_the_schedule_steps_from_one_session_to_the_next(xnys):
    from app.replay.bars.schedule import ReplayBarSchedule
    from app.replay.errors import ReplayDomainError

    grid = ReplayBarSchedule("1m")
    schedule = ReplayBarSchedule("1m", (), xnys)
    assert schedule.next_expected_open(TUE_LAST) == WED_OPEN
    assert grid.next_expected_open(TUE_LAST) == TUE_LAST + MINUTE
    assert not schedule.is_expected_open(TUE_LAST + MINUTE) and schedule.is_expected_open(WED_OPEN)
    assert schedule.next_expected_at_or_after(TUE_LAST + MINUTE) == WED_OPEN
    assert schedule.nth_expected_open(TUE_LAST - 4 * MINUTE, 10) == WED_OPEN + 5 * MINUTE
    assert schedule.expected_count(TUE_OPEN, WED_OPEN + 390 * MINUTE) == 780
    assert schedule.expected_bounds(WED_OPEN - 30 * MINUTE, WED_OPEN + 30 * MINUTE) == (30, WED_OPEN, WED_OPEN + 29 * MINUTE)
    [tuesday, wednesday] = schedule.segments(TUE_LAST - 4 * MINUTE, WED_OPEN + 4 * MINUTE)
    assert (tuesday.start_open_ms, tuesday.end_open_ms, tuesday.count) == (TUE_LAST - 4 * MINUTE, TUE_LAST, 5)
    assert (wednesday.start_open_ms, wednesday.count) == (WED_OPEN, 5)
    # Crypto keeps its exact schedule identity; the calendar only enters a stock's.
    assert grid.gap_policy == "reject" and schedule.gap_policy == "trading_calendar_v1"
    assert grid.fingerprint == ReplayBarSchedule("1m").fingerprint != schedule.fingerprint
    with pytest.raises(ReplayDomainError):
        ReplayBarSchedule("1M", (), xnys)


def test_archive_gaps_count_only_traded_minutes(tmp_path, xnys):
    from app.replay.history_archive import (
        REPLAY_HISTORY_CALENDAR_ID, ReplayHistoryArchiveError, ReplayHistoryArchiveWriter, ReplayHistoryRepository)

    tuesday = [TUE_LAST - offset * MINUTE for offset in reversed(range(10))]
    wednesday = [WED_OPEN + offset * MINUTE for offset in range(3, 10)]  # 14:30-14:32 missing
    writer = ReplayHistoryArchiveWriter(tmp_path / "archive", now_ms=lambda: WED_OPEN + 86_400_000)
    # Archived before its calendar was known: the continuous grid, so the night is a gap.
    older = writer.import_batches(_apple(), "1m", [_archive_batch(tuesday, "tue")])
    assert older.calendar_id == REPLAY_HISTORY_CALENDAR_ID
    manifest = writer.import_batches(_apple(), "1m", [_archive_batch(wednesday, "wed")],
                                     calendar_id=EXCHANGE_DATE_CALENDAR_ID)
    assert manifest.calendar_id == EXCHANGE_DATE_CALENDAR_ID
    scan = ReplayHistoryRepository(tmp_path / "archive").scan_gaps(
        "AAPL:NASDAQ", "1m", exchange="twelvedata", market_type="stock")
    # The night is not a gap; Wednesday's three missing opening minutes are.
    assert scan["calendar_id"] == EXCHANGE_DATE_CALENDAR_ID
    assert [(gap["start_ms"], gap["end_ms"], gap["missing_bars"]) for gap in scan["gaps"]] == [
        (WED_OPEN, WED_OPEN + 2 * MINUTE, 3)]
    # A route-only import keeps the market's calendar; a different one is refused.
    from app.replay.catalog import ReplaySeriesIdentity
    extended = writer.import_batches(ReplaySeriesIdentity("twelvedata", "stock", "AAPL:NASDAQ"), "1m",
                                     [_archive_batch([WED_OPEN + 10 * MINUTE], "later")])
    assert extended.calendar_id == EXCHANGE_DATE_CALENDAR_ID
    with pytest.raises(ReplayHistoryArchiveError, match="another trading calendar"):
        writer.import_batches(_apple(), "1m", [_archive_batch([WED_OPEN + 11 * MINUTE], "x")],
                              calendar_id=REPLAY_HISTORY_CALENDAR_ID)


def test_catalog_starts_are_session_ranges(xnys):
    from app.replay.catalog import ReplayCatalog

    # History from Tuesday 20:00 through Wednesday 15:00, no gaps: 60 + 30 bars.
    ranges = ReplayCatalog._eligible_ranges(
        "1m", interval_ms=MINUTE, earliest_ms=TUE_LAST - 59 * MINUTE, latest_ms=WED_OPEN + 29 * MINUTE,
        gaps=(), warmup_bars=50, replay_bars=20, calendar=xnys)
    assert [(item.first_start_ms, item.last_start_ms, item.count) for item in ranges] == [
        (TUE_LAST - 9 * MINUTE, TUE_LAST, 10),         # 50 warmup bars on Tuesday
        (WED_OPEN, WED_OPEN + 10 * MINUTE, 11),        # 20 forward bars end by 14:59
    ]
    window = ranges[0].materialize(9)  # start at Tuesday's last bar
    assert (window.warmup_start_ms, window.replay_start_ms, window.replay_end_open_ms) == (
        TUE_LAST - 50 * MINUTE, TUE_LAST, WED_OPEN + 18 * MINUTE)
    # The same history on the grid has no start whose forward bars fit before the night.
    grid = ReplayCatalog._eligible_ranges(
        "1m", interval_ms=MINUTE, earliest_ms=TUE_LAST - 59 * MINUTE, latest_ms=TUE_LAST,
        gaps=(), warmup_bars=50, replay_bars=20)
    assert grid == ()
