"""Chart reads' missing base ranges through the per-symbol planner (ADR-DATA-001 S5)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.backfill_contracts import (
    RepairOutcome, RepairReportSummary, RepairRequest, RepairWrittenRangeSummary,
)
from app.data_engine.data_manager.models import MissingRange, QueryResult, QuerySource
from app.data_engine.data_manager.symbol_history import router as router_module
from app.data_engine.data_manager.symbol_history.router import HistoryDemandRouter
from app.data_engine.interval_resolution import IntervalRouteKind

MINUTE = 60_000
DAY = 1440 * MINUTE
TARGET = 89 * MINUTE
T0 = 1_764_115_200_000  # on a 2-day piece block
NOW = T0 + 10 * DAY


class FakeResolver:
    def resolve(self, *, exchange, market_type, interval, purpose):
        if interval == "89m":
            return SimpleNamespace(kind=IntervalRouteKind.DERIVED, base_interval="1m")
        if interval == "90s":
            return SimpleNamespace(kind=IntervalRouteKind.DERIVED, base_interval="1s")
        return SimpleNamespace(kind=IntervalRouteKind.NATIVE, base_interval=None)


class FakeCoordinator:
    """Source pieces wait for ``finish``; target requests complete on submission."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.outcomes: dict[str, asyncio.Future] = {}
        self.listeners: list = []
        self.released: list[tuple[str, str]] = []

    async def release_demand(self, request_id, *, owner_id, cancel_if_unobserved=True, reason=""):
        self.released.append((request_id, owner_id))
        return True

    def trigger(self, symbol, interval, start_ms, end_ms, exchange="binance", market_type="spot", **kwargs):
        request_id = f"rq{len(self.calls) + 1}"
        self.calls.append(dict(id=request_id, symbol=symbol, interval=interval, start_ms=start_ms,
                               end_ms=end_ms, exchange=exchange, market_type=market_type, **kwargs))
        if interval == "1m":
            self.outcomes[request_id] = asyncio.get_running_loop().create_future()
        return request_id

    async def wait_for_request(self, request_id):
        return await self.outcomes[request_id]

    def add_demand_listener(self, listener) -> None:
        self.listeners.append(listener)

    def lease(self, request_id) -> str:
        return next(call for call in self.calls if call["id"] == request_id)["metadata"]["demand_owner_id"]

    def pieces(self) -> list[dict]:
        return [call for call in self.calls if call["interval"] == "1m"]

    def targets(self) -> list[dict]:
        return [call for call in self.calls if call["interval"] != "1m"]

    def finish(self, request_id, status="completed", *, written=(), error=None, retryable=False):
        call = next(call for call in self.calls if call["id"] == request_id)
        request = RepairRequest(call["symbol"], "1m", call["start_ms"], call["end_ms"],
                                exchange=call["exchange"], market_type=call["market_type"])
        report = RepairReportSummary(
            status=status, errors=(), error_count=0, reconcile_result=None, fetch_result_count=0,
            fetched_bar_count=0, written_range_count=len(written),
            written_ranges=tuple(RepairWrittenRangeSummary(call["exchange"], call["market_type"], call["symbol"],
                                                           "1m", a, b) for a, b in written), elapsed_ms=1)
        self.outcomes[request_id].set_result(RepairOutcome(request=request, status=status, report=report,
                                                           error=error, retryable=retryable))


def project(*, symbol, target_interval, base_interval, start_ms, end_ms, exchange, market_type):
    return {"interval": target_interval, "start_ms": start_ms - start_ms % TARGET, "end_ms": end_ms - end_ms % TARGET}


def make_router(coordinator, loop):
    return HistoryDemandRouter(coordinator, loop=loop, project_target=project, trigger_target=coordinator.trigger,
                               resolver=FakeResolver(), clock_ms=lambda: NOW)


def read(router, *, start=T0, end=T0 + 3 * DAY - MINUTE, requester="klines_history", metadata=None):
    return router.register(symbol="BTCUSDT", exchange="binance", market_type="futures", target_interval="89m",
                           base_interval="1m", start_ms=start, end_ms=end, reason="initial_history",
                           requester=requester, metadata=metadata or {"demand_owner_id": "pane-1",
                                                                      "demand_scope": "pane-1",
                                                                      "demand_generation": 3})


async def tick(rounds: int = 5) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


def test_only_single_base_chart_reads_go_to_the_planner():
    async def run():
        router = make_router(FakeCoordinator(), asyncio.get_running_loop())
        takes = lambda **kw: router.takes(**{"exchange": "binance", "market_type": "futures",  # noqa: E731
                                             "target_interval": "89m", "base_interval": "1m",
                                             "requester": "klines_history", "metadata": {}, **kw})
        assert takes()
        assert takes(requester="klines_history_before") and takes(requester="klines_range")
        assert not takes(requester="query")  # not a chart read: the engine would not reuse stored base
        # Warm-start demand (S5b): the forming bucket's components and the tail rebuild.
        assert takes(requester="warm_start_custom_seed") and takes(requester="warm_start_custom_tail")
        assert not takes(target_interval="1m", base_interval="1m")  # native
        assert not takes(base_interval="5m")  # not this interval's history base
        assert not takes(metadata={"required_history_composition": {"policy": "k130"}})
        assert not takes(metadata={"series_identity": {"provider_id": "x"}})
        assert takes(exchange="okx")
        # The engine reuses stored base only on 1m-or-wider Binance/OKX bases; elsewhere the
        # served read's target run would fetch the whole base again.
        assert not takes(exchange="binance", market_type="spot", target_interval="90s", base_interval="1s")
        assert not takes(exchange="bybit")
    asyncio.run(run())


