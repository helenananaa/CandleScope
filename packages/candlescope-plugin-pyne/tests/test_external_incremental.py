"""Actual engine callback/state, request visibility and protocol regressions."""
from copy import deepcopy

import pytest

from candlescope_plugin_pyne.external_incremental import CONTRACT, Evaluator
from candlescope_plugin_pyne.external_strategy import execute, settings_for


SOURCE = '''def init(ctx):
    ctx.strategy.configure()
def on_bar(ctx, bar):
    r = "TEST?chart=renko&style=Traditional&param=1"
    ctx.plot("Brick", ctx.request.security(r, ctx.timeframe.period, "close"))
    ctx.plot("Previous", ctx.request.security(r, ctx.timeframe.period, "close[1]"))
    ctx.plot("Account", ctx.strategy.equity)
    ctx.plot("Last", ctx.last_bar_index)
    ctx.plot("IsLast", int(bar.is_last))
    ctx.plot("History", int(bar.is_history))
    if ctx.bar_index == 1:
        ctx.strategy.entry("L", ctx.strategy.long, qty=1)
    if ctx.bar_index == 3:
        ctx.strategy.close("L")
'''


def wire(source=SOURCE):
    bars = [dict(time=1700000040+i*60, open=c, high=c+.2, low=c-.2, close=c, volume=10)
            for i, c in enumerate([100.4,103.8,106.9,101.6,104.8,100.1])]
    return {"protocol": "test", "identity": {}, "context": {"symbol": "TEST", "timeframe": "1"},
            "source": source, "bars": bars, "contexts": [], "accounts": [
                dict(time=b["time"], position_size=0, position_avg_price=None, equity=1000-i,
                     initial_capital=1000, netprofit=-i, openprofit=0) for i, b in enumerate(bars)]}


def delta(req, index):
    base = deepcopy(req) if not index else {"protocol": req["protocol"], "identity": req["identity"], "contexts": []}
    return {**base, "bars": req["bars"][index:index+1], "accounts": req["accounts"][index:index+1],
            "evaluation": {"contract": CONTRACT, "horizon": len(req["bars"]), "cursor": index}}


def test_each_bar_runs_once_with_fixed_horizon_and_real_account_frames():
    req = wire()
    reference = execute(req)
    evaluator = Evaluator(execute, settings_for)
    intents = []
    for index in range(len(req["bars"])):
        result = evaluator(delta(req, index))
        assert result["evaluation_contract"] == CONTRACT
        intents.extend(result["intents"])
        assert len(evaluator.session.provider.contexts["TEST", "1"]) == index + 1
        if index < len(req["bars"]) - 1:
            assert result["graphics"] == []
    assert intents == reference["intents"]
    assert result["graphics"] == reference["graphics"]
    assert "strategy" not in result["raw_output"]


@pytest.mark.parametrize("change", ["cursor", "horizon", "source", "past_time", "account", "future_context"])
def test_changed_history_configuration_and_future_data_fail_closed(change):
    req = wire()
    req["contexts"] = [{"symbol": "OTHER", "timeframe": "5", "bars": []}]
    evaluator = Evaluator(execute, settings_for)
    evaluator(delta(req, 0))
    step = delta(req, 1)
    if change == "cursor": step["evaluation"]["cursor"] = 0
    if change == "horizon": step["evaluation"]["horizon"] += 1
    if change == "source": step["source"] = "pass"
    if change == "past_time": step["bars"][0]["time"] = step["accounts"][0]["time"] = req["bars"][0]["time"]
    if change == "account": step["accounts"][0]["equity"] = float("nan")
    if change == "future_context":
        step["contexts"] = [{"symbol": "OTHER", "timeframe": "5", "offset": 0, "bars": [req["bars"][-1]]}]
    with pytest.raises((ValueError, RuntimeError)):
        evaluator(step)


def test_batch_evaluator_keeps_legacy_prefix_contract():
    req = wire('strategy("Batch")\nplot(close, "Close")\n')
    evaluator = Evaluator(execute, settings_for)
    result = evaluator({**req, "evaluation": {"contract": CONTRACT, "horizon": 6, "cursor": 0}})
    assert result["evaluation_contract"] == "historical-prefix/1"
    assert result["graphics"] == execute(req)["graphics"]


def test_higher_period_is_absent_until_close_and_matches_full_history():
    req = wire(SOURCE.replace('    ctx.plot("Account", ctx.strategy.equity)',
        '    ctx.plot("Higher", ctx.request.security("OTHER", "5", "close"))'))
    higher = {**req["bars"][0], "open": 700, "high": 702, "low": 698, "close": 701}
    req["contexts"] = [{"symbol": "OTHER", "timeframe": "5", "bars": [higher]}]
    expected = execute(req)
    evaluator = Evaluator(execute, settings_for)
    for index in range(6):
        step = delta(req, index)
        step["contexts"] = [{"symbol": "OTHER", "timeframe": "5", "bars": [higher] if index == 4 else []}]
        if index:
            step["contexts"][0]["offset"] = int(index > 4)
        result = evaluator(step)
    assert result["graphics"] == expected["graphics"]


def test_state_updates_once_and_final_flag_is_only_at_frozen_endpoint():
    req = wire('''def init(ctx):
    ctx.strategy.configure()
def on_bar(ctx, bar):
    count = ctx.state("count", 0)
    count.value += 1
    ctx.plot("Calls", count.value)
    if bar.is_last:
        ctx.strategy.entry("Final", ctx.strategy.long, qty=1)
''')
    evaluator = Evaluator(execute, settings_for)
    for index in range(6):
        result = evaluator(delta(req, index))
        if index < 5:
            assert result["intents"] == []
    assert [p["value"] for p in result["graphics"][0]["data"]] == [1, 2, 3, 4, 5, 6]
    assert result["intents"][0]["bar_index"] == 5
