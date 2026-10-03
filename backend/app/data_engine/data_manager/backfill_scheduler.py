"""Backfill scheduling, demand leases, dispatch fairness and cancellation.

Execution, durable ledger transitions and delivery are injected callbacks.
This owner does not read storage, mutate caches, or import the coordinator.
"""
from __future__ import annotations

import asyncio
import heapq
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.data_engine.history.models import BoundaryReason
from app.data_engine.interval_policy import parse_interval_ms
from app.data_engine.interval_resolution import IntervalPurpose, IntervalResolver
from app.data_engine.interval_work_plan import IntervalWorkPlan, resolve_interval_work_plan
from app.data_engine.kline_quality import repair_requires_trusted_finality
from app.exchanges.rate_limits import RateLimitDeferred
from .backfill_contracts import (
    RepairOutcome,
    RepairRequest,
    RepairRetryDeferred,
    _merge_derived_repair_targets,
    repair_status_value,
)

logger = logging.getLogger("data_manager.backfill_scheduler")


_BACKGROUND_BACKFILL_REASONS = frozenset({
    "active_history_hydration",
    "related_interval_warmup",
    "full_subscription_warmup",
    "startup_gap_scan",
    "background_gap_audit",
})

# Demand that directly gates the chart's current visible state.  When the
# configured scheduler is deliberately single-lane, one such request may use
# a tightly bounded reserve lane while that lane is occupied by speculative or
# maintenance work.  This avoids turning low concurrency into head-of-line
# blocking without reopening the old unbounded/multi-background burst.
_INTERACTIVE_BACKFILL_REASONS = frozenset({
    "initial_history",
    "visible_load_more",
    "visible_range_gap",
    "visible_seed_gap",
    "tail_gap",
})
_MAINTENANCE_BACKFILL_REASONS = (
    # Durable delivery recovery may retry old series for much longer than an
    # interactive gap fetch. Keep its normal priority, but let a visible chart
    # use the bounded reserve while that recovery occupies the single lane.
    _BACKGROUND_BACKFILL_REASONS | frozenset({"price_daily_open", "bar_delivery_recovery"})
)

_SCHEDULER_OUTCOME_HISTORY_LIMIT = 256


@dataclass(slots=True)
class _SeriesState:
    active: str | None = None
    pending: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _FetchChunk:
    chunk_id: str
    parent_id: str
    request: RepairRequest
    sequence: int
    queue_sequence: int = 0
    eligible_at_monotonic: float = 0.0
    retry_at_ms: int | None = None
    defer_reason: str | None = None
    rate_limit_bucket: str | None = None
    defer_count: int = 0


@dataclass(frozen=True, slots=True)
class _DemandLease:
    owner_id: str
    scope: str | None = None
    generation: int | None = None


@dataclass(slots=True)
class _RequestState:
    request: RepairRequest
    future: asyncio.Future[RepairOutcome]
    chunk_ids: list[str]
    completed: int = 0
    attempts: int = 0
    bars_loaded: int = 0
    outcomes: list[RepairOutcome] = field(default_factory=list)
    failed: RepairOutcome | None = None
    stale: bool = False
    demand_leases: dict[str, _DemandLease] = field(default_factory=dict)
    persistent_interest: bool = False
    cancel_requested: bool = False
    cancel_reason: str | None = None
    progress_revision: int = 0

    @property
    def total(self) -> int:
        return len(self.chunk_ids)

    @property
    def pending_count(self) -> int:
        return max(0, self.total - self.completed - (1 if self.failed else 0))


@dataclass(slots=True)
class _TokenBucket:
    """Local scheduler dispatch bucket, separate from exchange REST quotas."""

    key: str
    capacity: int = 60
    refill_per_second: float = 60.0
    tokens: float = 60.0
    updated_at: float = field(default_factory=time.monotonic)
    cooldown_until_ms: int = 0

    def try_acquire(self, now_ms: int, cost: int = 1) -> bool:
        if now_ms < self.cooldown_until_ms:
            return False
        now = time.monotonic()
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.updated_at = now
        if self.tokens < cost:
            return False
        self.tokens -= cost
        return True

    def next_available_delay(self, now_ms: int, cost: int = 1) -> float:
        if now_ms < self.cooldown_until_ms:
            return max(0.01, (self.cooldown_until_ms - now_ms) / 1000)
        if self.tokens >= cost:
            return 0.01
        if self.refill_per_second <= 0:
            return 1.0
        return max(0.01, (cost - self.tokens) / self.refill_per_second)

    def snapshot(self) -> dict[str, Any]:
        return {
            "scope": "scheduler_dispatch",
            "tokens": round(self.tokens, 2),
            "capacity": self.capacity,
            "refill_per_second": self.refill_per_second,
            "cooldown_until_ms": self.cooldown_until_ms,
        }


