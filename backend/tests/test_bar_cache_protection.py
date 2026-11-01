"""Real cache-owner protection, bounded admission and controlled claim races."""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.cache import CacheCapacityError
from app.data_engine.data_manager.config import CacheConfig, DataManagerConfig
from app.data_engine.data_manager.gc import execute_memory_gc_plan
from app.data_engine.data_manager.manager import StreamCapacityError
from app.data_engine.data_manager.models import BarData, SeriesKey, StreamInfo, StreamStatus
from app.data_engine.storage import klines_repo


def _manager(maximum=2, ttl=0):
    return DataManager(DataManagerConfig(cache=CacheConfig(max_series=maximum, ttl_seconds=ttl)))


def _bar(timestamp=60):
    return BarData(time=timestamp, open=1, high=1, low=1, close=1, volume=1)


async def _sink(event):
    pass


@pytest.mark.parametrize("protection", ["lease", "subscription", "target", "stream"])
def test_lru_skips_oldest_protected_series(protection):
    dm = _manager()
    active, cold, incoming = (SeriesKey(symbol, "1m") for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    dm.cache.upsert(active, _bar())
    dm.cache.upsert(cold, _bar())
    if protection == "lease":
        dm._register_stream_leases((active,), consumer_id="chart:one")
    elif protection == "subscription":
        dm.event_bus.subscribe(_sink, key=active)
    elif protection == "target":
        dm.bar_aggregator.add_target(active.symbol, active.interval)
    else:
        dm.coordinator._streams[active] = SimpleNamespace(info=StreamInfo(key=active, status=StreamStatus.ACTIVE))

    dm.cache.upsert(incoming, _bar())

    assert set(dm.cache.get_all_keys()) == {active, incoming}
    assert dm.cache.snapshot()["evictions"] == 1


def test_all_protected_declines_cold_admission_and_rejects_realtime_without_overflow():
    dm = _manager(1)
    active, incoming = SeriesKey("BTCUSDT", "1m"), SeriesKey("ETHUSDT", "1m")
    dm.cache.upsert(active, _bar())
    dm._register_stream_leases((active,), consumer_id="chart:one")
    dm._register_stream_leases((active,), consumer_id="indicator:one")
    assert dm.cache.bulk_load(incoming, [_bar()]) is False
    with pytest.raises(CacheCapacityError):
        dm.cache.upsert_if_accepted(incoming, _bar())
    dm._release_stream_leases((active,), consumer_id="chart:one")
    with pytest.raises(CacheCapacityError):
        dm.cache.append(incoming, _bar())
    assert dm.cache.get_all_keys() == [active]
    assert dm.cache.snapshot()["admission_rejected"] == 3
    dm._release_stream_leases((active,), consumer_id="indicator:one")
    assert dm.cache.upsert_if_accepted(incoming, _bar()) == (True, _bar())
    assert dm.cache.get_all_keys() == [incoming]


def test_stream_plan_cannot_claim_more_resident_series_than_cache_can_hold():
    dm = _manager(1)
    keys = (SeriesKey("BTCUSDT", "1m"), SeriesKey("BTCUSDT", "5m"))
    with pytest.raises(StreamCapacityError):
        dm._register_stream_leases(keys, consumer_id="chart:one")
    assert dm._stream_leases == {}
    assert dm.stream_lease_snapshot()["max_active_series"] == 1


def test_ttl_uses_same_protection_and_wildcards_do_not_pin_every_series(monkeypatch):
    monkeypatch.setattr("app.data_engine.data_manager.cache.time.time", lambda: 100.0)
    dm = _manager(3, ttl=10)
    active, subscribed, cold = (SeriesKey(symbol, "1m") for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    for key in (active, subscribed, cold):
        dm.cache.upsert(key, _bar())
    dm._register_stream_leases((active,), consumer_id="chart:one")
    handle = dm.event_bus.subscribe(_sink, key=subscribed)
    dm.event_bus.subscribe(_sink)
    monkeypatch.setattr("app.data_engine.data_manager.cache.time.time", lambda: 111.0)
    assert dm.cache.evict_idle() == 1
    assert set(dm.cache.get_all_keys()) == {active, subscribed}
    dm._release_stream_leases((active,), consumer_id="chart:one")
    dm.event_bus.unsubscribe(handle)
    assert dm.cache.evict_idle() == 2


def test_target_protection_preserves_semantic_identity():
    dm = _manager(2)
    special = SeriesKey("BTCUSDT", "1m", series_variant="mark")
    ordinary = SeriesKey("BTCUSDT", "1m")
    incoming = SeriesKey("ETHUSDT", "1m")
    dm.cache.upsert(special, _bar())
    dm.cache.upsert(ordinary, _bar())
    dm.bar_aggregator.add_target(special.symbol, special.interval, series_identity=special.identity)
    assert dm._protected_storage_keys() == {special}
    plan = dm.plan_memory_gc({"cold_idle_seconds": 0})
    assert plan["protected_count"] == 1
    dm.cache.upsert(incoming, _bar())
    assert set(dm.cache.get_all_keys()) == {special, incoming}


@pytest.mark.parametrize("action", ["delete-series", "trim-series"])
def test_lease_between_gc_precheck_and_owner_mutation_is_protected(monkeypatch, action):
    dm = _manager()
    key = SeriesKey("BTCUSDT", "1m" if action == "delete-series" else "1s")
    dm.cache.bulk_load(key, [_bar(60), _bar(120)])
    dm.cache.set_ephemeral_limit(1)
    plan = dm.plan_memory_gc({"cold_idle_seconds": 0})
    assert plan["victims"][0]["action"] == action
    name = "remove_series_if_unchanged" if action == "delete-series" else "trim_series_if_unchanged"
    original = getattr(dm.cache, name)

    def intervene(*args, **kwargs):
        dm._register_stream_leases((key,), consumer_id="chart:late")
        return original(*args, **kwargs)

    monkeypatch.setattr(dm.cache, name, intervene)
    report = execute_memory_gc_plan(dm, plan)
    assert report["removed_bars"] == 0
    assert report["skipped_count"] == 1
    assert report["status"] == "constrained"
    assert report["results"][0]["status"] == "protected-at-execute"
    assert dm.cache.series_count(key) == 2


def test_eviction_claim_and_new_lease_are_mutually_exclusive(monkeypatch):
    dm = _manager(1)
    old, new = SeriesKey("BTCUSDT", "1m"), SeriesKey("ETHUSDT", "1m")
    dm.cache.upsert(old, _bar())
    claim, release, attempted, acquired = (threading.Event() for _ in range(4))
    original = dm.cache._is_protected

    def pause(key):
        claim.set()
        assert release.wait(5)
        return original(key)

    def lease():
        assert not dm._storage_gc_guard.acquire(blocking=False)
        attempted.set()
        dm._register_stream_leases((old,), consumer_id="chart:late")
        acquired.set()

    monkeypatch.setattr(dm.cache, "_is_protected", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        eviction = pool.submit(dm.cache.upsert, new, _bar())
        assert claim.wait(5)
        acquisition = pool.submit(lease)
        try:
            assert attempted.wait(5)
            assert not acquired.is_set()
        finally:
            release.set()
        eviction.result(5)
        acquisition.result(5)
    assert acquired.is_set()
    assert dm.cache.get_all_keys() == [new]


def test_logical_invalidation_still_fences_protected_series():
    dm = _manager(1)
    key = SeriesKey("BTCUSDT", "1m")
    dm.cache.upsert(key, _bar())
    dm._register_stream_leases((key,), consumer_id="chart:one")
    with dm.cache.read_token(key) as token:
        dm.cache.invalidate(key)
        assert not dm.cache.bulk_load_if_unchanged(key, [_bar()], read_token=token)
    assert not dm.cache.has_series(key)


@pytest.mark.parametrize("cancel", [False, True])
def test_loop_write_waits_cooperatively_for_worker_gc_and_can_cancel(cancel):
    dm = _manager()
    key = SeriesKey("BTCUSDT", "1m")
    holding, release = threading.Event(), threading.Event()

    def worker():
        with dm._storage_gc_guard:
            holding.set()
            # Rescue a broken synchronous wait so the regression fails rather
            # than hanging pytest. Successful execution explicitly releases it.
            release.wait(2)

    async def run():
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            assert holding.wait(2)
            task = asyncio.create_task(dm.coordinator.on_bar_event(key.symbol, key.interval, _bar()))
            try:
                await asyncio.sleep(0)
                assert not task.done()
                assert not dm.cache.has_series(key)
                if cancel:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
            finally:
                release.set()
            future.result(2)
            if not cancel:
                await asyncio.wait_for(task, 2)
            assert dm.cache.has_series(key) is (not cancel)

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["range", "before"])
def test_storage_query_remains_available_when_all_cache_slots_are_protected(tmp_path, monkeypatch, mode):
    path = tmp_path / "bars.sqlite"
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", path)
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    start = 1_700_000_040_000
    rows = [dict(open_time=start + i * 60_000, close_time=start + (i + 1) * 60_000 - 1,
                 open=1, high=1, low=1, close=1, volume=1,
                 quote_volume=1, trades=1, taker_buy_base=0.5,
                 taker_buy_quote=0.5) for i in range(2)]
    klines_repo.upsert_klines("ETHUSDT", "1m", rows, source="backfill_rest_verified")
    dm = _manager(1)
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    active = SeriesKey("BTCUSDT", "1m")
    dm.cache.upsert(active, _bar())
    dm._register_stream_leases((active,), consumer_id="chart:one")
    if mode == "range":
        result = dm.query("ETHUSDT", "1m", start_ms=start, end_ms=start + 60_000,
                          limit=2, auto_backfill=False)
    else:
        result = dm.query_before("ETHUSDT", "1m", before_ms=start + 120_000,
                                 limit=2, auto_backfill=False)
    assert [bar.time_ms for bar in result.bars] == [start, start + 60_000]
    assert not result.metadata.get("cache_read_conflict")
    assert dm.cache.get_all_keys() == [active]
    assert dm.cache.snapshot()["admission_rejected"] >= 1
