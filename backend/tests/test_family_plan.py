"""A family plan lets every chart compose, checked by the real composed reader.

Each case builds a random stored state for one symbol (partial 1m/1h/1d runs,
unusable rows, stray finer rows of a non-route grid) and four chart demands
over overlapping ranges, each with its own selected source grids. After the
plan's cells are written next to the stored rows, every target of every chart
must compose completely through ``query_composed``. Planning each chart alone
does not have this property: finer cells one chart needs refine the coarse
spans another chart planned in the same range.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import replace

import pytest

from app.data_engine.backfill.family_plan import (
    ChartDemand, FamilyPlanUnavailable, StoredSeries, plan_family_sources)
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import FixedHistorySource
from app.data_engine.interval_resolution import IntervalResolver
from tests.test_mixed_history_session import CONTRACT, MINUTE, bar, manager_for

HOUR, DAY = 60 * MINUTE, 1440 * MINUTE
WIDE = 10007 * MINUTE
STOP = 2 * WIDE


def demand(interval, start_ms, stop_ms, grids=None):
    target = SeriesKey("BTCUSDT", interval, market_type="futures")
    policy, routes, precedence = IntervalResolver().history_composition_routes(
        exchange="binance", market_type="futures", interval=interval)
    sources = tuple(FixedHistorySource(replace(target, interval=route.canonical_interval), route.spec.nominal_ms,
                                       0, ((0, stop_ms),), frozenset(policy.fields), policy.contract_id)
                    for route in routes if grids is None or route.canonical_interval in grids)
    precedences = tuple((replace(target, interval=route.canonical_interval), route.spec.nominal_ms)
                        for route in precedence)
    return ChartDemand(target, start_ms, stop_ms, sources, precedences, frozenset(policy.fields))


def demands(rng):
    """Four charts over overlapping closed ranges, as one workspace opens them."""
    out = [demand("10007m", 0, STOP, rng.choice([None, ("1m", "1h", "1d"), ("1m", "15m", "1h", "4h", "1d")]))]
    for interval, count in (("89m", 40), ("97m", 36), ("101m", 34)):
        width = int(interval[:-1]) * MINUTE
        stop = STOP // width * width - rng.randrange(0, 6) * width
        out.append(demand(interval, stop - count * width, stop, rng.choice([None, ("1m", "1h"), ("1m", "15m", "1h")])))
    return out


def stored_state(rng):
    """Rows per (interval, source) and the matching StoredSeries per interval."""
    reusable, other = {}, {}

    def runs(interval, width, count, longest):
        for _ in range(count):
            start = rng.randrange(0, STOP // width) * width
            for at in range(start, min(STOP, start + rng.randrange(1, longest) * width), width):
                reusable.setdefault(interval, set()).add(at)

    runs("1d", DAY, rng.randrange(0, 6), 4)
    runs("1h", HOUR, rng.randrange(0, 8), 40)
    runs("1m", MINUTE, rng.randrange(0, 10), 300)
    for _ in range(rng.randrange(0, 3)):
        # A row the planner cannot reuse: its whole span must be refined.
        interval, width = rng.choice([("1h", HOUR), ("15m", 15 * MINUTE)])
        at = rng.randrange(0, STOP // width) * width
        reusable.get(interval, set()).discard(at)
        other.setdefault(interval, set()).add(at)
    if rng.random() < 0.5:
        # A stray finer row of a grid no chart selects still takes precedence.
        reusable.setdefault("3m", set()).add(rng.randrange(0, STOP // (3 * MINUTE)) * 3 * MINUTE)
    widths = {"1m": MINUTE, "3m": 3 * MINUTE, "15m": 15 * MINUTE, "1h": HOUR, "1d": DAY}
    rows = {}
    for interval, opens in reusable.items():
        rows[(interval, "backfill")] = [bar(at, widths[interval], rng) for at in sorted(opens)]
    for interval, opens in other.items():
        rows[(interval, "data_manager")] = [bar(at, widths[interval], rng) for at in sorted(opens)]
    stored = {interval: StoredSeries(frozenset(reusable.get(interval, ())), frozenset(other.get(interval, ())))
              for interval in set(reusable) | set(other)}
    return rows, stored


def with_cells(rows, cells, rng):
    out = {key: list(items) for key, items in rows.items()}
    widths = {"1m": MINUTE, "5m": 5 * MINUTE, "15m": 15 * MINUTE, "1h": HOUR, "4h": 4 * HOUR, "1d": DAY}
    for interval, opens in cells.items():
        out.setdefault((interval, "backfill"), []).extend(bar(at, widths[interval], rng) for at in sorted(opens))
    return out


def composed(tmp_path, monkeypatch, name, rows, charts):
    """Each chart's composed result: (complete targets, targets)."""
    manager = manager_for(tmp_path / f"{name}.sqlite", rows, monkeypatch)
    try:
        out = {}
        for chart in charts:
            width = parse_width(chart.target.interval)
            count = (chart.stop_ms - chart.start_ms) // width
            result = manager.query_composed("BTCUSDT", chart.target.interval, start_ms=chart.start_ms,
                end_ms=chart.stop_ms - 1, limit=count, market_type="futures", composition_contract=CONTRACT,
                min_revision=manager.query_engine.storage.revision_store.head())
            out[chart.target.interval] = (len(result.bars) if result.complete else 0, count)
        return out
    finally:
        asyncio.run(manager.shutdown())


