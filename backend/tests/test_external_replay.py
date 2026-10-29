"""Workbench replay must restore the Host account without matching old fills."""
import json
import os
from pathlib import Path

import pytest

from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_external_strategy_v2 import tape
from tests.test_native_replay import settle

PROFILES=[("BAR_APPROX",False), *[(mode,callbacks) for mode in
    ("TRADE_TAPE","BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED") for callbacks in (False,True)]]


def payload(main,mode,callbacks=False):
    source='''//@version=6
strategy("Host recovery",pyramiding=2%s)
varip bool sent=false
if barstate.isconfirmed and bar_index==0 and not sent
    sent:=true
    strategy.entry("A",strategy.long,qty=7,limit=11)
if barstate.isconfirmed and bar_index==3
    strategy.exit("X","A",stop=8,limit=40)
if not barstate.isconfirmed and strategy.position_size>6
    strategy.close("A",qty=1)
plot(strategy.position_size)
plot(strategy.netprofit)
''' % (",calc_on_order_fills=true" if callbacks else "")
    value={**main,"source":source,"language":"pine","execution_mode":"CANDLESCOPE",
        "execution_fidelity":mode,"fill_recalculation":callbacks,
        "host_settings":{"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":10}}
    if mode=="BAR_APPROX":
        return value
    data=tape()
    if mode.startswith("BOOK"):
        events=[]
        for index,row in enumerate(data["events"]):
            price=float(row["payload"]["price"])
            stamp=row["time_ms"]
            at=stamp if mode=="BOOK_ASSISTED" or not index else stamp-1
            book={"snapshot":True}
            if mode=="BOOK_ASSISTED":
                book.update(book_sequence=index+1,bid=str(price-.1),ask=str(price+.1))
            else:
                book.update(bids=[[str(price-.5),"5"]],asks=[[str(price+.5),"2"],[str(price+1),"3"]])
                if mode=="BOOK_DEPTH":
                    book.update(book_sequence=index+1,depth_complete=True)
                else:
                    book.update(sample_index=index+1,sample_time_ms=at if index else -1,
                        depth_complete=False,depth_scope="BOUNDED_SAMPLED")
                row["payload"]["aggressor_side"]="SELL"
            events.append({"time_ms":at,"role":"ORDER_BOOK","payload":book})
            events.append(row)
        data["events"]=events
    value["execution_data"]=data
    return value


def stable(result):
    return {key:value for key,value in result.items() if key not in {"report_hash","host_runtime_identity"}}


@pytest.mark.parametrize("mode,callbacks",PROFILES)
def test_external_endpoint_preserves_pre_replay_account_evidence(runtime,mode,callbacks):
    host,main=runtime
    origin=terminal(host.native,host.native.create(payload(main,mode,callbacks),"endpoint")["run_id"])
    assert origin["state"]=="COMPLETED",origin
    assert origin["result"]["account_authority"]=="candlescope"
    baseline=os.environ.get("PINE_REPLAY_BASELINE")
    if baseline:
        path=Path(baseline)/f"{mode}-{callbacks}.json"
        if os.environ.get("PINE_CAPTURE_REPLAY_BASELINE")=="1":
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(stable(origin["result"]),sort_keys=True,indent=2)+"\n",encoding="utf-8")
        else:
            assert stable(origin["result"])==json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode,callbacks",PROFILES)
