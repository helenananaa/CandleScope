"""Cost scenarios must rerun the actual Pine worker against independent accounts."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from threading import Event
import time

import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider
from app.backtest.errors import BacktestError
from app.market_dataset.snapshot import MarketEvent, sha256_hex
from app.simulation.execution_realism import BAR_PATH_SCENARIO
from tests.test_chart_pine_callbacks import service as service, pytestmark as pytestmark
from tests.test_backtest_dual_clock import _trade
from tests.test_native_backtests import runtime as runtime
from tests.test_chart_pine_orders import run_chart


FEE_BRANCH = '''//@version=6
strategy("Costs change decisions")
if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if bar_index==1
    strategy.exit("X","L",profit=2,loss=4)
    if strategy.netprofit < -0.0225
        strategy.order("fee_edge",strategy.long,qty=1)
'''


def config(service,source=FEE_BRANCH,mode="BAR_APPROX",**options):
    revision=service.create_strategy_revision({"language":"PINE_ENGINE","name":"Costs","source_text":source})
    value={"strategy_revision_id":revision["revision_id"],"dataset_id":"local-pine","data_epoch":"epoch-20261019",
        "snapshot_hash":"sha256:snapshot","fidelity_mode":mode,"source_event_kind":"BAR" if mode=="BAR_APPROX" else "AGG_TRADE",
        "start_time_ms":0,"end_time_ms":300000,"symbol":"BTCUSDT","interval":"1m","output_mode":"ORDER_INTENT",
        "parameters":{},"initial_balance":"10000","slippage_bps":"0","taker_fee_bps":"10","maker_fee_bps":"0",
        "price_tick":".5","execution_model_revision":"EXECUTION_REALISM_V2","participation_rate":".5"}
    if mode=="BAR_APPROX":
        value["bar_path_scenario"]=BAR_PATH_SCENARIO
    else:
        value.update(signal_clock="DERIVED_BAR_CLOSE",signal_interval="1m",execution_clock="NEXT_AGG_TRADE",
            bar_builder="TRADE_DERIVED_COMPLETE_BUCKETS_V1",timezone="UTC")
    value.update(options)
    service.smoke_strategy_revision(revision["revision_id"],value,now_ms=2)
    return value


def bars():
    return tuple(MarketEvent(i+1,(i+1)*60000-1,"BARS",dict(open_time_ms=i*60000,close_time_ms=(i+1)*60000-1,
        open="10",high="11",low="9",close="10",volume="100")) for i in range(5))


def execute(service,value,key="cost",events=None):
    record=service.create_run(value,idempotency_key=key,now_ms=3)
    fn=service.execute_bar_run if value["fidelity_mode"]=="BAR_APPROX" else service.execute_dual_clock_run
    return fn(record["run_id"],events=events or bars(),provider=PineEngineProvider(),now_ms=4,
        observation_market={"venue":"binance","symbol":"BTCUSDT"})


def scenarios(completed):
    matrix=completed["report"]["cost_sensitivity"]
    assert matrix["decision_source"]=="INDEPENDENT_PINE_HOST_REEXECUTION"
    assert matrix["baseline_reexecution_verified"] is True
    assert matrix["status"]=="COMPLETED"
    assert len(matrix["scenarios"])==5
    assert matrix["matrix_hash"]=="sha256:"+sha256_hex({k:v for k,v in matrix.items() if k!="matrix_hash"})
    for row in matrix["scenarios"]:
        assert row["scenario_hash"]=="sha256:"+sha256_hex({k:v for k,v in row.items() if k!="scenario_hash"})
    return {row["name"]:row for row in matrix["scenarios"]}


@pytest.mark.parametrize("inline",[True,False])
def test_fees_change_pine_decisions_and_relative_exits_use_each_actual_fill_basis(service,inline):
    service._colocated_worker=inline
    real=service._build_cost_sensitivity
    def verify_primary(*args,**kwargs):
        before=deepcopy(kwargs["provider"].snapshot())
        result=real(*args,**kwargs)
        assert kwargs["provider"].snapshot()==before
        return result
    service._build_cost_sensitivity=verify_primary
    value=config(service)
    result=execute(service,value)
    rows=scenarios(result)
    assert [float(fill["price"]) for fill in result["report"]["fills"]]==[10,11]
    assert rows["BASELINE"]["hashes"]["fill"]==result["result"]["fill_hash"]
    assert rows["BASELINE"]["hashes"]["decision"]==result["result"]["decision_hash"]
    assert rows["BASELINE"]["metrics"]["fill_count"]==2
    for name in ("COSTS_PLUS_25_PERCENT","COSTS_PLUS_50_PERCENT"):
        assert rows[name]["metrics"]["fill_count"]==3
        assert float(rows[name]["metrics"]["ending_position"])==1
        assert rows[name]["hashes"]["decision"]!=rows["BASELINE"]["hashes"]["decision"]
    assert rows["LATENCY_PLUS_ONE_TIER"]["status"]=="NOT_APPLICABLE_BAR_CLOCK"
    skipped=execute(service,{**value,"cost_sensitivity_mode":"SKIP"},key="skip")
    for key in ("decision_hash","fill_hash","ledger_hash"):
        assert result["result"][key]==skipped["result"][key]
    for key in ("fills","orders","ledger","equity_curve","pine_orders"):
        assert result["result"][key]==skipped["result"][key]
    assert result["result"]["report_hash"]!=skipped["result"]["report_hash"]
    assert len(service.repository.list_runs())==2


@pytest.mark.parametrize("warmup",[0,1])
def test_trade_cost_scenarios_recalculate_fill_callbacks_latency_and_partial_fills(service,warmup):
    source=f'''//@version=6
strategy("Causal costs",calc_on_order_fills=true)
if barstate.isconfirmed and bar_index=={warmup}
    strategy.entry("L",strategy.long,qty=2)
if not barstate.isconfirmed and strategy.position_size>0 and strategy.netprofit < -(strategy.position_avg_price * strategy.position_size * .0011)
    strategy.close_all()
'''
    trades=tuple(_trade(i+1,stamp,str(price),str(qty)) for i,(stamp,price,qty) in enumerate(
        ((1000,10,100),(60000,10,4),(70000,11,4),(120000,12,4),(180000,13,4),(240000,14,4))))
    result=execute(service,config(service,source,mode="AGG_TRADE_EXECUTION",warmup_bars=warmup),events=trades)
    rows=scenarios(result)
    assert rows["BASELINE"]["metrics"]["fill_count"]==1
    assert rows["BASELINE"]["pine_execution"]["fillCallbackCount"]==1
    for name in ("COSTS_PLUS_25_PERCENT","COSTS_PLUS_50_PERCENT"):
        assert rows[name]["metrics"]["fill_count"]==2
        assert rows[name]["pine_execution"]["fillCallbackCount"]==2
        assert float(rows[name]["metrics"]["ending_position"])==0
    down=rows["PARTICIPATION_DOWN_ONE_TIER"]
    assert down["metrics"]["fill_count"]==2
    assert down["pine_execution"]["fillCallbackCount"]==2
    assert float(down["metrics"]["ending_position"])==2
    assert rows["LATENCY_PLUS_ONE_TIER"]["status"]=="COMPLETED"
    assert rows["LATENCY_PLUS_ONE_TIER"]["hashes"]["fill"]!=rows["BASELINE"]["hashes"]["fill"]


def test_legacy_pine_targets_also_recalculate_against_each_cost_account(service):
    service.settings=replace(service.settings,python_scale_v1_enabled=True)
    source='''//@version=6
strategy("Target costs")
if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if strategy.netprofit < -.0225
    strategy.close("L")
'''
    result=execute(service,config(service,source,output_mode="TARGET_POSITION"))
    rows=scenarios(result)
    assert rows["BASELINE"]["metrics"]["fill_count"]==1
    assert rows["COSTS_PLUS_25_PERCENT"]["metrics"]["fill_count"]==2


@pytest.mark.parametrize("colocated",[True,False])
def test_actual_queued_pine_runs_publish_reexecuted_costs(runtime,monkeypatch,colocated):
    monkeypatch.setenv("BACKTEST_COLOCATED_BAR_ENABLED","1" if colocated else "0")
    host,main=runtime
    report=run_chart(host,main,FEE_BRANCH.split("\n",2)[2],execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate=".5",bar_path_scenario=BAR_PATH_SCENARIO,price_tick=".5",taker_fee_bps="10")
    rows=scenarios({"report":report})
    assert rows["BASELINE"]["metrics"]["fill_count"]==2
    assert rows["COSTS_PLUS_25_PERCENT"]["metrics"]["fill_count"]==3


@pytest.mark.parametrize("failure",["baseline","deadline","cancel","step_timeout"])
def test_scenario_failures_never_publish_a_matrix_or_leave_pine_workers(service,monkeypatch,failure):
    from app.backtest import pine_sensitivity as module
    created=[]
    released=Event()
    aborted=Event()
    def factory():
        fresh=PineEngineProvider()
        created.append(fresh)
        if failure=="step_timeout":
            step,abort=fresh.step,fresh.abort
            def wait(frame):
                released.wait(2)
                return step(frame)
            def stop():
                aborted.set()
                released.set()
                abort()
            fresh.step,fresh.abort=wait,stop
        return fresh
    monkeypatch.setattr(module,"PineEngineProvider",factory)
    if failure=="baseline":
        clone=module._clone_kernel
        def drift(*args,**kwargs):
            result=clone(*args,**kwargs)
            result.slippage_bps+=Decimal(1)
            return result
        monkeypatch.setattr(module,"_clone_kernel",drift)
    build=service._build_cost_sensitivity
    def controlled(*args,**kwargs):
        if failure=="deadline":
            kwargs["deadline"]=time.monotonic()-1
        if failure=="cancel":
            def cancelled():
                raise BacktestError("IDENTITY_MUTATION","controlled cancellation")
            kwargs["control"]=cancelled
        if failure=="step_timeout":
            service.settings=replace(service.settings,provider_step_timeout_ms=10)
        return build(*args,**kwargs)
    service._build_cost_sensitivity=controlled
    expected={"baseline":"PINE_SENSITIVITY_BASELINE_MISMATCH","deadline":"BUDGET_EXCEEDED",
        "cancel":"IDENTITY_MUTATION","step_timeout":"PROVIDER_TIMEOUT"}[failure]
    try:
        with pytest.raises((BacktestError,ValueError),match=expected):
            execute(service,config(service))
    finally:
        released.set()
    assert all(fresh.worker is None for fresh in created)
    if failure=="step_timeout":
        assert aborted.is_set() and len(created)==1
    assert service.repository.list_runs()[0]["state"]=="FAILED"


@pytest.mark.parametrize("account",["SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V2"])
def test_scenarios_preserve_spot_inventory_and_historical_contract_account_semantics(service,account):
    options={"account_model":account}
    events=bars()
    if account=="SPOT_CASH_V1":
        options["market_type"]="spot"
    else:
        from tests.test_backtest_account_v2_m4 import rules,event
        options.update(contract_data_mode="HISTORICAL_CONTRACT_V1",funding_mode="HISTORICAL_REQUIRED",leverage="10")
        bootstrap=rules(-2)
        events=(MarketEvent(1,-2,"INSTRUMENT_RULES",{**bootstrap.payload,"price_tick":".5"}),
            replace(event("MARK_INDEX",-1,mark_price="10"),sequence=2),
            *(replace(row,sequence=i+3) for i,row in enumerate(bars()[:4])),
            replace(event("FUNDING",240000,funding_rate=".001",period_id="period"),sequence=7),
            replace(bars()[-1],sequence=8))
    completed=execute(service,config(service,**options),events=events)
    rows=scenarios(completed)
    assert rows["BASELINE"]["metrics"]["fill_count"]==2, {key:completed["report"].get(key) for key in ("fills","orders","rejected_orders","pine_orders")}
    assert rows["COSTS_PLUS_25_PERCENT"]["metrics"]["fill_count"]==3


def test_partial_oca_checkpoint_recovery_reproduces_the_full_cost_matrix(service):
    source='''//@version=6
strategy("Recover causal costs",calc_on_order_fills=true)
if barstate.isconfirmed and bar_index==0
    strategy.order("A",strategy.long,qty=6,oca_name="g",oca_type=strategy.oca.reduce)
    strategy.order("B",strategy.long,qty=10,oca_name="g",oca_type=strategy.oca.reduce)
if not barstate.isconfirmed and strategy.position_size>0
    strategy.exit("X","A",profit=2)
'''
    value=config(service,source,mode="AGG_TRADE_EXECUTION",checkpoint_policy="INTERVAL",checkpoint_interval=1)
    trades=tuple(_trade(i+1,stamp,str(price),str(qty)) for i,(stamp,price,qty) in enumerate(
        ((1000,10,100),(60000,10,8),(70000,11,8),(80000,12,100),(90000,13,100),(120000,14,100),
         (180000,14,100),(240000,14,100))))
    def run(record):
        return service.execute_dual_clock_run(record["run_id"],events=trades,provider=PineEngineProvider(),now_ms=4,
            observation_market={"venue":"binance","symbol":"BTCUSDT"})
    baseline=run(service.create_run(value,idempotency_key="complete",now_ms=3))
    interrupted=service.create_run(value,idempotency_key="resume",now_ms=3)
    save=service.repository.save_checkpoint
    def interrupt(payload):
        result=save(payload)
        if payload["sequence"]==2:
            raise KeyboardInterrupt("durable partial OCA fill")
        return result
    service.repository.save_checkpoint=interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            run(interrupted)
    finally:
        service.repository.save_checkpoint=save
    assert service.requeue_interrupted_run(interrupted["run_id"],expected_generation=1,now_ms=8)
    resumed=run(interrupted)
    scenarios(resumed)
    assert resumed["report"]["cost_sensitivity"]==baseline["report"]["cost_sensitivity"]
    for key in ("decision_hash","fill_hash","ledger_hash","report_hash"):
        assert resumed["result"][key]==baseline["result"][key]
