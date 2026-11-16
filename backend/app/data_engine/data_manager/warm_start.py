"""Warm-start helpers for seeding BarAggregator state."""
from __future__ import annotations

import logging
import inspect
import time
from collections.abc import Callable
from typing import Any

from app.data_engine.interval_policy import (
    is_monthly_interval,
    parse_custom_interval,
    parse_interval_spec,
    parse_monthly_count,
    row_is_closed,
)
from app.data_engine.interval_resolution import (
    IntervalPurpose,
    IntervalResolver,
    IntervalRoute,
    IntervalRouteKind,
)
from app.data_engine.kline_quality import source_is_trusted_final, source_rank
from app.data_engine.market_data.kline_metrics import declared_enhanced_fields
from app.data_engine.series_identity import KlineSeriesIdentity, SERIES_IDENTITY_METADATA_KEY

from ..bar_aggregator import (
    BarAggregator,
    BarInput,
    BarInputSource,
)
from .cache import BarCache
from .backfill_contracts import priority_for_reason
from .models import BarData, SeriesKey, StorageBackend
from .query import BackfillTrigger

logger = logging.getLogger("data_manager.warm_start")

StorageProvider = Callable[[], StorageBackend | None]
BackfillProvider = Callable[[], BackfillTrigger | None]


def _base_row_is_final(row: dict) -> bool:
    # Legacy storage adapters may omit provenance. Canonical SQLite rows and
    # cache overlays carry it and must satisfy the shared source policy.
    return row_is_closed(row) and ("source" not in row or source_is_trusted_final(row["source"]))


