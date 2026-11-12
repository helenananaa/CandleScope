"""R129 source preparation must be immutable before sharing across targets."""
from copy import deepcopy
from dataclasses import replace

import pytest

from tests.test_component_incremental import component, engine, apply
from tests.test_kline_revision_contract import storage


def referenced_input():
    return replace(component(0),extra={'source_ref':{
        'series':'qualified-source','revision':1,'proof':{'rows':[1]}}})


def test_component_snapshot_nested_reference_is_readonly_in_published_copy():
    executor = engine()
    value = referenced_input()
    state, _ = apply(executor,value)
    snapshot = deepcopy(state)
    ref = snapshot.source_snapshots[value.input_key]['source_ref']
    with pytest.raises(TypeError):
        ref['revision'] = 9
    with pytest.raises((AttributeError,TypeError)):
        ref['proof']['rows'].append(2)
    assert state.source_snapshots[value.input_key]['source_ref']['revision'] == 1


def test_accepted_reference_detaches_original_nested_input_payload():
    executor = engine()
    value = referenced_input()
    state, _ = apply(executor,value)
    value.extra['source_ref']['revision'] = 99
    value.extra['source_ref']['proof']['rows'].append(2)
    assert state.source_snapshots[value.input_key]['source_ref']['revision'] == 1
    assert tuple(state.source_snapshots[value.input_key]['source_ref']['proof']['rows']) == (1,)
    assert state.source_refs[value.input_key]['revision'] == 1
    assert state.source_refs[value.input_key]['proof']['rows'] == [1]


@pytest.mark.parametrize('closed',[False,True])
def test_replacement_reference_detaches_input_for_active_and_closed_owner(closed):
    executor = engine()
    first = referenced_input()
    state, _ = apply(executor,first)
    old = deepcopy(state)
    if closed:
        executor.close_bar(first.exchange,first.market_type,first.symbol,0)
    revised = replace(first,volume=.1,extra={'source_ref':{
        'series':'qualified-source','revision':2,'proof':{'rows':[2]}}})
    state, _ = apply(executor,revised)
    revised.extra['source_ref']['proof']['rows'].append(3)
    assert state.source_refs[first.input_key]['proof']['rows'] == [2]
    assert tuple(state.source_snapshots[first.input_key]['source_ref']['proof']['rows']) == (2,)
    assert old.source_refs[first.input_key]['proof']['rows'] == [1]


def test_cyclic_reference_rejected_before_changing_existing_owner():
    executor = engine()
    value = referenced_input()
    state, _ = apply(executor,value)
    before = deepcopy(state)
    ref = {'series':'qualified-source','revision':2}
    ref['proof'] = ref
    with pytest.raises(ValueError,match='cyclic'):
        apply(executor,replace(value,volume=9,extra={'source_ref':ref}))
    assert state.volume == before.volume
    assert state.source_snapshots == before.source_snapshots
    assert state.source_refs == before.source_refs


import asyncio
import json
from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
from app.data_engine.ingestion.models import MarketEvent, DataSource, StreamType
from app.data_engine.memory_budget import MemoryBudget, retained_size

PERIODS = ('89m','97m','101m','10007m')


def aggregator(*, shared=True, periods=PERIODS):
    agg = BarAggregator(BarAggregatorConfig(shared_component_inputs=shared,
        update_throttle_ms=0,finalize_timeout_ms=10**15))
    for interval in periods:
        agg.add_target('BTCUSDT',interval,market_type='futures')
    return agg


def market(index=0, *, volume=1, sequence=1, closed=False, ref=None):
    value = component(index,volume=volume,closed=closed,sequence=sequence)
    data = dict(interval='1m',open_time=value.open_time_ms,close_time=value.close_time_ms,
        open=value.open,high=value.high,low=value.low,close=value.close,
        volume=value.volume,quote_volume=value.quote_volume,trades=value.trades,
        taker_buy_base=value.taker_buy_base,taker_buy_quote=value.taker_buy_quote,
        enhanced_fields=value.enhanced_fields,is_closed=closed)
    if ref is not None:
        data['source_ref'] = ref
    return MarketEvent(StreamType.KLINE,'BTCUSDT','binance',sequence,sequence,
                       DataSource.WEBSOCKET,data,sequence=sequence,market_type='futures')


