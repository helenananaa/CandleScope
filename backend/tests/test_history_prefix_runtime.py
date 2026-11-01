"""Real SQLite canonical changes through the actual live aggregator boundary."""
import asyncio
from dataclasses import replace
import threading

import pytest

from app.data_engine.bar_aggregator import BarAggregator
from app.data_engine.bar_aggregator.models import MergeMode
from app.data_engine.data_manager.history_prefix_runtime import HistoryPrefixRuntime
from tests.test_shared_blocks_integration import dm, write, read_rows, KEY, DAY
from tests.test_history_prefix_overlay import component, equal, state
from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge


@pytest.fixture(autouse=True)
def small_controlled_prefix(monkeypatch):
    monkeypatch.setattr(HistoryPrefixRuntime, 'MIN_ROWS', 64)


@pytest.fixture
def runtime(dm, monkeypatch):
    monkeypatch.setattr('time.time', lambda: 120 * DAY / 1000 + 30)
    agg = BarAggregator()
    agg.add_target('BTCUSDT', '121d', market_type='futures')
    recovery = []
    service = HistoryPrefixRuntime(dm.query_engine, agg, recovery.append)
    agg.history_prefix_runtime = service
    return agg, service, recovery


async def feed(agg, row, *, closed=False):
    incoming = replace(component(row, closed=closed), merge_mode=MergeMode.COMPONENT)
    await agg.ingest_bar_input('binance', 'futures', 'BTCUSDT', '121d', incoming,
                               emit_events=False)


def actual(agg):
    return agg.get_bucket_state('BTCUSDT', '121d', 0, market_type='futures')


def reference(dm, tail):
    target = state()
    merge = ComponentSnapshotOHLCVMerge()
    for row in read_rows(dm):
        merge.apply(target, component(row), is_new=False)
    merge.apply(target, component(tail, closed=False), is_new=False)
    return target


