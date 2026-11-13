"""Source-backed OKX repairs must progress alongside disjoint live writes."""
import asyncio

import ccxt.async_support as ccxt
import pytest

from app.data_engine.backfill import BackfillConfig, BackfillEngine
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillTask
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType
from app.data_engine.storage import klines_repo, kline_sources
from app.data_engine.storage.native_history_fence import capture_native_history_views
from app.data_engine.storage.revisions import acquisition_scope, StaleAcquisition, prepare_warmup_view
from app.data_engine.series_identity import KlineSeriesIdentity
from app.exchanges.ccxt_ext.fork_kline import normalize_fork_kline, prepare_source_messages
from tests.test_ccxt_source_extensions import SPOT


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', tmp_path / 'bars.sqlite')
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def descriptor(interval='1m'):
    return StreamDescriptor('BTC-USDT', StreamType.KLINE, interval=interval,
                            exchange='okx', market_type='spot')


def task(interval='1m', start=600000, end=600000, **kwargs):
    return BackfillTask(symbol='BTC-USDT', interval=interval, exchange='okx',
                        market_type='spot', start_ms=start, end_ms=end, **kwargs)


async def fetched(opened=600000, interval='1m', *, close='102', ws=False, closed=True):
    exchange = ccxt.okx()
    exchange.set_markets([SPOT])
    row = [str(opened), '100', '103', '99', close, '100', '1', '101', '1' if closed else '0']
    payload = (exchange.parse_candlescope_ws_klines(
        {'arg': {'channel': 'candle'+interval, 'instId': 'BTC-USDT'}, 'data': [row]})[0]
        if ws else exchange.parse_candlescope_kline(row, SPOT, interval))
    message = RawMessage(payload, DataSource.WEBSOCKET if ws else DataSource.HTTP_BACKFILL,
                         StreamType.KLINE, opened + 3600000)
    desc = descriptor(interval)
    await prepare_source_messages([message], desc, watermark=kline_sources.rest_watermark(),
                                  history_projection=not ws)
    return message, HistoricalFetcher._event_to_bar(normalize_fork_kline(message, desc),
                                                   task(interval, opened, opened))


def write(bar, source='backfill', **kwargs):
    return klines_repo.upsert_klines('BTC-USDT', bar.interval, [bar.to_storage_dict()],
                                    exchange='okx', source=source, **kwargs)


def capture(store, **kwargs):
    scope = store.revision_store.acquisition()
    capture_native_history_views(store.revision_store, scope, [task(**kwargs)])
    return scope


@pytest.mark.parametrize('interval', ['1m', '5m'])
def test_actual_backfill_engine_projects_selected_history_during_live_tail(store, interval):
    class Transport:
        async def http_fetch(self, request):
            message, _ = await fetched(interval=interval)
            with acquisition_scope(None):
                _, live = await fetched(3600000, interval, ws=True)
                assert write(live, 'data_manager_exchange_closed') == 1
            return [message]

    async def run():
        engine = BackfillEngine(BackfillConfig(fetch_rate_limit_delay=0),
                                storage=klines_repo.AsyncKlinesRepoAdapter(), transport=Transport())
        try:
            report = await engine.run('BTC-USDT', [interval], 600000, 600000,
                                      exchange='okx', market_type='spot')
            assert not report.errors, report.errors
            assert report.reconcile_result.bars_written == 1
            assert [r['open_time'] for r in store.query_bars('BTC-USDT', interval, exchange='okx')] == [600000, 3600000]
            head = kline_sources.latest(descriptor(interval), 600000)
            assert head['delivered_revision'] == head['revision']
        finally:
            await engine.close()
    asyncio.run(run())


@pytest.mark.parametrize('change', ['insert', 'correct', 'delete', 'empty-delete', 'external-sql'])
def test_changed_native_window_and_deletions_keep_their_fence(store, change):
    async def run():
        _, bar = await fetched()
        if change in {'correct', 'delete', 'external-sql'}:
            write(bar)
        scope = capture(store)
        if change in {'delete', 'empty-delete'}:
            store.delete_bars('BTC-USDT', '1m', 600000, 600000, exchange='okx')
        elif change == 'external-sql':
            with klines_repo._connect() as conn:
                conn.execute('UPDATE klines SET volume=99')
        else:
            # A canonical mutation after capture, even with the same source
            # proof, must invalidate this acquisition's optimistic window.
            write(bar)
            if change == 'correct':
                with klines_repo._connect() as conn:
                    conn.execute('UPDATE klines SET volume=99')
        with acquisition_scope(scope), pytest.raises(StaleAcquisition):
            write(bar)
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['missing', 'forged-marker', 'ws', 'forming', 'stale', 'numeric-mismatch'])
def test_only_exact_current_closed_rest_receipts_receive_range_permission(store, kind):
    async def run():
        scope = capture(store)
        message, bar = await fetched(ws=kind == 'ws', closed=kind != 'forming')
        if kind == 'forming':
            # The normal fetcher rejects forming bars before reconciliation;
            # exercise the storage boundary with that source's real values.
            event = normalize_fork_kline(message, descriptor())
            row = {key: event.data[key] for key in kline_sources._VALUES}
            row['source_refs'] = [event.data['source_ref']]
        else:
            row = bar.to_storage_dict()
        if kind in {'missing', 'forged-marker'}:
            row.pop('source_refs')
        if kind == 'forged-marker':
            row['_history_source_ref'] = {'series': 'forged', 'open_time': 600000, 'revision': 1}
        elif kind == 'stale':
            await fetched(close='101')
        elif kind == 'numeric-mismatch':
            row['volume'] += 1
        _, live = await fetched(3600000, ws=True)
        assert write(live, 'data_manager_exchange_closed') == 1
        with acquisition_scope(scope), pytest.raises(StaleAcquisition):
            klines_repo.upsert_klines('BTC-USDT', '1m', [row], exchange='okx', source='backfill')
        assert [r['open_time'] for r in store.query_bars('BTC-USDT', '1m', exchange='okx')] == [3600000]
        assert kline_sources.latest(descriptor(), 600000)['delivered_revision'] == 0
    asyncio.run(run())


