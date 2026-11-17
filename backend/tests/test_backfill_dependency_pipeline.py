"""Dependency subscription through real HTTP/CCXT, SQLite and target writers."""
import asyncio
import time
import pytest

from aiohttp import web

from app.core import config as core_config
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator, RepairRequest
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.transport import TransportLayer
from app.data_engine.interval_policy import parse_interval_ms
from app.exchanges.ccxt_ext import generic
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_reader import row, MINUTE
from tests.test_public_transport_loopback import serve, point_at_loopback


async def ignore(*args,**kwargs):
    pass


async def setup_pipeline(query,monkeypatch):
    started,release=asyncio.Event(),asyncio.Event()
    calls=[]
    async def handle(request):
        if request.path.endswith('/time'):
            return web.json_response({'serverTime':int(time.time()*1000)})
        if request.path.endswith('/exchangeInfo'):
            return web.json_response({'symbols':[dict(symbol=symbol,pair=symbol,
                contractType='PERPETUAL',status='TRADING',baseAsset=symbol[:-4],
                quoteAsset='USDT',marginAsset='USDT',pricePrecision=2,quantityPrecision=3,
                filters=[],orderTypes=['LIMIT','MARKET']) for symbol in ['BTCUSDT','ETHUSDT']]})
        assert request.path=='/fapi/v1/klines'
        symbol=request.query['symbol']
        width=parse_interval_ms(request.query['interval'])
        first,last=int(request.query['startTime']),int(request.query['endTime'])
        first=(first+width-1)//width*width
        calls.append((symbol,request.query['interval'],first,last))
        if symbol=='BTCUSDT' and first==0:
            started.set()
            await release.wait()
        units=width//MINUTE
        return web.json_response([[at,'100','102','99','101',str(units),at+width-1,
            str(2*units),units,str(units),str(2*units),'0']
            for at in list(range(first,last+1,width))[:int(request.query['limit'])]])
    runner,origin=await serve(handle)
    original=generic._create_exchange
    def create(*args,**kwargs):
        exchange=original(*args,**kwargs)
        point_at_loopback(exchange,origin)
        return exchange
    monkeypatch.setattr(generic,'_create_exchange',create)
    ingestion=IngestionConfig(proxy_mode='none',proxy_egress_group='dependency-loopback')
    transport=TransportLayer(ingestion)
    engine=engine_for(query)
    engine._fetcher=HistoricalFetcher(engine.config,transport,ingestion)
    coordinator=BackfillCoordinator(storage=query.storage,bars_backfilled=ignore,
        emit_event=ignore,engine=engine,base_delay_seconds=0,max_retries=5,
        max_concurrency=core_config.BACKFILL_COORDINATOR_MAX_CONCURRENCY)
    return coordinator,engine,transport,runner,started,release,calls


def request(period,symbol='BTCUSDT'):
    return RepairRequest(symbol,f'{period}m',0,0,exchange='binance',market_type='futures',
        reason='initial_history',requester='klines_range',metadata={
            'requires_trusted_finality':True,'history_calendar_id':'crypto.24x7.utc'})


