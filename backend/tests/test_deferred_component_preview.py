"""Accepted inputs precede preview coalescing; barriers and public reads stay current."""
import asyncio
import gc
import sys
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
from app.data_engine.bar_aggregator.models import BarInput, BarInputSource, BarEventType, MergeMode
from app.data_engine.bar_aggregator import publisher as publisher_module
from app.data_engine.bar_aggregator import preview_scheduler as scheduling
from app.data_engine.bar_aggregator import aggregator as aggregator_module
from app.data_engine.bar_aggregator import bar_state as state_module
from app.data_engine.bar_aggregator import finalizer as finalizer_module
from app.data_engine.memory_budget import MemoryBudget

TARGET = '10007m'


def item(sequence, **changes):
    return BarInput('BTCUSDT','1m',0,59999,10,20,5,11,float(sequence),is_closed=False,
        sequence=sequence,source=BarInputSource.REALTIME,merge_mode=MergeMode.COMPONENT,
        quote_volume=float(sequence)*2,trades=sequence,taker_buy_base=float(sequence),
        taker_buy_quote=float(sequence)*2,**changes)


def make(monkeypatch, *, throttle=1000, enabled=True, budget_bytes=1_000_000):
    clock = SimpleNamespace(now=1000.)
    wall = SimpleNamespace(time=lambda:clock.now)
    monkeypatch.setattr(publisher_module,'time',wall)
    monkeypatch.setattr(scheduling,'time',wall)
    monkeypatch.setattr(aggregator_module,'time',wall)
    monkeypatch.setattr(state_module,'time',wall)
    monkeypatch.setattr(finalizer_module,'time',wall)
    agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=throttle,
        deferred_component_previews=enabled))
    agg.add_target('BTCUSDT',TARGET)
    budget = MemoryBudget(budget_bytes)
    budget.register('realtime-state',limit_bytes=budget_bytes,usage=lambda:dict(estimated_bytes=0))
    agg.memory_budget = budget
    events = []
    async def receive(event):
        events.append(event)
    agg.publisher.on_bar_event(receive)
    async def feed(value):
        await agg.ingest_bar_input('binance','spot','BTCUSDT',TARGET,value)
    def state():
        return agg.get_pipeline(TARGET).bar_state.get_active('binance','spot','BTCUSDT',0)
    return agg,budget,clock,events,feed,state


def test_many_accepted_updates_do_one_summary_at_deadline_without_a_new_input(monkeypatch):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    async def run():
        await agg.start()
        try:
            await feed(item(1))
            await feed(item(2))  # First UPDATED keeps the ordinary immediate boundary.
            for i in range(3,103): await feed(item(i))
            held = state()
            assert held.preview_input_version == 102
            assert held.preview_computed_version == held.preview_published_version == 2
            assert held._preview_dirty and held._preview_calculations == 2
            assert held.source_snapshots[item(102).input_key]['volume'] == 102
            assert len(agg._previews.pending) == 1
            assert budget.snapshot()['reserved_bytes'] == scheduling.ENTRY_BYTES
            clock.now += 1
            next(iter(agg._previews.pending.values())).due = asyncio.get_running_loop().time()
            await agg._previews._drain()
            assert not held._preview_dirty
            assert held.volume == 102 and held.preview_computed_version == held.preview_published_version == 102
            assert held._preview_calculations == 3
            assert [e.bar.volume for e in events if e.event_type == BarEventType.UPDATED] == [2,102]
            assert budget.snapshot()['reserved_bytes'] == 0
        finally: await agg.stop()
    asyncio.run(run())


@pytest.mark.parametrize('reader', ['deepcopy','latest','bucket','dict','storage','ohlcv','data'])
def test_public_read_materializes_latest_without_falsely_advancing_published_watermark(monkeypatch,reader):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    async def run():
        await agg.start()
        try:
            for i in range(1,5): await feed(item(i))
            held = state()
            assert held._preview_dirty
            from app.data_engine.data_manager.models import BarData
            value = {'deepcopy':lambda:deepcopy(held),'latest':lambda:agg.get_latest_bar('BTCUSDT',TARGET),
                'bucket':lambda:agg.get_bucket_state('BTCUSDT',TARGET,0),'dict':held.to_dict,
                'storage':held.to_storage_dict,'ohlcv':held.to_ohlcv,'data':lambda:BarData.from_bar_state(held)}[reader]()
            assert (value['volume'] if isinstance(value,dict) else value.volume) == 4
            assert held.preview_input_version == held.preview_computed_version == 4
            assert held.preview_published_version == 2
            assert len(events) == 2
            assert not held._preview_dirty
        finally: await agg.stop()
        assert budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())


