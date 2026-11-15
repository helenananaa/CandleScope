"""Complete durable targets stay readable while unrelated live inputs advance."""
import pytest
from contextvars import Context

from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_history_reader import row, MINUTE

WIDTH = 10007*MINUTE


def seed(query, count=4):
    query.storage.upsert_bars('BTCUSDT','10007m',[row(n*WIDTH,WIDTH) for n in range(count)],
        market_type='futures',source='backfill_aggregated')


def read(query):
    return query.query('BTCUSDT','10007m',start_ms=0,end_ms=4*WIDTH-1,limit=4,
                       market_type='futures',auto_backfill=False)


@pytest.mark.parametrize('change',['tail','input','target','delete_reinsert','binding','decoded_row'])
def test_canonical_target_snapshot_is_fenced_without_recomputing_sources(mixed_query, monkeypatch, change):
    query = mixed_query
    seed(query)
    original = query.storage.read_closed_target_snapshot
    def during_read(*args):
        snapshot = original(*args)
        assert snapshot is not None
        def mutate():
            if change in ('tail','input'):
                at = 100*WIDTH if change == 'tail' else 0
                query.storage.upsert_bars('BTCUSDT','1m',[row(at,MINUTE)],
                    market_type='futures',source='backfill')
            elif change == 'target':
                query.storage.upsert_bars('BTCUSDT','10007m',[{**row(0,WIDTH),'close':100.5}],
                    market_type='futures',source='backfill_aggregated')
            elif change == 'delete_reinsert':
                query.storage.delete_bars('BTCUSDT','10007m',0,0,market_type='futures')
                query.storage.upsert_bars('BTCUSDT','10007m',[row(0,WIDTH)],
                    market_type='futures',source='backfill_aggregated')
            elif change == 'binding': query._storage = object()
            elif change == 'decoded_row': snapshot[0][0]['close'] = 100.5
        Context().run(mutate)
        return snapshot
    monkeypatch.setattr(query.storage,'read_closed_target_snapshot',during_read)
    result = read(query)
    if change == 'tail':
        assert result.complete and len(result.bars) == 4
        assert result.metadata['canonical_target_snapshot']
        assert result.metadata['storage_reads'] == 1 and result.metadata['storage_rows'] == 4
        assert not result.backfill_triggered
        assert query.storage.count_bars('BTCUSDT','1m',0,4*WIDTH-1,market_type='futures') == 0
        assert '_closed_target_read' not in result.to_dict()
    else:
        assert not result.complete and result.retryable and not result.bars


@pytest.mark.parametrize('invalid',['untrusted','malformed_close','malformed_value','forming','truncated'])
def test_canonical_fast_read_requires_closed_trusted_untruncated_rows(mixed_query, monkeypatch, invalid):
    query = mixed_query
    seed(query)
    if invalid == 'untrusted':
        from app.data_engine.storage import klines_repo
        with klines_repo._connect() as conn:
            conn.execute("UPDATE klines SET source='unknown' WHERE interval='10007m' AND open_time=?",(WIDTH,))
    elif invalid == 'malformed_close':
        from app.data_engine.storage import klines_repo
        with klines_repo._connect() as conn:
            conn.execute("UPDATE klines SET close_time=open_time WHERE interval='10007m' AND open_time=?",(WIDTH,))
    elif invalid == 'malformed_value':
        from app.data_engine.storage import klines_repo
        with klines_repo._connect() as conn:
            conn.execute("UPDATE klines SET open='bad' WHERE interval='10007m' AND open_time=?",(WIDTH,))
    elif invalid == 'forming': monkeypatch.setattr('time.time',lambda: (3*WIDTH+1)/1000)
    if invalid == 'truncated':
        result = query.query('BTCUSDT','10007m',start_ms=0,end_ms=4*WIDTH-1,limit=3,
                             market_type='futures',auto_backfill=False)
    else: result = read(query)
    assert not result.metadata.get('canonical_target_snapshot')


