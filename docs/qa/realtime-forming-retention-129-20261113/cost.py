"""Independent full backend processes; controlled forming input/maintenance, no network or RSS qualification."""
import argparse
import asyncio
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--mode',choices=['base','disabled','enabled'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sources=sorted((args.source/'backend/app/data_engine/bar_aggregator').glob('*.py'))
    source_hashes={str(p.relative_to(args.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    sys.path.insert(0,str(args.source/'backend'))
    from app.core import config as core_config
    from app.data_engine.bar_aggregator.models import BarInput,BarInputSource,MergeMode
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.config import DataManagerConfig
    from app.data_engine.data_manager.models import DataEventType
    from app.data_engine.ingestion.models import MarketEvent,DataSource,StreamType
    from app.data_engine.storage import klines_repo
    from app.data_engine.memory_budget import retained_size
    fields=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
    clock=[1000]
    time.time=lambda:clock[0]/1000
    digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    async def trial(period,base,attempt):
        clock[0]=1000
        width=base*60000
        count=128
        with tempfile.TemporaryDirectory(prefix='r129-forming-cost-') as temporary:
            klines_repo.KLINES_DB_PATH=core_config.KLINES_DB_PATH=Path(temporary)/'bars.sqlite'
            klines_repo.init_klines_storage()
            cfg=DataManagerConfig(); cfg.query.auto_backfill=False
            dm=DataManager(cfg); dm.set_storage(klines_repo.KlinesRepoAdapter())
            agg=dm.bar_aggregator
            if hasattr(agg.config,'compact_forming_components'): agg.config.compact_forming_components=args.mode=='enabled'
            class Ingestion:
                async def start(self,*,on_market_event,**_): self.send=on_market_event; return self
                async def stop(self): pass
            ingestion=Ingestion();dm.set_ingestion_factory(ingestion)
            seen=[]
            async def observe(event):
                bar=event.bar
                seen.append((event.event_type.value,event.key.exchange,event.key.market_type,event.key.symbol,
                    event.key.interval,event.key.identity.storage_values,bar.time,bar.is_closed,bar.source,
                    *[getattr(bar,name) for name in fields]))
            values=[dict(open_time=i*width,close_time=(i+1)*width-1,open=10.,high=20.,low=5.,close=11.,
                volume=float(i+1),quote_volume=2.*(i+1),trades=i+1,taker_buy_base=1.,taker_buy_quote=2.) for i in range(count)]
            try:
                await dm.start()
                await dm.subscribe_async(observe,symbol='BTCUSDT',interval=f'{period}m',market_type='futures',
                    continuity='gap_aware',preserve_updates=True,event_types={DataEventType.BAR_UPDATED})
                await dm.ensure_stream('BTCUSDT',f'{period}m',market_type='futures')
                # Measure maintenance separately from scheduling. Real automatic
                # timer and concurrent forming input have their own tests.
                timeout=agg._timeout_task;timeout.cancel();await timeout;agg._timeout_task=None
                klines_repo.upsert_klines('BTCUSDT',f'{base}m',values[:-1],source='backfill',market_type='futures')
                for value in values[:-1]:
                    incoming=BarInput(symbol='BTCUSDT',source_interval=f'{base}m',open_time_ms=value['open_time'],
                        close_time_ms=value['close_time'],market_type='futures',is_closed=True,source=BarInputSource.REALTIME,
                        merge_mode=MergeMode.COMPONENT,enhanced_fields=frozenset(fields[5:]),
                        **{name:value[name] for name in fields})
                    await agg.ingest_bar_input('binance','futures','BTCUSDT',f'{period}m',incoming,emit_events=False)
                clock[0]=count*width+1000
                last=MarketEvent(event_type=StreamType.KLINE,symbol='BTCUSDT',exchange='binance',market_type='futures',
                    event_time_ms=clock[0],received_at_ms=clock[0],sequence=clock[0],source=DataSource.WEBSOCKET,
                    data=dict(interval=f'{base}m',is_closed=True,**values[-1]))
                gc.collect()
                if attempt==4: tracemalloc.start()
                cpu,wall=time.process_time_ns(),time.perf_counter_ns()
                await ingestion.send(last)
                producer_cpu_ms=(time.process_time_ns()-cpu)/1e6
                producer_wall_ms=(time.perf_counter_ns()-wall)/1e6
                await dm.aggregator_bridge.delivery.flush()
                async with asyncio.timeout(5):
                    while not seen: await asyncio.sleep(.001)
                cpu,wall=time.process_time_ns(),time.perf_counter_ns()
                drain=getattr(dm.history_prefix_runtime,'drain_components',None) or dm.history_prefix_runtime.drain_closed
                await drain()
                maintenance_cpu_ms=(time.process_time_ns()-cpu)/1e6
                maintenance_wall_ms=(time.perf_counter_ns()-wall)/1e6
                allocation=tracemalloc.get_traced_memory() if attempt==4 else None
                if attempt==4: tracemalloc.stop()
                state=agg.get_pipeline(f'{period}m').bar_state.get_active('binance','futures','BTCUSDT',0)
                assert state.volume==count*(count+1)/2 and state.status.value=='forming'
                assert len(state.source_snapshots)==(0 if args.mode=='enabled' else count)
                canonical=[]
                for interval in (f'{base}m',f'{period}m'):
                    canonical.extend((interval,row['open_time'],row['close_time'],row['source'],
                        *[row[name] for name in fields]) for row in
                        dm.query_engine.storage.query_bars('BTCUSDT',interval,limit=count+1,market_type='futures'))
                assert len(canonical)==count
                heap=dm.memory_budget.snapshot(measure_heap=True)
                result=dict(attempt=attempt,producer_cpu_ms=producer_cpu_ms,producer_wall_ms=producer_wall_ms,
                    maintenance_cpu_ms=maintenance_cpu_ms,maintenance_wall_ms=maintenance_wall_ms,
                    allocation_current_peak=allocation,events=len(seen),event_sha256=digest(seen),canonical_sha256=digest(canonical),
                    canonical_rows=len(canonical),retained_components=len(state.source_snapshots),
                    state_retained_bytes=retained_size((state,))[0],memory=heap,blocks=dm.shared_blocks.snapshot(),
                    runtime=dm.history_prefix_runtime.snapshot(),watermarks=[getattr(state,name) for name in
                        ('preview_input_version','preview_computed_version','preview_published_version')])
            finally: await dm.shutdown()
            assert dm.memory_budget.snapshot()['reserved_bytes']==0
            return result
    results=[]
    for period,base in ((2048,1),(10007,1)):
        trials=[]
        for attempt in range(5):
            value=asyncio.run(trial(period,base,attempt));trials.append(value)
            print(json.dumps(dict(period=period,attempt=attempt,producer_cpu_ms=value['producer_cpu_ms'],
                maintenance_cpu_ms=value['maintenance_cpu_ms'],retained_components=value['retained_components'])),flush=True)
        results.append(dict(period=period,base=base,trials=trials,
            producer_cpu_median_ms=statistics.median(row['producer_cpu_ms'] for row in trials[1:4]),
            maintenance_cpu_median_ms=statistics.median(row['maintenance_cpu_ms'] for row in trials[1:4])))
    assert source_hashes=={str(p.relative_to(args.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    args.output.write_text(json.dumps(dict(mode=args.mode,source=str(args.source),scope=__doc__,
        source_hashes=source_hashes,results=results),indent=2)+'\n')


if __name__=='__main__': main()
