from __future__ import annotations

import asyncio
from threading import Event

import pytest
from app.replay.training.indicator_jobs import IndicatorPreparationJobs

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("cancel_waiter", [False, True])
async def test_cancellation_drains_active_worker_and_removes_waiters(cancel_waiter):
    jobs = IndicatorPreparationJobs()
    started, release, cancelled = Event(), Event(), Event()
    calls = []

    def slow():
        calls.append("first")
        started.set()
        assert release.wait(5)
        if cancelled.is_set():
            raise InterruptedError("cancelled")
        return "first"

    async def later():
        calls.append("second")
        return "second"

    first = asyncio.create_task(
        jobs.run(("same-prefix",), lambda: asyncio.to_thread(slow), cancelled)
    )
    assert await asyncio.to_thread(started.wait, 5)
    second = asyncio.create_task(jobs.run(("same-prefix",), later, Event()))
    try:
        await asyncio.sleep(0)
        assert calls == ["first"]
        if cancel_waiter:
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done(), (
            "worker cancellation must drain before releasing the lane"
        )
        assert cancelled.is_set()
        assert calls == ["first"]
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        if not cancel_waiter:
            assert await second == "second"
    assert not jobs._waiting


async def test_independent_prefixes_have_two_bounded_background_lanes():
    jobs = IndicatorPreparationJobs()
    started, release = [], asyncio.Event()

    async def work(index):
        started.append(index)
        await release.wait()
        return index

    tasks = [
        asyncio.create_task(
            jobs.run((index,), lambda index=index: work(index), Event())
        )
        for index in range(5)
    ]
    try:
        for _ in range(4):
            await asyncio.sleep(0)
        assert len(started) == 2
    finally:
        release.set()
        assert await asyncio.gather(*tasks) == list(range(5))
    assert not jobs._waiting
