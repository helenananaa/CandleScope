import argparse, gc, hashlib, json, platform, statistics, sys, time, tracemalloc
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root');args=p.parse_args();sys.path.insert(0,str(Path(args.root)/'backend'))
from app.data_engine.data_manager.models import BarData
from app.data_engine.data_manager.custom_query import _aggregate_fixed_bars_to_interval
from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
from app.data_engine.bar_aggregator.models import BarState, BarInput, BarInputSource
bars=[BarData(time=i*60,open=100.0+i%19,high=123.0,low=99.0,close=101.0+i%17,volume=round((i%99+1)*.0123456789,8),quote_volume=1000.12345678,trades=10,taker_buy_base=0,taker_buy_quote=0) for i in range(18000)]
inputs=[BarInput(symbol='BTC-USDT',exchange='okx',market_type='spot',source_interval='1m',open_time_ms=i*60000,close_time_ms=(i+1)*60000-1,open=100.0,high=105.0,low=99.0,close=101.0,volume=1.12345678,quote_volume=110,trades=5,taker_buy_base=.5,taker_buy_quote=50,enhanced_fields=frozenset(['quote_volume','trades','taker_buy_base','taker_buy_quote']),source=BarInputSource.BACKFILL,is_closed=True,sequence=1) for i in range(389)]
def history():
    return [b.to_aggregation_dict() for b in _aggregate_fixed_bars_to_interval(bars,89*60,source_interval_seconds=60)]
def live():
    s=BarState(symbol='BTC-USDT',exchange='okx',market_type='spot',interval='389m',bucket_start_ms=0,bucket_end_ms=389*60000,open=0,high=0,low=0,close=0,volume=0)
    merge=ComponentSnapshotOHLCVMerge()
    for i,item in enumerate(inputs):merge.apply(s,item,i==0)
    return {name:getattr(s,name) for name in ['open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote']}
result={'root':args.root,'python':platform.python_version(),'machine':platform.machine(),'cases':{}}
for name,fn in [('fixed_18000_rows_89m',history),('live_389_component_updates',live)]:
    fn();samples=[]
    for i in range(5):
        gc.collect();start=time.perf_counter();value=fn();samples.append((time.perf_counter()-start)*1000)
    gc.collect();tracemalloc.start();fn();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    result['cases'][name]={'milliseconds':samples,'median_ms':statistics.median(samples),'traced_peak_bytes':peak,'output_sha256':hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()}
print(json.dumps(result,indent=2))
