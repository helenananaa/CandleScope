from __future__ import annotations

import pytest

from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import CacheConfig
from app.data_engine.data_manager.models import BarData, SeriesKey


KEY = SeriesKey("BTCUSDT", "1m")
OTHER = SeriesKey("ETHUSDT", "1m")


def _bar(time=60, close=100):
    return BarData(time, 100, 250, 50, close, 10, source="backfill_rest_verified")


@pytest.mark.parametrize("action", ["invalidate", "remove_series", "clear"])
@pytest.mark.parametrize("resident", [False, True])
def test_removal_fences_old_reads_even_when_key_is_absent(action, resident):
    cache = BarCache()
    if resident:
        cache.append(KEY, _bar())
    with cache.read_token(KEY) as token:
        if action == "clear":
            cache.clear()
        else:
            getattr(cache, action)(KEY)
        assert not cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=token)
        assert cache.get_latest(KEY, 1) == []
        # New work after the invalidation is permitted to reload the series.
        with cache.read_token(KEY) as fresh:
            assert cache.bulk_load_if_unchanged(KEY, [_bar(close=200)], read_token=fresh)
        assert not cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=token)
    assert cache.snapshot()["active_read_tokens"] == 0


@pytest.mark.parametrize("mutation", ["append", "upsert", "upsert_if_accepted", "bulk_load", "trim"])
def test_concurrent_writes_or_trimming_reject_old_page(mutation):
    cache = BarCache()
    cache.bulk_load(KEY, [_bar(), _bar(120)])
    with cache.read_token(KEY) as token:
        if mutation == "bulk_load":
            cache.bulk_load(KEY, [_bar(close=200)])
        elif mutation == "trim":
            cache.trim_series(KEY, 1)
        else:
            getattr(cache, mutation)(KEY, _bar(close=200))
        assert not cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=token)


def test_multi_page_read_preserves_quality_and_does_not_fence_other_series():
    cache = BarCache()
    with cache.read_token(KEY) as token, cache.read_token(OTHER) as other:
        assert cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=token)
        cache.get_latest(KEY, 1)  # Access revision is not a data change.
        assert cache.bulk_load_if_unchanged(KEY, [_bar(120)], read_token=token)
        assert cache.bulk_load_if_unchanged(OTHER, [_bar()], read_token=other)
        lower = BarData(60, 1, 2, 0, 1, 1, source="data_manager_closed")
        assert cache.bulk_load_if_unchanged(KEY, [lower], read_token=token)
        assert cache.get_bar_at(KEY, 60).close == 100


def test_competing_refill_invalidates_other_read_and_empty_read_is_checked():
    cache = BarCache()
    with cache.read_token(KEY) as first, cache.read_token(KEY) as second:
        assert cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=first)
        assert not cache.bulk_load_if_unchanged(KEY, [], read_token=second)
        assert cache.bulk_load_if_unchanged(KEY, [], read_token=first)


def test_aba_through_lru_eviction_keeps_cold_read_invalid():
    cache = BarCache(CacheConfig(max_series=1))
    with cache.read_token(KEY) as token:
        cache.append(KEY, _bar(close=200))
        cache.append(OTHER, _bar())
        assert cache.get_latest(KEY, 1) == []
        assert not cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=token)


def test_idle_eviction_rejects_read_from_old_incarnation(monkeypatch):
    cache = BarCache(CacheConfig(ttl_seconds=1))
    cache.append(KEY, _bar())
    with cache.read_token(KEY) as token:
        monkeypatch.setattr("app.data_engine.data_manager.cache.time.time", lambda: 10**12)
        assert cache.evict_idle() == 1
        assert not cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=token)


def test_tokens_are_scoped_to_cache_key_and_context_even_after_error():
    cache = BarCache()
    other_cache = BarCache()
    with pytest.raises(RuntimeError):
        with cache.read_token(KEY) as token:
            assert not other_cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=token)
            assert not cache.bulk_load_if_unchanged(OTHER, [_bar()], read_token=token)
            raise RuntimeError("read failed")
    assert not cache.bulk_load_if_unchanged(KEY, [_bar()], read_token=token)
    assert cache.snapshot()["active_read_tokens"] == 0
