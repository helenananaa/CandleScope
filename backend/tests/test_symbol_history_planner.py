"""Per-symbol history planner skeleton (ADR-DATA-001 S4): demands, slots, pieces, execution.

The planner is not wired into DataManager yet (S5); these tests drive it with
a recording executor.
"""
from __future__ import annotations

import asyncio
import random
from collections import Counter

import pytest

from app.data_engine.data_manager.symbol_history import (
    REQUEST_FIELDS, URGENCY, Demand, DemandKind, DemandOwner, IntervalSet, PieceResult, PlannerRegistry,
    Segment, SlotMap, SymbolHistoryPlanner, SymbolKey, cut_pieces, kind_for_reason, piece_block_ms,
    planner_enabled,
)

SECOND = 1_000
MINUTE = 60 * SECOND
DAY = 24 * 60 * MINUTE
T0 = 1_764_115_200_000  # 2025-11-26 00:00 UTC, on a two-day epoch block
KEY = SymbolKey("binance", "futures", "BTCUSDT")


def source_for(interval: str) -> tuple[str, int]:
    return {"89m": ("1m", MINUTE), "97m": ("1m", MINUTE), "1m": ("1m", MINUTE),
            "90s": ("1s", SECOND), "30s": ("1s", SECOND)}[interval]


class Recorder:
    """An executor that records pieces and finishes them on request (or at once)."""

    def __init__(self, *, hold: bool = False, fail: set[int] | None = None) -> None:
        self.started: list = []
        self.hold = hold
        self.fail = fail or set()
        self.release = asyncio.Event()
        self.wanted_checks: list[bool] = []

    async def __call__(self, piece, still_wanted):
        self.started.append(piece)
        if self.hold:
            await self.release.wait()
        self.wanted_checks.append(still_wanted())
        if len(self.started) in self.fail:
            raise RuntimeError("exchange unavailable")
        return PieceResult("committed", written=((piece.start_ms, piece.end_ms),))


def planner(executor, *, closed=T0 + 30 * DAY, **kwargs) -> SymbolHistoryPlanner:
    return SymbolHistoryPlanner(KEY, executor=executor, source_for=source_for,
                                closed_until=lambda source: closed, **kwargs)


def demand(owner, interval, start, end, kind=DemandKind.VIEWPORT, scope=None, generation=None):
    return Demand(DemandOwner(owner, scope, generation), interval, start, end, kind)


async def tick() -> None:
    """Let the pump run and the started pieces reach their executor."""
    for _ in range(3):
        await asyncio.sleep(0)


def opens(pieces, width=MINUTE):
    return Counter(at for piece in pieces for at in range(piece.start_ms, piece.end_ms, width))


# Interval sets and slots ------------------------------------------------------

def test_interval_set_matches_a_point_set_under_random_edits():
    choose = random.Random(572)
    for _ in range(200):
        ranges, points = IntervalSet(), set()
        for _ in range(30):
            start = choose.randrange(0, 60)
            end = start + choose.randrange(0, 12)
            if choose.random() < 0.6:
                ranges.add(start, end)
                points |= set(range(start, end))
            else:
                ranges.remove(start, end)
                points -= set(range(start, end))
            stored = list(ranges)
            assert all(a < b for a, b in stored)
            assert all(b < c for (_, b), (c, _) in zip(stored, stored[1:])), "adjacent ranges must join"
            assert {p for a, b in stored for p in range(a, b)} == points
            start = choose.randrange(0, 60)
            end = start + choose.randrange(1, 12)
            window = set(range(start, end))
            assert ranges.covers(start, end) == (window <= points)
            assert ranges.overlaps(start, end) == bool(window & points)
            assert {p for a, b in ranges.minus(start, end) for p in range(a, b)} == window - points


