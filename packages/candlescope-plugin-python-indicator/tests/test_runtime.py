from pathlib import Path
import sys
import json
import os
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'candlescope-plugin-sdk/src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from candlescope_plugin_sdk import AnalyzeRequest, Bar, ExecuteBatchRequest, MarketContext
from candlescope_plugin_python_indicator.runtime import PythonIndicatorRuntime, STARTER

CONTEXT=MarketContext(exchange='binance',market_type='spot',symbol='BTCUSDT',interval='1m')


def test_public_sdk_batch_sma_matches_independent_arithmetic():
    runtime=PythonIndicatorRuntime()
    analysis=runtime.analyze(AnalyzeRequest(source=STARTER,context=CONTEXT))
    assert analysis.ok and analysis.inputs[0]['key']=='length'
    bars=tuple(Bar(i, i, i+1, i-1, i, 10) for i in range(1,31))
    result=runtime.execute_batch(ExecuteBatchRequest(source=STARTER,context=CONTEXT,bars=bars,params={'length':5}))
    assert result.ok
    values=[p.value for p in result.output.series[0].points]
    assert values[:4]==[None]*4
    assert values[4:]==[sum(range(i-4,i+1))/5 for i in range(5,31)]


def test_forming_tail_is_not_executed_and_window_remains_explicit():
    source="INDICATOR={'window':2}\ndef compute(bars, params):\n return {'lines':{'main':list(bars['close'])}}"
    bars=tuple(Bar(i,1,2,1,2,10,is_closed=i<4) for i in range(1,5))
    result=PythonIndicatorRuntime().execute_batch(ExecuteBatchRequest(source=source,context=CONTEXT,bars=bars))
    assert result.ok
    assert [p.value for p in result.output.series[0].points]==[None,2,2,None]
    assert result.meta['inputWindow']==dict(requestedBars=4,confirmedBars=3,computedBars=2,offset=1,formingBarsExcluded=1)


def test_unconfirmed_interior_and_unknown_parameters_are_diagnostics():
    runtime=PythonIndicatorRuntime()
    for bars,params in [((Bar(1,1,2,1,2,1,is_closed=False),Bar(2,1,2,1,2,1)),{}),
                        ((Bar(1,1,2,1,2,1),),{'typo':1})]:
        result=runtime.execute_batch(ExecuteBatchRequest(source=STARTER,context=CONTEXT,bars=bars,params=params))
        assert not result.ok and result.diagnostics[0].severity=='error'


def test_descriptor_exposes_own_language_editor_and_actual_execution_capabilities():
    d=PythonIndicatorRuntime().describe()
    assert d.languages[0].id=='python'
    assert d.meta['closedBarsOnly'] and not d.meta['incremental']
    assert d.meta['ui']['languages']['python']['monacoLanguage']=='python'
    assert d.meta['causality']=='unverified'


def test_real_sidecar_json_lines_handshake_analysis_and_execution():
    source="print('author output')\ndef compute(bars, params):\n return {'lines':{'main':list(bars['close'])}}"
    requests=[dict(jsonrpc='2.0',id=1,method='handshake',params={
        'protocols':['candlescope.script-runtime/1'], 'host':{'name':'CandleScope','version':'test'},
        'hostFeatures':['source-analysis/1','batch-execution/1','render.line-series/1','render.histogram-series/1']}),
        dict(jsonrpc='2.0',id=2,method='analyze',params={'source':source,'context':CONTEXT.to_wire()}),
        dict(jsonrpc='2.0',id=3,method='executeBatch',params={'source':source,'context':CONTEXT.to_wire(),
             'bars':[Bar(1,1,2,1,2,10).to_wire()],'params':{}})]
    roots=[Path(__file__).resolve().parents[1]/'src',Path(__file__).resolve().parents[2]/'candlescope-plugin-sdk/src']
    run=subprocess.run([sys.executable,'-m','candlescope_plugin_python_indicator'],
                       input=''.join(json.dumps(r)+'\n' for r in requests),text=True,capture_output=True,
                       env={**os.environ,'PYTHONPATH':os.pathsep.join(map(str,roots))},timeout=20,check=True)
    responses=[json.loads(line) for line in run.stdout.splitlines()]
    assert len(responses)==3 and all('result' in r for r in responses),responses
    assert responses[1]['result']['executable']
    assert responses[2]['result']['output']['series'][0]['data']==[{'time':1,'value':2.0}]
