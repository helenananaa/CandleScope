"""Real SQLite fences must invalidate consumers without replaying stale data."""
from __future__ import annotations

import asyncio

import pytest

from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.data_manager.models import DataEvent, DataEventType, SeriesKey
from app.data_engine.storage import klines_repo
from tests.test_bar_delivery_bridge import async_test, bridge, storage, wait_for
from tests.test_bar_delivery_journal import payload


KEY = SeriesKey("BTCUSDT", "1m")


def amend(storage):
    storage.upsert_bars("BTCUSDT", "1m", [payload(4)["storage_row"]],
                       "repair_binance_rest_verified")


@async_test
@pytest.mark.parametrize("mutation", ["amend", "delete"])
async def test_revision_rejection_notifies_matching_callbacks_and_iterators(storage, mutation):
    instance, bus = bridge(storage)
    received, errors, unrelated_errors = [], [], []

    async def receive(event):
        received.append(event)

    async def recover(error):
        errors.append(error)

    async def unrelated(error):
        unrelated_errors.append(error)

    bus.subscribe(receive, key=KEY, event_types={DataEventType.BAR_CLOSED}, on_recovery=recover)
    bus.subscribe(receive, on_recovery=recover)  # wildcard also depends on this series
    for key, kinds in [
        (SeriesKey("ETHUSDT", "1m"), None),
        (SeriesKey("BTCUSDT", "5m"), None),
        (SeriesKey("BTCUSDT", "1m", series_variant="other"), None),
        (KEY, {DataEventType.STREAM_STARTED}),
    ]:
        bus.subscribe(receive, key=key, event_types=kinds, on_recovery=unrelated)
    iterator = bus.subscribe_iter(key=KEY, event_types={DataEventType.BAR_CLOSED})
    next_event = asyncio.create_task(anext(iterator))
    try:
        await wait_for(lambda: bus.snapshot()["queue_subscriptions"] == 1)
        storage.bar_delivery.enqueue("old", payload())
        if mutation == "amend":
            amend(storage)
        else:
            storage.delete_bars("BTCUSDT", "1m")
        await instance.delivery.flush()
        with pytest.raises(ConsumerRecoveryRequired, match="source_revision_superseded"):
            await asyncio.wait_for(next_event, 1)
        await wait_for(lambda: len(errors) == 2)
        assert all(error.reason == "source_revision_superseded" for error in errors)
        assert unrelated_errors == received == []
        assert not storage.bar_delivery.pending()
        assert instance.delivery.snapshot()["rejected"] == 1
        assert [row["close"] for row in storage.query_bars("BTCUSDT", "1m")] == (
            [4] if mutation == "amend" else [])
        # Fresh subscriptions do not inherit a retired subscription's failure.
        fresh = bus.subscribe(receive, key=KEY)
        await bus.emit(DataEvent(DataEventType.STREAM_STARTED, KEY))
        await wait_for(lambda: len(received) == 2)  # fresh + unrelated type filter
        assert bus.snapshot()["consumer_states"][fresh.id]["state"] == "live"
    finally:
        next_event.cancel()
        await asyncio.gather(next_event, return_exceptions=True)
        await iterator.aclose()
        await bus.close()


@async_test
async def test_recovery_notification_does_not_wait_for_blocked_callback(storage):
    instance, bus = bridge(storage)
    entered, release = asyncio.Event(), asyncio.Event()
    errors = []

    async def receive(event):
        entered.set()
        await release.wait()

    async def recover(error):
        errors.append(error)

    bus.subscribe(receive, key=KEY, on_recovery=recover)
    try:
        await bus.emit(DataEvent(DataEventType.STREAM_STARTED, KEY))
        await entered.wait()
        storage.bar_delivery.enqueue("old", payload())
        storage.delete_bars("BTCUSDT", "1m")
        await asyncio.wait_for(instance.delivery.flush(), 1)
        await wait_for(lambda: bool(errors))
        assert errors[0].reason == "source_revision_superseded"
        assert storage.query_bars("BTCUSDT", "1m") == []
    finally:
        release.set()
        await bus.close()


