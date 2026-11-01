"""Real SQLite pre-fetch/write interleavings for bounded native REST repairs."""
import asyncio
from types import SimpleNamespace

import pytest

from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage import klines_repo
from app.data_engine.storage.native_history_fence import capture_native_history_views
from app.data_engine.storage.revisions import acquisition_scope, StaleAcquisition, prepare_native_history_views


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', tmp_path / 'bars.sqlite')
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def row(t, close=10):
    return dict(open_time=t, close_time=t+999, open=10, high=20, low=1,
                close=close, volume=1, quote_volume=10, trades=1,
                taker_buy_base=0, taker_buy_quote=0)


def write(t, close=10, **kwargs):
    return klines_repo.upsert_klines('BTCUSDT', kwargs.pop('interval', '1s'), [row(t, close)],
                                    source=kwargs.pop('source', 'backfill'), **kwargs)


def task(**kwargs):
    return SimpleNamespace(**dict(dict(symbol='BTCUSDT', interval='1s', exchange='binance',
                                      market_type='spot', start_ms=90000, end_ms=99000), **kwargs))


def capture(store, **kwargs):
    scope = store.revision_store.acquisition()
    capture_native_history_views(store.revision_store, scope, [task(**kwargs)])
    return scope


@pytest.mark.parametrize('exchange', ['binance', 'gate', 'upbit'])
def test_disjoint_live_appends_do_not_starve_old_native_window(store, exchange):
    write(100000, exchange=exchange)
    scope = capture(store, exchange=exchange)
    for i in range(5):
        write(101000+i*1000, exchange=exchange)
        with acquisition_scope(scope):
            assert write(90000+i*1000, exchange=exchange) == 1
    assert len(store.query_bars('BTCUSDT', '1s', exchange=exchange)) == 11


@pytest.mark.parametrize('change', ['insert', 'correct', 'delete', 'empty-delete'])
def test_window_mutations_and_deletions_still_reject_old_network_work(store, change):
    if change in {'correct', 'delete'}:
        write(91000)
    scope = capture(store)
    if change in {'delete', 'empty-delete'}:
        store.delete_bars('BTCUSDT', '1s', 91000, 91000)
    else:
        write(91000, 19)
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        write(90000)
    assert not any(r['open_time'] == 90000 for r in store.query_bars('BTCUSDT', '1s'))


def test_external_sql_correction_is_seen_without_repository_hooks(store):
    write(91000)
    scope = capture(store)
    with klines_repo._connect() as conn:
        conn.execute('UPDATE klines SET volume=99')
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        write(90000)


def test_uncommitted_correction_rollback_does_not_invalidate_view(store):
    write(91000)
    scope = capture(store)
    with klines_repo._connect() as conn:
        conn.execute('UPDATE klines SET volume=99')
        conn.rollback()
    with acquisition_scope(scope):
        assert write(90000) == 1


def test_disjoint_other_interval_amendment_does_not_grant_derived_permission(store):
    write(100000)
    scope = capture(store)
    write(90000, interval='1m')
    with acquisition_scope(scope):
        assert write(90000) == 1
        with pytest.raises(StaleAcquisition):
            write(90000, interval='7s', source='backfill_aggregated')


@pytest.mark.parametrize('kwargs', [dict(source='backfill_aggregated'), dict(source='trade_history_verified'),
                                   dict(interval='7s'), dict(market_type='futures'),
                                   dict(series_identity=KlineSeriesIdentity.for_exchange('binance', provider_id='foreign'))])
def test_range_permission_cannot_escape_native_rest_identity_or_provenance(store, kwargs):
    scope = capture(store)
    # Mutate the exact destination family to ensure fallback strict fencing
    # is exercised even for a nondefault identity/market.
    write(100000, **kwargs)
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        write(90000, **kwargs)


def test_write_outside_granted_window_remains_strict(store):
    scope = capture(store)
    write(101000)
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        write(89000)


@pytest.mark.parametrize('kwargs', [dict(exchange='kraken'), dict(interval='7s'),
                                   dict(market_type='futures'), dict(end_ms=90000+8192*1000)])
def test_unknown_derived_or_unbounded_requests_do_not_receive_views(store, kwargs):
    assert capture(store, **kwargs).native_history_views == []


def test_old_persistent_permission_is_not_renewed_by_prefetch_snapshot(store):
    old = store.revision_store.head()
    store.delete_bars('BTCUSDT', '1s', 90000, 99000)
    scope = store.revision_store.acquisition(revision=old)
    with pytest.raises(StaleAcquisition):
        capture_native_history_views(store.revision_store, scope, [task()])
    assert scope.native_history_views == []


