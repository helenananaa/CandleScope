"""Real installed-engine qualification. Never substitute provider stubs."""
from __future__ import annotations

import os
import sys
import json
import subprocess
import pytest
from app.backtest.native import invoke, PROTOCOL

PYTHON = os.environ.get("NATIVE_TEST_PYTHON", sys.executable)
pytestmark = pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PYTHON"), reason="set NATIVE_TEST_PYTHON to the qualified installed-plugin interpreter")
BARS = [{"time": 1_700_000_000 + i * 60, "open": value, "high": value + 1,
         "low": value - 1, "close": value, "volume": 100}
        for i, value in enumerate([10, 10, 10, 20, 20, 5, 5, 15, 15, 8])]
PINE = '''//@version=6
strategy("Native threshold", initial_capital=10000)
if close > 12
    strategy.entry("L", strategy.long, qty=2)
if close < 9
    strategy.close("L")
plot(close)
'''
PYNE = '''strategy("Native threshold", initial_capital=10000)
strategy.entry_when(close > 12, "L", strategy.long, qty=2)
strategy.close_when(close < 9, "L")
plot(close, "Close")
'''


def plugin(language):
    package = "pine_compat" if language == "pine" else "pyne"
    return {"command": [PYTHON, "-I", "-m", f"candlescope_plugin_{package}.native_strategy"],
            "plugin_id": "candlescope.pine-compat" if language == "pine" else "candlescope.pyne"}


def run(language, source, **kwargs):
    engine = plugin(language)
    description = invoke(engine, {"operation": "describe"})
    return invoke(engine, {"protocol": PROTOCOL, "identity": description["identity"],
                          "source": source, "bars": BARS, "parameters": {},
                          "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"}, **kwargs})


@pytest.mark.parametrize("language,source", [("pine", PINE), ("pyne", PYNE)])
def test_real_native_orders_equity_graphics_and_determinism(language, source):
    first = run(language, source)
    second = run(language, source)
    assert first == second
    assert first["orders"] and first["trades"]
    assert first["graphics"]
    assert len(first["equity"]) == len(BARS)
    assert first["execution_mode"] == "NATIVE"
    assert first["raw_output"]["strategy"]
    changed = run(language, source.replace("12", "200"))
    assert changed["orders"] != first["orders"]


def test_pyne_incremental_strategy_keeps_native_state():
    output = run("pyne", '''def init(ctx):
    ctx.strategy.configure(initial_capital=10000)

def on_bar(ctx, bar):
    if bar.close > 12 and ctx.strategy.position_size == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=2)
    if bar.close < 9:
        ctx.strategy.close("L")
''')
    assert output["orders"]
    assert len(output["equity"]) == len(BARS)


@pytest.mark.parametrize("language,source", [("pine", "//@version=6\nstrategy('bad')\nunknown()"),
                                            ("pyne", "strategy('bad')\nunknown()")])
def test_runtime_errors_are_failures(language, source):
    with pytest.raises(ValueError, match="rejected"):
        run(language, source)


def test_identity_mismatch_is_rejected():
    with pytest.raises(ValueError, match="rejected"):
        invoke(plugin("pine"), {"protocol": PROTOCOL, "identity": {}, "source": PINE})


def test_pine_named_parameters_change_real_orders_and_reject_unknown():
    source = PINE.replace("if close > 12", 'threshold = input.int(12, "Threshold")\nif close > threshold')
    assert run("pine", source)["orders"]
    assert not run("pine", source, parameters={"Threshold": 200})["orders"]
    with pytest.raises(ValueError, match="rejected") as error:
        run("pine", source, parameters={"Typo": 200})
    assert "UNKNOWN_OR_AMBIGUOUS" in str(error.value.details)


def test_pine_request_uses_only_supplied_frozen_context():
    source = PINE.replace("if close > 12", 'remote = request.security("BINANCE:ETHUSDT", "1", close)\nif remote > 12')
    with pytest.raises(ValueError, match="rejected"):
        run("pine", source)
    output = run("pine", source, contexts=[{"symbol": "BINANCE:ETHUSDT", "timeframe": "1", "bars": BARS}])
    assert output["trades"]


def test_pyne_request_uses_only_supplied_frozen_context():
    source = PYNE.replace('strategy.entry_when(close > 12', 'remote = request.security("BINANCE:ETHUSDT", "1", close)\nstrategy.entry_when(remote > 12')
    with pytest.raises(ValueError, match="rejected"):
        run("pyne", source)
    output = run("pyne", source, contexts=[{"symbol": "BINANCE:ETHUSDT", "timeframe": "1", "bars": BARS}])
    assert output["trades"]


def test_pine_magnifier_never_silently_falls_back():
    source = PINE.replace('initial_capital=10000', 'initial_capital=10000, use_bar_magnifier=true')
    with pytest.raises(ValueError, match="rejected"):
        run("pine", source)
    magnifier = {"schemaVersion": 1, "chartBars": [
        {"chartBarIndex": index, "bars": [dict(bar, time=bar["time"] + offset) for offset in (0,30)]}
        for index, bar in enumerate(BARS)]}
    assert run("pine", source, magnifier=magnifier)["orders"]


def test_native_margin_rejection_remains_an_engine_result():
    result = run("pine", PINE.replace("initial_capital=10000", "initial_capital=1, margin_long=100"))
    assert not result["orders"]
    assert result["diagnostics"]


@pytest.mark.parametrize("source", [PYNE, '''indicator("Incremental", mode="incremental")
def init(ctx):
    ctx.strategy.configure(initial_capital=10000)
def on_bar(ctx, bar):
    ctx.strategy.entry("L", ctx.strategy.long, qty=1, when=ctx.bar_index == 1)
    ctx.strategy.close("L", when=ctx.bar_index == 6)
'''])
def test_pyne_observer_does_not_change_native_report(source):
    result = run("pyne", source)
    code = '''import json,sys
from dataclasses import replace
import pyne_runtime as pn
from pyne_runtime.metadata import SymbolInfo,TimeframeInfo
from candlescope_plugin_pyne.host_policy import host_settings
r=json.load(sys.stdin)
settings=replace(host_settings(security_mode="safe"), timeout_seconds=None,
 syminfo=SymbolInfo.from_value("BINANCE:BTCUSDT"), timeframe=TimeframeInfo.from_value("1"))
result=pn.run(r["source"],r["bars"],settings=settings)
assert result.ok, result.error
print(json.dumps(result.output))
'''
    direct = subprocess.run([PYTHON, "-I", "-c", code], input=json.dumps({"source": source, "bars": BARS}),
                            text=True, encoding="utf-8", capture_output=True, check=True)
    assert result["raw_output"] == json.loads(direct.stdout)


def test_pine_time_units_are_milliseconds_in_engine_and_seconds_in_chart_records():
    result = run("pine", PINE + "\nplot(time)\n")
    assert result["graphics"][-1]["values"] == [bar["time"] * 1000 for bar in BARS]
    raw = result["raw_output"]["strategy"]["trades"]
    assert raw and len(raw) == len(result["trades"])
    for engine, chart in zip(raw, result["trades"], strict=True):
        assert chart["entryTime"] * 1000 == engine["entryTime"]
        assert chart["exitTime"] * 1000 == engine["exitTime"]
