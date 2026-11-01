import asyncio
from dataclasses import replace
import threading

import pytest

from app.core.bounded_executor import ExecutorBusyError
from app.data_engine.data_manager.models import BarData
from app.indicator import create_engine
from app.indicator.events import IndicatorEventType
from app.indicator.serial_owner import SerialIndicatorOwner


def bars(count=30):
    return [BarData(time=60 * (i + 1), open=100 + i, high=101 + i,
                    low=99 + i, close=100 + i, volume=10, is_closed=True)
            for i in range(count)]


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.001)


@pytest.mark.asyncio
async def test_state_and_listeners_have_distinct_single_owners_and_match_batch():
    loop_thread = threading.get_ident()
    worker_threads, listener_threads, notices = set(), set(), []

    def factory():
        engine = create_engine()
        worker_threads.add(threading.get_ident())
        for name in ('subscribe', 'on_bar_updated', 'on_bar_closed', 'unsubscribe', 'stop'):
            original = getattr(engine, name)
            def wrapped(*args, original=original, **kwargs):
                worker_threads.add(threading.get_ident())
                return original(*args, **kwargs)
            setattr(engine, name, wrapped)
        return engine

    owner = SerialIndicatorOwner(factory=factory)
    def listener(event):
        listener_threads.add(threading.get_ident())
        notices.append(event)
    owner.add_listener(listener)
    seed = bars()
    reference = create_engine()
    try:
        key, result = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 10}, bars=seed)
        assert result is not None
        committed = replace(seed[-1], time=1860, close=140)
        await owner.call('on_bar_updated', 'BTCUSDT', '1m', replace(committed, is_closed=False))
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', committed)
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', committed)
        actual = await owner.call('get_result', key)
        expected = reference.compute('BTCUSDT', '1m', 'spot', 'EMA', {'period': 10}, seed + [committed])
        assert actual.to_dict()['outputs'] == expected.to_dict()['outputs']
        assert sum(e.event_type == IndicatorEventType.INDICATOR_UPDATED for e in notices) == 1
        assert sum(e.event_type == IndicatorEventType.INDICATOR_PREVIEW for e in notices) == 1
        await owner.call('unsubscribe', key)
    finally:
        reference.stop()
        await owner.aclose()
    assert len(worker_threads) == 1 and loop_thread not in worker_threads
    assert listener_threads == {loop_thread}
    assert owner.snapshot()['serial_owner']['executor']['active'] == 0


@pytest.mark.asyncio
async def test_adoption_precedes_listener_delivery_and_next_command():
    owner = SerialIndicatorOwner()
    adopted, observed = set(), []
    owner.add_listener(lambda event: observed.append(event.key in adopted))
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'MA', {'period': 3},
                                  bars=bars(), adopt=lambda pair: adopted.add(pair[0]))
        assert observed and all(observed)
        result = await owner.call('get_result', key)
        result.outputs.clear()
        assert (await owner.call('get_result', key)).outputs
    finally:
        await owner.aclose()


@pytest.mark.asyncio
async def test_cancelled_running_command_keeps_capacity_and_drains_before_next():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def factory():
        engine = create_engine()
        original = engine.on_bar_closed
        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            calls.append(args[2].time)
            return original(*args, **kwargs)
        engine.on_bar_closed = blocked
        return engine
    owner = SerialIndicatorOwner(factory=factory, max_pending=1)
    first = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(1)[0]))
    try:
        await eventually(entered.is_set)
        first.cancel()
        second = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(2)[-1]))
        await eventually(lambda: owner.snapshot()['serial_owner']['inflight'] == 2)
        assert not first.done() and not second.done()
        with pytest.raises(ExecutorBusyError):
            await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(3)[-1])
        assert owner.snapshot()['serial_owner']['executor']['active'] == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
        assert calls == [60, 120]
        assert owner.snapshot()['serial_owner']['cancelled_running'] == 1
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
        await owner.aclose()


@pytest.mark.asyncio
async def test_queued_cancel_retracts_input_and_finite_admission_without_mutation():
    entered, release = threading.Event(), threading.Event()
    def factory():
        engine = create_engine()
        original = engine.on_bar_closed
        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return original(*args, **kwargs)
        engine.on_bar_closed = blocked
        return engine
    owner = SerialIndicatorOwner(factory=factory, max_pending=2, max_input_bars=10)
    running = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(1)[0]))
    try:
        await eventually(entered.is_set)
        with pytest.raises(ExecutorBusyError):
            await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'MA', {}, bars=bars(10))
        queued = asyncio.create_task(owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'MA', {}, bars=bars(5)))
        await eventually(lambda: owner.snapshot()['serial_owner']['input_bars'] == 6)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert owner.snapshot()['serial_owner']['input_bars'] == 1
        release.set()
        await running
        assert await owner.call('list_instances') == []
    finally:
        release.set()
        await asyncio.gather(running, return_exceptions=True)
        await owner.aclose()


@pytest.mark.asyncio
async def test_unexpected_failure_prevents_reuse_of_uncertain_state():
    def factory():
        engine = create_engine()
        def fail(*args):
            raise RuntimeError('failed halfway through state mutation')
        engine.on_bar_closed = fail
        return engine
    owner = SerialIndicatorOwner(factory=factory)
    try:
        with pytest.raises(RuntimeError, match='halfway'):
            await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(1)[0])
        with pytest.raises(RuntimeError, match='rebuild from canonical'):
            await owner.call('list_instances')
    finally:
        await owner.aclose()


@pytest.mark.asyncio
async def test_failure_also_rejects_commands_already_waiting_for_owner():
    entered, release = threading.Event(), threading.Event()
    def factory():
        engine = create_engine()
        def fail(*args):
            entered.set()
            assert release.wait(3)
            raise RuntimeError('partial mutation')
        engine.on_bar_closed = fail
        return engine
    owner = SerialIndicatorOwner(factory=factory)
    running = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(1)[0]))
    try:
        await eventually(entered.is_set)
        queued = asyncio.create_task(owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'MA', {}, bars=bars()))
        await eventually(lambda: owner.snapshot()['serial_owner']['inflight'] == 2)
        release.set()
        with pytest.raises(RuntimeError, match='partial mutation'):
            await running
        with pytest.raises(RuntimeError, match='rebuild from canonical'):
            await queued
        assert owner.snapshot()['serial_owner']['executor']['started'] == 1
    finally:
        release.set()
        await asyncio.gather(running, return_exceptions=True)
        await owner.aclose()


@pytest.mark.asyncio
async def test_running_subscription_cancel_adopts_for_deterministic_owner_cleanup():
    entered, release = threading.Event(), threading.Event()
    adopted = []
    def factory():
        engine = create_engine()
        original = engine.subscribe
        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return original(*args, **kwargs)
        engine.subscribe = blocked
        return engine
    owner = SerialIndicatorOwner(factory=factory)
    task = asyncio.create_task(owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'MA', {},
                                          bars=bars(), adopt=adopted.append))
    try:
        await eventually(entered.is_set)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(adopted) == 1
        await owner.call('unsubscribe', adopted[0][0])
        assert all(row['refcount'] == 0 for row in owner.snapshot()['instances'])
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await owner.aclose()
