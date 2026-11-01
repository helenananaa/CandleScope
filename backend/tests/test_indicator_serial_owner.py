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


def revision(number):
    return {'serverEpoch': 'test', 'correctionRevision': number,
            'revisionToken': f'test:{number}', 'closedThrough': 1800}


@pytest.mark.anyio
async def test_corrected_seed_cannot_relabel_an_active_uncorrected_instance():
    from app.indicator.serial_owner import IndicatorInputChanged
    owner = SerialIndicatorOwner()
    old, corrected = bars(), bars()
    corrected[10] = replace(corrected[10], close=900)
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5},
                                  bars=old, data_revision=revision(0))
        with pytest.raises(IndicatorInputChanged):
            await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5},
                             bars=corrected, data_revision=revision(1))
        assert owner.snapshot()['instances'][0]['refcount'] == 1
        await owner.call('on_bars_backfilled', 'BTCUSDT', '1m', corrected, data_revision=revision(1))
        _, actual = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5},
                                     bars=corrected, data_revision=revision(1))
        reference = create_engine()
        expected = reference.compute('BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, corrected)
        assert actual.to_dict()['outputs'] == expected.to_dict()['outputs']
        reference.stop()
        with pytest.raises(IndicatorInputChanged):
            await owner.call('on_bars_backfilled', 'BTCUSDT', '1m', old, data_revision=revision(0))
        assert (await owner.call('get_result', key)).to_dict()['outputs'] == expected.to_dict()['outputs']
    finally:
        await owner.aclose()


@pytest.mark.anyio
async def test_realtime_revision_describes_applied_state_and_out_of_span_cannot_skip_a_revision():
    owner = SerialIndicatorOwner()
    events = []
    owner.add_listener(events.append)
    try:
        await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5},
                         bars=bars(), data_revision=revision(0))
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1], input_revision=revision(1))
        event = [event for event in events if event.event_type == IndicatorEventType.INDICATOR_UPDATED][-1]
        assert event.detail['dataRevision']['revisionToken'] == 'test:0'
        assert event.detail['resyncRequired'] is True
        await owner.call('on_series_correction_invalidated', 'BTCUSDT', '1m',
                         dirty_range={'start': 1, 'end': 2}, data_revision=revision(2))
        assert events[-1].detail['dataRevision']['revisionToken'] == 'test:0'
        assert events[-1].detail['resyncRequired'] is True
        await owner.call('on_bars_backfilled', 'BTCUSDT', '1m', bars(31), data_revision=revision(2))
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(32)[-1], input_revision=revision(2))
        assert events[-1].detail['dataRevision']['revisionToken'] == 'test:2'
        assert not events[-1].detail.get('resyncRequired')
    finally:
        await owner.aclose()


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_queued_old_correction_cannot_erase_a_newly_committed_close():
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
    owner = SerialIndicatorOwner(factory=factory)
    source = bars()
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=source)
        close = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', replace(source[-1], time=1860, close=150)))
        await eventually(entered.is_set)
        correction = asyncio.create_task(owner.call('on_bars_backfilled', 'BTCUSDT', '1m', source,
            dirty_range={'start': 60, 'end': 60}))
        await eventually(lambda: owner.snapshot()['serial_owner']['inflight'] == 2)
        release.set()
        await close
        with pytest.raises(RuntimeError, match='input.*changed'):
            await correction
        assert owner.snapshot()['instances'][0]['last_committed'] == 1860
        assert (await owner.call('get_result', key)).get_latest()
    finally:
        release.set()
        await owner.aclose()


@pytest.mark.anyio
async def test_correction_must_keep_full_seed_even_when_row_count_has_not_shrunk():
    owner = SerialIndicatorOwner()
    source = bars()
    reference = create_engine()
    newer = replace(source[-1], time=1860, close=150)
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=source)
        with pytest.raises(RuntimeError, match='input.*changed'):
            await owner.call('on_bars_backfilled', 'BTCUSDT', '1m', source[1:] + [newer])
        assert owner.snapshot()['serial_owner']['failure'] is None
        await owner.call('on_bars_backfilled', 'BTCUSDT', '1m', source + [newer])
        result = await owner.call('get_result', key)
        expected = reference.compute('BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, source + [newer])
        assert result.to_dict()['outputs'] == expected.to_dict()['outputs']
    finally:
        reference.stop()
        await owner.aclose()


@pytest.mark.anyio
async def test_old_left_extension_subscription_cannot_roll_existing_instance_back():
    owner = SerialIndicatorOwner()
    source = bars()
    try:
        key, before = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=source)
        old_seed = [replace(source[0], time=0)] + source[:-1]
        with pytest.raises(RuntimeError, match='input.*changed'):
            await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=old_seed)
        after = await owner.call('get_result', key)
        assert after.to_dict()['outputs'] == before.to_dict()['outputs']
        assert owner.snapshot()['instances'][0]['refcount'] == 1
    finally:
        await owner.aclose()


