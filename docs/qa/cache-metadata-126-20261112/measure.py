"""Metadata accounting microcost; use the same script/interpreter with two backends.
PYTHONPATH=/checkout/backend python measure.py LABEL > result.json
No network, SQLite or native performance qualification. No user data.
"""
from collections import deque
import hashlib
import json
import statistics
import sys
import time
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.data_manager.revisions import CacheRevisionConsumer
from app.data_engine.memory_budget import MemoryBudget

class Store:
    def changes_since(self, revision):
        return dict(revision=4096,reset=False,changes=changes) if revision == 0 else dict(revision=4096,reset=False,changes=[])
changes = []
for number in range(1,4097):
    key = SeriesKey(f'HISTORY{number}USDT','1m')
    data = {name:getattr(key,name) for name in key.__slots__}
    data.update(revision=number,readback_revision=number,readback_previous=number-1,
                readback_start_ms=0,readback_end_ms=59999)
    changes.append(data)
cache = BarCache()
for number in range(200):
    cache.upsert(SeriesKey(f'LIVE{number}USDT','1m'), BarData(0,1,2,.5,1,1))
consumer=CacheRevisionConsumer(cache,Store());consumer.readbacks_enabled=True
cache.revision_consumer=consumer;consumer.sync(force=True)
budget=MemoryBudget();budget.register('bar-cache',limit_bytes=128*1024*1024,usage=cache.memory_usage,roots=cache._memory_roots)

def sample(function):
    for _ in range(20): function()
    samples=[]
    for _ in range(1000):
        began=time.perf_counter_ns();function();samples.append((time.perf_counter_ns()-began)/1000)
    samples.sort()
    return dict(p50_us=statistics.median(samples),p95_us=samples[950],p99_us=samples[990],samples=len(samples))

def reservation():
    with budget.reserve('bar-cache',1): pass

print(json.dumps(dict(label=sys.argv[1],python=sys.version,source=__import__('app.data_engine.data_manager.cache',fromlist=['x']).__file__,
    limitation='One uncontrolled-host microbenchmark pair; no end-to-end latency/RSS improvement claim',
    input_hash=hashlib.sha256(json.dumps(changes,sort_keys=True).encode()).hexdigest(),
    scenarios={name:sample(fn) for name,fn in [('cache_usage',cache.memory_usage),('budget_snapshot',budget.snapshot),('admission',reservation)]},
    cache=cache.memory_usage(),heap=budget.snapshot(measure_heap=True),
    recent_entries=len(consumer._recent),pending_readbacks=len(consumer._readbacks)),indent=2))
