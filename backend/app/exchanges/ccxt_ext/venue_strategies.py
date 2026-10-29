"""Typed venue policies and stream profiles used by the one CCXT provider."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from typing import Any

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import (
    RawMessage,
    StreamDescriptor,
    StreamType,
)
from app.data_engine.market_data.models import MarketChannel, TransportMode
from app.exchanges.models import ExchangeCapabilities
from app.exchanges.plugin import DefaultSymbolNormalizer
from app.exchanges.realtime import RealtimePolicy, RealtimeUpdateMode

from .generic import (
    CcxtUnifiedAdapter,
    CcxtUnifiedProfile,
)
from .venue_history import _okx_index_symbol
from .unified import CCXT_UNIFIED_MARKER, CcxtUnifiedNormalizer


class OkxCombinedSummaryProfile:
    """Merge independent OKX mark/index/funding CCXT subscriptions safely."""

    exchange_id = "okx"
    market_type = "futures"

    def __init__(self, entry: Any) -> None:
        self._delegate = CcxtUnifiedProfile(entry, self.market_type)
        self._exchange: Any | None = None
        self._watch_lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._latest: dict[str, Any] = {}

    def supports(self, descriptor: StreamDescriptor) -> bool:
        return (
            descriptor.exchange.strip().lower() == self.exchange_id
            and descriptor.market_type.strip().lower() == self.market_type
            and descriptor.stream_type
            in {
                StreamType.MARK_PRICE,
                StreamType.INDEX_PRICE,
            }
        )

    def create_exchange(self, *args: Any, **kwargs: Any) -> Any:
        return self._delegate.create_exchange(*args, **kwargs)

    def resolve_symbol(self, exchange: Any, descriptor: StreamDescriptor) -> str:
        return self._delegate.resolve_symbol(exchange, descriptor)

    async def watch(
        self,
        exchange: Any,
        descriptor: StreamDescriptor,
        ccxt_symbol: str,
    ) -> dict[str, Any]:
        async with self._watch_lock:
            return await self._watch_locked(exchange, descriptor, ccxt_symbol)

    async def _watch_locked(
        self,
        exchange: Any,
        descriptor: StreamDescriptor,
        ccxt_symbol: str,
    ) -> dict[str, Any]:
        del descriptor
        if self._exchange is not exchange:
            await self.close()
            self._exchange = exchange
        index_symbol = _okx_index_symbol(exchange, ccxt_symbol)
        factories = {
            "mark": lambda: exchange.watch_mark_price(ccxt_symbol),
            "index": lambda: exchange.watch_ticker(
                index_symbol,
                params={"channel": "index-tickers"},
            ),
            "funding": lambda: exchange.watch_funding_rate(ccxt_symbol),
        }
        for key, factory in factories.items():
            if key not in self._tasks:
                self._tasks[key] = asyncio.create_task(factory())
        done, _pending = await asyncio.wait(
            tuple(self._tasks.values()),
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            key = next(
                (name for name, value in self._tasks.items() if value is task),
                None,
            )
            if key is None:
                raise asyncio.CancelledError
            self._tasks.pop(key, None)
            value = task.result()
            if isinstance(value, dict):
                self._latest[key] = dict(value)
        result: dict[str, Any] = {}
        mark = self._latest.get("mark")
        index = self._latest.get("index")
        funding = self._latest.get("funding")
        if isinstance(mark, dict):
            result["markPrice"] = mark.get("markPrice")
            result["timestamp"] = mark.get("timestamp")
        if isinstance(index, dict):
            result["indexPrice"] = index.get("indexPrice") or index.get("last")
            result["timestamp"] = max(
                int(result.get("timestamp") or 0),
                int(index.get("timestamp") or 0),
            )
        if isinstance(funding, dict):
            result["fundingRate"] = funding.get("fundingRate")
            result["nextFundingTimestamp"] = funding.get("nextFundingTimestamp")
            result["fundingTimestamp"] = funding.get("fundingTimestamp")
        result["info"] = {
            key: value.get("info")
            for key, value in self._latest.items()
            if isinstance(value, dict)
        }
        return result

    @staticmethod
    def matches(event: Any, descriptor: StreamDescriptor) -> bool:
        return CcxtUnifiedProfile.matches(event, descriptor)

    def runtime_key(self, config: IngestionConfig) -> tuple[str, ...]:
        return self._delegate.runtime_key(config)

    def make_projector(self, descriptor: StreamDescriptor) -> Any:
        return self._delegate.make_projector(descriptor)

    async def close(self) -> None:
        tasks = tuple(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._latest.clear()
        self._exchange = None


class CcxtPrimaryAdapter(CcxtUnifiedAdapter):
    """CCXT catalog adapter that preserves CandleScope's native symbol IDs."""

    eager_catalog_refresh = True
    native_symbol_ids = True


