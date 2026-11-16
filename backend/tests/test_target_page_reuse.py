"""D458 bounded query work; real SQLite and existing query/materialization owners."""
import pytest

from app.data_engine.data_manager.models import BarData, SeriesKey
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_history_reader import row, MINUTE


def setup_page(query, monkeypatch, period, count, preview):
    width = period*MINUTE
    query.storage.upsert_bars('BTCUSDT', f'{period}m',
        [row(n*width, width) for n in range(count)],
        market_type='futures', source='backfill_aggregated')
    monkeypatch.setattr('time.time', lambda: (count*width+MINUTE)/1000)
    query._cache.revision_consumer.sync(force=True)
    if preview:
        key = SeriesKey('BTCUSDT', f'{period}m', exchange='binance', market_type='futures')
        query._cache.bulk_load(key, [BarData(time=count*width//1000,
            open=100, high=102, low=99, close=101, volume=1, source='ws', is_closed=False)])
    return width


def test_small_latest_page_reuses_closed_tail_and_existing_preview(mixed_query, monkeypatch):
    setup_page(mixed_query, monkeypatch, 89, 4, True)
    monkeypatch.setattr(mixed_query.custom_intervals, 'query_from_base',
                        lambda **kw: pytest.fail('reacquired closed inputs for a small latest page'))
    result = mixed_query.query_latest('BTCUSDT', '89m', limit=2, market_type='futures', auto_backfill=False)
    assert result.complete and len(result.bars) == 2
    assert result.metadata['canonical_target_snapshot']
    assert result.metadata['storage_reads'] == 1 and result.metadata['storage_rows'] == 1
    assert result.bars[0].trusted_final and not result.bars[-1].is_closed


def test_missing_current_preview_keeps_closed_prefix_without_reacquiring_it(mixed_query, monkeypatch):
    width = setup_page(mixed_query, monkeypatch, 89, 128, False)
    original = mixed_query.custom_intervals.query_from_base
    def current_only(**options):
        assert options['start_ms'] == options['end_ms'] == 128*width
        assert options['limit'] == 1 and not options['auto_backfill']
        return original(**options)
    monkeypatch.setattr(mixed_query.custom_intervals, 'query_from_base', current_only)
    result = mixed_query.query_latest('BTCUSDT', '89m', limit=128, market_type='futures', auto_backfill=False)
    assert not result.complete and result.retryable and len(result.bars) == 127
    assert result.metadata['canonical_target_snapshot']
    assert result.metadata['canonical_target_preview_pending']
    assert result.metadata['target_storage_reads'] == 1 and result.metadata['storage_rows'] == 127
    assert not result.missing_ranges and not result.backfill_triggered


