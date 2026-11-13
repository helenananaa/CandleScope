"""First live prefix uses existing maintenance and preserves the accepted tail."""
import asyncio
from dataclasses import replace
import threading

import pytest

from app.data_engine.bar_aggregator.models import BarInputSource
from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamType
from app.data_engine.storage import klines_repo
from tests.test_closed_component_retention import FIELDS, WIDTH, Ingestion, component, persist, rows
from tests.test_shared_blocks_integration import dm

TARGET='10007m'


async def flush_native(dm,count):
    async with asyncio.timeout(5):
        while True:
            await dm.aggregator_bridge.delivery.flush()
            stored=dm.query_engine.storage.query_bars('BTCUSDT','1m',market_type='futures',limit=count)
            if len(stored)==count: return
            await asyncio.sleep(.01)


async def start(dm,clock,*,timer=False):
    ingestion=Ingestion()
    dm.set_ingestion_factory(ingestion)
    await dm.start()
    if not timer:
        task=dm.bar_aggregator._timeout_task
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        dm.bar_aggregator._timeout_task=None
    # Capture original publisher output; no extra consumer changes production
    # demand, source leases or update-throttle behavior.
    events=[]
    async def receive(e): events.append((e.event_type.value,e.bar.volume))
    dm.bar_aggregator.publisher.on_bar_event(receive)
    await dm.ensure_stream('BTCUSDT',TARGET,market_type='futures')
    async def send(value,closed=True):
        clock[0]=max(clock[0],value['close_time']+1001)
        await ingestion.send(MarketEvent(event_type=StreamType.KLINE,symbol='BTCUSDT',exchange='binance',
            market_type='futures',event_time_ms=clock[0],received_at_ms=clock[0],sequence=clock[0],
            source=DataSource.WEBSOCKET,data=dict(interval='1m',is_closed=closed,**value)))
    def current():
        return dm.bar_aggregator.get_pipeline(TARGET).bar_state.get_active('binance','futures','BTCUSDT',0)
    return send,current,events


