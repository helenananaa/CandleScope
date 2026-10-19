"""A simulated close uses one revealed price and never invents tape liquidity."""
from decimal import Decimal

import pytest

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from app.simulation import SimulationKernel, DualClockSimulationKernel
from app.simulation.closing_tick import match_closing_tick
from app.backtest.pine_closing import ChartClosingTicks
from app.simulation.execution_realism import BAR_PATH_SCENARIO, EXECUTION_REALISM_V2
from tests.test_backtest_dual_clock import _trade


def bar():
    return MarketEvent(1, 59999, "BARS", dict(open_time_ms=0, close_time_ms=59999,
        open="10", high="20", low="5", close="12", volume="10"))


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("kind,limit,stop,filled", [
    ("MARKET", None, None, True), ("LIMIT", "13", None, True),
    ("LIMIT", "6", None, False), ("STOP", None, "13", False),
    ("STOP", None, "11", True), ("STOP_LIMIT", "13", "11", True),
    ("STOP_LIMIT", "10", "11", False)])
def test_only_the_close_price_can_trigger_new_orders(dual,kind,limit,stop,filled):
    kernel = DualClockSimulationKernel("1m",process_orders_on_close=True) if dual else SimulationKernel(process_orders_on_close=True,slippage_bps=Decimal(0))
    intent = {"side":"BUY","type":kind,"qty":"2"}
    if limit:
        intent["limit_price"] = limit
    if stop:
        intent["stop_price"] = stop
    events = (_trade(1,1000,"10","5"),_trade(2,59000,"12","5"),_trade(3,60000,"100","10")) if dual else (bar(),)
    # Do not let the boundary print obscure whether an order filled at close.
    if dual:
        def close(row,sequence):
            match_closing_tick(kernel.execution,row,sequence)
            for order in kernel.execution._working_orders():
                order.status="CANCELLED"
    else:
        close=ChartClosingTicks(kernel).process
    result=kernel.run(events,lambda *_:[intent],close_callback=close)
    assert len(result.fills)==int(filled)
    if filled:
        assert Decimal(result.fills[0]["price"])==12
        assert result.fills[0]["event_time_ms"]==59999
        assert result.fills[0]["reason"]=="PINE_BAR_CLOSE"


@pytest.mark.parametrize("dual",[False,True])
def test_closing_capacity_does_not_reuse_volume_and_snapshot_retains_pending_orders(dual):
    options=dict(process_orders_on_close=True,execution_model_revision=EXECUTION_REALISM_V2,
        participation_rate=Decimal(".5"),order_end_policy="KEEP_OPEN")
    if not dual:
        options["bar_path_scenario"]=BAR_PATH_SCENARIO
    factory=lambda: DualClockSimulationKernel("1m",**options) if dual else SimulationKernel(**options)
    kernel=factory()
    execution=getattr(kernel,"execution",kernel)
    def strategy(*_):
        return [{"side":"BUY","type":"MARKET","qty":"8"}]
    rows=(_trade(1,1000,"10","5"),_trade(2,59999,"12","5"),
        MarketEvent(3,60000,"MARK_INDEX",{"mark":"12"})) if dual else (bar(),)
    result=kernel.run(rows,strategy,close_callback=ChartClosingTicks(kernel).process)
    assert [Decimal(fill["qty"]) for fill in result.fills]==[5]
    assert result.fills[0]["source_event_kind"]=="SCRIPT_BAR_CLOSE"
    assert len(result.fills[0]["source_event_hash"])==71
    snapshot=kernel.snapshot()
    restored=factory()
    restored.restore(snapshot)
    assert restored.result().fill_hash==result.fill_hash
    restored_execution=getattr(restored,"execution",restored)
    assert restored_execution.orders[0].qty==3
    # Repeating the same tick has no remaining capacity.
    match_closing_tick(restored_execution,bar(),rows[-1].sequence)
    assert len(restored_execution.fills)==1
    assert execution.orders[0].qty==3
    with pytest.raises(MarketDatasetError,match="CHECKPOINT_CORRUPT"):
        (DualClockSimulationKernel("1m") if dual else SimulationKernel()).restore(snapshot)


