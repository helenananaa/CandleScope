"""Actual worker annotations through Host matching, report and replay."""
from dataclasses import replace
from decimal import Decimal as D

import pytest

from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_chart_pine_callbacks import service as service
from tests.test_chart_pine_v2_bar import config as chart_config, execute, bars
from tests.test_pine_workbench_v2_bar import config as workbench_config
from tests.test_backtest_account_v2_m4 import rules
from tests.test_pine_v2_bar_kernel import numbered, mark
from tests.test_native_replay import settle

SOURCE = '''//@version=6
strategy("Annotations",calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=7,comment="开仓",alert_message="open {{strategy.order.id}}",disable_alert=true)
if strategy.position_size>0
    strategy.exit("X","L",stop=9.5,limit=10.5,comment="generic",comment_loss="止损",comment_profit="止盈",alert_message="fallback",alert_loss="stop fill",alert_profit="")
'''
MODELS=["LINEAR_PERP_ONE_WAY_V1","SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V2"]


def check(fills, role):
    roles=[role,role] if isinstance(role,str) else list(role)
    assert [D(row["qty"]) for row in fills]==[5,2,3,4]
    assert [row["pine_comment"] for row in fills]==["开仓","开仓"]+["止损" if leg=="loss" else "止盈" for leg in roles]
    assert [row["pine_fill_role"] for row in fills]==["entry","entry",*roles]
    assert [row["pine_alert_enabled"] for row in fills]==[False,False,True,True]
    assert [row["pine_alert_message"] for row in fills]==["open {{strategy.order.id}}"]*2+["stop fill" if leg=="loss" else "" for leg in roles]


@pytest.mark.parametrize("model,role",[(model,"loss") for model in MODELS]+[("LINEAR_PERP_ONE_WAY_V2","profit")])
def test_chart_fill_leg_metadata_uses_actual_orders_and_account(service,model,role):
    rows=bars()
    if role=="profit":
        rows=tuple(replace(row,payload={**row.payload,"low":"9.9"}) for row in rows)
    if model=="LINEAR_PERP_ONE_WAY_V2":
        rows=numbered(rules(-2),mark(-1,10),*rows)
    result=execute(service,chart_config(service,account=model,source=SOURCE),"annotations",rows)
    check(result["report"]["fills"],role)
    assert result["report"]["pine_orders"]["open_entries"]==[]


@pytest.mark.parametrize("model",MODELS)
def test_workbench_annotations_survive_saved_prefix_restore_and_full_report(runtime,model):
    host,main=runtime
    value=workbench_config(main,model=model)
    value["source"]=SOURCE
    run=terminal(host.native,host.native.create(value,"annotations")["run_id"])
    assert run["state"]=="COMPLETED",run.get("error")
    # This Workbench fixture changes its range on the final bar: the remaining
    # bracket fills its limit after the earlier partial stop. Check both legs.
    check(run["result"]["trades"],("loss","profit"))
    assert D(run["result"]["position"]["position_qty"])==0
    if model=="LINEAR_PERP_ONE_WAY_V2":
        replay=host.native.replay
        created=replay.create(run["run_id"])
        key=created["replay_id"]
        def seek(target):
            replay.command(key,replay.get(key)["revision"],"seek",target)
            state=settle(replay,key)
            assert state.get("error") is None,state
            return state
        prefix=seek(1)
        saved=replay.snapshot(key,prefix["revision"])["snapshots"][0]["snapshot_id"]
        endpoint=seek(created["total"])
        assert endpoint["result"]==run["result"]
        replay.restore(key,endpoint["revision"],saved)
        assert seek(created["total"])["result"]==run["result"]


def test_workbench_generic_order_partial_close_and_close_all_keep_their_own_annotations(runtime):
    host,main=runtime
    value=workbench_config(main)
    value["source"]='''//@version=6
strategy("Order annotations",calc_on_order_fills=true)
varip int seen=-1
if barstate.isconfirmed and seen!=bar_index
    seen:=bar_index
    if bar_index==0
        strategy.entry("L",strategy.long,qty=2,comment="entry")
    if bar_index==1
        strategy.order("G",strategy.long,qty=1,comment="generic")
    if bar_index==2
        strategy.close("L",qty=1,comment="partial close",disable_alert=true)
    if bar_index==3
        strategy.close_all(comment="all")
'''
    run=terminal(host.native,host.native.create(value,"all-annotation-commands")["run_id"])
    assert run["state"]=="COMPLETED",run.get("error")
    fills=run["result"]["trades"]
    assert [D(row["qty"]) for row in fills]==[2,1,1,2]
    assert [row["pine_comment"] for row in fills]==["entry","generic","partial close","all"]
    assert [row["pine_fill_role"] for row in fills]==["entry","order","close","close"]
    assert [row["pine_alert_enabled"] for row in fills]==[True,True,False,True]
    assert D(run["result"]["position"]["position_qty"])==0


def test_cancelled_unfilled_order_keeps_annotations_without_creating_financial_fills(runtime):
    host,main=runtime
    value=workbench_config(main)
    value["source"]='''//@version=6
strategy("Pending annotations",calc_on_order_fills=true)
if bar_index==0
    strategy.entry("P",strategy.long,qty=7,limit=1,comment="pending then cancelled",alert_message="pending fill")
if bar_index==2
    strategy.cancel("P")
'''
    run=terminal(host.native,host.native.create(value,"cancelled-annotation")["run_id"])
    assert run["state"]=="COMPLETED",run.get("error")
    assert run["result"]["trades"]==[]
    assert run["result"]["orders"],run["result"]["diagnostics"]
    order=run["result"]["orders"][0]
    assert order["status"]=="CANCELLED"
    assert order["pine_comment"]=="pending then cancelled"
    assert order["pine_alert_message"]=="pending fill"
    assert "pine_fill_role" not in order
