"""Observed-print tick ordering, account feedback and durable continuation."""
from dataclasses import replace

import pytest

from app.market_dataset.snapshot import MarketDatasetError
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from tests.test_backtest_dual_clock import _trade


@pytest.mark.parametrize("stream",[False,True])
def test_ticks_see_settled_accounts_and_new_orders_wait_for_a_later_print(stream):
    tape=(_trade(1,1000,"10","100"),_trade(2,1000,"11","100"),
          _trade(3,60000,"12","100"),_trade(4,61000,"13","100"))
    def run(kernel,rows,seen):
        def tick(trade,forming):
            seen.append((trade.sequence,forming.payload["close"],forming.payload["volume"],str(kernel.account.position_qty)))
            if trade.sequence==1: return [{"side":"BUY","type":"MARKET","qty":"2"}]
            if trade.sequence==2: return [{"side":"SELL","type":"MARKET","qty":"2","reduce_only":True}]
            return []
        return kernel.run(rows,lambda *_:[],tick_callback=tick)
    baseline=DualClockSimulationKernel("1m",scale_stream_decisions=stream)
    seen=[]
    expected=run(baseline,tape,seen)
    assert seen==[(1,"10","100","0"),(2,"11","200","2"),(3,"12","100","0"),(4,"13","200","0")]
    assert [(fill["sequence"],str(fill["price"])) for fill in expected.fills]==[(2,"11"),(3,"12")]
    paused=DualClockSimulationKernel("1m",scale_stream_decisions=stream)
    run(paused,tape[:2],[])
    resumed=DualClockSimulationKernel("1m",scale_stream_decisions=stream)
    resumed.restore(paused.snapshot())
    result=run(resumed,tape[2:],[])
    for key in ("decision_hash","fill_hash","ledger_hash","report_hash"):
        assert getattr(result,key)==getattr(expected,key)


def test_v2_auxiliary_events_update_account_without_creating_extra_tick_observations():
    from tests.test_backtest_account_v2_m4 import rules,event
    tape=(replace(rules(-2),sequence=1),replace(event("MARK_INDEX",-1,mark_price="100"),sequence=2),
        replace(_trade(1,1000,"100","100"),sequence=3),
        replace(event("MARK_INDEX",2000,mark_price="110"),sequence=4),
        replace(event("FUNDING",2000,funding_rate=".01",period_id="p1"),sequence=5),
        replace(_trade(2,3000,"101","100"),sequence=6))
    kernel=DualClockSimulationKernel("1m",account_model="LINEAR_PERP_ONE_WAY_V2",funding_mode="HISTORICAL_REQUIRED")
    seen=[]
    def tick(trade,forming):
        seen.append((trade.sequence,str(kernel.account.mark),forming.payload["close"]))
        return []
    kernel.run(tape,lambda *_:[],tick_callback=tick)
    assert seen==[(3,"100","100"),(6,"110","101")]


def test_tick_and_fill_clocks_cannot_accidentally_double_evaluate_one_print():
    with pytest.raises(MarketDatasetError,match="one strategy clock"):
        DualClockSimulationKernel("1m").run((),lambda *_:[],tick_callback=lambda *_:[],fill_callback=lambda *_:[])
