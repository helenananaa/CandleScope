from decimal import Decimal
import pytest
from app.backtest.external_orders import ExternalOrders
from app.market_dataset.snapshot import MarketEvent
from app.simulation.kernel import SimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from app.simulation.book_kernel import BookAssistedKernel


def entry(id, direction="long", qty=1, **prices):
    return dict(action="entry", id=id, direction=direction, qty=qty, **prices)


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
