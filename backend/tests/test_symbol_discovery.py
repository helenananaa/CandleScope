from __future__ import annotations

import asyncio
from collections import OrderedDict
from functools import wraps
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import symbol_discovery as discovery


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def row(source="binance", symbol="BTCUSDT", market="spot", **extra):
    return {"exchange": source, "symbol": symbol, "baseAsset": "BTC", "quoteAsset": "USDT",
            "marketType": market, "assetClass": "crypto", **extra}


def test_grouping_retains_source_identity_and_contract_semantics():
    rows = [row(), row("okx"), row("okx", market="futures"),
            row("okx", expiryAtMs=123), row("okx", sessionVariant="extended")]
    result = discovery.build_result(rows, discovery.DiscoveryQuery(search="BTC/USDT"), [])
    assert result["total"] == 5
    grouped = [item for item in result["symbols"] if item["groupSourceCount"] == 2]
    assert len(grouped) == 2
    assert len({item["seriesKey"] for item in result["symbols"]}) == 5
    assert len({item["groupKey"] for item in result["symbols"]}) == 4


def test_stocks_do_not_group_across_venues_or_adjustments():
    stock = row("provider", "AAPL", "stock", baseAsset="AAPL", quoteAsset="USD", assetClass="stock", venue="XNAS")
    rows = [stock, {**stock, "exchange": "provider2"}, {**stock, "venue": "XNYS"}, {**stock, "priceAdjustment": "split"}]
    result = discovery.build_result(rows, discovery.DiscoveryQuery(), [])
    assert result["total"] == 4
    assert len({item["groupKey"] for item in result["symbols"]}) == 3


def test_search_facets_pagination_and_revision_guard():
    rows = [row(), row("okx"), row("provider", "AAPL", "stock", displayName="Apple Inc", venue="XNAS", assetClass="stock", quoteAsset="USD")]
    result = discovery.build_result(rows, discovery.DiscoveryQuery(search="apple", asset_class="stock"), [])
    assert result["total"] == 1
    assert result["facets"]["venues"] == [{"key": "XNAS", "count": 1}]
    query = discovery.DiscoveryQuery(limit=1, preferred_source="okx")
    first = discovery.build_result(rows, query, [])
    second = discovery.build_result(rows, query.model_copy(update={"offset": 1, "revision": first["revision"]}), [])
    assert first["symbols"][0]["seriesKey"] != second["symbols"][0]["seriesKey"]
    with pytest.raises(HTTPException) as exc:
        discovery.build_result(rows + [row("new")], query.model_copy(update={"offset": 1, "revision": first["revision"]}), [])
    assert exc.value.status_code == 409
    assert discovery.build_result(rows, discovery.DiscoveryQuery(venue="xnas"), [dict(id="okx", status="unavailable")])["partial"]


def test_favorites_and_recent_are_cross_source_and_ranked():
    rows = [row(), row("okx"), row("bybit")]
    result = discovery.build_result(rows, discovery.DiscoveryQuery(scope="favorites", favorites=["okx:spot:BTCUSDT"]), [])
    assert [item["exchange"] for item in result["symbols"]] == ["okx"]
    result = discovery.build_result(rows, discovery.DiscoveryQuery(scope="recent", recent=["bybit:spot:BTCUSDT", "spot:BTCUSDT"]), [])
    assert [item["exchange"] for item in result["symbols"]] == ["bybit", "binance"]


def test_pair_match_outranks_a_similar_token_on_the_preferred_source():
    rows = [row("binance", "PUMPBTCUSDT", baseAsset="PUMPBTC"), row("bybit", "BTC/USDT:USDT")]
    result = discovery.build_result(rows, discovery.DiscoveryQuery(search="BTCUSDT", preferred_source="binance"), [])
    assert result["symbols"][0]["exchange"] == "bybit"