def test_host_account_snapshot_resume_seek_and_restart_match_the_frozen_endpoint(runtime,monkeypatch,mode,callbacks):
    from app.backtest.native_replay import NativeReplay
    from app.simulation.kernel import SimulationKernel
    from app.simulation.trade_kernel import TradeSimulationKernel
    from app.simulation.book_kernel import BookAssistedKernel
    from app.simulation.depth_kernel import DepthQueueKernel
    from app.simulation.sampled_book_kernel import SampledBookKernel
    host,main=runtime
    origin=terminal(host.native,host.native.create(payload(main,mode,callbacks),"replay")["run_id"])
    assert origin["state"]=="COMPLETED",origin
    service=host.native.replay
    record=service.create(origin["run_id"])
    key=record["replay_id"]
    assert record["method"]=="HOST_ACCOUNT_CHECKPOINT" and record["result"] is None
    def seek(target):
        service.command(key,service.get(key)["revision"],"seek",target)
        return settle(service,key)
    first=seek(3)
    assert len(first["result"]["bars"])==3
    with host.native.lock:
        state=service._host_state(key)
    assert state["cursor"]==3 and state["orders"]["bindings"]
    assert state["kernel"]["account"]["position_qty"]==first["result"]["position"]["position_qty"]
    saved=service.snapshot(key,first["revision"])
    checkpoint=saved["snapshots"][0]["snapshot_id"]
    cls={"BAR_APPROX":SimulationKernel,"TRADE_TAPE":TradeSimulationKernel,"BOOK_ASSISTED":BookAssistedKernel,
        "BOOK_DEPTH":DepthQueueKernel,"BOOK_SAMPLED":SampledBookKernel}[mode]
    original=cls._match
    original_restore=cls.restore
    restored_kernels=[]
    def track_restore(kernel,state):
        result=original_restore(kernel,state)
        restored_kernels.append(kernel)
        return result
    monkeypatch.setattr(cls,"restore",track_restore)
    cutoff=180000
    matched=[]
    def only_future(kernel,event):
        # Restored accounts must never rematch their prefix. Independent cost
        # scenarios intentionally match the full input in fresh accounts.
        if cutoff is not None and any(kernel is item for item in restored_kernels):
            assert event.event_time_ms>=cutoff,"restored replay rematched an old market event"
            matched.append(event.event_time_ms)
        return original(kernel,event)
    monkeypatch.setattr(cls,"_match",only_future)
    fourth=seek(4)
    assert matched
    service.restore(key,fourth["revision"],checkpoint)
    assert service.get(key)["result"]==first["result"]
    assert seek(4)["result"]==fourth["result"]
    cutoff=None
    seek(1)
    assert seek(0)["result"] is None
    restored=service.restore(key,service.get(key)["revision"],checkpoint)
    assert restored["cursor"]==3
    process=service.workers[key].process
    service.shutdown()
    assert process.poll() is not None
    service=host.native.replay=NativeReplay(host.native)
    assert service.get(key)["result"]==first["result"]
    cutoff=180000
    final=seek(record["total"])
    assert final["result"]==origin["result"]
    assert final["state"]=="COMPLETED"
    assert "_externalStateRevision" not in service.get(key)
    assert "_externalStateRevision" not in service.list()[0]


@pytest.mark.parametrize("mode,callbacks",[("BAR_APPROX",False),("TRADE_TAPE",True)])
def test_spot_cash_and_inventory_restore_without_repeating_cash_transfers(runtime,monkeypatch,mode,callbacks):
    host,main=runtime
    test_host_account_snapshot_resume_seek_and_restart_match_the_frozen_endpoint(
        (host,{**main,"market_type":"spot"}),monkeypatch,mode,callbacks)


def prepared(runtime,mode="TRADE_TAPE",callbacks=True):
    host,main=runtime
    origin=terminal(host.native,host.native.create(payload(main,mode,callbacks),"prepared")["run_id"])
    assert origin["state"]=="COMPLETED",origin
    service=host.native.replay
    record=service.create(origin["run_id"])
    key=record["replay_id"]
    service.command(key,0,"seek",3)
    current=settle(service,key)
    return host,service,key,origin,current


@pytest.mark.parametrize("damage",["checksum","cursor","foreign_account","journal"])
def test_corrupt_or_mismatched_host_checkpoint_cannot_replace_the_current_view(runtime,damage):
    from app.backtest.native import digest,encoded
    host,service,key,origin,current=prepared(runtime)
    saved=service.snapshot(key,current["revision"])
    snapshot=saved["snapshots"][0]["snapshot_id"]
    service.command(key,saved["revision"],"step")
    advanced=settle(service,key)
    with host.native.lock:
        row=host.native.db.execute("SELECT record FROM native_replay_snapshots WHERE id=?",(snapshot,)).fetchone()
        value=json.loads(row[0])
        if damage=="checksum":
            value["external_state"]["kernel"]["account"]["quote_balance"]="999999"
            value["checksum"]=digest({k:v for k,v in value.items() if k!="checksum"})
        elif damage=="cursor":
            value["cursor"]=2
            value["checksum"]=digest({k:v for k,v in value.items() if k!="checksum"})
        elif damage=="foreign_account":
            value["external_state"]["input_hash"]="sha256:foreign"
            value["external_state"]["checksum"]=digest({k:v for k,v in value["external_state"].items() if k!="checksum"})
            value["checksum"]=digest({k:v for k,v in value.items() if k!="checksum"})
        else:
            host.native.db.execute("UPDATE native_replay_result_bases SET checksum='broken' WHERE id=?",("host:"+key,))
            service.results.cache.clear()
            host.native.db.commit()
            with pytest.raises(ValueError,match="checksum"):
                service._host_state(key)
            return
        host.native.db.execute("UPDATE native_replay_snapshots SET record=? WHERE id=?",(encoded(value),snapshot))
        host.native.db.commit()
    with pytest.raises(ValueError,match="IDENTITY_MISMATCH"):
        service.restore(key,advanced["revision"],snapshot)
    assert service.get(key)==advanced


