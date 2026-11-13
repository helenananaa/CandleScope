"""Confirmed live leaves retire only after fenced, exact canonical readback."""
import asyncio
from dataclasses import replace
import threading

import pytest

from app.data_engine.bar_aggregator import BarAggregator
from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
from app.data_engine.bar_aggregator.history_prefix_runtime import HistoryPrefixRuntime
from app.data_engine.bar_aggregator.models import BarInput, BarInputSource, BarState, MergeMode
from app.data_engine.data_manager.history_prefix import HistoryPrefixReader
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.storage import klines_repo
from tests.test_shared_blocks_integration import dm
from tests.test_history_prefix_overlay import equal as equivalent

WIDTH = 60_000
KEY = SeriesKey('BTCUSDT', '1m', market_type='futures')
TARGET = '10007m'


def equal(actual, expected):
    equivalent(actual, expected)
    for name in ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades',
                 'taker_buy_base', 'taker_buy_quote', 'first_input_at_ms',
                 'last_input_at_ms', 'last_close_received'):
        assert getattr(actual, name) == getattr(expected, name)


def persist(rows):
    klines_repo.upsert_klines(KEY.symbol, KEY.interval, [dict(
        open_time=r.time_ms, close_time=r.time_ms + WIDTH - 1,
        **{name:getattr(r, name) for name in ('open', 'high', 'low', 'close',
            'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote')})
        for r in rows], source='backfill', market_type=KEY.market_type)


def component(row, closed=True):
    return BarInput(symbol=KEY.symbol, source_interval=KEY.interval,
        market_type=KEY.market_type, open_time_ms=row.time_ms,
        close_time_ms=row.time_ms + WIDTH - 1, is_closed=closed,
        source=BarInputSource.BACKFILL if closed else BarInputSource.REALTIME,
        merge_mode=MergeMode.COMPONENT, enhanced_fields=row.enhanced_fields,
        **{name:getattr(row, name) or 0 for name in ('open', 'high', 'low', 'close',
            'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote')})


@pytest.fixture
def setup(dm, monkeypatch):
    monkeypatch.setattr('time.time', lambda: 5000 * 60)
    monkeypatch.setattr(HistoryPrefixRuntime, 'MIN_ROWS', 64)
    monkeypatch.setattr(HistoryPrefixRuntime, 'COMPACT_ROWS', 4)
    rows = [BarData(time=i * 60, open=10, high=20 + i % 7, low=5, close=11,
        volume=i + 1, quote_volume=2 * (i + 1), trades=3,
        taker_buy_base=1, taker_buy_quote=2, source='backfill') for i in range(2400)]
    persist(rows)
    agg = BarAggregator()
    agg.add_target(KEY.symbol, TARGET, market_type=KEY.market_type)
    recovery = []
    runtime = HistoryPrefixRuntime(HistoryPrefixReader(dm.query_engine), agg, recovery.append)
    agg.history_prefix_runtime = runtime
    def current():
        return agg.get_bucket_state(KEY.symbol, TARGET, 0, market_type=KEY.market_type)
    async def feed(row, closed=True):
        await agg.ingest_bar_input(KEY.exchange, KEY.market_type, KEY.symbol, TARGET,
                                   component(row, closed), emit_events=False)
    return rows, agg, runtime, recovery, current, feed


def test_repeated_rollover_retains_forming_tail_and_rebuilds_old_correction(dm, setup):
    rows, agg, runtime, recovery, current, feed = setup
    async def check():
        assert await runtime.seed(KEY, TARGET, 0, 64 * WIDTH)
        reference = BarState(KEY.symbol, TARGET, 0, 10007 * WIDTH, 0, 0, 0, 0, 0,
                             market_type=KEY.market_type)
        merge = ComponentSnapshotOHLCVMerge(incremental=False)
        for row in rows[:64]:
            merge.apply(reference, component(row), is_new=False)
        for index in range(64, 89):
            await feed(rows[index], closed=False)
            merge.apply(reference, component(rows[index], False), is_new=False)
            equal(current(), reference)
            await feed(rows[index])
            merge.apply(reference, component(rows[index]), is_new=False)
            equal(current(), reference)
            assert len(current().source_snapshots) <= 5
        assert runtime.metrics['compactions'] == 6
        assert runtime.metrics['compacted_components'] == 24
        assert current()._history_prefix.through_ms == 88 * WIDTH
        # A later canonical correction inside the retired prefix still goes
        # through its original revision refresh, never a stale retained leaf.
        persist([replace(rows[70], volume=1, high=21)])
        await feed(rows[89], closed=False)
        rebuilt = replace(reference, source_snapshots={}, source_refs={}, _component_accumulator=None)
        merge = ComponentSnapshotOHLCVMerge(incremental=False)
        for index, row in enumerate(rows[:90]):
            if index == 70:
                row = replace(row, volume=1, high=21)
            merge.apply(rebuilt, component(row, index < 89), is_new=False)
        equal(current(), rebuilt)
        assert not recovery
        await runtime.close()
    asyncio.run(check())


