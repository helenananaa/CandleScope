"""Workbench actual print/book tick execution and evaluator-before-ledger recovery."""
from decimal import Decimal
from copy import deepcopy

import pytest

from tests.test_native_backtests import runtime as runtime,terminal,pytestmark as pytestmark
from tests.test_external_replay import payload
from tests.test_pine_workbench_v2_print import config as v2_config
from tests.test_native_replay import settle


SOURCE='''//@version=6
strategy("physical ticks",calc_on_every_tick=true%s)
varip int n=0
n+=1
if n==1
    strategy.entry("L",strategy.long,qty=1)
if strategy.position_size>0
    strategy.close_all()
plot(n)
plot(strategy.position_size)
plot(close)
plot(volume)
'''
MODES=("TRADE_TAPE","BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED")


def config(main,mode,callbacks,account):
    value=v2_config(main,mode,callbacks) if account=="LINEAR_PERP_ONE_WAY_V2" else payload(main,mode,callbacks)
    if account!="LINEAR_PERP_ONE_WAY_V2": value["account_model"]=account
    if account=="SPOT_CASH_V1": value["market_type"]="spot"
    value["source"]=SOURCE % (",calc_on_order_fills=true" if callbacks else "")
    value["cost_sensitivity_mode"]="SKIP"
    return value


