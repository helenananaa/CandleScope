from copy import deepcopy
import json
import os
import sys
import threading

import pytest

from app.backtest.errors import BacktestError
from app.backtest.native import PROTOCOL, encoded, invoke
from app.backtest.native_session import SessionWorker, REQUEST_UPDATE_CONTRACT, SCHEDULE_CONTRACT
from app.backtest.strategy.pine_engine import plugin


def request(count, callbacks=False):
    bars=[dict(time=index*60,open=1,high=1,low=1,close=1,volume=1) for index in range(count)]
    accounts=[dict(time=bar["time"],position_size=0,position_avg_price=None,initial_capital=1000,
                   equity=1000,netprofit=0,openprofit=0) for bar in bars]
    observations=[dict(observed_at_ms=(index+1)*60_000-1,updates=[dict(symbol="B",timeframe="1",kind="confirmed",
        available_at_ms=(index+1)*60_000-1,bar={**bar,"open":(index+1)*100,"high":(index+1)*100,"low":(index+1)*100,"close":(index+1)*100})])
        for index,bar in enumerate(bars)]
    value=dict(source='//@version=6\nstrategy("observed"'+(',calc_on_order_fills=true' if callbacks else '')+')\nx=request.security("B","1",ta.cum(close))\nplot(x)\nplot(request.security("B","1",time))\nif x>250\n    strategy.entry("L",strategy.long,qty=1)',
        context=dict(symbol="A",timeframe="1",metadata=dict(priceTickSize=".1",currency="USD")),
        contexts=[dict(symbol="B",timeframe="1",bars=[])],bars=bars,accounts=accounts,
        request_update_contract=REQUEST_UPDATE_CONTRACT,request_updates=observations)
    if callbacks:
        del value["request_updates"]
        value["execution_schedule_contract"]=SCHEDULE_CONTRACT
        value["execution_schedule"]=[]
        for index,(bar,account,observation) in enumerate(zip(bars,accounts,observations,strict=True)):
            group=[]
            for close in [False,True]:
                group.append(dict(evaluation=dict(bar=deepcopy(bar),account=deepcopy(account),
                    event_time_ms=observation["observed_at_ms"] if close else bar["time"]*1000+1,
                    confirmed=close,request_observed_at_ms=observation["observed_at_ms"],
                    request_updates=[] if close else deepcopy(observation["updates"])),
                    context=dict(bar_state="historical",trigger="bar_close" if close else "order_fill",is_new=True)))
            value["execution_schedule"].append(group)
    return value


def test_append_transport_keeps_requested_prefixes_immutable():
    worker=object.__new__(SessionWorker)
    worker.identity=dict(prefix_append="candlescope.pine-prefix/1",request_update_contract=REQUEST_UPDATE_CONTRACT)
    worker._prefix_state=None
    first=request(1)
    worker._prefix_payload(first)
    second=request(2)
    assert worker._prefix_payload(second)["request_updates"]==second["request_updates"][1:]
    second["request_updates"][0]["updates"][0]["bar"]["close"]=999
    assert worker._prefix_payload({**second,"bars":[*second["bars"],second["bars"][-1]],
                                   "accounts":[*second["accounts"],second["accounts"][-1]],
                                   "request_updates":[*second["request_updates"],second["request_updates"][-1]]}).get("operation")!="append_prefix"


def test_worker_requires_requested_update_acknowledgement_and_reaps_failure(tmp_path):
    script=tmp_path/'missing_ack.py'
    script.write_text('import sys,json\nfor line in sys.stdin:\n value=json.loads(line)\n print(json.dumps(dict(ok=True,identity=value["identity"])),flush=True)\n')
    identity=dict(request_update_contract=REQUEST_UPDATE_CONTRACT)
    runtime=dict(command=[sys.executable,str(script)])
    cancelled=threading.Event()
    worker=SessionWorker(runtime,dict(identity=identity),cancelled,evaluator=True)
    with pytest.raises(BacktestError,match="requested-update acknowledgement missing"):
        worker.request({**request(1),"identity":identity},cancelled)
    assert worker.process.poll() is not None and worker._closed


@pytest.mark.skipif(not os.environ.get('NATIVE_TEST_PINE_PYTHON'),reason='requires installed Pine update bridge')
@pytest.mark.parametrize('route',['chart_strategy','external_strategy'])
@pytest.mark.parametrize('callbacks',[False,True])
def test_real_requested_update_ipc_append_and_restart_match_causal_replay(route,callbacks):
    runtime=plugin()
    runtime['command'][-1]=f'candlescope_plugin_pine_compat.{route}'
    identity=invoke(runtime,dict(operation='describe'))['identity']
    assert identity['request_update_contract']==REQUEST_UPDATE_CONTRACT
    base=dict(protocol=PROTOCOL,identity=identity)
    cancel=threading.Event()
    worker=SessionWorker(runtime,base,cancel,evaluator=True)
    try:
        first=worker.request({**base,**request(1,callbacks)},cancel)
        before=worker.input_bytes
        second={**base,**request(2,callbacks)}
        result=worker.request(second,cancel)
        assert result==invoke(runtime,second)
        assert [plot['values'] for plot in result['raw_output']['plots']]==[[100,300],[0,60000]]
        assert first['intents']==[] and result['intents']
        assert all(('pass_index' in intent)==callbacks for intent in result['intents'])
        assert worker.input_bytes-before < len((encoded(second)+'\n').encode('utf-8'))
        worker.close()
        worker=SessionWorker(runtime,base,cancel,evaluator=True)
        assert worker.request(second,cancel)==result
    finally:
        worker.close()
