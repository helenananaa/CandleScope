from types import SimpleNamespace
from dataclasses import replace

import pytest

from app.indicator.pine_host_inputs import requested_data
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, MarketContext


@pytest.mark.parametrize("boundary,expected", [(179998,[0,60000]),(179999,[0,60000,120000])])
def test_observed_indicator_requests_preserve_the_inclusive_confirmation_boundary(boundary,expected):
    bars=(Bar(time=120,open=1,high=1,low=1,close=1,volume=1,is_closed=False),)
    request=ExecuteBatchRequest(source="",context=MarketContext("binance","spot","BTCUSDT","1m"),
        bars=bars,options={"pineExecutionTimeMs":185000,"pineRevealedBoundaryMs":boundary})
    requirements={"requests":[{"function":"request.security","symbol":{"kind":"literal","value":"BINANCE:ETHUSDT"},
        "timeframe":{"kind":"literal","value":"1"}}]}
    result=requested_data(request,requirements,SimpleNamespace(query=lambda *a,**k:SimpleNamespace(
        bars=[replace(bars[0],time=t,is_closed=True) for t in (0,60,120,180)],missing_ranges=[])))
    assert [row["time"] for row in result["pineRequestBars"]["BINANCE:ETHUSDT:1"]]==expected
    assert result["pineRequestObservation"]=={"contract":"candlescope.pine-indicator-observations/1","observedAtMs":boundary}


