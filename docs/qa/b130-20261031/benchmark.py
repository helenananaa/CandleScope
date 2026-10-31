"""Same-input B130 cost and retention probe; no network or user database."""
import gc, json, statistics, sys, time, tracemalloc
from pathlib import Path
root=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root/'backend'))
from tests.test_shared_aggregation_blocks import manager, consume, key
from tests.test_custom_history_streaming import rows
from app.data_engine.aggregation.history_blocks import aggregate_closed_history
from app.data_engine.data_manager.custom_query import _aggregate_fixed_bars_to_interval
from app.data_engine.data_manager.models import SeriesKey
source=rows(384,86400)
series=SeriesKey('BTCUSDT','1d')
m=manager(max_bytes=4*1024*1024)
def run(shared):
    outputs=[]
    for factor in (2,4,5,7):
        fallback=lambda bars: _aggregate_fixed_bars_to_interval(bars,factor*86400,source_interval_seconds=86400)
        outputs.append(aggregate_closed_history(m,source,source_key=series,source_seconds=86400,
            width=factor*86400,phase_seconds=0,acquired_at=None,fallback=fallback) if shared else fallback(source))
    return outputs
run(True)
timing={'baseline':{'ms':[]},'shared':{'ms':[]}}
run(False)
for index in range(7):
    for shared in ((False,True) if index%2==0 else (True,False)):
        start=time.perf_counter(); outputs=run(shared)
        timing['shared' if shared else 'baseline']['ms'].append((time.perf_counter()-start)*1000)
for value in timing.values(): value['median_ms']=statistics.median(value['ms'])
expected,actual=run(False),run(True)
maximum=0
for aa,bb in zip(actual,expected):
    assert len(aa)==len(bb)
    for a,b in zip(aa,bb):
        assert (a.time,a.is_closed)==(b.time,b.is_closed)
        for f in ('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote'):
            av,bv=getattr(a,f),getattr(b,f)
            if av is None or bv is None: assert av is bv
            else:
                assert abs(av-bv)<=max(1e-8,abs(bv)*1e-12)
                maximum=max(maximum,abs(av-bv))
qualified=m.snapshot()
m.close()
tracemalloc.start()
stress=manager(max_entries=32,max_bytes=256*1024)
samples=[]
for i in range(2000):
    if i >= 1000 and i%113==0: stress.source.amend()
    consume(stress,key(i%97))
    if (i+1)%500==0:
        gc.collect(); current,peak=tracemalloc.get_traced_memory()
        samples.append({'operations':i+1,'traced_current':current,'traced_peak':peak,'blocks':stress.snapshot(),'budget':stress.budget.snapshot(measure_heap=True)})
stress.close(); gc.collect()
end={'blocks':stress.snapshot(),'budget':stress.budget.snapshot(),'traced_current':tracemalloc.get_traced_memory()[0]}
assert end['blocks']['estimated_bytes']==end['blocks']['views']==end['blocks']['leases']==end['blocks']['inflight']==0
assert end['budget']['reserved_bytes']==0
print(json.dumps({'timing':timing,'scope':'384 immutable daily bars -> 2d/4d/5d/7d; 7 alternating warm trials; synthetic revision source; no I/O timings','max_absolute_error':maximum,'qualified':qualified,'stress_samples':samples,'after_close':end},indent=2))
