from dataclasses import replace

import pytest
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, MarketContext

from candlescope_plugin_pine_compat import PineCompatRuntimePlugin
from candlescope_plugin_pine_compat.host_inputs import chart_metadata

CONTEXT = MarketContext("binance", "spot", "BTCUSDT", "1m")
BARS = (Bar(time=1700000000, open=10, high=11, low=9, close=10, volume=1),)


def request(source, **options):
    return ExecuteBatchRequest(
        source='//@version=6\nindicator("host")\n' + source,
        context=CONTEXT,
        bars=BARS,
        options=options,
    )


def test_execution_clock_is_explicit_for_batch_forming_confirmation_and_reseed():
    plugin = PineCompatRuntimePlugin()
    batch = plugin.execute_batch(request("plot(timenow)", pineExecutionTimeMs=100))
    assert batch.ok, batch.diagnostics
    assert batch.output.series[0].points[0].value == 100
    source = request("plot(timenow)", pineExecutionTimeMs=200, pineSessionId="clock")
    forming = replace(source, bars=BARS + (replace(BARS[0], time=1700000060, is_closed=False),))
    first = plugin.execute_batch(forming)
    second = plugin.execute_batch(
        replace(forming, options={**forming.options, "pineExecutionTimeMs": 300})
    )
    assert first.ok and second.ok
    assert [point.value for point in second.output.series[0].points] == [200, 300]
    assert second.meta["executionTimesMs"] == [200, 300]
    confirmed = plugin.execute_batch(
        replace(
            forming,
            bars=tuple(replace(bar, is_closed=True) for bar in forming.bars),
            options={**forming.options, "pineExecutionTimeMs": 400},
        )
    )
    assert confirmed.ok
    assert [point.value for point in confirmed.output.series[0].points] == [200, 400]
    plugin.shutdown()
    assert plugin.execute_batch(forming).meta["sessionReset"] is True


def test_missing_metadata_is_explicit_and_actual_grid_changes_mintick():
    plugin = PineCompatRuntimePlugin()
    missing = plugin.execute_batch(request("plot(syminfo.mintick)"))
    assert not missing.ok
    assert missing.diagnostics[0].code == "PINE_HOST_METADATA_REQUIRED"
    actual = plugin.execute_batch(
        request("plot(syminfo.mintick)", pineChartMetadata={"priceTickSize": "0.1"})
    )
    assert actual.ok, actual.diagnostics
    assert actual.output.series[0].points[0].value == 0.1


@pytest.mark.parametrize(
    "metadata",
    [
        {"priceTickSize": "0"},
        {"priceTickSize": "nan"},
        {"priceTickSize": True},
        {"priceTickSize": ".1", "quantityPrecision": True},
        {"priceTickSize": ".1", "pointValue": 0},
        {"priceTickSize": ".1", "timezone": "UTC"},
    ],
)
def test_invalid_or_unsupported_metadata_never_falls_back(metadata):
    with pytest.raises((TypeError, ValueError), match="PINE_HOST_METADATA"):
        chart_metadata(metadata)


def test_analysis_and_compilation_are_cached_across_ticks(monkeypatch):
    from candlescope_plugin_pine_compat import runtime

    engine, _ = runtime._engine_contract()
    runtime._native_analysis.cache_clear()

    calls = []
    original = engine.compile_script

    def compile(source, *args, **kwargs):
        calls.append(source)
        return original(source, *args, **kwargs)

    monkeypatch.setattr(engine, "compile_script", compile)
    plugin = PineCompatRuntimePlugin()
    for _ in range(3):
        assert plugin.execute_batch(request("plot(close)", pineSessionId="cache")).ok
    assert len(calls) == 1
    runtime._native_analysis.cache_clear()