@pytest.mark.anyio
async def test_actual_data_manager_bridge_runs_compute_on_owner_and_publishes_on_loop(monkeypatch):
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.models import DataEvent, DataEventType, SeriesKey
    from app.indicator import data_manager_bridge as bridge
    from app.indicator.range_result_service import IndicatorRangeResultService

    threads, delivered = [], []
    loop_thread = threading.get_ident()
    def factory():
        engine = create_engine()
        original = engine.on_bar_closed
        def observed(*args, **kwargs):
            threads.append(threading.get_ident())
            return original(*args, **kwargs)
        engine.on_bar_closed = observed
        return engine
    monkeypatch.setattr(bridge, 'create_engine', factory)
    dm = DataManager()
    service = IndicatorRangeResultService.from_config()
    owner = bridge.bridge_indicator_engine(dm, result_service=service, isolate_realtime=True)
    owner.add_listener(lambda event: delivered.append((threading.get_ident(), event.event_type)))
    source = bars()
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=source)
        close = replace(source[-1], time=1860, close=150)
        await dm.event_bus.emit(DataEvent(event_type=DataEventType.BAR_CLOSED, key=SeriesKey('BTCUSDT', '1m'), bar=close))
        await eventually(lambda: owner.snapshot()['instances'][0]['last_committed'] == 1860)
        assert threads and all(thread != loop_thread for thread in threads)
        assert delivered and all(thread == loop_thread for thread, _ in delivered)
        assert any(kind == IndicatorEventType.INDICATOR_UPDATED for _, kind in delivered)
        assert (await owner.call('get_result', key)).get_latest()
        assert dm.event_bus.snapshot()['callback_errors'] == 0
    finally:
        await owner.shutdown_bridge()
        await dm.event_bus.close()
        service.unbind_all()
        await owner.aclose()
        await dm.shutdown()


@pytest.mark.anyio
async def test_recovery_at_full_admission_discards_old_work_and_late_unsubscribe():
    from app.indicator.serial_owner import IndicatorGenerationChanged
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
    owner = SerialIndicatorOwner(factory=factory, max_pending=1)
    source, events = bars(), []
    owner.add_listener(events.append)
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=source)
        old_generation = owner.generation
        running = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', replace(source[-1], time=1860)))
        await eventually(entered.is_set)
        queued = asyncio.create_task(owner.call('get_result', key))
        await eventually(lambda: owner.snapshot()['serial_owner']['inflight'] == 2)
        recovering = asyncio.create_task(owner.recover({'reason': 'source_gap'}))
        await eventually(lambda: owner.generation > old_generation)
        recovering.cancel()
        await asyncio.sleep(0)
        assert not recovering.done()
        release.set()
        for task in [running, queued]:
            with pytest.raises(IndicatorGenerationChanged):
                await task
        with pytest.raises(asyncio.CancelledError):
            await recovering
        assert not any(event.event_type == IndicatorEventType.INDICATOR_UPDATED for event in events)
        assert any(event.detail.get('resyncRequired') for event in events)
        assert await owner.call('list_instances') == []
        new_key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=source)
        assert new_key == key
        await owner.call('unsubscribe', key, expected_generation=old_generation)
        assert owner.snapshot()['instances'][0]['refcount'] == 1
        assert owner.snapshot()['serial_owner']['failure'] is None
    finally:
        release.set()
        await owner.aclose()


@pytest.mark.anyio
async def test_failed_worker_state_is_replaced_before_fresh_history_subscription():
    creations = 0
    def factory():
        nonlocal creations
        creations += 1
        engine = create_engine()
        if creations == 1:
            def failed(*args, **kwargs):
                raise RuntimeError('state transition failed')
            engine.on_bar_closed = failed
        return engine
    owner = SerialIndicatorOwner(factory=factory)
    events = []
    owner.add_listener(events.append)
    try:
        await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        with pytest.raises(RuntimeError, match='transition failed'):
            await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1])
        assert any(event.detail.get('resyncRequired') for event in events)
        await owner.recover({'reason': 'callback_failed'})
        assert creations == 2
        assert owner.snapshot()['instances'] == []
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1])
        assert (await owner.call('get_result', key)).get_latest()
    finally:
        await owner.aclose()


