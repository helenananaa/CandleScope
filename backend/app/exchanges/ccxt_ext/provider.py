"""One CCXT connector, with venue data and finite protocol strategies.

Connector identity is routing metadata, never a replacement for dataset vendor,
venue or stored series identity. Bindings adapt existing exchange-keyed callers;
they own no clients, queues, acquisition logic or persistence.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import Any

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import StreamType
from app.exchanges.realtime import RealtimePolicy
from app.exchanges.rate_limits import RateLimitPolicy

from .catalog import build_ccxt_capabilities, get_ccxt_catalog
from .generic import (
    CcxtUnifiedAdapter, CcxtUnifiedProtocol, CcxtSymbolNormalizer,
    CcxtHistoricalPaginationPolicy, _RestExchangePool,
)
from .unified import CcxtUnifiedNormalizer
from .venue_strategies import (
    CcxtPrimaryAdapter, CcxtPrimaryNormalizer, _VenueContractBundle,
    _legacy_contract_plugin, _merge_primary_capabilities, stream_profile,
)


@dataclass
class _VenueContext:
    entry: Any
    contracts: _VenueContractBundle
    adapter: CcxtUnifiedAdapter
    rest_book_revision: int = 0


class CcxtVenueBinding:
    """A route selector for exchange-keyed consumers, not another provider."""

    connector_id = "ccxt"
    manages_physical_admission = True
    _methods = frozenset({
        "adapter", "capabilities", "protocol", "normalizer", "symbol_normalizer",
        "rate_limit_policy", "pagination_policy", "realtime_policy", "price_stream_type",
        "history_archive_provider", "supports_provider_stream", "provider_stream_enabled",
        "create_stream_session", "provider_rate_limit_endpoint", "fetch_history",
        "fetch_history_with_config", "close_history_transport", "history_transport_snapshot",
    })

    def __init__(self, provider: CcxtProvider, venue: str):
        self.provider = provider
        self.id = venue
        self.name = provider.context(venue).entry.name

    @property
    def entry(self):
        return self.provider.context(self.id).entry

    def __getattr__(self, name):
        if name in self._methods:
            return partial(getattr(self.provider, name), self.id)
        raise AttributeError(name)


class CcxtProvider:
    """Registry-owned connector and sole owner of CCXT REST acquisition state."""

    id = "ccxt"

    def __init__(self, entries=None):
        self._entries = {entry.exchange_id: entry for entry in
                         (get_ccxt_catalog() if entries is None else entries)}
        self._contexts: dict[str, _VenueContext] = {}
        self._bindings: dict[str, CcxtVenueBinding] = {}
        self._pools: dict[tuple, tuple[IngestionConfig, _RestExchangePool]] = {}
        self._closing: set[tuple] = set()
        self._protocol = CcxtUnifiedProtocol()

    def venues(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def context(self, venue: str) -> _VenueContext:
        venue = venue.strip().lower()
        if venue in self._contexts:
            return self._contexts[venue]
        entry = self._entries[venue]
        generic = build_ccxt_capabilities(entry)
        if venue in {"binance", "okx"}:
            contracts = _legacy_contract_plugin(venue)
            contracts.capabilities_value = _merge_primary_capabilities(contracts.capabilities(), generic)
            adapter = CcxtPrimaryAdapter(entry, contracts.capabilities())
            native_factory = contracts.normalizer_factory
            contracts.normalizer_factory = lambda cfg, desc: CcxtPrimaryNormalizer(desc, native_factory(cfg, desc))
        else:
            delay = max(0.001, entry.rate_limit_ms / 1000.0)
            contracts = _VenueContractBundle(
                generic, lambda cfg, desc: CcxtUnifiedNormalizer(desc), CcxtSymbolNormalizer(),
                lambda cfg: RateLimitPolicy(default_concurrency=1, default_delay_seconds=delay,
                                             default_retry_429_backoff_seconds=max(5.0, delay * 10)),
                lambda cfg: CcxtHistoricalPaginationPolicy(), RealtimePolicy(), StreamType.TICKER, None,
            )
            adapter = CcxtUnifiedAdapter(entry, generic)
        context = _VenueContext(entry, contracts, adapter)
        self._contexts[venue] = context
        return context

    def bind(self, venue: str) -> CcxtVenueBinding:
        venue = venue.strip().lower()
        if venue not in self._bindings:
            self._bindings[venue] = CcxtVenueBinding(self, venue)
        return self._bindings[venue]

    def adapter(self, venue):
        return self.context(venue).adapter

    def capabilities(self, venue):
        return self.context(venue).contracts.capabilities()

    def protocol(self, venue):
        self.context(venue)
        return self._protocol

    def normalizer(self, venue, config, descriptor):
        self._assert_route(venue, descriptor)
        return self.context(venue).contracts.normalizer(config, descriptor)

    def symbol_normalizer(self, venue):
        return self.context(venue).contracts.symbol_normalizer()

    def rate_limit_policy(self, venue, config=None):
        return self.context(venue).contracts.rate_limit_policy(config)

    def pagination_policy(self, venue, config=None):
        return self.context(venue).contracts.pagination_policy(config)

    def realtime_policy(self, venue):
        return self.context(venue).contracts.realtime_policy()

    def price_stream_type(self, venue, market_type="spot"):
        return self.context(venue).contracts.price_stream_type(market_type)

    def history_archive_provider(self, venue, config=None):
        factory = self.context(venue).contracts.history_archive_provider_factory
        return factory(config) if factory is not None else None

    @staticmethod
    def _assert_route(venue, descriptor):
        if descriptor.exchange.strip().lower() != venue:
            raise ValueError("CCXT binding cannot substitute another venue's data")

    def _profile(self, venue, descriptor):
        self._assert_route(venue, descriptor)
        return stream_profile(self.context(venue).entry, descriptor)

    def supports_provider_stream(self, venue, descriptor):
        return self._profile(venue, descriptor) is not None

    def provider_stream_enabled(self, venue, config, descriptor):
        self._assert_route(venue, descriptor)
        return bool(config.ccxt_unified_stream_enabled)

    def create_stream_session(self, venue, config, descriptor):
        if not self.provider_stream_enabled(venue, config, descriptor):
            return None
        profile = self._profile(venue, descriptor)
        if profile is None:
            return None
        from .session import CcxtProviderSession
        return CcxtProviderSession(config=config, descriptor=descriptor, profile=profile)

    def provider_rate_limit_endpoint(self, venue, req):
        self._assert_route(venue, req.descriptor)
        from .venue_history import rate_limit_endpoint
        return rate_limit_endpoint(venue, req)

    def _rest_pool(self, venue, config):
        # A connector may be called by multiple backend worker loops. Network
        # objects and asyncio locks never move between them.
        key = (venue, asyncio.get_running_loop(), id(config))
        if key in self._closing:
            raise RuntimeError("CCXT REST transport is closing")
        current = self._pools.get(key)
        if current is None:
            current = (config, _RestExchangePool(self.context(venue).entry, config))
            self._pools[key] = current
        return current[1]

    async def close_history_transport(self, venue, config):
        key = (venue, asyncio.get_running_loop(), id(config))
        current = self._pools.pop(key, None)
        if current is None:
            return
        self._closing.add(key)
        try:
            await current[1].close()
        finally:
            self._closing.discard(key)

    def history_transport_snapshot(self, venue, config):
        try:
            key = (venue, asyncio.get_running_loop(), id(config))
        except RuntimeError:
            return None
        current = self._pools.get(key)
        return current[1].snapshot() if current else None

    async def fetch_history(self, venue, req):
        config = IngestionConfig()
        try:
            return await self.fetch_history_with_config(venue, req, config)
        finally:
            await self.close_history_transport(venue, config)

    async def fetch_history_with_config(self, venue, req, config):
        self._assert_route(venue, req.descriptor)
        from .history import fetch_unified_history
        from .venue_history import HISTORY_STRATEGIES
        from .source_capture import REST_CAPTURE
        from app.core.executors import run_storage
        from app.data_engine.storage import market_sources

        captured = []
        token = REST_CAPTURE.set(captured) if config.ccxt_fork_kline_enabled else None
        try:
            pool = self._rest_pool(venue, config)
            strategy = HISTORY_STRATEGIES.get((venue, req.descriptor.stream_type))
            if strategy is not None:
                return await strategy(req, config, pool)
            return await fetch_unified_history(self.context(venue), req, config, pool)
        finally:
            if token is not None:
                REST_CAPTURE.reset(token)
                if captured:
                    await run_storage(market_sources.record_rest, req.descriptor, captured)

    def diagnostics(self):
        return {"connector_id": self.id, "venues": list(self.venues()),
                "active_rest_pools": len(self._pools), "identity_policy": "preserve_dataset_vendor_and_venue"}
