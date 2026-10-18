from __future__ import annotations

import asyncio
import gc
import weakref
from typing import Any

import pytest

from app.core import gc_policy
from app.exchanges.ccxt_ext import runtime as ccxt_runtime

pytestmark = pytest.mark.skipif(
    gc_policy._untrack is None,
    reason="untracking needs CPython's PyObject_GC_UnTrack",
)


class _Owner:
    """A tracked object that is not a plain container."""


def _catalog() -> dict[str, Any]:
    shared = [f"TRD_GRP_{index}" for index in range(50)]
    return {
        f"COIN{index}/USDT": {
            "id": f"COIN{index}USDT",
            "info": {
                "permissionSets": [shared],
                "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01"}],
            },
            "limits": {"amount": {"min": 1.0, "max": None}},
            "pair": ("COIN", ["USDT"]),
            "owner": _Owner(),
        }
        for index in range(200)
    }


def test_untrack_acyclic_tree_excludes_nested_plain_containers() -> None:
    markets = _catalog()
    by_id = {market["id"]: [market] for market in markets.values()}
    market = markets["COIN7/USDT"]
    shared = market["info"]["permissionSets"][0]
    assert gc.is_tracked(markets) and gc.is_tracked(shared)

    untracked = asyncio.run(gc_policy.untrack_acyclic_tree(markets, by_id, None, "text"))

    for container in (
        markets,
        by_id,
        by_id["COIN7USDT"],
        market,
        market["info"],
        market["info"]["filters"],
        market["pair"],
        market["pair"][1],
        shared,
    ):
        assert gc.is_tracked(container) is False
    # Objects that are not plain containers keep their own GC tracking.
    assert gc.is_tracked(market["owner"]) is True
    # Per market: the market, info, permissionSets, filters, limits, pair,
    # pair[1] and its by_id list.  Dicts holding only atomic values (the
    # filter rows, ``limits["amount"]``) were never tracked, and the shared
    # list is counted once.
    assert untracked == 2 + 1 + 200 * 8


def test_untrack_acyclic_tree_yields_to_the_event_loop(monkeypatch: Any) -> None:
    monkeypatch.setattr(gc_policy, "_UNTRACK_BATCH_ITEMS", 50)
    ticks = 0

    async def run() -> None:
        nonlocal ticks
        stop = asyncio.Event()

        async def ticker() -> None:
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0)

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        started = ticks
        await gc_policy.untrack_acyclic_tree(_catalog())
        stop.set()
        await task
        assert ticks - started > 10

    asyncio.run(run())


def test_untracked_data_is_still_freed_and_dicts_retrack_on_container_insert() -> None:
    markets = _catalog()
    owner = weakref.ref(markets["COIN3/USDT"]["owner"])
    asyncio.run(gc_policy.untrack_acyclic_tree(markets))

    market = markets["COIN1/USDT"]
    assert gc.is_tracked(market) is False
    market["extra"] = [1]
    assert gc.is_tracked(market) is True

    del markets, market
    # Reference counting frees the untracked tree without a GC pass.
    assert owner() is None


def test_freeze_startup_heap_is_optional_and_undone_at_shutdown() -> None:
    baseline = gc.get_freeze_count()
    assert gc_policy.freeze_startup_heap(enabled=False) is None
    assert gc.get_freeze_count() == baseline

    survivor = [_Owner()]
    try:
        result = gc_policy.freeze_startup_heap(enabled=True)
        assert result is not None
        assert result["frozen_objects"] == gc.get_freeze_count() > baseline
        assert not any(item is survivor for item in gc.get_objects())
        assert gc_policy.gc_policy_snapshot()["startup_freeze"] == result
    finally:
        gc_policy.unfreeze_startup_heap()
    assert gc.get_freeze_count() == 0
    assert gc_policy.gc_policy_snapshot()["startup_freeze"] is None


def test_ccxt_market_tables_follow_the_untrack_setting(monkeypatch: Any) -> None:
    class Exchange:
        def __init__(self) -> None:
            self.markets = _catalog()
            self.markets_by_id = {m["id"]: [m] for m in self.markets.values()}
            self.symbols = sorted(self.markets)
            self.currencies = {"USDT": {"limits": {"withdraw": {"min": None}}, "networks": {}}}

    monkeypatch.setattr(ccxt_runtime, "GC_UNTRACK_MARKET_TABLES", False)
    exchange = Exchange()
    assert asyncio.run(ccxt_runtime.untrack_ccxt_market_tables(exchange)) == 0
    assert gc.is_tracked(exchange.markets) is True

    monkeypatch.setattr(ccxt_runtime, "GC_UNTRACK_MARKET_TABLES", True)
    assert asyncio.run(ccxt_runtime.untrack_ccxt_market_tables(exchange)) > 0
    for table in (exchange.markets, exchange.markets_by_id, exchange.symbols, exchange.currencies):
        assert gc.is_tracked(table) is False
