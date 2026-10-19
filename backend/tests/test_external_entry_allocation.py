from decimal import Decimal
import pytest
from app.backtest.external_orders import ExternalOrders
from app.market_dataset.snapshot import MarketEvent
from app.simulation.kernel import SimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from app.simulation.book_kernel import BookAssistedKernel


def entry(id, direction="long", qty=1, **prices):
    return dict(action="entry", id=id, direction=direction, qty=qty, **prices)


def generic(id, direction="long", qty=1, **options):
    return {**entry(id,direction,qty,**options),"action":"order"}


@pytest.mark.parametrize("trailing",[False,True])
def test_relative_exit_admission_uses_observed_prices_instead_of_a_fake_unit_price(trailing):
    from tests.test_backtest_account_v2_m4 import rules,event
    kernel=TradeSimulationKernel(account_model="LINEAR_PERP_ONE_WAY_V2",leverage=Decimal(10))
    bootstrap=rules()
    kernel.account.apply(MarketEvent(1,0,"INSTRUMENT_RULES",{**bootstrap.payload,"price_tick":"2","min_notional":"50"}))
    kernel.account.apply(event("MARK_INDEX",0,mark_price="100"))
    orders=ExternalOrders(kernel,price_tick="2",fidelity="TRADE_TAPE")
    orders.configure(2)
    leg=dict(action="exit",id="X",from_entry="A",**(dict(trail_points=2,trail_offset=1) if trailing else dict(profit=2)))
    kernel._enqueue_many(orders.translate([entry("A",qty=2),leg],0),current_sequence=0)
    assert not kernel.rejected and len(kernel.orders)==2
    for i,price in enumerate((100,104,102),start=1):
        kernel._last_event=MarketEvent(i,i*1000,"TRADES",dict(price=str(price),qty="100"))
        kernel._match(kernel._last_event)
    assert [fill.qty for fill in kernel.fills]==[2,2]
    assert orders.owned()==0


@pytest.mark.parametrize("kernel_type", [SimulationKernel, TradeSimulationKernel, BookAssistedKernel])
def test_generic_orders_net_quantities_without_pyramiding_or_auto_reversal(kernel_type):
    kernel,orders = drive(kernel_type, {1:[generic("A",qty=5),generic("B",qty=3)],
        2:[generic("D","short",3)],3:[generic("R","short",7)],4:[dict(action="close",id="R")]},pyramiding=1)
    assert [fill.qty for fill in kernel.fills] == [5,3,3,7,2]
    assert orders.owned() == kernel.account.position_qty == 0
    assert orders.allocations[2]["closed"][0]["entry_id"] == "A"
    assert orders.allocations[3]["opened"] == {"entry_id":"R","qty":"2"}


@pytest.mark.parametrize("kernel_type", [SimulationKernel, TradeSimulationKernel, BookAssistedKernel])
@pytest.mark.parametrize("oca,expected", [("none",7),("cancel",2),("reduce",5)])
def test_generic_oca_groups_use_actual_filled_quantity(kernel_type,oca,expected):
    kernel,orders = drive(kernel_type,{1:[generic("A",qty=2,oca_name="g",oca_type=oca),
        generic("B",qty=5,oca_name="g",oca_type=oca)]},pyramiding=1)
    assert kernel.account.position_qty == orders.owned() == expected


def test_same_name_different_oca_types_are_independent_and_generic_pending_order_survives_close():
    kernel,orders = drive(SimulationKernel,{1:[generic("A",qty=2,oca_name="g",oca_type="cancel"),
        generic("B",qty=3,oca_name="g",oca_type="reduce"),generic("pending","short",5,limit=100)],
        2:[dict(action="close_all",id="")]},pyramiding=1)
    assert [fill.qty for fill in kernel.fills] == [2,3,5]
    assert orders.owned() == 0
    assert kernel.orders[2].status == "OPEN"


@pytest.mark.parametrize("oca",["cancel","reduce"])
@pytest.mark.parametrize("v2",[False,True])
def test_partial_generic_fill_applies_oca_before_next_print_and_recovers(oca,v2):
    import json
    def make():
        kernel=TradeSimulationKernel(slippage_bps=Decimal(0),account_model="LINEAR_PERP_ONE_WAY_V2" if v2 else "LINEAR_PERP_ONE_WAY_V1",leverage=Decimal(10))
        if v2:
            from tests.test_backtest_account_v2_m4 import rules,event
            kernel.account.apply(rules())
            kernel.account.apply(event("MARK_INDEX",2,mark_price="100"))
        orders=ExternalOrders(kernel)
        orders.configure(1)
        return kernel,orders
    kernel,orders=make()
    kernel._enqueue_many(orders.translate([generic("A",qty=4,oca_name="g",oca_type=oca),
        generic("B",qty=10,oca_name="g",oca_type=oca)],0),current_sequence=0)
    def match(kernel,sequence,qty):
        kernel._last_event=MarketEvent(sequence,sequence*1000,"TRADES",dict(price="10",qty=str(qty)))
        kernel.account.mark=Decimal(10)
        kernel._match(kernel._last_event)
    match(kernel,1,2)
    assert kernel.orders[1].status == ("CANCELLED" if oca == "cancel" else "OPEN")
    if oca == "reduce":
        assert kernel.orders[1].qty == 8
    restored,owners=make()
    restored.restore(json.loads(json.dumps(kernel.snapshot(),default=str)))
    owners.restore(json.loads(json.dumps(orders.snapshot())))
    for target in (kernel,restored):
        match(target,2,100)
    assert restored.snapshot() == kernel.snapshot()
    assert owners.snapshot() == orders.snapshot()
    assert owners.owned() == (4 if oca == "cancel" else 10)
    if v2:
        assert restored.account.frozen_order_margin == 0


