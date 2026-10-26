from dataclasses import replace
from candlescope_plugin_sdk import AnalyzeRequest, ExecuteBatchRequest, MarketContext, Bar
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin

CONTEXT = MarketContext("binance", "spot", "BTCUSDT", "1m")
BARS = tuple(Bar(time=1700000040+i*60, open=10, high=20, low=5, close=15, volume=100) for i in range(3))


def run(plugin, body, *, bars=BARS, identity=None, params=None, host=None):
    return plugin.execute_batch(ExecuteBatchRequest(source='//@version=6\nindicator("Host")\n'+body,
        context=CONTEXT, bars=bars, params=params or {},
        options={"pineHost": host or {}, **({"pineSessionId": identity} if identity else {})}))


def values(result):
    assert result.ok, result.diagnostics
    return [[point.value for point in series.points] for series in result.output.series]


def test_execution_clock_has_specific_error_and_uses_supplied_observation_times():
    plugin = PineCompatRuntimePlugin()
    result = run(plugin, "plot(timenow)")
    assert result.diagnostics[0].code == "PINE_EXECUTION_CLOCK_REQUIRED"
    clocks = [1700000099999+i*60000 for i in range(3)]
    assert values(run(plugin, "plot(timenow)", host={"executionTimes": clocks})) == [clocks]


def test_source_selection_uses_requested_field():
    plugin = PineCompatRuntimePlugin()
    body = 'src=input.source(close,"Source")\nplot(src)'
    source = '//@version=6\nindicator("Host")\n'+body
    analysis = plugin.analyze(AnalyzeRequest(source, CONTEXT))
    key = str(analysis.inputs[0]["callSiteId"])
    assert values(run(plugin, body, params={key: "high"})) == [[20]*3]


def test_calculation_window_uses_tail_timestamps_in_batch_and_recovered_realtime(tmp_path):
    source = '//@version=6\nindicator("Window",calc_bars_count=2)\nplot(close)'
    bars = tuple(replace(BARS[0], time=BARS[0].time+i*60, close=10+i) for i in range(5))
    request = ExecuteBatchRequest(source=source, context=CONTEXT, bars=bars)
    plugin = PineCompatRuntimePlugin(journal_path=tmp_path / "window.db")
    batch = plugin.execute_batch(request)
    assert values(batch) == [[13, 14]]
    assert [point.time for point in batch.output.series[0].points] == [bar.time for bar in bars[-2:]]
    live = replace(request, bars=(*bars[:-1], replace(bars[-1], is_closed=False)), options={"pineSessionId": "window"})
    first = plugin.execute_batch(live)
    assert values(first) == [[12, 13, 14]]
    assert [point.time for point in first.output.series[0].points] == [bar.time for bar in bars[-3:]]
    plugin.shutdown()
    resumed = PineCompatRuntimePlugin(journal_path=tmp_path / "window.db").execute_batch(live)
    assert resumed.meta["sessionRecovered"] and resumed.output == first.output


def test_historical_clock_correction_resets_instead_of_reusing_stale_values():
    plugin = PineCompatRuntimePlugin()
    clocks = [bar.time * 1000 + 10 for bar in BARS]
    run(plugin, "plot(timenow)", identity="clock", host={"executionTimes": clocks})
    changed = [stamp+5 for stamp in clocks]
    result = run(plugin, "plot(timenow)", identity="clock", host={"executionTimes": changed})
    assert result.meta["sessionReset"] and values(result) == [changed]


def test_root_request_expands_calculation_window_for_series_and_object_only_scripts():
    bars = tuple(replace(BARS[0], time=BARS[0].time+i*60, close=10+i) for i in range(8))
    base = '//@version=6\nindicator("Window",calc_bars_count=2)\nx=request.security(syminfo.tickerid,timeframe.period,close,calc_bars_count=6)\n'
    plugin = PineCompatRuntimePlugin()
    for identity in (None, "window"):
        for body in ('plot(x)', 'if x>0 and bar_index==2\n    line.new(0,x,5,x+1)'):
            result = plugin.execute_batch(ExecuteBatchRequest(source=base+body, context=CONTEXT, bars=bars,
                options={"pineSessionId": identity} if identity else {}))
            assert result.ok, result.diagnostics
            if body == 'plot(x)':
                times = [point.time for point in result.output.series[0].points]
            else:
                assert not result.output.series
                times = result.output.collections.objects["pineScenes"][0]["times"]
            assert times == [bar.time for bar in bars[2:]]


