"""A composed page survives unrelated writes; changes inside it are never published.

Each batch of targets reads inside its own B130 view and proves its read extent
unchanged since the query's floor. The page is then persisted and adopted by a
range proof, as a backfill reduction is, instead of requiring every series of
the family (including the live minute) to stay unchanged throughout.

These tests check that this publishes exactly what one view at the floor
publishes, survives a write outside the page, and never publishes, persists or
caches a page whose inputs changed inside it.
"""
from __future__ import annotations

import asyncio
import random
import threading

import pytest

from app.data_engine.data_manager import mixed_query
from app.data_engine.data_manager.mixed_precedence import MixedPrecedence
from app.data_engine.storage import klines_repo
from app.data_engine.storage.mixed_history_fence import (
    capture_read_computation, computation_scope, matching_computation)
from app.data_engine.storage.revisions import Acquisition, series_values
from tests.test_mixed_history_session import CONTRACT, DAY, MINUTE, TARGET_WIDTH, bar, history, manager_for, outcome

TARGETS = 6
STOP = TARGETS * TARGET_WIDTH


def query(manager):
    return manager.query_composed("BTCUSDT", "10007m", start_ms=0, end_ms=STOP - 1, limit=TARGETS,
        market_type="futures", composition_contract=CONTRACT,
        min_revision=manager.query_engine.storage.revision_store.head())


def published(result, manager):
    bars = [(b.time, b.open, b.high, b.low, b.close, b.volume, b.quote_volume, b.trades,
             b.taker_buy_base, b.taker_buy_quote, b.trusted_final) for b in result.bars]
    stored = manager.query_engine.storage.count_bars("BTCUSDT", "10007m", 0, STOP - 1, market_type="futures")
    return bars, result.complete, result.history_state, stored


def configure(monkeypatch, batched):
    monkeypatch.setattr(mixed_query, "BATCH_VIEWS", batched)
    monkeypatch.setattr(mixed_query, "READ_PROOF", batched)
    # Several batches in a six-target page.
    monkeypatch.setattr(mixed_query, "BATCH_TARGETS", 2)


def write_during(monkeypatch, at_call, write):
    """Another writer commits while the ``at_call``-th batch is inside its view.

    It runs on its own thread, outside the query's acquisition scope, as the
    live stream and backfill jobs do. (On the query's thread the write would
    join that scope and be accepted as the query's own.)
    """
    calls = []
    original = MixedPrecedence.prepare

    def prepare(self, opens, width):
        calls.append(None)
        if len(calls) == at_call:
            failures = []
            def run():
                try:
                    write()
                except BaseException as exc:  # Surface it on the query thread.
                    failures.append(exc)
            writer = threading.Thread(target=run)
            writer.start()
            writer.join()
            if failures:
                raise failures[0]
        return original(self, opens, width)

    monkeypatch.setattr(MixedPrecedence, "prepare", prepare)
    return calls


def reference(tmp_path, monkeypatch, rows, name="reference"):
    configure(monkeypatch, False)
    manager = manager_for(tmp_path / f"{name}.sqlite", rows, monkeypatch)
    try:
        return published(query(manager), manager)
    finally:
        asyncio.run(manager.shutdown())


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("fault", ["none", "missing_minute"])
def test_batched_views_publish_exactly_what_one_view_at_the_floor_does(tmp_path, monkeypatch, seed, fault):
    rows = history(seed, TARGETS)
    if fault == "missing_minute":
        minutes = rows[("1m", "backfill")]
        minutes.pop(random.Random(seed).randrange(len(minutes)))
    results = {}
    for batched in (False, True):
        configure(monkeypatch, batched)
        manager = manager_for(tmp_path / f"{batched}.sqlite", rows, monkeypatch)
        try:
            results[batched] = outcome(query(manager), manager, STOP)
        finally:
            asyncio.run(manager.shutdown())
        assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
    assert results[True] == results[False]


def later_minute():
    """A closed minute after the page, as the live stream or a short chart writes it."""
    klines_repo.upsert_klines("BTCUSDT", "1m", [bar(STOP + 5 * MINUTE, MINUTE, random.Random(5))],
                              source="backfill", market_type="futures")


@pytest.mark.parametrize("at_call", [1, 2, 3])
def test_a_write_after_the_page_neither_discards_nor_blocks_its_publication(tmp_path, monkeypatch, at_call):
    rows = history(3, TARGETS)
    expected = reference(tmp_path, monkeypatch, rows)
    assert expected[2] == "ready" and expected[3] == TARGETS

    configure(monkeypatch, True)
    manager = manager_for(tmp_path / "batched.sqlite", rows, monkeypatch)
    write_during(monkeypatch, at_call, later_minute)
    try:
        result = query(manager)
        assert published(result, manager) == expected
        # The disturbed batch was composed again; nothing else was redone.
        assert result.metadata.get("mixed_view_retries") == 1
    finally:
        asyncio.run(manager.shutdown())


