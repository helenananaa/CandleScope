"""Account-ledger settlements become exactly one causal Host execution."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal

import pytest

from app.backtest.external_orders import ExternalOrders
from app.backtest.reports import build_round_trip_trades
from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from app.simulation.account_execution import publish_account_liquidation
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from app.simulation.execution_realism import EXECUTION_REALISM_V2, BAR_PATH_SCENARIO
from app.simulation.kernel import SimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from tests.test_backtest_account_v2_m4 import rules, event as financial_event
from tests.test_backtest_dual_clock import _trade
from tests.test_pine_risk_stops import event, intent


def make(tape=True, *, realism=False, **overrides):
    config = dict(account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="HISTORICAL_REQUIRED",
        initial_balance=Decimal(1000), leverage=Decimal(10), slippage_bps=Decimal(0))
    if realism:
        config.update(execution_model_revision=EXECUTION_REALISM_V2, participation_rate=Decimal(1))
        if not tape:
            config.update(bar_path_scenario=BAR_PATH_SCENARIO)
    config.update(overrides)
    kernel = (TradeSimulationKernel if tape else SimulationKernel)(**config)
    orders = ExternalOrders(kernel, fidelity="TRADE_TAPE" if tape else "BAR_APPROX")
    orders.configure(8)
    return kernel, orders


def prelude():
    return (rules(1), financial_event("MARK_INDEX", 2, mark_price="100", index_price="100"),
        financial_event("FUNDING", 3, period_id="p0", funding_rate="0"))


def roundtrip(kernel):
    return build_round_trip_trades(asdict(kernel.result())["fills"])


@pytest.mark.parametrize("tape,realism", [(False,False),(True,False),(False,True),(True,True)])
@pytest.mark.parametrize("short", [False,True])
@pytest.mark.parametrize("trigger", ["MARK_INDEX","FUNDING","INSTRUMENT_RULES"])
def test_account_settlement_closes_owned_lots_and_cancels_all_live_orders(tape,realism,short,trigger):
    kernel, orders = make(tape, realism=realism)
    # Source IDs are contiguous for BAR mode; market ordinals remain separate.
    rows = (*prelude(), event(4,100,tape=tape,time=1000), event(5,100,tape=tape,time=2000))
    def strategy(_, current):
        batch = ([{**intent("A",qty=20), "direction":"short" if short else "long"},
            {**intent("B",qty=30), "direction":"short" if short else "long"},
            {**intent("waiting",qty=1,limit=200 if short else 1), "direction":"short" if short else "long"}]
            if current.event_time_ms==1000 else [])
        return orders.translate(batch,current.sequence)
    kernel.run(rows,strategy)
    if trigger=="MARK_INDEX":
        settlement = financial_event(trigger,6,mark_price="120" if short else "80",index_price="100")
    elif trigger=="FUNDING":
        settlement = financial_event(trigger,6,period_id="p1",funding_rate="-.2" if short else ".2")
    else:
        settlement = rules(6,version="r2",tiers=[{"notional_floor":"0","notional_cap":"1000000",
            "maintenance_rate":".3","maintenance_deduction":"0"}])
    # Account data has the same causal timestamp domain as the market stream.
    settlement = MarketEvent(6,3000,settlement.role,settlement.payload)
    result = kernel.run((settlement,),strategy)
    assert kernel.account.position_qty==orders.owned()==0
    assert [float(row.qty) for row in kernel.fills]==[20,30,50]
    assert kernel.fills[-1].position_before==(-50 if short else 50)
    assert all(row.status not in {"OPEN","PARTIAL"} for row in kernel.orders)
    assert kernel.account.frozen_order_margin==0
    assert orders.bindings[kernel.fills[-1].order_id][1]=="liquidation"
    closed = orders.allocations[-1]["closed"]
    assert [(row["entry_id"],float(row["qty"])) for row in closed]==[("A",20),("B",30)]
    assert len(roundtrip(kernel))==2
    assert sum(Decimal(row["net_pnl"]) for row in roundtrip(kernel))==kernel.account.cumulative_realized_pnl
    receipt = result.fills[-1]["account_liquidation"]
    assert receipt["trigger"]==trigger and receipt["ledger_entry_hash"]==kernel.account.ledger_entries[-1]["entry_hash"]
    assert result.fills[-1]["source_event_kind"]=="ACCOUNT_LIQUIDATION"
    assert Decimal(result.equity_curve[-1]["equity"])==kernel.account.equity()
    before = deepcopy(kernel.account.snapshot())
    for _ in range(3):
        publish_account_liquidation(kernel)
    assert len(kernel.fills)==3 and kernel.account.snapshot()==before
    assert orders.translate([intent("after",qty=1)],7)==[]
    saved, allocated = kernel.snapshot(), orders.snapshot()
    restored, ownership = make(tape,realism=realism)
    restored.restore(saved)
    ownership.restore(allocated)
    publish_account_liquidation(restored)
    assert asdict(restored.result())==asdict(kernel.result())


@pytest.mark.parametrize("tape", [False,True])
def test_one_fill_can_be_followed_by_immediate_maintenance_settlement(tape):
    kernel, orders = make(tape,realism=True)
    kernel._next_order_id=9  # Lexical order ord-10 must not precede its primary ord-9 fill.
    observations=[]
    orders.execution_reporter=lambda execution: observations.append(
        (execution["fill"]["position_after"],kernel.account.position_qty,orders.owned())) if execution.get("fill") else None
    # The order passed reservation at mark 100. Execution at 125 loses 1250
    # against the unchanged authoritative mark and settles at 100 immediately.
    kernel.run((*prelude(),event(4,100,tape=tape,time=1000),event(5,125,tape=tape,time=2000)),
        lambda _,current: orders.translate([intent("L",qty=50)] if current.event_time_ms==1000 else [],current.sequence))
    assert observations==[(50,50,50),(0,0,0)]
    assert [fill.reason for fill in kernel.fills]==["NEXT_PRINT" if tape else "NEXT_BAR_OPEN","ACCOUNT_LIQUIDATION"]
    assert kernel.fills[0].position_before==0 and kernel.fills[1].position_before==50
    assert kernel.account.cumulative_realized_pnl==-1250
    assert kernel.account.insolvency_state=="INSOLVENT"
    assert sum(Decimal(row["net_pnl"]) for row in roundtrip(kernel))==-1250
    assert roundtrip(kernel)[0]["entry_order_id"]=="ord-9" and roundtrip(kernel)[0]["exit_order_id"]=="ord-10"
    assert [row["kind"] for row in kernel.account.ledger_entries].count("FILL")==1
    assert [row["kind"] for row in kernel.account.ledger_entries].count("LIQUIDATION")==1


def dual():
    return DualClockSimulationKernel("1m",account_model="LINEAR_PERP_ONE_WAY_V2",
        initial_balance=Decimal(1000),leverage=Decimal(10),slippage_bps=Decimal(0))


@pytest.mark.parametrize("stamp,deferred", [(70000,False),(120000,True)])
def test_account_callbacks_use_observed_bars_and_deferred_queue_survives_restore(stamp,deferred):
    kernel = dual()
    orders = ExternalOrders(kernel.execution,fidelity="TRADE_TAPE")
    orders.configure(4)
    def strategy(_,bar):
        return orders.translate([intent("L",qty=50)] if bar.sequence==1 else [],bar.sequence)
    observations=[]
    def callback(source,bar):
        observations.append((source.event_time_ms,bar.event_time_ms,dict(bar.payload),orders.owned(),kernel.account.position_qty))
        return []
    rows=(*prelude()[:2],_trade(1,1000,"100","100"),_trade(2,60000,"100","100"),
        financial_event("MARK_INDEX",stamp,mark_price="80",index_price="80"))
    kernel.run(rows,strategy,fill_callback=callback)
    if deferred:
        assert len(observations)==1
        assert kernel.result().ledger["account_fill_callbacks"]["pending"]==[{"order_id":"ord-2","execution_time_ms":stamp}]
    else:
        assert observations[-1][0:2]==(stamp,stamp) and observations[-1][3:]==(0,0)
        assert observations[-1][2]["close"]=="100"  # Account mark is not a trade print.
    saved,allocated=kernel.snapshot(),orders.snapshot()
    resumed=dual()
    resumed.execution.restore(saved["execution"])
    restored_orders=ExternalOrders(resumed.execution,fidelity="TRADE_TAPE")
    restored_orders.restore(allocated)
    resumed.restore(saved)
    observed=[]
    def resumed_callback(source,bar):
        observed.append((source.event_time_ms,dict(bar.payload),restored_orders.owned(),resumed.account.position_qty))
        return []
    tail=(_trade(3,130000,"81","100"),_trade(4,180000,"82","100"))
    kernel.run(tail,strategy,fill_callback=callback)
    resumed.run(tail,lambda *_: [],fill_callback=resumed_callback)
    assert not resumed.result().ledger["account_fill_callbacks"]["pending"]
    assert resumed.result().ledger["account_fill_callbacks"]["delivered"]==1
    if deferred:
        assert observed[0][0]==130000 and observed[0][1]["close"]=="81"
        assert observed[0][2:]==(0,0)
        decision=resumed.decisions[-2] if resumed.decisions[-1].get("trigger")=="BAR_CLOSE" else resumed.decisions[-1]
        assert decision["execution_time_ms"]==stamp and decision["observation_deferred"]
    for field in ("fills","ledger","fill_hash","ledger_hash","report_hash"):
        assert getattr(resumed.result(),field)==getattr(kernel.result(),field)


@pytest.mark.parametrize("corruption", ["missing","amount","hash"])
def test_restore_rejects_missing_or_altered_settlement_proof(corruption):
    kernel,orders=make()
    kernel.run((*prelude(),event(1,100,tape=True,time=1000),event(2,100,tape=True,time=2000),
        financial_event("MARK_INDEX",3000,mark_price="80",index_price="80")),
        lambda _,row: orders.translate([intent("L",qty=50)] if row.event_time_ms==1000 else [],row.sequence))
    saved=kernel.snapshot()
    if corruption=="missing":
        saved.pop("account_execution_receipts")
    elif corruption=="amount":
        saved["fills"][-1]["qty"]="49"
    else:
        saved["account_execution_receipts"]["ord-2"]["ledger_entry_hash"]="sha256:fake"
    restored,_=make()
    with pytest.raises(MarketDatasetError,match="liquidation"):
        restored.restore(saved)


def test_fixed_funding_receipt_preserves_economic_and_observation_times():
    from app.backtest.pine_risk_stops import PineRiskStops
    from tests.test_pine_risk_stops import configuration,rule
    kernel,orders=make(funding_mode="FIXED_SCENARIO",funding_rate=Decimal(".2"),funding_interval_ms=1000)
    stops=PineRiskStops(orders,{})
    stops.configure(configuration(rule("max_drawdown",100,"percent_of_equity")))
    kernel.run((*prelude()[:2],event(1,100,tape=True,time=1000),event(2,100,tape=True,time=2000),
        event(3,100,tape=True,time=4500)),lambda _,row: orders.translate(
            [intent("L",qty=50)] if row.event_time_ms==1000 else [],row.sequence))
    assert kernel.account.cumulative_funding==-1000 and orders.owned()==0
    assert kernel.fills[-1].event_time_ms==3000
    assert kernel.result().fills[-1]["account_liquidation"]["event_time_ms"]==3000
    assert stops.state.trips[-1]["time_ms"]==4500  # First observation that reveals the scheduled debit.
    assert stops.blocked and not stops.flatten_requested


def test_partial_fill_then_liquidation_does_not_count_another_script_order():
    from app.backtest.pine_risk_stops import PineRiskStops
    from tests.test_pine_risk_stops import configuration,rule,CONTEXT
    kernel,orders=make(realism=True)
    stops=PineRiskStops(orders,CONTEXT)
    stops.configure(configuration(rule("max_intraday_filled_orders",2)))
    rows=(*prelude(),event(1,100,tape=True,time=1000),event(2,100,tape=True,time=2000,qty=40),
        financial_event("MARK_INDEX",3000,mark_price="75",index_price="75"))
    kernel.run(rows,lambda _,row: orders.translate([intent("L",qty=50)] if row.event_time_ms==1000 else [],row.sequence))
    assert [fill.qty for fill in kernel.fills]==[40,40]
    assert kernel.orders[0].status=="CANCELLED" and not stops.state.trips
    assert stops.blocked and orders.owned()==0


def test_compound_fill_callbacks_observe_primary_position_before_terminal_account():
    kernel=dual()
    orders=ExternalOrders(kernel.execution,fidelity="TRADE_TAPE")
    orders.configure(4)
    observed=[]
    kernel.run((*prelude()[:2],_trade(1,1000,"100","100"),_trade(2,60000,"125","100")),
        lambda _,bar: orders.translate([intent("L",qty=50)],bar.sequence),
        fill_callback=lambda source,bar: observed.append((kernel.account.position_qty,orders.owned(),bar.payload["close"])) or [])
    assert observed==[(50,50,"125"),(0,0,"125")]
    assert kernel.result().ledger["account_fill_callbacks"]["delivered"]==1
