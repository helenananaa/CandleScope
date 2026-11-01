"""129-A differential, lifecycle and work-bound contracts."""
from copy import deepcopy
import asyncio
from dataclasses import replace
import gc
import math
import random

import pytest

from app.data_engine.bar_aggregator import (
    BarAggregator, BarAggregatorConfig, BarStateEngine, BarInput, BarInputSource,
    BarStateChange, BarEventType, TimeBucketEngine, MergeMode,
)
from app.data_engine.bar_aggregator.bar_state import has_complete_closed_component_coverage
from app.data_engine.bar_aggregator import component_accumulator as module
from app.data_engine.memory_budget import retained_size

MINUTE = 60_000


def component(index, *, closed=True, sequence=1, **changes):
    p = 100 + math.sin(index / 11)
    row = BarInput(symbol='BTCUSDT', source_interval='1m', open_time_ms=index * MINUTE,
        close_time_ms=(index + 1) * MINUTE - 1, open=p, high=p + 2, low=p - 2,
        close=p + .25, volume=1 + index / 37, quote_volume=101 + index / 19,
        trades=10 + index, taker_buy_base=.25, taker_buy_quote=25,
        source=BarInputSource.BACKFILL, is_closed=closed, sequence=sequence,
        merge_mode=MergeMode.COMPONENT)
    return replace(row, **changes)


def engine(size=97, *, incremental=True, **config):
    return BarStateEngine(BarAggregatorConfig(incremental_components=incremental, **config),
                          TimeBucketEngine(size * MINUTE), f'{size}m')


def apply(executor, row, start=0):
    return executor.apply(row.exchange, row.market_type, row.symbol, start, row)


def equal(a, b):
    for name in ('open', 'high', 'low', 'close', 'volume', 'quote_volume',
                 'trades', 'taker_buy_base', 'taker_buy_quote'):
        assert getattr(a, name) == pytest.approx(getattr(b, name), rel=1e-12, abs=1e-8), name
    for name in ('enhanced_fields', 'tick_count', 'first_input_at_ms', 'last_input_at_ms',
                 'last_close_received', 'status', 'finality', 'close_reason'):
        assert getattr(a, name) == getattr(b, name), name
    assert a.source_snapshots == b.source_snapshots
    assert has_complete_closed_component_coverage(a) == has_complete_closed_component_coverage(b)


