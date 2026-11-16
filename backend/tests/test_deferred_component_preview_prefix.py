"""Scheduled previews consume the same fenced H127 owner as source inputs."""
import asyncio
from dataclasses import replace
import threading

import pytest

from app.data_engine.bar_aggregator.models import BarEventType
from app.data_engine.data_manager.history_prefix import HistoryPrefixReader
from tests.test_history_prefix_retention import setup,component,KEY,TARGET,WIDTH
from tests.test_shared_blocks_integration import dm


async def pending(agg,runtime,rows):
    assert await runtime.seed(KEY,TARGET,0,64*WIDTH)
    await agg.start()
    agg.publisher.set_update_throttle_ms(1000)
    for i in range(1,5):
        value=replace(component(rows[64],False),sequence=i,volume=65+i,quote_volume=(65+i)*2)
        await agg.ingest_bar_input(KEY.exchange,KEY.market_type,KEY.symbol,TARGET,value)
    state=agg.get_pipeline(TARGET).bar_state.get_active(KEY.exchange,KEY.market_type,KEY.symbol,0)
    assert state._preview_dirty
    return state


def owned(dm,setup):
    rows,_,_,recovery,_,_=setup
    agg=dm.bar_aggregator
    agg.add_target(KEY.symbol,TARGET,exchange=KEY.exchange,market_type=KEY.market_type)
    runtime=dm.history_prefix_runtime
    runtime.require_recovery=recovery.append
    def current():
        return agg.get_bucket_state(KEY.symbol,TARGET,0,exchange=KEY.exchange,market_type=KEY.market_type)
    return rows,agg,runtime,recovery,current


@pytest.mark.parametrize('deletion',['first','all'])
def test_timer_revalidates_deleted_prefix_before_publishing_without_another_input(dm,setup,monkeypatch,deletion):
    rows,agg,runtime,recovery,current=owned(dm,setup)
    clock=[5000*60.]
    monkeypatch.setattr('time.time',lambda:clock[0])
    observed=[]
    async def observe(event): observed.append((event.event_type,event.bar.volume,event.bar.finality))
    agg.publisher.on_bar_event(observe)
    async def run():
        try:
            state=await pending(agg,runtime,rows)
            before=len(observed)
            old_volume=sum(row.volume for row in rows[:64])+69
            dm.query_engine.storage.delete_bars(KEY.symbol,KEY.interval,start_ms=0,
                end_ms=0 if deletion=='first' else 63*WIDTH,market_type=KEY.market_type)
            clock[0]+=2
            next(iter(agg._previews.pending.values())).due=asyncio.get_running_loop().time()
            await agg._previews._drain()
            assert not agg._previews.pending and not agg._previews.inflight
            if deletion=='first':
                result=current()
                assert result.volume==old_volume-rows[0].volume
                assert result.finality.value=='provisional'
                assert all(value!=old_volume for kind,value,_ in observed[before:] if kind==BarEventType.UPDATED)
            else:
                assert current() is None and recovery
                assert not any(kind==BarEventType.UPDATED for kind,_,_ in observed[before:])
            assert dm.query_engine.storage.count_bars(KEY.symbol,KEY.interval,0,0,market_type=KEY.market_type)==0
        finally:
            await agg.stop()
            await runtime.close()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_detach_and_cancel_drain_physical_validation_with_owned_payload_still_accounted(dm,setup,monkeypatch):
    rows,agg,runtime,recovery,current=owned(dm,setup)
    clock=[5000*60.]
    monkeypatch.setattr('time.time',lambda:clock[0])
    entered,released=threading.Event(),threading.Event()
    original=HistoryPrefixReader.validate_bound
    block=[False]
    def held(self,*args,**kwargs):
        if block[0]:
            entered.set()
            assert released.wait(10)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(HistoryPrefixReader,'validate_bound',held)
    observed=[]
    async def observe(event): observed.append(event.event_type)
    agg.publisher.on_bar_event(observe)
    async def run():
        task=stop=None
        try:
            state=await pending(agg,runtime,rows)
            count=len(observed)
            block[0]=True
            clock[0]+=2
            next(iter(agg._previews.pending.values())).due=asyncio.get_running_loop().time()
            agg._previews._wake()
            task=agg._previews.task
            async with asyncio.timeout(5):
                while not entered.is_set(): await asyncio.sleep(.01)
            agg.remove_target(KEY.symbol,TARGET,exchange=KEY.exchange,market_type=KEY.market_type)
            assert not agg.get_pipeline(TARGET).bar_state._active
            usage=agg.memory_usage()
            assert usage['preview_inflight']==1 and usage['preview_payload_states']==1
            assert usage['retained_payload_states']>=1 and usage['retained_components']>=1
            assert dm.memory_budget.snapshot()['reserved_bytes']>0
            stop=asyncio.create_task(agg._previews.stop())
            await asyncio.sleep(.05)
            assert not stop.done() and dm.memory_budget.snapshot()['reserved_bytes']>0
            released.set()
            await stop
            assert len(observed)==count
        finally:
            block[0]=False
            released.set()
            if stop is not None: await asyncio.gather(stop,return_exceptions=True)
            if task is not None: await asyncio.gather(task,return_exceptions=True)
            await agg.stop()
            await runtime.close()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())
