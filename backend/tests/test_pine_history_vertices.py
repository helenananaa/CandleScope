"""Historical observations settle only their own market orders at that vertex."""
from decimal import Decimal

from app.simulation.pine_bar_kernel import PineBarKernel
from tests.test_pine_bar_kernel import bar, enqueue


def test_vertex_hook_ignores_crossings_and_market_feedback_is_visible_at_the_next_observation():
    kernel=PineBarKernel(slippage_bps=Decimal(0),taker_fee_bps=Decimal(0))
    observed=[]
    def observe(point,index):
        observed.append((index,Decimal(point.payload["price"]),kernel.account.position_qty))
        if index==0: enqueue(kernel,"MARKET")
        if index==1: enqueue(kernel,"MARKET","SELL",reduce_only=True)
        if index<3: kernel.match_observation_markets(point)
    kernel.walk_bar(bar(),lambda _:None,on_vertex=observe)
    assert observed==[(0,100,0),(1,110,1),(2,80,0),(3,105,0)]
    assert [(fill.price,fill.sequence,fill.reason) for fill in kernel.fills]==[
        (100,1,"MARKET_OBSERVATION_VERTEX"),(110,2,"MARKET_OBSERVATION_VERTEX")]
    assert all(order.eligible_after_sequence<=order.fill_sequence for order in kernel.orders)


def test_new_price_order_and_callback_market_do_not_gain_same_vertex_eligibility():
    kernel=PineBarKernel(slippage_bps=Decimal(0))
    def report(value):
        if value.get("fill") and len(kernel.fills)==1:
            enqueue(kernel,"MARKET","SELL",reduce_only=True)
    kernel.execution_reporter=report
    def observe(point,index):
        if index==0:
            enqueue(kernel,"MARKET")
            enqueue(kernel,"LIMIT",limit_price="109")
            kernel.match_observation_markets(point)
            assert len(kernel.fills)==1
    kernel.walk_bar(bar(),lambda _:None,on_vertex=observe)
    assert kernel.fills[0].price==100 and kernel.fills[0].sequence==1
    assert all(fill.sequence>1 for fill in kernel.fills[1:])


def test_final_observation_market_waits_for_the_next_open():
    kernel=PineBarKernel(slippage_bps=Decimal(0))
    def observe(point,index):
        if index==3: enqueue(kernel,"MARKET")
        else: kernel.match_observation_markets(point)
    kernel.walk_bar(bar(),lambda _:None,on_vertex=observe)
    assert kernel.fills==[]
    kernel.walk_bar(bar(open_=106,high=110,low=90,close=109,begin=60000),lambda _:None)
    assert kernel.fills[0].price==106 and kernel.fills[0].event_time_ms==60000


def test_v2_observation_markets_share_capacity_and_do_not_add_a_fill_execution():
    from tests.test_pine_v2_bar_kernel import kernel as v2_kernel, numbered
    from dataclasses import replace
    subject=v2_kernel(taker_fee_bps=Decimal(0))
    event=bar()
    event=replace(event,payload={**event.payload,"volume":"10"})
    callbacks=[]; seen=[]
    # Direct enqueue here allows a quantity of seven, independently of script allocation.
    def observe(source,point,index):
        seen.append(subject.account.position_qty)
        if index==0: subject._enqueue(dict(type="MARKET",side="BUY",qty="7"),current_sequence=point.sequence)
        if index<3: subject.match_observation_markets(point)
    subject.run(numbered(event),lambda *_:[],fill_callback=lambda *_:callbacks.append(True) or [],vertex_callback=observe)
    assert seen==[0,5,5,5] and callbacks==[]
    assert [fill.qty for fill in subject.fills]==[5] and subject._capacity_left==0
    assert subject.orders[0].qty==2 and subject.orders[0].status=="PARTIAL"
