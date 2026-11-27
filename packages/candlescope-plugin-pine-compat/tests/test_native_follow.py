"""Pine FOLLOW sessions give exactly the FIXED run of the same request (ADR-BACKTEST-015 O1, B-157a).

Each rebuild of a followed strategy is compared with ``native_strategy.execute`` over the
same request, the path an ordinary native run takes.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys

import pytest

import pine_compat
from candlescope_plugin_pine_compat import native_follow
from candlescope_plugin_pine_compat.native_follow import FOLLOW_CONTRACT, open_follow
from candlescope_plugin_pine_compat.native_strategy import describe, execute

pytestmark = pytest.mark.skipif(not native_follow.available(), reason="engine without HistoricalSession.extend")

ORDERS = '''//@version=6
strategy("Orders", overlay=true, initial_capital=10000, pyramiding=2, default_qty_type=strategy.percent_of_equity, default_qty_value=20, commission_type=strategy.commission.percent, commission_value=0.05)
r = ta.rsi(close, 5)
if r < 35
    strategy.entry("L", strategy.long, limit=close - 0.3)
if r > 65
    strategy.entry("S", strategy.short, stop=close - 0.2)
strategy.exit("XL", "L", profit=80, loss=60)
strategy.exit("XS", "S", trail_points=50, trail_offset=20)
plot(r)
'''


def rows(count, seed=0):
    out = []
    for index in range(count):
        close = 100 + 10 * math.sin((index + seed) / 7.0) + ((index * 7 + seed) % 5) * 0.3
        open_ = close - 0.5 if index % 2 else close + 0.5
        out.append({"time": 1_700_000_000 + index * 60, "open": open_, "high": max(open_, close) + 1,
                    "low": min(open_, close) - 1, "close": close, "volume": 10.0})
    return out


def request(bars, source=ORDERS, **extra):
    """A request shaped like the host's native wire for a chart Pine strategy."""
    clocks = [bar["time"] * 1000 + 59_999 for bar in bars]
    return {"source": source, "parameters": {}, "bars": bars, "contexts": [], "interval": "1m", "libraries": {},
            "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"}, "magnifier": None,
            "execution_times": clocks, "host_inputs": {"executionTimes": clocks}, "clock_policy": "historical-bar-close",
            **extra}


def test_each_rebuild_equals_the_fixed_run_of_its_request():
    bars = rows(400)
    session = open_follow({**request(bars[:250]), "operation": "open", "follow_contract": FOLLOW_CONTRACT})
    assert session is not None
    first = session.advance(250)
    assert first == execute(request(bars[:250]))
    assert first["trades"], "fixture must trade"
    for end in (251, 252, 260, 330, 400):
        assert session.extend({**request(bars[:end]), "operation": "extend"}) == execute(request(bars[:end]))


@pytest.mark.parametrize("source, reason", [
    ('//@version=6\nstrategy("Last")\nif barstate.islast\n    strategy.entry("L", strategy.long)\nplot(close)\n', "last bar"),
    ('//@version=6\nstrategy("Index")\nplot(last_bar_index - bar_index)\n', "last bar"),
    ('//@version=6\nstrategy("Clock")\nplot(timenow)\n', "last bar"),
    ('//@version=6\nstrategy("Window", calc_bars_count=50)\nplot(close)\n', "calc_bars_count"),
    ('//@version=6\nstrategy("Other")\nplot(request.security(syminfo.tickerid, "5", close))\n', "requests"),
])
def test_scripts_whose_incremental_result_could_differ_keep_full_rebuilds(source, reason):
    wire = request(rows(30), source=source)
    assert native_follow.unsupported_reason(wire, pine_compat.compile_script(source)) is not None
    assert open_follow({**wire, "operation": "open", "follow_contract": FOLLOW_CONTRACT}) is None


def test_frozen_inputs_that_would_have_to_grow_keep_full_rebuilds():
    program = pine_compat.compile_script(ORDERS)
    bars = rows(30)
    assert native_follow.unsupported_reason(request(bars, magnifier={"schemaVersion": 1, "chartBars": []}), program)
    assert native_follow.unsupported_reason(request(bars, contexts=[{"symbol": "X", "timeframe": "5", "bars": []}]), program)
    assert native_follow.unsupported_reason(request(bars, host_inputs={"sessionWindows": [[0, 1]]}), program)
    assert native_follow.unsupported_reason(request(bars), program) is None


def test_a_request_that_does_not_continue_the_history_is_refused():
    bars = rows(60)
    session = open_follow(request(bars[:40]))
    session.advance(40)
    changed = [dict(bar) for bar in bars[:50]]
    changed[10]["close"] += 1
    for wire in (request(changed),                                  # an earlier bar was revised
                 request(bars[:40]),                                # nothing new
                 {**request(bars[:50]), "parameters": {"x": 1}},    # other inputs
                 {**request(bars[:50]), "source": ORDERS + "plot(open)\n"}):
        with pytest.raises(ValueError, match="NATIVE_FOLLOW_MISMATCH"):
            session.extend(wire)
    # A refused request changes nothing.
    assert session.extend(request(bars[:50])) == execute(request(bars[:50]))


def test_the_runtime_advertises_follow_sessions():
    assert describe()["follow_session"] == FOLLOW_CONTRACT


def test_the_session_server_extends_over_its_wire_protocol():
    identity = describe()
    process = subprocess.Popen([sys.executable, "-I", "-m", "candlescope_plugin_pine_compat.native_session"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    bars = rows(120)

    def send(payload):
        process.stdin.write(json.dumps({**payload, "protocol": identity["protocol"], "identity": identity}) + "\n")
        process.stdin.flush()
        return json.loads(process.stdout.readline())

    try:
        opened = send({**request(bars[:100]), "operation": "open", "follow_contract": FOLLOW_CONTRACT})
        assert opened["ok"] and opened["supported"] is True
        first = send({"operation": "advance", "target": 100})
        assert first["ok"] and first["trades"] == execute(request(bars[:100]))["trades"]
        extended = send({**request(bars), "operation": "extend"})
        assert extended["ok"], extended
        expected = execute(request(bars))
        assert {key: extended[key] for key in expected} == expected
    finally:
        process.stdin.close()
        process.wait(timeout=10)
