"""The router obeys a route-aware mixed plan's archive choices (step 3 of MIXED_ROUTE_PLANNING_zh.md).

Plans come from the real route-aware planner over two adjacent 16-target
10007m chunks (``tests/test_mixed_routes.py``), then go through the real
``HistoricalSourceRouter`` and ``HistoricalFetcher`` against a Binance archive
and REST double. The rows a fetch returns must be exactly the rows the plan
counted (whole listed objects plus its REST windows): that is what the
planner's property test writes and composes. These tests check that:

- the router imports exactly the listed objects, each once, owned by one
  task, and gives REST tasks no object, while unplanned tasks routed in the
  same call keep today's selection;
- a listed object that fails to download (404) or is absent from the catalog
  at fetch time arrives whole over REST, so the rows are still exactly the
  plan's;
- the write windows taken from the plan alone (``planned_route_windows``,
  captured before fetching) are the windows the fetcher reports after
  routing, so capturing them first leaves routing no view to add (step 4).
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from dataclasses import replace

import pytest

from app.data_engine.backfill import mixed_routes
from app.data_engine.backfill.archive_cache import HistoricalArchiveCache
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher, planned_route_windows, planned_write_windows
from app.data_engine.backfill.models import BackfillStatus
from app.data_engine.backfill.source_router import PLANNED_OBJECTS_KEY, HistoricalSourceRouter
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.storage.native_history_fence import capture_planned_write_views
from app.data_engine.storage.revisions import Acquisition
from app.exchanges.archive import ArchiveHttpResponse
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider
from tests.history_stream_transport import IntervalTransport
from tests.test_history_archive_routing import (  # noqa: F401  (autouse fixture)
    _archive_payload,
    _isolate_archive_routing_from_production_cold_start,
)
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_session import manager_for
from tests.test_mixed_routes import CHUNKS, NOW, WIDTHS, catalog, plan_chunk, stored_rows, written_cells


class ArchiveHttp:
    """Serves every Binance object as a complete, checksummed ZIP, except ``missing`` (404)."""

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.refs = {}
        self.downloads = []

    def add(self, refs):
        self.refs.update((ref.expected_filename, ref) for ref in refs)

    def _payload(self, filename):
        ref = self.refs[filename]
        width = WIDTHS[ref.interval]
        return _archive_payload(ref, (ref.end_ms + 1 - ref.start_ms) // width, interval_ms=width)

    async def get_bytes(self, url, *, allowed_hosts, max_bytes):
        filename = url.rsplit("/", 1)[-1].removesuffix(".CHECKSUM")
        digest = hashlib.sha256(self._payload(filename)).hexdigest()
        return ArchiveHttpResponse(200, {}, f"{digest}  {filename}\n".encode())

    async def download(self, url, destination, *, allowed_hosts, max_bytes):
        filename = url.rsplit("/", 1)[-1]
        self.downloads.append(filename)
        if filename in self.missing:
            return ArchiveHttpResponse(404, {})
        destination.write_bytes(self._payload(filename))
        return ArchiveHttpResponse(200, {})

    async def head(self, url, *, allowed_hosts):
        return ArchiveHttpResponse(200, {})

    async def post_json(self, *args, **kwargs):
        raise AssertionError("Binance archives use no resolver")


def planned_chunks(tmp_path, monkeypatch, seed):
    """``[(start, stop, plan)]`` for the chunks route-aware planning adopted."""
    rng = random.Random(seed)
    monkeypatch.setattr(mixed_routes, "ROUTE_AWARE", True)
    monkeypatch.setattr(mixed_routes, "archive_catalog", lambda engine: catalog())
    monkeypatch.setattr("app.data_engine.backfill.mixed_plan.time.time", lambda: NOW / 1000)
    manager = manager_for(tmp_path / "plans.sqlite", stored_rows(rng, cold=seed < 3), monkeypatch)
    try:
        engine = engine_for(manager.query_engine)
        chunks = []
        for start, stop in CHUNKS:
            plan, report = plan_chunk(manager, engine, start, stop)
            if plan is not None:
                assert report["mixed_route_aware"] is True
                chunks.append((start, stop, plan))
        return chunks
    finally:
        asyncio.run(manager.shutdown())


def listed(plan):
    return {key for task in plan.tasks for key in task.metadata[PLANNED_OBJECTS_KEY]}


def refs_for(tasks):
    provider = BinanceKlineArchiveProvider()
    refs = {}
    for task in tasks:
        for ref in provider.plan_objects(market_type="futures", symbol=task.symbol, interval=task.interval,
                                         start_ms=task.start_ms, end_ms=task.end_ms + WIDTHS[task.interval] - 1,
                                         now_ms=NOW):
            refs[ref.object_key] = ref
    return refs


def router_and_fetcher(tmp_path, http):
    config = BackfillConfig(history_archive_enabled=True, history_archive_cache_dir=str(tmp_path / "zips"),
                            history_archive_cache_max_bytes=200_000_000, fetch_rate_limit_delay=0,
                            fetch_max_retries=0, reconcile_generate_custom=False,
                            reconcile_enable_cache_push=False)
    router = HistoricalSourceRouter(config, cache=HistoricalArchiveCache(
        tmp_path / "zips", max_bytes=config.history_archive_cache_max_bytes), http=http,
        deferred_prefetch_delay_seconds=0)
    transport = IntervalTransport()
    return router, HistoricalFetcher(config, transport, IngestionConfig(), source_router=router), transport


def fetched_cells(tasks, results):
    assert all(result.status is BackfillStatus.COMPLETED for result in results), [r.errors for r in results]
    return {(task.interval, bar.open_time) for task, result in zip(tasks, results) for bar in result.bars}


def rest_cells(transport):
    cells = set()
    for call in transport.calls:
        width = WIDTHS[call.descriptor.interval]
        first = -(-call.start_ms // width) * width
        cells.update((call.descriptor.interval, at) for at in list(range(first, call.end_ms + 1, width))[:call.limit])
    return cells


@pytest.mark.parametrize("seed", [0, 8])
def test_the_router_imports_exactly_the_planned_objects(tmp_path, monkeypatch, seed):
    chunks = planned_chunks(tmp_path, monkeypatch, seed)
    assert chunks and any(listed(plan) for _, _, plan in chunks)
    monkeypatch.setattr("app.data_engine.backfill.source_router.time.time", lambda: NOW / 1000)

    async def run():
        http = ArchiveHttp()
        router, fetcher, _ = router_and_fetcher(tmp_path, http)
        try:
            for start, stop, plan in chunks:
                # Unplanned tasks (another symbol) routed in the same call keep today's choice.
                plain = [replace(task, symbol="ETHUSDT", metadata={key: value for key, value in task.metadata.items()
                                                                   if key != PLANNED_OBJECTS_KEY})
                         for task in plan.tasks]
                http.add(refs_for(plan.tasks).values())
                http.add(refs_for(plain).values())
                alone = await router.prepare(plain)
                together = await router.prepare([*plan.tasks, *plain])
                for task in plain:
                    assert together.refs_for(task) == alone.refs_for(task)

                route = await router.prepare(plan.tasks)
                owners = {}
                for task in plan.tasks:
                    keys = set(task.metadata[PLANNED_OBJECTS_KEY])
                    refs = route.refs_for(task)
                    assert {ref.object_key for ref in refs} == keys
                    for ref in refs:
                        assert start <= ref.start_ms and ref.end_ms < stop
                        if route.owns_object(task, ref):
                            assert ref.object_key not in owners
                            owners[ref.object_key] = task.task_key
                assert set(owners) == listed(plan)
                assert not route.deferred_prefetch

                results = await fetcher.fetch(plan.tasks)
                assert fetched_cells(plan.tasks, results) == written_cells(plan)
                imported = [receipt["object_key"] for result in results
                            for receipt in result.metadata.get("archive_objects", ())]
                assert sorted(imported) == sorted(listed(plan))
        finally:
            await router.close()
    asyncio.run(run())


@pytest.mark.parametrize("seed", [0, 8])
def test_a_planned_object_that_fails_to_download_arrives_whole_over_rest(tmp_path, monkeypatch, seed):
    chunks = planned_chunks(tmp_path, monkeypatch, seed)
    monkeypatch.setattr("app.data_engine.backfill.source_router.time.time", lambda: NOW / 1000)
    start, stop, plan = next(chunk for chunk in chunks if listed(chunk[2]))
    refs = refs_for(plan.tasks)
    lost = refs[sorted(listed(plan))[0]]

    async def run():
        http = ArchiveHttp(missing={lost.expected_filename})
        http.add(refs.values())
        router, fetcher, transport = router_and_fetcher(tmp_path, http)
        try:
            results = await fetcher.fetch(plan.tasks)
            assert fetched_cells(plan.tasks, results) == written_cells(plan)
            width = WIDTHS[lost.interval]
            whole = {(lost.interval, at) for at in range(lost.start_ms, lost.end_ms + 1, width)}
            assert whole <= rest_cells(transport)
            assert lost.expected_filename in http.downloads
        finally:
            await router.close()
    asyncio.run(run())


def test_a_planned_object_absent_from_the_catalog_arrives_whole_over_rest(tmp_path, monkeypatch):
    chunks = planned_chunks(tmp_path, monkeypatch, 8)
    monkeypatch.setattr("app.data_engine.backfill.source_router.time.time", lambda: NOW / 1000)
    start, stop, plan = next(chunk for chunk in chunks if listed(chunk[2]))
    refs = refs_for(plan.tasks)
    lost = refs[sorted(listed(plan))[-1]]
    original = BinanceKlineArchiveProvider.plan_objects

    def plan_objects(self, **kwargs):
        return [ref for ref in original(self, **kwargs) if ref.object_key != lost.object_key]
    monkeypatch.setattr(BinanceKlineArchiveProvider, "plan_objects", plan_objects)

    async def run():
        http = ArchiveHttp()
        http.add(refs.values())
        router, fetcher, transport = router_and_fetcher(tmp_path, http)
        try:
            route = await router.prepare(plan.tasks)
            assert not any(ref.object_key == lost.object_key for task in plan.tasks for ref in route.refs_for(task))
            assert router.snapshot()["metrics"]["counters"]["archive_planned_object_rest_fallbacks"] == 1
            results = await fetcher.fetch(plan.tasks)
            assert fetched_cells(plan.tasks, results) == written_cells(plan)
            width = WIDTHS[lost.interval]
            assert {(lost.interval, at) for at in range(lost.start_ms, lost.end_ms + 1, width)} <= rest_cells(transport)
            assert lost.expected_filename not in http.downloads
        finally:
            await router.close()
    asyncio.run(run())


def window_items(windows):
    return {(window.interval, window.start_ms, window.end_ms, window.archive) for window in windows}


@pytest.mark.parametrize("seed", [0, 5, 8])
def test_the_plans_own_write_windows_are_what_routing_reports(tmp_path, monkeypatch, seed):
    chunks = planned_chunks(tmp_path, monkeypatch, seed)
    monkeypatch.setattr("app.data_engine.backfill.source_router.time.time", lambda: NOW / 1000)
    manager = manager_for(tmp_path / "fence.sqlite", {}, monkeypatch)
    store = manager.query_engine.storage.revision_store

    async def run():
        router, _, _ = router_and_fetcher(tmp_path, ArchiveHttp())
        try:
            for start, stop, plan in chunks:
                planned = planned_route_windows(plan.tasks)
                routed = planned_write_windows(plan.tasks, await router.prepare(plan.tasks))
                assert window_items(routed) == window_items(planned)
                assert {(w.start_ms, w.end_ms) for w in planned if w.archive} == {
                    (ref.start_ms, ref.end_ms) for key, ref in refs_for(plan.tasks).items() if key in listed(plan)}

                # The engine captures the plan's windows before fetching; the
                # fetcher's capture after routing then adds no view.
                scope = Acquisition(store.head())
                capture_planned_write_views(store, scope, planned)
                assert len(scope.native_history_views) == len(window_items(planned))
                captured = list(scope.native_history_views)
                capture_planned_write_views(store, scope, routed)
                assert scope.native_history_views == captured
        finally:
            await router.close()
    try:
        asyncio.run(run())
    finally:
        asyncio.run(manager.shutdown())


def test_routing_around_a_missing_object_needs_no_view_the_plan_lacks(tmp_path, monkeypatch):
    chunks = planned_chunks(tmp_path, monkeypatch, 8)
    monkeypatch.setattr("app.data_engine.backfill.source_router.time.time", lambda: NOW / 1000)
    start, stop, plan = next(chunk for chunk in chunks if listed(chunk[2]))
    lost = sorted(listed(plan))[0]
    original = BinanceKlineArchiveProvider.plan_objects
    monkeypatch.setattr(BinanceKlineArchiveProvider, "plan_objects", lambda self, **kwargs: [
        ref for ref in original(self, **kwargs) if ref.object_key != lost])

    async def run():
        router, _, _ = router_and_fetcher(tmp_path, ArchiveHttp())
        try:
            routed = planned_write_windows(plan.tasks, await router.prepare(plan.tasks))
            assert window_items(routed) < window_items(planned_route_windows(plan.tasks))
        finally:
            await router.close()
    asyncio.run(run())


def test_a_cold_wide_chart_captures_its_plans_writes_before_routing(tmp_path, monkeypatch):
    """Two adjacent route-aware chunks through the real coordinator, engine, router and storage."""
    import app.data_engine.backfill as engine_module
    from app.core import config as core_config
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
    from app.data_engine.data_manager.config import DataManagerConfig
    from app.data_engine.storage import klines_repo
    from app.data_engine.storage.gap_ledger import GapLedger
    from app.data_engine.storage.revisions import _acquisition
    from tests.test_mixed_routes import CONTRACT, TARGETS, WIDTH

    monkeypatch.setattr(mixed_routes, "ROUTE_AWARE", True)
    database = tmp_path / "chart.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", database)
    klines_repo.init_klines_storage()
    config = DataManagerConfig()
    config.query.auto_backfill = False
    dm = DataManager(config)
    storage = klines_repo.KlinesRepoAdapter()
    dm.set_storage(storage)
    engine = engine_for(dm.query_engine)
    engine.config.fetch_binance_futures_rate_limit_delay = 0
    http = ArchiveHttp()
    first, stop = CHUNKS[0][0], CHUNKS[1][1]
    provider = BinanceKlineArchiveProvider()
    for interval in ("1m", "1h", "1d"):
        http.add(provider.plan_objects(market_type="futures", symbol="BTCUSDT", interval=interval,
                                       start_ms=first, end_ms=stop - 1, now_ms=NOW))
    router, fetcher, transport = router_and_fetcher(tmp_path, http)
    engine._fetcher = fetcher

    captures = {}
    original = engine_module.prepare_planned_write_views

    async def spy(storage_, windows):
        scope = _acquisition.get()
        before = len(scope.native_history_views)
        await original(storage_, windows)
        captures.setdefault(id(scope), []).append((window_items(windows), len(scope.native_history_views) - before,
                                                   any(PLANNED_OBJECTS_KEY in w.metadata for w in windows)))
    monkeypatch.setattr(engine_module, "prepare_planned_write_views", spy)

    async def run():
        coordinator = BackfillCoordinator(storage=storage, bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.emit_event, source_available=dm.source_storage_available, engine=engine,
            loop=asyncio.get_running_loop(), gap_ledger=GapLedger(database), max_concurrency=0, chunk_bars=1000)
        try:
            request = coordinator.request(RepairRequest("BTCUSDT", "10007m", first, stop - 1, market_type="futures",
                reason="initial_history", requester="klines_history",
                metadata={"required_history_composition": CONTRACT, "history_calendar_id": "crypto.24x7.utc"}))
            outcome = await asyncio.wait_for(coordinator.wait_for_request(request), timeout=120)
            result = dm.query("BTCUSDT", "10007m", start_ms=first, end_ms=stop - 1, limit=2 * TARGETS,
                              market_type="futures", auto_backfill=False, min_revision=storage.revision_store.head())
            return outcome, result
        finally:
            await coordinator.shutdown()
            await router.close()
            await dm.shutdown()
    outcome, result = asyncio.run(run())

    assert outcome.verified_contiguous, outcome.error
    assert result.complete and len(result.bars) == 2 * TARGETS
    # One acquisition per chunk attempt: the plan's capture, then routing's.
    # Each chunk succeeds on its first attempt. Planned as today, both end
    # PARTIAL and run again: finer rows their imported objects write lie under
    # coarse spans the plan kept, which then "lack trusted composition coverage".
    runs = list(captures.values())
    assert len(runs) == 2 and all(flag for calls in runs for _, _, flag in calls)
    for (before, added, _), *after in runs:
        assert added == len(before) and after
        for items, added_after, _ in after:
            assert items <= before and added_after == 0
    assert http.downloads


def test_a_planned_daily_object_split_across_tasks_is_imported_once(tmp_path, monkeypatch):
    """A catalog lists a daily object only for a range holding the whole day, up to its last millisecond."""
    from datetime import datetime, timezone
    from app.data_engine.backfill.models import BackfillTask
    monkeypatch.setattr("app.data_engine.backfill.source_router.time.time", lambda: NOW / 1000)
    day = int(datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp() * 1000)
    minute = WIDTHS["1m"]
    ref = next(ref for ref in BinanceKlineArchiveProvider().plan_objects(
        market_type="futures", symbol="BTCUSDT", interval="1m", start_ms=day, end_ms=day + 1440 * minute - 1,
        now_ms=NOW) if ref.period == "2026-11-06")
    metadata = {"custom_interval": "10007m", "history_composition_contract": "binance.usdm.trade-klines/base-utc/1",
                "requester": "klines_history", PLANNED_OBJECTS_KEY: [ref.object_key]}
    tasks = [BackfillTask("BTCUSDT", "1m", lo, hi, estimated_bars=(hi - lo) // minute + 1, exchange="binance",
                          market_type="futures", metadata=dict(metadata))
             for lo, hi in ((day, day + 999 * minute), (day + 1000 * minute, day + 1439 * minute))]

    async def run():
        http = ArchiveHttp()
        http.add([ref])
        router, _, _ = router_and_fetcher(tmp_path, http)
        try:
            route = await router.prepare(tasks)
            assert [route.refs_for(task) for task in tasks] == [(ref,), (ref,)]
            assert route.owns_object(tasks[0], ref) and not route.owns_object(tasks[1], ref)
            assert router.snapshot()["metrics"]["counters"].get("archive_planned_object_rest_fallbacks", 0) == 0
        finally:
            await router.close()
    asyncio.run(run())


def test_a_planned_object_whose_tasks_were_trimmed_is_fetched_only_where_they_remain(tmp_path, monkeypatch):
    """The engine reuses committed minutes and trims 1m tasks; the router then imports nothing over them."""
    from datetime import datetime, timezone
    from app.data_engine.backfill.models import BackfillTask
    monkeypatch.setattr("app.data_engine.backfill.source_router.time.time", lambda: NOW / 1000)
    day = int(datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp() * 1000)
    minute = WIDTHS["1m"]
    ref = next(ref for ref in BinanceKlineArchiveProvider().plan_objects(
        market_type="futures", symbol="BTCUSDT", interval="1m", start_ms=day, end_ms=day + 1440 * minute - 1,
        now_ms=NOW) if ref.period == "2026-11-06")
    metadata = {"custom_interval": "10007m", "history_composition_contract": "binance.usdm.trade-klines/base-utc/1",
                "requester": "klines_history", PLANNED_OBJECTS_KEY: [ref.object_key]}
    # The middle of the day is already stored: both ends remain.
    tasks = [BackfillTask("BTCUSDT", "1m", lo, hi, estimated_bars=(hi - lo) // minute + 1, exchange="binance",
                          market_type="futures", metadata=dict(metadata))
             for lo, hi in ((day, day + 299 * minute), (day + 1000 * minute, day + 1439 * minute))]

    async def run():
        http = ArchiveHttp()
        http.add([ref])
        router, fetcher, transport = router_and_fetcher(tmp_path, http)
        try:
            route = await router.prepare(tasks)
            assert [route.refs_for(task) for task in tasks] == [(), ()]
            counters = router.snapshot()["metrics"]["counters"]
            assert counters["archive_planned_object_partial"] == 1
            results = await fetcher.fetch(tasks)
            assert fetched_cells(tasks, results) == {("1m", at) for task in tasks
                                                     for at in range(task.start_ms, task.end_ms + 1, minute)}
            assert not http.downloads
        finally:
            await router.close()
    asyncio.run(run())
