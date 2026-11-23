"""Per-process controlled publication accounting/cost comparison.

PYTHONPATH=/checkout/backend python measure.py PERIOD pending|callback
The default DataManager budget is used; source components and callback faults
are deterministic. No public network or native/performance acceptance is claimed.
"""
import asyncio
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import tempfile
import time

isolated=tempfile.TemporaryDirectory();os.environ['CANDLE_DATA_DIR']=isolated.name
from app.core import config
from app.data_engine.bar_aggregator import BarInput,BarInputSource,MergeMode
from app.data_engine.bar_aggregator import publisher as module
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.data_manager import DataManager
from app.data_engine.memory_budget import retained_size
from app.data_engine.storage import klines_repo

period=int(sys.argv[1]);scenario=sys.argv[2]
FIELDS=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def percentiles(values):
    values=sorted(values)
    return dict(samples=len(values),p50_us=statistics.median(values),p95_us=values[int(len(values)*.95)],p99_us=values[int(len(values)*.99)])


async def main():
    database=Path(isolated.name)/'market.sqlite'
    klines_repo.KLINES_DB_PATH=database;config.KLINES_DB_PATH=database;klines_repo.init_klines_storage()
    dm=DataManager();dm.set_storage(klines_repo.KlinesRepoAdapter());agg=dm.bar_aggregator
    agg.add_target('BTCUSDT',f'{period}m')
    async def no_siblings(*args):return []
    if scenario=='pending':agg.set_source_component_reader(no_siblings)
    for index in range(period):
        value=BarInput(symbol='BTCUSDT',source_interval='1m',open_time_ms=index*60000,
            close_time_ms=(index+1)*60000-1,open=100.,high=102.,low=99.,close=101.,volume=1.,
            quote_volume=101.,trades=1,taker_buy_base=.4,taker_buy_quote=40.,
            enhanced_fields=frozenset({'quote_volume','trades','taker_buy_base','taker_buy_quote'}),
            source=BarInputSource.BACKFILL,is_closed=True,merge_mode=MergeMode.COMPONENT,
            extra={'source_ref':{'series':'controlled-source','revision':index+1}} if scenario=='pending' else {})
        await agg.ingest_bar_input('binance','spot','BTCUSDT',f'{period}m',value,emit_events=False)
    state=agg.get_pipeline(f'{period}m').bar_state.get_closed('binance','spot','BTCUSDT',0)
    expected=state.to_storage_dict();seen=[];blocked=True;timing=False
    entered,released=asyncio.Event(),asyncio.Event()
    async def callback(event):
        if scenario=='pending' and blocked:raise BarDeliveryUnavailable('controlled source handoff outage')
        if scenario=='callback' and blocked:entered.set();await released.wait()
        seen.append(tuple(getattr(event.bar,name) for name in FIELDS) if timing
                    else digest(event.bar.to_storage_dict()))
    agg.publisher.on_bar_closed(callback)
    task=None
    try:
        if scenario=='pending':
            try:await agg.publisher.emit_closed(state)
            except BarDeliveryUnavailable:pass
        else:
            task=asyncio.create_task(agg.publisher.emit_closed(state))
            await asyncio.wait_for(entered.wait(),2)
        agg.remove_target('BTCUSDT',f'{period}m')
        held=dm.memory_budget.snapshot(measure_heap=True)['owners']['realtime-state']
        pending_graph=retained_size(list(agg.publisher._pending_source_events.values()))[0]
        pending_count=len(agg.publisher._pending_source_events)
        blocked=False;released.set()
        if task:await task
        if scenario=='pending':await agg.publisher.retry_source_deliveries()
        assert seen==[digest(expected)]
        assert not agg.publisher._pending_source_events
        after=dm.memory_budget.snapshot(measure_heap=True)['owners']['realtime-state']
        # Time unchanged explicit publication, not state construction or heap traversal.
        seen.clear()
        timing=True
        for _ in range(4):await agg.publisher.emit_closed(state)
        samples=64 if period>1000 else 256;cpu=[];wall=[]
        gc.collect();gc_before=gc.get_stats()
        for _ in range(samples):
            started=time.perf_counter_ns();stamp=time.process_time_ns()
            await agg.publisher.emit_closed(state)
            cpu.append((time.process_time_ns()-stamp)/1000);wall.append((time.perf_counter_ns()-started)/1000)
        assert len(seen)==samples+4 and set(seen)=={tuple(getattr(state,name) for name in FIELDS)}
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
        result=dict(python=sys.version,platform=platform.platform(),backend=str(Path(module.__file__).resolve()),
            period=period,scenario=scenario,source='deterministic controlled accepted components; no network/repo source qualification',
            owner='default DataManager realtime-state registration; manager not started, storage bridge callback remains inactive',
            payload_hash=digest(expected),components=len(state.source_snapshots),held=held,after=after,
            pending_before=pending_count,observed_pending_graph_bytes=pending_graph,
            cpu=percentiles(cpu),wall=percentiles(wall),gc_before=gc_before,gc_after=gc.get_stats(),
            process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            limits='heap is diagnostic visibility, not memory reduction/RSS; single-host instrumented callback costs, not product/native acceptance')
        print(json.dumps(result,indent=2))
    finally:
        released.set()
        if task and not task.done():await task
        await dm.shutdown()

if __name__=='__main__':asyncio.run(main())
