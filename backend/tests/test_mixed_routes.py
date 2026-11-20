"""Route-aware mixed plans write only their own targets and compose without a post-write rejection.

Two adjacent 16-target 10007m chunks are planned with the real Binance archive
catalog over a random stored state (cold, or partial stored 1m/1h/1d runs). Each
plan names what it writes: whole archive objects and REST windows. The tests
check that:

- every row a plan writes lies inside that chunk's own target range, so the
  two chunks never write the same row;
- after writing exactly those rows, ``checked_mixed_windows`` keeps every
  derive window (no object row sits on a coarse span the plan kept);
- every target of both chunks composes completely through the real reader.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

import pytest

from app.data_engine.backfill import mixed_routes
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.mixed_plan import build_mixed_backfill_plan, checked_mixed_windows
from app.data_engine.backfill.models import GapInfo, GapType
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.interval_resolution import IntervalResolver
from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import ensure_acquisition
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_session import CONTRACT, MINUTE, bar, manager_for

HOUR, DAY = 60 * MINUTE, 1440 * MINUTE
WIDTH = 10007 * MINUTE
TARGETS = 16
NOW = int(datetime(2026, 11, 20, tzinfo=timezone.utc).timestamp() * 1000)
FIRST = int(datetime(2025, 2, 1, tzinfo=timezone.utc).timestamp() * 1000) // WIDTH * WIDTH
CHUNKS = ((FIRST, FIRST + TARGETS * WIDTH), (FIRST + TARGETS * WIDTH, FIRST + 2 * TARGETS * WIDTH))
WIDTHS = {"1m": MINUTE, "3m": 3 * MINUTE, "5m": 5 * MINUTE, "15m": 15 * MINUTE, "1h": HOUR,
          "4h": 4 * HOUR, "1d": DAY}


def catalog():
    provider = BinanceKlineArchiveProvider()
    def plan_objects(symbol, interval, start_ms, end_ms, now_ms):
        return provider.plan_objects(market_type="futures", symbol=symbol, interval=interval,
                                     start_ms=start_ms, end_ms=end_ms, now_ms=NOW)
    cfg = BackfillConfig()
    return (plan_objects, provider.capabilities("futures").rest_page_size,
            max(1, cfg.history_archive_min_rest_pages), cfg.fetch_batch_size)


def stored_rows(rng, cold):
    """Cold, or grid-aligned runs of stored 1m, 1h and 1d (sometimes a whole month of 1h)."""
    rows = {}
    if cold:
        return rows
    lo, hi = CHUNKS[0][0], CHUNKS[1][1]
    for interval, count, longest in (("1m", rng.randrange(0, 3), 90), ("1h", rng.randrange(1, 6), 120),
                                     ("1d", rng.randrange(0, 4), 12)):
        width = WIDTHS[interval]
        for _ in range(count):
            start = -(-lo // width) * width + rng.randrange(0, (hi - lo) // width - 1) * width
            rows.setdefault((interval, "backfill"), []).extend(
                bar(at, width, rng) for at in range(start, min(hi, start + rng.randrange(1, longest) * width), width))
    if rng.random() < 0.5:
        month = int(datetime(2025, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
        stop = int(datetime(2025, 5, 1, tzinfo=timezone.utc).timestamp() * 1000)
        rows.setdefault(("1h", "backfill"), []).extend(bar(at, HOUR, rng) for at in range(month, stop, HOUR))
    for key, items in rows.items():
        unique = {item["open_time"]: item for item in items}
        rows[key] = [unique[at] for at in sorted(unique)]
    return rows


def plan_chunk(manager, engine, start, stop):
    gap = GapInfo("BTCUSDT", "10007m", GapType.HEAD, start, stop - WIDTH, (stop - start) // WIDTH,
                  market_type="futures")
    report = {}

    async def run():
        with ensure_acquisition(manager.query_engine.storage.revision_store.head()):
            return await build_mixed_backfill_plan(engine, [gap],
                {"required_history_composition": CONTRACT, "history_calendar_id": "crypto.24x7.utc"}, report)
    return asyncio.run(run()), report


def written_cells(plan):
    """(interval, open) of every row the plan writes: whole objects and REST windows."""
    cells = set()
    for task in plan.tasks:
        width = WIDTHS[task.interval]
        windows = (((task.start_ms, task.end_ms),) if task.metadata.get(mixed_routes.ROUTE_OBJECTS_KEY)
                   else task.metadata.get("mixed_fetch_windows", ((task.start_ms, task.end_ms),)))
        for lo, last in windows:
            cells.update((task.interval, at) for at in range(lo, last + 1, width))
    return cells


@pytest.mark.parametrize("seed", range(12))
def test_adjacent_route_aware_chunks_write_only_their_own_targets_and_compose(tmp_path, monkeypatch, seed):
    rng = random.Random(seed)
    monkeypatch.setattr(mixed_routes, "ROUTE_AWARE", True)
    monkeypatch.setattr(mixed_routes, "archive_catalog", lambda engine: catalog())
    monkeypatch.setattr("app.data_engine.backfill.mixed_plan.time.time", lambda: NOW / 1000)
    rows = stored_rows(rng, cold=seed < 3)
    manager = manager_for(tmp_path / "routes.sqlite", rows, monkeypatch)
    try:
        engine = engine_for(manager.query_engine)
        chunks, plans = [], []
        for start, stop in CHUNKS:
            plan, report = plan_chunk(manager, engine, start, stop)
            if plan is None:
                # Today's planner declined first (the scheduler splits such a
                # chunk); route-aware planning never ran.
                assert "mixed_route_aware" not in report and report.get("mixed_plan_fallback")
                continue
            assert report.get("mixed_route_aware") is True
            chunks.append((start, stop))
            plans.append(plan)
        assert plans
        cells = [written_cells(plan) for plan in plans]
        for (start, stop), chunk_cells in zip(chunks, cells):
            assert all(start <= at and at + WIDTHS[interval] <= stop for interval, at in chunk_cells)
        if len(cells) == 2:
            assert not cells[0] & cells[1]
        assert any(task.metadata.get(mixed_routes.ROUTE_OBJECTS_KEY) for plan in plans for task in plan.tasks)

        stored = {(interval, at) for (interval, _), items in rows.items() for at in (item["open_time"] for item in items)}
        writes = {}
        for interval, at in set().union(*cells) - stored:
            writes.setdefault(interval, []).append(bar(at, WIDTHS[interval], rng))
        for interval, items in writes.items():
            klines_repo.upsert_klines("BTCUSDT", interval, sorted(items, key=lambda item: item["open_time"]),
                                      source="backfill", market_type="futures")

        storage = engine._storage
        target = SeriesKey("BTCUSDT", "10007m", market_type="futures")
        policy = IntervalResolver().history_composition_routes(exchange="binance", market_type="futures",
                                                               interval="10007m")[0]
        for plan in plans:
            windows = [(task.interval, task.start_ms, task.end_ms, None) for task in plan.derived_source_windows]
            kept = asyncio.run(checked_mixed_windows(storage, target, policy, windows))
            assert len(kept) == len(windows)
        for start, stop in chunks:
            result = manager.query_composed("BTCUSDT", "10007m", start_ms=start, end_ms=stop - 1, limit=TARGETS,
                market_type="futures", composition_contract=CONTRACT,
                min_revision=manager.query_engine.storage.revision_store.head())
            assert result.complete and len(result.bars) == TARGETS, result.metadata.get("mixed_fallback_reason")
    finally:
        asyncio.run(manager.shutdown())


def test_without_the_flag_the_plan_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr("app.data_engine.backfill.mixed_plan.time.time", lambda: NOW / 1000)
    manager = manager_for(tmp_path / "plain.sqlite", {}, monkeypatch)
    try:
        engine = engine_for(manager.query_engine)
        plain, report = plan_chunk(manager, engine, *CHUNKS[0])
        assert "mixed_route_aware" not in report
        assert not any(task.metadata.get(mixed_routes.ROUTE_OBJECTS_KEY) for task in plain.tasks)
    finally:
        asyncio.run(manager.shutdown())
