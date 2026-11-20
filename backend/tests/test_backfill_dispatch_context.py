"""A dispatched chunk never runs in its dispatcher's context (fence and budget ContextVars).

asyncio.create_task and loop.call_later copy the caller's context. The
scheduler dispatches from wherever a drain runs: a submit inside another
run's acquisition scope, a finished chunk's task, a timer scheduled there.
A chunk that inherited that scope planned against the other run's floor
(revision 1 on the four-chart bench, so every replan of a held 10007m
target was rejected) and could match the other run's captured write views.
"""
from __future__ import annotations

import asyncio

from app.data_engine.data_manager import finer_work_hold as fwh
from app.data_engine.data_manager.backfill_contracts import RepairOutcome
from app.data_engine.memory_budget import _work_leases
from app.data_engine.storage.mixed_history_fence import _current as mixed_computations
from app.data_engine.storage.revisions import Acquisition, acquisition_scope, current_acquisition
from tests.test_backfill_batch_ownership import scheduler_for
from tests.test_finer_work_hold import LAST, WIDTH, mixed, settle, short, utc


def ambient():
    return current_acquisition(), mixed_computations.get(), _work_leases.get()


def test_a_chunk_submitted_inside_a_run_does_not_inherit_its_scope():
    async def run():
        seen = []

        async def execute(req):
            seen.append(ambient())
            return RepairOutcome(request=req, status="completed")

        scheduler = scheduler_for(execute, concurrency=0)
        token = mixed_computations.set(("another run's computation",))
        try:
            with acquisition_scope(Acquisition(1)):
                scheduler.submit(short(utc(2026, 11, 6, 18, 17), utc(2026, 11, 7, 16, 32)))
        finally:
            mixed_computations.reset(token)
        await settle()
        assert seen and all(item == (None, (), None) for item in seen), seen
        await scheduler.shutdown()
    asyncio.run(run())


def test_a_held_target_dispatched_by_a_drain_timer_starts_without_its_scheduler_s_scope(monkeypatch):
    """loop.call_later keeps the context the hold's wake-up was scheduled in."""
    monkeypatch.setattr(fwh, "SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(fwh, "MAX_HOLD_SECONDS", 0.05)

    async def run():
        seen, release = [], asyncio.Event()

        async def execute(req):
            if req.interval == "89m":
                await release.wait()
            else:
                seen.append((req.start_ms, ambient()))
            return RepairOutcome(request=req, status="completed")

        scheduler = scheduler_for(execute, concurrency=0)
        with acquisition_scope(Acquisition(1)):
            scheduler.submit(short(utc(2026, 11, 6, 18, 17), utc(2026, 11, 7, 16, 32)))
            scheduler.submit(mixed())
        await asyncio.sleep(0.15)
        await settle()
        held = [scope for start, scope in seen if start >= LAST - WIDTH]
        assert scheduler.finer_work_hold_timeouts == 2 and len(held) == 2
        assert all(item == (None, (), None) for item in held), seen
        release.set()
        await settle()
        await scheduler.shutdown()
    asyncio.run(run())
