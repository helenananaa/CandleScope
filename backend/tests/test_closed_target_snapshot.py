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
        assert not result.backfill_triggered
        assert query.storage.count_bars('BTCUSDT','1m',0,4*WIDTH-1,market_type='futures') == 0
        assert '_closed_target_read' not in result.to_dict()
    else:
        assert not result.complete and result.retryable and not result.bars


@pytest.mark.parametrize('invalid',['hole','untrusted','malformed_close','malformed_value','forming','truncated'])
def test_canonical_fast_read_requires_the_whole_closed_trusted_page(mixed_query, monkeypatch, invalid):
    query = mixed_query
    seed(query, 3 if invalid == 'hole' else 4)
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
