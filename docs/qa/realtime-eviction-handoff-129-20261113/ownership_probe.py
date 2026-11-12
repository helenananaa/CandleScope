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