def test_local_requested_data_never_exposes_unconfirmed_remote_close():
    bars = (Bar(time=120, open=1, high=1, low=1, close=1, volume=1),)
    request = ExecuteBatchRequest(
        source="", context=MarketContext("binance", "spot", "BTCUSDT", "1m"), bars=bars
    )
    seen = []

    def query(*args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(
            bars=[
                Bar(time=t, open=1, high=1, low=1, close=1, volume=1)
                for t in (0, 120, 240)
            ],
            missing_ranges=[],
        )

    result = requested_data(
        request,
        {
            "requests": [
                {
                    "function": "request.security",
                    "symbol": {"kind": "literal", "value": "BINANCE:ETHUSDT"},
                    "timeframe": {"kind": "literal", "value": "2"},
                }
            ]
        },
        SimpleNamespace(query=query),
    )
    assert [bar["time"] for bar in result["pineRequestBars"]["BINANCE:ETHUSDT:2"]] == [
        0
    ]
    assert seen[0][1]["auto_backfill"] is False
    assert seen[0][1]["end_ms"] == 179999


def test_cross_exchange_and_missing_context_fail_explicitly():
    request = ExecuteBatchRequest(
        source="",
        context=MarketContext("binance", "spot", "BTCUSDT", "1m"),
        bars=(Bar(time=120, open=1, high=1, low=1, close=1, volume=1),),
    )
    requirement = {
        "requests": [
            {
                "function": "request.security",
                "symbol": {"kind": "literal", "value": "OTHER:BTCUSDT"},
                "timeframe": {"kind": "literal", "value": "1"},
            }
        ]
    }
    def unavailable(*args, **kwargs):
        raise ValueError("Unknown exchange OTHER")
    assert "pineRequestError" in requested_data(request, requirement, SimpleNamespace(query=unavailable))
    assert "pineRequestError" in requested_data(request, requirement, None)


def test_cross_exchange_uses_exact_venue_and_explicit_market_type():
    seen = []
    request = ExecuteBatchRequest(
        source="", context=MarketContext("binance", "usdm", "BTCUSDT", "1m"),
        bars=(Bar(time=120, open=1, high=1, low=1, close=1, volume=1),),
        options={"pineRequestContexts": [{"symbol": "OKX:BTC-USDT", "timeframe": "1", "marketType": "spot"}]},
    )
    def query(*args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(bars=request.bars, missing_ranges=[])
    requirements = {"requests": [{"function": "request.security", "symbol": {"kind": "literal", "value": "OKX:BTC-USDT"}, "timeframe": {"kind": "literal", "value": "1"}}]}
    result = requested_data(request, requirements, SimpleNamespace(query=query))
    assert "OKX:BTC-USDT:1" in result["pineRequestBars"]
    assert seen[0][0] == ("BTC-USDT", "1m")
    assert seen[0][1]["exchange"] == "okx"
    assert seen[0][1]["market_type"] == "spot"
    assert seen[0][1]["auto_backfill"] is False


def test_inherited_chart_symbol_and_timeframe_are_resolved_without_source_guessing():
    from app.indicator.pine_host_inputs import requested_contexts
    request = ExecuteBatchRequest(source="", context=MarketContext("binance", "spot", "BTCUSDT", "2h"), bars=())
    requirements = [{"function": "request.security", "symbol": {"kind": "rootChartSymbol"}, "timeframe": {"kind": "currentContextTimeframe"}}]
    assert requested_contexts(request, requirements) == [("BINANCE:BTCUSDT", "120", "spot")]
    requirements[0]["symbol"] = {"kind": "runtimeExpression"}
    with pytest.raises(ValueError, match="explicit"):
        requested_contexts(request, requirements)
    request = replace(request, options={"pineRequestContexts": [{"symbol": "OKX:ETH-USDT", "timeframe": "D"}]})
    assert requested_contexts(request, requirements) == [("OKX:ETH-USDT", "D", "spot")]


@pytest.mark.parametrize("contexts", [None, {}, [{"symbol": "x", "timeframe": "0"}], [{"symbol": "x", "timeframe": "1", "marketType": False}], [{"symbol": "x", "timeframe": "1", "secret": "x"}], [{"symbol": "x", "timeframe": "1", "marketType": "spot"}, {"symbol": "x", "timeframe": "1", "marketType": "usdm"}]])
def test_invalid_provider_declarations_are_not_ignored(contexts):
    from app.indicator.pine_host_inputs import requested_contexts
    request = ExecuteBatchRequest(source="", context=MarketContext("binance", "spot", "BTCUSDT", "1m"), bars=(), options={"pineRequestContexts": contexts})
    with pytest.raises(ValueError):
        requested_contexts(request, [])


def test_inherited_usdm_symbol_uses_perpetual_identity_and_exact_storage_instrument():
    calls = []
    request = ExecuteBatchRequest(source="", context=MarketContext("binance", "usdm", "BTCUSDT", "1m"), bars=(Bar(time=120, open=1, high=1, low=1, close=1, volume=1),))
    def query(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(bars=request.bars, missing_ranges=[])
    result = requested_data(request, {"requests": [{"function": "request.security", "symbol": {"kind": "currentContextSymbol"}, "timeframe": {"kind": "literal", "value": "1"}}]}, SimpleNamespace(query=query))
    assert "BINANCE:BTCUSDT.P:1" in result["pineRequestBars"]
    assert calls[0][0] == ("BTCUSDT", "1m")
    assert calls[0][1]["market_type"] == "usdm"


def test_requested_metadata_uses_the_exact_auxiliary_market_and_preserves_explicit_values(monkeypatch):
    from app.indicator import pine_host_inputs
    calls = []
    def metadata(exchange, market, symbol):
        calls.append((exchange, market, symbol))
        return {"priceTickSize": ".25", "quoteAsset": "USDT"}
    monkeypatch.setattr(pine_host_inputs, "get_cached_symbol_metadata", metadata)
    context = {"symbol": "BINANCE:ETHUSDT.P", "timeframe": "1", "marketType": "usdm"}
    request = ExecuteBatchRequest(source="", context=MarketContext("okx", "spot", "BTC-USDT", "1m"),
        bars=(Bar(time=120, open=1, high=1, low=1, close=1, volume=1),), options={"pineRequestContexts": [context]})
    requirements = {"requests": [{"function": "request.security", "symbol": {"kind": "runtimeExpression"}, "timeframe": {"kind": "literal", "value": "1"}}]}
    result = requested_data(request, requirements, SimpleNamespace(query=lambda *a, **k: SimpleNamespace(bars=request.bars, missing_ranges=[])))
    assert calls == [("binance", "usdm", "ETHUSDT")]
    assert result["pineRequestSymbolMetadata"] == {"BINANCE:ETHUSDT.P": {"priceTickSize": ".25", "currency": "USDT"}}
    explicit = {"priceTickSize": ".5", "currency": "USDT", "quantityPrecision": 3}
    result = requested_data(replace(request, options={"pineRequestContexts": [{**context, "metadata": explicit}]}), requirements,
        SimpleNamespace(query=lambda *a, **k: SimpleNamespace(bars=request.bars, missing_ranges=[])))
    assert result["pineRequestSymbolMetadata"][context["symbol"]] == explicit