def test_capture_before_network_propagates_through_storage_executor(store):
    async def run():
        with acquisition_scope(store.revision_store.acquisition()) as scope:
            await prepare_native_history_views(store, [task()])
            assert len(scope.native_history_views) == 1
            # Another live acquisition, independent of the historical scope.
            with acquisition_scope(None):
                write(101000)
            assert write(90000) == 1
    asyncio.run(run())


def test_failed_commit_does_not_advance_range_permission(store, monkeypatch):
    scope = capture(store)
    old = scope.native_history_views[0].digest
    from app.data_engine.storage.revisions import guarded_write, series_values
    with acquisition_scope(scope), klines_repo._connect() as conn:
        with pytest.raises(RuntimeError):
            with guarded_write(conn, series_values('BTCUSDT','1s','binance','spot'),
                               native_rows=[row(90000)], source='backfill'):
                raise RuntimeError('writer aborted')
        conn.rollback()
    assert scope.native_history_views[0].digest == old


def test_real_engine_captures_window_before_transport_and_commits_history(store):
    from app.data_engine.backfill import BackfillEngine, BackfillConfig
    from app.data_engine.backfill.models import GapInfo, GapType
    from tests.test_binance_backfill_fetcher import _FakeBinanceTransport, _make_binance_rows

    class Detector:
        async def detect(self, **kwargs):
            return [GapInfo(symbol='BTCUSDT', interval='1s', gap_type=GapType.INTERIOR,
                            start_ms=90000, end_ms=99000, missing_bars=10,
                            exchange='binance', market_type='spot')]

    class Transport(_FakeBinanceTransport):
        async def http_fetch(self, request):
            with acquisition_scope(None):
                write(101000)
            return await super().http_fetch(request)

    async def run():
        engine = BackfillEngine(BackfillConfig(fetch_rate_limit_delay=0),
                                storage=klines_repo.AsyncKlinesRepoAdapter(),
                                transport=Transport(_make_binance_rows(100, 1000)))
        engine._detector = Detector()
        report = await engine.run('BTCUSDT', ['1s'], 90000, 99000)
        assert not report.errors, report.errors
        assert len([r for r in store.query_bars('BTCUSDT','1s') if 90000 <= r['open_time'] <= 99000]) == 10
        await engine.close()
    asyncio.run(run())


def test_prefetched_upbit_absence_survives_disjoint_live_append_and_own_span_merge(store):
    from app.data_engine.storage import native_empty_seconds
    write(101000,exchange='upbit')
    scope=capture(store,exchange='upbit')
    write(102000,exchange='upbit')
    with acquisition_scope(scope):
        native_empty_seconds.record('BTCUSDT',[(90000,92000)])
        native_empty_seconds.record('BTCUSDT',[(93000,94000)])
        assert write(95000,exchange='upbit')==1
    assert native_empty_seconds.read('BTCUSDT',90000,99000)==[(90000,94000)]


@pytest.mark.parametrize('mutation',['delete','correct','outside'])
def test_negative_evidence_retains_deletion_correction_and_window_fences(store,mutation):
    from app.data_engine.storage import native_empty_seconds
    scope=capture(store,exchange='upbit')
    if mutation=='delete':
        store.delete_bars('BTCUSDT','1s',90000,99000,exchange='upbit')
    elif mutation=='correct':
        write(91000,exchange='upbit')
    else:
        write(102000,exchange='upbit')
    with acquisition_scope(scope),pytest.raises(StaleAcquisition):
        native_empty_seconds.record('BTCUSDT',[(89000,89000)] if mutation=='outside' else [(90000,92000)])
    assert native_empty_seconds.read('BTCUSDT',89000,99000)==[]


def test_external_delete_after_own_empty_merge_still_cannot_be_resurrected(store):
    from app.data_engine.storage import native_empty_seconds
    scope=capture(store,exchange='upbit')
    with acquisition_scope(scope):native_empty_seconds.record('BTCUSDT',[(90000,92000)])
    store.delete_bars('BTCUSDT','1s',90000,99000,exchange='upbit')
    with acquisition_scope(scope),pytest.raises(StaleAcquisition):
        native_empty_seconds.record('BTCUSDT',[(90000,93000)])
    assert native_empty_seconds.read('BTCUSDT',90000,99000)==[]
