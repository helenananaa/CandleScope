"""A mixed chunk's targets wait for another chart's finer history (data_manager/finer_work_hold.py)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.data_engine.data_manager import finer_work_hold as fwh
from app.data_engine.data_manager.backfill_contracts import RepairOutcome, RepairRequest
from tests.test_backfill_batch_ownership import scheduler_for

MINUTE, DAY = 60_000, 86_400_000
WIDTH = 10007 * MINUTE
CONTRACT = "binance.usdm.trade-klines/base-utc/1"
# The bench's newest 10007m chunk: 16 targets, the last opening 2026-11-07 12:36.
LAST = int(datetime(2026, 11, 7, 12, 36, tzinfo=timezone.utc).timestamp() * 1000)
FIRST = LAST - 15 * WIDTH


def utc(*parts):
    return int(datetime(*parts, tzinfo=timezone.utc).timestamp() * 1000)


def mixed(start=FIRST, end=LAST, interval="10007m", reason="initial_history"):
    return RepairRequest("BTCUSDT", interval, start, end, market_type="futures", reason=reason,
                         metadata={"required_history_composition": CONTRACT})


def short(start, end, interval="89m", reason="initial_history", base="1m"):
    return RepairRequest("BTCUSDT", interval, start, end, market_type="futures", reason=reason,
                         metadata={"bounded_history_batch_contract": CONTRACT,
                                   "interval_work_plan": {"base_interval": base}})


def test_a_finer_chart_reaches_the_archive_objects_its_base_may_import():
    # 1m: a month does not fit one object, so whole UTC days.
    assert fwh.reach(short(utc(2026, 11, 6, 16, 57), utc(2026, 11, 7, 16, 32))) == (
        89 * MINUTE, utc(2026, 11, 6), utc(2026, 11, 8))
    # 1h: whole UTC months.
    assert fwh.reach(short(utc(2026, 10, 30), utc(2026, 11, 2), interval="4h", base="1h")) == (
        4 * 3_600_000, utc(2026, 10, 1), utc(2026, 12, 1))
    # Mixed chunks never hold another chunk.
    assert fwh.reach(mixed()) is None


def test_only_targets_a_finer_chart_reaches_are_held_each_on_its_own():
    reaches = [fwh.reach(short(utc(2026, 11, 6, 16, 57), utc(2026, 11, 20, 8, 37)))[1:]]
    ranges = fwh.partition(mixed(), reaches)
    # The last two targets (2026-10-31 13:49 and 2026-11-07 12:36) reach 2026-11-06.
    assert ranges == [(FIRST, LAST - 2 * WIDTH, False), (LAST - WIDTH, LAST - WIDTH, True), (LAST, LAST, True)]
    assert fwh.partition(mixed(), [(utc(2026, 11, 20), utc(2026, 11, 21))]) is None
    assert fwh.partition(mixed(), []) is None
    plain = RepairRequest("BTCUSDT", "10007m", FIRST, LAST, market_type="futures", reason="initial_history")
    assert fwh.partition(plain, reaches) is None


async def settle(rounds=40):
    for _ in range(rounds):
        await asyncio.sleep(0)


def runner(blocked):
    calls, release = [], asyncio.Event()
    async def execute(req):
        calls.append((req.interval, req.start_ms, req.end_ms))
        if req.interval in blocked:
            await release.wait()
        return RepairOutcome(request=req, status="completed")
    return calls, release, execute


def test_the_targets_a_short_chart_writes_into_wait_for_it_and_the_rest_runs_at_once(monkeypatch):
    monkeypatch.setattr(fwh, "SETTLE_SECONDS", 0.0)
    async def run():
        calls, release, execute = runner({"89m"})
        scheduler = scheduler_for(execute, concurrency=0)
        scheduler.submit(short(utc(2026, 11, 6, 18, 17), utc(2026, 11, 7, 16, 32)))
        scheduler.submit(mixed())
        await settle()
        mixed_calls = [call for call in calls if call[0] == "10007m"]
        assert mixed_calls == [("10007m", FIRST, LAST - 2 * WIDTH)]
        assert scheduler.finer_work_splits == 1 and scheduler.finer_work_holds == 2
        release.set()
        await settle()
        assert sorted(call for call in calls if call[0] == "10007m") == [
            ("10007m", FIRST, LAST - 2 * WIDTH), ("10007m", LAST - WIDTH, LAST - WIDTH), ("10007m", LAST, LAST)]
        assert scheduler.mixed_chunk_refinements == 0 and scheduler.finer_work_hold_timeouts == 0
        await scheduler.shutdown()
    asyncio.run(run())


def test_a_held_target_runs_as_today_once_it_has_waited_its_longest(monkeypatch):
    monkeypatch.setattr(fwh, "MAX_HOLD_SECONDS", 0.05)
    monkeypatch.setattr(fwh, "SETTLE_SECONDS", 0.0)
    async def run():
        calls, release, execute = runner({"89m"})
        scheduler = scheduler_for(execute, concurrency=0)
        scheduler.submit(short(utc(2026, 11, 7, 18, 1), utc(2026, 11, 8, 16, 16)))
        scheduler.submit(mixed())
        await settle()
        assert ("10007m", LAST, LAST) not in calls
        await asyncio.sleep(0.15)
        await settle()
        assert ("10007m", LAST, LAST) in calls
        assert scheduler.finer_work_hold_timeouts == 2  # both held targets
        release.set()
        await settle()
        await scheduler.shutdown()
    asyncio.run(run())


def test_background_finer_work_and_other_mixed_charts_never_hold_a_mixed_chunk(monkeypatch):
    monkeypatch.setattr(fwh, "SETTLE_SECONDS", 0.0)
    async def run():
        calls, release, execute = runner({"89m", "20011m", "1w"})
        scheduler = scheduler_for(execute, concurrency=0)
        scheduler.submit(short(utc(2026, 11, 6), utc(2026, 11, 7), reason="active_history_hydration"))
        scheduler.submit(short(utc(2026, 9, 7), utc(2026, 11, 9), interval="1w", base="1d"))
        wide = 20011 * MINUTE
        scheduler.submit(mixed(LAST // wide * wide - 2 * wide, LAST // wide * wide, interval="20011m"))
        scheduler.submit(mixed())
        await settle()
        # Dispatched whole. (The 1w chart, narrower than 20011m, may hold that one.)
        assert [call for call in calls if call[0] == "10007m"] == [("10007m", FIRST, LAST)]
        release.set()
        await settle()
        await scheduler.shutdown()
    asyncio.run(run())


def test_a_mixed_chart_opened_just_before_a_short_one_still_waits_for_it(monkeypatch):
    monkeypatch.setattr(fwh, "SETTLE_SECONDS", 0.1)
    async def run():
        calls, release, execute = runner({"89m"})
        scheduler = scheduler_for(execute, concurrency=0)
        # One request of 32 targets: two chunks.
        scheduler.submit(mixed(FIRST - 16 * WIDTH, LAST))
        await settle()
        # Only the newest chunk of a chart's initial history waits; an older one runs.
        assert ("10007m", FIRST - 16 * WIDTH, FIRST - WIDTH) in calls
        assert not [call for call in calls if call[1] >= FIRST]
        await asyncio.sleep(0.02)
        scheduler.submit(short(utc(2026, 11, 6, 18, 17), utc(2026, 11, 7, 16, 32)))
        await asyncio.sleep(0.15)
        await settle()
        assert ("10007m", FIRST, LAST - 2 * WIDTH) in calls and ("10007m", LAST, LAST) not in calls
        assert scheduler.finer_work_settles == 1 and scheduler.finer_work_splits == 1
        release.set()
        await settle()
        assert ("10007m", LAST, LAST) in calls
        await scheduler.shutdown()
    asyncio.run(run())


def test_a_held_target_the_finer_rows_only_partly_cover_still_plans_on_its_own(tmp_path, monkeypatch):
    """The bench's 2026-10-31 13:49 target, released after the short charts stored 1m from 2026-11-06 16:57.

    Composed from 1m, it needs one REST page more than fetching the target whole;
    a required composition has no single-base fallback, so it must keep its plan.
    """
    import random

    from app.data_engine.backfill import mixed_routes
    from app.data_engine.backfill.models import GapInfo, GapType
    from tests.test_mixed_history_session import bar, manager_for
    from tests.test_mixed_routes import catalog, plan_chunk

    now = utc(2026, 11, 20, 8, 40)
    monkeypatch.setattr(mixed_routes, "archive_catalog", lambda engine: catalog())
    monkeypatch.setattr("app.data_engine.backfill.mixed_plan.time.time", lambda: now / 1000)
    rng = random.Random(1)
    stored = [bar(at, MINUTE, rng) for at in range(utc(2026, 11, 6, 16, 57), now - 2 * 3_600_000, MINUTE)]
    manager = manager_for(tmp_path / "held.sqlite", {("1m", "backfill"): stored}, monkeypatch)
    try:
        from tests.test_mixed_backfill_plan import engine_for
        engine = engine_for(manager.query_engine)
        target = LAST - WIDTH
        plan, report = plan_chunk(manager, engine, target, target + WIDTH)
        assert plan is not None, report.get("mixed_plan_fallback")
        assert report["mixed_rest_requests_over_baseline"] >= 1
        # Every row it plans to write stays inside the target (whole archive
        # objects included); the engine's minute reuse trims what is stored.
        assert plan.tasks and all(target <= task.start_ms and task.end_ms < target + WIDTH for task in plan.tasks)
    finally:
        import asyncio as _asyncio
        _asyncio.run(manager.shutdown())