def test_native_objects_preserve_geometry_and_deletion():
    plugin = PineCompatRuntimePlugin()
    source = """var l = line.new(bar_index, close, bar_index+1, close+2)
var note = label.new(bar_index, close, "Host label")
line.set_y2(l, close+4)
"""
    result = plugin.execute_batch(
        replace(request(source), bars=BARS + (replace(BARS[0], time=1700000060),))
    )
    assert result.ok, result.diagnostics
    scene = result.output.collections.objects["pineScenes"][0]
    assert {item["kind"] for item in scene["objects"]} == {"lines", "labels"}
    assert scene["objects"][0]["row"]["y2"] == 14
    assert scene["objects"][1]["row"]["text"] == "Host label"
    assert result.meta["drawingProjection"] == "chart-native-objects/1"
    deleted = plugin.execute_batch(
        replace(request(source + "\nline.delete(l)\nlabel.delete(note)\n"), bars=BARS)
    )
    assert deleted.ok, deleted.diagnostics
    assert not deleted.output.collections.lines
    assert not deleted.output.collections.markers
    assert deleted.output.collections.objects["pineScenes"][0]["objects"] == []


def test_requested_indicator_uses_explicit_remote_data():
    request_bars = {
        "BINANCE:ETHUSDT:1": [
            {
                "time": BARS[0].time * 1000,
                "open": 22,
                "high": 23,
                "low": 21,
                "close": 22,
                "volume": 1,
            }
        ]
    }
    result = PineCompatRuntimePlugin().execute_batch(
        request(
            'plot(request.security("BINANCE:ETHUSDT", "1", close))', pineRequestBars=request_bars
        )
    )
    assert result.ok, result.diagnostics
    assert result.output.series[0].points[0].value == 22


def test_native_and_replay_share_frozen_clock_and_price_grid():
    from candlescope_plugin_pine_compat.native_session import Session
    from candlescope_plugin_pine_compat.native_strategy import execute

    source = '//@version=6\nstrategy("metadata")\nplot(syminfo.mintick)\nplot(timenow)\n'
    data = {
        "source": source,
        "bars": [{"time": 1700000000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1}],
        "parameters": {},
        "execution_times": [1700000059999],
        "context": {
            "symbol": "BINANCE:BTCUSDT",
            "timeframe": "1",
            "metadata": {"priceTickSize": "0.1"},
        },
    }
    batch = execute(data)
    session = Session(data)
    assert session.advance(1) == batch
    assert [plot["values"] for plot in batch["raw_output"]["plots"]] == [[0.1], [1700000059999]]


def test_prefix_receiver_rejects_missing_and_wrong_base_without_guessing():
    from candlescope_plugin_pine_compat.prefix_transport import PrefixInput

    prefix = PrefixInput()
    with pytest.raises(ValueError, match="PINE_PREFIX_MISMATCH"):
        prefix.decode(
            {"operation": "append_prefix", "prefix_base": 0, "bars": [{}], "accounts": [{}]}
        )
    prefix.decode({"bars": [{}], "accounts": [{}]})
    for base in (0, True):
        with pytest.raises(ValueError, match="PINE_PREFIX_MISMATCH"):
            prefix.decode(
                {"operation": "append_prefix", "prefix_base": base, "bars": [{}], "accounts": [{}]}
            )


def test_unused_wall_clock_does_not_add_history_sized_clock_vectors():
    result = PineCompatRuntimePlugin().execute_batch(
        request("plot(close)", pineExecutionTimeMs=100)
    )
    assert result.ok, result.diagnostics
    assert "executionTimesMs" not in result.meta


def test_foreign_symbol_metadata_reaches_native_sessions_and_requires_actual_values():
    from candlescope_plugin_pine_compat.native_session import Session
    from candlescope_plugin_pine_compat.native_strategy import execute
    source = '''//@version=6
strategy("Requested metadata")
plot(request.security("OKX:ETH-USDT","1",syminfo.mintick))
plot(request.security("OKX:ETH-USDT","1",syminfo.currency == "EUR" ? 1 : 0))
plot(request.security("OKX:ETH-USDT","1",syminfo.mincontract))
'''
    bars = [{"time": i * 60, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(3)]
    context = {"symbol": "OKX:ETH-USDT", "timeframe": "1", "bars": bars,
        "metadata": {"priceTickSize": ".25", "currency": "EUR", "quantityPrecision": 3}}
    data = {"source": source, "parameters": {}, "bars": bars, "contexts": [context],
        "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1", "metadata": {"priceTickSize": ".1", "currency": "USDT", "quantityPrecision": 2}}}
    result = execute(data)
    assert [plot["values"] for plot in result["raw_output"]["plots"]] == [[.25]*3, [1]*3, [.001]*3]
    session = Session(data)
    assert session.advance(3) == result
    for metadata in (None, {"priceTickSize": ".25"}):
        with pytest.raises(ValueError, match="PINE_HOST_METADATA_REQUIRED"):
            execute({**data, "contexts": [{**context, "metadata": metadata}]})


