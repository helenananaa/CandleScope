"""Real subprocess discovery and transcript recovery, before ledger restoration."""
from copy import deepcopy
import os
import threading

import pytest

from app.backtest.errors import BacktestError
from app.backtest.native import PROTOCOL, invoke
from app.backtest.pine_stream import PineStream, WINDOW_FEEDBACK_CONTRACT, WindowRebaseRequired
from app.backtest.pine_event_requests import CONTRACT, frozen_sources


pytestmark=pytest.mark.skipif(not os.environ.get("PINE_EVENT_TEST_PYTHON"),reason="requires the new installed event worker")


def inputs():
    bars=[dict(time=i*60,open=p,high=p,low=p,close=p,volume=6) for i,p in enumerate((10,13,15))]
    context=dict(symbol="A",timeframe="1")
    return dict(source='''//@version=6
strategy("event restart",calc_on_every_history_tick=true)
varip int n=0
n+=1
strategy.entry(str.tostring(n),strategy.long,qty=1)
r=ticker.renko("A","Traditional",1)
plot(request.security(r,"1",ta.cum(close),calc_bars_count=1))
plot(n)
''',parameters={},context=context,historical_plan=bars,
        event_request_contract=CONTRACT,event_sources=frozen_sources(context,bars,"1m",[]),
        window_feedback_contract=WINDOW_FEEDBACK_CONTRACT)


def observe(bar):
    return dict(evaluation=dict(bar=bar,account=dict(time=bar["time"],position_size=0,
        position_avg_price=None,initial_capital=1000,equity=1000,netprofit=0,openprofit=0),
        event_time_ms=bar["time"]*1000+59999,confirmed=True),
        context=dict(bar_state="historical",trigger="historical_tick",is_new=True))


@pytest.mark.parametrize("route",["chart_strategy","external_strategy"])
def test_real_event_stream_discards_interrupted_intents_and_reconstructs_identical_prefix(route):
    runtime=dict(command=[os.environ["PINE_EVENT_TEST_PYTHON"],"-m",f"candlescope_plugin_pine_compat.{route}"])
    identity=invoke(runtime,dict(operation="describe"))["identity"]
    assert identity["event_request_contract"]==CONTRACT
    wire=dict(protocol=PROTOCOL,identity=identity)
    opening=inputs()
    cancel=threading.Event()
    stream=PineStream(runtime,wire,opening,cancel)
    recovered=None
    try:
        first=opening["historical_plan"][0]
        stream.begin(first,bar_state="historical")
        with pytest.raises(WindowRebaseRequired):
            stream.observe(observe(first))
        assert stream.last["intents"]==[] and stream.intents==0
        assert stream.last["event_request_state"]["pending"]
        stream.rebase()
        for bar in opening["historical_plan"]:
            stream.begin(bar,bar_state="historical")
            stream.observe(observe(bar))
            stream.commit()
        stream.rebase(seal=True)
        assert not stream.last["window_status"]["requires_discovery"]
        for bar in opening["historical_plan"][:2]:
            stream.begin(bar,bar_state="historical")
            stream.observe(observe(bar))
            stream.commit()
        saved=stream.checkpoint()
        expected=stream.output()
        stream.close()
        seen=[]
        def verify(command,result):
            if command["operation"]=="stream_rebase":seen.clear()
            elif command["operation"]=="stream_observe":seen.extend(result["intents"])
        recovered=PineStream.restore(runtime,saved,cancel,verify=verify)
        assert [item["id"] for item in seen]==["1","2"]
        assert recovered.output()==expected
        recovered.begin(opening["historical_plan"][2],bar_state="historical")
        assert recovered.observe(observe(opening["historical_plan"][2]))["intents"][0]["id"]=="3"
        recovered.commit()
        assert [plot["values"] for plot in recovered.output()["output"]["plots"]]==[[None,None,15],[1,2,3]]
        corrupt=deepcopy(saved)
        for rows in (corrupt["opening"]["historical_plan"],corrupt["opening"]["event_sources"][0]["bars"]):
            rows[-1].update(open=16,high=16,low=16,close=16)
        with pytest.raises(BacktestError,match="replay changed"):
            PineStream.restore(runtime,corrupt,cancel)
    finally:
        stream.close()
        if recovered is not None:recovered.close()
