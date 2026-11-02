import asyncio,json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path.cwd()/'packages/candlescope-plugin-python-indicator/src'))
from candlescope_plugin_python_indicator.runtime import PythonIndicatorRuntime
from candlescope_plugin_sdk import Bar,ExecuteBatchRequest,MarketContext
from app.api.v1.indicator_range_batch import IndicatorRangeBatchJob,compute_indicator_range_batch_async
from app.data_engine.data_manager.models import BarData
from app.indicator.range_result_service import IndicatorRangeResultService
from app.indicator.series_revision import SeriesRevisionRegistry
SOURCE="INDICATOR={'window':3}\ndef compute(bars,params):\n return {'lines':{'main':list(bars['close'])}}"
bars=[BarData(time=1700000040+i*60,open=100+i,high=101+i,low=99+i,close=100+i,volume=1,is_closed=True) for i in range(1000)]
class DM:
 def query(self,*args,**kw):return SimpleNamespace(bars=[b for b in bars if kw['start_ms']<=b.time*1000<=kw['end_ms']],missing_ranges=[],metadata={})
class Runtime:
 def __init__(self):self.inputs=[]
 async def execute(self,request,**adapters):
  self.inputs.append(dict(first=request.bars[0].time,last=request.bars[-1].time,count=len(request.bars)))
  result=PythonIndicatorRuntime().execute_batch(ExecuteBatchRequest(source=request.source,context=MarketContext(exchange='binance',market_type='spot',symbol='BTCUSDT',interval='1m'),bars=tuple(Bar(b.time,b.open,b.high,b.low,b.close,b.volume,is_closed=b.is_closed) for b in request.bars)))
  return adapters['adapt_sidecar'](result)
def job(at):return IndicatorRangeBatchJob(client_id=str(at),meta=dict(kind='script',language='python',script=SOURCE,scriptHash='window-probe',name='Window',params={},exchange='binance',market_type='spot',symbol='BTCUSDT',interval='1m',indicatorId='window'),start=bars[at].time,end=bars[at+2].time)
async def probe(indices):
 rt=Runtime();svc=IndicatorRangeResultService(enabled=False,revision_registry=SeriesRevisionRegistry(server_epoch='probe'))
 result=await compute_indicator_range_batch_async(dm=DM(),jobs=[job(i) for i in indices],range_service=svc,runtime_service=rt)
 return dict(jobs=indices,inputs=rt.inputs,results=[dict(points=x['lines'][0]['data'],range=x.get('range')) if isinstance(x,dict) else dict(error=str(x)) for x in result])
async def main():
 out=[await probe(x) for x in [[600],[600,900]]];print(json.dumps(out,indent=2));assert len(out[0]['results'][0]['points'])==3;assert out[1]['results'][0]['points']==out[0]['results'][0]['points'],out
asyncio.run(main())
