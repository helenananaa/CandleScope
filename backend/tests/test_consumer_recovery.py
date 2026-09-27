from __future__ import annotations

import asyncio
from functools import wraps

import pytest

from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.data_manager.config import EventBusConfig
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.data_manager.models import DataEvent, DataEventType, SeriesKey


def async_test(fn):
    @wraps(fn)
    def run():
        asyncio.run(fn())
    return run


KEY = SeriesKey("BTCUSDT", "1m")
OTHER = SeriesKey("ETHUSDT", "1m")


def event(n, key=KEY, kind=DataEventType.BAR_CLOSED):
    return DataEvent(kind, key, detail={"n": n, "delivery_id": f"{key}-{n}"})


async def settle():
    for _ in range(8):
        await asyncio.sleep(0)


@async_test
async def test_fast_consumer_continues_and_slow_one_replays_with_new_arrivals():
    bus = DataEventBus(EventBusConfig(subscriber_queue_size=1, replay_capacity=12))
    slow, fast = [], []
    blocked = asyncio.Event()
    replay_blocked = asyncio.Event()

    async def consume(e):
        slow.append(e.detail["n"])
        if e.detail["n"] == 1:
            await blocked.wait()
        if e.detail["n"] == 3:
            await replay_blocked.wait()

    async def healthy(e):
        fast.append(e.detail["n"])

    handle = bus.subscribe(consume)
    bus.subscribe(healthy)
    for n in range(1, 5):
        await asyncio.wait_for(bus.emit(event(n)), 0.1)
        await settle()
    assert slow == [1] and fast == [1, 2, 3, 4]
    state = bus.snapshot()["consumer_states"][handle.id]
    assert state["state"] == "replaying" and state["confirmed_sequence"] == 0
    blocked.set()
    await settle()
    assert slow == [1, 2, 3]
    for n in (5, 6):
        await bus.emit(event(n))
        await settle()
    replay_blocked.set()
    await settle()
    assert slow == fast == [1, 2, 3, 4, 5, 6]
    state = bus.snapshot()["consumer_states"][handle.id]
    assert state["state"] == "live" and state["confirmed_sequence"] == 6
    assert state["replayed"] == 4
    assert not bus._callback_subs[handle.id].queue._putters
    await bus.close()


@async_test
async def test_expired_window_notifies_even_when_callback_is_hung_and_stays_terminal():
    bus = DataEventBus(EventBusConfig(subscriber_queue_size=1, replay_capacity=2))
    gate = asyncio.Event()
    delivered, failures = [], []

    async def consume(e):
        delivered.append(e.detail["n"])
        await gate.wait()

    async def recover(error):
        failures.append(error)
        raise OSError("snapshot unavailable")

    handle = bus.subscribe(consume, on_recovery=recover)
    for n in range(1, 8):
        await bus.emit(event(n))
        await settle()
    assert len(failures) == 1 and failures[0].first_missing_sequence == 3
    assert failures[0].confirmed_sequence == 0
    gate.set()
    await settle()
    assert delivered == [1]
    state = bus.snapshot()["consumer_states"][handle.id]
    assert state["state"] == "recovery_required"
    assert state["notification_error"] == "snapshot unavailable"
    assert bus.snapshot()["replay_size"] == 2
    await bus.close()


@async_test
async def test_callback_exception_does_not_ack_or_retry_ambiguous_side_effect():
    bus = DataEventBus()
    calls = []

    async def consumer(e):
        calls.append(e.detail["n"])
        raise RuntimeError("side effect may already have happened")

    handle = bus.subscribe(consumer)
    await bus.emit(event(1))
    await settle()
    await bus.emit(event(2))
    await settle()
    assert calls == [1]
    state = bus.snapshot()["consumer_states"][handle.id]
    assert state["confirmed_sequence"] == 0
    assert state["recovery"]["reason"] == "callback_failed"
    await bus.close()


@async_test
async def test_iterator_overrun_raises_before_returning_stale_queued_event():
    bus = DataEventBus(EventBusConfig(subscriber_queue_size=1, replay_capacity=2))
    stream = bus.subscribe_iter(key=KEY)
    first = asyncio.create_task(anext(stream))
    await settle()
    await bus.emit(event(1))
    await first
    for n in range(2, 7):
        await bus.emit(event(n))
    with pytest.raises(ConsumerRecoveryRequired) as caught:
        await anext(stream)
    assert caught.value.confirmed_sequence == 0  # next() never confirmed first
    assert bus.get_subscriber_count() == 0
    await bus.close()


