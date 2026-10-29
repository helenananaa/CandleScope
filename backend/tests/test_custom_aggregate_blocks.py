from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.data_engine.data_manager.aggregate_blocks import AggregateBlockCache
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.custom_query import CustomIntervalQueryService, _aggregate_fixed_bars_to_interval
from app.data_engine.data_manager.models import BarData, SeriesKey


def rows(count=100, source_width=86400):
    rng = random.Random(127)
    return [BarData(time=i * source_width, open=1 + rng.random(), high=3 + rng.random(),
                    low=rng.random(), close=1 + rng.random(), volume=rng.random() * 1e8,
                    quote_volume=rng.random() * 1e10, trades=i * 17,
                    taker_buy_base=rng.random(), taker_buy_quote=rng.random(), source="backfill")
            for i in range(count)]


def reduce(cache, source, factor, key=SeriesKey("BTCUSDT", "1d"), source_width=86400):
    fallback = lambda bars, on_bucket=None: _aggregate_fixed_bars_to_interval(
        bars, factor * source_width, source_interval_seconds=source_width, on_bucket=on_bucket)
    actual = cache.aggregate(source, key, factor * source_width, source_width, fallback)
    assert actual == fallback(source)
    return actual


@pytest.mark.parametrize("factor", [2, 3, 4, 5, 7, 17, 32, 64])
@pytest.mark.parametrize("variant", ["closed", "partial", "gap", "forming", "untrusted", "duplicate", "enhanced"])
def test_mixed_cover_exactly_preserves_canonical_values_and_finality(factor, variant):
    source = rows(factor * 8 + 1)
    if variant == "partial":
        source = source[1:-2]
    elif variant == "gap":
        del source[factor + 1]
    elif variant == "forming":
        source[-1] = replace(source[-1], is_closed=False)
    elif variant == "untrusted":
        source[2] = replace(source[2], source="unknown")
    elif variant == "duplicate":
        source.insert(3, replace(source[2], volume=9876))
    elif variant == "enhanced":
        source[1] = replace(source[1], quote_volume=None)
        source[2] = replace(source[2], trades=-1, taker_buy_base=float("nan"))
        source[-1]._prevalidated_aggregation_fields = (None, None, None, None)
    random.Random(45).shuffle(source)
    cache = AggregateBlockCache()
    cold = reduce(cache, source, factor)
    assert reduce(cache, source, factor) == cold


def test_cross_period_blocks_share_only_same_source_and_cover_boundaries():
    source = rows()
    cache = AggregateBlockCache()
    reduce(cache, source, 2)
    before = cache.snapshot()
    reduce(cache, source, 4)
    middle = cache.snapshot()
    reduce(cache, source, 5)
    after = cache.snapshot()
    assert middle["hits"] > before["hits"]
    assert after["hits"] > middle["hits"]
    assert after["mixed_buckets"] > 0 and after["fine_rows"] > 0
    # No target interval in the cache identity. All source semantics are in it.
    for key in [SeriesKey("ETHUSDT", "1d"), SeriesKey("BTCUSDT", "1d", exchange="okx"),
                SeriesKey("BTCUSDT", "1d", market_type="futures"), SeriesKey("BTCUSDT", "12h"),
                SeriesKey("BTCUSDT", "1d", series_variant="alternate")]:
        previous_hits = cache.snapshot()["hits"]
        reduce(cache, source, 2, key)
        assert cache.snapshot()["hits"] == previous_hits


@pytest.mark.parametrize("field,value", [
    ("open", 2.123456789), ("high", 17), ("low", -1), ("close", 2.765432198),
    ("volume", 1.23456789), ("quote_volume", None), ("trades", 76),
    ("taker_buy_base", 0.123), ("taker_buy_quote", 0.456), ("source", "archive"),
    ("is_closed", False), ("_prevalidated_aggregation_fields", (None, None, None, None)),
])
def test_corrections_including_mutation_and_decoder_contract_cannot_reuse_stale_values(field, value):
    cache = AggregateBlockCache()
    source = rows(40)
    reduce(cache, source, 4)
    setattr(source[2], field, value)
    reduce(cache, source, 4)
    reduce(cache, source, 2)
    del source[3]
    reduce(cache, source, 5)
    assert cache.snapshot()["fallback_buckets"] > 0


def test_concurrent_readers_corrections_and_lru_stay_bounded():
    cache = AggregateBlockCache(max_components=64, max_entries=12)
    source = rows(80)
    changed = [replace(bar, volume=bar.volume / 3) for bar in source]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(reduce, cache, source if i % 2 else changed, [2, 4, 5][i % 3])
                   for i in range(48)]
        for future in futures:
            future.result()
    assert cache.snapshot()["components"] <= 64
    assert cache.snapshot()["entries"] <= 12
    assert cache.snapshot()["evictions"] > 0


