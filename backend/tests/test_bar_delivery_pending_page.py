"""Bounded physical reads for the original durable delivery barrier."""
import asyncio
import threading

import pytest

from tests.test_source_window_recovery import database, manager_for
from tests.test_bar_delivery_journal import journal, payload
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.storage import klines_repo


def test_empty_delivery_barrier_uses_one_page_view_and_one_fresh_completion_view(database, monkeypatch):
    async def run():
        manager = manager_for('2m')
        journal = manager.aggregator_bridge.delivery.journal
        connect = journal._connect
        opened = []
        def counted():
            connection = connect()
            opened.append(connection)
            return connection
        monkeypatch.setattr(journal, '_connect', counted)
        try:
            await manager.aggregator_bridge.delivery.flush_pending()
            # A page/count snapshot and the post-dispatch empty boundary are
            # distinct views. Diagnostic counting must not open a third view.
            assert len(opened) <= 2
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


def test_cancelled_page_read_drains_physical_worker_without_acknowledging_receipt(database, monkeypatch):
    async def run():
        manager = manager_for('2m')
        delivery = manager.aggregator_bridge.delivery
        journal = delivery.journal
        journal.enqueue('cancelled-page', payload())
        original = journal._record
        entered, released = threading.Event(), threading.Event()
        observed = []
        def held(row):
            entered.set()
            assert released.wait(10)
            return original(row)
        monkeypatch.setattr(journal, '_record', held)
        async def receive(event):
            observed.append(event.detail['delivery_id'])
        manager.event_bus.subscribe(receive)
        task = asyncio.create_task(delivery.flush_pending())
        try:
            async with asyncio.timeout(5):
                while not entered.is_set():
                    await asyncio.sleep(.01)
            task.cancel()
            await asyncio.sleep(.02)
            assert not task.done() and delivery._dispatcher.locked()
            assert not observed and journal.pending_count() == 1
            released.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not delivery._dispatcher.locked() and not delivery._dispatch_records
            assert not observed and journal.pending_count() == 1
            await delivery.flush_pending()
            assert observed == ['cancelled-page'] and journal.pending_count() == 0
        finally:
            released.set()
            if not task.done():
                await task
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


def test_page_and_count_keep_one_read_view_during_concurrent_acknowledgement(journal, monkeypatch):
    for index in range(70):
        journal.enqueue(str(index), payload())
    journal.commit('0')
    original = journal._record
    changed = []
    def interleaved(row):
        result = original(row)
        if not changed:
            changed.append(result['event_id'])
            journal.acknowledge(result['event_id'])
        return result
    monkeypatch.setattr(journal, '_record', interleaved)
    rows, count = journal.pending_page()
    assert len(rows) == 64 and count == 70
    assert [row['event_id'] for row in rows] == [str(index) for index in range(64)]
    assert rows[0]['phase'] == 'committed' and all(row['phase'] == 'pending' for row in rows[1:])
    assert journal.pending_count() == 69
    # The returned page is an owned value, never an in-memory emptiness cache.
    rows[1]['payload']['bar']['close'] = 999
    again, count = journal.pending_page(limit=2)
    assert count == 69 and len(again) == 2 and again[0]['payload']['bar']['close'] == 2


@pytest.mark.parametrize('limit', [0, -1, 65, True])
def test_pending_page_rejects_unbounded_or_invalid_admission(journal, limit):
    with pytest.raises(ValueError):
        journal.pending_page(limit)


@pytest.mark.parametrize('method', ['pending', 'pending_count'])
def test_custom_pending_readers_keep_their_original_dispatch_contract(database, monkeypatch, method):
    async def run():
        manager = manager_for('2m')
        journal = manager.aggregator_bridge.delivery.journal
        original = getattr(journal, method)
        called = []
        def custom(*args):
            called.append(True)
            return original(*args)
        monkeypatch.setattr(journal, method, custom)
        try:
            await manager.aggregator_bridge.delivery.flush_pending()
            assert len(called) == (1 if method == 'pending' else 2)
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_failed_page_decode_retains_durable_receipt_for_exactly_one_later_delivery(database, monkeypatch):
    async def run():
        manager = manager_for('2m')
        delivery = manager.aggregator_bridge.delivery
        journal = delivery.journal
        journal.enqueue('page-read-fault', payload())
        original = journal._record
        failed = [True]
        attempts, observed = [], []
        def decode(row):
            attempts.append(True)
            if failed[0]:
                raise OSError('page decode interrupted')
            return original(row)
        monkeypatch.setattr(journal, '_record', decode)
        async def receive(event):
            observed.append(event.detail['delivery_id'])
        manager.event_bus.subscribe(receive)
        try:
            with pytest.raises(BarDeliveryUnavailable):
                await delivery.flush_pending()
            assert len(attempts) == 3 and journal.pending_count() == 1
            assert not observed and not delivery._dispatch_records
            assert not klines_repo.query_klines('BTCUSDT', '1m')
            failed[0] = False
            await delivery.flush_pending()
            assert journal.pending_count() == 0 and observed == ['page-read-fault']
            assert len(klines_repo.query_klines('BTCUSDT', '1m')) == 1
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())
