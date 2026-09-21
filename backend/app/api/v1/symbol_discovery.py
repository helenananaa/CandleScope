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

from app.api.v1 import symbols as catalog
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
        if not catalog._snapshot_persistence_enabled(snapshot):
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
                    rows = await catalog._search_provider_symbols(
                        exchange=adapter.id, market_type=market, search=query,
                    ) or []
                    if len(rows) >= 120:
                        status = "limited"
        except TimeoutError:
            status = "timeout"
        except HTTPException as exc:
            status = "rate_limited" if exc.status_code == 429 else "unavailable"
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
    from app.api.v1.discovery_catalog import run_discovery_catalogs
    await provider_queries.restore()
    task = asyncio.create_task(run_discovery_catalogs(), name="discovery:catalogs")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider_queries.close()


router = APIRouter(prefix="/symbols", tags=["symbols"], lifespan=lifespan)


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


def group_key(row: dict) -> str:
    # Presentation grouping only. Never infer equivalence from a stock ticker
    # across unknown venues, or merge option expiries/strikes/series semantics.
    asset = asset_class(row)
    base = text(row, "baseAsset") or text(row, "symbol")
    venue = text(row, "venue") or text(row, "venueMic")
    return json.dumps([
        asset, base.upper(), text(row, "quoteAsset").upper(), text(row, "marketType"),
        "" if asset == "crypto" else (venue or text(row, "exchange")).upper(),
        *[row.get(key) for key in ("contractType", "expiryAtMs", "optionStrike", "optionRight",
                                  "seriesVariant", "priceAdjustment", "sessionVariant", "volumeSemantics")],
    ], ensure_ascii=False, separators=(",", ":"))


def build_result(rows: list[dict], query: DiscoveryQuery, sources: list[dict]) -> dict:
    unique = {identity_key(row): row for row in rows if row.get("active", True) is True}
    scores = {key: relevance(row, query.search) for key, row in unique.items()
              if not query.source or row["exchange"] == query.source}
    matched = [unique[key] for key, score in scores.items() if score is not None]
    favorites, recent = set(query.favorites), set(query.recent)
    if query.scope != "all":
        wanted = favorites if query.scope == "favorites" else recent
        matched = [row for row in matched if symbol_key(row) in wanted]

    def matches(row: dict, exclude: str = "") -> bool:
        fields = {"assetClasses": (query.asset_class, asset_class(row)),
                  "markets": (query.market_type, text(row, "marketType")),
                  "venues": (query.venue, text(row, "venue") or text(row, "venueMic") or text(row, "exchange")),
                  "quotes": (query.quote, text(row, "quoteAsset"))}
        return all(key == exclude or not selected or selected.casefold() == value.casefold()
                   for key, (selected, value) in fields.items())

    facets = {}
    for field, accessor in {
        "assetClasses": asset_class, "markets": lambda row: text(row, "marketType"),
        "venues": lambda row: text(row, "venue") or text(row, "venueMic") or text(row, "exchange"),
        "quotes": lambda row: text(row, "quoteAsset"),
    }.items():
        counts = Counter(accessor(row) for row in matched if matches(row, field) and accessor(row))
        facets[field] = [{"key": key, "count": count} for key, count in sorted(counts.items())]

    groups: dict[str, list[dict]] = {}
    for row in matched:
        if matches(row):
            groups.setdefault(group_key(row), []).append(row)

    recent_order = {key: index for index, key in enumerate(query.recent)}

    ranks = {}
    for identity, row in unique.items():
        if identity not in scores or scores[identity] is None:
            continue
        key = symbol_key(row)
        ranks[id(row)] = (scores[identity], key not in favorites, recent_order.get(key, 1000),
                {"BTC": 0, "ETH": 1, "SOL": 2}.get(text(row, "baseAsset").upper(), 3) if not query.search.strip() else 0,
                contract_rank(row), {"USDT": 0, "USD": 1, "USDC": 2, "BTC": 3, "ETH": 4}.get(text(row, "quoteAsset").upper(), 5),
                row["exchange"] != query.preferred_source,
                text(row, "symbol"), identity)

    def rank(row: dict) -> tuple:
        return ranks[id(row)]

    ordered = []
    for key, items in sorted(groups.items(), key=lambda item: min(rank(row) for row in item[1])):
        count = len({row["exchange"] for row in items})
        for index, row in enumerate(sorted(items, key=rank)):
            ordered.append({**row, "seriesKey": identity_key(row), "groupKey": key,
                            "groupStart": index == 0, "groupSourceCount": count})
    revision = hashlib.sha256(json.dumps([row["seriesKey"] for row in ordered]).encode()).hexdigest()[:24]
    if query.offset and query.revision and query.revision != revision:
        raise HTTPException(409, detail="symbol_search_revision_changed")
    end = query.offset + query.limit
    return {"symbols": ordered[query.offset:end], "total": len(ordered), "revision": revision,
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
            await catalog._ensure_requested_catalog(source, query.market_type)
        except HTTPException:
            pass  # Coverage below distinguishes unavailable catalogs from zero matches.

    await asyncio.gather(*(warm(source) for source in warm_sources))
    rows, _ = catalog.list_cached_symbols()
    if not query.search.strip() or query.scope != "all":
        rows.extend(provider_queries.known.values())
    rows = [row for row in rows if row["exchange"] in selected]
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
            payload = catalog._catalog_status_payload(exchange=source)
            status = "stale" if payload["stale"] else "ready"
        else:
            payload = catalog._catalog_status_payload(exchange=source)
            failed = any(market.get("last_error") for market in payload.get("markets", {}).values())
            status = "unavailable" if source in requested or failed else "not_loaded"
        statuses.append({"id": source, "status": status})
    # Matching/sorting large snapshots must not occupy the API event loop used
    # by charts and streaming. Rows here are detached catalog snapshots.
    return await asyncio.to_thread(build_result, rows, query, statuses)
