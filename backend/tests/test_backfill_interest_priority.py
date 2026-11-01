"""A former foreground observer must not keep maintenance in the foreground lane."""
import asyncio

import pytest

from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from tests.test_backfill_coordinator import _DataManager, _Storage, _RepairReport, _request


@pytest.mark.parametrize('background_reason', ['background_gap_audit', 'startup_gap_scan+latest_refresh+price_daily_open'])
@pytest.mark.parametrize('release', ['owner', 'scope', 'lease'])
@pytest.mark.parametrize('observer_first', [False, True])
@pytest.mark.parametrize('other_observer', [False, True])
def test_persistent_history_releases_foreground_reserve_after_observer_leaves(release, observer_first, other_observer, background_reason):
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = []

        class Engine:
            async def run(self, **kwargs):
                calls.append(kwargs['intervals'][0])
                if len(calls) == 1:
                    entered.set()
                    await finish.wait()
                return _RepairReport(status='completed')

        dm = _DataManager()
        coordinator = BackfillCoordinator(
            storage=_Storage(), bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.event_bus.emit, engine=Engine(),
            loop=asyncio.get_running_loop(), max_concurrency=1, chunk_bars=1,
        )
        async def verified(request, **kwargs):
            return {'verified_contiguous': True, 'remaining_missing_bars': 0}

        coordinator._verify_request_range = verified
        background = _request(0, 120_000, request_id='persistent-history')
        background.reason = background_reason
        background.requester = 'mixed'
        background.priority = 70 if 'latest_refresh' in background_reason else 90
        await coordinator.advance_demand_scope('chart-switch', 1)
        observer = _request(0, 120_000, request_id='former-chart')
        observer.reason = 'visible_range_gap'
        observer.priority = 20
        observer.metadata.update(demand_owner_id='chart-switch:1', demand_scope='chart-switch', demand_generation=1)
        first, second = (observer, background) if observer_first else (background, observer)
        background_id = coordinator.request(first)
        await entered.wait()
        assert coordinator.request(second) == background_id
        if other_observer:
            sibling = _request(0, 120_000, request_id='sibling-chart')
            sibling.priority = 30
            sibling.reason = 'visible_load_more'
            sibling.metadata.update(demand_owner_id='other-chart')
            assert coordinator.request(sibling) == background_id
        if release == 'owner':
            await coordinator.revoke_demand_owner('chart-switch:1', reason='chart_unmounted')
        elif release == 'scope':
            await coordinator.advance_demand_scope('chart-switch', 2)
        else:
            await coordinator.release_demand(background_id, owner_id='chart-switch:1', cancel_if_unobserved=True)
        if other_observer:
            active = coordinator.snapshot()['active'][0]
            assert active['demand_count'] == 1 and not active['cancel_requested']
            assert active['priority'] == 30
            await coordinator.revoke_demand_owner('other-chart', reason='other_chart_unmounted')
        cold = _request(0, 0, request_id='cold-5m')
        cold.interval = '5m'
        cold.reason = 'visible_range_gap'
        cold.priority = 20
        cold_task = asyncio.create_task(coordinator.request_and_wait(cold))
        try:
            # Existing single-lane maintenance reserve must serve the new view
            # while the old persistent history chunk is still blocked upstream.
            result = await asyncio.wait_for(asyncio.shield(cold_task), 1)
            assert result.status == 'completed'
            assert calls == ['1m', '5m']
            assert not finish.is_set()
        finally:
            finish.set()
            background_result, _ = await asyncio.wait_for(
                asyncio.gather(coordinator.wait_for_request(background_id), cold_task), 5)
            assert background_result.status == 'completed'
            assert calls.count('1m') == 3

    asyncio.run(run())


def test_remaining_api_latest_interest_keeps_its_foreground_identity():
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = []

        class Engine:
            async def run(self, **kwargs):
                calls.append(kwargs['intervals'][0])
                if len(calls) == 1:
                    entered.set()
                    await finish.wait()
                return _RepairReport(status='completed')

        dm = _DataManager()
        coordinator = BackfillCoordinator(storage=_Storage(), bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.event_bus.emit, engine=Engine(), loop=asyncio.get_running_loop(), max_concurrency=1)
        async def verified(request, **kwargs):
            return {'verified_contiguous': True, 'remaining_missing_bars': 0}
        coordinator._verify_request_range = verified
        background = _request(0, 0, request_id='shared-latest-maintenance')
        background.reason, background.priority = 'background_gap_audit', 90
        parent = coordinator.request(background)
        await entered.wait()
        latest = _request(0, 0, request_id='api-latest')
        latest.reason, latest.requester, latest.priority = 'latest_refresh', 'klines_latest', 20
        latest.metadata['demand_owner_id'] = 'latest-view'
        assert coordinator.request(latest) == parent
        other = _request(0, 0, request_id='other-view')
        other.reason, other.priority = 'visible_range_gap', 30
        other.metadata['demand_owner_id'] = 'other-view'
        assert coordinator.request(other) == parent
        await coordinator.revoke_demand_owner('other-view', reason='view_closed')
        cold = _request(0, 0, request_id='another-cold-period')
        cold.interval, cold.reason = '5m', 'visible_range_gap'
        cold_id = coordinator.request(cold)
        try:
            # Drain reserves tasks synchronously: a still-observed API latest
            # is foreground and cannot be treated as maintenance by a sibling.
            assert coordinator.snapshot()['running_chunks'] == 1
            await coordinator.revoke_demand_owner('latest-view', reason='view_closed')
            assert (await asyncio.wait_for(coordinator.wait_for_request(cold_id), 1)).status == 'completed'
        finally:
            finish.set()
            await asyncio.wait_for(asyncio.gather(coordinator.wait_for_request(parent), coordinator.wait_for_request(cold_id)), 5)

    asyncio.run(run())
