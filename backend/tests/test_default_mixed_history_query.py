"""Default QueryEngine integration; real canonical SQLite, no mocked reducer."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.klines as api

from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import FixedHistorySource, plan_fixed_target
from app.data_engine.interval_resolution import IntervalResolver
from app.data_engine.storage import klines_repo
from tests.test_mixed_history_reader import row, FIELDS, MINUTE
from tests.test_shared_aggregation_blocks import assert_idle


@pytest.mark.parametrize('mode', ['range', 'before'])
def test_incomplete_mixed_request_keeps_committed_partial_target_history(mixed_query, mode):
    engine = mixed_query
    width, count = 89 * MINUTE, 200
    opened = [*range(50), *range(180, count)]
    rows = [row(index * width, width) for index in opened]
    engine.storage.upsert_bars('BTCUSDT', '89m', rows,
                              source='backfill_aggregated', market_type='futures')
    # The admitted target page fits; a legacy full minute window does not.
    assert count * 89 > engine._cfg.max_limit
    options = dict(exchange='binance', market_type='futures', limit=count,
                   auto_backfill=False, min_revision=engine.storage.revision_store.head())
    result = (engine.query_before('BTCUSDT', '89m', before_ms=count * width, **options)
              if mode == 'before' else engine.query('BTCUSDT', '89m',
                  start_ms=0, end_ms=count * width - 1, **options))
    stored = engine.query('BTCUSDT', '89m', start_ms=0, end_ms=count * width - 1,
                          limit=count, market_type='futures', _materialized_only=True)
    assert len(stored.bars) == len(rows)
    assert result.bars == stored.bars
    assert not result.complete and result.retryable and result.history_state == 'pending'
    assert result.metadata['mixed_partial_materialized'] and not result.metadata['target_materialized']
    assert result.metadata['target_materialized_written'] == 0
    assert all(bar.trusted_final and bar.is_closed for bar in result.bars)
    assert result.missing_ranges
    assert not any(gap.start_ms <= value.time_ms <= gap.end_ms
                   for gap in result.missing_ranges for value in result.bars)


def test_partial_target_repair_submits_only_uncovered_span(mixed_query, monkeypatch):
    engine = mixed_query
    width, count = 89 * MINUTE, 200
    rows = [row(index * width, width) for index in [*range(50), *range(180, count)]]
    engine.storage.upsert_bars('BTCUSDT', '89m', rows,
                              source='backfill_aggregated', market_type='futures')
    submitted = []
    monkeypatch.setattr(engine, '_backfill_trigger', lambda *args: submitted.append(args))
    result = engine.query('BTCUSDT', '89m', start_ms=0, end_ms=count * width - 1,
                          limit=count, market_type='futures', auto_backfill=True,
                          min_revision=engine.storage.revision_store.head())
    assert len(result.bars) == 70 and not result.complete and result.backfill_triggered
    assert submitted == [('BTCUSDT', '89m', 50 * width, 179 * width, 'binance', 'futures')]
    assert len(result.missing_ranges) == 1 and result.missing_ranges[0].missing_bars == 130
    assert result.metadata['target_materialized_written'] == 0


def test_before_keeps_sparse_older_canonical_targets_without_expanding_repair_window(mixed_query):
    engine = mixed_query
    width, count = 89 * MINUTE, 200
    rows = [row(index * width, width) for index in range(100)]
    engine.storage.upsert_bars('BTCUSDT', '89m', rows,
                              source='backfill_aggregated', market_type='futures')
    result = engine.query_before('BTCUSDT', '89m', before_ms=1000 * width, limit=count,
                                 market_type='futures', auto_backfill=False,
                                 min_revision=engine.storage.revision_store.head())
    assert [bar.time_ms for bar in result.bars] == [value['open_time'] for value in rows]
    assert not result.complete and result.retryable
    assert all(800 * width <= gap.start_ms <= gap.end_ms < 1000 * width
               for gap in result.missing_ranges)
    bounded = engine.query('BTCUSDT', '89m', start_ms=800 * width, end_ms=1000 * width - 1,
                           limit=count, market_type='futures', auto_backfill=False,
                           min_revision=engine.storage.revision_store.head())
    assert not bounded.bars and not bounded.complete


@pytest.mark.parametrize('mutation', ['target_delete', 'source_delete', 'amend'])
def test_partial_target_read_is_fenced_again_after_mixed_probe(mixed_query, monkeypatch, mutation):
    engine = mixed_query
    width, count = 89 * MINUTE, 200
    rows = [row(index * width, width) for index in range(180, count)]
    engine.storage.upsert_bars('BTCUSDT', '89m', rows,
                              source='backfill_aggregated', market_type='futures')
    original = engine.custom_intervals._mixed_query
    changed = []
    def interleaved(*args, **kwargs):
        if not changed:
            changed.append(True)
            # A concurrent producer does not inherit the reader's acquisition
            # scope, which permits its own intentional materialization writes.
            def write():
                if mutation == 'amend':
                    replacement = {**row(190 * width, width), 'close': 100.5}
                    engine.storage.upsert_bars('BTCUSDT', '89m', [replacement],
                                              source='backfill_aggregated', market_type='futures')
                else:
                    engine.storage.delete_bars('BTCUSDT', '89m' if mutation == 'target_delete' else '1m',
                                              190 * width, 190 * width, market_type='futures')
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(write).result(timeout=5)
        return original(*args, **kwargs)
    monkeypatch.setattr(engine.custom_intervals, '_mixed_query', interleaved)
    result = engine.query('BTCUSDT', '89m', start_ms=0, end_ms=count * width - 1,
                          limit=count, market_type='futures', auto_backfill=False,
                          min_revision=engine.storage.revision_store.head())
    assert changed == [True]
    affected = [bar for bar in result.bars if bar.time_ms == 190 * width]
    assert not affected or (mutation == 'amend' and affected[0].close == 100.5)
    assert not result.complete
    fresh = engine.query('BTCUSDT', '89m', start_ms=0, end_ms=count * width - 1,
                         limit=count, market_type='futures', auto_backfill=False,
                         min_revision=engine.storage.revision_store.head())
    affected = [bar for bar in fresh.bars if bar.time_ms == 190 * width]
    if mutation == 'source_delete':
        # Clearing the fine series leaves the existing target canonical
        # representation intact. Reading it must neither recreate fine
        # coverage nor rewrite an old derived value after the deletion.
        assert len(affected) == 1 and affected[0].close == 101
        assert fresh.metadata['target_materialized_written'] == 0
        assert engine.storage.count_bars('BTCUSDT', '1m', 0, count * width - 1,
                                         market_type='futures') == 0
    else:
        assert not affected or (mutation == 'amend' and affected[0].close == 100.5)
    assert not fresh.complete


def test_untrusted_partial_target_is_not_promoted_by_a_missing_mixed_source(mixed_query):
    engine = mixed_query
    width, count = 89 * MINUTE, 200
    rows = [row(index * width, width) for index in range(180, count)]
    engine.storage.upsert_bars('BTCUSDT', '89m', rows,
                              source='backfill_aggregated', market_type='futures')
    with klines_repo._connect() as conn:
        conn.execute("UPDATE klines SET source='unknown' WHERE interval='89m' AND open_time=?", (190 * width,))
        conn.commit()
    result = engine.query('BTCUSDT', '89m', start_ms=0, end_ms=count * width - 1,
                          limit=count, market_type='futures', auto_backfill=False,
                          min_revision=engine.storage.revision_store.head())
    assert len(result.bars) == len(rows) - 1, result.metadata
    assert all(bar.trusted_final and bar.time_ms != 190 * width for bar in result.bars)
    assert any(gap.start_ms <= 190 * width <= gap.end_ms for gap in result.missing_ranges)
    assert not result.complete and result.metadata['target_materialized_written'] == 0


def test_history_http_probe_exposes_partial_targets_without_repairing(tmp_path, monkeypatch):
    from app.core import config as core_config
    database = tmp_path / 'partial-history-api.sqlite'
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', database)
    monkeypatch.setattr(core_config, 'KLINES_DB_PATH', database)
    width, count = 89 * MINUTE, 200
    monkeypatch.setattr('time.time', lambda: (count * width + 1000) / 1000)
    klines_repo.init_klines_storage()
    config = DataManagerConfig()
    config.query.auto_backfill = False
    manager = DataManager(config)
    manager.set_storage(klines_repo.KlinesRepoAdapter())
    rows = [row(index * width, width) for index in [*range(50), *range(180, count)]]
    manager.query_engine.storage.upsert_bars('BTCUSDT', '89m', rows,
                                            source='backfill_aggregated', market_type='futures')
    manager.query_engine._cache.revision_consumer.sync(force=True)
    def forbidden(*args, **kwargs):
        raise AssertionError('a zero-wait viewport probe admitted new history work')
    monkeypatch.setattr(api, '_submit_verification_repairs', forbidden)
    monkeypatch.setattr(api, '_poll_backfill_storage', forbidden)
    monkeypatch.setattr(api, '_schedule_related_interval_warmup', forbidden)
    app = FastAPI()
    app.state.data_manager = manager
    app.include_router(api.router, prefix='/api/v1')
    try:
        with TestClient(app) as client:
            response = client.get('/api/v1/klines/history', params=dict(
                symbol='BTCUSDT', interval='89m', exchange='binance', market_type='futures',
                count_back=count, max_wait_ms=0))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['count'] == len(rows)
        assert not result['complete'] and result['history_state'] == 'pending'
        assert not result['verified_contiguous'] and not result['backfill_triggered']
        assert all(bar['is_closed'] and bar['volume'] == 89 for bar in result['data'])
    finally:
        asyncio.run(manager.shutdown())
    assert manager.memory_budget.snapshot()['reserved_bytes'] == 0


@pytest.fixture
def mixed_query(tmp_path, monkeypatch):
    from app.core import config as core_config
    database = tmp_path / "default-mixed.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", database)
    klines_repo.init_klines_storage()
    config = DataManagerConfig()
    config.query.auto_backfill = False
    dm = DataManager(config)
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    yield dm.query_engine
    asyncio.run(dm.shutdown())
    assert_idle(dm.shared_blocks, empty=True)
    assert dm.memory_budget.snapshot()["reserved_bytes"] == 0


def seed(engine, period=89, count=3):
    target = SeriesKey("BTCUSDT", f"{period}m", market_type="futures")
    policy, routes, _ = engine._interval_resolver.history_composition_routes(
        exchange=target.exchange, market_type=target.market_type, interval=target.interval)
    stop = period * count * MINUTE
    sources = tuple(FixedHistorySource(replace(target, interval=route.canonical_interval),
        route.spec.nominal_ms, 0, ((0, stop),), FIELDS, policy.contract_id) for route in routes)
    inserted = set()
    for opened in range(0, stop, period * MINUTE):
        plan = plan_fixed_target(target, opened, opened + period * MINUTE, sources)
        for span in plan.spans:
            for t in range(span.start_ms, span.end_ms, span.source.width_ms):
                value = (span.source.series.interval, t)
                if value not in inserted:
                    inserted.add(value)
                    engine.storage.upsert_bars(target.symbol, value[0], [row(t, span.source.width_ms)],
                        source="backfill", market_type=target.market_type)
    return target, stop, inserted


@pytest.mark.parametrize("period", [89, 97, 101, 10007])
@pytest.mark.parametrize("mode", ["range", "before"])
def test_default_queries_read_mixed_only_inputs_then_use_target_fast_path(mixed_query, period, mode):
    engine = mixed_query
    count = 1 if period == 10007 else 3
    target, stop, inserted = seed(engine, period, count)
    def query():
        options = dict(exchange=target.exchange, market_type=target.market_type, limit=count,
                       auto_backfill=False, min_revision=engine.storage.revision_store.head())
        return (engine.query_before(target.symbol, target.interval, before_ms=stop, **options)
                if mode == "before" else engine.query(target.symbol, target.interval,
                    start_ms=0, end_ms=stop - 1, **options))
    result = query()
    assert result.complete and not result.retryable
    assert result.metadata.get("mixed_history") is True
    assert len(result.bars) == count
    for bar in result.bars:
        assert bar.trusted_final and bar.is_closed
        assert (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.quote_volume,
                bar.trades, bar.taker_buy_base, bar.taker_buy_quote) == (
                    100, 102, 99, 101, period, period * 2, period, period, period * 2)
    assert result.metadata["target_materialized_written"] == count
    assert result.metadata["mixed_accepted_rows"] < period * count
    # Persisting targets never invents minute coverage.
    assert engine.storage.count_bars(target.symbol, "1m", 0, stop - 1,
        market_type=target.market_type) == sum(interval == "1m" for interval, _ in inserted)
    reads = engine.history_blocks.snapshot()["reads"]
    cached = query()
    assert cached.metadata["target_materialized"] is True
    assert engine.history_blocks.snapshot()["reads"] == reads
    assert cached.bars == result.bars


def add_fine(engine, stop, *, amended=False):
    rows = [row(t, MINUTE) for t in range(0, stop, MINUTE)]
    if amended:
        rows[0].update(high=150, low=90, volume=7, quote_volume=14, trades=7,
                       taker_buy_base=7, taker_buy_quote=14)
    engine.storage.upsert_bars("BTCUSDT", "1m", rows,
        source="data_manager_amended" if amended else "backfill", market_type="futures")


def test_fine_amendment_invalidates_target_and_cannot_hide_behind_native_coarse(mixed_query):
    engine = mixed_query
    target, stop, _ = seed(engine, count=1)
    first = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=1, market_type="futures",
                         min_revision=engine.storage.revision_store.head())
    assert first.bars[0].volume == 89
    add_fine(engine, stop, amended=True)
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=1,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    assert result.complete and not result.retryable
    assert result.bars[0].volume == 95
    assert result.bars[0].high == 150 and result.bars[0].low == 90
    assert result.metadata["mixed_fallback_reason"] == "local_single_base_preferred"
    assert result.metadata["mixed_page_reads"] == 0


def test_deleting_fine_history_cannot_restore_target_from_old_native_coarse(mixed_query):
    engine = mixed_query
    _, stop, _ = seed(engine, count=1)
    add_fine(engine, stop)
    engine.storage.delete_bars("BTCUSDT", "1m", start_ms=0, end_ms=59 * MINUTE,
                              market_type="futures")
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=1,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    assert not result.bars
    assert result.metadata.get("mixed_fallback_reason")
    assert engine.storage.count_bars("BTCUSDT", "89m", 0, stop - 1, market_type="futures") == 0


@pytest.mark.parametrize("mutation", ["fine_insert", "fine_delete", "rebind", "qualification", "rollback"])
def test_interleaved_mutation_never_publishes_or_materializes_mixed_page(mixed_query, monkeypatch, mutation):
    engine = mixed_query
    _, stop, _ = seed(engine, count=1)
    original = engine.read_mixed_history_blocks
    @contextmanager
    def changed(*args, **kwargs):
        with original(*args, **kwargs) as read:
            yield read
        if mutation == "fine_insert":
            add_fine(engine, stop, amended=True)
        elif mutation == "fine_delete":
            engine.storage.delete_bars("BTCUSDT", "1m", start_ms=0, end_ms=MINUTE,
                                      market_type="futures")
        elif mutation == "rebind":
            engine.set_storage(klines_repo.KlinesRepoAdapter())
        elif mutation == "qualification":
            monkeypatch.setattr(engine, "_interval_resolver", IntervalResolver())
        else:
            engine._cfg.mixed_custom_history = False
    monkeypatch.setattr(engine, "read_mixed_history_blocks", changed)
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=1,
                          market_type="futures", min_revision=engine.storage.revision_store.head())
    assert result.retryable and not result.complete and not result.bars
    assert engine.storage.count_bars("BTCUSDT", "89m", 0, stop - 1, market_type="futures") == 0


def test_partial_finer_unqualified_grid_blocks_coarse_and_stays_incomplete(mixed_query):
    engine = mixed_query
    _, stop, _ = seed(engine, count=1)
    engine.storage.upsert_bars("BTCUSDT", "3m", [{**row(0, 3 * MINUTE), "volume": 20}],
                              source="data_manager_amended", market_type="futures")
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=1, market_type="futures",
                          min_revision=engine.storage.revision_store.head())
    assert not result.bars
    assert result.metadata["mixed_fallback_reason"]
    assert result.metadata["mixed_probe_reads"] + result.metadata["mixed_presence_reads"] > 0


@pytest.mark.parametrize("market,interval", [("spot", "89m"), ("futures", "1h"), ("futures", "5M")])
def test_composition_routes_are_qualified_by_market_and_boundary(market, interval):
    assert IntervalResolver().history_composition_routes(exchange="binance", market_type=market,
                                                        interval=interval) is None


def test_qualification_selects_only_proven_grids_but_fences_other_native_finer_grids():
    policy, selected, precedences = IntervalResolver().history_composition_routes(
        exchange="binance", market_type="futures", interval="10007m")
    assert {r.canonical_interval for r in selected} == {"1m", "5m", "15m", "1h", "4h", "1d"}
    assert "3m" in {r.canonical_interval for r in precedences}
    assert policy.to_dict()["identity_scope"] == "default-trade-base"


@pytest.mark.parametrize("changes", [dict(fields=("open", "volume")), dict(native_intervals=("1M",)),
    dict(native_intervals=("1s",)), dict(native_intervals=("1m", "1m")), dict(evidence=()),
    dict(contract_id=""), dict(min_width_ms=True), dict(fields=(["open"],)),
    dict(native_intervals=(["1m"],))])
def test_invalid_composition_scope_cannot_be_declared(changes):
    policy, _, _ = IntervalResolver().history_composition_routes(
        exchange="binance", market_type="futures", interval="89m")
    with pytest.raises(ValueError):
        replace(policy, **changes)


def test_partial_fine_amendment_is_not_bypassed_when_fine_cannot_fill_target(mixed_query):
    engine = mixed_query
    _, stop, _ = seed(engine, count=1)
    engine.storage.upsert_bars("BTCUSDT", "1m", [{**row(0, MINUTE), "high": 150, "volume": 20}],
                              source="data_manager_amended", market_type="futures")
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=1, market_type="futures",
                          min_revision=engine.storage.revision_store.head())
    assert not result.bars
    assert result.metadata["mixed_fallback_reason"]
    assert engine.storage.count_bars("BTCUSDT", "89m", 0, stop - 1, market_type="futures") == 0


def test_rollback_retains_source_data_and_valid_target_materialization(mixed_query):
    engine = mixed_query
    _, stop, inserted = seed(engine, count=1)
    engine._cfg.mixed_custom_history = False
    options = dict(start_ms=0, end_ms=stop - 1, limit=1, market_type="futures")
    old = engine.query("BTCUSDT", "89m", min_revision=engine.storage.revision_store.head(), **options)
    assert not old.bars and "mixed_history_attempted" not in old.metadata
    engine._cfg.mixed_custom_history = True
    current = engine.query("BTCUSDT", "89m", min_revision=engine.storage.revision_store.head(), **options)
    assert current.complete and current.metadata["mixed_history"]
    engine._cfg.mixed_custom_history = False
    restored = engine.query("BTCUSDT", "89m", min_revision=engine.storage.revision_store.head(), **options)
    assert restored.bars == current.bars and restored.metadata["target_materialized"]
    assert engine.storage.count_bars("BTCUSDT", "1m", 0, stop - 1, market_type="futures") == sum(
        interval == "1m" for interval, _ in inserted)


def test_large_fine_only_target_uses_bounded_h127_pages_instead_of_large_base_window(mixed_query, monkeypatch):
    engine = mixed_query
    stop = 10007 * MINUTE
    add_fine(engine, stop)
    original = engine._read_canonical_history_rows
    limits = []
    def bounded(storage, source, start_ms, end_ms, limit):
        limits.append(limit)
        return original(storage, source, start_ms, end_ms, limit)
    monkeypatch.setattr(engine, "_read_canonical_history_rows", bounded)
    result = engine.query("BTCUSDT", "10007m", start_ms=0, end_ms=stop - 1, limit=1,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    assert result.complete and not result.retryable
    assert result.metadata["mixed_history"]
    assert result.bars[0].volume == result.bars[0].trades == 10007
    assert result.metadata["mixed_accepted_rows"] == 10007
    assert max(limits) <= 257 and len(limits) > 1


def test_precedence_evidence_failure_is_pending_and_never_materialized(mixed_query, monkeypatch):
    engine = mixed_query
    _, stop, _ = seed(engine, count=1)
    def failed(_):
        raise OSError("controlled revision read failure")
    monkeypatch.setattr(engine.storage.revision_store, "read_series_changes", failed)
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=1,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    assert not result.bars and result.retryable and not result.complete
    assert engine.storage.count_bars("BTCUSDT", "89m", 0, stop - 1, market_type="futures") == 0