def test_freshness_is_checked_before_coalescing_when_sequence_is_missing(monkeypatch):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    async def run():
        await agg.start()
        try:
            for i in [1,2]: await feed(item(i))
            # An accepted high/volume advance followed by ambiguous close-only
            # regression must retain the accepted observation, not the last raw row.
            await feed(replace(item(3),sequence=None,close=12,high=21))
            await feed(replace(item(3),sequence=None,close=11,high=20))
            result = agg.get_latest_bar('BTCUSDT',TARGET)
            assert (result.close,result.high,result.volume) == (12,21,3)
            assert result.preview_input_version == 3
        finally: await agg.stop()
    asyncio.run(run())


@pytest.mark.parametrize('barrier', ['close','new-component','correction','next-bucket'])
def test_barriers_match_eager_values_and_never_leave_a_deferred_closed_bar(monkeypatch,barrier):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    async def run():
        eager = BarAggregator(BarAggregatorConfig(update_throttle_ms=1000,deferred_component_previews=False))
        eager.add_target('BTCUSDT',TARGET)
        await agg.start()
        await eager.start()
        try:
            values = [item(i) for i in range(1,6)]
            last = item(6)
            if barrier == 'close': last = replace(last,is_closed=True)
            elif barrier == 'correction': last = replace(last,source=BarInputSource.CORRECTION,is_closed=True,high=15,volume=1)
            elif barrier == 'new-component': last = replace(last,open_time_ms=60000,close_time_ms=119999)
            else: last = replace(last,open_time_ms=10007*60000,close_time_ms=10008*60000-1)
            for value in [*values,last]:
                await feed(value)
                await eager.ingest_bar_input('binance','spot','BTCUSDT',TARGET,value)
            for interval in [0,10007*60000]:
                a = agg.get_pipeline(TARGET).bar_state.get_state('binance','spot','BTCUSDT',interval)
                b = eager.get_pipeline(TARGET).bar_state.get_state('binance','spot','BTCUSDT',interval)
                if a is None or b is None: assert a is b; continue
                a.materialize_preview()
                for name in ('open','high','low','close','volume','quote_volume','trades',
                             'taker_buy_base','taker_buy_quote','status','finality'):
                    assert getattr(a,name) == getattr(b,name),name
                assert not a._preview_dirty
        finally:
            await agg.stop()
            await eager.stop()
        assert budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('fallback', ['disabled','every','budget','capacity','custom-finalizer'])
def test_required_and_unqualified_work_keeps_eager_contract(monkeypatch,fallback):
    agg,budget,clock,events,feed,state = make(monkeypatch,
        enabled=fallback!='disabled',budget_bytes=100 if fallback=='budget' else 1_000_000)
    if fallback == 'every': agg.publisher.set_update_requirement(lambda _:True)
    if fallback == 'capacity': monkeypatch.setattr(scheduling,'MAX_PENDING',0)
    if fallback == 'custom-finalizer':
        class Custom:
            def should_close(self,state,trigger):
                assert not state._preview_dirty
                return False
        agg.get_pipeline(TARGET).finalizer.add_strategy('observer',Custom(),0)
    async def run():
        await agg.start()
        try:
            for i in range(1,8): await feed(item(i))
            assert state().volume == 7 and not state()._preview_dirty
            assert state()._preview_calculations == 7
            if fallback == 'every':
                assert [e.bar.volume for e in events] == list(range(1,8))
        finally: await agg.stop()
        assert budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())


def test_detach_cancels_pending_and_recreated_generation_gets_no_old_preview(monkeypatch):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    async def run():
        await agg.start()
        try:
            for i in range(1,6): await feed(item(i))
            assert state()._preview_dirty
            agg.remove_target('BTCUSDT',TARGET)
            assert budget.snapshot()['reserved_bytes'] == 0 and not agg._previews.pending
            count = len(events)
            agg.add_target('BTCUSDT',TARGET)
            await feed(item(1))
            clock.now += 2
            await agg._previews._drain()
            assert len(events) == count+1
            assert events[-1].bar.volume == 1
        finally: await agg.stop()
    asyncio.run(run())


def test_actual_deadline_sends_latest_without_a_following_source_frame(monkeypatch):
    agg,budget,clock,events,feed,state = make(monkeypatch,throttle=20)
    async def run():
        initial = asyncio.get_running_loop().time()
        clock_time = lambda:1000+asyncio.get_running_loop().time()-initial
        for module in [publisher_module,scheduling,aggregator_module,state_module,finalizer_module]:
            monkeypatch.setattr(module,'time',SimpleNamespace(time=clock_time))
        await agg.start()
        try:
            for i in range(1,5): await feed(item(i))
            assert state()._preview_dirty
            async with asyncio.timeout(2):
                while not events or events[-1].bar.volume != 4: await asyncio.sleep(.005)
            assert [e.bar.volume for e in events if e.event_type==BarEventType.UPDATED] == [2,4]
            assert budget.snapshot()['reserved_bytes'] == 0
        finally: await agg.stop()
    asyncio.run(run())