@pytest.mark.parametrize('variant', ['missing', 'opposite-corrections', 'unknown-fields', 'forming'])
def test_unqualified_seam_keeps_every_accepted_leaf_and_does_not_retry_each_preview(dm, setup, variant):
    rows, agg, runtime, recovery, current, feed = setup
    async def check():
        assert await runtime.seed(KEY, TARGET, 0, 64 * WIDTH)
        for index in range(64, 68):
            row = rows[index]
            if variant == 'unknown-fields' and index == 65:
                row = replace(row, quote_volume=None, trades=None,
                              taker_buy_base=None, taker_buy_quote=None)
            await feed(row, closed=not (variant == 'forming' and index == 65))
        if variant == 'missing':
            dm.query_engine.storage.delete_bars(KEY.symbol, KEY.interval,
                start_ms=65 * WIDTH, end_ms=66 * WIDTH, market_type=KEY.market_type)
        elif variant == 'opposite-corrections':
            # Same aggregate volume, different accepted leaves: cannot retire.
            persist([replace(rows[65], volume=rows[65].volume + 1),
                     replace(rows[66], volume=rows[66].volume - 1)])
        await feed(rows[68], closed=False)
        assert current()._history_prefix.through_ms == 64 * WIDTH
        await feed(rows[68])
        assert current()._history_prefix.through_ms == 64 * WIDTH
        assert len(current().source_snapshots) == 5
        deferred = runtime.metrics['compaction_deferred']
        for _ in range(3):
            await feed(rows[68])
            await feed(rows[68], closed=False)
        assert runtime.metrics['compaction_deferred'] == deferred
        assert not recovery
        await runtime.close()
    asyncio.run(check())


@pytest.mark.parametrize('failure', ['budget', 'read', 'revision'])
def test_optional_read_failure_preserves_prefix_and_source_acceptance(dm, setup, monkeypatch, failure):
    from app.data_engine.aggregation.blocks import BlockUnavailable, BlockRevisionChanged
    from app.data_engine.memory_budget import MemoryBudgetExceeded
    rows, agg, runtime, recovery, current, feed = setup
    async def check():
        assert await runtime.seed(KEY, TARGET, 0, 64 * WIDTH)
        for row in rows[64:68]:
            await feed(row)
        def fail(*_args):
            raise {'budget':MemoryBudgetExceeded, 'read':BlockUnavailable,
                   'revision':BlockRevisionChanged}[failure]('controlled optional failure')
        monkeypatch.setattr(runtime.reader, 'matches_closed_overlay', fail)
        await feed(rows[68])
        assert current()._history_prefix.through_ms == 64 * WIDTH
        assert len(current().source_snapshots) == 5
        assert runtime.metrics['compaction_deferred'] == 1 and not recovery
        await runtime.close()
        assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(check())


@pytest.mark.parametrize('action', ['detach', 'cancel'])
def test_inflight_compaction_cannot_adopt_after_lifetime_end(dm, setup, monkeypatch, action):
    rows, agg, runtime, recovery, current, feed = setup
    original = runtime.reader.matches_closed_overlay
    entered, released = threading.Event(), threading.Event()
    def blocked(*args):
        entered.set()
        assert released.wait(10)
        return original(*args)
    async def check():
        assert await runtime.seed(KEY, TARGET, 0, 64 * WIDTH)
        for row in rows[64:68]:
            await feed(row)
        monkeypatch.setattr(runtime.reader, 'matches_closed_overlay', blocked)
        task = asyncio.create_task(feed(rows[68]))
        try:
            while not entered.is_set():
                await asyncio.sleep(.01)
            if action == 'detach':
                agg.remove_target(KEY.symbol, TARGET, market_type=KEY.market_type)
            else:
                task.cancel()
            released.set()
            await asyncio.gather(task, return_exceptions=True)
            assert runtime.metrics['compactions'] == 0
            if action == 'cancel':
                assert current()._history_prefix.through_ms == 64 * WIDTH
                assert len(current().source_snapshots) == 4
            else:
                assert current() is None
        finally:
            released.set()
            await asyncio.gather(task, return_exceptions=True)
            await runtime.close()
        assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(check())


def test_production_size_prefix_and_seam_are_bounded(dm, setup, monkeypatch):
    rows, agg, runtime, recovery, current, feed = setup
    monkeypatch.setattr(HistoryPrefixRuntime, 'MIN_ROWS', 2048)
    monkeypatch.setattr(HistoryPrefixRuntime, 'COMPACT_ROWS', 128)
    async def check():
        assert await runtime.seed(KEY, TARGET, 0, 2048 * WIDTH)
        for row in rows[2048:2306]:
            await feed(row)
        assert runtime.metrics['compactions'] == 2
        assert runtime.metrics['compacted_components'] == 256
        assert current()._history_prefix.through_ms == 2304 * WIDTH
        assert len(current().source_snapshots) == 2
        assert not recovery
        await runtime.close()
    asyncio.run(check())


def test_compaction_does_not_add_a_public_event_or_materialize_on_a_preview(dm, setup):
    rows, agg, runtime, recovery, current, feed = setup
    events = []
    agg.publisher._cfg.update_throttle_ms = 0
    agg.publisher.on_bar_event(events.append)
    async def check():
        assert await runtime.seed(KEY, TARGET, 0, 64 * WIDTH)
        for row in rows[64:68]:
            await feed(row)
        before = runtime.metrics['adoptions']
        for _ in range(5):
            await feed(rows[68], closed=False)
        assert runtime.metrics['adoptions'] == before
        events.clear()
        await agg.ingest_bar_input(KEY.exchange, KEY.market_type, KEY.symbol, TARGET,
                                   component(rows[68]), emit_events=True)
        assert runtime.metrics['compactions'] == 1
        assert len(events) == 1
        assert events[0].bar.tick_count == 69
        assert not recovery
        await runtime.close()
    asyncio.run(check())
