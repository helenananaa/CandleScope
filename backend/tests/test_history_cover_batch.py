"""Bounded whole-target proposals and exact resume semantics for backfill."""
import pytest

from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import CoverBudgetExceeded, CoverUnavailable, plan_fixed_batch, plan_fixed_target
from tests.test_history_cover_plan import MINUTE, source, assert_cover


@pytest.mark.parametrize("minutes", [89, 97, 101, 10007])
def test_large_request_resumes_whole_targets_without_gaps_or_duplicate_inputs(minutes):
    target = SeriesKey("BTCUSDT", f"{minutes}m")
    grids = tuple(source(n) for n in (60, 15, 5, 1))
    width = minutes * MINUTE
    first, stop = 7 * width, 72 * width
    cursor, starts = first, []
    while cursor < stop:
        batch = plan_fixed_batch(target, cursor, stop, grids, max_targets=8, max_source_rows=1024)
        assert batch.requested_range == (cursor, stop)
        assert 1 <= len(batch.covers) <= 8 and batch.planned_rows <= 1024
        at = cursor
        for cover in batch.covers:
            assert cover.start_ms == at
            assert_cover(cover)
            starts.append(cover.start_ms)
            at = cover.end_ms
        assert batch.planned_range == (cursor, at)
        assert at > cursor
        assert batch.next_start_ms == (at if at < stop else None)
        assert (batch.stopped_by is None) == (at == stop)
        cursor = at
    assert starts == list(range(first, stop, width))


def test_source_row_budget_never_splits_or_labels_the_remaining_request_complete():
    target = SeriesKey("BTCUSDT", "10007m")
    width = 10007 * MINUTE
    batch = plan_fixed_batch(target, 0, 2 * width, (source(1),), max_source_rows=16384)
    assert len(batch.covers) == 1 and batch.planned_rows == 10007
    assert batch.stopped_by == "source_rows" and batch.next_start_ms == width
    assert batch.explored_positions > batch.covers[0].explored_positions
    resumed = plan_fixed_batch(target, batch.next_start_ms, 2 * width, (source(1),))
    assert resumed.next_start_ms is None and resumed.covers[0].start_ms == width
    with pytest.raises(CoverBudgetExceeded, match="source-row"):
        plan_fixed_batch(target, 0, width, (source(1),), max_source_rows=10000)


def test_search_budget_is_shared_by_all_targets_and_not_hidden_in_an_abandoned_attempt():
    target = SeriesKey("BTCUSDT", "89m")
    width = 89 * MINUTE
    grids = tuple(source(n) for n in (60, 15, 5, 1))
    one = plan_fixed_target(target, 0, width, grids)
    for extra in (0, 1):
        budget = one.explored_positions + extra
        batch = plan_fixed_batch(target, 0, 2 * width, grids, max_positions=budget)
        assert len(batch.covers) == 1 and batch.next_start_ms == width
        assert batch.stopped_by == "planning_budget" and batch.explored_positions == budget
    with pytest.raises(CoverBudgetExceeded):
        plan_fixed_batch(target, 0, width, grids, max_positions=1)


def test_unavailable_later_sources_preserve_only_the_proposed_prefix():
    target = SeriesKey("BTCUSDT", "89m")
    width = 89 * MINUTE
    grids = (source(1, end=width),)
    batch = plan_fixed_batch(target, 0, 2 * width, grids)
    assert len(batch.covers) == 1 and batch.stopped_by == "source_unavailable"
    assert batch.next_start_ms == width and batch.planned_range == (0, width)
    assert batch.explored_positions > sum(cover.explored_positions for cover in batch.covers)
    with pytest.raises(CoverUnavailable):
        plan_fixed_batch(target, width, 2 * width, grids)


@pytest.mark.parametrize("bounds", [(1, 89 * MINUTE), (0, 89 * MINUTE + 1), (0, 0)])
def test_partial_target_boundaries_are_not_approximated(bounds):
    with pytest.raises(CoverUnavailable):
        plan_fixed_batch(SeriesKey("BTCUSDT", "89m"), *bounds, (source(1),))


@pytest.mark.parametrize("options", [dict(max_targets=33), dict(max_targets=True),
    dict(max_source_rows=0), dict(max_source_rows=131073), dict(max_positions=0)])
def test_work_limits_are_explicit_bounded_inputs(options):
    with pytest.raises(ValueError):
        plan_fixed_batch(SeriesKey("BTCUSDT", "89m"), 0, 89 * MINUTE, (source(1),), **options)
