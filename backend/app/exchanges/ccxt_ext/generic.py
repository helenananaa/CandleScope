"""Generic CCXT exchange plugins backed by unified REST and Pro methods."""

from __future__ import annotations

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

import aiohttp
import ccxt
import ccxt.async_support as ccxt_async
import ccxt.pro as ccxtpro

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import (
    DataSource,
    RawMessage,
    StreamDescriptor,
    StreamType,
    TransportRequest,
)
from app.exchanges.models import ExchangeCapabilities, SymbolInfo
from app.exchanges.pagination import ReverseTimePaginationPolicy
from app.exchanges.plugin import BuiltinExchangePlugin
from app.exchanges.rate_limits import RateLimitPolicy

from .catalog import (
    CcxtCatalogEntry,
    assert_supported_ccxt_version,
    build_ccxt_capabilities,
    get_ccxt_catalog,
    market_matches_selection,
    market_selection_parts,
)
from .unified import (
    CcxtUnifiedNormalizer,
    CcxtUnifiedProjector,
    make_unified_payload,
)
from .runtime import close_ccxt_exchange


_GENERIC_STREAM_METHODS = {
    StreamType.KLINE: ("watchOHLCV", "fetchOHLCV"),
    StreamType.TRADE: ("watchTrades", "fetchTrades"),
    StreamType.DEPTH: ("watchOrderBook", "fetchOrderBook"),
    StreamType.TICKER: ("watchTicker", "fetchTicker"),
    StreamType.MINI_TICKER: ("watchTicker", "fetchTicker"),
    StreamType.MARK_PRICE: ("watchMarkPrice", "fetchMarkPrice"),
    StreamType.INDEX_PRICE: ("watchMarkPrice", "fetchMarkPrice"),
    StreamType.FUNDING_RATE: ("watchFundingRate", "fetchFundingRateHistory"),
    StreamType.OPEN_INTEREST: (None, "fetchOpenInterest"),
    StreamType.LIQUIDATION: ("watchLiquidations", "fetchLiquidations"),
    StreamType.PREMIUM_INDEX: (None, "fetchPremiumIndexOHLCV"),
}


class _OwnedThreadedResolverMixin:
    """Give one-shot CCXT clients a reliable owned session on Windows."""

    def open(self) -> None:
        if getattr(self, "_candlescope_closed", False):
            raise ccxt.ExchangeNotAvailable("CandleScope exchange is closed")
        if sys.platform != "win32" or self.session is not None or not self.own_session:
            super().open()
            return

        self.own_session = False
        try:
            super().open()
        finally:
            self.own_session = True
        self.tcp_connector = aiohttp.TCPConnector(
            ssl=self.ssl_context,
            loop=self.asyncio_loop,
            resolver=aiohttp.ThreadedResolver(loop=self.asyncio_loop),
        )
        self.session = aiohttp.ClientSession(
            loop=self.asyncio_loop,
            connector=self.tcp_connector,
            trust_env=self.aiohttp_trust_env,
        )

    async def close(self, clean_instance_data: bool = True) -> None:
        self._candlescope_closed = True
        await super().close(clean_instance_data)


@lru_cache(maxsize=None)
def _owned_exchange_class(exchange_class: type, *, windows: bool) -> type:
    if not windows:
        return exchange_class
    return type(
        f"CandleScopeOwned{exchange_class.__name__}",
        (_OwnedThreadedResolverMixin, exchange_class),
        {"__module__": __name__},
    )


def _consume_task_outcome(task: asyncio.Task[Any]) -> None:
    """Retrieve detached bootstrap failures without changing await semantics."""

    try:
        task.exception()
    except BaseException:
        pass


@dataclass(slots=True)
class _RestExchangeEntry:
    exchange: Any
    load_task: asyncio.Task[Any]
    borrowers: int
    idle: asyncio.Event
    reload_task: asyncio.Task[Any] | None = None


