"""Real streamed Pine decisions and Host OHLC matching against native control."""
import json
import os
import subprocess
import threading
from decimal import Decimal

import pytest

from app.backtest.external_orders import ExternalOrders
from app.backtest.pine_history_tick_clock import HistoryTickClock
from app.backtest.pine_stream import PineStream
from app.backtest.pine_workbench import bar_event
from app.simulation.pine_bar_kernel import PineBarKernel
from app.simulation.pine_chart_kernel import PineChartBarKernel
from app.simulation.pine_v2_bar_kernel import PineV2BarKernel
from tests.test_pine_stream import runtime_for

pytestmark=pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"),reason="requires installed streaming runtime")
SOURCE='''//@version=6
strategy("vertices",calc_on_every_history_tick=true,calc_on_order_fills=true,initial_capital=1000)
varip int n=0
n+=1
varip array<float> seen=array.new_float(4,na)
i=(n-1)%4
array.set(seen,i,strategy.position_size)
if i==0
    strategy.entry("L",strategy.long,qty=1)
if i==1
    strategy.close_all()
plot(array.get(seen,0))
plot(array.get(seen,1))
plot(array.get(seen,2))
plot(array.get(seen,3))
plot(n)
plot(strategy.netprofit)
plot(ta.cum(volume))
'''


@pytest.mark.parametrize("kernel_type",[PineBarKernel,PineChartBarKernel,PineV2BarKernel])
def test_actual_stream_clock_matches_native_tick_observations_without_duplicate_fill_executions(kernel_type):
    runtime,wire=runtime_for("external_strategy")
    bars=[dict(time=i*60,open=100,high=110,low=80,close=105,volume=100) for i in range(2)]
    opening=dict(source=SOURCE,parameters={},context=dict(symbol="A",timeframe="1"),historical_plan=bars)
    frozen={**wire,**opening,"bars":bars,"interval":"1m"}
    cancel=threading.Event()
    stream=PineStream(runtime,wire,opening,cancel)
    kernel=kernel_type(initial_balance=Decimal(1000),slippage_bps=Decimal(0),taker_fee_bps=Decimal(0))
    orders=ExternalOrders(kernel,fidelity="PINE_BAR_PATH")
    clock=HistoryTickClock(stream,kernel,orders,frozen)
    events=[bar_event(frozen,i,i+1) for i in range(2)]
    callbacks=[]
    try:
        if kernel_type is PineBarKernel:
            for event in events:
                kernel.walk_bar(event,lambda _,event=event:clock.close(event),
                                on_vertex=lambda point,index,event=event:clock.vertex(event,point,index))
        else:
            kernel.run(events,lambda window,event:clock.close(event),
                       fill_callback=lambda *_:callbacks.append(True) or [],vertex_callback=clock.vertex)
        actual=clock.output()["raw_output"]
        control='import sys,json,pine_compat\nx=json.load(sys.stdin)\nb=[dict(b,time=b["time"]*1000) for b in x["bars"]]\nprint(json.dumps(pine_compat.compile_script(x["source"]).run(b,chart_symbol="A",chart_timeframe="1")))'
        expected=json.loads(subprocess.check_output([os.environ["NATIVE_TEST_PINE_PYTHON"],"-I","-c",control],
            input=json.dumps(dict(source=SOURCE,bars=bars)),text=True))
        assert [p["values"] for p in actual["plots"]]==[p["values"] for p in expected["plots"]]
        assert [len(group) for group in clock.groups]==[4,4] and callbacks==[]
        assert [(fill.price,fill.qty) for fill in kernel.fills]==[(100,1),(110,1),(100,1),(110,1)]
        assert kernel.account.position_qty==0 and kernel.account.equity()==1020
        assert stream.cursor==2 and len(clock.history)==4
        assert all(fill.reason=="MARKET_OBSERVATION_VERTEX" for fill in kernel.fills)
    finally:
        stream.close()
