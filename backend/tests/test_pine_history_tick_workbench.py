"""Actual Workbench history ticks, including durable ledger/stream restore."""
from decimal import Decimal
import json

import pytest

from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_pine_bar_workbench import config as v1_config
from tests.test_pine_workbench_v2_bar import config as v2_config
from tests.test_native_replay import settle
from tests.test_pine_history_tick_clock import SOURCE


def config(main,model="v1",*,count=None):
    value=v1_config(main) if model=="v1" else v2_config(main,model=model)
    value["fill_recalculation"]=False
    value["source"]=SOURCE.replace(",calc_on_order_fills=true","")
    if count is not None:
        value["source"]=value["source"].replace('initial_capital=1000)',f'initial_capital=1000,calc_bars_count={count})')
    return value


@pytest.mark.parametrize("model",["SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V1","LINEAR_PERP_ONE_WAY_V2"])
@pytest.mark.parametrize("profile",["plain","closing","renko"])
def test_chained_history_begin_preserves_complete_reports_journals_and_cold_restore(runtime,monkeypatch,model,profile):
    import threading
    from app.backtest.external import run_external_host
    from app.backtest.native import encoded,digest,invoke
    from app.backtest.native_session import SessionWorker
    from app.backtest.pine_stream import PineStream
    from app.backtest import pine_history_tick_execution as execution
    from tests.test_pine_event_realtime import SOURCE as renko_source

    host,main=runtime
    value=config(main,model)
    value["cost_sensitivity_mode"]="SKIP"
    if profile=="closing":
        value["source"]=value["source"].replace("initial_capital=1000)","initial_capital=1000,process_orders_on_close=true)")
    elif profile=="renko":
        value["source"]=renko_source.replace("calc_on_every_tick=true","calc_on_every_history_tick=true")
    run_clock=execution.run_clock
    def serial_clock(*args,**kwargs):
        return run_clock(*args,**kwargs,_chain_commits=False)
    def serial_begin(stream,bar,*,bar_state,observation,_owned=False,_commit_previous=False):
        assert not _commit_previous
        stream.begin(bar,bar_state=bar_state)
        return stream.observe(observation,_owned=_owned)
    with monkeypatch.context() as patch:
        patch.setattr(PineStream,"begin_and_observe",serial_begin)
        patch.setattr(execution,"run_clock",serial_clock)
        control=terminal(host.native,host.native.create(value,"history-serial-begin")["run_id"])
    optimized=terminal(host.native,host.native.create(value,"history-chained-begin")["run_id"])
    assert control["state"]==optimized["state"]=="COMPLETED",(control.get("error"),optimized.get("error"))
    assert encoded(optimized["result"])==encoded(control["result"])
    wire=host.native.replay._input(control["run_id"])
    exchange=SessionWorker._exchange_one
    def capture(chained):
        frames=[]
        def measured(worker,raw):
            request=json.loads(raw)
            frames.append([command["operation"] for command in request["commands"]]
                if request["operation"]=="stream_chain" else [request["operation"]])
            return exchange(worker,raw)
        with monkeypatch.context() as patch:
            if not chained:
                patch.setattr(PineStream,"begin_and_observe",serial_begin)
                patch.setattr(execution,"run_clock",serial_clock)
            patch.setattr(SessionWorker,"_exchange_one",measured)
            result,state=run_external_host(control["runtime_launch"],wire,invoke,threading.Event(),target=3)
        return result,state,frames
    before,old_state,old_frames=capture(False)
    after,new_state,new_frames=capture(True)
    assert encoded(after)==encoded(before)
    assert encoded(new_state)==encoded(old_state)
    assert new_state["clock"]["stream"]["bar_open"] is False
    assert [operation for frame in new_frames for operation in frame]==[operation for frame in old_frames for operation in frame]
    assert len(new_frames)<len(old_frames)
    assert ["stream_begin","stream_observe"] in new_frames
    assert ["stream_commit","stream_begin","stream_observe"] in new_frames
    restored,_=run_external_host(control["runtime_launch"],wire,invoke,threading.Event(),
        resume=old_state,target=len(wire["bars"]))
    restored["bars"]=wire["bars"];restored["report_hash"]=digest(restored)
    assert encoded(restored)==encoded(control["result"])