class _RestExchangePool:
    """Transport-owned CCXT REST clients with one market bootstrap per rail.

    REST fetches used to construct, ``load_markets()``, and close a CCXT
    exchange for every page or HTTP-fallback poll.  Parsing a venue catalog
    (thousands of markets) runs synchronously on the event loop, so a 2 s
    poll cadence kept the loop busy almost continuously, and every fresh
    client also built a new aiohttp session and SSL context.  One
    ``IngestionConfig`` belongs to one ``TransportLayer``; keeping the pool
    scoped to that exact config gives the transport connection and catalog
    reuse without sharing proxy/session state between transport owners.
    """

    def __init__(self, entry: Any, config: IngestionConfig) -> None:
        self._catalog_entry = entry
        self._config = config
        self._entries: dict[str, _RestExchangeEntry] = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._created = 0
        self._reused = 0
        self._load_failures = 0
        self._request_count = 0
        self._request_failures = 0
        self._market_load_ms_total = 0.0
        self._market_load_ms_last = 0.0
        self._request_ms_total = 0.0
        self._request_ms_last = 0.0
        self._request_ms_max = 0.0
        self._market_reloads = 0
        self._market_reload_failures = 0
        self._symbol_reload_attempts: dict[tuple[str, str], float] = {}

    async def _load_markets(self, exchange: Any) -> Any:
        """Bootstrap one client and measure the physical task, not a waiter.

        The bootstrap is shielded from individual request cancellation.  Its
        timing therefore has to live on the shared task itself; measuring in
        ``get()`` would under-report whenever the request that created the
        client was superseded while another request kept using the bootstrap.
        """

        started = time.perf_counter()
        try:
            return await exchange.load_markets()
        except asyncio.CancelledError:
            raise
        except BaseException:
            self._load_failures += 1
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._market_load_ms_last = elapsed_ms
            self._market_load_ms_total += elapsed_ms

    async def _acquire(self, selection: str) -> _RestExchangeEntry:
        async with self._lock:
            if self._closed:
                raise RuntimeError("CCXT REST pool is closed")
            current = self._entries.get(selection)
            if current is None:
                exchange = _create_exchange(
                    self._catalog_entry,
                    self._config,
                    market_type=selection,
                    websocket=False,
                )
                load_task = asyncio.create_task(self._load_markets(exchange))
                load_task.add_done_callback(_consume_task_outcome)
                idle = asyncio.Event()
                idle.set()
                current = _RestExchangeEntry(
                    exchange=exchange,
                    load_task=load_task,
                    borrowers=0,
                    idle=idle,
                )
                self._entries[selection] = current
                self._created += 1
            else:
                self._reused += 1

        try:
            await asyncio.shield(current.load_task)
        except asyncio.CancelledError:
            # The shared market bootstrap belongs to the transport, not to one
            # HTTP consumer.  A superseded chart request must not tear down the
            # client while another backfill page is joining the same task.
            raise
        except BaseException:
            should_close = False
            async with self._lock:
                if self._entries.get(selection) is current:
                    self._entries.pop(selection, None)
                    should_close = True
            if should_close:
                await close_ccxt_exchange(current.exchange)
            raise
        async with self._lock:
            if self._closed or self._entries.get(selection) is not current:
                raise RuntimeError("CCXT REST pool closed during client acquisition")
            current.borrowers += 1
            current.idle.clear()
        return current

    @staticmethod
    def _release(current: _RestExchangeEntry) -> None:
        # All pool mutations belong to one asyncio loop.  Keeping borrower
        # release synchronous makes this cleanup immune to repeated task
        # cancellation; an await here could strand ``idle`` forever and hang
        # transport shutdown after a second cancel arrived.
        current.borrowers = max(0, current.borrowers - 1)
        if current.borrowers == 0:
            current.idle.set()

    async def resolve_symbol(
        self,
        selection: str,
        exchange: Any,
        descriptor: StreamDescriptor,
        *,
        market_type: str | None = None,
    ) -> str:
        """Resolve a symbol, refreshing a stale pooled catalog once on miss."""

        try:
            return resolve_ccxt_symbol(
                exchange,
                descriptor,
                market_type=market_type,
            )
        except ValueError:
            pass

        requested = str(descriptor.symbol or "").strip().upper()
        attempt_key = (selection, requested)
        now = time.monotonic()
        async with self._lock:
            current = self._entries.get(selection)
            if current is None or current.exchange is not exchange or self._closed:
                raise RuntimeError("CCXT REST pool changed during symbol refresh")
            reload_task = current.reload_task
            last_attempt = self._symbol_reload_attempts.get(attempt_key, 0.0)
            if reload_task is None and now - last_attempt >= 60.0:
                self._symbol_reload_attempts[attempt_key] = now
                reload_task = asyncio.create_task(exchange.load_markets(reload=True))
                reload_task.add_done_callback(_consume_task_outcome)
                current.reload_task = reload_task
                self._market_reloads += 1

        if reload_task is not None:
            try:
                await asyncio.shield(reload_task)
            except asyncio.CancelledError:
                raise
            except BaseException:
                self._market_reload_failures += 1
                raise
            finally:
                async with self._lock:
                    current = self._entries.get(selection)
                    if (
                        current is not None
                        and current.reload_task is reload_task
                        and reload_task.done()
                    ):
                        current.reload_task = None

        return resolve_ccxt_symbol(
            exchange,
            descriptor,
            market_type=market_type,
        )

    def record_request(self, *, elapsed_ms: float, failed: bool) -> None:
        self._request_count += 1
        if failed:
            self._request_failures += 1
        self._request_ms_last = max(0.0, float(elapsed_ms))
        self._request_ms_total += self._request_ms_last
        self._request_ms_max = max(self._request_ms_max, self._request_ms_last)

    @asynccontextmanager
    async def request(self, selection: str):
        current = await self._acquire(selection)
        started = time.perf_counter()
        failed = True
        try:
            yield current.exchange
            failed = False
        finally:
            self.record_request(
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                failed=failed,
            )
            self._release(current)

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            entries = tuple(self._entries.values())
            self._entries.clear()
        if entries:
            for entry in entries:
                if not entry.load_task.done():
                    entry.load_task.cancel()
                if entry.reload_task is not None and not entry.reload_task.done():
                    entry.reload_task.cancel()
            await asyncio.gather(
                *(
                    task
                    for entry in entries
                    for task in (entry.load_task, entry.reload_task)
                    if task is not None
                ),
                return_exceptions=True,
            )
            # Never close a shared connector while a physical CCXT request is
            # still borrowing it. Runtime shutdown first drains backfill work;
            # this fence also makes direct/restart races deterministic.
            await asyncio.gather(*(entry.idle.wait() for entry in entries))
            await asyncio.gather(
                *(close_ccxt_exchange(entry.exchange) for entry in entries),
                return_exceptions=True,
            )

    def snapshot(self) -> dict[str, Any]:
        request_average = (
            self._request_ms_total / self._request_count
            if self._request_count
            else 0.0
        )
        load_average = (
            self._market_load_ms_total / self._created
            if self._created
            else 0.0
        )
        return {
            "closed": self._closed,
            "rails": sorted(self._entries),
            "clients": len(self._entries),
            "clients_created": self._created,
            "client_reuses": self._reused,
            "market_load_failures": self._load_failures,
            "market_reloads": self._market_reloads,
            "market_reload_failures": self._market_reload_failures,
            "market_load_ms_last": round(self._market_load_ms_last, 3),
            "market_load_ms_average": round(load_average, 3),
            "requests": self._request_count,
            "request_failures": self._request_failures,
            "request_ms_last": round(self._request_ms_last, 3),
            "request_ms_average": round(request_average, 3),
            "request_ms_max": round(self._request_ms_max, 3),
        }


