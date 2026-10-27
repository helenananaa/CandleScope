"""Each evaluator request costs only its new rows, in both directions."""
import copy
import os
import threading
from types import SimpleNamespace

import pytest

from app.backtest import native_session
from app.backtest.native import PROTOCOL, encoded, invoke
from app.backtest.native_session import PREFIX_REPLY_CONTRACT, SessionWorker


def bar(i):
    return {"time": 60 * i, "open": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i, "close": 10.0 + i, "volume": 1.0}


def swing(i):
    price = 10.0 + i % 7
    return {"time": 60 * i, "open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1.0}


def account(i, equity=1000.0):
    return {"time": 60 * i, "position_size": 0.0, "position_avg_price": None, "equity": equity,
            "initial_capital": 1000.0, "netprofit": 0.0, "openprofit": 0.0}


def reply(base):
    return {"contract": PREFIX_REPLY_CONTRACT, "intent_base": base}


def transport(**identity):
    return SimpleNamespace(identity={"prefix_append": "candlescope.pine-prefix/2", **identity}, _prefix_state=None)


def send(worker, request):
    return SessionWorker._prefix_payload(worker, request)


def test_appends_send_only_new_rows_and_never_copy_the_history(monkeypatch):
    copied = []
    real = native_session.deepcopy
    monkeypatch.setattr(native_session, "deepcopy", lambda value: copied.append(value) or real(value))
    worker = transport()
    bars, accounts = [], []
    for i in range(60):
        bars.append(bar(i))
        accounts.append(account(i, 1000.0 + i))
        payload = send(worker, {"source": "s", "bars": bars[:i + 1], "accounts": accounts})
        if i == 0:
            assert "operation" not in payload
            continue
        assert payload == {"operation": "append_prefix", "prefix_base": i, "bars": [bars[i]],
                           "account_deltas": [{"time": 60 * i, "equity": 1000.0 + i}]}
    # Only the newest bar and account frame are ever snapshotted.
    assert copied and all(isinstance(value, dict) for value in copied)


def test_changed_history_is_sent_in_full_and_equal_rebuilt_rows_still_append():
    worker = transport()
    rows, frames = [bar(i) for i in range(3)], [account(i) for i in range(3)]
    assert "operation" not in send(worker, {"source": "s", "bars": rows, "accounts": frames})
    # Equal rows rebuilt by the caller are the same prefix.
    rows, frames = copy.deepcopy(rows) + [bar(3)], copy.deepcopy(frames) + [account(3)]
    assert send(worker, {"source": "s", "bars": rows, "accounts": frames})["prefix_base"] == 3
    # A replaced earlier bar is a correction.
    rows, frames = rows + [bar(4)], frames + [account(4)]
    rows[1] = {**rows[1], "close": 10.5}
    assert "operation" not in send(worker, {"source": "s", "bars": rows, "accounts": frames})
    rows, frames = rows + [bar(5)], frames + [account(5)]
    assert send(worker, {"source": "s", "bars": rows, "accounts": frames})["prefix_base"] == 5
    # An in-place change to the newest sent frame is still seen.
    frames[-1]["equity"] = 999.0
    rows, frames = rows + [bar(6)], frames + [account(6)]
    assert "operation" not in send(worker, {"source": "s", "bars": rows, "accounts": frames})
    # A changed frozen field resends everything.
    rows, frames = rows + [bar(7)], frames + [account(7)]
    assert "operation" not in send(worker, {"source": "t", "bars": rows, "accounts": frames})
    # A shorter or equal prefix is never an append.
    assert "operation" not in send(worker, {"source": "t", "bars": rows, "accounts": frames})
    assert "operation" not in send(worker, {"source": "t", "bars": rows[:-1], "accounts": frames[:-1]})


def test_reply_requests_ride_along_and_open_pass_groups_resend_the_prefix():
    worker = transport(prefix_passes="candlescope.pine-prefix-passes/1")
    rows, frames, passes = [bar(0)], [account(0)], [[{"confirmed": False}]]
    first = send(worker, {"source": "s", "bars": rows, "accounts": frames, "execution_passes": passes,
                          "prefix_reply": reply(0)})
    assert first["prefix_reply"] == reply(0) and "operation" not in first
    # An unconfirmed final pass may still be followed by another pass.
    passes[0].append({"confirmed": True})
    rows, frames, passes = rows + [bar(1)], frames + [account(1)], passes + [[{"confirmed": True}]]
    assert "operation" not in send(worker, {"source": "s", "bars": rows, "accounts": frames, "execution_passes": passes,
                                            "prefix_reply": reply(1)})
    rows, frames, passes = rows + [bar(2)], frames + [account(2)], passes + [[{"confirmed": True}]]
    payload = send(worker, {"source": "s", "bars": rows, "accounts": frames, "execution_passes": passes,
                            "prefix_reply": reply(7)})
    assert payload["operation"] == "append_prefix" and payload["prefix_base"] == 2
    assert payload["execution_passes"] == [[{"confirmed": True}]] and payload["prefix_reply"] == reply(7)
    # Pass groups changed in place before their bar is resent are seen too.
    passes[-1].append({"confirmed": True})
    rows, frames, passes = rows + [bar(3)], frames + [account(3)], passes + [[{"confirmed": True}]]
    assert "operation" not in send(worker, {"source": "s", "bars": rows, "accounts": frames, "execution_passes": passes})


def test_rebuilt_newest_row_is_compared_alone():
    worker = transport()
    rows, frames = [bar(i) for i in range(3)], [account(i) for i in range(3)]
    send(worker, {"source": "s", "bars": rows, "accounts": frames})
    compared = []

    class Row(dict):
        def __eq__(self, other):
            compared.append(self["time"])
            return dict.__eq__(self, other)

        __hash__ = None

    rows = rows[:2] + [Row(rows[2]), bar(3)]
    assert send(worker, {"source": "s", "bars": rows, "accounts": frames + [account(3)]})["prefix_base"] == 3
    assert set(compared) == {120}


def test_chart_provider_keeps_encoded_pass_groups_of_settled_bars():
    from app.backtest.strategy.pine_engine import PineEngineProvider
    from app.backtest.strategy.pine_schedule import encode
    provider = PineEngineProvider.__new__(PineEngineProvider)
    provider.execution_passes, provider.execution_contexts, provider.encoded_schedule = [], [], []
    for index in range(4):
        provider.execution_passes.append([{"confirmed": True, "bar": index}])
        provider.execution_contexts.append([{"bar_state": "historical", "trigger": "bar_close"}])
        previous = list(provider.encoded_schedule)
        schedule = provider._schedule()
        assert schedule == encode(provider.execution_passes, provider.execution_contexts)
        assert all(a is b for a, b in zip(schedule[:-1], previous))
    # Another pass on the newest bar re-encodes only that bar's group.
    provider.execution_passes[-1].append({"confirmed": True, "bar": 3})
    provider.execution_contexts[-1].append({"bar_state": "historical", "trigger": "order_fill"})
    previous = list(provider.encoded_schedule)
    schedule = provider._schedule()
    assert schedule == encode(provider.execution_passes, provider.execution_contexts)
    assert all(a is b for a, b in zip(schedule[:-1], previous[:-1])) and schedule[-1] is not previous[-1]


SOURCE = """//@version=6
strategy("compact")
if bar_index % 5 == 1
    strategy.entry("L", strategy.long, qty=1)
if bar_index % 5 == 3
    strategy.close("L")
plot(close)
plot(ta.sma(close, 3))
"""


@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"), reason="requires installed Pine candidate")
@pytest.mark.parametrize("module", ["chart_strategy", "external_strategy"])
def test_real_compact_replies_rebuild_the_complete_evaluator_result(module):
    from app.backtest.strategy.pine_engine import plugin
    runtime = plugin()
    runtime["command"][-1] = "candlescope_plugin_pine_compat." + module
    identity = invoke(runtime, {"operation": "describe"})["identity"]
    assert identity["prefix_reply"] == PREFIX_REPLY_CONTRACT
    wire = {"protocol": PROTOCOL, "identity": identity, "source": SOURCE, "parameters": {},
            "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"}}
    cancelled = threading.Event()
    compact = SessionWorker(runtime, wire, cancelled, evaluator=True)
    full = SessionWorker(runtime, wire, cancelled, evaluator=True)
    bars, accounts, history = [], [], []
    compact_bytes = full_bytes = 0
    try:
        for count in range(1, 81):
            bars.append(swing(count))
            accounts.append(account(count))
            request = {**wire, "bars": bars, "accounts": accounts}
            expected = full.request(request, cancelled)
            result = compact.request({**request, "prefix_reply": reply(len(history))}, cancelled)
            assert result["prefix_reply"] == PREFIX_REPLY_CONTRACT
            assert "raw_output" not in result and "graphics" not in result
            assert result["intent_base"] == (len(history) if count > 1 else 0)
            history = history[:result["intent_base"]] + result["intents"]
            assert history == expected["intents"]
            assert ({key: value for key, value in result.items() if key not in {"intents", "intent_base", "prefix_reply"}}
                    == {key: value for key, value in expected.items() if key not in {"intents", "graphics", "raw_output"}})
            # The transport restores the bound identity on both replies.
            compact_bytes += len(encoded({key: value for key, value in result.items() if key != "identity"}))
            full_bytes += len(encoded({key: value for key, value in expected.items() if key != "identity"}))
        assert len(history) > 20
        assert compact_bytes < full_bytes / 5
        # The final full reply on the same worker equals a fresh full request.
        bars.append(swing(81))
        accounts.append(account(81))
        request = {**wire, "bars": bars, "accounts": accounts}
        assert compact.request(request, cancelled) == invoke(runtime, request)
        # A corrected prefix is resent in full; the evaluator then vouches for nothing.
        bars.append(swing(82))
        accounts.append(account(82))
        bars[3] = {**bars[3], "close": bars[3]["close"] + 0.5}
        request = {**wire, "bars": bars, "accounts": accounts}
        corrected = compact.request({**request, "prefix_reply": reply(len(history))}, cancelled)
        assert corrected["intent_base"] == 0
        assert corrected["intents"] == invoke(runtime, request)["intents"]
    finally:
        compact.close()
        full.close()