def test_host_state_and_report_commit_together_or_both_roll_back(runtime,monkeypatch):
    host,service,key,origin,current=prepared(runtime)
    with host.native.lock:
        before=service._host_state(key)
    save=service.results.save
    fired=False
    def fail_after_host_write(name,value):
        nonlocal fired
        result=save(name,value)
        if name=="host:"+key and not fired:
            fired=True
            raise RuntimeError("injected host journal transaction failure")
        return result
    monkeypatch.setattr(service.results,"save",fail_after_host_write)
    service.command(key,current["revision"],"step")
    # A deliberate worker failure is a terminal state, so do not use settle's
    # successful-operation assertion here.
    import time
    end=time.monotonic()+15
    while time.monotonic()<end:
        with host.native.lock:
            if key not in service.jobs:
                break
        time.sleep(.02)
    failed=service.get(key)
    assert fired and failed["state"]=="FAILED"
    assert failed["cursor"]==current["cursor"] and failed["result"]==current["result"]
    with host.native.lock:
        assert service._host_state(key)==before
    service.command(key,failed["revision"],"seek",failed["total"])
    assert settle(service,key)["result"]==origin["result"]


def test_pause_discards_uncommitted_host_fills_and_preserves_the_durable_account(runtime):
    from threading import Event
    from app.backtest.native_replay import NativeReplay
    host,service,key,origin,current=prepared(runtime)
    with host.native.lock:
        before=service._host_state(key)
    entered,release=Event(),Event()
    runner=host.native.runner
    def slow(plugin,request,**kwargs):
        if len(request.get("bars",[]))==4:
            entered.set()
            release.wait(10)
        return runner(plugin,request,**kwargs)
    host.native.runner=slow
    service.command(key,current["revision"],"step")
    assert entered.wait(5)
    paused=service.command(key,service.get(key)["revision"],"pause")
    release.set()
    assert settle(service,key)["cursor"]==3
    with host.native.lock:
        assert service._host_state(key)==before
    saved=service.snapshot(key,paused["revision"])
    service.shutdown()
    host.native.runner=runner
    host.native.replay=service=NativeReplay(host.native)
    assert service.get(key)["snapshots"]==saved["snapshots"]
    service.command(key,saved["revision"],"play")
    assert settle(service,key)["result"]==origin["result"]