class CcxtUnifiedProtocol:
    """Protocol sentinel: physical I/O is owned by CCXT provider methods."""

    @staticmethod
    def supports_ws(_descriptor: StreamDescriptor) -> bool:
        return False

    @staticmethod
    def rest_base_urls(
        _market_type: str = "spot",
        config: Any | None = None,
    ) -> list[str]:
        del config
        return []

    @staticmethod
    def rest_request(
        _request: TransportRequest,
        config: Any | None = None,
    ) -> None:
        del config
        return None

    @staticmethod
    def ws_base_urls(
        _descriptor: StreamDescriptor,
        config: Any | None = None,
    ) -> list[str]:
        del config
        return []


class CcxtSymbolNormalizer:
    """Preserve CCXT unified symbols, including case-sensitive venue IDs."""

    @staticmethod
    def normalize(symbol: str, market_type: str = "spot") -> str:
        del market_type
        return str(symbol or "").strip()

    @staticmethod
    def display(symbol: str, market_type: str = "spot") -> str:
        del market_type
        return str(symbol or "").strip()


class CcxtHistoricalPaginationPolicy(ReverseTimePaginationPolicy):
    """Forward ``since`` pagination matching CCXT's unified OHLCV contract."""

    def first_request(
        self,
        task: Any,
        *,
        batch_size: int,
        now_ms: int,
    ) -> TransportRequest:
        end_ms = int(task.end_ms) if task.end_ms is not None else now_ms
        start_ms = int(task.start_ms) if task.start_ms is not None else None
        if start_ms is None:
            try:
                width = int(ccxt.Exchange.parse_timeframe(task.interval) * 1000)
            except Exception:
                width = 60_000
            start_ms = max(0, end_ms - max(1, batch_size) * width)
        return TransportRequest(
            descriptor=self._descriptor(task),
            limit=batch_size,
            start_ms=start_ms,
            end_ms=end_ms,
        )

    def next_request(
        self,
        task: Any,
        previous_request: TransportRequest,
        bars: list[Any],
        *,
        batch_size: int,
    ) -> TransportRequest | None:
        if not bars:
            return None
        newest = max(int(bar.open_time) for bar in bars)
        end_ms = previous_request.end_ms
        if end_ms is not None and newest >= end_ms:
            return None
        next_start = newest + 1
        if previous_request.start_ms is not None and next_start <= previous_request.start_ms:
            return None
        return TransportRequest(
            descriptor=previous_request.descriptor,
            limit=batch_size,
            start_ms=next_start,
            end_ms=end_ms,
        )


