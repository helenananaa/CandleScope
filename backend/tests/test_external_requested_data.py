import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_native_additional_inputs import additional
from tests.test_external_strategy_v2 import tape


SOURCES = {
    "pine": '''//@version=6
strategy("Requested host")
remote = request.security("BINANCE:ETHUSDT", "2", close)
if remote > 100 and strategy.position_size == 0
    strategy.entry("L", strategy.long, qty=1)
plot(remote)
''',
    "pyne": '''def init(ctx):
    ctx.strategy.configure()

def on_bar(ctx, bar):
    remote = ctx.request.security("BINANCE:ETHUSDT", "2", "close")
    if remote is not None and remote > 100 and ctx.strategy.position_size == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=1)
    ctx.plot("remote", remote)
''',
    "pyne_batch": '''strategy("Requested host")
remote = request.security("BINANCE:ETHUSDT", "2", "close")
strategy.entry_when((remote > 100) & (strategy.position_size == 0), "L", strategy.long, qty=1)
plot(remote)
''',
}


@pytest.mark.parametrize("kind", list(SOURCES))
@pytest.mark.parametrize("fidelity", ["BAR_APPROX", "TRADE_TAPE", "BOOK_ASSISTED"])
def test_requested_data_crosses_only_closed_boundary_and_host_owns_fills(runtime, kind, fidelity):
    host, payload = runtime
    context = {**additional(host, "higher", "ETHUSDT", "2m", 120000, [100,200,300,400,500]),
               "symbol": "BINANCE:ETHUSDT", "timeframe": "2"}
    seen = []
    original = host.native.runner
    def observe(plugin, request, **kwargs):
        if request.get("accounts"):
            boundary = (request["bars"][-1]["time"] + 60)*1000
            seen.append((boundary, request["contexts"][0]["bars"]))
            assert all((bar["time"]+120)*1000 <= boundary for bar in request["contexts"][0]["bars"])
        return original(plugin, request, **kwargs)
    host.native.runner = observe
    config = {**payload, "language": "pine" if kind == "pine" else "pyne", "source": SOURCES[kind],
              "execution_mode": "CANDLESCOPE", "contexts": [context], "execution_fidelity": fidelity,
              "host_settings": {"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}}
    if fidelity != "BAR_APPROX":
        data = tape()
        if fidelity == "BOOK_ASSISTED":
            events = []
            for i, event in enumerate(data["events"]):
                price = float(event["payload"]["price"])
                events.append({"time_ms":event["time_ms"], "role":"ORDER_BOOK", "payload":{
                    "book_sequence":i+1, "snapshot":i == 0, "bid":str(price-.1), "ask":str(price+.1)}})
                events.append(event)
            data["events"] = events
        config["execution_data"] = data
    record = terminal(host.native, host.native.create(config, kind)["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    assert seen[0] == (60000, [])
    assert len(seen[1][1]) == 1
    result = record["result"]
    assert result["account_authority"] == "candlescope"
    assert not result["raw_output"]["strategy_output"].get("strategy")
    assert result["raw_output"]["intent_history"][0]["bar_index"] == 3
    assert len(result["trades"]) == 1
    assert result["trades"][0]["event_time_ms"] >= 240000


@pytest.mark.parametrize("kind", list(SOURCES))
def test_missing_requested_dataset_never_falls_back(runtime, kind):
    host, payload = runtime
    record = terminal(host.native, host.native.create({**payload,"execution_mode":"CANDLESCOPE",
        "language":"pine" if kind == "pine" else "pyne", "source":SOURCES[kind],
        "host_settings":{"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}}, kind)["run_id"])
    assert record["state"] == "FAILED"
    assert record["result"] is None


def test_capability_probe_accepts_current_versioned_adapters(runtime):
    host, _ = runtime
    assert all(item["external_available"] for item in host.native.capabilities()["engines"])


def test_lookahead_that_rewrites_previous_host_intents_is_rejected(runtime):
    host, payload = runtime
    context = {**additional(host,"higher","ETHUSDT","2m",120000,[100,200,300,400,500]),
               "symbol":"BINANCE:ETHUSDT","timeframe":"2"}
    source = SOURCES["pine"].replace('"2", close)', '"2", close, lookahead=barmerge.lookahead_on)').replace('remote > 100','remote > 50')
    record = terminal(host.native, host.native.create({**payload,"source":source,"contexts":[context],
        "execution_mode":"CANDLESCOPE", "host_settings":{"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}},"lookahead")["run_id"])
    assert record["state"] == "FAILED"
    assert record["error"]["code"] == "EXTERNAL_NONCAUSAL_PREFIX"
    assert record["result"] is None