class AggregatorWarmStartService:
    """Seeds aggregator state from cache/storage when streams are started."""

    def __init__(
        self,
        *,
        cache: BarCache,
        bar_aggregator: BarAggregator,
        base_interval: str,
        storage_provider: StorageProvider,
        backfill_trigger_provider: BackfillProvider,
        interval_resolver: IntervalResolver | None = None,
    ) -> None:
        self._cache = cache
        self._bar_aggregator = bar_aggregator
        self._base_interval = base_interval
        self._storage_provider = storage_provider
        self._backfill_trigger_provider = backfill_trigger_provider
        self._interval_resolver = interval_resolver or IntervalResolver()
        self.history_prefix_runtime = None
        self._tail_repair_buckets: dict[SeriesKey, tuple[int, object | None]] = {}

    def reset_tail_repairs(self) -> None:
        """A replacement storage binding cannot reuse the old repair demand."""
        self._tail_repair_buckets.clear()

    async def seed_if_needed(
        self,
        symbol: str,
        interval: str,
        *,
        exchange: str,
        market_type: str,
        had_stream: bool,
        focus_scope: str = "foreground",
        subscription_tier: str | None = None,
        series_identity: KlineSeriesIdentity | None = None,
    ) -> None:
        """Seed the relevant active bucket after DataManager starts a stream."""
        market_type = self._normalize_market_type(market_type)
        route = self._interval_resolver.resolve(
            exchange=exchange,
            market_type=market_type,
            interval=interval,
            purpose=IntervalPurpose.REALTIME,
        )
        interval = route.canonical_interval
        if route.kind is IntervalRouteKind.DERIVED:
            try:
                await self._seed_custom_interval(
                    symbol,
                    interval,
                    exchange=exchange,
                    market_type=market_type,
                    focus_scope=focus_scope,
                    subscription_tier=subscription_tier,
                    route=route,
                    series_identity=series_identity,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to seed active custom bucket for %s@%s: %s",
                    symbol,
                    interval,
                    exc,
                    exc_info=True,
                )
            if not had_stream:
                self._trigger_custom_tail_repair(
                    symbol,
                    interval,
                    exchange=exchange,
                    market_type=market_type,
                    focus_scope=focus_scope,
                    subscription_tier=subscription_tier,
                    route=route,
                    series_identity=series_identity,
                )
            return

        if had_stream:
            return

        try:
            await self._seed_standard_interval(
                symbol,
                interval,
                exchange=exchange,
                market_type=market_type,
                series_identity=series_identity,
            )
        except Exception as exc:
            logger.warning(
                "Failed to seed standard interval %s@%s: %s",
                symbol,
                interval,
                exc,
                exc_info=True,
            )

    async def _seed_custom_interval(
        self,
        symbol: str,
        interval: str,
        exchange: str = "binance",
        market_type: str = "spot",
        focus_scope: str = "foreground",
        subscription_tier: str | None = None,
        route: IntervalRoute | None = None,
        series_identity: KlineSeriesIdentity | None = None,
    ) -> None:
        """Seed the currently-forming custom bucket from recent base bars."""
        symbol = symbol.upper()
        exchange = exchange.strip().lower()
        market_type = self._normalize_market_type(market_type)
        storage = self._storage_provider()
        if storage is None:
            return

        base_interval = route.base_interval if route is not None else self._base_interval
        if base_interval is None:
            raise ValueError("derived warm-start route has no base interval")
        base_seconds = parse_custom_interval(base_interval) or 60
        base_spec = parse_interval_spec(base_interval)
        now_ms = int(time.time() * 1000)
        bucket_start_ms = self._bar_aggregator.compute_bucket(
            interval, now_ms, exchange=exchange, series_identity=series_identity,
        )
        if bucket_start_ms is None:
            return
        if self.history_prefix_runtime is not None and base_spec is not None:
            source = SeriesKey.create(symbol, base_interval, exchange=exchange,
                                      market_type=market_type, identity=series_identity)
            if await self.history_prefix_runtime.seed(source, interval, bucket_start_ms,
                                                       base_spec.floor_ms(now_ms)):
                # Match legacy warm-start's cache fallback when the bridge is
                # not yet started, or its preview was throttled. Preserve a
                # better canonical cached bar through ordinary arbitration.
                current = self._bar_aggregator.get_bucket_state(symbol, interval, bucket_start_ms,
                    exchange=exchange, market_type=market_type, series_identity=series_identity)
                if current is not None and current._source_recovery is not None:
                    # The live bridge already owns this accepted source view.
                    # A partial/empty canonical warm read cannot replace it.
                    self._keep_source_recovery(current, base_interval, base_seconds, now_ms,
                        focus_scope, subscription_tier)
                    return
                if current is not None:
                    key = SeriesKey.create(symbol, interval, exchange=exchange,
                                           market_type=market_type, identity=series_identity)
                    bar = BarData.from_bar_state(current)
                    if self._cache.get_latest(key, 1) != [bar]:
                        await self._cache.apply_protected(self._cache.upsert_if_accepted, key, bar)
                return
        current = self._bar_aggregator.get_bucket_state(symbol, interval, bucket_start_ms,
            exchange=exchange, market_type=market_type, series_identity=series_identity)
        if current is not None and current._source_recovery is not None:
            self._keep_source_recovery(current, base_interval, base_seconds, now_ms,
                focus_scope, subscription_tier)
            return
        prev_bucket_start_ms = self._bar_aggregator.previous_bucket(
            interval, bucket_start_ms, exchange=exchange, series_identity=series_identity,
        )
        fetch_start_ms = (
            prev_bucket_start_ms
            if prev_bucket_start_ms is not None
            else bucket_start_ms
        )
        if (self.history_prefix_runtime is not None and base_spec is not None
                and self.history_prefix_runtime.owns_target(source, interval)):
            # A subsequent small/new current bucket can use ordinary fine
            # components. Do not expand/replay its already-owned old prefix.
            fetch_start_ms = bucket_start_ms

        rows = storage.query_bars(
            symbol=symbol,
            interval=base_interval,
            start_ms=fetch_start_ms,
            end_ms=now_ms,
            order="ASC",
            exchange=exchange,
            market_type=market_type,
            series_identity=series_identity,
        )
        base_key = SeriesKey.create(
            symbol,
            base_interval,
            exchange=exchange,
            market_type=market_type,
            identity=series_identity,
        )
        rows_by_open_time = {int(row["open_time"]): dict(row) for row in rows}
        for open_time_ms, row in rows_by_open_time.items():
            row.setdefault(
                "close_time",
                (
                    base_spec.next_ms(open_time_ms) - 1
                    if base_spec is not None
                    else open_time_ms + (base_seconds * 1000) - 1
                ),
            )

        cached_rows = self._cache.query(
            base_key,
            start_time=fetch_start_ms // 1000,
            end_time=now_ms // 1000,
        )
        for cached in cached_rows:
            open_time_ms = cached.time * 1000
            if open_time_ms < fetch_start_ms:
                continue

            close_time_ms = (
                base_spec.next_ms(open_time_ms) - 1
                if base_spec is not None
                else open_time_ms + (base_seconds * 1000) - 1
            )
            stored = rows_by_open_time.get(open_time_ms)
            if stored is not None and _base_row_is_final(stored):
                # The committed row decides equal-rank conflicts: the cache
                # has no evidence that its older copy is still canonical.
                if not cached.trusted_final or source_rank(cached.source) <= source_rank(stored.get("source")):
                    continue
            rows_by_open_time[open_time_ms] = {
                "open_time": open_time_ms,
                "close_time": close_time_ms,
                "open": cached.open,
                "high": cached.high,
                "low": cached.low,
                "close": cached.close,
                "volume": cached.volume,
                "quote_volume": cached.quote_volume,
                "trades": cached.trades,
                "taker_buy_base": cached.taker_buy_base,
                "taker_buy_quote": cached.taker_buy_quote,
                "enhanced_fields": sorted(cached.enhanced_fields),
                "is_closed": bool(cached.is_closed),
                "source": cached.source,
            }

        if not is_monthly_interval(interval):
            elapsed_in_bucket_ms = now_ms - bucket_start_ms
            expected_closed_components = max(
                0,
                int(elapsed_in_bucket_ms / (base_seconds * 1000)),
            )
            actual_closed_components = sum(
                1
                for open_time, row in rows_by_open_time.items()
                if bucket_start_ms <= open_time < now_ms
                and int(row["close_time"]) < now_ms
                and _base_row_is_final(row)
            )
            if actual_closed_components < expected_closed_components:
                missing = expected_closed_components - actual_closed_components
                logger.warning(
                    "Custom seed %s@%s: expected %d final base bars in current bucket "
                    "but found %d (%d missing). Triggering base backfill.",
                    symbol,
                    interval,
                    expected_closed_components,
                    actual_closed_components,
                    missing,
                )
                try:
                    self._call_backfill_trigger(
                        symbol=symbol,
                        interval=base_interval,
                        start_ms=bucket_start_ms,
                        end_ms=now_ms,
                        exchange=exchange,
                        market_type=market_type,
                        reason=self._warmup_reason(focus_scope, subscription_tier),
                        requester="warm_start_custom_seed",
                        metadata={
                            "focus_scope": focus_scope,
                            "subscription_tier": subscription_tier,
                            "requested_interval": interval,
                            "base_interval": base_interval,
                            "had_stream": True,
                            "requires_trusted_finality": True,
                        },
                        series_identity=series_identity,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to trigger base backfill during custom seed: %s",
                        exc,
                    )
        else:
            logger.debug(
                "Custom seed %s@%s: skipping completeness check for monthly interval",
                symbol,
                interval,
            )

        if not rows_by_open_time:
            return

        rows = sorted(rows_by_open_time.values(), key=lambda row: int(row["open_time"]))
        current_state = self._bar_aggregator.get_bucket_state(
            symbol,
            interval,
            bucket_start_ms,
            exchange=exchange,
            market_type=market_type,
            series_identity=series_identity,
        )
        components: list[BarInput] = []
        for row in rows:
            open_time_ms = int(row["open_time"])
            close_time_ms = int(
                row.get("close_time", open_time_ms + (base_seconds * 1000) - 1)
            )
            is_closed = close_time_ms < now_ms and _base_row_is_final(row)
            explicit_fields = row.get("enhanced_fields")
            if isinstance(explicit_fields, (str, bytes, dict)):
                explicit_fields = ()
            components.append(BarInput(
                symbol=symbol,
                source_interval=base_interval,
                exchange=exchange,
                open_time_ms=open_time_ms,
                close_time_ms=close_time_ms,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0)),
                source=BarInputSource.BACKFILL if is_closed else BarInputSource.REALTIME,
                is_closed=is_closed,
                market_type=market_type,
                quote_volume=float(row.get("quote_volume", 0) or 0),
                trades=int(row.get("trades", 0) or 0),
                taker_buy_base=float(row.get("taker_buy_base", 0) or 0),
                taker_buy_quote=float(row.get("taker_buy_quote", 0) or 0),
                enhanced_fields=declared_enhanced_fields(
                    exchange,
                    market_type,
                    row,
                    explicit_fields=explicit_fields,
                ),
                sequence=open_time_ms if is_closed else None,
                extra={"warm_start_seed": True},
                series_identity=series_identity,
            ))

        if current_state is not None:
            components = current_state.with_accepted_forming_components(components, base_interval)
        if current_state is not None and current_state.matches_source_components(components):
            await self._cache.apply_protected(
                self._cache.upsert,
                SeriesKey.create(
                    symbol,
                    interval,
                    exchange=exchange,
                    market_type=market_type,
                    identity=series_identity,
                ),
                BarData.from_bar_state(current_state),
            )
            return

        rebuilt_state = await self._bar_aggregator.replay_components(
            symbol,
            interval,
            components,
            exchange,
            market_type,
            bucket_start_ms=bucket_start_ms,
            expire_existing=True,
            emit_events=False,
            series_identity=series_identity,
        )
        if rebuilt_state is not None:
            key = SeriesKey.create(
                symbol,
                interval,
                exchange=exchange,
                market_type=market_type,
                identity=series_identity,
            )
            rebuilt_bar = BarData.from_bar_state(rebuilt_state)
            # Component replay is an internal reconstruction, not N live bar
            # updates.  Publish one final snapshot; if no bridge is attached
            # (notably in focused tests), warm the cache directly as fallback.
            await self._bar_aggregator.publisher.emit_updated(rebuilt_state)
            cached = self._cache.get_latest(key, 1)
            if not cached or cached[-1] != rebuilt_bar:
                await self._cache.apply_protected(self._cache.upsert, key, rebuilt_bar)

    def _keep_source_recovery(self, state, base_interval, base_seconds, now_ms,
                              focus_scope, subscription_tier):
        """Keep accepted source data; missing confirmations still request repair."""
        receipt = state._source_recovery
        reader = self._bar_aggregator.source_recovery_reader
        owned = (reader is not None and receipt.binding is reader.binding
                 and receipt.version.source_width_ms == base_seconds * 1000)
        received = (receipt.version.closed_count + sum(
            row['is_closed'] and row['open_time_ms'] >= receipt.version.through_ms
            for row in state.source_snapshots.values())) if owned else 0
        expected = max(0, (now_ms-state.bucket_start_ms)//(base_seconds*1000))
        if received >= expected:
            return
        try:
            self._call_backfill_trigger(symbol=state.symbol, interval=base_interval,
                start_ms=state.bucket_start_ms, end_ms=now_ms, exchange=state.exchange,
                market_type=state.market_type,
                reason=self._warmup_reason(focus_scope, subscription_tier),
                requester='warm_start_custom_seed', metadata={
                    'focus_scope':focus_scope, 'subscription_tier':subscription_tier,
                    'requested_interval':state.interval, 'base_interval':base_interval,
                    'had_stream':True, 'requires_trusted_finality':True},
                series_identity=state.identity)
        except Exception as exc:
            logger.warning('Failed to request source fallback warm repair: %s', exc)

    async def _seed_standard_interval(
        self,
        symbol: str,
        interval: str,
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> None:
        """Seed the BarAggregator with the currently-forming standard bar."""
        symbol = symbol.upper()
        exchange = exchange.strip().lower()
        market_type = self._normalize_market_type(market_type)
        storage = self._storage_provider()
        if storage is None:
            return

        interval_seconds = parse_custom_interval(interval) or 60
        interval_ms = interval_seconds * 1000
        now_ms = int(time.time() * 1000)
        bucket_start_ms = self._bar_aggregator.compute_bucket(
            interval, now_ms, exchange=exchange, series_identity=series_identity,
        )
        if bucket_start_ms is None:
            return

        if self._bar_aggregator.get_bucket_state(
            symbol,
            interval,
            bucket_start_ms,
            exchange=exchange,
            market_type=market_type,
            series_identity=series_identity,
        ) is not None:
            return

        rows = storage.query_bars(
            symbol=symbol,
            interval=interval,
            start_ms=bucket_start_ms,
            end_ms=bucket_start_ms,
            limit=1,
            order="ASC",
            exchange=exchange,
            market_type=market_type,
            **({"series_identity": series_identity} if series_identity is not None else {}),
        )
        if not rows:
            return

        row = rows[0]
        open_time_ms = int(row["open_time"])
        if open_time_ms != bucket_start_ms:
            return

        close_time_ms = int(row.get("close_time", open_time_ms + interval_ms - 1))
        enhanced_fields = declared_enhanced_fields(
            exchange,
            market_type,
            row,
        )
        bar_input = BarInput(
            symbol=symbol,
            source_interval=interval,
            exchange=exchange,
            open_time_ms=open_time_ms,
            close_time_ms=close_time_ms,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            source=BarInputSource.MANUAL,
            is_closed=False,
            market_type=market_type,
            quote_volume=float(row.get("quote_volume", 0) or 0),
            trades=int(row.get("trades", 0) or 0),
            taker_buy_base=float(row.get("taker_buy_base", 0) or 0),
            taker_buy_quote=float(row.get("taker_buy_quote", 0) or 0),
            enhanced_fields=enhanced_fields,
            sequence=open_time_ms,
            series_identity=series_identity,
        )

        await self._bar_aggregator.seed_active_bar(
            symbol,
            interval,
            bar_input,
            exchange=exchange,
            market_type=market_type,
            emit_events=False,
        )
        logger.debug(
            "Seeded standard interval %s@%s: bucket=%d OHLCV=(%s,%s,%s,%s) V=%s",
            symbol,
            interval,
            bucket_start_ms,
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row.get("volume", 0),
        )

    def _trigger_custom_tail_repair(
        self,
        symbol: str,
        interval: str,
        exchange: str = "binance",
        market_type: str = "spot",
        focus_scope: str = "foreground",
        subscription_tier: str | None = None,
        route: IntervalRoute | None = None,
        series_identity: KlineSeriesIdentity | None = None,
    ) -> None:
        """Force a recent custom-interval rebuild to overwrite stale rows."""
        interval_seconds = parse_custom_interval(interval) or 60
        now_ms = int(time.time() * 1000)
        repair_bucket_ms = self._bar_aggregator.compute_bucket(
            interval, now_ms, exchange=exchange, series_identity=series_identity,
        )
        repair_key = SeriesKey.create(
            symbol, interval, exchange=exchange, market_type=market_type, identity=series_identity,
        )
        # A request belongs to one target lifetime. Closing its last consumer
        # may cancel queued work; reopening within the same bucket must get a
        # new demand. The aggregator already owns this generation token.
        target_token = self._bar_aggregator.history_target_token(repair_key, interval)
        repair_scope = (repair_bucket_ms, target_token[1] if target_token is not None else None)
        if (
            repair_bucket_ms is not None
            and self._tail_repair_buckets.get(repair_key) == repair_scope
        ):
            return

        month_count = parse_monthly_count(interval)
        if month_count is not None:
            repair_window_ms = month_count * 2 * 31 * 86_400 * 1000
        elif interval_seconds < 60:
            # This automatic seed repairs the recent tail, not the viewport.
            # The old six-hour floor silently queued21,600source seconds for
            # a new7s chart and delayed other foreground repairs. Explicit
            # history/range requests still own their complete requested span.
            repair_window_ms = interval_seconds * 16 * 1000
        else:
            repair_window_ms = min(
                max(interval_seconds * 16 * 1000, 6 * 60 * 60 * 1000),
                7 * 24 * 60 * 60 * 1000,
            )
        start_ms = max(0, now_ms - repair_window_ms)

        try:
            submitted = self._call_backfill_trigger(
                symbol=symbol.upper(),
                interval=interval,
                start_ms=start_ms,
                end_ms=now_ms,
                exchange=exchange,
                market_type=self._normalize_market_type(market_type),
                reason=self._warmup_reason(focus_scope, subscription_tier),
                requester="warm_start_custom_tail",
                metadata={
                    "focus_scope": focus_scope,
                    "subscription_tier": subscription_tier,
                    "requested_interval": interval,
                    "base_interval": (
                        route.base_interval if route is not None else self._base_interval
                    ),
                    "had_stream": False,
                },
                series_identity=series_identity,
            )
            if submitted and repair_bucket_ms is not None:
                self._tail_repair_buckets[repair_key] = repair_scope
                if len(self._tail_repair_buckets) > 2_048:
                    self._tail_repair_buckets.pop(
                        next(iter(self._tail_repair_buckets)),
                        None,
                    )
        except Exception as exc:
            logger.warning(
                "Failed to trigger custom tail repair for %s@%s: %s",
                symbol,
                interval,
                exc,
                exc_info=True,
            )

    def _call_backfill_trigger(
        self,
        *,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        exchange: str,
        market_type: str,
        reason: str,
        requester: str,
        metadata: dict[str, Any] | None = None,
        series_identity: KlineSeriesIdentity | None = None,
    ) -> bool:
        trigger = self._backfill_trigger_provider()
        if trigger is None:
            return False
        raw_kwargs = {
            "reason": reason,
            "priority": priority_for_reason(reason),
            "requester": requester,
            "metadata": {
                key: value
                for key, value in (metadata or {}).items()
                if value is not None
            },
        }
        if series_identity is not None:
            raw_kwargs["metadata"][SERIES_IDENTITY_METADATA_KEY] = series_identity.to_dict()
        kwargs: dict[str, Any] = {
            key: value
            for key, value in raw_kwargs.items()
            if value is not None
        }
        try:
            signature = inspect.signature(trigger)
            supports_kwargs = any(
                param.kind is inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
            if not supports_kwargs:
                kwargs = {
                    key: value
                    for key, value in kwargs.items()
                    if key in signature.parameters
                }
        except (TypeError, ValueError):
            pass

        trigger(symbol, interval, start_ms, end_ms, exchange, market_type, **kwargs)
        return True

    @staticmethod
    def _warmup_reason(focus_scope: str, subscription_tier: str | None) -> str:
        if str(subscription_tier or "").lower() == "full":
            return "full_subscription_warmup"
        if str(focus_scope or "").lower() == "subscription":
            return "full_subscription_warmup"
        return "visible_seed_gap"

    @staticmethod
    def _normalize_market_type(market_type: str) -> str:
        return (market_type or "spot").strip().lower()