class CcxtUnifiedAdapter:
    """Lazy symbol-catalog adapter for one pinned CCXT exchange ID."""

    eager_catalog_refresh = False

    def __init__(
        self,
        entry: CcxtCatalogEntry,
        capabilities: ExchangeCapabilities,
    ) -> None:
        self.entry = entry
        self.id = entry.exchange_id
        self.name = entry.name
        self._capabilities = capabilities

    def capabilities(self) -> ExchangeCapabilities:
        return self._capabilities

    async def list_symbols(self, market_type: str = "") -> list[SymbolInfo]:
        config = IngestionConfig()
        selection = str(market_type or "").strip().lower()
        if not self.entry.market_types:
            return []
        resolved_selection = (
            resolve_market_selection(self.entry, selection) if selection else ""
        )
        exchange = _create_exchange(
            self.entry,
            config,
            market_type=resolved_selection or self.entry.market_types[0],
            websocket=False,
        )
        try:
            await exchange.load_markets()
            selections = (
                (resolved_selection,) if resolved_selection else self.entry.market_types
            )
            symbols: list[SymbolInfo] = []
            for market in exchange.markets.values():
                if market.get("active") is False:
                    continue
                selected = next(
                    (
                        candidate
                        for candidate in selections
                        if market_matches_selection(market, candidate)
                    ),
                    None,
                )
                if selected is None:
                    continue
                symbol = str(market.get("symbol") or "").strip()
                base = str(market.get("base") or "").strip()
                quote = str(market.get("quote") or "").strip()
                if not symbol or not base or not quote:
                    continue
                symbols.append(
                    SymbolInfo(
                        symbol=symbol,
                        base_asset=base,
                        quote_asset=quote,
                        status="TRADING",
                        exchange=self.id,
                        market_type=selection or selected,
                        product_type=_product_type(selection or selected),
                        contract_type=_contract_type(selection or selected),
                        raw=dict(market),
                        listed_at_ms=_timestamp(market.get("created")),
                        expiry_at_ms=_timestamp(market.get("expiry")),
                        price_tick_size=_price_tick_size(exchange, market),
                    )
                )
            return sorted(symbols, key=lambda item: item.symbol)
        finally:
            await close_ccxt_exchange(exchange)

    @staticmethod
    def get_http_base_urls(
        market_type: str = "spot",
        config: Any | None = None,
    ) -> list[str]:
        del market_type, config
        return []

    @staticmethod
    def get_ws_base_urls(
        market_type: str = "spot",
        config: Any | None = None,
    ) -> list[str]:
        del market_type, config
        return []

    @staticmethod
    def get_rest_path(
        stream_type: StreamType,
        market_type: str = "spot",
    ) -> None:
        del stream_type, market_type
        return None

    @staticmethod
    def build_http_params(req: TransportRequest) -> dict[str, Any]:
        del req
        return {}

    @staticmethod
    def build_ws_stream_name(descriptor: StreamDescriptor) -> str:
        return descriptor.key

    @staticmethod
    def build_ws_subscription(descriptor: StreamDescriptor) -> Any:
        del descriptor
        raise RuntimeError("CCXT unified plugins do not expose direct WS subscriptions")

    @staticmethod
    def get_multi_symbol_ticker_stream_name(
        market_type: str = "spot",
    ) -> None:
        del market_type
        return None

    @staticmethod
    def supports_ws_streaming(market_type: str = "spot") -> bool:
        del market_type
        return False

    @staticmethod
    def extract_http_rows(payload: Any, stream_type: StreamType) -> list[Any]:
        del stream_type
        return list(payload) if isinstance(payload, list) else [payload]


