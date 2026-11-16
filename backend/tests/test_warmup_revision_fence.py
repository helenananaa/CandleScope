"""Scoped D461 regressions using real SQLite writes and canonical reduction."""
import asyncio
from types import SimpleNamespace

import pytest

from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.models import IntervalComponent, IntervalDecomposition
from app.data_engine.backfill.reconciler import Reconciler
from app.data_engine.storage import klines_repo
from app.data_engine.storage.native_history_fence import capture_planned_write_views
from app.data_engine.storage.mixed_history_fence import capture_standard_targets
from app.data_engine.storage.revisions import acquisition_scope, prepare_warmup_view, StaleAcquisition

MINUTE = 60_000
SLOTS = 17 * 89


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', tmp_path / 'bars.sqlite')
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def row(i, close=10):
    return dict(open_time=i*MINUTE, close_time=(i+1)*MINUTE-1,
                open=10., high=20., low=1., close=float(close), volume=1.,
                quote_volume=10., trades=1, taker_buy_base=.5, taker_buy_quote=5.)


def write(rows, *, symbol='BTCUSDT', interval='1m', **kwargs):
    return klines_repo.upsert_klines(symbol, interval, rows, exchange='binance',
        market_type='futures', source=kwargs.pop('source', 'backfill'), **kwargs)


def window():
    return SimpleNamespace(symbol='BTCUSDT', interval='1m', exchange='binance',
        market_type='futures', start_ms=0, end_ms=(SLOTS-1)*MINUTE,
        archive=False, metadata={'custom_interval': '89m'})


def captured(store):
    scope = store.revision_store.acquisition()
    capture_planned_write_views(store.revision_store, scope, [window()])
    with acquisition_scope(scope):
        prepare_warmup_view([window()])
    assert scope.warmup_view is not None
    assert len(scope.native_history_views) == 1
    return scope


def test_second_native_batch_survives_own_large_commit_after_disjoint_live_tail(store):
    scope = captured(store)
    write([row(3000)])  # A newer live source, outside every acquired window.
    with acquisition_scope(scope):
        assert write([row(i) for i in range(1500)]) == 1500
        assert write([row(i) for i in range(1500, 1511)]) == 11
    assert len(store.query_bars('BTCUSDT', '1m', exchange='binance', market_type='futures')) == 1512


@pytest.mark.parametrize('batch', [1, 500])
def test_builtin_reduction_survives_disjoint_tail_and_unrelated_journal_overrun(store, batch):
    write([row(i) for i in range(SLOTS)])
    scope = store.revision_store.acquisition()
    decomp = IntervalDecomposition('89m', 89*MINUTE, [IntervalComponent('1m', 89, MINUTE)])
    plan = SimpleNamespace(decompositions=[decomp], tasks=[window()], derived_source_windows=[])
    capture_standard_targets(store.revision_store, scope, plan)
    fired = []

    class Storage(klines_repo.AsyncKlinesRepoAdapter):
        async def upsert_bars(self, symbol, interval, rows, source='backfill', **kwargs):
            if interval == '89m' and not fired:
                fired.append(True)
                with acquisition_scope(None):
                    write([row(3000)])
                    write([row(i) for i in range(1100)], symbol='ETHUSDT')
            return await super().upsert_bars(symbol, interval, rows, source, **kwargs)

    async def run():
        reducer = Reconciler(BackfillConfig(reconcile_write_batch_size=batch), Storage())
        with acquisition_scope(scope):
            return await reducer._generate_custom_bars(decomp, {}, [window()])

    generated, written, failures, _ = asyncio.run(run())
    assert fired
    assert not failures, failures
    assert generated == written == 17
    targets = store.query_bars('BTCUSDT', '89m', exchange='binance', market_type='futures')
    assert len(targets) == 17
    for target in targets:
        assert (target['open'], target['high'], target['low'], target['close']) == (10, 20, 1, 10)
        assert (target['volume'], target['quote_volume'], target['trades']) == (89, 890, 89)
        assert (target['taker_buy_base'], target['taker_buy_quote']) == (44.5, 445)


