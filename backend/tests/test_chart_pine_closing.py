"""Installed Pine closing ticks through real Host accounts and workers."""
from decimal import Decimal
import json
from dataclasses import replace

import pytest

from tests.test_chart_pine_callbacks import service as service, pytestmark as pytestmark, RecordingProvider
from tests.test_pine_cost_sensitivity import config, execute, scenarios
from tests.test_chart_pine_orders import run_chart
from tests.test_native_backtests import runtime as runtime
from tests.test_backtest_dual_clock import _trade


SOURCE='''//@version=6
strategy("Closing",process_orders_on_close=true)
if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if bar_index==1
    strategy.close("L")
'''


@pytest.mark.parametrize("mode",["BAR_APPROX","AGG_TRADE_EXECUTION"])
def test_same_close_execution_is_disclosed_and_cost_scenarios_reexecute(service,mode):
    trades=tuple(_trade(i+1,stamp,str(price),"100") for i,(stamp,price) in enumerate(
        ((1000,10),(60000,20),(120000,30),(180000,40),(240000,50),(300000,60))))
    result=execute(service,config(service,SOURCE,mode=mode),events=trades if mode!="BAR_APPROX" else None)
    fills=result["report"]["fills"]
    assert [fill["event_time_ms"] for fill in fills]==[59999,119999]
    assert all(fill["source_event_kind"]=="SCRIPT_BAR_CLOSE" for fill in fills)
    report=result["report"]
    assert report["report_label"].endswith("_WITH_SIMULATED_CLOSE")
    assert report["fill_model"]["closing_tick"]["fill_count"]==2
    assert report["execution_assumptions"]["closing_tick"]["synthetic"] is True
    assert report["pine_orders"]["open_entries"]==[]
    rows=scenarios(result)
    assert rows["BASELINE"]["metrics"]["fill_count"]==2
    if mode!="BAR_APPROX":
        assert rows["LATENCY_PLUS_ONE_TIER"]["hashes"]["fill"]!=rows["BASELINE"]["hashes"]["fill"]


def test_actual_queued_bar_uses_close_without_an_extra_signal_bar(runtime):
    host,main=runtime
    report=run_chart(host,main,SOURCE.split("\n",2)[2],process_orders_on_close=True)
    assert [fill["event_time_ms"] for fill in report["fills"]]==[59999,119999]
    assert report["report_label"]=="APPROXIMATE_WITH_SIMULATED_CLOSE"
    assert report["fill_model"]["closing_tick"]["liquidity"]=="UNCAPPED"


def test_closing_fill_callbacks_share_the_tick_and_authoritative_account(service):
    source='''//@version=6
strategy("Close callback",process_orders_on_close=true,calc_on_order_fills=true)
varip int passes=0
passes+=1
if bar_index==0 and passes==1
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0
    strategy.close("L")
'''
    from tests.test_chart_pine_callbacks import payload, execute as callback_execute
    provider=RecordingProvider()
    run=service.create_run(payload(service,source),idempotency_key="closing-callback",now_ms=3)
    result=callback_execute(service,run,provider)
    assert [fill["event_time_ms"] for fill in result["report"]["fills"]]==[59999,59999]
    frames=provider.observations
    assert [f.event_time_ms for f in frames[:3]]==[59999]*3
    assert [Decimal(str(f.account_view["position_size"])) for f in frames[:3]]==[0,2,0]
    assert all(f.features["pineExecutionPass"]["confirmed"] for f in frames[:3])
    assert all(f.bar==frames[0].bar for f in frames[:3])
    assert result["report"]["strategy"]["pineExecution"]["closingFillCallbackCount"]==2
    assert result["report"]["pine_orders"]["open_entries"]==[]


def test_closed_fill_groups_recover(service):
    from tests.test_chart_pine_callbacks import payload, execute as callback_execute
    source=SOURCE.replace('process_orders_on_close=true','process_orders_on_close=true,calc_on_order_fills=true')
    # Guard entry creation with a varip flag so the confirmed fill callback does
    # not replace the same partially filled order.
    source=source.replace('if bar_index==0','varip bool sent=false\nif bar_index==0 and not sent\n    sent:=true')
    value=payload(service,source)
    baseline=callback_execute(service,service.create_run(value,idempotency_key="baseline",now_ms=3))
    run=service.create_run(value,idempotency_key="resume",now_ms=3)
    save=service.repository.save_checkpoint
    def interrupt(checkpoint):
        saved=save(checkpoint)
        if checkpoint["sequence"]==2:
            raise KeyboardInterrupt("durable closing fill group")
        return saved
    service.repository.save_checkpoint=interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            callback_execute(service,run)
    finally:
        service.repository.save_checkpoint=save
    checkpoint=service.repository.latest_checkpoint(run["run_id"])
    groups=json.loads(checkpoint["payload_json"])["provider"]["provider"]["execution_passes"]
    assert len(groups[0])==2 and all(row["confirmed"] for row in groups[0])
    assert service.requeue_interrupted_run(run["run_id"],expected_generation=1,now_ms=8)
    resumed=callback_execute(service,run)
    for field in ("fills","orders","pine_orders"):
        assert resumed["report"][field]==baseline["report"][field]
    for field in ("decision_hash","fill_hash","ledger_hash","report_hash"):
        assert resumed["result"][field]==baseline["result"][field]