@pytest.mark.parametrize('mode', ['range', 'before'])
@pytest.mark.parametrize('auto_backfill', [False, True])
def test_nearly_complete_page_reads_once_and_repairs_only_missing_targets(mixed_query, monkeypatch, mode, auto_backfill):
    query = mixed_query
    holes = {118, 119}
    query.storage.upsert_bars('BTCUSDT','10007m',
        [row(n*WIDTH,WIDTH) for n in range(128) if n not in holes],
        market_type='futures',source='backfill_aggregated')
    submitted = []
    monkeypatch.setattr(query, '_backfill_trigger', lambda *args: submitted.append(args))
    monkeypatch.setattr(query, '_query_closed_mixed', lambda *a, **kw: pytest.fail('recomputed surviving targets'))
    options = dict(limit=128, market_type='futures', auto_backfill=auto_backfill)
    result = (query.query_before('BTCUSDT','10007m',128*WIDTH,**options) if mode == 'before'
        else query.query('BTCUSDT','10007m',start_ms=0,end_ms=128*WIDTH-1,**options))
    assert [bar.time_ms for bar in result.bars] == [n*WIDTH for n in range(128) if n not in holes]
    assert not result.complete and result.retryable and result.history_state == 'pending'
    assert result.metadata['canonical_target_snapshot'] and result.metadata['canonical_target_partial']
    assert not result.metadata['target_materialized'] and result.metadata['target_materialized_written'] == 0
    assert result.metadata['storage_reads'] == 1 and result.metadata['storage_rows'] == 126
    assert [(gap.start_ms,gap.end_ms,gap.missing_bars) for gap in result.missing_ranges] == [
        (118*WIDTH,118*WIDTH,1),(119*WIDTH,119*WIDTH,1)]
    expected = [('BTCUSDT','10007m',n*WIDTH,n*WIDTH,'binance','futures') for n in sorted(holes)]
    assert submitted == (expected if auto_backfill else [])
    assert result.backfill_triggered is auto_backfill
    # Filling a hole creates a new snapshot, never an old "complete" page.
    query.storage.upsert_bars('BTCUSDT','10007m',[row(n*WIDTH,WIDTH) for n in holes],
        market_type='futures',source='backfill_aggregated')
    complete = query.query('BTCUSDT','10007m',start_ms=0,end_ms=128*WIDTH-1,**options)
    assert complete.complete and len(complete.bars) == 128 and not complete.missing_ranges


@pytest.mark.parametrize('change', ['fill', 'amend', 'delete_reinsert', 'decoded_row', 'input'])
def test_partial_snapshot_rechecks_surviving_rows_and_absent_slots(mixed_query, monkeypatch, change):
    query = mixed_query
    seed(query, 3)
    original = query.storage.read_closed_target_snapshot
    def changing(*args):
        snapshot = original(*args)
        def mutate():
            if change == 'fill':
                query.storage.upsert_bars('BTCUSDT','10007m',[row(3*WIDTH,WIDTH)],
                    market_type='futures',source='backfill_aggregated')
            elif change == 'amend':
                query.storage.upsert_bars('BTCUSDT','10007m',[{**row(0,WIDTH),'close':100.5}],
                    market_type='futures',source='backfill_aggregated')
            elif change == 'delete_reinsert':
                query.storage.delete_bars('BTCUSDT','10007m',0,0,market_type='futures')
                query.storage.upsert_bars('BTCUSDT','10007m',[row(0,WIDTH)],
                    market_type='futures',source='backfill_aggregated')
            elif change == 'input':
                query.storage.upsert_bars('BTCUSDT','1m',[row(0,MINUTE)],
                    market_type='futures',source='backfill')
            else: snapshot[0][0]['close'] = 100.5
        Context().run(mutate)
        return snapshot
    monkeypatch.setattr(query.storage,'read_closed_target_snapshot',changing)
    result = read(query)
    assert not result.complete and result.retryable and not result.bars


@pytest.mark.parametrize('missing', [8, 9, 16])
def test_sparse_fast_path_caps_repair_fanout_and_defers_cold_pages(mixed_query, missing):
    query = mixed_query
    query.storage.upsert_bars('BTCUSDT','10007m',
        [row(n*WIDTH,WIDTH) for n in range(16-missing)],
        market_type='futures',source='backfill_aggregated')
    result = query.query('BTCUSDT','10007m',start_ms=0,end_ms=16*WIDTH-1,limit=16,
        market_type='futures',auto_backfill=False)
    assert bool(result.metadata.get('canonical_target_partial')) is (missing == 8)
    if missing == 8:
        assert len(result.missing_ranges) == 8 and not result.complete


def test_partial_closed_prefix_keeps_forming_preview_explicit(mixed_query, monkeypatch):
    from app.data_engine.data_manager.models import BarData, SeriesKey
    query = mixed_query
    seed(query, 3)
    monkeypatch.setattr('time.time', lambda: (4*WIDTH+MINUTE)/1000)
    query._cache.revision_consumer.sync(force=True)
    key = SeriesKey('BTCUSDT','10007m',exchange='binance',market_type='futures')
    forming = BarData(time=4*WIDTH//1000,open=100,high=102,low=99,close=101,
        volume=1,is_closed=False,source='ws')
    query._cache.bulk_load(key,[forming])
    result = query.query('BTCUSDT','10007m',start_ms=0,end_ms=4*WIDTH,limit=5,
        market_type='futures',auto_backfill=False)
    assert not result.complete and result.retryable and result.bars[-1] == forming
    assert len(result.bars) == 4 and result.metadata['canonical_target_partial']
    assert result.metadata['canonical_target_preview'] and not result.metadata['all_rows_final']
    assert [(gap.start_ms,gap.end_ms) for gap in result.missing_ranges] == [(3*WIDTH,3*WIDTH)]


