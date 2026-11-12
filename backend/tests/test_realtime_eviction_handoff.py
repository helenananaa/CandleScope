"""Engine handoff buffers have one ordered publication owner across awaits."""
import asyncio

import pytest

from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from tests.test_realtime_handoff_accounting import populated


def test_concurrent_eviction_drains_publish_each_head_once():
    async def run():
        agg,state=await populated()
        pipeline=agg.get_pipeline('97m')
        pipeline.bar_state.evicted_closed.append(state)
        entered,released=asyncio.Event(),asyncio.Event();seen=[]
        async def callback(event):
            seen.append(event.delivery_id)
            if len(seen)==1:
                entered.set();await released.wait()
        agg.publisher.on_bar_closed(callback)
        first=asyncio.create_task(agg._drain_eviction_buffers(pipeline))
        await asyncio.wait_for(entered.wait(),2)
        second=asyncio.create_task(agg._drain_eviction_buffers(pipeline))
        try:
            await asyncio.sleep(.01)
            assert len(seen)==1
        finally:
            released.set();await asyncio.gather(first,second)
        assert len(seen)==1 and not pipeline.bar_state.evicted_closed
    asyncio.run(run())


def test_source_retry_acknowledgment_does_not_publish_raw_eviction_again():
    async def run():
        agg,state=await populated(source_refs=True)
        pipeline=agg.get_pipeline('97m')
        pipeline.bar_state.evicted_closed.append(state)
        failed=True;accepted=[]
        async def callback(event):
            if failed:raise BarDeliveryUnavailable('controlled durable queue outage')
            accepted.append(event.delivery_id)
        agg.publisher.on_bar_closed(callback)
        with pytest.raises(BarDeliveryUnavailable):await agg._drain_eviction_buffers(pipeline)
        assert agg.publisher._pending_source_events
        failed=False
        await agg.publisher.retry_source_deliveries()
        await agg._drain_eviction_buffers(pipeline)
        assert len(accepted)==1
        assert not agg.publisher._pending_source_events
        assert not pipeline.bar_state.evicted_closed
    asyncio.run(run())


@pytest.mark.parametrize('source_refs',[False,True])
def test_cancelled_claim_returns_to_raw_buffer_only_without_source_retry_owner(source_refs):
    async def run():
        agg,state=await populated(source_refs=source_refs)
        pipeline=agg.get_pipeline('97m');buffer=pipeline.bar_state.evicted_closed
        buffer.append(state)
        entered,released=asyncio.Event(),asyncio.Event();accepted=[]
        async def callback(event):
            entered.set();await released.wait();accepted.append(event.delivery_id)
        agg.publisher.on_bar_closed(callback)
        task=asyncio.create_task(agg._drain_eviction_buffers(pipeline))
        await asyncio.wait_for(entered.wait(),2)
        agg.remove_target('BTCUSDT','97m')
        assert not buffer and len(pipeline.eviction_claims)==1
        assert agg.memory_usage()['buffered_handoff_states']==1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert not pipeline.eviction_claims
        assert bool(buffer) is not source_refs
        assert bool(agg.publisher._pending_source_events) is source_refs
        released.set()
        await agg.publisher.retry_source_deliveries()
        await agg._drain_eviction_buffers(pipeline)
        assert len(accepted)==1
        assert not buffer and not pipeline.eviction_claims
    asyncio.run(run())


def test_concurrent_source_retry_ack_before_original_failure_still_owns_handoff():
    async def run():
        agg,state=await populated(source_refs=True)
        pipeline=agg.get_pipeline('97m');buffer=pipeline.bar_state.evicted_closed;buffer.append(state)
        entered,released=asyncio.Event(),asyncio.Event();attempts=0;accepted=[]
        async def callback(event):
            nonlocal attempts
            attempts+=1
            if attempts==1:
                entered.set();await released.wait()
                raise BarDeliveryUnavailable('original publication resumes after retry ack')
            accepted.append(event.delivery_id)
        agg.publisher.on_bar_closed(callback)
        task=asyncio.create_task(agg._drain_eviction_buffers(pipeline))
        await asyncio.wait_for(entered.wait(),2)
        await agg.publisher.retry_source_deliveries()
        assert not agg.publisher._pending_source_events
        released.set()
        with pytest.raises(BarDeliveryUnavailable):await task
        await agg._drain_eviction_buffers(pipeline)
        assert len(accepted)==1 and attempts==2
        assert not buffer and not pipeline.eviction_claims
    asyncio.run(run())