def test_closing_oca_reduction_and_fill_callback_cost_baseline(service):
    source='''//@version=6
strategy("Closing OCA",process_orders_on_close=true,calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.order("A",strategy.long,qty=2,oca_name="g",oca_type=strategy.oca.reduce)
    strategy.order("B",strategy.long,qty=5,oca_name="g",oca_type=strategy.oca.reduce)
'''
    trades=tuple(_trade(i+1,stamp,"10","100") for i,stamp in enumerate((1000,60000,120000,180000,240000,300000)))
    result=execute(service,config(service,source,mode="AGG_TRADE_EXECUTION"),events=trades)
    assert [Decimal(fill["qty"]) for fill in result["report"]["fills"]]==[2,3]
    assert all(fill["event_time_ms"]==59999 for fill in result["report"]["fills"])
    assert scenarios(result)["BASELINE"]["pine_execution"]["closingFillCallbackCount"]==2


def test_process_close_private_flag_cannot_be_supplied_by_a_caller(service):
    value=config(service,SOURCE.replace(',process_orders_on_close=true',''))
    value["pine_process_on_close"]=True
    result=execute(service,value)
    assert result["report"]["fills"][0]["event_time_ms"]==119999
    assert result["report"]["report_label"]=="APPROXIMATE"


def test_closing_callback_can_leave_an_exit_for_the_next_real_print_when_capacity_is_used(service):
    source='''//@version=6
strategy("Close capacity",process_orders_on_close=true,calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0
    strategy.close("L")
'''
    trades=tuple(_trade(i+1,stamp,"10",str(qty)) for i,(stamp,qty) in enumerate(
        ((1000,4),(60000,100),(70000,100),(120000,100),(180000,100))))
    value=config(service,source,mode="AGG_TRADE_EXECUTION")
    result=execute(service,value,events=trades)
    assert [row["event_time_ms"] for row in result["report"]["fills"]]==[59999,60000]
    assert [row["source_event_kind"] for row in result["report"]["fills"]]==["SCRIPT_BAR_CLOSE","AGG_TRADE"]
    assert scenarios(result)["BASELINE"]["pine_execution"]["closingFillCallbackCount"]==1


def test_workbench_process_close_uses_negotiated_host_closing_execution(runtime):
    from tests.test_native_backtests import terminal
    host,main=runtime
    record=host.native.create({**main,"language":"pine","source":SOURCE,"execution_mode":"CANDLESCOPE",
        "host_settings":{"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}},"workbench-close")
    completed=terminal(host.native,record["run_id"])
    assert completed["state"]=="COMPLETED",completed.get("error")
    result=completed["result"]
    assert result["account_authority"]=="candlescope"
    assert [row["event_time_ms"] for row in result["trades"]]==[59999,119999]
    assert [float(row["price"]) for row in result["trades"]]==[10,10]
    assert all(row["reason"]=="PINE_BAR_CLOSE" for row in result["trades"])
    assert float(result["position"]["position_qty"])==0
    assert not result["raw_output"]["strategy_output"].get("strategy")


def test_bar_closing_mode_connects_v2_path_callbacks_and_shared_capacity(service):
    from app.simulation.execution_realism import PINE_BAR_PATH_SCENARIO
    value=config(service,SOURCE.replace("process_orders_on_close=true","process_orders_on_close=true,calc_on_order_fills=true"),
        bar_path_scenario=PINE_BAR_PATH_SCENARIO)
    result=execute(service,value)
    assert [row["event_time_ms"] for row in result["report"]["fills"]]==[59999,119999]
    assert result["report"]["fill_model"]["name"]=="PINE_OHLC_PATH_V2"
    assert result["report"]["strategy"]["pineExecution"]["closingFillCallbackCount"]==2


def test_legacy_target_positions_use_the_same_closing_contract(service):
    service.settings=replace(service.settings,python_scale_v1_enabled=True)
    result=execute(service,config(service,SOURCE,output_mode="TARGET_POSITION"))
    assert [row["event_time_ms"] for row in result["report"]["fills"]]==[59999,119999]
    assert scenarios(result)["BASELINE"]["metrics"]["fill_count"]==2
