"""Run the actual event-series engine, including causal host feedback boundaries."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
import pine_compat

from candlescope_plugin_pine_compat.event_requests import renko_rows, run_with_event_requests
from candlescope_plugin_pine_compat.native_strategy import execute
from candlescope_plugin_pine_compat.native_session import Session
from candlescope_plugin_pine_compat.external_strategy import execute as external
from candlescope_plugin_pine_compat.strategy_time import engine_bars


pytestmark = pytest.mark.skipif(
    getattr(pine_compat, "EVENT_REQUEST_SERIES_CONTRACT", None) != "renko-event-rows/1",
    reason="requires the locally built Renko event-series candidate")

SOURCE = '''//@version=6
strategy("Causal Renko")
r = ticker.renko(syminfo.tickerid, "Traditional", 1)
brick = request.security(r, timeframe.period, close)
previous = request.security(r, timeframe.period, close[1])
plot(brick)
plot(previous)
if bar_index == 1 and brick > previous
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 3 and brick < previous
    strategy.close("L")
'''


def request():
    return {"source": SOURCE, "context": {"symbol": "TEST", "timeframe": "1"},
            "bars": [dict(time=1700000040+i*60, open=c+.2, high=c+.25,
                          low=c-.25, close=c, volume=10, is_closed=True)
                     for i, c in enumerate([100.4,103.8,106.9,101.6,104.8,100.1])]}


def values(report):
    return [item["values"] for item in report["graphics"]]


def test_multiple_bricks_reversal_and_real_native_fill_prices():
    req = request()
    before = deepcopy(req)
    result = execute(req)
    assert req == before
    assert values(result)[0] == pytest.approx([None,103.4,106.4,102.4,104.4,100.4])
    # History is the preceding brick, including another brick at the same source
    # time; it is not the previous primary-market bar.
    assert values(result)[1] == pytest.approx([None,102.4,105.4,103.4,102.4,101.4])
    trade = result["trades"][0]
    assert trade["entryPrice"] == req["bars"][2]["open"]
    assert trade["exitPrice"] == req["bars"][4]["open"]
    assert trade["entryPrice"] != values(result)[0][2]
    assert trade["entryTime"] == req["bars"][2]["time"]


@pytest.mark.parametrize("style,parameter", [("Traditional",1),("ATR",2)])
def test_prefixes_are_immutable_and_ignore_forming_source(style, parameter):
    rows = request()["bars"]
    full = renko_rows(rows, style, parameter)
    for count in range(1,len(rows)+1):
        prefix = renko_rows(rows[:count], style, parameter)
        assert prefix == [item for item in full if item["source_index"] < count]
        forming = [*rows[:count-1], {**rows[count-1], "is_closed":False}]
        assert renko_rows(forming, style, parameter) == renko_rows(rows[:count-1], style, parameter)
    times = [item["time"] for item in full]
    if style == "Traditional":
        assert len(times) > len(set(times))
    assert all(time in {row["time"] for row in rows} for time in times)


def test_fixed_session_seek_and_hidden_future_match_market_prefix():
    req = request()
    session = Session(req)
    for count in [1,2,4,6,3,6]:
        stepped = session.advance(count)
        standalone = execute({**req,"bars":req["bars"][:count]})
        assert values(stepped) == values(standalone)
        assert stepped["trades"] == standalone["trades"]


def test_external_prefixes_use_host_feedback_and_never_create_native_ledger():
    req = request()
    req["accounts"] = [{"time":row["time"],"position_size":0,
        "position_avg_price":None,"equity":1000,"initial_capital":1000,
        "netprofit":0,"openprofit":0} for row in req["bars"]]
    full = external(req)
    assert "strategy" not in full["raw_output"]
    assert full["account_authority"] == "candlescope"
    assert [item["action"] for item in full["intents"]] == ["entry","close"]
    for count in range(1,len(req["bars"])+1):
        prefix = external({**req,"bars":req["bars"][:count],"accounts":req["accounts"][:count]})
        assert values(prefix) == [series[:count] for series in values(full)]
        assert prefix["intents"] == [item for item in full["intents"] if item["bar_index"] < count]


def test_missing_frozen_source_and_old_runtime_fail_explicitly():
    req = request()
    req["source"] = SOURCE.replace('syminfo.tickerid', '"OTHER"')
    with pytest.raises(ValueError,match="SYNTHETIC_SOURCE_REQUIRED"):
        execute(req)
    req = request()
    program = pine_compat.compile_script(req["source"])
    with pytest.raises(ValueError,match="SYNTHETIC_RUNTIME_REQUIRED"):
        run_with_event_requests(lambda data: program.run(engine_bars(req["bars"]),
            chart_symbol="TEST",chart_timeframe="1",request_bars=data),
            req,{},engine_bars,SimpleNamespace())


@pytest.mark.parametrize("parameter", [None,0,-1,"invalid",True])
def test_invalid_parameters_do_not_generate_approximate_data(parameter):
    with pytest.raises(ValueError,match="SYNTHETIC_INPUT_INVALID"):
        renko_rows(request()["bars"], "Traditional", parameter)
