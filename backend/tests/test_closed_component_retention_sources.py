"""Pinned CCXT source receipts, original durable admission and retired corrections."""
import asyncio

import ccxt.async_support as ccxt
import pytest

from app.core.executors import run_storage
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillTask
from app.data_engine.bar_aggregator.history_prefix_runtime import HistoryPrefixRuntime
from app.data_engine.data_manager.models import DataEventType
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType
from app.data_engine.storage import kline_sources,klines_repo
from app.exchanges.ccxt_ext.fork_kline import normalize_fork_kline, prepare_source_messages
from tests.test_ccxt_source_extensions import SPOT
from tests.test_shared_blocks_integration import dm
from tests.test_closed_component_retention import Ingestion


@pytest.mark.parametrize('retire',[True,False])
def test_real_source_correction_waits_for_original_native_commit_before_refresh(dm,monkeypatch,retire):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    exchange=ccxt.okx()
    exchange.set_markets([SPOT])
    if not retire:
        dm.bar_aggregator.config.compact_closed_components=False
        monkeypatch.setattr(HistoryPrefixRuntime,'MIN_ROWS',2)
    desc=StreamDescriptor('BTC-USDT',StreamType.KLINE,interval='1m',exchange='okx',market_type='spot')
    async def source(opened,volume,*,rest=False):
        row=[str(opened),'100','103','99','102',str(volume),'1',str(volume*101),'1']
        payload=(exchange.parse_candlescope_kline(row,SPOT,'1m') if rest else
            exchange.parse_candlescope_ws_klines({'arg':{'channel':'candle1m','instId':'BTC-USDT'},'data':[row]})[0])
        message=RawMessage(payload,DataSource.HTTP_BACKFILL if rest else DataSource.WEBSOCKET,StreamType.KLINE,clock[0])
        await prepare_source_messages([message],desc,watermark=kline_sources.rest_watermark(),history_projection=rest)
        return normalize_fork_kline(message,desc)
    async def run():
        task=None
        ingestion=Ingestion()
        dm.set_ingestion_factory(ingestion)
        observed=[]
        async def receive(event): observed.append((event.event_type,event.bar.volume))
        try:
            if not retire:
                for index in range(6):
                    clock[0]=(index+1)*60000+1000
                    event=await source(index*60000,100)
                    bar=HistoricalFetcher._event_to_bar(event,BackfillTask(symbol='BTC-USDT',interval='1m',
                        exchange='okx',market_type='spot',start_ms=index*60000,end_ms=index*60000))
                    assert klines_repo.upsert_klines('BTC-USDT','1m',[bar.to_storage_dict()],exchange='okx',source='backfill')==1
                    kline_sources.acknowledge(event.data['source_ref'])
            await dm.start()
            await dm.subscribe_async(receive,symbol='BTC-USDT',interval='7m',exchange='okx',market_type='spot',
                continuity='gap_aware',preserve_updates=True,
                event_types={DataEventType.BAR_CLOSED,DataEventType.BAR_AMENDED})
            await dm.ensure_stream('BTC-USDT','7m',exchange='okx',market_type='spot')
            for index in range(0 if retire else 6,7):
                clock[0]=(index+1)*60000+1000
                event=await source(index*60000,100)
                await ingestion.send(event)
                kline_sources.acknowledge(event.data['source_ref'])
            if retire: await dm.history_prefix_runtime.drain_components()
            engine=dm.bar_aggregator.get_pipeline('7m',exchange='okx').bar_state
            state=engine.get_closed('okx','spot','BTC-USDT',0)
            assert state._history_prefix.complete
            assert len(state.source_snapshots)==(0 if retire else 1)
            assert len(state.source_refs)==(0 if retire else 1)
            assert state.volume==700
            async with asyncio.timeout(5):
                while (DataEventType.BAR_CLOSED,700) not in observed: await asyncio.sleep(.01)
            delivery=dm.aggregator_bridge.delivery
            entered=asyncio.Event()
            original=dm.history_prefix_runtime.flush_delivery
            async def watched():
                entered.set()
                await original()
            dm.history_prefix_runtime.flush_delivery=watched
            # Hold the original dispatcher, not a replacement writer. Native
            # admission can complete while canonical projection is still old.
            event=await source(0,1,rest=True)
            async with delivery._dispatcher:
                task=asyncio.create_task(ingestion.send(event))
                async with asyncio.timeout(5):
                    while not entered.is_set() and not task.done(): await asyncio.sleep(.01)
                assert entered.is_set() and not task.done()
                assert await run_storage(delivery.journal.pending_count)>0
                assert state.volume==700
            await task
            kline_sources.acknowledge(event.data['source_ref'])
            async with asyncio.timeout(5):
                while (DataEventType.BAR_AMENDED,601) not in observed: await asyncio.sleep(.01)
            assert state.volume==601 and state.status.value=='closed' and state.finality.value=='authoritative'
            assert not state.source_snapshots
            stored=dm.query_engine.storage.query_bars('BTC-USDT','7m',0,0,exchange='okx')
            assert stored[0]['volume']==601
            assert observed==[(DataEventType.BAR_CLOSED,700),(DataEventType.BAR_AMENDED,601)]
        finally:
            if task is not None: await asyncio.gather(task,return_exceptions=True)
            await dm.shutdown()
            await exchange.close()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())
