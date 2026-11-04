"""Typed domain facades exposed by :class:`DataManager`.

These facades make channel semantics discoverable without breaking the older
flat DataManager methods.  They delegate to existing engines/services and own
no storage, lifecycle tasks, or mutable market state themselves.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
from typing import Any

from app.data_engine.market_data.models import MarketStreamKey
from app.data_engine.market_data.ports import (
    AdvancedMarketDataPort,
    FullOrderBookPort,
    LiquidationPort,
    OrderBookPort,
    PublicTradePort,
)

from .models import QueryResult, StreamInfo


class BarSourcePrefixFacade:
    """Transaction-owned source prefix protection behind the DataManager."""

    def __init__(self, storage: Callable[[], Any] | None) -> None:
        self._storage = storage

    def _require(self):
        from app.data_engine.storage.prefix_watches import PrefixContinuityUnavailable
        store = None if self._storage is None else self._storage()
        if store is None:
            raise PrefixContinuityUnavailable("This data source has no durable prefix protection")
        return store

    def register(self, owner: str, series, **kwargs):
        values = (series.exchange, series.market_type, series.symbol, series.interval, *series.identity.storage_values)
        return self._require().register(owner, values, **kwargs)

    def prepare(self, receipt, **kwargs):
        return self._require().prepare(receipt, **kwargs)

    def commit(self, proof, publish: Callable[[], Any], *, committed_through_ms=None):
        # Computation and provider snapshots belong before this short guard.
        # The callback only commits its already prepared financial checkpoint.
        if inspect.iscoroutinefunction(publish):
            raise TypeError("source prefix commit requires a synchronous durable callback")
        with self._require().commit_guard(proof,committed_through_ms=committed_through_ms):
            result = publish()
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("source prefix commit cannot acknowledge asynchronous work")
            return result

    def inspect(self, owner: str):
        return self._require().inspect(owner)

    def release(self, receipt):
        return self._require().release(receipt)


class BarDataFacade:
    """Typed access to cache/storage-backed bar operations."""

    def __init__(
        self,
        *,
        query: Callable[..., QueryResult],
        query_latest: Callable[..., QueryResult],
        query_before: Callable[..., QueryResult],
        get_bounds: Callable[..., dict[str, Any]],
        ensure_stream: Callable[..., Any],
        prefix_store: Callable[[], Any] | None = None,
    ) -> None:
        self._query = query
        self._query_latest = query_latest
        self._query_before = query_before
        self._get_bounds = get_bounds
        self._ensure_stream = ensure_stream
        self.prefixes = BarSourcePrefixFacade(prefix_store)

    def query(self, symbol: str, interval: str, **kwargs: Any) -> QueryResult:
        return self._query(symbol, interval, **kwargs)

    def latest(self, symbol: str, interval: str, **kwargs: Any) -> QueryResult:
        return self._query_latest(symbol, interval, **kwargs)

    def before(self, symbol: str, interval: str, **kwargs: Any) -> QueryResult:
        return self._query_before(symbol, interval, **kwargs)

    def bounds(self, symbol: str, interval: str, **kwargs: Any) -> dict[str, Any]:
        return self._get_bounds(symbol, interval, **kwargs)

    async def ensure_stream(
        self,
        symbol: str,
        interval: str,
        **kwargs: Any,
    ) -> StreamInfo:
        return await self._ensure_stream(symbol, interval, **kwargs)


class MarketStateFacade:
    """Latest/history access for ticker, mark, funding, OI, and basis data."""

    def __init__(self, service: Callable[[], AdvancedMarketDataPort]) -> None:
        self._service = service

    async def ensure_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().ensure_stream(key, consumer_id=consumer_id)

    async def release_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().release_stream(key, consumer_id=consumer_id)

    async def snapshot(
        self,
        keys: list[MarketStreamKey],
        *,
        refresh_missing: bool = True,
    ) -> list[Any]:
        return await self._service().snapshot(keys, refresh_missing=refresh_missing)

    async def history(self, key: MarketStreamKey, **kwargs: Any) -> list[Any]:
        return await self._service().history(key, **kwargs)

    async def history_page(self, key: MarketStreamKey, **kwargs: Any) -> Any:
        return await self._service().history_page(key, **kwargs)

    def subscribe(
        self,
        keys: list[MarketStreamKey],
        *,
        max_pending: int = 64,
        replay: bool = True,
        continuity=None,
    ) -> Any:
        options = {} if continuity is None else {"continuity": continuity}
        return self._service().subscribe(
            keys,
            max_pending=max_pending,
            replay=replay,
            **options,
        )

    def diagnostics(self) -> dict[str, Any]:
        return self._service().diagnostics()


class TradeDataFacade:
    """Append-only public trades, one-minute rollups, and raw archive access."""

    def __init__(self, service: Callable[[], PublicTradePort]) -> None:
        self._service = service

    async def ensure_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().ensure_stream(key, consumer_id=consumer_id)

    async def release_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().release_stream(key, consumer_id=consumer_id)

    def recent(self, key: MarketStreamKey, **kwargs: Any) -> list[Any]:
        return self._service().recent(key, **kwargs)

    async def history(self, key: MarketStreamKey, **kwargs: Any) -> list[Any]:
        return await self._service().history(key, **kwargs)

    def attach(self, keys: list[MarketStreamKey], **kwargs: Any) -> Any:
        return self._service().attach(keys, **kwargs)

    async def archive_coverage(self, key: MarketStreamKey, **kwargs: Any) -> Any:
        return await self._service().archive_coverage(key, **kwargs)

    def diagnostics(self) -> dict[str, Any]:
        return self._service().diagnostics()


class LiquidationDataFacade:
    """Sampled public liquidation observations and derived rollups."""

    def __init__(self, service: Callable[[], LiquidationPort]) -> None:
        self._service = service

    async def ensure_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().ensure_stream(key, consumer_id=consumer_id)

    async def release_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().release_stream(key, consumer_id=consumer_id)

    def recent(self, key: MarketStreamKey, **kwargs: Any) -> list[Any]:
        return self._service().recent(key, **kwargs)

    async def history(self, key: MarketStreamKey, **kwargs: Any) -> list[Any]:
        return await self._service().history(key, **kwargs)

    def attach(self, keys: list[MarketStreamKey], **kwargs: Any) -> Any:
        return self._service().attach(keys, **kwargs)

    def diagnostics(self) -> dict[str, Any]:
        return self._service().diagnostics()


class PartialOrderBookFacade:
    """Replaceable Partial Top-N order-book snapshots."""

    def __init__(self, service: Callable[[], OrderBookPort]) -> None:
        self._service = service

    async def ensure_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().ensure_stream(key, consumer_id=consumer_id)

    async def release_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().release_stream(key, consumer_id=consumer_id)

    def snapshot(self, key: MarketStreamKey) -> Any:
        return self._service().current(key)

    async def wait_for_snapshot(
        self,
        key: MarketStreamKey,
        *,
        timeout_seconds: float,
    ) -> Any:
        return await self._service().wait_for_snapshot(
            key,
            timeout_seconds=timeout_seconds,
        )

    def attach(self, keys: list[MarketStreamKey], **kwargs: Any) -> Any:
        return self._service().attach(keys, **kwargs)

    def diagnostics(self) -> dict[str, Any]:
        return self._service().diagnostics()


class FullOrderBookFacade:
    """Sequence-gated full-depth reconstructed books."""

    def __init__(self, service: Callable[[], FullOrderBookPort]) -> None:
        self._service = service

    async def ensure_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().ensure_stream(key, consumer_id=consumer_id)

    async def release_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        return await self._service().release_stream(key, consumer_id=consumer_id)

    def snapshot(self, key: MarketStreamKey) -> Any:
        return self._service().current(key, require_live=True)

    async def wait_for_snapshot(
        self,
        key: MarketStreamKey,
        *,
        timeout_seconds: float,
    ) -> Any:
        return await self._service().wait_for_live(
            key,
            timeout_seconds=timeout_seconds,
        )

    def attach(self, keys: list[MarketStreamKey], **kwargs: Any) -> Any:
        return self._service().attach(keys, **kwargs)

    def diagnostics(self) -> dict[str, Any]:
        return self._service().diagnostics()


@dataclass(frozen=True, slots=True)
class OrderBookFacades:
    partial: PartialOrderBookFacade
    full: FullOrderBookFacade


__all__ = [
    "BarDataFacade",
    "FullOrderBookFacade",
    "LiquidationDataFacade",
    "MarketStateFacade",
    "OrderBookFacades",
    "PartialOrderBookFacade",
    "TradeDataFacade",
]
