"""Same controlled tape against complete old/new backends, not network/RSS qualification."""
import argparse
import asyncio
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from types import SimpleNamespace


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--mode',choices=['base','eager','deferred'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.source/'backend'))
    from app.data_engine.bar_aggregator import BarAggregator,BarAggregatorConfig
    from app.data_engine.bar_aggregator import aggregator,bar_state,finalizer,publisher
    from app.data_engine.bar_aggregator.models import BarInput,BarInputSource,MergeMode
    from app.data_engine.ingestion.models import MarketEvent,DataSource,StreamType
    from app.data_engine.memory_budget import MemoryBudget,retained_size
    try:
        from app.data_engine.bar_aggregator import preview_scheduler
    except ImportError:
        preview_scheduler=None
    clock=[0.]
    wall=SimpleNamespace(time=lambda:clock[0])
    for module in [aggregator,bar_state,finalizer,publisher,preview_scheduler]:
        if module is not None: module.time=wall
    fields=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
    async def trial(period,source,seed_count,attempt):
        target_ms=period*60000
        width=source*60000
        cfg=BarAggregatorConfig(update_throttle_ms=250)
        if hasattr(cfg,'deferred_component_previews'):
            cfg.deferred_component_previews=args.mode=='deferred'
        agg=BarAggregator(cfg)
        agg.add_target('BTCUSDT',f'{period}m',market_type='futures')
        budget=MemoryBudget()
        budget.register('realtime-state',limit_bytes=128*1024*1024,usage=agg.memory_usage,roots=agg._memory_roots)
        agg.memory_budget=budget
        seen=[]
        async def observe(event):
            bar=event.bar
            seen.append((event.event_type.value,bar.exchange,bar.market_type,bar.symbol,bar.interval,
                         bar.identity.storage_values,bar.bucket_start_ms,bar.bucket_end_ms,bar.status.value,
                         bar.finality.value,bar.close_reason,sorted(bar.enhanced_fields),bar.tick_count,
                         bar.first_input_at_ms,bar.last_input_at_ms,bar.last_close_received,
                         *[getattr(bar,name) for name in fields]))
        agg.publisher.on_bar_event(observe)
        def data(index,volume,closed):
            return dict(interval=f'{source}m',open_time=index*width,close_time=(index+1)*width-1,
                open=10.,high=20.,low=5.,close=11.,volume=volume,quote_volume=2*volume,
                trades=int(volume*1000),taker_buy_base=volume,taker_buy_quote=2*volume,is_closed=closed)
        # Inputs and the near-tail builder are constructed before measurement.
        tape=tuple(MarketEvent(event_type=StreamType.KLINE,symbol='BTCUSDT',exchange='binance',
            market_type='futures',event_time_ms=seed_count*width+i,received_at_ms=seed_count*width+i,
            sequence=i,source=DataSource.WEBSOCKET,data=data(seed_count,5+i/1000,False))
            for i in range(1,1025))
        closing=MarketEvent(event_type=StreamType.KLINE,symbol='BTCUSDT',exchange='binance',
            market_type='futures',event_time_ms=seed_count*width+1025,received_at_ms=seed_count*width+1025,
            sequence=1025,source=DataSource.WEBSOCKET,data=data(seed_count,6.025,True))
        await agg.start()
        clock[0]=seed_count*width/1000+1
        def closed(index,volume=1.):
            return BarInput(symbol='BTCUSDT',source_interval=f'{source}m',open_time_ms=index*width,
                close_time_ms=(index+1)*width-1,open=10,high=20,low=5,close=11,volume=volume,
                quote_volume=2*volume,trades=int(volume*1000),taker_buy_base=volume,taker_buy_quote=2*volume,
                source=BarInputSource.BACKFILL,is_closed=True,merge_mode=MergeMode.COMPONENT,market_type='futures')
        for i in range(seed_count):
            await agg.ingest_bar_input('binance','futures','BTCUSDT',f'{period}m',closed(i),emit_events=False)
        engine=agg.get_pipeline(f'{period}m').bar_state
        gc.collect()
        if attempt==7: tracemalloc.start()
        cpu,wall_ns=time.process_time_ns(),time.perf_counter_ns()
        for i,event in enumerate(tape):
            clock[0]=seed_count*width/1000+1+i/1000
            await agg.on_market_event(event)
            if i%32==0: await asyncio.sleep(0)
        await agg.on_market_event(closing)
        for i in range(seed_count+1,period//source):
            await agg.ingest_bar_input('binance','futures','BTCUSDT',f'{period}m',closed(i))
        cpu_ms=(time.process_time_ns()-cpu)/1e6
        wall_ms=(time.perf_counter_ns()-wall_ns)/1e6
        allocations=tracemalloc.get_traced_memory() if attempt==7 else None
        if attempt==7: tracemalloc.stop()
        state=engine.get_state('binance','futures','BTCUSDT',0)
        assert state.status.value=='closed' and state.finality.value=='authoritative'
        index=state._component_accumulator.snapshot()
        signature=hashlib.sha256(json.dumps(seen,separators=(',',':')).encode()).hexdigest()
        projection=hashlib.sha256(json.dumps(state.to_storage_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        usage=agg.memory_usage()
        result=dict(attempt=attempt,cpu_ms=cpu_ms,wall_ms=wall_ms,allocation_current_peak=allocations,
            events=len(seen),event_sha256=signature,projection_sha256=projection,
            input_components=period//source,forming_inputs=len(tape),retained_state_bytes=retained_size((state,))[0],
            estimated_runtime_bytes=usage['estimated_bytes'],reserved_bytes=budget.snapshot()['reserved_bytes'],
            index=index,calculations=getattr(state,'_preview_calculations',None),
            deferred_inputs=getattr(state,'_preview_deferred_inputs',0),
            watermarks=[getattr(state,name,None) for name in
                ['preview_input_version','preview_computed_version','preview_published_version']])
        await agg.stop()
        assert budget.snapshot()['reserved_bytes']==0
        return result
    results=[]
    for period,source,seed in [(45,15,2),(90,30,2),(10007,1,10000)]:
        trials=[]
        for attempt in range(8):
            value=asyncio.run(trial(period,source,seed,attempt))
            print(json.dumps(dict(period=period,source=source,**value)),flush=True)
            if attempt>=2: trials.append(value)
        results.append(dict(period=period,source=source,seed_components=seed,timed=trials[:5],allocation=trials[-1],
            cpu_median_ms=statistics.median(v['cpu_ms'] for v in trials[:5]),
            wall_median_ms=statistics.median(v['wall_ms'] for v in trials[:5])))
    files=list((args.source/'backend/app/data_engine/bar_aggregator').glob('*.py'))
    args.output.write_text(json.dumps(dict(mode=args.mode,source=str(args.source),results=results,
        source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}),indent=2)+'\n')


if __name__=='__main__': main()