def test_overlapping_targets_share_source_slots_at_the_most_urgent_level():
    slots = SlotMap("1m", MINUTE)
    a, b = DemandOwner("chart-89m"), DemandOwner("chart-97m")
    assert slots.want("a", a, T0, T0 + 600 * MINUTE, URGENCY[DemandKind.VIEWPORT])
    assert slots.want("b", b, T0 + 300 * MINUTE, T0 + 900 * MINUTE, URGENCY[DemandKind.FIRST_SCREEN])
    assert not slots.want("b", b, T0 + 300 * MINUTE, T0 + 900 * MINUTE, URGENCY[DemandKind.FIRST_SCREEN])
    assert slots.missing() == [
        Segment(T0, T0 + 300 * MINUTE, 3, frozenset({a})),
        Segment(T0 + 300 * MINUTE, T0 + 900 * MINUTE, 1, frozenset({a, b})),
    ]
    slots.present.add(T0 + 100 * MINUTE, T0 + 200 * MINUTE)
    slots.in_flight.add(T0 + 800 * MINUTE, T0 + 900 * MINUTE)
    assert [(s.start_ms, s.end_ms) for s in slots.missing()] == [
        (T0, T0 + 100 * MINUTE), (T0 + 200 * MINUTE, T0 + 300 * MINUTE), (T0 + 300 * MINUTE, T0 + 800 * MINUTE)]
    assert slots.unwant("a") and slots.owners_over(T0, T0 + 300 * MINUTE) == frozenset()


def test_source_ranges_snap_outward_to_the_source_grid():
    slots = SlotMap("1m", MINUTE)
    slots.want("a", DemandOwner("x"), T0 + 10 * SECOND, T0 + MINUTE + 1, 0)
    assert [(s.start_ms, s.end_ms) for s in slots.missing()] == [(T0, T0 + 2 * MINUTE)]


# Pieces ------------------------------------------------------------------------

def test_piece_blocks_follow_calendar_days_and_stay_under_the_bar_limit():
    assert piece_block_ms(MINUTE) == 2 * DAY          # 2,880 1m bars, whole UTC days
    assert piece_block_ms(SECOND) == 3_600 * SECOND   # one hour of 1s bars
    assert piece_block_ms(5 * MINUTE) == 7 * DAY      # 2,016 bars
    for width in (SECOND, MINUTE, 5 * MINUTE, 89 * MINUTE):
        assert piece_block_ms(width) // width <= 4_000


def test_pieces_are_most_urgent_first_then_newest_first_and_stable_under_progress():
    owner = frozenset({DemandOwner("x")})
    segments = [Segment(T0, T0 + 5 * DAY, 3, owner), Segment(T0 + 5 * DAY, T0 + 5 * DAY + 90 * MINUTE, 0, owner)]
    pieces = cut_pieces("1m", MINUTE, segments)
    assert [(p.start_ms - T0, p.end_ms - T0, p.urgency) for p in pieces] == [
        (5 * DAY, 5 * DAY + 90 * MINUTE, 0),
        (4 * DAY, 5 * DAY, 3), (2 * DAY, 4 * DAY, 3), (0, 2 * DAY, 3),
    ]
    assert all(p.bars <= 2_880 for p in pieces)
    # After the newest block is present, the rest is cut at the same bounds.
    rest = cut_pieces("1m", MINUTE, [Segment(T0, T0 + 4 * DAY, 3, owner)])
    assert [(p.start_ms, p.end_ms) for p in rest] == [(p.start_ms, p.end_ms) for p in pieces[2:]]


def test_kinds_map_to_existing_reasons_and_priorities():
    assert kind_for_reason("initial_history") is DemandKind.FIRST_SCREEN
    assert kind_for_reason("visible_range_gap+visible_load_more") is DemandKind.PAGE_BACK
    assert kind_for_reason("tail_gap+visible_seed_gap") is DemandKind.FORMING
    assert kind_for_reason("manual_repair") is DemandKind.GAP_REPAIR
    priorities = [REQUEST_FIELDS[kind][1] for kind in sorted(DemandKind, key=URGENCY.__getitem__)]
    assert priorities == sorted(priorities)


def test_planner_is_off_by_default():
    assert planner_enabled() is False


# Planner -----------------------------------------------------------------------

def test_two_charts_on_one_symbol_fetch_their_overlap_once():
    async def run():
        executor = Recorder()
        plan = planner(executor)
        plan.register(demand("chart-89m", "89m", T0, T0 + 3 * DAY))
        plan.register(demand("chart-97m", "97m", T0 + DAY, T0 + 4 * DAY))
        await plan.drain()
        counts = opens(executor.started)
        assert set(counts.values()) == {1}
        assert min(counts) == T0 and max(counts) == T0 + 4 * DAY - MINUTE and len(counts) == 4 * 1440
        assert plan.metrics["pieces_committed"] == len(executor.started) == 2
        assert plan.snapshot()["sources"]["1m"]["missing_bars"] == 0
        await plan.close()
    asyncio.run(run())