@pytest.mark.parametrize('size', [7, 89, 97, 101])
@pytest.mark.parametrize('variant', ['ordered', 'shuffled', 'holes', 'unknown', 'overlap'])
def test_every_accepted_step_matches_batch(size, variant):
    fast, slow = engine(size), engine(size, incremental=False)
    rows = [component(i) for i in range(size)]
    if variant == 'shuffled':
        random.Random(71).shuffle(rows)
    elif variant == 'holes':
        rows = rows[1::2]
    elif variant == 'unknown':
        rows = [replace(r, quote_volume=None, trades=None, enhanced_fields=frozenset())
                if i % 3 == 0 else r for i, r in enumerate(rows)]
    elif variant == 'overlap':
        rows[size // 2] = replace(rows[size // 2], close_time_ms=(size // 2 + 2) * MINUTE - 1)
    for row in rows:
        a, ac = apply(fast, row)
        b, bc = apply(slow, row)
        assert ac == bc
        equal(a, b)
    assert a._component_accumulator is not None


@pytest.mark.parametrize('position', [0, 31, 63])
@pytest.mark.parametrize('change', ['extrema', 'unknown', 'boundary', 'sequence', 'revision'])
def test_authoritative_replacement_recomputes_without_double_count(position, change):
    fast, slow = engine(), engine(incremental=False)
    rows = [component(i) for i in range(64)]
    for row in rows:
        a, _ = apply(fast, row)
        b, _ = apply(slow, row)
    old = rows[position]
    corrected = replace(old, sequence=2, source=BarInputSource.CORRECTION,
                        open=99, high=100, low=98, close=99, volume=.1,
                        quote_volume=10, trades=1, taker_buy_base=.05, taker_buy_quote=5)
    if change == 'unknown':
        corrected = replace(corrected, enhanced_fields=frozenset(), quote_volume=None, trades=None)
    elif change == 'boundary':
        corrected = replace(corrected, close_time_ms=old.close_time_ms - 1000,
                            extra={'source_ref': {'revision': 2}})
    elif change == 'sequence':
        corrected = replace(old, sequence=0)  # rejected, unchanged index
    elif change == 'revision':
        corrected = replace(corrected, sequence=None, extra={'source_ref': {'revision': 2}})
    before = a._component_accumulator.rebuilds
    a, ac = apply(fast, corrected)
    b, bc = apply(slow, corrected)
    assert ac == bc
    equal(a, b)
    if change == 'sequence':
        assert ac == BarStateChange.NO_CHANGE
        assert a._component_accumulator.rebuilds == before
    elif position == 63 and change != 'boundary':
        assert a._component_accumulator.rebuilds == before
    else:
        assert a._component_accumulator.rebuilds == before + 1


def test_long_tail_updates_do_not_sort_scan_or_rebuild(monkeypatch):
    fast = engine(10007)
    for i in range(10006):
        a, _ = apply(fast, component(i))
    a, _ = apply(fast, component(10006, closed=False))
    index = a._component_accumulator
    before = index.rebuilt_components
    def no_rebuild(*a, **kw):
        pytest.fail('normal tail update rebuilt prefix')
    monkeypatch.setattr(module, 'sorted', no_rebuild, raising=False)
    for seq in range(2, 102):
        a, _ = apply(fast, component(10006, closed=False, sequence=seq, volume=1000 + seq,
                                    quote_volume=100_000 + seq))
    assert index.rebuilt_components == before == 1
    assert index.tail_replacements == 100
    assert len(index.prefixes) <= 14
    assert retained_size((index,))[0] <= index.snapshot()['estimated_bytes']
    assert not has_complete_closed_component_coverage(a)
    a, _ = apply(fast, component(10006, closed=True, sequence=102, volume=1102, quote_volume=100102))
    assert has_complete_closed_component_coverage(a)


@pytest.mark.parametrize('seed', range(6))
def test_repeated_mixed_corrections_match_batch(seed):
    rng = random.Random(seed)
    fast, slow = engine(101), engine(101, incremental=False)
    sequences = {}
    for _ in range(250):
        i = rng.randrange(101)
        sequences[i] = sequences.get(i, 0) + 1
        row = component(i, sequence=sequences[i], volume=rng.random() * 100,
                        high=105 + rng.random(), low=95 - rng.random())
        a, ac = apply(fast, row)
        b, bc = apply(slow, row)
        assert ac == bc
        equal(a, b)


def test_snapshot_never_shares_mutable_execution_index_and_can_reseed():
    fast = engine()
    for i in range(20):
        a, _ = apply(fast, component(i))
    snapshot = deepcopy(a)
    assert snapshot._component_accumulator is None
    assert snapshot.source_snapshots is not a.source_snapshots
    before = snapshot.to_dict()
    apply(fast, component(20))
    assert snapshot.to_dict() == before
    restored = engine()
    key = next(iter(fast._active))
    restored._active[key] = snapshot
    result, _ = apply(restored, component(20))
    equal(result, a)
    assert result._component_accumulator.rebuilt_components == 21


def test_source_revision_rejection_preserves_index():
    fast = engine()
    row = component(0, extra={'source_ref': {'revision': 3}})
    state, _ = apply(fast, row)
    before = state._component_accumulator.result
    _, change = apply(fast, replace(row, sequence=9, volume=999,
                                   extra={'source_ref': {'revision': 2}}))
    assert change == BarStateChange.NO_CHANGE
    assert state._component_accumulator.result is before


@pytest.mark.parametrize('mode', [MergeMode.SNAPSHOT, MergeMode.PRICE_ONLY, MergeMode.INCREMENTAL])
def test_non_component_modes_keep_existing_executor(mode):
    fast, slow = engine(), engine(incremental=False)
    for i in range(5):
        row = component(i, merge_mode=mode)
        a, ac = apply(fast, row)
        b, bc = apply(slow, row)
        assert ac == bc
        equal(a, b)
        assert a._component_accumulator is None


def test_metadata_cap_falls_back_without_truncating_source_or_changing_results(monkeypatch):
    monkeypatch.setattr(module, 'MAX_COMPONENTS', 16)
    fast, slow = engine(), engine(incremental=False)
    for i in range(30):
        a, _ = apply(fast, component(i))
        b, _ = apply(slow, component(i))
        equal(a, b)
    assert a._component_accumulator is None and len(a.source_snapshots) == 30


def test_equal_time_sources_and_late_first_component_keep_order_and_bad_coverage():
    fast, slow = engine(), engine(incremental=False)
    rows = [component(2), component(1), component(0),
            replace(component(2), source_interval='2m', sequence=4),
            replace(component(2), source_interval='2m', sequence=5, volume=1)]
    for row in rows:
        a, _ = apply(fast, row)
        b, _ = apply(slow, row)
        equal(a, b)
    assert not has_complete_closed_component_coverage(a)


def test_closed_bucket_correction_preserves_amendment_lifecycle():
    fast, slow = engine(7), engine(7, incremental=False)
    for i in range(7):
        a, _ = apply(fast, component(i))
        b, _ = apply(slow, component(i))
    for executor in (fast, slow):
        key, state = executor._active.popitem()
        executor._closed[key] = state
    row = component(2, sequence=2, volume=.5, source=BarInputSource.CORRECTION)
    a, ac = apply(fast, row)
    b, bc = apply(slow, row)
    assert ac == bc == BarStateChange.AMENDED
    equal(a, b)


def test_owner_memory_reports_new_index_and_clear_releases_it():
    aggregator = BarAggregator()
    aggregator.add_target('BTCUSDT', '97m')
    owner = aggregator.get_pipeline('97m').bar_state
    for i in range(31):
        state, _ = apply(owner, component(i))
    usage = aggregator.memory_usage()
    assert usage['component_index_bytes'] > 0
    assert owner.snapshot()['component_execution']['appends'] == 30
    # Immutable summary weakref isn't supported, so inspect actual owner roots
    # after clear; no global registry retains the accumulator.
    owner.clear()
    del state
    gc.collect()
    assert aggregator.memory_usage()['component_index_bytes'] == 0
    assert owner.snapshot()['component_execution']['indexed_states'] == 0


def test_calendar_targets_keep_reference_path():
    executor = BarStateEngine(BarAggregatorConfig(), TimeBucketEngine(31 * 86400000), '1M')
    state, _ = apply(executor, component(0))
    assert state._component_accumulator is None


def test_missing_raw_enhancements_publish_unknown_without_rounding_none():
    for incremental in (False, True):
        executor = engine(1, incremental=incremental)
        row = component(0, quote_volume=None, trades=None, taker_buy_base=None, taker_buy_quote=None)
        state, _ = apply(executor, row)
        assert has_complete_closed_component_coverage(state)
        assert state.enhanced_fields == frozenset()
        assert all(state.to_storage_dict()[name] is None for name in module.ENHANCED)


def test_public_pipeline_keeps_close_amend_order_and_published_snapshot_isolation():
    async def run(incremental):
        aggregator = BarAggregator(BarAggregatorConfig(incremental_components=incremental, update_throttle_ms=0))
        aggregator.add_target('BTCUSDT', '7m')
        events = []
        async def record(event):
            assert event.bar._component_accumulator is None
            events.append(event)
        aggregator.publisher.on_bar_event(record)
        rows = [dict(open_time=i * MINUTE, close_time=(i + 1) * MINUTE - 1,
                     open=100, high=110 + i, low=90, close=101, volume=10,
                     quote_volume=1000, trades=10, sequence=100, is_closed=True) for i in range(7)]
        await aggregator.on_backfill_bars('BTCUSDT', '1m', rows)
        await aggregator.on_backfill_bars('BTCUSDT', '1m', [dict(rows[2], volume=1, high=105, sequence=200)])
        assert events[-1].event_type == BarEventType.AMENDED
        assert events[-1].bar.volume == 61
        assert next(e for e in events if e.event_type == BarEventType.CLOSED).bar.volume == 70
        trace = [(e.event_type.value, e.bar.to_storage_dict(), e.bar.finality) for e in events]
        await aggregator.stop()
        return trace
    fast, slow = asyncio.run(run(True)), asyncio.run(run(False))
    assert fast == slow
