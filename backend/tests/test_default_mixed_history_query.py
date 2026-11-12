"""Default QueryEngine integration; real canonical SQLite, no mocked reducer."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace

import pytest

from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import FixedHistorySource, plan_fixed_target
from app.data_engine.interval_resolution import IntervalResolver
from app.data_engine.storage import klines_repo
from tests.test_mixed_history_reader import row, FIELDS, MINUTE
from tests.test_shared_aggregation_blocks import assert_idle


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
    assert result.metadata["mixed_probe_reads"] > 0


@pytest.mark.parametrize("market,interval", [("spot", "89m"), ("futures", "1h"), ("futures", "5M")])
def test_composition_routes_are_qualified_by_market_and_boundary(market, interval):
    assert IntervalResolver().history_composition_routes(exchange="binance", market_type=market,
                                                        interval=interval) is None


def test_qualification_selects_only_proven_grids_but_fences_other_native_finer_grids():
    policy, selected, precedences = IntervalResolver().history_composition_routes(
        exchange="binance", market_type="futures", interval="10007m")
    assert {r.canonical_interval for r in selected} == {"1m", "5m", "15m", "1h"}
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
