"""Request admission for BackfillCoordinator: requests, demand leases and retained outcomes.

Split out of ``backfill_coordinator.py`` without changes (ADR-DATA-001 §8,
S4). ``BackfillCoordinator`` inherits this mixin; the state it reads and
writes is created in ``BackfillCoordinator.__init__``.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.data_engine.series_identity import identity_from_metadata

from .backfill_contracts import RepairOutcome, RepairRequest

_REQUEST_ID_ALIAS_HISTORY_LIMIT = 2048


class BackfillAdmission:
    """Public request and demand API, request ids and retained outcomes."""

    def trigger(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        exchange: str = "binance",
        market_type: str = "spot",
        *,
        reason: str = "query_gap",
        priority: int | None = None,
        requester: str = "query",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Synchronous QueryEngine-compatible callback."""
        return self.request(RepairRequest(
            symbol=symbol,
            interval=interval,
            start_ms=int(start_ms),
            end_ms=int(end_ms),
            exchange=exchange,
            market_type=market_type,
            reason=reason,
            priority=priority,
            requester=requester,
            metadata=metadata or {},
        ))

    def request(self, request: RepairRequest) -> str:
        """Submit a repair request and return its request id."""
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                raise RuntimeError("BackfillCoordinator requires an event loop")

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            return self._request_in_loop(request)[0]

        self._loop.call_soon_threadsafe(self._request_in_loop, request)
        return request.request_id

    async def request_and_wait(self, request: RepairRequest) -> RepairOutcome:
        _request_id, future = self._request_in_loop(request)
        return await asyncio.shield(future)

    def progress_for_request(self, request_id: str) -> dict[str, Any] | None:
        canonical_id = self._canonical_request_id(request_id)
        snapshot = self._progress_snapshots.get(canonical_id)
        return dict(snapshot) if snapshot is not None else None

    async def wait_for_progress(
        self,
        request_id: str,
        *,
        after_revision: int = 0,
    ) -> dict[str, Any] | None:
        """Wait for the next physical chunk revision, not the whole parent."""
        canonical_id = self._canonical_request_id(request_id)
        snapshot = self._progress_snapshots.get(canonical_id)
        if snapshot is not None and (
            int(snapshot.get("revision", 0)) > int(after_revision)
            or bool(snapshot.get("terminal"))
        ):
            return dict(snapshot)
        if canonical_id in self._outcomes:
            return dict(snapshot) if snapshot is not None else None

        waiter: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        waiters = self._progress_waiters.setdefault(canonical_id, set())
        waiters.add(waiter)
        snapshot = self._progress_snapshots.get(canonical_id)
        if snapshot is not None and (
            int(snapshot.get("revision", 0)) > int(after_revision)
            or bool(snapshot.get("terminal"))
        ):
            waiter.set_result(dict(snapshot))
        try:
            while True:
                observed = await waiter
                if (
                    int(observed.get("revision", 0)) > int(after_revision)
                    or bool(observed.get("terminal"))
                ):
                    return observed
        finally:
            waiters.discard(waiter)
            if not waiters:
                self._progress_waiters.pop(canonical_id, None)

    async def acquire_demand(
        self,
        request_id: str,
        *,
        owner_id: str,
        scope: str | None = None,
        generation: int | None = None,
    ) -> bool:
        canonical_id = self._canonical_request_id(request_id)
        normalized_scope = str(scope or "").strip() or None
        normalized_generation = (
            max(0, int(generation))
            if generation is not None
            else None
        )
        stale_generation = bool(
            normalized_scope is not None
            and normalized_generation is not None
            and (
                current := self._scope_generations.get(normalized_scope)
            ) is not None
            and normalized_generation < current
        )
        acquired = self._scheduler.acquire_demand(
            canonical_id,
            owner_id=owner_id,
            scope=normalized_scope,
            generation=normalized_generation,
        )
        if acquired and stale_generation:
            # Close the race where generation N schedules its repair after
            # generation N+1 already advanced the pane scope. Acquiring then
            # immediately releasing lets the scheduler cancel the otherwise
            # unowned request with the same pending/chunk-boundary semantics.
            await self._scheduler.release_demand(
                canonical_id,
                owner_id=owner_id,
                cancel_if_unobserved=True,
                reason=(
                    f"scope_stale:{normalized_scope}:{normalized_generation}"
                ),
            )
            return False
        return acquired

    async def release_demand(
        self,
        request_id: str,
        *,
        owner_id: str,
        cancel_if_unobserved: bool = True,
        reason: str = "demand_released",
    ) -> bool:
        canonical_id = self._canonical_request_id(request_id)
        return await self._scheduler.release_demand(
            canonical_id,
            owner_id=owner_id,
            cancel_if_unobserved=cancel_if_unobserved,
            reason=reason,
        )

    async def advance_demand_scope(self, scope: str, generation: int) -> int:
        normalized_scope = str(scope or "").strip()
        if not normalized_scope:
            return 0
        normalized_generation = max(0, int(generation))
        current = self._scope_generations.get(normalized_scope)
        if current is not None and normalized_generation <= current:
            return 0
        self._scope_generations.pop(normalized_scope, None)
        self._scope_generations[normalized_scope] = normalized_generation
        while len(self._scope_generations) > _REQUEST_ID_ALIAS_HISTORY_LIMIT:
            self._scope_generations.popitem(last=False)
        return await self._scheduler.supersede_scope(
            normalized_scope,
            normalized_generation,
        )

    async def revoke_demand_owner(
        self,
        owner_id: str,
        *,
        reason: str = "demand_owner_revoked",
    ) -> int:
        normalized_owner = str(owner_id or "").strip()
        if not normalized_owner:
            return 0
        self._revoked_demand_owners.pop(normalized_owner, None)
        self._revoked_demand_owners[normalized_owner] = str(reason or "demand_owner_revoked")
        while len(self._revoked_demand_owners) > _REQUEST_ID_ALIAS_HISTORY_LIMIT:
            self._revoked_demand_owners.popitem(last=False)
        return await self._scheduler.revoke_owner(
            normalized_owner,
            reason=str(reason or "demand_owner_revoked"),
        )

    def is_demand_generation_current(self, scope: str, generation: int) -> bool:
        normalized_scope = str(scope or "").strip()
        if not normalized_scope:
            return True
        current = self._scope_generations.get(normalized_scope)
        return current is None or int(generation) >= current

    def _request_in_loop(
        self,
        request: RepairRequest,
    ) -> tuple[str, asyncio.Future[RepairOutcome]]:
        if self._shutdown:
            raise RuntimeError("BackfillCoordinator is shut down")

        store = getattr(self._storage, "revision_store", None)
        if store is not None:
            from app.data_engine.storage.revisions import acquisition_delete_floor
            request.metadata.setdefault("acquisition_revision", acquisition_delete_floor(store.observed_revision))

        self._prune_retained_state()
        rejected_reason = self._demand_rejection_reason(request)
        if rejected_reason is not None:
            future = self._future_for(request)
            outcome = RepairOutcome(
                request=request,
                status="cancelled",
                verified_contiguous=False,
                error=rejected_reason,
                terminal_reason="demand_superseded",
                retryable=False,
            )
            self._complete(request, outcome)
            self._note_progress(request, {
                "request_id": request.request_id,
                "revision": 0,
                "status": "cancelled",
                "terminal": True,
                "completed_chunks": 0,
                "total_chunks": 0,
                "pending_chunks": 0,
                "bars_loaded": 0,
                "priority": request.priority,
                "demand_count": 0,
                "cancel_requested": True,
                "updated_at_ms": int(time.time() * 1000),
            })
            return request.request_id, future
        suppression = self.get_repair_suppression(
            request.symbol,
            request.interval,
            request.start_ms,
            request.end_ms,
            request.exchange,
            request.market_type,
            series_identity=identity_from_metadata(request.exchange, request.metadata),
        )
        if suppression is not None:
            future = self._future_for(request)
            outcome = RepairOutcome(
                request=request,
                status="suppressed",
                verified_contiguous=False,
                terminal_reason=f"gap_ledger_{suppression['ledger_status']}",
                retryable=False,
                retry_at_ms=suppression.get("retry_at_ms"),
                suppressed=True,
                ledger_status=str(suppression["ledger_status"]),
                suppression=dict(suppression),
            )
            self._complete(request, outcome)
            return request.request_id, future
        prepared = self._history_planner.prepare(request)
        if self._history_planner.source_second_close_delay(request, prepared.plan) is not None:
            # Preserve the exact source gap, including a temporarily forming
            # tail. _run_with_retries defers it without occupying a worker.
            prepared.request = request
        if prepared.request is None:
            self._ledger_mark_history_deferred(request, prepared.plan)
            future = self._future_for(request)
            outcome = self._history_planner.no_fetch_outcome(request, prepared.plan)
            self._complete(request, outcome)
            return request.request_id, future

        canonical_id, future = self._scheduler.submit(prepared.request)
        if canonical_id != request.request_id:
            self._request_id_aliases[request.request_id] = canonical_id
            self._request_id_alias_expires_at[request.request_id] = None
            self._prune_retained_state()
        return canonical_id, future

    def _demand_rejection_reason(self, request: RepairRequest) -> str | None:
        metadata = request.metadata or {}
        owner_id = str(metadata.get("demand_owner_id") or "").strip()
        if owner_id and owner_id in self._revoked_demand_owners:
            return self._revoked_demand_owners[owner_id]
        scope = str(metadata.get("demand_scope") or "").strip()
        generation_raw = metadata.get("demand_generation")
        if not scope or generation_raw is None:
            return None
        try:
            generation = int(generation_raw)
        except (TypeError, ValueError):
            return "invalid_demand_generation"
        current = self._scope_generations.get(scope)
        if current is not None and generation < current:
            return f"scope_superseded:{scope}:{generation}<{current}"
        return None


    def _canonical_request_id(self, request_id: str) -> str:
        canonical_id = request_id
        seen: set[str] = set()
        while canonical_id not in seen:
            seen.add(canonical_id)
            next_id = self._request_id_aliases.get(canonical_id)
            if next_id is None:
                break
            canonical_id = next_id
        return canonical_id

    def _prune_retained_state(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        expired_outcomes = [
            request_id
            for request_id, expires_at in self._outcome_expires_at.items()
            if expires_at <= current
        ]
        for request_id in expired_outcomes:
            self._drop_retained_outcome(request_id)

        expired_aliases = [
            request_id
            for request_id, expires_at in self._request_id_alias_expires_at.items()
            if expires_at is not None and expires_at <= current
        ]
        for request_id in expired_aliases:
            self._drop_request_id_alias(request_id)

        while len(self._outcomes) > self._max_retained_outcomes:
            self._drop_retained_outcome(next(iter(self._outcomes)))
        while len(self._request_id_aliases) > self._max_request_id_aliases:
            self._drop_request_id_alias(next(iter(self._request_id_aliases)))

    def _drop_retained_outcome(self, request_id: str) -> None:
        self._outcomes.pop(request_id, None)
        self._outcome_expires_at.pop(request_id, None)
        aliases = [
            alias_id
            for alias_id in self._request_id_aliases
            if self._canonical_request_id(alias_id) == request_id
        ]
        for alias_id in aliases:
            self._drop_request_id_alias(alias_id)

    def _drop_request_id_alias(self, request_id: str) -> None:
        self._request_id_aliases.pop(request_id, None)
        self._request_id_alias_expires_at.pop(request_id, None)

    def _retain_completed_outcome(
        self,
        request: RepairRequest,
        outcome: RepairOutcome,
    ) -> None:
        now = time.monotonic()
        expires_at = now + self._retained_outcome_ttl_seconds
        self._outcomes[request.request_id] = outcome
        self._outcome_expires_at[request.request_id] = expires_at
        aliases = [
            alias_id
            for alias_id in self._request_id_aliases
            if self._canonical_request_id(alias_id) == request.request_id
        ]
        for alias_id in aliases:
            self._request_id_alias_expires_at[alias_id] = expires_at
        self._prune_retained_state(now)

    def _future_for(self, request: RepairRequest) -> asyncio.Future[RepairOutcome]:
        future = self._futures.get(request.request_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._futures[request.request_id] = future
        return future
