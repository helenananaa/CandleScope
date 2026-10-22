"""Real worker deltas and restart before matching ledger restoration."""
from copy import deepcopy
import os
import threading

import pytest

from app.backtest.errors import BacktestError
from app.backtest.native import PROTOCOL, invoke
from app.backtest.native_session import SessionWorker, STREAM_CONTRACT
from app.backtest.pine_stream import PineStream
from app.backtest.strategy.pine_engine import plugin


def test_stream_cannot_cross_an_unnegotiated_transport():
    worker = object.__new__(SessionWorker)
    worker.identity = {}
    with pytest.raises(BacktestError, match="not negotiated"):
        worker.request(dict(operation="stream_open", external_stream_contract=STREAM_CONTRACT),threading.Event())


installed = pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"), reason="requires isolated source worker")
SOURCE='''//@version=6
strategy("restart",calc_on_every_tick=true,calc_on_every_history_tick=true)
varip int n=0
n+=1
plot(n)
plot(strategy.position_size)
plot(timenow)
strategy.entry(str.tostring(n),strategy.long,qty=1)
'''


def runtime_for(route):
    runtime = plugin()
    runtime["command"][-1] = f"candlescope_plugin_pine_compat.{route}"
    identity = invoke(runtime, dict(operation="describe"))["identity"]
    return runtime, dict(protocol=PROTOCOL,identity=identity)


def observation(index, ordinal, count=4):
    bar=dict(time=index*60,open=10,high=10,low=10,close=10,volume=100)
    account=dict(time=bar["time"],position_size=ordinal,position_avg_price=10 if ordinal else None,
                 initial_capital=10000,equity=10000,netprofit=0,openprofit=0)
    return dict(evaluation=dict(bar=bar,account=account,event_time_ms=bar["time"]*1000+ordinal,confirmed=ordinal==count-1),
                context=dict(bar_state="realtime",trigger="bar_close" if ordinal==count-1 else "realtime_tick",is_new=ordinal==0))


@installed
@pytest.mark.parametrize("route",["chart_strategy","external_strategy"])
def test_actual_worker_keeps_forming_state_and_replays_identical_deltas_after_restart(route):
    runtime,wire=runtime_for(route)
    cancel=threading.Event()
    stream=PineStream(runtime,wire,dict(source=SOURCE,parameters={},context=dict(symbol="A",timeframe="1")),cancel)
    recovered=None
    try:
        stream.begin(observation(0,0)["evaluation"]["bar"],bar_state="realtime")
        for ordinal in range(2):
            result=stream.observe(observation(0,ordinal))
            assert len(result["intents"])==1 and result["intent_base"]==ordinal and "output" not in result
        saved=stream.checkpoint()
        # Caller mutation cannot rewrite the durable checkpoint or its transcript.
        edited=deepcopy(saved);edited["journal"][1]["command"]["observation"]["evaluation"]["account"]["position_size"]=99
        with pytest.raises(BacktestError): PineStream.restore(runtime,edited,cancel)
        stream.close()
        recovered=PineStream.restore(runtime,saved,cancel)
        for ordinal in range(2,4):
            result=recovered.observe(observation(0,ordinal))
            assert result["intents"][0]["id"]==str(ordinal+1)
        recovered.commit()
        result=recovered.output(include_intents=True)
        assert [p["values"] for p in result["output"]["plots"]]==[[4],[3],[3]]
        assert len(result["intents"])==4 and result["intent_base"]==0
        assert saved["passes"]==2 and len(saved["journal"])==3
        assert result["output"].get("strategy") is None
    finally:
        stream.close()
        if recovered is not None: recovered.close()


@installed
def test_many_same_bar_observations_do_not_resend_prior_intents_or_output_history():
    runtime,wire=runtime_for("external_strategy")
    cancel=threading.Event()
    stream=PineStream(runtime,wire,dict(source=SOURCE,parameters={},context=dict(symbol="A",timeframe="1")),cancel)
    try:
        stream.begin(observation(0,0)["evaluation"]["bar"],bar_state="realtime")
        sizes=[]
        for ordinal in range(128):
            before=stream.worker.input_bytes
            result=stream.observe(observation(0,ordinal,128))
            sizes.append(stream.worker.input_bytes-before)
            assert len(result["intents"])==1 and result["intent_base"]==ordinal
        stream.commit()
        assert max(sizes)-min(sizes)<100
        assert stream.cursor==1 and stream.intents==128
        assert stream.output()["output"]["plots"][0]["values"]==[128]
    finally:
        stream.close()