def test_preview_waits_for_existing_publication_and_wakes_after_it_finishes(monkeypatch):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    async def run():
        entered,released = asyncio.Event(),asyncio.Event()
        async def hold(event):
            if event.event_type==BarEventType.UPDATED and event.bar.volume==2:
                entered.set()
                await released.wait()
        agg.publisher.on_bar_event(hold)
        await agg.start()
        pending = None
        try:
            await feed(item(1))
            pending = asyncio.create_task(feed(item(2)))
            await asyncio.wait_for(entered.wait(),2)
            await feed(item(3))
            assert state()._preview_dirty and state()._preview_publications == 1
            clock.now += 1
            next(iter(agg._previews.pending.values())).due = asyncio.get_running_loop().time()
            await agg._previews._drain()
            assert [e.bar.volume for e in events] == [1,2]
            assert state()._preview_dirty
            released.set()
            await pending
            clock.now += 1
            next(iter(agg._previews.pending.values())).due = asyncio.get_running_loop().time()
            await agg._previews._drain()
            assert [e.bar.volume for e in events] == [1,2,3]
        finally:
            released.set()
            if pending is not None: await asyncio.gather(pending,return_exceptions=True)
            await agg.stop()
        assert budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('change', ['config','strategy','finalizer','budget'])
def test_rebound_owner_or_execution_does_not_publish_old_scheduled_result(monkeypatch,change):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    async def run():
        await agg.start()
        try:
            for i in range(1,6): await feed(item(i))
            if change=='config': agg._cfg = replace(agg._cfg)
            elif change=='strategy': agg.get_pipeline(TARGET).bar_state._merge_strategy_overridden = True
            elif change=='finalizer': agg.get_pipeline(TARGET).finalizer.clear_strategies()
            else: agg.memory_budget = MemoryBudget()
            clock.now += 1
            next(iter(agg._previews.pending.values())).due = asyncio.get_running_loop().time()
            await agg._previews._drain()
            assert [e.bar.volume for e in events] == [1,2]
            assert budget.snapshot()['reserved_bytes'] == 0
            assert state().volume == 5 and not state()._preview_dirty
        finally: await agg.stop()
    asyncio.run(run())


def test_timer_poll_does_not_compute_an_undemanded_tail_before_its_boundary(monkeypatch):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    async def run():
        await agg.start()
        try:
            for i in range(1,5): await feed(item(i))
            agg._cfg.emit_updated_events = False
            await agg._check_timeouts()
            assert state()._preview_dirty and state().preview_computed_version == 2
            assert state().preview_input_version == 4
        finally: await agg.stop()
    asyncio.run(run())


def test_finished_preview_does_not_hold_removed_builder_across_later_await(monkeypatch):
    agg,budget,clock,events,feed,state = make(monkeypatch)
    agg.add_target('ETHUSDT',TARGET)
    async def run():
        entered,released = asyncio.Event(),asyncio.Event()
        first = None
        async def remove_then_hold(event):
            if event.event_type != BarEventType.UPDATED or event.bar.volume != 3: return
            if event.bar.symbol=='BTCUSDT': agg.remove_target('BTCUSDT',TARGET)
            else:
                entered.set()
                await released.wait()
        agg.publisher.on_bar_event(remove_then_hold)
        await agg.start()
        task = None
        try:
            for symbol in ['BTCUSDT','ETHUSDT']:
                for i in [1,2,3]:
                    await agg.ingest_bar_input('binance','spot',symbol,TARGET,replace(item(i),symbol=symbol))
            first = state()
            clock.now += 1
            for entry in agg._previews.pending.values(): entry.due = asyncio.get_running_loop().time()
            agg._previews._wake()
            task = agg._previews.task
            await asyncio.wait_for(entered.wait(),2)
            gc.collect()
            # One explicit probe reference and getrefcount's temporary only;
            # neither the finished entry nor a suspended drain retains it.
            assert sys.getrefcount(first) == 2
            assert len(agg._previews.inflight)==1
            assert budget.snapshot()['reserved_bytes']==scheduling.ENTRY_BYTES
            released.set()
            await task
        finally:
            released.set()
            if task is not None: await asyncio.gather(task,return_exceptions=True)
            await agg.stop()
    asyncio.run(run())


