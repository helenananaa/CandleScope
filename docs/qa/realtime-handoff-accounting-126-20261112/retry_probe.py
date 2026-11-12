"""Unchanged retry-release probe for full baseline and product backends."""
import asyncio
from app.data_engine.bar_aggregator import BarAggregator,BarAggregatorConfig
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from tests.test_component_incremental import component

async def populated(*,source_refs=False,agg=None):
    if agg is None:
        agg=BarAggregator(BarAggregatorConfig(finalize_timeout_ms=10**15,update_throttle_ms=0))
    agg.add_target('BTCUSDT','97m')
    async def no_prior_components(*args):return []
    if source_refs:agg.set_source_component_reader(no_prior_components)
    for index in range(97):
        value=component(index,extra={'source_ref':{'series':'source','revision':index+1}} if source_refs else {})
        await agg.ingest_bar_input('binance','spot','BTCUSDT','97m',value,emit_events=False)
    return agg,agg.get_pipeline('97m').bar_state.get_closed('binance','spot','BTCUSDT',0)


def test_source_retry_releases_acknowledged_payload_before_next_callback_awaits():
    import gc
    import weakref
    async def run():
        agg,state=await populated(source_refs=True)
        failing=True;calls=0
        entered,released=asyncio.Event(),asyncio.Event()
        async def callback(event):
            nonlocal calls
            if failing:raise BarDeliveryUnavailable('controlled outage')
            calls+=1
            if calls==2:entered.set();await released.wait()
        agg.publisher.on_bar_closed(callback)
        for _ in range(2):
            try:await agg.publisher.emit_closed(state)
            except BarDeliveryUnavailable:pass
        assert len(agg.publisher._pending_source_events)==2
        first=next(iter(agg.publisher._pending_source_events.values()))
        class WatchedIndex(dict):pass
        # BarState is slotted; observe its uniquely owned index without
        # changing any component values or the production snapshot type.
        first.bar.source_snapshots=WatchedIndex(first.bar.source_snapshots)
        retired=weakref.ref(first.bar.source_snapshots);del first
        agg.remove_target('BTCUSDT','97m')
        failing=False
        task=asyncio.create_task(agg.publisher.retry_source_deliveries())
        try:
            await asyncio.wait_for(entered.wait(),2)
            gc.collect()
            assert retired() is None,'acknowledged payload remains in a whole retry snapshot'
        finally:released.set();await task
        assert calls==2 and not agg.publisher._pending_source_events
        assert not getattr(agg.publisher,'_inflight_payloads',{})
    asyncio.run(run())