@pytest.mark.parametrize('preview', [False, True])
def test_countback_and_preview_reuse_the_closed_prefix(mixed_query, monkeypatch, preview):
    from app.data_engine.data_manager.models import BarData, SeriesKey
    query = mixed_query
    seed(query)
    monkeypatch.setattr('time.time', lambda: (4*WIDTH+MINUTE)/1000)
    # Synchronize canonical mutations before installing the current preview.
    query._cache.revision_consumer.sync(force=True)
    key = SeriesKey('BTCUSDT','10007m',exchange='binance',market_type='futures')
    forming = BarData(time=4*WIDTH//1000,open=100,high=102,low=99,close=101,
                      volume=1,is_closed=False,source='ws')
    if preview:
        query._cache.bulk_load(key,[forming])
    monkeypatch.setattr(query,'_query_closed_mixed',lambda *a,**kw: pytest.fail('recomputed a complete closed prefix'))
    if preview:
        result = query.query('BTCUSDT','10007m',start_ms=0,end_ms=4*WIDTH,limit=5,
                             market_type='futures',auto_backfill=False)
        assert result.bars[-1] == forming and not result.bars[-1].is_closed
        assert result.metadata['canonical_target_preview']
        assert not result.metadata['all_rows_final']
    else:
        result = query.query_before('BTCUSDT','10007m',4*WIDTH,limit=4,
                                    market_type='futures',auto_backfill=False)
    assert result.complete and result.metadata['canonical_target_snapshot']
    assert len(result.bars) == 4+preview
    assert result.metadata['storage_rows'] == 4


def test_preview_does_not_bypass_a_closed_prefix_correction(mixed_query, monkeypatch):
    from app.data_engine.data_manager.models import BarData, SeriesKey
    query = mixed_query
    seed(query)
    monkeypatch.setattr('time.time', lambda: (4*WIDTH+MINUTE)/1000)
    query._cache.revision_consumer.sync(force=True)
    key = SeriesKey('BTCUSDT','10007m',exchange='binance',market_type='futures')
    query._cache.bulk_load(key,[BarData(time=4*WIDTH//1000,open=100,high=102,low=99,
                                      close=101,volume=1,is_closed=False,source='ws')])
    original = query.storage.read_closed_target_snapshot
    def correcting(*args):
        result = original(*args)
        Context().run(lambda: query.storage.upsert_bars('BTCUSDT','1m',[row(0,MINUTE)],
                    market_type='futures',source='backfill'))
        return result
    monkeypatch.setattr(query.storage,'read_closed_target_snapshot',correcting)
    result = query.query('BTCUSDT','10007m',start_ms=0,end_ms=4*WIDTH,limit=5,
                         market_type='futures',auto_backfill=False)
    assert not result.complete and result.retryable and not result.bars


@pytest.mark.parametrize('change', ['tick', 'cache_aba', 'forming_source', 'other_symbol'])
def test_preview_keeps_its_own_generation_fence(mixed_query, monkeypatch, change):
    from dataclasses import replace
    from app.data_engine.data_manager.models import BarData, SeriesKey
    query = mixed_query
    seed(query)
    monkeypatch.setattr('time.time', lambda: (4*WIDTH+MINUTE)/1000)
    query._cache.revision_consumer.sync(force=True)
    key = SeriesKey('BTCUSDT','10007m',exchange='binance',market_type='futures')
    forming = BarData(time=4*WIDTH//1000,open=100,high=102,low=99,
                      close=101,volume=1,is_closed=False,source='ws')
    query._cache.bulk_load(key,[forming])
    original = query.storage.read_closed_target_snapshot
    def changing(*args):
        result = original(*args)
        def mutate():
            if change == 'tick': query._cache.bulk_load(key,[replace(forming, close=102)])
            elif change == 'cache_aba':
                query._cache.invalidate(key)
                query._cache.bulk_load(key,[forming])
            else:
                symbol = 'ETHUSDT' if change == 'other_symbol' else 'BTCUSDT'
                query.storage.upsert_bars(symbol,'1m',[row(4*WIDTH,MINUTE)],
                    market_type='futures',source='backfill')
        Context().run(mutate)
        return result
    monkeypatch.setattr(query.storage,'read_closed_target_snapshot',changing)
    result = query.query('BTCUSDT','10007m',start_ms=0,end_ms=4*WIDTH,limit=5,
                         market_type='futures',auto_backfill=False)
    if change == 'other_symbol':
        assert result.complete and result.bars[-1] == forming
    else:
        assert not result.complete and result.retryable and not result.bars
