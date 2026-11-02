"""A former foreground observer must not keep maintenance in the foreground lane."""
import asyncio

import pytest
from app.exchanges.public_admission import current_demand, TrafficClass

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
        active_demands = []

        class Engine:
            async def run(self, **kwargs):
                calls.append(kwargs['intervals'][0])
                if len(calls) == 1:
                    active_demands.append(current_demand())
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
        assert active_demands[0].priority() == TrafficClass.INTERACTIVE
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
        if background_reason == 'background_gap_audit':
            assert active_demands[0].priority() == TrafficClass.BACKGROUND
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


def test_narrow_foreground_interest_does_not_promote_unrelated_history_chunks():
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = []

        class Engine:
            async def run(self, **kwargs):
                calls.append((kwargs['intervals'][0], kwargs['range_start_ms']))
                if len(calls) == 1:
                    entered.set()
                    await finish.wait()
                return _RepairReport(status='completed')

        dm = _DataManager()
        coordinator = BackfillCoordinator(storage=_Storage(), bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.event_bus.emit, engine=Engine(), loop=asyncio.get_running_loop(),
            max_concurrency=1, chunk_bars=1)
        async def verified(request, **kwargs):
            return {'verified_contiguous': True, 'remaining_missing_bars': 0}
        coordinator._verify_request_range = verified
        background = _request(0, 120_000, request_id='wide-persistent-history')
        background.reason, background.priority = 'background_gap_audit', 90
        parent = coordinator.request(background)
        await entered.wait()
        visible = _request(120_000, 120_000, request_id='narrow-visible-window')
        visible.reason, visible.priority = 'visible_range_gap', 20
        visible.metadata['demand_owner_id'] = 'still-visible-chart'
        assert coordinator.request(visible) == parent
        cold = _request(0, 0, request_id='cold-other-period')
        cold.interval, cold.reason, cold.priority = '5m', 'visible_range_gap', 20
        cold_id = coordinator.request(cold)
        try:
            # The running old chunk is outside the visible observer's range.
            # It remains maintenance even though another chunk of this parent
            # has current foreground demand.
            assert coordinator.snapshot()['running_chunks'] == 2
            assert (await asyncio.wait_for(coordinator.wait_for_request(cold_id), 1)).status == 'completed'
            assert calls == [('1m', 0), ('5m', 0)]
        finally:
            finish.set()
            original, _ = await asyncio.wait_for(asyncio.gather(
                coordinator.wait_for_request(parent), coordinator.wait_for_request(cold_id)), 5)
            assert original.status == 'completed'
            assert sorted(start for interval, start in calls if interval == '1m') == [0, 60_000, 120_000]

    asyncio.run(run())


@pytest.mark.parametrize("api_latest", [False, True])
def test_unscoped_narrow_foreground_does_not_promote_unrelated_history_chunks(api_latest):
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = []

        class Engine:
            async def run(self, **kwargs):
                calls.append((kwargs['intervals'][0], kwargs['range_start_ms']))
                if len(calls) == 1:
                    entered.set()
                    await finish.wait()
                return _RepairReport(status='completed')

        dm = _DataManager()
        coordinator = BackfillCoordinator(storage=_Storage(), bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.event_bus.emit, engine=Engine(), loop=asyncio.get_running_loop(),
            max_concurrency=1, chunk_bars=1)
        async def verified(request, **kwargs):
            return {'verified_contiguous': True, 'remaining_missing_bars': 0}
        coordinator._verify_request_range = verified
        background = _request(0, 120_000, request_id='wide-persistent-history')
        background.reason, background.priority = 'background_gap_audit', 90
        parent = coordinator.request(background)
        await entered.wait()
        visible = _request(120_000, 120_000, request_id='narrow-visible-window')
        visible.reason, visible.priority = 'visible_range_gap', 20
        if api_latest:
            visible.reason, visible.requester = "latest_refresh", "klines_latest"
        # Legacy caller supplies no revocable owner; range still matters.
        assert coordinator.request(visible) == parent
        cold = _request(0, 0, request_id='cold-other-period')
        cold.interval, cold.reason, cold.priority = '5m', 'visible_range_gap', 20
        cold_id = coordinator.request(cold)
        try:
            # The running old chunk is outside the visible observer's range.
            # It remains maintenance even though another chunk of this parent
            # has current foreground demand.
            assert coordinator.snapshot()['running_chunks'] == 2
            assert (await asyncio.wait_for(coordinator.wait_for_request(cold_id), 1)).status == 'completed'
            assert calls == [('1m', 0), ('5m', 0)]
        finally:
            finish.set()
            original, _ = await asyncio.wait_for(asyncio.gather(
                coordinator.wait_for_request(parent), coordinator.wait_for_request(cold_id)), 5)
            assert original.status == 'completed'
            assert sorted(start for interval, start in calls if interval == '1m') == [0, 60_000, 120_000]

    asyncio.run(run())


def test_unscoped_interest_capacity_queues_independent_parent_without_dropping_work(monkeypatch):
    import app.data_engine.data_manager.backfill_scheduler as scheduling
    monkeypatch.setattr(scheduling, '_PERSISTENT_INTEREST_LIMIT', 2)
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = []
        class Engine:
            async def run(self, **kwargs):
                calls.append(kwargs['range_start_ms'])
                if len(calls) == 1:
                    entered.set()
                    await finish.wait()
                return _RepairReport(status='completed')
        dm = _DataManager()
        coordinator = BackfillCoordinator(storage=_Storage(), bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.event_bus.emit, engine=Engine(), loop=asyncio.get_running_loop(), max_concurrency=1, chunk_bars=1)
        async def verified(request, **kwargs):
            return {'verified_contiguous': True, 'remaining_missing_bars': 0}
        coordinator._verify_request_range = verified
        background = _request(0,120_000,request_id='bounded-parent')
        background.reason, background.priority = 'background_gap_audit',90
        parent = coordinator.request(background)
        await entered.wait()
        latest = _request(120_000,120_000,request_id='narrow-latest')
        latest.reason, latest.requester, latest.priority = 'latest_refresh','klines_latest',20
        assert coordinator.request(latest) == parent
        state = coordinator._scheduler._requests[parent]
        try:
            assert len(state.persistent_scheduling) == 2
            # Exact repeats compact rather than allocating more metadata.
            for i in range(10):
                repeated = _request(120_000,120_000,request_id=f'repeated-{i}')
                repeated.reason, repeated.requester, repeated.priority = 'latest_refresh','klines_latest',20
                assert coordinator.request(repeated) == parent
            assert len(state.persistent_scheduling) == 2
            new = _request(60_000,60_000,request_id='capacity-new-parent')
            new.reason, new.priority = 'visible_range_gap',30
            independent = coordinator.request(new)
            assert independent != parent
            assert len(state.persistent_scheduling) == 2
            # Nothing was discarded or given a widened range to fit the cap.
            assert coordinator._scheduler._requests[independent].request.start_ms == 60_000
        finally:
            finish.set()
        results = await asyncio.wait_for(asyncio.gather(coordinator.wait_for_request(parent),coordinator.wait_for_request(independent)),5)
        assert all(result.status == 'completed' for result in results)
        assert calls.count(60_000) == 2
    asyncio.run(run())
