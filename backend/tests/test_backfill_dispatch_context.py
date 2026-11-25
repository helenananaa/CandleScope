"""A dispatched chunk never runs in its dispatcher's context (ADR-DATA-001 S3).

asyncio.create_task and loop.call_later copy the caller's context. The
scheduler dispatches from wherever a drain runs: a submit inside another
run's acquisition scope, a finished chunk's task, a timer scheduled there.
fenced_acquisition reuses a scope it finds (it is meant for nested runs), so a
chunk that inherited one planned against the other run's floor and accepted
revisions, and could match its captured write views, fetch gates and memory
leases. Salvaged from the parked stack (d0221e1e6, #511).
"""
from __future__ import annotations

import asyncio
import time

from app.data_engine.backfill.fetcher import _SIBLING_GATES
from app.data_engine.data_manager.backfill_contracts import RepairOutcome, RepairRequest
from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
from app.data_engine.memory_budget import _work_leases
from app.data_engine.storage.derived_history_fence import _computation as derived_computations
from app.data_engine.storage.revisions import Acquisition, _acquisition, acquisition_scope

CLEAN = (None, (), None, None)


def ambient():
    return _acquisition.get(), derived_computations.get(), _work_leases.get(), _SIBLING_GATES.get()


def scheduler_for(execute) -> BackfillScheduler:
    futures: dict[str, asyncio.Future] = {}

    def future_for(request):
        if request.request_id not in futures:
            futures[request.request_id] = asyncio.get_running_loop().create_future()
        return futures[request.request_id]

    async def finalize(request, outcome):
        return None

    def complete(request, outcome):
        future = future_for(request)
        if not future.done():
            future.set_result(outcome)

    return BackfillScheduler(
        execute=execute, future_for=future_for, finalize=finalize, complete=complete,
        on_queued=lambda request: None,
    )


def request(request_id: str) -> RepairRequest:
    return RepairRequest(
        exchange="binance", market_type="futures", symbol="BTCUSDT", interval="1m",
        start_ms=1_700_000_000_000, end_ms=1_700_000_000_000 + 59 * 60_000,
        request_id=request_id, reason="initial_history",
    )


async def settle(scheduler: BackfillScheduler, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.01)
        if not scheduler._tasks and not scheduler._ready:
            return
    raise AssertionError("scheduler did not settle")


def test_a_chunk_submitted_inside_another_run_does_not_inherit_its_scope():
    async def run():
        seen = []

        async def execute(req):
            seen.append(ambient())
            return RepairOutcome(request=req, status="completed")

        scheduler = scheduler_for(execute)
        computation = derived_computations.set(("another run's computation",))
        leases = _work_leases.set(object())
        gates = _SIBLING_GATES.set({"another fetch": asyncio.Semaphore(1)})
        try:
            with acquisition_scope(Acquisition(1)):
                scheduler.submit(request("inside-scope"))
        finally:
            _SIBLING_GATES.reset(gates)
            _work_leases.reset(leases)
            derived_computations.reset(computation)
        await settle(scheduler)
        assert seen and all(item == CLEAN for item in seen), seen
        await scheduler.shutdown()

    asyncio.run(run())


def test_a_chunk_dispatched_by_a_drain_timer_does_not_inherit_the_timer_s_scope():
    """loop.call_later keeps the context the deferred drain was scheduled in."""

    async def run():
        seen = []

        async def execute(req):
            seen.append(ambient())
            return RepairOutcome(request=req, status="completed")

        scheduler = scheduler_for(execute)
        first = request("timer")
        # The local dispatch bucket is cooling down, so the submit's drain
        # schedules a timer from inside the scope instead of dispatching.
        scheduler._bucket_for(first).cooldown_until_ms = int(time.time() * 1000) + 50
        with acquisition_scope(Acquisition(1)):
            scheduler.submit(first)
        assert not seen and scheduler._drain_timer is not None
        await settle(scheduler)
        assert seen and all(item == CLEAN for item in seen), seen
        await scheduler.shutdown()

    asyncio.run(run())
