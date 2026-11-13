"""Closed indexes retire through H127 and recover old amendments through D126."""
import asyncio
from dataclasses import replace
import threading

import pytest

from app.data_engine.bar_aggregator.models import BarInput, BarInputSource, MergeMode
from app.data_engine.bar_aggregator.history_prefix_runtime import HistoryPrefixRuntime
from app.data_engine.data_manager.models import DataEventType
from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamType
from app.data_engine.storage import klines_repo
from tests.test_shared_blocks_integration import dm

WIDTH = 60000
FIELDS = ('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')


def rows(count):
    return [dict(open_time=i*WIDTH,close_time=(i+1)*WIDTH-1,open=10.,high=20.,low=5.,close=11.,
        volume=float(i+1),quote_volume=float(2*(i+1)),trades=i+1,taker_buy_base=1.,taker_buy_quote=2.)
        for i in range(count)]


def persist(values):
    return klines_repo.upsert_klines('BTCUSDT','1m',values,market_type='futures',source='backfill')


def component(value, *, correction=False):
    return BarInput(symbol='BTCUSDT',source_interval='1m',open_time_ms=value['open_time'],
        close_time_ms=value['close_time'],market_type='futures',is_closed=True,merge_mode=MergeMode.COMPONENT,
        source=BarInputSource.CORRECTION if correction else BarInputSource.REALTIME,
        sequence=value['open_time']+1,enhanced_fields=frozenset(FIELDS[5:]),
        **{name:value[name] for name in FIELDS})


class Ingestion:
    async def start(self, *, on_market_event, **_): self.send=on_market_event; return self
    async def stop(self): pass


async def prepare(dm, clock, count, *, prefix=False):
    values=rows(count)
    interval=f'{count}m'
    ingestion=Ingestion()
    dm.set_ingestion_factory(ingestion)
    observed=[]
    async def receive(event): observed.append((event.event_type,event.bar.volume))
    if prefix:
        persist(values[:-1]); clock[0]=(count-1)*WIDTH+1000
    await dm.start()
    await dm.subscribe_async(receive,symbol='BTCUSDT',interval=interval,market_type='futures',
        continuity='gap_aware',preserve_updates=True,
        event_types={DataEventType.BAR_CLOSED,DataEventType.BAR_AMENDED})
    await dm.ensure_stream('BTCUSDT',interval,market_type='futures')
    if not prefix:
        persist(values[:-1])
        for value in values[:-1]:
            await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',interval,component(value),emit_events=False)
    state=dm.bar_aggregator.get_pipeline(interval).bar_state.get_active('binance','futures','BTCUSDT',0)
    assert (state._history_prefix is not None) == prefix
    async def close(drain=True,last=None):
        last=values[-1] if last is None else last
        clock[0]=last['close_time']+1001
        await ingestion.send(MarketEvent(event_type=StreamType.KLINE,symbol='BTCUSDT',exchange='binance',
            market_type='futures',event_time_ms=clock[0],received_at_ms=clock[0],sequence=clock[0],
            source=DataSource.WEBSOCKET,data=dict(interval='1m',is_closed=True,**last)))
        if drain: await dm.history_prefix_runtime.drain_closed()
    return values,interval,state,observed,close