def test_warm_prefix_live_tail_and_canonical_correction_match_full_recompute(dm, runtime):
    agg, service, recovery = runtime
    async def check():
        rows = read_rows(dm)
        tail = replace(rows[-1], time=120 * DAY // 1000, volume=4)
        await feed(agg, tail)
        assert await service.seed(KEY, '121d', 0, 120 * DAY)
        assert len(actual(agg).source_snapshots) == 1
        equal(actual(agg), reference(dm, tail))
        write([replace(rows[31], high=rows[31].close, volume=1)])
        tail = replace(tail, volume=8)
        await feed(agg, tail)
        equal(actual(agg), reference(dm, tail))
        assert service.metrics['refreshes'] == 1
        assert not recovery
        await service.close()
    asyncio.run(check())


def test_fresh_prefix_never_upgrades_the_acquisition_of_a_retained_live_tail(dm, runtime):
    agg, service, _ = runtime
    agg.acquisition_revision_provider = lambda: 1
    async def check():
        rows = read_rows(dm)
        tail = replace(rows[-1], time=120 * DAY // 1000, volume=4)
        await feed(agg, tail)
        assert await service.seed(KEY, '121d', 0, 120 * DAY)
        assert actual(agg)._history_prefix.acquisition_revision > 1
        assert actual(agg).acquisition_revision == 1
        write([replace(rows[31], volume=1)])
        await feed(agg, replace(tail, volume=5))
        assert actual(agg).acquisition_revision == 1
        await service.close()
    asyncio.run(check())


def test_failed_source_validation_signals_recovery_without_mutating_tail(dm, runtime, monkeypatch):
    from app.data_engine.aggregation.blocks import BlockUnavailable
    agg, service, recovery = runtime
    async def check():
        tail = replace(read_rows(dm)[-1], time=120 * DAY // 1000, volume=4)
        await feed(agg, tail)
        assert await service.seed(KEY, '121d', 0, 120 * DAY)
        previous = actual(agg)
        def fail(*_args, **_kwargs):
            raise BlockUnavailable('source cannot prove its revision')
        monkeypatch.setattr(service.reader, 'validate', fail)
        with pytest.raises(BlockUnavailable):
            await feed(agg, replace(tail, volume=5))
        equal(actual(agg), previous)
        assert recovery == [replace(KEY, interval='121d')]
        assert service.metrics['failures'] == 1
        await service.close()
    asyncio.run(check())


def test_empty_delete_repeated_stale_input_and_partial_repair_never_resurrect(dm, runtime):
    agg, service, recovery = runtime
    async def check():
        rows = read_rows(dm)
        assert await service.seed(KEY, '121d', 0, 120 * DAY)
        dm.query_engine.storage.delete_bars('BTCUSDT', '1d', start_ms=0,
                                           end_ms=120 * DAY, market_type='futures')
        for _ in range(3):
            await feed(agg, rows[10], closed=True)
            assert actual(agg) is None
        assert recovery and service.metrics['empty'] == 1
        tail = replace(rows[-1], time=120 * DAY // 1000, volume=7)
        await feed(agg, tail)
        assert actual(agg).volume == 7 and actual(agg)._history_prefix is None
        await feed(agg, rows[10], closed=True)
        assert actual(agg).volume == 7
        write([rows[40]])
        await feed(agg, rows[10], closed=True)
        equal(actual(agg), reference(dm, tail))
        assert actual(agg)._history_prefix.summary.coverage.count == 1
        await service.close()
    asyncio.run(check())


def test_initial_pages_do_not_block_live_overlay_and_detach_discards_late_result(dm, runtime, monkeypatch):
    agg, service, recovery = runtime
    original = service.reader._read_page
    entered, release = threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(service.reader, '_read_page', blocked)
    async def check():
        task = asyncio.create_task(service.seed(KEY, '121d', 0, 120 * DAY))
        try:
            while not entered.is_set():
                await asyncio.sleep(.01)
            tail = replace(read_rows(dm)[-1], time=120 * DAY // 1000, volume=5)
            await asyncio.wait_for(feed(agg, tail), 1)
            assert actual(agg).volume == 5
            agg.remove_target('BTCUSDT', '121d', market_type='futures')
            release.set()
            assert await task
            assert actual(agg) is None and not service.targets
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await service.close()
        assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(check())


def test_shutdown_waits_for_physical_page_and_releases_handoff_capacity(dm, runtime, monkeypatch):
    agg, service, _ = runtime
    original = service.reader._read_page
    entered, release = threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(service.reader, '_read_page', blocked)
    async def check():
        seed = asyncio.create_task(service.seed(KEY, '121d', 0, 120 * DAY))
        try:
            while not entered.is_set():
                await asyncio.sleep(.01)
            stopping = asyncio.create_task(service.close())
            await asyncio.sleep(.05)
            assert not stopping.done()
            release.set()
            await stopping
            assert seed.cancelled()
            assert not service.tasks and not service.targets
            assert actual(agg) is None
        finally:
            release.set()
            await asyncio.gather(seed, return_exceptions=True)
        assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(check())


def test_actual_data_manager_warm_start_uses_bounded_storage_pages_and_cache(dm, monkeypatch):
    monkeypatch.setattr('time.time', lambda: 120 * DAY / 1000 + 30)
    original = dm.query_engine.storage.query_bars
    calls = []
    def query(*args, **kwargs):
        calls.append((threading.current_thread().name, kwargs.get('limit')))
        return original(*args, **kwargs)
    monkeypatch.setattr(dm.query_engine.storage, 'query_bars', query)
    async def check():
        dm.bar_aggregator.add_target('BTCUSDT', '121d', market_type='futures')
        await dm.warm_start.seed_if_needed('BTCUSDT', '121d', exchange='binance',
                                          market_type='futures', had_stream=True)
        current = actual(dm.bar_aggregator)
        assert current is not None and current._history_prefix is not None
        assert current.tick_count == 120 and not current.source_snapshots
        cached = dm.cache.get_latest(replace(KEY, interval='121d'), 1)
        assert len(cached) == 1 and cached[0].volume == current.volume
        assert calls and all(limit is not None and limit <= 257 for _thread, limit in calls)
        assert all(name != threading.main_thread().name for name, _limit in calls)
        assert dm.history_prefix_runtime.snapshot()['adoptions'] == 1
    asyncio.run(check())


def test_large_new_bucket_and_partial_history_do_not_query_previous_full_bucket(dm, monkeypatch):
    monkeypatch.setattr('time.time', lambda: 30)
    # An already admitted large prefix can become empty after deletion; that
    # recovery behavior is independent of the default size selection policy.
    monkeypatch.setattr(HistoryPrefixRuntime, 'MIN_ROWS', 0)
    original = dm.query_engine.storage.query_bars
    calls = []
    def query(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(dm.query_engine.storage, 'query_bars', query)
    async def check():
        dm.bar_aggregator.add_target('BTCUSDT', '121d', market_type='futures')
        await dm.warm_start.seed_if_needed('BTCUSDT', '121d', exchange='binance',
                                          market_type='futures', had_stream=True)
        assert not calls and actual(dm.bar_aggregator) is None
        monkeypatch.setattr('time.time', lambda: 120 * DAY / 1000 + 30)
        dm.query_engine.storage.delete_bars('BTCUSDT', '1d', start_ms=0,
                                           end_ms=0, market_type='futures')
        await dm.warm_start.seed_if_needed('BTCUSDT', '121d', exchange='binance',
                                          market_type='futures', had_stream=True)
        current = actual(dm.bar_aggregator)
        assert current is not None and current._history_prefix is not None
        assert not current._history_prefix.complete
        assert calls and all(call.get('limit', 1000000) <= 257 for call in calls)
    asyncio.run(check())


def test_default_size_selection_keeps_small_histories_on_legacy_path(dm, runtime, monkeypatch):
    agg, service, _ = runtime
    monkeypatch.setattr(HistoryPrefixRuntime, 'MIN_ROWS', 2048)
    async def check():
        assert not await service.seed(KEY, '121d', 0, 120 * DAY)
        assert not service.targets and actual(agg) is None
        await service.close()
    asyncio.run(check())


def test_new_bucket_warm_fallback_does_not_expand_an_owned_previous_prefix(dm, monkeypatch):
    monkeypatch.setattr('time.time', lambda: 120 * DAY / 1000 + 30)
    original = dm.query_engine.storage.query_bars
    calls = []
    def query(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    async def check():
        dm.bar_aggregator.add_target('BTCUSDT', '121d', market_type='futures')
        await dm.warm_start.seed_if_needed('BTCUSDT', '121d', exchange='binance',
                                          market_type='futures', had_stream=True)
        assert actual(dm.bar_aggregator)._history_prefix is not None
        monkeypatch.setattr('time.time', lambda: 121 * DAY / 1000 + 30)
        monkeypatch.setattr(dm.query_engine.storage, 'query_bars', query)
        await dm.warm_start.seed_if_needed('BTCUSDT', '121d', exchange='binance',
                                          market_type='futures', had_stream=True)
        assert calls and all(call['start_ms'] >= 121 * DAY for call in calls)
    asyncio.run(check())
