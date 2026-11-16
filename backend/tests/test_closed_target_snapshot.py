"""Complete durable targets stay readable while unrelated live inputs advance."""
import pytest
from contextvars import Context

from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_history_reader import row, MINUTE

WIDTH = 10007*MINUTE


@pytest.mark.parametrize('period', [89,97,101])
@pytest.mark.parametrize('preview', [False, True])
def test_canonical_page_rebuilds_only_local_closed_holes_before_waiting_for_scheduler(mixed_query, monkeypatch, period, preview):
    query = mixed_query
    width = period*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(2*period)],
        market_type='futures',source='backfill')
    query.storage.upsert_bars('BTCUSDT',f'{period}m',[row(n*width,width) for n in range(2,128)],
        market_type='futures',source='backfill_aggregated')
    calls = []
    original = query.custom_intervals.query_from_base
    def bounded(**options):
        calls.append((options['start_ms'],options['end_ms'],options['limit'],options['auto_backfill']))
        assert options['limit'] == 1, 'never recompute the surviving page'
        return original(**options)
    monkeypatch.setattr(query.custom_intervals,'query_from_base',bounded)
    if preview:
        from app.data_engine.data_manager.models import BarData, SeriesKey
        monkeypatch.setattr('time.time', lambda: (128*width+MINUTE)/1000)
        query._cache.revision_consumer.sync(force=True)
        key = SeriesKey('BTCUSDT',f'{period}m',exchange='binance',market_type='futures')
        forming = BarData(time=128*width//1000,open=100,high=102,low=99,close=101,
                          volume=1,is_closed=False,source='ws')
        query._cache.bulk_load(key,[forming])
    submitted = []
    monkeypatch.setattr(query,'_backfill_trigger',lambda *args: submitted.append(args))
    result = query.query('BTCUSDT',f'{period}m',start_ms=0,end_ms=128*width if preview else 128*width-1,limit=128+preview,
        market_type='futures',auto_backfill=True)
    if preview:
        # The local canonical writes invalidate the old cache incarnation.
        # Never adopt that preview. A new live frame can reuse the repaired
        # closed page without repeating either the reduction or network work.
        assert not result.complete and result.retryable and not result.bars
        query._cache.revision_consumer.sync(force=True)
        query._cache.bulk_load(key,[forming])
        result = query.query('BTCUSDT',f'{period}m',start_ms=0,end_ms=128*width,limit=129,
            market_type='futures',auto_backfill=True)
    assert result.complete and len(result.bars) == 128+preview and not result.missing_ranges and not submitted
    if preview:
        assert result.bars[-1] == forming and not result.metadata['all_rows_final']
    assert result.metadata['canonical_target_snapshot'] and result.metadata['target_materialized_written'] == (0 if preview else 2)
    assert result.metadata['canonical_local_repair_source_budget'] == (0 if preview else 8*period) <= query._cfg.max_limit
    assert calls == [(0,0,1,False),(width,width,1,False)]
    assert all((bar.volume,bar.trades) == (period,period) for bar in result.bars[:128])


def test_local_row_count_is_only_a_hint_and_never_authorizes_untrusted_inputs(mixed_query):
    from app.data_engine.storage import klines_repo
    query = mixed_query
    width = 89*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(2*89)],
        market_type='futures',source='backfill')
    query.storage.upsert_bars('BTCUSDT','89m',[row(n*width,width) for n in range(2,128)],
        market_type='futures',source='backfill_aggregated')
    with klines_repo._connect() as conn:
        conn.execute("UPDATE klines SET source='unknown' WHERE interval='1m' AND open_time=0")
    result = query.query('BTCUSDT','89m',start_ms=0,end_ms=128*width-1,limit=128,
        market_type='futures',auto_backfill=False)
    assert not result.complete and result.retryable and not result.backfill_triggered
    assert [gap.start_ms for gap in result.missing_ranges] == [0]
    assert query.storage.count_bars('BTCUSDT','89m',0,0,market_type='futures') == 0
    assert result.metadata['target_materialized_written'] == 1


def test_local_rebuild_reserves_source_padding_and_declines_an_oversized_hole(mixed_query, monkeypatch):
    query = mixed_query
    width = 3001*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(3001)],
        market_type='futures',source='backfill')
    query.storage.upsert_bars('BTCUSDT','3001m',[row(n*width,width) for n in range(1,4)],
        market_type='futures',source='backfill_aggregated')
    monkeypatch.setattr(query.custom_intervals,'query_from_base',lambda **kw: pytest.fail('exceeded local source budget'))
    result = query.query('BTCUSDT','3001m',start_ms=0,end_ms=4*width-1,limit=4,
        market_type='futures',auto_backfill=False)
    assert not result.complete and len(result.bars) == 3
    assert result.metadata['canonical_local_repair_source_budget'] == 0
    assert result.metadata['target_materialized_written'] == 0