@pytest.mark.parametrize('mutation', ['correction', 'source-delete', 'source-empty-delete', 'target-empty-delete'])
def test_native_warmup_keeps_content_and_original_deletion_floor(store, mutation):
    scope = captured(store)
    with acquisition_scope(scope):
        write([row(i) for i in range(10)])
    before = list(scope.warmup_view.owned)
    if mutation == 'correction':
        write([row(0, 19)])
    else:
        interval = '89m' if mutation == 'target-empty-delete' else '1m'
        at = 20*MINUTE if mutation == 'source-empty-delete' else 0
        store.delete_bars('BTCUSDT', interval, at, at, exchange='binance', market_type='futures')
    with acquisition_scope(scope), pytest.raises(StaleAcquisition):
        write([row(10)])
    assert scope.warmup_view.owned == before
    assert not any(r['open_time'] == 10*MINUTE for r in store.query_bars(
        'BTCUSDT', '1m', exchange='binance', market_type='futures'))


def test_failed_native_transaction_does_not_advance_digest_or_own_commit_receipts(store):
    import sqlite3
    scope = captured(store)
    with acquisition_scope(scope):
        write([row(0)])
    before = (scope.native_history_views[0].digest, list(scope.warmup_view.owned))
    with klines_repo._connect() as conn:
        conn.execute("CREATE TRIGGER fail_native BEFORE INSERT ON klines WHEN NEW.open_time=60000 "
                     "BEGIN SELECT RAISE(ABORT,'injected'); END")
    with acquisition_scope(scope), pytest.raises(sqlite3.IntegrityError):
        write([row(1)])
    assert (scope.native_history_views[0].digest, scope.warmup_view.owned) == before
    with klines_repo._connect() as conn:
        conn.execute('DROP TRIGGER fail_native')
    with acquisition_scope(scope):
        assert write([row(1)]) == 1


@pytest.mark.parametrize('mutation', ['input', 'delete-restore', 'target', 'target-delete', 'owner', 'owner-aba'])
def test_consumed_input_proof_rejects_actual_changes_and_late_rebound_owner(store, mutation):
    write([row(i) for i in range(SLOTS)])
    scope = store.revision_store.acquisition()
    decomp = IntervalDecomposition('89m', 89*MINUTE, [IntervalComponent('1m', 89, MINUTE)])
    capture_standard_targets(store.revision_store, scope,
        SimpleNamespace(decompositions=[decomp], tasks=[window()], derived_source_windows=[]))
    fired = []
    reducer = None

    class Storage(klines_repo.AsyncKlinesRepoAdapter):
        async def upsert_bars(self, symbol, interval, rows, source='backfill', **kwargs):
            if interval == '89m' and not fired:
                fired.append(True)
                with acquisition_scope(None):
                    if mutation == 'input':
                        write([row(0, 19)])
                    elif mutation == 'delete-restore':
                        store.delete_bars('BTCUSDT', '1m', 0, 0, exchange='binance', market_type='futures')
                        write([row(0)])
                    elif mutation == 'target-delete':
                        store.delete_bars('BTCUSDT', '89m', 0, 0, exchange='binance', market_type='futures')
                    elif mutation == 'target':
                        write([{**row(0, 19), 'close_time': 89*MINUTE-1}],
                              interval='89m', source='backfill_aggregated')
                    elif mutation == 'owner':
                        reducer._storage = klines_repo.AsyncKlinesRepoAdapter()
                    else:
                        reducer.set_custom_aggregator(lambda *_: None)
                        reducer.set_custom_aggregator(None)
            return await super().upsert_bars(symbol, interval, rows, source, **kwargs)

    async def run():
        nonlocal reducer
        reducer = Reconciler(BackfillConfig(), Storage())
        with acquisition_scope(scope):
            return await reducer._generate_custom_bars(decomp, {}, [window()])

    _, written, failures, _ = asyncio.run(run())
    assert fired and failures and written == 0
    assert reducer.metrics.snapshot()['counters']['canonical_input_snapshots'] == 1
    targets = store.query_bars('BTCUSDT', '89m', exchange='binance', market_type='futures')
    if mutation == 'target':
        assert len(targets) == 1 and targets[0]['close'] == 19
    else:
        assert not targets
    if mutation in {'input', 'owner', 'owner-aba'}:
        assert failures[0]['fence_reason'] in {'canonical_window_changed', 'reducer_owner_changed'}