def parse_width(interval):
    return int(interval[:-1]) * MINUTE


@pytest.mark.parametrize("seed", range(12))
def test_after_the_family_plan_is_written_every_chart_composes(tmp_path, monkeypatch, seed):
    rng = random.Random(seed)
    charts = demands(rng)
    rows, stored = stored_state(rng)
    plan = plan_family_sources(charts, stored)
    for interval, cells in plan.cells.items():
        # Stored reusable rows are never acquired again.
        assert not cells & stored.get(interval, StoredSeries()).reusable
    results = composed(tmp_path, monkeypatch, "family", with_cells(rows, plan.cells, rng), charts)
    assert all(done == count for done, count in results.values()), results


def test_planning_each_chart_alone_leaves_targets_that_cannot_compose(tmp_path, monkeypatch):
    """The property above needs the joint plan: separate plans break across seeds."""
    broken = 0
    for seed in range(12):
        rng = random.Random(seed)
        charts = demands(rng)
        rows, stored = stored_state(rng)
        cells = {}
        for chart in charts:
            for interval, opens in plan_family_sources([chart], stored).cells.items():
                cells[interval] = cells.get(interval, frozenset()) | opens
        results = composed(tmp_path, monkeypatch, f"alone-{seed}", with_cells(rows, cells, rng), charts)
        broken += any(done != count for done, count in results.values())
    assert broken


def test_a_deletion_history_refines_every_coarser_span_it_may_reach():
    charts = [demand("10007m", 0, WIDE, ("1m", "1h", "1d"))]
    clean = plan_family_sources(charts, {})
    deleted = plan_family_sources(charts, {"1h": StoredSeries(deleted_from=0)})
    # Missing 1h rows are not proof after a deletion: no 1d span survives.
    assert "1d" in clean.cells and "1d" not in deleted.cells
    assert all(span.source.width_ms < DAY for spans in deleted.covers.values() for span in spans)


def test_whole_archive_objects_count_as_present_and_are_not_planned_again():
    charts = [demand("10007m", 0, WIDE, ("1m", "1h", "1d"))]
    day = set(range(2 * DAY, 3 * DAY, MINUTE))
    plan = plan_family_sources(charts, {}, extra={"1m": day})
    assert not plan.cells.get("1m", frozenset()) & day
    # That day is composed from its minutes, not from the coarser grids.
    assert not any(span.source.width_ms > MINUTE and span.start_ms < 3 * DAY and 2 * DAY < span.end_ms
                   for spans in plan.covers.values() for span in spans)


def test_bounds_and_unsupported_demands_decline():
    chart = demand("10007m", 0, STOP)
    with pytest.raises(FamilyPlanUnavailable):
        plan_family_sources([chart], {"1h": StoredSeries(deleted_from=0), "1m": StoredSeries(deleted_from=0)},
                            max_cells=10)
    with pytest.raises(FamilyPlanUnavailable):
        plan_family_sources([replace(chart, start_ms=MINUTE)], {})
    other = replace(chart, target=SeriesKey("ETHUSDT", "10007m", market_type="futures"))
    with pytest.raises(ValueError):
        plan_family_sources([chart, other], {})