def test_native_calculation_window_aligns_equity_and_replay():
    from candlescope_plugin_pine_compat.native_strategy import execute
    from candlescope_plugin_pine_compat.native_session import Session
    rows = [{k: getattr(bar, k) for k in ("time", "open", "high", "low", "close", "volume")} for bar in BARS]
    request = {"source": '//@version=6\nstrategy("Window",calc_bars_count=2)\nplot(close)\nstrategy.entry("L",strategy.long)',
               "context": {"symbol": "A", "timeframe": "1"}, "bars": rows}
    result = execute(request)
    assert [row["time"] for row in result["equity"]] == [bar.time for bar in BARS[-2:]]
    assert result["graphics"][0]["values"] == [None, 15, 15]
    session = Session(request)
    assert session.advance(1)["equity"] == []
    assert session.advance(2)["equity"][0]["time"] == BARS[1].time
    assert session.advance(3) == result


def test_external_window_aligns_intents_and_rejects_rewritten_observations():
    import pytest
    from candlescope_plugin_pine_compat import external_strategy, external_stream
    from candlescope_plugin_pine_compat.execution_schedule import CONTRACT, TICK_CONTRACT
    bars = [{k: getattr(bar, k) for k in ("time", "open", "high", "low", "close", "volume")} for bar in BARS]
    request = dict(source='//@version=6\nstrategy("Window",calc_bars_count=2)\nplot(close)\nstrategy.entry("L",strategy.long)',
        context=dict(symbol="A",timeframe="1"), historical_plan=bars,
        external_stream_contract=external_stream.CONTRACT,
        execution_schedule_contract=CONTRACT, execution_tick_contract=TICK_CONTRACT)
    external_stream._active = None
    try:
        opened = external_strategy.execute({**request, "operation": "stream_open"})
        cursor, intent_cursor = opened["bar_cursor"], 0
        def command(operation, **kwargs):
            return external_strategy.execute(dict(operation=operation, external_stream_contract=external_stream.CONTRACT,
                bar_cursor=cursor, intent_base=intent_cursor, **kwargs))
        assert opened["input_skip"] == 1
        for bar in bars[opened["input_skip"]+cursor:]:
            command("stream_begin", bar=bar, bar_state="historical")
            account=dict(time=bar["time"], position_size=0, position_avg_price=None, equity=1000,
                initial_capital=1000, netprofit=0, openprofit=0)
            result=command("stream_observe", observation=dict(evaluation=dict(bar=bar, account=account,
                confirmed=True,event_time_ms=bar["time"]*1000+59999),
                context=dict(bar_state="historical",trigger="bar_close",is_new=True)))
            intent_cursor += len(result["intents"])
            command("stream_commit")
            cursor += 1
        result=command("stream_snapshot",include_intents=True)
        assert result["output"]["plots"][0]["values"] == [15, 15]
        assert len(result["intents"]) == 2
        with pytest.raises(ValueError, match="PINE_STREAM_CURSOR"):
            external_strategy.execute(dict(operation="stream_begin", external_stream_contract=external_stream.CONTRACT,
                bar_cursor=0, intent_base=intent_cursor, bar=bars[0], bar_state="historical"))
    finally:
        external_stream._active = None


def test_metadata_and_multitimeframe_requests_are_executable():
    plugin = PineCompatRuntimePlugin()
    rows = [{k: getattr(bar, k) for k in ("time", "open", "high", "low", "close", "volume")} for bar in BARS]
    host = {"chartMetadata": {"minMove": 1, "priceScale": 4, "pointValue": 10,
                              "minContract": ".25", "quantityStep": ".25", "currency": "USDT"},
            "symbolMetadata": {"B": {"minMove": 1, "priceScale": 4, "pointValue": 10}},
            "contexts": [{"symbol": "B", "timeframe": "1", "bars": rows}]}
    assert values(run(plugin, 'plot(syminfo.mintick)\nplot(syminfo.pointvalue)\nplot(request.security("B","1",high))', host=host)) == [[.25]*3, [10]*3, [20]*3]