@dataclass(slots=True)
class CcxtUnifiedProfile:
    """Parameterized CCXT Pro profile using unified ``watch_*`` results."""

    entry: CcxtCatalogEntry
    market_type: str
    selection: str = field(init=False)

    def __post_init__(self) -> None:
        self.market_type = str(self.market_type or "").strip().lower()
        if not self.entry.pro:
            raise ValueError(f"{self.entry.exchange_id} has no CCXT Pro class")
        self.selection = resolve_market_selection(self.entry, self.market_type)

    @property
    def exchange_id(self) -> str:
        return self.entry.exchange_id

    def supports(self, descriptor: StreamDescriptor) -> bool:
        if (
            descriptor.exchange.strip().lower() != self.exchange_id
            or resolve_market_selection(
                self.entry,
                descriptor.market_type,
            ) != self.selection
        ):
            return False
        methods = _GENERIC_STREAM_METHODS.get(descriptor.stream_type)
        if methods is None or methods[0] is None or not self.entry.supports(methods[0]):
            return False
        if descriptor.stream_type in {
            StreamType.MARK_PRICE,
            StreamType.INDEX_PRICE,
            StreamType.FUNDING_RATE,
            StreamType.OPEN_INTEREST,
            StreamType.LIQUIDATION,
            StreamType.PREMIUM_INDEX,
        } and market_selection_parts(self.selection)[0] not in {"swap", "future"}:
            return False
        if (
            descriptor.stream_type == StreamType.KLINE
            and self.entry.timeframes
            and descriptor.interval not in self.entry.timeframes
        ):
            return False
        if descriptor.stream_type == StreamType.DEPTH:
            return descriptor.depth_levels in {5, 10, 20}
        return True

    def create_exchange(
        self,
        config: IngestionConfig,
        *,
        raw_event_sink: Any,
        lifecycle_sink: Any,
    ) -> Any:
        del raw_event_sink, lifecycle_sink
        return _create_exchange(
            self.entry,
            config,
            market_type=self.selection,
            websocket=True,
        )

    def resolve_symbol(self, exchange: Any, descriptor: StreamDescriptor) -> str:
        return resolve_ccxt_symbol(
            exchange,
            descriptor,
            market_type=self.selection,
        )

    async def watch(
        self,
        exchange: Any,
        descriptor: StreamDescriptor,
        ccxt_symbol: str,
    ) -> Any:
        if descriptor.stream_type == StreamType.KLINE:
            return await exchange.watch_ohlcv(ccxt_symbol, descriptor.interval)
        if descriptor.stream_type == StreamType.TRADE:
            return await exchange.watch_trades(ccxt_symbol)
        if descriptor.stream_type == StreamType.DEPTH:
            # Venue depth ladders differ (for example Bybit starts at 50 and
            # Kraken at 10).  Let CCXT choose a valid upstream default, then
            # the projector enforces CandleScope's logical 5/10/20 bound.
            return await exchange.watch_order_book(ccxt_symbol)
        if descriptor.stream_type == StreamType.TICKER:
            return await exchange.watch_ticker(ccxt_symbol)
        if descriptor.stream_type == StreamType.MINI_TICKER:
            return await exchange.watch_ticker(ccxt_symbol)
        if descriptor.stream_type in {StreamType.MARK_PRICE, StreamType.INDEX_PRICE}:
            return await exchange.watch_mark_price(ccxt_symbol)
        if descriptor.stream_type == StreamType.FUNDING_RATE:
            return await exchange.watch_funding_rate(ccxt_symbol)
        if descriptor.stream_type == StreamType.LIQUIDATION:
            return await exchange.watch_liquidations(ccxt_symbol)
        raise ValueError(f"Unsupported CCXT unified stream: {descriptor.stream_type.value}")

    @staticmethod
    def matches(event: Any, descriptor: StreamDescriptor) -> bool:
        del event, descriptor
        # Unified profiles project the return value of their own watch call;
        # they never demultiplex raw exchange envelopes.
        return False

    def runtime_key(self, config: IngestionConfig) -> tuple[str, ...]:
        return (
            "ccxt-unified",
            self.exchange_id,
            self.selection,
            config.proxy_mode,
            config.http_proxy or "",
        )

    def make_projector(
        self,
        descriptor: StreamDescriptor,
    ) -> CcxtUnifiedProjector:
        return CcxtUnifiedProjector(
            exchange_id=self.exchange_id,
            market_type=self.market_type,
            descriptor=descriptor,
        )