def held(agg, interval, *, at=0):
    pipe = agg.get_pipeline(interval)
    return pipe.bar_state.get_state('binance','futures','BTCUSDT',at)


def snapshots(agg):
    return [next(iter(held(agg,interval).source_snapshots.values())) for interval in PERIODS]


def test_default_market_fanout_shares_only_immutable_values_across_independent_targets():
    async def run():
        agg = aggregator()
        await agg.on_market_event(market())
        first = snapshots(agg)
        assert len({id(value) for value in first}) == 1
        assert len({id(held(agg,interval).source_snapshots) for interval in PERIODS}) == 4
        assert agg.memory_usage()['preparation_builds'] == 1
        assert agg.memory_usage()['preparation_hits'] == 3
        await agg.on_market_event(market(volume=2,sequence=2))
        second = snapshots(agg)
        assert len({id(value) for value in second}) == 1
        assert second[0] is not first[0] and first[0]['volume'] == 1
        assert second[0]['volume'] == 2
        assert agg.memory_usage()['source_preparation_scopes'] == 0
        assert not agg._active_preparations and agg._source_preparation.get() is None
    asyncio.run(run())


def test_multi_row_backfill_reuses_each_input_without_retaining_a_dispatch_cache():
    async def run():
        agg, reference = aggregator(), aggregator(shared=False)
        rows = [dict(open_time=i*60000,close_time=(i+1)*60000-1,
            open=100,high=102,low=99,close=101,volume=1,quote_volume=2,
            trades=1,taker_buy_base=1,taker_buy_quote=2) for i in range(12)]
        for owner in (agg,reference):
            await owner.on_backfill_bars('BTCUSDT','1m',rows,market_type='futures')
        assert agg.memory_usage()['preparation_builds'] == 12
        assert agg.memory_usage()['preparation_hits'] == 36
        values = [value for interval in PERIODS for value in held(agg,interval).source_snapshots.values()]
        independent = [value for interval in PERIODS for value in held(reference,interval).source_snapshots.values()]
        assert len({id(value) for value in values}) == 12
        assert len({id(value) for value in independent}) == 48
        assert retained_size([values])[0] < retained_size([independent])[0]
        for interval in PERIODS:
            left,right = held(agg,interval),held(reference,interval)
            assert left.to_storage_dict() == right.to_storage_dict()
            assert left.tick_count == right.tick_count == 12
        assert not agg._active_preparations
    asyncio.run(run())


def test_flat_source_provenance_shares_but_nested_provenance_keeps_original_route():
    async def run():
        agg = aggregator()
        await agg.on_market_event(market(ref={'series':'fixture','revision':1}))
        assert len({id(value) for value in snapshots(agg)}) == 1
        other = aggregator()
        await other.on_market_event(market(ref={'series':'fixture','revision':1,'proof':{'rows':[1]}}))
        assert len({id(value) for value in snapshots(other)}) == 4
        assert other.memory_usage()['preparation_builds'] == other.memory_usage()['preparation_hits'] == 0
        for interval in PERIODS:
            json.dumps(held(other,interval).to_storage_dict())
    asyncio.run(run())


def test_optional_shared_preparation_budget_failure_never_discards_mandatory_input():
    async def run():
        agg = aggregator()
        budget = MemoryBudget(total_bytes=1)
        budget.register('realtime-state',limit_bytes=1,usage=agg.memory_usage)
        agg.memory_budget = budget
        await agg.on_market_event(market())
        assert all(held(agg,interval).volume == 1 for interval in PERIODS)
        assert len({id(value) for value in snapshots(agg)}) == 4
        assert agg.memory_usage()['preparation_budget_deferred'] == 1
        assert not agg._active_preparations and budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())


def test_cancelled_callback_releases_scope_and_reservation_before_retry():
    async def run():
        agg = aggregator()
        budget = MemoryBudget()
        budget.register('realtime-state',limit_bytes=128*1024*1024,usage=agg.memory_usage)
        agg.memory_budget = budget
        entered, block = asyncio.Event(), asyncio.Event()
        once = True
        async def paused(event):
            nonlocal once
            if once:
                once=False; entered.set(); await block.wait()
        agg.publisher.on_bar_created(paused)
        task = asyncio.create_task(agg.on_market_event(market()))
        await asyncio.wait_for(entered.wait(),2)
        assert budget.snapshot()['reserved_bytes'] == 0
        assert agg.memory_usage()['source_preparation_in_use'] == 1
        assert agg.memory_usage()['source_preparation_capacity_bytes'] == 16384
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not agg._active_preparations and budget.snapshot()['reserved_bytes'] == 0
        await agg.on_market_event(market())
        assert all(held(agg,interval).volume == 1 for interval in PERIODS)
        assert not agg._active_preparations and budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())


