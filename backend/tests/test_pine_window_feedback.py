"""Actual worker control transfer and fresh-ledger dynamic window discovery."""
from copy import deepcopy
from decimal import Decimal
import os
import threading
import pytest

from app.backtest.errors import BacktestError
from app.backtest.pine_stream import PineStream, WINDOW_FEEDBACK_CONTRACT, WindowRebaseRequired
from tests.test_pine_stream import runtime_for, observation
from tests.test_native_backtests import runtime_at, terminal
from tests.test_chart_pine_callbacks import service as service

pytestmark=pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"),reason="requires isolated installed Pine worker")


@pytest.fixture
def runtime(tmp_path):
    # Chart and Native services must not share a database/dispatcher fixture.
    directory=tmp_path/"native-window"
    directory.mkdir()
    yield from runtime_at(directory)


SOURCE='''//@version=6
strategy("observed window",calc_on_every_history_tick=true,calc_bars_count=1)
varip int n=0
n+=1
strategy.entry(str.tostring(n),strategy.long,qty=1)
s=strategy.position_size>0?"A":"B"
plot(request.security(s,"1",close,calc_bars_count=2))
plot(n)
'''


def historical(index,ordinal):
    value=observation(index,ordinal)
    value["context"]=dict(bar_state="historical",trigger="historical_tick",is_new=True)
    return value


@pytest.mark.parametrize("route",["chart_strategy","external_strategy"])
def test_interrupted_worker_emits_no_partial_intents_and_replays_resets_exactly(route):
    runtime,wire=runtime_for(route)
    cancel=threading.Event()
    opening=dict(source=SOURCE,parameters={},context=dict(symbol="A",timeframe="1"),
        contexts=[dict(symbol="B",timeframe="1",bars=[])],
        historical_plan=[historical(i,0)["evaluation"]["bar"] for i in range(2)],
        window_feedback_contract=WINDOW_FEEDBACK_CONTRACT)
    stream=PineStream(runtime,wire,opening,cancel)
    restored=None
    try:
        assert stream.input_skip==1 and stream.last["window_status"]["requires_discovery"]
        stream.begin(opening["historical_plan"][1],bar_state="historical")
        assert len(stream.observe(historical(1,0))["intents"])==1
        with pytest.raises(WindowRebaseRequired): stream.observe(historical(1,1))
        assert stream.last["intents"]==[] and stream.intents==1
        assert stream.last["window_status"]["input_skip"]==0
        stream.rebase()
        assert stream.cursor==stream.intents==stream.passes==stream.input_skip==0 and not stream.bar_open
        for i in range(2):
            stream.begin(opening["historical_plan"][i],bar_state="historical")
            for ordinal in range(4): stream.observe(historical(i,ordinal))
            stream.commit()
        assert stream.output()["output"]["plots"][1]["values"]==[4,8]
        stream.rebase(seal=True)
        assert not stream.last["window_status"]["requires_discovery"]
        saved=stream.checkpoint()
        stream.close()
        seen=[]
        def verify(command,result):
            if command["operation"]=="stream_rebase": seen.clear()
            elif command["operation"]=="stream_observe": seen.extend(result["intents"])
        restored=PineStream.restore(runtime,saved,cancel,verify=verify)
        assert seen==[] and restored.checkpoint()==saved
        edited=deepcopy(saved)
        edited["journal"][-1]["command"]["seal"]=False
        with pytest.raises(BacktestError): PineStream.restore(runtime,edited,cancel)
        restored.begin(opening["historical_plan"][0],bar_state="historical")
        assert restored.observe(historical(0,0))["intents"][0]["id"]=="1"
    finally:
        stream.close()
        if restored is not None: restored.close()


def workbench_value(host,main,model="v1"):
    from tests.test_pine_history_tick_workbench import config
    from tests.test_native_additional_inputs import additional
    value=config(main,model)
    root=value["context"]["symbol"]
    value["source"]='''//@version=6
strategy("actual window",calc_on_every_history_tick=true,calc_bars_count=1)
varip int n=0
n+=1
if n==1
    strategy.entry("L",strategy.long,qty=1)
s=strategy.position_size>0?"ROOT":"BINANCE:ETHUSDT"
plot(request.security(s,"1",ta.cum(close),calc_bars_count=3))
plot(n)
plot(strategy.position_size)
'''.replace("ROOT",root)
    value["contexts"]=[{**additional(host,"actual-window","ETHUSDT","1m",60000,list(range(100,1001,100))),
        "symbol":"BINANCE:ETHUSDT","timeframe":"1"}]
    value["cost_sensitivity_mode"]="SKIP"
    return value


