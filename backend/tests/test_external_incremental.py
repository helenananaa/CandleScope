"""Qualify versioned Pyne worker against real host accounts and source clocks."""
from decimal import Decimal as D
import threading
import time

import pytest

from app.backtest.native import invoke
from app.backtest.native_session import SessionWorker
from app.backtest.external import host_identity, run_external_host
from tests.test_native_strategy_plugins import plugin, pytestmark


SOURCE = '''def init(ctx):
    ctx.strategy.configure()
def on_bar(ctx, bar):
    r = "TEST?chart=renko&style=Traditional&param=1"
    ctx.plot("Brick", ctx.request.security(r, ctx.timeframe.period, "close"))
    ctx.plot("Equity", ctx.strategy.equity)
    if ctx.bar_index == 0:
        ctx.strategy.entry("too-big", ctx.strategy.long, qty=1000)
    if ctx.bar_index == 2:
        ctx.strategy.entry("short", ctx.strategy.short, qty=1)
    if ctx.bar_index == 20:
        ctx.strategy.entry("L", ctx.strategy.long, qty=1)
    if ctx.bar_index == 30:
        ctx.strategy.close("L")
'''


def prepared(source=SOURCE):
    runtime = plugin("pyne")
    runtime["command"][-1] = runtime["command"][-1].replace("native_strategy", "external_strategy")
    identity = invoke(runtime, {"operation": "describe"})["identity"]
    assert identity["adapter"] == "pyne-external/5", "requires the current bridge candidate"
    bars = [dict(time=1700000040+i*60, open=100+i*.1, high=100.2+i*.1, low=99.8+i*.1,
                 close=100.1+i*.1, volume=100) for i in range(600)]
    wire = dict(protocol="candlescope.native-strategy/1", identity=identity, host_runtime_identity=host_identity(),
                account_model="SPOT_CASH_V1", execution_fidelity="BAR_APPROX", source=source,
                context={"symbol": "TEST", "timeframe": "1"}, interval="1m", contexts=[], context_intervals=[],
                host_settings=dict(initial_balance=1000, slippage_bps=1, taker_fee_bps=10, price_tick=.01), bars=bars)
    return runtime, wire


def test_six_hundred_bars_use_real_feedback_and_reproducible_cash():
    runtime, wire = prepared()
    started = time.monotonic()
    result = run_external_host(runtime, wire, invoke, threading.Event())
    # A broad regression guard for the former 120-second failure, not a UI P95.
    assert time.monotonic() - started < 20
    assert result["evaluation_contract"] == "pyne.host-fixed-history/1"
    assert len(result["raw_output"]["account_feedback"]) == 600
    assert len(result["trades"]) == 2
    assert {r["reason"] for r in result["diagnostics"]} == {"SPOT_INSUFFICIENT_CASH", "SPOT_INSUFFICIENT_BASE"}
    cash = D(1000)
    for trade in result["trades"]:
        notional = D(trade["price"]) * D(trade["qty"])
        cash += (-notional if trade["side"] == "BUY" else notional) - D(trade["fee"])
    assert cash == D(result["position"]["quote_balance"])
    assert D(result["position"]["position_qty"]) == 0
    feedback = result["raw_output"]["account_feedback"]
    assert feedback[21]["position_size"] == 1
    assert feedback[31]["position_size"] == 0
    again = run_external_host(runtime, wire, invoke, threading.Event())
    assert result == again


def test_delta_worker_preserves_host_deadline_and_reaps_process():
    runtime, wire = prepared('''def init(ctx):
    ctx.strategy.configure()
def on_bar(ctx, bar):
    while True:
        pass
''')
    worker = SessionWorker(runtime, wire, threading.Event(), evaluator=True)
    bar = wire["bars"][0]
    request = {**wire, "bars": [bar], "accounts": [dict(time=bar["time"], position_size=0,
        position_avg_price=None, equity=1000, initial_capital=1000, netprofit=0, openprofit=0)],
        "evaluation": dict(contract="pyne.host-fixed-history/1", horizon=600, cursor=0)}
    try:
        with pytest.raises(ValueError, match="deadline"):
            worker.request(request, threading.Event(), timeout=.8)
        assert worker.process.poll() is not None
    finally:
        worker.close()


def test_delta_worker_cancellation_reaps_process_without_waiting_for_deadline():
    runtime, wire = prepared()
    cancelled = threading.Event()
    worker = SessionWorker(runtime, wire, cancelled, evaluator=True)
    cancelled.set()
    try:
        with pytest.raises(ValueError, match="cancelled"):
            worker.request({}, cancelled, timeout=120)
        assert worker.process.poll() is not None
    finally:
        worker.close()