class CcxtUnifiedPlugin(BuiltinExchangePlugin):
    """One registry plugin generated from a pinned CCXT exchange class."""

    def __init__(self, entry: CcxtCatalogEntry) -> None:
        self.entry = entry
        capabilities = build_ccxt_capabilities(entry)
        adapter = CcxtUnifiedAdapter(entry, capabilities)
        delay = max(0.001, entry.rate_limit_ms / 1000.0)
        super().__init__(
            adapter,
            protocol=CcxtUnifiedProtocol(),
            normalizer_factory=lambda _config, descriptor: CcxtUnifiedNormalizer(
                descriptor,
            ),
            symbol_normalizer=CcxtSymbolNormalizer(),
            rate_limit_policy_factory=lambda _config: RateLimitPolicy(
                default_concurrency=1,
                default_delay_seconds=delay,
                default_retry_429_backoff_seconds=max(5.0, delay * 10),
            ),
            pagination_policy_factory=lambda _config: CcxtHistoricalPaginationPolicy(),
            price_stream_type_factory=lambda _market_type: StreamType.TICKER,
        )
        self._rest_book_revision = 0
        self._rest_pools: dict[int, tuple[IngestionConfig, _RestExchangePool]] = {}
        self._rest_pools_closing: set[int] = set()

    def _rest_pool(self, config: IngestionConfig) -> _RestExchangePool:
        key = id(config)
        if key in self._rest_pools_closing:
            raise RuntimeError("CCXT REST transport is closing")
        current = self._rest_pools.get(key)
        if current is not None and current[0] is config:
            return current[1]
        pool = _RestExchangePool(self.entry, config)
        self._rest_pools[key] = (config, pool)
        return pool

    async def close_history_transport(self, config: IngestionConfig) -> None:
        """Close only the REST clients owned by one transport configuration."""

        current = self._rest_pools.get(id(config))
        if current is None or current[0] is not config:
            return
        key = id(config)
        self._rest_pools_closing.add(key)
        self._rest_pools.pop(key, None)
        try:
            await current[1].close()
        finally:
            self._rest_pools_closing.discard(key)

    def history_transport_snapshot(
        self,
        config: IngestionConfig,
    ) -> dict[str, Any] | None:
        # Every pinned CCXT ID registers a plugin.  Report only the venues this
        # transport actually used so diagnostics do not list hundreds of
        # empty pools.
        current = self._rest_pools.get(id(config))
        if current is None or current[0] is not config:
            return None
        return current[1].snapshot()

    def supports_provider_stream(self, descriptor: StreamDescriptor) -> bool:
        if not self.entry.pro:
            return False
        try:
            profile = CcxtUnifiedProfile(self.entry, descriptor.market_type)
        except ValueError:
            return False
        return profile.supports(descriptor)

    @staticmethod
    def provider_stream_enabled(
        config: IngestionConfig,
        descriptor: StreamDescriptor,
    ) -> bool:
        del descriptor
        return bool(getattr(config, "ccxt_unified_stream_enabled", True))

    def create_stream_session(
        self,
        config: IngestionConfig,
        descriptor: StreamDescriptor,
    ) -> Any | None:
        if not self.provider_stream_enabled(config, descriptor):
            return None
        try:
            profile = CcxtUnifiedProfile(self.entry, descriptor.market_type)
        except ValueError:
            return None
        if not profile.supports(descriptor):
            return None
        from .session import CcxtProviderSession

        return CcxtProviderSession(
            config=config,
            descriptor=descriptor,
            profile=profile,
        )

    async def fetch_history(self, req: TransportRequest) -> list[RawMessage]:
        """Compatibility one-shot fetch without leaking a config-scoped pool."""

        config = IngestionConfig()
        try:
            return await self.fetch_history_with_config(req, config)
        finally:
            await self.close_history_transport(config)

    async def fetch_history_with_config(
        self,
        req: TransportRequest,
        config: IngestionConfig,
    ) -> list[RawMessage]:
        descriptor = req.descriptor
        methods = _GENERIC_STREAM_METHODS.get(descriptor.stream_type)
        rest_method = _rest_method_for(req, self.entry)
        if methods is None or rest_method is None or not self.entry.supports(rest_method):
            raise ValueError(
                f"{self.id} does not support CCXT REST {descriptor.stream_type.value}",
            )
        selection = resolve_market_selection(self.entry, descriptor.market_type)
        if descriptor.stream_type in {
            StreamType.MARK_PRICE,
            StreamType.INDEX_PRICE,
            StreamType.FUNDING_RATE,
            StreamType.OPEN_INTEREST,
            StreamType.LIQUIDATION,
            StreamType.PREMIUM_INDEX,
        } and market_selection_parts(selection)[0] not in {"swap", "future"}:
            raise ValueError(
                f"{self.id} derivatives stream requires a contract market",
            )
        pool = self._rest_pool(config)
        async with pool.request(selection) as exchange:
            symbol = await pool.resolve_symbol(
                selection,
                exchange,
                descriptor,
                market_type=selection,
            )
            rows: list[dict[str, Any]] = []
            if descriptor.stream_type == StreamType.KLINE:
                limit = min(max(1, int(req.limit or 1)), self.entry.history_limit)
                values = await exchange.fetch_ohlcv(
                    symbol,
                    timeframe=descriptor.interval,
                    since=req.start_ms,
                    limit=limit,
                )
                interval_ms = int(ccxt.Exchange.parse_timeframe(descriptor.interval) * 1000)
                now_ms = int(time.time() * 1000)
                rows = [
                    make_unified_payload(
                        "kline",
                        list(row[:6]),
                        is_closed=int(row[0]) + interval_ms <= now_ms,
                    )
                    for row in values
                    if isinstance(row, (list, tuple))
                    and len(row) >= 6
                    and (req.end_ms is None or int(row[0]) <= req.end_ms)
                ]
            elif descriptor.stream_type == StreamType.TRADE:
                values = await exchange.fetch_trades(
                    symbol,
                    since=req.start_ms,
                    limit=max(1, int(req.limit or 1)),
                )
                rows = [
                    make_unified_payload("trade", dict(value))
                    for value in values
                    if isinstance(value, dict)
                    and (
                        req.end_ms is None
                        or _timestamp(value.get("timestamp")) is None
                        or int(value["timestamp"]) <= req.end_ms
                    )
                ]
            elif descriptor.stream_type == StreamType.DEPTH:
                value = await exchange.fetch_order_book(
                    symbol,
                )
                self._rest_book_revision += 1
                rows = [
                    make_unified_payload(
                        "order_book",
                        dict(value),
                        local_revision=self._rest_book_revision,
                    )
                ]
            elif descriptor.stream_type in {StreamType.TICKER, StreamType.MINI_TICKER}:
                value = await exchange.fetch_ticker(symbol)
                rows = [make_unified_payload("ticker", dict(value))]
            elif descriptor.stream_type in {StreamType.MARK_PRICE, StreamType.INDEX_PRICE}:
                value = await exchange.fetch_mark_price(symbol)
                rows = [make_unified_payload("derivatives_summary", dict(value))]
            elif descriptor.stream_type == StreamType.FUNDING_RATE:
                if req.history or req.start_ms is not None or req.end_ms is not None:
                    values = await exchange.fetch_funding_rate_history(
                        symbol,
                        since=req.start_ms,
                        limit=max(1, int(req.limit or 1)),
                    )
                else:
                    values = [await exchange.fetch_funding_rate(symbol)]
                rows = [
                    make_unified_payload("funding_rate", dict(value))
                    for value in values
                    if isinstance(value, dict)
                ]
            elif descriptor.stream_type == StreamType.OPEN_INTEREST:
                if (
                    (req.history or req.start_ms is not None or req.end_ms is not None)
                    and self.entry.supports("fetchOpenInterestHistory")
                ):
                    values = await exchange.fetch_open_interest_history(
                        symbol,
                        timeframe=descriptor.interval,
                        since=req.start_ms,
                        limit=max(1, int(req.limit or 1)),
                    )
                else:
                    values = [await exchange.fetch_open_interest(symbol)]
                rows = [
                    make_unified_payload("open_interest", dict(value))
                    for value in values
                    if isinstance(value, dict)
                ]
            elif descriptor.stream_type == StreamType.LIQUIDATION:
                values = await exchange.fetch_liquidations(
                    symbol,
                    since=req.start_ms,
                    limit=max(1, int(req.limit or 1)),
                )
                rows = [
                    make_unified_payload("liquidation", dict(value))
                    for value in values
                    if isinstance(value, dict)
                ]
            elif descriptor.stream_type == StreamType.PREMIUM_INDEX:
                values = await exchange.fetch_premium_index_ohlcv(
                    symbol,
                    timeframe=descriptor.interval,
                    since=req.start_ms,
                    limit=max(1, int(req.limit or 1)),
                )
                rows = [
                    make_unified_payload("premium_index", list(value[:6]))
                    for value in values
                    if isinstance(value, (list, tuple)) and len(value) >= 6
                ]
            received = int(time.time() * 1000)
            return [
                RawMessage(
                    payload=row,
                    source=DataSource.HTTP,
                    stream_type=descriptor.stream_type,
                    received_at_ms=received,
                    endpoint=f"ccxt+rest://{self.id}",
                    http_status=200,
                    request_limit=req.limit,
                )
                for row in rows
            ]


