"""Exact-grid proposals against an independent minute-level coverage oracle."""
from dataclasses import replace
import random

import pytest

from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import (
    CoverBudgetExceeded, CoverUnavailable, FixedHistorySource, plan_fixed_target,
)

MINUTE = 60_000
FIELDS = frozenset({"open", "high", "low", "close", "volume"})


def source(minutes, *, phase=0, end=10_000_000 * MINUTE, cost=1, **kwargs):
    return FixedHistorySource(SeriesKey("BTCUSDT", f"{minutes}m"), minutes * MINUTE,
                              phase * MINUTE, ((0, end),), FIELDS, "test-recording/v1", cost,
                              **kwargs)


def assert_cover(plan):
    at = plan.start_ms
    # Independently enumerate coverage slots; never call the planner's admits.
    seen = set()
    count = 0
    for span in plan.spans:
        assert span.start_ms == at
        assert (span.start_ms - span.source.phase_ms) % span.source.width_ms == 0
        assert span.end_ms <= plan.end_ms
        assert any(lo <= span.start_ms and span.end_ms <= hi for lo, hi in span.source.eligible_ranges)
        for opened in range(span.start_ms, span.end_ms, span.source.width_ms):
            count += 1
            for point in range(opened, opened + span.source.width_ms, MINUTE):
                assert point not in seen
                seen.add(point)
        at = span.end_ms
    assert at == plan.end_ms
    assert seen == set(range(plan.start_ms, plan.end_ms, MINUTE))
    assert count == plan.planned_rows


@pytest.mark.parametrize("width", [89, 97, 101, 10_007])
def test_many_actual_target_phases_tile_without_clipping_coarse_candles(width):
    grids = tuple(source(value) for value in (1440, 720, 480, 360, 240, 120, 60, 30, 15, 5, 3, 1))
    rng = random.Random(127)
    target = SeriesKey("BTCUSDT", f"{width}m")
    for index in [0, 1, 2, 499, *[rng.randrange(3, 499) for _ in range(20)]]:
        start, end = index * width * MINUTE, (index + 1) * width * MINUTE
        plan = plan_fixed_target(target, start, end, grids)
        assert_cover(plan)
        assert plan.planned_rows < width


def test_89m_documented_cover_uses_only_eight_native_candles():
    plan = plan_fixed_target(SeriesKey("BTCUSDT", "89m"), 0, 89 * MINUTE,
                             tuple(source(value) for value in (60, 15, 5, 1)))
    assert [(span.source.series.interval, span.rows) for span in plan.spans] == [
        ("1h", 1), ("15m", 1), ("5m", 2), ("1m", 4),
    ]
    assert plan.planned_rows == 8
    assert_cover(plan)


