from dataclasses import replace

import pytest

from candlescope_plugin_sdk import AnalyzeRequest, Bar, ExecuteBatchRequest, MarketContext
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin


SOURCE = '//@version=6\nindicator("SMA")\nplot(ta.sma(close, 2))\n'
CONTEXT = MarketContext("binance", "spot", "BTCUSDT", "1m")


def bar(index, close, closed=True):
    return Bar(time=1700000000 + index * 60, open=close, high=close + 1,
               low=close - 1, close=close, volume=10, is_closed=closed)


def execute(plugin, bars, *, source=SOURCE, identity="subscription-a", params=None):
    request = ExecuteBatchRequest(source=source, context=CONTEXT, bars=tuple(bars),
                                  params=params or {},
                                  options={"pineSessionId": identity} if identity else {})
    result = plugin.execute_batch(request)
    assert result.ok, result.diagnostics
    return result


def values(result):
    return [point.value for point in result.output.series[0].points]


def test_real_wheel_forming_replace_confirm_append_and_history_correction():
    plugin = PineCompatRuntimePlugin()
    seed = [bar(0, 10), bar(1, 20)]
    initial = execute(plugin, seed)
    assert initial.meta["sessionReset"] is True
    forming = execute(plugin, seed + [bar(2, 30, False)])
    assert values(forming)[-1] == 25
    assert forming.meta["incremental"] is True
    replaced = execute(plugin, seed + [bar(2, 40, False)])
    assert values(replaced)[-1] == 30
    confirmed = execute(plugin, seed + [bar(2, 40)])
    assert values(confirmed) == values(replaced)
    appended_bars = seed + [bar(2, 40), bar(3, 50)]
    appended = execute(plugin, appended_bars)
    assert values(appended) == values(execute(plugin, appended_bars, identity=None))
    corrected = [bar(0, 12)] + appended_bars[1:]
    replayed = execute(plugin, corrected)
    assert replayed.meta["sessionReset"] is True
    assert values(replayed) == values(execute(plugin, corrected, identity=None))


def test_native_varip_isolated_between_subscriptions_and_survives_replacements():
    source = ('//@version=6\nindicator("ticks")\nvarip int n = 0\n'
              'n += 1\nplot(n)\n')
    plugin = PineCompatRuntimePlugin()
    bars = [bar(0, 10), bar(1, 20, False)]
    first = execute(plugin, bars, source=source)
    second = execute(plugin, bars, source=source)
    other = execute(plugin, bars, source=source, identity="subscription-b")
    assert values(second)[-1] == values(first)[-1] + 1
    assert values(other) == values(first)
    plugin.shutdown()
    assert plugin._sessions.entries == {}


def test_stateless_forming_and_changed_parameters_do_not_reuse_state():
    source = '//@version=6\nindicator("x")\nx=input.int(2)\nplot(close*x)\n'
    plugin = PineCompatRuntimePlugin()
    analysis = plugin.analyze(AnalyzeRequest(source=source, context=CONTEXT))
    assert analysis.ok and analysis.meta["hostRequirements"]["schemaVersion"] == 2
    key = str(analysis.inputs[0]["callSiteId"])
    bars = [bar(0, 10), bar(1, 20, False)]
    first = execute(plugin, bars, source=source)
    changed = execute(plugin, bars, source=source, params={key: 3})
    assert values(first)[-1] == 40 and values(changed)[-1] == 60
    assert changed.meta["sessionReset"] is True
    independent = execute(plugin, bars, source=source, identity=None)
    assert values(independent)[-1] == 40
    assert independent.meta["sessionRetained"] is False


def test_session_eviction_rebases_and_invalid_bars_fail_without_hidden_advance():
    plugin = PineCompatRuntimePlugin()
    plugin._sessions.capacity = 1
    execute(plugin, [bar(0, 10)])
    execute(plugin, [bar(0, 10)], identity="b")
    assert execute(plugin, [bar(0, 10)]).meta["sessionReset"] is True
    bad = ExecuteBatchRequest(source=SOURCE, context=CONTEXT,
                              bars=(bar(0, 10), replace(bar(1, 20), high=1)),
                              options={"pineSessionId": "subscription-a"})
    assert not plugin.execute_batch(bad).ok
    assert execute(plugin, [bar(0, 10), bar(1, 20)]).meta["sessionReset"] is True


def test_engine_version_drift_is_rejected(monkeypatch):
    from candlescope_plugin_pine_compat import runtime
    monkeypatch.setattr(runtime, "_engine_version", lambda: "0.2.0")
    with pytest.raises(RuntimeError, match="requires"):
        PineCompatRuntimePlugin().describe()


def test_gradient_fill_fails_explicitly_instead_of_losing_visual_information():
    source = ('//@version=6\nindicator("gradient")\n'
              'a=plot(close+2)\nb=plot(close-2)\n'
              'fill(a,b,close+1,close-1,color.green,color.red)\n')
    plugin = PineCompatRuntimePlugin()
    result = plugin.execute_batch(ExecuteBatchRequest(
        source=source, context=CONTEXT, bars=(bar(0, 10),),
        options={"pineSessionId": "gradient"}))
    assert not result.ok
    assert any(d.code == "PINE_HOST_CAPABILITY_UNSUPPORTED" for d in result.diagnostics)
    assert "gradient" not in plugin._sessions.entries


def test_time_close_uses_chart_interval_and_resource_errors_are_reported():
    plugin = PineCompatRuntimePlugin()
    result = execute(plugin, [bar(0, 10)], source=(
        '//@version=6\nindicator("close time")\nplot(time_close-time)\n'))
    assert values(result) == [60_000]
    large = plugin.execute_batch(ExecuteBatchRequest(
        source=('//@version=6\nindicator("budget")\na=array.new_float(100000,1.0)\n'
                'for i=0 to 99\n    b=array.copy(a)\nplot(close)\n'),
        context=CONTEXT, bars=(bar(0, 10),)))
    assert not large.ok
    assert any(d.code == "E_RESOURCE_BUDGET" for d in large.diagnostics)