@pytest.mark.parametrize("failure",["next_begin","final_commit"])
def test_failed_chained_history_begin_keeps_committed_state_and_retries_exactly(runtime,monkeypatch,failure):
    import time
    from app.backtest.errors import BacktestError
    from app.backtest.native import encoded
    from app.backtest.native_replay import NativeReplay
    from app.backtest.pine_stream import PineStream
    from app.backtest.pine_history_tick_clock import HistoryTickClock
    host,main=runtime
    value=config(main,"LINEAR_PERP_ONE_WAY_V2");value["cost_sensitivity_mode"]="SKIP"
    origin=terminal(host.native,host.native.create(value,"history-begin-failure")["run_id"])
    assert origin["state"]=="COMPLETED",origin.get("error")
    replay=host.native.replay
    created=replay.create(origin["run_id"]);key=created["replay_id"]
    replay.command(key,created["revision"],"seek",3)
    middle=settle(replay,key)
    saved=encoded(replay._host_state(key))
    replay.shutdown()
    host.native.replay=replay=NativeReplay(host.native)
    begin=PineStream.begin_and_observe
    flush=HistoryTickClock.flush_commit
    observed=[]
    def failed_begin(stream,*args,**kwargs):
        begin(stream,*args,**kwargs)
        observed.append(stream.cursor)
        raise BacktestError("CONTROLLED_BEGIN_FAILURE","after both checked replies before Host publication")
    def failed_flush(clock):
        pending=clock._pending_commit
        flush(clock)
        if pending:
            observed.append(clock.stream.cursor)
            raise BacktestError("CONTROLLED_BEGIN_FAILURE","after final commit before Host publication")
    with monkeypatch.context() as patch:
        if failure=="next_begin": patch.setattr(PineStream,"begin_and_observe",failed_begin)
        else: patch.setattr(HistoryTickClock,"flush_commit",failed_flush)
        replay.command(key,replay.get(key)["revision"],"seek",created["total"])
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            with host.native.lock:
                if key not in replay.jobs: break
            time.sleep(.02)
        else: pytest.fail("controlled history begin failure did not stop")
    failed=replay.get(key)
    assert observed and failed["state"]=="FAILED" and "CONTROLLED_BEGIN_FAILURE" in failed["error"]["message"]
    assert failed["cursor"]==3 and encoded(failed["result"])==encoded(middle["result"])
    assert encoded(replay._host_state(key))==saved
    replay.command(key,failed["revision"],"seek",created["total"])
    assert encoded(settle(replay,key)["result"])==encoded(origin["result"])


