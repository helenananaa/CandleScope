"""Frozen chart boundaries coexist with explicit Pine Host inputs."""
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, MarketContext
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin


def test_calendar_indicator_preserves_metadata_and_requested_streams():
    start, end = 1709960400000, 1710046800000
    row = dict(time=start // 1000, open=10, high=12, low=9, close=11, volume=1)
    request = ExecuteBatchRequest(
        source='''//@version=6
indicator("combined Host inputs")
plot(time_close)
plot(syminfo.mintick)
plot(request.security("BINANCE:ETHUSDT", "1D", close))
''',
        context=MarketContext("binance", "spot", "BTCUSDT", "1d~c1~America/New_York"),
        bars=(Bar(**row),),
        options={
            "barBasis": {"id": "frozen-day/1", "windows": [[start, end]]},
            "pineChartMetadata": {"priceTickSize": "0.01", "currency": "USD"},
            "pineHost": {
                "contexts": [{"symbol": "BINANCE:ETHUSDT", "timeframe": "1D",
                              "bars": [{**row, "close": 12}]}],
                "symbolMetadata": {"BINANCE:ETHUSDT": {"priceTickSize": "0.01", "currency": "USD"}},
            },
        },
    )
    result = PineCompatRuntimePlugin().execute_batch(request)
    assert result.ok, result.diagnostics
    assert [[point.value for point in line.points] for line in result.output.series] == [[end], [0.01], [12]]
