"""Compact evaluator replies carry only new intents and never the chart output."""

import pine_compat
import pytest

from candlescope_plugin_pine_compat import external_strategy as adapter
from candlescope_plugin_pine_compat.prefix_transport import REPLY_CONTRACT

pytestmark = pytest.mark.skipif(
    not hasattr(pine_compat.Program, "external_session"),
    reason="requires isolated incremental engine candidate",
)

TRADING = """
if bar_index % 5 == 1
    strategy.entry("L", strategy.long, qty=1)
if bar_index % 5 == 3
    strategy.close("L")
plot(close)
plot(ta.sma(close, 3))
"""


def wire(source):
    return {
        "source": '//@version=6\nstrategy("reply")\n' + source,
        "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"},
        "parameters": {},
    }


def data(i):
    bar = {"time": 1700000000 + i * 60, "open": 10 + i % 7, "high": 12 + i % 7,
           "low": 9 + i % 7, "close": 11 + i % 7, "volume": 1}
    account = {"time": bar["time"], "position_size": 0, "position_avg_price": None, "equity": 1000,
               "initial_capital": 1000, "netprofit": 0, "openprofit": 0}
    return bar, account


def reply(base):
    return {"contract": REPLY_CONTRACT, "intent_base": base}


def walk(request, count, *, compact_from=1, base=None, extra=None):
    """Grow one prefix bar by bar through the append transport."""
    bars, accounts, history, replies = [], [], [], []
    for i in range(count):
        bar, account = data(i)
        bars.append(bar)
        accounts.append(account)
        payload = ({**request, **(extra or {}), "bars": list(bars), "accounts": list(accounts)} if i == 0 else
                   {"operation": "append_prefix", "prefix_base": i, "bars": [bar], "accounts": [account]})
        compact = i >= compact_from
        if compact:
            payload["prefix_reply"] = reply(len(history) if base is None else base(history))
        result = adapter.execute(payload)
        replies.append(result)
        if compact:
            assert result["prefix_reply"] == REPLY_CONTRACT
            assert "raw_output" not in result and "graphics" not in result
            history = history[:result["intent_base"]] + result["intents"]
        else:
            assert "prefix_reply" not in result and "intent_base" not in result
            history = list(result["intents"])
    return bars, accounts, history, replies


def full(request, bars, accounts, extra=None):
    return adapter.execute({**request, **(extra or {}), "bars": bars, "accounts": accounts})


def test_retained_session_replies_with_only_new_intents_and_rebuilds_the_full_history():
    request = wire(TRADING)
    bars, accounts, history, replies = walk(request, 40)
    expected = full(request, bars, accounts)
    assert history == expected["intents"] and len(history) > 10
    # After the first bar the session vouches for every earlier intent.
    assert all(item["intent_base"] > 0 for item in replies[2:])
    assert sum(len(item["intents"]) for item in replies[1:]) == len(history) - len(replies[0]["intents"])
    # Contract fields are unchanged; only the output and earlier intents are left out.
    assert ({key: value for key, value in replies[-1].items() if key not in {"intents", "intent_base", "prefix_reply"}}
            == {key: value for key, value in expected.items() if key not in {"intents", "graphics", "raw_output"}})


def test_final_full_reply_after_compact_appends_equals_a_full_request():
    request = wire(TRADING)
    bars, accounts, history, _ = walk(request, 25)
    bar, account = data(25)
    last = adapter.execute({"operation": "append_prefix", "prefix_base": 25, "bars": [bar], "accounts": [account]})
    assert last == full(request, [*bars, bar], [*accounts, account])
    assert last["intents"][:len(history)] == history


def test_an_unknown_base_gets_every_intent_from_zero():
    request = wire(TRADING)
    bars, accounts, history, replies = walk(request, 30, base=lambda history: max(0, len(history) - 1))
    assert all(item["intent_base"] == 0 for item in replies[1:])
    assert history == full(request, bars, accounts)["intents"]


@pytest.mark.parametrize("value", [{"contract": "other", "intent_base": 0}, {"contract": REPLY_CONTRACT, "intent_base": -1},
                                   {"contract": REPLY_CONTRACT, "intent_base": True}, {"contract": REPLY_CONTRACT}])
def test_invalid_reply_requests_fail_without_retaining_the_prefix(value):
    request = wire(TRADING)
    bar, account = data(0)
    with pytest.raises(ValueError, match="PINE_PREFIX_INVALID"):
        adapter.execute({**request, "bars": [bar], "accounts": [account], "prefix_reply": value})
    with pytest.raises(ValueError, match="PINE_PREFIX_MISMATCH"):
        adapter.execute({"operation": "append_prefix", "prefix_base": 1, "bars": [bar], "accounts": [account]})


def test_a_reply_request_is_never_stored_with_the_retained_prefix():
    request = wire(TRADING)
    bar, account = data(0)
    adapter.execute({**request, "bars": [bar], "accounts": [account], "prefix_reply": reply(0)})
    assert "prefix_reply" not in adapter._prefix.request
    bar, account = data(1)
    result = adapter.execute({"operation": "append_prefix", "prefix_base": 1, "bars": [bar], "accounts": [account]})
    assert "raw_output" in result and "intent_base" not in result


@pytest.mark.skipif(getattr(pine_compat, "EXTERNAL_COMPACT_APPEND_SCHEMA_VERSION", 0) != 1,
                    reason="requires a core with compact external appends")
def test_a_capable_core_never_builds_chart_output_for_compact_replies():
    class Spy:
        def __init__(self, native):
            self.native, self.calls = native, []

        def append(self, *args, **kwargs):
            self.calls.append(kwargs.get("snapshot", True))
            return self.native.append(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.native, name)

    request = wire(TRADING)
    bars, accounts = [], []
    for i in range(12):
        bar, account = data(i)
        bars.append(bar)
        accounts.append(account)
        if i == 0:
            history = list(adapter.execute({**request, "bars": [bar], "accounts": [account]})["intents"])
            spy = adapter._session = Spy(adapter._session)
            continue
        result = adapter.execute({"operation": "append_prefix", "prefix_base": i, "bars": [bar],
                                  "accounts": [account], "prefix_reply": reply(len(history))})
        history = history[:result["intent_base"]] + result["intents"]
    assert spy.calls == [False] * 11
    assert history == full(request, bars, accounts)["intents"]


def test_full_prefix_reruns_always_reply_from_zero():
    # Dataset-end builtins repaint growing prefixes, so nothing is retained.
    request = wire(TRADING + "plot(last_bar_index)\n")
    bars, accounts, history, replies = walk(request, 12)
    assert adapter._session is None
    assert all(item["intent_base"] == 0 for item in replies[1:])
    assert history == full(request, bars, accounts)["intents"]


def test_fixed_history_replies_with_new_intents_against_the_frozen_plan():
    request = wire("""
if barstate.islast or bar_index % 4 == 2
    strategy.entry("L", strategy.long, qty=1)
if bar_index % 4 == 3
    strategy.close("L")
plot(close)
""")
    plan = [data(i)[0] for i in range(20)]
    extra = {"fixed_history_contract": "candlescope.pine-fixed-history/1", "planned_bars": plan}
    bars, accounts, history, replies = walk(request, 20, extra=extra)
    assert adapter._fixed_history is not None
    assert all(item["intent_base"] > 0 for item in replies[4:])
    expected = full(request, bars, accounts, extra)
    assert history == expected["intents"]
    assert any(item["bar_index"] == 19 for item in history)
