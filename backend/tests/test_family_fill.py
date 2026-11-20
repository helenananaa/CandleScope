"""The family fill's gate and pieces (data_manager/family_fill.py)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.data_engine.backfill.family_plan import FamilyPlan
from app.data_engine.data_manager import family_fill as ff
from app.data_engine.data_manager.backfill_contracts import RepairOutcome, RepairRequest
from app.data_engine.data_manager.models import SeriesKey
from tests.test_backfill_batch_ownership import scheduler_for

MINUTE, HOUR = 60_000, 3_600_000
CONTRACT = "binance.usdm.trade-klines/base-utc/1"


def utc(*parts):
    return int(datetime(*parts, tzinfo=timezone.utc).timestamp() * 1000)


def chart(interval="10007m", start=0, end=0, reason="initial_history", **metadata):
    return RepairRequest("BTCUSDT", interval, start, end, market_type="futures", reason=reason,
                         metadata={"required_history_composition": CONTRACT, **metadata})


def test_only_qualified_mixed_history_of_one_usdm_symbol_belongs_to_a_family():
    assert ff.family_of(chart()) == ("binance", "futures", "BTCUSDT")
    assert ff.family_of(chart("89m", bounded_history_batch_contract=CONTRACT)) == ("binance", "futures", "BTCUSDT")
    plain = RepairRequest("BTCUSDT", "10007m", 0, 0, market_type="futures", reason="initial_history")
    assert ff.family_of(plain) is None
    assert ff.family_of(RepairRequest("BTCUSDT", "1m", 0, 0, market_type="futures",
                                      metadata={ff.PIECE_MARKER: "x"})) is None
    spot = RepairRequest("BTCUSDT", "10007m", 0, 0, market_type="spot", reason="initial_history",
                         metadata={"required_history_composition": CONTRACT})
    assert ff.family_of(spot) is None


def test_a_fill_holds_everything_while_planning_then_only_what_a_piece_can_reach():
    fill = ff.FamilyFill(manager=None, family=("binance", "futures", "BTCUSDT"))
    inside = chart("89m", utc(2026, 3, 30), utc(2026, 3, 31))
    later = chart("89m", utc(2026, 5, 2), utc(2026, 5, 3))
    assert fill.holds(inside) and fill.holds(later)
    # The newest chunks are planned first and wait only for their pieces.
    fill.early = {(later.interval, later.start_ms, later.end_ms)}
    assert fill.holds(inside) and not fill.holds(later)
    fill.planning = False
    # A few March hours may import the whole March object of 1h.
    fill.pending = {"piece": ff._widen("1h", utc(2026, 3, 10), utc(2026, 3, 10, 5))}
    assert fill.holds(inside) and not fill.holds(later)
    fill.pending = {}
    assert not fill.holds(inside)


def test_a_piece_reaches_as_far_as_the_archive_object_that_may_hold_it():
    # A month of 1h fits in one object; a month of 1m does not, a day does.
    assert ff._widen("1h", utc(2026, 3, 10), utc(2026, 3, 10, 5)) == (utc(2026, 3, 1), utc(2026, 4, 1))
    assert ff._widen("1m", utc(2026, 3, 10, 5), utc(2026, 3, 11, 1)) == (utc(2026, 3, 10), utc(2026, 3, 12))


def demand(interval, start, stop, grids):
    from dataclasses import replace
    from app.data_engine.backfill.family_plan import ChartDemand
    from app.data_engine.history.cover_plan import FixedHistorySource
    target = SeriesKey("BTCUSDT", interval, market_type="futures")
    sources = tuple(FixedHistorySource(replace(target, interval=grid), width, 0, ((0, stop),),
                                       frozenset({"open"}), CONTRACT) for grid, width in grids)
    return ChartDemand(target, start, stop, sources, (), frozenset({"open"}))


def test_coarse_needs_become_whole_months_of_1h_and_only_dense_or_boundary_minutes_are_acquired():
    wide = demand("10007m", utc(2026, 1, 3), utc(2026, 4, 20), (("1m", MINUTE), ("1h", HOUR), ("1d", 24 * HOUR)))
    near = utc(2026, 1, 3)  # A chunk boundary.
    plan = FamilyPlan(
        cells={"1d": frozenset({utc(2026, 1, 20)}), "1h": frozenset({utc(2026, 3, 5, 7)})},
        windows={"1m": ((utc(2026, 4, 1), utc(2026, 4, 1, 8)),            # dense: 480 minutes
                        (utc(2026, 2, 11, 3), utc(2026, 2, 11, 3, 40)),   # sparse, mid-chunk: left to the chunk
                        (near - 30 * MINUTE, near))},                     # sparse at a boundary: whole day
        covers={}, iterations=1)
    ranges = ff.FamilyFill._ranges(plan, [wide])
    # January to March as 1h, clipped to the first target; 1d is superseded.
    assert ranges["1h"] == [(utc(2026, 1, 3), utc(2026, 4, 1))] and "1d" not in ranges
    assert ranges["1m"] == [(utc(2026, 1, 2), utc(2026, 1, 3)), (utc(2026, 4, 1), utc(2026, 4, 1, 8))]
    # A chart that cannot use 1h keeps its exact coarse windows.
    narrow = demand("10007m", utc(2026, 1, 3), utc(2026, 4, 20), (("1m", MINUTE), ("4h", 4 * HOUR)))
    plan = FamilyPlan(cells={"4h": frozenset({utc(2026, 3, 5, 8)})},
                      windows={"4h": ((utc(2026, 3, 5, 8), utc(2026, 3, 5, 12)),)}, covers={}, iterations=1)
    assert ff.FamilyFill._ranges(plan, [narrow]) == {"4h": [(utc(2026, 3, 5, 8), utc(2026, 3, 5, 12))]}


def test_pieces_are_contiguous_bounded_native_repairs_newest_first():
    ranges = {"1h": [(utc(2026, 1, 1), utc(2026, 1, 1) + 9000 * HOUR)], "1m": [(utc(2026, 4, 1), utc(2026, 4, 1, 1))]}
    pieces = ff.FamilyFill._pieces(ranges, SeriesKey("BTCUSDT", "10007m", market_type="futures"))
    hours = [piece for piece in pieces if piece.interval == "1h"]
    assert [(piece.end_ms - piece.start_ms) // HOUR + 1 for piece in hours] == [4000, 4000, 1000]
    assert hours[0].end_ms == utc(2026, 1, 1) + 8999 * HOUR and hours[-1].start_ms == utc(2026, 1, 1)
    assert all(later.start_ms == earlier.end_ms + HOUR for later, earlier in zip(hours, hours[1:]))
    assert pieces[0].interval == "1h" and pieces[-1].interval == "1h"
    assert all(piece.requester == "family_fill" and ff.PIECE_MARKER in piece.metadata
               and "history_fetch_ranges" not in piece.metadata for piece in pieces)
    assert len({piece.metadata[ff.PIECE_MARKER] for piece in pieces}) == 4
    assert ff._subtract([(0, 10)], [(2, 4), (6, 7)]) == [(0, 2), (4, 6), (7, 10)]


def test_adjacent_pieces_of_one_series_never_coalesce_into_one_future():
    async def run():
        calls = []
        async def execute(req):
            calls.append(req.metadata.get(ff.PIECE_MARKER))
            await asyncio.sleep(0)
            return RepairOutcome(request=req, status="completed")
        scheduler = scheduler_for(execute, concurrency=0)
        first = RepairRequest("BTCUSDT", "1h", 0, 9 * HOUR, market_type="futures", reason="initial_history",
                              metadata={ff.PIECE_MARKER: "a"})
        second = RepairRequest("BTCUSDT", "1h", 10 * HOUR, 19 * HOUR, market_type="futures",
                               reason="initial_history", metadata={ff.PIECE_MARKER: "b"})
        ids = [scheduler.submit(first)[0], scheduler.submit(second)[0]]
        assert ids == [first.request_id, second.request_id]
        for _ in range(20):
            await asyncio.sleep(0)
        assert sorted(calls) == ["a", "b"]
        await scheduler.shutdown()
    asyncio.run(run())


class Gate:
    def __init__(self):
        self.held, self.noted = True, []

    def note(self, request):
        self.noted.append(request.request_id)

    def holds(self, request):
        return self.held and request.interval == "10007m"

    def snapshot(self):
        return {}

    async def shutdown(self):
        pass


def test_a_held_chunk_is_not_dispatched_until_its_gate_releases_it(monkeypatch):
    # The gate alone: the newest mixed chunk's settling wait (finer_work_hold) is off.
    from app.data_engine.data_manager import finer_work_hold
    monkeypatch.setattr(finer_work_hold, "SETTLE_SECONDS", 0.0)
    async def run():
        calls = []
        async def execute(req):
            calls.append(req.interval)
            return RepairOutcome(request=req, status="completed")
        scheduler = scheduler_for(execute, concurrency=0)
        gate = scheduler.family_gate = Gate()
        held = chart(end=10007 * MINUTE)
        free = RepairRequest("BTCUSDT", "1m", 0, 9 * MINUTE, market_type="futures", reason="initial_history")
        scheduler.submit(held)
        scheduler.submit(free)
        for _ in range(20):
            await asyncio.sleep(0)
        assert gate.noted == [held.request_id, free.request_id]
        assert calls == ["1m"]
        gate.held = False
        scheduler._drain()
        for _ in range(20):
            await asyncio.sleep(0)
        assert sorted(calls) == ["10007m", "1m"]
        await scheduler.shutdown()
    asyncio.run(run())