@async_test
async def test_replay_filters_topics_and_types_without_false_gap_on_unrelated_eviction():
    bus = DataEventBus(EventBusConfig(subscriber_queue_size=1, replay_capacity=2))
    gate = asyncio.Event()
    replay_gate = asyncio.Event()
    seen = []

    async def consume(e):
        seen.append(e.detail["n"])
        if len(seen) == 1:
            await gate.wait()
        if len(seen) == 3:
            await replay_gate.wait()

    handle = bus.subscribe(consume, key=KEY, event_types={DataEventType.BAR_CLOSED})
    for n in (1, 2, 3):
        await bus.emit(event(n))
        await settle()
    gate.set()
    await settle()
    # The replayed item is now in flight; evicting its log row is safe.
    for n in range(10, 20):
        await bus.emit(event(n, OTHER))
        await bus.emit(event(n, KEY, DataEventType.STREAM_STARTED))
    replay_gate.set()
    await settle()
    assert seen == [1, 2, 3]
    assert bus.snapshot()["consumer_states"][handle.id]["state"] == "live"
    await bus.close()


@async_test
async def test_stable_delivery_retry_and_callback_mutation_do_not_corrupt_replay():
    bus = DataEventBus(EventBusConfig(subscriber_queue_size=1, replay_capacity=8))
    gate = asyncio.Event()
    seen = []

    async def mutate(e):
        e.detail["n"] = -1

    async def slow(e):
        seen.append(e.detail["n"])
        await gate.wait()

    bus.subscribe(mutate)
    bus.subscribe(slow)
    for n in (1, 2, 3, 3, 4):
        await bus.emit(event(n))
        await settle()
    gate.set()
    await settle()
    assert seen == [1, 2, 3, 4]
    assert bus.snapshot()["sequence"] == 4
    await bus.close()


@async_test
async def test_close_cancels_both_hung_callback_and_recovery_notification():
    bus = DataEventBus(EventBusConfig(subscriber_queue_size=1, replay_capacity=1))

    async def hang(_):
        await asyncio.Event().wait()

    handle = bus.subscribe(hang, on_recovery=hang)
    for n in range(1, 7):
        await bus.emit(event(n))
        await settle()
    sub = bus._callback_subs[handle.id]
    assert sub.recovery_task is not None
    await asyncio.wait_for(bus.close(), 0.1)
    assert sub.task.done() and sub.recovery_task.done()
    assert bus.snapshot()["replay_size"] == 0
    with pytest.raises(RuntimeError, match="closed"):
        bus.subscribe(hang)


def test_restart_changes_epoch_and_unbounded_queue_settings_are_rejected():
    assert DataEventBus().snapshot()["epoch"] != DataEventBus().snapshot()["epoch"]
    with pytest.raises(ValueError):
        DataEventBus(EventBusConfig(subscriber_queue_size=0))
    with pytest.raises(ValueError):
        DataEventBus(EventBusConfig(replay_capacity=0))


@async_test
async def test_real_indicator_bridge_overrun_invalidates_epoch_and_reseeds_without_losing_owners():
    from app.indicator.data_manager_bridge import bridge_indicator_engine
    from app.indicator.range_result_service import IndicatorRangeResultService
    from app.data_engine.data_manager.models import BarData

    bus = DataEventBus(EventBusConfig(subscriber_queue_size=1, replay_capacity=1))

    class Manager:
        subscribe = bus.subscribe
        unsubscribe = bus.unsubscribe

    cache = IndicatorRangeResultService()
    engine = bridge_indicator_engine(Manager(), result_service=cache)
    bars = [BarData(time=n * 60, open=n, high=n, low=n, close=n, volume=1) for n in range(1, 5)]
    args = dict(symbol="BTCUSDT", interval="1m", market_type="spot", indicator_name="MA", params={"period": 2})
    key, initial = engine.subscribe(**args, bars=bars)
    assert initial is not None
    epoch = cache.revisions.server_epoch
    notifications = []
    engine.add_listener(notifications.append)
    # No worker gets a turn before its replay window has been exhausted.
    for n in range(1, 6):
        await bus.emit(event(n))
    await settle()
    assert cache.revisions.server_epoch != epoch
    assert engine.get_result(key) is None
    assert any(e.detail.get("resyncRequired") for e in notifications)
    assert bus.get_subscriber_count() == 3  # old subscriptions replaced once
    new_key, seeded = engine.subscribe(**args, bars=bars)
    assert seeded is not None and new_key == key
    engine.unsubscribe(key)  # old socket finally closes after the new seed
    assert engine._refcounts[key] == 1
    assert engine.get_result(key) is not None
    await bus.close()


@async_test
async def test_bar_publisher_reliable_overflow_is_terminal_and_full_close_wakes_iterator():
    from app.data_engine.bar_aggregator.publisher import BarAggregatorPublisher
    from app.data_engine.bar_aggregator.config import BarAggregatorConfig
    from types import SimpleNamespace
    from app.data_engine.bar_aggregator.models import BarEventType

    publisher = BarAggregatorPublisher(BarAggregatorConfig(publisher_queue_size=1))
    stream = publisher.subscribe()
    first = asyncio.create_task(anext(stream))
    await settle()
    publisher._enqueue(SimpleNamespace(event_type=BarEventType.CLOSED))
    await first
    publisher._enqueue(SimpleNamespace(event_type=BarEventType.CLOSED))
    publisher._enqueue(SimpleNamespace(event_type=BarEventType.AMENDED))
    with pytest.raises(ConsumerRecoveryRequired):
        await anext(stream)
    assert publisher.snapshot()["queue_recovery_required"] == 1
    stream = publisher.subscribe()
    first = asyncio.create_task(anext(stream))
    await settle()
    publisher._enqueue(SimpleNamespace(event_type=BarEventType.CLOSED))
    await first
    publisher._enqueue(SimpleNamespace(event_type=BarEventType.CLOSED))
    await publisher.close_all_subscribers()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), .1)


