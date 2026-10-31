"""Explicit schedules through real IPC and immutable Host prefix/rebuild state."""
from copy import deepcopy
from dataclasses import replace
import json
import os
import threading
from decimal import Decimal

import pytest

from app.backtest.errors import BacktestError
from app.backtest.native import PROTOCOL, invoke
from app.backtest.native_session import SessionWorker, SCHEDULE_CONTRACT, PREFIX_SCHEDULE_CONTRACT
from app.backtest.strategy.pine_engine import PineEngineProvider, plugin
from app.backtest.strategy.protocol import StrategyProviderError
from app.backtest.strategy.workspace import compile_revision
from tests.test_chart_pine_engine import frame


def request(count=2, *, commit=True):
    value = dict(source='//@version=6\nstrategy("scheduled",calc_on_every_tick=true)\nvarip int n=0\nn+=1\nplot(n)\nplot(timenow)\nstrategy.entry("L",strategy.long,qty=1)',
                 parameters={}, context=dict(symbol="BINANCE:BTCUSDT", timeframe="1"),
                 execution_schedule_contract=SCHEDULE_CONTRACT, bars=[], accounts=[], execution_schedule=[])
    for index in range(count):
        bar = dict(time=index*60, open=10, high=12, low=9, close=12, volume=100)
        account = dict(time=bar["time"], position_size=0, position_avg_price=None,
                       initial_capital=10000, equity=10000, openprofit=0, netprofit=0)
        value["bars"].append(bar)
        value["accounts"].append(account)
        value["execution_schedule"].append([
            dict(evaluation=dict(bar={**bar, "close": close}, account=deepcopy(account),
                event_time_ms=bar["time"]*1000+stamp, confirmed=confirmed),
                 context=dict(bar_state="realtime", trigger=trigger, is_new=first))
            for close, stamp, confirmed, trigger, first in [(10, 1000, False, "realtime_tick", True),
                (12, 59999, commit, "bar_close" if commit else "realtime_tick", False)]])
    return value


def prefix_worker():
    worker = object.__new__(SessionWorker)
    worker.identity = dict(prefix_append="candlescope.pine-prefix/1", prefix_schedule=PREFIX_SCHEDULE_CONTRACT,
                           execution_schedule_contract=SCHEDULE_CONTRACT)
    worker._prefix_state = None
    return worker


@pytest.mark.parametrize("commit", [True, False])
def test_only_closed_explicit_groups_can_use_suffix_transport(commit):
    worker = prefix_worker()
    first = request(1, commit=commit)
    worker._prefix_payload(first)
    second = request(2)
    if not commit:
        second["execution_schedule"][0] = deepcopy(first["execution_schedule"][0])
    transmitted = worker._prefix_payload(second)
    assert (transmitted.get("operation") == "append_prefix") == commit
    if commit:
        assert transmitted["execution_schedule"] == second["execution_schedule"][1:]


@pytest.mark.parametrize("field", ["bar", "account", "context"])
def test_mutating_a_previous_payload_cannot_mutate_the_workers_frozen_prefix(field):
    worker = prefix_worker()
    value = request(1)
    worker._prefix_payload(value)
    if field == "context":
        value["execution_schedule"][0][0]["context"]["is_new"] = False
    elif field == "bar":
        value["bars"][0]["close"] = 11
    else:
        value["accounts"][0]["equity"] = 9999
    second = request(2)
    for key in ("bars", "accounts", "execution_schedule"):
        second[key][0] = value[key][0]
    assert worker._prefix_payload(second) is second


def test_explicit_schedule_cannot_be_sent_to_an_unnegotiated_worker():
    worker = prefix_worker()
    worker.identity.pop("execution_schedule_contract")
    with pytest.raises(BacktestError, match="not negotiated"):
        worker.request(request(), threading.Event())


