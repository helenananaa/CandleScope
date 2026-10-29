import json
import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider
from app.backtest.strategy.protocol import StrategyProviderError
from app.backtest.strategy.workspace import compile_revision
from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_chart_pine_orders import run_chart
from tests.test_external_strategy_v2 import tape

BODY = '''if bar_index==0
    strategy.order("A",strategy.long,qty=5)
if bar_index==1
    strategy.order("B",strategy.long,qty=3)
if bar_index==2
    strategy.order("D",strategy.short,qty=3)
if bar_index==3
    strategy.order("R",strategy.short,qty=7)
if bar_index==4
    strategy.close("R")
'''


def test_queued_generic_orders_net_fixed_quantities_and_close_the_reverse_owner(runtime):
    host,main=runtime
    report=run_chart(host,main,BODY,pyramiding=1)
    assert [float(fill["qty"]) for fill in report["fills"]] == [5,3,3,7,2]
    assert report["pine_orders"]["open_entries"] == []
    assert report["pine_orders"]["fill_allocations"][3]["opened"] == {"entry_id":"R","qty":"2.0"}


@pytest.mark.parametrize("kind,arguments",[("MARKET",""),("LIMIT",",limit=11"),("STOP",",stop=11"),("STOP_LIMIT",",limit=21,stop=11")])
def test_queued_generic_order_prices_reach_the_real_chart_matcher(runtime,kind,arguments):
    host,main=runtime
    report=run_chart(host,main,f'if bar_index==0\n    strategy.order("L",strategy.long,qty=4{arguments})')
    assert report["orders"][0]["type"] == kind
    assert report["fills"] and report["pine_orders"]["open_entries"][0]["entry_id"] == "L"


@pytest.mark.parametrize("oca,expected",[("none",[2,5]),("cancel",[2]),("reduce",[2,3])])
def test_queued_oca_orders_apply_before_the_next_same_bar_fill(runtime,oca,expected):
    host,main=runtime
    body=f'''if bar_index==0
    strategy.order("A",strategy.long,qty=2,oca_name="g",oca_type=strategy.oca.{oca})
    strategy.order("B",strategy.long,qty=5,oca_name="g",oca_type=strategy.oca.{oca})
'''
    report=run_chart(host,main,body,pyramiding=1,prepared=oca=="reduce")
    assert [float(fill["qty"]) for fill in report["fills"]] == expected


@pytest.mark.parametrize("mode",["BAR_APPROX","TRADE_TAPE","BOOK_ASSISTED"])
def test_workbench_generic_orders_share_the_authoritative_allocator(runtime,mode):
    host,payload=runtime
    settings={"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}
    config={**payload,"source":'//@version=6\nstrategy("Orders",pyramiding=1)\n'+BODY,
        "execution_mode":"CANDLESCOPE","execution_fidelity":mode,"host_settings":settings}
    if mode != "BAR_APPROX":
        data=tape()
        if mode == "BOOK_ASSISTED":
            rows=[]
            for i,event in enumerate(data["events"]):
                price=event["payload"]["price"]
                rows.append({"time_ms":event["time_ms"],"role":"ORDER_BOOK","payload":{
                    "book_sequence":i+1,"snapshot":i==0,"bid":price,"ask":price}})
                rows.append(event)
            data["events"]=rows
        config["execution_data"]=data
    record=terminal(host.native,host.native.create(config,"generic-"+mode)["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    assert [float(fill["qty"]) for fill in record["result"]["trades"]] == [5,3,3,7,2]
    assert record["result"]["raw_output"]["entry_allocation"]["open_entries"] == []


@pytest.mark.parametrize("body",[BODY,'strategy.entry("A",strategy.long,oca_name="g",oca_type=strategy.oca.cancel)'])
def test_generic_or_oca_revision_cannot_silently_use_legacy_targets(body):
    revision=compile_revision({"language":"PINE_ENGINE","name":"Order mode","source_text":'//@version=6\nstrategy("Orders")\n'+body},now_ms=1)
    provider=PineEngineProvider()
    with pytest.raises(StrategyProviderError,match="FIDELITY_UNSUPPORTED"):
        provider.prepare({"source":json.loads(revision["compiled_json"])["executionSource"],"outputMode":"TARGET_POSITION"})