def test_consumed_inputs_match_independent_varying_ohlcv_and_duplicate_commit_is_idempotent(store):
    import math
    source = []
    for i in range(SLOTS):
        opened = 100+i/100
        volume = .5+(i % 7)/2
        source.append({**row(i), 'open': opened, 'close': opened+1,
            'high': opened+5, 'low': opened-3, 'volume': volume,
            'quote_volume': volume*(opened+1), 'trades': 1+i%11,
            'taker_buy_base': volume/4, 'taker_buy_quote': volume*(opened+1)/4})
    write(source)
    scope = store.revision_store.acquisition()
    decomp = IntervalDecomposition('89m', 89*MINUTE, [IntervalComponent('1m', 89, MINUTE)])
    capture_standard_targets(store.revision_store, scope,
        SimpleNamespace(decompositions=[decomp], tasks=[window()], derived_source_windows=[]))

    async def run():
        reducer = Reconciler(BackfillConfig(), klines_repo.AsyncKlinesRepoAdapter())
        with acquisition_scope(scope):
            first = await reducer._generate_custom_bars(decomp, {}, [window()])
            head = store.revision_store.head()
            second = await reducer._generate_custom_bars(decomp, {}, [window()])
            assert store.revision_store.head() == head
            return first, second

    first, second = asyncio.run(run())
    assert not first[2] and not second[2]
    actual = store.query_bars('BTCUSDT', '89m', exchange='binance', market_type='futures')
    assert len(actual) == 17
    for i, target in enumerate(actual):
        group = source[i*89:(i+1)*89]
        expected = dict(open=group[0]['open'], high=max(r['high'] for r in group),
            low=min(r['low'] for r in group), close=group[-1]['close'])
        expected.update({name:math.fsum(r[name] for r in group) for name in
            ['volume','quote_volume','trades','taker_buy_base','taker_buy_quote']})
        for name, value in expected.items():
            assert target[name] == pytest.approx(value, rel=1e-12, abs=1e-9)


@pytest.mark.parametrize('kind', ['sparse', 'partial', 'off-grid', 'mixed-grid', 'oversized'])
def test_consumed_input_permission_does_not_extend_to_unproven_reductions(kind):
    from app.data_engine.storage.mixed_history_fence import (
        MixedTarget, MixedComputation, computation_scope, seal_standard_inputs,
    )
    from app.data_engine.storage.revisions import series_values
    source = series_values('BTCUSDT', '1m', 'binance', 'futures')
    dependencies = (source,)
    count = 89
    rows = [{**row(i), 'interval': '1m', 'source': 'backfill'} for i in range(count)]
    if kind == 'sparse':
        rows.pop(40)
    elif kind == 'partial':
        rows = rows[:-1]
    elif kind == 'off-grid':
        rows[0]['close_time'] -= 1
    elif kind == 'mixed-grid':
        dependencies += (series_values('BTCUSDT', '1d', 'binance', 'futures'),)
    else:
        count = 89*100
        rows = [{**row(i), 'interval': '1m', 'source': 'backfill'} for i in range(count)]
    target = MixedTarget(series_values('BTCUSDT', '89m', 'binance', 'futures'),
                         dependencies, 0, (count-89)*MINUTE, 89*MINUTE, b'')
    view = MixedComputation(target, 0)
    with computation_scope((view,)):
        assert seal_standard_inputs('BTCUSDT', '89m', 'binance', 'futures', rows, lambda: None) == 0
    assert view.canonical_input is None and view.input_owner_check is None