@pytest.mark.parametrize("model",["v1","SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V2"])
def test_workbench_discovers_with_actual_fills_then_publishes_a_fresh_canonical_ledger(runtime,model):
    from tests.test_native_replay import settle
    host,main=runtime
    value=workbench_value(host,main,model)
    record=terminal(host.native,host.native.create(value,"actual-window")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert result["graphics"][1]["values"]==[4,8,12]
    assert result["graphics"][2]["values"]==[1,1,1]
    assert len(result["trades"])==1 and result["trades"][0]["event_time_ms"]==420000
    assert [len(group) for group in result["raw_output"]["execution_schedule"]]==[0]*7+[4]*3
    control=deepcopy(value);control["source"]=control["source"].replace("calc_bars_count=1)","calc_bars_count=3)")
    reference=terminal(host.native,host.native.create(control,"fixed-window-control")["run_id"])
    assert reference["state"]=="COMPLETED",reference.get("error")
    assert result["trades"]==reference["result"]["trades"]
    assert result["graphics"]==reference["result"]["graphics"]
    replay=host.native.replay
    created=replay.create(record["run_id"]);key=created["replay_id"]
    for target in (2,8,created["total"]):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        state=settle(replay,key)
        assert state.get("error") is None,state
    assert state["result"]==result
    from app.backtest.external_replay import validate_state
    from app.backtest.native import digest
    with host.native.lock:
        damaged=deepcopy(replay._host_state(key))
        wire=deepcopy(replay._input(record["run_id"]))
    damaged["clock"]["groups"][7][0]["evaluation"]["account"]["equity"]+=1
    damaged["last_request"]["execution_schedule"]=deepcopy(damaged["clock"]["groups"])
    damaged["checksum"]=digest({k:v for k,v in damaged.items() if k!="checksum"})
    with pytest.raises(BacktestError,match="observations differ"):
        validate_state(wire,damaged)


def test_cost_scenarios_repeat_the_actual_window_discovery_with_independent_host_accounts(runtime):
    host,main=runtime
    value=workbench_value(host,main)
    value["cost_sensitivity_mode"]="AUTO"
    value["host_settings"].update(taker_fee_bps=10,slippage_bps=5)
    record=terminal(host.native,host.native.create(value,"actual-window-costs")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert len(result["trades"])==1
    matrix=result["cost_sensitivity"]
    assert matrix["status"]=="COMPLETED" and matrix["baseline_reexecution_verified"]
    assert len(matrix["scenarios"])==5
    executed=[item for item in matrix["scenarios"] if item["executed"]]
    assert len(executed)==3
    assert all(Decimal(item["metrics"]["ending_position"])==1 for item in executed)
    assert {item["name"] for item in executed}=={"BASELINE","COSTS_PLUS_25_PERCENT","COSTS_PLUS_50_PERCENT"}


@pytest.mark.parametrize("route",["chart_strategy","external_strategy"])
def test_actual_script_failure_is_fatal_even_with_window_feedback_negotiated(route):
    runtime,wire=runtime_for(route)
    opening=dict(source=SOURCE+'\nruntime.error("actual failure")',parameters={},
        context=dict(symbol="A",timeframe="1"),contexts=[dict(symbol="B",timeframe="1",bars=[])],
        historical_plan=[historical(i,0)["evaluation"]["bar"] for i in range(2)],
        window_feedback_contract=WINDOW_FEEDBACK_CONTRACT)
    stream=PineStream(runtime,wire,opening,threading.Event())
    try:
        stream.begin(opening["historical_plan"][1],bar_state="historical")
        with pytest.raises(BacktestError) as error: stream.observe(historical(1,0))
        assert error.value.code!="PINE_WINDOW_REBASE_REQUIRED"
        assert stream.worker._closed
    finally: stream.close()


@pytest.mark.parametrize("spot,inline,cost",[(False,True,"FULL"),(True,True,"SKIP"),(False,False,"SKIP")])
def test_chart_discards_all_tentative_fills_before_committing_a_stable_window(service,runtime,spot,inline,cost):
    from tests.test_chart_pine_bar_callbacks import config,execute,RecordingProvider
    from tests.test_native_additional_inputs import additional
    from app.backtest.strategy.pine_engine import PineEngineProvider
    host,_=runtime
    reference=additional(host,"chart-dynamic-window","ETHUSDT","1m",60000,[100,200,300,400,500])
    service.pine_local_data_root=str(host.local_data.root)
    service._colocated_worker=inline
    source='''//@version=6
strategy("chart window",calc_on_every_history_tick=true,calc_bars_count=1)
strategy.risk.max_intraday_filled_orders(2)
varip int n=0
n+=1
if n==1
    strategy.entry("L",strategy.long,qty=1)
s=strategy.position_size>0?syminfo.tickerid:"BINANCE:ETHUSDT"
plot(request.security(s,"1",ta.cum(close),calc_bars_count=3))
plot(n)
plot(strategy.position_size)
'''
    value=config(service,source=source,spot=spot,cost_sensitivity_mode=cost,slippage_bps="5",taker_fee_bps="10",
        pine_contexts=[{**reference,"symbol":"BINANCE:ETHUSDT","timeframe":"1"}])
    provider=RecordingProvider()
    checkpoints=[]
    save=service._save_bar_checkpoint
    def checked_save(*args,**kwargs):
        pending=bool(provider.stream and provider.stream.last.get("window_status",{}).get("requires_discovery"))
        checkpoints.append((kwargs["sequence"],len(kwargs["kernel"].fills),pending))
        return save(*args,**kwargs)
    service._save_bar_checkpoint=checked_save
    result=execute(service,value,"chart-dynamic-window",provider)
    service._save_bar_checkpoint=save
    assert checkpoints and all(not item[2] and item[1]<=1 for item in checkpoints)
    saved=provider.snapshot()
    assert saved["stream_checkpoint"]["input_skip"]==2
    assert len(saved["history"])==1
    assert len(result["report"]["fills"])==1 and result["report"]["fills"][0]["event_time_ms"]==120000
    restored=PineEngineProvider()
    try:
        restored.restore(saved)
        assert [plot["values"] for plot in restored.stream.output()["output"]["plots"]][1:]==[[4,8,12],[1,1,1]]
    finally: restored.close()
    control=config(service,source=source.replace("calc_bars_count=1)","calc_bars_count=3)"),spot=spot,
        cost_sensitivity_mode="SKIP",slippage_bps="5",taker_fee_bps="10",pine_contexts=value["pine_contexts"])
    baseline=execute(service,control,"chart-fixed-window")
    assert result["report"]["fills"]==baseline["report"]["fills"]
    if cost=="FULL":
        matrix=result["report"]["cost_sensitivity"]
        assert matrix["status"]=="COMPLETED" and matrix["baseline_reexecution_verified"]


def test_chart_v2_dynamic_window_restarts_the_actual_rules_mark_capacity_and_account_state(service,runtime):
    from tests.test_chart_pine_v2_bar import config,execute,bars
    from tests.test_chart_pine_bar_callbacks import RecordingProvider
    from tests.test_pine_v2_bar_kernel import numbered,mark
    from tests.test_backtest_account_v2_m4 import rules
    from tests.test_native_additional_inputs import additional
    host,_=runtime
    reference=additional(host,"chart-v2-window","ETHUSDT","1m",60000,[100,200,300,400,500])
    service.pine_local_data_root=str(host.local_data.root)
    source='''//@version=6
strategy("chart V2 window",calc_on_every_history_tick=true,calc_bars_count=1)
varip int n=0
n+=1
if n==1
    strategy.entry("L",strategy.long,qty=1)
s=strategy.position_size>0?syminfo.tickerid:"BINANCE:ETHUSDT"
plot(request.security(s,"1",ta.cum(close),calc_bars_count=3))
plot(n)
plot(strategy.position_size)
'''
    value=config(service,account="LINEAR_PERP_ONE_WAY_V2",source=source,cost_sensitivity_mode="SKIP",
        pine_contexts=[{**reference,"symbol":"BINANCE:ETHUSDT","timeframe":"1"}])
    rows=numbered(rules(-2),mark(-1,10),*bars())
    provider=RecordingProvider()
    result=execute(service,value,"chart-v2-window",rows=rows,provider=provider)
    assert len(result["report"]["fills"])==1 and result["report"]["fills"][0]["event_time_ms"]==120000
    assert provider.snapshot()["stream_checkpoint"]["input_skip"]==2
