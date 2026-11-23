from dataclasses import replace
import pytest
import pine_compat
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, MarketContext
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin

pytestmark = pytest.mark.skipif(getattr(pine_compat, 'ORDERED_CHART_INPUT_CONTRACT', None) != 'ordered-chart-input/1',
    reason='requires the ordered chart source-build engine')


def request(values=(102,104,106), closed=(True,False,False)):
    return ExecuteBatchRequest(source='''//@version=6
indicator("chart input")
plot(ta.sma(close, 2))
plot(time)
plot(bar_index)
plot(barstate.isconfirmed ? 1 : 0)
plot(barstate.islast ? 1 : 0)
plot(barstate.islastconfirmedhistory ? 1 : 0)
''', context=MarketContext('binance','spot','BTCUSDT','1m'),
        bars=tuple(Bar(time=i+1,open=c-2,high=c,low=c-2,close=c,volume=2,is_closed=closed[i]) for i,c in enumerate(values)),
        options={'chartInput': {'contract':'candlescope.chart-indicator-input/1', 'transform':'renko',
            'sourceTimes':[1700000040]*len(values), 'closed':list(closed)}})


def values(result):
    assert result.ok, result.diagnostics
    return [[point.value for point in line.points] for line in result.output.series]


def test_native_chart_same_clock_advances_history_and_preserves_preview_states():
    plugin = PineCompatRuntimePlugin()
    result = plugin.execute_batch(request())
    plots = values(result)
    assert plots == [[103,105], [1700000040000]*3, [0,1,2], [1,0,0], [0,0,1], [1,0,0]]
    assert [point.time for point in result.output.series[0].points] == [2,3]
    assert not plugin._sessions.entries and not plugin._windows
    rewind = plugin.execute_batch(request((102,108), (True,False)))
    assert values(rewind)[0] == [105]
    assert values(plugin.execute_batch(request())) == plots


def test_native_chart_explicit_requested_context_uses_real_source_clock():
    req = request(closed=(True,True,True))
    req = replace(req, source='''//@version=6
indicator("explicit context")
plot(close)
plot(request.security("BINANCE:ETHUSDT", "1", close))
''', options={**req.options, 'pineRequestBars': {'BINANCE:ETHUSDT:1': [
        dict(time=t*1000,open=c,high=c,low=c,close=c,volume=1)
        for t,c in [(1699999980,77),(1700000040,88),(1700000100,999)]]}})
    plots=values(PineCompatRuntimePlugin().execute_batch(req))
    assert plots[0] == [102,104,106]
    assert plots[1] == [88,88,88]


def test_invalid_clock_and_candle_sessions_fail_closed():
    req=request()
    bad=replace(req,options={**req.options,'chartInput':{**req.options['chartInput'],'sourceTimes':[10,9,8]}})
    assert not PineCompatRuntimePlugin().execute_batch(bad).ok
    bad=replace(req, options={**req.options,'pineSessionId':'not-an-ordinal-session'})
    assert not PineCompatRuntimePlugin().execute_batch(bad).ok
    with pytest.raises(ValueError,match='duplicate bar time'):
        pine_compat.run_script('//@version=6\nindicator("ordinary")\nplot(close)',
            [dict(time=60000,open=1,high=1,low=1,close=1,volume=1)]*2)