def test_eviction_process_reconstruction_and_sliding_history_keep_varip(tmp_path):
    path = tmp_path / "journal.sqlite3"
    body = "varip int n=0\nn+=1\nplot(n)"
    forming = (*BARS[:2], replace(BARS[2], is_closed=False))
    plugin = PineCompatRuntimePlugin(journal_path=path)
    plugin._sessions.capacity = 1
    assert values(run(plugin, body, bars=forming, identity="a"))[-1][-1] == 3
    run(plugin, body, bars=forming, identity="b")
    recovered = run(plugin, body, bars=forming, identity="a")
    assert recovered.meta["sessionRecovered"] and values(recovered)[0][-1] == 3
    changed = (*forming[:2], replace(forming[2], close=16))
    assert values(run(plugin, body, bars=changed, identity="a"))[0][-1] == 4
    plugin.shutdown()
    resumed = PineCompatRuntimePlugin(journal_path=path)
    result = run(resumed, body, bars=changed[1:], identity="a")
    assert result.meta["sessionRecovered"] and not result.meta["sessionReset"]
    assert values(result)[0][-1] == 4


def test_provider_only_update_does_not_reset_or_double_execute_varip():
    plugin = PineCompatRuntimePlugin()
    body = 'varip int n=0\nn+=1\nplot(n)\nplot(request.security("B","1",close))'
    forming = (*BARS[:2], replace(BARS[2], is_closed=False))
    rows = [{k: getattr(bar, k) for k in ("time", "open", "high", "low", "close", "volume")} for bar in BARS]
    host = {"contexts": [{"symbol": "B", "timeframe": "1", "bars": rows, "forming": True}]}
    first = run(plugin, body, bars=forming, identity="a", host=host)
    assert values(first)[0][-1] == 3
    changed = {**host, "contexts": [{**host["contexts"][0], "bars": [*rows[:2], {**rows[2], "close": 19}]}]}
    second = run(plugin, body, bars=forming, identity="a", host=changed)
    assert not second.meta["sessionReset"]
    assert values(second)[0][-1] == 4
    assert values(second)[1][-1] == 19


def test_library_and_native_drawings_survive_render_contract():
    plugin = PineCompatRuntimePlugin()
    body = 'import test/Math/1 as m\nplot(m.twice(close))\nvar l=line.new(0,10,2,12)\nplotcandle(open,high,low,close)\nvar t=table.new(position.top_right,1,1)\ntable.cell(t,0,0,"OK")'
    result = run(plugin, body, host={"libraries": {"test/Math/1": '//@version=6\nlibrary("Math")\nexport twice(float value) => value*2'}})
    assert result.ok, result.diagnostics
    assert values(result)[0] == [30]*3
    assert not any(series.style.get("nativeScene") for series in result.output.series)
    scene = result.output.collections.objects["pineScenes"][0]
    assert {item["kind"] for item in scene["objects"]} == {"lines", "tables", "plotseries"}
    candle = next(item["row"] for item in scene["objects"] if item["kind"] == "plotseries")
    assert candle["family"] == "plotCandles" and candle["closes"] == [15]*3
    assert scene["times"] == [bar.time for bar in BARS]


def test_render_failure_does_not_commit_an_observation(monkeypatch):
    from candlescope_plugin_pine_compat import runtime
    plugin = PineCompatRuntimePlugin()
    forming = (*BARS[:2], replace(BARS[2], is_closed=False))
    body = 'varip int n=0\nn+=1\nplot(n)'
    assert values(run(plugin, body, bars=forming, identity="a"))[0][-1] == 3
    normalize = runtime._normalize_output
    def fail(*args, **kwargs): raise ValueError("PINE_TEST_RENDER_FAILED")
    monkeypatch.setattr(runtime, "_normalize_output", fail)
    assert not run(plugin, body, bars=forming, identity="a").ok
    monkeypatch.setattr(runtime, "_normalize_output", normalize)
    changed = (*forming[:2], replace(forming[2], close=16))
    assert values(run(plugin, body, bars=changed, identity="a"))[0][-1] == 4


def test_calendar_currency_and_observation_clock_are_forwarded_together():
    intervals = [{"open": bar.time * 1000, "close": bar.time * 1000 + 45000, "tradingDay": (bar.time // 86400) * 86400000} for bar in BARS]
    host = {"barCalendars": {"schemaVersion": 1, "symbols": [{"symbol": "BINANCE:BTCUSDT", "timezone": "Etc/UTC", "timeframes": [{"timeframe": "1", "intervals": intervals}]}]},
        "currencyRates": {"schemaVersion": 1, "pairs": [{"from": "USD", "to": "EUR", "rates": [{"effectiveTime": 0, "rate": .9}]}]},
        "executionTimes": [bar.time * 1000 + 44999 for bar in BARS]}
    assert values(run(PineCompatRuntimePlugin(), 'plot(time_close-time)\nplot(request.currency_rate("USD","EUR"))\nplot(timenow-time)', host=host)) == [[45000]*3, [.9]*3, [44999]*3]