def test_disabled_updates_keep_only_admitted_state_until_read_or_barrier(monkeypatch):
    agg,budget,clock,events,feed,state=make(monkeypatch)
    agg._cfg.emit_updated_events=False
    async def run():
        await agg.start()
        try:
            for i in range(1,6): await feed(item(i))
            assert state()._preview_dirty and state().preview_computed_version==1
            assert not any(e.event_type==BarEventType.UPDATED for e in events)
            assert agg._previews.timer is None
            assert len(agg._previews.pending)==1
            await agg._check_timeouts()
            assert state()._preview_dirty
            await feed(replace(item(6),is_closed=True))
            assert state().volume==6 and not state()._preview_dirty
            assert not any(e.event_type==BarEventType.UPDATED for e in events)
        finally: await agg.stop()
        assert budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_queue_capacity_falls_back_and_due_targets_make_progress_in_bounded_batches(monkeypatch):
    agg,budget,clock,events,feed,state=make(monkeypatch)
    for symbol in ['ETHUSDT','SOLUSDT']: agg.add_target(symbol,TARGET)
    monkeypatch.setattr(scheduling,'MAX_PENDING',2)
    monkeypatch.setattr(scheduling,'MAX_DRAIN',1)
    async def run():
        await agg.start()
        try:
            for symbol in ['BTCUSDT','ETHUSDT','SOLUSDT']:
                for i in [1,2,3]:
                    await agg.ingest_bar_input('binance','spot',symbol,TARGET,replace(item(i),symbol=symbol))
            assert len(agg._previews.pending)==2
            last=agg.get_pipeline(TARGET).bar_state.get_active('binance','spot','SOLUSDT',0)
            assert last.volume==3 and not last._preview_dirty and last.preview_fallback_reason=='pending_capacity'
            clock.now+=1
            for entry in agg._previews.pending.values(): entry.due=asyncio.get_running_loop().time()
            agg._previews._wake()
            async with asyncio.timeout(2):
                while agg._previews.pending or agg._previews.task is not None: await asyncio.sleep(.005)
            progressed=[e.bar.symbol for e in events if e.event_type==BarEventType.UPDATED and e.bar.volume==3]
            assert progressed==['BTCUSDT','ETHUSDT']
            assert budget.snapshot()['reserved_bytes']==0
        finally: await agg.stop()
    asyncio.run(run())


def test_stop_cancels_held_preview_without_acknowledging_its_unfinished_publication(monkeypatch):
    agg,budget,clock,events,feed,state=make(monkeypatch)
    async def run():
        entered,released=asyncio.Event(),asyncio.Event()
        async def hold(event):
            if event.event_type==BarEventType.UPDATED and event.bar.volume==3:
                entered.set()
                await released.wait()
        agg.publisher.on_bar_event(hold)
        await agg.start()
        try:
            for i in [1,2,3]: await feed(item(i))
            clock.now+=1
            next(iter(agg._previews.pending.values())).due=asyncio.get_running_loop().time()
            agg._previews._wake()
            await asyncio.wait_for(entered.wait(),2)
            await feed(item(4))
            await agg._previews.stop()
            assert state().preview_input_version==state().preview_computed_version==4
            assert state().preview_published_version==2
            assert not state()._preview_publications
            assert not agg._previews.pending and not agg._previews.inflight
            assert budget.snapshot()['reserved_bytes']==0
        finally:
            released.set()
            await agg.stop()
    asyncio.run(run())


def test_shared_source_targets_keep_distinct_live_preview_requirements(monkeypatch):
    from tests.test_shared_component_input import market
    agg,budget,clock,events,feed,state=make(monkeypatch)
    for interval in ['89m','97m','101m']: agg.add_target('BTCUSDT',interval,market_type='futures')
    agg.remove_target('BTCUSDT',TARGET)
    agg.add_target('BTCUSDT',TARGET,market_type='futures')
    required={'97m'}
    agg.publisher.set_update_requirement(lambda state:state.interval in required)
    async def run():
        await agg.start()
        try:
            for i in range(1,20): await agg.on_market_event(market(0,volume=i,sequence=i))
            per_target={interval:agg.get_pipeline(interval).bar_state.get_active('binance','futures','BTCUSDT',0)
                        for interval in ['89m','97m','101m',TARGET]}
            assert per_target['97m']._preview_calculations==19
            assert all(s._preview_dirty and s._preview_calculations==2
                       for key,s in per_target.items() if key!='97m')
            assert [e.bar.volume for e in events if e.bar.interval=='97m']==list(range(1,20))
            required.clear()
            for i in range(20,24): await agg.on_market_event(market(0,volume=i,sequence=i))
            assert per_target['97m']._preview_dirty
            clock.now+=1
            for entry in agg._previews.pending.values(): entry.due=asyncio.get_running_loop().time()
            await agg._previews._drain()
            assert all(s.volume==23 and not s._preview_dirty for s in per_target.values())
            leaves=[next(iter(s.source_snapshots.values())) for s in per_target.values()]
            assert all(leaf is leaves[0] for leaf in leaves)
        finally: await agg.stop()
    asyncio.run(run())
