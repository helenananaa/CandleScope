"""Daily open resolver for price snapshots."""
from __future__ import annotations

import inspect
import logging
import math
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from app.core.executors import run_storage
from app.data_engine.interval_policy import (
    compute_bucket_start_ms,
    last_closed_bar_open_ms,
)
from app.data_engine.market_data.lifecycle import KeyedAsyncLockPool

from .backfill_contracts import priority_for_reason
from .price_cache import PriceSnapshot
from .query import BackfillTrigger

logger = logging.getLogger("data_manager.daily_open")

DAY_MS = 86_400_000


class DailyOpenService:
    """Resolve the current daily open without backfilling a forming 1d bar."""

    def __init__(
        self,
        *,
        storage_provider: Callable[[], Any | None],
        backfill_trigger_provider: Callable[[], BackfillTrigger | None],
        miss_ttl_seconds: float = 2.0,
        repair_retry_seconds: float = 30.0,
        max_cached_symbols: int = 4096,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._storage_provider = storage_provider
        # History repairs admit only closed candles, so request the first
        # closed minute instead of the current forming daily candle.
        self._backfill_trigger_provider = backfill_trigger_provider
        self._cache: OrderedDict[tuple[str, str, str], tuple[int, float, float]] = OrderedDict()
        self._requested: OrderedDict[tuple[str, str, str], tuple[int, float]] = OrderedDict()
        self._locks = KeyedAsyncLockPool[tuple[str, str, str]]()
        self._miss_ttl = max(0.01, float(miss_ttl_seconds))
        self._repair_retry = max(self._miss_ttl, float(repair_retry_seconds))
        self._max_cached_symbols = max(1, int(max_cached_symbols))
        self._monotonic = monotonic

    async def resolve(self, snapshot: PriceSnapshot) -> float:
        """Return the best daily open for a price snapshot."""
        bucket_start_ms = compute_bucket_start_ms(
            snapshot.updated_at_ms,
            DAY_MS,
            interval="1d",
        )
        key = (snapshot.exchange, snapshot.market_type, snapshot.symbol)
        async with self._locks.hold(key):
            cached = self._cache.get(key)
            now = self._monotonic()
            if cached is None or cached[0] != bucket_start_ms or (cached[1] <= 0 and now >= cached[2]):
                storage_open = await run_storage(self._load_from_storage, snapshot, bucket_start_ms)
                cached = (bucket_start_ms, storage_open, self._monotonic() + self._miss_ttl)
                self._cache[key] = cached
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_cached_symbols:
                self._cache.popitem(last=False)
            if cached[1] > 0:
                self._requested.pop(key, None)
                return cached[1]

            # Retry a failed/asynchronously rejected repair at a bounded rate;
            # a missing row must not pin the fallback for the rest of the day.
            self._request_open_minute_backfill(snapshot, bucket_start_ms)
        return snapshot.daily_open or snapshot.open

    def _load_from_storage(
        self,
        snapshot: PriceSnapshot,
        bucket_start_ms: int,
    ) -> float:
        storage = self._storage_provider()
        if storage is None:
            return 0.0
        for interval in ("1d", "1m"):
            try:
                rows = storage.query_bars(
                    symbol=snapshot.symbol,
                    interval=interval,
                    start_ms=bucket_start_ms,
                    end_ms=bucket_start_ms,
                    limit=1,
                    order="ASC",
                    exchange=snapshot.exchange,
                    market_type=snapshot.market_type,
                )
            except Exception as exc:
                logger.warning(
                    "Daily open storage query failed for %s:%s:%s@%s: %s",
                    snapshot.exchange,
                    snapshot.market_type,
                    snapshot.symbol,
                    interval,
                    exc,
                )
                continue
            if not rows:
                continue
            try:
                value = float(rows[0].get("open", 0) or 0)
                if math.isfinite(value) and value > 0:
                    return value
            except (TypeError, ValueError):
                continue
        return 0.0

    def _request_open_minute_backfill(
        self,
        snapshot: PriceSnapshot,
        bucket_start_ms: int,
    ) -> None:
        last_closed_minute = last_closed_bar_open_ms(snapshot.updated_at_ms, "1m")
        if last_closed_minute is None or last_closed_minute < bucket_start_ms:
            return
        request_key = (
            snapshot.exchange,
            snapshot.market_type,
            snapshot.symbol,
        )
        previous = self._requested.get(request_key)
        now = self._monotonic()
        if previous is not None and previous[0] == bucket_start_ms and now < previous[1]:
            return
        trigger = self._backfill_trigger_provider()
        if trigger is None:
            return
        self._requested[request_key] = (bucket_start_ms, now + self._repair_retry)
        self._requested.move_to_end(request_key)
        while len(self._requested) > self._max_cached_symbols:
            self._requested.popitem(last=False)
        try:
            kwargs = self._supported_trigger_kwargs(
                trigger,
                {
                    "reason": "price_daily_open",
                    "priority": priority_for_reason("price_daily_open"),
                    "requester": "daily_open",
                    "metadata": {
                        "focus_scope": "price",
                        "subscription_tier": "price",
                        "requested_interval": "1m",
                        "daily_bucket_start_ms": bucket_start_ms,
                    },
                },
            )
            trigger(
                snapshot.symbol,
                "1m",
                bucket_start_ms,
                bucket_start_ms,
                snapshot.exchange,
                snapshot.market_type,
                **kwargs,
            )
        except Exception as exc:
            logger.warning(
                "Daily open minute backfill trigger failed for %s:%s:%s: %s",
                snapshot.exchange,
                snapshot.market_type,
                snapshot.symbol,
                exc,
            )

    @staticmethod
    def _supported_trigger_kwargs(
        trigger: BackfillTrigger,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        filtered = {key: value for key, value in kwargs.items() if value is not None}
        try:
            signature = inspect.signature(trigger)
            supports_kwargs = any(
                param.kind is inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
            if not supports_kwargs:
                filtered = {
                    key: value
                    for key, value in filtered.items()
                    if key in signature.parameters
                }
        except (TypeError, ValueError):
            pass
        return filtered
