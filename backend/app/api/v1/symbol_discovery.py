"""Bounded, cache-first product discovery across venues and providers.

Opening/searching never enumerates every remote exchange. A lifecycle-owned
background sweep fills the durable host snapshot. Query-only providers are
searched only for nonempty queries.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter, OrderedDict
from contextlib import asynccontextmanager
from typing import Any
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.exchanges import symbol_catalog as catalog
from app.api.v1.discovery_ranking import contract_rank, provider_search_text, relevance
from app.api.v1.discovery_store import exchange_rows


class DiscoveryQuery(BaseModel):
    search: str = Field("", max_length=120)
    source: str = Field("", max_length=100)
    asset_class: str = Field("", max_length=40)
    market_type: str = Field("", max_length=60)
    venue: str = Field("", max_length=100)
    quote: str = Field("", max_length=30)
    preferred_source: str = Field("", max_length=100)
    favorites: list[str] = Field(default_factory=list, max_length=500)
    recent: list[str] = Field(default_factory=list, max_length=30)
    scope: str = Field("all", pattern="^(all|favorites|recent)$")
    offset: int = Field(0, ge=0, le=1_000_000)
    limit: int = Field(100, ge=1, le=200)
    revision: str = Field("", max_length=64)
    load_sources: list[str] = Field(default_factory=list, max_length=3)


class ProviderQueries:
    def __init__(self) -> None:
        self.cache: OrderedDict[tuple, tuple[float, list, str]] = OrderedDict()
        self.tasks: dict[tuple, asyncio.Task] = {}
        self.gate = asyncio.Semaphore(3)
        self.known: OrderedDict[str, dict] = OrderedDict()
        self.store_path: Path | None = None

    async def restore(self) -> None:
        snapshot = Path(catalog.SYMBOL_CATALOG_SNAPSHOT_PATH)
        if not catalog.snapshot_persistence_enabled(snapshot):
            return
        self.store_path = snapshot.with_name("symbol_discovery.providers.sqlite3")
        rows = await asyncio.to_thread(exchange_rows, self.store_path)
        for row in rows:
            if isinstance(row, dict) and all(isinstance(row.get(key), str) and row[key]
                                             for key in ("exchange", "symbol", "marketType")):
                self.known[identity_key(row)] = row

    async def get(self, adapter: Any, query: str, market: str) -> tuple[list, str]:
        key = (id(adapter), query.casefold(), market)
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            self.cache.move_to_end(key)
            return cached[1], cached[2]
        if key not in self.tasks:
            if len(self.tasks) >= 24:
                return [], "busy"
            self.tasks[key] = asyncio.create_task(self._run(adapter, query, market, key))
        return await asyncio.shield(self.tasks[key])

    async def _run(self, adapter: Any, query: str, market: str, key: tuple) -> tuple[list, str]:
        rows, status = [], "ready"
        try:
            async with asyncio.timeout(5):
                async with self.gate:
                    rows = await catalog.search_provider_symbols(
                        exchange=adapter.id, market_type=market, search=query,
                    ) or []
                    if len(rows) >= 120:
                        status = "limited"
        except TimeoutError:
            status = "timeout"
        except catalog.SymbolCatalogError as exc:
            status = "rate_limited" if exc.code == "provider_rate_limited" else "unavailable"
        except Exception:
            status = "unavailable"
        finally:
            self.tasks.pop(key, None)
        self.cache[key] = (time.monotonic() + (60 if status in {"ready", "limited"} else 10), rows, status)
        for row in rows:
            self.known[identity_key(row)] = row
        if rows and self.store_path:
            await asyncio.to_thread(exchange_rows, self.store_path, [(identity_key(row), row) for row in rows])
        while len(self.known) > 3000:
            self.known.popitem(last=False)
        while len(self.cache) > 128:
            self.cache.popitem(last=False)
        return rows, status

    async def close(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.cache.clear()
        self.known.clear()


provider_queries = ProviderQueries()


@asynccontextmanager
async def lifespan(_app):
    from app.exchanges.discovery_catalog import run_discovery_catalogs
    await provider_queries.restore()
    task = asyncio.create_task(run_discovery_catalogs(), name="discovery:catalogs")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider_queries.close()


router = APIRouter(prefix="/symbols", tags=["symbols"], lifespan=lifespan)
_result_cache: OrderedDict[tuple, tuple[dict, list]] = OrderedDict()


def text(row: dict, key: str) -> str:
    return str(row.get(key) or "").strip()


def asset_class(row: dict) -> str:
    asset = text(row, "assetClass").lower()
    market = text(row, "marketType").lower()
    if asset in {"stock", "equity", "equities"} or market == "stock":
        return "stock"
    if market in {"etf", "forex", "index", "commodity"}:
        return market
    return asset or "crypto"


def symbol_key(row: dict) -> str:
    prefix = "" if row["exchange"] == "binance" else f'{row["exchange"]}:'
    return f'{prefix}{row["marketType"]}:{row["symbol"]}'


def identity_key(row: dict) -> str:
    return json.dumps([row.get(key) for key in (
        "exchange", "marketType", "symbol", "providerId", "venue", "assetClass",
        "seriesVariant", "priceAdjustment", "sessionVariant", "volumeSemantics",
        "contractType", "expiryAtMs", "optionStrike", "optionRight",
    )], ensure_ascii=False, separators=(",", ":"))


def group_parts(row: dict) -> tuple:
    # Presentation grouping only. Never infer equivalence from a stock ticker
    # across unknown venues, or merge option expiries/strikes/series semantics.
    asset = asset_class(row)
    base = text(row, "baseAsset") or text(row, "symbol")
    venue = text(row, "venue") or text(row, "venueMic")
    return (
        asset, base.upper(), text(row, "quoteAsset").upper(), text(row, "marketType"),
        "" if asset == "crypto" else (venue or text(row, "exchange")).upper(),
        *[row.get(key) for key in ("contractType", "expiryAtMs", "optionStrike", "optionRight",
                                  "seriesVariant", "priceAdjustment", "sessionVariant", "volumeSemantics")],
    )


def group_key(row: dict) -> str:
    return json.dumps(list(group_parts(row)), ensure_ascii=False, separators=(",", ":"))


IDENTITY_FIELDS = (
    "exchange", "marketType", "symbol", "providerId", "venue", "assetClass",
    "seriesVariant", "priceAdjustment", "sessionVariant", "volumeSemantics",
    "contractType", "expiryAtMs", "optionStrike", "optionRight",
)


def build_result(rows: list[dict], query: DiscoveryQuery, sources: list[dict]) -> dict:
    """Filter, facet, group and page a catalog snapshot.

    Runs over the whole catalog (tens of thousands of rows), so each row's derived
    values are computed once, internal keys are tuples, and output dicts are built
    only for the requested page. Input rows are read, never mutated.
    """
    unique: dict[tuple, dict] = {}
    for row in rows:
        if row.get("active", True) is True:
            unique[tuple(row.get(key) for key in IDENTITY_FIELDS)] = row
    scores = {key: relevance(row, query.search) for key, row in unique.items()
              if not query.source or row["exchange"] == query.source}
    matched = [key for key, score in scores.items() if score is not None]
    favorites, recent = set(query.favorites), set(query.recent)
    if query.scope != "all":
        wanted = favorites if query.scope == "favorites" else recent
        matched = [key for key in matched if symbol_key(unique[key]) in wanted]

    fields = ("assetClasses", "markets", "venues", "quotes")
    selected = [(value or "").casefold() for value in (query.asset_class, query.market_type, query.venue, query.quote)]
    values: dict[tuple, tuple[str, str, str, str]] = {}
    passes: dict[tuple, tuple[bool, bool, bool, bool]] = {}
    for key in matched:
        row = unique[key]
        row_values = (
            asset_class(row),
            text(row, "marketType"),
            text(row, "venue") or text(row, "venueMic") or text(row, "exchange"),
            text(row, "quoteAsset"),
        )
        values[key] = row_values
        passes[key] = tuple(not want or want == value.casefold() for want, value in zip(selected, row_values))

    facets = {}
    for index, field in enumerate(fields):
        # A facet's counts ignore its own selection, so every option stays visible.
        counts = Counter(
            row_values[index] for key, row_values in values.items()
            if row_values[index] and all(ok for other, ok in enumerate(passes[key]) if other != index)
        )
        facets[field] = [{"key": key, "count": count} for key, count in sorted(counts.items())]

    groups: dict[tuple, list[tuple]] = {}
    for key in matched:
        if all(passes[key]):
            groups.setdefault(group_parts(unique[key]), []).append(key)

    recent_order = {key: index for index, key in enumerate(query.recent)}
    ranks: dict[tuple, tuple] = {}
    for items in groups.values():
        for identity in items:
            row = unique[identity]
            key = symbol_key(row)
            ranks[identity] = (scores[identity], key not in favorites, recent_order.get(key, 1000),
                    {"BTC": 0, "ETH": 1, "SOL": 2}.get(text(row, "baseAsset").upper(), 3) if not query.search.strip() else 0,
                    contract_rank(row), {"USDT": 0, "USD": 1, "USDC": 2, "BTC": 3, "ETH": 4}.get(text(row, "quoteAsset").upper(), 5),
                    row["exchange"] != query.preferred_source,
                    text(row, "symbol"), repr(identity))

    ordered: list[tuple[tuple, tuple, bool, int]] = []
    for group, items in sorted(groups.items(), key=lambda item: min(ranks[key] for key in item[1])):
        count = len({unique[key]["exchange"] for key in items})
        for index, key in enumerate(sorted(items, key=ranks.__getitem__)):
            ordered.append((key, group, index == 0, count))
    revision = hashlib.sha256(
        json.dumps([list(key) for key, *_ in ordered], ensure_ascii=False, default=str).encode()
    ).hexdigest()[:24]
    if query.offset and query.revision and query.revision != revision:
        raise HTTPException(409, detail="symbol_search_revision_changed")
    end = query.offset + query.limit
    page = [
        {**unique[key], "seriesKey": identity_key(unique[key]),
         "groupKey": json.dumps(list(group), ensure_ascii=False, separators=(",", ":")),
         "groupStart": start, "groupSourceCount": count}
        for key, group, start, count in ordered[query.offset:end]
    ]
    return {"symbols": page, "total": len(ordered), "revision": revision,
            "nextOffset": end if end < len(ordered) else None, "facets": facets, "sources": sources,
            "partial": any(source["status"] not in {"ready", "query_required"} for source in sources)}


@router.post("/search")
async def search_symbols(query: DiscoveryQuery) -> dict:
    catalog.bootstrap_default_adapters()
    adapters = {adapter.id: adapter for adapter in catalog.get_exchange_registry().list()
                if adapter.capabilities().markets}
    if query.source and query.source not in adapters:
        raise HTTPException(400, detail="unsupported_symbol_source")
    if any(source not in adapters for source in query.load_sources):
        raise HTTPException(400, detail="unsupported_symbol_source")
    selected = [query.source] if query.source else sorted(adapters)
    requested = set(query.load_sources)
    if query.source:
        requested.add(query.source)
    # One preferred source can cold-start the default view. No global fanout.
    elif not requested and query.preferred_source in adapters:
        requested.add(query.preferred_source)
    query_sources = [source for source in selected if callable(getattr(adapters[source], "search_symbols", None))]
    warm_sources = [source for source in requested if source in selected and source not in query_sources]

    async def warm(source: str) -> None:
        try:
            await catalog.ensure_catalog(source, query.market_type)
        except catalog.SymbolCatalogError:
            pass  # Coverage below distinguishes unavailable catalogs from zero matches.

    await asyncio.gather(*(warm(source) for source in warm_sources))
    # Take only references on the event loop; detaching ~30k rows with deepcopy
    # here used to stall charts and streams for seconds per search.
    rows = catalog.cached_symbol_refs()
    if not query.search.strip() or query.scope != "all":
        rows.extend(provider_queries.known.values())
    selected_set = set(selected)
    rows = [row for row in rows if row["exchange"] in selected_set]
    statuses = []
    cached_sources = {row["exchange"] for row in rows}
    provider_results = {}
    # Providers beyond the bounded global budget remain explicitly discoverable
    # through the source selector instead of silently disappearing.
    queried = query_sources[:3] if query.search.strip() else []
    if queried:
        results = await asyncio.gather(*(provider_queries.get(adapters[source], provider_search_text(query.search), query.market_type)
                                         for source in queried))
        provider_results = dict(zip(queried, results, strict=True))
    for source in selected:
        if source in query_sources:
            found, status = provider_results.get(source, ([], "not_queried" if query.search.strip() else "query_required"))
            if query.search.strip() and query.scope == "all" and status not in {"ready", "limited"}:
                rows.extend(row for row in provider_queries.known.values() if row["exchange"] == source)
            rows.extend(found)
        elif source in cached_sources:
            payload = catalog.catalog_status(exchange=source)
            status = "stale" if payload["stale"] else "ready"
        else:
            payload = catalog.catalog_status(exchange=source)
            failed = any(market.get("last_error") for market in payload.get("markets", {}).values())
            status = "unavailable" if source in requested or failed else "not_loaded"
        statuses.append({"id": source, "status": status})
    # Matching/sorting large snapshots must not occupy the API event loop used
    # by charts and streaming. Rows here are detached catalog snapshots.
    # Reopening the dialog repeats the same query over the same catalog, so the ranked
    # rows are reused until the catalog changes. Provider answers are cached by
    # ``provider_queries`` and return the same list object while fresh; that identity
    # joins the key, and the entry keeps those lists alive so an id cannot be reused.
    # Source statuses change on their own (catalogs warm in the background), so they
    # are attached per response rather than cached.
    found_lists = [found for _, (found, _) in sorted(provider_results.items())]
    cache_key = (
        catalog.cache_generation(), len(rows), len(provider_queries.known), query.model_dump_json(),
        tuple((source, id(found), status) for source, (found, status) in sorted(provider_results.items())),
    )
    cached = _result_cache.get(cache_key)
    if cached is None:
        # build_result only reads rows and returns new dicts, so no detached copy is needed.
        result = await asyncio.to_thread(build_result, rows, query, [])
        _result_cache[cache_key] = (result, found_lists)
        while len(_result_cache) > 16:
            _result_cache.popitem(last=False)
    else:
        result = cached[0]
        _result_cache.move_to_end(cache_key)
    return {**result, "sources": statuses,
            "partial": any(source["status"] not in {"ready", "query_required"} for source in statuses)}