def test_local_materialization_rechecks_a_later_canonical_amendment(mixed_query, monkeypatch):
    query = mixed_query
    width = 89*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(2*89)],
        market_type='futures',source='backfill')
    query.storage.upsert_bars('BTCUSDT','89m',[row(n*width,width) for n in range(2,128)],
        market_type='futures',source='backfill_aggregated')
    original = query.storage.read_closed_target_snapshot
    reads = []
    def changing(*args):
        snapshot = original(*args)
        reads.append(len(snapshot[0]))
        if reads == [126,128]:
            Context().run(lambda: query.storage.upsert_bars('BTCUSDT','89m',
                [{**row(10*width,width),'close':100.5}],market_type='futures',source='backfill_aggregated'))
        return snapshot
    monkeypatch.setattr(query.storage,'read_closed_target_snapshot',changing)
    result = query.query('BTCUSDT','89m',start_ms=0,end_ms=128*width-1,limit=128,
        market_type='futures',auto_backfill=False)
    assert reads == [126,128]
    assert not result.complete and result.retryable and not result.bars


def test_local_reacquisition_cannot_renew_deleted_source_permission(mixed_query, monkeypatch):
    query = mixed_query
    width = 89*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(2*89)],
        market_type='futures',source='backfill')
    query.storage.upsert_bars('BTCUSDT','89m',[row(n*width,width) for n in range(2,128)],
        market_type='futures',source='backfill_aggregated')
    original = query.storage.count_bars
    changed = []
    def count(*args, **options):
        result = original(*args, **options)
        if not changed:
            changed.append(True)
            def delete_reinsert():
                query.storage.delete_bars('BTCUSDT','1m',0,0,market_type='futures')
                query.storage.upsert_bars('BTCUSDT','1m',[row(0,MINUTE)],
                    market_type='futures',source='backfill')
            Context().run(delete_reinsert)
        return result
    monkeypatch.setattr(query.storage,'count_bars',count)
    result = query.query('BTCUSDT','89m',start_ms=0,end_ms=128*width-1,limit=128,
        market_type='futures',auto_backfill=False)
    # The unrelated surviving canonical prefix remains readable; neither
    # deleted input permission nor either missing target may be recreated.
    assert not result.complete and result.retryable and len(result.bars) == 126
    assert result.metadata['target_materialized_written'] == 0
    assert original('BTCUSDT','89m',0,width,market_type='futures') == 0


@pytest.mark.parametrize('period', [89, 97, 101])
@pytest.mark.parametrize('mode', ['range', 'before'])
@pytest.mark.parametrize('holes', [(), (60, 61)])
def test_large_source_window_reuses_canonical_targets_even_when_each_bar_is_small(mixed_query, monkeypatch, period, mode, holes):
    query = mixed_query
    width = period*MINUTE
    query.storage.upsert_bars('BTCUSDT',f'{period}m',
        [row(n*width,width) for n in range(128) if n not in holes],
        market_type='futures',source='backfill_aggregated')
    monkeypatch.setattr(query, '_query_closed_mixed', lambda *a, **kw: pytest.fail('reacquired a large persisted source window'))
    options = dict(limit=128,market_type='futures',auto_backfill=False)
    result = (query.query_before('BTCUSDT',f'{period}m',128*width,**options) if mode == 'before'
        else query.query('BTCUSDT',f'{period}m',start_ms=0,end_ms=128*width-1,**options))
    assert result.metadata['canonical_target_snapshot']
    assert result.metadata['target_storage_reads'] == 1 and result.metadata['storage_rows'] == 128-len(holes)
    assert result.metadata['storage_reads'] == 1+len(holes)
    assert [bar.time_ms for bar in result.bars] == [n*width for n in range(128) if n not in holes]
    assert result.complete is (not holes)
    assert [(gap.start_ms,gap.end_ms) for gap in result.missing_ranges] == [(n*width,n*width) for n in holes]


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


