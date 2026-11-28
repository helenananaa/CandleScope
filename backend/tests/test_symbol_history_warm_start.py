"""Warm-start seeds and tails as per-symbol planner demand (ADR-DATA-001 S5b)."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.warm_start import AggregatorWarmStartService
from tests.test_symbol_history_router import DAY, MINUTE, NOW, TARGET, FakeCoordinator, make_router, tick

BUCKET = NOW - NOW % TARGET  # the forming 89m bucket at NOW
TAIL_FIRST = (NOW - 89 * 16 * MINUTE) - (NOW - 89 * 16 * MINUTE) % TARGET  # 89m tail: 16 target bars


class EmptyStorage:
    def query_bars(self, **kwargs):
        return []


def make_service(router_provider, legacy: list):
    aggregator = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
    aggregator.add_target("BTCUSDT", "89m", exchange="binance", market_type="futures")
    return AggregatorWarmStartService(
        cache=BarCache(), bar_aggregator=aggregator, base_interval="1m",
        storage_provider=lambda: EmptyStorage(),  # type: ignore[return-value]
        backfill_trigger_provider=lambda: lambda *args, **kwargs: legacy.append((args, kwargs)),
        history_router_provider=router_provider,
    )


async def open_chart(service, *, had_stream: bool, interval: str = "89m") -> None:
    with patch("app.data_engine.data_manager.warm_start.time.time", return_value=NOW / 1000):
        await service.seed_if_needed("BTCUSDT", interval, exchange="binance", market_type="futures",
                                     had_stream=had_stream, focus_scope="foreground")


def test_a_new_chart_s_seed_and_tail_are_forming_and_tail_demand_fetched_once():
    async def run():
        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        legacy: list = []
        service = make_service(lambda: router, legacy)
        await open_chart(service, had_stream=False)

        assert legacy == []  # neither the seed nor the tail went to its own repair
        pieces = coordinator.pieces()
        by_priority = {call["priority"]: call for call in pieces}
        # The forming bucket's closed components first (forming, priority 5), then the tail
        # back to its first target bucket (tail, priority 25): one 1m lane, no overlap.
        assert sorted(by_priority) == [5, 25] and len(pieces) == 2
        forming, tail = by_priority[5], by_priority[25]
        assert (forming["reason"], forming["start_ms"], forming["end_ms"]) == ("visible_seed_gap", BUCKET, NOW - MINUTE)
        assert (tail["reason"], tail["start_ms"], tail["end_ms"]) == ("tail_gap", TAIL_FIRST, BUCKET - MINUTE)
        assert {call["requester"] for call in pieces} == {"symbol_history"}

        # A served seed needs no target run: the next /klines/latest poll seeds from storage.
        coordinator.finish(forming["id"])
        await tick()
        assert coordinator.targets() == [] and router.metrics["served_forming"] == 1

        # The served tail is the existing tail rebuild, now with its base present.
        coordinator.finish(tail["id"])
        await tick()
        [target] = coordinator.targets()
        assert target["interval"] == "89m" and target["requester"] == "warm_start_custom_tail"
        assert (target["reason"], target["priority"]) == ("tail_gap", 25)
        metadata = target["metadata"]
        assert metadata["had_stream"] is False and metadata["focus_scope"] == "foreground"
        # Like the existing tail, no trusted-finality requirement: the engine reuses the stored base.
        assert "requires_trusted_finality" not in metadata
        assert metadata["symbol_history_served"] == "derive"
        # The whole tail, the forming bucket's components included (the forming piece fetched those).
        assert metadata["base_missing_range"] == {"start_ms": TAIL_FIRST, "end_ms": NOW - MINUTE}
        await router.close()
    asyncio.run(run())


def test_a_polled_seed_inside_a_running_read_adds_no_fetch():
    async def run():
        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        legacy: list = []
        service = make_service(lambda: router, legacy)
        # The chart's first screen already covers the forming bucket's components.
        ids = router.register(symbol="BTCUSDT", exchange="binance", market_type="futures", target_interval="89m",
                              base_interval="1m", start_ms=NOW - DAY, end_ms=NOW - MINUTE,
                              reason="initial_history", requester="klines_history",
                              metadata={"demand_owner_id": "pane-1"})
        assert ids and len(coordinator.pieces()) == 1
        for _ in range(3):  # /klines/latest about once a second
            await open_chart(service, had_stream=True)
        assert legacy == [] and len(coordinator.pieces()) == 1
        await router.close()
    asyncio.run(run())


def test_without_the_planner_or_off_its_routes_the_seed_and_tail_keep_their_repairs():
    async def run():
        legacy: list = []
        await open_chart(make_service(lambda: None, legacy), had_stream=False)
        assert sorted(kwargs["requester"] for _, kwargs in legacy) == [
            "warm_start_custom_seed", "warm_start_custom_tail"]

        coordinator = FakeCoordinator()
        router = make_router(coordinator, asyncio.get_running_loop())
        legacy = []
        service = make_service(lambda: router, legacy)
        service._bar_aggregator.add_target("BTCUSDT", "97m", exchange="binance", market_type="futures")
        await open_chart(service, had_stream=False, interval="97m")  # the planner does not take 97m here
        assert sorted(kwargs["requester"] for _, kwargs in legacy) == [
            "warm_start_custom_seed", "warm_start_custom_tail"]
        assert coordinator.calls == []
        await router.close()
    asyncio.run(run())
