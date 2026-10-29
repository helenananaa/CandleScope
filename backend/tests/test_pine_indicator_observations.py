"""Installed indicator sidecar over the production SDK JSON-RPC entry point."""
from dataclasses import replace
import json
import os
import subprocess
from types import SimpleNamespace

import pytest
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, ExecuteBatchResult, MarketContext
from candlescope_plugin_sdk.constants import KNOWN_FEATURES_V1, PROTOCOL_V1
from app.indicator.pine_host_inputs import requested_data


@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"),reason="requires installed Pine sidecar")
def test_installed_indicator_retains_observed_prefixes_across_rpc_and_transcript_restart():
    source='//@version=6\nindicator("Observed RPC")\nvarip int n=0\nn+=1\nplot(n)\nplot(array.size(request.security_lower_tf("OKX:ETH-USDT","1",close)))'
    chart=tuple(Bar(time=300+i*300,open=10,high=10,low=10,close=10,volume=1) for i in range(4))
    request=ExecuteBatchRequest(source=source,context=MarketContext("binance","spot","BTCUSDT","5m"),
        bars=chart[:2]+(replace(chart[2],is_closed=False),),options={"pineSessionId":"observed"})
    remote=[replace(chart[0],time=300+i*60,open=i,high=i,low=i,close=i) for i in range(20)]
    requirements={"requests":[{"function":"request.security_lower_tf",
        "symbol":{"kind":"literal","value":"OKX:ETH-USDT"},"timeframe":{"kind":"literal","value":"1"}}]}
    states=[(request,1019999),(request,1079999),(request,1079999),
        (replace(request,bars=chart[:3]),1199999),
        (replace(request,bars=chart[:3]+(replace(chart[3],is_closed=False),)),1259999)]
    payloads=[]
    for value,clock in states:
        value=replace(value,options={**value.options,"pineExecutionTimeMs":clock,"pineRevealedBoundaryMs":clock})
        data=requested_data(value,requirements,SimpleNamespace(query=lambda *a,**k:SimpleNamespace(bars=remote,missing_ranges=[])))
        payloads.append(replace(value,options={**value.options,**data}).to_wire())

    def run(count):
        messages=[{"jsonrpc":"2.0","id":0,"method":"handshake","params":{
            "protocols":[PROTOCOL_V1],"host":{"name":"Controlled Host","version":"1"},"hostFeatures":list(KNOWN_FEATURES_V1)}}]
        messages += [{"jsonrpc":"2.0","id":i+1,"method":"executeBatch","params":value} for i,value in enumerate(payloads[:count])]
        messages += [{"jsonrpc":"2.0","id":count+1,"method":"shutdown","params":{}}]
        process=subprocess.run([os.environ["NATIVE_TEST_PINE_PYTHON"],"-I","-m","candlescope_plugin_pine_compat"],
            input="\n".join(json.dumps(value) for value in messages)+"\n",capture_output=True,text=True,encoding="utf-8",
            timeout=30,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),check=True)
        responses=[json.loads(line) for line in process.stdout.splitlines()]
        assert len(responses)==len(messages),process.stderr
        assert all("error" not in response for response in responses),responses
        return [response["result"] for response in responses[1:-1]]

    short=run(2)
    results=run(5)
    restarted=run(5)
    assert [result["output"] for result in short]==[result["output"] for result in results[:2]]
    expected=[[3,2],[4,3],[5,3],[6,5],[7,1]]
    for actual,restored,wanted,(_,clock) in zip(results,restarted,expected,states,strict=True):
        assert actual["ok"],actual.get("diagnostics")
        decoded=ExecuteBatchResult.from_wire(actual)
        assert [series.points[-1].value for series in decoded.output.series]==wanted
        assert actual["meta"]["requestedObservationContract"]=="candlescope.pine-indicator-observations/1"
        assert actual["meta"]["requestedObservedAtMs"]==clock
        assert actual["output"]==restored["output"]
    assert [result["meta"]["sessionReset"] for result in results]==[True,False,False,False,False]
