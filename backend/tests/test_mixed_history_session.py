"""A composed query's shared session must publish exactly what per-target views publish.

Each case seeds two identical databases and runs the same query once with
``SESSION_READS`` and once with the original one-view-per-target reads. The
published bars, their finality, completeness, fallback decisions and the
materialized rows must be identical.
"""
from __future__ import annotations

import asyncio
import random

import pytest

from app.core import config as core_config
from app.data_engine.data_manager import DataManager, mixed_query
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import FixedHistorySource
from app.data_engine.storage import klines_repo

MINUTE = 60_000
DAY = 1440 * MINUTE
CONTRACT = "binance.usdm.trade-klines/base-utc/1"
FIELDS = frozenset({"open", "high", "low", "close", "volume", "quote_volume", "trades",
                    "taker_buy_base", "taker_buy_quote"})
TARGET_WIDTH = 10007 * MINUTE
META_KEYS = ("mixed_fallback_reason", "mixed_accepted_rows", "mixed_fallbacks", "mixed_planned_rows",
             "target_materialized_written", "history_composition_deferred")


def bar(opened, width, rng):
    minutes = width // MINUTE
    base = 100 + rng.random()
    volume = minutes * (1 + rng.random())
    return dict(open_time=opened, close_time=opened + width - 1, open=base,
                high=base + 1 + rng.random() * 3, low=base - 1 - rng.random() * 2,
                close=base + rng.random() - 0.5, volume=volume, quote_volume=volume * base,
                trades=minutes * rng.randrange(1, 9), taker_buy_base=volume / 2,
                taker_buy_quote=volume * base / 2)


def _sources(stop):
    from dataclasses import replace as _replace
    from app.data_engine.interval_resolution import IntervalResolver
    target = SeriesKey("BTCUSDT", "10007m", market_type="futures")
    policy, routes, _ = IntervalResolver().history_composition_routes(
        exchange=target.exchange, market_type=target.market_type, interval=target.interval)
    return target, tuple(FixedHistorySource(_replace(target, interval=route.canonical_interval),
        route.spec.nominal_ms, 0, ((0, stop),), FIELDS, policy.contract_id) for route in routes)


