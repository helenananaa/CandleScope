"""Installed sidecar RPC: ordinal output keys, real clocks and fresh previews."""
import json
import os
import subprocess
import pytest
from candlescope_plugin_sdk import ExecuteBatchResult
from candlescope_plugin_sdk.constants import KNOWN_FEATURES_V1, PROTOCOL_V1
from app.indicator.runtime_service import IndicatorRuntimeRequest


@pytest.mark.skipif(not os.environ.get('NATIVE_TEST_PINE_PYTHON'), reason='requires installed ordered-chart-input/1 sidecar')
def test_installed_chart_indicator_rpc_retains_each_brick_and_rewinds_without_session_state():
    source='''//@version=6
indicator("ordered RPC")
plot(ta.sma(close, 2))
plot(time)
plot(bar_index)
plot(barstate.isconfirmed ? 1 : 0)
'''
    def request(values):
        return IndicatorRuntimeRequest(language='pine', source=source,exchange='binance',market_type='spot',symbol='BTCUSDT',interval='1m',
            bars=tuple(dict(time=i+1,open=value-2,high=value,low=value-2,close=value,volume=2,is_closed=i==0) for i,value in enumerate(values)),
            options={'chartInput':{'contract':'candlescope.chart-indicator-input/1','transform':'renko',
                'sourceTimes':[1700000040]*len(values),'closed':[True]+[False]*(len(values)-1)},
                'pineExecutionTimeMs':1700000099000,'pineRevealedBoundaryMs':1700000099000}).to_sdk_request().to_wire()
    payloads=[request([102,104,106]),request([102,108]),request([102,104,106])]
    messages=[{'jsonrpc':'2.0','id':0,'method':'handshake','params':{'protocols':[PROTOCOL_V1],
        'host':{'name':'Chart input qualification','version':'1'},'hostFeatures':list(KNOWN_FEATURES_V1)}}]
    messages += [{'jsonrpc':'2.0','id':i+1,'method':'executeBatch','params':value} for i,value in enumerate(payloads)]
    messages += [{'jsonrpc':'2.0','id':4,'method':'shutdown','params':{}}]
    result=subprocess.run([os.environ['NATIVE_TEST_PINE_PYTHON'],'-I','-m','candlescope_plugin_pine_compat'],
        input='\n'.join(json.dumps(value) for value in messages)+'\n',capture_output=True,text=True,timeout=60,check=True)
    responses=[json.loads(line) for line in result.stdout.splitlines()]
    assert len(responses)==len(messages),result.stderr
    assert all('error' not in value for value in responses),responses
    outputs=[]
    for response in responses[1:-1]:
        decoded=ExecuteBatchResult.from_wire(response['result'])
        assert decoded.ok,decoded.diagnostics
        outputs.append(decoded.output)
    assert [[point.value for point in line.points] for line in outputs[0].series] == [
        [103,105],[1700000040000]*3,[0,1,2],[1,0,0]]
    assert [point.time for point in outputs[0].series[0].points] == [2,3]
    assert [point.value for point in outputs[1].series[0].points] == [105]
    assert outputs[0] == outputs[2]
