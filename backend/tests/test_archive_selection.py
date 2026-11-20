"""select_archive_objects is the router's archive-or-REST choice, unchanged, as a pure function.

Each case builds a run of tasks the way the mixed planner and the scheduler do
(composed edge windows, bounded pages, plain native pages), lists the real
provider's catalog for the run, and compares the function with the chain the
router ran inline before (_filter_daily_candidates, then the Binance USD-M
budget, then the composed daily REST preference).
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from app.data_engine.backfill.models import BackfillTask
from app.data_engine.backfill.source_router import (
    _archive_decision_range, _bounded_usdm_archive_candidates, _ceil_div, _composed_group_key,
    _filter_daily_candidates, _task_runs, select_archive_objects)
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider

CONTRACT = "binance.usdm.trade-klines/base-utc/1"
MINUTE, HOUR, DAY = 60_000, 3_600_000, 86_400_000
NOW = int(datetime(2026, 11, 20, tzinfo=timezone.utc).timestamp() * 1000)
PAGE, MINIMUM_PAGES, BATCH = 1500, 2, 1000
WIDTHS = {"1m": MINUTE, "1h": HOUR, "1d": DAY}


def inline_choice(candidates, run, exchange, market_type, interval, start, end):
    """The router's choice as it was written inline in prepare()."""
    planned = len(candidates)
    candidates = _filter_daily_candidates(candidates, range_start_ms=start, range_end_ms=end, interval=interval,
                                          rest_page_size=PAGE, minimum_pages=MINIMUM_PAGES, tasks=run)
    threshold = len(candidates)
    rejected = {}
    if exchange == "binance" and market_type == "futures":
        candidates = _bounded_usdm_archive_candidates(candidates, run, interval, rejected=rejected)
    preferred = bool(candidates and exchange == "binance" and market_type == "futures" and interval == "1d"
                     and all(_composed_group_key(task) for task in run)
                     and (page := min(BATCH, PAGE)) > 0
                     and sum(_ceil_div((task.end_ms - task.start_ms) // DAY + 1, page) for task in run)
                     <= len(candidates))
    return planned, threshold, [ref.object_key for ref in candidates], rejected, preferred


def tasks_for(rng, interval, kind, market_type="futures"):
    width = WIDTHS[interval]
    span = rng.choice([20, 200, 2000]) * width
    first = (NOW - rng.randrange(40, 900) * DAY) // width * width
    out = []
    at = first
    for _ in range(rng.randrange(1, 6)):
        length = rng.randrange(1, 60) * width
        metadata = {"requester": "klines_history", "reason": "initial_history",
                    "ledger_range": {"start_ms": first, "end_ms": first + span}}
        if kind == "composed":
            metadata.update(custom_interval="10007m", history_composition_contract=CONTRACT,
                            mixed_fetch_windows=[(at, at + length - width)])
        elif kind == "bounded":
            metadata.update(bounded_history_batch_contract=CONTRACT)
        out.append(BackfillTask(symbol="BTCUSDT", interval=interval, start_ms=at, end_ms=at + length - width,
                                estimated_bars=length // width, exchange="binance", market_type=market_type,
                                metadata=metadata))
        at += length + rng.randrange(1, 9) * 7 * DAY // width * width
    return out


@pytest.mark.parametrize("seed", range(60))
def test_the_extracted_choice_equals_the_router_chain_it_replaced(seed):
    rng = random.Random(seed)
    interval = rng.choice(["1m", "1h", "1d"])
    kind = rng.choice(["composed", "bounded", "native"])
    market_type = rng.choice(["futures", "futures", "spot"])
    provider = BinanceKlineArchiveProvider()
    for run in _task_runs(tasks_for(rng, interval, kind, market_type), interval):
        start, end = _archive_decision_range(run)
        candidates = provider.plan_objects(market_type=market_type, symbol="BTCUSDT", interval=interval,
                                           start_ms=start, end_ms=end, now_ms=NOW)
        selection = select_archive_objects(candidates, run, exchange="binance", market_type=market_type,
            interval=interval, route_start_ms=start, route_end_ms=end, rest_page_size=PAGE,
            minimum_pages=MINIMUM_PAGES, fetch_batch_size=BATCH)
        got = (selection.planned, selection.above_threshold, [ref.object_key for ref in selection.eligible],
               selection.rejected, selection.rest_preferred)
        assert got == inline_choice(candidates, run, "binance", market_type, interval, start, end)
        assert selection.budget_checked == (market_type == "futures")
        assert selection.objects == (() if selection.rest_preferred else selection.eligible)


def test_the_choice_needs_no_cache_network_or_router():
    """The planner can call it with nothing but the catalog and its tasks."""
    rng = random.Random(7)
    run = tasks_for(rng, "1h", "composed")
    start, end = _archive_decision_range(run)
    candidates = BinanceKlineArchiveProvider().plan_objects(market_type="futures", symbol="BTCUSDT", interval="1h",
                                                            start_ms=start, end_ms=end, now_ms=NOW)
    first = select_archive_objects(candidates, run, exchange="binance", market_type="futures", interval="1h",
        route_start_ms=start, route_end_ms=end, rest_page_size=PAGE, minimum_pages=MINIMUM_PAGES,
        fetch_batch_size=BATCH)
    again = select_archive_objects(candidates, run, exchange="binance", market_type="futures", interval="1h",
        route_start_ms=start, route_end_ms=end, rest_page_size=PAGE, minimum_pages=MINIMUM_PAGES,
        fetch_batch_size=BATCH)
    assert first == again
