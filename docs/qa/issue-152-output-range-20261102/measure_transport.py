"""Observe actual installed sidecar pipe bytes; never replace a response."""
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'packages/candlescope-plugin-sdk/src')]
from app.plugin_runtime.installer import PluginInstaller
from app.plugin_runtime.registry import load_runtime_registry
from app.plugin_runtime.supervisor import RuntimeSupervisor
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, MarketContext, KNOWN_FEATURES_V1, FEATURE_BATCH_BARS_PATCH_V1, FEATURE_RENDER_OUTPUT_PATCH_V1

OUT=Path(os.environ['PINE_TRANSPORT_OUT']);OUT.mkdir(parents=True,exist_ok=False)
BUNDLE=Path(os.environ['PINE_TRANSPORT_BUNDLE'])
PYTHON=Path('/Users/ryanliang/.codex/retained-worktree-resources/CandleScope/h127-r129-adoption-20261101-39b9de42/output/h127-r129-native-20261101/Installed App/CandleScope.app/Contents/Resources/python-runtime/python/bin/python3.12')
installer=PluginInstaller(root=OUT/'installed',python_executable=PYTHON)
installed=installer.install(BUNDLE,expected_sha256='sha256:'+hashlib.sha256(BUNDLE.read_bytes()).hexdigest())
spec=load_runtime_registry(installer.registry_path).plugins[0]
runner=OUT/'runner.py';runner.write_text('import sys\nfrom candlescope_plugin_sdk import serve_runtime\nfrom candlescope_plugin_pine_compat import PineCompatRuntimePlugin\nraise SystemExit(serve_runtime(PineCompatRuntimePlugin(journal_path=sys.argv[1])))\n')
SOURCE='//@version=6\nindicator("transport")\nplot(ta.ema(close,20))\nplot(close*2)'
CONTEXT=MarketContext('binance','spot','BTCUSDT','1m')
rows=[];stopped=[]
def save():
 (OUT/'measurements.json').write_text(json.dumps({'scope':'Actual installed current SDK/bridge and unchanged verified native engine. Real RuntimeSupervisor stdin/stdout frames observed without replacement; full-vs-negotiated patches. No HTTP/UI/network, no new engine getter. Timings include host reconstruction and native materialization, exclude observer JSON inspection/equality.', 'sourceCommit':os.popen('git rev-parse HEAD').read().strip(),'bundleSha256':hashlib.sha256(BUNDLE.read_bytes()).hexdigest(),'install':installed.to_wire(),'rows':rows,'stopped':stopped},indent=2)+'\n')

class InputObserver:
 def __init__(self,stream,record):self.stream,self.record=stream,record
 def __getattr__(self,name):return getattr(self.stream,name)
 def write(self,raw):self.record['in']=raw;return self.stream.write(raw)
class OutputObserver:
 def __init__(self,stream,record):self.stream,self.record=stream,record
 def __getattr__(self,name):return getattr(self.stream,name)
 async def readline(self):
  raw=await self.stream.readline();self.record['out']=raw;return raw

async def supervisor(name,patches):
 process=RuntimeSupervisor(replace(spec,arguments=('-B','-I',str(runner),str(OUT/(name+'.sqlite'))),startup_timeout_seconds=60,request_timeout_seconds=60),host_name='CandleScope',host_version='0.3.0',host_features=tuple(feature for feature in KNOWN_FEATURES_V1 if patches or feature not in {FEATURE_BATCH_BARS_PATCH_V1,FEATURE_RENDER_OUTPUT_PATCH_V1}))
 await process.start();record={};child=process._process
 child.stdin=InputObserver(child.stdin,record);child.stdout=OutputObserver(child.stdout,record)
 return process,record

def frame(record,elapsed):
 incoming=json.loads(record['in']);outgoing=json.loads(record['out']);params=incoming['params'];result=outgoing['result']
 return {'ms':elapsed,'requestBytes':len(record['in']),'responseBytes':len(record['out']),'bars':len(params['bars']),'inputPatch':params.get('barsPatch'),'outputPatch':result.get('outputPatch') is not None,'fullOutput':result.get('output') is not None}

async def run():
 ticks=int(os.environ.get('PINE_TRANSPORT_TICKS','30'));trials=int(os.environ.get('PINE_TRANSPORT_TRIALS','3'))
 for count in map(int,os.environ.get('PINE_TRANSPORT_ROWS','1000,10000,50000').split(',')):
  history=tuple(Bar(time=1700000000+i*60,open=100,high=102,low=99,close=101,volume=10,is_closed=True) for i in range(count))
  for trial in range(trials):
   processes={};samples={'full':[],'patch':[]};seeds={}
   try:
    for name,patch in [('full',False),('patch',True)]:processes[name]=await supervisor(f'{count}-{trial}-{name}',patch)
    for tick in range(ticks+1):
     tail=Bar(time=1700000000+count*60,open=101,high=103,low=100,close=102+(tick%50)/100,volume=11+tick,is_closed=False)
     request=ExecuteBatchRequest(source=SOURCE,bars=history+(tail,),context=CONTEXT,options={'pineSessionId':'measure'},bars_stream='measure',output_stream='measure')
     outputs={}
     order=['patch','full'] if (trial+tick)%2 else ['full','patch']
     for name in order:
      process,record=processes[name];started=time.perf_counter_ns();value=await process.execute_batch(request);elapsed=(time.perf_counter_ns()-started)/1e6
      assert value.ok,value.diagnostics;outputs[name]=value
      observed=frame(record,elapsed)
      if tick:samples[name].append(observed)
      else:seeds[name]=observed
     assert outputs['full'].meta['outputUpdate']['mode']=='snapshot'
     assert outputs['patch'].meta['outputUpdate']['mode'] in {'snapshot','range'}
     semantic=lambda result: replace(result,meta={key:value for key,value in result.meta.items() if key!='outputUpdate'})
     assert semantic(outputs['patch'])==semantic(outputs['full']),'Complete caller-visible semantics differ'
    assert all(item['bars']==1 and item['outputPatch'] and not item['fullOutput'] for item in samples['patch'])
    rows.append({'history':count,'trial':trial,'ticks':ticks,'seed':seeds,'samples':samples,'summary':{name:{'roundTripP50Ms':statistics.median(item['ms'] for item in items),'requestBytesP50':statistics.median(item['requestBytes'] for item in items),'responseBytesP50':statistics.median(item['responseBytes'] for item in items)} for name,items in samples.items()},'callerResultsEqual':True})
    print(json.dumps({'history':count,'trial':trial,'summary':rows[-1]['summary']}),flush=True)
   finally:
    for name,(process,record) in processes.items():
     await process.stop();snapshot=process.snapshot();assert snapshot['state']=='stopped';stopped.append({'history':count,'trial':trial,'name':name,'snapshot':snapshot})
    save()
asyncio.run(run())