@pytest.mark.parametrize("search", ["比特币", "bitcoin", "bitcion", "比特币 USDT", "ＢＴＣ／ＵＳＤＴ", "okx:BTCUSDT"])
def test_alias_typo_unicode_and_source_qualified_search(search):
    result = discovery.build_result([row("okx")], discovery.DiscoveryQuery(search=search), [])
    assert result["total"] == 1
    assert result["symbols"][0]["symbol"] == "BTCUSDT"


def test_relevance_precedes_preferences_and_spot_precedes_derivatives():
    rows = [row("okx", market="futures", expiryAtMs=42), row("okx", market="futures"), row(),
            row("preferred", "BTCUPUSDT", baseAsset="BTCUP")]
    result = discovery.build_result(rows, discovery.DiscoveryQuery(search="BTC", preferred_source="preferred"), [])
    assert [item["marketType"] for item in result["symbols"][:3]] == ["spot", "futures", "futures"]
    assert result["symbols"][2]["expiryAtMs"] == 42
    assert result["symbols"][-1]["symbol"] == "BTCUPUSDT"


def test_fuzzy_search_does_not_match_short_unrelated_codes():
    assert discovery.build_result([row()], discovery.DiscoveryQuery(search="BTX"), [])["total"] == 0


def test_common_quote_precedes_alphabetically_earlier_fiat_pair():
    result = discovery.build_result([row("okx", "BTC-AED", quoteAsset="AED"), row()], discovery.DiscoveryQuery(search="比特币"), [])
    assert result["symbols"][0]["quoteAsset"] == "USDT"


@async_test
async def test_catalog_gate_bounds_concurrent_upstream_work():
    active, peak = 0, 0
    async def work():
        nonlocal active, peak
        async with discovery.catalog._catalog_gate():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
    await asyncio.gather(*(work() for _ in range(12)))
    assert peak == 2 and active == 0


def test_provider_metadata_survives_restart_and_keeps_full_identity(tmp_path):
    from app.api.v1.discovery_store import exchange_rows
    path = tmp_path / "providers.sqlite3"
    stock = row("provider", "AAPL", "stock", venue="XNAS", priceAdjustment="split", sessionVariant="regular")
    exchange_rows(path, [(discovery.identity_key(stock), stock)])
    restored = exchange_rows(path)
    assert restored == [stock]
    result = discovery.build_result(restored, discovery.DiscoveryQuery(scope="recent", recent=["provider:stock:AAPL"]), [])
    assert result["symbols"][0]["priceAdjustment"] == "split"


@async_test
async def test_background_sweep_includes_lazy_catalogs_but_never_query_providers(monkeypatch):
    from app.exchanges import discovery_catalog
    adapters = [SimpleNamespace(id="lazy", eager_catalog_refresh=False, capabilities=lambda: SimpleNamespace(markets=[SimpleNamespace(market_type="spot")])),
                SimpleNamespace(id="provider", search_symbols=lambda: None)]
    monkeypatch.setattr(discovery.catalog, "bootstrap_default_adapters", lambda: None)
    monkeypatch.setattr(discovery.catalog, "get_exchange_registry", lambda: SimpleNamespace(list=lambda: adapters))
    monkeypatch.setattr(discovery.catalog, "_foreground_busy_probe", None)
    calls = []
    async def refresh(adapter, market, force):
        calls.append((adapter.id, market, force))
    monkeypatch.setattr(discovery.catalog, "refresh_market_catalog", refresh)
    await discovery_catalog.refresh_discovery_catalogs()
    assert calls == [("lazy", "spot", False)]


@async_test
async def test_provider_query_singleflight_cache_and_cancellation(monkeypatch):
    cache = discovery.ProviderQueries()
    calls = []
    started, release = asyncio.Event(), asyncio.Event()

    async def search(**kwargs):
        calls.append(kwargs)
        started.set()
        await release.wait()
        return [row("provider")]

    monkeypatch.setattr(discovery.catalog, "search_provider_symbols", search)
    adapter = SimpleNamespace(id="provider")
    first = asyncio.create_task(cache.get(adapter, "BTC", ""))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(cache.get(adapter, "BTC", ""))
    release.set()
    assert (await second)[1] == "ready"
    assert (await cache.get(adapter, "btc", ""))[0] == [row("provider")]
    assert len(calls) == 1
    await cache.close()


