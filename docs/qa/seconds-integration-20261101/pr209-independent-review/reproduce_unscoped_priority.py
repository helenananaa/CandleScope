import asyncio
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from tests.test_backfill_coordinator import _DataManager, _Storage, _RepairReport, _request
def test_unscoped_narrow_foreground_does_not_promote_unrelated_history_chunks():
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
