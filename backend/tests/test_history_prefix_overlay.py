"""Same canonical input through full components and compact prefix + overlay."""
import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from app.data_engine.bar_aggregator.bar_state import (
    ComponentSnapshotOHLCVMerge, has_complete_closed_component_coverage,
)
from app.data_engine.bar_aggregator.models import BarInput, BarInputSource, BarState
from app.data_engine.bar_aggregator import BarAggregator
from app.data_engine.data_manager.history_prefix import HistoryPrefixReader
from tests.test_shared_blocks_integration import dm, write, read_rows, KEY, DAY


def state():
    return BarState('BTCUSDT', '121d', 0, 121 * DAY, 0, 0, 0, 0, 0,
                    market_type='futures')


def component(row, *, closed=True, sequence=None):
    return BarInput(symbol='BTCUSDT', exchange='binance', market_type='futures',
        source_interval='1d', open_time_ms=row.time_ms, close_time_ms=row.time_ms + DAY - 1,
        open=row.open, high=row.high, low=row.low, close=row.close, volume=row.volume,
        quote_volume=row.quote_volume or 0, trades=row.trades or 0,
        taker_buy_base=row.taker_buy_base or 0, taker_buy_quote=row.taker_buy_quote or 0,
        enhanced_fields=row.enhanced_fields, is_closed=closed, sequence=sequence,
        source=BarInputSource.BACKFILL if closed else BarInputSource.REALTIME)


def equal(a, b):
    for field in ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades',
                  'taker_buy_base', 'taker_buy_quote'):
        assert getattr(a, field) == pytest.approx(getattr(b, field), abs=1e-8, rel=1e-12)
    assert a.tick_count == b.tick_count
    assert a.enhanced_fields == b.enhanced_fields
    assert has_complete_closed_component_coverage(a) == has_complete_closed_component_coverage(b)


