from __future__ import annotations

import asyncio
import threading

import pytest

from app.data_engine import runtime
from app.data_engine.data_manager import DataManager, DataManagerConfig
from app.data_engine.data_manager.backfill_contracts import ScanReport
from app.data_engine.data_manager.config import PrewarmTarget


class _Storage:
    def __init__(self) -> None:
        self.list_threads: list[int] = []

    def list_series(self, custom_only: bool = False):
        assert custom_only is False
        self.list_threads.append(threading.get_ident())
        return [
            {
                "exchange": "okx",
                "market_type": "spot",
                "symbol": "ETH-USDT",
                "interval": "5m",
            }
        ]


class _FailingStorage:
    def list_series(self, custom_only: bool = False):
        raise RuntimeError("database is locked")


def _data_manager(storage) -> DataManager:
    cfg = DataManagerConfig()
    cfg.coordinator.prewarm_targets = [
        PrewarmTarget(symbol="BTC-USDT", exchange="okx", market_type="spot")
    ]
    cfg.coordinator.prewarm_intervals = {"1m": 1}

    dm = DataManager(cfg)
    dm.set_storage(storage)
    dm.bar_aggregator.add_target("SOL-USDT", "15m", exchange="okx", market_type="spot")
    return dm


def test_data_manager_gap_audit_series_includes_prewarm_active_and_storage() -> None:
    dm = _data_manager(_Storage())

    assert dm.gap_audit_series() == [
        ("okx", "spot", "BTC-USDT", "1m"),
        ("okx", "spot", "ETH-USDT", "5m"),
        ("okx", "spot", "SOL-USDT", "15m"),
    ]
    assert dm.gap_audit_tail_series() == [
        ("okx", "spot", "BTC-USDT", "1m"),
        ("okx", "spot", "SOL-USDT", "15m"),
    ]


def test_gap_audit_series_async_lists_storage_off_the_event_loop() -> None:
    storage = _Storage()
    dm = _data_manager(storage)

    async def scenario():
        return await dm.gap_audit_series_async(), threading.get_ident()

    series, loop_thread = asyncio.run(scenario())

    assert series == dm.gap_audit_series()
    assert storage.list_threads[0] != loop_thread


def test_gap_audit_series_keeps_tracked_series_when_storage_listing_fails() -> None:
    dm = _data_manager(_FailingStorage())
    tracked = [
        ("okx", "spot", "BTC-USDT", "1m"),
        ("okx", "spot", "SOL-USDT", "15m"),
    ]

    assert dm.gap_audit_series() == tracked
    assert asyncio.run(dm.gap_audit_series_async()) == tracked


def test_gap_audit_series_async_propagates_cancellation() -> None:
    entered = threading.Event()
    release = threading.Event()

    class _BlockingStorage:
        def list_series(self, custom_only: bool = False):
            entered.set()
            release.wait(5)
            return []

    dm = _data_manager(_BlockingStorage())

    async def scenario() -> None:
        task = asyncio.create_task(dm.gap_audit_series_async())
        await asyncio.get_running_loop().run_in_executor(None, entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_background_gap_audit_loop_awaits_async_series_listing() -> None:
    series = [("okx", "spot", "ETH-USDT", "5m")]
    tail_series = [("okx", "spot", "BTC-USDT", "1m")]

    class _DataManager:
        async def gap_audit_series_async(self):
            return series

        def gap_audit_series(self):
            raise AssertionError("the audit loop must not list storage on the loop")

        def gap_audit_tail_series(self):
            return tail_series

    class _Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[list, list]] = []
            self.audited = asyncio.Event()

        async def audit_storage_series(self, audit_series, **kwargs):
            self.calls.append((list(audit_series), list(kwargs["tail_series"])))
            self.audited.set()
            return ScanReport()

    async def scenario() -> list[tuple[list, list]]:
        coordinator = _Coordinator()
        task = asyncio.create_task(
            runtime._background_gap_audit_loop(
                _DataManager(),
                coordinator,
                initial_delay_seconds=0,
                interval_seconds=3600,
            )
        )
        await asyncio.wait_for(coordinator.audited.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return coordinator.calls

    assert asyncio.run(scenario()) == [(series, tail_series)]