def test_stress_case_bypasses_block_cache_and_preserves_streaming_budget():
    cache = AggregateBlockCache()
    reduce(cache, rows(20014, 60), 10007, SeriesKey("BTCUSDT", "1m"), 60)
    assert cache.snapshot()["entries"] == 0


def test_cached_complete_child_cannot_certify_a_partial_parent():
    cache = AggregateBlockCache()
    source = rows(8)
    reduce(cache, source, 2)
    partial = reduce(cache, source[:2], 5)
    assert len(partial) == 1 and not partial[0].is_closed
    assert partial[0].quote_volume is None


def test_published_mutable_targets_cannot_modify_shared_blocks():
    cache = AggregateBlockCache()
    source = rows(12)
    outputs = reduce(cache, source, 4)
    outputs[0].volume = -1
    reduce(cache, source, 4)


def test_compact_decoded_rows_retain_their_twice_normalized_contract():
    source = rows(100)
    for bar in source:
        values = bar.normalized_aggregation_values()
        bar.open, bar.high, bar.low, bar.close, bar.volume = values[1:6]
        bar._prevalidated_aggregation_fields = bar.normalized_aggregation_fields()
    source[3]._prevalidated_aggregation_fields = (None, None, None, None)
    cache = AggregateBlockCache()
    for factor in [2, 4, 5, 2, 4, 5]:
        reduce(cache, source, factor)


@pytest.mark.parametrize("stream", [False, True])
def test_production_query_wires_shared_blocks_and_rollback(stream):
    from tests.test_custom_history_streaming import service_for
    source = rows(100, 900)
    service = service_for(source, enabled=stream, page_size=11 if stream else 1000)
    service._cfg.share_custom_aggregate_blocks = True
    kwargs = dict(symbol="BTCUSDT", interval="45m", start_ms=0,
                  end_ms=30 * 2700_000, limit=30, started_at=0)
    first = service.query_from_base(**kwargs)
    second = service.query_from_base(**kwargs)
    assert first.bars == second.bars
    assert service.snapshot()["aggregate_blocks_hits"] > 0
    assert service.snapshot()["aggregate_blocks_builds"] > 0
    service._cfg.share_custom_aggregate_blocks = False
    snapshot = service._aggregate_blocks.snapshot()
    assert service.query_from_base(**kwargs).bars == first.bars
    assert service._aggregate_blocks.snapshot() == snapshot


def test_native_three_day_and_calendar_paths_are_not_replaced():
    service = CustomIntervalQueryService(cache=BarCache(), config=QueryConfig(share_custom_aggregate_blocks=True), base_query=lambda: None)
    source = rows(20)
    service.aggregate_custom_bars(source, "BTCUSDT", "3d", source_interval="3d")
    service.aggregate_custom_bars(source, "BTCUSDT", "2M", source_interval="1d")
    assert service._aggregate_blocks.snapshot()["entries"] == 0


@pytest.mark.parametrize("correct_source", [False, True])
def test_sqlite_cross_period_sharing_revalidates_committed_source_rows(monkeypatch, tmp_path, correct_source):
    from app.data_engine.data_manager.query import QueryEngine
    from app.data_engine.storage import klines_repo
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "mixed.sqlite")
    klines_repo.init_klines_storage()
    source = rows(40)
    def write(items):
        klines_repo.upsert_klines("BTCUSDT", "1d", [dict(
            open_time=bar.time_ms, close_time=bar.time_ms + 86400_000 - 1,
            open=bar.open, high=bar.high, low=bar.low, close=bar.close,
            volume=bar.volume, quote_volume=bar.quote_volume, trades=bar.trades,
            taker_buy_base=bar.taker_buy_base, taker_buy_quote=bar.taker_buy_quote,
        ) for bar in items], source="backfill", exchange="binance", market_type="futures")
    write(source)
    cache = BarCache()
    engine = QueryEngine(cache, klines_repo.KlinesRepoAdapter(), QueryConfig(
        auto_backfill=False, share_custom_aggregate_blocks=True))
    def query(factor):
        return engine.query("BTCUSDT", f"{factor}d", start_ms=0,
                            end_ms=(40 - factor) * 86400_000, limit=40 // factor, market_type="futures")
    assert query(2).complete and query(4).complete
    if correct_source:
        source[2] = replace(source[2], volume=source[2].volume * 3, high=99)
        write([source[2]])
        # The storage writer's normal cache invalidation is outside this
        # fixture. Keep the aggregate-block cache warm while refreshing base.
        cache.invalidate(SeriesKey("BTCUSDT", "1d", market_type="futures"))
    result = query(5)
    assert result.complete and len(result.bars) == 8
    assert engine.custom_intervals.snapshot()["aggregate_blocks_mixed_buckets"] > 0
    assert engine.custom_intervals.snapshot()["aggregate_blocks_hits"] > 0
    oracle = _aggregate_fixed_bars_to_interval(source, 5 * 86400, source_interval_seconds=86400)
    assert [bar.to_kline_dict() for bar in result.bars] == [bar.to_kline_dict() for bar in oracle]