@pytest.mark.parametrize('count,prefix',[(7,False),(7,True),(89,False),(10007,False)])
def test_closed_bucket_retirement_and_old_correction_use_default_owners(dm,monkeypatch,count,prefix):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    if prefix: monkeypatch.setattr(HistoryPrefixRuntime,'MIN_ROWS',2)
    before=[]
    async def record(event):
        if event.event_type.value=='bar.closed':
            state=event.bar
            before.append(tuple(getattr(state,name) for name in (*FIELDS,'status','finality','close_reason','created_at_ms','updated_at_ms','acquisition_revision')))
    dm.bar_aggregator.publisher.on_bar_event(record)
    async def run():
        try:
            values,interval,state,observed,close=await prepare(dm,clock,count,prefix=prefix)
            await close()
            runtime=dm.history_prefix_runtime
            assert state.status.value=='closed' and state.finality.value=='authoritative'
            assert state._history_prefix is not None, runtime.last_closed_compaction
            assert state._history_prefix.complete and state._history_prefix.through_ms==count*WIDTH
            assert not state.source_snapshots and not state.source_refs and state._component_accumulator is None
            assert tuple(getattr(state,name) for name in (*FIELDS,'status','finality','close_reason','created_at_ms','updated_at_ms','acquisition_revision'))==before[-1]
            assert state.preview_input_version==state.preview_computed_version==state.preview_published_version
            assert runtime.metrics['closed_compactions']==1
            assert runtime.metrics['closed_compacted_components']==(1 if prefix else count)
            assert runtime.metrics['closed_compaction_pages']==((1 if prefix else count)+127)//128
            expected=sum(value['volume'] for value in values)
            async with asyncio.timeout(5):
                while (DataEventType.BAR_CLOSED,expected) not in observed: await asyncio.sleep(.01)
            assert len(observed)==1
            stored=dm.query_engine.storage.query_bars('BTCUSDT',interval,0,0,market_type='futures')
            assert stored[0]['volume']==expected
            # A correction to the first, now retired leaf refreshes the same
            # canonical prefix and writes/publishes one amended target.
            changed=dict(values[0],volume=0.,quote_volume=0.,high=11.)
            persist([changed])
            await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',interval,component(changed,correction=True))
            current=dm.bar_aggregator.get_pipeline(interval).bar_state.get_closed('binance','futures','BTCUSDT',0)
            assert current is state and not current.source_snapshots and current.volume==expected-1
            async with asyncio.timeout(5):
                while (DataEventType.BAR_AMENDED,expected-1) not in observed: await asyncio.sleep(.01)
            assert observed==[(DataEventType.BAR_CLOSED,expected),(DataEventType.BAR_AMENDED,expected-1)]
            stored=dm.query_engine.storage.query_bars('BTCUSDT',interval,0,0,market_type='futures')
            assert stored[0]['volume']==expected-1
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


@pytest.mark.parametrize('variant',['disabled','missing','opposite-corrections','unknown-fields'])
def test_retirement_declines_unproven_inputs_without_changing_close(dm,monkeypatch,variant):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    if variant=='disabled': dm.bar_aggregator.config.compact_closed_components=False
    async def run():
        try:
            values,interval,state,observed,close=await prepare(dm,clock,7)
            if variant=='missing': dm.query_engine.storage.delete_bars('BTCUSDT','1m',0,0,market_type='futures')
            elif variant=='opposite-corrections': persist([dict(values[0],volume=2.),dict(values[1],volume=1.)])
            elif variant=='unknown-fields':
                with klines_repo._connect() as conn:
                    conn.execute("UPDATE klines SET quote_volume=NULL WHERE symbol='BTCUSDT' AND interval='1m' AND open_time=0")
            await close()
            assert state.status.value=='closed' and state.volume==28 and len(state.source_snapshots)==7
            assert state._history_prefix is None
            runtime=dm.history_prefix_runtime
            assert runtime.metrics['closed_compactions']==0
            if variant!='disabled':
                assert runtime.metrics['closed_compaction_deferred']==1
                assert runtime.last_closed_compaction['reason']=='BlockUnavailable'
                assert not runtime.targets
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


@pytest.mark.parametrize('deletion',['first','all'])
def test_deleted_retired_components_revoke_close_without_resurrection(dm,monkeypatch,deletion):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    async def run():
        try:
            values,interval,state,_,close=await prepare(dm,clock,7)
            await close()
            assert not state.source_snapshots and state._history_prefix.complete
            dm.query_engine.storage.delete_bars('BTCUSDT','1m',0,0 if deletion=='first' else 7*WIDTH-1,market_type='futures')
            await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',interval,component(values[0],correction=True))
            current=dm.bar_aggregator.get_pipeline(interval).bar_state.get_state('binance','futures','BTCUSDT',0)
            if deletion=='first':
                assert current.status.value=='forming' and current.finality.value=='provisional'
                assert current.volume==27 and not current._history_prefix.complete
            else: assert current is None
            assert not dm.query_engine.storage.query_bars('BTCUSDT',interval,0,0,market_type='futures')
            assert dm.query_engine.storage.count_bars('BTCUSDT','1m',0,0,market_type='futures')==0
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