@pytest.mark.parametrize("mode",["BAR_APPROX","TRADE_TAPE","BOOK_DEPTH"])
def test_batch_avoids_unused_private_checkpoint_with_exact_complete_report_parity(runtime,monkeypatch,mode):
    from app.backtest import pine_history_tick_execution, pine_print_tick_execution
    from app.backtest.native import encoded
    from app.backtest.pine_stream import PineStream
    from tests.test_pine_history_tick_workbench import config as history_config
    host,main=runtime
    value=(history_config(main,"LINEAR_PERP_ONE_WAY_V2") if mode=="BAR_APPROX"
           else config(main,mode,False,"LINEAR_PERP_ONE_WAY_V2"))
    value["cost_sensitivity_mode"]="SKIP"
    clock=pine_history_tick_execution if mode=="BAR_APPROX" else pine_print_tick_execution
    run_clock=clock.run_clock
    observe=PineStream.observe
    def materialize_private_state(*args,**kwargs):
        kwargs["capture_checkpoint"]=True
        kwargs["compact_groups"]=False
        return run_clock(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(clock,"run_clock",materialize_private_state)
        patch.setattr(PineStream,"_request_many",lambda self,commands,**kwargs:[self._request(command) for command in commands])
        patch.setattr(PineStream,"observe",lambda self,observation,**kwargs:observe(self,observation))
        control=terminal(host.native,host.native.create(value,"batch-with-private-copy")["run_id"])
    assert control["state"]=="COMPLETED",control.get("error")
    def unused_checkpoint(*args,**kwargs):
        raise AssertionError("batch built an unused private evaluator checkpoint")
    with monkeypatch.context() as patch:
        patch.setattr(PineStream,"checkpoint",unused_checkpoint)
        optimized=terminal(host.native,host.native.create(value,"batch-without-private-copy")["run_id"])
    assert optimized["state"]=="COMPLETED",optimized.get("error")
    assert encoded(optimized["result"])==encoded(control["result"])


@pytest.mark.parametrize("mode",["BAR_APPROX","TRADE_TAPE","BOOK_DEPTH"])
def test_consumed_job_resume_failure_keeps_committed_account_and_public_resume_detached(runtime,monkeypatch,mode):
    import threading
    import time
    from app.backtest import external
    from app.backtest.errors import BacktestError
    from app.backtest.native import encoded,digest,invoke
    from app.backtest.native_replay import NativeReplay
    from app.backtest.pine_history_tick_clock import HistoryTickClock
    from app.backtest.pine_print_tick_execution import PrintTickClock
    from tests.test_pine_history_tick_workbench import config as history_config
    host,main=runtime
    value=(history_config(main,"LINEAR_PERP_ONE_WAY_V2") if mode=="BAR_APPROX"
           else config(main,mode,False,"LINEAR_PERP_ONE_WAY_V2"))
    value["cost_sensitivity_mode"]="SKIP"
    origin=terminal(host.native,host.native.create(value,"owned-resume")["run_id"])
    assert origin["state"]=="COMPLETED",origin.get("error")
    replay=host.native.replay
    created=replay.create(origin["run_id"]);key=created["replay_id"]
    replay.command(key,created["revision"],"seek",3)
    middle=settle(replay,key)
    before=encoded(replay._host_state(key))
    replay.shutdown()
    host.native.replay=replay=NativeReplay(host.native)
    consumed=[]
    run=external._run_external_host
    def observed_run(*args,**kwargs):
        owned=kwargs.get("_consume_resume")
        resume=kwargs.get("resume")
        try: return run(*args,**kwargs)
        finally:
            if owned: consumed.append(resume=={})
    clock_type=HistoryTickClock if mode=="BAR_APPROX" else PrintTickClock
    step_name="vertex" if mode=="BAR_APPROX" else "observe"
    step=getattr(clock_type,step_name)
    def fail_after_restore(*args,**kwargs):
        step(*args,**kwargs)
        raise BacktestError("CONTROLLED_RESUME_FAILURE","after mutating the resumed clock and account")
    with monkeypatch.context() as patch:
        patch.setattr(external,"_run_external_host",observed_run)
        patch.setattr(clock_type,step_name,fail_after_restore)
        replay.command(key,replay.get(key)["revision"],"seek",created["total"])
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            with host.native.lock:
                if key not in replay.jobs: break
            time.sleep(.02)
        else: pytest.fail("controlled resumed operation did not stop")
    failed=replay.get(key)
    assert failed["state"]=="FAILED" and "CONTROLLED_RESUME_FAILURE" in failed["error"]["message"]
    assert consumed==[True]
    assert failed["cursor"]==3 and encoded(failed["result"])==encoded(middle["result"])
    assert encoded(replay._host_state(key))==before
    # The public helper retains caller ownership and its complete input value.
    checkpoint=replay._host_state(key)
    wire=replay._input(origin["run_id"])
    result,_=external.run_external_host(origin["runtime_launch"],wire,invoke,threading.Event(),
        resume=checkpoint,target=created["total"])
    assert encoded(checkpoint)==before
    result["bars"]=wire["bars"];result["report_hash"]=digest(result)
    assert encoded(result)==encoded(origin["result"])
    replay.command(key,failed["revision"],"seek",created["total"])
    assert encoded(settle(replay,key)["result"])==encoded(origin["result"])


@pytest.mark.parametrize("mode", ["BAR_APPROX", "TRADE_TAPE", "BOOK_DEPTH"])
def test_cold_large_seek_replaces_only_the_verified_private_base(runtime, monkeypatch, mode):
    from app.backtest import native_replay
    from app.backtest.native import encoded
    from tests.test_pine_history_tick_workbench import config as history_config
    host, main = runtime
    value = (history_config(main, "LINEAR_PERP_ONE_WAY_V2") if mode == "BAR_APPROX"
             else config(main, mode, False, "LINEAR_PERP_ONE_WAY_V2"))
    value["cost_sensitivity_mode"] = "SKIP"
    origin = terminal(host.native, host.native.create(value, "large-seek-base")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    replay = host.native.replay
    created = replay.create(origin["run_id"]); key = created["replay_id"]
    replay.command(key, created["revision"], "seek", 3)
    middle = settle(replay, key)
    snapshot = replay.snapshot(key, middle["revision"])["snapshots"][0]["snapshot_id"]
    replay.shutdown()
    host.native.replay = replay = native_replay.NativeReplay(host.native)
    replay.restore(key, replay.get(key)["revision"], snapshot)
    loads, saves, owned_states = [], [], []
    load, save = replay.results.load, replay.results.save
    def observed_load(name, **options):
        if name == "host:" + key: loads.append(options)
        return load(name, **options)
    def observed_save(name, value, **options):
        if name == "host:" + key:
            saves.append(options)
            owned_states.append(value)
        return save(name, value, **options)
    # Exercise the large-seek policy with this small semantic fixture. The
    # original threshold is independently exercised by the 16K resource matrix.
    with monkeypatch.context() as patch:
        patch.setattr(native_replay, "PRIVATE_REBASE_MIN_BARS", 2)
        patch.setattr(replay.results, "load", observed_load)
        patch.setattr(replay.results, "save", observed_save)
        replay.command(key, replay.get(key)["revision"], "seek", created["total"])
        final = settle(replay, key)
    assert encoded(final["result"]) == encoded(origin["result"])
    assert len(loads) == 1 and loads[0]["validation"] is True
    assert len(saves) == 1 and saves[0]["validated_base"] is not None
    assert owned_states == [{}]
    revision, base = host.native.db.execute("SELECT revision,base_revision FROM native_replay_result_bases WHERE id=?", ("host:" + key,)).fetchone()
    assert revision == base
    assert not host.native.db.execute("SELECT * FROM native_replay_result_deltas WHERE id=?", ("host:" + key,)).fetchall()
    assert replay._host_state(key)["cursor"] == created["total"]


def test_consumed_seek_checkpoint_rolls_back_when_public_result_write_fails(runtime, monkeypatch):
    import time
    from app.backtest import native_replay
    from app.backtest.native import encoded
    host, main = runtime
    origin = terminal(host.native, host.native.create(config(main, "BOOK_DEPTH", False,
        "LINEAR_PERP_ONE_WAY_V2"), "consume-before-public-save")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    replay = host.native.replay
    created = replay.create(origin["run_id"]); key = created["replay_id"]
    replay.command(key, created["revision"], "seek", 3)
    middle = settle(replay, key)
    before = encoded(replay._host_state(key))
    # Default callers retain their checkpoint. Only the exclusive seek job
    # opts into consuming its detached, newly produced state.
    caller_state = replay._host_state(key)
    with host.native.lock:
        replay._save(middle, external_state=caller_state)
    assert encoded(caller_state) == before
    save = replay.results.save
    owned_states, failed = [], []
    def fail_after_private_save(name, value, **options):
        if name == "host:" + key:
            result = save(name, value, **options)
            owned_states.append(value)
            return result
        if name == key and owned_states and not failed:
            assert owned_states == [{}]
            failed.append(True)
            raise RuntimeError("controlled public result write failure")
        return save(name, value, **options)
    with monkeypatch.context() as patch:
        patch.setattr(native_replay, "PRIVATE_REBASE_MIN_BARS", 2)
        patch.setattr(replay.results, "save", fail_after_private_save)
        replay.command(key, middle["revision"], "seek", created["total"])
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            with host.native.lock:
                if key not in replay.jobs: break
            time.sleep(.02)
        else: pytest.fail("failed public save did not stop the seek")
    record = replay.get(key)
    assert failed == [True] and owned_states == [{}]
    assert record["state"] == "FAILED" and "controlled public result write failure" in record["error"]["message"]
    assert record["cursor"] == middle["cursor"] and record["result"] == middle["result"]
    assert encoded(replay._host_state(key)) == before
    replay.command(key, record["revision"], "seek", created["total"])
    assert settle(replay, key)["result"] == origin["result"]


def test_changed_private_storage_after_resume_validation_cannot_publish_a_new_cursor(runtime, monkeypatch):
    import time
    from app.backtest import native_replay
    from app.backtest.native_replay_storage import checksum
    host, main = runtime
    origin = terminal(host.native, host.native.create(config(main, "BOOK_DEPTH", False,
        "LINEAR_PERP_ONE_WAY_V2"), "changed-base")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    replay = host.native.replay
    created = replay.create(origin["run_id"]); key = created["replay_id"]
    replay.command(key, created["revision"], "seek", 3)
    middle = settle(replay, key)
    worker = replay.workers[key]
    execute = worker.execute
    original = host.native.db.execute("SELECT payload,checksum FROM native_replay_result_bases WHERE id=?", ("host:" + key,)).fetchone()
    def changed_after_execution(*args, **options):
        value = execute(*args, **options)
        with host.native.lock, host.native.db:
            raw = '{"changed":true}'
            host.native.db.execute("UPDATE native_replay_result_bases SET payload=?,checksum=? WHERE id=?",
                                   (raw, checksum(raw), "host:" + key))
        return value
    with monkeypatch.context() as patch:
        patch.setattr(native_replay, "PRIVATE_REBASE_MIN_BARS", 2)
        patch.setattr(worker, "execute", changed_after_execution)
        replay.command(key, middle["revision"], "seek", created["total"])
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            with host.native.lock:
                if key not in replay.jobs: break
            time.sleep(.02)
        else: pytest.fail("changed-base replay did not stop")
    failed = replay.get(key)
    assert failed["state"] == "FAILED" and "checksum changed" in failed["error"]["message"]
    assert failed["cursor"] == middle["cursor"] and failed["result"] == middle["result"]
    # Repair only the deliberately damaged test row, then prove retry recovers
    # from the original committed account instead of the rejected new state.
    with host.native.lock, host.native.db:
        host.native.db.execute("UPDATE native_replay_result_bases SET payload=?,checksum=? WHERE id=?",
                               (*original, "host:" + key))
    replay.command(key, failed["revision"], "seek", created["total"])
    assert settle(replay, key)["result"] == origin["result"]


@pytest.mark.parametrize("account",["LINEAR_PERP_ONE_WAY_V1","SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V2"])
@pytest.mark.parametrize("mode",MODES)
@pytest.mark.parametrize("callbacks",[False,True])
def test_actual_print_ticks_observe_partial_bars_and_settled_accounts_without_duplicate_fill_executions(runtime,account,mode,callbacks):
    host,main=runtime
    record=terminal(host.native,host.native.create(config(main,mode,callbacks,account),"physical-ticks")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    groups=result["raw_output"]["execution_schedule"]
    assert [len(group) for group in groups]==[5]*10
    assert [plot["values"] for plot in result["graphics"][:1]]==[list(range(5,51,5))]
    first=groups[0]
    assert [row["evaluation"]["bar"]["volume"] for row in first]==[25,50,75,100,100]
    assert [row["evaluation"]["account"]["position_size"] for row in first]==[0,1,0,0,0]
    assert [row["context"]["trigger"] for row in first]==["realtime_tick"]*4+["bar_close"]
    assert [row["context"]["is_new"] for row in first]==[True,False,False,False,False]
    assert all(row["context"]["bar_state"]=="realtime" for group in groups for row in group)
    assert [fill["event_time_ms"] for fill in result["trades"]]==[10000,20000]
    assert Decimal(result["position"]["position_qty"])==0


@pytest.mark.parametrize("mode",MODES)
def test_physical_tick_replay_reuses_or_reconstructs_the_exact_stream_without_rematching_history(runtime,monkeypatch,mode):
    host,main=runtime
    record=terminal(host.native,host.native.create(config(main,mode,True,"LINEAR_PERP_ONE_WAY_V2"),"tick-replay")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    def seek(target):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        state=settle(replay,key)
        assert state.get("error") is None,state
        return state
    first=seek(1)
    from app.simulation.trade_kernel import TradeSimulationKernel
    from app.simulation.book_kernel import BookAssistedKernel
    from app.simulation.depth_kernel import DepthQueueKernel
    from app.simulation.sampled_book_kernel import SampledBookKernel
    cls=dict(TRADE_TAPE=TradeSimulationKernel,BOOK_ASSISTED=BookAssistedKernel,BOOK_DEPTH=DepthQueueKernel,BOOK_SAMPLED=SampledBookKernel)[mode]
    original_match,original_restore=cls._match,cls.restore
    restored=[]
    def track_restore(kernel,state):
        result=original_restore(kernel,state)
        restored.append((kernel,state["last_event"]["sequence"]))
        return result
    def match_only_later_source(kernel,event):
        cutoff=next((sequence for item,sequence in restored if item is kernel),None)
        if cutoff is not None: assert event.sequence>cutoff,"recovered account matched a recorded physical event"
        return original_match(kernel,event)
    monkeypatch.setattr(cls,"restore",track_restore)
    monkeypatch.setattr(cls,"_match",match_only_later_source)
    snapshot=replay.snapshot(key,first["revision"])["snapshots"][0]["snapshot_id"]
    third=seek(3)
    replay.restore(key,third["revision"],snapshot)
    assert seek(3)["result"]==third["result"]
    from app.backtest.native_replay import NativeReplay
    replay.shutdown()
    replay=host.native.replay=NativeReplay(host.native)
    assert seek(created["total"])["result"]==record["result"]


@pytest.mark.parametrize("mode,participation",[(mode,None) for mode in MODES]+[("TRADE_TAPE",.2)])
def test_cost_scenarios_and_funding_reexecute_the_same_observed_tick_clock(runtime,mode,participation):
    host,main=runtime
    value=config(main,mode,True,"LINEAR_PERP_ONE_WAY_V2")
    value["source"]=value["source"].replace('if strategy.position_size>0\n    strategy.close_all()\n','')
    value["cost_sensitivity_mode"]="AUTO"
    if participation is not None: value.update(execution_model_revision="EXECUTION_REALISM_V2",participation_rate=participation)
    record=terminal(host.native,host.native.create(value,"physical-tick-costs")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert result["cost_sensitivity"]["baseline_reexecution_verified"] is True
    assert result["position"]["funding_event_count"]==1 and Decimal(result["position"]["funding_paid"])<0
    group=result["raw_output"]["execution_schedule"][1]
    assert [row["evaluation"]["event_time_ms"] for row in group]==[60000,70000,80000,90000,119999]
    assert group[3]["evaluation"]["account"]["netprofit"]<group[2]["evaluation"]["account"]["netprofit"]


@pytest.mark.parametrize("mode,fresh",[(mode,False) for mode in MODES]+[("BOOK_SAMPLED",True)])
def test_simulated_closing_fill_chains_keep_one_confirmation_and_explicit_feedback(runtime,mode,fresh):
    host,main=runtime
    value=config(main,mode,True,"LINEAR_PERP_ONE_WAY_V2")
    value["source"]=value["source"].replace('calc_on_every_tick=true','calc_on_every_tick=true,process_orders_on_close=true')
    value["source"]=value["source"].replace('if n==1','if n==5 and barstate.isconfirmed')
    if fresh:
        # A same-ms sampled quote has no known cross-stream ordering. A quote
        # observed strictly before the close may supply its existing liquidity.
        quote=next(row for row in value["execution_data"]["events"] if row["role"]=="ORDER_BOOK" and row["time_ms"]==59999)
        quote["time_ms"]=quote["payload"]["sample_time_ms"]=59998
    record=terminal(host.native,host.native.create(value,"physical-tick-closing")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    group=result["raw_output"]["execution_schedule"][0]
    if mode=="BOOK_SAMPLED" and not fresh:
        assert [row["event_time_ms"] for row in result["trades"]]==[60000,70000]
        assert [row["context"]["trigger"] for row in group]==["realtime_tick"]*4+["bar_close"]
        return
    assert [row["event_time_ms"] for row in result["trades"]]==[59999,59999]
    assert [row["context"]["trigger"] for row in group]==["realtime_tick"]*4+["bar_close"]+["closing_fill"]*2
    assert [row["evaluation"]["account"]["position_size"] for row in group[-3:]]==[0,1,0]


def test_changed_observation_transcript_cannot_replace_the_committed_stream_journal(runtime):
    from app.backtest.errors import BacktestError
    from app.backtest.external_replay import validate_state
    from app.backtest.native import digest
    host,main=runtime
    record=terminal(host.native,host.native.create(config(main,"TRADE_TAPE",True,"LINEAR_PERP_ONE_WAY_V2"),"tick-journal")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    replay.command(key,created["revision"],"seek",1)
    assert settle(replay,key).get("error") is None
    with host.native.lock:
        state=deepcopy(replay._host_state(key))
        wire=deepcopy(replay._input(record["run_id"]))
    state["clock"]["groups"][0][0]["evaluation"]["account"]["equity"]+=1
    state["last_request"]["execution_schedule"]=deepcopy(state["clock"]["groups"])
    state["checksum"]=digest({key:value for key,value in state.items() if key!="checksum"})
    with pytest.raises(BacktestError,match="transcript differs"):
        validate_state(wire,state)


def test_requested_rows_follow_actual_print_times_and_confirmation_then_recover_the_same_feed(runtime):
    from tests.test_native_additional_inputs import additional
    host,main=runtime
    value=config(main,"TRADE_TAPE",False,"LINEAR_PERP_ONE_WAY_V2")
    value["contexts"]=[{**additional(host,"print-tick-foreign","ETHUSDT","2m",120000,[100,200,300,400,500]),
        "symbol":"BINANCE:ETHUSDT","timeframe":"2","metadata":{"priceTickSize":".25"}}]
    value["source"]+='''
r=request.security("BINANCE:ETHUSDT","2",close)
varip array<float> seen=array.new_float(5,na)
array.set(seen,(n-1)%5,r)
plot(array.get(seen,0))
plot(array.get(seen,1))
plot(array.get(seen,2))
plot(array.get(seen,3))
plot(array.get(seen,4))
'''
    record=terminal(host.native,host.native.create(value,"physical-tick-requested")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    plots=result["graphics"][-5:]
    assert [plot["values"] for plot in plots[:4]]==[[None,None,100,100,200,200,300,300,400,400]]*4
    assert plots[4]["values"]==[None,100,100,200,200,300,300,400,400,500]
    group=result["raw_output"]["execution_schedule"][1]
    assert [row["evaluation"]["request_observed_at_ms"] for row in group]==[60000,70000,80000,90000,119999]
    assert [len(row["evaluation"]["request_updates"]) for row in group]==[0,0,0,0,1]
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    for target in (1,5,created["total"]):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        state=settle(replay,key)
        assert state.get("error") is None,state
    assert state["result"]==record["result"]