def test_rollout_switch_during_dispatch_preserves_values_and_uses_independent_fallback():
    async def run():
        agg = aggregator()
        async def switched(event):
            agg.config.shared_component_inputs=False
        agg.publisher.on_bar_created(switched)
        await agg.on_market_event(market())
        assert all(held(agg,interval).volume == 1 for interval in PERIODS)
        assert len({id(value) for value in snapshots(agg)}) == 4
        assert agg.memory_usage()['preparation_builds'] == 1
        assert agg.memory_usage()['preparation_hits'] == 0
        assert not agg._active_preparations
    asyncio.run(run())


def test_same_input_event_trace_matches_independent_preparation_through_closes_and_correction():
    async def run():
        periods = ('1m','5m',*PERIODS)
        shared,reference = aggregator(periods=periods),aggregator(shared=False,periods=periods)
        traces = [[],[]]
        for owner,trace in zip((shared,reference),traces):
            async def capture(event, destination=trace):
                destination.append((event.event_type.value,event.bar.interval,
                    event.bar.to_storage_dict(),event.bar.status.value,event.bar.finality.value,
                    event.bar.close_reason,event.bar.tick_count,
                    event.bar.first_input_at_ms,event.bar.last_input_at_ms))
            owner.publisher.on_bar_event(capture)
        for index in range(101):
            for step,closed in enumerate((False,False,True)):
                event = market(index,volume=step+1,sequence=1000+index*3+step,closed=closed)
                for owner in (shared,reference):
                    await owner.on_market_event(deepcopy(event))
        revised = market(0,volume=.1,sequence=10000,closed=True)
        revised.source = DataSource.PLUGIN
        revised.data['is_correction'] = True
        revised.data.update(high=101,low=99,close=100,quote_volume=.2,trades=1,
                            taker_buy_base=.05,taker_buy_quote=.1)
        for owner in (shared,reference):
            await owner.on_market_event(deepcopy(revised))
        assert traces[0] == traces[1]
        assert any(kind == 'bar.closed' and interval == '89m' for kind,interval,*_ in traces[0])
        assert any(kind == 'bar.amended' and interval == '89m' for kind,interval,*_ in traces[0])
        assert shared.memory_usage()['preparation_hits'] > 0
        assert not shared._active_preparations
    asyncio.run(run())


def test_preparation_signature_separates_semantic_identity_and_missing_fields():
    from app.data_engine.bar_aggregator.component_inputs import SourceComponentPreparation
    from app.data_engine.series_identity import KlineSeriesIdentity
    stats = dict(preparation_builds=0,preparation_hits=0,preparation_declines=0,preparation_budget_deferred=0)
    scope = SourceComponentPreparation(stats)
    value = component(0)
    first = scope.get(value)
    assert scope.get(value) is first
    marked = replace(value,series_identity=KlineSeriesIdentity.for_exchange('binance',series_variant='mark'))
    assert scope.get(marked) is not first
    unknown = replace(marked,quote_volume=None,trades=None,enhanced_fields=frozenset())
    record = scope.get(unknown)
    assert record['quote_volume'] is record['trades'] is None
    assert record is not scope.get(value)
    scope.close()
    assert scope.snapshot is scope.source_extra is scope.fingerprint is None


def test_custom_merge_keeps_its_original_independent_contract():
    from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
    async def run():
        agg = aggregator()
        custom = ComponentSnapshotOHLCVMerge()
        agg.get_pipeline('97m').bar_state.set_merge_strategy(custom)
        await agg.on_market_event(market())
        assert all(held(agg,interval).volume == 1 for interval in PERIODS)
        assert len({id(value) for value in snapshots(agg)}) == 4
        assert agg.memory_usage()['preparation_hits'] == agg.memory_usage()['preparation_builds'] == 0
    asyncio.run(run())