def test_empty_live_bucket_establishes_prefix_then_uses_existing_rollover(dm,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    async def run():
        try:
            send,current,events=await start(dm,clock)
            values=rows(261)
            for row in values[:128]: await send(row)
            state=current()
            assert state._history_prefix is None and len(state.source_snapshots)==128
            assert len(dm.history_prefix_runtime.component_jobs)==1
            fields=(*FIELDS,'enhanced_fields','status','finality','created_at_ms','updated_at_ms',
                    'acquisition_revision','preview_input_version','preview_computed_version','preview_published_version')
            before=tuple(getattr(state,f) for f in fields)
            before_events=list(events)
            await dm.history_prefix_runtime.drain_components()
            assert state._history_prefix is not None,dm.history_prefix_runtime.last_forming_compaction
            assert state._history_prefix.through_ms==128*WIDTH and not state.source_snapshots
            assert tuple(getattr(state,f) for f in fields)==before and events==before_events
            assert dm.history_prefix_runtime.metrics['forming_compactions']==1
            for row in values[128:]: await send(row)
            assert state._history_prefix.through_ms==256*WIDTH
            assert len(state.source_snapshots)==5
            assert state.volume==sum(r['volume'] for r in values)
            assert state.tick_count==261 and state.status.value=='forming'
            assert dm.history_prefix_runtime.metrics['compacted_components']==128
            # A canonical correction to a retired first leaf refreshes, and
            # does not replay the old raw receipt as an additional component.
            changed=dict(values[0],volume=0.,quote_volume=0.,high=11.)
            persist([changed])
            await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',TARGET,component(changed,correction=True))
            assert current().volume==sum(r['volume'] for r in values)-1
            assert current().tick_count==261 and len(current().source_snapshots)==5
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


@pytest.mark.parametrize('variant',['disabled','missing','opposite','unknown','unclosed','budget'])
def test_unproved_first_prefix_keeps_live_inputs_and_bounds_failed_retries(dm,monkeypatch,variant):
    from app.data_engine.memory_budget import MemoryBudgetExceeded
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    async def run():
        try:
            send,current,events=await start(dm,clock)
            if variant=='disabled': dm.bar_aggregator.config.compact_forming_components=False
            values=rows(129)
            for i,row in enumerate(values[:128]): await send(row,closed=not(variant=='unclosed' and i==2))
            await flush_native(dm,127 if variant=='unclosed' else 128)
            if variant=='missing': dm.query_engine.storage.delete_bars('BTCUSDT','1m',0,0,market_type='futures')
            if variant=='opposite': persist([dict(values[0],volume=2.),dict(values[1],volume=1.)])
            if variant=='unknown':
                with klines_repo._connect() as conn:
                    conn.execute("UPDATE klines SET quote_volume=NULL WHERE symbol='BTCUSDT' AND interval='1m' AND open_time=0")
            if variant=='budget':
                original=dm.memory_budget.reserve
                def reserve(owner,amount,*args,**kwargs):
                    if owner=='realtime-state' and amount>16384: raise MemoryBudgetExceeded('controlled first-prefix work refusal')
                    return original(owner,amount,*args,**kwargs)
                monkeypatch.setattr(dm.memory_budget,'reserve',reserve)
            before=list(events)
            await dm.history_prefix_runtime.drain_components()
            assert current()._history_prefix is None and len(current().source_snapshots)==128
            assert current().volume==sum(r['volume'] for r in values[:128]) and events==before
            attempts=dm.history_prefix_runtime.metrics['forming_compaction_deferred']
            assert attempts==(0 if variant=='disabled' else 1)
            for _ in range(3): await send(values[127])
            await dm.history_prefix_runtime.drain_components()
            assert dm.history_prefix_runtime.metrics['forming_compaction_deferred']==attempts
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


@pytest.mark.parametrize('action',['tail','leaf','detach','rebind','cancel','close','disable','storage','config','strategy','method'])
def test_first_prefix_physical_read_lifetime_and_live_concurrency(dm,monkeypatch,action):
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
        task=closing=None
        try:
            send,current,events=await start(dm,clock)
            values=rows(129)
            for row in values[:128]: await send(row)
            state=current()
            await flush_native(dm,128)
            task=asyncio.create_task(dm.history_prefix_runtime.drain_components())
            async with asyncio.timeout(5):
                while not entered.is_set() and not task.done(): await asyncio.sleep(.01)
            assert entered.is_set(),dm.history_prefix_runtime.last_forming_compaction
            reserved=dm.memory_budget.snapshot()['reserved_bytes']
            assert reserved>128*1024
            if action=='tail':
                # No native close commit changes the canonical read view.
                # The ordinary forming cumulative tail can keep advancing.
                async with asyncio.timeout(1): await send(values[128],closed=False)
                assert len(state.source_snapshots)==129
            elif action=='leaf':
                changed=dict(values[0],volume=0.,quote_volume=0.)
                # Change accepted evidence without modifying storage, proving
                # the final leaf-identity fence independently of D126 fencing.
                async with asyncio.timeout(1):
                    await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',TARGET,replace(component(changed,correction=True),sequence=clock[0]+1))
                assert state.volume==sum(r['volume'] for r in values[:128])-1
            elif action=='detach': dm.bar_aggregator.remove_target('BTCUSDT',TARGET,market_type='futures')
            elif action=='rebind':
                dm.bar_aggregator.remove_target('BTCUSDT',TARGET,market_type='futures')
                dm.bar_aggregator.add_target('BTCUSDT',TARGET,market_type='futures')
            elif action=='cancel': task.cancel()
            elif action=='close': closing=asyncio.create_task(dm.history_prefix_runtime.close())
            elif action=='disable': dm.bar_aggregator.config.compact_forming_components=False
            elif action=='storage': dm.set_storage(klines_repo.KlinesRepoAdapter())
            elif action=='config': dm.bar_aggregator._cfg=replace(dm.bar_aggregator.config)
            elif action=='method':
                monkeypatch.setattr(dm.bar_aggregator.get_pipeline(TARGET).bar_state._component_merge_strategy,
                                    'apply',lambda *_args,**_kwargs:None)
            else:
                from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
                dm.bar_aggregator.get_pipeline(TARGET).bar_state._component_merge_strategy=ComponentSnapshotOHLCVMerge()
            await asyncio.sleep(.01)
            assert not task.done() and dm.memory_budget.snapshot()['reserved_bytes']>=reserved
            if action=='detach':
                assert dm.bar_aggregator.memory_usage()['retained_component_payload_bytes']>=state.source_snapshots.estimated_bytes
            released.set()
            if action in {'cancel','close'}:
                with pytest.raises(asyncio.CancelledError): await task
            else: await task
            if closing is not None: await closing
            if action=='tail':
                assert state._history_prefix is not None,dm.history_prefix_runtime.last_forming_compaction
                assert len(state.source_snapshots)==1 and state.volume==sum(r['volume'] for r in values)
                assert state.preview_input_version==state.preview_computed_version
            else:
                assert state._history_prefix is None and len(state.source_snapshots)==128
                assert dm.history_prefix_runtime.metrics['forming_compactions']==0
        finally:
            released.set()
            if task is not None: await asyncio.gather(task,return_exceptions=True)
            if closing is not None: await closing
            await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_original_timer_adopts_first_prefix_without_another_market_input(dm,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    async def run():
        try:
            send,current,events=await start(dm,clock)
            for row in rows(128): await send(row)
            await flush_native(dm,128)
            assert current()._history_prefix is None
            before=list(events)
            # Restart the original loop, with the same production interval,
            # after fixture preparation. No new input or manual drain follows.
            await dm.bar_aggregator.start()
            async with asyncio.timeout(6):
                while current()._history_prefix is None: await asyncio.sleep(.01)
            assert not current().source_snapshots
            assert current().volume==128*129/2 and events==before
            assert dm.history_prefix_runtime.metrics['forming_compactions']==1
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_source_delete_after_first_live_prefix_preserves_gap_and_delete_floor(dm,monkeypatch):
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    async def run():
        try:
            send,current,events=await start(dm,clock)
            values=rows(129)
            for row in values[:128]: await send(row)
            await flush_native(dm,128)
            await dm.history_prefix_runtime.drain_components()
            assert current()._history_prefix is not None
            floor=current().acquisition_revision
            dm.query_engine.storage.delete_bars('BTCUSDT','1m',0,0,market_type='futures')
            await send(values[128],closed=False)
            assert not current()._history_prefix.complete
            assert current().status.value=='forming' and current().finality.value=='provisional'
            assert current().volume==sum(r['volume'] for r in values)-1
            assert current().canonical_recovery_delete_floor==floor
            assert current().acquisition_revision>floor
            assert dm.query_engine.storage.count_bars('BTCUSDT','1m',0,0,market_type='futures')==0
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_forming_prefix_refresh_cannot_recreate_explicitly_deleted_target(dm,monkeypatch):
    import sys
    from app.data_engine.bar_aggregator.history_prefix_runtime import HistoryPrefixRuntime
    monkeypatch.setattr(sys.modules[__name__],'TARGET','7m')
    monkeypatch.setattr(HistoryPrefixRuntime,'MIN_ROWS',2)
    monkeypatch.setattr(HistoryPrefixRuntime,'COMPACT_ROWS',2)
    clock=[1000]
    monkeypatch.setattr('time.time',lambda:clock[0]/1000)
    async def run():
        try:
            send,current,events=await start(dm,clock)
            values=rows(7)
            for row in values[:2]: await send(row)
            await flush_native(dm,2)
            # Existing warm-prefix adoption also reproduces this permission
            # regression on the complete old backend, independently of the new
            # first-live-prefix feature and its renamed maintenance diagnostics.
            from app.data_engine.data_manager.models import SeriesKey
            key=SeriesKey('BTCUSDT','1m',market_type='futures')
            assert await dm.history_prefix_runtime.seed(key,TARGET,0,2*WIDTH)
            state=current()
            floor=state.acquisition_revision
            historical=dict(values[0],close_time=7*WIDTH-1,volume=28.,quote_volume=56.,trades=28)
            klines_repo.upsert_klines('BTCUSDT',TARGET,[historical],source='backfill',market_type='futures')
            dm.query_engine.storage.delete_bars('BTCUSDT',TARGET,0,0,market_type='futures')
            changed=dict(values[0],volume=0.,quote_volume=0.,high=11.)
            persist([changed,*values[2:]])
            clock[0]=7*WIDTH+1000
            for row in values[2:]:
                await dm.bar_aggregator.ingest_bar_input('binance','futures','BTCUSDT',TARGET,component(row))
            await dm.aggregator_bridge.delivery.flush()
            assert state.status.value=='closed' and state.volume==27
            assert not dm.query_engine.storage.query_bars('BTCUSDT',TARGET,0,0,market_type='futures')
            assert state.canonical_recovery_delete_floor==floor
            assert dm.aggregator_bridge.delivery.snapshot()['rejected']>=1
        finally: await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())