@pytest.mark.parametrize('missing', [8, 9, 32])
def test_sparse_fast_path_caps_repair_fanout_and_defers_cold_pages(mixed_query, missing):
    query = mixed_query
    query.storage.upsert_bars('BTCUSDT','10007m',
        [row(n*WIDTH,WIDTH) for n in range(32-missing)],
        market_type='futures',source='backfill_aggregated')
    result = query.query('BTCUSDT','10007m',start_ms=0,end_ms=32*WIDTH-1,limit=32,
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


@pytest.mark.parametrize('period', [89, 97, 101])
def test_sparse_withdrawn_page_advances_local_repair_with_bounded_work(mixed_query, monkeypatch, period):
    query = mixed_query
    width = period*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(128*period)],
        market_type='futures',source='backfill')
    query.storage.upsert_bars('BTCUSDT',f'{period}m',[row(n*width,width) for n in range(104,128)],
        market_type='futures',source='backfill_aggregated')
    calls = []
    original = query.custom_intervals.query_from_base
    def bounded(**options):
        assert options['limit'] == 1 and options['start_ms'] == options['end_ms']
        assert not options['auto_backfill']
        calls.append(options['start_ms'])
        return original(**options)
    monkeypatch.setattr(query.custom_intervals,'query_from_base',bounded)
    monkeypatch.setattr(query,'_query_closed_mixed',lambda *a, **k: pytest.fail('recomputed whole withdrawn page'))
    previous = 24
    for attempt in range(8):
        result = query.query('BTCUSDT',f'{period}m',start_ms=0,end_ms=128*width-1,limit=128,
            market_type='futures',auto_backfill=False)
        assert result.metadata['canonical_target_snapshot']
        assert previous < len(result.bars) <= 128
        assert result.metadata['canonical_local_repair_source_budget'] <= query._cfg.max_limit
        assert sum(r['storage_rows'] for r in result.metadata['canonical_local_repair_reports']) <= query._cfg.max_limit
        if result.complete:
            break
        assert result.retryable and result.history_state == 'pending'
        assert len(result.missing_ranges) <= 8, 'group the unrepaired frontier rather than fan out per target'
        previous = len(result.bars)
    assert result.complete and len(result.bars) == 128
    assert len(calls) == len(set(calls)) == 104
    assert all((bar.volume,bar.trades) == (period,period) for bar in result.bars)


def test_sparse_local_progress_preserves_live_preview_fence(mixed_query, monkeypatch):
    from app.data_engine.data_manager.models import BarData, SeriesKey
    query = mixed_query
    period, count = 89, 128
    width = period*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(count*period)],
        market_type='futures',source='backfill')
    query.storage.upsert_bars('BTCUSDT','89m',[row(n*width,width) for n in range(104,128)],
        market_type='futures',source='backfill_aggregated')
    monkeypatch.setattr('time.time',lambda: (128*width+MINUTE)/1000)
    key = SeriesKey('BTCUSDT','89m',exchange='binance',market_type='futures')
    for attempt in range(8):
        query._cache.revision_consumer.sync(force=True)
        forming = BarData(time=128*width//1000,open=100,high=110,low=99,close=101+attempt,
                          volume=1,is_closed=False,source='ws')
        query._cache.bulk_load(key,[forming])
        result = query.query('BTCUSDT','89m',start_ms=0,end_ms=128*width,limit=129,
            market_type='futures',auto_backfill=False)
        if result.complete:
            assert result.bars[-1] == forming
            assert len(result.bars) == 129 and not result.metadata['all_rows_final']
            break
        # Each local write changes the cache incarnation, so that read cannot
        # expose its older preview even though its closed repairs are durable.
        assert result.retryable and not result.bars
    assert result.complete


def test_sparse_repair_preserves_all_holes_but_caps_scheduler_submissions(mixed_query, monkeypatch):
    query = mixed_query
    width = 89*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(128*89)],
        market_type='futures',source='backfill')
    query.storage.upsert_bars('BTCUSDT','89m',[row(n*width,width) for n in range(0,128,2)],
        market_type='futures',source='backfill_aggregated')
    submitted = []
    monkeypatch.setattr(query,'_backfill_trigger',lambda *args: submitted.append(args))
    result = query.query('BTCUSDT','89m',start_ms=0,end_ms=128*width-1,limit=128,
        market_type='futures',auto_backfill=True)
    assert not result.complete and result.retryable
    assert result.metadata['target_materialized_written'] > 0
    assert len(submitted) == 8 < len(result.missing_ranges)
    absent = {n*width for n in range(128)} - {bar.time_ms for bar in result.bars}
    assert absent == {gap.start_ms for gap in result.missing_ranges}
    assert all(gap.start_ms == gap.end_ms and gap.missing_bars == 1 for gap in result.missing_ranges)


def test_sparse_untrusted_local_inputs_do_not_fall_through_to_second_source_budget(mixed_query, monkeypatch):
    query = mixed_query
    width = 89*MINUTE
    query.storage.upsert_bars('BTCUSDT','1m',[row(n*MINUTE,MINUTE) for n in range(128*89)],
        market_type='futures',source='unknown')
    query.storage.upsert_bars('BTCUSDT','89m',[row(n*width,width) for n in range(104,128)],
        market_type='futures',source='backfill_aggregated')
    monkeypatch.setattr(query,'_query_closed_mixed',lambda *a, **k: pytest.fail('spent a second full source budget'))
    result = query.query('BTCUSDT','89m',start_ms=0,end_ms=128*width-1,limit=128,
        market_type='futures',auto_backfill=False)
    assert not result.complete and result.retryable and len(result.bars) == 24
    assert result.metadata['target_materialized_written'] == 0
    assert result.metadata['canonical_local_repair_source_budget'] <= query._cfg.max_limit
    assert all(not item['complete'] for item in result.metadata['canonical_local_repair_reports'])