@pytest.mark.anyio
async def test_disconnect_release_remains_available_when_regular_admission_is_full():
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
    owner = SerialIndicatorOwner(factory=factory, max_pending=0)
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        running = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1]))
        await eventually(entered.is_set)
        cleanup = asyncio.create_task(owner.call('unsubscribe', key, expected_generation=owner.generation))
        await asyncio.sleep(0)
        assert not cleanup.done(), 'release must wait for ownership instead of rejecting and leaking a reference'
        release.set()
        await running
        await cleanup
        assert owner.snapshot()['instances'][0]['refcount'] == 0
    finally:
        release.set()
        await owner.aclose()


@pytest.mark.anyio
async def test_actual_bridge_recovers_failed_worker_and_accepts_fresh_generation(monkeypatch):
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.models import DataEvent, DataEventType, SeriesKey
    from app.indicator import data_manager_bridge as bridge
    from app.indicator.range_result_service import IndicatorRangeResultService
    creations = 0
    def factory():
        nonlocal creations
        creations += 1
        engine = create_engine()
        if creations == 1:
            def fail(*args, **kwargs):
                raise RuntimeError('injected transition failure')
            engine.on_bar_closed = fail
        return engine
    monkeypatch.setattr(bridge, 'create_engine', factory)
    dm = DataManager()
    service = IndicatorRangeResultService.from_config()
    owner = bridge.bridge_indicator_engine(dm, result_service=service, isolate_realtime=True)
    try:
        await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        event = DataEvent(event_type=DataEventType.BAR_CLOSED, key=SeriesKey('BTCUSDT', '1m'), bar=bars(31)[-1])
        await dm.event_bus.emit(event)
        await eventually(lambda: owner.generation == 1 and not owner.snapshot()['serial_owner']['recovering'])
        assert creations == 2 and owner.snapshot()['serial_owner']['failure'] is None
        assert dm.event_bus.snapshot()['callback_subscriptions'] == 3
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        await dm.event_bus.emit(event)
        await eventually(lambda: owner.snapshot()['instances'][0]['last_committed'] == event.bar.time)
        assert (await owner.call('get_result', key)).get_latest()
    finally:
        await owner.shutdown_bridge()
        await dm.event_bus.close()
        service.unbind_all()
        await owner.aclose()
        await dm.shutdown()


@pytest.mark.anyio
async def test_cancelled_shutdown_waits_for_recovery_and_physical_worker_exit():
    from app.indicator.serial_owner import IndicatorGenerationChanged
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
    owner = SerialIndicatorOwner(factory=factory)
    running = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(1)[0]))
    await eventually(entered.is_set)
    recovering = asyncio.create_task(owner.recover({'reason': 'source_gap'}))
    await eventually(lambda: owner.generation == 1)
    closing = asyncio.create_task(owner.aclose())
    await eventually(lambda: owner.snapshot()['serial_owner']['closing'])
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    with pytest.raises(IndicatorGenerationChanged):
        await running
    await recovering
    with pytest.raises(asyncio.CancelledError):
        await closing
    state = owner.snapshot()
    assert state['serial_owner']['closed']
    assert state['serial_owner']['executor']['active'] == 0
    assert state['instances'] == []


@pytest.mark.anyio
async def test_recovery_stays_unavailable_until_source_callbacks_are_ready():
    from app.indicator.serial_owner import IndicatorGenerationChanged
    owner = SerialIndicatorOwner()
    entered, allow_ready = asyncio.Event(), asyncio.Event()
    async def reconnect_source():
        entered.set()
        await allow_ready.wait()
    recovery = None
    try:
        await owner.call('list_instances')
        recovery = asyncio.create_task(owner.recover({'reason':'source_gap'}, before_ready=reconnect_source))
        await asyncio.wait_for(entered.wait(), 3)
        assert owner.snapshot()['serial_owner']['recovering']
        with pytest.raises(IndicatorGenerationChanged):
            await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period':5}, bars=bars())
        allow_ready.set()
        await recovery
        assert not owner.snapshot()['serial_owner']['recovering']
        assert (await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period':5}, bars=bars()))[1]
    finally:
        allow_ready.set()
        if recovery is not None:
            await asyncio.gather(recovery, return_exceptions=True)
        await owner.aclose()
