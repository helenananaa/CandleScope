"""Independent lifecycle and projection service for advanced market data."""

from __future__ import annotations

import asyncio
from bisect import bisect_right
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from app.core.async_cleanup import finish_cleanup
from app.core.executors import run_storage
from app.data_engine.ingestion.models import (
    DataSource,
    MarketEvent,
    StreamDescriptor,
    StreamType,
    TransportRequest,
)
from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    last_closed_bar_open_ms,
    parse_interval_ms,
    parse_interval_spec,
)
from app.data_engine.history import (
    BoundaryReason,
    ExchangeHistoryPolicyResolver,
    TimeBound,
)
from app.data_engine.storage.market_metrics_repo import (
    MarketMetricsRepository,
    normalize_funding_cycle_ms,
)
from app.exchanges import (
    bootstrap_default_adapters,
    get_exchange_registry,
    get_shared_rate_limit_manager,
)

from .events import HubRecord, MarketStateEvent
from .hub import MarketEventHub, MarketHubSubscription
from .lifecycle import KeyedAsyncLockPool, drain_cancellation_safe_cleanup
from .models import MarketChannel, MarketStreamKey
from .storage_writer import MarketMetricStorageWriter
from .oi_history import (
    merge_ranges, missing_ranges, unsampled_prefixes, verified_sample_ranges,
)


logger = logging.getLogger("data_engine.market_data")

_SUMMARY_CHANNELS = frozenset({
    MarketChannel.MARK_PRICE,
    MarketChannel.INDEX_PRICE,
    MarketChannel.BASIS,
})
_P1_CHANNELS = _SUMMARY_CHANNELS | {
    MarketChannel.FUNDING_RATE,
    MarketChannel.OPEN_INTEREST,
}
_HISTORY_STREAM_TYPES = {
    MarketChannel.FUNDING_RATE: StreamType.FUNDING_RATE,
    MarketChannel.OPEN_INTEREST: StreamType.OPEN_INTEREST,
    MarketChannel.LIQUIDATION: StreamType.LIQUIDATION,
}
_DEFAULT_OPEN_INTEREST_STORAGE_PERIOD = "5m"
_DEFAULT_OPEN_INTEREST_STORAGE_BUCKET_MS = 5 * 60 * 1000
_HISTORY_RETENTION_SAFETY_MS = 60 * 1000
_PREMIUM_INDEX_INTERVAL = "1m"
_PREMIUM_INDEX_INTERVAL_MS = 60 * 1000
_DEFAULT_FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000
_BINANCE_FUNDING_INTERVALS_MS = frozenset(
    hours * 60 * 60 * 1000
    for hours in (1, 2, 4, 8)
)
_FUNDING_CONTEXT_LOOKBACK_MS = 24 * 60 * 60 * 1000
_FUNDING_INTEREST_RATE_8H = 0.0001
_FUNDING_ADJUSTMENT_BOUND = 0.0005
_FUNDING_RATE_BOUND = 0.0075
_FUNDING_FORMULA_VERSION = "binance-premium-index-cumavg-v2"
_MAX_PREMIUM_ESTIMATE_POINTS = 250_000
_MAX_UPSTREAM_HISTORY_PAGES_PER_REQUEST = 16
_MAX_PREMIUM_HISTORY_PAGES_PER_REQUEST = 64
_PREMIUM_HISTORY_PAGE_POINTS = 1000
_PREMIUM_FETCH_CONCURRENCY = 4
_REALTIME_FUNDING_STALE_MS = 10_000
_FUNDING_SETTLEMENT_EDGE_TTL_MS = 60_000
_FUNDING_SETTLEMENT_POLICY_REVISION = "binance-usdm-regular-settlement-v1"


@dataclass(slots=True)
class _LogicalLease:
    consumers: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _PhysicalEntry:
    descriptor: StreamDescriptor
    logical_keys: set[MarketStreamKey] = field(default_factory=set)
    handle: Any = None
    stop_task: asyncio.Task | None = None
    stop_error: str | None = None
    stop_attempts: int = 0
    retry_stop_at: float = 0.0


@dataclass(frozen=True, slots=True)
class MarketHistoryPage:
    events: list[MarketStateEvent]
    fallback: bool = False
    complete: bool | None = None
    retryable: bool = False
    terminal_reason: str | None = None
    earliest_available_ms: int | None = None
    availability_revision: str | None = None
    excluded_ranges: tuple[dict[str, Any], ...] = ()
    covered_ranges: tuple[dict[str, Any], ...] | None = None
    missing_ranges: tuple[dict[str, Any], ...] = ()
    has_more: bool | None = None
    next_end_ms: int | None = None
    next_start_ms: int | None = None
    query_mode: str | None = None
    coverage_basis: str = "unqualified_local"
    revalidate_after_ms: int | None = None


@dataclass(frozen=True, slots=True)
class _HistoryRefreshPlan:
    start_ms: int | None
    end_ms: int | None
    should_fetch: bool = True
    terminal_reason: str | None = None
    earliest_available_ms: int | None = None
    availability_revision: str | None = None
    max_page_size: int | None = None
    event_cutoff_ms: int | None = None
    excluded_ranges: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class _HybridFundingResult:
    events: list[MarketStateEvent]
    complete: bool
    retryable: bool = False
    fallback: bool = False
    excluded_ranges: tuple[dict[str, Any], ...] = ()


