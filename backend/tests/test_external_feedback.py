import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_external_strategy_v2 import tape

PINE = """//@version=6
strategy("Fill feedback", calc_on_order_fills=true)
if bar_index == 0 and barstate.isconfirmed
    strategy.entry("L", strategy.long, qty=4)
if strategy.position_size > 0 and not barstate.isconfirmed
    strategy.close("L")
plot(ta.sma(close, 2))
"""
PYNE = """def init(ctx):
    ctx.strategy.configure(calc_on_order_fills=True)
def on_bar(ctx, bar):
    if ctx.bar_index == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=4)
def on_fill(ctx, bar):
    if ctx.strategy.position_size > 0:
        ctx.strategy.close("L")
"""


def run(host, payload, language, source, mode):
    data = tape()
    if mode == "BOOK_ASSISTED":
        events = []
        for i, event in enumerate(data["events"]):
            price = float(event["payload"]["price"])
            events.append({"time_ms": event["time_ms"], "role": "ORDER_BOOK", "payload": {
                "book_sequence": i+1, "snapshot": i == 0, "bid": str(price-.1), "ask": str(price+.1)}})
            events.append(event)
        data["events"] = events
    config = {**payload, "language": language, "source": source, "execution_mode": "CANDLESCOPE",
        "host_settings": {"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 1},
        "execution_fidelity": mode, "execution_data": data, "fill_recalculation": True}
    record = host.native.create(config, "fill-"+language)
    return terminal(host.native, record["run_id"])


@pytest.mark.parametrize("language,source", [("pine", PINE), ("pyne", PYNE)])
@pytest.mark.parametrize("mode", ["TRADE_TAPE", "BOOK_ASSISTED"])
def test_fill_callbacks_use_actual_account_visible_prices_and_next_event(runtime, language, source, mode):
    host, payload = runtime
    record = run(host, payload, language, source, mode)
    assert record["state"] == "COMPLETED", record.get("error")
    report = record["result"]
    assert [fill["event_time_ms"] for fill in report["trades"]] == [60000, 70000]
    assert [float(fill["position_after"]) for fill in report["trades"]] == [4, 0]
    passes = report["raw_output"]["execution_passes"][1]
    assert [event["confirmed"] for event in passes] == [False, False, True]
    assert passes[0]["bar"] == dict(time=60, open=10, high=10, low=10, close=10, volume=25)
    assert passes[0]["account"]["position_size"] == 4
    assert passes[0]["account"]["position_avg_price"] == (10.1 if mode == "BOOK_ASSISTED" else 10)
    assert passes[1]["account"]["position_size"] == 0
    assert report["account_authority"] == "candlescope"
    assert not report["raw_output"]["strategy_output"].get("strategy")
    if language == "pine":
        assert report["graphics"][0]["values"][1:] == [10,10,15,20,12.5,5,10,15,11.5]


def test_fill_profile_requires_incremental_callback_and_explicit_opt_in(runtime):
    host, payload = runtime
    record = run(host, payload, "pyne", PYNE.replace("def on_fill(ctx, bar):", "def unused(ctx, bar):"), "TRADE_TAPE")
    assert record["state"] == "FAILED" and record["result"] is None
    assert "on_fill" in str(record["error"])


def test_bar_only_fill_profile_is_rejected_before_run(runtime):
    host, payload = runtime
    with pytest.raises(ValueError, match="trade tape"):
        host.native.create({**payload, "execution_mode": "CANDLESCOPE", "fill_recalculation": True,
            "host_settings": {"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 0}}, "bad-fill")


@pytest.mark.parametrize("language", ["pine", "pyne"])
def test_multiple_entry_fill_callbacks_never_close_other_owner(runtime, language):
    host, payload = runtime
    source = '''//@version=6
strategy("Owned callbacks", pyramiding=2, calc_on_order_fills=true)
if barstate.isconfirmed and bar_index == 0
    strategy.entry("A", strategy.long, qty=2)
    strategy.entry("B", strategy.long, qty=3)
if not barstate.isconfirmed and strategy.position_size > 0
    strategy.close("A")
''' if language == "pine" else '''def init(ctx):
    ctx.strategy.configure(pyramiding=2, calc_on_order_fills=True)

def on_bar(ctx, bar):
    if ctx.bar_index == 0:
        ctx.strategy.entry("A", qty=2)
        ctx.strategy.entry("B", qty=3)

def on_fill(ctx, bar):
    if ctx.strategy.position_size > 0:
        ctx.strategy.close("A")
'''
    record = run(host, payload, language, source, "TRADE_TAPE")
    assert record["state"] == "COMPLETED", record.get("error")
    assert [float(fill["position_after"]) for fill in record["result"]["trades"]] == [2,5,3]
    lots = record["result"]["raw_output"]["entry_allocation"]["open_entries"]
    assert len(lots) == 1 and lots[0]["entry_id"] == "B" and float(lots[0]["qty"]) == 3


@pytest.mark.parametrize("language", ["pine", "pyne"])
@pytest.mark.parametrize("mode", ["TRADE_TAPE", "BOOK_ASSISTED"])
def test_requested_data_is_frozen_per_fill_not_retroactively_visible(runtime, language, mode):
    from tests.test_native_additional_inputs import additional
    host, payload = runtime
    context = {**additional(host,"higher","ETHUSDT","2m",120000,[100,200,300,400,500]),
               "symbol":"BINANCE:ETHUSDT","timeframe":"2"}
    source = """//@version=6
strategy("Pass data", calc_on_order_fills=true)
remote = request.security("BINANCE:ETHUSDT", "2", close)
if barstate.isconfirmed and bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if barstate.isconfirmed and bar_index == 1
    strategy.entry("B", strategy.long, qty=1)
if not barstate.isconfirmed and strategy.position_size > 0
    if na(remote)
        strategy.exit("X", "L", limit=10.5)
    else
        strategy.close_all()
plot(remote)
""" if language == "pine" else """def init(ctx):
    ctx.strategy.configure(calc_on_order_fills=True)
    ctx.request_alias = request

def on_bar(ctx, bar):
    if ctx.bar_index == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=1)
    if ctx.bar_index == 1:
        ctx.strategy.entry("B", ctx.strategy.long, qty=1)
    ctx.plot("remote", ctx.request.security("BINANCE:ETHUSDT", "2", "close"))

def on_fill(ctx, bar):
    remote = ctx.request_alias.security("BINANCE:ETHUSDT", "2", "close")
    if ctx.strategy.position_size > 0:
        if remote is None or remote != remote:
            ctx.strategy.exit("X", "L", limit=10.5)
        else:
            ctx.strategy.close_all()
"""
    record = run(host, {**payload,"contexts":[context]}, language, source, mode)
    assert record["state"] == "COMPLETED", record.get("error")
    report = record["result"]
    groups = report["raw_output"]["execution_passes"]
    first_fill_intents = [item for item in report["raw_output"]["intent_history"] if item.get("bar_index") == 1 and item.get("pass_index") == 0]
    assert [item["action"] for item in first_fill_intents] == ["exit"]
    assert [p["request_data"][0]["bars"] for p in groups[1][:2]] == [[], []]
    assert len(groups[1][-1]["request_data"][0]["bars"]) == 1
    assert [fill["event_time_ms"] for fill in report["trades"]] == [60000,70000,120000,130000]
    for group in groups:
        for event in group:
            assert all((bar["time"]+120)*1000 <= event["event_time_ms"]+int(event["confirmed"])
                       for bar in event["request_data"][0]["bars"])
    assert report["account_authority"] == "candlescope"
    assert not report["raw_output"]["strategy_output"].get("strategy")


@pytest.mark.parametrize("language", ["pine", "pyne"])
def test_fill_in_last_millisecond_does_not_see_unconfirmed_requested_close(runtime, language):
    from tests.test_native_additional_inputs import additional
    host, payload = runtime
    context = {**additional(host,"edge","ETHUSDT","2m",120000,[100,200,300,400,500]),
               "symbol":"BINANCE:ETHUSDT","timeframe":"2"}
    data = tape()
    data["events"][6]["time_ms"] = 119999
    data["events"][7]["time_ms"] = 119999
    source = '''//@version=6
strategy("Boundary", calc_on_order_fills=true)
remote = request.security("BINANCE:ETHUSDT", "2", close)
if barstate.isconfirmed and bar_index == 0
    strategy.entry("L", strategy.long, qty=1, limit=9)
if not barstate.isconfirmed and strategy.position_size > 0 and na(remote)
    strategy.exit("X", "L", limit=10.5)
''' if language == "pine" else '''def init(ctx):
    ctx.strategy.configure(calc_on_order_fills=True)

def on_bar(ctx, bar):
    if ctx.bar_index == 0:
        ctx.strategy.entry("L", qty=1, limit=9)

def on_fill(ctx, bar):
    remote = ctx.request.security("BINANCE:ETHUSDT", "2", "close")
    if ctx.strategy.position_size > 0 and (remote is None or remote != remote):
        ctx.strategy.exit("X", "L", limit=10.5)
'''
    created = host.native.create({**payload,"language":language,"source":source,
        "execution_mode":"CANDLESCOPE","execution_fidelity":"TRADE_TAPE","execution_data":data,
        "fill_recalculation":True,"contexts":[context],
        "host_settings":{"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}}, "edge-"+language)
    record = terminal(host.native, created["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    report = record["result"]
    passes = report["raw_output"]["execution_passes"][1]
    assert passes[0]["event_time_ms"] == 119999 and not passes[0]["confirmed"]
    assert passes[0]["request_data"][0]["bars"] == []
    assert passes[-1]["confirmed"] and len(passes[-1]["request_data"][0]["bars"]) == 1
    assert [fill["event_time_ms"] for fill in report["trades"]] == [119999,130000]