@dataclass(slots=True)
class _VenueContractBundle:
    capabilities_value: ExchangeCapabilities
    normalizer_factory: Any
    symbol_normalizer_value: Any
    rate_limit_factory: Any
    pagination_factory: Any
    realtime_policy_value: RealtimePolicy
    price_stream_type_value: StreamType
    history_archive_provider_factory: Any

    def capabilities(self) -> ExchangeCapabilities:
        return self.capabilities_value

    def normalizer(self, config: Any, descriptor: Any) -> Any:
        return self.normalizer_factory(config, descriptor)

    def symbol_normalizer(self) -> Any:
        return self.symbol_normalizer_value

    def rate_limit_policy(self, config: Any = None) -> Any:
        return self.rate_limit_factory(config)

    def pagination_policy(self, config: Any = None) -> Any:
        return self.pagination_factory(config)

    def realtime_policy(self) -> RealtimePolicy:
        return self.realtime_policy_value

    def price_stream_type(self, market_type: str = "spot") -> StreamType:
        del market_type
        return self.price_stream_type_value


class CcxtPrimaryNormalizer:
    def __init__(
        self,
        descriptor: StreamDescriptor,
        native_normalizer: Any,
    ) -> None:
        self._unified = CcxtUnifiedNormalizer(descriptor)
        self._native = native_normalizer
        self._descriptor = descriptor

    def parse(self, message: RawMessage) -> Any:
        payload = message.payload
        if isinstance(payload, dict) and str(payload.get("schema", "")).startswith(("candlescope.binance.", "candlescope.okx.")):
            from .fork_kline import normalize_fork_kline

            return normalize_fork_kline(message, self._descriptor)
        if isinstance(payload, dict) and payload.get("schema") == CCXT_UNIFIED_MARKER:
            return self._unified.parse(message)
        return self._native.parse(message)


def _legacy_contract_plugin(venue: str) -> _VenueContractBundle:
    if venue == "binance":
        from app.exchanges.plugins.binance.adapter import BinanceExchangeAdapter
        from app.exchanges.plugins.binance.normalizer import BinanceNormalizer
        from app.exchanges.plugins.binance.plugin import BinancePlugin
        from app.exchanges.plugins.binance.symbols import BinanceSymbolNormalizer

        adapter = object.__new__(BinanceExchangeAdapter)
        return _VenueContractBundle(
            capabilities_value=BinanceExchangeAdapter.capabilities(adapter),
            normalizer_factory=BinanceNormalizer,
            symbol_normalizer_value=BinanceSymbolNormalizer(),
            rate_limit_factory=BinancePlugin._rate_limit_policy,
            pagination_factory=BinancePlugin._pagination_policy,
            realtime_policy_value=RealtimePolicy(),
            price_stream_type_value=StreamType.MINI_TICKER,
            history_archive_provider_factory=BinancePlugin._history_archive_provider,
        )
    from app.exchanges.plugins.okx.adapter import OkxExchangeAdapter
    from app.exchanges.plugins.okx.normalizer import OkxNormalizer
    from app.exchanges.plugins.okx.plugin import OkxPlugin

    adapter = object.__new__(OkxExchangeAdapter)
    return _VenueContractBundle(
        capabilities_value=OkxExchangeAdapter.capabilities(adapter),
        normalizer_factory=OkxNormalizer,
        symbol_normalizer_value=DefaultSymbolNormalizer(),
        rate_limit_factory=OkxPlugin._rate_limit_policy,
        pagination_factory=OkxPlugin._pagination_policy,
        realtime_policy_value=RealtimePolicy(
            update_mode=RealtimeUpdateMode.BASE_INTERVAL_FANOUT,
        ),
        price_stream_type_value=StreamType.TICKER,
        history_archive_provider_factory=OkxPlugin._history_archive_provider,
    )