@pytest.mark.parametrize("identity,available,replay,persistent", [
    ({"adapter": "pine-external/1"}, True, False, False),
    ({"adapter": "pine-external/4"}, True, False, False),
    ({"adapter": "pine-external/5"}, True, True, True),
    ({"adapter": "pine-external/8"}, True, True, True),
    ({"adapter": "pine-external/9"}, False, False, False),
    ({"adapter": "pine-external/99"}, False, False, False),
    ({"adapter": "pine-external/99", "external_replay": "candlescope.external-replay/1",
      "prefix_append": "candlescope.pine-prefix/1", "external_orders": 2}, True, True, True),
    ({"adapter": "pine-external/99", "external_replay": "unknown",
      "prefix_append": "candlescope.pine-prefix/1", "external_orders": 2}, False, False, False),
    ({"adapter": "pine-external/99", "external_replay": "candlescope.external-replay/1",
      "prefix_append": "unknown", "external_orders": 2}, False, False, False),
    ({"adapter": "pine-external/99", "external_replay": "candlescope.external-replay/1",
      "prefix_append": "candlescope.pine-prefix/1", "external_orders": True}, False, False, False),
    ({"adapter": "pyne-external/5"}, False, False, False),
    ({"adapter": "pyne-external/99", "external_replay": "candlescope.external-replay/1",
      "prefix_append": "candlescope.pine-prefix/1", "external_orders": 2}, False, False, False),
])
def test_external_admission_negotiates_new_capabilities_and_preserves_legacy_profiles(identity, available, replay, persistent):
    from app.backtest.external_support import external_available, pine_replay_available, persistent_evaluator
    assert external_available("pine", identity) is available
    assert pine_replay_available(identity) is replay
    assert persistent_evaluator(identity) is persistent


installed = pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"), reason="requires installed Pine bridge")


@installed
@pytest.mark.parametrize("route", ["chart_strategy", "external_strategy"])
def test_real_schedule_ipc_append_rebase_restart_and_corrected_context(route):
    runtime = plugin()
    runtime["command"][-1] = f"candlescope_plugin_pine_compat.{route}"
    identity = invoke(runtime, {"operation": "describe"})["identity"]
    assert identity["execution_schedule_contract"] == SCHEDULE_CONTRACT
    wire = dict(protocol=PROTOCOL, identity=identity)
    cancel = threading.Event()
    worker = SessionWorker(runtime, wire, cancel, evaluator=True)
    try:
        value = request(1)
        first = worker.request({**wire, **value}, cancel)
        value = request(2)
        appended = worker.request({**wire, **value}, cancel)
        assert appended == invoke(runtime, {**wire, **value})
        assert appended["raw_output"]["plots"][0]["values"] == [2, 4]
        assert appended["raw_output"]["plots"][1]["values"] == [59999, 119999]
        assert first["intents"] == appended["intents"][:2]
        # Replacing a forming observation and its context requires reconstruction.
        forming = request(1, commit=False)
        assert worker.request({**wire, **forming}, cancel) == invoke(runtime, {**wire, **forming})
        closed = request(1)
        assert worker.request({**wire, **closed}, cancel) == first
        worker.close()
        worker = SessionWorker(runtime, wire, cancel, evaluator=True)
        assert worker.request({**wire, **value}, cancel) == appended
    finally:
        worker.close()


@installed
def test_chart_provider_preserves_historical_confirmation_and_context_across_restore():
    source = '''//@version=6
strategy("history callbacks",calc_on_order_fills=true)
if barstate.isconfirmed and barstate.ishistory
    if strategy.position_size>0
        strategy.close("L")
    else
        strategy.entry("L",strategy.long,qty=2)
'''
    revision = compile_revision(dict(language="PINE_ENGINE", name="scheduled", source_text=source), now_ms=1)
    compiled = json.loads(revision["compiled_json"])["executionSource"]
    context = dict(source=compiled, parameters={}, outputMode="ORDER_INTENT",
                   pineExecutionScheduleContract=SCHEDULE_CONTRACT)
    provider, restored = PineEngineProvider(), PineEngineProvider()
    try:
        provider.prepare(context)
        first = replace(frame(0, 10, position=2), event_time_ms=1000, watermark_ms=1000,
            features=dict(pineExecutionPass=dict(barIndex=0, confirmed=False),
                          pineExecutionContext=dict(bar_state="historical", trigger="order_fill", is_new=True)))
        output = provider.step(first)
        assert output.payload["intents"][0]["action"] == "close"
        saved = provider.snapshot()
        restored.restore(saved)
        closing = replace(frame(0, 10), sequence=2,
            features=dict(pineExecutionPass=dict(barIndex=0, confirmed=True),
                          pineExecutionContext=dict(bar_state="historical", trigger="bar_close", is_new=True)))
        assert provider.step(closing) == restored.step(closing)
        assert saved["execution_schedule"][0][0]["evaluation"]["confirmed"] is False
        assert len(saved["execution_schedule"][0]) == 1  # Snapshot owns its nested lists.
        assert provider.snapshot() == restored.snapshot()
        assert provider.report_metadata()["pineExecution"]["fillCallbackCount"] == 1
        broken = deepcopy(saved)
        broken.pop("execution_schedule")
        with pytest.raises(StrategyProviderError, match="schedule mode differs"):
            restored.restore(broken)
    finally:
        provider.close()
        restored.close()


