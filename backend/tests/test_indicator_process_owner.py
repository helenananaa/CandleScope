import asyncio
import os
import signal
from dataclasses import replace

import pytest

from app.data_engine.data_manager.models import BarData
from app.indicator import create_engine
from app.indicator.events import IndicatorEventType
from app.indicator.serial_owner import IndicatorInputChanged, SerialIndicatorOwner


def bars(count=30):
    return [BarData(time=60 * (i + 1), open=100 + i, high=101 + i,
                    low=99 + i, close=100 + i, volume=10, is_closed=True)
            for i in range(count)]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['thread', 'process'])
async def test_warm_resubscribe_keeps_logical_key_diagnostic_frontier(mode):
    owner = SerialIndicatorOwner(execution_mode=mode)
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        await owner.call('unsubscribe', key)
        resumed, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        before = owner.snapshot()
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1])
        assert owner.generation == 0
        assert before['instances'][0]['last_committed'] == 1800
        assert owner.snapshot()['instances'][0]['last_committed'] == 1860
        assert (await owner.call('get_result', resumed)).get_latest()
    finally:
        await owner.aclose()


@pytest.mark.asyncio
async def test_process_owns_builtin_state_and_shutdown_reaps_owned_process():
    owner = SerialIndicatorOwner(execution_mode='process')
    events = []
    owner.add_listener(events.append)
    reference = create_engine()
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        pid = owner.snapshot()['worker']['pid']
        assert pid != os.getpid()
        before = owner.snapshot()
        await owner.call('on_bar_updated', 'BTCUSDT', '1m', replace(bars(31)[-1], is_closed=False))
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1])
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1])
        current = owner.snapshot()
        assert current['instances'][0]['bar_count'] == before['instances'][0]['bar_count'] + 1
        assert before['instances'][0]['last_committed'] == 1800
        assert current['instances'][0]['last_committed'] == 1860
        with pytest.raises(IndicatorInputChanged):
            await owner.call('on_bars_backfilled', 'BTCUSDT', '1m', bars())
        actual = await owner.call('get_result', key)
        expected = reference.compute('BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars(31))
        assert actual.to_dict()['outputs'] == expected.to_dict()['outputs']
        assert sum(e.event_type == IndicatorEventType.INDICATOR_UPDATED for e in events) == 1
        assert sum(e.event_type == IndicatorEventType.INDICATOR_PREVIEW for e in events) == 1
    finally:
        reference.stop()
        await owner.aclose()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert owner.snapshot()['serial_owner']['closed']


@pytest.mark.asyncio
async def test_failed_process_is_replaced_and_old_release_cannot_change_new_reference():
    owner = SerialIndicatorOwner(execution_mode='process')
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        old_generation = owner.generation
        old_pid = owner.snapshot()['worker']['pid']
        os.kill(old_pid, signal.SIGKILL)  # This test created and owns exactly this process.
        with pytest.raises(Exception):
            await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1])
        assert owner.snapshot()['serial_owner']['failure']
        await owner.recover({'reason': 'injected_owned_process_failure'})
        new_key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars(31))
        assert owner.snapshot()['worker']['pid'] != old_pid
        assert owner.generation == old_generation + 1
        await owner.call('unsubscribe', key, expected_generation=old_generation)
        assert owner.snapshot()['instances'][0]['refcount'] == 1
        assert (await owner.call('get_result', new_key)).get_latest()
    finally:
        await owner.aclose()


@pytest.mark.asyncio
async def test_remote_admission_errors_preserve_existing_instance_and_worker(monkeypatch):
    from app.indicator.engine import IndicatorCapacityError, IndicatorParametersError
    monkeypatch.setenv('INDICATOR_APP_MAX_ACTIVE_TARGETS', '1')
    owner = SerialIndicatorOwner(execution_mode='process')
    try:
        # No shared instance exists yet; an invalid constructor is a request
        # rejection and must not poison the process for valid callers.
        with pytest.raises(IndicatorParametersError):
            await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': -1}, bars=bars())
        assert owner.snapshot()['serial_owner']['failure'] is None
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        pid = owner.snapshot()['worker']['pid']
        with pytest.raises(IndicatorCapacityError) as rejected:
            await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 6}, bars=bars())
        assert rejected.value.active == rejected.value.maximum == 1
        assert owner.snapshot()['serial_owner']['failure'] is None
        await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1])
        assert (await owner.call('get_result', key)).get_latest()
        assert owner.snapshot()['worker']['pid'] == pid
    finally:
        await owner.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(not hasattr(signal, 'SIGSTOP'), reason='POSIX owned-process suspension probe')
async def test_cancelled_waiter_keeps_physical_process_capacity_until_resume():
    from app.core.bounded_executor import ExecutorBusyError
    owner = SerialIndicatorOwner(execution_mode='process', max_pending=0)
    pending = None
    pid = None
    try:
        key, _ = await owner.call('subscribe', 'BTCUSDT', '1m', 'spot', 'EMA', {'period': 5}, bars=bars())
        pid = owner.snapshot()['worker']['pid']
        os.kill(pid, signal.SIGSTOP)
        pending = asyncio.create_task(owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(31)[-1]))
        async with asyncio.timeout(3):
            while owner.snapshot()['serial_owner']['executor']['active'] != 1:
                await asyncio.sleep(.001)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        with pytest.raises(ExecutorBusyError):
            await owner.call('get_result', key)
        os.kill(pid, signal.SIGCONT)
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert owner.snapshot()['instances'][0]['last_committed'] == 1860
        assert (await owner.call('get_result', key)).get_latest()
    finally:
        if pid is not None:
            os.kill(pid, signal.SIGCONT)
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await owner.aclose()