def test_backtracking_recovers_from_a_larger_grid_dead_end():
    plan = plan_fixed_target(SeriesKey("BTCUSDT", "10m"), 0, 10 * MINUTE,
                             (source(4), source(3, phase=1)))
    assert [(span.source.width_ms // MINUTE, span.rows) for span in plan.spans] == [(4, 1), (3, 2)]
    assert_cover(plan)


def test_two_and_three_minute_grids_can_exactly_cover_nine_minutes():
    plan = plan_fixed_target(SeriesKey("BTCUSDT", "9m"), 0, 9 * MINUTE,
                             (source(2), source(3)))
    assert plan.planned_rows == 3
    assert_cover(plan)


def test_hot_fine_data_can_cost_less_than_a_cold_coarse_plan():
    plan = plan_fixed_target(SeriesKey("BTCUSDT", "89m"), 0, 89 * MINUTE,
                             (source(60, cost=10), source(1, cost=0)))
    assert plan.planned_rows == 89 and plan.estimated_cost == 0
    assert len(plan.spans) == 1
    assert_cover(plan)


def test_unqualified_range_uses_only_the_local_fine_replacement():
    coarse = replace(source(60), eligible_ranges=((60 * MINUTE, 120 * MINUTE),))
    plan = plan_fixed_target(SeriesKey("BTCUSDT", "89m"), 0, 89 * MINUTE, (coarse, source(1)))
    assert plan.planned_rows == 89
    assert_cover(plan)


def test_adjacent_eligibility_ranges_do_not_create_an_artificial_grid_boundary():
    grid = replace(source(5), eligible_ranges=((0, 3 * MINUTE), (3 * MINUTE, 10 * MINUTE)))
    plan = plan_fixed_target(SeriesKey("BTCUSDT", "10m"), 0, 10 * MINUTE, (grid,))
    assert plan.planned_rows == 2
    assert_cover(plan)


@pytest.mark.parametrize("width", [89, 97, 101, 10_007])
@pytest.mark.parametrize("index", [0, 1, 17])
def test_mixed_components_use_k130_without_changing_the_fine_reference(width, index):
    from app.data_engine.aggregation.core import AcceptedComponent, InputRevision, summarize
    from app.data_engine.data_manager.models import BarData

    target = SeriesKey("BTCUSDT", f"{width}m")
    plan = plan_fixed_target(target, index * width * MINUTE, (index + 1) * width * MINUTE,
                             tuple(source(value) for value in (1440, 60, 15, 5, 3, 1)))
    def minute(opened):
        value = opened % 113 + 10
        return dict(open=value, high=value + 4, low=value - 3, close=value + 1,
                    volume=opened % 7 + 1, quote_volume=opened % 11 + 10,
                    trades=opened % 5 + 1, taker_buy_base=1, taker_buy_quote=3)
    def reduce(values):
        return dict(open=values[0]["open"], high=max(row["high"] for row in values),
                    low=min(row["low"] for row in values), close=values[-1]["close"],
                    **{field: sum(row[field] for row in values) for field in
                       ("volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote")})
    components = []
    for span in plan.spans:
        for opened in range(span.start_ms, span.end_ms, span.source.width_ms):
            end = opened + span.source.width_ms
            values = reduce([minute(point) for point in range(opened // MINUTE, end // MINUTE)])
            bar = BarData(time=opened // 1000, is_closed=True, source="backfill", **values)
            components.append(AcceptedComponent(span.source.series, bar, end,
                              InputRevision(span.source.series, "fixture/v1", 1)))
    result = summarize(components, target=target)
    reference = reduce([minute(point) for point in range(index * width, (index + 1) * width)])
    assert result.is_authoritative(plan.start_ms, plan.end_ms)
    assert result.values.project(enhanced_complete=True) == reference


@pytest.mark.parametrize("mismatch", ["fields", "provider", "market", "instrument"])
def test_incompatible_semantics_never_enter_a_cover(mismatch):
    grid = source(1)
    if mismatch == "fields":
        grid = replace(grid, fields=FIELDS - {"volume"})
    elif mismatch == "provider":
        grid = replace(grid, series=SeriesKey.create(
            "BTCUSDT", "1m", identity=replace(grid.series.identity, provider_id="foreign")))
    elif mismatch == "market":
        grid = replace(grid, series=replace(grid.series, market_type="futures"))
    else:
        grid = replace(grid, series=replace(grid.series, symbol="ETHUSDT"))
    with pytest.raises(CoverUnavailable):
        plan_fixed_target(SeriesKey("BTCUSDT", "89m"), 0, 89 * MINUTE, (grid,))


def test_budget_exhaustion_is_distinct_from_impossible_source_coverage():
    with pytest.raises(CoverBudgetExceeded):
        plan_fixed_target(SeriesKey("BTCUSDT", "89m"), 0, 89 * MINUTE,
                          (source(1),), max_positions=8)
    with pytest.raises(CoverUnavailable) as failure:
        plan_fixed_target(SeriesKey("BTCUSDT", "89m"), 0, 89 * MINUTE, (source(5),))
    assert not isinstance(failure.value, CoverBudgetExceeded)


@pytest.mark.parametrize("start,end", [(1, 89 * MINUTE), (0, 90 * MINUTE), (True, 89 * MINUTE)])
def test_partial_and_unaligned_targets_are_explicitly_rejected(start, end):
    with pytest.raises(CoverUnavailable):
        plan_fixed_target(SeriesKey("BTCUSDT", "89m"), start, end, (source(1),))


def test_calendar_months_are_not_approximated_by_fixed_days():
    with pytest.raises(CoverUnavailable):
        plan_fixed_target(SeriesKey("BTCUSDT", "1M"), 0, 30 * 1440 * MINUTE, (source(1440),))