def test_http_replay_create_step_snapshot_restore_and_export_keep_host_authority(runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.backtests import router
    host,main=runtime
    origin=terminal(host.native,host.native.create(payload(main,"BAR_APPROX"),"http")["run_id"])
    assert origin["replay_contract"]=="candlescope.external-replay/1"
    app=FastAPI()
    app.state.backtest_runtime=host
    app.include_router(router)
    with TestClient(app) as client:
        response=client.post("/backtests/native/replays",json={"run_id":origin["run_id"]})
        assert response.status_code==200,response.text
        record=response.json()
        key=record["replay_id"]
        assert record["result"] is None and record["execution_mode"]=="CANDLESCOPE"
        response=client.post(f"/backtests/native/replays/{key}/commands",json={"revision":0,"action":"seek","target":3})
        assert response.status_code==200,response.text
        current=settle(host.native.replay,key)
        saved=client.post(f"/backtests/native/replays/{key}/commands",json={"revision":current["revision"],"action":"snapshot"}).json()
        client.post(f"/backtests/native/replays/{key}/commands",json={"revision":saved["revision"],"action":"step"})
        advanced=settle(host.native.replay,key)
        restored=client.post(f"/backtests/native/replays/{key}/commands",json={"revision":advanced["revision"],"action":"restore",
            "snapshot_id":saved["snapshots"][0]["snapshot_id"]})
        assert restored.status_code==200,restored.text
        assert restored.json()["result"]==current["result"]
        exported=client.get(f"/backtests/native/replays/{key}/export")
        assert exported.status_code==200
        assert exported.json()["result"]["account_authority"]=="candlescope"
        assert "_externalStateRevision" not in exported.json()


@pytest.mark.parametrize("failure",["transcript","checkpoint_budget"])
def test_recovery_failures_keep_the_previous_account_and_cursor(runtime,monkeypatch,failure):
    from app.backtest import external_replay,native
    host,service,key,origin,current=prepared(runtime)
    with host.native.lock:
        before=service._host_state(key)
    if failure=="transcript":
        worker=service.workers[key]
        request=worker.request
        def changed(*args,**kwargs):
            response=request(*args,**kwargs)
            response["graphics"]=[]
            return response
        monkeypatch.setattr(worker,"request",changed)
    else:
        make=external_replay.make_state
        def small(*args,**kwargs):
            old=native.MAX_BYTES
            try:
                native.MAX_BYTES=1
                return make(*args,**kwargs)
            finally:
                native.MAX_BYTES=old
        monkeypatch.setattr(external_replay,"make_state",small)
    service.command(key,current["revision"],"step")
    import time
    end=time.monotonic()+15
    while time.monotonic()<end:
        with host.native.lock:
            if key not in service.jobs:
                break
        time.sleep(.02)
    failed=service.get(key)
    assert failed["state"]=="FAILED",failed
    assert failed["cursor"]==3 and failed["result"]==current["result"]
    assert ("transcript changed" if failure=="transcript" else "64 MiB") in failed["error"]["message"]
    with host.native.lock:
        assert service._host_state(key)==before
    if failure=="checkpoint_budget":
        monkeypatch.setattr(external_replay,"make_state",make)
    service.command(key,failed["revision"],"seek",failed["total"])
    assert settle(service,key)["result"]==origin["result"]


@pytest.mark.parametrize("callbacks",[False,True])
def test_requested_inputs_and_imports_restore_without_revealing_future_context_rows(runtime,callbacks):
    from tests.test_native_additional_inputs import additional
    host,main=runtime
    value=payload(main,"TRADE_TAPE",callbacks)
    context={**additional(host,"replay-foreign","ETHUSDT","2m",120000,[100,200,300,400,500]),
        "symbol":"BINANCE:ETHUSDT","timeframe":"2"}
    value["contexts"]=[context]
    value["libraries"]={"local/Scale/1":'//@version=6\nlibrary("Scale")\nexport twice(float x)=>x*2'}
    value["source"]=value["source"].replace('varip bool sent=false','import local/Scale/1 as lib\nvarip bool sent=false')+\
        '\nremote=request.security("BINANCE:ETHUSDT","2",close)\nplot(lib.twice(remote))'
    origin=terminal(host.native,host.native.create(value,"requested")["run_id"])
    assert origin["state"]=="COMPLETED",origin
    service=host.native.replay
    record=service.create(origin["run_id"])
    key=record["replay_id"]
    service.command(key,0,"seek",2)
    first=settle(service,key)
    assert first["result"]["graphics"][-1]["values"]==[None,200]
    with host.native.lock:
        state=service._host_state(key)
    request=state["last_request"]
    assert len(request["bars"])==2
    if request.get("request_update_contract") == "candlescope.pine-request-updates/1":
        assert request["contexts"] and all(not context["bars"] for context in request["contexts"])
        observations=([dict(observed_at_ms=item["request_observed_at_ms"],updates=item["request_updates"])
                       for group in request["execution_passes"] for item in group]
                      if callbacks else request["request_updates"])
        updates=[item for observation in observations for item in observation["updates"]]
        assert [(item["bar"]["time"],item["bar"]["close"],item["available_at_ms"]) for item in updates]==[(0,100,119999)]
        assert all(item["available_at_ms"]<=observation["observed_at_ms"]<=119999
                   for observation in observations for item in observation["updates"])
        assert state["clock"]["request_feed"]["cursors"]==[1]
    else:
        contexts=([row for group in request["execution_passes"] for item in group for row in item.get("request_data",[])]
            if callbacks else request["contexts"])
        assert contexts and all(bar["time"]<120 for context in contexts for bar in context["bars"])
    saved=service.snapshot(key,first["revision"])
    service.command(key,saved["revision"],"seek",6)
    later=settle(service,key)
    service.restore(key,later["revision"],saved["snapshots"][0]["snapshot_id"])
    service.command(key,service.get(key)["revision"],"play")
    assert settle(service,key)["result"]==origin["result"]
