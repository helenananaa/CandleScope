"""Actual Pyne event observations, with primary market execution unchanged."""
from copy import deepcopy

import pytest
import pyne_runtime

from candlescope_plugin_pyne.event_requests import FrozenProvider, closed_boundary
from candlescope_plugin_pyne.native_strategy import execute
from candlescope_plugin_pyne.external_strategy import execute as external
from candlescope_plugin_pyne.native_session import Session


pytestmark = pytest.mark.skipif(
    getattr(pyne_runtime, "EVENT_REQUEST_SERIES_CONTRACT", None) != "source-close-events/1",
    reason="requires the pinned event-series Pyne candidate")

SOURCE = '''strategy("Causal Renko", overlay=True)
r = ticker.renko(syminfo.tickerid, "Traditional", 1)
brick = request.security(r, timeframe.period, "close")
previous = request.security(r, timeframe.period, "close[1]")
plot(brick, "Brick")
plot(previous, "Previous")
strategy.entry_when((bar_index == 1) & (brick > previous), "L", strategy.long, qty=1)
strategy.close_when((bar_index == 3) & (brick < previous), "L")
'''


def request():
    return {"source": SOURCE, "context": {"symbol": "TEST", "timeframe": "1"},
            "bars": [dict(time=1700000040+i*60, open=c+.2, high=c+.25,
                          low=c-.25, close=c, volume=10, is_closed=True)
                     for i, c in enumerate([100.4,103.8,106.9,101.6,104.8,100.1])]}


def values(report, bars):
    return [[next((point["value"] for point in line["data"] if point["time"] == bar["time"]), None)
             for bar in bars] for line in report["graphics"]]


def test_native_uses_brick_ordinal_history_but_market_fill_prices():
    req = request()
    original = deepcopy(req)
    result = execute(req)
    assert req == original
    assert values(result, req["bars"])[0] == pytest.approx([None,103.4,106.4,102.4,104.4,100.4])
    assert values(result, req["bars"])[1] == pytest.approx([None,102.4,105.4,103.4,102.4,101.4])
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    # Pyne's native default settles on the source close. Host mode is tested
    # separately with its next real print; neither uses a synthetic price.
    assert trade["entry_price"] == req["bars"][1]["close"]
    assert trade["exit_price"] == req["bars"][3]["close"]
    assert trade["entry_price"] != values(result, req["bars"])[0][1]


def test_host_feedback_intents_are_causal_on_every_prefix():
    req = request()
    req["accounts"] = [{"time":row["time"], "position_size":0,
        "position_avg_price":None, "equity":1000, "initial_capital":1000,
        "netprofit":0, "openprofit":0} for row in req["bars"]]
    full = external(req)
    assert "strategy" not in full["raw_output"]
    assert [item["action"] for item in full["intents"]] == ["entry", "close"]
    for count in range(2, len(req["bars"])+1):
        prefix = external({**req, "bars":req["bars"][:count], "accounts":req["accounts"][:count]})
        assert values(prefix, req["bars"][:count]) == [v[:count] for v in values(full, req["bars"])]
        assert prefix["intents"] == [item for item in full["intents"] if item["bar_index"] < count]


def test_provider_rejects_unfrozen_source_and_unknown_modifiers():
    provider = FrozenProvider([], request())
    with pytest.raises(ValueError, match="SYNTHETIC_SOURCE_REQUIRED"):
        provider.get_ohlcv("OTHER?chart=renko&style=Traditional&param=1", "1", 0, 2**40)
    with pytest.raises(ValueError, match="SYNTHETIC_INPUT_UNSUPPORTED"):
        provider.get_ohlcv("TEST?chart=renko&style=Traditional&param=1&session=regular", "1", 0, 2**40)


def test_calendar_boundaries_use_actual_month_and_year_lengths():
    assert closed_boundary({"time":1706745600}, "1M") == 1709251200
    assert closed_boundary({"time":1704067200}, "12M") == 1735689600
    with pytest.raises(ValueError, match="calendar source is not aligned"):
        closed_boundary({"time":1706745660}, "1M")


def test_frozen_higher_timeframe_bricks_wait_for_the_source_close():
    req = request()
    req["bars"] = [dict(time=i*60, open=100, high=101, low=99, close=100, volume=10)
                   for i in range(10)]
    req["contexts"] = [{"symbol": "OTHER", "timeframe": "5", "bars": [
        dict(time=i*300, open=c, high=c+1, low=c-1, close=c, volume=50)
        for i, c in enumerate([100, 106])]}]
    req["source"] = '''strategy("Frozen higher timeframe")
r = ticker.renko("OTHER", "Traditional", 2)
plot(request.security(r, "5", "close"), "Brick")
plot(request.security(r, "5", "close[1]"), "Previous")
'''
    full = values(execute(req), req["bars"])
    assert full == [[None]*9 + [106], [None]*9 + [104]]
    for count in [4, 5, 9, 10]:
        prefix = {**req, "bars": req["bars"][:count]}
        assert values(execute(prefix), prefix["bars"]) == [series[:count] for series in full]


def test_fixed_history_seek_matches_fresh_market_prefix():
    req = request()
    req["source"] = '''def init(ctx):
    ctx.strategy.configure(initial_capital=10000)
def on_bar(ctx, bar):
    r = "TEST?chart=renko&style=Traditional&param=1"
    brick = ctx.request.security(r, ctx.timeframe.period, "close")
    previous = ctx.request.security(r, ctx.timeframe.period, "close[1]")
    ctx.plot("Brick", brick)
    ctx.plot("Previous", previous)
    if ctx.bar_index == 1:
        ctx.strategy.entry("L", ctx.strategy.long, qty=1)
    if ctx.bar_index == 3:
        ctx.strategy.close("L")
'''
    session = Session(req)
    for count in [2, 4, 6, 3, 6]:
        stepped = session.advance(count)
        standalone = execute({**req, "bars": req["bars"][:count]})
        assert values(stepped, req["bars"][:count]) == values(standalone, req["bars"][:count])


def test_incremental_strategy_with_no_orders_is_not_rejected_as_an_indicator():
    req = request()
    req["source"] = '''def init(ctx):
    ctx.strategy.configure(initial_capital=4321)
def on_bar(ctx, bar):
    ctx.plot("Close", bar.close)
'''
    result = execute(req)
    assert result["orders"] == result["trades"] == []
    assert result["equity"] == [{"time": bar["time"], "value": 4321} for bar in req["bars"]]
    with pytest.raises(ValueError, match="NATIVE_STRATEGY_REQUIRED"):
        execute({**req, "source": 'def on_bar(ctx, bar):\n    ctx.plot("Close", bar.close)\n'})
