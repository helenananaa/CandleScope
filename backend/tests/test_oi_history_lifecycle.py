import asyncio
from contextlib import contextmanager
import threading

import pytest

from app.data_engine.storage import market_metrics_repo
from tests.test_oi_local_history import async_test, make_service, query, KEY, START, STEP


def hold_sqlite_snapshot(monkeypatch, *, fail=False):
    entered, release, finished = (threading.Event() for _ in range(3))
    original = market_metrics_repo._connect

    @contextmanager
    def held_connection(path):
        connection = original(path)
        try:
            with connection:
                yield connection
                entered.set()
                assert release.wait(5), 'The test must release the physical SQLite reader'
                if fail:
                    raise RuntimeError('physical OI read failed during drain')
        finally:
            connection.close()
            finished.set()

    monkeypatch.setattr(market_metrics_repo, '_connect', held_connection)
    return entered, release, finished


async def wait_for_logical_release(service):
    deadline = asyncio.get_running_loop().time() + 1
    while service._history_tasks:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0)


@pytest.mark.parametrize('read_fails', [False, True])
@async_test
async def test_shutdown_retains_cancelled_query_until_physical_sqlite_read_finishes(tmp_path, monkeypatch, read_fails):
    _, transport, service = make_service(tmp_path, monkeypatch)
    # Complete capability/bootstrap work before timing the held storage read.
    await query(service, mode='local_only')
    entered, release, finished = hold_sqlite_snapshot(monkeypatch, fail=read_fails)
    consumer = asyncio.create_task(query(service, mode='local_only'))
    shutdown = None
    try:
        started = await asyncio.to_thread(entered.wait, 2)
        if not started and consumer.done():
            await consumer  # Surface a startup failure rather than a misleading timeout.
        assert started
        consumer.cancel()
        await wait_for_logical_release(service)
        assert not consumer.done() and not finished.is_set()
        shutdown = asyncio.create_task(service.shutdown())
        await asyncio.sleep(.03)
        assert not shutdown.done(), 'Service shutdown lost the cancelled query still holding SQLite'
        release.set()
        await asyncio.wait_for(shutdown, 2)
        with pytest.raises(asyncio.CancelledError):
            await consumer
        assert finished.is_set() and not transport.calls
        assert service.diagnostics()['history_queries']['owned_jobs'] == 0
        assert service.diagnostics()['history_queries']['identities'] == 0
    finally:
        release.set()
        await asyncio.gather(consumer, return_exceptions=True)
        if shutdown is not None:
            await asyncio.gather(shutdown, return_exceptions=True)
        await service.shutdown()


@async_test
async def test_retiring_physical_query_keeps_its_capacity_until_storage_is_drained(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    await query(service, mode='local_only')
    entered, release, finished = hold_sqlite_snapshot(monkeypatch)
    retiring = asyncio.create_task(query(service, mode='local_only'))
    queued = []
    probe = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        retiring.cancel()
        await wait_for_logical_release(service)
        queued = [asyncio.create_task(service.history_page(KEY, period='5m', mode='local_only',
            start_ms=START, end_ms=START + (index + 6) * STEP)) for index in range(31)]
        await asyncio.sleep(.02)
        assert len(service._history_tasks) == 31
        probe = asyncio.create_task(service.history_page(KEY, period='5m', mode='local_only',
            start_ms=START, end_ms=START + 40 * STEP))
        await asyncio.sleep(.02)
        assert probe.done(), 'Retiring storage work was omitted from the32-query capacity limit'
        rejected = await probe
        assert rejected.retryable and not rejected.complete and rejected.events == []
        assert service.diagnostics()['history_queries']['owned_jobs'] == 32
        assert not finished.is_set() and not transport.calls
    finally:
        for task in [*queued, probe]:
            if task is not None and not task.done():
                task.cancel()
        release.set()
        await asyncio.gather(retiring, *queued, *([probe] if probe else []), return_exceptions=True)
        await service.shutdown()
    assert finished.is_set()
    assert service.diagnostics()['history_queries']['owned_jobs'] == 0
