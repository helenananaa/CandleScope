"""Real SQLite batching, identity isolation and default mixed-query fences."""
import pytest

from app.data_engine.series_identity import KlineSeriesIdentity
from tests.test_default_mixed_history_query import mixed_query, seed
from tests.test_mixed_history_reader import row, MINUTE


def test_range_presence_preserves_order_boundaries_duplicates_and_full_identity(mixed_query):
    storage = mixed_query.storage
    identity = KlineSeriesIdentity.for_exchange("binance", series_variant="mark")
    for options, opened in ((dict(market_type="spot"), 0),
                            (dict(market_type="futures"), MINUTE),
                            (dict(market_type="futures", series_identity=identity), 2 * MINUTE)):
        storage.upsert_bars("BTCUSDT", "1m", [row(opened, MINUTE)], source="backfill", **options)
    ranges = ((2 * MINUTE, 3 * MINUTE), (0, MINUTE), (MINUTE, 2 * MINUTE), (MINUTE, 2 * MINUTE))
    assert storage.query_bars_range_presence("BTCUSDT", "1m", ranges, market_type="futures") == [False, False, True, True]
    assert storage.query_bars_range_presence("BTCUSDT", "1m", ranges, market_type="spot") == [False, True, False, False]
    assert storage.query_bars_range_presence("BTCUSDT", "1m", ranges, market_type="futures",
                                            series_identity=identity) == [True, False, False, False]
    assert storage.query_bars_range_presence("BTCUSDT", "5m", ranges, market_type="futures") == [False] * 4
    assert storage.query_bars_range_presence("BTCUSDT", "1m", ((0, 1),) * 256,
                                            market_type="spot") == [True] * 256


@pytest.mark.parametrize("ranges", [(), ((0, 1),) * 257, ((1, 1),), ((2, 1),), ((-1, 1),),
    ((False, 1),), ((0, 1.0),), ((0, 1, 2),), [(0, 1)]])
def test_presence_query_rejects_unbounded_or_invalid_work(mixed_query, ranges):
    with pytest.raises(ValueError):
        mixed_query.storage.query_bars_range_presence("BTCUSDT", "1m", ranges)


def test_many_targets_batch_probe_work_instead_of_probing_each_span(mixed_query, monkeypatch):
    engine = mixed_query
    _, stop, _ = seed(engine, count=65)
    original = engine.storage.query_bars_range_presence
    sizes = []
    def bounded(symbol, interval, ranges, **options):
        sizes.append(len(ranges))
        assert 0 < len(ranges) <= 256
        return original(symbol, interval, ranges, **options)
    monkeypatch.setattr(engine.storage, "query_bars_range_presence", bounded)
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=65,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    assert result.complete and len(result.bars) == 65
    assert all(bar.volume == 89 and bar.trades == 89 for bar in result.bars)
    assert len(sizes) <= 9  # Three qualified finer grids across three bounded batches.
    assert result.metadata["mixed_presence_reads"] == len(sizes)
    assert result.metadata["mixed_probe_reads"] == 0
    assert result.metadata["mixed_preflight_positions"] > 0


@pytest.mark.parametrize("mutation", ["insert", "delete"])
def test_revision_during_batch_probe_never_publishes_or_materializes(mixed_query, monkeypatch, mutation):
    engine = mixed_query
    _, stop, _ = seed(engine, count=3)
    original = engine.storage.query_bars_range_presence
    done = False
    def changed(*args, **kwargs):
        nonlocal done
        flags = original(*args, **kwargs)
        if not done:
            done = True
            if mutation == "insert":
                engine.storage.upsert_bars("BTCUSDT", "1m", [{**row(0, MINUTE), "volume": 77}],
                                          source="data_manager_amended", market_type="futures")
            else:
                engine.storage.delete_bars("BTCUSDT", "1m", start_ms=0, end_ms=stop - 1,
                                          market_type="futures")
        return flags
    monkeypatch.setattr(engine.storage, "query_bars_range_presence", changed)
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=3,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    assert done and result.retryable and not result.bars and not result.complete
    assert engine.storage.count_bars("BTCUSDT", "89m", 0, stop - 1, market_type="futures") == 0


def test_existing_storage_without_optional_batch_probe_keeps_safe_single_probes(mixed_query, monkeypatch):
    engine = mixed_query
    _, stop, _ = seed(engine, count=3)
    monkeypatch.setattr(engine.storage, "query_bars_range_presence", None)
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=3,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    assert result.complete and result.bars[0].volume == 89
    assert result.metadata["mixed_presence_reads"] == 0
    assert result.metadata["mixed_probe_reads"] > 0


@pytest.mark.parametrize("fault", ["io", "wrong_size", "untyped_flag"])
def test_failed_or_malformed_presence_probe_cannot_qualify_native_coarse(mixed_query, monkeypatch, fault):
    engine = mixed_query
    _, stop, _ = seed(engine, count=3)
    def failed(*args, **kwargs):
        if fault == "io":
            raise OSError("controlled presence read failure")
        return [] if fault == "wrong_size" else [0] * len(args[2])
    monkeypatch.setattr(engine.storage, "query_bars_range_presence", failed)
    result = engine.query("BTCUSDT", "89m", start_ms=0, end_ms=stop - 1, limit=3,
        market_type="futures", min_revision=engine.storage.revision_store.head())
    assert not any(bar.trusted_final for bar in result.bars)
    assert result.metadata["mixed_fallback_reason"]
    if fault == "io":
        assert result.metadata["mixed_presence_failures"] == 1
        assert result.metadata["storage_failures"] >= 1
    assert engine.storage.count_bars("BTCUSDT", "89m", 0, stop - 1, market_type="futures") == 0