def test_a_read_is_served_by_source_pieces_and_a_poll_adds_nothing():
    async def run():
        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        ids = read(router)
        pieces = coordinator.pieces()
        assert ids == [call["id"] for call in pieces] and len(ids) == 2
        # Newest piece first, inclusive bounds, the read's urgency, one writer lane (1m).
        assert [(call["start_ms"], call["end_ms"]) for call in pieces] == [
            (T0 + 2 * DAY, T0 + 3 * DAY - MINUTE), (T0, T0 + 2 * DAY - MINUTE)]
        assert {(call["reason"], call["priority"], call["requester"]) for call in pieces} == {
            ("initial_history", 10, "symbol_history")}
        assert all(call["metadata"]["requires_trusted_finality"] for call in pieces)
        # Each piece holds its own lease, so the scheduler can cancel it once no chart wants it.
        leases = {call["metadata"]["demand_owner_id"] for call in pieces}
        assert len(leases) == 2 and all(lease.startswith("symbol_history:binance:futures:BTCUSDT:") for lease in leases)
        assert coordinator.targets() == []

        assert sorted(read(router)) == sorted(ids)  # the chart polls: same pieces, nothing submitted
        assert len(coordinator.calls) == 2
        await router.close()
    asyncio.run(run())


def test_a_read_from_a_storage_thread_gets_the_piece_ids_from_the_loop():
    async def run():
        coordinator = FakeCoordinator()
        loop = asyncio.get_running_loop()
        router = make_router(coordinator, loop)
        ids = await loop.run_in_executor(None, lambda: read(router))
        assert ids == [call["id"] for call in coordinator.pieces()] and len(ids) == 2
        await router.close()
    asyncio.run(run())


def test_a_loop_that_does_not_answer_keeps_the_existing_path(monkeypatch):
    monkeypatch.setattr(router_module, "REGISTER_TIMEOUT_SECONDS", 0.05)
    idle_loop = asyncio.new_event_loop()  # not running while the read waits
    try:
        coordinator = FakeCoordinator()
        router = make_router(coordinator, idle_loop)
        assert read(router) is None
        assert router.metrics["fallbacks"] == 1
        # The existing path has the range now: the late callback registers nothing.
        idle_loop.run_until_complete(asyncio.sleep(0))
        assert coordinator.calls == [] and router.snapshot()["planners"] == []
    finally:
        idle_loop.close()


def test_a_read_with_nothing_to_plan_keeps_the_existing_path():
    async def run():
        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        # Only the forming slot: it belongs to the live stream, not the planner.
        assert read(router, start=NOW, end=NOW + MINUTE) is None
        assert coordinator.calls == [] and router.snapshot()["planners"][0]["demands"] == 0
        await router.close()
    asyncio.run(run())


def test_a_served_read_derives_its_target_window_once_as_a_chart_read():
    async def run():
        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        first, second = read(router)
        coordinator.finish(first)
        await tick()
        assert coordinator.targets() == []  # one piece still running: not settled
        coordinator.finish(second)
        await tick()
        [target] = coordinator.targets()
        assert target["interval"] == "89m" and target["requester"] == "klines_history"
        assert (target["start_ms"], target["end_ms"]) == (T0 - T0 % TARGET, (T0 + 3 * DAY - MINUTE)
                                                          - (T0 + 3 * DAY - MINUTE) % TARGET)
        assert (target["reason"], target["priority"]) == ("initial_history", 10)
        metadata = target["metadata"]
        assert metadata["symbol_history_served"] == "derive"
        assert metadata["derived_from"] == "1m" and metadata["requires_trusted_finality"] is True
        assert metadata["base_missing_range"] == {"start_ms": T0, "end_ms": T0 + 3 * DAY - MINUTE}
        assert (metadata["demand_owner_id"], metadata["demand_scope"], metadata["demand_generation"]) == (
            "pane-1", "pane-1", 3)
        assert router.metrics["served_derive"] == 1
        # Served: the planner forgot it; nothing more is derived or fetched.
        assert router.snapshot()["planners"][0]["demands"] == 0
        await tick()
        assert len(coordinator.calls) == 3
        await router.close()
    asyncio.run(run())


