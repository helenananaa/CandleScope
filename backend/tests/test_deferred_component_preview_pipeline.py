"""Default DataManager ingestion/router/bridge/SQLite, no alternate preview producer."""
import asyncio

import pytest

from app.data_engine.data_manager.models import DataEventType
from app.data_engine.ingestion.models import DataSource,MarketEvent,StreamType
from app.data_engine.storage import klines_repo
from tests.test_shared_blocks_integration import dm


@pytest.mark.parametrize('preserve',[False,True])
def test_default_pipeline_preserves_close_and_required_observations(dm,monkeypatch,preserve):
    clock = [88*60000+1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    klines_repo.upsert_klines('BTCUSDT','1m',[dict(open_time=i*60000,close_time=(i+1)*60000-1,
        open=10,high=20,low=5,close=11,volume=1,quote_volume=2,trades=1,taker_buy_base=1,
        taker_buy_quote=2) for i in range(88)],source='backfill',market_type='futures')
    class Ingestion:
        async def start(self,*,on_market_event,**_):
            self.send=on_market_event
            return self
        async def stop(self): pass
    ingestion=Ingestion()
    dm.set_ingestion_factory(ingestion)
    dm.bar_aggregator.publisher.set_update_throttle_ms(1000)
    observed=[]
    async def receive(event): observed.append((event.event_type,event.bar.volume))
    def market(volume,closed=False):
        return MarketEvent(event_type=StreamType.KLINE,symbol='BTCUSDT',exchange='binance',market_type='futures',
            event_time_ms=clock[0],received_at_ms=clock[0],sequence=volume,source=DataSource.WEBSOCKET,
            data=dict(interval='1m',open_time=88*60000,close_time=89*60000-1,is_closed=closed,
                open=10,high=20,low=5,close=11,volume=volume,quote_volume=volume*2,trades=volume,
                taker_buy_base=volume,taker_buy_quote=volume*2))
    async def run():
        try:
            await dm.start()
            await dm.subscribe_async(receive,symbol='BTCUSDT',interval='89m',market_type='futures',
                continuity='gap_aware',preserve_updates=preserve,
                event_types={DataEventType.BAR_UPDATED,DataEventType.BAR_CLOSED})
            await dm.ensure_stream('BTCUSDT','89m',market_type='futures')
            for value in range(1,51): await ingestion.send(market(value))
            engine=dm.bar_aggregator.get_pipeline('89m').bar_state
            state=engine.get_active('binance','futures','BTCUSDT',0)
            assert state.preview_input_version>state.preview_computed_version if not preserve else not state._preview_dirty
            if not preserve:
                assert state._preview_deferred_inputs>=40
            clock[0]=89*60000+1000
            await ingestion.send(market(51,True))
            closed=engine.get_state('binance','futures','BTCUSDT',0)
            assert closed.status.value=='closed' and closed.finality.value=='authoritative'
            assert closed.volume==139 and not closed._preview_dirty
            async with asyncio.timeout(5):
                while (DataEventType.BAR_CLOSED,139) not in observed: await asyncio.sleep(.01)
            if preserve:
                progress=[value for kind,value in observed if kind==DataEventType.BAR_UPDATED]
                assert progress[-51:]==list(range(89,140))
            stored=dm.query_engine.storage.query_bars('BTCUSDT','89m',0,0,market_type='futures')
            assert stored and stored[0]['volume']==139
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())