class BackfillScheduler:
    """Priority scheduler used behind BackfillCoordinator's public API."""

    def __init__(
        self,
        *,
        execute: Callable[[RepairRequest], Awaitable[RepairOutcome]],
        future_for: Callable[[RepairRequest], asyncio.Future[RepairOutcome]],
        complete: Callable[[RepairRequest, RepairOutcome], None],
        finalize: Callable[[RepairRequest, RepairOutcome], Awaitable[None]],
        on_queued: Callable[[RepairRequest], None],
        on_progress: Callable[[RepairRequest, dict[str, Any]], None] | None = None,
        max_concurrency: int = 4,
        chunk_bars: int = 1000,
    ) -> None:
        self._execute = execute
        self._future_for = future_for
        self._complete = complete
        self._finalize = finalize
        self._on_queued = on_queued
        self._on_progress = on_progress
        self._max_concurrency = max(1, max_concurrency)
        self._chunk_bars = max(1, chunk_bars)
        self._interval_resolver = IntervalResolver()

        self._series: dict[tuple[str, ...], _SeriesState] = {}
        self._requests: dict[str, _RequestState] = {}
        self._chunks: dict[str, _FetchChunk] = {}
        self._ready: list[tuple[int, int, int, str]] = []
        self._tasks: dict[str, asyncio.Task] = {}
        self._buckets: dict[str, _TokenBucket] = {}
        self._coverage: dict[tuple[str, ...], list[dict[str, int]]] = {}
        self._outcomes: dict[str, RepairOutcome] = {}
        self._max_retained_outcomes = _SCHEDULER_OUTCOME_HISTORY_LIMIT
        self._seq = 0
        self._shutdown = False
        self._drain_timer: asyncio.TimerHandle | None = None
        self._next_drain_at: float | None = None
        self._last_foreground_activity_at = 0.0
        self._active_foreground_chunks: set[str] = set()
        self._active_background_chunks: set[str] = set()
        self._last_dispatch_owner: dict[tuple[int, bool], str] = {}

        self.submitted = 0
        self.deduped = 0
        self.merged = 0
        self.rate_limited_skips = 0
        self.exchange_rate_limit_deferrals = 0
        self.priority_promotions = 0
        self.cancelled_pending = 0
        self.cancelled_after_chunk = 0
        self.background_dispatches = 0
        self.foreground_reserve_dispatches = 0
        self.covered_chunks_skipped = 0
        self.fairness_rotations = 0

    def submit(self, request: RepairRequest) -> tuple[str, asyncio.Future[RepairOutcome]]:
        if self._shutdown:
            raise RuntimeError("BackfillCoordinator is shut down")
        if repair_requires_trusted_finality(
            request.metadata,
            reason=request.reason,
        ):
            # Normalize legacy reason-only demand into the durable merge-safe
            # contract before any covering/dedupe decision is made.
            request.metadata["requires_trusted_finality"] = True

        self.submitted += 1
        if not self._is_background(request):
            self._last_foreground_activity_at = time.monotonic()
        series_key = request.series_key
        series = self._series.setdefault(series_key, _SeriesState())

        active_state = self._requests.get(series.active or "")
        if (
            active_state is not None
            and not active_state.stale
            and not active_state.cancel_requested
            and self._can_coalesce(active_state.request, request)
            and self._covers(active_state.request, request)
            and not self._requires_stronger_finality(
                active_state.request,
                request,
            )
        ):
            self._merge_request_interest(active_state, request)
            self.deduped += 1
            # A background parent can become foreground demand here.  That
            # changes the global background-slot admission decision even when
            # this exact series is already active, so re-evaluate the queue.
            self._drain()
            return active_state.request.request_id, active_state.future

        for request_id in list(series.pending):
            state = self._requests.get(request_id)
            if state is None or state.stale:
                continue
            if self._can_coalesce(state.request, request) and self._covers(
                state.request,
                request,
            ):
                stronger_finality = self._requires_stronger_finality(
                    state.request,
                    request,
                )
                if stronger_finality and state.completed > 0:
                    # Completed chunks ran under the weaker contract and no
                    # longer exist to upgrade in place.  Keep this ordinary
                    # parent and enqueue a full authoritative successor.
                    continue
                upgraded_finality = self._merge_request_interest(state, request)
                if upgraded_finality:
                    # Persist the stronger contract for crash recovery.  The
                    # original queued ledger snapshot predates this upgrade.
                    self._on_queued(state.request)
                    self._publish_progress(
                        state,
                        status="trusted_finality_upgraded",
                    )
                self.deduped += 1
                # Pending background work may have just been promoted to
                # foreground demand.  It is now runnable in a spare slot and
                # must not wait for an unrelated active chunk to finish.
                self._drain()
                return state.request.request_id, state.future
            if state.completed == 0 and self._should_merge(state.request, request):
                state.request = state.request.merged_with(request)
                incoming_leases = self._demand_leases_from_request(request)
                state.demand_leases.update(incoming_leases)
                if not incoming_leases:
                    state.persistent_interest = True
                self._replace_pending_chunks(state)
                self._on_queued(state.request)
                self._publish_progress(state, status="merged")
                self.merged += 1
                # _replace_pending_chunks rebuilds the ready work.  A merge
                # may occur while the only active task is stalled upstream,
                # so explicitly wake the scheduler for the replacement.
                self._drain()
                return state.request.request_id, state.future

        future = self._future_for(request)
        demand_leases = self._demand_leases_from_request(request)
        state = _RequestState(
            request=request,
            future=future,
            chunk_ids=[],
            demand_leases=demand_leases,
            persistent_interest=not bool(demand_leases),
        )
        self._requests[request.request_id] = state
        series.pending.append(request.request_id)
        self._on_queued(request)
        self._replace_pending_chunks(state)
        self._publish_progress(state, status="queued")
        self._drain()
        return request.request_id, future

    def _merge_request_interest(
        self,
        state: _RequestState,
        request: RepairRequest,
    ) -> bool:
        self._merge_derived_targets_into_state(state, request)
        incoming_leases = self._demand_leases_from_request(request)
        state.demand_leases.update(incoming_leases)
        if not incoming_leases:
            state.persistent_interest = True
        current_requires_trusted_finality = repair_requires_trusted_finality(
            state.request.metadata,
            reason=state.request.reason,
        )
        incoming_requires_trusted_finality = repair_requires_trusted_finality(
            request.metadata,
            reason=request.reason,
        )
        requires_trusted_finality = (
            current_requires_trusted_finality
            or incoming_requires_trusted_finality
        )
        upgraded_finality = (
            incoming_requires_trusted_finality
            and not current_requires_trusted_finality
        )
        if requires_trusted_finality:
            state.request.metadata["requires_trusted_finality"] = True
        reasons = [
            part.strip()
            for raw in (state.request.reason, request.reason)
            for part in str(raw or "").split("+")
            if part.strip()
        ]
        state.request.reason = "+".join(dict.fromkeys(reasons))
        if state.request.requester != request.requester:
            state.request.requester = "mixed"
        incoming_priority = int(request.priority or 100)
        current_priority = int(state.request.priority or 100)
        promoted = incoming_priority < current_priority
        if promoted:
            state.request.priority = incoming_priority
            self.priority_promotions += 1
        chunk_ids: Iterable[str] = state.chunk_ids
        if promoted and self._newest_first(state.request):
            chunk_ids = reversed(state.chunk_ids)
        if promoted:
            # Priority queues do not support an in-place key update.  Remove
            # each old heap item before inserting the promoted chunk; leaving
            # both entries inflates ready diagnostics and can repeatedly skip
            # the same physical chunk while its series is active.
            promoted_chunk_ids = {
                chunk_id
                for chunk_id in state.chunk_ids
                if chunk_id not in self._tasks and chunk_id in self._chunks
            }
            if promoted_chunk_ids:
                self._ready = [
                    item for item in self._ready if item[3] not in promoted_chunk_ids
                ]
                heapq.heapify(self._ready)
        for chunk_id in chunk_ids:
            if chunk_id in self._tasks and not self._is_background(state.request):
                self._active_background_chunks.discard(chunk_id)
                self._active_foreground_chunks.add(chunk_id)
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            chunk.request.reason = state.request.reason
            chunk.request.requester = state.request.requester
            if requires_trusted_finality:
                chunk.request.metadata["requires_trusted_finality"] = True
            if promoted:
                chunk.request.priority = incoming_priority
            if promoted and chunk_id not in self._tasks:
                self._push_ready(chunk)
        if promoted:
            self._publish_progress(state, status="priority_promoted")
        return upgraded_finality

    @staticmethod
    def _demand_leases_from_request(
        request: RepairRequest,
    ) -> dict[str, _DemandLease]:
        metadata = request.metadata or {}
        owner_id = str(metadata.get("demand_owner_id") or "").strip()
        if not owner_id:
            return {}
        scope_raw = metadata.get("demand_scope")
        scope = str(scope_raw).strip() if scope_raw is not None else None
        generation_raw = metadata.get("demand_generation")
        try:
            generation = int(generation_raw) if generation_raw is not None else None
        except (TypeError, ValueError):
            generation = None
        lease = _DemandLease(
            owner_id=owner_id,
            scope=scope or None,
            generation=generation,
        )
        return {owner_id: lease}

    @staticmethod
    def _requires_stronger_finality(
        current: RepairRequest,
        incoming: RepairRequest,
    ) -> bool:
        """Return whether an active ordinary repair cannot satisfy incoming."""
        return (
            repair_requires_trusted_finality(
                incoming.metadata,
                reason=incoming.reason,
            )
            and not repair_requires_trusted_finality(
                current.metadata,
                reason=current.reason,
            )
        )

    def _merge_derived_targets_into_state(
        self,
        state: _RequestState,
        request: RepairRequest,
    ) -> None:
        targets = _merge_derived_repair_targets(
            state.request.metadata.get("derived_repair_targets"),
            request.metadata.get("derived_repair_targets"),
        )
        if not targets:
            return
        state.request.metadata["derived_repair_targets"] = targets
        # Active chunks carry their own metadata copy.  Update it in place so
        # a late deduped custom consumer is present on the completion emitted
        # by work that is already running.
        for chunk_id in state.chunk_ids:
            chunk = self._chunks.get(chunk_id)
            if chunk is not None:
                chunk.request.metadata["derived_repair_targets"] = [
                    dict(target) for target in targets
                ]

    def acquire_demand(
        self,
        request_id: str,
        *,
        owner_id: str,
        scope: str | None = None,
        generation: int | None = None,
    ) -> bool:
        state = self._requests.get(request_id)
        normalized_owner = str(owner_id or "").strip()
        if state is None or state.stale or not normalized_owner:
            return False
        state.demand_leases[normalized_owner] = _DemandLease(
            owner_id=normalized_owner,
            scope=str(scope).strip() if scope is not None and str(scope).strip() else None,
            generation=int(generation) if generation is not None else None,
        )
        self._publish_progress(state, status="demand_acquired")
        return True

    async def release_demand(
        self,
        request_id: str,
        *,
        owner_id: str,
        cancel_if_unobserved: bool,
        reason: str = "demand_released",
    ) -> bool:
        state = self._requests.get(request_id)
        if state is None:
            return False
        state.demand_leases.pop(str(owner_id or "").strip(), None)
        if (
            state.demand_leases
            or state.persistent_interest
            or not cancel_if_unobserved
        ):
            self._publish_progress(state, status="demand_released")
            return False
        return await self._request_cancel(state, reason=reason)

    async def supersede_scope(self, scope: str, generation: int) -> int:
        normalized_scope = str(scope or "").strip()
        if not normalized_scope:
            return 0
        superseded = 0
        pending_finalizers: list[
            tuple[_RequestState, RepairOutcome, _SeriesState | None]
        ] = []
        for state in list(self._requests.values()):
            old_owners = [
                owner_id
                for owner_id, lease in state.demand_leases.items()
                if lease.scope == normalized_scope
                and lease.generation is not None
                and lease.generation < int(generation)
            ]
            if not old_owners:
                continue
            for owner_id in old_owners:
                state.demand_leases.pop(owner_id, None)
            if not state.demand_leases and not state.persistent_interest:
                started, final, series = self._begin_request_cancel(
                    state,
                    reason=f"scope_superseded:{normalized_scope}:{generation}",
                )
                if started:
                    superseded += 1
                if final is not None:
                    pending_finalizers.append((state, final, series))
        if pending_finalizers:
            await asyncio.gather(*(
                self._finish_pending_cancellation(state, final, series)
                for state, final, series in pending_finalizers
            ))
        return superseded

    async def revoke_owner(self, owner_id: str, *, reason: str) -> int:
        normalized_owner = str(owner_id or "").strip()
        if not normalized_owner:
            return 0
        revoked = 0
        pending_finalizers: list[
            tuple[_RequestState, RepairOutcome, _SeriesState | None]
        ] = []
        for state in list(self._requests.values()):
            if normalized_owner not in state.demand_leases:
                continue
            state.demand_leases.pop(normalized_owner, None)
            revoked += 1
            if not state.demand_leases and not state.persistent_interest:
                _started, final, series = self._begin_request_cancel(
                    state,
                    reason=reason,
                )
                if final is not None:
                    pending_finalizers.append((state, final, series))
            else:
                self._publish_progress(state, status="demand_revoked")
        if pending_finalizers:
            await asyncio.gather(*(
                self._finish_pending_cancellation(state, final, series)
                for state, final, series in pending_finalizers
            ))
        return revoked

    async def _request_cancel(self, state: _RequestState, *, reason: str) -> bool:
        started, final, series = self._begin_request_cancel(state, reason=reason)
        if final is not None:
            await self._finish_pending_cancellation(state, final, series)
        return started

    def _begin_request_cancel(
        self,
        state: _RequestState,
        *,
        reason: str,
    ) -> tuple[bool, RepairOutcome | None, _SeriesState | None]:
        """Synchronously revoke scheduler ownership before durable finalization."""
        if state.cancel_requested or state.future.done():
            return False, None, None
        state.cancel_requested = True
        state.cancel_reason = reason
        self._discard_remaining_chunks(state)
        series = self._series.get(state.request.series_key)
        is_active = bool(series is not None and series.active == state.request.request_id)
        if is_active:
            self.cancelled_after_chunk += 1
            self._publish_progress(state, status="cancelling_after_chunk")
            return True, None, series

        if series is not None and state.request.request_id in series.pending:
            series.pending.remove(state.request.request_id)
        self.cancelled_pending += 1
        final = self._cancelled_outcome(state)
        return True, final, series

    async def _finish_pending_cancellation(
        self,
        state: _RequestState,
        final: RepairOutcome,
        series: _SeriesState | None,
    ) -> None:
        """Durably finalize a cancellation after all target states are inert."""
        try:
            try:
                await self._finalize(state.request, final)
            except Exception:
                logger.exception(
                    "Backfill cancellation finalization failed for %s",
                    state.request.request_id,
                )
        finally:
            # Cancellation of the caller is allowed to interrupt durable
            # finalization, but it must never leave a stale scheduler state or
            # unresolved shared future behind.
            self._retain_outcome(state.request.request_id, final)
            self._complete(state.request, final)
            self._publish_progress(state, status="cancelled", terminal=True)
            self._requests.pop(state.request.request_id, None)
            series_key = state.request.series_key
            if (
                series is not None
                and self._series.get(series_key) is series
                and not series.pending
                and series.active is None
            ):
                self._series.pop(series_key, None)
            self._drain()

    @staticmethod
    def _cancelled_outcome(state: _RequestState) -> RepairOutcome:
        return RepairOutcome(
            request=state.request,
            status="cancelled",
            attempts=state.attempts,
            bars_loaded=state.bars_loaded,
            verified_contiguous=False,
            error=state.cancel_reason or "demand_released",
            terminal_reason="demand_released",
            retryable=True,
        )

    def _publish_progress(
        self,
        state: _RequestState,
        *,
        status: str,
        terminal: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        callback = self._on_progress
        if callback is None:
            return
        payload: dict[str, Any] = {
            "request_id": state.request.request_id,
            "revision": state.progress_revision,
            "status": status,
            "terminal": bool(terminal),
            "completed_chunks": state.completed,
            "total_chunks": state.total,
            "pending_chunks": state.pending_count,
            "bars_loaded": state.bars_loaded,
            "priority": state.request.priority,
            "demand_count": len(state.demand_leases),
            "persistent_interest": state.persistent_interest,
            "cancel_requested": state.cancel_requested,
            "updated_at_ms": int(time.time() * 1000),
        }
        if details:
            payload.update(details)
        callback(state.request, payload)

    async def shutdown(self) -> None:
        self._shutdown = True
        self._cancel_drain_timer()
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        for state in list(self._requests.values()):
            if state.future.done():
                continue
            outcome = RepairOutcome(
                request=state.request,
                status="failed",
                error="cancelled",
            )
            state.future.set_result(outcome)

        self._ready.clear()
        self._chunks.clear()
        self._requests.clear()
        self._series.clear()
        self._tasks.clear()

    def snapshot(self) -> dict[str, Any]:
        active: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        now_monotonic = time.monotonic()
        for series_key, series in self._series.items():
            series_label = ":".join(series_key)
            if series.active:
                state = self._requests.get(series.active)
                if state is not None:
                    active.append(self._state_snapshot(series_label, state, active=True))
            for request_id in series.pending:
                state = self._requests.get(request_id)
                if state is not None and not state.stale:
                    pending.append(self._state_snapshot(series_label, state, active=False))

        deferred = [
            {
                "chunk_id": chunk.chunk_id,
                "request_id": chunk.parent_id,
                "series": ":".join(chunk.request.series_key),
                "priority": chunk.request.priority,
                "sequence": chunk.sequence,
                "retry_at_ms": chunk.retry_at_ms,
                "retry_in_ms": max(
                    0,
                    int((chunk.eligible_at_monotonic - now_monotonic) * 1000),
                ),
                "reason": chunk.defer_reason,
                "bucket_key": chunk.rate_limit_bucket,
                "defer_count": chunk.defer_count,
                "fairness_owner": self._fairness_owner(chunk.request),
            }
            for chunk in self._chunks.values()
            if chunk.eligible_at_monotonic > now_monotonic
        ]

        return {
            "submitted": self.submitted,
            "deduped": self.deduped,
            "merged": self.merged,
            "priority_promotions": self.priority_promotions,
            "cancelled_pending": self.cancelled_pending,
            "cancelled_after_chunk": self.cancelled_after_chunk,
            "background_dispatches": self.background_dispatches,
            "foreground_reserve_dispatches": self.foreground_reserve_dispatches,
            "covered_chunks_skipped": self.covered_chunks_skipped,
            "fairness_rotations": self.fairness_rotations,
            "running_background_chunks": self._running_background_count(),
            "active": active,
            "pending": pending,
            "ready_chunks": len(self._ready),
            "running_chunks": len(self._tasks),
            "max_concurrency": self._max_concurrency,
            "next_drain_in_ms": self._next_drain_in_ms(),
            "rate_limited_skips": self.rate_limited_skips,
            "exchange_rate_limit_deferrals": self.exchange_rate_limit_deferrals,
            "deferred_chunks": len(deferred),
            "deferred": sorted(
                deferred,
                key=lambda item: (int(item["retry_at_ms"] or 0), item["chunk_id"]),
            ),
            "buckets": {
                key: bucket.snapshot()
                for key, bucket in sorted(self._buckets.items())
            },
            "scheduler_buckets": {
                key: bucket.snapshot()
                for key, bucket in sorted(self._buckets.items())
            },
            "coverage": {
                ":".join(series): {"covered_ranges": ranges, "missing_ranges": []}
                for series, ranges in sorted(self._coverage.items())
            },
            "recent_outcomes": {
                request_id: self._outcome_snapshot(outcome)
                for request_id, outcome in list(self._outcomes.items())[-20:]
            },
        }

    def _replace_pending_chunks(self, state: _RequestState) -> None:
        replaced_chunk_ids = set(state.chunk_ids)
        for chunk_id in replaced_chunk_ids:
            self._chunks.pop(chunk_id, None)
        if replaced_chunk_ids:
            self._ready = [
                item for item in self._ready if item[3] not in replaced_chunk_ids
            ]
            heapq.heapify(self._ready)
        state.chunk_ids = []
        state.completed = 0
        state.failed = None
        state.outcomes = []
        state.attempts = 0
        state.bars_loaded = 0

        for chunk in self._split_request(state.request):
            self._chunks[chunk.chunk_id] = chunk
            state.chunk_ids.append(chunk.chunk_id)
            self._push_ready(chunk)

    def _split_request(self, request: RepairRequest) -> list[_FetchChunk]:
        interval_ms = parse_interval_ms(request.interval) or 60_000
        work_plan = self._source_aware_chunk_plan(request, self._chunk_bars)
        target_chunk_bars = max(1, int(work_plan.effective_target_bars or 1))
        chunk_span = interval_ms * target_chunk_bars
        chunks: list[_FetchChunk] = []
        sequence = 0
        for planned_start, planned_end in self._planned_ranges(request):
            start = planned_start
            while start <= planned_end:
                chunk_end = min(planned_end, start + chunk_span - interval_ms)
                actual_target_bars = max(1, (chunk_end - start) // interval_ms + 1)
                chunk_work_plan = self._source_aware_chunk_plan(
                    request,
                    actual_target_bars,
                    source_row_budget=work_plan.source_row_budget,
                )
                chunk_request = RepairRequest(
                    symbol=request.symbol,
                    interval=request.interval,
                    start_ms=start,
                    end_ms=chunk_end,
                    exchange=request.exchange,
                    market_type=request.market_type,
                    reason=request.reason,
                    priority=request.priority,
                    requester=request.requester,
                    wait_policy=request.wait_policy,
                    metadata={
                        **request.metadata,
                        **chunk_work_plan.to_metadata(),
                        "parent_request_id": request.request_id,
                        "chunk_sequence": sequence,
                        "ledger_range": {
                            "start_ms": int(request.start_ms),
                            "end_ms": int(request.end_ms),
                        },
                    },
                    request_id=request.request_id,
                )
                chunks.append(_FetchChunk(
                    chunk_id=f"{request.request_id}:{sequence}",
                    parent_id=request.request_id,
                    request=chunk_request,
                    sequence=sequence,
                ))
                sequence += 1
                start = chunk_end + interval_ms
        if self._newest_first(request):
            return list(reversed(chunks))
        return chunks

    def _source_aware_chunk_plan(
        self,
        request: RepairRequest,
        requested_target_bars: int,
        *,
        source_row_budget: int | None = None,
    ) -> IntervalWorkPlan:
        budget = self._chunk_bars if source_row_budget is None else source_row_budget
        try:
            plan = resolve_interval_work_plan(
                self._interval_resolver,
                exchange=request.exchange,
                market_type=request.market_type,
                interval=request.interval,
                requested_target_bars=max(1, int(requested_target_bars)),
                source_row_budget=budget,
                source_padding_bars=3,
                purpose=IntervalPurpose.HISTORY,
            )
            if plan.effective_target_bars > 0:
                return plan
            # One derived candle can legitimately exceed the ordinary source
            # page size (for example a monthly target sourced from minutes).
            # Admit exactly one target with an explicit, finite source budget
            # instead of falling back to the old unbounded target chunk.
            minimum_budget = max(1, (plan.source_padding_bars + 1) * plan.source_factor)
            return resolve_interval_work_plan(
                self._interval_resolver,
                exchange=request.exchange,
                market_type=request.market_type,
                interval=request.interval,
                requested_target_bars=1,
                source_row_budget=minimum_budget,
                source_padding_bars=plan.source_padding_bars,
                purpose=IntervalPurpose.HISTORY,
            )
        except Exception:
            logger.debug(
                "Source-aware chunk planning fell back to native sizing for %s@%s",
                request.symbol,
                request.interval,
                exc_info=True,
            )
            requested = max(1, int(requested_target_bars))
            return IntervalWorkPlan(
                requested_target_bars=requested,
                effective_target_bars=requested,
                base_interval=request.interval,
                source_factor=1,
                source_padding_bars=0,
                planned_source_rows=requested,
                source_row_budget=budget,
                budget_limited=False,
                derived=False,
            )

    @staticmethod
    def _planned_ranges(request: RepairRequest) -> list[tuple[int, int]]:
        raw_ranges = request.metadata.get("history_fetch_ranges")
        if not isinstance(raw_ranges, list):
            return [(int(request.start_ms), int(request.end_ms))]
        ranges: list[tuple[int, int]] = []
        for raw in raw_ranges:
            if not isinstance(raw, dict):
                continue
            try:
                start_ms = max(int(request.start_ms), int(raw["start_ms"]))
                end_ms = min(int(request.end_ms), int(raw["end_ms"]))
            except (KeyError, TypeError, ValueError):
                continue
            if start_ms <= end_ms:
                ranges.append((start_ms, end_ms))
        return ranges or [(int(request.start_ms), int(request.end_ms))]

    @staticmethod
    def _newest_first(request: RepairRequest) -> bool:
        reasons = {
            part.strip()
            for part in str(request.reason or "").split("+")
            if part.strip()
        }
        return bool(reasons & {
            "initial_history",
            "active_history_hydration",
            "visible_load_more",
            "visible_range_gap",
            "visible_seed_gap",
            "tail_gap",
            "latest_refresh",
        })

    def _push_ready(
        self,
        chunk: _FetchChunk,
        *,
        preserve_sequence: bool = False,
    ) -> None:
        if not preserve_sequence or chunk.queue_sequence <= 0:
            self._seq += 1
            chunk.queue_sequence = self._seq
        heapq.heappush(
            self._ready,
            (
                int(chunk.request.priority or 100),
                int(chunk.request.metadata.get("created_at_ms", 0) or 0),
                chunk.queue_sequence,
                chunk.chunk_id,
            ),
        )

    def _drain(self) -> None:
        if self._shutdown:
            return
        skipped: list[tuple[int, int, int, str]] = []
        next_delay: float | None = None
        try:
            # The extra candidate slot exists only for the deliberately
            # single-lane configuration. It is admitted below solely for one
            # interactive request while maintenance occupies that lane.
            candidate_capacity = self._max_concurrency + (
                1 if self._max_concurrency == 1 else 0
            )
            while len(self._tasks) < candidate_capacity and self._ready:
                item = heapq.heappop(self._ready)
                chunk = self._chunks.get(item[3])
                if chunk is None:
                    continue
                state = self._requests.get(chunk.parent_id)
                if state is None or state.stale or state.failed is not None:
                    self._chunks.pop(chunk.chunk_id, None)
                    continue
                using_foreground_reserve = len(self._tasks) >= self._max_concurrency
                if (
                    using_foreground_reserve
                    and not self._can_use_foreground_reserve(chunk.request)
                ):
                    skipped.append(item)
                    continue
                now_monotonic = time.monotonic()
                if chunk.eligible_at_monotonic > now_monotonic:
                    delay = chunk.eligible_at_monotonic - now_monotonic
                    next_delay = delay if next_delay is None else min(next_delay, delay)
                    skipped.append(item)
                    continue
                series = self._series.setdefault(chunk.request.series_key, _SeriesState())
                if series.active is not None:
                    skipped.append(item)
                    continue
                if self._is_background(chunk.request) and (
                    self._running_background_count() >= 1
                    or self._has_foreground_work(skipped)
                ):
                    skipped.append(item)
                    continue
                fairness_lane = (
                    int(chunk.request.priority or 100),
                    self._is_background(chunk.request),
                )
                fairness_owner = self._fairness_owner(chunk.request)
                if (
                    self._last_dispatch_owner.get(fairness_lane) == fairness_owner
                    and self._has_fairness_alternative(chunk, lane=fairness_lane)
                ):
                    self.fairness_rotations += 1
                    skipped.append(item)
                    continue
                bucket = self._bucket_for(chunk.request)
                now_ms = int(time.time() * 1000)
                if not bucket.try_acquire(now_ms):
                    self.rate_limited_skips += 1
                    delay = bucket.next_available_delay(now_ms)
                    next_delay = delay if next_delay is None else min(next_delay, delay)
                    skipped.append(item)
                    continue

                chunk.eligible_at_monotonic = 0.0
                chunk.retry_at_ms = None
                chunk.defer_reason = None
                chunk.rate_limit_bucket = None
                series.active = chunk.parent_id
                if chunk.parent_id in series.pending:
                    series.pending.remove(chunk.parent_id)
                task = asyncio.create_task(
                    self._run_chunk(chunk),
                    name=(
                        "backfill-chunk:"
                        f"{chunk.request.exchange}:{chunk.request.market_type}:"
                        f"{chunk.request.symbol}@{chunk.request.interval}:"
                        f"{chunk.sequence}"
                    ),
                )
                self._tasks[chunk.chunk_id] = task
                self._last_dispatch_owner[fairness_lane] = fairness_owner
                if self._is_background(chunk.request):
                    self._active_background_chunks.add(chunk.chunk_id)
                    self.background_dispatches += 1
                else:
                    self._active_foreground_chunks.add(chunk.chunk_id)
                    if using_foreground_reserve:
                        self.foreground_reserve_dispatches += 1
                task.add_done_callback(
                    lambda _task, chunk_id=chunk.chunk_id: (
                        self._active_foreground_chunks.discard(chunk_id),
                        self._active_background_chunks.discard(chunk_id),
                    )
                )
        finally:
            for item in skipped:
                heapq.heappush(self._ready, item)
            if next_delay is not None and self._ready:
                self._schedule_drain(next_delay)
            elif not self._ready:
                self._cancel_drain_timer()

    @staticmethod
    def _is_background(request: RepairRequest) -> bool:
        reasons = BackfillScheduler._reasons(request)
        return bool(reasons) and reasons.issubset(_BACKGROUND_BACKFILL_REASONS)

    @staticmethod
    def _reasons(request: RepairRequest) -> set[str]:
        return {
            part.strip()
            for part in str(request.reason or "").split("+")
            if part.strip()
        }

    @classmethod
    def _is_interactive(cls, request: RepairRequest) -> bool:
        reasons = cls._reasons(request)
        if reasons & _INTERACTIVE_BACKFILL_REASONS:
            return True
        # The initial chart's bounded /latest repair is intentionally tagged
        # as an internal completion event, but it is still foreground demand.
        # Admit only that explicit API requester; generic query_latest callers
        # must not consume the single maintenance reserve.
        return (
            "latest_refresh" in reasons
            and request.requester == "klines_latest"
        )

    @classmethod
    def _is_maintenance(cls, request: RepairRequest) -> bool:
        reasons = cls._reasons(request)
        return (
            bool(reasons)
            and not bool(reasons & _INTERACTIVE_BACKFILL_REASONS)
            and reasons.issubset(_MAINTENANCE_BACKFILL_REASONS)
        )

    def _can_use_foreground_reserve(self, request: RepairRequest) -> bool:
        """Admit one visible request beside one single-lane maintenance task."""

        if (
            self._max_concurrency != 1
            or len(self._tasks) != 1
            or not self._is_interactive(request)
        ):
            return False
        active_chunk_id = next(iter(self._tasks), None)
        active_chunk = self._chunks.get(active_chunk_id or "")
        return active_chunk is not None and self._is_maintenance(active_chunk.request)

    def _running_background_count(self) -> int:
        return len(self._active_background_chunks)

    @staticmethod
    def _fairness_owner(request: RepairRequest) -> str:
        """Return a stable app/window/cell owner for equal-priority rotation."""
        metadata = request.metadata or {}
        structured = [
            str(metadata.get(key) or "").strip()
            for key in ("app_id", "workspace_id", "window_id", "cell_id")
        ]
        if any(structured):
            return "/".join(value or "_" for value in structured)
        demand_scope = str(metadata.get("demand_scope") or "").strip()
        if demand_scope:
            return demand_scope
        return f"{request.requester}:{':'.join(request.series_key)}"

    def _has_fairness_alternative(
        self,
        current: _FetchChunk,
        *,
        lane: tuple[int, bool],
    ) -> bool:
        current_owner = self._fairness_owner(current.request)
        now = time.monotonic()
        for item in self._ready:
            if int(item[0]) != lane[0]:
                continue
            candidate = self._chunks.get(item[3])
            if candidate is None or candidate.eligible_at_monotonic > now:
                continue
            if self._is_background(candidate.request) != lane[1]:
                continue
            state = self._requests.get(candidate.parent_id)
            if state is None or state.stale or state.failed is not None:
                continue
            series = self._series.get(candidate.request.series_key)
            if series is not None and series.active is not None:
                continue
            if self._fairness_owner(candidate.request) != current_owner:
                return True
        return False

    def _has_foreground_active(self) -> bool:
        return bool(self._active_foreground_chunks)

    def _has_foreground_work(
        self,
        extra: Iterable[tuple[int, int, int, str]] = (),
    ) -> bool:
        if self._has_foreground_active():
            return True
        for item in (*self._ready, *tuple(extra)):
            chunk = self._chunks.get(item[3])
            if chunk is None or self._is_background(chunk.request):
                continue
            state = self._requests.get(chunk.parent_id)
            if state is not None and not state.stale and state.failed is None:
                return True
        return False

    def has_foreground_work(self) -> bool:
        """Return whether unresolved user-visible work owns the scheduler.

        Rate-deferred foreground chunks still count: speculative warmup must
        not consume another exchange or worker budget merely because the
        visible request is waiting for its exact Retry-After deadline.
        """

        return self._has_foreground_work()

    def has_backfill_work(self) -> bool:
        """Return whether any runnable/deferred/running repair owns resources.

        Speculative producers use this stronger admission fence so they do not
        add network pressure behind maintenance work merely because no visible
        chart request is currently queued.
        """

        if self._tasks:
            return True
        for item in self._ready:
            chunk = self._chunks.get(item[3])
            if chunk is None:
                continue
            state = self._requests.get(chunk.parent_id)
            if state is not None and not state.stale and state.failed is None:
                return True
        return False

    def foreground_idle_seconds(self) -> float:
        if self.has_foreground_work():
            return 0.0
        if self._last_foreground_activity_at <= 0:
            return float("inf")
        return max(0.0, time.monotonic() - self._last_foreground_activity_at)

    def _schedule_drain(self, delay: float) -> None:
        if self._shutdown:
            return
        delay = max(float(delay), 0.01)
        loop = asyncio.get_running_loop()
        when = loop.time() + delay
        if (
            self._drain_timer is not None
            and not self._drain_timer.cancelled()
            and self._next_drain_at is not None
            and self._next_drain_at <= when
        ):
            return
        self._cancel_drain_timer()
        self._next_drain_at = when
        self._drain_timer = loop.call_later(delay, self._run_scheduled_drain)

    def _run_scheduled_drain(self) -> None:
        self._drain_timer = None
        self._next_drain_at = None
        self._drain()

    def _cancel_drain_timer(self) -> None:
        if self._drain_timer is not None and not self._drain_timer.cancelled():
            self._drain_timer.cancel()
        self._drain_timer = None
        self._next_drain_at = None

    def _next_drain_in_ms(self) -> int | None:
        if self._next_drain_at is None:
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        return max(0, int((self._next_drain_at - loop.time()) * 1000))

    async def _run_chunk(self, chunk: _FetchChunk) -> None:
        foreground_chunk = not self._is_background(chunk.request)
        if foreground_chunk:
            self._active_foreground_chunks.add(chunk.chunk_id)
        else:
            self._active_background_chunks.add(chunk.chunk_id)
        try:
            try:
                outcome = await self._execute(chunk.request)
            except RepairRetryDeferred as exc:
                chunk.request._retry_attempt = exc.attempt + 1
                await self._defer_chunk(chunk, exc)
                return
            except RateLimitDeferred as exc:
                await self._defer_chunk(chunk, exc)
                return
            except asyncio.CancelledError:
                outcome = RepairOutcome(
                    request=chunk.request,
                    status="failed",
                    error="cancelled",
                )
            except Exception as exc:
                logger.exception("Backfill chunk failed for %s", chunk.chunk_id)
                outcome = RepairOutcome(
                    request=chunk.request,
                    status="failed",
                    error=str(exc),
                )
            await self._finish_chunk(chunk, outcome)
        finally:
            if foreground_chunk or not self._is_background(chunk.request):
                self._last_foreground_activity_at = time.monotonic()
            self._active_foreground_chunks.discard(chunk.chunk_id)
            self._active_background_chunks.discard(chunk.chunk_id)
            self._tasks.pop(chunk.chunk_id, None)
            self._drain()

    async def _defer_chunk(
        self,
        chunk: _FetchChunk,
        exc: RateLimitDeferred | RepairRetryDeferred,
    ) -> None:
        """Return deferred work to the ready heap without completing it."""

        state = self._requests.get(chunk.parent_id)
        series = self._series.get(chunk.request.series_key)
        if series is not None and series.active == chunk.parent_id:
            series.active = None

        if state is None:
            self._chunks.pop(chunk.chunk_id, None)
            if series is not None and not series.pending and series.active is None:
                self._series.pop(chunk.request.series_key, None)
            return

        # Cancellation wins every race with deferral. Never let a revoked
        # request reappear when an old quota timer fires.
        if state.cancel_requested:
            self._chunks.pop(chunk.chunk_id, None)
            if series is not None and chunk.parent_id in series.pending:
                series.pending.remove(chunk.parent_id)
            await self._finish_pending_cancellation(
                state,
                self._cancelled_outcome(state),
                series,
            )
            return

        if state.stale or state.failed is not None:
            self._chunks.pop(chunk.chunk_id, None)
            return

        now_monotonic = time.monotonic()
        eligible_at = exc.retry_at_monotonic or (
            now_monotonic + exc.retry_after_seconds
        )
        eligible_at = max(now_monotonic + 0.01, eligible_at)
        retry_at_ms = exc.retry_at_ms or (
            int(time.time() * 1000)
            + max(1, int((eligible_at - now_monotonic) * 1000))
        )
        chunk.eligible_at_monotonic = eligible_at
        chunk.retry_at_ms = int(retry_at_ms)
        chunk.defer_reason = exc.reason
        chunk.rate_limit_bucket = exc.bucket_key
        chunk.defer_count += 1
        if isinstance(exc, RateLimitDeferred):
            self.exchange_rate_limit_deferrals += 1
        if series is None:
            series = self._series.setdefault(
                chunk.request.series_key,
                _SeriesState(),
            )
        if chunk.parent_id not in series.pending:
            series.pending.append(chunk.parent_id)
        self._push_ready(chunk, preserve_sequence=True)
        state.progress_revision += 1
        self._publish_progress(
            state,
            status="rate_limit_deferred" if isinstance(exc, RateLimitDeferred) else "retry_wait",
            details={
                "retry_at_ms": chunk.retry_at_ms,
                "retry_in_ms": max(
                    0,
                    int((eligible_at - now_monotonic) * 1000),
                ),
                "rate_limit_bucket": chunk.rate_limit_bucket,
                "rate_limit_reason": chunk.defer_reason,
                "deferred_chunk_sequence": chunk.sequence,
                "defer_count": chunk.defer_count,
            },
        )
        self._schedule_drain(eligible_at - now_monotonic)

    async def _finish_chunk(self, chunk: _FetchChunk, outcome: RepairOutcome) -> None:
        self._chunks.pop(chunk.chunk_id, None)
        state = self._requests.get(chunk.parent_id)
        series = self._series.get(chunk.request.series_key)
        if state is None:
            if series is not None and series.active == chunk.parent_id:
                series.active = None
            if series is not None and not series.pending and series.active is None:
                self._series.pop(chunk.request.series_key, None)
            return

        skipped_covered = self._discard_chunks_covered_by_report(
            state,
            outcome,
            current_chunk_id=chunk.chunk_id,
        )
        state.completed += 1
        state.attempts += int(outcome.attempts or 0)
        state.bars_loaded += int(outcome.bars_loaded or 0)
        state.outcomes.append(outcome)
        state.progress_revision += 1
        if self._is_failed(outcome.status):
            state.failed = outcome
            self._discard_remaining_chunks(state)
        elif (
            self._newest_first(state.request)
            and self._is_left_terminal_outcome(outcome)
        ):
            # Newest-first requests must not continue scheduling successively
            # older chunks after the provider has confirmed the left edge.
            self._discard_remaining_chunks(state)
            state.completed = state.total

        if state.cancel_requested:
            self._discard_remaining_chunks(state)
            state.completed = state.total

        self._publish_progress(
            state,
            status=("cancelled" if state.cancel_requested else "chunk_completed"),
            details={
                "completed_chunk_sequence": chunk.sequence,
                "completed_chunk_start_ms": chunk.request.start_ms,
                "completed_chunk_end_ms": chunk.request.end_ms,
                "completed_chunk_target_bars": int(
                    (
                        chunk.request.metadata.get("interval_work_plan")
                        or {}
                    ).get("effective_target_bars", 0)
                    or 0
                ),
                "completed_chunk_source_rows": int(
                    (
                        chunk.request.metadata.get("interval_work_plan")
                        or {}
                    ).get("planned_source_rows", 0)
                    or 0
                ),
                "covered_chunks_skipped": skipped_covered,
            },
        )

        # Scheduler coverage is a continuity claim, not merely evidence that
        # an HTTP/reconcile attempt returned without raising.  A partial
        # verification must stay visible to later demand and ledger recovery.
        if outcome.verified_contiguous is True:
            self._coverage.setdefault(chunk.request.series_key, []).append({
                "start_ms": chunk.request.start_ms,
                "end_ms": chunk.request.end_ms,
            })

        if state.failed is not None or state.completed >= state.total:
            final = (
                self._cancelled_outcome(state)
                if state.cancel_requested
                else self._aggregate_outcome(state)
            )
            try:
                if self._shutdown:
                    # A cancellation raised by ``_execute`` is consumed in
                    # ``_run_chunk``.  Starting a new durable finalizer after
                    # that point would no longer be interrupted by the one
                    # shutdown cancellation and could hang shutdown forever.
                    final = RepairOutcome(
                        request=state.request,
                        status="failed",
                        report=final.report,
                        attempts=final.attempts,
                        bars_loaded=final.bars_loaded,
                        verified_contiguous=False,
                        remaining_missing_bars=final.remaining_missing_bars,
                        error="cancelled",
                        retryable=True,
                    )
                else:
                    try:
                        await self._finalize(state.request, final)
                    except asyncio.CancelledError:
                        # Scheduler shutdown may interrupt an awaited durable
                        # finalizer.  Complete the shared waiter before dropping
                        # ownership; otherwise the parent disappears from
                        # ``_requests`` and no shutdown path can resolve it.
                        final = RepairOutcome(
                            request=state.request,
                            status="failed",
                            report=final.report,
                            attempts=final.attempts,
                            bars_loaded=final.bars_loaded,
                            verified_contiguous=False,
                            remaining_missing_bars=final.remaining_missing_bars,
                            error="cancelled",
                            retryable=True,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Backfill parent finalization failed for %s",
                            state.request.request_id,
                        )
                        final = RepairOutcome(
                            request=state.request,
                            status="failed",
                            report=final.report,
                            attempts=final.attempts,
                            bars_loaded=final.bars_loaded,
                            verified_contiguous=False,
                            remaining_missing_bars=final.remaining_missing_bars,
                            error=f"parent finalization failed: {exc}",
                            retryable=True,
                        )
                self._retain_outcome(state.request.request_id, final)
                self._complete(state.request, final)
                self._publish_progress(
                    state,
                    status=("cancelled" if state.cancel_requested else "completed"),
                    terminal=True,
                )
            finally:
                self._requests.pop(state.request.request_id, None)
                # The finalizing parent remains the active series owner until
                # its durable ledger state and shared result are committed.
                # Submissions during that window must dedupe to this request,
                # not start a second physical repair for the same range.
                if series is not None and series.active == chunk.parent_id:
                    series.active = None
                if series is not None and not series.pending and series.active is None:
                    self._series.pop(chunk.request.series_key, None)
        else:
            if series is not None and series.active == chunk.parent_id:
                series.active = None
            if series is not None and state.request.request_id not in series.pending:
                # Remaining chunks are already in the global queue. Keep the parent
                # visible in pending diagnostics while it waits for the next turn.
                series.pending.append(state.request.request_id)

    def _discard_chunks_covered_by_report(
        self,
        state: _RequestState,
        outcome: RepairOutcome,
        *,
        current_chunk_id: str,
    ) -> int:
        """Drop queued pages already covered by a broad archive import.

        Archive objects intentionally write beyond the planner's current
        1,000-source-row chunk.  The exact target-interval written ranges are
        durable evidence that later queued chunks no longer need another
        fetch/reconcile/materialize pass.
        """
        if self._is_failed(outcome.status) or outcome.report is None:
            return 0
        normalized = [
            value
            for raw in list(
                getattr(outcome.report, "written_ranges", None) or []
            )
            if (value := self._normalize_summary_written_range(raw)) is not None
            and value["exchange"] == state.request.exchange.lower().strip()
            and value["market_type"] == state.request.market_type.lower().strip()
            and value["symbol"] == state.request.symbol.upper().strip()
            and value["interval"] == state.request.interval
        ]
        if not normalized:
            return 0
        interval_ms = parse_interval_ms(state.request.interval) or 1
        ordered = sorted(
            (int(item["start_ms"]), int(item["end_ms"]))
            for item in normalized
        )
        merged: list[tuple[int, int]] = []
        for start_ms, end_ms in ordered:
            if not merged or start_ms > merged[-1][1] + interval_ms:
                merged.append((start_ms, end_ms))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))

        removed: set[str] = set()
        for chunk_id in state.chunk_ids:
            if chunk_id == current_chunk_id or chunk_id in self._tasks:
                continue
            pending = self._chunks.get(chunk_id)
            if pending is None or pending.parent_id != state.request.request_id:
                continue
            if any(
                start_ms <= pending.request.start_ms
                and pending.request.end_ms <= end_ms
                for start_ms, end_ms in merged
            ):
                removed.add(chunk_id)
                self._chunks.pop(chunk_id, None)
        if not removed:
            return 0
        state.chunk_ids = [
            chunk_id for chunk_id in state.chunk_ids if chunk_id not in removed
        ]
        self._ready = [item for item in self._ready if item[3] not in removed]
        heapq.heapify(self._ready)
        self.covered_chunks_skipped += len(removed)
        coverage = self._coverage.setdefault(state.request.series_key, [])
        coverage.extend(
            {"start_ms": start_ms, "end_ms": end_ms}
            for start_ms, end_ms in merged
        )
        return len(removed)

    @staticmethod
    def _normalize_summary_written_range(raw: Any) -> dict[str, Any] | None:
        def _value(key: str, default: Any = None) -> Any:
            if isinstance(raw, dict):
                return raw.get(key, default)
            return getattr(raw, key, default)

        start_ms = _value("start_ms")
        end_ms = _value("end_ms")
        if start_ms is None or end_ms is None:
            return None
        return {
            "exchange": str(_value("exchange", "binance")).lower().strip(),
            "market_type": str(_value("market_type", "spot")).lower().strip(),
            "symbol": str(_value("symbol", "")).upper().strip(),
            "interval": _value("interval", ""),
            "start_ms": int(start_ms),
            "end_ms": int(end_ms),
        }

    def _retain_outcome(self, request_id: str, outcome: RepairOutcome) -> None:
        self._outcomes[request_id] = outcome
        while len(self._outcomes) > self._max_retained_outcomes:
            oldest_request_id = next(iter(self._outcomes))
            self._outcomes.pop(oldest_request_id, None)

    def _discard_remaining_chunks(self, state: _RequestState) -> None:
        discarded: set[str] = set()
        for chunk_id in state.chunk_ids:
            if chunk_id not in self._tasks:
                self._chunks.pop(chunk_id, None)
                discarded.add(chunk_id)
        if discarded:
            self._ready = [
                item for item in self._ready if item[3] not in discarded
            ]
            heapq.heapify(self._ready)
        state.stale = True

    def _aggregate_outcome(self, state: _RequestState) -> RepairOutcome:
        if state.failed is not None:
            return RepairOutcome(
                request=state.request,
                status=state.failed.status,
                report=state.failed.report,
                attempts=state.attempts or state.failed.attempts,
                bars_loaded=state.bars_loaded,
                verified_contiguous=False,
                remaining_missing_bars=state.failed.remaining_missing_bars,
                error=state.failed.error,
                terminal_reason=state.failed.terminal_reason,
                exhausted_before_ms=state.failed.exhausted_before_ms,
                retryable=state.failed.retryable,
            )

        last = state.outcomes[-1] if state.outcomes else None
        all_chunks_verified = (
            len(state.outcomes) == state.total
            and not state.stale
            and all(
                outcome.verified_contiguous is True
                for outcome in state.outcomes
            )
        )
        any_chunk_failed_verification = any(
            outcome.verified_contiguous is False
            for outcome in state.outcomes
        )
        missing_values = [
            outcome.remaining_missing_bars
            for outcome in state.outcomes
            if outcome.remaining_missing_bars is not None
        ]
        return RepairOutcome(
            request=state.request,
            status=last.status if last is not None else "completed",
            report=last.report if last is not None else None,
            attempts=state.attempts,
            bars_loaded=state.bars_loaded,
            verified_contiguous=(
                True
                if all_chunks_verified
                else (False if any_chunk_failed_verification else None)
            ),
            remaining_missing_bars=(
                sum(int(value or 0) for value in missing_values)
                if missing_values
                else None
            ),
            error=None,
            terminal_reason=(
                next(
                    (
                        outcome.terminal_reason
                        for outcome in reversed(state.outcomes)
                        if outcome.terminal_reason
                    ),
                    None,
                )
            ),
            exhausted_before_ms=(
                next(
                    (
                        outcome.exhausted_before_ms
                        for outcome in reversed(state.outcomes)
                        if outcome.exhausted_before_ms is not None
                    ),
                    None,
                )
            ),
            retryable=any(outcome.retryable for outcome in state.outcomes),
        )

    def _bucket_for(self, request: RepairRequest) -> _TokenBucket:
        key = f"{request.exchange.lower().strip()}:{request.market_type.lower().strip()}"
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _TokenBucket(key=key)
            self._buckets[key] = bucket
        return bucket

    @staticmethod
    def _is_left_terminal_outcome(outcome: RepairOutcome) -> bool:
        return (
            not outcome.retryable
            and outcome.terminal_reason in {
                "provider_exhausted",
                BoundaryReason.SOURCE_EXHAUSTED.value,
                BoundaryReason.DATA_START.value,
                BoundaryReason.LISTING.value,
                BoundaryReason.UPSTREAM_START.value,
                BoundaryReason.PROVIDER_RETENTION.value,
            }
        )

    def _state_snapshot(
        self,
        series: str,
        state: _RequestState,
        *,
        active: bool,
    ) -> dict[str, Any]:
        now_monotonic = time.monotonic()
        deferred = [
            chunk
            for chunk_id in state.chunk_ids
            if (chunk := self._chunks.get(chunk_id)) is not None
            and chunk.eligible_at_monotonic > now_monotonic
        ]
        payload = {
            "series": series,
            "request_id": state.request.request_id,
            "reason": state.request.reason,
            "priority": state.request.priority,
            "requester": state.request.requester,
            "fairness_owner": self._fairness_owner(state.request),
            "range_start_ms": state.request.start_ms,
            "range_end_ms": state.request.end_ms,
            "total_chunks": state.total,
            "completed_chunks": state.completed,
            "pending_chunks": state.pending_count,
            "active": active,
            "progress_revision": state.progress_revision,
            "demand_count": len(state.demand_leases),
            "persistent_interest": state.persistent_interest,
            "cancel_requested": state.cancel_requested,
            "deferred_chunks": len(deferred),
            "retry_at_ms": min(
                (
                    int(chunk.retry_at_ms)
                    for chunk in deferred
                    if chunk.retry_at_ms is not None
                ),
                default=None,
            ),
            "rate_limit_buckets": sorted({
                str(chunk.rate_limit_bucket)
                for chunk in deferred
                if chunk.rate_limit_bucket
            }),
        }
        metadata = state.request.metadata or {}
        for key in (
            "focus_scope",
            "subscription_tier",
            "current_interval",
            "demand_scope",
            "demand_generation",
            "interval_work_plan",
        ):
            if key in metadata:
                payload[key] = metadata[key]
        return payload

    @staticmethod
    def _outcome_snapshot(outcome: RepairOutcome) -> dict[str, Any]:
        return {
            "status": repair_status_value(outcome.status),
            "reason": outcome.request.reason,
            "priority": outcome.request.priority,
            "requester": outcome.request.requester,
            "range_start_ms": outcome.request.start_ms,
            "range_end_ms": outcome.request.end_ms,
            "attempts": outcome.attempts,
            "bars_loaded": outcome.bars_loaded,
            "verified_contiguous": outcome.verified_contiguous,
            "remaining_missing_bars": outcome.remaining_missing_bars,
            "error": outcome.error,
            "terminal_reason": outcome.terminal_reason,
            "exhausted_before_ms": outcome.exhausted_before_ms,
            "retryable": outcome.retryable,
        }

    @staticmethod
    def _covers(existing: RepairRequest, new: RepairRequest) -> bool:
        return existing.start_ms <= new.start_ms and existing.end_ms >= new.end_ms

    @classmethod
    def _should_merge(cls, existing: RepairRequest, new: RepairRequest) -> bool:
        interval_ms = parse_interval_ms(existing.interval) or 60_000
        tolerance = interval_ms * 3
        return (
            existing.series_key == new.series_key
            and cls._can_coalesce(existing, new)
            and existing.start_ms <= new.end_ms + tolerance
            and new.start_ms <= existing.end_ms + tolerance
        )

    @staticmethod
    def _can_coalesce(existing: RepairRequest, new: RepairRequest) -> bool:
        """Keep active hydration from widening or owning foreground work.

        Other background parents retain their established foreground-promotion
        behavior. ``active_history_hydration`` is a dedicated cache-fill lane:
        it may dedupe/merge only with the same lane, never with a viewport
        parent whose response latency must remain bounded to visible demand.
        """

        def _is_active_hydration(request: RepairRequest) -> bool:
            return "active_history_hydration" in {
                part.strip()
                for part in str(request.reason or "").split("+")
                if part.strip()
            }

        return _is_active_hydration(existing) == _is_active_hydration(new)

    @staticmethod
    def _is_failed(status: Any) -> bool:
        return repair_status_value(status) == "failed"
