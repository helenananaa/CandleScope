"""Installed-core defaults across chart/Workbench matching, costs and replay."""
from decimal import Decimal as D

import pytest

from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_chart_pine_callbacks import service as service
from tests.test_chart_pine_v2_bar import config as chart_config, execute, bars
from tests.test_pine_workbench_v2_bar import config as workbench_config
from tests.test_backtest_account_v2_m4 import rules
from tests.test_pine_v2_bar_kernel import numbered, mark
from tests.test_native_replay import settle

MODELS=["LINEAR_PERP_ONE_WAY_V1","SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V2"]


def source(kind):
    amount="70" if kind=="cash" else "0.7"
    return f'''//@version=6
strategy("Host defaults",initial_capital=1000000,default_qty_type=strategy.{kind},default_qty_value={amount},calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long)
if strategy.position_size>0
    strategy.exit("X","L",stop=9.5,limit=10.5)
plot(strategy.default_entry_qty(close))
plot(strategy.equity)
'''


def declaration(kind):
    return {"kind":kind,"value":"70" if kind=="cash" else "0.7"}


@pytest.mark.parametrize("model",MODELS)
@pytest.mark.parametrize("kind",["cash","percent_of_equity"])
def test_actual_chart_defaults_use_host_capital_and_preserve_partial_fill_callbacks(service,model,kind):
    rows=bars()
    if model=="LINEAR_PERP_ONE_WAY_V2":
        rows=numbered(rules(-2),mark(-1,10),*rows)
    value=chart_config(service,account=model,source=source(kind),taker_fee_bps="10")
    result=execute(service,value,"default-chart",rows)
    report=result["report"]
    assert [D(row["qty"]) for row in report["fills"]]==[5,2,3,4]
    assert report["strategy"]["pineExecution"]["defaultQuantity"]==declaration(kind)
    assert report["pine_orders"]["open_entries"]==[]
    assert report["cost_sensitivity"]["baseline_reexecution_verified"] is True


@pytest.mark.parametrize("model",MODELS)
@pytest.mark.parametrize("kind",["cash","percent_of_equity"])
def test_actual_workbench_defaults_are_frozen_reexecuted_and_replayable(runtime,model,kind):
    host,main=runtime
    value=workbench_config(main,model=model)
    value["source"]=source(kind)
    value["host_settings"]["taker_fee_bps"]=10
    value["context"]={**value["context"],"metadata":{"priceTickSize":"1/10","quantityPrecision":3}}
    record=terminal(host.native,host.native.create(value,"default-workbench")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    report=record["result"]
    assert [D(row["qty"]) for row in report["trades"]]==[5,2,3,4]
    assert report["raw_output"]["default_quantity"]==declaration(kind)
    assert report["cost_sensitivity"]["baseline_reexecution_verified"] is True
    assert D(report["position"]["position_qty"])==0
    if model=="LINEAR_PERP_ONE_WAY_V2" and kind=="percent_of_equity":
        replay=host.native.replay
        created=replay.create(record["run_id"])
        key=created["replay_id"]
        def seek(target):
            replay.command(key,replay.get(key)["revision"],"seek",target)
            state=settle(replay,key)
            assert state.get("error") is None,state
            return state
        prefix=seek(1)
        saved=replay.snapshot(key,prefix["revision"])["snapshots"][0]["snapshot_id"]
        endpoint=seek(created["total"])
        assert endpoint["result"]==report
        replay.restore(key,endpoint["revision"],saved)
        assert seek(created["total"])["result"]==report