def test_without_batched_views_a_write_after_the_page_discards_it(tmp_path, monkeypatch):
    """What the batches replace: the whole page was lost to the live minute."""
    rows = history(3, TARGETS)
    configure(monkeypatch, False)
    manager = manager_for(tmp_path / "single.sqlite", rows, monkeypatch)
    write_during(monkeypatch, 2, later_minute)
    try:
        bars, complete, state, stored = published(query(manager), manager)
        assert (bars, complete, state, stored) == ([], False, "pending", 0)
    finally:
        asyncio.run(manager.shutdown())


def changed_minute(rows, lo, hi):
    """A different value for a stored minute that a target in [lo, hi) consumes."""
    candidates = [row for row in rows[("1m", "backfill")] if lo <= row["open_time"] < hi]
    assert candidates
    row = random.Random(lo).choice(candidates)
    return {**row, "close": row["close"] + 0.5, "high": max(row["high"], row["close"] + 0.5)}


@pytest.mark.parametrize("composed", ["earlier_batch", "current_batch"])
def test_a_change_inside_the_page_is_never_published_persisted_or_cached(tmp_path, monkeypatch, composed):
    rows = history(4, TARGETS)
    batch = 2 * TARGET_WIDTH
    # Written while the second batch is open: inside the first (already
    # composed) batch, or inside the second one itself.
    # An earlier batch's change stays clear of the later batches' read extent
    # (they start up to one day early), so only the page's proof can catch it.
    lo, hi = (0, batch - 2 * DAY) if composed == "earlier_batch" else (batch, 2 * batch)
    changed = changed_minute(rows, lo, hi)
    changed_rows = {**rows, ("1m", "backfill"): [changed if row["open_time"] == changed["open_time"] else row
                                                 for row in rows[("1m", "backfill")]]}
    expected_after = reference(tmp_path, monkeypatch, changed_rows, "changed")

    configure(monkeypatch, True)
    manager = manager_for(tmp_path / "batched.sqlite", rows, monkeypatch)
    write_during(monkeypatch, 2, lambda: klines_repo.upsert_klines(
        "BTCUSDT", "1m", [changed], source="backfill", market_type="futures"))
    try:
        bars, complete, state, stored = published(query(manager), manager)
        assert (bars, complete, state, stored) == ([], False, "pending", 0)
        # The next read (the write happens only once) composes the changed
        # inputs: nothing stale was kept.
        assert published(query(manager), manager) == expected_after
    finally:
        asyncio.run(manager.shutdown())


def test_a_read_proof_grants_only_its_own_scope_and_never_backfill_captures(tmp_path, monkeypatch):
    manager = manager_for(tmp_path / "proof.sqlite", history(2, 2), monkeypatch)
    try:
        store = manager.query_engine.storage.revision_store
        scope = Acquisition(store.head())
        key = series_values("BTCUSDT", "10007m", "binance", "futures")
        dependencies = (series_values("BTCUSDT", "1m", "binance", "futures"),)
        computation = capture_read_computation(store, scope, key, dependencies, 0, TARGET_WIDTH,
                                               TARGET_WIDTH, scope.revision)
        assert computation is not None and scope.read_targets == [computation.target]
        # Backfill captures and native writes consult only mixed_target_views.
        assert scope.mixed_target_views == []
        rows = [{"open_time": 0, "close_time": TARGET_WIDTH - 1}]
        assert matching_computation(scope, key, rows, "backfill_aggregated") is None
        with computation_scope((computation,)):
            assert matching_computation(scope, key, rows, "backfill_aggregated") is computation
            assert matching_computation(Acquisition(store.head()), key, rows, "backfill_aggregated") is None
            assert matching_computation(scope, key, rows, "backfill") is None
        # Phase-shifted or oversized pages have no proof and keep the strict path.
        assert capture_read_computation(store, scope, key, dependencies, MINUTE, MINUTE + TARGET_WIDTH,
                                        TARGET_WIDTH, scope.revision) is None
        assert capture_read_computation(store, scope, key, dependencies, 0, 512 * TARGET_WIDTH,
                                        TARGET_WIDTH, scope.revision) is None
    finally:
        asyncio.run(manager.shutdown())


def test_without_a_query_scope_every_batch_is_still_read_as_of_the_floor(tmp_path, monkeypatch):
    """No revision consumer: no publication proof, so each batch's own check is the guard."""
    from app.data_engine.data_manager.models import SeriesKey
    from app.data_engine.memory_budget import budgeted_query
    from app.data_engine.storage.revisions import StaleAcquisition, current_acquisition
    rows = history(4, TARGETS)
    batch = 2 * TARGET_WIDTH
    changed = changed_minute(rows, batch, 2 * batch)
    configure(monkeypatch, True)
    manager = manager_for(tmp_path / "unscoped.sqlite", rows, monkeypatch)
    write_during(monkeypatch, 2, lambda: klines_repo.upsert_klines(
        "BTCUSDT", "1m", [changed], source="backfill", market_type="futures"))
    try:
        assert current_acquisition() is None
        compose = budgeted_query(manager.query_engine._query_closed_mixed)
        with pytest.raises(StaleAcquisition):
            compose(SeriesKey("BTCUSDT", "10007m", market_type="futures"),
                    start_ms=0, end_ms=STOP - 1, limit=TARGETS, report={}, composition_contract=CONTRACT)
    finally:
        asyncio.run(manager.shutdown())
