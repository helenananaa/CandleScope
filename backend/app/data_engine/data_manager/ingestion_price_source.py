"""DataManager price source backed by the ingestion pipeline."""
from __future__ import annotations

import logging
import inspect
from typing import Any, Awaitable, Callable

from .subscriptions import format_subscription_key, parse_subscription_key

logger = logging.getLogger("data_manager.ingestion_price_source")

PriceUpdateCallback = Callable[[list[Any]], Awaitable[None]]


class IngestionPriceSource:
    """Start and stop ingestion ticker streams for watched price symbols."""

    def __init__(self, ingestion_factory: Any, *, availability: Any = None) -> None:
        self._factory = ingestion_factory
        self._availability = availability
        self._handles: dict[str, Any] = {}
        self._probes: dict[str, Any] = {}
        self._multi_handles: dict[tuple[str, str], Any] = {}
        self._multi_symbols: dict[tuple[str, str], set[str]] = {}
        self._callbacks: list[PriceUpdateCallback] = []

    def on_price_update(self, callback: PriceUpdateCallback) -> None:
        self._callbacks.append(callback)

    async def ensure_symbol(self, key: str) -> None:
        normalized_key = self._normalize_key(key)
        if normalized_key in self._handles:
            return
        exchange, market_type, symbol = parse_subscription_key(normalized_key)
        if self._supports_multi_symbol_ticker():
            await self._ensure_multi_symbol(exchange, market_type, symbol)
            return
        start_price = getattr(self._factory, "start_price", None)
        if not callable(start_price):
            logger.warning("Ingestion factory does not support price streams")
            return
        options: dict[str, Any] = {"on_price": self._emit_price_update}
        probe = None
        if self._availability is not None and _accepts(start_price, "on_health"):
            # Watchlist prices report their ticker session health so the
            # browser can mark them stale while the exchange is unreachable.
            probe = self._availability.probe("price", exchange, market_type, symbol)
            options["on_health"] = probe.health
            options["on_price"] = self._observed_price_callback(probe)
        try:
            handle = await start_price(
                symbol=symbol,
                exchange=exchange,
                market_type=market_type,
                **options,
            )
        except BaseException:
            if probe is not None:
                probe.close()
            raise
        self._handles[normalized_key] = handle
        if probe is not None:
            self._probes[normalized_key] = probe

    async def remove_symbol(self, key: str) -> None:
        normalized_key = self._normalize_key(key)
        exchange, market_type, symbol = parse_subscription_key(normalized_key)
        if self._supports_multi_symbol_ticker():
            await self._remove_multi_symbol(exchange, market_type, symbol)
            return
        handle = self._handles.pop(normalized_key, None)
        probe = self._probes.pop(normalized_key, None)
        if probe is not None:
            probe.close()
        if handle is None:
            return
        stop = getattr(handle, "stop", None)
        if callable(stop):
            await stop()

    async def stop(self) -> None:
        for key in list(self._handles):
            await self.remove_symbol(key)
        for group in list(self._multi_handles):
            await self._stop_multi_group(group)

    async def shutdown(self) -> None:
        await self.stop()

    def _observed_price_callback(self, probe: Any) -> Callable[[Any], Awaitable[None]]:
        async def on_price(item: Any) -> None:
            probe.observe_data()
            await self._emit_price_update(item)
        return on_price

    async def _emit_price_update(self, item: Any) -> None:
        for callback in list(self._callbacks):
            try:
                await callback([item])
            except Exception as exc:
                logger.warning("Price update callback failed: %s", exc)

    def _supports_multi_symbol_ticker(self) -> bool:
        return callable(getattr(self._factory, "start_price_many", None))

    async def _ensure_multi_symbol(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> None:
        group = (exchange, market_type)
        symbols = self._multi_symbols.setdefault(group, set())
        if symbol in symbols and group in self._multi_handles:
            return
        symbols.add(symbol)
        handle = self._multi_handles.get(group)
        if handle is None:
            start_price_many = getattr(self._factory, "start_price_many")
            handle = await start_price_many(
                symbols=sorted(symbols),
                exchange=exchange,
                market_type=market_type,
                on_price=self._emit_price_update,
            )
            self._multi_handles[group] = handle
            return
        await self._update_multi_symbols(handle, symbols)

    async def _remove_multi_symbol(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> None:
        group = (exchange, market_type)
        symbols = self._multi_symbols.get(group)
        if not symbols or symbol not in symbols:
            return
        symbols.discard(symbol)
        handle = self._multi_handles.get(group)
        if not symbols:
            await self._stop_multi_group(group)
            return
        if handle is not None:
            await self._update_multi_symbols(handle, symbols)

    async def _stop_multi_group(self, group: tuple[str, str]) -> None:
        self._multi_symbols.pop(group, None)
        handle = self._multi_handles.pop(group, None)
        if handle is None:
            return
        stop = getattr(handle, "stop", None)
        if callable(stop):
            result = stop()
            if inspect.isawaitable(result):
                await result

    @staticmethod
    async def _update_multi_symbols(handle: Any, symbols: set[str]) -> None:
        updater = getattr(handle, "set_symbols", None)
        if not callable(updater):
            updater = getattr(handle, "set_watched_symbols", None)
        if not callable(updater):
            return
        result = updater(sorted(symbols))
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _normalize_key(key: str) -> str:
        exchange, market_type, symbol = parse_subscription_key(key)
        return format_subscription_key(exchange, market_type, symbol)


def _accepts(function: Any, name: str) -> bool:
    try:
        return name in inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