def test_three_target_periods_share_inflight_native_inputs_and_keep_source_fences(mixed_query,monkeypatch):
    async def run():
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        tasks=[]
        try:
            tasks.append(asyncio.create_task(coordinator.request_and_wait(request(89))))
            await asyncio.wait_for(started.wait(),5)
            tasks.extend(asyncio.create_task(coordinator.request_and_wait(request(period))) for period in [97,101])
            deadline=asyncio.get_running_loop().time()+5
            while engine.fetcher.snapshot()['input_subscriptions']['shared_page_subscriptions']<2:
                assert asyncio.get_running_loop().time()<deadline
                await asyncio.sleep(.01)
            release.set()
            results=await asyncio.wait_for(asyncio.gather(*tasks),20)
            assert all(result.status=='completed' for result in results),[result.error for result in results]
            for period in [89,97,101]:
                result=mixed_query.query('BTCUSDT',f'{period}m',start_ms=0,end_ms=period*MINUTE-1,
                    market_type='futures',limit=1,min_revision=mixed_query.storage.revision_store.head())
                assert result.complete and result.bars[0].trusted_final
                bar=result.bars[0]
                assert (bar.open,bar.high,bar.low,bar.close,bar.volume,bar.quote_volume,
                    bar.trades,bar.taker_buy_base,bar.taker_buy_quote)==(
                    100,102,99,101,period,2*period,period,period,2*period)
            # Existing canonical input reuse handles completed siblings on
            # retry; the in-flight book handles those not yet committed.
            opens=[at for symbol,interval,first,last in calls if interval=='1m'
                   for at in range(first,last+1,MINUTE)]
            assert len(opens)==len(set(opens))==101,calls
            assert engine.fetcher.snapshot()['input_subscriptions']['in_flight']==0
        finally:
            release.set()
            await coordinator.shutdown()
            await engine.close()
            await transport.stop()
            await server.cleanup()
    asyncio.run(run())


def test_local_input_adoption_completes_while_another_chart_waits_on_http(mixed_query,monkeypatch):
    async def run():
        # Deliberately seeded component test; not a cold performance claim.
        mixed_query.storage.upsert_bars('ETHUSDT','1m',[row(at,MINUTE) for at in range(0,97*MINUTE,MINUTE)],
            source='backfill',market_type='futures')
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        pending=asyncio.create_task(coordinator.request_and_wait(request(89)))
        try:
            await asyncio.wait_for(started.wait(),5)
            result=await asyncio.wait_for(coordinator.request_and_wait(request(97,'ETHUSDT')),5)
            assert result.status=='completed',result.error
            assert not pending.done()
            assert all(symbol=='BTCUSDT' for symbol,_,_,_ in calls)
            target=mixed_query.query('ETHUSDT','97m',start_ms=0,end_ms=97*MINUTE-1,
                market_type='futures',limit=1,min_revision=mixed_query.storage.revision_store.head())
            assert target.complete and target.bars[0].volume==97
            release.set()
            assert (await asyncio.wait_for(pending,10)).status=='completed'
        finally:
            release.set()
            await coordinator.shutdown()
            await engine.close()
            await transport.stop()
            await server.cleanup()
    asyncio.run(run())


@pytest.mark.parametrize('deleted_interval',['1m','89m'])
def test_retried_shared_inputs_cannot_renew_permission_after_a_delete(mixed_query,monkeypatch,deleted_interval):
    async def run():
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        pending=asyncio.create_task(coordinator.request_and_wait(request(89)))
        try:
            await asyncio.wait_for(started.wait(),5)
            mixed_query.storage.delete_bars('BTCUSDT',deleted_interval,0,0,
                exchange='binance',market_type='futures')
            release.set()
            result=await asyncio.wait_for(pending,15)
            assert result.status!='completed'
            assert mixed_query.storage.count_bars('BTCUSDT',deleted_interval,0,0,market_type='futures')==0
            assert engine.fetcher.snapshot()['input_subscriptions']['registered_inputs']==0
        finally:
            release.set()
            await coordinator.shutdown()
            await engine.close()
            await transport.stop()
            await server.cleanup()
    asyncio.run(run())


