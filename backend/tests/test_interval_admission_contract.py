"""Same serialized capabilities and decisions as the frontend contract suite."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.data_engine.interval_resolution import IntervalResolver, IntervalResolutionError
from app.exchanges import bootstrap_default_adapters
from app.exchanges.contracts import validate_exchange_capabilities
from app.exchanges.registry import _snapshot_capabilities
from app.exchanges.models import ExchangeCapabilities, ExchangeMarket, MarketChannelCapability

_FIXTURE = json.loads((Path(__file__).parent / "fixtures/interval_admission.json").read_text())


@pytest.mark.parametrize("document", _FIXTURE["documents"], ids=lambda d: d["capability"]["exchange"])
def test_shared_wire_admission(document):
    payload = document["capability"]
    capability = ExchangeCapabilities(**{
        **payload,
        "markets": [ExchangeMarket(**market) for market in payload["markets"]],
        "channels": [MarketChannelCapability(**channel) for channel in payload["channels"]],
    })
    assert validate_exchange_capabilities(capability).ok
    assert capability.to_dict() == payload  # fixtures must be real backend wire shapes
    resolver = IntervalResolver(SimpleNamespace(
        get_capabilities=lambda _: _snapshot_capabilities(capability),
    ))
    for case in document["checks"]:
        kwargs = dict(exchange=capability.exchange, market_type=case["market"],
                      interval=case["target"], purpose=case["purpose"])
        if case["kind"] == "unavailable":
            with pytest.raises(IntervalResolutionError) as failure:
                resolver.resolve(**kwargs)
            assert failure.value.code.value == case["code"], case
        else:
            route = resolver.resolve(**kwargs)
            assert (route.kind.value, route.source_interval) == (case["kind"], case["source"]), case


@pytest.mark.parametrize("purpose", ["history", "realtime"])
def test_registered_ordinary_usdm_route_does_not_inherit_spot_seconds(purpose):
    registry = bootstrap_default_adapters()
    resolver = IntervalResolver(registry)
    for exchange, market in (("binance", "futures"), ("binanceusdm", "swap.linear")):
        with pytest.raises(IntervalResolutionError) as failure:
            resolver.resolve(exchange=exchange, market_type=market, interval="1s", purpose=purpose)
        assert failure.value.code.value == "no_exact_base"
        assert resolver.resolve(exchange=exchange, market_type=market, interval="1m", purpose=purpose).is_native
    assert resolver.resolve(exchange="binance", market_type="spot", interval="1s", purpose=purpose).is_native


def test_registered_generic_swap_market_is_not_a_legacy_futures_alias():
    registry = bootstrap_default_adapters()
    for purpose in ("history", "realtime"):
        route = IntervalResolver(registry).resolve(
            exchange="backpack", market_type="swap", interval="1m", purpose=purpose,
        )
        assert route.is_native
        assert route.market_type == "swap"


def test_pinned_ccxt_usdm_history_selects_ordinary_contract_endpoint():
    import ccxt
    exchange = ccxt.binanceusdm()
    # Controlled market metadata: execute the real CCXT route selection, intercept
    # the HTTP boundary, and fail if it attempts discovery or any other endpoint.
    exchange.load_markets = lambda: None
    exchange.market = lambda _: {"id": "BTCUSDT", "option": False, "linear": True, "inverse": False}
    calls = []
    exchange.fapiPublicGetKlines = lambda params: calls.append(params) or []
    exchange.fetch_ohlcv("BTC/USDT:USDT", "1s", limit=1)
    assert calls == [{"symbol": "BTCUSDT", "interval": "1s", "limit": 1}]
    assert "1s" in exchange.timeframes  # metadata alone is not an execution contract