@async_test
async def test_websocket_iterator_gap_sends_explicit_resync_close():
    from app.api.v1.stream_klines import forward_events_to_ws

    class Manager:
        async def subscribe_iter(self, **kwargs):
            raise ConsumerRecoveryRequired("replay_window_exhausted")
            yield  # async generator contract

    class Socket:
        async def close(self, **kwargs):
            self.closed = kwargs

    socket = Socket()
    await forward_events_to_ws(socket, Manager(), "BTCUSDT", ["1m"])
    assert socket.closed == {"code": 1013, "reason": "CONSUMER_RESYNC_REQUIRED"}


def test_multi_kline_closes_on_bus_gap_or_authoritative_outbox_failure(monkeypatch):
    import json
    from fastapi import WebSocketDisconnect
    from app.api.v1 import stream_klines
    from app.data_engine.data_manager.models import BarData

    class FullOutbox:
        def __init__(self, *args, **kwargs):
            pass

        async def put(self, *args, **kwargs):
            return False

        async def get(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(stream_klines, "_KlineWsOutbox", FullOutbox)

    async def run(kind):
        acknowledged, closed = asyncio.Event(), asyncio.Event()

        class Socket:
            received = False

            async def receive_text(self):
                if not self.received:
                    self.received = True
                    return json.dumps({"action": "subscribe", "intervals": ["1m"]})
                await closed.wait()
                raise WebSocketDisconnect()

            async def send_json(self, payload):
                if payload.get("type") == "subscribed":
                    acknowledged.set()

            async def close(self, **kwargs):
                self.close_payload = kwargs
                closed.set()

        class Manager:
            async def ensure_stream(self, *args, **kwargs):
                pass

            async def release_stream(self, *args, **kwargs):
                pass

            def subscribe(self, **kwargs):
                self.subscription = kwargs
                return "handle"

            def unsubscribe(self, handle):
                self.unsubscribed = handle

        socket, manager = Socket(), Manager()
        stream = asyncio.create_task(stream_klines.stream_multi_kline(socket, manager, "BTCUSDT"))
        await asyncio.wait_for(acknowledged.wait(), 1)
        if kind == "bus":
            await manager.subscription["on_recovery"](ConsumerRecoveryRequired("window_exhausted"))
        else:
            await manager.subscription["callback"](DataEvent(
                kind, KEY, bar=BarData(time=60, open=1, high=1, low=1, close=1, volume=1),
                detail={"bars_count": 1},
            ))
        await asyncio.wait_for(stream, 1)
        assert socket.close_payload == {"code": 1013, "reason": "CONSUMER_RESYNC_REQUIRED"}
        assert manager.unsubscribed == "handle"

    for kind in ("bus", DataEventType.BAR_CLOSED, DataEventType.BACKFILL_COMPLETED):
        asyncio.run(run(kind))


@async_test
async def test_failed_indicator_bridge_replacement_stays_visible_and_rejects_new_subscriptions():
    from app.indicator.data_manager_bridge import bridge_indicator_engine

    bus = DataEventBus(EventBusConfig(subscriber_queue_size=1, replay_capacity=1))

    class Manager:
        calls = 0
        unsubscribe = bus.unsubscribe

        def subscribe(self, **kwargs):
            self.calls += 1
            if self.calls > 3:
                raise RuntimeError("runtime unavailable")
            return bus.subscribe(**kwargs)

    engine = bridge_indicator_engine(Manager())
    for n in range(1, 6):
        await bus.emit(event(n))
    await settle()
    assert engine.snapshot()["source_delivery"]["state"] == "recovery_failed"
    assert bus.get_subscriber_count() == 0
    with pytest.raises(RuntimeError, match="recovery is incomplete"):
        engine.subscribe("BTCUSDT", "1m", "spot", "MA", {"period": 2})
    await bus.close()


@async_test
async def test_shutdown_drains_recovery_hook_that_already_unsubscribed_itself():
    bus = DataEventBus()
    recovering = asyncio.Event()

    async def fail(_):
        raise RuntimeError("lost consumer state")

    async def recover(_):
        bus.unsubscribe(handle)
        recovering.set()
        await asyncio.Event().wait()

    handle = bus.subscribe(fail, on_recovery=recover)
    await bus.emit(event(1))
    await asyncio.wait_for(recovering.wait(), .2)
    assert bus.get_subscriber_count() == 0
    assert any(not task.done() for task in bus._worker_tasks)
    await asyncio.wait_for(bus.close(), .2)
    assert not bus._worker_tasks
