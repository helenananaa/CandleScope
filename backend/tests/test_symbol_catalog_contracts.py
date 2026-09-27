from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

from app.api.v1.symbols import router
from app.data_engine.history.exchange_policy import ExchangeHistoryPolicyResolver
from app.exchanges import symbol_catalog as catalog
from app.exchanges.rate_limits import RateLimitAdmission, RateLimitDeferred
from app.plugin_market_v2.data_manager_port import DataManagerConsumerPort


@pytest.mark.anyio
@pytest.mark.parametrize("failure,status,detail,retry_after", [
    ("unknown", 400, "Unsupported exchange: test", None),
    ("quota", 429, {"code": "provider_rate_limited",
                   "message": "Symbol provider quota is temporarily exhausted",
                   "retryable": True, "retry_at_ms": 123456}, "3"),
    ("provider", 503, {"code": "provider_symbol_search_unavailable",
                      "message": "provider offline", "retryable": False}, None),
])
async def test_provider_errors_keep_http_status_body_and_retry_hint(monkeypatch, failure, status, detail, retry_after):
    async def search(*args, **kwargs):
        if failure == "quota":
            raise RateLimitDeferred(RateLimitAdmission(
                allowed=False, bucket_key="test", rule_name="query",
                cost=1, reason="budget", retry_at_monotonic=None,
                retry_after_seconds=3.9, retry_at_ms=123456,
            ))
        raise RuntimeError("provider offline")

    def get(_exchange):
        if failure == "unknown":
            raise KeyError(_exchange)
        return SimpleNamespace(search_symbols=search)

    monkeypatch.setattr(catalog, "bootstrap_default_adapters", lambda: None)
    monkeypatch.setattr(catalog, "get_exchange_registry", lambda: SimpleNamespace(get=get))
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/symbols/exchange-info", params={"exchange": "test", "search": "BTC"})
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert response.headers.get("retry-after") == retry_after


@pytest.mark.anyio
@pytest.mark.parametrize("refresh", [False, True])
async def test_no_usable_catalog_is_retryable_failure_in_both_http_paths(monkeypatch, refresh):
    async def empty(*args, **kwargs):
        return {}

    monkeypatch.setattr(catalog, "bootstrap_default_adapters", lambda: None)
    monkeypatch.setattr(catalog, "get_exchange_registry", lambda: SimpleNamespace(list=lambda: []))
    monkeypatch.setattr(catalog, "refresh_exchange_metadata", empty)
    monkeypatch.setattr(catalog, "_symbol_cache", {})
    monkeypatch.setattr(catalog, "_market_refresh_state", {})
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/symbols/exchange-info/refresh") if refresh else await client.get("/symbols/exchange-info")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json() == {"detail": {
        "code": "symbol_catalog_unavailable",
        "message": "Symbol catalog refresh produced no usable snapshot" if refresh else "Symbol catalog is not available yet",
        "retryable": True, "retry_at_ms": None, "markets": {},
    }}


@pytest.mark.anyio
async def test_http_history_and_plugin_share_one_catalog_and_eviction(monkeypatch):
    now = time.time()
    row = {"symbol": "AAPL:XNAS", "baseAsset": "AAPL", "quoteAsset": "USD", "active": True,
           "exchange": "test", "marketType": "stock", "providerId": "provider", "venue": "XNAS",
           "assetClass": "stock", "seriesVariant": "regular", "priceAdjustment": "split",
           "sessionVariant": "regular", "volumeSemantics": "shares"}
    monkeypatch.setattr(catalog, "_symbol_cache", {("test", "stock"): [row]})
    monkeypatch.setattr(catalog, "_market_refresh_state", {
        ("test", "stock"): catalog._MarketRefreshState(last_success_at=now, stale=False),
    })
    for name in ("_market_refresh_tasks", "_market_refresh_timers", "_market_auto_refresh_tasks"):
        monkeypatch.setattr(catalog, name, {})
    monkeypatch.setattr(catalog, "_cache_loaded_at", now)
    monkeypatch.setattr(catalog, "bootstrap_default_adapters", lambda: None)
    adapter = SimpleNamespace(id="test", capabilities=lambda: SimpleNamespace(markets=[SimpleNamespace(market_type="stock")]))
    monkeypatch.setattr(catalog, "get_exchange_registry", lambda: SimpleNamespace(get=lambda exchange: adapter))
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/symbols/exchange-info", params={"exchange": "test", "market_type": "stock"})
    assert response.status_code == 200
    assert response.json()["symbols"] == [row]
    port = DataManagerConsumerPort(None)
    request = SimpleNamespace(context=SimpleNamespace(exchange="test", market_type="stock"))
    rows, _ = await port.list_symbols(request)
    resolver = ExchangeHistoryPolicyResolver(None)
    key = SimpleNamespace(exchange="test", market_type="stock", symbol="AAPL:XNAS")
    assert rows == [row] and resolver._lookup_symbol(key) == row
    rows[0]["venue"] = "mutated"
    assert resolver._lookup_symbol(key)["venue"] == "XNAS"
    assert catalog.evict_exchange_metadata("test") == 1
    assert (await port.list_symbols(request))[0] == []
    assert resolver._lookup_symbol(key) is None
