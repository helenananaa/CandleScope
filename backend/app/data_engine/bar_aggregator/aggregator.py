"""
Bar Aggregator — top-level orchestrator that wires L1–L5 together.

This is the main entry point for the Bar Aggregator module.  It creates
and connects all sub-components (Router, TimeBucket, BarState, Finalizer,
Publisher) and provides a high-level API.

Usage::

    from bar_aggregator import BarAggregator, BarAggregatorConfig

    config = BarAggregatorConfig()
    agg = BarAggregator(config)

    # Register symbols and intervals
    agg.add_target("BTCUSDT", "1m")
    agg.add_target("BTCUSDT", "91m")

    # Hook up consumers
    agg.publisher.on_bar_closed(save_to_db)

    # Feed from ingestion
    await agg.on_market_event(market_event)

    # Feed from backfill
    await agg.on_backfill_bars("BTCUSDT", "1m", bars)

Architecture::

    MarketEvent / FetchedBar
            │
            ▼
    ┌─ L1: EventRouter ─────────────────────────┐
    │   normalize → BarInput                     │
    │   dispatch by (symbol, target_interval)    │
    └───────────────┬────────────────────────────┘
                    │  BarInput
                    ▼
    ┌─ L2: TimeBucketEngine ─────────────────────┐
    │   compute_bucket(open_time_ms) → bucket_ms │
    └───────────────┬────────────────────────────┘
                    │  bucket_start_ms
                    ▼
    ┌─ L3: BarStateEngine ───────────────────────┐
    │   apply(symbol, bucket, input) → BarState  │
    │   + merge strategy (OHLCV / custom)        │
    └───────────────┬────────────────────────────┘
                    │  BarState + BarStateChange
                    ▼
    ┌─ L4: Finalizer ───────────────────────────┐
    │   check(state, trigger) → close?           │
    │   strategy chain evaluation                │
    └───────────────┬────────────────────────────┘
                    │  BarEvent (if closed)
                    ▼
    ┌─ L5: Publisher ───────────────────────────┐
    │   emit(CREATED/UPDATED/CLOSED/...)        │
    │   → callbacks + async iterators           │
    └───────────────────────────────────────────┘
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import asynccontextmanager
from contextvars import ContextVar

import json
from app.data_engine.series_identity import (
    KlineSeriesIdentity,
    resolve_kline_series_identity,
)

import asyncio
import logging
import sys
import time
from dataclasses import replace
from typing import Any, Awaitable, Callable

from app.data_engine.interval_policy import parse_interval_spec, intervals_equivalent
from app.data_engine.interval_resolution import IntervalResolver, IntervalPurpose, IntervalRouteKind, IntervalResolutionError

from .config import BarAggregatorConfig
from .models import (
    BarStatus,
    AlignmentMode,
    BarInput,
    BarInputSource,
    BarFinality,
    BarState,
    BarStateChange,
    BarEvent,
    BarEventType,
    FinalizeTrigger,
    MergeMode,
    parse_interval_ms,
)
from .router import EventRouter
from .time_bucket import TimeBucketEngine, MonthlyBucketCalculator, WeeklyBucketCalculator, ScheduleBucketCalculator
from .bar_state import BarStateEngine
from .component_inputs import SourceComponentPreparation, SourcePreparationCapacity, PREPARATION_BYTES, SCOPE_BYTES, MAX_PREPARATION_TARGETS
from .finalizer import Finalizer
from .publisher import BarAggregatorPublisher
from .component_memory import ComponentSnapshots
from .preview_scheduler import ComponentPreviewScheduler
from app.data_engine.memory_budget import retained_size

logger = logging.getLogger("bar_aggregator")


class IntervalPipeline:
    """Internal: a per-interval aggregation pipeline (L2 + L3 + L4).

    Each registered interval gets its own pipeline with dedicated
    TimeBucketEngine, BarStateEngine, and Finalizer instances.
    """

    def __init__(
        self,
        interval: str,
        interval_ms: int,
        config: BarAggregatorConfig,
    ) -> None:
        self.interval = interval
        self.interval_ms = interval_ms

        alignment = AlignmentMode(config.default_alignment_mode)
        spec = parse_interval_spec(interval)
        epoch_ms = config.alignment_epoch_ms
        if spec is not None:
            # A persisted series key must imply the same grid in history and
            # realtime, including the zero-phase alias. Process-wide legacy
            # alignment settings must not silently change that identity.
            alignment = AlignmentMode.CUSTOM if spec.phase_ms else AlignmentMode.EPOCH
            epoch_ms = spec.phase_ms

        # Monthly intervals need calendar-based bucketing, not fixed 30-day.
        # This applies to ALL month-unit intervals (1M, 2M, 3M, etc.),
        # not just the standard "1M".
        custom_calc = None
        if spec is not None and spec.timezone:
            custom_calc = ScheduleBucketCalculator(spec)
        elif interval.endswith("M") and interval[:-1].isdigit():
            month_count = int(interval[:-1])
            if month_count > 0:
                custom_calc = MonthlyBucketCalculator(months=month_count)
        # Weekly intervals need Monday-aligned bucketing.
        # Without this, floor-dividing from Unix epoch (a Thursday)
        # would produce buckets starting on Thursday instead of Monday.
        elif interval.endswith("w") and interval[:-1].isdigit():
            week_count = int(interval[:-1])
            if week_count > 0:
                custom_calc = WeeklyBucketCalculator(weeks=week_count)

        self.time_bucket = TimeBucketEngine(
            interval_ms=interval_ms,
            alignment=alignment,
            epoch_ms=epoch_ms,
            custom_calculator=custom_calc,
        )
        self.bar_state = BarStateEngine(config, self.time_bucket, interval)
        self.finalizer = Finalizer(config, self.time_bucket, interval)
        # Raw buffer items claimed by suspended drains; references only.
        self.eviction_claims: dict[object, BarState] = {}

    def snapshot(self) -> dict:
        return {
            "interval": self.interval,
            "interval_ms": self.interval_ms,
            "time_bucket": self.time_bucket.snapshot(),
            "bar_state": self.bar_state.snapshot(),
            "finalizer": self.finalizer.snapshot(),
        }


class BarAggregator:
    """Top-level Bar Aggregator — wires L1 through L5 together.

    This is the **only class** external code needs to interact with.
    It exposes:
      - ``add_target()`` / ``remove_target()`` to manage (symbol, interval) pairs
      - ``on_market_event()`` to feed realtime data from ingestion
      - ``on_backfill_bars()`` to feed historical data from backfill
      - ``publisher`` property for subscribing to bar lifecycle events
      - Per-layer access for advanced customization
    """

    def __init__(
        self,
        config: BarAggregatorConfig | None = None,
        interval_resolver: IntervalResolver | None = None,
    ) -> None:
        self._cfg = config or BarAggregatorConfig()
        self._source_component_reader: Callable[[str, int, int], Awaitable[list[dict]]] | None = None
        self.source_recovery_reader = None

        # L1: Event Router
        self._router = EventRouter(self._cfg, interval_resolver=interval_resolver)
        self._router.set_on_bar_input(self._handle_bar_input)

        # L5: Publisher (shared across all intervals)
        self._publisher = BarAggregatorPublisher(self._cfg)

        # Per-interval pipelines: {interval → IntervalPipeline}
        self._pipelines: dict[str, IntervalPipeline] = {}

        # Track which (exchange, market_type, symbol) are active per interval
        # (redundant with router targets, but useful for fast lookup)
        self._symbol_intervals: dict[
            tuple[str, str, str, KlineSeriesIdentity], set[str]
        ] = {}
        # Tokens exist only for registered targets. Removal/re-addition changes
        # identity even when the interval pipeline itself remains resident.
        self._target_epochs: dict[tuple, object] = {}
        self.history_prefix_runtime = None
        self.memory_budget = None
        self._source_preparation = ContextVar("bar_aggregator_source_preparation", default=None)
        self._active_preparations = set()
        self._preparation_capacity = SourcePreparationCapacity()
        self._preparation_targets_revision = 0
        self._source_preparation_metrics = dict(preparation_scopes=0, preparation_builds=0,
            preparation_hits=0, preparation_declines=0, preparation_budget_deferred=0)

        # Timeout checker task
        self._timeout_task: asyncio.Task | None = None
        self._previews = ComponentPreviewScheduler(self)
        self._publisher._preview_wakeup = self._previews.publication_finished
        self._preview_source_validator = self._preview_source_binding = None

    # ── Public: Lifecycle ────────────────────────────────────

    async def start(self) -> None:
        """Start background tasks (e.g. timeout checker)."""
        self._previews.start()
        if self._timeout_task is None:
            self._timeout_task = asyncio.create_task(
                self._timeout_loop(), name="bar_agg_timeout",
            )
            logger.info("BarAggregator started")

    async def stop(self) -> None:
        """Stop background tasks and flush all active bars."""
        if self._timeout_task is not None:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
            self._timeout_task = None

        await self._previews.stop()

        # Flush all active bars
        await self._flush_all()
        self._target_epochs.clear()
        self._preparation_capacity.close()
        await self._publisher.close_all_subscribers()
        logger.info("BarAggregator stopped")

    # ── Public: Target Management ────────────────────────────

    @staticmethod
    def _pipeline_key(
        interval: str, exchange: str, series_identity: KlineSeriesIdentity | None
    ) -> str:
        identity = resolve_kline_series_identity(exchange, series_identity)
        if identity.is_legacy_default_for(exchange):
            return interval
        return json.dumps([interval, *identity.storage_values], separators=(",", ":"))

    def add_target(
        self,
        symbol: str,
        interval: str,
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> None:
        """Register a (symbol, interval) aggregation target.

        Creates the per-interval pipeline if it doesn't exist yet.

        Args:
            symbol:   Trading pair (e.g. "BTCUSDT")
            interval: Target interval (e.g. "1m", "5m", "91m")

        Raises:
            ValueError: If the interval string cannot be parsed
        """
        symbol = symbol.upper()
        exchange = exchange.lower().strip()
        market_type = market_type.lower().strip()
        spec = parse_interval_spec(interval)
        if spec is not None:
            interval = spec.canonical
        interval_ms = parse_interval_ms(interval)
        if interval_ms is None:
            raise ValueError(f"Cannot parse interval: {interval!r}")

        # Create pipeline if needed
        pipeline_key = self._pipeline_key(interval, exchange, series_identity)
        if pipeline_key not in self._pipelines:
            self._pipelines[pipeline_key] = IntervalPipeline(
                interval,
                interval_ms,
                self._cfg,
            )
            self._pipelines[pipeline_key].bar_state._component_merge_strategy.prepare_input = self._prepare_component_input
            logger.info(
                "Created pipeline for interval %s (%d ms)", interval, interval_ms,
            )

        self._preparation_capacity.closing = False
        self._preparation_targets_revision += 1
        # Register with router
        self._router.register_target(
            symbol,
            interval,
            exchange=exchange,
            market_type=market_type,
            series_identity=series_identity,
        )

        # Track
        self._symbol_intervals.setdefault(
            (
                exchange,
                market_type,
                symbol,
                resolve_kline_series_identity(exchange, series_identity),
            ),
            set(),
        ).add(interval)
        self._target_epochs.setdefault((exchange, market_type, symbol, interval,
                                        resolve_kline_series_identity(exchange, series_identity)), object())

    def remove_target(
        self,
        symbol: str,
        interval: str,
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> None:
        """Unregister a (symbol, interval) target.

        Does NOT destroy the pipeline — other symbols may use it.  Any
        forming state for this exact target is discarded so a detached
        stream cannot later be promoted to CLOSED by timeout or shutdown.
        Closed correction builders are released too; canonical history and
        pending delivery snapshots keep their existing independent owners.
        """
        symbol = symbol.upper()
        exchange = exchange.lower().strip()
        market_type = market_type.lower().strip()
        spec = parse_interval_spec(interval)
        if spec is not None:
            interval = spec.canonical
        self._preparation_targets_revision += 1
        self._target_epochs.pop((exchange, market_type, symbol, interval,
                                 resolve_kline_series_identity(exchange, series_identity)), None)
        self._previews.detach((exchange, market_type, symbol, interval,
                               resolve_kline_series_identity(exchange, series_identity)))
        if len(self._target_epochs) < 2:
            self._preparation_capacity.trim_idle()
        if self.history_prefix_runtime is not None:
            self.history_prefix_runtime.detach((exchange, market_type, symbol, interval,
                resolve_kline_series_identity(exchange, series_identity)))
        self._router.unregister_target(
            symbol,
            interval,
            exchange=exchange,
            market_type=market_type,
            series_identity=series_identity,
        )
        pipeline = self._pipelines.get(
            self._pipeline_key(interval, exchange, series_identity)
        )
        expired = 0
        if pipeline is not None:
            for state in pipeline.bar_state.get_all_active(exchange, market_type, symbol):
                state.close_reason = "target_removed"
                if pipeline.bar_state.expire_bar(
                    exchange,
                    market_type,
                    symbol,
                    state.bucket_start_ms,
                ) is not None:
                    expired += 1
            pipeline.bar_state.clear(symbol, exchange, market_type)
        key = (
            exchange,
            market_type,
            symbol,
            resolve_kline_series_identity(exchange, series_identity),
        )
        if key in self._symbol_intervals:
            self._symbol_intervals[key].discard(interval)
            if not self._symbol_intervals[key]:
                self._symbol_intervals.pop(key, None)
        if expired:
            logger.info(
                "Expired %d forming bars while removing target %s:%s:%s@%s",
                expired,
                exchange,
                market_type,
                symbol,
                interval,
            )

    def get_targets(self) -> list[tuple[str, str, str, str]]:
        """Return all registered (symbol, interval) targets."""
        return self._router.get_targets()

    def history_target_token(self, source, interval):
        """Capture before asynchronous preparation; no token for detached targets."""
        spec = parse_interval_spec(interval)
        canonical = spec.canonical if spec is not None else interval
        key = (source.exchange, source.market_type, source.symbol, canonical, source.identity)
        epoch = self._target_epochs.get(key)
        return (key, epoch) if epoch is not None else None

    def adopt_history_prefix(self, prefix, token, *, acquisition_revision=None, refresh=False,
                             replace_provisional=False, compact_closed=False):
        """Loop-owned, synchronous last step after the durable read fence.

        No await separates the target-generation check and builder adoption.
        The caller publishes the returned detached snapshot through the normal
        publisher and remains responsible for source revisions during live use.
        """
        if token is None:
            raise ValueError('history initialization target is detached')
        key, epoch = token
        if self._target_epochs.get(key) is not epoch:
            raise ValueError('history initialization target generation expired')
        exchange, market_type, symbol, interval, identity = key
        source = prefix.summary.target
        if (source.exchange, source.market_type, source.symbol, source.identity) != (
                exchange, market_type, symbol, identity):
            raise ValueError('history initialization source differs from target')
        pipeline = self._pipelines[self._pipeline_key(interval, exchange, identity)]
        previous = pipeline.bar_state.get_state(exchange, market_type, symbol, prefix.start_ms)
        overlay_floor = previous.acquisition_revision if previous is not None else None
        delete_floor = ((previous.canonical_recovery_delete_floor
                         if previous.canonical_recovery_delete_floor is not None else overlay_floor)
                        if previous is not None else None)
        state = pipeline.bar_state.adopt_history_prefix(
            prefix, refresh=refresh, replace_provisional=replace_provisional,
            compact_closed=compact_closed,
        )
        state.acquisition_revision = (prefix.acquisition_revision if acquisition_revision is None
                                      else min(acquisition_revision, prefix.acquisition_revision))
        if state.source_snapshots:
            # A fresh historical prefix cannot relabel a retained live tail
            # acquired before a deletion. Preserve the oldest acquisition.
            state.acquisition_revision = min(state.acquisition_revision, overlay_floor or 0)
        if delete_floor is not None:
            # Canonical content can acquire a newer revision when the last raw
            # leaves retire or a warm prefix is adopted again. That never grants
            # permission to recreate a target/source deleted during its lifetime.
            state.canonical_recovery_delete_floor = delete_floor
        return deepcopy(state)

    def get_series_targets(self):
        return self._router.get_series_targets()

    def has_series_target(self, symbol, interval, exchange, market_type, identity) -> bool:
        return self._router.has_series_target(symbol, interval, exchange, market_type, identity)

    # ── Public: Data Ingestion ───────────────────────────────

    def _uses_builtin_dispatch(self):
        callback = self._router._on_bar_input
        return (getattr(callback,"__self__",None) is self
                and getattr(callback,"__func__",None) is BarAggregator._handle_bar_input)

    @asynccontextmanager
    async def _component_input_scope(self, *, enabled=True):
        if not enabled or not self._cfg.shared_component_inputs or len(self._target_epochs) < 2 or not self._uses_builtin_dispatch():
            if not self._cfg.shared_component_inputs or len(self._target_epochs) < 2 or not self._uses_builtin_dispatch():
                self._preparation_capacity.trim_idle()
            yield
            return
        preparation = SourceComponentPreparation(self._source_preparation_metrics, self.memory_budget, self._preparation_capacity)
        token = self._source_preparation.set((asyncio.current_task(), preparation))
        self._active_preparations.add(preparation)
        self._source_preparation_metrics['preparation_scopes'] += 1
        try:
            yield
        finally:
            self._source_preparation.reset(token)
            self._active_preparations.discard(preparation)
            preparation.close(keep_capacity=self._cfg.shared_component_inputs and len(self._target_epochs) >= 2 and self._uses_builtin_dispatch())

    def _prepare_component_input(self, value):
        scope = self._source_preparation.get()
        if scope is None or not self._cfg.shared_component_inputs or not self._uses_builtin_dispatch():
            return None
        try:
            if scope[0] is not asyncio.current_task():
                return None  # Child tasks never borrow an inherited source dispatch.
        except RuntimeError:
            return None
        purpose = IntervalPurpose.HISTORY if value.source == BarInputSource.BACKFILL else IntervalPurpose.REALTIME
        key = (value.exchange,value.market_type,value.symbol,value.source_interval,value.series_identity,purpose,self._preparation_targets_revision)
        def inspect_targets():
            identity = value.identity
            intervals = self._symbol_intervals.get((value.exchange,value.market_type,value.symbol,identity), ())
            if len(intervals) > MAX_PREPARATION_TARGETS:
                self._source_preparation_metrics['preparation_declines'] += 1
                return False, ()
            count = 0
            for interval in intervals:
                try:
                    route = self._router._route_for(value.exchange,value.market_type,interval,purpose)
                except IntervalResolutionError:
                    continue
                if (route.kind is IntervalRouteKind.DERIVED and route.base_interval is not None
                        and intervals_equivalent(route.base_interval,value.source_interval)):
                    count += 1
                    if count >= 2:
                        break
            engines = (tuple(self._pipelines[self._pipeline_key(interval,value.exchange,identity)].bar_state
                             for interval in intervals) if count >= 2 else ())
            return count >= 2, engines
        if not scope[1].qualifies(key,inspect_targets):
            self._preparation_capacity.trim_idle()
            return None
        if any(engine._merge_strategy_overridden for engine in scope[1].engines):
            # Saved owner handles are refreshed on target generation changes;
            # extension flags remain live across awaits within one dispatch.
            scope[1].invalidate()
            scope[1].eligible = False
            scope[1].engines = ()
            self._source_preparation_metrics['preparation_declines'] += 1
            self._preparation_capacity.trim_idle()
            return None
        return scope[1].get(value)

    async def on_market_event(self, event: Any) -> None:
        """Normalize and dispatch one source frame to independently admitted targets."""
        await self._publisher.retry_source_deliveries()
        kind = getattr(event, 'event_type', None)
        async with self._component_input_scope(enabled=getattr(kind,'value',kind) == 'kline'):
            runtime = self.history_prefix_runtime
            if runtime is None:
                await self._router.on_market_event(event)
            else:
                async with runtime.forming_input_scope(event):
                    await self._router.on_market_event(event)

    async def on_backfill_bars(
        self,
        symbol: str,
        interval: str,
        bars: list[Any],
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> None:
        """Feed historical bars from the backfill engine.

        Each bar is converted to BarInput and processed through the
        full pipeline.
        """
        async with self._component_input_scope(enabled=interval != "tick"):
            await self._router.on_backfill_bars(
                symbol, interval, bars, exchange=exchange, market_type=market_type,
                series_identity=series_identity,
            )

    async def on_custom_data(self, adapter_name: str, raw_data: Any) -> None:
        """Feed data through a registered custom adapter."""
        await self._router.on_custom_data(adapter_name, raw_data)

    async def ingest_bar_input(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        bar_input: BarInput,
        *,
        emit_events: bool = True,
    ) -> None:
        """Public wrapper for feeding an already-normalized BarInput."""
        token = self._source_preparation.set(None)
        try:
            await self._handle_bar_input(
                exchange.lower().strip(), market_type.lower().strip(), symbol.upper().strip(),
                interval, bar_input, emit_events=emit_events,
            )
        finally:
            self._source_preparation.reset(token)

    def compute_bucket(
        self,
        interval: str,
        open_time_ms: int,
        *,
        exchange: str = "binance",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> int | None:
        """Return the bucket start for an interval using its pipeline policy."""
        pipeline = self._pipelines.get(
            self._pipeline_key(interval, exchange, series_identity)
        )
        if pipeline is None:
            return None
        return pipeline.time_bucket.compute_bucket(open_time_ms)

    def previous_bucket(
        self,
        interval: str,
        bucket_start_ms: int,
        *,
        exchange: str = "binance",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> int | None:
        """Return the previous bucket start for an interval."""
        pipeline = self._pipelines.get(
            self._pipeline_key(interval, exchange, series_identity)
        )
        if pipeline is None:
            return None
        return pipeline.time_bucket.prev_bucket(bucket_start_ms)

    def get_bucket_state(
        self,
        symbol: str,
        interval: str,
        bucket_start_ms: int,
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> BarState | None:
        """Return active state for a specific bucket."""
        pipeline = self._pipelines.get(
            self._pipeline_key(interval, exchange, series_identity)
        )
        if pipeline is None:
            return None
        return deepcopy(pipeline.bar_state.get_active(
            exchange.lower().strip(),
            market_type.lower().strip(),
            symbol.upper().strip(),
            bucket_start_ms,
        ))


    def expire_bucket(
        self,
        symbol: str,
        interval: str,
        bucket_start_ms: int,
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> BarState | None:
        """Expire an active bucket without exposing BarStateEngine internals."""
        pipeline = self._pipelines.get(
            self._pipeline_key(interval, exchange, series_identity)
        )
        if pipeline is None:
            return None
        state = pipeline.bar_state.expire_bar(
            exchange.lower().strip(),
            market_type.lower().strip(),
            symbol.upper().strip(),
            bucket_start_ms,
        )
        if state is not None:
            self._previews.discard(state)
        return state

    async def seed_active_bar(
        self,
        symbol: str,
        interval: str,
        bar_input: BarInput,
        exchange: str = "binance",
        market_type: str = "spot",
        *,
        emit_events: bool = False,
    ) -> BarState | None:
        """Seed a forming standard bucket from a trusted snapshot."""
        await self.ingest_bar_input(
            exchange,
            market_type,
            symbol,
            interval,
            bar_input,
            emit_events=emit_events,
        )
        bucket_start_ms = self.compute_bucket(
            interval,
            bar_input.open_time_ms,
            exchange=exchange,
            series_identity=bar_input.identity,
        )
        if bucket_start_ms is None:
            return None
        return self.get_bucket_state(
            symbol,
            interval,
            bucket_start_ms,
            exchange=exchange,
            market_type=market_type,
            series_identity=bar_input.identity,
        )

    async def replay_components(
        self,
        symbol: str,
        interval: str,
        components: list[BarInput],
        exchange: str = "binance",
        market_type: str = "spot",
        *,
        bucket_start_ms: int | None = None,
        expire_existing: bool = True,
        emit_events: bool = False,
        series_identity: KlineSeriesIdentity | None = None,
    ) -> BarState | None:
        """Replay base components into a target bucket and return its state."""
        identity = resolve_kline_series_identity(exchange, series_identity)
        if any(component.identity != identity for component in components):
            raise ValueError("Component series identity does not match the target")
        if bucket_start_ms is not None and expire_existing:
            self.expire_bucket(
                symbol,
                interval,
                bucket_start_ms,
                exchange=exchange,
                market_type=market_type,
                series_identity=series_identity,
            )

        for component in components:
            if component.merge_mode != MergeMode.COMPONENT:
                component = replace(component, merge_mode=MergeMode.COMPONENT)
            await self.ingest_bar_input(
                exchange,
                market_type,
                symbol,
                interval,
                component,
                emit_events=emit_events,
            )

        if bucket_start_ms is None and components:
            bucket_start_ms = self.compute_bucket(
                interval,
                components[-1].open_time_ms,
                exchange=exchange,
                series_identity=series_identity,
            )
        if bucket_start_ms is None:
            return None
        return self.get_bucket_state(
            symbol,
            interval,
            bucket_start_ms,
            exchange=exchange,
            market_type=market_type,
            series_identity=series_identity,
        )

    async def aggregate_batch(
        self,
        symbol: str,
        target_interval: str,
        source_interval: str | None,
        bars: list[Any],
        exchange: str = "binance",
        market_type: str = "spot",
        *,
        require_authoritative: bool = False,
        series_identity: KlineSeriesIdentity | None = None,
    ) -> list[BarState]:
        """Aggregate a batch in an isolated aggregator instance.

        Persistence callers must set ``require_authoritative`` so a partial
        historical component set cannot become durable merely because the
        time-based fallback closed it. Diagnostic callers retain incomplete
        active states, explicitly marked provisional, so capability masks and
        gap evidence remain inspectable without becoming publishable data.
        """
        temp = BarAggregator(self._cfg)
        temp.add_target(
            symbol,
            target_interval,
            exchange=exchange,
            market_type=market_type,
            series_identity=series_identity,
        )
        rows_by_open_time: dict[int, BarState] = {}

        async def _capture(event: BarEvent) -> None:
            if (
                require_authoritative
                and event.bar.finality != BarFinality.AUTHORITATIVE
            ):
                return
            rows_by_open_time[event.bar.bucket_start_ms] = event.bar

        temp.publisher.on_bar_closed(_capture)
        temp.publisher.on_bar_amended(_capture)
        if source_interval is not None:
            components = [
                temp.router._convert_fetched_bar(
                    bar,
                    symbol,
                    source_interval,
                    exchange=exchange,
                    market_type=market_type,
                    series_identity=series_identity,
                )
                for bar in bars
            ]
            await temp.replay_components(
                symbol,
                target_interval,
                [component for component in components if component is not None],
                exchange=exchange,
                market_type=market_type,
                series_identity=series_identity,
                expire_existing=False,
                emit_events=True,
            )
        else:
            for bar in bars:
                interval = (
                    bar.get("interval")
                    if isinstance(bar, dict)
                    else getattr(bar, "interval", None)
                )
                if interval is None:
                    raise ValueError("source_interval is required when bars do not carry interval")
                await temp.on_backfill_bars(
                    symbol,
                    interval,
                    [bar],
                    exchange=exchange,
                    market_type=market_type,
                    series_identity=series_identity,
                )
        if not require_authoritative:
            for state in temp.get_active_bars(
                symbol,
                target_interval,
                exchange=exchange,
                market_type=market_type,
                series_identity=series_identity,
            ):
                rows_by_open_time.setdefault(state.bucket_start_ms, state)
        return [rows_by_open_time[key] for key in sorted(rows_by_open_time)]

    # ── Public: Layer Access (advanced customization) ────────

    @property
    def config(self) -> BarAggregatorConfig:
        """Access the aggregator configuration."""
        return self._cfg

    @property
    def router(self) -> EventRouter:
        """Access L1: EventRouter (for adapter registration, etc.)."""
        return self._router

    @property
    def publisher(self) -> BarAggregatorPublisher:
        """Access L5: Publisher (for subscribing to bar events)."""
        return self._publisher

    def get_pipeline(
        self,
        interval: str,
        *,
        exchange: str = "binance",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> IntervalPipeline | None:
        """Access a per-interval pipeline for advanced customization.

        Returns None if no pipeline exists for this interval.

        Example — swap merge strategy for 91m bars::

            pipeline = agg.get_pipeline("91m")
            if pipeline:
                pipeline.bar_state.set_merge_strategy(MyCustomMerge())
        """
        return self._pipelines.get(
            self._pipeline_key(interval, exchange, series_identity)
        )

    def get_time_bucket(self, interval: str) -> TimeBucketEngine | None:
        """Access L2: TimeBucketEngine for a specific interval."""
        p = self._pipelines.get(interval)
        return p.time_bucket if p else None

    def get_bar_state(self, interval: str) -> BarStateEngine | None:
        """Access L3: BarStateEngine for a specific interval."""
        p = self._pipelines.get(interval)
        return p.bar_state if p else None

    def get_finalizer(self, interval: str) -> Finalizer | None:
        """Access L4: Finalizer for a specific interval."""
        p = self._pipelines.get(interval)
        return p.finalizer if p else None

    # ── Public: State Queries ────────────────────────────────

    def get_latest_bar(
        self,
        symbol: str,
        interval: str,
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> BarState | None:
        """Get the most recent bar for a (symbol, interval) pair."""
        p = self.get_pipeline(
            interval, exchange=exchange, series_identity=series_identity
        )
        if p is None:
            return None
        return deepcopy(p.bar_state.get_latest_bar(exchange, market_type, symbol))

    def get_active_bars(
        self,
        symbol: str,
        interval: str,
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> list[BarState]:
        """Get all active (FORMING) bars for a (symbol, interval) pair."""
        p = self.get_pipeline(
            interval, exchange=exchange, series_identity=series_identity
        )
        if p is None:
            return []
        return deepcopy(p.bar_state.get_all_active(exchange, market_type, symbol))

    def get_recent_bars(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
        exchange: str = "binance",
        market_type: str = "spot",
        series_identity: KlineSeriesIdentity | None = None,
    ) -> list[BarState]:
        """Get recently closed bars for a (symbol, interval) pair."""
        p = self.get_pipeline(
            interval, exchange=exchange, series_identity=series_identity
        )
        if p is None:
            return []
        return deepcopy(p.bar_state.get_recent_closed(exchange, market_type, symbol, limit))

    # ── Public: Snapshot ─────────────────────────────────────

    def memory_usage(self):
        active = closed = 0
        resident = []
        buffered = []
        for pipeline in list(self._pipelines.values()):
            engine = pipeline.bar_state
            active += len(engine._active)
            closed += len(engine._closed)
            resident.extend([*engine._active.values(), *engine._closed.values()])
            buffered.extend([*engine.evicted_closed, *engine.evicted_expired,
                             *pipeline.eviction_claims.values()])
        events = [event for queue, _ in list(self._publisher._subscribers)
                  for event in list(queue._queue) if isinstance(event, BarEvent)]
        publications, inputs, publisher_counts = self._publisher._retained_payloads()
        preview_states = [entry.state for entry in
                          (*self._previews.pending.values(),*self._previews.inflight)]
        mutable_callback_states = self._publisher._mutable_callback_state_ids()
        retained_events = {id(event): event for event in [*events, *publications]}
        payload_states = {id(state): state for state in [
            *buffered, *inputs, *preview_states,
            *(state for event in retained_events.values()
              for state in (event.bar, event.previous_bar) if state is not None),
        ]}
        # Deduplicate state containers which are both resident and in a handoff.
        # Immutable component values may still be conservatively counted once
        # per state index; optional retained-heap traversal deduplicates values.
        retained = {id(state): state for state in [*resident, *payload_states.values()]}
        index_bytes = {key: state._component_accumulator.snapshot()["estimated_bytes"]
                       if state._component_accumulator is not None else 0
                       for key, state in retained.items()}
        component_index_bytes = sum(index_bytes[id(state)] for state in resident)
        components = sum(len(state.source_snapshots) for state in resident)
        history_prefixes = sum(state._history_prefix is not None for state in resident)
        queued_components = sum(len(state.source_snapshots) for event in events
                                for state in (event.bar, event.previous_bar) if state is not None)
        component_payload_bytes = source_ref_bytes = 0
        for state in retained.values():
            snapshots = state.source_snapshots
            if isinstance(snapshots, ComponentSnapshots):
                component_payload_bytes += snapshots.estimated_bytes
                if id(state) in mutable_callback_states:
                    # Consumers may grow a nested proof without adding index
                    # keys. Accepted component hints cannot cover that mutable
                    # callback graph; measure it while this owner holds it.
                    source_ref_bytes += retained_size([state.source_refs])[0]
                elif snapshots and not snapshots.foreign_entries and len(state.source_refs) <= len(snapshots):
                    # Accepted proof weights cover the ordinary cloned source
                    # dictionaries conservatively; they may overcount leaves
                    # shared with immutable components. Callback-exposed copies
                    # use the live path above instead of this accepted hint.
                    source_ref_bytes += sys.getsizeof(state.source_refs)
                    if state.source_refs:
                        source_ref_bytes += snapshots.source_proof_bytes
                else:
                    source_ref_bytes += retained_size([state.source_refs])[0]
            else:
                component_payload_bytes += retained_size([snapshots])[0]
                source_ref_bytes += retained_size([state.source_refs])[0]
        retained_components = sum(len(state.source_snapshots) for state in retained.values())
        retained_prefixes = sum(state._history_prefix is not None for state in retained.values())
        source_recovery_bytes = sum(state._source_recovery.estimated_bytes + 1024
                                    for state in retained.values() if state._source_recovery is not None)
        claim_metadata_bytes = sum(sys.getsizeof(p.eviction_claims) + len(p.eviction_claims) * 16
                                   for p in self._pipelines.values())
        handoff = self.history_prefix_runtime
        handoff_bytes = (len(handoff.targets)*1024 + len(handoff.tasks)*8192
                         + len(handoff.component_jobs)*1024) if handoff else 0
        return {"active_bars": active, "closed_bars": closed, "components": components,
                "queued_snapshots": len(events), "queued_components": queued_components,
                "buffered_handoff_states": len(buffered),
                "eviction_claims": sum(len(p.eviction_claims) for p in self._pipelines.values()),
                "eviction_claim_metadata_bytes": claim_metadata_bytes,
                "retained_payload_states": len(payload_states),
                "retained_states": len(retained),
                "retained_components": retained_components,
                "retained_component_payload_bytes": component_payload_bytes,
                "source_ref_estimated_bytes": source_ref_bytes,
                "mutable_callback_states": len(mutable_callback_states),
                "retained_events": len(retained_events),
                **publisher_counts,
                "component_index_bytes": component_index_bytes,
                "retained_component_index_bytes": sum(index_bytes.values()),
                "history_prefixes": history_prefixes,
                "retained_history_prefixes": retained_prefixes,
                "source_recovery_bytes": source_recovery_bytes,
                "history_handoff_bytes": handoff_bytes,
                "source_preparation_scopes": len(self._active_preparations),
                "source_preparation_capacity_slots": self._preparation_capacity.capacity,
                "source_preparation_max_targets": MAX_PREPARATION_TARGETS,
                "source_preparation_in_use": self._preparation_capacity.in_use,
                "source_preparation_capacity_bytes": self._preparation_capacity.capacity * PREPARATION_BYTES,
                "preview_pending": len(self._previews.pending),
                "preview_inflight": len(self._previews.inflight),
                "preview_payload_states": len({id(state) for state in preview_states}),
                "preview_reserved_bytes": self._previews.snapshot()['reserved_bytes'],
                **self._source_preparation_metrics,
                "estimated_bytes": (len(retained) * 1024 + component_payload_bytes + source_ref_bytes
                    + sum(index_bytes.values()) + retained_prefixes * 32 * 1024 + source_recovery_bytes
                    + len(retained_events) * 256 + publisher_counts["publisher_metadata_bytes"]
                    + claim_metadata_bytes + handoff_bytes + len(self._active_preparations) * SCOPE_BYTES
                    + self._preparation_capacity.capacity * PREPARATION_BYTES),
                "estimate_basis": "accepted component/proof reference weights with live callback proof graphs; shared values may be overcounted; not an allocator/RSS cap",
                "protection": "active/correction state and pending publications stay with realtime owner"}

    def _memory_roots(self):
        # Diagnostic traversal is synchronous on the aggregation event loop;
        # callers must not retain or mutate the owner-private roots.
        return [*[list(engine._active.values()) + list(engine._closed.values())
                  + list(engine.evicted_closed) + list(engine.evicted_expired)
                  for pipeline in list(self._pipelines.values()) for engine in [pipeline.bar_state]],
                *[list(queue._queue) for queue, _ in list(self._publisher._subscribers)],
                *[pipeline.eviction_claims for pipeline in self._pipelines.values()],
                self._publisher._memory_roots(),
                self._previews.roots(),
                list(self.history_prefix_runtime.targets.values()) if self.history_prefix_runtime else [],
                self.history_prefix_runtime.component_jobs if self.history_prefix_runtime else {},
                [preparation.memory_roots() for preparation in list(self._active_preparations)]]

    def snapshot(self) -> dict:
        """Full diagnostic snapshot of the entire aggregator."""
        return {
            "config": self._cfg.snapshot(),
            "router": self._router.snapshot(),
            "publisher": self._publisher.snapshot(),
            "previews": self.preview_diagnostics(),
            "pipelines": {
                interval: p.snapshot()
                for interval, p in self._pipelines.items()
            },
        }

    def preview_diagnostics(self):
        """Bounded scalar observations; diagnostics never force calculation."""
        watermarks = []
        active = deferred = calculations = 0
        for pipeline in self._pipelines.values():
            for state in (*pipeline.bar_state._active.values(),*pipeline.bar_state._closed.values()):
                deferred += state._preview_deferred_inputs
                calculations += state._preview_calculations
            for state in pipeline.bar_state._active.values():
                active += 1
                if len(watermarks) < 128:
                    watermarks.append(dict(symbol=state.symbol,interval=state.interval,
                        exchange=state.exchange,market_type=state.market_type,identity=state.identity.to_dict(),
                        bucket_start_ms=state.bucket_start_ms,input=state.preview_input_version,
                        computed=state.preview_computed_version,published=state.preview_published_version,
                        dirty=state._preview_dirty,fallback_reason=state.preview_fallback_reason))
        return dict(self._previews.snapshot(),resident_deferred_inputs=deferred,
                    resident_calculations=calculations,active_states=active,
                    watermarks=watermarks,watermark_limit=128,watermarks_truncated=active>128,
                    publication_scope='successful publisher fanout; not consumer acknowledgment')

    def set_source_component_reader(
        self, reader: Callable[[str, int, int], Awaitable[list[dict]]],
    ) -> None:
        """Bind the owner's source readback without importing a storage backend."""
        self._source_component_reader = reader

    def set_preview_source_validator(self, validator, binding):
        """Bind the existing source/storage owner, without importing storage."""
        self._preview_source_validator = validator
        self._preview_source_binding = binding

    # ── Internal: Core Processing ────────────────────────────

    async def _handle_bar_input(self, exchange, market_type, symbol, interval,
                                bar_input, emit_events=True):
        # Capture before any reader, history admission or callback can suspend.
        # A native/default target needs the same detach fence as a compact
        # history target. Unregistered direct maintenance ingest remains valid.
        target_token = self.history_target_token(bar_input, interval)
        runtime = self.history_prefix_runtime
        if runtime is None:
            return await self._apply_bar_input(exchange, market_type, symbol, interval,
                                               bar_input, emit_events, target_token=target_token)
        if runtime.closing:
            from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
            raise BarDeliveryUnavailable('history/live owner is shutting down')
        async with runtime.hold(exchange, market_type, symbol, interval, bar_input.identity) as slot:
            if slot is not None:
                pipeline = self._pipelines[self._pipeline_key(interval, exchange, bar_input.identity)]
                try:
                    if not await runtime.before_input(slot, pipeline, bar_input, emit_events=emit_events):
                        return
                except Exception:
                    runtime.failed(slot)
                    raise
                if not runtime._current(slot):
                    raise RuntimeError('history target detached before input adoption')
            return await self._apply_bar_input(exchange, market_type, symbol, interval,
                                               bar_input, emit_events,
                                               target_token=target_token or (slot.token if slot else None))

    async def _apply_bar_input(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        bar_input: BarInput,
        emit_events: bool = True,
        target_token=None,
        _source_recovery=None,
        _cold_prepared=False,
        _source_fence=None,
        _source_adoption_fence=None,
    ) -> None:
        """Core processing callback: L1 → L2 → L3 → L4 → L5.

        This is the heart of the aggregator, called by the EventRouter
        for each (symbol, interval, BarInput) tuple.
        """
        pipeline = self._pipelines.get(
            self._pipeline_key(interval, exchange, bar_input.identity)
        )
        if pipeline is None:
            logger.warning("No pipeline for interval %s", interval)
            return

        def check_target():
            if _source_fence is not None and not _source_fence():
                from app.data_engine.aggregation.blocks import BlockRevisionChanged
                raise BlockRevisionChanged('source recovery binding changed before handoff')
            if target_token is not None and self._target_epochs.get(target_token[0]) is not target_token[1]:
                from app.data_engine.aggregation.blocks import BlockRevisionChanged
                raise BlockRevisionChanged('aggregation target detached during input')

        check_target()

        revision_provider = getattr(self, "acquisition_revision_provider", None)
        acquisition_revision = revision_provider() if revision_provider is not None else None
        source_floor = bar_input.extra.get('source_permission_floor')
        if source_floor is not None and (type(source_floor) is not int or source_floor < 0):
            raise ValueError('source deletion permission must be a nonnegative revision')

        # L2: Compute which bucket this input belongs to
        bucket_start_ms = pipeline.time_bucket.compute_bucket(bar_input.open_time_ms)

        existing = pipeline.bar_state.get_state(exchange, market_type, symbol, bucket_start_ms)
        if (existing is not None and existing._source_recovery is not None
                and (bar_input.merge_mode != MergeMode.COMPONENT or not bar_input.extra.get('source_ref')
                     or bar_input.source_interval != json.loads(existing._source_recovery.version.series)[3])):
            from app.data_engine.aggregation.blocks import BlockUnavailable
            raise BlockUnavailable('selected-source builder requires its receipted source grid or canonical handoff')
        reader = self.source_recovery_reader
        if (not _cold_prepared and reader is not None and bar_input.extra.get('source_ref')
                and bar_input.merge_mode == MergeMode.COMPONENT
                and ((existing is None)
                     or (existing is not None and existing._source_recovery is not None))):
            from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
            from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
            from app.data_engine.aggregation.source_window import MAX_SOURCE_WINDOW_ROWS
            from app.data_engine.interval_policy import IntervalAlignment
            strategy = pipeline.bar_state._component_merge_strategy
            source_ref = bar_input.extra['source_ref']
            target_spec, source_spec = parse_interval_spec(interval), parse_interval_spec(bar_input.source_interval)
            qualified = (target_spec is not None and source_spec is not None
                and len(source_ref) == 3 and set(source_ref) == {'series','open_time','revision'}
                and isinstance(source_ref['series'],str) and len(source_ref['series'])<=1024
                and type(source_ref['open_time']) is int and type(source_ref['revision']) is int
                and source_ref['revision']>0 and source_ref['open_time']==bar_input.open_time_ms
                and type(bar_input.open_time_ms) is int and type(bar_input.close_time_ms) is int
                and target_spec.alignment is source_spec.alignment is IntervalAlignment.FIXED_EPOCH
                and not target_spec.phase_ms and not source_spec.phase_ms
                and target_spec.nominal_ms % source_spec.nominal_ms == 0
                and target_spec.nominal_ms // source_spec.nominal_ms <= MAX_SOURCE_WINDOW_ROWS
                and bar_input.close_time_ms + 1 - bar_input.open_time_ms == source_spec.nominal_ms
                and bar_input.identity.is_legacy_default_for(exchange)
                and not pipeline.bar_state._merge_strategy_overridden
                and type(strategy) is ComponentSnapshotOHLCVMerge
                and getattr(strategy.apply, '__func__', None) is ComponentSnapshotOHLCVMerge.apply
                and reader.available())
            if not qualified and existing is not None and existing._source_recovery is not None:
                raise BlockUnavailable('selected-source builder lost its qualified owner')
            if qualified:
                if target_token is None or self.memory_budget is None:
                    raise BlockUnavailable('bounded cold recovery requires a registered budgeted target')
                cfg, budget, engine = self.config, self.memory_budget, pipeline.bar_state
                version = existing.preview_input_version if existing is not None else None
                snapshots = existing.source_snapshots if existing is not None else None
                refs = existing.source_refs if existing is not None else None
                accepted = ComponentSnapshotOHLCVMerge._snapshot_from_input(bar_input)
                incoming_key = (bar_input.symbol,bar_input.exchange,bar_input.market_type,
                                bar_input.source_interval,bar_input.source,bar_input.merge_mode)
                prepare = getattr(strategy, 'prepare_input', None)
                component_reader = self._source_component_reader
                lifecycle = (existing.status, existing.finality) if existing is not None else None
                def compatible():
                    check_target()
                    return (self.source_recovery_reader is reader and self.config is cfg
                        and self._source_component_reader is component_reader
                        and self.memory_budget is budget
                        and self._pipelines.get(self._pipeline_key(interval, exchange, bar_input.identity)) is pipeline
                        and pipeline.bar_state is engine and engine._component_merge_strategy is strategy
                        and not engine._merge_strategy_overridden
                        and getattr(strategy.apply, '__func__', None) is ComponentSnapshotOHLCVMerge.apply
                        and getattr(strategy, 'prepare_input', None) == prepare
                        and (bar_input.symbol,bar_input.exchange,bar_input.market_type,
                             bar_input.source_interval,bar_input.source,bar_input.merge_mode) == incoming_key
                        and ComponentSnapshotOHLCVMerge._snapshot_from_input(bar_input) == accepted)
                def current():
                    return (compatible()
                        and engine.get_state(exchange, market_type, symbol, bucket_start_ms) is existing
                        and (existing is None or (existing.preview_input_version == version
                            and (existing.status, existing.finality) == lifecycle
                            and existing.source_snapshots is snapshots and existing.source_refs is refs)))
                held = self.publisher._hold_payload('input', (existing,)) if existing is not None else None
                work = retained_size((existing,accepted))[0] + 16384
                try:
                    # Old immutable indexes can outlive a concurrent eviction or
                    # replacement while the physical reader is running.
                    with budget.reserve('history-query', work):
                        _, end = pipeline.time_bucket.compute_bucket_range(bucket_start_ms)
                        async with reader.stage(bar_input, bucket_start_ms, end,
                                                target_interval=interval, is_current=current,
                                                previous=existing._source_recovery if existing is not None else None,
                                                force=(existing is not None and len(existing.source_snapshots)>=128
                                                    and (bar_input.input_key not in existing.source_snapshots
                                                        or (bar_input.is_closed and existing.source_refs.get(bar_input.input_key)
                                                            != bar_input.extra['source_ref'])))) as staged:
                            receipt, owner_bound, watermark = staged
                            if not current():
                                raise BlockRevisionChanged('builder changed during source reconstruction')
                            if receipt is None and watermark is not None and existing is not None:
                                # Only the original loop-owned builder advances a read hint.
                                # Immutable runs and durable content proof stay shared/unchanged.
                                existing._source_recovery = replace(existing._source_recovery,
                                    observation_watermark=watermark)
                            if (receipt is None and existing is not None and existing._source_recovery is not None
                                    and existing._source_recovery.covers(bar_input.open_time_ms)):
                                return
                            # The first ordinary live leaf has no siblings to
                            # reconstruct. Keep the existing raw/live-prefix
                            # path rather than creating a cold owner for it.
                            return await self._apply_bar_input(exchange, market_type, symbol, interval,
                                bar_input, emit_events, target_token, receipt, True,
                                lambda: compatible() and owner_bound(), current)
                finally:
                    if held is not None:
                        self.publisher._release_payload(held)

        if (
            bar_input.extra.get("source_ref")
            and bar_input.is_closed
            and bar_input.merge_mode == MergeMode.COMPONENT
            and pipeline.bar_state.get_state(exchange, market_type, symbol, bucket_start_ms) is None
            and not _cold_prepared
        ):
            # After restart/eviction a historical correction is only one
            # component. Restore its siblings before recalculating the bucket.
            if self._source_component_reader is None:
                raise RuntimeError("source component readback is not configured")
            _, bucket_end_ms = pipeline.time_bucket.compute_bucket_range(bucket_start_ms)
            components = await self._source_component_reader(
                bar_input.extra["source_ref"]["series"], bucket_start_ms, bucket_end_ms,
            )
            check_target()
            for component in components:
                data = component["data"]
                if data["open_time"] == bar_input.open_time_ms:
                    continue
                sibling = replace(
                    bar_input, open_time_ms=data["open_time"], close_time_ms=data["close_time"],
                    **{name: data[name] if data[name] is not None else 0 for name in (
                        "open", "high", "low", "close", "volume", "quote_volume", "trades",
                        "taker_buy_base", "taker_buy_quote",
                    )},
                    extra={"source_ref": component["ref"]},
                )
                pipeline.bar_state.apply(exchange, market_type, symbol, bucket_start_ms, sibling)
            restored = pipeline.bar_state.get_state(exchange, market_type, symbol, bucket_start_ms)
            floors = [component['permission_floor'] for component in components if 'permission_floor' in component]
            if restored is not None and floors:
                restored.source_permission_floor = min(floors)

        # Check for event-driven close: if this input starts a new bucket,
        # close previous active bars for this symbol
        await self._check_event_driven_close(
            exchange,
            market_type,
            symbol,
            interval,
            pipeline,
            bucket_start_ms,
            bar_input,
            emit_events=emit_events,
            check_target=check_target,
        )
        check_target()

        # L3: Apply input to bar state
        if _source_adoption_fence is not None and not _source_adoption_fence():
            from app.data_engine.aggregation.blocks import BlockRevisionChanged
            raise BlockRevisionChanged('source builder changed before synchronous adoption')
        previous = pipeline.bar_state.get_active(exchange,market_type,symbol,bucket_start_ms)
        delay_preview = (self._previews.qualifies(pipeline,previous,bar_input,target_token,emit_events)
                         and self._previews.admit(pipeline,previous,target_token))
        if _source_recovery is not None:
            from app.data_engine.aggregation.source_window import SOURCE_SUMMARY_BYTES
            with self.memory_budget.reserve('realtime-state', SOURCE_SUMMARY_BYTES + 16384) as lease:
                def adopt():
                    return pipeline.bar_state.apply(exchange, market_type, symbol, bucket_start_ms,
                                                    bar_input, source_recovery=_source_recovery)
                result = []
                lease.retain(SOURCE_SUMMARY_BYTES + 16384, lambda: result.append(adopt()))
                state, change = result[0]
        else:
            state, change = pipeline.bar_state.apply(
                exchange, market_type, symbol, bucket_start_ms, bar_input,
                **({'defer_preview': True} if delay_preview else {}),
            )

        if state.acquisition_revision is None:
            state.acquisition_revision = acquisition_revision
        if source_floor is not None:
            state.source_permission_floor = min(
                source_floor, state.source_permission_floor
                if state.source_permission_floor is not None else source_floor)
        warm_floor = bar_input.extra.get("warm_start_acquisition_floor")
        if warm_floor is not None:
            # A replayed forming input keeps its original delete fence.
            state.acquisition_revision = (
                warm_floor if state.acquisition_revision is None
                else min(warm_floor, state.acquisition_revision)
            )

        # Drain eviction buffers — emit events for bars that were
        # force-closed or expired during apply() due to limit enforcement.
        await self._drain_eviction_buffers(pipeline, emit_events=emit_events)
        check_target()

        if state._preview_dirty:
            # Qualified forming tails cannot close on this input. Accepted
            # versions already advanced; the bounded deadline owns calculation.
            return

        # L5: Emit lifecycle events
        if emit_events:
            if change == BarStateChange.CREATED:
                await self._publisher.emit_created(state)
            elif change == BarStateChange.UPDATED:
                await self._publisher.emit_updated(state)
            elif change == BarStateChange.AMENDED:
                await self._publisher.emit_amended(state)
        check_target()

        if state.preview_published_version >= state.preview_input_version:
            self._previews.discard(state)

        runtime = self.history_prefix_runtime
        if (emit_events and runtime is not None and bar_input.merge_mode == MergeMode.COMPONENT
                and bar_input.extra.get("bybit_close_confirmed") is True):
            state = await runtime.complete_repaired_bucket(pipeline, state, bar_input)
            if state is None:
                return
            check_target()

        # L4: Check if this bar should be finalized
        is_backfill = bar_input.source == BarInputSource.BACKFILL
        trigger = FinalizeTrigger(
            trigger_type="input",
            input=bar_input,
            current_time_ms=int(time.time() * 1000),
            is_backfill=is_backfill,
        )
        close_event = pipeline.finalizer.check(state, trigger)

        if close_event is not None:
            # Seal the bar
            closed = pipeline.bar_state.close_bar(
                exchange, market_type, symbol, bucket_start_ms,
            )
            if closed is not None:
                self._previews.discard(closed)
                if emit_events:
                    await self._publisher.emit_closed(closed)
                # Drain eviction buffers after close_bar() — closing a bar
                # may trigger expired evictions from the closed bars cache.
                await self._drain_eviction_buffers(pipeline, emit_events=emit_events)

        if emit_events and runtime is not None:
            runtime.schedule_components(state,bar_input)

    async def _check_event_driven_close(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        pipeline: IntervalPipeline,
        new_bucket_start_ms: int,
        bar_input: BarInput,
        *,
        emit_events: bool = True,
        check_target=lambda: None,
    ) -> None:
        """Close any older active bars when a new bucket's data arrives."""
        if not self._cfg.use_event_driven_close:
            return

        active = pipeline.bar_state.get_all_active(exchange, market_type, symbol)
        for state in active:
            check_target()
            if pipeline.bar_state.get_active(exchange, market_type, symbol, state.bucket_start_ms) is not state:
                continue
            if state.bucket_start_ms < new_bucket_start_ms:
                trigger = FinalizeTrigger(
                    trigger_type="next_bucket",
                    current_time_ms=int(time.time() * 1000),
                    next_bucket_start=new_bucket_start_ms,
                )
                close_event = pipeline.finalizer.check(state, trigger)
                if close_event is not None:
                    closed = pipeline.bar_state.close_bar(
                        exchange, market_type, symbol, state.bucket_start_ms,
                    )
                    if closed is not None:
                        self._previews.discard(closed)
                        if emit_events:
                            await self._publisher.emit_closed(closed)
                        await self._drain_eviction_buffers(pipeline, emit_events=emit_events)
                        check_target()
                elif pipeline.finalizer.should_expire_unconfirmed(state, trigger):
                    state.close_reason = "next_bucket_unconfirmed"
                    expired = pipeline.bar_state.expire_bar(
                        exchange,
                        market_type,
                        symbol,
                        state.bucket_start_ms,
                    )
                    if expired is not None and emit_events:
                        self._previews.discard(expired)
                        await self._publisher.emit_expired(expired)
                        check_target()

    # ── Internal: Eviction Buffer Drain ──────────────────────

    async def _drain_eviction_buffers(
        self,
        pipeline: IntervalPipeline,
        *,
        emit_events: bool = True,
    ) -> None:
        """Emit lifecycle events for bars evicted by limit enforcement.

        The BarStateEngine populates ``evicted_closed`` and ``evicted_expired``
        buffers when bars are force-closed or expired during apply()/close_bar().
        This method drains those buffers and emits the appropriate events.
        """
        for buffer, emit in (
            (pipeline.bar_state.evicted_closed, self._publisher.emit_closed),
            (pipeline.bar_state.evicted_expired, self._publisher.emit_expired),
        ):
            if not emit_events:
                buffer.clear()
                continue
            while buffer:
                # Claim synchronously before callbacks await. Another drain
                # can process later items but cannot publish this item again.
                bar = buffer.pop(0)
                self._previews.discard(bar)
                token = object()
                pipeline.eviction_claims[token] = bar
                handoff = None
                try:
                    with self._publisher._observe_source_handoff(bar) as handoff:
                        await emit(bar)
                except BaseException:
                    # Source-backed failures/cancellation already belong to the
                    # publisher's original-ID retry snapshot, possibly even
                    # acknowledged by a concurrent retry. Never enqueue raw
                    # data a second time. Otherwise preserve the original item.
                    if handoff is None or not handoff.transferred:
                        buffer.insert(0, bar)
                    raise
                finally:
                    pipeline.eviction_claims.pop(token, None)
                    if not pipeline.eviction_claims:
                        pipeline.eviction_claims.clear()
                    del bar

    @asynccontextmanager
    async def _validated_active_state(self, pipeline, state):
        runtime = self.history_prefix_runtime
        if runtime is None:
            yield state
            return
        if runtime.closing:
            # Shutdown already drained all physical history reads. Do not
            # revive their summaries after the shared source has closed.
            if state._history_prefix is not None:
                pipeline.bar_state.expire_bar(state.exchange, state.market_type,
                                              state.symbol, state.bucket_start_ms)
                yield None
            else:
                yield state
            return
        async with runtime.hold(state.exchange, state.market_type, state.symbol,
                                state.interval, state.identity) as slot:
            current = pipeline.bar_state.get_active(state.exchange, state.market_type,
                                                    state.symbol, state.bucket_start_ms)
            if current is not None and slot is not None:
                try:
                    current = await runtime._refresh(slot, pipeline, current, emit_events=True)
                except Exception:
                    runtime.failed(slot)
                    raise
            yield current

    # ── Internal: Timeout Loop ───────────────────────────────

    async def _timeout_loop(self) -> None:
        """Background task that periodically checks for timed-out bars."""
        while True:
            try:
                await asyncio.sleep(1.0)  # check every second
                await self._check_timeouts()
                if self.history_prefix_runtime is not None:
                    await self.history_prefix_runtime.drain_components()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Timeout loop error: %s", exc, exc_info=True)
                await asyncio.sleep(5.0)

    async def _check_timeouts(self) -> None:
        """Check all active bars for timeout-based finalization."""
        for interval, pipeline in self._pipelines.items():
            # Get all active bars across all symbols
            for key, state in list(pipeline.bar_state._active.items()):
                async with self._validated_active_state(pipeline, state) as state:
                    if state is None:
                        continue
                    trigger = FinalizeTrigger(
                        trigger_type="timer",
                        current_time_ms=int(time.time() * 1000),
                    )
                    close_event = pipeline.finalizer.check(state, trigger)
                    if close_event is not None:
                        closed = pipeline.bar_state.close_bar(
                            state.exchange, state.market_type, state.symbol, state.bucket_start_ms,
                        )
                        if closed is not None:
                            self._previews.discard(closed)
                            await self._publisher.emit_closed(closed)
                    elif pipeline.finalizer.should_expire_unconfirmed(state, trigger):
                        state.close_reason = "timeout_unconfirmed"
                        expired = pipeline.bar_state.expire_bar(
                            state.exchange,
                            state.market_type,
                            state.symbol,
                            state.bucket_start_ms,
                        )
                        if expired is not None:
                            self._previews.discard(expired)
                            await self._publisher.emit_expired(expired)

    # ── Internal: Flush ──────────────────────────────────────

    async def _flush_all(self) -> None:
        """Finalize active bars during shutdown without inventing authority."""
        for interval, pipeline in self._pipelines.items():
            for key in list(pipeline.bar_state._active.keys()):
                exchange, market_type, symbol, bucket_start = key
                state = pipeline.bar_state.get_active(
                    exchange,
                    market_type,
                    symbol,
                    bucket_start,
                )
                if state is None:
                    continue
                async with self._validated_active_state(pipeline, state) as state:
                    if state is None:
                        continue
                    event = pipeline.finalizer.flush(state)
                    if event.event_type == BarEventType.CLOSED:
                        closed = pipeline.bar_state.close_bar(
                            exchange,
                            market_type,
                            symbol,
                            bucket_start,
                        )
                        if closed is not None:
                            await self._publisher.emit_closed(closed)
                    else:
                        expired = pipeline.bar_state.expire_bar(
                            exchange,
                            market_type,
                            symbol,
                            bucket_start,
                        )
                        if expired is not None:
                            await self._publisher.emit_expired(expired)
        logger.info("Flushed all active bars")
