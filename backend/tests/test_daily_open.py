from __future__ import annotations

import asyncio
import threading

import pytest

from app.data_engine.data_manager.daily_open import DAY_MS, DailyOpenService
from app.data_engine.data_manager.price_cache import PriceSnapshot


def _snapshot(*, day=10, second=123, fallback=99):
    return PriceSnapshot.from_any({
        "symbol": "BTCUSDT", "price": 100, "open": 90,
        "daily_open": fallback, "updated_at_ms": DAY_MS * day + second * 1000,
    })


@pytest.mark.anyio
async def test_misses_are_coalesced_and_storage_does_not_block_loop():
    entered, resume = threading.Event(), threading.Event()
    threads = []

    class Storage:
        def query_bars(self, **kwargs):
            threads.append(threading.get_ident())
            entered.set()
            assert resume.wait(3)
            return []

    service = DailyOpenService(storage_provider=Storage, backfill_trigger_provider=lambda: None)
    tasks = [asyncio.create_task(service.resolve(_snapshot())) for _ in range(20)]
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        # This code executes while the storage worker is physically blocked.
        assert not tasks[0].done()
        assert threads[0] != threading.get_ident()
    finally:
        resume.set()
    assert await asyncio.gather(*tasks) == [99] * 20
    assert len(threads) == 2
    assert service._locks.active_keys == 0


@pytest.mark.anyio
async def test_missing_data_rechecks_and_failed_repairs_retry_across_days():
    now = [0.0]
    calls, repairs = [], []
    available = [False]

    class Storage:
        def query_bars(self, **kwargs):
            calls.append(kwargs)
            return [{"open": 95}] if available[0] else []

    def repair(*args, **kwargs):
        repairs.append(args)
        if len(repairs) == 1:
            raise RuntimeError("temporary failure")

    service = DailyOpenService(storage_provider=Storage, backfill_trigger_provider=lambda: repair,
                               monotonic=lambda: now[0])
    assert await service.resolve(_snapshot(second=30)) == 99
    assert repairs == []
    assert await service.resolve(_snapshot(fallback=98)) == 98
    assert len(calls) == 2 and len(repairs) == 1
    now[0] = 2.1
    assert await service.resolve(_snapshot()) == 99
    assert len(calls) == 4 and len(repairs) == 1
    now[0] = 30.1
    assert await service.resolve(_snapshot()) == 99
    assert len(repairs) == 2
    available[0] = True
    now[0] = 32.2
    assert await service.resolve(_snapshot()) == 95
    count = len(calls)
    assert await service.resolve(_snapshot()) == 95
    assert len(calls) == count
    available[0] = False
    assert await service.resolve(_snapshot(day=11)) == 99
    assert len(calls) == count + 2 and len(repairs) == 3


@pytest.mark.anyio
async def test_daily_open_cache_and_repair_bookkeeping_are_bounded():
    class Storage:
        def query_bars(self, **kwargs):
            return []

    service = DailyOpenService(storage_provider=Storage, backfill_trigger_provider=lambda: lambda *a, **k: None,
                               max_cached_symbols=2)
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        snapshot = _snapshot()
        snapshot.symbol = symbol
        await service.resolve(snapshot)
    assert len(service._cache) == len(service._requested) == 2


@pytest.mark.anyio
async def test_cancelled_lookup_does_not_release_ownership_of_active_query():
    entered, resume = threading.Event(), threading.Event()
    calls = []

    class Storage:
        def query_bars(self, **kwargs):
            calls.append(kwargs)
            entered.set()
            assert resume.wait(3)
            return [{"open": 95}]

    service = DailyOpenService(storage_provider=Storage, backfill_trigger_provider=lambda: None)
    first = asyncio.create_task(service.resolve(_snapshot()))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        first.cancel()
        second = asyncio.create_task(service.resolve(_snapshot()))
        await asyncio.sleep(0)
        assert len(calls) == 1 and not first.done() and not second.done()
    finally:
        resume.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert await second == 95