@pytest.mark.parametrize("field,value", [("minContract", "2"), ("quantityStep", ".25"), ("quantityPrecision", 2)])
def test_mincontract_requires_quantity_metadata_for_chart_and_requested_symbols(field, value):
    from candlescope_plugin_pine_compat.host_inputs import require_price_grid

    analysis = {"compatibility": {"supported": [{"feature": "syminfo.mincontract"}]}}
    request = {"context": {"symbol": "A", "metadata": {field: value}},
               "contexts": [{"symbol": "B", "metadata": {field: value}}]}
    require_price_grid(analysis, request)
    with pytest.raises(ValueError, match="PINE_HOST_METADATA_REQUIRED"):
        require_price_grid(analysis, {**request, "context": {"symbol": "A"}})
    with pytest.raises(ValueError, match="PINE_HOST_METADATA_REQUIRED"):
        require_price_grid(analysis, {**request, "contexts": [{"symbol": "B"}]})


def test_requested_symbol_metadata_rejects_contradictory_timeframes_and_old_runtime(monkeypatch):
    import pine_compat
    from candlescope_plugin_pine_compat.host_inputs import native_request_bars
    context = {"symbol": "B", "metadata": {"priceTickSize": ".25"}}
    with pytest.raises(ValueError, match="conflicting metadata"):
        native_request_bars({"contexts": [context, {**context, "metadata": {"priceTickSize": ".1"}}]}, {})
    monkeypatch.setattr(pine_compat, "SYMBOL_METADATA_SCHEMA_VERSION", 0)
    with pytest.raises(ValueError, match="PINE_HOST_METADATA_UNAVAILABLE"):
        native_request_bars({"contexts": [context]}, {})


def test_indicator_requests_use_foreign_metadata_and_do_not_use_runtime_defaults():
    bars = (Bar(time=60, open=1, high=1, low=1, close=1, volume=1),)
    supplied = {"OKX:ETH-USDT:1": [{"time": 60000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]}
    options = {"pineChartMetadata": {"priceTickSize": ".1", "currency": "USDT"}, "pineRequestBars": supplied,
        "pineRequestSymbolMetadata": {"OKX:ETH-USDT": {"priceTickSize": ".25", "currency": "EUR"}}}
    source = 'plot(request.security("OKX:ETH-USDT","1",syminfo.mintick))\nplot(request.security("OKX:ETH-USDT","1",syminfo.currency == "EUR" ? 1 : 0))'
    plugin = PineCompatRuntimePlugin()
    actual = plugin.execute_batch(replace(request(source, **options), bars=bars))
    assert actual.ok, actual.diagnostics
    assert [series.points[0].value for series in actual.output.series] == [.25, 1]
    missing = plugin.execute_batch(replace(request(source, **{**options, "pineRequestSymbolMetadata": {}}), bars=bars))
    assert not missing.ok
    assert missing.diagnostics[0].code == "PINE_HOST_METADATA_REQUIRED"


def test_forming_lower_timeframe_requests_retain_the_symbol_registry():
    plugin = PineCompatRuntimePlugin()
    bars = tuple(Bar(time=t, open=1, high=1, low=1, close=1, volume=1, is_closed=t == 60) for t in (60, 120))
    supplied = {"OKX:ETH-USDT:30S": [{"time": t, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        for t in (60000, 90000, 120000, 150000)]}
    options = {"pineChartMetadata": {"priceTickSize": ".1"}, "pineRequestBars": supplied,
        "pineRequestSymbolMetadata": {"OKX:ETH-USDT": {"priceTickSize": ".25"}}, "pineExecutionTimeMs": 179999}
    source = 'values=request.security_lower_tf("OKX:ETH-USDT","30S",syminfo.mintick)\nplot(array.sum(values))'
    result = plugin.execute_batch(replace(request(source, **options), bars=bars))
    assert result.ok, result.diagnostics
    assert [point.value for point in result.output.series[0].points] == [.5, .5]