class MarketDataService:
    """Own logical leases, physical feeds, REST reads, and the typed hub."""

    def __init__(
        self,
        ingestion_factory: Any,
        *,
        hub: MarketEventHub | None = None,
        open_interest_poll_seconds: float = 5.0,
        max_open_interest_streams: int = 64,
        max_summary_streams: int = 512,
        metrics_repository: MarketMetricsRepository | None = None,
        metrics_writer: MarketMetricStorageWriter | None = None,
        history_policy: ExchangeHistoryPolicyResolver | None = None,
    ) -> None:
        self._factory = ingestion_factory
        self.hub = hub or MarketEventHub()
        self._open_interest_poll_seconds = max(1.0, float(open_interest_poll_seconds))
        self._max_open_interest_streams = max(1, int(max_open_interest_streams))
        self._max_summary_streams = max(1, int(max_summary_streams))
        self._logical_leases: dict[MarketStreamKey, _LogicalLease] = {}
        self._physical_entries: dict[tuple[str, str, str, str], _PhysicalEntry] = {}
        self._lock = asyncio.Lock()
        self._identity_locks = KeyedAsyncLockPool[tuple[str, str, str, str]]()
        self._snapshot_lock = asyncio.Lock()
        self._snapshot_tasks: dict[tuple[str, str, str, str], asyncio.Task] = {}
        self._history_tasks: dict[tuple, asyncio.Task] = {}
        # Joinable requests and physically owned work have separate lifetimes:
        # the last waiter unlinks a request before its storage thread drains.
        self._history_jobs: set[asyncio.Task] = set()
        self._history_waiters: dict[tuple, int] = {}
        self._history_identity_locks = KeyedAsyncLockPool[tuple]()
        self._funding_refresh_tasks: dict[
            tuple[tuple[str, str, str], int, int, int, bool], asyncio.Task[int | None],
        ] = {}
        self._funding_refresh_jobs: set[asyncio.Task[int | None]] = set()
        self._funding_refresh_waiters: dict[asyncio.Task[int | None], int] = {}
        self._rate_limits = get_shared_rate_limit_manager()
        self._metrics_repository = metrics_repository
        self._metrics_writer = metrics_writer
        self._history_policy = history_policy
        self._metrics = {"snapshot_fetch_errors": 0, "physical_stop_errors": 0}
        self._shutdown_task: asyncio.Task[None] | None = None
        self._closed = False

    async def ensure_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        """Acquire one idempotent consumer lease; start the first physical feed."""

        consumer = self._consumer_id(consumer_id)
        self._validate_key(key, history=False)
        physical_id = self._physical_id(key)

        async with self._identity_locks.hold(physical_id):
            while True:
                wait_for_stop: asyncio.Task | None = None
                created_physical = False
                async with self._lock:
                    if self._closed:
                        raise RuntimeError("market data service is closed")
                    entry = self._physical_entries.get(physical_id)
                    if entry is not None and entry.stop_task is not None:
                        wait_for_stop = entry.stop_task
                    elif entry is not None and entry.stop_error is not None:
                        delay = max(0.0, entry.retry_stop_at - time.monotonic())
                        wait_for_stop = self._schedule_physical_stop(
                            physical_id,
                            entry,
                            delay=delay,
                        )
                    else:
                        lease = self._logical_leases.get(key)
                        if lease is not None and consumer in lease.consumers:
                            return False

                        created_physical = entry is None
                        if entry is None:
                            wait_for_stop = self._physical_capacity_waiter(key)
                            if wait_for_stop is None:
                                entry = _PhysicalEntry(
                                    descriptor=self._physical_descriptor(key),
                                )
                                self._physical_entries[physical_id] = entry

                        if wait_for_stop is None:
                            assert entry is not None
                            lease = self._logical_leases.setdefault(key, _LogicalLease())
                            lease.consumers.add(consumer)
                            entry.logical_keys.add(key)
                            if not created_physical:
                                return True

                if wait_for_stop is not None:
                    await asyncio.shield(wait_for_stop)
                    continue

                async def _on_event(event: MarketEvent) -> None:
                    await self._on_ingestion_event(physical_id, event)

                try:
                    from .continuity import health_callback, ingestion_options
                    handle = await self._factory.start_market(
                        entry.descriptor,
                        _on_event,
                        **ingestion_options(self._factory, on_health=health_callback(
                            self.hub, lambda: tuple(entry.logical_keys)
                            if self._physical_entries.get(physical_id) is entry else ())),
                    )
                except BaseException:
                    await drain_cancellation_safe_cleanup(
                        self._cleanup_start_entry(
                            physical_id,
                            entry,
                            key,
                            consumer,
                        ),
                        name=(
                            f"market-start-cleanup-{physical_id[0]}-"
                            f"{physical_id[1]}-{physical_id[2]}-{physical_id[3]}"
                        ),
                    )
                    raise

                try:
                    entry.handle = handle
                    async with self._lock:
                        if (
                            not self._closed
                            and self._physical_entries.get(physical_id) is entry
                        ):
                            return True
                except BaseException:
                    await drain_cancellation_safe_cleanup(
                        self._cleanup_start_entry(
                            physical_id,
                            entry,
                            key,
                            consumer,
                        ),
                        name=(
                            f"market-start-cleanup-{physical_id[0]}-"
                            f"{physical_id[1]}-{physical_id[2]}-{physical_id[3]}"
                        ),
                    )
                    raise

                caller_cancelled = await drain_cancellation_safe_cleanup(
                    self._cleanup_start_entry(
                        physical_id,
                        entry,
                        key,
                        consumer,
                    ),
                    name=(
                        f"market-start-cleanup-{physical_id[0]}-"
                        f"{physical_id[1]}-{physical_id[2]}-{physical_id[3]}"
                    ),
                )
                if caller_cancelled:
                    raise asyncio.CancelledError
                raise RuntimeError("market data service closed while stream was starting")

    async def ensure_streams(
        self,
        keys: Iterable[MarketStreamKey],
        *,
        consumer_id: str,
    ) -> list[MarketStreamKey]:
        acquired: list[MarketStreamKey] = []
        try:
            for key in keys:
                if await self.ensure_stream(key, consumer_id=consumer_id):
                    acquired.append(key)
            return acquired
        except BaseException:
            for key in reversed(acquired):
                try:
                    await self.release_stream(key, consumer_id=consumer_id)
                except BaseException:
                    logger.exception("Failed to roll back market stream %s", key)
            raise

    async def release_stream(self, key: MarketStreamKey, *, consumer_id: str) -> bool:
        """Release one lease and stop the physical feed after its last dependent."""

        consumer = self._consumer_id(consumer_id)
        physical_id = self._physical_id(key)
        async with self._identity_locks.hold(physical_id):
            stop_task: asyncio.Task | None = None
            async with self._lock:
                lease = self._logical_leases.get(key)
                if lease is None or consumer not in lease.consumers:
                    return False
                lease.consumers.remove(consumer)
                if lease.consumers:
                    return True

                self._logical_leases.pop(key, None)
                entry = self._physical_entries.get(physical_id)
                if entry is None:
                    return True
                entry.logical_keys.discard(key)
                if entry.logical_keys:
                    return True

                if entry.stop_task is None:
                    self._schedule_physical_stop(physical_id, entry)
                stop_task = entry.stop_task

            if stop_task is not None:
                await asyncio.shield(stop_task)
            return True

    async def snapshot(
        self,
        keys: Iterable[MarketStreamKey],
        *,
        refresh_missing: bool = True,
    ) -> list[HubRecord]:
        self._ensure_open()
        requested = list(dict.fromkeys(keys))
        for key in requested:
            self._validate_key(key, history=False)

        now_ms = int(time.time() * 1000)
        existing = {
            record.event.key
            for record in self.hub.snapshot(requested)
            if self._is_fresh(record, now_ms=now_ms)
        }
        missing = [key for key in requested if key not in existing]
        if refresh_missing and missing:
            await self.refresh_snapshot(missing)
        now_ms = int(time.time() * 1000)
        by_key = {
            record.event.key: record
            for record in self.hub.snapshot(requested)
            if self._is_fresh(record, now_ms=now_ms)
        }
        return [by_key[key] for key in requested if key in by_key]

    async def refresh_snapshot(
        self,
        keys: Iterable[MarketStreamKey],
    ) -> list[HubRecord]:
        self._ensure_open()
        requested = list(dict.fromkeys(keys))
        grouped: dict[tuple[str, str, str, str], list[MarketStreamKey]] = {}
        for key in requested:
            self._validate_key(key, history=False)
            grouped.setdefault(self._physical_id(key), []).append(key)

        pages = await asyncio.gather(
            *(self._refresh_group(physical_id, group) for physical_id, group in grouped.items()),
            return_exceptions=True,
        )
        records: list[HubRecord] = []
        for page in pages:
            if isinstance(page, BaseException):
                self._metrics["snapshot_fetch_errors"] += 1
                logger.warning("Advanced market snapshot group failed: %s", page)
                continue
            records.extend(self.hub.seed(page))
        return records

    async def history(
        self,
        key: MarketStreamKey,
        *,
        period: str | None = None,
        limit: int = 500,
        start_ms: int | None = None,
        end_ms: int | None = None,
        view: str | None = None,
        mode: str | None = None,
    ) -> list[MarketStateEvent]:
        page = await self.history_page(
            key,
            period=period,
            limit=limit,
            start_ms=start_ms,
            end_ms=end_ms,
            view=view,
            mode=mode,
        )
        return page.events

    async def history_page(
        self,
        key: MarketStreamKey,
        *,
        period: str | None = None,
        limit: int = 500,
        start_ms: int | None = None,
        end_ms: int | None = None,
        view: str | None = None,
        mode: str | None = None,
    ) -> MarketHistoryPage:
        """Read one Funding/OI page, reusing qualified local acquisition ranges.

        Without an injected repository this preserves the original upstream-
        only behavior for tests and alternate embeddings.  With storage
        enabled, an upstream failure falls back to an already persisted page.
        """

        self._ensure_open()
        self._validate_key(key, history=True)
        if mode not in {None, "local_only", "fill_missing", "refresh"}:
            raise ValueError("history mode must be local_only, fill_missing or refresh")
        if not 1 <= limit <= 1000:
            raise ValueError("history limit must be between 1 and 1000")
        if start_ms is not None and end_ms is not None and start_ms > end_ms:
            raise ValueError("start_ms must be less than or equal to end_ms")
        stream_type = _HISTORY_STREAM_TYPES.get(key.channel)
        if stream_type is None:
            raise ValueError(f"history is not supported for channel {key.channel.value!r}")
        if key.channel == MarketChannel.OPEN_INTEREST and not period:
            raise ValueError("open-interest history requires period")
        normalized_view = (view or "sparse").strip().lower()
        if normalized_view not in {"sparse", "hybrid"}:
            raise ValueError("funding history view must be 'sparse' or 'hybrid'")
        hybrid_funding = normalized_view == "hybrid"
        if hybrid_funding and key.channel != MarketChannel.FUNDING_RATE:
            raise ValueError("hybrid history is available only for funding_rate")
        if hybrid_funding:
            if key.exchange != "binance" or key.market_type != "futures":
                raise ValueError(
                    "hybrid funding history is currently available only for binance futures",
                )
            period_spec = parse_interval_spec(period or "")
            if period_spec is None:
                raise ValueError("hybrid funding history requires a valid chart period")
            period = period_spec.canonical
            if self._metrics_repository is None:
                raise ValueError("hybrid funding history requires metric storage")
            if mode == "refresh":
                raise ValueError("explicit refresh is not yet supported for hybrid funding history")

        descriptor = StreamDescriptor(
            symbol=key.symbol,
            stream_type=stream_type,
            interval=period,
            exchange=key.exchange,
            market_type=key.market_type,
        )
        event_params: dict[str, str] = {}
        if period is not None:
            event_params["period"] = period
        if hybrid_funding:
            event_params["view"] = "hybrid"
        event_key = (
            MarketStreamKey.build(
                key.exchange,
                key.market_type,
                key.symbol,
                key.channel,
                params=event_params,
            )
            if event_params
            else key
        )
        refresh_plan = self._history_refresh_plan(
            key,
            period=period,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        native_bounded = (
            key.exchange == "binance" and key.market_type == "futures"
            and start_ms is not None and end_ms is not None
            and self._metrics_repository is not None
        )
        if native_bounded and key.channel == MarketChannel.FUNDING_RATE and not hybrid_funding:
            assert start_ms is not None and end_ms is not None
            return await self._sparse_funding_history_page(
                event_key, start_ms=start_ms, end_ms=end_ms, limit=limit,
                mode=mode or "fill_missing", plan=refresh_plan,
            )
        native_oi = (
            key.channel == MarketChannel.OPEN_INTEREST
            and native_bounded
        )
        if native_oi:
            assert start_ms is not None and end_ms is not None
            step_ms = parse_interval_ms(period or "")
            assert step_ms is not None
            return await self._shared_oi_history(
                event_key, descriptor, period=period or "", step_ms=step_ms,
                start_ms=start_ms, end_ms=end_ms, limit=limit,
                mode=mode or "fill_missing", plan=refresh_plan,
            )
        if mode == "fill_missing" and not hybrid_funding:
            raise ValueError("fill_missing requires bounded native Binance futures funding or OI history")
        if mode == "local_only":
            if hybrid_funding:
                result = await self._build_hybrid_funding_history(
                    event_key, period=period or "", start_ms=start_ms,
                    end_ms=end_ms, limit=limit, fetch_missing=False,
                )
                return MarketHistoryPage(events=result.events, complete=False,
                                         covered_ranges=(), query_mode=mode)
            return MarketHistoryPage(
                events=await self._read_persisted_history(
                    event_key, period=period, limit=limit,
                    start_ms=start_ms, end_ms=end_ms,
                ), complete=False, covered_ranges=(), query_mode=mode,
                excluded_ranges=refresh_plan.excluded_ranges,
            )
        if hybrid_funding:
            page = await self._hybrid_funding_history_page(
                event_key,
                period=period or "",
                start_ms=start_ms,
                end_ms=end_ms,
                limit=limit,
                refresh_plan=refresh_plan,
            )
            return replace(page, query_mode=mode) if mode is not None else page
        fetch_start_ms = refresh_plan.start_ms
        fetch_end_ms = refresh_plan.end_ms
        if self._metrics_repository is None:
            if not refresh_plan.should_fetch:
                return MarketHistoryPage(
                    events=[],
                    complete=True,
                    terminal_reason=refresh_plan.terminal_reason,
                    earliest_available_ms=refresh_plan.earliest_available_ms,
                    availability_revision=refresh_plan.availability_revision,
                    excluded_ranges=refresh_plan.excluded_ranges,
                )
            raw_events = await self._fetch_market(
                descriptor,
                limit=min(limit, refresh_plan.max_page_size or limit),
                start_ms=fetch_start_ms,
                end_ms=fetch_end_ms,
                history=True,
            )
            projected_events = [
                projected
                for event in raw_events
                if (projected := self._project(event, event_key)) is not None
            ]
            return MarketHistoryPage(
                events=self._apply_history_event_cutoff(projected_events, refresh_plan),
                excluded_ranges=refresh_plan.excluded_ranges,
            )

        local_events = await self._read_persisted_history(
            event_key,
            period=period,
            limit=limit,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        local_events = self._apply_history_event_cutoff(local_events, refresh_plan)
        if not refresh_plan.should_fetch:
            return MarketHistoryPage(
                events=local_events,
                complete=len(local_events) < limit,
                terminal_reason=(
                    refresh_plan.terminal_reason
                    if len(local_events) < limit
                    else None
                ),
                earliest_available_ms=refresh_plan.earliest_available_ms,
                availability_revision=refresh_plan.availability_revision,
                excluded_ranges=refresh_plan.excluded_ranges,
            )
        try:
            raw_events = await self._fetch_market(
                descriptor,
                limit=min(limit, refresh_plan.max_page_size or limit),
                start_ms=fetch_start_ms,
                end_ms=fetch_end_ms,
                history=True,
            )
        except ValueError:
            raise
        except Exception:
            if not local_events:
                raise
            logger.warning(
                "Advanced market history refresh failed; serving persisted %s page",
                event_key.topic,
                exc_info=True,
            )
            return MarketHistoryPage(
                events=local_events,
                fallback=True,
                retryable=True,
                excluded_ranges=refresh_plan.excluded_ranges,
            )

        projected_events = [
            projected
            for event in raw_events
            if (projected := self._project(event, event_key)) is not None
        ]
        await self._persist_final_history(projected_events, period=period)
        persisted_events = await self._read_persisted_history(
            event_key,
            period=period,
            limit=limit,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        return MarketHistoryPage(
            events=self._apply_history_event_cutoff(persisted_events, refresh_plan),
            excluded_ranges=refresh_plan.excluded_ranges,
        )

    async def _sparse_funding_history_page(
        self, key: MarketStreamKey, *, start_ms: int, end_ms: int, limit: int,
        mode: str, plan: _HistoryRefreshPlan,
    ) -> MarketHistoryPage:
        repository = self._metrics_repository
        assert repository is not None
        read_end = min(end_ms, plan.event_cutoff_ms) if plan.event_cutoff_ms is not None else end_ms
        fetch_start = max(start_ms, plan.start_ms if plan.start_ms is not None else start_ms)
        fetch_end = min(read_end, plan.end_ms if plan.end_ms is not None else read_end)
        fetchable = plan.should_fetch and fetch_start <= fetch_end
        async def read():
            return await run_storage(
                repository.read_funding_with_settlement_coverage,
                exchange=key.exchange, market_type=key.market_type, symbol=key.symbol,
                start_ms=start_ms, end_ms=read_end, limit=limit + 1, coverage_end_ms=read_end,
                policy_revision=_FUNDING_SETTLEMENT_POLICY_REVISION,
                now_ms=self._funding_refresh_wall_ms(), use_cycle_range=False,
            )

        rows, proof = await read()
        # A verified oldest-first page can end before the requested window.
        # Its continuation owns the suffix and can acquire it independently.
        acquisition_end = fetch_end
        if mode == "fill_missing" and len(rows) > limit:
            acquisition_end = min(fetch_end, rows[limit - 1]["funding_time_ms"])
        failed = False
        should_refresh = mode == "refresh" or (
            mode == "fill_missing" and missing_ranges(fetch_start, acquisition_end, proof)
        )
        if fetchable and fetch_start <= acquisition_end and should_refresh:
            try:
                acquired, _ = await self._fetch_funding_settlement_pages(
                    key, start_ms=fetch_start, end_ms=acquisition_end, refresh=mode == "refresh",
                )
                failed = mode == "refresh" and not acquired
            except Exception:
                logger.warning("Sparse funding settlement acquisition failed for %s", key.topic, exc_info=True)
                failed = True
            rows, proof = await read()

        more = len(rows) > limit
        rows = rows[:limit]
        page_end = rows[-1]["funding_time_ms"] if more else end_ms
        relevant_proof = [item for item in proof if item["start_ms"] <= page_end]
        covered = merge_ranges([
            {"start_ms": item["start_ms"], "end_ms": min(page_end, item["end_ms"])}
            for item in relevant_proof
        ])
        excluded = [
            {**item, "end_ms": min(page_end, item["end_ms"])}
            for item in plan.excluded_ranges if item["start_ms"] <= page_end
        ]
        unavailable = (
            [(start_ms, fetch_start - 1), (fetch_end + 1, page_end)] if fetchable
            else [(start_ms, page_end)]
        )
        for left, right in unavailable:
            for gap in missing_ranges(left, min(right, page_end), [*covered, *excluded]):
                excluded.append({
                    **gap, "disposition": "unavailable",
                    "reason": plan.terminal_reason or "outside_provider_window",
                })
        missing = missing_ranges(start_ms, page_end, [*covered, *excluded])
        events = self._funding_history_events(key, rows, now_ms=self._funding_refresh_wall_ms())
        return MarketHistoryPage(
            events=events, fallback=failed and bool(events),
            complete=not missing and not more and not failed,
            retryable=(failed or bool(missing)) and mode != "local_only",
            terminal_reason=plan.terminal_reason, earliest_available_ms=plan.earliest_available_ms,
            availability_revision=plan.availability_revision, excluded_ranges=tuple(excluded),
            covered_ranges=tuple(covered), missing_ranges=tuple(missing), has_more=more,
            next_start_ms=page_end + 1 if more and not missing and not failed else None,
            query_mode=mode, coverage_basis=_FUNDING_SETTLEMENT_POLICY_REVISION,
            revalidate_after_ms=min(
                (item["expires_at_ms"] for item in relevant_proof if "expires_at_ms" in item), default=None,
            ),
        )

    async def _shared_oi_history(
        self, key, descriptor, *, period, step_ms, start_ms, end_ms, limit, mode, plan,
    ) -> MarketHistoryPage:
        identity = (key.exchange, key.market_type, key.symbol, period)
        request_id = (identity, start_ms, end_ms, limit, mode, plan.availability_revision)
        task = self._history_tasks.get(request_id)
        if task is None:
            if len(self._history_jobs) >= 32:
                return MarketHistoryPage(events=[], complete=False, retryable=True,
                                         covered_ranges=(), query_mode=mode)
            self._ensure_open()
            task = asyncio.create_task(self._oi_history_page(
                key, descriptor, identity=identity, period=period, step_ms=step_ms,
                start_ms=start_ms, end_ms=end_ms, limit=limit, mode=mode, plan=plan,
            ), name="market-oi-history")
            self._history_tasks[request_id] = task
            self._history_jobs.add(task)
            def completed(done):
                self._history_jobs.discard(done)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(completed)
        self._history_waiters[request_id] = self._history_waiters.get(request_id, 0) + 1
        try:
            return await asyncio.shield(task)
        finally:
            remaining = self._history_waiters.get(request_id, 1) - 1
            if remaining:
                self._history_waiters[request_id] = remaining
            else:
                self._history_waiters.pop(request_id, None)
                if self._history_tasks.get(request_id) is task:
                    self._history_tasks.pop(request_id, None)
                if not task.done():
                    task.cancel()
                async def drain():
                    await asyncio.gather(task, return_exceptions=True)
                if await drain_cancellation_safe_cleanup(drain(), name="market-oi-history-release"):
                    raise asyncio.CancelledError

    async def _oi_history_page(
        self, key, descriptor, *, identity, period, step_ms,
        start_ms, end_ms, limit, mode, plan,
    ) -> MarketHistoryPage:
        # Binance USD-M OI is period-sampled. Off-grid observations can be
        # retained, but only committed on-grid samples prove expected coverage.
        async with self._history_identity_locks.hold(identity):
            self._ensure_open()
            repository = self._metrics_repository
            assert repository is not None
            now_ms = int(time.time() * 1000)
            page_limit = min(500, plan.max_page_size or 500)
            window_start = max(start_ms, end_ms - 86_400_000 + 1)
            revision = "binance-oi-grid-v2:" + (plan.availability_revision or "static")
            common = dict(exchange=key.exchange, market_type=key.market_type,
                          symbol=key.symbol, period=period)

            async def read():
                return await run_storage(
                    repository.read_open_interest_with_coverage, **common,
                    start_ms=window_start, end_ms=min(end_ms, now_ms), limit=limit,
                    policy_revision=revision, now_ms=int(time.time() * 1000),
                )

            rows, covered, more_rows, revalidate_after_ms = await read()
            fetch_start = max(window_start, plan.start_ms or window_start)
            fetch_end = min(end_ms, plan.end_ms if plan.end_ms is not None else now_ms)
            excluded = list(plan.excluded_ranges)
            if window_start < fetch_start:
                excluded.append({"start_ms": window_start, "end_ms": fetch_start - 1,
                                 "disposition": "unavailable", "reason": plan.terminal_reason or "outside_upstream_retention"})
            if not plan.should_fetch:
                reason = plan.terminal_reason or "future"
                excluded.append({"start_ms": window_start, "end_ms": end_ms,
                                 "disposition": "not_expected" if reason == "future" else "unavailable",
                                 "reason": reason})
            fetchable = plan.should_fetch and fetch_start <= fetch_end
            pending = []
            if fetchable:
                if mode == "refresh":
                    pending = [{"start_ms": fetch_start, "end_ms": fetch_end}]
                else:
                    empty_prefixes = unsampled_prefixes(fetch_start, fetch_end, covered, step_ms)
                    pending = missing_ranges(fetch_start, fetch_end, [*covered, *empty_prefixes])
            failed = False
            if mode != "local_only":
                refreshed = []
                calls = 0
                while pending and calls < 16:
                    run = pending.pop(0)
                    calls += 1
                    try:
                        raw = await self._fetch_market(
                            descriptor, limit=page_limit, start_ms=run["start_ms"],
                            end_ms=run["end_ms"], history=True,
                        )
                        projected = [self._project(item, key) for item in raw]
                        if any(event is None or not run["start_ms"] <= event.event_time_ms <= run["end_ms"]
                               for event in projected):
                            raise RuntimeError("OI history response did not satisfy its requested range")
                        stamps = [event.event_time_ms for event in projected]
                        if len(set(stamps)) != len(stamps):
                            raise RuntimeError("OI history response contained duplicate timestamps")
                        await self._persist_final_history(projected, period=period)
                        if len(raw) >= page_limit:
                            # No ordering or exhaustion is assumed at capacity.
                            # Bisect time, with a strict per-call work budget.
                            midpoint = (run["start_ms"] + run["end_ms"]) // 2
                            if midpoint >= run["end_ms"]:
                                raise RuntimeError("OI history page cannot be resolved within its timestamp range")
                            pending[:0] = [{"start_ms": run["start_ms"], "end_ms": midpoint},
                                           {"start_ms": midpoint + 1, "end_ms": run["end_ms"]}]
                            continue
                        expected_rows = [dict(event_time_ms=event.event_time_ms,
                                              open_interest=event.data["open_interest"],
                                              open_interest_value=event.data.get("open_interest_value"),
                                              is_final=True) for event in projected]
                        # Split on a sample boundary so a mutable cell's
                        # expiration cannot discard established history.
                        mutable_start = (now_ms // step_ms - 1) * step_ms
                        for proof in verified_sample_ranges(stamps, run["end_ms"], step_ms):
                            start, end = proof["start_ms"], proof["end_ms"]
                            segments = [(start, min(end, mutable_start - 1), None),
                                        (max(start, mutable_start), end, now_ms + 60_000)]
                            for left, right, expires in segments:
                                if left > right:
                                    continue
                                recorded = await run_storage(
                                    repository.record_open_interest_query, **common,
                                    start_ms=left, end_ms=right, policy_revision=revision,
                                    expected_rows=[row for row in expected_rows if left <= row["event_time_ms"] <= right],
                                    observed_at_ms=now_ms, expires_at_ms=expires,
                                )
                                if recorded and mode == "refresh":
                                    refreshed.append({"start_ms": left, "end_ms": right})
                    except ValueError:
                        raise
                    except Exception:
                        logger.warning("OI history range fetch failed", exc_info=True)
                        failed = True
                        break
                failed = failed or bool(pending)
                if mode == "refresh" and fetchable:
                    refresh_prefixes = unsampled_prefixes(fetch_start, fetch_end, refreshed, step_ms)
                    failed = failed or bool(missing_ranges(fetch_start, fetch_end, [*refreshed, *refresh_prefixes]))
                if calls:
                    rows, covered, more_rows, revalidate_after_ms = await read()
            response_start = rows[0]["event_time_ms"] if more_rows else window_start
            covered = merge_ranges([{ "start_ms": max(response_start, r["start_ms"]), "end_ms": r["end_ms"] }
                                    for r in covered if r["end_ms"] >= response_start])
            empty_prefixes = unsampled_prefixes(response_start, end_ms, [*covered, *excluded], step_ms)
            covered = merge_ranges([*covered, *empty_prefixes])
            unresolved = missing_ranges(response_start, end_ms, [*covered, *excluded])
            events = [MarketStateEvent(
                key=key, event_time_ms=row["event_time_ms"], received_at_ms=row["received_at_ms"],
                source=row["source"], sequence=row["event_time_ms"],
                data={"open_interest": row["open_interest"], "is_final": bool(row["is_final"]),
                      "sample_kind": "final" if row["is_final"] else "provisional",
                      **({"open_interest_value": row["open_interest_value"]} if row["open_interest_value"] is not None else {})},
            ) for row in rows]
            earlier = response_start > start_ms
            return MarketHistoryPage(
                events=events, fallback=failed and bool(events),
                complete=not unresolved and not earlier and not failed,
                retryable=(bool(unresolved) or failed) and mode != "local_only",
                covered_ranges=tuple(covered), missing_ranges=tuple(unresolved),
                excluded_ranges=tuple(excluded), has_more=earlier,
                next_end_ms=response_start - 1 if earlier else None,
                terminal_reason=plan.terminal_reason,
                earliest_available_ms=plan.earliest_available_ms,
                availability_revision=plan.availability_revision, query_mode=mode,
                coverage_basis="native_binance_oi_sample_grid_v2",
                revalidate_after_ms=revalidate_after_ms,
            )

    async def _hybrid_funding_history_page(
        self,
        key: MarketStreamKey,
        *,
        period: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
        refresh_plan: _HistoryRefreshPlan,
    ) -> MarketHistoryPage:
        """Serve Hybrid Funding through its single cache/fetch owner."""
        if not refresh_plan.should_fetch:
            hybrid = await self._build_hybrid_funding_history(
                key,
                period=period,
                start_ms=start_ms,
                end_ms=end_ms,
                limit=limit,
                fetch_missing=False,
            )
            return MarketHistoryPage(
                events=hybrid.events,
                complete=hybrid.complete,
                fallback=hybrid.fallback,
                retryable=hybrid.retryable,
                terminal_reason=refresh_plan.terminal_reason,
                earliest_available_ms=refresh_plan.earliest_available_ms,
                availability_revision=refresh_plan.availability_revision,
                excluded_ranges=(
                    *refresh_plan.excluded_ranges,
                    *hybrid.excluded_ranges,
                ),
            )

        try:
            hybrid = await self._build_hybrid_funding_history(
                key,
                period=period,
                start_ms=start_ms,
                end_ms=end_ms,
                limit=limit,
                fetch_missing=True,
            )
        except ValueError:
            raise
        except Exception:
            logger.warning(
                "Hybrid Funding refresh failed; rebuilding the page from cache",
                exc_info=True,
            )
            cached = await self._build_hybrid_funding_history(
                key,
                period=period,
                start_ms=start_ms,
                end_ms=end_ms,
                limit=limit,
                fetch_missing=False,
            )
            return MarketHistoryPage(
                events=cached.events,
                complete=False,
                fallback=True,
                retryable=True,
                excluded_ranges=(
                    *refresh_plan.excluded_ranges,
                    *cached.excluded_ranges,
                ),
            )

        return MarketHistoryPage(
            events=hybrid.events,
            complete=hybrid.complete,
            fallback=hybrid.fallback,
            retryable=hybrid.retryable,
            excluded_ranges=(
                *refresh_plan.excluded_ranges,
                *hybrid.excluded_ranges,
            ),
        )

    def _history_refresh_plan(
        self,
        key: MarketStreamKey,
        *,
        period: str | None,
        start_ms: int | None,
        end_ms: int | None,
    ) -> _HistoryRefreshPlan:
        """Limit upstream refreshes to the exchange-declared retention window.

        The caller's original range is still used for the SQLite read.  This
        plan controls only the range sent to the exchange, so already-persisted
        history remains queryable after it falls out of upstream retention.
        """

        capabilities = get_exchange_registry().get_plugin(key.exchange).capabilities()
        capability = capabilities.channel_capability(key.channel, key.market_type)
        if key.channel == MarketChannel.OPEN_INTEREST and period is not None:
            params = getattr(capability, "params", {}) if capability is not None else {}
            supported_periods = params.get("period", ())
            # Native adapters publish an exact period allowlist and stay
            # fail-closed. Unified CCXT venues often expose OI history
            # without discoverable timeframe metadata; pass those periods
            # through to CCXT and let the venue validate them.
            if supported_periods and period not in supported_periods:
                raise ValueError(f"unsupported open-interest period: {period}")

        current_ms = int(time.time() * 1000)
        latest_expected_ms = self._latest_expected_history_ms(
            capability,
            period=period,
            current_ms=current_ms,
        )
        future_exclusions: tuple[dict[str, Any], ...] = ()
        refresh_request_end_ms = end_ms
        if start_ms is not None and start_ms > latest_expected_ms:
            excluded_end_ms = end_ms if end_ms is not None else start_ms
            return _HistoryRefreshPlan(
                start_ms=None,
                end_ms=None,
                should_fetch=False,
                event_cutoff_ms=latest_expected_ms,
                excluded_ranges=(self._future_history_exclusion(
                    start_ms,
                    excluded_end_ms,
                ),),
            )
        if end_ms is not None and end_ms > latest_expected_ms:
            refresh_request_end_ms = latest_expected_ms
            future_exclusions = (self._future_history_exclusion(
                latest_expected_ms + 1,
                end_ms,
            ),)

        if self._history_policy is not None:
            series = self._history_policy.series_key(
                exchange=key.exchange,
                market_type=key.market_type,
                symbol=key.symbol,
                channel=key.channel,
                variant=period or "",
                params=dict(key.params),
            )
            context = self._history_policy.resolve(series)
            availability = context.availability
            policy = context.policy
            lower_bounds = [
                bound
                for bound in (availability.data_start, availability.upstream_start)
                if bound is not None and bound.confirmed and not bound.retryable
            ]
            if availability.rolling_retention_ms is not None:
                retention_start_ms = (
                    current_ms
                    - availability.rolling_retention_ms
                    + _HISTORY_RETENTION_SAFETY_MS
                )
                if period:
                    period_ms = parse_interval_ms(period)
                    if period_ms is None:
                        raise ValueError(f"unsupported history period: {period}")
                    retention_start_ms = (
                        (retention_start_ms + period_ms - 1) // period_ms
                    ) * period_ms
                lower_bounds.append(TimeBound(
                    retention_start_ms,
                    BoundaryReason.PROVIDER_RETENTION,
                    revision=context.revision,
                    dynamic=True,
                ))
            upper_bounds = [
                bound
                for bound in (availability.data_end, availability.upstream_end)
                if bound is not None and bound.confirmed and not bound.retryable
            ]
            lower = max(lower_bounds, key=lambda item: item.value_ms, default=None)
            upper = min(upper_bounds, key=lambda item: item.value_ms, default=None)
            max_page_size = policy.max_page_size if policy is not None else None

            if (
                refresh_request_end_ms is not None
                and lower is not None
                and refresh_request_end_ms < lower.value_ms
            ):
                return _HistoryRefreshPlan(
                    start_ms=None,
                    end_ms=None,
                    should_fetch=False,
                    terminal_reason=lower.reason.value,
                    earliest_available_ms=lower.value_ms,
                    availability_revision=context.revision,
                    max_page_size=max_page_size,
                    event_cutoff_ms=(
                        latest_expected_ms if future_exclusions else None
                    ),
                    excluded_ranges=future_exclusions,
                )
            if start_ms is not None and upper is not None and start_ms > upper.value_ms:
                return _HistoryRefreshPlan(
                    start_ms=None,
                    end_ms=None,
                    should_fetch=False,
                    terminal_reason=upper.reason.value,
                    earliest_available_ms=lower.value_ms if lower is not None else None,
                    availability_revision=context.revision,
                    max_page_size=max_page_size,
                    event_cutoff_ms=(
                        latest_expected_ms if future_exclusions else None
                    ),
                    excluded_ranges=future_exclusions,
                )

            refresh_start_ms = (
                max(start_ms, lower.value_ms)
                if start_ms is not None and lower is not None
                else start_ms
            )
            refresh_end_ms = (
                min(refresh_request_end_ms, upper.value_ms)
                if refresh_request_end_ms is not None and upper is not None
                else refresh_request_end_ms
            )
            if (
                policy is not None
                and policy.max_window_ms is not None
                and refresh_end_ms is not None
            ):
                window_start = refresh_end_ms - policy.max_window_ms
                refresh_start_ms = (
                    window_start
                    if refresh_start_ms is None
                    else max(refresh_start_ms, window_start)
                )
            return _HistoryRefreshPlan(
                start_ms=refresh_start_ms,
                end_ms=refresh_end_ms,
                earliest_available_ms=lower.value_ms if lower is not None else None,
                availability_revision=context.revision,
                max_page_size=max_page_size,
                event_cutoff_ms=(latest_expected_ms if future_exclusions else None),
                excluded_ranges=future_exclusions,
            )

        if start_ms is None and refresh_request_end_ms is None:
            return _HistoryRefreshPlan(start_ms=None, end_ms=None)

        limits = getattr(capability, "limits", {}) if capability is not None else {}
        raw_max_age_ms = limits.get("history.max_age_ms")
        if type(raw_max_age_ms) is not int or raw_max_age_ms <= 0:
            return _HistoryRefreshPlan(
                start_ms=start_ms,
                end_ms=refresh_request_end_ms,
                event_cutoff_ms=(latest_expected_ms if future_exclusions else None),
                excluded_ranges=future_exclusions,
            )

        retention_start_ms = current_ms - raw_max_age_ms
        if period:
            period_ms = parse_interval_ms(period)
            if period_ms is None:
                raise ValueError(f"unsupported history period: {period}")
            # Move inside retention before aligning to a complete period.  A
            # boundary sample can expire while the HTTP request is in flight,
            # especially when local and exchange clocks differ slightly.
            retention_start_ms += _HISTORY_RETENTION_SAFETY_MS
            retention_start_ms = (
                (retention_start_ms + period_ms - 1) // period_ms
            ) * period_ms

        if (
            refresh_request_end_ms is not None
            and refresh_request_end_ms < retention_start_ms
        ):
            return _HistoryRefreshPlan(
                start_ms=None,
                end_ms=None,
                should_fetch=False,
                terminal_reason="outside_upstream_retention",
                earliest_available_ms=retention_start_ms,
                availability_revision=f"rolling:{raw_max_age_ms}",
                event_cutoff_ms=(latest_expected_ms if future_exclusions else None),
                excluded_ranges=future_exclusions,
            )

        refresh_start_ms = (
            None
            if start_ms is None
            else max(start_ms, retention_start_ms)
        )
        return _HistoryRefreshPlan(
            start_ms=refresh_start_ms,
            end_ms=refresh_request_end_ms,
            earliest_available_ms=retention_start_ms,
            availability_revision=f"rolling:{raw_max_age_ms}",
            event_cutoff_ms=(latest_expected_ms if future_exclusions else None),
            excluded_ranges=future_exclusions,
        )

    @staticmethod
    def _latest_expected_history_ms(
        capability: Any,
        *,
        period: str | None,
        current_ms: int,
    ) -> int:
        policy = getattr(capability, "history_policy", None)
        if getattr(getattr(capability, "channel", None), "value", None) == "open_interest":
            return current_ms
        cadence = getattr(getattr(policy, "cadence", None), "value", None)
        if cadence == "regular" and period:
            period_ms = parse_interval_ms(period)
            if period_ms is None:
                raise ValueError(f"unsupported history period: {period}")
            return (current_ms // period_ms) * period_ms
        return current_ms

    @staticmethod
    def _future_history_exclusion(start_ms: int, end_ms: int) -> dict[str, Any]:
        return {
            "start_ms": int(start_ms),
            "end_ms": int(end_ms),
            "disposition": "not_expected",
            "reason": "future",
        }

    @staticmethod
    def _apply_history_event_cutoff(
        events: list[MarketStateEvent],
        plan: _HistoryRefreshPlan,
    ) -> list[MarketStateEvent]:
        if plan.event_cutoff_ms is None:
            return events
        return [
            event
            for event in events
            if event.event_time_ms <= plan.event_cutoff_ms
        ]

    async def _read_persisted_history(
        self,
        key: MarketStreamKey,
        *,
        period: str | None,
        limit: int,
        start_ms: int | None,
        end_ms: int | None,
    ) -> list[MarketStateEvent]:
        repository = self._metrics_repository
        if repository is None:
            return []
        common = {
            "exchange": key.exchange,
            "market_type": key.market_type,
            "symbol": key.symbol,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "limit": limit,
        }
        if key.channel == MarketChannel.FUNDING_RATE:
            rows = await run_storage(
                repository.query_funding,
                oldest_first=True,
                **common,
            )
            return self._funding_history_events(key, rows, now_ms=int(time.time() * 1000))

        if key.channel == MarketChannel.OPEN_INTEREST:
            if not period:
                raise ValueError("open-interest history requires period")
            rows = await run_storage(
                repository.query_open_interest,
                period=period,
                **common,
            )
            events = []
            for row in rows:
                is_final = bool(row["is_final"])
                data = {
                    "open_interest": row["open_interest"],
                    "is_final": is_final,
                    "sample_kind": "final" if is_final else "provisional",
                }
                if row.get("open_interest_value") is not None:
                    data["open_interest_value"] = row["open_interest_value"]
                events.append(
                    MarketStateEvent(
                        key=key,
                        event_time_ms=row["event_time_ms"],
                        received_at_ms=row["received_at_ms"],
                        source=row["source"],
                        data=data,
                        sequence=row["event_time_ms"],
                    ),
                )
            return events
        return []

    @staticmethod
    def _funding_history_events(
        key: MarketStreamKey, rows: list[dict[str, Any]], *, now_ms: int,
    ) -> list[MarketStateEvent]:
        events: list[MarketStateEvent] = []
        for row in rows:
            is_final = bool(row["is_final"])
            cycle_ms = int(row["funding_cycle_ms"])
            raw_time_ms = int(row["funding_time_ms"])
            data: dict[str, Any] = {
                "funding_rate": row["funding_rate"],
                "funding_cycle_ms": cycle_ms,
                "raw_funding_time_ms": raw_time_ms,
                "is_final": is_final,
                "sample_kind": "settlement" if is_final else "preview",
                "provenance": (
                    "exchange_settlement" if is_final else "exchange_realtime"
                ),
            }
            if is_final:
                data["funding_time_ms"] = raw_time_ms
                data["quality"] = "final"
            else:
                stale_after_ms = int(row["received_at_ms"]) + _REALTIME_FUNDING_STALE_MS
                stale = now_ms > stale_after_ms or now_ms >= cycle_ms
                data.update({
                    "next_funding_time_ms": cycle_ms,
                    "observed_at_ms": int(row["received_at_ms"]),
                    "valid_until_ms": cycle_ms,
                    "stale_after_ms": stale_after_ms,
                    "carried": False,
                    "stale": stale,
                    "quality": "stale" if stale else "live",
                })
            events.append(
                MarketStateEvent(
                    key=key,
                    event_time_ms=raw_time_ms,
                    received_at_ms=row["received_at_ms"],
                    source=row["source"],
                    data=data,
                    sequence=raw_time_ms,
                ),
            )
        return events

    async def _persist_final_history(
        self,
        events: list[MarketStateEvent],
        *,
        period: str | None,
    ) -> None:
        repository = self._metrics_repository
        if repository is None or not events:
            return
        channel = events[0].key.channel
        if channel == MarketChannel.FUNDING_RATE:
            rows = [self._funding_storage_row(event, is_final=True) for event in events]
            if self._metrics_writer is not None:
                await self._metrics_writer.write_funding(rows)
            else:
                await run_storage(repository.upsert_funding, rows)
            return
        if channel == MarketChannel.OPEN_INTEREST:
            if not period:
                raise ValueError("open-interest history requires period")
            rows = [
                self._open_interest_storage_row(
                    event,
                    period=period,
                    is_final=True,
                )
                for event in events
            ]
            if self._metrics_writer is not None:
                await self._metrics_writer.write_open_interest(rows)
            else:
                await run_storage(repository.upsert_open_interest, rows)

    async def _build_hybrid_funding_history(
        self,
        key: MarketStreamKey,
        *,
        period: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
        fetch_missing: bool,
    ) -> _HybridFundingResult:
        repository = self._metrics_repository
        period_ms = parse_interval_ms(period)
        if repository is None or period_ms is None or period_ms <= 0:
            return _HybridFundingResult(events=[], complete=True)

        now_ms = int(time.time() * 1000)
        last_closed_ms = last_closed_bar_open_ms(now_ms, period)
        if last_closed_ms is None:
            return _HybridFundingResult(events=[], complete=True)

        requested_last_ms = (
            last_closed_ms
            if end_ms is None
            else compute_bucket_start_ms(end_ms, period_ms, interval=period)
        )
        last_bucket_ms = min(last_closed_ms, requested_last_ms)
        if start_ms is None:
            first_bucket_ms = last_bucket_ms
            for _ in range(max(0, int(limit) - 1)):
                previous = compute_bucket_start_ms(
                    first_bucket_ms - 1,
                    period_ms,
                    interval=period,
                )
                if previous >= first_bucket_ms or previous < 0:
                    break
                first_bucket_ms = previous
        else:
            first_bucket_ms = compute_bucket_start_ms(
                start_ms,
                period_ms,
                interval=period,
            )
            if first_bucket_ms < start_ms:
                first_bucket_ms = compute_bucket_end_ms(
                    first_bucket_ms,
                    period_ms,
                    interval=period,
                )
        if first_bucket_ms > last_bucket_ms:
            return _HybridFundingResult(events=[], complete=True)

        bucket_starts: list[int] = []
        cursor_ms = first_bucket_ms
        page_limit = max(1, min(int(limit), 1000))
        while cursor_ms <= last_bucket_ms and len(bucket_starts) <= page_limit:
            bucket_starts.append(cursor_ms)
            next_cursor_ms = compute_bucket_end_ms(
                cursor_ms,
                period_ms,
                interval=period,
            )
            if next_cursor_ms <= cursor_ms:
                break
            cursor_ms = next_cursor_ms
        complete = len(bucket_starts) <= page_limit and cursor_ms > last_bucket_ms
        bucket_starts = bucket_starts[:page_limit]
        if not bucket_starts:
            return _HybridFundingResult(events=[], complete=True)

        support_start_ms = max(
            0,
            bucket_starts[0] - _FUNDING_CONTEXT_LOOKBACK_MS,
        )
        desired_support_end_ms = compute_bucket_end_ms(
            bucket_starts[-1],
            period_ms,
            interval=period,
        ) - 1
        support_end_ms = desired_support_end_ms
        excluded_ranges: list[dict[str, Any]] = []
        maximum_support_end_ms = (
            support_start_ms
            + _MAX_PREMIUM_ESTIMATE_POINTS * _PREMIUM_INDEX_INTERVAL_MS
            - 1
        )
        premium_capacity_truncated = support_end_ms > maximum_support_end_ms
        if premium_capacity_truncated:
            support_end_ms = maximum_support_end_ms

        settlement_refresh_failed = False
        settlement_refresh_complete = True
        settlement_covered_through_ms = desired_support_end_ms
        if fetch_missing:
            try:
                (
                    settlement_refresh_complete,
                    settlement_covered_through_ms,
                ) = await self._fetch_funding_settlement_pages(
                    key,
                    start_ms=max(0, support_start_ms - _FUNDING_CONTEXT_LOOKBACK_MS),
                    end_ms=min(now_ms, desired_support_end_ms),
                )
            except Exception:
                settlement_refresh_failed = True
                settlement_refresh_complete = False
                settlement_covered_through_ms = bucket_starts[0] - 1
                logger.warning(
                    "Funding settlement pagination failed for %s",
                    key.topic,
                    exc_info=True,
                )

        funding_query_start_ms = max(
            0,
            support_start_ms - _FUNDING_CONTEXT_LOOKBACK_MS,
        )
        funding_query_end_ms = desired_support_end_ms + _FUNDING_CONTEXT_LOOKBACK_MS
        funding_query_limit = min(
            100_000,
            max(
                1000,
                (funding_query_end_ms - funding_query_start_ms) // (60 * 60 * 1000)
                + 100,
            ),
        )
        funding_query = {
            "exchange": key.exchange,
            "market_type": key.market_type,
            "symbol": key.symbol,
            "start_ms": funding_query_start_ms,
            "end_ms": funding_query_end_ms,
            "limit": funding_query_limit,
        }
        if (
            fetch_missing and not settlement_refresh_failed
            and settlement_covered_through_ms >= funding_query_start_ms
        ):
            funding_rows, coverage = await run_storage(
                repository.read_funding_with_settlement_coverage,
                **funding_query,
                coverage_end_ms=settlement_covered_through_ms,
                policy_revision=_FUNDING_SETTLEMENT_POLICY_REVISION,
                now_ms=self._funding_refresh_wall_ms(),
            )
            if missing_ranges(funding_query_start_ms, settlement_covered_through_ms, coverage):
                settlement_refresh_failed = True
                settlement_refresh_complete = False
        else:
            funding_rows = await run_storage(
                repository.query_funding, **funding_query, oldest_first=True, use_cycle_range=True,
            )
        final_rows = sorted(
            (row for row in funding_rows if bool(row["is_final"])),
            key=lambda row: int(row["funding_cycle_ms"]),
        )
        final_cycles = [int(row["funding_cycle_ms"]) for row in final_rows]

        capacity_truncated = False
        if not settlement_refresh_complete and not settlement_refresh_failed:
            settlement_capacity_buckets = [
                bucket_ms
                for bucket_ms in bucket_starts
                if compute_bucket_end_ms(
                    bucket_ms,
                    period_ms,
                    interval=period,
                ) - 1 <= settlement_covered_through_ms
            ]
            if len(settlement_capacity_buckets) < len(bucket_starts):
                bucket_starts = settlement_capacity_buckets
                capacity_truncated = True
                complete = False
                if not bucket_starts:
                    return _HybridFundingResult(
                        events=[],
                        complete=False,
                        retryable=False,
                        excluded_ranges=tuple(excluded_ranges),
                    )

        settlement_by_bucket: dict[int, tuple[dict[str, Any], int]] = {}
        requested_bucket_set = set(bucket_starts)
        for row in final_rows:
            cycle_ms = int(row["funding_cycle_ms"])
            bucket_ms = compute_bucket_start_ms(
                cycle_ms,
                period_ms,
                interval=period,
            )
            if bucket_ms not in requested_bucket_set:
                continue
            previous = settlement_by_bucket.get(bucket_ms)
            count = 1 if previous is None else previous[1] + 1
            settlement_by_bucket[bucket_ms] = (row, count)

        needs_estimates = len(settlement_by_bucket) < len(bucket_starts)
        premium_rows: list[dict[str, Any]] = []
        premium_continuous_through_ms: int | None = None
        if needs_estimates:
            if premium_capacity_truncated:
                capacity_truncated = True
                complete = False
                excluded_ranges.append({
                    "start_ms": support_end_ms + 1,
                    "end_ms": desired_support_end_ms,
                    "disposition": "deferred",
                    "reason": "premium_index_capacity_page",
                })
            (
                premium_rows,
                premium_missing_ranges,
                premium_fetch_failed,
                premium_budget_exhausted,
            ) = await self._ensure_premium_index_history(
                key,
                start_ms=support_start_ms,
                end_ms=support_end_ms,
                fetch_missing=fetch_missing,
            )
            relevant_missing_ranges = [
                (max(missing_start, bucket_starts[0]), min(missing_end, support_end_ms))
                for missing_start, missing_end in premium_missing_ranges
                if missing_end >= bucket_starts[0] and missing_start <= support_end_ms
            ]
            if relevant_missing_ranges:
                # Premium Index is a fixed 1m input stream. A later row cannot
                # repair an earlier hole, even when both land inside the same
                # multi-minute chart bucket. Consume and emit only the prefix
                # strictly before the first relevant missing minute.
                premium_continuous_through_ms = (
                    min(start for start, _end in relevant_missing_ranges) - 1
                )
            excluded_ranges.extend({
                "start_ms": missing_start,
                "end_ms": missing_end,
                "disposition": "estimated_data_unavailable",
                "reason": "premium_index_unavailable",
            } for missing_start, missing_end in relevant_missing_ranges)
        else:
            relevant_missing_ranges = []
            premium_fetch_failed = False
            premium_budget_exhausted = False

        # The repository contract is unique ascending 1m rows. Keep one
        # cumulative state per funding cycle and advance it only as chart
        # cutoffs need data; do not materialize one point dictionary per minute.
        running: dict[int, tuple[float, int, int, int]] = {}
        premium_cursor = 0
        latest_global_row: dict[str, Any] | None = None
        events: list[MarketStateEvent] = []
        for bucket_ms in bucket_starts:
            bucket_end_ms = compute_bucket_end_ms(
                bucket_ms,
                period_ms,
                interval=period,
            )
            sample_time_ms = bucket_end_ms - 1
            if (
                premium_continuous_through_ms is not None
                and sample_time_ms > premium_continuous_through_ms
            ):
                break
            settlement = settlement_by_bucket.get(bucket_ms)
            if settlement is not None:
                row, settlement_count = settlement
                cycle_ms = int(row["funding_cycle_ms"])
                raw_time_ms = int(row["funding_time_ms"])
                events.append(MarketStateEvent(
                    key=key,
                    event_time_ms=bucket_ms,
                    received_at_ms=int(row["received_at_ms"]),
                    source=row["source"],
                    data={
                        "funding_rate": float(row["funding_rate"]),
                        "funding_time_ms": raw_time_ms,
                        "raw_funding_time_ms": raw_time_ms,
                        "funding_cycle_ms": cycle_ms,
                        "target_funding_time_ms": cycle_ms,
                        "sample_time_ms": raw_time_ms,
                        "is_final": True,
                        "sample_kind": "settlement",
                        "provenance": "exchange_settlement",
                        "quality": "final",
                        "settlement_count": settlement_count,
                    },
                    sequence=bucket_ms,
                ))
                continue

            while premium_cursor < len(premium_rows):
                premium_row = premium_rows[premium_cursor]
                close_time_ms = int(premium_row["close_time_ms"])
                if (
                    close_time_ms > sample_time_ms
                    or close_time_ms > support_end_ms
                    or (
                        premium_continuous_through_ms is not None
                        and close_time_ms > premium_continuous_through_ms
                    )
                ):
                    break
                premium_cursor += 1
                latest_global_row = premium_row
                row_target_cycle_ms, row_funding_interval_ms = (
                    _funding_cycle_context_ms(
                        close_time_ms,
                        final_cycles=final_cycles,
                    )
                )
                row_cycle_start_ms = max(
                    0,
                    row_target_cycle_ms - row_funding_interval_ms,
                )
                if close_time_ms < row_cycle_start_ms:
                    continue
                premium_sum, sample_count, _last_time_ms, _received_at_ms = running.get(
                    row_target_cycle_ms,
                    (0.0, 0, 0, 0),
                )
                running[row_target_cycle_ms] = (
                    premium_sum + float(premium_row["premium_close"]),
                    sample_count + 1,
                    close_time_ms,
                    int(premium_row["received_at_ms"]),
                )

            target_cycle_ms, funding_interval_ms = _funding_cycle_context_ms(
                sample_time_ms,
                final_cycles=final_cycles,
            )
            cycle_state = running.get(target_cycle_ms)
            input_carried = False
            if cycle_state is not None:
                premium_sum, sample_count, point_time_ms, received_at_ms = cycle_state
                carry_age_ms = sample_time_ms - point_time_ms
                if carry_age_ms >= _PREMIUM_INDEX_INTERVAL_MS:
                    break
                cycle_start_ms = max(0, target_cycle_ms - funding_interval_ms)
                premium_average = premium_sum / sample_count
                expected_count = max(
                    1,
                    (
                        point_time_ms
                        - cycle_start_ms
                        + _PREMIUM_INDEX_INTERVAL_MS
                    ) // _PREMIUM_INDEX_INTERVAL_MS,
                )
                point = {
                    "time_ms": point_time_ms,
                    "funding_rate": _estimated_funding_rate(
                        premium_average,
                        funding_interval_ms=funding_interval_ms,
                    ),
                    "premium_average": premium_average,
                    "sample_count": sample_count,
                    "expected_count": expected_count,
                    "coverage": min(1.0, sample_count / expected_count),
                    "received_at_ms": received_at_ms,
                }
                input_carried = carry_age_ms > 0
            else:
                if period_ms >= _PREMIUM_INDEX_INTERVAL_MS:
                    break
                if latest_global_row is None:
                    break
                proxy_row = latest_global_row
                proxy_time_ms = int(proxy_row["close_time_ms"])
                proxy_age_ms = sample_time_ms - proxy_time_ms
                if proxy_age_ms < 0 or proxy_age_ms >= _PREMIUM_INDEX_INTERVAL_MS:
                    break
                cycle_start_ms = max(0, target_cycle_ms - funding_interval_ms)
                premium_average = float(proxy_row["premium_close"])
                point = {
                    "time_ms": proxy_time_ms,
                    "funding_rate": _estimated_funding_rate(
                        premium_average,
                        funding_interval_ms=target_cycle_ms - cycle_start_ms,
                    ),
                    "premium_average": premium_average,
                    "sample_count": 0,
                    "expected_count": 1,
                    "coverage": 0.0,
                    "received_at_ms": int(proxy_row["received_at_ms"]),
                    "input_proxy": True,
                }
                input_carried = True
            events.append(MarketStateEvent(
                key=key,
                event_time_ms=bucket_ms,
                received_at_ms=int(point["received_at_ms"]),
                source=DataSource.HTTP_BACKFILL,
                data={
                    "funding_rate": float(point["funding_rate"]),
                    "sample_time_ms": sample_time_ms,
                    "target_funding_time_ms": target_cycle_ms,
                    "funding_cycle_ms": target_cycle_ms,
                    "is_final": False,
                    "sample_kind": "estimate",
                    "provenance": "derived_history",
                    "quality": "estimated",
                    "formula_version": _FUNDING_FORMULA_VERSION,
                    "input_resolution": _PREMIUM_INDEX_INTERVAL,
                    "input_samples": int(point["sample_count"]),
                    "expected_input_samples": int(point["expected_count"]),
                    "input_coverage": round(float(point["coverage"]), 6),
                    "input_carried": input_carried,
                    "input_proxy": bool(point.get("input_proxy", False)),
                    "premium_index_average": float(point["premium_average"]),
                },
                sequence=bucket_ms,
            ))

        returned_bucket_starts = {event.event_time_ms for event in events}
        missing_bucket_starts = [
            bucket_ms
            for bucket_ms in bucket_starts
            if bucket_ms not in returned_bucket_starts
        ]
        excluded_ranges.extend(
            _missing_bucket_exclusions(
                missing_bucket_starts,
                period_ms=period_ms,
                period=period,
            ),
        )
        retryable = bool(
            settlement_refresh_failed
            or premium_fetch_failed
        )
        return _HybridFundingResult(
            events=events,
            complete=(
                complete
                and not retryable
                and not capacity_truncated
                and not premium_budget_exhausted
                and not missing_bucket_starts
            ),
            retryable=retryable,
            fallback=settlement_refresh_failed,
            excluded_ranges=tuple(excluded_ranges),
        )

    async def _ensure_premium_index_history(
        self,
        key: MarketStreamKey,
        *,
        start_ms: int,
        end_ms: int,
        fetch_missing: bool,
    ) -> tuple[
        list[dict[str, Any]],
        list[tuple[int, int]],
        bool,
        bool,
    ]:
        repository = self._metrics_repository
        if repository is None or end_ms < start_ms:
            return [], [], False, False
        aligned_start_ms = (
            start_ms // _PREMIUM_INDEX_INTERVAL_MS
        ) * _PREMIUM_INDEX_INTERVAL_MS
        aligned_end_ms = (
            ((end_ms + 1) // _PREMIUM_INDEX_INTERVAL_MS) - 1
        ) * _PREMIUM_INDEX_INTERVAL_MS
        if aligned_end_ms < aligned_start_ms:
            return [], [], False, False
        common = {
            "exchange": key.exchange,
            "market_type": key.market_type,
            "symbol": key.symbol,
            "interval": _PREMIUM_INDEX_INTERVAL,
            "start_ms": aligned_start_ms,
            "end_ms": aligned_end_ms,
            "limit": _MAX_PREMIUM_ESTIMATE_POINTS,
        }
        query_premium = getattr(
            repository,
            "query_premium_index_compact",
            repository.query_premium_index,
        )
        rows = await run_storage(query_premium, **common)
        missing = _missing_minute_ranges(
            [int(row["open_time_ms"]) for row in rows],
            start_ms=aligned_start_ms,
            end_ms=aligned_end_ms,
        )
        fetch_failed = False
        budget_exhausted = False
        if fetch_missing and missing:
            # Release the potentially large first materialization before the
            # post-refresh query. A complete hot-cache hit returns it directly.
            rows = []
            try:
                (
                    _pages_used,
                    budget_exhausted,
                    fetch_failed,
                ) = await self._fetch_premium_index_pages(
                    key,
                    ranges=missing,
                )
            except Exception:
                fetch_failed = True
                logger.warning(
                    "Premium-index history refresh failed for %s",
                    key.topic,
                    exc_info=True,
                )
            rows = await run_storage(query_premium, **common)
            missing = _missing_minute_ranges(
                [int(row["open_time_ms"]) for row in rows],
                start_ms=aligned_start_ms,
                end_ms=aligned_end_ms,
            )
        return rows, missing, fetch_failed, budget_exhausted

    async def _fetch_premium_index_pages(
        self,
        key: MarketStreamKey,
        *,
        ranges: list[tuple[int, int]],
        max_pages: int = _MAX_PREMIUM_HISTORY_PAGES_PER_REQUEST,
        max_concurrency: int = _PREMIUM_FETCH_CONCURRENCY,
    ) -> tuple[int, bool, bool]:
        repository = self._metrics_repository
        if repository is None:
            return 0, False, False
        descriptor = StreamDescriptor(
            symbol=key.symbol,
            stream_type=StreamType.PREMIUM_INDEX,
            interval=_PREMIUM_INDEX_INTERVAL,
            exchange=key.exchange,
            market_type=key.market_type,
        )
        page_ranges, budget_exhausted = _premium_index_page_ranges(
            ranges,
            max_pages=max_pages,
        )
        pages_used = 0
        fetch_failed = False
        concurrency = max(1, min(int(max_concurrency), len(page_ranges) or 1))

        async def fetch_page(page_start_ms: int, page_end_ms: int) -> list[dict[str, Any]]:
            page_points = (
                (page_end_ms - page_start_ms) // _PREMIUM_INDEX_INTERVAL_MS
            ) + 1
            raw_events = await self._fetch_market(
                descriptor,
                limit=min(_PREMIUM_HISTORY_PAGE_POINTS, page_points),
                start_ms=page_start_ms,
                end_ms=page_end_ms,
                history=True,
            )
            return [
                row
                for event in raw_events
                if event.event_type == StreamType.PREMIUM_INDEX
                and page_start_ms
                <= int(event.data.get("open_time_ms", -1))
                <= page_end_ms
                for row in (self._premium_index_storage_row(event),)
            ]

        for offset in range(0, len(page_ranges), concurrency):
            wave = page_ranges[offset:offset + concurrency]
            results = await asyncio.gather(
                *(fetch_page(page_start, page_end) for page_start, page_end in wave),
                return_exceptions=True,
            )
            pages_used += len(wave)
            batch: list[dict[str, Any]] = []
            for (page_start, page_end), result in zip(wave, results):
                if isinstance(result, BaseException):
                    fetch_failed = True
                    logger.warning(
                        "Premium-index page failed for %s [%s, %s]",
                        key.topic,
                        page_start,
                        page_end,
                        exc_info=(type(result), result, result.__traceback__),
                    )
                    continue
                batch.extend(result)
            if batch:
                await run_storage(repository.upsert_premium_index, batch)
            if fetch_failed:
                break

        return pages_used, budget_exhausted, fetch_failed

    async def _fetch_funding_settlement_pages(
        self,
        key: MarketStreamKey,
        *,
        start_ms: int,
        end_ms: int,
        max_pages: int = _MAX_UPSTREAM_HISTORY_PAGES_PER_REQUEST,
        refresh: bool = False,
    ) -> tuple[bool, int]:
        if self._metrics_repository is None or end_ms < start_ms:
            return True, end_ms
        self._ensure_open()
        identity = (key.exchange, key.market_type, key.symbol)
        page_limit = min(_MAX_UPSTREAM_HISTORY_PAGES_PER_REQUEST, max(1, int(max_pages)))
        joined = next(
            ((candidate_key, candidate)
             for candidate_key, candidate in self._funding_refresh_tasks.items()
             if not candidate.done() and candidate_key[0] == identity
             and candidate_key[1] <= start_ms and candidate_key[2] >= end_ms
             and candidate_key[3:] == (page_limit, refresh)),
            None,
        )
        if joined is None:
            if len(self._funding_refresh_jobs) >= 32:
                return False, start_ms - 1
            task_key = (identity, start_ms, end_ms, page_limit, refresh)
            task = asyncio.create_task(
                self._run_funding_settlement_acquisition(
                    key, identity, start_ms, end_ms, max_pages=page_limit, refresh=refresh,
                ), name=f"funding-settlement-refresh:{key.topic}",
            )
            self._funding_refresh_tasks[task_key] = task
            self._funding_refresh_jobs.add(task)
            task.add_done_callback(
                lambda completed, cache_key=task_key: self._discard_funding_refresh_task(cache_key, completed),
            )
        else:
            task_key, task = joined
        self._funding_refresh_waiters[task] = self._funding_refresh_waiters.get(task, 0) + 1
        try:
            refreshed_through = await asyncio.shield(task)
        finally:
            remaining = self._funding_refresh_waiters[task] - 1
            if remaining:
                self._funding_refresh_waiters[task] = remaining
            else:
                self._funding_refresh_waiters.pop(task)
                if not task.done():
                    task.cancel()
                    # Unlink before draining, so a new request never joins a
                    # cancelled owner. The identity lock remains held until
                    # any physical storage write in that owner drains.
                    if self._funding_refresh_tasks.get(task_key) is task:
                        self._funding_refresh_tasks.pop(task_key)
                    async def drain():
                        await asyncio.gather(task, return_exceptions=True)
                    if await drain_cancellation_safe_cleanup(drain(), name="funding-settlement-release"):
                        raise asyncio.CancelledError
        remaining_gaps = await self._funding_settlement_gaps(identity, start_ms, end_ms)
        through = remaining_gaps[0]["start_ms"] - 1 if remaining_gaps else end_ms
        if refresh:
            through = min(through, refreshed_through if refreshed_through is not None else start_ms - 1)
        return through >= end_ms, max(start_ms - 1, through)

    async def _run_funding_settlement_acquisition(
        self, key: MarketStreamKey, identity: tuple[str, str, str],
        start_ms: int, end_ms: int, *, max_pages: int, refresh: bool,
    ) -> int | None:
        async with self._history_identity_locks.hold(identity):
            self._ensure_open()
            # Partially overlapping requests wait for the first owner, then
            # plan only the still-unverified part against committed receipts.
            gaps = ([{"start_ms": start_ms, "end_ms": end_ms}] if refresh
                    else await self._funding_settlement_gaps(identity, start_ms, end_ms))
            return await self._fetch_funding_settlement_gaps(key, identity, gaps, max_pages=max_pages)

    async def _funding_settlement_gaps(
        self, identity: tuple[str, str, str], start_ms: int, end_ms: int,
    ) -> list[dict[str, int]]:
        coverage = await run_storage(
            self._metrics_repository.funding_settlement_coverage,
            identity,
            start_ms=start_ms,
            end_ms=end_ms,
            policy_revision=_FUNDING_SETTLEMENT_POLICY_REVISION,
            now_ms=self._funding_refresh_wall_ms(),
        )
        return missing_ranges(start_ms, end_ms, coverage)

    def _discard_funding_refresh_task(
        self,
        task_key: tuple[tuple[str, str, str], int, int, int, bool],
        task: asyncio.Task[int | None],
    ) -> None:
        self._funding_refresh_jobs.discard(task)
        if not task.cancelled():
            task.exception()
        if self._funding_refresh_tasks.get(task_key) is task:
            self._funding_refresh_tasks.pop(task_key, None)

    async def _fetch_funding_settlement_gaps(
        self, key: MarketStreamKey, identity: tuple[str, str, str],
        gaps: list[dict[str, int]], *, max_pages: int,
    ) -> int | None:
        last_committed_end = None
        descriptor = StreamDescriptor(
            symbol=key.symbol,
            stream_type=StreamType.FUNDING_RATE,
            exchange=key.exchange,
            market_type=key.market_type,
        )
        for gap in gaps:
            cursor_ms, end_ms = gap["start_ms"], gap["end_ms"]
            previous_cycle_ms = -1
            while cursor_ms <= end_ms:
                if max_pages <= 0:
                    return last_committed_end
                raw_events = await self._fetch_market(
                    descriptor,
                    limit=1000,
                    start_ms=cursor_ms,
                    end_ms=end_ms,
                    history=True,
                )
                max_pages -= 1
                if len(raw_events) > 1000:
                    raise RuntimeError("Binance funding settlement page exceeds its request limit")
                projected_events = []
                latest_time_ms = cursor_ms - 1
                for event in raw_events:
                    time_ms = event.data.get("funding_time_ms")
                    if (
                        event.event_type != StreamType.FUNDING_RATE
                        or (event.exchange, event.market_type, event.symbol) != identity
                        or type(time_ms) is not int
                        or time_ms != event.event_time_ms
                        or not latest_time_ms < time_ms <= end_ms
                    ):
                        raise RuntimeError("Invalid Binance funding settlement page identity, bounds or order")
                    projected = self._project(event, key)
                    if projected is None or projected.data["funding_cycle_ms"] <= previous_cycle_ms:
                        raise RuntimeError("Unrepresentable Binance funding settlement page")
                    projected_events.append(projected)
                    latest_time_ms = time_ms
                    previous_cycle_ms = projected.data["funding_cycle_ms"]
                # An exhaustive short or empty response proves the bounded gap.
                # A full page proves only its prefix through the last settlement.
                covered_end = end_ms if len(raw_events) < 1000 else latest_time_ms
                # The production writer can finish an accepted batch even if
                # its caller is cancelled. Retain the identity owner through
                # both the acknowledged rows and their verified receipt.
                await finish_cleanup(self._commit_funding_settlement_page(
                    identity, cursor_ms, covered_end, projected_events,
                ))
                last_committed_end = covered_end
                cursor_ms = covered_end + 1
        return last_committed_end

    async def _commit_funding_settlement_page(
        self, identity: tuple[str, str, str], start_ms: int, end_ms: int,
        events: list[MarketStateEvent],
    ) -> None:
        await self._persist_final_history(events, period=None)
        now_ms = self._funding_refresh_wall_ms()
        cutoff = now_ms - _DEFAULT_FUNDING_INTERVAL_MS
        rows = [self._funding_storage_row(event, is_final=True) for event in events]
        spans = (
            (start_ms, min(cutoff, end_ms), None),
            (max(start_ms, cutoff + 1), end_ms, now_ms + _FUNDING_SETTLEMENT_EDGE_TTL_MS),
        )
        for first, last, expires_at_ms in spans:
            if last < first:
                continue
            recorded = await run_storage(
                self._metrics_repository.record_funding_settlement_query,
                identity=identity,
                start_ms=first,
                end_ms=last,
                policy_revision=_FUNDING_SETTLEMENT_POLICY_REVISION,
                expected_rows=[row for row in rows if first <= row["funding_time_ms"] <= last],
                observed_at_ms=now_ms,
                expires_at_ms=expires_at_ms,
            )
            if not recorded:
                raise RuntimeError("Committed funding settlements differ from the acquired page")

    @staticmethod
    def _funding_refresh_wall_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _premium_index_storage_row(event: MarketEvent) -> dict[str, Any]:
        return {
            "exchange": event.exchange,
            "market_type": event.market_type,
            "symbol": event.symbol,
            "interval": event.data.get("interval", _PREMIUM_INDEX_INTERVAL),
            "open_time_ms": int(event.data["open_time_ms"]),
            "close_time_ms": int(event.data["close_time_ms"]),
            "premium_open": event.data["premium_index_open"],
            "premium_high": event.data["premium_index_high"],
            "premium_low": event.data["premium_index_low"],
            "premium_close": event.data["premium_index_close"],
            "source": event.source.value,
            "received_at_ms": event.received_at_ms,
        }

    def subscribe(
        self,
        keys: Iterable[MarketStreamKey],
        *,
        max_pending: int = 64,
        replay: bool = True,
        continuity=None,
    ) -> MarketHubSubscription:
        self._ensure_open()
        return self.hub.subscribe(keys, max_pending=max_pending, replay=replay, continuity=continuity)

    async def shutdown(self) -> None:
        async with self._lock:
            if self._shutdown_task is None:
                self._closed = True
                self._logical_leases.clear()
                self._shutdown_task = asyncio.create_task(
                    self._shutdown_impl(),
                    name="market-data-shutdown",
                )
            task = self._shutdown_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Runtime wait_for cancels this waiter at its step deadline. The
            # owned task can still be draining physical SQLite reads; do not
            # let dependent runtime components stop before that drain ends.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            task.result()
            raise

    async def _shutdown_impl(self) -> None:
        async with self._lock:
            physical_ids = tuple(self._physical_entries)

        history_tasks = list(self._history_jobs)
        self._history_tasks.clear()
        for task in history_tasks:
            task.cancel()
        if history_tasks:
            await asyncio.gather(*history_tasks, return_exceptions=True)

        async with self._snapshot_lock:
            snapshot_tasks = list(self._snapshot_tasks.values())
            self._snapshot_tasks.clear()
        for task in snapshot_tasks:
            if not task.done():
                task.cancel()
        if snapshot_tasks:
            await asyncio.gather(*snapshot_tasks, return_exceptions=True)

        funding_refresh_tasks = list(self._funding_refresh_jobs)
        self._funding_refresh_tasks.clear()
        for task in funding_refresh_tasks:
            if not task.done():
                task.cancel()
        if funding_refresh_tasks:
            await asyncio.gather(*funding_refresh_tasks, return_exceptions=True)

        if physical_ids:
            await asyncio.gather(
                *(self._shutdown_physical(item) for item in physical_ids),
                return_exceptions=True,
            )
        async with self._lock:
            self._physical_entries.clear()
        if self._metrics_writer is not None:
            await self._metrics_writer.close()
        await self.hub.close()

    async def _shutdown_physical(
        self,
        physical_id: tuple[str, str, str, str],
    ) -> None:
        async with self._identity_locks.hold(physical_id):
            async with self._lock:
                entry = self._physical_entries.get(physical_id)
                if entry is None:
                    return
                entry.logical_keys.clear()
                if entry.stop_task is None:
                    entry.stop_error = None
                    self._schedule_physical_stop(physical_id, entry)
                stop_task = entry.stop_task
            if stop_task is not None:
                await asyncio.shield(stop_task)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "closed": self._closed,
            "logical_streams": len(self._logical_leases),
            "logical_consumers": sum(
                len(lease.consumers) for lease in self._logical_leases.values()
            ),
            "physical_streams": len(self._physical_entries),
            "history_queries": {
                "inflight": len(self._history_tasks),
                "owned_jobs": len(self._history_jobs),
                "max_inflight": 32,
                "identities": self._history_identity_locks.active_keys,
            },
            "limits": {
                "summary_streams": self._max_summary_streams,
                "open_interest_streams": self._max_open_interest_streams,
            },
            "physical": [
                {
                    "descriptor": entry.descriptor.key,
                    "logical_streams": len(entry.logical_keys),
                    "state": (
                        "stop_failed"
                        if entry.stop_error is not None
                        else "stopping"
                        if entry.stop_task is not None
                        else "running"
                    ),
                    "stop_error": entry.stop_error,
                }
                for entry in self._physical_entries.values()
            ],
            "hub": self.hub.diagnostics(),
            "storage": {
                "enabled": self._metrics_repository is not None,
                "writer": (
                    self._metrics_writer.diagnostics()
                    if self._metrics_writer is not None
                    else None
                ),
            },
            "rate_limits": self._rate_limits.snapshot(),
            **self._metrics,
        }

    async def _refresh_group(
        self,
        physical_id: tuple[str, str, str, str],
        group: list[MarketStreamKey],
    ) -> list[MarketStateEvent]:
        async with self._snapshot_lock:
            self._ensure_open()
            task = self._snapshot_tasks.get(physical_id)
            if task is None:
                task = asyncio.create_task(
                    self._fetch_snapshot_source(group[0]),
                    name=f"market-snapshot-{group[0].symbol}",
                )
                self._snapshot_tasks[physical_id] = task
                task.add_done_callback(
                    lambda completed, key=physical_id: self._discard_snapshot_task(
                        key,
                        completed,
                    ),
                )
        raw_events = await asyncio.shield(task)
        projected: list[MarketStateEvent] = []
        for raw_event in raw_events:
            for key in group:
                event = self._project(raw_event, key)
                if event is not None:
                    projected.append(event)
        return projected

    def _discard_snapshot_task(
        self,
        physical_id: tuple[str, str, str, str],
        task: asyncio.Task,
    ) -> None:
        if not task.cancelled():
            task.exception()
        if self._snapshot_tasks.get(physical_id) is task:
            self._snapshot_tasks.pop(physical_id, None)

    async def _fetch_snapshot_source(self, key: MarketStreamKey) -> list[MarketEvent]:
        return await self._fetch_market(self._physical_descriptor(key), limit=1)

    async def _fetch_market(
        self,
        descriptor: StreamDescriptor,
        *,
        limit: int,
        start_ms: int | None = None,
        end_ms: int | None = None,
        history: bool = False,
    ) -> list[MarketEvent]:
        self._ensure_open()
        plugin = get_exchange_registry().get_plugin(descriptor.exchange)
        request = TransportRequest(
            descriptor=descriptor,
            limit=limit,
            start_ms=start_ms,
            end_ms=end_ms,
            history=history,
        )
        spec = plugin.protocol().rest_request(
            request,
            config=getattr(self._factory, "config", None),
        )
        provider_fetch = getattr(plugin, "fetch_history_with_config", None)
        if spec is None and not callable(provider_fetch):
            raise ValueError(f"No REST endpoint for {descriptor.key}")
        return await self._factory.fetch_market(
            descriptor,
            limit=limit,
            start_ms=start_ms,
            end_ms=end_ms,
            history=history,
        )

    async def _cleanup_start_entry(
        self,
        physical_id: tuple[str, str, str, str],
        entry: _PhysicalEntry,
        key: MarketStreamKey,
        consumer: str,
    ) -> None:
        stop_task: asyncio.Task | None = None
        async with self._lock:
            entry.logical_keys.discard(key)
            lease = self._logical_leases.get(key)
            if lease is not None:
                lease.consumers.discard(consumer)
                if not lease.consumers:
                    self._logical_leases.pop(key, None)

            if entry.handle is None:
                if self._physical_entries.get(physical_id) is entry:
                    self._physical_entries.pop(physical_id, None)
                return
            if entry.stop_task is None:
                self._schedule_physical_stop(physical_id, entry)
            stop_task = entry.stop_task

        if stop_task is not None:
            await asyncio.shield(stop_task)

    def _schedule_physical_stop(
        self,
        physical_id: tuple[str, str, str, str],
        entry: _PhysicalEntry,
        *,
        delay: float = 0.0,
    ) -> asyncio.Task:
        entry.stop_error = None
        task = asyncio.create_task(
            self._stop_physical_after_delay(physical_id, entry, delay),
            name=f"market-stop-{entry.descriptor.key}",
        )
        entry.stop_task = task
        task.add_done_callback(self._consume_background_task_result)
        return task

    async def _stop_physical_after_delay(
        self,
        physical_id: tuple[str, str, str, str],
        entry: _PhysicalEntry,
        delay: float,
    ) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        await self._stop_physical(physical_id, entry)

    @staticmethod
    def _consume_background_task_result(task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()

    async def _stop_physical(
        self,
        physical_id: tuple[str, str, str, str],
        entry: _PhysicalEntry,
    ) -> None:
        error: BaseException | None = None
        try:
            if entry.handle is not None:
                stopped = await entry.handle.stop()
                if stopped is False:
                    raise RuntimeError("ingestion handle reported stop failure")
        except BaseException as exc:
            error = exc

        async with self._lock:
            current = self._physical_entries.get(physical_id)
            if current is entry:
                entry.stop_task = None
                if error is None:
                    self._physical_entries.pop(physical_id, None)
                else:
                    self._metrics["physical_stop_errors"] += 1
                    entry.stop_attempts += 1
                    entry.retry_stop_at = time.monotonic() + min(
                        5.0,
                        0.25 * (2 ** (entry.stop_attempts - 1)),
                    )
                    entry.stop_error = f"{type(error).__name__}: {error}"
                    if not self._closed:
                        self._schedule_physical_stop(
                            physical_id,
                            entry,
                            delay=max(0.0, entry.retry_stop_at - time.monotonic()),
                        )

        if error is not None:
            raise error

    async def _on_ingestion_event(
        self,
        physical_id: tuple[str, str, str, str],
        event: MarketEvent,
    ) -> None:
        # No await is needed to take this event-loop-local snapshot.  Keeping
        # callbacks lock-free also lets a handle stop while a final event is in
        # flight without deadlocking the lifecycle lock.
        entry = self._physical_entries.get(physical_id)
        keys = tuple(entry.logical_keys) if entry is not None else ()
        for key in keys:
            projected = self._project(event, key)
            if projected is not None:
                self.hub.publish(projected)
        self._offer_realtime_provisional(event, keys)

    def _offer_realtime_provisional(
        self,
        event: MarketEvent,
        keys: tuple[MarketStreamKey, ...],
    ) -> None:
        writer = self._metrics_writer
        if writer is None:
            return

        funding_key = next(
            (key for key in keys if key.channel == MarketChannel.FUNDING_RATE),
            None,
        )
        if funding_key is not None and "next_funding_time_ms" in event.data:
            projected = self._project(event, funding_key)
            if projected is not None:
                writer.offer_funding(
                    self._funding_storage_row(projected, is_final=False),
                )

        open_interest_key = next(
            (key for key in keys if key.channel == MarketChannel.OPEN_INTEREST),
            None,
        )
        if open_interest_key is not None:
            projected = self._project(event, open_interest_key)
            if projected is not None:
                bucket_time_ms = (
                    projected.event_time_ms // _DEFAULT_OPEN_INTEREST_STORAGE_BUCKET_MS
                ) * _DEFAULT_OPEN_INTEREST_STORAGE_BUCKET_MS
                writer.offer_open_interest(
                    self._open_interest_storage_row(
                        projected,
                        period=_DEFAULT_OPEN_INTEREST_STORAGE_PERIOD,
                        is_final=False,
                        event_time_ms=bucket_time_ms,
                    ),
                )

    @staticmethod
    def _funding_storage_row(
        event: MarketStateEvent,
        *,
        is_final: bool,
    ) -> dict[str, Any]:
        time_field = "funding_time_ms" if is_final else "next_funding_time_ms"
        funding_time_ms = event.data.get(time_field)
        if funding_time_ms is None:
            funding_time_ms = event.event_time_ms
        funding_cycle_ms = event.data.get("funding_cycle_ms")
        if funding_cycle_ms is None:
            funding_cycle_ms = normalize_funding_cycle_ms(funding_time_ms)
        row: dict[str, Any] = {
            "exchange": event.key.exchange,
            "market_type": event.key.market_type,
            "symbol": event.key.symbol,
            "funding_time_ms": int(funding_time_ms),
            "funding_cycle_ms": int(funding_cycle_ms),
            "funding_rate": event.data["funding_rate"],
            "is_final": is_final,
            "source": event.source.value,
            "received_at_ms": event.received_at_ms,
        }
        return row

    @staticmethod
    def _open_interest_storage_row(
        event: MarketStateEvent,
        *,
        period: str,
        is_final: bool,
        event_time_ms: int | None = None,
    ) -> dict[str, Any]:
        resolved_event_time_ms = (
            event.event_time_ms if event_time_ms is None else event_time_ms
        )
        period_ms = parse_interval_ms(period)
        if not is_final and period_ms is not None and period_ms > 0:
            resolved_event_time_ms = (
                resolved_event_time_ms // period_ms
            ) * period_ms
        row: dict[str, Any] = {
            "exchange": event.key.exchange,
            "market_type": event.key.market_type,
            "symbol": event.key.symbol,
            "period": period,
            "event_time_ms": resolved_event_time_ms,
            "open_interest": event.data["open_interest"],
            "is_final": is_final,
            "source": event.source.value,
            "received_at_ms": event.received_at_ms,
        }
        if event.data.get("open_interest_value") is not None:
            row["open_interest_value"] = event.data["open_interest_value"]
        return row

    @staticmethod
    def _project(event: MarketEvent, key: MarketStreamKey) -> MarketStateEvent | None:
        data = event.data
        projected: dict[str, Any]
        if key.channel == MarketChannel.MARK_PRICE:
            if "mark_price" not in data:
                return None
            projected = {"mark_price": data["mark_price"]}
            if "estimated_settle_price" in data:
                projected["estimated_settle_price"] = data["estimated_settle_price"]
        elif key.channel == MarketChannel.INDEX_PRICE:
            if "index_price" not in data:
                return None
            projected = {"index_price": data["index_price"]}
        elif key.channel == MarketChannel.FUNDING_RATE:
            if "funding_rate" not in data:
                return None
            projected = {"funding_rate": data["funding_rate"]}
            for name in ("next_funding_time_ms", "funding_time_ms", "mark_price"):
                if name in data:
                    projected[name] = data[name]
            if "funding_time_ms" in data:
                raw_time_ms = int(data["funding_time_ms"])
                cycle_ms = normalize_funding_cycle_ms(raw_time_ms)
                projected.update({
                    "funding_time_ms": raw_time_ms,
                    "raw_funding_time_ms": raw_time_ms,
                    "funding_cycle_ms": cycle_ms,
                    "target_funding_time_ms": cycle_ms,
                    "sample_time_ms": raw_time_ms,
                    "is_final": True,
                    "sample_kind": "settlement",
                    "provenance": "exchange_settlement",
                    "quality": "final",
                })
            else:
                raw_target_ms = int(data.get("next_funding_time_ms", event.event_time_ms))
                cycle_ms = normalize_funding_cycle_ms(raw_target_ms)
                projected.update({
                    "next_funding_time_ms": raw_target_ms,
                    "raw_next_funding_time_ms": raw_target_ms,
                    "target_funding_time_ms": cycle_ms,
                    "funding_cycle_ms": cycle_ms,
                    "observed_at_ms": event.received_at_ms,
                    "valid_until_ms": cycle_ms,
                    "stale_after_ms": event.received_at_ms + _REALTIME_FUNDING_STALE_MS,
                    "is_final": False,
                    "sample_kind": "preview",
                    "provenance": "exchange_realtime",
                    "quality": "live",
                    "carried": False,
                    "stale": False,
                })
        elif key.channel == MarketChannel.OPEN_INTEREST:
            if "open_interest" not in data:
                return None
            projected = {"open_interest": data["open_interest"]}
            if "open_interest_value" in data:
                projected["open_interest_value"] = data["open_interest_value"]
        elif key.channel == MarketChannel.BASIS:
            if "mark_price" not in data or "index_price" not in data:
                return None
            mark_price = float(data["mark_price"])
            index_price = float(data["index_price"])
            if index_price == 0:
                return None
            basis = mark_price - index_price
            basis_rate = basis / index_price
            projected = {
                "mark_price": mark_price,
                "index_price": index_price,
                "basis": basis,
                "basis_rate": basis_rate,
                "basis_bps": basis_rate * 10_000,
            }
        else:
            return None

        return MarketStateEvent(
            key=key,
            event_time_ms=event.event_time_ms,
            received_at_ms=event.received_at_ms,
            source=event.source,
            data=projected,
            sequence=event.sequence,
        )

    def _physical_descriptor(self, key: MarketStreamKey) -> StreamDescriptor:
        stream_type = self._physical_stream_type(key)
        if stream_type is StreamType.MARK_PRICE:
            return StreamDescriptor(
                symbol=key.symbol,
                stream_type=StreamType.MARK_PRICE,
                exchange=key.exchange,
                market_type=key.market_type,
            )
        default_poll_seconds = (
            self._open_interest_poll_seconds
            if stream_type is StreamType.OPEN_INTEREST
            else 5.0
        )
        return StreamDescriptor(
            symbol=key.symbol,
            stream_type=stream_type,
            exchange=key.exchange,
            market_type=key.market_type,
            poll_interval_seconds=self._rest_poll_interval_seconds(
                key,
                default_seconds=default_poll_seconds,
            ),
        )

    def _physical_stream_type(self, key: MarketStreamKey) -> StreamType:
        if key.channel is MarketChannel.OPEN_INTEREST:
            return StreamType.OPEN_INTEREST
        if (
            key.channel is MarketChannel.FUNDING_RATE
            and not self._funding_shares_summary(key)
        ):
            return StreamType.FUNDING_RATE
        return StreamType.MARK_PRICE

    @staticmethod
    def _capabilities(key: MarketStreamKey) -> Any:
        bootstrap_default_adapters()
        return get_exchange_registry().get_plugin(key.exchange).capabilities()

    def _funding_shares_summary(self, key: MarketStreamKey) -> bool:
        capabilities = self._capabilities(key)
        funding = capabilities.channel_capability(
            MarketChannel.FUNDING_RATE,
            key.market_type,
        )
        mark = capabilities.channel_capability(
            MarketChannel.MARK_PRICE,
            key.market_type,
        )
        return bool(
            funding is not None
            and mark is not None
            and (
                funding.connection_model == "shared_multiplex"
                or any(
                    "shares the mark-price upstream stream" in str(limitation)
                    for limitation in funding.known_limitations
                )
            )
        )

    def _rest_poll_interval_seconds(
        self,
        key: MarketStreamKey,
        *,
        default_seconds: float,
    ) -> float:
        capabilities = self._capabilities(key)
        capability = capabilities.channel_capability(key.channel, key.market_type)
        declared = tuple(
            int(value)
            for value in getattr(capability, "update_intervals_ms", ())
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
        )
        rate_limit_ms = getattr(capabilities, "limits", {}).get(
            "ccxt.rate_limit_ms",
            0,
        )
        safe_ms = max(
            int(float(default_seconds) * 1000),
            min(declared) if declared else 0,
            rate_limit_ms if isinstance(rate_limit_ms, int) else 0,
        )
        return max(1.0, safe_ms / 1000.0)

    def _physical_id(self, key: MarketStreamKey) -> tuple[str, str, str, str]:
        source = {
            StreamType.MARK_PRICE: "derivatives_summary",
            StreamType.FUNDING_RATE: "funding_rate",
            StreamType.OPEN_INTEREST: "open_interest",
        }[self._physical_stream_type(key)]
        return key.exchange, key.market_type, key.symbol, source

    def _physical_capacity_waiter(
        self,
        key: MarketStreamKey,
    ) -> asyncio.Task | None:
        source = self._physical_id(key)[3]
        active = [
            (physical_id, entry)
            for physical_id, entry in self._physical_entries.items()
            if physical_id[3] == source
        ]
        limit = (
            self._max_summary_streams
            if source in {"derivatives_summary", "funding_rate"}
            else self._max_open_interest_streams
        )
        if len(active) < limit:
            return None
        for physical_id, entry in active:
            if entry.logical_keys:
                continue
            if entry.stop_task is not None:
                return entry.stop_task
            return self._schedule_physical_stop(
                physical_id,
                entry,
                delay=max(0.0, entry.retry_stop_at - time.monotonic()),
            )
        raise RuntimeError(f"{source} physical stream limit reached ({limit})")

    @staticmethod
    def _is_fresh(record: HubRecord, *, now_ms: int) -> bool:
        max_age_ms = (
            15_000
            if record.event.key.channel == MarketChannel.OPEN_INTEREST
            else 10_000
        )
        return now_ms - record.event.received_at_ms <= max_age_ms

    @staticmethod
    def _consumer_id(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("market stream consumer_id cannot be blank")
        return value.strip()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("market data service is closed")

    @staticmethod
    def _validate_key(key: MarketStreamKey, *, history: bool) -> None:
        if key.params:
            raise ValueError("P1 realtime market streams do not accept params")
        if len(key.symbol) > 64:
            raise ValueError("market stream symbol is too long")
        if key.channel not in _P1_CHANNELS:
            raise ValueError(f"unsupported P1 market channel: {key.channel.value}")
        bootstrap_default_adapters()
        try:
            capabilities = get_exchange_registry().get_plugin(key.exchange).capabilities()
        except KeyError as exc:
            raise ValueError(str(exc)) from exc

        if key.channel == MarketChannel.BASIS:
            supported = all(
                capabilities.supports_channel(channel, key.market_type, history=history)
                for channel in (MarketChannel.MARK_PRICE, MarketChannel.INDEX_PRICE)
            )
        else:
            supported = capabilities.supports_channel(
                key.channel,
                key.market_type,
                history=history,
            )
        if not supported:
            mode = "history" if history else "realtime"
            raise ValueError(
                f"{key.exchange}:{key.market_type}:{key.channel.value} does not support {mode}",
            )


def _inferred_funding_interval_ms(
    final_cycles: list[int],
    *,
    as_of_ms: int,
    observed_index: int | None = None,
) -> int:
    """Infer a Binance funding cadence from a bounded, no-lookahead window."""
    if observed_index is None:
        observed_index = bisect_right(final_cycles, as_of_ms)
    observed_index = min(max(0, int(observed_index)), len(final_cycles))
    # A missing settlement can make the latest adjacent difference 16h. Scan a
    # small fixed window backwards for a valid Binance cadence instead of
    # allocating/filtering the whole history for every Premium Index minute.
    oldest_pair_index = max(1, observed_index - 8)
    for current_index in range(observed_index - 1, oldest_pair_index - 1, -1):
        difference_ms = final_cycles[current_index] - final_cycles[current_index - 1]
        if difference_ms in _BINANCE_FUNDING_INTERVALS_MS:
            return difference_ms
    return _DEFAULT_FUNDING_INTERVAL_MS


def _funding_cycle_context_ms(
    as_of_ms: int,
    *,
    final_cycles: list[int],
) -> tuple[int, int]:
    observed_index = bisect_right(final_cycles, as_of_ms)
    interval_ms = _inferred_funding_interval_ms(
        final_cycles,
        as_of_ms=as_of_ms,
        observed_index=observed_index,
    )
    if observed_index:
        anchor_ms = final_cycles[observed_index - 1]
        steps = ((as_of_ms - anchor_ms) // interval_ms) + 1
        return anchor_ms + steps * interval_ms, interval_ms
    return ((as_of_ms // interval_ms) + 1) * interval_ms, interval_ms


def _next_funding_cycle_ms(
    as_of_ms: int,
    *,
    final_cycles: list[int],
) -> int:
    return _funding_cycle_context_ms(
        as_of_ms,
        final_cycles=final_cycles,
    )[0]


def _funding_cycle_start_ms(
    target_cycle_ms: int,
    *,
    final_cycles: list[int],
    as_of_ms: int,
) -> int:
    interval_ms = _inferred_funding_interval_ms(
        final_cycles,
        as_of_ms=as_of_ms,
    )
    return max(
        0,
        target_cycle_ms - interval_ms,
    )


def _estimated_funding_rate(
    premium_average: float,
    *,
    funding_interval_ms: int,
) -> float:
    interest_rate = _FUNDING_INTEREST_RATE_8H * (
        max(1, int(funding_interval_ms)) / _DEFAULT_FUNDING_INTERVAL_MS
    )
    adjustment = max(
        -_FUNDING_ADJUSTMENT_BOUND,
        min(
            _FUNDING_ADJUSTMENT_BOUND,
            interest_rate - premium_average,
        ),
    )
    estimate = premium_average + adjustment
    return max(-_FUNDING_RATE_BOUND, min(_FUNDING_RATE_BOUND, estimate))


def _missing_minute_ranges(
    open_times_ms: list[int],
    *,
    start_ms: int,
    end_ms: int,
) -> list[tuple[int, int]]:
    """Return gaps from the repository's unique ascending open-time stream."""
    if end_ms < start_ms:
        return []
    cursor_ms = start_ms
    missing: list[tuple[int, int]] = []
    previous_ms: int | None = None
    for open_time_ms in open_times_ms:
        if previous_ms == open_time_ms:
            continue
        previous_ms = open_time_ms
        if open_time_ms < cursor_ms:
            continue
        if open_time_ms > end_ms:
            break
        if open_time_ms > cursor_ms:
            missing.append((cursor_ms, open_time_ms - _PREMIUM_INDEX_INTERVAL_MS))
        cursor_ms = open_time_ms + _PREMIUM_INDEX_INTERVAL_MS
    if cursor_ms <= end_ms:
        missing.append((cursor_ms, end_ms))
    return missing


def _premium_index_page_ranges(
    missing_ranges: list[tuple[int, int]],
    *,
    max_pages: int,
) -> tuple[list[tuple[int, int]], bool]:
    """Split aligned missing ranges into deterministic 1000-minute pages."""
    page_limit = max(1, int(max_pages))
    page_span_ms = (
        (_PREMIUM_HISTORY_PAGE_POINTS - 1) * _PREMIUM_INDEX_INTERVAL_MS
    )
    pages: list[tuple[int, int]] = []
    budget_exhausted = False
    for range_start_ms, range_end_ms in sorted(missing_ranges):
        cursor_ms = int(range_start_ms)
        aligned_end_ms = int(range_end_ms)
        while cursor_ms <= aligned_end_ms:
            if len(pages) >= page_limit:
                budget_exhausted = True
                return pages, budget_exhausted
            page_end_ms = min(aligned_end_ms, cursor_ms + page_span_ms)
            pages.append((cursor_ms, page_end_ms))
            cursor_ms = page_end_ms + _PREMIUM_INDEX_INTERVAL_MS
    return pages, budget_exhausted


def _missing_bucket_exclusions(
    bucket_starts_ms: list[int],
    *,
    period_ms: int,
    period: str,
) -> list[dict[str, Any]]:
    exclusions: list[dict[str, Any]] = []
    range_start_ms: int | None = None
    range_end_ms: int | None = None
    for bucket_ms in sorted(set(bucket_starts_ms)):
        bucket_end_ms = compute_bucket_end_ms(
            bucket_ms,
            period_ms,
            interval=period,
        ) - 1
        if range_start_ms is None:
            range_start_ms = bucket_ms
            range_end_ms = bucket_end_ms
            continue
        if range_end_ms is not None and bucket_ms == range_end_ms + 1:
            range_end_ms = bucket_end_ms
            continue
        exclusions.append({
            "start_ms": range_start_ms,
            "end_ms": range_end_ms,
            "disposition": "estimated_data_unavailable",
            "reason": "premium_index_unavailable",
        })
        range_start_ms = bucket_ms
        range_end_ms = bucket_end_ms
    if range_start_ms is not None and range_end_ms is not None:
        exclusions.append({
            "start_ms": range_start_ms,
            "end_ms": range_end_ms,
            "disposition": "estimated_data_unavailable",
            "reason": "premium_index_unavailable",
        })
    return exclusions