def test_unreceipted_legacy_writer_remains_supported_without_concurrent_change(store):
    async def run():
        scope = capture(store)
        _, bar = await fetched()
        row = bar.to_storage_dict()
        row.pop('source_refs')
        with acquisition_scope(scope):
            assert klines_repo.upsert_klines('BTC-USDT', '1m', [row], exchange='okx', source='backfill') == 1
        assert kline_sources.latest(descriptor(), 600000)['delivered_revision'] == 0
    asyncio.run(run())


def test_forged_history_marker_is_removed_by_projection_validation(store):
    async def run():
        _, bar = await fetched(ws=True)
        row = bar.to_storage_dict()
        row['_history_source_ref'] = bar.source_ref
        with klines_repo._connect() as conn:
            accepted = kline_sources.filter_projection_rows(conn, [row], exchange='okx',
                market_type='spot', symbol='BTC-USDT', interval='1m', native_identity=True)
        assert len(accepted) == 1 and '_history_source_ref' not in accepted[0]
        assert klines_repo.upsert_klines('BTC-USDT', '1m', [row], exchange='okx', source='backfill') == 1
        assert kline_sources.latest(descriptor(), 600000)['delivered_revision'] == 0
    asyncio.run(run())


def test_rollback_preserves_pending_receipt_and_range_digest_for_retry(store):
    import sqlite3

    async def run():
        scope = capture(store)
        _, bar = await fetched()
        old = scope.native_history_views[0].digest
        with klines_repo._connect() as conn:
            conn.execute("CREATE TRIGGER reject_native BEFORE INSERT ON klines BEGIN SELECT RAISE(ABORT,'injected'); END")
        with acquisition_scope(scope), pytest.raises(sqlite3.IntegrityError, match='injected'):
            write(bar)
        assert scope.native_history_views[0].digest == old
        assert kline_sources.latest(descriptor(), 600000)['delivered_revision'] == 0
        with klines_repo._connect() as conn:
            conn.execute('DROP TRIGGER reject_native')
        with acquisition_scope(scope):
            assert write(bar) == 1
        assert kline_sources.latest(descriptor(), 600000)['delivered_revision'] == 1
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['outside', 'derived', 'foreign-identity'])
def test_permission_does_not_escape_range_source_or_identity(store, kind):
    async def run():
        scope = capture(store)
        _, bar = await fetched(540000 if kind == 'outside' else 600000)
        _, live = await fetched(3600000, ws=True)
        identity = (KlineSeriesIdentity.for_exchange('okx', provider_id='foreign')
                    if kind == 'foreign-identity' else None)
        write(live, 'data_manager_exchange_closed', series_identity=identity)
        with acquisition_scope(scope), pytest.raises(StaleAcquisition):
            write(bar, 'backfill_aggregated' if kind == 'derived' else 'backfill', series_identity=identity)
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['derived', 'unaligned', 'oversized', 'foreign-identity', 'futures'])
def test_unqualified_or_unbounded_requests_keep_strict_family_fence(store, kind):
    request = task(interval='7m' if kind == 'derived' else '1m',
                   start=600001 if kind == 'unaligned' else 600000,
                   end=600000 + 60000*8192 if kind == 'oversized' else 600000)
    if kind == 'foreign-identity':
        request.metadata['series_identity'] = KlineSeriesIdentity.for_exchange('okx', provider_id='foreign').to_dict()
    if kind == 'futures':
        request.market_type = 'futures'
    scope = store.revision_store.acquisition()
    capture_native_history_views(store.revision_store, scope, [request])
    assert scope.native_history_views == []


def test_persisted_permission_cannot_be_renewed_after_delete(store):
    old = store.revision_store.head()
    store.delete_bars('BTC-USDT', '1m', 600000, 600000, exchange='okx')
    scope = store.revision_store.acquisition(revision=old)
    with pytest.raises(StaleAcquisition):
        capture_native_history_views(store.revision_store, scope, [task()])
    assert scope.native_history_views == []


@pytest.mark.parametrize('intervening', [None, 'correction', 'deletion'])
def test_range_commits_transfer_own_write_receipts_to_existing_warmup_owner(store, intervening):
    async def run():
        request = task('15m', 0, 1800000, metadata={'custom_interval': '45m'})
        scope = store.revision_store.acquisition()
        capture_native_history_views(store.revision_store, scope, [request])
        with acquisition_scope(scope):
            prepare_warmup_view([request])
            bars = [(await fetched(opened, '15m'))[1] for opened in [0, 900000, 1800000]]
            for bar in bars:
                assert write(bar) == 1
            target = dict(bars[0].to_storage_dict(), close_time=2699999, volume=300,
                          quote_volume=303, source_refs=[bar.source_ref for bar in bars])
            if intervening:
                with acquisition_scope(None):
                    if intervening == 'deletion':
                        store.delete_bars('BTC-USDT', '15m', 0, 0, exchange='okx')
                    else:
                        _, correction = await fetched(0, '15m', close='101')
                        assert write(correction) == 1
                with pytest.raises(StaleAcquisition):
                    klines_repo.upsert_klines('BTC-USDT', '45m', [target], exchange='okx', source='backfill_aggregated')
            else:
                assert klines_repo.upsert_klines('BTC-USDT', '45m', [target], exchange='okx', source='backfill_aggregated') == 1
                assert scope.warmup_view.owned
    asyncio.run(run())
