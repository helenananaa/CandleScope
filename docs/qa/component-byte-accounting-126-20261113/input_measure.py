"""Same-input R129 work/heap comparison; one case per process, no public I/O.

PYTHONPATH=/checkout/backend python measure.py baseline|independent|shared single|multi|long
Use the full baseline backend for baseline, the product for the other variants.
These are controlled reducer/preparation costs with previews disabled, not
native, network, indicator or whole-application performance qualification.
"""
import asyncio
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import tempfile
import time
import tracemalloc

isolated = tempfile.TemporaryDirectory()
os.environ['CANDLE_DATA_DIR'] = isolated.name
from app.data_engine.bar_aggregator import BarAggregator,BarAggregatorConfig
from app.data_engine.bar_aggregator import bar_state as state_module
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.models import BarData,SeriesKey
from app.data_engine.ingestion.models import MarketEvent,StreamType,DataSource
from app.data_engine.memory_budget import MemoryBudget,retained_size

variant,case = sys.argv[1:3]
periods,warm,samples = {
    'single':(('1m','89m'),32,512),
    'multi':(('1m','89m','97m','101m','10007m'),64,512),
    'long':(('1m','10007m','10009m','10037m','10039m'),2048,256),
    'near_tail':(('1m','10007m','10009m','10037m','10039m'),10000,64),
}[case]


def record(index):
    return dict(open_time=index*60000,close_time=(index+1)*60000-1,
        open=100.,high=102.,low=99.,close=101.,volume=1.,quote_volume=2.,
        trades=1,taker_buy_base=.4,taker_buy_quote=.8)


def event(step):
    data={**record(warm),'interval':'1m','is_closed':False,'volume':float(step),
          'quote_volume':float(2*step),'trades':step,'taker_buy_base':step*.4,'taker_buy_quote':step*.8}
    stamp=warm*60000+step+1
    return MarketEvent(StreamType.KLINE,'BTCUSDT','binance',stamp,stamp,
        DataSource.WEBSOCKET,data,sequence=stamp,market_type='futures')


def percentiles(values):
    values=sorted(values)
    return dict(p50_us=statistics.median(values),p95_us=values[int(len(values)*.95)],
                p99_us=values[int(len(values)*.99)],samples=len(values))


async def main():
    cfg=BarAggregatorConfig(emit_created_events=False,emit_updated_events=False,
        emit_expired_events=False,finalize_timeout_ms=10**15,update_throttle_ms=0)
    if hasattr(cfg,'shared_component_inputs'):
        cfg.shared_component_inputs=variant=='shared'
    agg=BarAggregator(cfg)
    for interval in periods:
        agg.add_target('BTCUSDT',interval,market_type='futures')
    cache=BarCache()
    for index in range(200):
        cache.upsert(SeriesKey(f'CACHED{index}USDT','1m'),BarData(0,100,102,99,101,1))
    budget=MemoryBudget()
    budget.register('bar-cache',limit_bytes=128*1024*1024,usage=cache.memory_usage,roots=cache._memory_roots)
    budget.register('realtime-state',limit_bytes=128*1024*1024,usage=agg.memory_usage,roots=agg._memory_roots)
    agg.memory_budget=budget
    normalizations=0
    original=state_module.snapshot_aggregation_values
    def counted(value):
        nonlocal normalizations
        normalizations+=1
        return original(value)
    state_module.snapshot_aggregation_values=counted
    rows=[record(index) for index in range(warm)]
    # Resolve/import the provider before tracing source-state retention.
    await agg.on_backfill_bars('BTCUSDT','1m',rows[:1],market_type='futures')
    gc.collect()
    tracemalloc.start()
    await agg.on_backfill_bars('BTCUSDT','1m',rows[1:],market_type='futures')
    traced_current,traced_peak=tracemalloc.get_traced_memory()
    tracemalloc.stop()
    warm_normalizations=normalizations
    # Resolve realtime routes and initialize the current tail outside timing.
    await agg.on_market_event(event(1))
    before=normalizations
    wall,cpu=[],[]
    for step in range(2,samples+2):
        value=event(step)
        started=time.perf_counter_ns();cpu_start=time.process_time_ns()
        await agg.on_market_event(value)
        cpu.append((time.process_time_ns()-cpu_start)/1000)
        wall.append((time.perf_counter_ns()-started)/1000)
    final=[]; components=[]
    for interval in periods:
        width=int(interval[:-1])*60000
        opened=warm*60000//width*width
        state=agg.get_pipeline(interval).bar_state.get_state('binance','futures','BTCUSDT',opened)
        final.append(dict(interval=interval,row=state.to_storage_dict(),status=state.status.value,
            finality=state.finality.value,ticks=state.tick_count,first=state.first_input_at_ms,last=state.last_input_at_ms))
        components.extend(state.source_snapshots.values())
    # Hold all temporary owner views through the traversal, including when
    # measuring the baseline whose registry can recycle earlier view IDs.
    root_views=[cache._memory_roots(),agg._memory_roots()]
    seen=set()
    held_heap=sum(retained_size(roots,seen)[0] for roots in root_views)
    result=dict(variant=variant,case=case,python=sys.version,platform=platform.platform(),
        backend=str(Path(state_module.__file__).resolve()),periods=periods,warm_rows=warm,
        preview_contract='created/updated previews disabled for isolated computation cost; closes retained',
        input_hash=hashlib.sha256(json.dumps(dict(rows=rows,last=event(samples+1).data),sort_keys=True).encode()).hexdigest(),
        final_hash=hashlib.sha256(json.dumps(final,sort_keys=True).encode()).hexdigest(),final=final,
        wall=percentiles(wall),cpu=percentiles(cpu),warm_normalizations=warm_normalizations,
        measured_normalizations=normalizations-before,
        component_references=len(components),unique_component_values=len({id(value) for value in components}),
        component_graph_bytes=retained_size([components])[0],
        held_root_heap_bytes=held_heap,
        traced_warm_retained=traced_current,traced_warm_peak=traced_peak,
        memory=budget.snapshot(measure_heap=True),diagnostics=agg.memory_usage(),
        process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        rss_scope='whole interpreter maximum; not solely aggregation and not a release/RSS budget pass')
    assert budget.snapshot()['reserved_bytes']==0
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    asyncio.run(main())
