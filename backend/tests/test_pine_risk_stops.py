from copy import deepcopy
from decimal import Decimal

import pytest

from app.backtest.errors import BacktestError
from app.backtest.external_orders import ExternalOrders
from app.backtest.pine_risk_stops import PineRiskStops, window_contract
from app.market_dataset.snapshot import MarketEvent
from app.simulation.kernel import SimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from tests.test_pine_entry_risk import configuration, intent

DAY = 86_400_000
CONTEXT = {"exchange": "binance", "market_type": "usdm", "interval": "1m", "fidelity_mode": "BAR_APPROX"}


def rule(name, value, kind=None):
    return name, {"value": value, **({"valueType": "strategy." + kind} if kind else {})}


def event(i, price, *, tape=False, qty=100, time=None):
    stamp = i*60000-1 if time is None else time
    if tape:
        return MarketEvent(i, stamp, "TRADES", {"price": str(price), "qty": str(qty),
            "source_event_kind": "AGG_TRADE", "source_sequence": i})
    return MarketEvent(i, stamp, "BARS", {"open_time_ms": (stamp//60000)*60000,
        "close_time_ms": stamp, **{name: str(price) for name in ("open", "high", "low", "close")}, "volume": str(qty)})


def make(*rules, tape=False, config=None):
    cls = TradeSimulationKernel if tape else SimulationKernel
    kernel = cls(initial_balance=Decimal(1000), slippage_bps=Decimal(0))
    orders = ExternalOrders(kernel, fidelity="TRADE_TAPE" if tape else "BAR_APPROX")
    orders.configure(8)
    controller = PineRiskStops(orders, CONTEXT if config is None else config)
    controller.configure(configuration(*rules))
    return kernel, orders, controller


def test_drawdown_observes_a_peak_without_resting_orders_cancels_then_matches_a_real_close():
    kernel, orders, stop = make(rule("max_drawdown", 100, "cash"))
    batches = {1: [intent("L", qty=2)], 3: [intent("pending", limit=50)],
        4: [intent("halted_generic", action="order")], 5: [intent("halted_entry")]}
    kernel.run([event(i, p) for i, p in enumerate((100, 100, 150, 90, 80), 1)],
        lambda _, e: orders.translate(batches.get(e.sequence, []), e.sequence))
    assert [fill.sequence for fill in kernel.fills] == [2, 5]
    assert [fill.qty for fill in kernel.fills] == [2, 2]
    assert kernel.orders[1].status == "CANCELLED"
    assert stop.state.peak == 1100 and Decimal(stop.state.trips[0]["equity"]) == 980
    assert not orders.lots and kernel.account.position_qty == 0
    assert stop.report()["blocked"] and not stop.report()["flatten_requested"]


def test_first_partial_fill_stops_later_same_print_orders_and_close_uses_only_future_capacity():
    kernel, orders, stop = make(rule("max_intraday_filled_orders", 1), tape=True)
    rows = [event(i, 100, tape=True, qty=q) for i, q in enumerate((100, ".5", ".25", ".25"), 1)]
    kernel.run(tuple(rows), lambda _, e: orders.translate(
        [intent("A", qty=1), intent("B", qty=2)] if e.sequence == 1 else [], e.sequence))
    assert [fill.sequence for fill in kernel.fills] == [2, 3, 4]
    assert [fill.qty for fill in kernel.fills] == [Decimal(".5"), Decimal(".25"), Decimal(".25")]
    assert [order.status for order in kernel.orders[:2]] == ["CANCELLED", "CANCELLED"]
    assert stop.state.filled_orders == {kernel.fills[0].order_id}
    assert kernel.account.position_qty == 0 and len(stop.actions) == 1


def test_window_reset_does_not_allow_new_entries_until_a_pending_risk_close_finishes():
    kernel, orders, stop = make(rule("max_intraday_loss", 100, "cash"), tape=True)
    rows = tuple(event(i, price, tape=True, time=stamp) for i, (stamp, price) in enumerate(
        ((1000,100),(2000,100),(3000,50),(DAY,50),(DAY+1000,50)), 1))
    def strategy(_, e):
        batch = [intent("L", qty=2)] if e.sequence == 1 else [intent("new_day", qty=1)] if e.sequence == 4 else []
        return orders.translate(batch, e.sequence)
    kernel.run(rows, strategy)
    assert [fill.sequence for fill in kernel.fills] == [2, 4, 5]
    assert [fill.qty for fill in kernel.fills] == [2, 2, 1]
    assert not stop.blocked and kernel.account.position_qty == 1
    assert len(stop.state.trips) == 1 and not stop.state.trips[0]["permanent"]
    # Restoring the new day's reduced equity must not replay a fresh initial-
    # equity daily stop or submit an extra liquidation during configuration.
    saved = (deepcopy(kernel.snapshot()), deepcopy(orders.snapshot()), deepcopy(stop.snapshot()))
    restored, allocation, manager = make(rule("max_intraday_loss", 100, "cash"), tape=True)
    restored.restore(saved[0])
    allocation.restore(saved[1])
    manager.restore(saved[2])
    assert restored.snapshot() == saved[0]
    assert manager.snapshot() == saved[2] and not manager.blocked


def test_consecutive_realized_loss_day_halts_on_the_new_day_without_a_script_calculation():
    kernel, orders, stop = make(rule("max_cons_loss_days", 1), tape=True)
    rows = tuple(event(i, price, tape=True, time=stamp) for i, (stamp, price) in enumerate(
        ((1000,100),(2000,100),(3000,90),(4000,90),(DAY,90),(DAY+1000,90)), 1))
    batches = {1: [intent("L", qty=2)], 3: [{"action": "close_all", "id": "C"}],
        4: [intent("pending", limit=80)], 5: [intent("forbidden_generic", action="order")]}
    kernel.run(rows, lambda _, e: orders.translate(batches.get(e.sequence, []), e.sequence))
    assert [fill.sequence for fill in kernel.fills] == [2, 4]
    assert stop.state.loss_days == 1 and stop.blocked
    assert stop.state.trips[0]["time_ms"] == DAY
    assert kernel.orders[-1].status == "CANCELLED" and stop.actions == []


def test_partial_forced_close_and_actual_lots_restore_without_rematching_the_prefix():
    rows = tuple(event(i, 100, tape=True, qty=q) for i, q in enumerate((100,".5",".25",".25"), 1))
    kernel, orders, stop = make(rule("max_intraday_filled_orders", 1), tape=True)
    kernel.run(rows[:2], lambda _, e: orders.translate([intent("L", qty=2)] if e.sequence == 1 else [], e.sequence))
    saved = (deepcopy(kernel.snapshot()), deepcopy(orders.snapshot()), deepcopy(stop.snapshot()))
    restored, allocation, manager = make(rule("max_intraday_filled_orders", 1), tape=True)
    restored.restore(saved[0])
    allocation.restore(saved[1])
    manager.restore(saved[2])
    assert len(restored.orders) == len(kernel.orders) == 2
    kernel.run(rows[2:], lambda *_: [])
    restored.run(rows[2:], lambda *_: [])
    assert restored.result() == kernel.result()
    assert allocation.snapshot() == orders.snapshot()
    assert manager.snapshot() == stop.snapshot()
    assert not manager.flatten_requested and len(restored.fills) == 3


def test_end_of_data_reports_a_real_unfilled_risk_close_and_residual_inventory():
    kernel, orders, stop = make(rule("max_intraday_filled_orders", 1), tape=True)
    kernel.run(tuple(event(i, 100, tape=True) for i in (1,2)), lambda _, e:
        orders.translate([intent("L", qty=2)] if e.sequence == 1 else [], e.sequence), finalize=True)
    assert kernel.account.position_qty == 2 and len(kernel.fills) == 1
    assert kernel.orders[-1].status.startswith("CANCELLED")
    assert stop.report()["flatten_requested"] and Decimal(stop.report()["residual_position"]) == 2


@pytest.mark.parametrize("context", [{}, {**CONTEXT, "exchange": "stock"}, {**CONTEXT, "interval": "1w"}])
def test_daily_loss_streak_requires_supported_calendar_and_sufficient_account_observations(context):
    with pytest.raises(BacktestError, match="FIDELITY_UNSUPPORTED"):
        make(rule("max_cons_loss_days", 2), config=context)


def test_multi_day_intraday_window_is_explicit_and_drawdown_needs_no_session_guess():
    assert window_contract({**CONTEXT, "interval": "1w"}, ["strategy.risk.max_intraday_loss"])["intraday_per_bar"]
    kernel, orders, stop = make(rule("max_drawdown", 100, "cash"), config={})
    assert stop.windows == {"policy": "NON_WINDOWED_V1"}


@pytest.mark.parametrize("account_event,threshold", [("MARK_INDEX", 15), ("FUNDING", 1)])
def test_v2_account_events_trip_without_trades_and_close_uses_the_matching_clock(account_event, threshold):
    from tests.test_backtest_account_v2_m4 import rules
    kernel = TradeSimulationKernel(account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="HISTORICAL_REQUIRED",
        initial_balance=Decimal(1000), leverage=Decimal(10), slippage_bps=Decimal(0))
    orders = ExternalOrders(kernel,fidelity="TRADE_TAPE")
    orders.configure(4)
    stop = PineRiskStops(orders,{})
    stop.configure(configuration(rule("max_drawdown",threshold,"cash")))
    def account(role, stamp, **data):
        return MarketEvent(stamp,stamp,role,data)
    bootstrap = [rules(1), account("MARK_INDEX",2,mark_price="100",index_price="100"),
        account("FUNDING",3,period_id="p0",funding_rate="0")]
    financial = (account("MARK_INDEX",3000,mark_price="90",index_price="90") if account_event=="MARK_INDEX"
        else account("FUNDING",3000,period_id="p1",funding_rate=".01"))
    rows = (*bootstrap,event(1,100,tape=True,time=1000),event(2,100,tape=True,time=2000),
        financial,event(3,90 if account_event=="MARK_INDEX" else 100,tape=True,time=4000))
    kernel.run(tuple(rows),lambda _, e: orders.translate([intent("L",qty=2)] if e.sequence==1 else [],e.sequence))
    assert [fill.sequence for fill in kernel.fills] == [2,3]
    assert stop.state.trips[0]["time_ms"] == 3000
    assert kernel.account.position_qty == 0 and not stop.flatten_requested


def test_risk_close_created_during_a_simulated_close_waits_for_a_new_matching_tick():
    from app.simulation.closing_tick import match_closing_tick
    kernel, orders, stop = make(rule("max_intraday_filled_orders",1),tape=True)
    kernel.run((event(1,100,tape=True,time=1000),),lambda _, e: orders.translate([intent("L",qty=2)],e.sequence))
    closing = event(1,100,time=59999)
    match_closing_tick(kernel,closing,1,on_fill=lambda *_: None)
    assert len(kernel.fills)==1 and kernel.account.position_qty==2
    assert stop.flatten_requested and kernel.orders[-1].status=="OPEN"
    kernel.run((event(2,100,tape=True,time=60000,qty=".5"),event(3,100,tape=True,time=70000,qty="1.5")),lambda *_: [])
    assert [fill.event_time_ms for fill in kernel.fills]==[59999,60000,70000]
    assert [fill.qty for fill in kernel.fills]==[2,Decimal(".5"),Decimal("1.5")]
    assert kernel.account.position_qty==0


def test_funding_first_event_in_a_new_session_counts_as_that_sessions_actual_loss():
    from tests.test_backtest_account_v2_m4 import rules
    kernel = TradeSimulationKernel(account_model="LINEAR_PERP_ONE_WAY_V2",funding_mode="HISTORICAL_REQUIRED",
        initial_balance=Decimal(1000),leverage=Decimal(10),slippage_bps=Decimal(0))
    orders = ExternalOrders(kernel,fidelity="TRADE_TAPE")
    orders.configure(4)
    stop = PineRiskStops(orders,CONTEXT)
    stop.configure(configuration(rule("max_intraday_loss",1,"cash")))
    rows = (rules(1),MarketEvent(2,2,"MARK_INDEX",{"mark_price":"100","index_price":"100"}),
        MarketEvent(3,3,"FUNDING",{"period_id":"p0","funding_rate":"0"}),
        event(1,100,tape=True,time=1000),event(2,100,tape=True,time=2000),
        MarketEvent(3000,DAY,"FUNDING",{"period_id":"p1","funding_rate":".01"}),
        event(3,100,tape=True,time=DAY+1000))
    kernel.run(rows,lambda _,e: orders.translate([intent("L",qty=2)] if e.sequence==1 else [],e.sequence))
    assert kernel.account.cumulative_funding == -2
    assert [fill.sequence for fill in kernel.fills] == [2,3]
    assert stop.state.trips[0]["time_ms"] == DAY
    assert Decimal(stop.state.trips[0]["intraday_peak"]) == 1000


@pytest.mark.parametrize("tape", [False,True])
def test_flat_permanent_halt_does_not_scan_completed_order_history_on_every_tick(tape):
    kernel, orders, stop = make(rule("max_drawdown",1,"cash"),tape=tape)
    rows = tuple(event(i,100 if i<=204 else 90,tape=tape) for i in range(1,207))
    def strategy(_, current):
        i=current.sequence
        batch = ([intent("round",qty=1)] if i%2 else [{"action":"close_all","id":"C"}]) if i<=200 else (
            [intent("last",qty=2)] if i==203 else [])
        return orders.translate(batch,i)
    kernel.run(rows,strategy)
    assert stop.blocked and kernel.account.position_qty==0 and len(kernel.orders)>=200
    class History(list):
        visited=0
        def __iter__(self):
            for row in super().__iter__():
                self.visited+=1
                yield row
    history=History(kernel.orders)
    kernel.orders=history
    # Rebuilding the derived active index once after replacing a history is
    # allowed; subsequent risk-only observations must remain bounded by live orders.
    tuple(kernel._live_orders() if hasattr(kernel,"_live_orders") else kernel._working_orders())
    history.visited=0
    for i in range(207,307):
        stop.observe_market(event(i,90,tape=tape))
    assert history.visited < len(history)


def test_automatic_v2_liquidation_cannot_publish_an_unreconciled_pine_allocation_report():
    from tests.test_backtest_account_v2_m4 import rules
    kernel = TradeSimulationKernel(account_model="LINEAR_PERP_ONE_WAY_V2",funding_mode="HISTORICAL_REQUIRED",
        initial_balance=Decimal(1000),leverage=Decimal(10),slippage_bps=Decimal(0))
    orders = ExternalOrders(kernel,fidelity="TRADE_TAPE")
    orders.configure(4)
    stop = PineRiskStops(orders,{})
    stop.configure(configuration(rule("max_drawdown",100,"percent_of_equity")))
    rows = (rules(1),MarketEvent(2,2,"MARK_INDEX",{"mark_price":"100","index_price":"100"}),
        MarketEvent(3,3,"FUNDING",{"period_id":"p0","funding_rate":"0"}),
        event(1,100,tape=True,time=1000),event(2,100,tape=True,time=2000),
        MarketEvent(3000,3000,"MARK_INDEX",{"mark_price":"80","index_price":"80"}))
    with pytest.raises(BacktestError,match="EXTERNAL_LIQUIDATION_RECEIPT_REQUIRED"):
        kernel.run(rows,lambda _,e: orders.translate([intent("L",qty=50)] if e.sequence==1 else [],e.sequence))
    assert kernel.account.position_qty==0 and orders.owned()==50
    assert kernel.account.liquidation_event is not None  # The actual account settlement is not fabricated or undone.
