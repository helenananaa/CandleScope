"""Repeated identical demand is merged without re-ranking; cold source choices are cached."""
from __future__ import annotations

import asyncio

from app.data_engine.backfill import cold_cover
from app.data_engine.data_manager.backfill_contracts import RepairOutcome, RepairRequest
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import FixedHistorySource
from tests.test_backfill_batch_ownership import scheduler_for

MINUTE = 60_000


def gap(interval, priority=None):
    return RepairRequest("BTCUSDT", interval, 0, 9 * MINUTE, market_type="futures", reason="visible_range_gap",
                         requester="klines_range", priority=priority)


def test_a_pending_request_merges_the_same_demand_again_without_re_ranking_it():
    async def run():
        release = asyncio.Event()
        async def execute(req):
            await release.wait()
            return RepairOutcome(request=req, status="completed")
        # One worker: the 1m repair runs, the 3m repair stays pending.
        scheduler = scheduler_for(execute, concurrency=1)
        scheduler.submit(gap("1m"))
        pending_id, _ = scheduler.submit(gap("3m"))
        await asyncio.sleep(0)
        # The first merge also records the request's latest-interest flag.
        scheduler.submit(gap("3m"))
        reranked = []
        original = scheduler._restore_remaining_interest
        scheduler._restore_remaining_interest = lambda state: (reranked.append(state), original(state))
        for _ in range(20):
            # A chart polling the same gap.
            assert scheduler.submit(gap("3m"))[0] == pending_id
        assert reranked == [] and scheduler.deduped == 21
        # New interest (a higher priority) is still applied to the pending chunks.
        scheduler.submit(gap("3m", priority=1))
        assert len(reranked) == 1
        state = scheduler._requests[pending_id]
        assert state.request.priority == 1
        assert all(scheduler._chunks[chunk_id].request.priority == 1 for chunk_id in state.chunk_ids)
        release.set()
        await scheduler.shutdown()
    asyncio.run(run())


def test_cold_source_choices_are_computed_once_per_identical_arguments(monkeypatch):
    target = SeriesKey("BTCUSDT", "10007m", market_type="futures")
    width = 10007 * MINUTE
    fields = frozenset({"open", "high", "low", "close", "volume"})
    sources = tuple(FixedHistorySource(SeriesKey("BTCUSDT", interval, market_type="futures"), step, 0,
                                       ((0, 4 * width),), fields, "contract")
                    for interval, step in (("1m", MINUTE), ("1h", 60 * MINUTE), ("1d", 1440 * MINUTE)))
    options = dict(required_fields=fields, target_width=width, base_width=0, page_size=1500, task_page_size=1500,
                   max_rows=100_000, max_tasks=1024, max_positions=131_072)
    calls = []
    original = cold_cover._choose_cold_sources
    monkeypatch.setattr(cold_cover, "_choose_cold_sources", lambda *a, **k: (calls.append(a), original(*a, **k))[1])
    cold_cover._cached_choice.cache_clear()
    first = cold_cover.choose_cold_sources(target, 0, 4 * width, sources, **options)
    again = cold_cover.choose_cold_sources(target, 0, 4 * width, sources, **options)
    assert again is first and len(calls) == 1
    # The same sources as a list are the same choice; another range is another.
    assert cold_cover.choose_cold_sources(target, 0, 4 * width, list(sources), **options) is first
    cold_cover.choose_cold_sources(target, 0, 2 * width, sources, **options)
    assert len(calls) == 2
