"""Exercise logical admission and actual REST sharing through the public owners."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillTask
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator, RepairRequest
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamType
from app.exchanges import bootstrap_default_adapters
from app.data_engine.backfill.input_subscriptions import input_adoption
from app.data_engine.memory_budget import MemoryBudget
from app.data_engine.storage.revisions import Acquisition, acquisition_scope
from app.exchanges.public_admission import PublicDemand, TrafficClass, public_demand, current_demand

ORIGIN = 1_700_000_040_000


async def ignore(*args,**kwargs):
    pass


class Transport:
    def __init__(self, *, page_cap=1000):
        self.requests = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.residual = asyncio.Event()
        self.page_cap = page_cap
        self.cancelled = 0
        self.demands = []

    async def http_fetch(self, request):
        self.requests.append(request)
        self.demands.append(current_demand())
        if request.symbol == 'BTCUSDT' and request.start_ms == ORIGIN:
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        else:
            self.residual.set()
        first = ((request.start_ms+59_999)//60_000)*60_000
        opens = range(first, request.end_ms+1, 60_000)
        return [RawMessage(payload=[opened, '100', '110', '90', str(100+(opened-ORIGIN)//60_000),
                    '1.5', opened+59_999, '157.5', 10, '.75', '78.75', '0'],
                source=DataSource.HTTP, stream_type=StreamType.KLINE, received_at_ms=180_000,
                endpoint='https://fapi.binance.com/fapi/v1/klines')
                for opened in list(opens)[:min(request.limit, self.page_cap)]]


def task(start, end, *, symbol='BTCUSDT', target='89m'):
    return BackfillTask(symbol=symbol, interval='1m', start_ms=ORIGIN+start, end_ms=ORIGIN+end,
        estimated_bars=(end-start)//60_000+1, exchange='binance', market_type='futures',
        metadata={'custom_interval':target})


def fetcher(transport, concurrency=3):
    bootstrap_default_adapters()
    result = HistoricalFetcher(BackfillConfig(history_archive_enabled=False,
        fetch_concurrency=concurrency, fetch_binance_futures_concurrency=concurrency,
        fetch_rate_limit_delay=0, fetch_max_retries=0), transport)
    # These tests isolate sharing from the separately tested venue quota owner.
    result.set_rate_limiter(lambda: asyncio.sleep(0))
    return result


def test_partial_cross_target_overlap_subscribes_and_fetches_only_residual():
    async def run():
        transport = Transport()
        owner = fetcher(transport)
        first = asyncio.create_task(owner.fetch([task(0, 120_000)]))
        await asyncio.wait_for(transport.started.wait(), 1)
        second = asyncio.create_task(owner.fetch([task(60_000, 180_000, target='97m')]))
        try:
            await asyncio.wait_for(transport.residual.wait(), 1)
            assert [(r.start_ms-ORIGIN, r.end_ms-ORIGIN) for r in transport.requests] == [(0,120_000),(180_000,180_000)]
            assert not second.done()
            transport.release.set()
            a, b = await asyncio.wait_for(asyncio.gather(first, second), 1)
            assert [bar.open_time-ORIGIN for bar in a[0].bars] == [0,60_000,120_000]
            assert [bar.open_time-ORIGIN for bar in b[0].bars] == [60_000,120_000,180_000]
            assert b[0].task.metadata['custom_interval'] == '97m'
            assert [bar.quote_volume for bar in b[0].bars] == [157.5]*3
            assert owner.snapshot()['input_subscriptions']['in_flight'] == 0
        finally:
            transport.release.set()
            await asyncio.gather(first, second, return_exceptions=True)
            await owner.close()
    asyncio.run(run())


def test_cancelling_one_consumer_does_not_cancel_shared_physical_input():
    async def run():
        transport = Transport()
        owner = fetcher(transport)
        first = asyncio.create_task(owner.fetch([task(0,120_000)]))
        await asyncio.wait_for(transport.started.wait(), 1)
        second = asyncio.create_task(owner.fetch([task(0,120_000,target='101m')]))
        for _ in range(10):
            await asyncio.sleep(0)
        first.cancel()
        try:
            await asyncio.gather(first, return_exceptions=True)
            assert transport.cancelled == 0
            transport.release.set()
            results = await asyncio.wait_for(second, 1)
            assert len(transport.requests) == 1
            assert len(results[0].bars) == 3
        finally:
            transport.release.set()
            await asyncio.gather(first, second, return_exceptions=True)
            await owner.close()
    asyncio.run(run())


def test_short_shared_page_does_not_fabricate_empty_history_for_a_follower():
    async def run():
        transport = Transport(page_cap=1)
        owner = fetcher(transport)
        first = asyncio.create_task(owner.fetch([task(0,120_000)]))
        await asyncio.wait_for(transport.started.wait(), 1)
        second = asyncio.create_task(owner.fetch([task(60_000,120_000,target='101m')]))
        for _ in range(10):
            await asyncio.sleep(0)
        transport.release.set()
        try:
            a,b = await asyncio.wait_for(asyncio.gather(first,second),2)
            assert [bar.open_time-ORIGIN for bar in a[0].bars] == [0,60_000,120_000]
            assert [bar.open_time-ORIGIN for bar in b[0].bars] == [60_000,120_000]
            assert not b[0].errors
        finally:
            await owner.close()
    asyncio.run(run())


def test_physical_global_slots_still_bound_independent_logical_demands():
    async def run():
        transport = Transport()
        owner = fetcher(transport,concurrency=1)
        a=asyncio.create_task(owner.fetch([task(0,120_000)]))
        await asyncio.wait_for(transport.started.wait(),1)
        b=asyncio.create_task(owner.fetch([task(0,120_000,symbol='ETHUSDT')]))
        for _ in range(10):
            await asyncio.sleep(0)
        try:
            assert len(transport.requests)==1
            assert owner.snapshot()['input_subscriptions']['in_flight']==2
            transport.release.set()
            await asyncio.wait_for(asyncio.gather(a,b),1)
            assert len(transport.requests)==2
        finally:
            transport.release.set()
            await asyncio.gather(a,b,return_exceptions=True)
            await owner.close()
    asyncio.run(run())


def test_default_coordinator_admits_every_independent_demand_before_slow_input_finishes():
    async def run():
        calls=set()
        release=asyncio.Event()
        class Engine:
            async def run(self,**kw):
                calls.add(kw['intervals'][0])
                await release.wait()
                return SimpleNamespace(status='completed',errors=[],reconcile_result=None)
        coordinator=BackfillCoordinator(storage=object(),bars_backfilled=ignore,
            emit_event=ignore,engine=Engine(),base_delay_seconds=0)
        futures=[]
        try:
            for interval in ['89m','97m','101m','10007m','103m','107m']:
                request=RepairRequest(symbol='BTCUSDT',interval=interval,start_ms=0,end_ms=0,
                    exchange='binance',market_type='futures',reason='initial_history')
                futures.append(asyncio.create_task(coordinator.request_and_wait(request)))
            for _ in range(30):
                await asyncio.sleep(0)
            assert calls=={'89m','97m','101m','10007m','103m','107m'}
            release.set()
            outcomes=await asyncio.wait_for(asyncio.gather(*futures),2)
            assert all(outcome.status=='completed' for outcome in outcomes)
        finally:
            release.set()
            await coordinator.shutdown()
    asyncio.run(run())


def test_completed_input_is_shared_until_adoption_then_released_with_its_memory():
    async def run():
        transport=Transport()
        transport.release.set()
        owner=fetcher(transport)
        budget=MemoryBudget(1_000_000)
        budget.register('history-backfill',limit_bytes=1_000_000,usage=lambda:{'estimated_bytes':0})
        owner.memory_budget=budget
        try:
            with input_adoption():
                first=await owner.fetch([task(0,120_000)])
                assert budget.snapshot()['reserved_bytes']>0
                second=await owner.fetch([task(60_000,120_000,target='97m')])
                assert len(transport.requests)==1
                second[0].bars[0].close=999
                assert first[0].bars[1].close==101
                assert owner.snapshot()['input_subscriptions']['completed_pages_awaiting_adoption']==1
            assert budget.snapshot()['reserved_bytes']==0
            assert owner.snapshot()['input_subscriptions']['in_flight']==0
            await owner.fetch([task(0,120_000)])
            assert len(transport.requests)==2, 'completed bytes must not become an unversioned cache'
        finally:
            await owner.close()
    asyncio.run(run())


@pytest.mark.parametrize('difference',['revision','finality','identity','market'])
def test_incompatible_inputs_do_not_share_permission(difference):
    async def run():
        transport=Transport()
        owner=fetcher(transport)
        first_task=task(0,120_000)
        second_task=task(0,120_000,target='97m')
        if difference=='finality':
            second_task.metadata['requires_trusted_finality']=True
        elif difference=='identity':
            second_task.metadata['series_identity']={'series_variant':'mark'}
        elif difference=='market':
            second_task.market_type='spot'
        with acquisition_scope(Acquisition(1)):
            first=asyncio.create_task(owner.fetch([first_task]))
        await asyncio.wait_for(transport.started.wait(),1)
        with acquisition_scope(Acquisition(2 if difference=='revision' else 1)):
            second=asyncio.create_task(owner.fetch([second_task]))
        try:
            for _ in range(30):
                await asyncio.sleep(0)
            assert len(transport.requests)==2
            transport.release.set()
            await asyncio.wait_for(asyncio.gather(first,second),1)
        finally:
            transport.release.set()
            await asyncio.gather(first,second,return_exceptions=True)
            await owner.close()
    asyncio.run(run())


def test_shared_input_inherits_live_priority_and_owner_cancellation_cannot_drop_it():
    async def run():
        transport=Transport()
        owner=fetcher(transport)
        background=PublicDemand(TrafficClass.BACKGROUND)
        visible=PublicDemand(TrafficClass.INTERACTIVE)
        with public_demand(background):
            first=asyncio.create_task(owner.fetch([task(0,120_000)]))
        await asyncio.wait_for(transport.started.wait(),1)
        with public_demand(visible):
            second=asyncio.create_task(owner.fetch([task(0,120_000,target='97m')]))
        try:
            for _ in range(20):
                await asyncio.sleep(0)
            assert transport.demands[0].priority()==TrafficClass.INTERACTIVE
            first.cancel()
            await asyncio.gather(first,return_exceptions=True)
            assert transport.demands[0].priority()==TrafficClass.INTERACTIVE
            assert transport.cancelled==0
            transport.release.set()
            await asyncio.wait_for(second,1)
        finally:
            transport.release.set()
            await asyncio.gather(first,second,return_exceptions=True)
            await owner.close()
    asyncio.run(run())


def test_last_consumer_cancellation_retracts_the_physical_request():
    async def run():
        transport=Transport()
        owner=fetcher(transport)
        pending=asyncio.create_task(owner.fetch([task(0,120_000)]))
        await asyncio.wait_for(transport.started.wait(),1)
        pending.cancel()
        await asyncio.gather(pending,return_exceptions=True)
        await owner.close()
        assert transport.cancelled==1
        assert owner.snapshot()['input_subscriptions']['subscriptions']==0
    asyncio.run(run())


def test_streaming_ack_releases_each_page_before_the_next_network_request():
    async def run():
        transport=Transport()
        transport.release.set()
        owner=fetcher(transport)
        owner._cfg.fetch_batch_size=2
        budget=MemoryBudget(100_000)
        budget.register('history-backfill',limit_bytes=100_000,usage=lambda:{'estimated_bytes':0})
        owner.memory_budget=budget
        counts=[]
        async def commit(page):
            counts.append(len(page.bars))
            assert budget.snapshot()['reserved_bytes']<=100_000
        try:
            result=await owner.fetch([task(0,240_000)],on_native_page=commit)
            assert counts==[2,2,1]
            assert result[0].bars_count==5
            assert budget.snapshot()['reserved_bytes']==0
            assert owner.snapshot()['input_subscriptions']['in_flight']==0
        finally:
            await owner.close()
    asyncio.run(run())


def test_same_series_independent_residual_is_admitted_before_the_older_parent_finishes():
    async def run():
        calls=[]
        started=asyncio.Event()
        release=asyncio.Event()
        independent=asyncio.Event()
        class Engine:
            async def run(self,**kw):
                calls.append(kw['range_start_ms'])
                if kw['range_start_ms']==0:
                    started.set()
                    await release.wait()
                else:
                    independent.set()
                return SimpleNamespace(status='completed',errors=[],reconcile_result=None)
        coordinator=BackfillCoordinator(storage=object(),bars_backfilled=ignore,
            emit_event=ignore,engine=Engine(),base_delay_seconds=0)
        first=asyncio.create_task(coordinator.request_and_wait(RepairRequest('BTCUSDT','1m',0,60_000)))
        await asyncio.wait_for(started.wait(),1)
        second=asyncio.create_task(coordinator.request_and_wait(RepairRequest('BTCUSDT','1m',120_000,180_000)))
        try:
            await asyncio.wait_for(independent.wait(),1)
            assert not first.done()
            release.set()
            await asyncio.wait_for(asyncio.gather(first,second),1)
            assert len(calls)==2
        finally:
            release.set()
            await coordinator.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize('keep_other_consumer',[False,True])
def test_coordinator_release_retracts_only_its_subscription(keep_other_consumer):
    async def run():
        transport=Transport()
        owner=fetcher(transport)
        class Engine:
            async def run(self,**kw):
                results=await owner.fetch([task(0,120_000,target=kw['intervals'][0])])
                assert len(results[0].bars)==3
                return SimpleNamespace(status='completed',errors=[],reconcile_result=None)
        coordinator=BackfillCoordinator(storage=object(),bars_backfilled=ignore,
            emit_event=ignore,engine=Engine(),base_delay_seconds=0)
        first_id=coordinator.request(RepairRequest('BTCUSDT','89m',0,0,
            metadata={'demand_owner_id':'first'},reason='initial_history'))
        await asyncio.wait_for(transport.started.wait(),1)
        second_id=None
        if keep_other_consumer:
            second_id=coordinator.request(RepairRequest('BTCUSDT','97m',0,0,
                metadata={'demand_owner_id':'second'},reason='initial_history'))
            for _ in range(20):
                await asyncio.sleep(0)
        try:
            await coordinator.release_demand(first_id,owner_id='first')
            cancelled=await asyncio.wait_for(coordinator.wait_for_request(first_id),1)
            assert cancelled.status=='cancelled'
            if keep_other_consumer:
                assert transport.cancelled==0
                transport.release.set()
                result=await asyncio.wait_for(coordinator.wait_for_request(second_id),1)
                assert result.status=='completed'
                assert len(transport.requests)==1
            else:
                for _ in range(10):
                    await asyncio.sleep(0)
                assert transport.cancelled==1
        finally:
            transport.release.set()
            await coordinator.shutdown()
            await owner.close()
        assert owner.snapshot()['input_subscriptions']['subscriptions']==0
    asyncio.run(run())


def test_transport_rebinding_cannot_deliver_old_shared_input():
    async def run():
        transport=Transport()
        owner=fetcher(transport)
        pending=asyncio.create_task(owner.fetch([task(0,120_000)]))
        await asyncio.wait_for(transport.started.wait(),1)
        owner.set_transport(Transport())
        transport.release.set()
        try:
            result=await asyncio.wait_for(pending,1)
            assert not result[0].bars
            assert any('binding changed' in error for error in result[0].errors)
            assert owner.snapshot()['input_subscriptions']['in_flight']==0
        finally:
            await owner.close()
    asyncio.run(run())


def test_legacy_bytes_cannot_be_reused_after_the_observed_read_head_changes():
    async def run():
        transport=Transport()
        transport.release.set()
        owner=fetcher(transport)
        try:
            with input_adoption():
                with acquisition_scope(Acquisition(1,delete_revision=0)):
                    await owner.fetch([task(0,120_000)])
                with acquisition_scope(Acquisition(2,delete_revision=0)):
                    await owner.fetch([task(0,120_000,target='97m')])
                assert len(transport.requests)==2
        finally:
            await owner.close()
    asyncio.run(run())


def test_release_before_the_first_coroutine_step_completes_without_starting_work():
    async def run():
        calls=[]
        class Engine:
            async def run(self,**kw):
                calls.append(kw)
                return SimpleNamespace(status='completed',errors=[],reconcile_result=None)
        coordinator=BackfillCoordinator(storage=object(),bars_backfilled=ignore,
            emit_event=ignore,engine=Engine(),base_delay_seconds=0)
        ident=coordinator.request(RepairRequest('BTCUSDT','89m',0,0,
            metadata={'demand_owner_id':'gone'}))
        try:
            await coordinator.release_demand(ident,owner_id='gone')
            result=await asyncio.wait_for(coordinator.wait_for_request(ident),1)
            assert result.status=='cancelled'
            assert calls==[]
            assert coordinator.snapshot()['running_chunks']==0
        finally:
            await coordinator.shutdown()
    asyncio.run(run())


def test_failed_shared_part_does_not_redownload_the_successful_residual():
    async def run():
        from app.data_engine.ingestion.transport import TransportError
        class FailsOnce(Transport):
            failed=False
            async def http_fetch(self,request):
                values=await super().http_fetch(request)
                if request.start_ms==ORIGIN and not self.failed:
                    self.failed=True
                    raise TransportError('temporary source failure')
                return values
        transport=FailsOnce()
        owner=fetcher(transport)
        owner._cfg.fetch_max_retries=1
        first=asyncio.create_task(owner.fetch([task(0,120_000)]))
        await asyncio.wait_for(transport.started.wait(),1)
        second=asyncio.create_task(owner.fetch([task(60_000,180_000,target='97m')]))
        try:
            await asyncio.wait_for(transport.residual.wait(),1)
            # Allow the residual response to finish before the shared failure.
            for _ in range(10):
                await asyncio.sleep(0)
            transport.release.set()
            a,b=await asyncio.wait_for(asyncio.gather(first,second),2)
            assert len(a[0].bars)==len(b[0].bars)==3
            assert sum(request.start_ms==ORIGIN+180_000 for request in transport.requests)==1
            assert owner.snapshot()['input_subscriptions']['registered_inputs']==0
        finally:
            transport.release.set()
            await asyncio.gather(first,second,return_exceptions=True)
            await owner.close()
    asyncio.run(run())
