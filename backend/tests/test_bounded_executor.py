from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar

import pytest

from app.core.bounded_executor import BoundedExecutor, ExecutorBusyError
from app.core.executors import _run


def test_capacity_cancel_reclaims_queue_and_metrics_settle():
    pool = BoundedExecutor("test", max_workers=1, max_pending=2)
    gate, started = threading.Event(), threading.Event()
    def block():
        started.set()
        assert gate.wait(5)
    try:
        running = pool.submit(block)
        assert started.wait(2)
        first, second = pool.submit(lambda: 1), pool.submit(lambda: 2)
        with pytest.raises(ExecutorBusyError):
            pool.submit(lambda: 3)
        assert first.cancel()
        # Cancellation must remove the queue entry, not accumulate tombstones
        # in ThreadPoolExecutor while a long-running operation occupies it.
        for _ in range(200):
            assert pool.submit(lambda: None).cancel()
        snapshot = pool.snapshot()
        assert snapshot["pending"] == snapshot["queued"] == 1
        assert snapshot["cancelled"] == 201
        assert snapshot["rejected"] == 1
        gate.set()
        running.result(2)
        assert second.result(2) == 2
    finally:
        gate.set()
        pool.shutdown()
    snapshot = pool.snapshot()
    assert snapshot["pending"] == snapshot["active"] == 0
    assert snapshot["submitted"] == snapshot["completed"] + snapshot["cancelled"]


def test_running_storage_drains_even_after_repeated_cancellation():
    async def scenario():
        pool = BoundedExecutor("storage-test", max_workers=1, max_pending=1)
        gate, started, committed = threading.Event(), threading.Event(), threading.Event()
        def write():
            started.set()
            assert gate.wait(5)
            committed.set()
        try:
            task = asyncio.create_task(_run(pool, write, drain_on_cancel=True))
            while not started.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
            assert pool.snapshot()["active"] == 1
            gate.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert committed.is_set()
            assert pool.snapshot()["active"] == 0
        finally:
            gate.set()
            pool.shutdown()
    asyncio.run(scenario())


def test_queued_async_cancel_never_executes_and_failed_work_releases_capacity():
    async def scenario():
        pool = BoundedExecutor("test", max_workers=1, max_pending=1)
        gate, started = threading.Event(), threading.Event()
        called = []
        def block():
            started.set()
            assert gate.wait(5)
        try:
            running = pool.submit(block)
            while not started.is_set():
                await asyncio.sleep(0.001)
            queued = asyncio.create_task(_run(pool, lambda: called.append(True), drain_on_cancel=True))
            await asyncio.sleep(0)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            assert pool.snapshot()["pending"] == 0
            gate.set()
            await asyncio.wrap_future(running)
            with pytest.raises(ZeroDivisionError):
                await _run(pool, lambda: 1 / 0)
            assert await _run(pool, lambda: 42) == 42
            assert not called
            assert pool.snapshot()["failed"] == 1
        finally:
            gate.set()
            pool.shutdown()
    asyncio.run(scenario())


def test_worker_preserves_context_without_leaking_to_the_next_call():
    owner = ContextVar("write-budget-owner", default=None)
    async def scenario():
        pool = BoundedExecutor("test", max_workers=1, max_pending=1)
        try:
            token = owner.set("publication")
            assert await _run(pool, owner.get) == "publication"
            owner.reset(token)
            assert await _run(pool, owner.get) is None
        finally:
            pool.shutdown()
    asyncio.run(scenario())