def test_oca_reduced_reversal_keeps_the_gross_quantity_cap_after_restore():
    import json
    kernel=TradeSimulationKernel(slippage_bps=Decimal(0))
    orders=ExternalOrders(kernel)
    orders.configure(3)
    def match(sequence,qty):
        kernel._last_event=MarketEvent(sequence,sequence*1000,"TRADES",dict(price="10",qty=str(qty)))
        kernel.account.mark=Decimal(10)
        kernel._match(kernel._last_event)
    kernel._enqueue_many(orders.translate([generic("short","short",2)],0),current_sequence=0)
    match(1,2)
    kernel._enqueue_many(orders.translate([generic("A",qty=3,oca_name="g",oca_type="reduce"),
        entry("B",qty=3,oca_name="g",oca_type="reduce")],1),current_sequence=1)
    match(2,3)
    assert kernel.account.position_qty == 1
    assert kernel.orders[2].qty == 2
    restored=TradeSimulationKernel(slippage_bps=Decimal(0))
    owners=ExternalOrders(restored)
    restored.restore(json.loads(json.dumps(kernel.snapshot(),default=str)))
    owners.restore(json.loads(json.dumps(orders.snapshot())))
    restored._last_event=MarketEvent(3,3000,"TRADES",dict(price="10",qty="100"))
    restored._match(restored._last_event)
    assert restored.account.position_qty == owners.owned() == 3
    assert owners.owned("B") == 2


def drive(kernel_type, decisions, pyramiding=2, **settings):
    kernel = kernel_type(slippage_bps=Decimal(0), taker_fee_bps=Decimal(0))
    orders = ExternalOrders(kernel, **settings)
    orders.configure(pyramiding)
    for sequence in range(1, 7):
        if kernel_type is SimulationKernel:
            event = MarketEvent(sequence, sequence*60000, "BARS", dict(open="10",high="11",low="9",close="10",volume="100"))
        else:
            event = MarketEvent(sequence, sequence*60000, "TRADES", dict(price="10",qty="100"))
            if kernel_type is BookAssistedKernel:
                kernel._apply_book(MarketEvent(sequence, sequence*60000, "ORDER_BOOK",
                    dict(book_sequence=sequence,snapshot=sequence == 1,bid="10",ask="10")))
        kernel._last_event = event
        kernel.account.mark = Decimal(10)
        kernel._match(event)
        orders.feedback()
        kernel._enqueue_many(orders.translate(decisions.get(sequence, []), sequence), current_sequence=sequence)
    return kernel, orders


@pytest.mark.parametrize("kernel_type", [SimulationKernel, TradeSimulationKernel, BookAssistedKernel])
def test_multiple_entries_partial_close_preserves_requested_owner(kernel_type):
    kernel, orders = drive(kernel_type, {
        1:[entry("A",qty=2),entry("B",qty=3)],
        2:[dict(action="close",id="B",qty=1)],
        3:[dict(action="close",id="A")],
    })
    assert kernel.account.position_qty == 2
    assert orders.owned("A") == 0 and orders.owned("B") == 2
    assert [row["closed"][0]["entry_id"] for row in orders.allocations if row["closed"]] == ["B","A"]
    assert [fill.qty for fill in kernel.fills] == [2,3,1,2]


@pytest.mark.parametrize("kernel_type", [SimulationKernel, TradeSimulationKernel, BookAssistedKernel])
def test_pending_reversal_uses_actual_position_at_fill(kernel_type):
    kernel, orders = drive(kernel_type, {1:[entry("A",qty=2),entry("B","short",qty=1)]})
    assert [fill.qty for fill in kernel.fills] == [2,3]
    assert kernel.account.position_qty == -1
    assert orders.owned("A") == 0 and orders.owned("B") == -1
    assert orders.allocations[1]["closed"] == [{"entry_id":"A","entry_order_id":"ord-1","qty":"2"}]


@pytest.mark.parametrize("kernel_type", [SimulationKernel, TradeSimulationKernel, BookAssistedKernel])
def test_pending_entries_cannot_bypass_pyramiding(kernel_type):
    kernel, orders = drive(kernel_type, {1:[entry("A"),entry("B")]}, pyramiding=1)
    assert len(kernel.fills) == 1
    assert kernel.orders[1].status == "CANCELLED"
    assert orders.owned() == 1


