"""Planner pieces run as ordinary source-interval coordinator repairs (ADR-DATA-001 S5)."""
from __future__ import annotations

import asyncio

from app.data_engine.data_manager.backfill_contracts import (
    RepairOutcome, RepairReportSummary, RepairRequest, RepairWrittenRangeSummary,
)
from app.data_engine.data_manager.symbol_history import Demand, DemandKind, DemandOwner, SymbolHistoryPlanner, SymbolKey
from app.data_engine.data_manager.symbol_history.coordinator_executor import CoordinatorPieceExecutor, request_fields
from app.data_engine.data_manager.symbol_history.pieces import Piece

MINUTE = 60_000
DAY = 1440 * MINUTE
T0 = 1_764_115_200_000
KEY = SymbolKey("binance", "futures", "BTCUSDT")


class FakeCoordinator:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.outcomes: dict[str, asyncio.Future] = {}

    def trigger(self, symbol, interval, start_ms, end_ms, exchange="binance", market_type="spot", **kwargs):
        request_id = f"rq{len(self.calls) + 1}"
        self.calls.append((request_id, symbol, interval, start_ms, end_ms, exchange, market_type, kwargs))
        self.outcomes[request_id] = asyncio.get_running_loop().create_future()
        return request_id

    async def wait_for_request(self, request_id):
        return await self.outcomes[request_id]

    def finish(self, request_id, status, *, written=(), error=None, retryable=False):
        _, symbol, interval, start, end, exchange, market_type, kwargs = next(
            call for call in self.calls if call[0] == request_id)
        request = RepairRequest(symbol, interval, start, end, exchange=exchange, market_type=market_type)
        report = RepairReportSummary(
            status=status, errors=(), error_count=0, reconcile_result=None, fetch_result_count=0,
            fetched_bar_count=0, written_range_count=len(written),
            written_ranges=tuple(RepairWrittenRangeSummary(exchange, market_type, symbol, interval, a, b)
                                 for a, b in written), elapsed_ms=1)
        self.outcomes[request_id].set_result(RepairOutcome(request=request, status=status, report=report,
                                                           error=error, retryable=retryable))


def piece(urgency=1, start=T0, end=T0 + DAY):
    return Piece("p1", "1m", MINUTE, start, end, urgency, frozenset({DemandOwner("chart")}))


def test_a_piece_is_submitted_as_a_source_repair_with_inclusive_bounds_and_its_targets():
    async def run():
        coordinator = FakeCoordinator()
        targets = [{"interval": "89m", "start_ms": T0, "end_ms": T0 + 15 * 89 * MINUTE}]
        executor = CoordinatorPieceExecutor(coordinator, KEY, targets_for=lambda p: targets)
        assert executor.submit(piece(urgency=0)) == "rq1"
        _, symbol, interval, start, end, exchange, market_type, kwargs = coordinator.calls[0]
        assert (symbol, interval, exchange, market_type) == ("BTCUSDT", "1m", "binance", "futures")
        assert (start, end) == (T0, T0 + DAY - MINUTE)
        assert (kwargs["reason"], kwargs["priority"]) == ("visible_seed_gap", 5)
        assert kwargs["requester"] == "symbol_history"
        assert kwargs["metadata"]["derived_repair_targets"] == targets
        assert kwargs["metadata"]["requires_trusted_finality"] is True
    asyncio.run(run())


def test_urgency_maps_to_the_existing_reasons():
    assert [request_fields(urgency) for urgency in range(6)] == [
        ("visible_seed_gap", 5), ("initial_history", 10), ("visible_load_more", 20),
        ("visible_range_gap", 20), ("tail_gap", 25), ("active_history_hydration", 90)]


def test_outcomes_map_to_piece_results():
    async def run():
        coordinator = FakeCoordinator()
        executor = CoordinatorPieceExecutor(coordinator, KEY)
        cases = [
            ("completed", {}, ("committed", ())),
            ("completed", {"retryable": True}, ("failed", ())),
            ("partial", {"written": [(T0, T0 + 99 * MINUTE)], "error": "warmup"},
             ("failed", ((T0, T0 + 100 * MINUTE),))),
            ("cancelled", {"written": [(T0, T0)]}, ("cancelled", ((T0, T0 + MINUTE),))),
        ]
        for status, extra, (expected, written) in cases:
            handle = executor.submit(piece())
            coordinator.finish(handle, status, **extra)
            result = await executor.wait(handle, piece(), lambda: True)
            assert (result.status, result.written) == (expected, written), status
    asyncio.run(run())


def test_the_planner_hands_out_coordinator_request_ids():
    async def run():
        coordinator = FakeCoordinator()
        plan = SymbolHistoryPlanner(
            KEY, executor=CoordinatorPieceExecutor(coordinator, KEY), max_running=16,
            source_for=lambda interval: ("1m", MINUTE), closed_until=lambda source: T0 + 30 * DAY)
        ids = plan.register_now(Demand(DemandOwner("chart-89m"), "89m", T0, T0 + 4 * DAY, DemandKind.FIRST_SCREEN))
        assert ids == ["rq1", "rq2"]
        assert plan.register_now(Demand(DemandOwner("chart-97m"), "97m", T0 + DAY, T0 + 3 * DAY,
                                        DemandKind.VIEWPORT)) == ["rq1", "rq2"]
        assert len(coordinator.calls) == 2
        for request_id in ids:
            coordinator.finish(request_id, "completed")
        await plan.drain()
        assert plan.snapshot()["sources"]["1m"]["missing_bars"] == 0
        await plan.close()
    asyncio.run(run())