def _merge_primary_capabilities(
    legacy: ExchangeCapabilities,
    generic: ExchangeCapabilities,
) -> ExchangeCapabilities:
    merged = copy.deepcopy(legacy)
    if merged.exchange == "binance":
        # These channels now consume CCXT unified values.  Their former native
        # capability documents claimed exchange sequence IDs or venue-only
        # fields that CCXT intentionally does not promise.
        replaced_channels = {
            MarketChannel.TRADE,
            MarketChannel.TICKER,
            MarketChannel.DEPTH,
        }
        merged.channels = [
            channel
            for channel in merged.channels
            if channel.channel not in replaced_channels
        ]
    occupied = {
        (channel.channel, market_type)
        for channel in merged.channels
        for market_type in channel.market_types
    }
    for channel in copy.deepcopy(generic.channels):
        # Binance/OKX keep their stable public ``spot``/``futures`` product
        # identities.  CCXT's richer family names remain available on generic
        # exchange plugins, while the primary venues map linear swaps back to
        # the long-lived CandleScope futures contract.
        market_types: list[str] = []
        if "spot" in channel.market_types:
            market_types.append("spot")
        if "swap.linear" in channel.market_types:
            market_types.append("futures")
        channel.market_types = tuple(
            market_type
            for market_type in market_types
            if (channel.channel, market_type) not in occupied
        )
        if not channel.market_types:
            continue
        merged.channels.append(channel)
        occupied.update(
            (channel.channel, market_type) for market_type in channel.market_types
        )
    for channel in merged.channels:
        if TransportMode.WEBSOCKET in channel.realtime_transports:
            channel.realtime_transports = tuple(
                TransportMode.PLUGIN_STREAM
                if transport == TransportMode.WEBSOCKET
                else transport
                for transport in channel.realtime_transports
            )
        if channel.connection_model not in {None, "polling_only"}:
            channel.connection_model = "plugin_sidecar"
    merged.protocol_features = list(
        dict.fromkeys(
            [
                *merged.protocol_features,
                *generic.protocol_features,
                "provider.ccxt_primary",
                "native_transport.retired",
            ]
        )
    )
    merged.ws_connection_model = "plugin_sidecar"
    merged.known_limitations = list(
        dict.fromkeys(
            [
                *merged.known_limitations,
                "All physical public market-data I/O is owned by pinned CCXT",
                "Strict aggregate-trade and full-depth semantics use CCXT raw event hooks",
            ]
        )
    )
    return merged


def stream_profile(entry, descriptor):
    from .profiles import BinanceSpotCcxtProfile, BinanceUsdmCcxtProfile, OkxSpotCcxtProfile, OkxSwapCcxtProfile
    factories = {
        "binance": (BinanceSpotCcxtProfile, BinanceUsdmCcxtProfile),
        "okx": (OkxSpotCcxtProfile, OkxSwapCcxtProfile),
    }
    for factory in factories.get(entry.exchange_id, ()):
        profile = factory()
        if profile.supports(descriptor):
            return profile
    if entry.exchange_id == "okx" and descriptor.market_type == "futures" and descriptor.stream_type in {StreamType.MARK_PRICE, StreamType.INDEX_PRICE}:
        return OkxCombinedSummaryProfile(entry)
    if not entry.pro:
        return None
    try:
        profile = CcxtUnifiedProfile(entry, descriptor.market_type)
    except ValueError:
        return None
    return profile if profile.supports(descriptor) else None
