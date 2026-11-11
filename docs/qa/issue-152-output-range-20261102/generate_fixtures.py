"""Frozen production-adapter messages from the freshly installed real sidecar."""
from pathlib import Path
import asyncio
from dataclasses import replace
import hashlib
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'packages/candlescope-plugin-sdk/src')]
from app.plugin_runtime.registry import load_runtime_registry
from app.plugin_runtime.supervisor import RuntimeSupervisor
from app.indicator.runtime_service import IndicatorRuntimeRequest
from app.api.v1.stream_indicator_payloads import _plugin_snapshot_or_patch_from_result
from candlescope_plugin_sdk import Bar

PRODUCT=Path(os.environ.get('PINE_BUNDLE_ROOT',str(ROOT/'output/issue-152-output-range-20261102')))
OUT=Path(os.environ.get('PINE_FIXTURE_OUT',str(PRODUCT/'fixture-generation-attempt1')));OUT.mkdir(exist_ok=False)
QUALIFICATION=Path(os.environ.get('PINE_QUALIFICATION_OUT',str(PRODUCT/'qualification-attempt2')))
spec=load_runtime_registry(QUALIFICATION/'controlled-install/runtime-registry.json').plugins[0]
runner=OUT/'runner.py';runner.write_text('import sys\nfrom candlescope_plugin_sdk import serve_runtime\nfrom candlescope_plugin_pine_compat import PineCompatRuntimePlugin\nraise SystemExit(serve_runtime(PineCompatRuntimePlugin(journal_path=sys.argv[1])))\n')
def bar(time,close,closed=True):return Bar(time=time,open=100,high=max(105,close+1),low=99,close=close,volume=1,is_closed=closed)

async def main():
 supervisor=RuntimeSupervisor(replace(spec,arguments=('-I',str(runner),str(OUT/'journal.sqlite')),startup_timeout_seconds=60,request_timeout_seconds=60),host_name='CandleScope',host_version='0.3.0')
 cases=[]
 try:
  for name,source,history_close in (
   ('negative-line','plot(close,offset=-1)',101),
   ('negative-na','plot(close > 102 ? close : na,offset=-1)',101),
   ('negative-markers','plotshape(close > 102,offset=-1,style=shape.circle)',103),
   ('negative-bgcolor','bgcolor(close > 102 ? color.red : na,offset=-1)',103),
   ('remove-last-marker','plotshape(close > 102,offset=-1,style=shape.circle)',101),
   ('history-correction','plot(close,offset=-1)',101),
   ('show-last','plot(close,offset=-1,show_last=3)',101),
  ):
   history=tuple(bar(1700000000+i*120,history_close) for i in range(20))
   forming_time=history[-1].time+600
   source='//@version=6\nindicator("'+name+'")\n'+source
   meta={'language':'pine','exchange':'binance','market_type':'spot','symbol':'BTCUSDT','interval':'1m','name':name,'indicatorId':name,'params':{}}
   def request(bars):return IndicatorRuntimeRequest(language='pine',source=source,exchange='binance',market_type='spot',symbol='BTCUSDT',interval='1m',bars=bars,options={'pineSessionId':name},transport='websocket.snapshot').to_sdk_request()
   before=history+(bar(forming_time,103,False),)
   seed=await supervisor.execute_batch(request(before));assert seed.ok,seed.diagnostics
   snapshot=_plugin_snapshot_or_patch_from_result(name,meta,list(before),seed,bar_time=forming_time)
   after=history+(bar(forming_time,102,False),)
   if name=='negative-line':after=history+(bar(forming_time,104,False),)
   if name=='history-correction':after=history[:5]+(bar(history[5].time,130),)+history[6:]+(bar(forming_time,103,False),)
   if name=='show-last':after=history+(bar(forming_time,103),bar(forming_time+60,104,False))
   result=await supervisor.execute_batch(request(after));assert result.ok,result.diagnostics
   update=_plugin_snapshot_or_patch_from_result(name,meta,list(after),result,bar_time=after[-1].time)
   expected=_plugin_snapshot_or_patch_from_result(name,meta,list(after),result,bar_time=0)
   if name.startswith('negative-'):
    assert update['type']=='indicator.replace_range',update
    assert update['range']=={'start':history[-1].time,'end':history[-1].time}
   else:assert update['type']=='indicator.snapshot',update
   changed_display=history[4].time if name=='history-correction' else history[17].time if name=='show-last' else history[-1].time
   cases.append({'id':name,'source':source,'sourceBarTime':after[-1].time,'changedDisplayTime':changed_display,'snapshot':snapshot,'update':update,'expected':expected})
 finally:
  await supervisor.stop()
 status=supervisor.snapshot();assert status['state']=='stopped'
 lock=json.loads((PRODUCT/'plugins/candlescope-plugin-pine-compat.lock.json').read_text())
 fixture={'schema':'candlescope.render-update-range-fixtures/1','sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'bridgeSourceSha256':lock['bridgeSourceSha256'],'scope':'Real freshly installed SDK/bridge+unchanged engine, RuntimeSupervisor and production payload adapter. No public source, HTTP/WS server or native browser acceptance.','cases':cases,'process':status}
 (OUT/'fixtures.json').write_text(json.dumps(fixture,indent=2)+'\n')
 (ROOT/'backend/tests/fixtures/plugin_runtime/script-output-ranges.json').write_text(json.dumps(fixture,indent=2)+'\n')
 print(json.dumps({'passed':True,'cases':[case['id'] for case in cases],'state':status['state']}))
asyncio.run(main())