def test_real_pipeline_resumes_after_local_memory_backpressure(mixed_query,monkeypatch):
    async def run():
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        coordinator._max_retries=1
        budget=engine.memory_budget
        capacity=budget.snapshot()['owners']['history-backfill']['limit_bytes']
        lease=budget.reserve('history-backfill',capacity)
        lease.__enter__()
        task=None
        try:
            task=asyncio.create_task(coordinator.request_and_wait(request(89)))
            deadline=asyncio.get_running_loop().time()+10
            while not coordinator.snapshot()['capacity_waiting_chunks']:
                assert not task.done(),task.result() if task.done() else None
                assert asyncio.get_running_loop().time()<deadline
                await asyncio.sleep(.01)
            assert not calls and coordinator.snapshot()['running_chunks']==0
            lease.__exit__(None,None,None)
            release.set()
            outcome=await asyncio.wait_for(task,20)
            assert outcome.status=='completed' and outcome.attempts==1,outcome.error
            result=mixed_query.query('BTCUSDT','89m',start_ms=0,end_ms=89*MINUTE-1,
                market_type='futures',limit=1,min_revision=mixed_query.storage.revision_store.head())
            assert result.complete and result.bars[0].trusted_final and result.bars[0].trades==89
        finally:
            lease.__exit__(None,None,None)
            release.set()
            await coordinator.shutdown()
            if task is not None:
                await asyncio.gather(task,return_exceptions=True)
            await engine.close()
            await transport.stop()
            await server.cleanup()
    asyncio.run(run())


def test_repeated_typed_view_rejections_reuse_received_input_until_canonical_adoption(mixed_query,monkeypatch):
    from app.data_engine.storage.revisions import StaleAcquisition
    async def run():
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        coordinator._max_retries=1
        rejected=[]
        original=engine.reconciler.reconcile
        async def reconcile(*args,**kwargs):
            if len(rejected)<4:
                rejected.append(True)
                raise StaleAcquisition('injected optimistic view rejection',
                    details={'reason':'canonical_window_changed'})
            return await original(*args,**kwargs)
        monkeypatch.setattr(engine.reconciler,'reconcile',reconcile)
        release.set()
        try:
            outcome=await asyncio.wait_for(coordinator.request_and_wait(request(89)),20)
            assert outcome.status=='completed' and outcome.attempts==1,outcome.error
            assert len(rejected)==4 and len(calls)==1,calls
            result=mixed_query.query('BTCUSDT','89m',start_ms=0,end_ms=89*MINUTE-1,
                market_type='futures',limit=1,min_revision=mixed_query.storage.revision_store.head())
            assert result.complete and result.bars[0].trusted_final and result.bars[0].trades==89
        finally:
            await coordinator.shutdown()
            await engine.close()
            await transport.stop()
            await server.cleanup()
    asyncio.run(run())


@pytest.mark.parametrize('loop_kind',['asyncio','uvloop'])
def test_saturated_storage_executor_defers_then_completes_without_consuming_attempt(mixed_query,monkeypatch,loop_kind):
    import threading
    from app.core import executors
    from app.core.bounded_executor import BoundedExecutor
    async def run():
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        coordinator._max_retries=1
        original_pool=executors._storage_executor
        pool=BoundedExecutor('dependency-saturation-test',max_workers=1,max_pending=0)
        held_started,held_release=threading.Event(),threading.Event()
        def held():held_started.set();held_release.wait()
        occupied=pool.submit(held)
        await asyncio.to_thread(held_started.wait)
        monkeypatch.setattr(executors,'_storage_executor',pool)
        task=None
        try:
            task=asyncio.create_task(coordinator.request_and_wait(request(89)))
            deadline=asyncio.get_running_loop().time()+5
            while not any(d.get('reason')=='local_executor_admission' for d in coordinator.snapshot()['deferred']):
                assert not task.done(),task.result() if task.done() else None
                assert asyncio.get_running_loop().time()<deadline
                await asyncio.sleep(.01)
            assert not calls and coordinator.snapshot()['running_chunks']==0
            held_release.set()
            await asyncio.wrap_future(occupied)
            release.set()
            result=await asyncio.wait_for(task,20)
            assert result.status=='completed' and result.attempts==1,result.error
            assert len(calls)==1
        finally:
            held_release.set();release.set()
            await coordinator.shutdown()
            if task is not None:await asyncio.gather(task,return_exceptions=True)
            monkeypatch.setattr(executors,'_storage_executor',original_pool)
            pool.shutdown(wait=True)
            await engine.close()
            await transport.stop()
            await server.cleanup()
    factory = None if loop_kind=='asyncio' else __import__('uvloop').new_event_loop
    asyncio.run(run(),loop_factory=factory)
