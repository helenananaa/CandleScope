"""D126/R129 must count retained publisher and eviction handoff payloads."""
import asyncio
from copy import deepcopy

import pytest

from app.data_engine.bar_aggregator import BarAggregator,BarAggregatorConfig,BarEventType
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.memory_budget import MemoryBudget,MemoryBudgetExceeded,retained_size
from tests.test_component_incremental import component
from tests.test_source_revision_pipeline import database
from tests.test_kline_revision_contract import storage


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


def budget_for(agg,limit=10000):
    budget=MemoryBudget(limit)
    budget.register('realtime-state',limit_bytes=limit,usage=agg.memory_usage,roots=agg._memory_roots)
    return budget


def test_pending_source_retry_keeps_its_bytes_visible_after_target_detach():
    async def run():
        agg,state=await populated(source_refs=True)
        unavailable=True;received=[]
        async def callback(event):
            if unavailable:raise BarDeliveryUnavailable('controlled outage')
            received.append(event.bar.to_storage_dict())
        agg.publisher.on_bar_closed(callback)
        expected=state.to_storage_dict()
        with pytest.raises(BarDeliveryUnavailable):await agg.publisher.emit_closed(state)
        agg.remove_target('BTCUSDT','97m')
        assert len(agg.publisher._pending_source_events)==1
        budget=budget_for(agg)
        measured=budget.snapshot(measure_heap=True)
        assert measured['estimated_bytes']>10000
        assert measured['owners']['realtime-state']['unique_retained_bytes']>=retained_size(list(agg.publisher._pending_source_events.values()))[0]
        with pytest.raises(MemoryBudgetExceeded):
            with budget.reserve('realtime-state',1):pass
        assert len(agg.publisher._pending_source_events)==1
        unavailable=False
        await agg.publisher.retry_source_deliveries()
        assert received==[expected]
        assert not agg.publisher._pending_source_events
        assert agg.memory_usage().get('retained_payload_states',0)==0
        assert budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


@pytest.mark.parametrize('source_refs',[False,True])
@pytest.mark.parametrize('cancel',[False,True])
def test_callback_input_and_snapshot_frames_are_counted_until_completion(source_refs,cancel):
    async def run():
        agg,state=await populated(source_refs=source_refs)
        entered,released=asyncio.Event(),asyncio.Event()
        async def callback(event):
            entered.set();await released.wait()
        agg.publisher.on_bar_closed(callback)
        task=asyncio.create_task(agg.publisher.emit_closed(state))
        try:
            await asyncio.wait_for(entered.wait(),2)
            agg.remove_target('BTCUSDT','97m')
            measured=budget_for(agg).snapshot(measure_heap=True)
            usage=measured['owners']['realtime-state']
            assert usage.get('retained_payload_states',0)>=3
            assert usage['estimated_bytes']>10000 and usage['unique_retained_bytes']>10000
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):await task
            else:
                released.set();await task
        finally:
            released.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        # Cancelled durable source handoff remains a real retry obligation.
        if source_refs and cancel:
            assert agg.publisher._pending_source_events
            await agg.publisher.retry_source_deliveries()
        assert not agg.publisher._pending_source_events
        assert agg.memory_usage().get('retained_payload_states',0)==0
    asyncio.run(run())


def test_amendment_previous_and_current_frames_both_remain_accounted():
    async def run():
        agg,state=await populated()
        previous=deepcopy(state);previous.volume-=1
        entered,released=asyncio.Event(),asyncio.Event()
        async def callback(event):
            assert event.event_type==BarEventType.AMENDED
            assert event.previous_bar.volume==state.volume-1
            entered.set();await released.wait()
        agg.publisher.on_bar_amended(callback)
        task=asyncio.create_task(agg.publisher.emit_amended(state,previous))
        try:
            await asyncio.wait_for(entered.wait(),2)
            agg.remove_target('BTCUSDT','97m')
            assert agg.memory_usage().get('retained_payload_states',0)>=6
        finally:
            released.set();await task
        assert agg.memory_usage().get('retained_payload_states',0)==0
    asyncio.run(run())


def test_engine_eviction_buffers_remain_visible_after_resident_state_is_released():
    agg=BarAggregator(BarAggregatorConfig(max_closed_bars_in_memory=1))
    agg.add_target('BTCUSDT','97m')
    engine=agg.get_pipeline('97m').bar_state
    for bucket in range(2):
        for index in range(bucket*97,(bucket+1)*97):
            engine.apply('binance','spot','BTCUSDT',bucket*97*60000,component(index))
        engine.close_bar('binance','spot','BTCUSDT',bucket*97*60000)
    assert len(engine.evicted_expired)==1
    agg.remove_target('BTCUSDT','97m')
    measured=budget_for(agg).snapshot(measure_heap=True)
    assert measured['estimated_bytes']>10000
    assert measured['owners']['realtime-state'].get('retained_payload_states',0)==1
    asyncio.run(agg._drain_eviction_buffers(agg.get_pipeline('97m'),emit_events=False))
    assert not engine.evicted_expired
    assert agg.memory_usage().get('retained_payload_states',0)==0


