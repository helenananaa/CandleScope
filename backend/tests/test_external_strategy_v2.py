from __future__ import annotations
import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark


def source(language, operation):
    if language == "pine":
        return '//@version=6' + '\nstrategy("Orders")\n' + operation
    return 'def init(ctx):\n    ctx.strategy.configure()\ndef on_bar(ctx, bar):\n' + '\n'.join('    '+line for line in operation.replace('bar_index', 'ctx.bar_index').replace('strategy.', 'ctx.strategy.').replace('true', 'True').splitlines())


def execute(host, payload, language, operation, **extra):
    payload = {**payload, "language": language, "source": source(language, operation), "execution_mode": "CANDLESCOPE",
               "host_settings": {"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 1}, **extra}
    record = host.native.create(payload, str(hash(str(payload))))
    result = terminal(host.native, record["run_id"])
    assert result["state"] == "COMPLETED", result.get("error")
    return result["result"]


@pytest.mark.parametrize("language", ["pine", "pyne"])
@pytest.mark.parametrize("kind,arguments", [("LIMIT", "limit=11"), ("STOP", "stop=11"), ("STOP_LIMIT", "limit=21, stop=11")])
def test_price_orders_reach_real_host_kernel(runtime, language, kind, arguments):
    host, payload = runtime
    report = execute(host, payload, language, f'if bar_index == 0:\n    strategy.entry("L", strategy.long, qty=4, {arguments})'.replace('0:', '0' if language == 'pine' else '0:'))
    assert report["orders"][0]["type"] == kind
    assert report["trades"]
    assert report["account_authority"] == "candlescope"


@pytest.mark.parametrize("language", ["pine", "pyne"])
def test_partial_exit_bracket_cancel_and_replacement(runtime, language):
    host, payload = runtime
    operation = '''if bar_index == 0:
    strategy.entry("L", strategy.long, qty=4, limit=1)
if bar_index == 1:
    strategy.entry("L", strategy.long, qty=4)
if bar_index == 2:
    strategy.close("L", qty_percent=50)
if bar_index == 3:
    strategy.exit("X", "L", limit=30, stop=8)
'''
    if language == "pine": operation = operation.replace(':', '')
    report = execute(host, payload, language, operation)
    assert report["orders"][0]["status"] == "CANCELLED"
    assert [float(f["qty"]) for f in report["trades"]] == [4, 2, 2]
    assert float(report["trades"][-1]["position_after"]) == 0
    assert any(o["status"] == "CANCELLED_OCO" for o in report["orders"])


def tape():
    events=[]
    index=0
    for i,v in enumerate([10,10,10,20,20,5,5,15,15,8]):
        for j,price in enumerate([v,v+1,v-1,v]):
            index+=1
            events.append({"time_ms": i*60000+j*10000, "role":"TRADES", "payload":{"source_event_kind":"AGG_TRADE", "source_sequence":index,"price":str(price),"qty":"25"}})
    return {"symbol":"BTCUSDT", "events":events}


@pytest.mark.parametrize("language", ["pine", "pyne"])
@pytest.mark.parametrize("mode", ["TRADE_TAPE", "BOOK_ASSISTED"])
def test_real_print_clock_and_book_feedback(runtime, language, mode):
    host,payload=runtime
    data=tape()
    if mode == "BOOK_ASSISTED":
        events=[]
        for i,e in enumerate(data["events"]):
            price=float(e["payload"]["price"])
            events.append({"time_ms":e["time_ms"],"role":"ORDER_BOOK","payload":{"book_sequence":i+1,"snapshot":i==0,"bid":str(price-0.1),"ask":str(price+0.1)}})
            events.append(e)
        data["events"]=events
    operation='''if bar_index == 0:
    strategy.entry("L", strategy.long, qty=4)
if bar_index == 2:
    strategy.exit("X", "L", stop=8)
'''
    if language == "pine": operation=operation.replace(':','')
    report=execute(host,payload,language,operation,execution_fidelity=mode,execution_data=data)
    first=report["trades"][0]
    assert first["event_time_ms"] == 60000
    assert float(first["price"]) == (10.1 if mode == "BOOK_ASSISTED" else 10)
    assert float(report["raw_output"]["account_feedback"][1]["position_size"]) == 4
    assert float(report["trades"][-1]["position_after"]) == 0
    assert report["fidelity"] == ("AGG_TRADE_TAPE" if mode == "TRADE_TAPE" else mode)


def test_mismatched_tape_and_book_gap_are_rejected(runtime):
    host,payload=runtime
    data=tape(); data["events"][1]["payload"]["source_sequence"]=99
    with pytest.raises(ValueError):
        execute(host,payload,"pine",'strategy.entry("L", strategy.long)',execution_fidelity="TRADE_TAPE",execution_data=data)
    data=tape();data["events"][1]["payload"]["price"]="99"
    with pytest.raises(ValueError, match="OHLCV"):
        execute(host,payload,"pine",'strategy.entry("L", strategy.long)',execution_fidelity="TRADE_TAPE",execution_data=data)


def test_partial_oco_does_not_exit_more_than_reserved_quantity():
    from decimal import Decimal
    from app.backtest.external_orders import ExternalOrders
    from app.simulation.trade_kernel import TradeSimulationKernel
    from app.market_dataset.snapshot import MarketEvent
    kernel=TradeSimulationKernel()
    bridge=ExternalOrders(kernel)
    def event(seq, price, qty):
        return MarketEvent(seq, seq*1000, "TRADES", {"source_event_kind":"RAW_TRADE", "source_sequence":seq, "price":str(price), "qty":str(qty)})
    kernel._last_event=event(1,10,10);kernel.account.mark=Decimal(10)
    kernel._enqueue_many(bridge.translate([{"action":"entry","id":"L","direction":"long","qty":4}],1),current_sequence=1)
    kernel._last_event=event(2,10,10);kernel._match(kernel._last_event);bridge.feedback()
    kernel._enqueue_many(bridge.translate([{"action":"exit","id":"X","from_entry":"L","qty":2,"stop":9,"limit":11}],2),current_sequence=2)
    kernel._last_event=event(3,8,1);kernel._match(kernel._last_event)
    kernel._last_event=event(4,12,10);kernel._match(kernel._last_event)
    assert kernel.account.position_qty == 2
    assert [float(fill.qty) for fill in kernel.fills] == [4,1,1]