@installed
def test_scheduled_intents_consume_real_host_fills_and_never_native_account_results():
    from app.backtest.external import account_feedback_profit
    from app.backtest.external_orders import ExternalOrders
    from app.market_dataset.snapshot import MarketEvent
    from app.simulation.trade_kernel import TradeSimulationKernel
    kernel = TradeSimulationKernel(initial_balance=Decimal(10000), slippage_bps=Decimal(0), taker_fee_bps=Decimal(0))
    orders = ExternalOrders(kernel, fidelity="TRADE_TAPE")
    orders.configure(1)
    runtime = plugin()
    runtime["command"][-1] = "candlescope_plugin_pine_compat.external_strategy"
    identity = invoke(runtime, dict(operation="describe"))["identity"]
    source = '''//@version=6
strategy("Host fills",calc_on_order_fills=true)
plot(strategy.position_size)
plot(strategy.netprofit)
if barstate.isconfirmed and barstate.ishistory
    if strategy.position_size>0
        strategy.close("L")
    else
        strategy.entry("L",strategy.long,qty=2)
'''
    bars = [dict(time=0, open=10, high=10, low=10, close=10, volume=100),
            dict(time=60, open=11, high=12, low=11, close=12, volume=100)]
    frames, groups = [], []
    wire = dict(protocol=PROTOCOL, identity=identity, source=source, parameters={},
                context=dict(symbol="BINANCE:BTCUSDT", timeframe="1"), execution_schedule_contract=SCHEDULE_CONTRACT)
    cancelled = threading.Event()
    worker = SessionWorker(runtime, wire, cancelled, evaluator=True)
    def evaluate(index, trigger, commit, clock, sequence):
        account = kernel.account
        feedback = dict(time=bars[index]["time"], position_size=float(account.position_qty),
            position_avg_price=None if account.entry_price is None else float(account.entry_price),
            equity=float(account.equity()), initial_capital=10000,
            netprofit=float(account_feedback_profit(account, kernel.initial_balance)), openprofit=float(account.unrealized()))
        if len(groups) == index:
            groups.append([])
            frames.append(feedback)
        frames[index] = feedback
        ordinal = len(groups[index])
        groups[index].append(dict(evaluation=dict(bar=bars[index], account=feedback, confirmed=commit, event_time_ms=clock),
            context=dict(bar_state="historical", trigger=trigger, is_new=True)))
        actual = worker.request({**wire, "bars": bars[:index+1], "accounts": frames, "execution_schedule": groups}, cancelled)
        assert "strategy" not in actual["raw_output"]
        current = [item for item in actual["intents"] if (item["bar_index"], item["pass_index"]) == (index, ordinal)]
        kernel._enqueue_many(orders.translate(current, sequence), current_sequence=sequence)
        return actual
    def trade(sequence, stamp, price):
        event = MarketEvent(sequence, stamp, "TRADES", dict(price=str(price), qty="100"))
        kernel._last_event = event
        kernel.account.mark = Decimal(price)
        kernel._match(event)
    try:
        evaluate(0, "bar_close", True, 59999, 0)
        trade(1, 60000, 11)
        assert kernel.account.position_qty == 2
        filled = evaluate(1, "order_fill", False, 60000, 1)
        assert filled["intents"][-1]["action"] == "close"
        trade(2, 61000, 12)
        assert kernel.account.position_qty == 0 and len(kernel.fills) == 2
        actual = evaluate(1, "bar_close", True, 119999, 2)
        assert actual["raw_output"]["plots"][0]["values"] == [0, 0]
        assert actual["raw_output"]["plots"][1]["values"] == [0, 2]
        assert [(fill.price, fill.qty) for fill in kernel.fills] == [(11, 2), (12, 2)]
    finally:
        worker.close()
