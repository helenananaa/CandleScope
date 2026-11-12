"""D126 bookkeeping belongs to the common cache budget even with zero bars."""
from collections import deque

import pytest

from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.data_manager.revisions import CacheRevisionConsumer
from app.data_engine.memory_budget import MemoryBudget, MemoryBudgetExceeded
from tests.test_kline_revision_contract import storage, write


def test_real_canonical_mutations_are_accounted_without_resident_bars(storage):
    manager = DataManager()
    manager.set_storage(storage)
    consumer = manager.cache.revision_consumer
    consumer.readbacks_enabled = True
    for index in range(64):
        write(symbol=f'ASSET{index}USDT')
    consumer.sync(force=True)
    usage = manager.memory_budget.snapshot(measure_heap=True)['owners']['bar-cache']
    assert usage['bars'] == usage['series'] == 0
    assert usage['revision_recent_entries'] == usage['revision_pending_readbacks'] == 64
    assert usage['estimated_bytes'] == usage['metadata_estimated_bytes'] > 0
    assert usage['unique_retained_bytes'] > 0
    # Budget pressure is explicit; correctness watermarks are not cache victims.
    budget = MemoryBudget(total_bytes=usage['estimated_bytes'] - 1)
    budget.register('bar-cache',limit_bytes=usage['estimated_bytes'] * 2,
                    usage=manager.cache.memory_usage, roots=manager.cache._memory_roots)
    with pytest.raises(MemoryBudgetExceeded), budget.reserve('bar-cache', 1):
        pass
    assert consumer.memory_usage()['revision_recent_entries'] == 64
    assert consumer.memory_usage()['revision_pending_readbacks'] == 64
    assert budget.snapshot()['reserved_bytes'] == 0


def test_scoped_cold_read_tokens_are_charged_until_release():
    cache = BarCache()
    key = SeriesKey('BTCUSDT','89m')
    assert cache.memory_usage()['metadata_estimated_bytes'] == 0
    with cache.read_token(key) as token:
        usage = cache.memory_usage()
        assert usage['bars'] == 0 and usage['active_read_tokens'] == 1
        assert usage['metadata_estimated_bytes'] > 0
        cache.clear()
        assert token.invalidated
        assert cache.memory_usage()['active_read_tokens'] == 1
    assert cache.memory_usage()['active_read_tokens'] == 0
    assert cache.memory_usage()['metadata_estimated_bytes'] == 0


class Changes:
    def __init__(self):
        self.batch = dict(revision=0,reset=False,changes=[])
    def changes_since(self, revision):
        return self.batch
    def change(self, number):
        key = SeriesKey(f'ASSET{number}USDT','1m')
        value = {name:getattr(key,name) for name in key.__slots__}
        value.update(revision=number,readback_revision=number,readback_previous=number-1,
                     readback_start_ms=0,readback_end_ms=60000)
        self.batch = dict(revision=number,reset=False,changes=[value])


def test_bounded_revision_eviction_readback_overflow_and_reset_release_estimates():
    store, cache = Changes(), BarCache()
    consumer = CacheRevisionConsumer(cache,store)
    consumer._recent = deque(maxlen=2)
    consumer.readbacks_enabled = True
    for number in (1,2):
        store.change(number); consumer.sync(force=True)
    full = consumer.memory_usage()
    assert full['revision_recent_entries'] == full['revision_pending_readbacks'] == 2
    reset, old = consumer.pending_readbacks()
    consumer.acknowledge_readback(old[0])
    after_ack = consumer.memory_usage()
    assert after_ack['revision_pending_readbacks'] == 1
    assert after_ack['revision_estimated_bytes'] < full['revision_estimated_bytes']
    consumer.acknowledge_readback(old[0])
    assert consumer.memory_usage() == after_ack
    # One new series fills the queue, the next collapses it to a reset marker.
    for number in (3,4):
        store.change(number); consumer.sync(force=True)
    overflow = consumer.memory_usage()
    assert overflow['revision_recent_entries'] == 2
    assert overflow['revision_pending_readbacks'] == 0 and overflow['revision_reset_pending']
    assert consumer._recent_bytes > 0 and consumer._readback_bytes == 0
    store.batch = dict(revision=5,reset=True,changes=[])
    consumer.sync(force=True)
    reset, values = consumer.pending_readbacks()
    assert not values
    consumer.acknowledge_readback(reset)
    assert consumer.memory_usage()['revision_estimated_bytes'] == 0
    assert consumer._recent_bytes == consumer._readback_bytes == 0


@pytest.mark.parametrize('method',['memory_usage','_memory_roots'])
def test_cache_diagnostics_never_acquire_revision_owner_under_cache_lock(monkeypatch, method):
    cache = BarCache()
    consumer = CacheRevisionConsumer(cache,Changes())
    cache.revision_consumer = consumer
    original = getattr(consumer,method)
    def checked():
        assert cache._lock.acquire(blocking=False), 'cache -> revision lock inversion'
        cache._lock.release()
        return original()
    monkeypatch.setattr(consumer,method,checked)
    getattr(cache,method)()


def test_replaced_readback_cannot_be_released_by_old_acknowledgement():
    store, cache = Changes(), BarCache()
    consumer = CacheRevisionConsumer(cache,store)
    consumer.readbacks_enabled = True
    store.change(1); consumer.sync(force=True)
    _, (old,) = consumer.pending_readbacks()
    changed = {**store.batch['changes'][0], 'revision':2, 'readback_revision':2,
               'readback_previous':1, 'readback_end_ms':120000}
    store.batch = dict(revision=2,reset=False,changes=[changed])
    consumer.sync(force=True)
    _, (new,) = consumer.pending_readbacks()
    assert old is not new
    accounted = consumer.memory_usage()['revision_estimated_bytes']
    consumer.acknowledge_readback(old)
    assert consumer.memory_usage()['revision_pending_readbacks'] == 1
    assert consumer.memory_usage()['revision_estimated_bytes'] == accounted
    consumer.acknowledge_readback(new)
    assert consumer.memory_usage()['revision_pending_readbacks'] == 0
    assert consumer.memory_usage()['revision_estimated_bytes'] < accounted


def test_empty_reserved_history_identity_is_counted_and_clear_releases_it():
    cache = BarCache()
    key = SeriesKey('BTCUSDT','89m')
    reserved = cache.reserve_history_capacity(key, cache._cfg.max_bars_per_series + 1)
    assert reserved.active
    cache.invalidate(key)
    usage = cache.memory_usage()
    assert usage['bars'] == usage['series'] == 0
    assert usage['history_capacity_entries'] == 1 and usage['metadata_estimated_bytes'] > 0
    cache.clear()
    assert cache.memory_usage()['metadata_estimated_bytes'] == 0
