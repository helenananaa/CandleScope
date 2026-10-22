"""A missing tick acknowledgement must reap the actual worker process."""
import sys
import threading
import os
from copy import deepcopy
import pytest
from app.backtest.native_session import SessionWorker, SCHEDULE_CONTRACT, TICK_CONTRACT
from app.backtest.native import PROTOCOL, encoded, invoke


def test_tick_schedule_missing_acknowledgement_reaps_worker():
    identity={"execution_schedule_contract":SCHEDULE_CONTRACT,"execution_tick_contract":TICK_CONTRACT}
    script="import json,sys\nr=json.loads(sys.stdin.readline())\nprint(json.dumps({'ok':True,'identity':r['identity'],'execution_schedule_contract':'"+SCHEDULE_CONTRACT+"'}),flush=True)\nsys.stdin.read()\n"
    worker=SessionWorker({"command":[sys.executable,"-u","-c",script]},{"identity":identity},threading.Event(),evaluator=True)
    with pytest.raises(ValueError,match="tick schedule acknowledgement missing"):
        worker.request({"operation":"execute","execution_schedule":[],"execution_schedule_contract":SCHEDULE_CONTRACT,"execution_tick_contract":TICK_CONTRACT},threading.Event())
    assert worker.process.poll() is not None and worker.stderr.closed


def test_unnegotiated_tick_schedule_is_rejected_before_worker_exchange():
    worker=SessionWorker({"command":[sys.executable,"-u","-c","import sys; sys.stdin.read()"]},{"identity":{}},threading.Event(),evaluator=True)
    try:
        with pytest.raises(ValueError,match="tick schedule was not negotiated"):
            worker.request({"execution_tick_contract":TICK_CONTRACT,"execution_schedule":[]},threading.Event())
        assert worker.input_bytes == 0
    finally:
        worker.close()


@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"),reason="requires installed Pine bridge")
@pytest.mark.parametrize("route",["chart_strategy","external_strategy"])
def test_actual_history_ticks_cross_ipc_append_and_restart_with_frozen_contract(route):
    from app.backtest.strategy.pine_engine import plugin
    from tests.test_pine_schedule_transport import request
    runtime=plugin()
    runtime["command"][-1]=f"candlescope_plugin_pine_compat.{route}"
    identity=invoke(runtime,{"operation":"describe"})["identity"]
    if identity.get("execution_tick_contract") != TICK_CONTRACT:
        pytest.skip("installed core does not advertise tick schedule")
    assert identity["max_tick_passes_per_bar"] == 100_000
    header=dict(protocol=PROTOCOL,identity=identity)
    def payload(count):
        value=request(count)
        value["source"]='//@version=6\nstrategy("history ticks",calc_on_every_history_tick=true)\nvar int ordinary=0\nvarip int n=0\nordinary+=1\nn+=1\nplot(ordinary)\nplot(n)\n'
        value["execution_tick_contract"]=TICK_CONTRACT
        for group in value["execution_schedule"]:
            template=deepcopy(group[-1])
            group[:]=[deepcopy(template) for _ in range(4)]
            for index,item in enumerate(group):
                item["evaluation"]["event_time_ms"]=item["evaluation"]["bar"]["time"]*1000+index
                item["evaluation"]["confirmed"]=index==3
                item["context"]={"bar_state":"historical","trigger":"historical_tick","is_new":True}
        return {**header,**value}
    cancel=threading.Event()
    worker=SessionWorker(runtime,header,cancel,evaluator=True)
    try:
        first=worker.request(payload(1),cancel)
        before=worker.input_bytes
        value=payload(2)
        appended=worker.request(value,cancel)
        assert worker.input_bytes-before < len((encoded(value)+"\n").encode("utf-8"))
        assert appended == invoke(runtime,value)
        assert [row["values"] for row in appended["raw_output"]["plots"]] == [[1,2],[4,8]]
        assert first["raw_output"]["plots"][1]["values"] == [4]
        assert appended["execution_tick_contract"] == TICK_CONTRACT
        before=worker.input_bytes
        with pytest.raises(ValueError,match="tick schedule was not negotiated"):
            worker.request({**value,"execution_tick_contract":"unknown"},cancel)
        assert worker.input_bytes == before
        assert worker.request(value,cancel) == appended
    finally:
        worker.close()
    restarted=SessionWorker(runtime,header,cancel,evaluator=True)
    try:
        assert restarted.request(payload(2),cancel) == appended
    finally:
        restarted.close()


@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"),reason="requires installed Pine bridge")
@pytest.mark.parametrize("route",["chart_strategy","external_strategy"])
@pytest.mark.parametrize("field",["open","high","low","close","volume"])
@pytest.mark.parametrize("history",[False,True])
def test_actual_realtime_static_root_tracks_observed_tuple_after_append_and_restart(route,field,history):
    from app.backtest.strategy.pine_engine import plugin
    from tests.test_pine_schedule_transport import request
    runtime=plugin()
    runtime["command"][-1]=f"candlescope_plugin_pine_compat.{route}"
    identity=invoke(runtime,{"operation":"describe"})["identity"]
    header=dict(protocol=PROTOCOL,identity=identity)
    value=request(2)
    value["context"]=dict(symbol="A",timeframe="1")
    value["contexts"]=[dict(symbol="B",timeframe="1",bars=[dict(time=i*60,open=50,high=50,low=50,close=50,volume=1) for i in range(2)])]
    value["source"]=f'''//@version=6
strategy("Observed static root",calc_on_every_tick=true,calc_on_every_history_tick={str(history).lower()},dynamic_requests=false)
x=request.security(syminfo.tickerid,timeframe.period,{field})
y=request.security("B","1",x)
varip float direct=0
varip float nested=0
direct:=direct*100+x
nested:=nested*100+y
plot(direct)
plot(nested)
'''
    expected=[]
    total=0
    for index,bar in enumerate(value["bars"]):
        bar.update(open=10+10*index,high=12+10*index,low=9+10*index,close=11+10*index)
        high=low=bar["open"]
        group=[]
        for tick,price in enumerate([bar["open"],bar["high"],bar["low"],bar["close"]]):
            high=max(high,price)
            low=min(low,price)
            observed={**bar,"high":high,"low":low,"close":price,"volume":bar["volume"]*(tick+1)/4}
            group.append(dict(evaluation=dict(bar=observed,account=deepcopy(value["accounts"][index]),
                event_time_ms=bar["time"]*1000+59999*tick//3,confirmed=tick==3),
                context=dict(bar_state="realtime",trigger="bar_close" if tick==3 else "realtime_tick",is_new=tick==0)))
            total=total*100+observed[field]
        value["execution_schedule"][index]=group
        expected.append(total)
    value={**header,**value}
    first=deepcopy(value)
    for key in ("bars","accounts","execution_schedule"):
        first[key]=first[key][:1]
    cancel=threading.Event()
    worker=SessionWorker(runtime,header,cancel,evaluator=True)
    try:
        assert [p["values"] for p in worker.request(first,cancel)["raw_output"]["plots"]] == [[expected[0]],[expected[0]]]
        before=worker.input_bytes
        appended=worker.request(value,cancel)
        assert worker.input_bytes-before < len((encoded(value)+"\n").encode("utf-8"))
        assert appended == invoke(runtime,value)
        assert [p["values"] for p in appended["raw_output"]["plots"]] == [expected,expected]
    finally:
        worker.close()
    restarted=SessionWorker(runtime,header,cancel,evaluator=True)
    try:
        assert restarted.request(value,cancel) == appended
    finally:
        restarted.close()