def test_polls_that_register_the_same_demand_plan_nothing():
    async def run():
        executor = Recorder()
        plan = planner(executor)
        for _ in range(59):
            plan.register(demand("chart", "89m", T0, T0 + DAY, DemandKind.FORMING))
        await plan.drain()
        assert plan.metrics["registered"] == 1 and plan.metrics["unchanged"] == 58
        assert len(executor.started) == 1
        # Once fetched, the same demand again starts nothing.
        plan.register(demand("chart", "89m", T0, T0 + DAY, DemandKind.FORMING))
        await plan.drain()
        assert len(executor.started) == 1
        await plan.close()
    asyncio.run(run())


def test_forming_then_first_screen_then_page_back_then_the_rest():
    async def run():
        executor = Recorder(hold=True)
        plan = planner(executor, max_running=1)
        plan.register(demand("a", "89m", T0, T0 + 2 * DAY, DemandKind.PREFETCH))
        plan.register(demand("a", "89m", T0 + 2 * DAY, T0 + 4 * DAY, DemandKind.PAGE_BACK))
        plan.register(demand("a", "89m", T0 + 6 * DAY, T0 + 8 * DAY, DemandKind.FIRST_SCREEN))
        plan.register(demand("b", "1m", T0 + 4 * DAY, T0 + 6 * DAY, DemandKind.VIEWPORT))
        plan.register(demand("a", "89m", T0 + 8 * DAY, T0 + 8 * DAY + 50 * MINUTE, DemandKind.FORMING))
        await tick()
        executor.release.set()
        await plan.drain()
        assert [p.urgency for p in executor.started] == [0, 1, 2, 3, 5]
        assert executor.started[0].start_ms == T0 + 8 * DAY
        await plan.close()
    asyncio.run(run())


def test_slots_beyond_the_closed_bound_wait_for_it():
    async def run():
        executor = Recorder()
        closed = {"1m": T0 + 30 * MINUTE}
        plan = SymbolHistoryPlanner(KEY, executor=executor, source_for=source_for,
                                    closed_until=lambda source: closed[source])
        plan.register(demand("chart", "89m", T0, T0 + 89 * MINUTE, DemandKind.FORMING))
        await plan.drain()
        assert [(p.start_ms, p.end_ms) for p in executor.started] == [(T0, T0 + 30 * MINUTE)]
        closed["1m"] = T0 + 31 * MINUTE
        assert plan.register(demand("chart", "89m", T0, T0 + 89 * MINUTE, DemandKind.FORMING))
        await plan.drain()
        assert [(p.start_ms, p.end_ms) for p in executor.started][-1] == (T0 + 30 * MINUTE, T0 + 31 * MINUTE)
        await plan.close()
    asyncio.run(run())


def test_released_demand_is_not_started_and_a_running_piece_sees_it_go():
    async def run():
        executor = Recorder(hold=True)
        plan = planner(executor, max_running=1)
        plan.register(demand("old", "89m", T0, T0 + 2 * DAY, DemandKind.FIRST_SCREEN, scope="chart-1", generation=1))
        plan.register(demand("other", "89m", T0 + 4 * DAY, T0 + 6 * DAY, DemandKind.PREFETCH))
        await tick()
        assert len(executor.started) == 1
        # The chart switched symbol: generation 2 replaces generation 1.
        assert plan.advance_scope("chart-1", 2) == 1
        plan.release(DemandOwner("other"))
        executor.release.set()
        await plan.drain()
        assert executor.wanted_checks == [False]
        assert len(executor.started) == 1
        assert plan.idle
        await plan.close()
    asyncio.run(run())


