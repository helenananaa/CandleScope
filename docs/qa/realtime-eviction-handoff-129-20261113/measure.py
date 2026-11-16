"""Controlled engine-buffer publication, no network/source qualification.
Run in one fresh process per checkout: PYTHONPATH=backend python measure.py COUNT
"""
import asyncio
from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path
import platform
import resource
import statistics
import sys
import time

from app.data_engine.memory_budget import MemoryBudget
from app.data_engine.bar_aggregator import aggregator as module
from tests.test_realtime_handoff_accounting import populated

FIELDS=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
count=int(sys.argv[1])

async def main():
    agg,state=await populated(source_refs=True)
    pipeline=agg.get_pipeline('97m');buffer=pipeline.bar_state.evicted_closed
    agg.remove_target('BTCUSDT','97m')
    budget=MemoryBudget(128*1024**2)
    budget.register('realtime-state',limit_bytes=128*1024**2,usage=agg.memory_usage,roots=agg._memory_roots)
    seen=[];block=False;entered=asyncio.Event();release=asyncio.Event()
    async def callback(event):
        seen.append((event.bar.bucket_start_ms,*(getattr(event.bar,k) for k in FIELDS)))
        if block and len(seen)==count:entered.set();await release.wait()
    agg.publisher.on_bar_closed(callback)
    def fill():
        for i in range(count):
            bar=deepcopy(state);bar.bucket_start_ms=i*97*60000;buffer.append(bar)
    fill();block=True;task=asyncio.create_task(agg._drain_eviction_buffers(pipeline))
    try:
        await asyncio.wait_for(entered.wait(),10)
        held=budget.snapshot(measure_heap=True)['owners']['realtime-state']
    finally:release.set();await task
    assert len(seen)==count and not buffer and not agg.publisher._pending_source_events
    after=budget.snapshot(measure_heap=True)['owners']['realtime-state'];block=False
    cpu=[];wall=[];hashes=[]
    gc.collect();before=gc.get_stats()
    for _ in range(32):
        seen.clear();fill() # construction outside publication timing in both variants
        stamp=time.process_time_ns();started=time.perf_counter_ns()
        await agg._drain_eviction_buffers(pipeline)
        cpu.append((time.process_time_ns()-stamp)/1000);wall.append((time.perf_counter_ns()-started)/1000)
        assert len(seen)==count and [x[0] for x in seen]==[i*97*60000 for i in range(count)]
        assert not buffer and not agg.publisher._pending_source_events
        hashes.append(hashlib.sha256(json.dumps(seen).encode()).hexdigest())
    assert len(set(hashes))==1 and budget.snapshot()['reserved_bytes']==0
    def pct(values):
        values=sorted(values)
        return {'samples':len(values),'p50_us':statistics.median(values),'p95_us':values[int(.95*len(values))],'p99_us':values[int(.99*len(values))]}
    print(json.dumps(dict(backend=str(Path(module.__file__).resolve()),python=sys.version,platform=platform.platform(),
        count=count,components_per_state=97,payload_hash=hashes[0],held=held,after=after,cpu=pct(cpu),wall=pct(wall),
        gc_before=before,gc_after=gc.get_stats(),process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        scope='controlled accepted component fixtures and direct engine buffers; no network/source authority or stable performance/native qualification'),indent=2))

if __name__=='__main__':asyncio.run(main())
