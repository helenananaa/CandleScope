"""Actual V2 historical-account print/book admission and worker boundaries."""
from decimal import Decimal as D

import pytest
from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_external_replay import payload as base_payload
from tests.test_backtest_account_v2_m4 import rules


def config(main,mode,callbacks):
    value=base_payload(main,mode,callbacks)
    value.update(account_model="LINEAR_PERP_ONE_WAY_V2",leverage=10,
        funding_mode="HISTORICAL_REQUIRED",cost_sensitivity_mode="SKIP")
    opening=dict(rules(-2).payload,contract_multiplier="50")
    value["account_data"]={"symbol":"BTCUSDT","events":[
        dict(time_ms=-2,role="INSTRUMENT_RULES",payload=opening),
        dict(time_ms=-1,role="MARK_INDEX",payload={"mark_price":"12","index_price":"12"}),
        dict(time_ms=70000,role="MARK_INDEX",payload={"mark_price":"13","index_price":"13"}),
        dict(time_ms=90000,role="FUNDING",payload={"rate":".001","period_id":"p1"})],
        "provenance":{"fixture":"physical-account-independent"}}
    return value


@pytest.mark.parametrize("mode",["TRADE_TAPE","BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED"])
@pytest.mark.parametrize("callbacks",[False,True])
def test_actual_v2_print_book_uses_historical_marks_and_keeps_account_tape_outside_worker(runtime,monkeypatch,mode,callbacks):
    from app.backtest.native_session import SessionWorker
    host,main=runtime
    seen=[]
    original=SessionWorker.request
    def request(self,payload,*args,**kwargs):
        seen.append(set(payload))
        return original(self,payload,*args,**kwargs)
    monkeypatch.setattr(SessionWorker,"request",request)
    record=terminal(host.native,host.native.create(config(main,mode,callbacks),"v2-physical")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert result["account_model"]=="LINEAR_PERP_ONE_WAY_V2"
    assert result["trades"] and all(D(row["contract_multiplier"])==50 for row in result["trades"])
    position=result["position"]
    assert D(position["mark_price"])==13
    assert position["funding_event_count"]==1 and D(position["funding_paid"])<0
    assert D(position["equity"])==D(position["wallet_balance"])+D(position["unrealized_pnl"])
    assert result["raw_output"]["account_feedback"][-1]["equity"]==float(position["equity"])
    assert seen and all(not keys & {"account_events","account_provenance","pine_v2_settings","execution_events"} for keys in seen)
    disclosure=result["raw_output"]["pine_v2_print_account"]
    assert disclosure["mark_authority"]=="HISTORICAL_MARK_INDEX"
    assert disclosure["account_event_order"]=="ACCOUNT_BEFORE_MARKET_ON_TIES"


@pytest.mark.parametrize("mode",["TRADE_TAPE","BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED"])
@pytest.mark.parametrize("callbacks",[False,True])
def test_v2_physical_account_recovery_matches_complete_run_without_double_funding(runtime,mode,callbacks):
    from tests.test_native_replay import settle
    host,main=runtime
    record=terminal(host.native,host.native.create(config(main,mode,callbacks),"v2-physical-replay")["run_id"])
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
    snapshot=replay.snapshot(key,first["revision"])["snapshots"][0]["snapshot_id"]
    third=seek(3)
    replay.restore(key,third["revision"],snapshot)
    assert seek(3)["result"]==third["result"]
    assert seek(created["total"])["result"]==record["result"]


@pytest.mark.parametrize("stamp",[70000,120000])
def test_actual_account_liquidation_callback_waits_for_visible_print_without_inventing_price(runtime,stamp):
    host,main=runtime
    value=config(main,"TRADE_TAPE",True)
    value["host_settings"]["initial_balance"]=30
    value["funding_mode"]="OFF"
    value["source"]='//@version=6\nstrategy("physical liquidation",calc_on_order_fills=true)\nif bar_index==0 and barstate.isconfirmed\n    strategy.entry("L",strategy.long,qty=25)\nplot(strategy.position_size)\n'
    value["account_data"]["events"]=[
        dict(time_ms=-2,role="INSTRUMENT_RULES",payload=dict(rules(-2).payload)),
        dict(time_ms=-1,role="MARK_INDEX",payload={"mark_price":"10","index_price":"10"}),
        dict(time_ms=stamp,role="MARK_INDEX",payload={"mark_price":"8","index_price":"8"})]
    record=terminal(host.native,host.native.create(value,"v2-physical-liquidation")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert [D(row["position_after"]) for row in result["trades"]]==[D(25),D(0)]
    assert result["trades"][-1]["reason"]=="ACCOUNT_LIQUIDATION"
    assert result["trades"][-1]["event_time_ms"]==stamp
    passes=result["raw_output"]["execution_passes"][stamp//60000]
    liquidations=[row for row in passes if not row["confirmed"] and row["account"]["position_size"]==0]
    assert len(liquidations)==1
    observation=liquidations[0]
    assert observation["event_time_ms"]==stamp
    assert observation["bar"]["open"]==10
    assert observation["bar"]["close"] in {10,11}  # Physical quote, independent of account mark 8.