def register_ccxt_plugins(registry: Any) -> int:
    """Register every pinned CCXT ID not owned by a stricter plugin."""

    registered = 0
    for entry in get_ccxt_catalog():
        if registry.has(entry.exchange_id):
            continue
        registry.register(
            CcxtUnifiedPlugin(entry),
            source=f"builtin:ccxt:{entry.exchange_id}",
        )
        registered += 1
    return registered


def resolve_ccxt_symbol(
    exchange: Any,
    descriptor: StreamDescriptor,
    *,
    market_type: str | None = None,
) -> str:
    requested = str(descriptor.symbol or "").strip()
    selection = str(market_type or descriptor.market_type).strip().lower()
    candidates = [
        market
        for market in exchange.markets.values()
        if market_matches_selection(market, selection)
        and (
            str(market.get("symbol") or "") == requested
            or str(market.get("symbol") or "").upper() == requested.upper()
            or str(market.get("id") or "").upper() == requested.upper()
        )
    ]
    by_symbol = {
        str(market.get("symbol")): market
        for market in candidates
        if str(market.get("symbol") or "").strip()
    }
    if len(by_symbol) != 1:
        raise ValueError(
            f"unable to resolve one {selection} CCXT symbol for "
            f"{descriptor.exchange}:{requested}",
        )
    return next(iter(by_symbol))


