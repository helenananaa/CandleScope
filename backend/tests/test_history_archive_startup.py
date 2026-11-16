"""Archive qualification must not hold application readiness or leak on exit."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data_engine import runtime as runtime_module
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.source_router import HistoricalSourceRouter
from app.exchanges.archive import ArchiveCompatibilityError


@pytest.mark.anyio
async def test_runtime_becomes_ready_while_archive_probe_waits_and_cancels_before_close(monkeypatch):
    entered, cancelled = asyncio.Event(), asyncio.Event()
    events = []

    async def probe():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            events.append('probe-cancelled')
            cancelled.set()

    async def close_engine():
        assert cancelled.is_set()
        events.append('archives-closed')

    idle = MagicMock()
    idle.shutdown = AsyncMock()
    idle.stop = AsyncMock()
    idle.start = AsyncMock()
    dm = MagicMock()
    dm.start = AsyncMock(side_effect=lambda: events.append('dm-started'))
    dm.shutdown = AsyncMock()
    engine = MagicMock()
    engine.fetcher.probe_history_archives = AsyncMock(side_effect=probe)
    engine.close = AsyncMock(side_effect=close_engine)
    coordinator = MagicMock()
    coordinator.refresh_suppressions = AsyncMock()
    coordinator.shutdown = AsyncMock()
    for name in ['HistoryAvailabilityService', 'HistoryBoundaryRepository',
                 'ExchangeHistoryPolicyResolver', 'KlinesRepoAdapter', 'AsyncKlinesRepoAdapter',
                 'GapLedger', 'MarketMetricsRepository', 'MarketMetricStorageWriter']:
        monkeypatch.setattr(runtime_module, name, MagicMock())
    monkeypatch.setattr(runtime_module, 'DataManager', lambda *args, **kw: dm)
    monkeypatch.setattr(runtime_module, 'ExchangeIngestionFactory', lambda: idle)
    monkeypatch.setattr(runtime_module, 'TransportLayer', lambda *args: idle)
    monkeypatch.setattr(runtime_module, 'BackfillEngine', lambda **kw: engine)
    monkeypatch.setattr(runtime_module, 'BackfillCoordinator', lambda **kw: coordinator)
    for name in ['MarketDataService', 'PublicTradeService', '_build_trade_flow_service',
                 '_build_trade_tape_service', '_build_liquidation_service',
                 '_build_order_book_service', '_build_full_order_book_service']:
        monkeypatch.setattr(runtime_module, name, lambda *a, **kw: idle)
    for name in ['_start_raw_archive_streams', '_start_liquidation_capture_streams']:
        monkeypatch.setattr(runtime_module, name, AsyncMock())
    monkeypatch.setattr(runtime_module, '_start_subscription_workflows', AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(runtime_module, '_start_startup_gap_scan', lambda *a: None)
    monkeypatch.setattr(runtime_module, '_start_background_gap_audit', lambda *a: None)
    monkeypatch.setattr(runtime_module, 'attach_manual_history_service', lambda **kw: idle)

    # On unchanged main this times out at the awaited public probe, before
    # BackfillCoordinator wiring and DataManager.start ever take place.
    runtime = await asyncio.wait_for(runtime_module.start_data_engine(), 1)
    await asyncio.wait_for(entered.wait(), 1)
    assert events == ['dm-started']
    dm.set_backfill_trigger.assert_called_once_with(coordinator.trigger)
    assert runtime.archive_probe_task is not None and not runtime.archive_probe_task.done()
    await runtime.shutdown(step_timeout=1)
    assert events == ['dm-started', 'probe-cancelled', 'archives-closed']
    assert runtime.archive_probe_task.cancelled()


class ProbeProvider:
    id = 'controlled-probe-v1'

    def capabilities(self, market_type):
        return SimpleNamespace(probe_symbol='TEST', probe_market_type='spot', intervals=('1m',))

    def plan_objects(self, **kwargs):
        return [SimpleNamespace(start_ms=0)]

    async def resolve_objects(self, candidates, http):
        return candidates


@pytest.mark.anyio
async def test_probe_waiters_share_qualification_and_cancellation_is_independent(tmp_path, monkeypatch):
    router = HistoricalSourceRouter(BackfillConfig(history_archive_cache_dir=str(tmp_path)))
    provider = ProbeProvider()
    entered, release = asyncio.Event(), asyncio.Event()
    loads = []

    async def load(*args):
        loads.append(args)
        entered.set()
        await release.wait()
        return SimpleNamespace(bars=(1, 2))

    monkeypatch.setattr(router, '_load_object', load)
    monkeypatch.setattr(router, '_http_for', lambda *args: object())
    first = asyncio.create_task(router._probe_provider('test', provider))
    await entered.wait()
    second = asyncio.create_task(router._probe_provider('test', provider))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert provider.id not in router._probe_passed
    assert len(loads) == 1 and len(router._probe_tasks) == 1
    release.set()
    assert (await second)['enabled'] is True
    assert provider.id in router._probe_passed
    assert (await router._probe_provider('test', provider))['enabled'] is True
    assert len(loads) == 1
    await router.close()
    assert not router._probe_tasks


@pytest.mark.anyio
async def test_router_close_cancels_probe_download_and_clears_qualification_task(tmp_path, monkeypatch):
    router = HistoricalSourceRouter(BackfillConfig(history_archive_cache_dir=str(tmp_path)))
    provider = ProbeProvider()
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def load(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(router, '_load_object', load)
    monkeypatch.setattr(router, '_http_for', lambda *args: object())
    waiter = asyncio.create_task(router._probe_provider('test', provider))
    await entered.wait()
    await router.close()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert cancelled.is_set() and not router._probe_tasks
    assert provider.id not in router._probe_passed


@pytest.mark.anyio
@pytest.mark.parametrize('error', [RuntimeError('temporary network'), ArchiveCompatibilityError('wrong format')])
async def test_probe_failure_never_grants_qualification(tmp_path, monkeypatch, error):
    router = HistoricalSourceRouter(BackfillConfig(history_archive_cache_dir=str(tmp_path)))
    provider = ProbeProvider()
    monkeypatch.setattr(router, '_load_object', AsyncMock(side_effect=error))
    monkeypatch.setattr(router, '_http_for', lambda *args: object())
    result = await router._probe_provider('test', provider)
    assert result['enabled'] is False
    assert provider.id not in router._probe_passed
    if isinstance(error, ArchiveCompatibilityError):
        assert 'test' in router._disabled_providers
    else:
        assert (await router._probe_provider('test', provider))['reason'] == 'probe_retry_deferred'
    await router.close()
