"""Real HTTP/SQLite/CPU interleavings, including external delete-and-restore."""
import asyncio
from types import SimpleNamespace
import pytest

from app.data_engine.backfill import BackfillEngine, BackfillConfig
from app.data_engine.backfill.models import GapInfo, GapType
from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import acquisition_scope
from tests.test_binance_backfill_fetcher import _FakeBinanceTransport, _make_binance_rows


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', tmp_path/'bars.sqlite')
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def write(t=200000, *, interval='1s', close=105, **kwargs):
    duration = 7000 if interval == '7s' else 1000
    return klines_repo.upsert_klines('BTCUSDT', interval, [dict(
        open_time=t, close_time=t+duration-1, open=100, high=110, low=90,
        close=close, volume=1.5, quote_volume=157.5, trades=10,
        taker_buy_base=.75, taker_buy_quote=78.75)],
        source='backfill_aggregated' if interval=='7s' else 'backfill', **kwargs)


def run_repair(*, stage=None, mutate=lambda: None, batch=500):
    fired = []
    def inject(where):
        if where == stage and not fired:
            fired.append(where)
            with acquisition_scope(None):
                mutate()

    class Transport(_FakeBinanceTransport):
        async def http_fetch(self, request):
            result = await super().http_fetch(request)
            inject('http')
            return result

    class Storage(klines_repo.AsyncKlinesRepoAdapter):
        async def upsert_bars(self, symbol, interval, rows, source='backfill', **kwargs):
            if interval == '7s':
                inject('commit')
            count = await super().upsert_bars(symbol, interval, rows, source, **kwargs)
            if interval == '1s':
                inject('input')
            return count

    class Detector:
        async def detect(self, **kwargs):
            return [GapInfo(symbol='BTCUSDT', interval='7s', gap_type=GapType.INTERIOR,
                            start_ms=91000, end_ms=98000, missing_bars=2,
                            exchange='binance', market_type='spot')]

    async def execute():
        engine = BackfillEngine(BackfillConfig(fetch_rate_limit_delay=0,
                                reconcile_write_batch_size=batch), storage=Storage(),
                                transport=Transport(_make_binance_rows(106,1000)))
        async def admission(*args):
            pass  # Synthetic transport never touches the host's HTTP quota.
        engine.fetcher._rate_limit_admission = admission
        engine.fetcher._rate_limit = admission
        engine._detector = Detector()
        try:
            return await engine.run('BTCUSDT',['7s'],91000,98000)
        finally:
            await engine.close()
    report = asyncio.run(execute())
    if stage is not None:
        assert fired == [stage]
    return report


@pytest.mark.parametrize('stage', ['http','input','commit'])
@pytest.mark.parametrize('batch', [1,500])
def test_disjoint_live_append_does_not_starve_dense_custom_repair(store,stage,batch):
    report = run_repair(stage=stage, mutate=write, batch=batch)
    assert report.errors == []
    bars = store.query_bars('BTCUSDT','7s')
    assert [r['open_time'] for r in bars] == [91000,98000]
    assert all(r['volume']==10.5 and r['trades']==70 and r['close']==105 for r in bars)


def test_own_native_writes_can_invalidate_and_rebuild_existing_targets(store):
    write(91000,interval='7s',close=99)
    report = run_repair(stage='input',mutate=write)
    assert report.errors == []
    assert [r['close'] for r in store.query_bars('BTCUSDT','7s')] == [105,105]


@pytest.mark.parametrize('stage',['input','commit'])
def test_input_correction_after_http_cannot_publish_stale_reduction(store,stage):
    report = run_repair(stage=stage,mutate=lambda:write(92000,close=109))
    assert report.errors
    assert store.query_bars('BTCUSDT','7s') == []
    assert next(r for r in store.query_bars('BTCUSDT','1s') if r['open_time']==92000)['close']==109


@pytest.mark.parametrize('stage',['http','input','commit'])
@pytest.mark.parametrize('interval',['1s','7s'])
def test_empty_or_physical_delete_retains_initial_permission(store,stage,interval):
    report = run_repair(stage=stage,mutate=lambda:store.delete_bars('BTCUSDT',interval,91000,104999))
    assert report.errors
    assert store.query_bars('BTCUSDT','7s') == []


@pytest.mark.parametrize('stage',['http','input','commit'])
def test_target_edit_during_network_or_compute_cannot_be_overwritten(store,stage):
    report = run_repair(stage=stage,mutate=lambda:write(91000,interval='7s',close=99))
    assert report.errors
    assert [r['close'] for r in store.query_bars('BTCUSDT','7s')] == [99]