def test_real_fork_source_and_sqlite_receipt_survive_detach_with_visible_retry_payload(monkeypatch,database):
    from tests.test_source_revision_pipeline import Harness,message,DESC
    from app.data_engine.storage import klines_repo,kline_sources
    async def run():
        harness=Harness('1m')
        agg=harness.aggregator
        journal=harness.bridge.delivery.journal
        enqueue=journal.enqueue
        adapter=klines_repo.KlinesRepoAdapter();adapter.bar_delivery=journal
        harness.bridge._storage_provider=lambda:adapter
        harness.bridge.delivery._storage_provider=lambda:adapter
        harness.bridge.delivery.retry_delay=0
        def fail(*args):raise OSError('controlled journal admission outage')
        monkeypatch.setattr(journal,'enqueue',fail)
        try:
            with pytest.raises(BarDeliveryUnavailable):await harness.ingest(message())
            assert kline_sources.pending(DESC)
            agg.remove_target('BTCUSDT','1m',market_type='futures')
            measured=budget_for(agg,65536).snapshot(measure_heap=True)['owners']['realtime-state']
            assert measured['active_bars']==measured['closed_bars']==0
            assert measured.get('pending_source_snapshots',0)==1
            assert measured.get('retained_payload_states',0)==1
            assert measured['unique_retained_bytes']>1000
            monkeypatch.setattr(journal,'enqueue',enqueue)
            await harness.pipeline.normalize.replay_source_pending()
            await harness.bridge.delivery.flush()
            assert not kline_sources.pending(DESC)
            assert not journal.pending()
            assert not agg.publisher._pending_source_events
            assert agg.memory_usage()['retained_payload_states']==0
            rows=klines_repo.query_klines('BTCUSDT','1m',market_type='futures')
            assert len(rows)==1 and rows[0]['quote_volume']==1010
        finally:await harness.close()
    asyncio.run(run())


def test_cancelling_one_publication_keeps_other_callback_frames_registered():
    async def run():
        agg,state=await populated()
        entered,released=asyncio.Event(),asyncio.Event()
        count=0
        async def callback(event):
            nonlocal count
            count+=1
            if count==2:entered.set()
            await released.wait()
        agg.publisher.on_bar_closed(callback)
        tasks=[asyncio.create_task(agg.publisher.emit_closed(state)) for _ in range(2)]
        try:
            await asyncio.wait_for(entered.wait(),2)
            agg.remove_target('BTCUSDT','97m')
            usage=agg.memory_usage()
            assert usage['retained_payload_states']==5
            assert usage['inflight_callback_frames']==2
            tasks[0].cancel()
            await asyncio.gather(tasks[0],return_exceptions=True)
            usage=agg.memory_usage()
            assert usage['retained_payload_states']==3
            assert usage['inflight_callback_frames']==1
            assert not tasks[1].done()
        finally:
            released.set()
            await asyncio.gather(*tasks,return_exceptions=True)
        assert agg.memory_usage()['retained_payload_states']==0
        assert not agg.publisher._inflight_payloads
    asyncio.run(run())


def test_aliasing_current_previous_bars_are_counted_once_per_actual_state_container():
    async def run():
        agg,state=await populated()
        entered,released=asyncio.Event(),asyncio.Event()
        async def callback(event):
            assert event.previous_bar is event.bar
            entered.set();await released.wait()
        agg.publisher.on_bar_amended(callback)
        task=asyncio.create_task(agg.publisher.emit_amended(state,state))
        try:
            await asyncio.wait_for(entered.wait(),2)
            agg.remove_target('BTCUSDT','97m')
            assert agg.memory_usage()['retained_payload_states']==3
        finally:released.set();await task
    asyncio.run(run())


def test_direct_public_event_emission_counts_owned_snapshots_without_retaining_input():
    from app.data_engine.bar_aggregator import BarEvent
    async def run():
        agg,state=await populated()
        entered,released=asyncio.Event(),asyncio.Event()
        async def callback(event):entered.set();await released.wait()
        agg.publisher.on_bar_closed(callback)
        task=asyncio.create_task(agg.publisher.emit(BarEvent(event_type=BarEventType.CLOSED,bar=state)))
        try:
            await asyncio.wait_for(entered.wait(),2)
            agg.remove_target('BTCUSDT','97m')
            usage=agg.memory_usage()
            assert usage['retained_payload_states']==2
            assert usage['inflight_input_frames']==0
        finally:released.set();await task
    asyncio.run(run())


def test_default_data_manager_budget_reports_its_own_suspended_publisher(storage):
    from app.data_engine.data_manager import DataManager
    async def run():
        dm=DataManager();dm.set_storage(storage)
        agg,state=await populated(agg=dm.bar_aggregator)
        entered,released=asyncio.Event(),asyncio.Event()
        async def callback(event):entered.set();await released.wait()
        agg.publisher.on_bar_closed(callback)
        task=asyncio.create_task(agg.publisher.emit_closed(state))
        try:
            await asyncio.wait_for(entered.wait(),2)
            agg.remove_target('BTCUSDT','97m')
            measured=dm.memory_budget.snapshot(measure_heap=True)['owners']['realtime-state']
            assert measured['retained_payload_states']==3
            assert measured['estimated_bytes']>10000 and measured['unique_retained_bytes']>10000
        finally:
            released.set();await task;await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
        assert agg.memory_usage()['retained_payload_states']==0
    asyncio.run(run())


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
            usage=agg.memory_usage()
            assert usage['pending_source_snapshots']==1
            assert usage['inflight_retry_keys_frames']==1
            assert usage['retained_payload_states']==3
        finally:released.set();await task
        assert calls==2 and not agg.publisher._pending_source_events
        assert not agg.publisher._inflight_payloads
    asyncio.run(run())
