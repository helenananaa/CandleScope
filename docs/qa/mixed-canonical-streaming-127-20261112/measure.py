"""Run per fresh process against a full baseline/product backend.

PYTHONPATH=/checkout/backend python measure.py TARGET_MINUTES TARGET_COUNT
Actual default BackfillEngine + SQLite, deterministic synthetic upstream. This
measures instrumented reconciliation work, not public transport/native/RSS limits.
"""
import asyncio
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import tempfile
import time
import tracemalloc

isolated=tempfile.TemporaryDirectory()
os.environ['CANDLE_DATA_DIR']=isolated.name
from app.core import config as core_config
from app.data_engine.backfill import BackfillEngine
from app.data_engine.backfill import reconciler as module
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.models import FetchedBar,FetchResult,BackfillStatus
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.interval_policy import parse_interval_ms
from app.data_engine.storage import klines_repo

period,count=map(int,sys.argv[1:3])
MINUTE=60000
FIELDS=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def percentiles(values):
    if not values:return {'samples':0}
    values=sorted(values)
    return dict(samples=len(values),p50_us=values[len(values)//2],
        p95_us=values[min(len(values)-1,int(len(values)*.95))],
        p99_us=values[min(len(values)-1,int(len(values)*.99))])


class Upstream:
    def __init__(self):self.tasks=[];self.input=[]
    async def close(self):pass
    async def fetch(self,tasks,**options):
        self.tasks.extend(tasks)
        results=[]
        for task in tasks:
            width=parse_interval_ms(task.interval)
            values=[]
            for at in range(task.start_ms,task.end_ms+1,width):
                volume=width//MINUTE
                value=FetchedBar(symbol=task.symbol,interval=task.interval,exchange=task.exchange,
                    market_type=task.market_type,open_time=at,close_time=at+width-1,
                    open=100.,high=102.,low=99.,close=101.,volume=volume,
                    quote_volume=2*volume,trades=volume,taker_buy_base=volume,taker_buy_quote=2*volume,
                    enhanced_fields=frozenset(FIELDS[5:]))
                values.append(value)
                self.input.append((task.interval,at,*(getattr(value,f) for f in FIELDS)))
            results.append(FetchResult(task,values))
        return results


async def main():
    database=Path(isolated.name)/'market.sqlite'
    klines_repo.KLINES_DB_PATH=database;core_config.KLINES_DB_PATH=database
    klines_repo.init_klines_storage()
    cfg=DataManagerConfig();cfg.query.auto_backfill=False
    dm=DataManager(cfg);dm.set_storage(klines_repo.KlinesRepoAdapter())
    config=BackfillConfig();config.history_archive_enabled=False
    config.gap_max_scan_range_ms=period*count*MINUTE
    engine=BackfillEngine(config,storage=klines_repo.AsyncKlinesRepoAdapter())
    engine.memory_budget=dm.memory_budget
    engine._fetcher=upstream=Upstream()
    live=peak=0;phase=False;pages=[];page_rows=[];phase_metrics={}
    class ObservedRow(dict):
        def __init__(self,value):
            nonlocal live,peak
            super().__init__(value);live+=1;peak=max(peak,live)
        def __del__(self):
            nonlocal live
            live-=1
    original_page=engine._storage.query_canonical_page
    async def page(*args,**kwargs):
        started=time.perf_counter_ns()
        values=await original_page(*args,**kwargs)
        if not phase:return values
        pages.append((time.perf_counter_ns()-started)/1000)
        page_rows.append(len(values))
        return [ObservedRow(value) for value in values]
    engine._storage.query_canonical_page=page
    original_reconcile=engine.reconciler.reconcile
    async def reconcile(*args,**kwargs):
        nonlocal phase
        phase=True;gc.collect()
        trace=os.environ.get('CANDLE_BENCH_TRACE','true')!='false'
        if trace:tracemalloc.start()
        started=time.perf_counter_ns();cpu=time.process_time_ns()
        try:return await original_reconcile(*args,**kwargs)
        finally:
            current,maximum=tracemalloc.get_traced_memory() if trace else (None,None)
            if trace:tracemalloc.stop()
            phase_metrics.update(cpu_us=(time.process_time_ns()-cpu)/1000,
                wall_us=(time.perf_counter_ns()-started)/1000,
                traced_end_bytes=current,traced_peak_bytes=maximum,
                live_canonical_rows=live,peak_canonical_rows=peak)
            phase=False
    engine.reconciler.reconcile=reconcile
    try:
        report=await engine.run('BTCUSDT',intervals=[f'{period}m'],range_start_ms=0,
            range_end_ms=(count-1)*period*MINUTE,exchange='binance',market_type='futures',
            metadata=dict(requires_trusted_finality=True,requester='klines_range',history_calendar_id='crypto.24x7.utc'))
        assert report.status==BackfillStatus.COMPLETED,report.errors
        rows=dm.query_engine.storage.query_bars('BTCUSDT',f'{period}m',market_type='futures')
        assert len(rows)==count and all(row['volume']==row['trades']==period for row in rows)
        selected=[{name:row[name] for name in ('open_time','close_time',*FIELDS,'source')} for row in rows]
        assert dm.memory_budget.snapshot()['reserved_bytes']==0
        result=dict(python=sys.version,platform=platform.platform(),backend=str(Path(module.__file__).resolve()),
            scope='actual default BackfillEngine + real fresh SQLite; synthetic upstream, instrumented reconcile phase',
            target_minutes=period,target_count=count,input_hash=digest(upstream.input),result_hash=digest(selected),
            rows=selected,fetch_tasks=len(upstream.tasks),source_rows=len(upstream.input),
            canonical_page_calls=len(pages),canonical_rows_read=sum(page_rows),canonical_page_rows=page_rows,
            canonical_sql_page_wall=percentiles(pages),phase=phase_metrics,
            fetched_rows_retained_in_report=sum(len(result.bars) for result in report.fetch_results),
            native_written=report.reconcile_result.bars_written,
            custom_written=report.reconcile_result.custom_bars_written,
            written_ranges=[value.to_dict() for value in report.written_ranges],
            metrics=engine.reconciler.metrics.snapshot(),budget=dm.memory_budget.snapshot(),
            process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            limits='canonical page counters only, not all SQLite I/O; RSS is whole interpreter maximum; no public network/native/whole-app pass')
        print(json.dumps(result,indent=2))
    finally:
        await engine.close();await dm.shutdown()

if __name__=='__main__':asyncio.run(main())