@async_test
async def test_global_discovery_does_not_fan_out_catalog_downloads(monkeypatch):
    adapters = [SimpleNamespace(id=f"source{index}", capabilities=lambda: SimpleNamespace(markets=[SimpleNamespace(market_type="spot")])) for index in range(30)]
    monkeypatch.setattr(discovery.catalog, "bootstrap_default_adapters", lambda: None)
    monkeypatch.setattr(discovery.catalog, "get_exchange_registry", lambda: SimpleNamespace(list=lambda: adapters))
    monkeypatch.setattr(discovery.catalog, "cached_symbol_refs", lambda: [row("source0")])
    monkeypatch.setattr(discovery.catalog, "catalog_status", lambda **kwargs: {"stale": False})
    calls = []

    async def ensure(source, market):
        calls.append((source, market))

    monkeypatch.setattr(discovery.catalog, "ensure_catalog", ensure)
    result = await discovery.search_symbols(discovery.DiscoveryQuery(search="btc"))
    assert calls == []
    assert result["total"] == 1 and result["partial"]
    assert sum(source["status"] == "not_loaded" for source in result["sources"]) == 29
    await discovery.search_symbols(discovery.DiscoveryQuery(load_sources=["source1", "source2", "source3"], preferred_source="source0"))
    assert len(calls) == 3


@async_test
async def test_failure_does_not_become_empty_success_or_hide_other_sources(monkeypatch):
    adapters = [SimpleNamespace(id="binance", capabilities=lambda: SimpleNamespace(markets=[1])),
                SimpleNamespace(id="provider", search_symbols=lambda: None, capabilities=lambda: SimpleNamespace(markets=[1]))]
    monkeypatch.setattr(discovery.catalog, "bootstrap_default_adapters", lambda: None)
    monkeypatch.setattr(discovery.catalog, "get_exchange_registry", lambda: SimpleNamespace(list=lambda: adapters))
    monkeypatch.setattr(discovery.catalog, "cached_symbol_refs", lambda: [row()])
    monkeypatch.setattr(discovery.catalog, "catalog_status", lambda **kwargs: {"stale": False})

    async def fail(**kwargs):
        raise discovery.catalog.SymbolCatalogError("provider_rate_limited", "quota exhausted", retryable=True)

    cache = discovery.ProviderQueries()
    monkeypatch.setattr(discovery, "provider_queries", cache)
    monkeypatch.setattr(discovery.catalog, "search_provider_symbols", fail)
    result = await discovery.search_symbols(discovery.DiscoveryQuery(search="btc"))
    assert result["total"] == 1 and result["partial"]
    assert result["sources"][1] == {"id": "provider", "status": "rate_limited"}
    await cache.close()


def provider_discovery_fixture(monkeypatch):
    cache = discovery.ProviderQueries()
    adapter = SimpleNamespace(id="provider", search_symbols=lambda: None,
                              capabilities=lambda: SimpleNamespace(markets=[1]))
    monkeypatch.setattr(discovery, "provider_queries", cache)
    monkeypatch.setattr(discovery, "_result_cache", OrderedDict())
    monkeypatch.setattr(discovery.catalog, "bootstrap_default_adapters", lambda: None)
    monkeypatch.setattr(discovery.catalog, "get_exchange_registry", lambda: SimpleNamespace(list=lambda: [adapter]))
    monkeypatch.setattr(discovery.catalog, "cached_symbol_refs", lambda: [])
    return cache, adapter


