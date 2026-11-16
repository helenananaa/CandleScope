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


@pytest.mark.parametrize('finish', ['error', 'cancel'])
def test_callback_mutable_proof_owner_ends_on_error_or_cancellation(finish):
    async def run():
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target('BTCUSDT', '1m')
        async def readback(*args):
            return []
        agg.set_source_component_reader(readback)
        await agg.ingest_bar_input('binance', 'spot', 'BTCUSDT', '1m',
            component(0, extra={'source_ref': {'series': 'controlled-source',
                'revision': 1, 'proof': {'metadata': 'accepted'}}}), emit_events=False)
        state = agg.get_pipeline('1m').bar_state.get_closed('binance', 'spot', 'BTCUSDT', 0)
        ready, release = asyncio.Event(), asyncio.Event()
        initial = agg.memory_usage()['source_ref_estimated_bytes']

        async def consumer(event):
            key = next(iter(event.bar.source_refs))
            event.bar.source_refs[key]['proof']['metadata'] = 'x' * 1048576
            ready.set()
            await release.wait()
            raise BarDeliveryUnavailable('controlled callback failure')

        agg.publisher.on_bar_closed(consumer)
        dispatch = asyncio.create_task(agg.publisher.emit_closed(state))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            held = agg.memory_usage()
            assert held['source_ref_estimated_bytes'] - initial >= 1048500
            assert held['mutable_callback_states'] == 1
        finally:
            if finish == 'cancel':
                dispatch.cancel()
            else:
                release.set()
            with pytest.raises(asyncio.CancelledError if finish == 'cancel' else BarDeliveryUnavailable):
                await dispatch
        after = agg.memory_usage()
        assert after['mutable_callback_states'] == 0
        assert after['source_ref_estimated_bytes'] < initial + 100000
        assert all(ref['proof']['metadata'] == 'accepted' for ref in state.source_refs.values())
    asyncio.run(run())


@pytest.mark.parametrize('mutated', ['bar', 'previous_bar'])
def test_callback_nested_proof_growth_is_counted_without_changing_index_cardinality(mutated):
    from copy import deepcopy
    import gc
    import weakref

    class Payload(dict):
        pass

    async def run():
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target('BTCUSDT', '3m')
        async def readback(*args):
            return []
        agg.set_source_component_reader(readback)
        for i in range(3):
            await agg.ingest_bar_input('binance', 'spot', 'BTCUSDT', '3m',
                component(i, extra={'source_ref': {'series': 'controlled-source',
                    'revision': i+1, 'proof': {'metadata': 'accepted'}}}), emit_events=False)
        state = agg.get_pipeline('3m').bar_state.get_closed('binance', 'spot', 'BTCUSDT', 0)
        previous = deepcopy(state)
        observed = []

        async def consumer(event):
            target = getattr(event, mutated)
            before = agg.memory_usage()
            key = next(iter(target.source_refs))
            count = len(target.source_refs)
            payload = Payload(text='x' * 1048576)
            target.source_refs[key]['proof']['metadata'] = payload
            after = agg.memory_usage()
            assert len(target.source_refs) == count
            assert after['source_ref_estimated_bytes'] - before['source_ref_estimated_bytes'] >= 1048500
            observed.append(weakref.ref(payload))

        agg.publisher.on_bar_amended(consumer)
        await agg.publisher.emit_amended(state, previous)
        assert observed
        assert all(ref['proof']['metadata'] == 'accepted' for ref in state.source_refs.values())
        assert all(ref['proof']['metadata'] == 'accepted' for ref in previous.source_refs.values())
        gc.collect()
        assert observed[0]() is None
        assert agg.memory_usage()['inflight_callback_frames'] == 0
    asyncio.run(run())
