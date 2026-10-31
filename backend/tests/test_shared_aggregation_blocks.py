"""B130 ownership, races, bounded retention and reference semantic proofs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, CancelledError
from dataclasses import replace
import threading
import time

import pytest

from app.data_engine.aggregation.blocks import (
    BlockKey, BlockRevisionChanged, BlockUnavailable, SharedBlockManager,
)
from app.data_engine.aggregation.core import AcceptedComponent, InputRevision, summarize
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.memory_budget import MemoryBudget, MemoryBudgetExceeded


SOURCE = SeriesKey("BTCUSDT", "1d")


class Versions:
    domain = "test-source"

    def __init__(self):
        self.versions = {}
        self.changes = []
        self.reset = False
        self.fail = False

    def read(self, keys, *, acquired_at=None):
        if self.fail:
            raise OSError("revision read failed")
        revisions = tuple(InputRevision(k, self.domain, self.versions.get(k, 1)) for k in keys)
        changes, self.changes = tuple(self.changes), []
        reset, self.reset = self.reset, False
        return revisions, changes, reset

    def amend(self, key=SOURCE):
        self.versions[key] = self.versions.get(key, 1) + 1
        self.changes.append((key, self.domain))


def manager(**kwargs):
    capacity = kwargs.pop("max_bytes", 512 * 1024)
    budget = MemoryBudget(capacity)
    return SharedBlockManager(budget=budget, source=Versions(), max_bytes=capacity, **kwargs)


def key(index=0, source=SOURCE):
    return BlockKey(source, index * 2 * 86400000, (index + 1) * 2 * 86400000)


def build(view, block_key, volume=3):
    revision = next(r for r in view.revisions if r.series == block_key.series)
    bars = [BarData(time=t // 1000, open=2, high=4, low=1, close=3,
                    volume=volume, quote_volume=volume * 3, trades=2,
                    source="backfill") for t in range(block_key.start_ms, block_key.end_ms, 86400000)]
    return summarize([AcceptedComponent(block_key.series, bar, bar.time_ms + 86400000, revision)
                      for bar in bars], target=block_key.series)


def consume(m, k=None, builder=None, cancel=None):
    k = k or key()
    with m.view((k.series,)) as view:
        with m.acquire(k, view, lambda: builder(view, k) if builder else build(view, k), cancel=cancel) as block:
            return block


def eventually(predicate):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(.005)
    assert predicate()


def assert_idle(m, *, empty=False):
    snapshot = m.snapshot()
    assert snapshot["leases"] == snapshot["views"] == snapshot["inflight"] == 0
    assert snapshot["retired_entries"] == 0
    assert m.budget.snapshot()["reserved_bytes"] == 0
    assert m.budget.snapshot()["over_budget_bytes"] == 0
    if empty:
        assert snapshot["entries"] == snapshot["estimated_bytes"] == 0


def test_warm_blocks_are_immutable_and_target_independent():
    m = manager()
    first = consume(m)
    assert consume(m) is first
    assert m.snapshot()["builds"] == 1 and m.snapshot()["hits"] == 1
    assert first.summary.values.volume == 6
    with pytest.raises(AttributeError):
        first.summary.values.volume = 0
    assert_idle(m)
    m.collect()
    assert_idle(m, empty=True)


@pytest.mark.parametrize("variant", [
    {"exchange": "okx"}, {"market_type": "futures"}, {"symbol": "ETHUSDT"},
    {"interval": "1d@utc+8"}, {"series_variant": "other"},
    {"volume_semantics": "contracts"}, {"session_variant": "regular"},
    {"price_adjustment": "split"},
])
def test_full_source_semantics_never_share_blocks(variant):
    m = manager()
    consume(m)
    other = replace(SOURCE, **variant)
    consume(m, key(source=other))
    assert m.snapshot()["builds"] == 2
    assert m.snapshot()["hits"] == 0
    assert_idle(m)


def test_pins_prevent_eviction_then_last_release_allows_lru():
    m = manager(max_entries=1)
    with m.view((SOURCE,)) as view:
        lease = m.acquire(key(), view, lambda: build(view, key()))
        with pytest.raises(MemoryBudgetExceeded):
            m.acquire(key(1), view, lambda: build(view, key(1)))
        m.collect()
        assert lease.block.summary.values.volume == 6
        lease.close()
        lease.close()
        with m.acquire(key(1), view, lambda: build(view, key(1))) as block:
            assert block.key == key(1)
    assert m.snapshot()["evictions"] == 1
    assert_idle(m)


def test_invalidated_pinned_values_remain_charged_until_release():
    m = manager(max_entries=1)
    with pytest.raises(BlockRevisionChanged):
        with m.view((SOURCE,)) as view:
            lease = m.acquire(key(), view, lambda: build(view, key()))
            before = m.snapshot()["estimated_bytes"]
            m.invalidate(SOURCE, m.source.domain)
            assert m.snapshot()["retired_entries"] == 1
            assert m.snapshot()["estimated_bytes"] == before
            with pytest.raises(BlockRevisionChanged):
                _ = lease.block
            lease.close()
            assert m.snapshot()["retired_entries"] == 0
    assert_idle(m, empty=True)


def test_equal_requests_build_once_and_share_one_version():
    m = manager()
    entered, release = threading.Event(), threading.Event()
    def slow(view, k):
        entered.set()
        assert release.wait(5)
        return build(view, k)
    with ThreadPoolExecutor(max_workers=8) as pool:
        first = pool.submit(consume, m, builder=slow)
        assert entered.wait(5)
        others = [pool.submit(consume, m) for _ in range(7)]
        eventually(lambda: m.snapshot()["joins"] == 7)
        release.set()
        blocks = [f.result(5) for f in (first, *others)]
    assert all(block is blocks[0] for block in blocks)
    assert m.snapshot()["builds"] == 1
    assert_idle(m)


@pytest.mark.parametrize("cancel_owner", [False, True])
def test_one_cancellation_does_not_cancel_the_shared_build(cancel_owner):
    m = manager()
    entered, release, cancel = threading.Event(), threading.Event(), threading.Event()
    def slow(view, k):
        entered.set()
        assert release.wait(5)
        return build(view, k)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(consume, m, builder=slow, cancel=cancel if cancel_owner else None)
        assert entered.wait(5)
        joined = pool.submit(consume, m, cancel=None if cancel_owner else cancel)
        eventually(lambda: m.snapshot()["joins"] == 1)
        cancel.set()
        if not cancel_owner:
            with pytest.raises(CancelledError):
                joined.result(5)
        release.set()
        if cancel_owner:
            with pytest.raises(CancelledError):
                owner.result(5)
            assert joined.result(5).summary.values.volume == 6
        else:
            assert owner.result(5).summary.values.volume == 6
    assert m.snapshot()["builds"] == 1
    assert_idle(m)


@pytest.mark.parametrize("error", [ValueError, TimeoutError, MemoryBudgetExceeded])
def test_failed_build_does_not_poison_retry_or_leak_waiters(error):
    m = manager()
    def fail(view, k):
        raise error("injected")
    with pytest.raises(error):
        consume(m, builder=fail)
    assert_idle(m, empty=True)
    assert consume(m).summary.values.volume == 6
    assert_idle(m)


@pytest.mark.parametrize("mutation", ["amend", "reset", "close"])
def test_late_build_cannot_adopt_after_revision_or_generation_change(mutation):
    m = manager()
    entered, release = threading.Event(), threading.Event()
    def slow(view, k):
        entered.set()
        assert release.wait(5)
        return build(view, k)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(consume, m, builder=slow)
        assert entered.wait(5)
        if mutation == "amend":
            m.source.amend()
            with m.view((SOURCE,)):
                pass
        elif mutation == "reset":
            m.source.reset = True
            with m.view((SOURCE,)):
                pass
        else:
            m.close()
        release.set()
        with pytest.raises(BlockRevisionChanged):
            future.result(5)
    assert_idle(m, empty=True)


def test_revision_failure_fails_closed_and_recovers_with_new_view():
    m = manager()
    consume(m)
    m.source.fail = True
    with pytest.raises(BlockUnavailable):
        consume(m)
    assert_idle(m, empty=True)
    m.source.fail = False
    consume(m)
    assert m.snapshot()["last_error"] is None
    assert_idle(m)


def test_revision_change_at_view_exit_rejects_already_computed_result():
    m = manager()
    with pytest.raises(BlockRevisionChanged):
        with m.view((SOURCE,)) as view:
            with m.acquire(key(), view, lambda: build(view, key())) as block:
                assert block.summary.values.volume == 6
            m.source.amend()
    assert_idle(m, empty=True)
    assert consume(m).summary.revisions[0].version == 2


def test_range_invalidation_is_half_open_and_keeps_unrelated_source():
    m = manager()
    a, b = consume(m, key()), consume(m, key(1))
    other = key(source=replace(SOURCE, symbol="ETHUSDT"))
    c = consume(m, other)
    m.invalidate(SOURCE, m.source.domain, start_ms=0, end_ms=key().end_ms)
    assert consume(m, key(1)) is b
    assert consume(m, other) is c
    assert consume(m).version != a.version
    assert_idle(m)


def test_expired_foreign_views_and_unknown_algorithm_are_rejected():
    m = manager()
    with m.view((SOURCE,)) as view:
        pass
    with pytest.raises(BlockRevisionChanged):
        m.acquire(key(), view, lambda: build(view, key()))
    other = manager()
    with other.view((SOURCE,)) as foreign:
        with pytest.raises(BlockRevisionChanged):
            m.acquire(key(), foreign, lambda: build(foreign, key()))
    with pytest.raises(ValueError):
        replace(key(), algorithm_version="future-v2")
    assert_idle(m, empty=True)


def test_view_lease_flight_and_result_size_limits_release_all_accounting():
    m = manager(max_views=1, max_leases=1)
    with m.view((SOURCE,)) as view:
        with pytest.raises(MemoryBudgetExceeded):
            with m.view((SOURCE,)):
                pass
        with m.acquire(key(), view, lambda: build(view, key())):
            with pytest.raises(MemoryBudgetExceeded):
                m.acquire(key(), view, lambda: build(view, key()))
    m.collect()
    with m.view((SOURCE,)) as view:
        with pytest.raises(MemoryBudgetExceeded):
            m.acquire(key(), view, lambda: build(view, key()), work_bytes=128)
    assert_idle(m, empty=True)


def test_lru_repeated_revisions_never_accumulate_tombstones_or_retired_values():
    m = manager(max_entries=4)
    for i in range(80):
        if i % 3 == 0:
            m.source.amend()
        consume(m, key(i % 9))
        assert m.snapshot()["entries"] <= 4
        assert len(m._dependencies) <= 1
        assert_idle(m)
    m.close()
    assert_idle(m, empty=True)


def test_work_to_retained_transfer_is_atomic_against_other_budget_owners():
    budget = MemoryBudget(100)
    used = {"a": 0, "b": 0}
    for owner in used:
        budget.register(owner, limit_bytes=100, usage=lambda owner=owner: {"estimated_bytes": used[owner]})
    with budget.reserve("a", 60) as lease:
        with budget.reserve("b", 30):
            with pytest.raises(MemoryBudgetExceeded):
                lease.retain(80, lambda: used.update(a=80))
            assert used["a"] == 0 and budget.snapshot()["reserved_bytes"] == 90
        lease.retain(80, lambda: used.update(a=80))
        assert budget.snapshot()["estimated_bytes"] == 80
        assert budget.snapshot()["reserved_bytes"] == 0
        with pytest.raises(RuntimeError):
            lease.retain(1, lambda: None)
    assert budget.snapshot()["over_budget_bytes"] == 0


def test_cache_only_consumer_never_starts_or_joins_a_build():
    m = manager()
    with m.view((SOURCE,)) as view:
        assert m.acquire(key(), view) is None
        assert m.snapshot()["builds"] == 0
        with m.acquire(key(), view, lambda: build(view, key())):
            with m.acquire(key(), view) as cached:
                assert cached.summary.values.volume == 6
    assert_idle(m)


def test_recursive_builder_fails_instead_of_blocking_its_own_worker():
    m = manager()
    with m.view((SOURCE,)) as view:
        with pytest.raises(RuntimeError, match="own in-flight"):
            m.acquire(key(), view, lambda: m.acquire(key(), view, lambda: build(view, key())))
    assert_idle(m, empty=True)


def test_inflight_capacity_is_bounded_and_unrelated_builds_are_independent():
    m = manager(max_flights=1)
    entered, release = threading.Event(), threading.Event()
    def slow(view, k):
        entered.set()
        assert release.wait(5)
        return build(view, k)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(consume, m, builder=slow)
        assert entered.wait(5)
        with pytest.raises(MemoryBudgetExceeded):
            consume(m, key(1))
        release.set()
        future.result(5)
    consume(m, key(1))
    assert_idle(m)


def test_close_invalidates_lease_reopen_requires_old_consumers_to_drain():
    m = manager()
    with pytest.raises(BlockRevisionChanged):
        with m.view((SOURCE,)) as view:
            lease = m.acquire(key(), view, lambda: build(view, key()))
            m.close()
            with pytest.raises(BlockUnavailable):
                m.reopen()
            with pytest.raises(BlockRevisionChanged):
                _ = lease.block
    assert_idle(m, empty=True)
    m.reopen()
    consume(m)
    assert_idle(m)


def test_different_revision_domains_are_not_numerically_ordered():
    m = manager()
    class Domains:
        first, second = 100, 2
        def read(self, series, *, acquired_at=None):
            return (InputRevision(SOURCE, "archive", self.first),
                    InputRevision(SOURCE, "live", self.second)), (), False
    source = Domains()
    m.bind_source(source)
    def value(view, k):
        return replace(build(view, k), revisions=view.revisions)
    first = consume(m, builder=value)
    source.second = 1  # An opaque-domain change, not "older than archive 100".
    second = consume(m, builder=value)
    assert second.version != first.version
    assert second.summary.revisions[1].version == 1
    assert m.snapshot()["invalidations"] == 1
    assert_idle(m)


@pytest.mark.parametrize("fault", ["unknown", "revision", "identity", "algorithm", "range", "fragmentation"])
def test_invalid_summary_never_enters_cache(fault):
    from app.data_engine.aggregation.semantics import Coverage
    m = manager(max_ranges=1)
    def invalid(view, k):
        summary = build(view, k)
        if fault == "unknown":
            return replace(summary, revisions_known=False)
        if fault == "revision":
            return replace(summary, revisions=(replace(view.revisions[0], version=999),))
        if fault == "identity":
            return replace(summary, target=replace(SOURCE, symbol="ETHUSDT"))
        if fault == "algorithm":
            return replace(summary, algorithm_version="unknown-v2")
        if fault == "range":
            return replace(summary, coverage=Coverage(((-1, k.end_ms),), True, True, 2))
        return replace(summary, coverage=Coverage(((0, 1), (2, 3)), True, True, 2))
    with pytest.raises(ValueError):
        consume(m, builder=invalid)
    assert_idle(m, empty=True)


def test_calendar_blocks_keep_actual_leap_month_boundaries():
    from datetime import datetime, timezone
    start = int(datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
    series = replace(SOURCE, interval="1M")
    k = BlockKey(series, start, end)
    m = manager()
    with m.view((series,)) as view:
        bar = BarData(start // 1000, 1, 2, 1, 2, 10, source="backfill")
        with m.acquire(k, view, lambda: summarize([
            AcceptedComponent(series, bar, end, view.revisions[0])], target=series)) as block:
            assert block.summary.is_authoritative(start, end)
            assert block.key.end_ms - block.key.start_ms == 29 * 86400000
            assert not block.summary.evaluate(start, end + 86400000).complete
    assert_idle(m)


def test_transitive_parent_uses_flattened_source_dependencies_for_invalidation():
    from app.data_engine.aggregation.core import combine
    m = manager()
    with m.view((SOURCE,)) as view:
        children = []
        for i in range(2):
            with m.acquire(key(i), view, lambda i=i: build(view, key(i))) as child:
                children.append(child.summary)
        parent_key = BlockKey(SOURCE, 0, key(1).end_ms)
        with m.acquire(parent_key, view, lambda: combine(children)) as parent:
            assert parent.summary.values.volume == 12
    assert m.snapshot()["entries"] == 3
    m.source.amend()
    m.poll()
    assert_idle(m, empty=True)