@async_test
async def test_cached_results_refresh_after_provider_metadata_replacement(monkeypatch):
    cache, adapter = provider_discovery_fixture(monkeypatch)
    stock = row("provider", "AAPL", "stock", displayName="Old name")

    async def search(**_kwargs):
        return [dict(stock)]

    monkeypatch.setattr(discovery.catalog, "search_provider_symbols", search)
    await cache.get(adapter, "initial", "")
    query = discovery.DiscoveryQuery(source="provider")
    first = await discovery.search_symbols(query)
    # An unchanged snapshot should still reuse the expensive ranked result.
    assert (await discovery.search_symbols(query))["symbols"] is first["symbols"]
    stock["displayName"] = "Updated name"
    await cache.get(adapter, "refresh", "")
    assert len(cache.known) == 1
    updated = await discovery.search_symbols(query)
    assert updated["symbols"][0]["displayName"] == "Updated name"
    await cache.close()
    assert (await discovery.search_symbols(query))["total"] == 0


@async_test
async def test_cached_results_refresh_after_bounded_provider_eviction(monkeypatch):
    cache, adapter = provider_discovery_fixture(monkeypatch)
    cache._remember([row("provider", f"OLD{index:04d}") for index in range(3000)])
    query = discovery.DiscoveryQuery(source="provider", scope="favorites",
                                     favorites=["provider:spot:OLD0000", "provider:spot:NEW"])
    assert (await discovery.search_symbols(query))["symbols"][0]["symbol"] == "OLD0000"

    async def search(**_kwargs):
        return [row("provider", "NEW")]

    monkeypatch.setattr(discovery.catalog, "search_provider_symbols", search)
    await cache.get(adapter, "new", "")
    assert len(cache.known) == 3000
    assert [item["symbol"] for item in (await discovery.search_symbols(query))["symbols"]] == ["NEW"]
    await cache.close()


@async_test
async def test_cached_results_refresh_after_provider_snapshot_restore(monkeypatch, tmp_path):
    cache, _adapter = provider_discovery_fixture(monkeypatch)
    stock = row("provider", "AAPL", "stock", displayName="Before restore")
    cache._remember([stock])
    query = discovery.DiscoveryQuery(source="provider")
    assert (await discovery.search_symbols(query))["symbols"][0]["displayName"] == "Before restore"
    monkeypatch.setattr(discovery.catalog, "SYMBOL_CATALOG_SNAPSHOT_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(discovery.catalog, "snapshot_persistence_enabled", lambda _path: True)
    monkeypatch.setattr(discovery, "exchange_rows", lambda _path: [{**stock, "displayName": "Restored"}])
    await cache.restore()
    assert (await discovery.search_symbols(query))["symbols"][0]["displayName"] == "Restored"
    await cache.close()


@async_test
async def test_result_cache_version_belongs_to_catalog_snapshot_before_provider_await(monkeypatch):
    cache, _adapter = provider_discovery_fixture(monkeypatch)
    generation, rows = 1, [row("binance", "BTC-OLD")]
    adapter = SimpleNamespace(id="binance", capabilities=lambda: SimpleNamespace(markets=[1]))
    monkeypatch.setattr(discovery.catalog, "get_exchange_registry",
                        lambda: SimpleNamespace(list=lambda: [adapter, _adapter]))
    monkeypatch.setattr(discovery.catalog, "cached_symbol_refs", lambda: list(rows))
    monkeypatch.setattr(discovery.catalog, "cache_generation", lambda: generation)
    monkeypatch.setattr(discovery.catalog, "catalog_status", lambda **_kwargs: {"stale": False})

    async def search(**_kwargs):
        nonlocal generation, rows
        await asyncio.sleep(0)
        generation, rows = 2, [row("binance", "BTC-NEW")]
        return []

    monkeypatch.setattr(discovery.catalog, "search_provider_symbols", search)
    query = discovery.DiscoveryQuery(search="BTC")
    assert (await discovery.search_symbols(query))["symbols"][0]["symbol"] == "BTC-OLD"
    assert (await discovery.search_symbols(query))["symbols"][0]["symbol"] == "BTC-NEW"
    await cache.close()