def test_a_failed_piece_is_fetched_by_the_existing_target_path_once_the_read_settles():
    async def run():
        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        first, second = read(router)
        coordinator.finish(first, "failed", error="rest timeout",
                           written=[(T0 + 2 * DAY, T0 + 2 * DAY + 99 * MINUTE)])
        await tick()
        assert coordinator.targets() == []
        coordinator.finish(second)
        await tick()
        [target] = coordinator.targets()
        assert target["metadata"]["symbol_history_served"] == "fetch_handed_back"
        assert target["requester"] == "klines_history"  # the engine reuses the stored base slots
        assert target["metadata"]["base_missing_range"] == {"start_ms": T0, "end_ms": T0 + 3 * DAY - MINUTE}
        assert router.metrics["served_with_fetch"] == 1
        # Handed-back slots are not planned again while the existing path has them.
        assert read(router) is None
        await router.close()
    asyncio.run(run())


def test_a_newer_scope_generation_releases_the_read_so_nothing_is_derived():
    async def run():
        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        first, second = read(router)
        [listener] = coordinator.listeners
        listener("scope", "pane-1", 4)
        await tick()
        # Nothing wants the pieces: their own leases go, so the scheduler may cancel them.
        assert sorted(coordinator.released) == [(first, coordinator.lease(first)), (second, coordinator.lease(second))]
        coordinator.finish(first)
        coordinator.finish(second)
        await tick()
        assert coordinator.targets() == []
        assert router.snapshot()["planners"][0]["demands"] == 0
        read(router, start=T0 + 5 * DAY, end=T0 + 5 * DAY + 59 * MINUTE,
             metadata={"demand_owner_id": "pane-2"})
        assert [planner["demands"] for planner in router.snapshot()["planners"]] == [1]
        await router.close()
    asyncio.run(run())


def test_a_revoked_owner_releases_its_reads():
    async def run():
        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        first, second = read(router)
        read(router, start=T0 + 2 * DAY, end=T0 + 2 * DAY + 59 * MINUTE, metadata={"demand_owner_id": "pane-2"})
        coordinator.listeners[0]("owner", "pane-1")
        await tick()
        # pane-2 still wants part of the newest piece: only the older piece is released.
        assert coordinator.released == [(second, coordinator.lease(second))]
        coordinator.finish(first)
        coordinator.finish(second)
        await tick()
        [target] = coordinator.targets()  # only pane-2's read is served
        assert target["metadata"]["demand_owner_id"] == "pane-2"
        await router.close()
    asyncio.run(run())


# DataManager ------------------------------------------------------------------


class StubRouter:
    def __init__(self, ids):
        self.ids = ids
        self.registered: list[dict] = []

    def takes(self, **kwargs):
        return kwargs["requester"] == "klines_history" and kwargs["base_interval"] == "15m"

    def register(self, **kwargs):
        self.registered.append(kwargs)
        return self.ids


def derived_result():
    return QueryResult(
        bars=[], symbol="BTCUSDT", interval="45m", exchange="binance", market_type="spot",
        source=QuerySource.EMPTY,
        missing_ranges=[MissingRange(symbol="BTCUSDT", interval="15m", start_ms=900_000, end_ms=1_800_000,
                                     exchange="binance", market_type="spot", reason="query_interior_gap")],
        metadata={"derived_from": "15m"},
    )


@pytest.mark.parametrize("ids, expect_trigger", [(["rq-piece-1", "rq-piece-2"], False), (None, True)])
def test_data_manager_returns_planner_piece_ids_or_keeps_the_existing_path(ids, expect_trigger):
    calls: list[tuple] = []
    dm = DataManager()
    dm.set_backfill_trigger(lambda *args, **kwargs: calls.append((args, kwargs)) or "rq-target")
    dm.set_backfill_suppression_lookup(lambda *args: None)
    router = StubRouter(ids)
    dm.set_history_router(router)

    result = dm._submit_missing_ranges(derived_result(), reason="initial_history", requester="klines_history",
                                       backfill_metadata={"demand_owner_id": "pane-1"})

    [registered] = router.registered
    assert (registered["target_interval"], registered["base_interval"]) == ("45m", "15m")
    assert (registered["start_ms"], registered["end_ms"]) == (900_000, 1_800_000)
    assert registered["metadata"] == {"demand_owner_id": "pane-1", "query_reason": "query_interior_gap"}
    assert result.backfill_triggered is True
    if expect_trigger:
        assert result.metadata["backfill_request_ids"] == ["rq-target"]
        assert calls[0][0][1] == "45m"
    else:
        assert result.metadata["backfill_request_ids"] == ["rq-piece-1", "rq-piece-2"]
        assert calls == []


def test_data_manager_keeps_other_requesters_on_the_existing_path():
    calls: list[tuple] = []
    dm = DataManager()
    dm.set_backfill_trigger(lambda *args, **kwargs: calls.append((args, kwargs)) or "rq-target")
    dm.set_backfill_suppression_lookup(lambda *args: None)
    router = StubRouter(["rq-piece-1"])
    dm.set_history_router(router)

    dm._submit_missing_ranges(derived_result(), reason="tail_gap", requester="query")

    assert router.registered == [] and len(calls) == 1


def test_data_manager_builds_the_router_on_the_coordinator():
    async def run():
        dm = DataManager()
        coordinator = FakeCoordinator()
        router = dm.enable_history_planner(coordinator, loop=asyncio.get_running_loop())
        assert dm.get_history_router() is router
        assert coordinator.listeners == [router.on_demand_event]
        await router.close()
    asyncio.run(run())
