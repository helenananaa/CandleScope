import asyncio
import os
import signal

import pytest

from app.core.bounded_executor import ExecutorBusyError
from app.indicator.history_worker import BuiltinHistoryExecutor
from app.data_engine.data_manager.models import BarData


def request(count=30):
    bars = tuple(BarData(time=(i + 1) * 60, open=100+i, high=101+i,
                         low=99+i, close=100+i, volume=10) for i in range(count))
    return ('compute', 'EMA', {'symbol':'BTCUSDT', 'interval':'1m',
            'exchange':'binance', 'market_type':'spot', 'params':{'period':5}}, bars)


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.001)


@pytest.mark.asyncio
@pytest.mark.skipif(not hasattr(signal, 'SIGSTOP'), reason='POSIX owned-process suspension probe')
async def test_history_cancellation_retains_physical_rows_and_retracts_queued_work():
    executor = BuiltinHistoryExecutor(max_pending=1, max_input_bars=60)
    running = queued = None
    pid = None
    try:
        assert (await executor.run(request(), 30)).get_latest()
        pid = executor.snapshot()['worker']['pid']
        assert pid != os.getpid()
        os.kill(pid, signal.SIGSTOP)
        running = asyncio.create_task(executor.run(request(), 30))
        await until(lambda: executor.snapshot()['active'] == 1)
        queued = asyncio.create_task(executor.run(request(), 30))
        await until(lambda: executor.snapshot()['input_bars'] == 60)
        with pytest.raises(ExecutorBusyError):
            await executor.run(request(), 30)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert executor.snapshot()['input_bars'] == 30
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert executor.snapshot()['input_bars'] == 30
        assert executor.snapshot()['active'] == 1
        os.kill(pid, signal.SIGCONT)
        await until(lambda: executor.snapshot()['input_bars'] == 0)
        assert (await executor.run(request(), 30)).get_latest()
    finally:
        if pid is not None:
            os.kill(pid, signal.SIGCONT)
        await asyncio.gather(*(task for task in (running, queued) if task), return_exceptions=True)
        await asyncio.to_thread(executor.close)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
@pytest.mark.skipif(not hasattr(signal, 'SIGSTOP'), reason='POSIX owned-process suspension probe')
async def test_physical_deadline_reaps_only_owned_worker_before_reusing_capacity():
    executor = BuiltinHistoryExecutor(timeout=2)
    try:
        await executor.run(request(), 30)
        pid = executor.snapshot()['worker']['pid']
        os.kill(pid, signal.SIGSTOP)
        with pytest.raises(TimeoutError):
            await executor.run(request(), 30)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert executor.snapshot()['input_bars'] == executor.snapshot()['active'] == 0
        assert (await executor.run(request(), 30)).get_latest()
        assert executor.snapshot()['worker']['pid'] != pid
    finally:
        await asyncio.to_thread(executor.close)
