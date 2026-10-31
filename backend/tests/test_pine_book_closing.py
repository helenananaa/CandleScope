"""Closing matching retains real quotes, exhausted depth and sample age."""
from decimal import Decimal

import pytest

from app.backtest.external_orders import ExternalOrders
from app.market_dataset.snapshot import MarketEvent
from app.simulation.book_kernel import BookAssistedKernel
from app.simulation.depth_kernel import DepthQueueKernel
from app.simulation.sampled_book_kernel import SampledBookKernel
from app.simulation.closing_tick import match_closing_tick
from tests.test_pine_closing_tick_kernel import bar
from tests.test_pine_risk_stops import intent


def make(kind,*,stamp=59000):
    kernel=kind(slippage_bps=Decimal(0),taker_fee_bps=Decimal(10))
    payload={"snapshot":True,"bids":[["9","5"]],"asks":[["11","2"],["12","3"]]}
    if kind is BookAssistedKernel:
        payload={"snapshot":True,"book_sequence":1,"bid":"9","ask":"11"}
    elif kind is SampledBookKernel:
        payload.update(sample_index=1,sample_time_ms=stamp,depth_complete=False,depth_scope="BOUNDED_SAMPLED")
    else:
        payload.update(book_sequence=1,depth_complete=True)
    kernel._apply_book(MarketEvent(1,stamp,"ORDER_BOOK",payload))
    kernel._last_event=MarketEvent(2,59998,"TRADES",{"price":"12","qty":"10"})
    kernel.account.mark=Decimal(12)
    orders=ExternalOrders(kernel,fidelity="TRADE_TAPE")
    orders.configure(4)
    return kernel,orders


def submit(kernel,orders,script_id,qty,**options):
    kernel._enqueue_many(orders.translate([intent(script_id,qty=qty,**options)],2),current_sequence=2)


@pytest.mark.parametrize("kind",[DepthQueueKernel,SampledBookKernel])
def test_closing_walk_does_not_recreate_consumed_depth_across_calls_or_restore(kind):
    kernel,orders=make(kind)
    submit(kernel,orders,"A",4)
    match_closing_tick(kernel,bar(),2)
    assert [(fill.price,fill.qty) for fill in kernel.fills]==[(11,2),(12,2)]
    submit(kernel,orders,"B",2)
    match_closing_tick(kernel,bar(),2)
    assert [fill.qty for fill in kernel.fills]==[2,2,1]
    assert kernel.account.position_qty==orders.owned()==5
    restored,allocation=make(kind)
    restored.restore(kernel.snapshot())
    allocation.restore(orders.snapshot())
    match_closing_tick(restored,bar(),2)
    assert len(restored.fills)==3 and restored.account.position_qty==5
    assert all(qty==0 for qty in restored.available["SELL"].values())
    assert kernel.fee_total==Decimal(".058")


def test_assisted_closing_uses_current_quote_and_remaining_bar_volume_proxy():
    kernel,orders=make(BookAssistedKernel)
    submit(kernel,orders,"A",7)
    match_closing_tick(kernel,bar(),2)
    submit(kernel,orders,"B",7)
    match_closing_tick(kernel,bar(),2)
    assert [fill.qty for fill in kernel.fills]==[7,3]
    assert all(fill.price==11 for fill in kernel.fills)
    match_closing_tick(kernel,bar(),2)
    assert len(kernel.fills)==2 and kernel.account.position_qty==10


@pytest.mark.parametrize("stamp,filled",[(57000,False),(59000,True),(59999,False),(60000,False)])
def test_sampled_closing_requires_a_prior_fresh_quote(stamp,filled):
    kernel,orders=make(SampledBookKernel,stamp=stamp)
    submit(kernel,orders,"A",1)
    match_closing_tick(kernel,bar(),2)
    assert len(kernel.fills)==int(filled)


@pytest.mark.parametrize("kind",[BookAssistedKernel,DepthQueueKernel,SampledBookKernel])
def test_closing_never_turns_full_bar_extremes_into_passive_prints(kind):
    kernel,orders=make(kind)
    submit(kernel,orders,"passive",1,limit=8)
    submit(kernel,orders,"stop",1,stop=15)
    match_closing_tick(kernel,bar(),2)
    assert kernel.fills==[]  # The revealed close is 12, despite bar high 20 / low 5.
