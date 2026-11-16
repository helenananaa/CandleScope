"""Component/proof size must affect default realtime owner accounting."""
import asyncio

import pytest

from app.data_engine.bar_aggregator import BarAggregator,BarAggregatorConfig
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.memory_budget import MemoryBudget
from tests.test_component_incremental import component


@pytest.mark.parametrize('proof_bytes',[0,8192])
def test_detached_pending_default_component_payload_estimate_covers_registered_value_graph(proof_bytes):
    async def run():
        agg=BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target('BTCUSDT','97m')
        async def readback(*args):return []
        agg.set_source_component_reader(readback)
        for i in range(97):
            ref={'series':'controlled-source','revision':i+1}
            if proof_bytes:ref['proof']={'metadata':str(i)+':'+('x'*proof_bytes)}
            await agg.ingest_bar_input('binance','spot','BTCUSDT','97m',
                component(i,extra={'source_ref':ref}),emit_events=False)
        state=agg.get_pipeline('97m').bar_state.get_closed('binance','spot','BTCUSDT',0)
        async def unavailable(event):raise BarDeliveryUnavailable('controlled handoff outage')
        agg.publisher.on_bar_closed(unavailable)
        with pytest.raises(BarDeliveryUnavailable):await agg.publisher.emit_closed(state)
        agg.remove_target('BTCUSDT','97m')
        budget=MemoryBudget(128*1024**2)
        budget.register('realtime-state',limit_bytes=128*1024**2,usage=agg.memory_usage,roots=agg._memory_roots)
        held=budget.snapshot(measure_heap=True)['owners']['realtime-state']
        assert held['pending_source_snapshots']==1 and held['retained_components']==97
        assert held['estimated_bytes']>=held['unique_retained_bytes']
    asyncio.run(run())