def history(seed, targets):
    """Rows per (interval, source): each target's exact cover, then perturbed.

    The cover comes from the planner (as stored history would). A perturbation
    spoils one planned span (a missing, untrusted or field-incomplete row, or
    an unqualified finer 3m row inside it) and stores the planner's finer cover
    of that whole span, since a refinement replaces the entire span.
    """
    from app.data_engine.history.cover_plan import plan_fixed_range, plan_fixed_target
    rng = random.Random(seed)
    stop = targets * TARGET_WIDTH
    target, sources = _sources(stop)
    cells, spans = {}, []
    for opened in range(0, stop, TARGET_WIDTH):
        for span in plan_fixed_target(target, opened, opened + TARGET_WIDTH, sources).spans:
            spans.append(span)
            for at in range(span.start_ms, span.end_ms, span.source.width_ms):
                cells[(span.source.series.interval, at)] = (span.source.width_ms, "backfill")
    extra = []
    small = [span for span in spans if span.source.width_ms > MINUTE
             and (span.end_ms - span.start_ms) // span.source.width_ms <= 64]
    for span in rng.sample(small, min(len(small), rng.randrange(1, 5))):
        width = span.source.width_ms
        key = (span.source.series.interval, rng.randrange(span.start_ms, span.end_ms, width))
        kind = rng.choice(["missing", "untrusted", "incomplete", "finer_3m"])
        finer = tuple(source for source in sources if source.width_ms < width)
        if kind == "finer_3m":
            if width <= 3 * MINUTE or span.end_ms - span.start_ms > 4 * 60 * MINUTE:
                continue
            extra.append(("3m", 3 * MINUTE, key[1]))
            finer = tuple(source for source in sources if source.width_ms < 3 * MINUTE)
        elif kind == "missing":
            cells.pop(key, None)
        else:
            cells[key] = (width, "data_manager" if kind == "untrusted" else "incomplete")
        for part in plan_fixed_range(target, span.start_ms, span.end_ms, finer).spans:
            for opened in range(part.start_ms, part.end_ms, part.source.width_ms):
                cells.setdefault((part.source.series.interval, opened), (part.source.width_ms, "backfill"))
    rows = {}
    for (interval, opened), (width, source) in sorted(cells.items()):
        item = bar(opened, width, rng)
        if source == "incomplete":
            item["quote_volume"], source = None, "backfill"
        rows.setdefault((interval, source), []).append(item)
    for interval, width, opened in extra:
        rows.setdefault((interval, "backfill"), []).append(bar(opened, width, rng))
    return rows


def manager_for(path, rows, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    for (interval, source), items in sorted(rows.items()):
        klines_repo.upsert_klines("BTCUSDT", interval, items, source=source, market_type="futures")
    config = DataManagerConfig()
    config.query.auto_backfill = False
    manager = DataManager(config)
    manager.set_storage(klines_repo.KlinesRepoAdapter())
    return manager


def outcome(result, manager, stop):
    bars = [(b.time, b.open, b.high, b.low, b.close, b.volume, b.quote_volume, b.trades,
             b.taker_buy_base, b.taker_buy_quote, b.trusted_final) for b in result.bars]
    stored = manager.query_engine.storage.count_bars("BTCUSDT", "10007m", 0, stop - 1, market_type="futures")
    return (bars, result.complete, result.history_state,
            {key: result.metadata.get(key) for key in META_KEYS}, stored)


def run_both(tmp_path, monkeypatch, rows, query, *, warm=None):
    results = {}
    for session in (False, True):
        monkeypatch.setattr(mixed_query, "SESSION_READS", session)
        manager = manager_for(tmp_path / f"{session}.sqlite", rows, monkeypatch)
        try:
            if warm is not None:
                warm(manager)
            results[session] = query(manager)
        finally:
            asyncio.run(manager.shutdown())
        assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
    return results


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("fault", ["none", "missing_minute", "untrusted_coarse", "incomplete_coarse"])
def test_session_reads_publish_exactly_the_per_target_result(tmp_path, monkeypatch, seed, fault):
    targets = 6
    stop = targets * TARGET_WIDTH
    rows = history(seed, targets)
    choose = random.Random(seed)
    if fault == "missing_minute":
        # No finer source can replace a missing 1m row.
        minutes = rows[("1m", "backfill")]
        minutes.pop(choose.randrange(len(minutes)))
    elif fault != "none":
        # A coarse row read as untrusted or incomplete, with no finer data to
        # take precedence over it, leaves that target unavailable.
        interval = choose.choice([name for name, source in rows if source == "backfill" and name not in ("1m", "3m")])
        coarse = rows[(interval, "backfill")]
        item = coarse.pop(choose.randrange(len(coarse)))
        if fault == "untrusted_coarse":
            rows.setdefault((interval, "data_manager"), []).append(item)
        else:
            coarse.append({**item, "quote_volume": None})

    def query(manager):
        result = manager.query_composed("BTCUSDT", "10007m", start_ms=0, end_ms=stop - 1, limit=targets,
            market_type="futures", composition_contract=CONTRACT,
            min_revision=manager.query_engine.storage.revision_store.head())
        return outcome(result, manager, stop)

    results = run_both(tmp_path, monkeypatch, rows, query)
    assert results[True] == results[False]


def test_session_reads_reuse_resident_blocks_with_the_same_result(tmp_path, monkeypatch):
    targets = 3
    stop = targets * TARGET_WIDTH
    rows = history(101, targets)
    rows[("1d", "backfill")] = [bar(at, DAY, random.Random(at)) for at in range(0, stop, DAY)]

    def warm(manager):
        # A finished read leaves its 1d block summaries in the shared cache.
        source = FixedHistorySource(SeriesKey("BTCUSDT", "1d", market_type="futures"), DAY, 0,
                                    ((0, 6 * DAY),), FIELDS, CONTRACT)
        with manager.read_mixed_history_blocks(SeriesKey("BTCUSDT", "6d", market_type="futures"),
                                               0, 6 * DAY, (source,), required_fields=FIELDS):
            pass

    def query(manager):
        result = manager.query_composed("BTCUSDT", "10007m", start_ms=0, end_ms=stop - 1, limit=targets,
            market_type="futures", composition_contract=CONTRACT,
            min_revision=manager.query_engine.storage.revision_store.head())
        return outcome(result, manager, stop)

    results = run_both(tmp_path, monkeypatch, rows, query, warm=warm)
    assert results[True] == results[False]


def test_session_opens_no_view_or_page_reservation_per_target(tmp_path, monkeypatch):
    targets = 4
    stop = targets * TARGET_WIDTH
    rows = history(7, targets)
    monkeypatch.setattr(mixed_query, "SESSION_READS", True)
    manager = manager_for(tmp_path / "views.sqlite", rows, monkeypatch)
    blocks = manager.shared_blocks
    views = []
    original = blocks.view

    def counted(*args, **kwargs):
        views.append(args[0] if args else kwargs.get("series"))
        return original(*args, **kwargs)

    monkeypatch.setattr(blocks, "view", counted)
    try:
        result = manager.query_composed("BTCUSDT", "10007m", start_ms=0, end_ms=stop - 1, limit=targets,
            market_type="futures", composition_contract=CONTRACT,
            min_revision=manager.query_engine.storage.revision_store.head())
    finally:
        asyncio.run(manager.shutdown())
    assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
    if result.metadata.get("mixed_accepted_rows"):
        # The query's own view only: no per-target or per-page views.
        assert len(views) <= 2