def resolve_market_selection(
    entry: CcxtCatalogEntry,
    market_type: str,
) -> str:
    """Resolve CandleScope's legacy ``futures`` name to one CCXT family."""

    requested = str(market_type or "spot").strip().lower()
    if requested in entry.market_types:
        return requested
    if requested == "futures":
        for candidate in ("swap.linear", "swap", "future.linear", "future"):
            if candidate in entry.market_types:
                return candidate
    raise ValueError(
        f"{entry.exchange_id} does not advertise CCXT market type {requested!r}",
    )


def _rest_method_for(
    req: TransportRequest,
    entry: CcxtCatalogEntry,
) -> str | None:
    stream_type = req.descriptor.stream_type
    ranged = req.history or req.start_ms is not None or req.end_ms is not None
    if stream_type == StreamType.FUNDING_RATE:
        return "fetchFundingRateHistory" if ranged else "fetchFundingRate"
    if stream_type == StreamType.OPEN_INTEREST:
        if ranged and entry.supports("fetchOpenInterestHistory"):
            return "fetchOpenInterestHistory"
        return "fetchOpenInterest"
    methods = _GENERIC_STREAM_METHODS.get(stream_type)
    return methods[1] if methods is not None else None


def _create_exchange(
    entry: CcxtCatalogEntry,
    config: IngestionConfig,
    *,
    market_type: str,
    websocket: bool,
) -> Any:
    assert_supported_ccxt_version()
    module = ccxtpro if websocket else ccxt_async
    if websocket and not entry.pro:
        raise ValueError(f"{entry.exchange_id} has no CCXT Pro implementation")
    base_type, subtype = market_selection_parts(market_type)
    exchange_id = entry.exchange_id
    if entry.exchange_id == "binance" and base_type in {"swap", "future"}:
        # ``ccxt.binance`` loads spot, USD-M, and COIN-M market catalogs in one
        # call even when defaultType points at a derivative family.  A transient
        # spot exchangeInfo failure would therefore block an otherwise healthy
        # USD-M history request and leave visible K-line, OI, or Funding gaps.
        # Use the venue-specific CCXT subclasses so catalog bootstrap and every
        # later implicit request stay on the selected derivative rail.
        exchange_id = "binancecoinm" if subtype == "inverse" else "binanceusdm"
    exchange_class = _owned_exchange_class(
        getattr(module, exchange_id),
        windows=sys.platform == "win32",
    )
    options: dict[str, Any] = {"defaultType": base_type}
    if subtype is not None:
        options["defaultSubType"] = subtype
    values: dict[str, Any] = {
        "enableRateLimit": True,
        "newUpdates": True,
        "aiohttp_trust_env": config.proxy_mode == "system",
        "options": options,
    }
    if config.http_proxy and config.proxy_mode != "none":
        values["httpsProxy"] = config.http_proxy
        values["wssProxy"] = config.http_proxy
    return exchange_class(values)


def _product_type(market_type: str) -> str:
    base, _subtype = market_selection_parts(market_type)
    return {
        "spot": "spot",
        "swap": "perpetual",
        "future": "delivery_future",
        "option": "option",
    }[base]


def _contract_type(market_type: str) -> str:
    base, subtype = market_selection_parts(market_type)
    if base not in {"swap", "future"}:
        return ""
    return (subtype or "exchange_default").upper()


def _timestamp(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _price_tick_size(exchange: Any, market: dict[str, Any]) -> str:
    precision = (market.get("precision") or {}).get("price")
    if isinstance(precision, bool) or precision is None:
        return ""
    try:
        if exchange.precisionMode == ccxt.TICK_SIZE:
            tick = Decimal(str(precision))
        else:
            tick = Decimal(1).scaleb(-int(precision))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return ""
    if not tick.is_finite() or tick <= 0:
        return ""
    return format(tick, "f")