@async_test
async def test_rejected_notification_survives_restart_pruning_and_ack_failure(storage, monkeypatch):
    journal = storage.bar_delivery
    journal.enqueue("old", payload())
    storage.delete_bars("BTCUSDT", "1m")
    assert journal.commit("old")["recovery_required"] == 1
    # A rejected but unnotified receipt counts toward admission and cannot be pruned.
    journal.max_pending = 1
    with pytest.raises(RuntimeError, match="capacity"):
        journal.enqueue("blocked", payload())
    journal.max_pending = 4096
    journal.retained = 0
    journal.enqueue("newer", {**payload(), "symbol": "ETHUSDT"})
    journal.commit("newer")
    journal.acknowledge("newer")
    restarted = klines_repo.KlinesRepoAdapter()
    assert [row["event_id"] for row in restarted.bar_delivery.pending()] == ["old"]
    instance, bus = bridge(restarted)
    errors = []

    async def receive(event):
        pytest.fail("a rejected receipt must not publish a bar")

    async def recover(error):
        errors.append(error)

    bus.subscribe(receive, key=KEY, on_recovery=recover)
    acknowledge = restarted.bar_delivery.acknowledge
    monkeypatch.setattr(restarted.bar_delivery, "acknowledge",
                        lambda *args: (_ for _ in ()).throw(OSError("ack failed")))
    try:
        await instance.delivery.flush()
        await wait_for(lambda: len(errors) == 1)
        assert restarted.bar_delivery.pending_count() == 1
        assert instance.delivery.snapshot()["degraded"]
        monkeypatch.setattr(restarted.bar_delivery, "acknowledge", acknowledge)
        await instance.delivery.flush()
        await asyncio.sleep(0)
        assert len(errors) == 1
        assert restarted.bar_delivery.pending_count() == 0
        assert not instance.delivery.snapshot()["degraded"]
        assert restarted.query_bars("BTCUSDT", "1m") == []
    finally:
        await bus.close()


@async_test
async def test_quality_rejection_does_not_invalidate_consumers(storage):
    instance, bus = bridge(storage)
    errors = []

    async def receive(event):
        pytest.fail("lower-quality receipt must not publish")

    async def recover(error):
        errors.append(error)

    handle = bus.subscribe(receive, key=KEY, on_recovery=recover)
    try:
        amend(storage)
        storage.bar_delivery.enqueue("lower-quality", payload())
        await instance.delivery.flush()
        assert bus.snapshot()["consumer_states"][handle.id]["state"] == "live"
        assert errors == []
        assert storage.query_bars("BTCUSDT", "1m")[0]["close"] == 4
        assert not storage.bar_delivery.pending()
    finally:
        await bus.close()


@async_test
@pytest.mark.parametrize("delete_at", ["before_dispatch", "before_adoption"])
async def test_deleted_committed_receipt_requires_snapshot_without_resurrection(storage, monkeypatch, delete_at):
    from app.data_engine.data_manager import DataManager

    dm = DataManager()
    dm.set_storage(storage)
    delivery = dm.aggregator_bridge.delivery
    errors = []

    async def receive(event):
        pytest.fail("deleted canonical data must not be published")

    async def recover(error):
        errors.append(error)

    dm.subscribe(receive, symbol="BTCUSDT", interval="1m", on_recovery=recover)
    storage.bar_delivery.enqueue("committed", payload())
    storage.bar_delivery.commit("committed")
    if delete_at == "before_dispatch":
        storage.delete_bars("BTCUSDT", "1m")
    else:
        publish = delivery._publish

        async def delete_then_publish(event):
            storage.delete_bars("BTCUSDT", "1m")
            await publish(event)

        monkeypatch.setattr(delivery, "_publish", delete_then_publish)
    try:
        await delivery.flush()
        await wait_for(lambda: bool(errors))
        assert errors[0].reason == "source_revision_superseded"
        assert dm.cache.get_latest(KEY, 10) == []
        assert storage.query_bars("BTCUSDT", "1m") == []
        assert not storage.bar_delivery.pending()
    finally:
        await dm.event_bus.close()
