from copy import deepcopy

import pytest

from candlescope_plugin_pine_compat.external_strategy import execute
from candlescope_plugin_pine_compat.request_updates import CONTRACT, engine_updates


def request(count):
    bars = [dict(time=index*60,open=1,high=1,low=1,close=1,volume=1) for index in range(count)]
    accounts = [dict(time=bar["time"],position_size=0,position_avg_price=None,
                     initial_capital=1000,equity=1000,netprofit=0,openprofit=0) for bar in bars]
    updates = [dict(observed_at_ms=(index+1)*60_000-1,updates=[dict(symbol="B",timeframe="1",kind="confirmed",
        available_at_ms=(index+1)*60_000-1,bar={**bar,"open":(index+1)*100,"high":(index+1)*100,"low":(index+1)*100,"close":(index+1)*100})])
        for index,bar in enumerate(bars)]
    return dict(source='//@version=6\nstrategy("observed")\nx=request.security("B","1",ta.cum(close))\nplot(x)\nif x>250\n    strategy.entry("L",strategy.long,qty=1)',
        context=dict(symbol="A",timeframe="1",metadata=dict(priceTickSize=".1",currency="USD")),
        contexts=[dict(symbol="B",timeframe="1",bars=[])],bars=bars,accounts=accounts,
        request_update_contract=CONTRACT,request_updates=updates)


def test_closed_update_groups_use_milliseconds_and_keep_public_bar_only_intents():
    first = execute(request(1))
    assert first["raw_output"]["plots"][0]["values"]==[100]
    value=request(2)
    result=execute(dict(operation="append_prefix",prefix_base=1,bars=value["bars"][1:],
                        accounts=value["accounts"][1:],request_updates=value["request_updates"][1:]))
    assert result["request_update_contract"]==CONTRACT
    assert result["raw_output"]["plots"][0]["values"]==[100,300]
    assert result["intents"] and all("pass_index" not in intent for intent in result["intents"])
    assert result==execute(value)


def test_failed_append_cannot_reuse_an_unacknowledged_prefix():
    execute(request(1))
    value=request(2)
    delta=dict(operation="append_prefix",prefix_base=1,bars=value["bars"][1:],accounts=value["accounts"][1:],
               request_updates=deepcopy(value["request_updates"][1:]))
    delta["request_updates"][0]["updates"][0]["available_at_ms"]+=1
    with pytest.raises(ValueError,match="future"):
        execute(delta)
    with pytest.raises(ValueError,match="prefix differs"):
        execute({**delta,"request_updates":value["request_updates"][1:]})
    assert execute(value)["raw_output"]["plots"][0]["values"]==[100,300]


@pytest.mark.parametrize("change", [dict(time=True),dict(time=1.5),dict(extra=1)])
def test_update_bar_transport_is_exact(change):
    item=request(1)["request_updates"][0]["updates"][0]
    item["bar"].update(change)
    with pytest.raises(ValueError,match="exact bar"):
        engine_updates([item])


def test_nonempty_initial_context_cannot_preload_future_requested_bars():
    value=request(1)
    value["contexts"][0]["bars"]=value["bars"]
    with pytest.raises(ValueError,match="initial requested contexts must be empty"):
        execute(value)


def test_requested_update_contract_requires_explicit_negotiation():
    value=request(1)
    del value["request_update_contract"]
    with pytest.raises(ValueError,match="not negotiated"):
        execute(value)