@pytest.mark.parametrize("model",["v1","LINEAR_PERP_ONE_WAY_V1","SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V2"])
def test_actual_workbench_routes_four_observations_independently_of_fill_callbacks(runtime,model):
    host,main=runtime
    record=terminal(host.native,host.native.create(config(main,model),"history-ticks")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    groups=result["raw_output"]["execution_schedule"]
    assert all(len(group)==4 for group in groups) and len(groups)==10
    assert all(item["context"]==dict(bar_state="historical",trigger="historical_tick",is_new=True)
               for group in groups for item in group)
    assert result["graphics"][4]["values"]==list(range(4,41,4))
    assert all(Decimal(trade["qty"])==1 for trade in result["trades"])
    expected=16 if model=="LINEAR_PERP_ONE_WAY_V2" else 20
    assert len(result["trades"])==expected and Decimal(result["position"]["position_qty"])==0, json.dumps(result["diagnostics"])
    if model=="LINEAR_PERP_ONE_WAY_V2":
        # The frozen legacy Host policy applies its minimum notional to these
        # reduce-only closes too. Two low-price closes are rejected; their
        # position remains real until a later eligible close. Tick scheduling
        # must not relax the account's admission policy to force native parity.
        assert [row["reason"] for row in result["diagnostics"]]==["MIN_NOTIONAL","MIN_NOTIONAL"]
        assert all(row["intent"]["reduce_only"] for row in result["diagnostics"])
    assert result["trades"][0]["event_time_ms"]==0
    assert result["trades"][1]["event_time_ms"]==19999


@pytest.mark.parametrize("model,count",[("v1",None),("LINEAR_PERP_ONE_WAY_V2",None),("v1",2)])
def test_durable_replay_reconstructs_observations_before_restoring_the_matching_ledger(runtime,model,count):
    host,main=runtime
    record=terminal(host.native,host.native.create(config(main,model,count=count),"tick-replay")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    def seek(target):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        value=settle(replay,key)
        assert value.get("error") is None,value
        return value
    first=seek(1)
    saved=replay.snapshot(key,first["revision"])["snapshots"][0]["snapshot_id"]
    third=seek(3)
    replay.restore(key,third["revision"],saved)
    assert seek(3)["result"]==third["result"]
    assert seek(created["total"])["result"]==record["result"]


@pytest.mark.parametrize("closing",[False,True])
def test_final_vertex_market_uses_next_open_or_explicit_closing_tick(runtime,closing):
    host,main=runtime
    value=config(main)
    value["source"]='''//@version=6
strategy("last vertex",calc_on_every_history_tick=true%s)
varip int n=0
n+=1
if n==4
    strategy.entry("L",strategy.long,qty=2)
plot(n)
plot(strategy.position_size)
''' % (",process_orders_on_close=true" if closing else "")
    record=terminal(host.native,host.native.create(value,"last-vertex")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert result["trades"][0]["event_time_ms"]==(59999 if closing else 60000)
    assert result["trades"][0]["reason"]==("PINE_BAR_CLOSE" if closing else "MARKET_NEXT_VERTEX")
    assert result["graphics"][0]["values"]==list(range(4,41,4))
    assert result["graphics"][1]["values"][0]==0
    assert result["graphics"][1]["values"][1]==2


def test_v2_liquidation_is_observed_at_the_next_vertex_without_a_second_tick_execution(runtime):
    host,main=runtime
    value=config(main,"LINEAR_PERP_ONE_WAY_V2")
    value["host_settings"]["initial_balance"]=100
    value["participation_rate"]=.5
    value["source"]='''//@version=6
strategy("liquidation ticks",calc_on_every_history_tick=true,calc_on_order_fills=true)
varip int n=0
n+=1
if n==1
    strategy.entry("L",strategy.long,qty=50)
plot(n)
plot(strategy.position_size)
'''
    value["fill_recalculation"]=True
    value["account_data"]["events"].append(dict(time_ms=70000,role="MARK_INDEX",payload=dict(mark_price="8",index_price="8")))
    record=terminal(host.native,host.native.create(value,"tick-liquidation")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert len(result["trades"])==2 and result["trades"][-1]["account_liquidation"]["trigger"]=="MARK_INDEX"
    assert result["trades"][-1]["event_time_ms"]==70000
    group=result["raw_output"]["execution_schedule"][1]
    assert [item["evaluation"]["account"]["position_size"] for item in group]==[50,0,0,0]
    assert result["graphics"][0]["values"]==list(range(4,41,4))
    assert all(len(group)==4 for group in result["raw_output"]["execution_schedule"])


def test_requested_streams_use_canonical_history_and_restore_without_resending_old_updates(runtime):
    from tests.test_native_additional_inputs import additional
    host,main=runtime
    value=config(main)
    value["contexts"]=[{**additional(host,"tick-foreign","ETHUSDT","2m",120000,[100,200,300,400,500]),
        "symbol":"BINANCE:ETHUSDT","timeframe":"2","metadata":{"priceTickSize":".25"}}]
    value["source"]+='\nplot(request.security("BINANCE:ETHUSDT","2",close))\n'
    value["source"]+='''
varip array<float> requestedSeen=array.new_float(4,na)
array.set(requestedSeen,(n-1)%4,request.security("BINANCE:ETHUSDT","2",close))
plot(array.get(requestedSeen,0))
plot(array.get(requestedSeen,1))
plot(array.get(requestedSeen,2))
plot(array.get(requestedSeen,3))
'''
    record=terminal(host.native,host.native.create(value,"tick-requests")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert [plot["values"] for plot in result["graphics"][-5:]]==[[None,100,100,200,200,300,300,400,400,500]]*5
    group=result["raw_output"]["execution_schedule"][1]
    assert [item["evaluation"]["request_observed_at_ms"] for item in group]==[119999]*4
    assert [len(item["evaluation"]["request_updates"]) for item in group]==[1,0,0,0]
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    for target in (2,5,created["total"]):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        current=settle(replay,key)
        assert current.get("error") is None,current
    assert current["result"]==record["result"]