def test_a_failed_piece_is_handed_back_and_not_retried_until_its_hold_expires():
    async def run():
        now = [0.0]
        executor = Recorder(fail={1})
        handed = []
        plan = planner(executor, clock=lambda: now[0], hand_back_seconds=300,
                       on_handed_back=lambda piece, ranges, error: handed.append((ranges, error)))
        plan.register(demand("chart", "89m", T0, T0 + DAY, DemandKind.FIRST_SCREEN))
        await plan.drain()
        assert handed == [([(T0, T0 + DAY)], "RuntimeError('exchange unavailable')")]
        plan.register(demand("chart", "89m", T0, T0 + DAY + MINUTE, DemandKind.FIRST_SCREEN))
        await plan.drain()
        assert [(p.start_ms, p.end_ms) for p in executor.started[1:]] == [(T0 + DAY, T0 + DAY + MINUTE)]
        now[0] = 301.0
        plan.register(demand("chart", "89m", T0, T0 + DAY + 2 * MINUTE, DemandKind.FIRST_SCREEN))
        await plan.drain()
        assert opens(executor.started[2:]) == opens([executor.started[0]]) + Counter({T0 + DAY + MINUTE: 1})
        await plan.close()
    asyncio.run(run())


def test_partial_writes_before_a_failure_are_kept():
    async def run():
        handed = []

        async def executor(piece, still_wanted):
            half = piece.start_ms + (piece.end_ms - piece.start_ms) // 2
            return PieceResult("failed", written=((piece.start_ms, half),), error="timeout")

        plan = planner(executor, on_handed_back=lambda piece, ranges, error: handed.extend(ranges))
        plan.register(demand("chart", "1m", T0, T0 + DAY))
        await plan.drain()
        assert handed == [(T0 + DAY // 2, T0 + DAY)]
        assert plan.snapshot()["sources"]["1m"]["present_ms"] == DAY // 2
        await plan.close()
    asyncio.run(run())


def test_a_revision_that_deletes_rows_makes_them_missing_again():
    async def run():
        executor = Recorder()
        plan = planner(executor)
        plan.register(demand("chart", "89m", T0, T0 + DAY))
        await plan.drain()
        plan.mark_missing("1m", [(T0 + 60 * MINUTE, T0 + 62 * MINUTE)])
        await plan.drain()
        assert [(p.start_ms, p.end_ms) for p in executor.started[1:]] == [(T0 + 60 * MINUTE, T0 + 62 * MINUTE)]
        plan.mark_present("1m", [(T0, T0 + 3 * DAY)])
        plan.register(demand("chart", "89m", T0, T0 + 3 * DAY))
        await plan.drain()
        assert len(executor.started) == 2
        await plan.close()
    asyncio.run(run())


def test_one_symbol_one_planner_and_separate_source_grids():
    async def run():
        executor = Recorder()
        registry = PlannerRegistry(lambda key: planner(executor))
        plan = registry.get(KEY)
        assert registry.get(KEY) is plan
        assert registry.get(SymbolKey("okx", "futures", "BTC-USDT-SWAP")) is not plan
        plan.register(demand("spot-90s", "90s", T0, T0 + 900 * SECOND))
        plan.register(demand("chart-89m", "89m", T0, T0 + 89 * MINUTE))
        await plan.drain()
        assert sorted(p.source_interval for p in executor.started) == ["1m", "1s"]
        plan.release(DemandOwner("spot-90s"))
        plan.release(DemandOwner("chart-89m"))
        assert registry.prune() == 2
        await registry.close()
    asyncio.run(run())


def test_a_listener_error_does_not_stop_the_planner():
    async def run():
        executor = Recorder()

        def broken(piece, result):
            raise ValueError("listener bug")

        plan = planner(executor, on_committed=broken)
        plan.register(demand("chart", "89m", T0, T0 + 5 * DAY))
        await plan.drain()
        assert plan.metrics["pieces_committed"] == 3
        await plan.close()
    asyncio.run(run())


def test_close_cancels_running_pieces():
    async def run():
        executor = Recorder(hold=True)
        plan = planner(executor)
        plan.register(demand("chart", "89m", T0, T0 + 5 * DAY))
        await tick()
        assert len(executor.started) == 2
        await plan.close()
        assert plan.snapshot()["running"] == []
        assert not plan.register(demand("chart", "89m", T0, T0 + 6 * DAY))
    asyncio.run(run())


@pytest.mark.parametrize("bad", [(T0, T0), (T0 + 1, T0)])
def test_demands_need_a_nonempty_range(bad):
    with pytest.raises(ValueError):
        demand("x", "89m", *bad)
