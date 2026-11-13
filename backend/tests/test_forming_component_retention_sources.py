"""First live prefix with real pinned source receipts and native commit owner."""
import asyncio

import ccxt.async_support as ccxt

from app.core.executors import run_storage
from app.data_engine.bar_aggregator.history_prefix_runtime import HistoryPrefixRuntime
from app.data_engine.ingestion.models import DataSource,RawMessage,StreamDescriptor,StreamType
from app.data_engine.storage import kline_sources
from app.exchanges.ccxt_ext.fork_kline import normalize_fork_kline,prepare_source_messages
from tests.test_ccxt_source_extensions import SPOT
from tests.test_closed_component_retention import Ingestion
from tests.test_shared_blocks_integration import dm


def test_source_receipts_first_live_prefix_and_covered_correction_use_native_commit(dm,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    monkeypatch.setattr(HistoryPrefixRuntime,'MIN_ROWS',64)
    monkeypatch.setattr(HistoryPrefixRuntime,'COMPACT_ROWS',4)
    exchange=ccxt.okx()
    exchange.set_markets([SPOT])
    desc=StreamDescriptor('BTC-USDT',StreamType.KLINE,interval='1m',exchange='okx',market_type='spot')
    async def source(opened,volume,*,rest=False,closed=True):
        row=[str(opened),'100','103','99','102',str(volume),'1',str(volume*101),'1' if closed else '0']
        payload=(exchange.parse_candlescope_kline(row,SPOT,'1m') if rest else
            exchange.parse_candlescope_ws_klines({'arg':{'channel':'candle1m','instId':'BTC-USDT'},'data':[row]})[0])
        message=RawMessage(payload,DataSource.HTTP_BACKFILL if rest else DataSource.WEBSOCKET,StreamType.KLINE,clock[0])
        await prepare_source_messages([message],desc,watermark=kline_sources.rest_watermark(),history_projection=rest)
        return normalize_fork_kline(message,desc)
    async def run():
        task=None
        ingestion=Ingestion()
        dm.set_ingestion_factory(ingestion)
        try:
            await dm.start()
            timer=dm.bar_aggregator._timeout_task
            timer.cancel()
            await asyncio.gather(timer,return_exceptions=True)
            dm.bar_aggregator._timeout_task=None
            await dm.ensure_stream('BTC-USDT','89m',exchange='okx',market_type='spot')
            delivery=dm.aggregator_bridge.delivery
            entered=asyncio.Event()
            original=dm.history_prefix_runtime.flush_delivery
            async def watched():
                entered.set()
                await original()
            dm.history_prefix_runtime.flush_delivery=watched
            receipts=[]
            async with delivery._dispatcher:
                for index in range(4):
                    clock[0]=(index+1)*60000+1000
                    event=await source(index*60000,100)
                    await ingestion.send(event)
                    receipts.append(event.data['source_ref'])
                state=dm.bar_aggregator.get_pipeline('89m',exchange='okx').bar_state.get_active('okx','spot','BTC-USDT',0)
                assert state._history_prefix is None and len(state.source_refs)==4
                task=asyncio.create_task(dm.history_prefix_runtime.drain_components())
                async with asyncio.timeout(5):
                    while not entered.is_set() and not task.done(): await asyncio.sleep(.01)
                assert entered.is_set() and not task.done()
                assert state._history_prefix is None and await run_storage(delivery.journal.pending_count)>0
            await task
            assert state._history_prefix is not None,dm.history_prefix_runtime.last_forming_compaction
            assert state._history_prefix.through_ms==240000 and not state.source_snapshots and not state.source_refs
            assert state.volume==400 and state.status.value=='forming'
            for receipt in receipts: kline_sources.acknowledge(receipt)
            clock[0]=301000
            await ingestion.send(await source(240000,100,closed=False))
            state.materialize_preview()
            assert state.volume==500 and len(state.source_snapshots)==1
            entered.clear()
            changed=await source(0,1,rest=True)
            async with delivery._dispatcher:
                task=asyncio.create_task(ingestion.send(changed))
                async with asyncio.timeout(5):
                    while not entered.is_set() and not task.done(): await asyncio.sleep(.01)
                assert entered.is_set() and not task.done() and state.volume==500
            await task
            kline_sources.acknowledge(changed.data['source_ref'])
            state.materialize_preview()
            assert state.volume==401 and state.status.value=='forming' and len(state.source_snapshots)==1
            assert state.tick_count==5 and state._history_prefix.complete
        finally:
            if task is not None: await asyncio.gather(task,return_exceptions=True)
            await dm.shutdown()
            await exchange.close()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())