def test_child_task_cannot_borrow_inherited_source_preparation():
    async def run():
        agg = aggregator()
        seen=[]
        async def capture(event):
            async def child():
                value=component(0)
                value.market_type='futures'
                seen.append(agg._prepare_component_input(value))
            await asyncio.create_task(child())
        agg.publisher.on_bar_created(capture)
        await agg.on_market_event(market())
        assert seen == [None]*4
        assert agg.memory_usage()['preparation_builds'] == 1
    asyncio.run(run())


def test_default_data_manager_commits_adopts_and_queries_shared_backfill_targets(storage):
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.config import DataManagerConfig
    from app.data_engine.storage import klines_repo
    rows = [dict(open_time=i*60000,close_time=(i+1)*60000-1,
        open=100,high=102,low=99,close=101,volume=1,quote_volume=2,
        trades=1,taker_buy_base=1,taker_buy_quote=2) for i in range(101)]
    klines_repo.upsert_klines('BTCUSDT','1m',rows,source='backfill',market_type='futures')
    cfg = DataManagerConfig()
    cfg.coordinator.prewarm_symbols=[]
    cfg.coordinator.auto_start_ingestion=False
    cfg.query.auto_backfill=False
    manager=DataManager(cfg);manager.set_storage(storage)
    owner=manager.bar_aggregator
    owner.config.update_throttle_ms=0
    owner.config.finalize_timeout_ms=10**15
    for interval in PERIODS:
        owner.add_target('BTCUSDT',interval,market_type='futures')
    async def run():
        await manager.start()
        try:
            await owner.on_backfill_bars('BTCUSDT','1m',rows,market_type='futures')
            for interval in PERIODS[:3]:
                period=int(interval[:-1])
                result=manager.query('BTCUSDT',interval,start_ms=0,end_ms=period*60000-1,
                    limit=1,market_type='futures',auto_backfill=False,
                    min_revision=storage.revision_store.head())
                assert result.complete and result.bars[0].trusted_final
                assert result.bars[0].volume == period
            assert storage.count_bars('BTCUSDT','10007m',0,0,market_type='futures') == 0
            assert owner.memory_budget is manager.memory_budget
            assert owner.memory_usage()['preparation_hits'] > 0
            assert not owner._active_preparations
            assert manager.memory_budget.snapshot()['reserved_bytes'] == 0
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())


def test_native_plus_one_custom_target_does_not_admit_unused_shared_work():
    async def run():
        agg=aggregator(periods=('1m','89m'))
        await agg.on_market_event(market())
        assert held(agg,'89m').volume == 1
        assert agg.memory_usage()['preparation_builds'] == 0
        assert agg.memory_usage()['source_preparation_capacity_slots'] == 0
    asyncio.run(run())


def test_idle_capacity_retains_no_input_and_releases_on_target_detach_and_stop():
    async def run():
        agg=aggregator()
        budget=MemoryBudget()
        budget.register('realtime-state',limit_bytes=128*1024*1024,usage=agg.memory_usage)
        agg.memory_budget=budget
        await agg.on_market_event(market())
        assert agg._preparation_capacity.in_use == 0
        assert agg.memory_usage()['source_preparation_capacity_slots'] == 1
        assert not agg._active_preparations and budget.snapshot()['reserved_bytes'] == 0
        for interval in PERIODS:
            agg.remove_target('BTCUSDT',interval,market_type='futures')
        assert agg.memory_usage()['source_preparation_capacity_slots'] == 0
        for interval in PERIODS:
            agg.add_target('BTCUSDT',interval,market_type='futures')
        await agg.on_market_event(market(volume=2,sequence=2))
        assert agg.memory_usage()['source_preparation_capacity_slots'] == 1
        await agg.stop()
        assert agg.memory_usage()['source_preparation_capacity_slots'] == 0
        assert budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())


def test_preparation_capacity_is_bounded_and_old_budget_cannot_supply_new_slots():
    from app.data_engine.bar_aggregator.component_inputs import SourcePreparationCapacity
    from app.data_engine.memory_budget import MemoryBudgetExceeded
    pool=SourcePreparationCapacity()
    for _ in range(pool.MAX_SLOTS):
        pool.acquire(None)
    with pytest.raises(MemoryBudgetExceeded):
        pool.acquire(None)
    assert pool.in_use == pool.capacity == 64
    changed=MemoryBudget()
    changed.register('realtime-state',limit_bytes=1024*1024,usage=lambda:{'estimated_bytes':pool.capacity*16384})
    with pytest.raises(MemoryBudgetExceeded):
        pool.acquire(changed)
    for _ in range(64):
        pool.release(keep=False)
    assert pool.in_use == pool.capacity == 0
    pool.acquire(changed)
    assert pool.capacity == pool.in_use == 1
    assert changed.snapshot()['reserved_bytes'] == 0
    pool.close()
    pool.release(keep=True)
    assert pool.capacity == pool.in_use == 0