def test_reentrant_callback_drains_later_items_without_publishing_claimed_head():
    async def run():
        from copy import deepcopy
        agg,state=await populated()
        pipeline=agg.get_pipeline('97m');buffer=pipeline.bar_state.evicted_closed
        later=deepcopy(state);later.bucket_start_ms=97*60000
        buffer.extend([state,later]);seen=[]
        async def callback(event):
            seen.append(event.bar.bucket_start_ms)
            if len(seen)==1:await agg._drain_eviction_buffers(pipeline)
        agg.publisher.on_bar_closed(callback)
        await asyncio.wait_for(agg._drain_eviction_buffers(pipeline),2)
        assert seen==[0,97*60000]
        assert not buffer and not pipeline.eviction_claims
    asyncio.run(run())


def test_pre_handoff_snapshot_failure_restores_raw_item_and_resets_observer(monkeypatch):
    async def run():
        from app.data_engine.bar_aggregator import publisher as module
        agg,state=await populated(source_refs=True)
        pipeline=agg.get_pipeline('97m');buffer=pipeline.bar_state.evicted_closed;buffer.append(state)
        original=module.deepcopy
        def fault(*args):raise MemoryError('controlled pre-handoff copy fault')
        monkeypatch.setattr(module,'deepcopy',fault)
        with pytest.raises(MemoryError):await agg._drain_eviction_buffers(pipeline)
        assert buffer==[state] and not agg.publisher._pending_source_events
        assert not pipeline.eviction_claims
        assert agg.publisher._source_handoff_observer.get() is None
        monkeypatch.setattr(module,'deepcopy',original)
        await agg._drain_eviction_buffers(pipeline)
        assert not buffer and not agg.publisher._pending_source_events
    asyncio.run(run())


def test_silent_drain_does_not_remove_another_tasks_claim():
    async def run():
        from copy import deepcopy
        agg,state=await populated();pipeline=agg.get_pipeline('97m')
        buffer=pipeline.bar_state.evicted_closed;buffer.append(state)
        entered,released=asyncio.Event(),asyncio.Event();seen=[]
        async def callback(event):
            seen.append(event.bar.bucket_start_ms);entered.set();await released.wait()
        agg.publisher.on_bar_closed(callback)
        task=asyncio.create_task(agg._drain_eviction_buffers(pipeline))
        await asyncio.wait_for(entered.wait(),2)
        later=deepcopy(state);later.bucket_start_ms=97*60000;buffer.append(later)
        await agg._drain_eviction_buffers(pipeline,emit_events=False)
        assert not buffer and len(pipeline.eviction_claims)==1
        released.set();await task
        assert seen==[0] and not pipeline.eviction_claims
    asyncio.run(run())


@pytest.mark.parametrize('expired',[False,True])
def test_actual_engine_capacity_eviction_transfers_once_to_source_retry(expired):
    async def run():
        from app.data_engine.bar_aggregator import BarAggregator,BarAggregatorConfig
        from tests.test_component_incremental import component
        agg=BarAggregator(BarAggregatorConfig(max_active_bars=1,max_closed_bars_in_memory=1,emit_expired_events=True))
        agg.add_target('BTCUSDT','97m');pipeline=agg.get_pipeline('97m');engine=pipeline.bar_state
        for bucket in range(2):
            for i in range(bucket*97,(bucket+1)*97):
                engine.apply('binance','spot','BTCUSDT',bucket*97*60000,
                    component(i,extra={'source_ref':{'series':'controlled-source','revision':i+1}}))
            if expired:engine.close_bar('binance','spot','BTCUSDT',bucket*97*60000)
        buffer=engine.evicted_expired if expired else engine.evicted_closed
        assert len(buffer)==1
        failed=True;accepted=[]
        async def callback(event):
            if failed:raise BarDeliveryUnavailable('controlled durable queue outage')
            accepted.append((event.delivery_id,event.event_type.value,event.bar.bucket_start_ms))
        if expired:agg.publisher.on_bar_expired(callback)
        else:agg.publisher.on_bar_closed(callback)
        with pytest.raises(BarDeliveryUnavailable):await agg._drain_eviction_buffers(pipeline)
        assert not buffer and agg.publisher._pending_source_events
        failed=False;await agg.publisher.retry_source_deliveries();await agg._drain_eviction_buffers(pipeline)
        assert len(accepted)==1 and accepted[0][2]==0
        assert accepted[0][1]==('bar.expired' if expired else 'bar.closed')
        assert not pipeline.eviction_claims
    asyncio.run(run())
