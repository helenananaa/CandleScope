"""Recoverable native/derived manual-history job runner and exact sealer."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from app.core.bounded_executor import ExecutorBusyError
from app.core.executors import run_storage
from app.data_engine.manual_history.models import (
    JobState,
    JobTargetState,
    ManualHistoryCreateSpec,
    ManualHistoryTargetSpec,
    RouteKind,
)
from app.data_engine.manual_history.planner import ManualHistoryPlanner
from app.data_engine.manual_history.repository import ManualHistoryRepository
from app.data_engine.storage.klines_repo import KlinesRepoAdapter

logger = logging.getLogger("candlescope.manual_history")

FetchNative = Callable[..., Awaitable[int]]
VerifyRange = Callable[..., dict[str, Any]]
StoragePressure = Callable[[], Mapping[str, Any]]
T = TypeVar("T")

# Enqueue and cancel wake the runner at once. The fallback rescan picks up
# storage-blocked jobs once pressure clears (no event announces that) and any
# job state changed outside this service.
IDLE_POLL_SECONDS = 5.0
_BUSY_RETRY_SECONDS = 0.05


class _JobCancelled(RuntimeError):
    pass


class _StorageBlocked(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ManualHistoryService:
    def __init__(
        self,
        *,
        repository: ManualHistoryRepository,
        planner: ManualHistoryPlanner | None = None,
        data_manager: Any | None = None,
        coordinator: Any | None = None,
        storage: KlinesRepoAdapter | None = None,
        fetch_native: FetchNative | None = None,
        verify_range: VerifyRange | None = None,
        enabled: bool = False,
        clock_ms: Callable[[], int] | None = None,
        storage_pressure: StoragePressure | None = None,
        idle_poll_seconds: float = IDLE_POLL_SECONDS,
    ) -> None:
        self.repository = repository
        self.planner = planner or ManualHistoryPlanner()
        self.data_manager = data_manager
        self.coordinator = coordinator
        self.storage = storage or KlinesRepoAdapter()
        self._fetch_native = fetch_native
        self._verify_range = verify_range or self.storage.verify_contiguous_range
        self.enabled = bool(enabled)
        self._clock_ms = clock_ms
        self._disk_free_bytes: Callable[[], int | None] | None = None
        self._storage_pressure = storage_pressure
        self._idle_poll_seconds = float(idle_poll_seconds)
        self._runner_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._active = asyncio.Lock()
        self._durable_lock = asyncio.Lock()
        self._active_job_ids: set[str] = set()

    def _now_ms(self) -> int:
        if self._clock_ms is not None:
            return int(self._clock_ms())
        return int(time.time() * 1000)

    async def _off_loop(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run blocking SQLite work on the storage executor.

        The runner is background work, so a full executor is backpressure:
        wait for capacity instead of failing the job or ending the loop.
        """
        while True:
            try:
                return await run_storage(func, *args, **kwargs)
            except ExecutorBusyError:
                await asyncio.sleep(_BUSY_RETRY_SECONDS)

    async def _durable(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run one check-then-transition span off the loop, one span at a time.

        These spans were atomic while they ran synchronously on the event loop.
        The lock keeps a cancel from landing between a span's check and its
        transition now that they run on storage threads.
        """
        async with self._durable_lock:
            return await self._off_loop(func, *args, **kwargs)

    def _wake_runner(self) -> None:
        """Rescan durable jobs now instead of at the next fallback poll."""
        self._wake.set()

    def _seal_end_open_ms(self, interval: str, *, fallback: int) -> int:
        from app.data_engine.interval_policy import last_closed_bar_open_ms

        closed = last_closed_bar_open_ms(self._now_ms(), interval)
        if closed is None:
            return int(fallback)
        return max(int(fallback), int(closed))

    def recover_jobs(self) -> tuple[Any, ...]:
        recovered = []
        for job in self.repository.list_recoverable_jobs():
            if job.state in {JobState.RUNNING, JobState.SEALING}:
                self.repository.increment_recovery_count(job.job_id)
                self.repository.reset_recoverable_targets(job.job_id)
                recovered.append(
                    self.repository.cas_job_state(
                        job.job_id,
                        from_state=job.state,
                        to_state=JobState.QUEUED,
                        stage="recovered",
                    )
                )
            elif job.state is JobState.BLOCKED_STORAGE and self._storage_block_reason() is None:
                self.repository.reset_recoverable_targets(job.job_id)
                recovered.append(
                    self.repository.cas_job_state(
                        job.job_id,
                        from_state=JobState.BLOCKED_STORAGE,
                        to_state=JobState.QUEUED,
                        stage="storage_recovered",
                    )
                )
            elif job.state is JobState.CANCELLING:
                recovered.append(self._finalize_cancellation(job.job_id))
            else:
                recovered.append(job)
        return tuple(recovered)

    async def cancel_job(self, job_id: str) -> Any:
        # An HTTP caller: a full storage executor raises ExecutorBusyError
        # (a retryable 503) instead of waiting for capacity like the runner.
        async with self._durable_lock:
            job, settled = await run_storage(self._request_cancellation, job_id)
        if settled:
            return job
        self._wake_runner()
        coordinator = self.coordinator
        revoke_owner = getattr(coordinator, "revoke_demand_owner", None)
        if callable(revoke_owner):
            await revoke_owner(
                self._demand_owner_id(job_id),
                reason="manual_history_job_cancelled",
            )
        async with self._durable_lock:
            if job_id in self._active_job_ids:
                return await run_storage(self.repository.get_job, job_id)
            return await run_storage(self._finalize_cancellation, job_id)

    def _request_cancellation(self, job_id: str) -> tuple[Any, bool]:
        """Move a live job to CANCELLING; the flag is true when it had already ended."""
        job = self.repository.get_job(job_id)
        if job.state in {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.PARTIAL,
        }:
            return job, True
        if job.state is not JobState.CANCELLING:
            job = self.repository.cas_job_state(
                job_id,
                from_state=job.state,
                to_state=JobState.CANCELLING,
                stage="cancelling",
            )
        return job, False

    def _finalize_cancellation(self, job_id: str) -> Any:
        finalized = self.repository.finalize_job_cancellation(job_id)
        reload = getattr(self.data_manager, "reload_durable_protections", None)
        if callable(reload):
            reload(repository=self.repository)
        return finalized

    @staticmethod
    def _demand_owner_id(job_id: str) -> str:
        return f"manual-history:{job_id}"

    def _storage_block_reason(self) -> str | None:
        if self._storage_pressure is not None:
            snapshot = dict(self._storage_pressure() or {})
            if bool(snapshot.get("disk_free_critical")):
                return "disk_free_critical"
            if str(snapshot.get("level") or "").lower() in {
                "critical",
                "over_budget",
            }:
                return "sqlite_budget_critical"
            if bool(snapshot.get("blocked")):
                return str(snapshot.get("reason") or "storage_blocked")
        free = None if self._disk_free_bytes is None else self._disk_free_bytes()
        if free is not None and int(free) <= 0:
            return "disk_critical"
        return None

    def _raise_if_cancelled(self, job_id: str) -> None:
        job = self.repository.get_job(job_id)
        if job.cancel_requested or job.state is JobState.CANCELLING:
            raise _JobCancelled("cancel_requested")

    def _raise_if_interrupted(self, job_id: str) -> None:
        self._raise_if_cancelled(job_id)
        reason = self._storage_block_reason()
        if reason is not None:
            raise _StorageBlocked(reason)

    def _block_job(self, job_id: str, reason: str) -> Any:
        job = self.repository.get_job(job_id)
        for target in self.repository.list_job_targets(job_id):
            if target.state in {
                JobTargetState.READY,
                JobTargetState.FAILED,
                JobTargetState.CANCELLED,
                JobTargetState.BLOCKED_STORAGE,
            }:
                continue
            try:
                self.repository.cas_job_target_state(
                    job_id,
                    target.symbol,
                    target.canonical_interval,
                    from_state=target.state,
                    to_state=JobTargetState.BLOCKED_STORAGE,
                    last_error=reason,
                )
            except Exception:
                logger.exception("Failed to mark manual-history target storage-blocked")
        if job.state is JobState.BLOCKED_STORAGE:
            return job
        return self.repository.cas_job_state(
            job_id,
            from_state=job.state,
            to_state=JobState.BLOCKED_STORAGE,
            stage="blocked_storage",
            last_error=reason,
        )

    async def start(self) -> None:
        if self._runner_task is not None:
            return
        await self._durable(self.recover_jobs)
        self._stop.clear()
        self._runner_task = asyncio.create_task(self._run_loop(), name="manual-history-runner")

    async def stop(self) -> None:
        self._stop.set()
        self._wake_runner()
        task = self._runner_task
        self._runner_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def create_from_plan(
        self,
        plan: dict[str, Any],
        *,
        idempotency_key: str,
        collection_id: str | None = None,
        job_id: str | None = None,
    ) -> Any:
        if not plan.get("can_start"):
            raise ValueError("plan cannot start: " + ",".join(plan.get("blocking_reasons") or []))
        selection = plan["selection"]
        targets = []
        for item in plan["targets"]:
            if item.get("error"):
                raise ValueError(item["error"])
            targets.append(
                ManualHistoryTargetSpec(
                    symbol=item["symbol"],
                    requested_interval=item["requested_interval"],
                    canonical_interval=item["canonical_interval"],
                    route_kind=RouteKind(item["route_kind"]),
                    source_interval=item["source_interval"],
                    effective_start_ms=int(item["effective_start_ms"]),
                    initial_end_open_ms=int(item["initial_end_open_ms"]),
                    estimated_rows=item.get("estimated_target_rows"),
                    expected_rows=item.get("estimated_target_rows"),
                    boundary_reason=item.get("boundary_reason"),
                )
            )
        spec = ManualHistoryCreateSpec(
            collection_id=collection_id or f"col:{uuid.uuid4()}",
            job_id=job_id or f"job:{uuid.uuid4()}",
            exchange=selection["exchange"],
            market_type=selection["market_type"],
            requested_start_ms=int(selection["requested_start_ms"]),
            idempotency_key=idempotency_key,
            request_hash=str(plan["plan_hash"]),
            plan_hash=str(plan["plan_hash"]),
            targets=tuple(targets),
            estimated_db_bytes=(plan.get("storage") or {}).get("estimated_db_growth_bytes"),
            estimated_temp_bytes=(plan.get("storage") or {}).get("estimated_temp_bytes"),
            reserved_bytes=sum(
                max(0, int(value or 0))
                for value in (
                    (plan.get("storage") or {}).get("estimated_db_growth_bytes"),
                    (plan.get("storage") or {}).get("estimated_temp_bytes"),
                )
            ),
        )
        guarded_create = getattr(
            self.data_manager,
            "create_manual_history_collection",
            None,
        )
        if callable(guarded_create):
            created = guarded_create(self.repository, spec)
        else:
            created = self.repository.create_collection_and_job(spec)
        self._wake_runner()
        return created

    def release_collection(self, collection_id: str) -> Any:
        guarded_release = getattr(
            self.data_manager,
            "release_manual_history_collection",
            None,
        )
        if callable(guarded_release):
            return guarded_release(self.repository, collection_id)
        return self.repository.release_collection(collection_id)

    async def run_job(self, job_id: str) -> Any:
        async with self._active:
            self._active_job_ids.add(job_id)
            try:
                job, collection, targets = await self._durable(self._begin_job, job_id)
                if collection is None:
                    return job
                ready = 0
                failed = 0
                groups: dict[tuple[str, str], list[Any]] = {}
                for target in targets:
                    if target.state is JobTargetState.READY:
                        ready += 1
                        continue
                    groups.setdefault((target.symbol, target.source_interval), []).append(target)
                for (_symbol, source_interval), group in groups.items():
                    await self._durable(self._raise_if_interrupted, job_id)
                    native = [
                        item for item in group
                        if item.canonical_interval == source_interval
                    ]
                    derived = [
                        item for item in group
                        if item.canonical_interval != source_interval
                    ]
                    try:
                        if native:
                            await self._run_native_target(collection, job, native[0])
                            ready += 1
                        elif derived:
                            await self._fetch_source_group(
                                collection, job, derived[0], source_interval=source_interval
                            )
                        for target in derived:
                            await self._durable(self._raise_if_interrupted, job_id)
                            try:
                                await self._run_derived_target(collection, job, target)
                                ready += 1
                            except (_JobCancelled, _StorageBlocked):
                                raise
                            except Exception as exc:
                                failed += await self._durable(self._fail_targets, job_id, [target], exc)
                                logger.warning("manual history derived target failed: %s", exc)
                    except (_JobCancelled, _StorageBlocked):
                        raise
                    except Exception as exc:
                        logger.warning("manual history source group failed: %s", exc)
                        failed += await self._durable(self._fail_targets, job_id, group, exc)
                return await self._durable(self._complete_job, job_id, ready=ready, failed=failed)
            except _JobCancelled:
                return await self._durable(self._cancel_interrupted_job, job_id)
            except _StorageBlocked as exc:
                return await self._durable(self._settle_storage_block, job_id, exc.reason)
            finally:
                self._active_job_ids.discard(job_id)

    def _begin_job(self, job_id: str) -> tuple[Any, Any, tuple[Any, ...]]:
        """Admit a job to RUNNING; collection is None when the job settled here instead."""
        job = self.repository.get_job(job_id)
        if job.cancel_requested or job.state is JobState.CANCELLING:
            return self._finalize_cancellation(job_id), None, ()
        reason = self._storage_block_reason()
        if reason is not None:
            return self._block_job(job_id, reason), None, ()
        if job.state is JobState.BLOCKED_STORAGE:
            self.repository.reset_recoverable_targets(job_id)
            job = self.repository.cas_job_state(
                job_id,
                from_state=JobState.BLOCKED_STORAGE,
                to_state=JobState.QUEUED,
                stage="storage_recovered",
            )
        if job.state is JobState.QUEUED:
            job = self.repository.cas_job_state(
                job_id,
                from_state=JobState.QUEUED,
                to_state=JobState.RUNNING,
                stage="fetching",
            )
        if job.state is not JobState.RUNNING:
            return job, None, ()
        collection = self.repository.get_collection(job.collection_id)
        return job, collection, self.repository.list_job_targets(job_id)

    def _complete_job(self, job_id: str, *, ready: int, failed: int) -> Any:
        self._raise_if_interrupted(job_id)
        if failed and ready:
            return self.repository.cas_job_state(
                job_id,
                from_state=JobState.RUNNING,
                to_state=JobState.PARTIAL,
                stage="done",
            )
        if failed:
            return self.repository.cas_job_state(
                job_id,
                from_state=JobState.RUNNING,
                to_state=JobState.FAILED,
                stage="done",
                last_error="no targets ready",
            )
        sealing = self.repository.cas_job_state(
            job_id,
            from_state=JobState.RUNNING,
            to_state=JobState.SEALING,
            stage="sealing",
        )
        self._raise_if_interrupted(job_id)
        return self.repository.cas_job_state(
            sealing.job_id,
            from_state=JobState.SEALING,
            to_state=JobState.SUCCEEDED,
            stage="done",
        )

    def _cancel_interrupted_job(self, job_id: str) -> Any:
        current = self.repository.get_job(job_id)
        if current.state is not JobState.CANCELLING:
            self.repository.cas_job_state(
                job_id,
                from_state=current.state,
                to_state=JobState.CANCELLING,
                stage="cancelling",
            )
        return self._finalize_cancellation(job_id)

    def _settle_storage_block(self, job_id: str, reason: str) -> Any:
        # A cancel can land between the span that saw the pressure and this
        # one. It wins, as in _raise_if_interrupted (CANCELLING cannot block).
        try:
            self._raise_if_cancelled(job_id)
        except _JobCancelled:
            return self._cancel_interrupted_job(job_id)
        return self._block_job(job_id, reason)

    def _fail_targets(self, job_id: str, targets: list[Any], exc: Exception) -> int:
        return sum(self._fail_target(job_id, target, exc) for target in targets)

    def _fail_target(self, job_id: str, target: Any, exc: Exception) -> int:
        current = self.repository.list_job_targets(job_id)
        current_target = next(
            item for item in current
            if item.symbol == target.symbol
            and item.canonical_interval == target.canonical_interval
        )
        if current_target.state in {
            JobTargetState.FAILED,
            JobTargetState.CANCELLED,
            JobTargetState.READY,
        }:
            return 0 if current_target.state is JobTargetState.READY else 1
        self.repository.cas_job_target_state(
            job_id,
            target.symbol,
            target.canonical_interval,
            from_state=current_target.state,
            to_state=JobTargetState.FAILED,
            last_error=str(exc),
        )
        return 1

    async def _fetch_source_group(
        self,
        collection: Any,
        job: Any,
        sample_target: Any,
        *,
        source_interval: str,
    ) -> None:
        collection_targets, job_targets = await self._durable(
            self._source_group_targets, job.job_id, collection.collection_id
        )
        matching = [
            item for item in collection_targets
            if item.symbol == sample_target.symbol
            and item.source_interval == source_interval
        ]
        start_ms = min(item.effective_start_ms for item in matching)
        from app.data_engine.interval_policy import parse_interval_ms

        source_width = parse_interval_ms(source_interval) or 0
        planned_end = max(
            int(target.initial_end_open_ms)
            + max(
                0,
                (parse_interval_ms(target.canonical_interval) or source_width)
                - source_width,
            )
            for target in job_targets
            if target.symbol == sample_target.symbol
            and target.source_interval == source_interval
        )
        end_ms = self._seal_end_open_ms(source_interval, fallback=int(planned_end))
        await self._fetch(
            exchange=collection.exchange,
            market_type=collection.market_type,
            symbol=sample_target.symbol,
            interval=source_interval,
            target=sample_target,
            collection=collection,
            job=job,
            start_ms=start_ms,
            end_ms=end_ms,
        )

    def _source_group_targets(
        self, job_id: str, collection_id: str
    ) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
        self._raise_if_interrupted(job_id)
        return (
            self.repository.list_collection_targets(collection_id),
            self.repository.list_job_targets(job_id),
        )

    async def _run_derived_target(self, collection: Any, job: Any, target: Any) -> None:
        collection_target, sealed_end, source_end_ms, source_tail_contiguous = await self._durable(
            self._start_derived_target, collection, job, target
        )
        if not source_tail_contiguous:
            await self._fetch(
                exchange=collection.exchange,
                market_type=collection.market_type,
                symbol=target.symbol,
                interval=target.source_interval,
                target=target,
                collection=collection,
                job=job,
                start_ms=sealed_end,
                end_ms=source_end_ms,
            )

        cursor = int(collection_target.effective_start_ms)
        carry: list[dict[str, Any]] = []
        while cursor <= source_end_ms:
            # One page per span, so a cancel can land between pages and is
            # seen by the next page's interrupt check.
            cursor, carry, more = await self._durable(
                self._materialize_page, collection, job, target, cursor, carry, source_end_ms
            )
            if not more:
                break
        await self._durable(
            self._seal_derived_target, collection, job, target, collection_target, sealed_end
        )

    def _start_derived_target(
        self, collection: Any, job: Any, target: Any
    ) -> tuple[Any, int, int, bool]:
        from app.data_engine.interval_policy import parse_interval_ms

        collection_target = next(
            item for item in self.repository.list_collection_targets(collection.collection_id)
            if item.symbol == target.symbol
            and item.canonical_interval == target.canonical_interval
        )
        self.repository.cas_job_target_state(
            job.job_id,
            target.symbol,
            target.canonical_interval,
            from_state=target.state,
            to_state=JobTargetState.MATERIALIZING,
        )
        sealed_end = self._seal_end_open_ms(
            target.canonical_interval,
            fallback=int(target.initial_end_open_ms),
        )
        target_width = parse_interval_ms(target.canonical_interval) or 0
        source_width = parse_interval_ms(target.source_interval) or 0
        if target_width <= source_width or source_width <= 0:
            raise RuntimeError("invalid_derived_interval_route")
        source_end_ms = int(sealed_end) + max(0, target_width - source_width)
        source_tail = self._verify_range(
            target.symbol,
            target.source_interval,
            sealed_end,
            source_end_ms,
            exchange=collection.exchange,
            market_type=collection.market_type,
        )
        return (
            collection_target,
            sealed_end,
            source_end_ms,
            source_tail.get("verified_contiguous") is True,
        )

    def _materialize_page(
        self,
        collection: Any,
        job: Any,
        target: Any,
        cursor: int,
        carry: list[dict[str, Any]],
        source_end_ms: int,
    ) -> tuple[int, list[dict[str, Any]], bool]:
        """Rebuild closed target bars from one source page; returns (cursor, carry, more)."""
        from app.data_engine.manual_history.materializer import materialize_closed_target_bars
        from app.data_engine.storage.klines_repo import query_klines, upsert_klines
        from app.data_engine.interval_policy import compute_bucket_start_ms, parse_interval_ms

        page_size = 5_000
        target_width = parse_interval_ms(target.canonical_interval) or 0
        source_width = parse_interval_ms(target.source_interval) or 0
        self._raise_if_interrupted(job.job_id)
        page = query_klines(
            target.symbol,
            target.source_interval,
            start_ms=cursor,
            end_ms=source_end_ms,
            limit=page_size,
            exchange=collection.exchange,
            market_type=collection.market_type,
        )
        if not page:
            rows_to_flush = carry
            carry = []
        else:
            combined = [*carry, *page]
            final_bucket = compute_bucket_start_ms(
                int(combined[-1]["open_time"]),
                target_width,
                interval=target.canonical_interval,
            )
            if len(page) >= page_size:
                rows_to_flush = [
                    row
                    for row in combined
                    if compute_bucket_start_ms(
                        int(row["open_time"]),
                        target_width,
                        interval=target.canonical_interval,
                    )
                    < final_bucket
                ]
                carry = combined[len(rows_to_flush):]
            else:
                rows_to_flush = combined
                carry = []
            cursor = int(page[-1]["open_time"]) + max(1, source_width)
        rebuilt = materialize_closed_target_bars(
            rows_to_flush,
            target_interval=target.canonical_interval,
            source_interval=target.source_interval,
            now_ms=self._now_ms(),
        )
        if rebuilt:
            upsert_klines(
                target.symbol,
                target.canonical_interval,
                rebuilt,
                source=collection.exchange,
                exchange=collection.exchange,
                market_type=collection.market_type,
            )
        return cursor, carry, bool(page) and len(page) >= page_size

    def _seal_derived_target(
        self,
        collection: Any,
        job: Any,
        target: Any,
        collection_target: Any,
        sealed_end: int,
    ) -> None:
        self._raise_if_interrupted(job.job_id)
        self.repository.cas_job_target_state(
            job.job_id,
            target.symbol,
            target.canonical_interval,
            from_state=JobTargetState.MATERIALIZING,
            to_state=JobTargetState.VERIFYING,
        )
        verification = self._verify_range(
            target.symbol,
            target.canonical_interval,
            collection_target.effective_start_ms,
            sealed_end,
            exchange=collection.exchange,
            market_type=collection.market_type,
        )
        if verification.get("verified_contiguous") is not True:
            raise RuntimeError(
                f"continuity_failed expected={verification.get('expected_open_time')} "
                f"actual={verification.get('actual_open_time')}"
            )
        self._seal_target(
            job,
            target,
            sealed_end=sealed_end,
            verified_rows=int(
                verification.get("expected_count") or verification.get("actual_count") or 0
            ),
        )

    def _start_native_target(self, job_id: str, target: Any) -> None:
        self._raise_if_interrupted(job_id)
        self.repository.cas_job_target_state(
            job_id,
            target.symbol,
            target.canonical_interval,
            from_state=target.state,
            to_state=JobTargetState.FETCHING,
        )

    async def _run_native_target(self, collection: Any, job: Any, target: Any) -> None:
        await self._durable(self._start_native_target, job.job_id, target)
        from app.data_engine.interval_policy import parse_interval_ms

        fetch_end = self._seal_end_open_ms(
            target.canonical_interval,
            fallback=int(target.initial_end_open_ms),
        )
        await self._fetch(
            exchange=collection.exchange,
            market_type=collection.market_type,
            symbol=target.symbol,
            interval=target.canonical_interval,
            target=target,
            collection=collection,
            job=job,
            end_ms=fetch_end,
        )
        sealed_end = self._seal_end_open_ms(
            target.canonical_interval,
            fallback=fetch_end,
        )
        if sealed_end > fetch_end:
            step = parse_interval_ms(target.canonical_interval) or 1
            await self._fetch(
                exchange=collection.exchange,
                market_type=collection.market_type,
                symbol=target.symbol,
                interval=target.canonical_interval,
                target=target,
                collection=collection,
                job=job,
                start_ms=fetch_end + step,
                end_ms=sealed_end,
            )
        await self._durable(self._seal_native_target, collection, job, target, sealed_end)

    def _seal_native_target(self, collection: Any, job: Any, target: Any, sealed_end: int) -> None:
        # _fetch's closing check used to share one synchronous span with this
        # seal. Repeat the cancel half so a cancel landing between them cannot seal.
        self._raise_if_cancelled(job.job_id)
        self.repository.cas_job_target_state(
            job.job_id,
            target.symbol,
            target.canonical_interval,
            from_state=JobTargetState.FETCHING,
            to_state=JobTargetState.VERIFYING,
        )
        collection_target = next(
            item for item in self.repository.list_collection_targets(collection.collection_id)
            if item.symbol == target.symbol
            and item.canonical_interval == target.canonical_interval
        )
        verification = self._verify_range(
            target.symbol,
            target.canonical_interval,
            collection_target.effective_start_ms,
            sealed_end,
            exchange=collection.exchange,
            market_type=collection.market_type,
        )
        if verification.get("verified_contiguous") is not True:
            raise RuntimeError(
                f"continuity_failed expected={verification.get('expected_open_time')} "
                f"actual={verification.get('actual_open_time')}"
            )
        verified_rows = int(verification.get("expected_count") or verification.get("actual_count") or 0)
        self._seal_target(
            job,
            target,
            sealed_end=sealed_end,
            verified_rows=verified_rows,
        )

    def _seal_target(
        self,
        job: Any,
        target: Any,
        *,
        sealed_end: int,
        verified_rows: int,
    ) -> Any:
        guarded_seal = getattr(
            self.data_manager,
            "seal_manual_history_target",
            None,
        )
        if callable(guarded_seal):
            return guarded_seal(
                self.repository,
                job.job_id,
                target.symbol,
                target.canonical_interval,
                sealed_end_open_ms=sealed_end,
                verified_rows=verified_rows,
            )
        return self.repository.seal_target(
            job.job_id,
            target.symbol,
            target.canonical_interval,
            sealed_end_open_ms=sealed_end,
            verified_rows=verified_rows,
        )

    async def _fetch(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        target: Any,
        collection: Any,
        job: Any,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> int:
        collection_target = await self._durable(
            self._fetch_collection_target, job.job_id, collection.collection_id, symbol, interval
        )
        resolved_start = start_ms
        resolved_end = end_ms
        if collection_target is not None:
            if resolved_start is None:
                resolved_start = collection_target.effective_start_ms
            if resolved_end is None:
                resolved_end = self._seal_end_open_ms(
                    interval,
                    fallback=int(target.initial_end_open_ms),
                )
        if resolved_start is None:
            resolved_start = int(getattr(target, "initial_end_open_ms", 0))
        if resolved_end is None:
            resolved_end = self._seal_end_open_ms(
                interval,
                fallback=int(target.initial_end_open_ms),
            )
        if self._fetch_native is not None:
            written = int(
                await self._fetch_native(
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    interval=interval,
                    start_ms=int(resolved_start),
                    end_ms=int(resolved_end),
                    job_id=job.job_id,
                    collection_id=collection.collection_id,
                )
                or 0
            )
            await self._durable(self._raise_if_interrupted, job.job_id)
            return written
        coordinator = self.coordinator
        if coordinator is None:
            return 0
        from app.data_engine.data_manager.backfill_contracts import RepairRequest

        request = RepairRequest(
            symbol=symbol,
            interval=interval,
            start_ms=int(resolved_start),
            end_ms=int(resolved_end),
            exchange=exchange,
            market_type=market_type,
            reason="manual_history_download",
            requester="manual_history_download",
            metadata={
                "origin": "data_workbench",
                "manual_job_id": job.job_id,
                "manual_collection_id": collection.collection_id,
                "archive_explicit_demand": True,
                "requires_trusted_finality": True,
                "demand_owner_id": self._demand_owner_id(job.job_id),
                "demand_scope": f"manual-history-job:{job.job_id}",
            },
        )
        submit = getattr(coordinator, "request", None)
        wait_for_request = getattr(coordinator, "wait_for_request", None)
        if callable(submit) and callable(wait_for_request):
            # A submit that races a cancel is safe: the coordinator rejects
            # requests from a revoked demand owner.
            request_id = str(submit(request))
            await self._durable(
                self.repository.set_job_target_backfill_request_id,
                job.job_id,
                target.symbol,
                target.canonical_interval,
                request_id,
            )
            try:
                outcome = await wait_for_request(request_id)
            finally:
                await self._durable(
                    self.repository.set_job_target_backfill_request_id,
                    job.job_id,
                    target.symbol,
                    target.canonical_interval,
                    None,
                )
        else:
            outcome = await coordinator.request_and_wait(request)
        await self._durable(self._raise_if_interrupted, job.job_id)
        status = str(getattr(outcome, "status", "completed") or "completed").lower()
        if status == "cancelled":
            raise _JobCancelled(str(getattr(outcome, "error", None) or status))
        if status in {"failed", "error"}:
            raise RuntimeError(str(getattr(outcome, "error", None) or status))
        return 0

    def _fetch_collection_target(
        self, job_id: str, collection_id: str, symbol: str, interval: str
    ) -> Any:
        self._raise_if_interrupted(job_id)
        return next(
            (
                item for item in self.repository.list_collection_targets(collection_id)
                if item.symbol == symbol and item.canonical_interval == interval
            ),
            None,
        )

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            # Clear before scanning so a wake-up raised mid-scan forces a rescan.
            self._wake.clear()
            action, job_id = await self._durable(
                self._schedule_next, frozenset(self._active_job_ids)
            )
            if action == "run":
                await self.run_job(job_id)
                continue
            if action == "rescan" or self._stop.is_set():
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._idle_poll_seconds)
            except asyncio.TimeoutError:
                continue

    def _schedule_next(self, active_job_ids: frozenset[str]) -> tuple[str, str | None]:
        """Settle or pick one job: cancelling first, then storage-blocked, then queued.

        Returns ("run", job_id), ("rescan", None) after settling a job, or
        ("idle", None) when nothing is runnable.
        """
        recoverable = self.repository.list_recoverable_jobs()
        cancelling = [
            job for job in recoverable
            if job.state is JobState.CANCELLING
            and job.job_id not in active_job_ids
        ]
        if cancelling:
            self._finalize_cancellation(cancelling[0].job_id)
            return "rescan", None
        blocked = [
            job for job in recoverable
            if job.state is JobState.BLOCKED_STORAGE
        ]
        # The pressure probe scans SQLite page ownership. Idle polling
        # needs no scan; run_job still checks pressure before doing work.
        if blocked and self._storage_block_reason() is None:
            self.repository.reset_recoverable_targets(blocked[0].job_id)
            self.repository.cas_job_state(
                blocked[0].job_id,
                from_state=JobState.BLOCKED_STORAGE,
                to_state=JobState.QUEUED,
                stage="storage_recovered",
            )
            return "rescan", None
        queued = [job for job in recoverable if job.state is JobState.QUEUED]
        if queued:
            return "run", queued[0].job_id
        return "idle", None
