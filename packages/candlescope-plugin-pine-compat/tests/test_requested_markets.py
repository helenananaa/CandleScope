"""Exercise host data resolution against the actual interpreter, not a stub."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from candlescope_plugin_sdk import AnalyzeRequest, Bar, ExecuteBatchRequest, MarketContext
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin
from app.indicator.pine_host_inputs import requested_data


@pytest.mark.parametrize("source,contexts,exchange", [
    ('//@version=6\nindicator("r")\nplot(request.security("OKX:ETH-USDT", "1", close))', [], "okx"),
    ('//@version=4\nstudy("r")\ns=input("OKX:ETH-USDT")\nplot(security(s,"1",close))', [{"symbol": "OKX:ETH-USDT", "timeframe": "1"}], "okx"),
    ('//@version=6\nindicator("r")\nplot(request.security(syminfo.tickerid, "1", close))', [], None),
])
def test_resolved_request_reaches_real_engine_without_market_substitution(source, contexts, exchange):
    plugin = PineCompatRuntimePlugin()
    bars = tuple(Bar(time=t, open=10, high=10, low=10, close=10, volume=1) for t in (60, 120, 180))
    request = ExecuteBatchRequest(source=source, context=MarketContext("binance", "spot", "BTCUSDT", "1m"), bars=bars, options={"pineRequestContexts": contexts}, params={"__pineContexts": contexts})
    analysis = plugin.analyze(AnalyzeRequest(source=source, context=request.context))
    assert analysis.executable, analysis.diagnostics
    calls = []
    def query(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(bars=[replace(bar, open=20, high=20, low=20, close=20) for bar in bars], missing_ranges=[])
    data = requested_data(request, analysis.meta["hostRequirements"], SimpleNamespace(query=query))
    assert "pineRequestError" not in data, data
    result = plugin.execute_batch(replace(request, options={**request.options, **data}))
    assert result.ok, result.diagnostics
    assert result.output.series[0].points[-1].value == (20 if exchange else 10)
    if exchange:
        assert calls[0][1]["exchange"] == exchange
        assert calls[0][1]["auto_backfill"] is False


def test_dynamic_request_missing_from_declared_provider_never_uses_another_market():
    plugin = PineCompatRuntimePlugin()
    request = ExecuteBatchRequest(source='//@version=4\nstudy("r")\ns=input("OKX:ETH-USDT")\nplot(security(s,"1",close))',
        context=MarketContext("binance", "spot", "BTCUSDT", "1m"),
        bars=(Bar(time=60, open=10, high=10, low=10, close=10, volume=1),),
        options={"pineRequestBars": {"BINANCE:ETHUSDT:1": [{"time": 60000, "open": 999, "high": 999, "low": 999, "close": 999, "volume": 1}]}})
    result = plugin.execute_batch(request)
    assert not result.ok


def test_usdm_indicator_exposes_its_actual_perpetual_identity():
    plugin = PineCompatRuntimePlugin()
    request = ExecuteBatchRequest(source='//@version=6\nindicator("perp")\nplot(syminfo.tickerid == "BINANCE:BTCUSDT.P" ? 1 : 0)',
        context=MarketContext("binance", "usdm", "BTCUSDT", "1m"),
        bars=(Bar(time=60, open=10, high=10, low=10, close=10, volume=1),))
    result = plugin.execute_batch(request)
    assert result.ok, result.diagnostics
    assert result.output.series[0].points[-1].value == 1


def test_confirmed_intrabar_feed_survives_repeated_forming_updates_and_chart_confirmation():
    plugin = PineCompatRuntimePlugin()
    source = ('//@version=6\nindicator("intrabar")\n'
        'a=request.security_lower_tf("OKX:ETH-USDT","1",close)\nplot(array.size(a))\n'
        'plot(request.security("OKX:ETH-USDT","1",close))')
    chart = tuple(Bar(time=300 + i * 300, open=10, high=10, low=10, close=10, volume=1) for i in range(4))
    request = ExecuteBatchRequest(source=source, context=MarketContext("binance", "spot", "BTCUSDT", "5m"),
        bars=chart[:2] + (replace(chart[2], is_closed=False),), options={"pineSessionId": "intrabar"})
    remote = tuple(replace(chart[0], time=300 + i * 60, open=i, high=i, low=i, close=i) for i in range(20))
    analysis = plugin.analyze(AnalyzeRequest(source=source, context=request.context))
    assert analysis.executable, analysis.diagnostics

    def compute(request, boundary):
        boundary += 300000
        request = replace(request, options={**request.options, "pineExecutionTimeMs": boundary, "pineRevealedBoundaryMs": boundary})
        data = requested_data(request, analysis.meta["hostRequirements"], SimpleNamespace(
            query=lambda *args, **kwargs: SimpleNamespace(bars=remote, missing_ranges=[])))
        result = plugin.execute_batch(replace(request, options={**request.options, **data}))
        assert result.ok, result.diagnostics
        return result

    first = compute(request, 719999)
    assert [series.points[-1].value for series in first.output.series] == [2, 11]
    repeat = compute(request, 719999)
    assert not repeat.meta["sessionReset"]
    assert repeat.output == first.output
    later = compute(request, 779999)
    assert [series.points[-1].value for series in later.output.series] == [3, 12]
    confirmed = compute(replace(request, bars=chart[:3]), 899999)
    assert [series.points[-1].value for series in confirmed.output.series] == [5, 14]
    independent = compute(replace(request, bars=chart[:3], options={}), 899999)
    assert independent.output == confirmed.output
    next_bar = compute(replace(request, bars=chart[:3] + (replace(chart[3], is_closed=False),)), 959999)
    assert [series.points[-1].value for series in next_bar.output.series] == [1, 15]
