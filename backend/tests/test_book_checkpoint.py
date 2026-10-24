import json
from copy import deepcopy
from decimal import Decimal

import pytest

from app.backtest.external_orders import ExternalOrders
from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from app.simulation.book_kernel import BookAssistedKernel
from app.simulation.depth_kernel import DepthQueueKernel
from app.simulation.sampled_book_kernel import SampledBookKernel
from tests.test_depth_queue import setup,enqueue,entry,trade,book
from tests import test_sampled_book as sampled


def restore(kernel,orders):
    copied=type(kernel)()
    bindings=ExternalOrders(copied,fidelity=orders.fidelity)
    copied.restore(json.loads(json.dumps(kernel.snapshot(),default=str)))
    bindings.restore(json.loads(json.dumps(orders.snapshot())))
    return copied,bindings


def test_depth_restore_keeps_consumed_liquidity_and_pending_quantity():
    kernel,orders=setup()
    enqueue(kernel,orders,[entry("A",7)])
    trade(kernel,2,10)
    copied,bindings=restore(kernel,orders)
    for target in (kernel,copied):
        target._apply_book(book(2))
        trade(target,3,10)
        assert len(target.fills)==2
        assert target.orders[0].qty==2
        target._apply_book(MarketEvent(4,4000,"ORDER_BOOK",dict(book_sequence=3,bids=[],asks=[["11","5"]])))
        trade(target,5,10)
    assert copied.result()==kernel.result()
    assert bindings.snapshot()==orders.snapshot()


def test_depth_restore_keeps_own_queue_priority_and_remaining_ahead():
    kernel,orders=setup()
    enqueue(kernel,orders,[entry("A",2,limit=9),entry("B",2,limit=9)])
    trade(kernel,2,qty=11)
    copied,bindings=restore(kernel,orders)
    for target in (kernel,copied):
        trade(target,3,qty=2)
        trade(target,4,qty=1)
    assert [(f.order_id,f.qty) for f in copied.fills]==[("ord-1",1),("ord-1",1),("ord-2",1),("ord-2",1)]
    assert copied.result()==kernel.result()
    assert bindings.snapshot()==orders.snapshot()


def test_sampled_restore_keeps_stale_time_and_exhausted_depth():
    kernel,orders=sampled.setup()
    sampled.enqueue(kernel,orders)
    sampled.trade(kernel)
    sampled.trade(kernel,4000,3)
    copied,bindings=restore(kernel,orders)
    for target in (kernel,copied):
        target._apply_book(sampled.book(2,5000))
        sampled.trade(target,5001,4)
        assert len(target.fills)==2
        target._apply_book(sampled.book(3,6000))
        sampled.trade(target,9000,5)
    assert copied.result()==kernel.result()
    assert copied.disclosure()==kernel.disclosure()
    assert bindings.snapshot()==orders.snapshot()


def test_assisted_restore_uses_the_last_visible_spread():
    kernel=BookAssistedKernel()
    orders=ExternalOrders(kernel,fidelity="BOOK_ASSISTED")
    kernel._apply_book(MarketEvent(1,1000,"ORDER_BOOK",dict(bid="9",ask="11")))
    kernel.account.mark=Decimal(10)
    orders.configure(1)
    enqueue(kernel,orders,[entry("A",2)])
    copied,bindings=restore(kernel,orders)
    for target in (kernel,copied):
        trade(target,2,10,2)
    assert copied.fills[0].price==11
    assert copied.result()==kernel.result()
    assert bindings.snapshot()==orders.snapshot()


@pytest.mark.parametrize("mutate",[
    lambda p:p["book_state"].update(fill_policy="another"),
    lambda p:p["book_state"]["available"]["SELL"][0].__setitem__(1,"999"),
    lambda p:p["book_state"]["depth"]["BUY"][0].__setitem__(0,"NaN"),
    lambda p:p["book_state"]["queues"].update(unknown=["BUY","9","1"]),
    lambda p:p.pop("book_state"),
])
def test_corrupt_depth_checkpoint_fails_before_applying_account_state(mutate):
    kernel,orders=setup()
    enqueue(kernel,orders,[entry("A",7)])
    trade(kernel,2,10)
    state=deepcopy(kernel.snapshot())
    mutate(state)
    copied=DepthQueueKernel()
    before=copied.snapshot()
    with pytest.raises(MarketDatasetError,match="CHECKPOINT_CORRUPT"):
        copied.restore(state)
    assert copied.snapshot()==before


def test_sample_age_policy_cannot_change_during_restore():
    kernel,_=sampled.setup()
    with pytest.raises(MarketDatasetError,match="CHECKPOINT_CORRUPT"):
        SampledBookKernel(max_age_ms=1).restore(kernel.snapshot())
