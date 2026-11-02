"""Count native full conversion on the actual pinned engine, no market access."""
import json
import os
import cProfile
import pstats
from pathlib import Path
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[3]
ENGINE=Path(os.environ.get('PINE_PROFILE_ENGINE_SITE','/Users/ryanliang/.codex/retained-worktree-resources/CandleScope/h127-r129-adoption-20261101-39b9de42/output/h127-r129-native-20261101/attempts/attempt9/profile/data/plugins/installs/candlescope.pine-compat/c99fa34216a8e7f90e2953891bf306872e94b3edfd4fe1103159e12619cae3b7/venv/lib/python3.12/site-packages'))
sys.path[:0]=[str(ROOT/'packages/candlescope-plugin-sdk/src'),str(ROOT/'packages/candlescope-plugin-pine-compat/src'),str(ENGINE)]
import pine_compat
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, MarketContext

factory=pine_compat.create_realtime_session
stats={'calls':0,'ns':0}
class Probe:
    def __init__(self,native):self.native=native
    def __getattr__(self,name):
        method=getattr(self.native,name)
        if name!='result':return method
        def result(*args,**kwargs):
            started=time.perf_counter_ns()
            value=method(*args,**kwargs)
            stats['calls']+=1;stats['ns']+=time.perf_counter_ns()-started
            return value
        return result
pine_compat.create_realtime_session=lambda *a,**kw:Probe(factory(*a,**kw))
source='//@version=6\nindicator("measure")\nplot(ta.ema(close,20))\nplot(close*2)'
rows=[]
trace=os.environ.get('PINE_PROFILE_TRACE','1')=='1'
detail=os.environ.get('PINE_PROFILE_DETAIL','0')=='1'
reuse=os.environ.get('PINE_PROFILE_REUSE','1')=='1'
ticks=int(os.environ.get('PINE_PROFILE_TICKS','20'))
for count in map(int,os.environ.get('PINE_PROFILE_ROWS','100,1000,10000').split(',')):
    plugin=PineCompatRuntimePlugin()
    if not reuse:
        execute=plugin._sessions.execute
        def compare_prefix(*args,**kwargs):
            kwargs['validated_prefix']=None
            return execute(*args,**kwargs)
        plugin._sessions.execute=compare_prefix
    bars=tuple(Bar(time=1700000000+i*60,open=100,high=102,low=99,close=101,volume=10,is_closed=True) for i in range(count))
    forming=Bar(time=1700000000+count*60,open=101,high=103,low=100,close=102,volume=11,is_closed=False)
    def request(bar,base):
        return ExecuteBatchRequest(source=source,bars=bars+(bar,),context=MarketContext('binance','spot','BTCUSDT','1m'),options={'pineSessionId':'measure'},output_stream='measure',output_base=base)
    first=plugin.execute_batch(request(forming,None));assert first.ok,first.diagnostics
    base=first.output_revision
    stats.update(calls=0,ns=0)
    elapsed=[];patches=0
    if trace:tracemalloc.start()
    profile=cProfile.Profile()
    if detail:profile.enable()
    for tick in range(ticks):
        bar=Bar(time=forming.time,open=101,high=103,low=100,close=102+(tick%50)/100,volume=11+tick,is_closed=False)
        began=time.perf_counter_ns();result=plugin.execute_batch(request(bar,base));elapsed.append((time.perf_counter_ns()-began)/1e6)
        assert result.ok,result.diagnostics
        patches+=result.output_patch is not None
        base=result.output_revision
    if detail:profile.disable()
    if trace:
        _current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    else:peak=None
    rows.append({'history_rows':count,'ticks':ticks,'patches':patches,'full_native_results':stats['calls'],'native_result_ms':stats['ns']/1e6,'total_ms':sum(elapsed),'tick_p50_ms':sorted(elapsed)[(ticks-1)//2],'python_peak_bytes':peak})
    if detail:
        rows[-1]['profile_top']=[{'file':Path(k[0]).name,'line':k[1],'function':k[2],'calls':v[1],'total_ms':v[2]*1000,'cumulative_ms':v[3]*1000} for k,v in sorted(pstats.Stats(profile).stats.items(),key=lambda item:item[1][3],reverse=True)[:15]]
    plugin.shutdown()
print(json.dumps({'scope':'Actual pinned native engine; direct source bridge; profiling flags are explicit below; no IPC or external market. Native conversion timing is included in total.','tracemalloc':trace,'cprofile':detail,'validated_prefix':reuse,'measurements':rows},indent=2))