@pytest.mark.parametrize('incremental', [True, False])
def test_tail_replacement_close_copy_and_compact_state_match_full_components(dm, incremental):
    async def check():
        rows = read_rows(dm)
        reference, compact = state(), state()
        merge = ComponentSnapshotOHLCVMerge(incremental=incremental)
        for row in rows:
            merge.apply(reference, component(row), is_new=False)
        async with HistoryPrefixReader(dm.query_engine).stage(KEY, 0, 120 * DAY) as prefix:
            merge.adopt_history_prefix(compact, prefix)
        equal(compact, reference)
        assert len(compact.source_snapshots) == 0
        # A repeated cumulative tail replaces; it is never added twice.
        tail = replace(rows[-1], time=120 * DAY // 1000, volume=4)
        for index in range(1, 5):
            bar = component(replace(tail, volume=4 + index), closed=index == 4, sequence=index)
            merge.apply(reference, bar, is_new=False)
            merge.apply(compact, bar, is_new=False)
            equal(compact, reference)
            equal(deepcopy(compact), reference)
            assert len(compact.source_snapshots) == 1
        assert has_complete_closed_component_coverage(compact)
        before = deepcopy(compact)
        with pytest.raises(ValueError, match='prefix revision refresh'):
            merge.apply(compact, component(rows[0]), is_new=False)
        equal(compact, before)
    asyncio.run(check())


def test_refresh_replaces_reduced_extreme_and_volume_without_losing_live_overlay(dm):
    async def check():
        rows = read_rows(dm)
        merge, live = ComponentSnapshotOHLCVMerge(), state()
        tail = replace(rows[-1], time=120 * DAY // 1000, high=500, low=1, volume=7)
        # Live events are already present when the initial history page finishes.
        merge.apply(live, component(tail, closed=False), is_new=True)
        reader = HistoryPrefixReader(dm.query_engine)
        async with reader.stage(KEY, 0, 120 * DAY) as prefix:
            merge.adopt_history_prefix(live, prefix)
        corrected = replace(rows[40], high=rows[40].close, volume=1)
        write([corrected])
        async with reader.stage(KEY, 0, 120 * DAY) as fresh:
            assert fresh.summary.revisions != prefix.summary.revisions
            merge.adopt_history_prefix(live, fresh)
        reference = state()
        for row in read_rows(dm):
            merge.apply(reference, component(row), is_new=False)
        merge.apply(reference, component(tail, closed=False), is_new=False)
        equal(live, reference)
        assert len(live.source_snapshots) == 1
    asyncio.run(check())


@pytest.mark.parametrize('change', ['remove', 'replace', 'stop'])
def test_detached_target_or_old_generation_cannot_adopt_late_prefix(dm, change):
    async def check():
        agg = BarAggregator()
        agg.add_target('BTCUSDT', '121d', market_type='futures')
        token = agg.history_target_token(KEY, '121d')
        async with HistoryPrefixReader(dm.query_engine).stage(KEY, 0, 120 * DAY) as prefix:
            if change == 'stop':
                await agg.stop()
            else:
                agg.remove_target('BTCUSDT', '121d', market_type='futures')
                if change == 'replace':
                    agg.add_target('BTCUSDT', '121d', market_type='futures')
            with pytest.raises(ValueError, match='generation expired'):
                agg.adopt_history_prefix(prefix, token, acquisition_revision=1)
            assert not agg.get_active_bars('BTCUSDT', '121d', market_type='futures')
    asyncio.run(check())


def test_owner_adoption_preserves_interleaved_tail_and_publishes_detached_snapshot(dm, monkeypatch):
    # The canonical fixture starts at epoch zero. Its final bucket must be
    # forming at this simulated time rather than timeout-closed in 2026.
    monkeypatch.setattr('time.time', lambda: 120 * DAY / 1000 + 30)
    async def check():
        agg = BarAggregator()
        agg.add_target('BTCUSDT', '121d', market_type='futures')
        token = agg.history_target_token(KEY, '121d')
        async with HistoryPrefixReader(dm.query_engine).stage(KEY, 0, 120 * DAY) as prefix:
            tail = replace(read_rows(dm)[-1], time=120 * DAY // 1000, volume=3)
            from app.data_engine.bar_aggregator.models import MergeMode
            incoming = replace(component(tail, closed=False), merge_mode=MergeMode.COMPONENT)
            await agg.ingest_bar_input('binance', 'futures', 'BTCUSDT', '121d', incoming,
                                       emit_events=False)
            adopted = agg.adopt_history_prefix(prefix, token, acquisition_revision=1)
            assert adopted.tick_count == 121 and len(adopted.source_snapshots) == 1
            assert adopted.volume == pytest.approx(prefix.summary.values.volume + 3)
            assert agg.memory_usage()['history_prefixes'] == 1
            adopted.volume = -1
            assert agg.get_bucket_state('BTCUSDT', '121d', 0, market_type='futures').volume > 0
    asyncio.run(check())


@pytest.mark.parametrize('deleted', [0, 60, 119])
def test_explicit_partial_refresh_preserves_gap_and_unknown_enhanced_totals(dm, deleted):
    dm.query_engine.storage.delete_bars('BTCUSDT', '1d', start_ms=deleted * DAY,
                                       end_ms=deleted * DAY, market_type='futures')
    async def check():
        async with HistoryPrefixReader(dm.query_engine).stage(
                KEY, 0, 120 * DAY, page_rows=16, require_complete=False) as prefix:
            assert not prefix.complete
            compact, reference = state(), state()
            merge = ComponentSnapshotOHLCVMerge()
            merge.adopt_history_prefix(compact, prefix)
            for row in read_rows(dm):
                merge.apply(reference, component(row), is_new=False)
            tail = replace(read_rows(dm)[-1], time=120 * DAY // 1000)
            for target in (compact, reference):
                merge.apply(target, component(tail), is_new=False)
            equal(compact, reference)
            assert not has_complete_closed_component_coverage(compact)
            assert not compact.enhanced_fields
            assert len(compact.source_snapshots) == 1
    asyncio.run(check())
