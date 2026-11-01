"""Acknowledgement microbatches retain per-event commit/publication order."""
import asyncio
import threading

import pytest

from app.data_engine.data_manager.bar_delivery import DurableBarDelivery
from tests.test_bar_delivery_journal import journal, payload
from tests.test_bar_delivery_bridge import storage, async_test, wait_for, bridge


def enqueue(journal, count):
    for i in range(count):
        value = payload(2 + i / 100)
        value['symbol'] = f'TEST{i}USDT'
        journal.enqueue(f'event-{i}', value)


def test_batch_ack_is_atomic_idempotent_and_never_promotes_pending(journal, monkeypatch):
    enqueue(journal, 4)
    for i in range(3):
        journal.commit(f'event-{i}')
    prune = journal._prune
    def fail(_connection):
        raise OSError('interrupted after updates before commit')
    monkeypatch.setattr(journal, '_prune', fail)
    with pytest.raises(OSError):
        journal.acknowledge_many(['event-0', 'event-1', 'event-3'])
    assert [r['phase'] for r in journal.pending()] == ['committed'] * 3 + ['pending']
    monkeypatch.setattr(journal, '_prune', prune)
    journal.acknowledge_many(['event-0', 'event-1', 'event-1', 'event-3'])
    journal.acknowledge_many(['event-0', 'event-1'])
    assert [(r['event_id'], r['phase']) for r in journal.pending()] == [
        ('event-2', 'committed'), ('event-3', 'pending')]


@pytest.mark.parametrize('ids', [[], ['x'] * 65, ['x' * 65537], [None], iter(['x'])])
def test_invalid_ack_batch_is_rejected_before_io(journal, monkeypatch, ids):
    monkeypatch.setattr(journal, '_connect', lambda: pytest.fail('invalid batch opened connection'))
    with pytest.raises(ValueError):
        journal.acknowledge_many(ids)


def test_rejected_recovery_and_committed_ack_share_one_atomic_boundary(journal, monkeypatch):
    enqueue(journal, 2)
    journal.commit('event-0')
    # Simulate the persisted rejection marker; this test exercises only the
    # receipt boundary after the owner has requested consumer recovery.
    from contextlib import closing
    with closing(journal._connect()) as connection, connection:
        connection.execute("UPDATE bar_delivery SET phase='rejected',recovery_required=1 WHERE event_id='event-1'")
    prune = journal._prune
    monkeypatch.setattr(journal, '_prune', lambda _c: (_ for _ in ()).throw(OSError('ack rollback')))
    with pytest.raises(OSError):
        journal.acknowledge_many(['event-0', 'event-1'])
    assert [(r['phase'], r['recovery_required']) for r in journal.pending()] == [
        ('committed', 0), ('rejected', 1)]
    monkeypatch.setattr(journal, '_prune', prune)
    journal.acknowledge_many(['event-0', 'event-1'])
    assert not journal.pending()


@async_test
@pytest.mark.parametrize('batch_size', [1, 2, 16])
async def test_publish_failure_restarts_only_unconfirmed_prefix(storage, batch_size):
    journal = storage.bar_delivery
    enqueue(journal, 6)
    first = []
    async def publish(event):
        if len(first) == 2:
            raise OSError('subscriber failed before third handoff')
        first.append(event.detail['delivery_id'])
    delivery = DurableBarDelivery(lambda: storage, publish, retry_delay=0,
        acknowledgement_batch_size=batch_size, acknowledgement_delay=100)
    await delivery.flush()
    assert first == ['event-0', 'event-1']
    expected_start = 0 if batch_size == 16 else 2
    assert journal.pending()[0]['event_id'] == f'event-{expected_start}'
    replayed = []
    async def recover(event):
        replayed.append(event.detail['delivery_id'])
        row = storage.query_bars(event.key.symbol, '1m')[0]
        assert row['close'] == event.bar.close
    restarted = DurableBarDelivery(lambda: storage, recover, retry_delay=0)
    await restarted.flush()
    assert replayed == [f'event-{i}' for i in range(expected_start, 6)]
    assert not journal.pending()


@async_test
async def test_close_and_amend_are_committed_and_published_sequentially(storage):
    journal = storage.bar_delivery
    journal.enqueue('close', payload(2))
    journal.enqueue('amend', payload(3, 'bar.amended'))
    observed = []
    async def publish(event):
        row = storage.query_bars('BTCUSDT', '1m')[0]
        observed.append((event.detail['delivery_id'], event.bar.close, row['close']))
    delivery = DurableBarDelivery(lambda: storage, publish, retry_delay=0, acknowledgement_delay=100)
    await delivery.flush()
    assert observed == [('close', 2, 2), ('amend', 3, 3)]
    assert delivery.snapshot()['acknowledgement_batches'] == 1
    assert delivery.snapshot()['acknowledgement_records'] == 2
    assert not journal.pending()


@async_test
async def test_shutdown_drains_physically_running_ack_transaction(storage, monkeypatch):
    journal = storage.bar_delivery
    enqueue(journal, 3)
    entered, release = threading.Event(), threading.Event()
    acknowledge = journal.acknowledge_many
    def blocked(ids):
        entered.set()
        assert release.wait(5)
        return acknowledge(ids)
    monkeypatch.setattr(journal, 'acknowledge_many', blocked)
    async def publish(_event):
        pass
    delivery = DurableBarDelivery(lambda: storage, publish, retry_delay=0, acknowledgement_delay=100)
    await delivery.start()
    stopping = None
    try:
        await wait_for(entered.is_set)
        stopping = asyncio.create_task(delivery.stop())
        await asyncio.sleep(.02)
        assert not stopping.done()
    finally:
        release.set()
        if stopping is not None:
            await stopping
        else:
            await delivery.stop()
    assert not journal.pending()


@async_test
async def test_failed_batch_ack_replays_without_duplicate_live_consumer_events(storage, monkeypatch):
    instance, bus = bridge(storage)
    instance.delivery.acknowledgement_delay = 100
    enqueue(storage.bar_delivery, 16)
    delivered = []
    async def receive(event):
        delivered.append(event.detail['delivery_id'])
    bus.subscribe(receive)
    acknowledge = storage.bar_delivery.acknowledge_many
    monkeypatch.setattr(storage.bar_delivery, 'acknowledge_many',
                        lambda ids: (_ for _ in ()).throw(OSError('batch ack unavailable')))
    try:
        await instance.delivery.flush()
        await wait_for(lambda: len(delivered) == 16)
        assert len(storage.bar_delivery.pending()) == 16
        assert instance.delivery.snapshot()['published'] == 0
        monkeypatch.setattr(storage.bar_delivery, 'acknowledge_many', acknowledge)
        await instance.delivery.flush()
        await asyncio.sleep(.02)
        assert delivered == [f'event-{i}' for i in range(16)]
        assert not storage.bar_delivery.pending()
        assert instance.delivery.snapshot()['published'] == 16
    finally:
        await bus.close()
