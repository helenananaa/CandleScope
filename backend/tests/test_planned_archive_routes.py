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
  plan's.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import replace

import pytest

from app.data_engine.backfill import mixed_routes
from app.data_engine.backfill.archive_cache import HistoricalArchiveCache
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillStatus
from app.data_engine.backfill.source_router import PLANNED_OBJECTS_KEY, HistoricalSourceRouter
from app.data_engine.ingestion.config import IngestionConfig
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

import hashlib


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
                                         start_ms=task.start_ms, end_ms=task.end_ms, now_ms=NOW):
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
