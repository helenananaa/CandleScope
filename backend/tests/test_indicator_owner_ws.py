"""The real serial owner at the WebSocket/lease boundary."""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from app.api.v1.stream_indicators import _handle_indicator_subscribe, stream_indicators
from app.data_engine.data_manager.models import BarData
from app.indicator import create_engine
from app.indicator.range_result_service import IndicatorRangeResultService
from app.indicator.serial_owner import SerialIndicatorOwner


@pytest.fixture(scope="module", autouse=True)
def initialized_exchange_registry():
    # Start the cancellation deadline after provider/calendar setup. Cold
    # bootstrap is a separate synchronous workload, not worker cancellation.
    from app.exchanges import bootstrap_default_adapters
    bootstrap_default_adapters()


def bars(count=30):
    return [BarData(time=60 * (i + 1), open=100 + i, high=101 + i,
                    low=99 + i, close=100 + i, volume=10, is_closed=True)
            for i in range(count)]


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.001)


class DataManager:
    def __init__(self):
        self.leases = set()
        self.release_entered = asyncio.Event()
        self.release_allowed = asyncio.Event()
        self.release_allowed.set()

    async def ensure_stream(self, *args, **kwargs):
        self.leases.add(kwargs['consumer_id'])

    async def release_stream(self, *args, **kwargs):
        self.release_entered.set()
        await self.release_allowed.wait()
        self.leases.discard(kwargs['consumer_id'])

    def query_latest(self, *args, **kwargs):
        return SimpleNamespace(bars=bars())


class Subscription:
    def __init__(self, owner, dm):
        self.owner, self.dm = owner, dm
        self.subscribed, self.meta, self.sent = {}, {}, []
        self.queue = asyncio.Queue(maxsize=32)

    async def send(self, message):
        self.sent.append(message)
        return True

    async def run(self):
        await _handle_indicator_subscribe(
            websocket=SimpleNamespace(), dm=self.dm, indicator_engine=self.owner,
            subscribed=self.subscribed, client_meta=self.meta, custom_handles={},
            custom_tasks={}, queue=self.queue, seed_query_cache={}, send_json=self.send,
            msg={'clientId': 'ema', 'name': 'EMA', 'params': {'period': 5},
                 'symbol': 'BTCUSDT', 'interval': '1m', 'historyLimit': 30},
        )


def blocking_factory(entered, release):
    def factory():
        engine = create_engine()
        subscribe = engine.subscribe
        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return subscribe(*args, **kwargs)
        engine.subscribe = blocked
        return engine
    return factory


@pytest.mark.anyio
async def test_repeated_cancel_drains_adopted_subscription_and_market_lease():
    entered, release = threading.Event(), threading.Event()
    owner = SerialIndicatorOwner(factory=blocking_factory(entered, release), max_pending=0)
    dm = DataManager()
    dm.release_allowed.clear()
    subscription = Subscription(owner, dm)
    task = asyncio.create_task(subscription.run())
    try:
        await until(entered.is_set)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        await asyncio.wait_for(dm.release_entered.wait(), timeout=3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not task.done() and dm.leases
        dm.release_allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not dm.leases and not subscription.subscribed and not subscription.meta
        assert not subscription.sent
        assert all(row['refcount'] == 0 for row in owner.snapshot()['instances'])
    finally:
        release.set()
        dm.release_allowed.set()
        await asyncio.gather(task, return_exceptions=True)
        await owner.aclose()


@pytest.mark.anyio
async def test_source_revision_change_while_worker_seeds_prevents_success_ack():
    entered, release = threading.Event(), threading.Event()
    owner = SerialIndicatorOwner(factory=blocking_factory(entered, release))
    service = IndicatorRangeResultService.from_config()
    service.bind_engine(owner)
    dm = DataManager()
    subscription = Subscription(owner, dm)
    task = asyncio.create_task(subscription.run())
    try:
        await until(entered.is_set)
        service.note_correction(series_key='binance:spot:BTCUSDT:1m', start=600, end=600)
        release.set()
        await task
        assert not subscription.sent, 'old seed cannot be acknowledged with a newer correction token'
        assert (await subscription.queue.get())['type'] == 'resync_required'
        assert not dm.leases and not subscription.subscribed
        assert service.snapshot()['entries'] == 0
        assert all(row['refcount'] == 0 for row in owner.snapshot()['instances'])
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        service.unbind_all()
        await owner.aclose()


@pytest.mark.anyio
async def test_reconnect_during_recovery_remains_retryable_and_releases_market_lease():
    entered, release = threading.Event(), threading.Event()
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        if calls > 1:
            entered.set()
            assert release.wait(3)
        return create_engine()
    owner = SerialIndicatorOwner(factory=factory)
    dm = DataManager()
    subscription = Subscription(owner, dm)
    recovery = None
    try:
        await owner.call('list_instances')
        recovery = asyncio.create_task(owner.recover({'reason':'owned_process_failure'}))
        await until(entered.is_set)
        await subscription.run()
        assert not subscription.sent, 'recovery must not become permanent HTTP-only fallback'
        assert (await subscription.queue.get())['type'] == 'resync_required'
        assert not dm.leases and not subscription.subscribed
        release.set()
        await recovery
        await subscription.run()
        assert subscription.sent[0]['type'] == 'indicator.subscribed'
        assert dm.leases and subscription.subscribed
    finally:
        release.set()
        if recovery is not None:
            await asyncio.gather(recovery, return_exceptions=True)
        await owner.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('updates', [1, 17])
async def test_live_events_wait_for_ack_and_pending_overflow_requires_resync(updates):
    owner = SerialIndicatorOwner()
    dm = DataManager()
    class Socket:
        def __init__(self):
            self.sent = []
            self.first = True
            self.closed = asyncio.Event()

        async def receive_text(self):
            if self.closed.is_set():
                raise RuntimeError('WebSocket is not connected')
            if self.first:
                self.first = False
                return json.dumps({'action': 'subscribe', 'clientId': 'ema', 'name': 'EMA',
                                   'params': {'period': 5}, 'symbol': 'BTCUSDT', 'interval': '1m', 'historyLimit': 30})
            await self.closed.wait()
            raise WebSocketDisconnect()

        async def send_json(self, message):
            if message['type'] == 'indicator.subscribed':
                for count in range(31, 31 + updates):
                    await owner.call('on_bar_closed', 'BTCUSDT', '1m', bars(count)[-1])
                await asyncio.sleep(0)
                assert [message['type'] for message in self.sent] == ['connected']
            self.sent.append(message)

        async def close(self, **kwargs):
            self.close_reason = kwargs
            self.closed.set()

    socket = Socket()
    task = asyncio.create_task(stream_indicators(socket, dm, owner))
    try:
        if updates == 1:
            await until(lambda: any(row['type'] == 'indicator.update' for row in socket.sent))
            assert [row['type'] for row in socket.sent] == ['connected', 'indicator.subscribed', 'indicator.update']
            socket.closed.set()
        else:
            await asyncio.wait_for(socket.closed.wait(), timeout=3)
            assert [row['type'] for row in socket.sent] == ['connected', 'indicator.subscribed']
            assert socket.close_reason == {'code': 1013, 'reason': 'CONSUMER_RESYNC_REQUIRED'}
        await asyncio.wait_for(task, timeout=3)
        assert not dm.leases
        assert all(row['refcount'] == 0 for row in owner.snapshot()['instances'])
    finally:
        socket.closed.set()
        await asyncio.gather(task, return_exceptions=True)
        await owner.aclose()