@pytest.mark.parametrize("latency",[{"latency_ms":1},{"latency_events":1}])
def test_explicit_latency_still_prevents_same_close_fills(latency):
    kernel=DualClockSimulationKernel("1m",process_orders_on_close=True,
        execution_model_revision=EXECUTION_REALISM_V2,participation_rate=Decimal(1),**latency)
    result=kernel.run((_trade(1,1000,"10","100"),_trade(2,60000,"20","100")),
        lambda *_:[{"side":"BUY","type":"MARKET","qty":"1"}],
        close_callback=ChartClosingTicks(kernel).process)
    assert [fill["event_time_ms"] for fill in result.fills]==[60000]
    assert result.fills[0]["source_event_kind"]=="AGG_TRADE"


def test_preexisting_intrabar_fill_consumes_closing_capacity():
    kernel=SimulationKernel(process_orders_on_close=True,execution_model_revision=EXECUTION_REALISM_V2,
        participation_rate=Decimal(".5"),bar_path_scenario=BAR_PATH_SCENARIO)
    kernel._enqueue_many([{"side":"BUY","type":"MARKET","qty":"4"}],current_sequence=0)
    result=kernel.run((bar(),),lambda *_:[{"side":"BUY","type":"MARKET","qty":"4"}],
        close_callback=ChartClosingTicks(kernel).process)
    assert [Decimal(fill["qty"]) for fill in result.fills]==[4,1]
    assert result.fills[0]["source_event_kind"]=="BAR"
    assert result.fills[1]["source_event_kind"]=="SCRIPT_BAR_CLOSE"


def test_an_intrabar_callback_order_waits_until_a_later_closing_tick():
    other=DualClockSimulationKernel("1m",process_orders_on_close=True)
    other.execution._enqueue_many([{"side":"BUY","type":"MARKET","qty":"1"}],current_sequence=0)
    def callback(*_):
        return [{"side":"SELL","type":"MARKET","qty":"1","reduce_only":True}]
    result=other.run((_trade(1,1000,"10","100"),_trade(2,60000,"20","100")),lambda *_:[],
        fill_callback=callback,close_callback=ChartClosingTicks(other).process)
    assert [row["event_time_ms"] for row in result.fills]==[1000,59999]


def test_unbounded_closing_callbacks_fail_and_restore_the_execution_hooks():
    kernel=SimulationKernel(process_orders_on_close=True,slippage_bps=Decimal(0))
    original=kernel.execution_reporter
    kernel._last_event=bar()
    kernel._enqueue_many([{"side":"BUY","type":"MARKET","qty":"1"}],current_sequence=0)
    def again(_,tick):
        kernel._enqueue_many([{"side":"SELL" if kernel.account.position_qty else "BUY",
            "type":"MARKET","qty":"1"}],current_sequence=tick.sequence-1)
    with pytest.raises(MarketDatasetError,match="BUDGET_EXCEEDED"):
        match_closing_tick(kernel,bar(),1,on_fill=again)
    assert kernel.execution_reporter is original
    assert kernel._last_event==bar()


def test_new_closing_mode_preserves_existing_positional_constructor_arguments():
    assert SimulationKernel("SPOT_CASH_V1").account_model=="SPOT_CASH_V1"
    assert DualClockSimulationKernel("1m","REJECT").gap_policy=="REJECT"


def test_default_dual_clock_traces_physical_aggregate_events_truthfully():
    kernel=DualClockSimulationKernel("1m",execution_model_revision=EXECUTION_REALISM_V2,participation_rate=Decimal(1))
    result=kernel.run((_trade(1,1000,"10","100"),_trade(2,60000,"20","100")),
        lambda *_:[{"side":"BUY","type":"MARKET","qty":"1"}])
    assert result.fills[0]["source_event_kind"]=="AGG_TRADE"
    assert result.fills[0]["event_time_ms"]==60000