def test_missing_local_inputs_cap_probe_work_without_losing_discrete_holes(mixed_query, monkeypatch):
    period, count = 89, 128
    width = period*MINUTE
    mixed_query.storage.upsert_bars('BTCUSDT', '89m',
        [row(n*width, width) for n in range(0,count,2)],
        market_type='futures', source='backfill_aggregated')
    calls = []
    original = mixed_query.storage.count_final_bars
    def probe(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(mixed_query.storage, 'count_final_bars', probe)
    result = mixed_query.query('BTCUSDT', '89m', start_ms=0, end_ms=count*width-1,
                              limit=count, market_type='futures', auto_backfill=False)
    assert len(calls) <= 8
    assert not result.complete and len(result.bars) == 64
    assert {gap.start_ms for gap in result.missing_ranges} == {n*width for n in range(1,count,2)}


@pytest.mark.parametrize('period', [89, 97, 101, 10007])
@pytest.mark.parametrize('limit', [2, 128])
def test_missing_preview_recovers_on_existing_live_frame_without_closed_source_reads(mixed_query, monkeypatch, period, limit):
    query = mixed_query
    width = setup_page(query, monkeypatch, period, 128, False)
    original = query.custom_intervals.query_from_base
    def current_only(**options):
        assert options['start_ms'] == options['end_ms'] == 128*width
        assert options['limit'] == 1 and not options['auto_backfill']
        return original(**options)
    monkeypatch.setattr(query.custom_intervals, 'query_from_base', current_only)
    submitted = []
    monkeypatch.setattr(query, '_backfill_trigger', lambda *a: submitted.append(a))
    head = query.storage.revision_store.head()
    pending = query.query_latest('BTCUSDT', f'{period}m', limit=limit,
                                market_type='futures', auto_backfill=True)
    assert pending.retryable and not pending.complete and len(pending.bars) == limit-1
    assert pending.metadata['canonical_target_preview_pending']
    key = SeriesKey('BTCUSDT', f'{period}m', exchange='binance', market_type='futures')
    forming = BarData(time=128*width//1000, open=100, high=103, low=99,
                      close=102, volume=2, is_closed=False, source='ws')
    query._cache.bulk_load(key, [forming])
    result = query.query_latest('BTCUSDT', f'{period}m', limit=limit,
                               market_type='futures', auto_backfill=True)
    assert result.complete and not result.retryable and result.bars[-1] == forming
    assert len(result.bars) == limit and not result.metadata['all_rows_final']
    assert result.metadata['storage_rows'] == limit-1 and result.metadata['storage_reads'] == 1
    assert not submitted and query.storage.revision_store.head() == head


def local_page(query):
    width = 89*MINUTE
    query.storage.upsert_bars('BTCUSDT', '1m', [row(n*MINUTE, MINUTE) for n in range(89)],
                            market_type='futures', source='backfill')
    query.storage.upsert_bars('BTCUSDT', '89m', [row(n*width,width) for n in range(1,128)],
                            market_type='futures', source='backfill_aggregated')
    return width


@pytest.mark.parametrize('aba', [False, True])
def test_local_repair_cannot_write_through_a_rebound_storage_owner(mixed_query, monkeypatch, aba):
    query = mixed_query
    width = local_page(query)
    original = query.storage
    writes = []
    class Rebound:
        def __getattr__(self, name):
            return getattr(original, name)
        def upsert_bars(self, *args, **kwargs):
            writes.append(args)
            return original.upsert_bars(*args, **kwargs)
    writer = query.custom_intervals._target_writer
    def change(*args, **kwargs):
        query.set_storage(Rebound())
        if aba:
            query.set_storage(original)
        return writer(*args, **kwargs)
    monkeypatch.setattr(query.custom_intervals, '_target_writer', change)
    result = query.query('BTCUSDT', '89m', start_ms=0, end_ms=128*width-1,
                         limit=128, market_type='futures', auto_backfill=False)
    assert not result.complete and result.retryable and not result.bars
    assert not writes and original.count_bars('BTCUSDT', '89m', 0, 0, market_type='futures') == 0
    assert query._local_closed_repair_lock.acquire(blocking=False)
    query._local_closed_repair_lock.release()


def test_failed_post_repair_proof_does_not_spend_a_second_source_budget(mixed_query, monkeypatch):
    query = mixed_query
    width = local_page(query)
    reader = query.storage.read_closed_target_snapshot
    reads = []
    def unproven(*args):
        value = reader(*args)
        reads.append(True)
        return (value[0], None) if len(reads) == 2 else value
    monkeypatch.setattr(query.storage, 'read_closed_target_snapshot', unproven)
    reducer = query.custom_intervals.query_from_base
    calls = []
    def once(**options):
        calls.append(options)
        assert len(calls) == 1, 'second acquisition after local source budget'
        return reducer(**options)
    monkeypatch.setattr(query.custom_intervals, 'query_from_base', once)
    result = query.query('BTCUSDT', '89m', start_ms=0, end_ms=128*width-1,
                         limit=128, market_type='futures', auto_backfill=False)
    assert not result.complete and result.retryable and not result.bars
    assert len(calls) == 1 and len(reads) == 2


def test_local_cancel_releases_repair_lock_and_writer_binding(mixed_query, monkeypatch):
    import asyncio
    from app.data_engine.data_manager.query import _local_closed_write
    query = mixed_query
    width = local_page(query)
    def cancel(**options):
        raise asyncio.CancelledError()
    monkeypatch.setattr(query.custom_intervals, 'query_from_base', cancel)
    with pytest.raises(asyncio.CancelledError):
        query.query('BTCUSDT', '89m', start_ms=0, end_ms=128*width-1,
                    limit=128, market_type='futures', auto_backfill=False)
    assert _local_closed_write.get() is None
    assert query._local_closed_repair_lock.acquire(blocking=False)
    query._local_closed_repair_lock.release()


@pytest.mark.parametrize('period', [89, 97, 101])
def test_missing_preview_reduces_only_available_current_inputs_and_never_persists_forming(mixed_query, monkeypatch, period):
    query = mixed_query
    width = setup_page(query, monkeypatch, period, 128, False)
    current_open = 128*width
    monkeypatch.setattr('time.time', lambda: (current_open+2*MINUTE+1000)/1000)
    query.storage.upsert_bars('BTCUSDT', '1m',
        [row(current_open+i*MINUTE,MINUTE) for i in range(2)],
        market_type='futures', source='backfill')
    head = query.storage.revision_store.head()
    result = query.query_latest('BTCUSDT', f'{period}m', limit=128,
                               market_type='futures', auto_backfill=False)
    assert result.complete and len(result.bars) == 128
    assert not result.bars[-1].is_closed and result.bars[-1].time_ms == current_open
    assert (result.bars[-1].open,result.bars[-1].high,result.bars[-1].low,result.bars[-1].close) == (100,102,99,101)
    assert result.bars[-1].volume == 2
    # Unproven forming enhanced fields stay absent, never synthesized as zero.
    assert all(getattr(result.bars[-1], field) is None for field in
               ['quote_volume','trades','taker_buy_base','taker_buy_quote'])
    assert not result.metadata['all_rows_final']
    assert result.metadata['canonical_local_repair_source_budget'] == 4*period <= 2048
    assert result.metadata['canonical_local_repair_reports'][0]['source_start_ms'] == current_open
    assert result.metadata['storage_rows'] == 129
    assert query.storage.revision_store.head() == head
    assert query.storage.count_bars('BTCUSDT',f'{period}m',current_open,current_open,market_type='futures') == 0