def test_numeric_adapter_scalars_remain_supported_by_immutable_component_values():
    import numpy as np
    value=replace(component(0),open=np.float32(100),high=np.float32(102),low=np.float32(99),
                  close=np.float32(101),volume=np.float32(1),is_closed=np.bool_(True),sequence=np.int64(1))
    owner=engine()
    state,_=apply(owner,value)
    record=state.source_snapshots[value.input_key]
    assert state.volume == 1 and state.open == 100
    assert record['open'] is value.open and isinstance(record['open'],np.float32)
    assert record['is_closed'] is True and record['sequence'] is value.sequence


def test_real_fork_normalizer_journal_delivery_and_correction_share_components(storage,monkeypatch):
    from app.data_engine.storage import klines_repo,kline_sources
    from tests.test_source_revision_pipeline import Harness,message,DESC
    periods=('2m','7m','11m','13m')
    from types import SimpleNamespace
    from app.data_engine.bar_aggregator import aggregator as aggregation_module
    clock=0
    monkeypatch.setattr(aggregation_module,'time',SimpleNamespace(time=lambda:clock/1000))
    async def run():
        nonlocal clock
        harness=Harness('1m',*periods)
        owner=harness.aggregator
        owner.config.finalize_timeout_ms=10**15
        owner.config.update_throttle_ms=0
        try:
            for index in range(13):
                opened=index*60000
                clock=opened+1000
                await harness.ingest(message(opened,closed=False,event_time=clock))
                clock=opened+60001
                await harness.ingest(message(opened,event_time=clock))
            before=[owner.get_pipeline(interval).bar_state.get_state('binance','futures','BTCUSDT',0)
                    for interval in periods]
            node_key=next(key for key in before[0].source_snapshots if key.endswith(':0'))
            old=before[0].source_snapshots[node_key]
            assert len({id(state.source_snapshots[node_key]) for state in before}) == 1
            clock=13*60000+100010
            await harness.ingest(message(0,quote='1008',event_time=clock))
            after=[owner.get_pipeline(interval).bar_state.get_state('binance','futures','BTCUSDT',0)
                   for interval in periods]
            assert len({id(state.source_snapshots[node_key]) for state in after}) == 1
            assert after[0].source_snapshots[node_key] is not old
            assert old['quote_volume'] == 1010
            for interval in periods:
                rows=klines_repo.query_klines('BTCUSDT',interval,market_type='futures')
                row=next(row for row in rows if row['open_time']==0)
                assert row['quote_volume'] == int(interval[:-1])*1010-2
            assert not kline_sources.pending(DESC)
            assert not harness.bridge.delivery.journal.pending()
            assert owner.memory_usage()['preparation_hits'] >= 3*27
            assert not owner._active_preparations
        finally:
            await harness.close()
    asyncio.run(run())


def test_terminal_preparation_drops_service_handles_and_cannot_be_reopened():
    from app.data_engine.bar_aggregator.component_inputs import SourceComponentPreparation
    stats=dict(preparation_builds=0,preparation_hits=0,preparation_declines=0,preparation_budget_deferred=0)
    source=SourceComponentPreparation(stats)
    source.get(component(0))
    source.close()
    assert source.get(component(0)) is None
    assert source.budget is source.pool is source.metrics is None
    assert not source.engines and source.qualification is None
    assert source.memory_roots() == [None,None,None]
    source.close()


def test_replaced_router_callback_keeps_independent_preparation_even_when_forwarding():
    async def run():
        agg=aggregator()
        original=agg.router._on_bar_input
        async def forwarding(*args):
            await original(*args)
        agg.router.set_on_bar_input(forwarding)
        await agg.on_market_event(market())
        assert all(held(agg,interval).volume == 1 for interval in PERIODS)
        assert len({id(value) for value in snapshots(agg)}) == 4
        assert agg.memory_usage()['preparation_builds'] == 0
        assert not agg._active_preparations
    asyncio.run(run())