@pytest.mark.parametrize('action',['cancel','detach','disable','storage','config','strategy'])
def test_closed_readback_lifetime_and_late_fences(dm,monkeypatch,action):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    entered,released=threading.Event(),threading.Event()
    reader=dm.history_prefix_runtime.reader
    original=reader.matches_closed_overlay
    def held(*args,**kwargs):
        entered.set()
        assert released.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(reader,'matches_closed_overlay',held)
    async def run():
        task=None
        try:
            _,interval,state,_,close=await prepare(dm,clock,7)
            task=asyncio.create_task(close())
            async with asyncio.timeout(5):
                while not entered.is_set(): await asyncio.sleep(.01)
            reserved=dm.memory_budget.snapshot()['reserved_bytes']
            assert reserved>65536
            if action=='cancel': task.cancel()
            elif action=='detach':
                dm.bar_aggregator.remove_target('BTCUSDT',interval,market_type='futures')
                assert dm.bar_aggregator.memory_usage()['retained_component_payload_bytes']>=state.source_snapshots.estimated_bytes
            elif action=='disable': dm.bar_aggregator.config.compact_closed_components=False
            elif action=='storage': dm.set_storage(klines_repo.KlinesRepoAdapter())
            elif action=='config': dm.bar_aggregator._cfg=replace(dm.bar_aggregator.config)
            else:
                from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
                dm.bar_aggregator.get_pipeline(interval).bar_state._component_merge_strategy=ComponentSnapshotOHLCVMerge()
            await asyncio.sleep(.02)
            assert not task.done() and dm.memory_budget.snapshot()['reserved_bytes']>=reserved
            released.set()
            if action=='cancel':
                with pytest.raises(asyncio.CancelledError): await task
            else: await task
            assert state._history_prefix is None and len(state.source_snapshots)==7
            assert dm.history_prefix_runtime.metrics['closed_compactions']==0
            assert not dm.history_prefix_runtime.targets
            # Cancellation/declining maintenance does not undo a legitimately
            # committed close, nor create another canonical write.
            stored=dm.query_engine.storage.query_bars('BTCUSDT',interval,0,0,market_type='futures')
            assert stored[0]['volume']==28
        finally:
            released.set()
            if task is not None: await asyncio.gather(task,return_exceptions=True)
            await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_closed_work_budget_refusal_preserves_state_and_does_not_retry_a_duplicate(dm,monkeypatch):
    from app.data_engine.memory_budget import MemoryBudgetExceeded
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    original=dm.memory_budget.reserve
    refused=[]
    def reserve(owner,size,**kwargs):
        if owner=='realtime-state' and size>65536:
            refused.append(size)
            raise MemoryBudgetExceeded('controlled closed-work refusal')
        return original(owner,size,**kwargs)
    async def run():
        try:
            values,interval,state,_,close=await prepare(dm,clock,7)
            monkeypatch.setattr(dm.memory_budget,'reserve',reserve)
            await close()
            assert len(refused)==1 and len(state.source_snapshots)==7 and state._history_prefix is None
            assert state.status.value=='closed' and state.volume==28
            runtime=dm.history_prefix_runtime
            assert runtime.last_closed_compaction['reason']=='MemoryBudgetExceeded' and not runtime.targets
            await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',interval,component(values[-1]))
            assert len(refused)==1
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_existing_timer_drains_closed_work_without_blocking_the_next_forming_bucket(dm,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    entered,released=threading.Event(),threading.Event()
    runtime=dm.history_prefix_runtime
    original=runtime.reader.matches_closed_overlay
    def held(*args,**kwargs):
        entered.set()
        assert released.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(runtime.reader,'matches_closed_overlay',held)
    async def run():
        try:
            _,interval,state,_,close=await prepare(dm,clock,7)
            await close(drain=False)
            async with asyncio.timeout(5):
                while not entered.is_set(): await asyncio.sleep(.01)
            assert runtime.snapshot()['closed_job_inflight']
            value=rows(8)[-1]
            forming=replace(component(value),is_closed=False)
            async with asyncio.timeout(1):
                await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',interval,forming)
            current=dm.bar_aggregator.get_pipeline(interval).bar_state.get_active('binance','futures','BTCUSDT',7*WIDTH)
            assert current.volume==8 and state._history_prefix is None
            released.set()
            async with asyncio.timeout(5):
                while not runtime.metrics['closed_compactions']: await asyncio.sleep(.01)
            assert not state.source_snapshots and state._history_prefix.complete
            assert current.volume==8 and current.status.value=='forming'
        finally:
            released.set()
            await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_fresh_closed_rebuild_does_not_forget_an_explicit_target_delete(dm,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    async def run():
        try:
            values,interval,state,observed,close=await prepare(dm,clock,7)
            await close()
            async with asyncio.timeout(5):
                while not observed: await asyncio.sleep(.01)
            old_floor=state.acquisition_revision
            dm.query_engine.storage.delete_bars('BTCUSDT',interval,0,0,market_type='futures')
            changed=dict(values[0],volume=2.,quote_volume=4.)
            persist([changed])
            await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',interval,component(changed,correction=True))
            await dm.aggregator_bridge.delivery.flush()
            assert state.canonical_recovery_delete_floor==old_floor
            assert state.acquisition_revision>old_floor
            assert not dm.query_engine.storage.query_bars('BTCUSDT',interval,0,0,market_type='futures')
            assert observed==[(DataEventType.BAR_CLOSED,28)]
            assert dm.aggregator_bridge.delivery.snapshot()['rejected']>=1
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_bounded_maintenance_jobs_drain_one_and_detach_without_deleting_history(dm,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    runtime=dm.history_prefix_runtime
    monkeypatch.setattr(runtime,'MAX_CLOSED_JOBS',2)
    async def run():
        try:
            _,interval,first,_,close=await prepare(dm,clock,7)
            # This test drives the same service deterministically; the separate
            # timer test proves the automatic lifecycle and concurrent input.
            task=dm.bar_aggregator._timeout_task
            task.cancel()
            await task
            dm.bar_aggregator._timeout_task=None
            await close(drain=False)
            for value in rows(21)[7:]: await close(drain=False,last=value)
            assert len(runtime.closed_jobs)==2 and runtime.metrics['closed_jobs_refused']==1
            async with asyncio.timeout(5):
                while True:
                    await dm.aggregator_bridge.delivery.flush()
                    stored=dm.query_engine.storage.query_bars('BTCUSDT',interval,market_type='futures')
                    if len(stored)==3: break
                    await asyncio.sleep(.01)
            assert [row['volume'] for row in stored]==[28,77,126]
            await runtime.drain_closed()
            assert runtime.metrics['closed_compactions']==1 and len(runtime.closed_jobs)==1
            assert not first.source_snapshots
            engine=dm.bar_aggregator.get_pipeline(interval).bar_state
            assert len(engine.get_closed('binance','futures','BTCUSDT',7*WIDTH).source_snapshots)==7
            dm.bar_aggregator.remove_target('BTCUSDT',interval,market_type='futures')
            assert not runtime.closed_jobs
            assert len(dm.query_engine.storage.query_bars('BTCUSDT',interval,market_type='futures'))==3
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_obsolete_readback_preserves_newer_closed_jobs_for_the_same_target(dm,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    runtime=dm.history_prefix_runtime
    entered,released=threading.Event(),threading.Event()
    original=runtime.reader.matches_closed_overlay
    blocked=[True]
    def held(*args,**kwargs):
        if blocked[0]:
            entered.set()
            assert released.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(runtime.reader,'matches_closed_overlay',held)
    async def run():
        task=None
        try:
            _,interval,first,_,close=await prepare(dm,clock,7)
            task=asyncio.create_task(close())
            async with asyncio.timeout(5):
                while not entered.is_set(): await asyncio.sleep(.01)
            for value in rows(14)[7:]: await close(drain=False,last=value)
            assert len(runtime.closed_jobs)==1
            blocked[0]=False;released.set()
            await task
            assert first._history_prefix is None and len(first.source_snapshots)==7
            assert len(runtime.closed_jobs)==1
            await runtime.drain_closed()
            second=dm.bar_aggregator.get_pipeline(interval).bar_state.get_closed('binance','futures','BTCUSDT',7*WIDTH)
            assert second._history_prefix.complete and not second.source_snapshots
        finally:
            released.set()
            if task is not None: await asyncio.gather(task,return_exceptions=True)
            await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())