@pytest.mark.parametrize('interval',['1s','7s'])
def test_raw_sql_delete_and_restore_same_values_is_still_a_delete(store,interval):
    if interval=='7s':
        # Keep an existing target through the no-op native upserts, so the
        # external DELETE really removes a row rather than an empty selection.
        for t in range(91000,105000,1000):
            write(t)
        write(91000,interval='7s')
    def mutate():
        with klines_repo._connect() as conn:
            rows=conn.execute('SELECT * FROM klines WHERE interval=?',(interval,)).fetchall()
            assert rows
            conn.execute('DELETE FROM klines WHERE interval=?',(interval,))
            for row in rows:
                conn.execute('INSERT INTO klines VALUES ('+','.join('?' for _ in row)+')',tuple(row))
    report=run_repair(stage='commit',mutate=mutate)
    assert report.errors
    # Never publish either calculated bucket after the intervening delete.
    assert not any(r['source']=='backfill_aggregated' and r['open_time']==98000
                   for r in store.query_bars('BTCUSDT','7s'))


def test_rolled_back_raw_sql_mutation_does_not_poison_computation(store):
    def mutate():
        with klines_repo._connect() as conn:
            conn.execute("DELETE FROM klines WHERE interval='1s'")
            conn.rollback()
    report=run_repair(stage='commit',mutate=mutate)
    assert report.errors == []
    assert len(store.query_bars('BTCUSDT','7s'))==2


@pytest.mark.parametrize('mutation',['append','correction'])
def test_other_semantic_identity_does_not_enter_dependency_view(store,mutation):
    from app.data_engine.series_identity import KlineSeriesIdentity
    identity=KlineSeriesIdentity.for_exchange('binance',provider_id='foreign')
    report=run_repair(stage='commit',mutate=lambda:write(
        200000 if mutation=='append' else 92000,close=109,series_identity=identity))
    assert report.errors == []
    assert len(store.query_bars('BTCUSDT','7s'))==2


def test_custom_source_label_without_computation_view_remains_strict(store):
    from app.data_engine.storage.revisions import StaleAcquisition
    scope=store.revision_store.acquisition()
    write()
    with acquisition_scope(scope),pytest.raises(StaleAcquisition):
        write(91000,interval='7s')


def test_shared_reducer_preserves_dependency_permission(store):
    report=run_repair(stage='commit',mutate=write)
    assert report.errors == []
    assert len(store.query_bars('BTCUSDT','7s'))==2
    assert all(r.phase=='custom' for r in report.written_ranges if r.interval=='7s')


@pytest.mark.parametrize('field',['close','volume','trades','source'])
def test_sql_correction_during_cpu_is_seen_for_every_dependency_field(store,field):
    def mutate():
        with klines_repo._connect() as conn:
            conn.execute(f"UPDATE klines SET {field}=? WHERE interval='1s' AND open_time=92000",
                         ('data_manager_closed' if field=='source' else 999,))
    report=run_repair(stage='commit',mutate=mutate)
    assert report.errors
    assert store.query_bars('BTCUSDT','7s')==[]


def plan(**changes):
    decomp=SimpleNamespace(custom_interval='7s',custom_duration_ms=7000,
                          alignment_epoch_ms=0,components=[SimpleNamespace(interval='1s')])
    task=dict(exchange='binance',market_type='spot',symbol='BTCUSDT',interval='1s',
              start_ms=91000,end_ms=104000,metadata={'custom_interval':'7s'})
    task.update(changes)
    return SimpleNamespace(decompositions=[decomp],tasks=[SimpleNamespace(**task)])


@pytest.mark.parametrize('changes',[dict(exchange='gate'),dict(exchange='upbit'),
    dict(market_type='futures'),dict(interval='1m'),dict(end_ms=9000000)])
def test_unproven_or_large_dependencies_keep_strict_fence(store,changes):
    from app.data_engine.storage.derived_history_fence import capture_targets
    scope=store.revision_store.acquisition()
    capture_targets(store.revision_store,scope,plan(**changes))
    assert scope.derived_target_views==[]


def test_old_manual_permission_cannot_be_renewed_by_target_capture(store):
    from app.data_engine.storage.derived_history_fence import capture_targets
    from app.data_engine.storage.revisions import StaleAcquisition
    old=store.revision_store.head()
    store.delete_bars('BTCUSDT','7s',91000,104000)
    klines_repo.init_klines_storage()
    scope=store.revision_store.acquisition(revision=old)
    with pytest.raises(StaleAcquisition):
        capture_targets(store.revision_store,scope,plan())
    assert scope.derived_target_views==[]
