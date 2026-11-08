import asyncio
from dataclasses import replace
import threading

import pytest

from app.data_engine.data_manager.indicator_inputs import IndicatorInputPort
from app.data_engine.data_manager.models import DataEvent, DataEventType
from app.indicator.numeric_queries import NumericIndicatorService
from app.indicator.range_result_service import IndicatorRangeResultService
from tests.test_numeric_indicator_queries import compute, query
from tests.test_shared_blocks_integration import dm, read_rows, write, KEY


def bind_service(dm, query, monkeypatch):
    leases, releases = set(), []

    async def ensure(**kwargs):
        leases.add(kwargs['consumer_id'])

    async def release(**kwargs):
        leases.discard(kwargs['consumer_id'])
        releases.append(kwargs['consumer_id'])

    async def actual(name, meta, bars):
        return compute(name, meta, bars)

    monkeypatch.setattr(dm, 'ensure_stream', ensure)
    monkeypatch.setattr(dm, 'release_stream', release)
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=actual)
    dm.bind_indicator_queries(service)
    original = service.query

    async def bounded(request):
        return await original(replace(request, through_ms=request.through_ms or query.through_ms))

    monkeypatch.setattr(service, 'query', bounded)
    return service, leases, releases


async def cleanup(service, dm, leases):
    # Also unwind the intentionally broken pre-fix counterexample fixture.
    for subscription in tuple(service.subscriptions):
        if subscription.handle is not None:
            await dm.unsubscribe_async(subscription.handle)
        service.subscriptions.discard(subscription)
    leases.clear()
    await service.close()


@pytest.mark.parametrize('check', ['drain', 'retry'])
def test_cancelled_numeric_close_does_not_strand_gc_protected_subscription(dm, query, monkeypatch, check):
    service, leases, releases = bind_service(dm, query, monkeypatch)

    async def run():
        async def ignore(*args):
            pass

        subscription = await service.subscribe(replace(query, through_ms=None), ignore,
            on_recovery=ignore, consumer_id='numeric:cancel-close')
        handle = subscription.handle
        entered, release_guard = threading.Event(), threading.Event()

        def hold_guard():
            with dm._storage_gc_guard:
                entered.set()
                assert release_guard.wait(5)

        thread = threading.Thread(target=hold_guard)
        thread.start()
        closer = None
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            closer = asyncio.create_task(subscription.close())
            await asyncio.sleep(.02)
            closer.cancel()
            await asyncio.sleep(.02)
            if check == 'drain':
                assert not closer.done(), 'Close abandoned the still-registered numeric consumer'
                closer.cancel()
            release_guard.set()
            await asyncio.to_thread(thread.join, 2)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(closer, 2)
            await subscription.close()
            await service.close()
            assert handle.id not in dm.event_bus._callback_subs, 'Retry left the actual event-bus subscriber registered'
            assert not service.subscriptions and not service.queries
            assert not leases and releases == ['numeric:cancel-close']
        finally:
            release_guard.set()
            await asyncio.to_thread(thread.join, 2)
            if closer is not None:
                await asyncio.gather(closer, return_exceptions=True)
            await cleanup(service, dm, leases)
    asyncio.run(run())


@pytest.mark.parametrize('external', [False, True])
def test_numeric_callback_close_preserves_self_and_concurrent_shutdown(dm, query, monkeypatch, external):
    service, leases, releases = bind_service(dm, query, monkeypatch)

    async def run():
        entered, finished, block = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def receive(observation):
            entered.set()
            if external:
                try:
                    await block.wait()
                finally:
                    await subscription.close()
                    finished.set()
            else:
                await subscription.close()
                finished.set()

        async def recovery(error):
            raise AssertionError(error)

        subscription = await service.subscribe(replace(query, through_ms=None), receive,
            on_recovery=recovery, consumer_id='numeric:self-close')
        handle = subscription.handle
        try:
            old = read_rows(dm)[-1]
            changed = replace(old, close=old.close + 1, high=old.high + 1)
            write([changed])
            await dm.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED, KEY, bar=changed))
            await asyncio.wait_for(entered.wait(), 2)
            if external:
                await asyncio.wait_for(subscription.close(), 2)
            await asyncio.wait_for(finished.wait(), 2)
            assert handle.id not in dm.event_bus._callback_subs
            assert not leases and releases == ['numeric:self-close']
            assert not service.subscriptions
        finally:
            block.set()
            await cleanup(service, dm, leases)
    asyncio.run(run())
