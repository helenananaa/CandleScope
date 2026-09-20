from decimal import Decimal
import pytest
from app.market_dataset.snapshot import MarketEvent, MarketDatasetError
from app.simulation.depth_kernel import DepthQueueKernel
from app.backtest.external_orders import ExternalOrders


def book(seq=1, **kwargs):
    return MarketEvent(seq,seq*1000,"ORDER_BOOK",dict(book_sequence=seq,snapshot=True,depth_complete=True,
        bids=[["9","10"],["8","20"]],asks=[["10","2"],["11","3"]],**kwargs))


def setup():
    kernel=DepthQueueKernel(slippage_bps=Decimal(0),taker_fee_bps=Decimal(0))
    orders=ExternalOrders(kernel,fidelity="BOOK_DEPTH")
    orders.configure(4)
    kernel._apply_book(book())
    kernel.account.mark=Decimal(10)
    return kernel,orders


def trade(kernel,seq,price=9,qty=1,side="SELL"):
    event=MarketEvent(seq,seq*1000,"TRADES",dict(price=str(price),qty=str(qty),aggressor_side=side))
    kernel._last_event=event
    kernel.account.mark=Decimal(price)
    kernel._match(event)


def enqueue(kernel,orders,intents,seq=1):
    kernel._enqueue_many(orders.translate(intents,seq),current_sequence=seq)


def entry(id,qty,**kwargs):
    return dict(action="entry",id=id,direction="long",qty=qty,**kwargs)


def test_taker_walks_levels_and_repeated_snapshot_does_not_refill_capacity():
    kernel,orders=setup()
    enqueue(kernel,orders,[entry("A",7)])
    trade(kernel,2,10)
    assert [(fill.price,fill.qty) for fill in kernel.fills]==[(10,2),(11,3)]
    kernel._apply_book(book(2))
    trade(kernel,3,10)
    assert len(kernel.fills)==2
    kernel._apply_book(MarketEvent(4,4000,"ORDER_BOOK",dict(book_sequence=3,bids=[],asks=[["11","5"]])))
    trade(kernel,5,10)
    assert kernel.fills[-1].qty==2 and orders.owned("A")==7


def test_passive_fifo_shares_print_capacity_and_own_priority():
    kernel,orders=setup()
    enqueue(kernel,orders,[entry("A",2,limit=9),entry("B",2,limit=9)])
    trade(kernel,2,qty=11)
    assert [(fill.qty,fill.order_id) for fill in kernel.fills]==[(1,"ord-1")]
    trade(kernel,3,qty=2)
    assert [(fill.qty,fill.order_id) for fill in kernel.fills]==[(1,"ord-1"),(1,"ord-1"),(1,"ord-2")]
    assert orders.owned("A")==2 and orders.owned("B")==1


def test_cancelled_displayed_depth_does_not_advance_assumed_queue():
    kernel,orders=setup()
    enqueue(kernel,orders,[entry("A",1,limit=9)])
    trade(kernel,2,qty=1)
    kernel._apply_book(MarketEvent(3,3000,"ORDER_BOOK",dict(book_sequence=2,bids=[["9","1"]],asks=[])))
    trade(kernel,4,qty=1)
    assert not kernel.fills
    trade(kernel,5,qty=9)
    assert kernel.fills[-1].qty==1


def test_wrong_aggressor_does_not_consume_our_queue():
    kernel,orders=setup()
    enqueue(kernel,orders,[entry("A",1,limit=9)])
    trade(kernel,2,qty=100,side="BUY")
    assert not kernel.fills
    trade(kernel,3,qty=10)
    assert not kernel.fills


def test_bad_depth_chain_and_truncated_initial_input_fail_closed():
    kernel,_=setup()
    with pytest.raises(MarketDatasetError,match="gap"):
        kernel._apply_book(book(3))
    bad=book(); bad.payload["depth_complete"]=False
    with pytest.raises(MarketDatasetError,match="complete"):
        DepthQueueKernel()._apply_book(bad)


def test_marketable_limit_pays_taker_fee_and_stop_waits_for_trigger():
    kernel,orders=setup()
    kernel.taker_fee_bps=Decimal(10)
    kernel.maker_fee_bps=Decimal(1)
    enqueue(kernel,orders,[entry("A",1,limit=10),entry("B",1,stop=12)])
    trade(kernel,2,10)
    assert len(kernel.fills)==1 and kernel.fee_total==Decimal('.01')
    trade(kernel,3,12)
    assert len(kernel.fills)==2 and orders.owned("B")==1
    bad=book(); bad.payload["asks"]=[["8","1"]]
    with pytest.raises(MarketDatasetError,match="uncrossed"):
        DepthQueueKernel()._apply_book(bad)