def test_unfilled_entry_bracket_cannot_close_a_different_owner():
    kernel, orders = drive(SimulationKernel, {
        1:[entry("A"),entry("B",limit=1),dict(action="exit",id="XB",from_entry="B",stop=11)],
        2:[dict(action="close",id="B")],
    })
    assert len(kernel.fills) == 1
    assert orders.owned("A") == 1
    assert kernel.orders[2].status == "OPEN"


@pytest.mark.parametrize("direction", ["long", "short"])
def test_tick_bracket_uses_fill_basis_and_worst_case_oco(direction):
    kernel, orders = drive(SimulationKernel, {
        1:[entry("A",direction),dict(action="exit",id="X",from_entry="A",profit=2,loss=2)],
    }, price_tick="0.5")
    assert [fill.price for fill in kernel.fills] == [10, 9 if direction == "long" else 11]
    assert kernel.ambiguity_count == 1
    assert orders.owned() == 0


def test_distances_require_explicit_tick_and_trailing_requires_prints():
    from app.backtest.errors import BacktestError
    with pytest.raises(BacktestError, match="price_tick"):
        drive(SimulationKernel, {1:[entry("A"),dict(action="exit",id="X",profit=2)]})
    with pytest.raises(BacktestError, match="trade events"):
        drive(SimulationKernel, {1:[entry("A"),dict(action="exit",id="X",trail_points=2,trail_offset=1)]}, price_tick="0.5")


@pytest.mark.parametrize("kernel_type", [SimulationKernel, TradeSimulationKernel, BookAssistedKernel])
def test_rejected_order_does_not_claim_the_next_actual_order_id(kernel_type):
    kernel = kernel_type(account_model="SPOT_CASH_V1", initial_balance=Decimal(100), slippage_bps=Decimal(0))
    observed = []
    kernel.execution_reporter = observed.append
    orders = ExternalOrders(kernel)
    orders.configure(2)
    kernel.account.mark = Decimal(10)
    kernel._last_event = MarketEvent(1, 60000, "BARS" if kernel_type is SimulationKernel else "TRADES",
        dict(open="10", high="11", low="9", close="10", volume="100", price="10", qty="100"))
    kernel._enqueue_many(orders.translate([entry("unfunded", qty=1000000), entry("B", qty=2)], 1), current_sequence=1)
    assert len(kernel.rejected) == 1
    assert orders.bindings == {"ord-1": ("B", "entry")}
    assert not orders.staged_bindings
    assert len(observed) == 2 and observed[1]["order"]["order_id"] == "ord-1"


def test_pending_submission_tokens_survive_snapshot_before_kernel_admission():
    import json
    original, restored_kernel = SimulationKernel(), SimulationKernel()
    orders, restored = ExternalOrders(original), ExternalOrders(restored_kernel)
    orders.configure(2)
    intents = orders.translate([entry("B", qty=2)], 1)
    restored.restore(json.loads(json.dumps(orders.snapshot())))
    restored_kernel._enqueue_many(intents, current_sequence=1)
    assert restored.bindings == {"ord-1": ("B", "entry")}
    assert not restored.staged_bindings


@pytest.mark.parametrize("kernel_type", [TradeSimulationKernel, BookAssistedKernel])
@pytest.mark.parametrize("direction", [1,-1])
def test_trailing_watermark_survives_replace_and_partial_trigger(kernel_type, direction):
    kernel = kernel_type(slippage_bps=Decimal(0), taker_fee_bps=Decimal(0))
    orders = ExternalOrders(kernel, price_tick="0.5", fidelity="TRADE_TAPE")
    orders.configure(2)
    # Entry at 10, activation at 11 (short: 9), advance to 12, trigger
    # partially at 11, then complete the triggered market order on a rebound.
    prices = [10,10,11,12,11,12]
    bracket = dict(action="exit",id="X",from_entry="A",trail_points=2,trail_offset=2)
    for seq, long_price in enumerate(prices, 1):
        price = Decimal(10+(long_price-10)*direction)
        event = MarketEvent(seq,seq*1000,"TRADES",dict(price=str(price),qty="1" if seq==5 else "100"))
        if kernel_type is BookAssistedKernel:
            kernel._apply_book(MarketEvent(seq,seq*1000,"ORDER_BOOK",dict(book_sequence=seq,snapshot=seq==1,bid=str(price),ask=str(price))))
        kernel._last_event=event
        kernel.account.mark=price
        kernel._match(event)
        intents = [entry("A","long" if direction==1 else "short",qty=2)] if seq==1 else [bracket] if seq in {2,4} else []
        kernel._enqueue_many(orders.translate(intents,seq),current_sequence=seq)
    assert [fill.sequence for fill in kernel.fills] == [2,5,6]
    assert [fill.qty for fill in kernel.fills] == [2,1,1]
    assert orders.owned() == 0
