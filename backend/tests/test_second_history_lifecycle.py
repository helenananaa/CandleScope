"""1s uses the normal durable-history path, with an independent memory cap."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import config as core_config
from app.data_engine.bar_aggregator import BarEvent, BarEventType, BarFinality, BarState
from app.data_engine.data_manager import DataManager, SeriesKey
from app.data_engine.data_manager.aggregator_bridge import AggregatorBridge
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.data_manager.models import BarData, QuerySource
from app.data_engine.data_manager.query import QueryEngine
from app.data_engine.interval_resolution import IntervalResolutionError
from app.data_engine.manual_history.models import StorageProtectionFloor
from app.data_engine.manual_history.planner import ManualHistoryPlanner
from app.data_engine.manual_history.repository import ManualHistoryRepository
from app.data_engine.manual_history.service import ManualHistoryService
from app.data_engine.storage import klines_repo

START = 1_700_000_000_000
KEY = SeriesKey("BTCUSDT", "1s")


def row(index: int) -> dict:
    return dict(open_time=START + index * 1000, close_time=START + index * 1000 + 999,
                open=10, high=12, low=9, close=11, volume=2,
                quote_volume=22, trades=1, taker_buy_base=1, taker_buy_quote=11)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    path = tmp_path / "bars.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


@pytest.mark.anyio
async def test_closed_and_amended_seconds_survive_process_restart(storage):
    cache, bus = BarCache(), DataEventBus()
    bridge = AggregatorBridge(cache=cache, event_bus=bus, storage_provider=lambda: storage,
                              mark_bar_received=lambda _: None, is_started=lambda: True)
    bar = BarState(symbol=KEY.symbol, interval="1s", bucket_start_ms=START,
                   bucket_end_ms=START + 1000, open=10, high=12, low=9, close=11, volume=2)
    try:
        await bridge.on_bar_event(BarEvent(BarEventType.UPDATED, bar))
        assert len(cache.get_latest(KEY, 10)) == 1
        assert storage.query_bars(KEY.symbol, "1s") == []
        assert await bridge.on_bar_event(BarEvent(BarEventType.CLOSED, bar)) is None
        assert storage.query_bars(KEY.symbol, "1s") == []
        final = replace(bar, finality=BarFinality.AUTHORITATIVE, close_reason="source_close")
        assert await bridge.on_bar_event(BarEvent(BarEventType.CLOSED, final)) == "accepted"
        amended = replace(final, close=12, volume=3)
        assert await bridge.on_bar_event(BarEvent(BarEventType.AMENDED, amended, previous_bar=final)) == "accepted"
        assert not storage.bar_delivery.pending()
        assert len(storage.query_bars(KEY.symbol, "1s")) == 1
    finally:
        await bridge.delivery.stop()
        await bus.close()

    # A genuinely fresh Python process has no prior cache/manager state.
    script = f'''
import json
from app.data_engine.storage import klines_repo
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.query import QueryEngine
from app.data_engine.data_manager.config import QueryConfig
klines_repo.KLINES_DB_PATH = {str(klines_repo.KLINES_DB_PATH)!r}
engine = QueryEngine(cache=BarCache(), storage=klines_repo.KlinesRepoAdapter(), config=QueryConfig(auto_backfill=False))
result = engine.query("BTCUSDT", "1s", start_ms={START}, end_ms={START}, limit=1)
print(json.dumps({{"count": len(result.bars), "close": result.bars[0].close, "volume": result.bars[0].volume, "source": result.source.value}}))
'''
    # Cold imports on a loaded host are not part of this durability assertion.
    process = await asyncio.to_thread(
        subprocess.run, [sys.executable, "-B", "-c", script],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=120,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout.splitlines()[-1]) == dict(count=1, close=12, volume=3, source="storage")


def test_seconds_history_pages_and_gaps_use_storage_and_normal_backfill(storage):
    storage.upsert_bars(KEY.symbol, "1s", [row(i) for i in (0, 1, 3, 4)], "backfill_rest_verified")
    triggered = []
    cache = BarCache()
    cache.set_ephemeral_limit(2)
    engine = QueryEngine(cache=cache, storage=storage, backfill_trigger=lambda *args, **kw: triggered.append((args, kw)))
    result = engine.query(KEY.symbol, "1s", start_ms=START, end_ms=START + 4000, limit=5)
    assert [bar.time for bar in result.bars] == [(START // 1000) + i for i in (0, 1, 3, 4)]
    assert result.backfill_triggered and triggered
    assert not result.complete
    assert result.metadata.get("ephemeral") is not True
    assert cache.series_count(KEY) <= 2
    reservation = cache.reserve_history_capacity(KEY, 10)
    assert reservation.capacity_bars == 2 and reservation.capped

    storage.upsert_bars(KEY.symbol, "1s", [row(2)], "backfill_rest_verified")
    engine = QueryEngine(cache=BarCache(), storage=storage, config=QueryConfig(auto_backfill=False))
    page = engine.query_before(KEY.symbol, "1s", before_ms=START + 5000, limit=3)
    assert [bar.time for bar in page.bars] == [(START // 1000) + i for i in (2, 3, 4)]
    older = engine.query_before(KEY.symbol, "1s", before_ms=START + 2000, limit=2)
    assert [bar.time for bar in older.bars] == [(START // 1000) + i for i in (0, 1)]
    assert older.source in (QuerySource.STORAGE, QuerySource.MIXED)
    assert older.metadata["storage_reads"] >= 1
    with pytest.raises(IntervalResolutionError):
        engine.query(KEY.symbol, "1s", exchange="bybit", market_type="spot")


@pytest.mark.anyio
async def test_seconds_gc_respects_protection_and_invalidates_cached_history(storage):
    storage.upsert_bars(KEY.symbol, "1s", [row(i) for i in range(10)], "backfill_rest_verified")
    dm = DataManager()
    dm.set_storage(storage)
    dm.cache.bulk_load(KEY, [BarData.from_storage_row(row(i)) for i in range(10)])
    floor = StorageProtectionFloor(key=KEY, protected_start_ms=START + 5000, owner_count=1,
                                  transient_owner_count=0, durable_owner_count=1, owner_ids=("COLLECTION:test",))
    dm.durable_protections.replace([floor])
    dm.update_retention_limits(db_limits={"seconds": 2}, storage_row_limits_enabled=True)
    plan = dm.plan_storage_gc()
    victim = next(v for v in plan["series"] if v["interval"] == "1s")
    assert victim["tier"] == "seconds" and victim["keep_rows"] == 5
    assert victim["would_delete_rows"] == 5 and victim["protection_clamped"]
    report = await dm.maintenance.run_storage_gc(plan=plan, batch_size=2)
    assert report["deleted_rows"] == 5
    assert [r["open_time"] for r in storage.query_bars(KEY.symbol, "1s", order="ASC")] == [START + i * 1000 for i in range(5, 10)]
    assert not dm.cache.has_series(KEY)
    assert len(dm.query(KEY.symbol, "1s", start_ms=START + 5000, end_ms=START + 9000, limit=5, auto_backfill=False).bars) == 5


@pytest.mark.anyio
async def test_existing_manual_download_seals_seconds_and_protects_them(storage):
    now_ms = START + 5000
    repo = ManualHistoryRepository(klines_repo.KLINES_DB_PATH)
    dm = DataManager()
    dm.set_storage(storage)
    planner = ManualHistoryPlanner(clock_ms=lambda: now_ms, get_bounds=storage.get_bounds,
                                   disk_snapshot=lambda: {"free_bytes": 10**10, "physical_size_bytes": 0})
    plan = planner.plan(exchange="binance", market_type="spot", symbols=[KEY.symbol], intervals=["1s"], start_ms=START)
    assert plan["can_start"] and plan["targets"][0]["source_strategy"] == "REST"
    requests = []

    async def fetch_native(**kwargs):
        requests.append(kwargs)
        return storage.upsert_bars(KEY.symbol, "1s", [row(i) for i in range(5)], "backfill_rest_verified")

    service = ManualHistoryService(repository=repo, data_manager=dm, planner=planner, storage=storage,
                                   enabled=True, clock_ms=lambda: now_ms, fetch_native=fetch_native)
    created = service.create_from_plan(plan, idempotency_key="seconds")
    result = await service.run_job(created.job.job_id)
    assert result.state.value == "SUCCEEDED"
    assert requests and requests[0]["interval"] == "1s"
    target = repo.list_job_targets(result.job_id)[0]
    assert target.state.value == "READY"
    floors = repo.active_protection_snapshot()
    assert floors[0].key.interval == "1s" and floors[0].durable_owner_count == 1
    restarted = DataManager()
    restarted.set_storage(klines_repo.KlinesRepoAdapter())
    restarted.reload_durable_protections(repository=ManualHistoryRepository(klines_repo.KLINES_DB_PATH))
    assert restarted.durable_protections.floor_for(KEY) is not None
    assert len(restarted.query(KEY.symbol, "1s", start_ms=START, end_ms=now_ms - 1000, limit=5, auto_backfill=False).bars) == 5
    restarted.update_retention_limits(db_limits={"seconds": 1}, storage_row_limits_enabled=True)
    assert restarted.plan_storage_gc()["would_delete_rows"] == 0


@pytest.mark.anyio
async def test_gap_maintenance_includes_stored_seconds(storage):
    storage.upsert_bars(KEY.symbol, "1s", [row(0)], "backfill_rest_verified")
    dm = DataManager()
    dm.set_storage(storage)
    requests = []
    async def repair(request):
        requests.append(request)
        return SimpleNamespace(bars_written=1, status="completed", error=None)
    await dm.maintenance.scan_and_fill_gaps(symbols_filter=[KEY.symbol], backfill_coordinator=SimpleNamespace(request_and_wait=repair))
    assert requests and requests[0].interval == "1s"


def test_cold_seconds_cache_can_be_evicted_and_reloaded(storage):
    storage.upsert_bars(KEY.symbol, "1s", [row(i) for i in range(3)], "backfill_rest_verified")
    dm = DataManager()
    dm.set_storage(storage)
    first = dm.query(KEY.symbol, "1s", start_ms=START, end_ms=START + 2000, limit=3, auto_backfill=False)
    assert len(first.bars) == 3
    plan = dm.plan_memory_gc({"cold_idle_seconds": 0})
    victim = next(v for v in plan["victims"] if v["interval"] == "1s")
    assert victim["ephemeral"] is False
    assert victim["restoreCostReason"] == "sqlite-reload"
    report = dm.run_memory_gc({"cold_idle_seconds": 0})
    assert report["removed_series"] == 1
    assert not dm.cache.has_series(KEY)
    again = dm.query(KEY.symbol, "1s", start_ms=START, end_ms=START + 2000, limit=3, auto_backfill=False)
    assert len(again.bars) == 3 and again.source == QuerySource.STORAGE
