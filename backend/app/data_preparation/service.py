"""Durable orchestration above shared, capability-aware acquisition adapters."""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Protocol

from .models import PreparationError, PreparationRequest, Requirement, fingerprint, split_requirement
from .repository import PreparationRepository
from .lease import PreparationLease

logger = logging.getLogger(__name__)


class PreparationAdapter(Protocol):
    def validate(self, request: PreparationRequest) -> None: ...
    async def acquire(self, requirement: Requirement, key: str) -> tuple[dict, int]: ...
    async def publish(self, request: PreparationRequest, chunks: list[dict], job_id: str) -> dict: ...


class PreparationService:
    def __init__(self, repository: PreparationRepository, adapter: PreparationAdapter, *, workers=2, enabled=True):
        self.repository, self.adapter = repository, adapter
        if hasattr(adapter, "publication_repository"):
            adapter.publication_repository = repository
        self.workers = workers
        self.enabled = enabled
        self._runner = None
        self._inventory_task = None
        self._inventory_dirty = False
        self._inventory_enabled = False
        self._inventory_stop = threading.Event()
        self._tasks: dict[str, asyncio.Task] = {}
        self._acquisitions: dict[str, tuple[asyncio.Task, set[str]]] = {}
        self._acquisition_specs: dict[str, Requirement] = {}
        self._wake = asyncio.Event()
        self._closing = False
        self._lease = PreparationLease(repository.path.with_suffix(".lock"))

    async def start(self):
        if self._runner is not None or not self.enabled:
            return
        self._lease.acquire()
        try:
            self.repository.recover()
            reconcile = getattr(self.adapter, "reconcile_cache", None)
            if reconcile is not None:
                from .bar_adapter import storage_call
                await storage_call(reconcile, self.repository)
            remove = getattr(self.adapter, "remove_cached_object", None)
            if remove is not None:
                self.repository.cleanup_pending(remove, before_workers=True)
            scopes = getattr(self.adapter, "publication_scopes", None)
            if scopes is not None:
                self.repository.register_publication_scopes(scopes())
        except BaseException:
            self._lease.release()
            raise
        self._closing = False
        self._inventory_stop.clear()
        self._inventory_enabled = scopes is not None
        self._refresh_inventory()
        self._runner = asyncio.create_task(self._loop(), name="data-preparation")

    def _refresh_inventory(self):
        if not self._inventory_enabled or self._closing:
            return
        if self._inventory_task is not None and not self._inventory_task.done():
            self._inventory_dirty = True
            return
        from .storage_inventory import reconcile as reconcile_publications
        from .bar_adapter import storage_call
        self._inventory_dirty = False
        self.repository.set_inventory_state("SCANNING")
        self._inventory_task = asyncio.create_task(storage_call(
            reconcile_publications, self.repository, self._inventory_stop), name="preparation-storage-inventory")
        self._inventory_task.add_done_callback(self._inventory_finished)

    def _inventory_finished(self, task):
        if not task.cancelled():
            task.exception()
        if self._inventory_dirty and not self._closing:
            self._refresh_inventory()

    async def shutdown(self):
        self._closing = True
        self._inventory_stop.set()
        self._wake.set()
        if self._runner:
            await self._runner
            self._runner = None
        # Drain storage/network boundaries before application dependencies stop.
        # A job observes closing at its next checkpoint and remains recoverable.
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        if self._inventory_task is not None:
            await asyncio.gather(self._inventory_task, return_exceptions=True)
            self._inventory_task = None
        self._lease.release()

    def submit(self, request: PreparationRequest):
        if not self.enabled:
            raise PreparationError("PREPARATION_DISABLED", "Automatic history preparation is disabled")
        if self._closing:
            raise PreparationError("SHUTTING_DOWN", "Data preparation is stopping")
        self.adapter.validate(request)
        total = sum(len(split_requirement(item)) for item in request.requirements)
        if request.progressive:
            from .progressive import plan
            total = len(plan(request)[1])
        if total > 4096:
            raise PreparationError("PLAN_TOO_LARGE", "Preparation exceeds 4096 data fragments")
        result = self.repository.create(request, total)
        self._wake.set()
        return result

    def cancel(self, job_id):
        job = self.repository.cancel(job_id)
        self._wake.set()
        return job

    def retry(self, job_id):
        if not self.enabled:
            raise PreparationError("PREPARATION_DISABLED", "Automatic history preparation is disabled")
        job = self.repository.get(job_id)
        self.adapter.validate(PreparationRequest.model_validate(job["request"]))
        result = self.repository.retry(job_id)
        self._refresh_inventory()
        self._wake.set()
        return result

    async def _loop(self):
        while not self._closing:
            self._wake.clear()
            self._tasks = {key: task for key, task in self._tasks.items() if not task.done()}
            jobs = sorted(self.repository.list(active=True),
                          key=lambda job: (job["request"]["consumer"] == "PREFETCH", job["created_ms"]))
            for job in jobs:
                if len(self._tasks) >= self.workers:
                    break
                if job["id"] in self._tasks or job["state"] == "BLOCKED_STORAGE":
                    continue
                if job["next_attempt_ms"] > self.repository.now() and not job["cancel_requested"]:
                    continue
                if job["request"]["consumer"] == "PREFETCH":
                    prefetch_running = sum(self.repository.get(key)["request"]["consumer"] == "PREFETCH"
                                           for key in self._tasks)
                    if prefetch_running >= max(1, self.workers - 1):
                        continue
                self._tasks[job["id"]] = asyncio.create_task(self._run(job["id"]))
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=0.5)
            except TimeoutError:
                pass

    def _checkpoint(self, job_id):
        if self._closing:
            raise asyncio.CancelledError
        if self.repository.get(job_id)["cancel_requested"]:
            raise PreparationError("CANCELLED", "Data preparation was cancelled")

    async def _obtain(self, fragment, key, job_id):
        cached = self.repository.covering(fragment, owner=job_id)
        if cached is not None:
            return cached
        entry = self._acquisitions.get(key)
        if entry is None:
            async def acquire():
                receipt, byte_count = await self.adapter.acquire(fragment, key)
                return self.repository.publish_chunk(key, fragment.model_dump(), receipt, byte_count, f"acquire:{key}")
            entry = (asyncio.create_task(acquire()), set())
            self._acquisitions[key] = entry
            self._acquisition_specs[key] = fragment
        task, owners = entry
        owners.add(job_id)
        previous_waiting = None
        try:
            while not task.done():
                self._checkpoint(job_id)
                observe = getattr(self.adapter, "acquisition_waiting", None)
                waiting = observe(key) if observe is not None else None
                if waiting != previous_waiting:
                    self.repository.set_waiting(job_id, waiting)
                    previous_waiting = waiting
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.25)
                except TimeoutError:
                    pass
            await task
            self._checkpoint(job_id)
            return self.repository.chunk(key, owner=job_id)
        finally:
            if previous_waiting is not None:
                self.repository.set_waiting(job_id, None)
            owners.discard(job_id)
            if not owners:
                # No consumer observes this acquisition now. Releasing the
                # scheduler demand cancels physical work only if nobody else
                # (including live charts) still needs that repair.
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if not owners:
                    self._acquisitions.pop(key, None)
                    self._acquisition_specs.pop(key, None)
                    self.repository.release(f"acquire:{key}")

    async def _parts(self, fragment, job_id):
        series = self.repository.series_key(fragment.model_dump())
        # Join already running overlapping downloads before calculating gaps.
        # This never expands the new consumer's requested output range.
        for key, running in list(self._acquisition_specs.items()):
            if (self.repository.series_key(running.model_dump()) == series
                    and running.start_ms < fragment.end_ms and running.end_ms > fragment.start_ms):
                await self._obtain(running, key, job_id)
        return [await self._obtain(part, fingerprint(part.model_dump()), job_id)
                for part in self.repository.partition(fragment)]

    async def _run(self, job_id):
        needs_inventory = False
        try:
            self._checkpoint(job_id)
            if self._inventory_task is not None:
                while not self._inventory_task.done():
                    self._checkpoint(job_id)
                    try:
                        await asyncio.wait_for(asyncio.shield(self._inventory_task), 0.25)
                    except TimeoutError:
                        pass
                await self._inventory_task
                self._checkpoint(job_id)
                self.repository.check_physical_budget()
            job = self.repository.get(job_id)
            request = PreparationRequest.model_validate(job["request"])
            self.adapter.validate(request)
            needs_inventory = True  # BAR prefetch can also grow shared Host storage.
            if request.progressive:
                await self._run_progressive(job_id, request, job)
                return
            launch = getattr(self.adapter, "launch", None)
            if job["result"] is not None and launch is not None and request.intent:
                # The consumer input was frozen at the previous STARTING
                # barrier. Recovery must not resolve a newer input generation.
                self.repository.update(job_id, state="RUNNING", stage="STARTING")
                self.repository.begin_start(job_id, job["result"])
                result = await launch(request, job["result"], job_id)
                self._ready(job_id, request, result)
                return
            self.repository.update(job_id, state="RUNNING", stage="CHECKING", completed=0)
            reuse = getattr(self.adapter, "reuse", None)
            prepared = await reuse(request, job_id) if reuse is not None else None
            if prepared is not None:
                self._checkpoint(job_id)
                self.repository.update(job_id, completed=job["total"])
                if launch is not None and request.intent:
                    self.repository.begin_start(job_id, prepared)
                    prepared = await launch(request, prepared, job_id)
                self._ready(job_id, request, prepared)
                return
            prepare_dependencies = getattr(self.adapter, "prepare_dependencies", None)
            dependencies = await prepare_dependencies(request) if prepare_dependencies is not None else {}
            self._checkpoint(job_id)
            chunks = []
            size = 0
            completed = 0
            sized_keys = set()
            for requirement in request.requirements:
                for fragment in split_requirement(requirement):
                    self._checkpoint(job_id)
                    self.repository.update(job_id, stage="FETCHING")
                    parts = await self._parts(fragment, job_id)
                    self._checkpoint(job_id)
                    for chunk in parts:
                        if chunk["key"] not in sized_keys:
                            size += chunk["bytes"]
                            sized_keys.add(chunk["key"])
                    if size > request.max_bytes:
                        raise PreparationError("STORAGE_BUDGET", "Prepared input exceeds the job storage budget")
                    chunks.extend(parts)
                    completed += 1
                    self.repository.update(job_id, completed=completed, stage="VALIDATING")
            self._checkpoint(job_id)
            self.repository.update(job_id, stage="PUBLISHING")
            result = await self.adapter.publish(request, chunks, job_id)
            result = {**result, **dependencies}
            self._checkpoint(job_id)
            launch = getattr(self.adapter, "launch", None)
            if launch is not None and request.intent:
                self.repository.begin_start(job_id, result)
                result = await launch(request, result, job_id)
            self._ready(job_id, request, result)
        except asyncio.CancelledError:
            # Shutdown is recoverable, user cancellation is an explicit state.
            pass
        except PreparationError as exc:
            error = {"code": exc.code, "message": str(exc), "retryable": exc.retryable}
            if exc.retryable and self.repository.get(job_id)["attempts"] < 3:
                self.repository.defer(job_id, error)
                return
            state = "CANCELLED" if exc.code == "CANCELLED" else "BLOCKED_STORAGE" if exc.code == "STORAGE_BUDGET" else "FAILED"
            self.repository.update(job_id, state=state, stage=state,
                                   error=error)
            if state == "CANCELLED":
                self.repository.release(job_id)
        except Exception:
            logger.exception("Preparation failed: %s", job_id)
            self.repository.update(job_id, state="FAILED", stage="FAILED",
                                   error={"code": "PREPARATION_FAILED", "message": "Data preparation failed; retry to resume", "retryable": True})
        finally:
            if needs_inventory:
                self._refresh_inventory()
            self._wake.set()

    async def _run_progressive(self, job_id, request, job):
        plan, fragments = await self.adapter.begin_progressive(request, job_id)
        self.repository.update(job_id, state="RUNNING", stage="CHECKING", completed=0)
        result = job["result"]
        dependencies = (result or {}).get("replay_dependencies")
        if dependencies is None:
            dependencies = await self.adapter.prepare_dependencies(request)
        else:
            dependencies = {"replay_dependencies": dependencies}
        size, sized_keys = 0, set()
        launched = False
        for completed, fragment in enumerate(fragments, 1):
            self._checkpoint(job_id)
            self.repository.update(job_id, stage="FETCHING")
            chunks = await self._parts(fragment, job_id)
            self._checkpoint(job_id)
            for chunk in chunks:
                if chunk["key"] not in sized_keys:
                    size += chunk["bytes"]
                    sized_keys.add(chunk["key"])
            if size > request.max_bytes:
                raise PreparationError("STORAGE_BUDGET", "Prepared input exceeds the job storage budget")
            self.repository.update(job_id, stage="PUBLISHING")
            published = await self.adapter.publish_progressive(request, chunks, job_id, plan, fragment)
            self.repository.update(job_id, completed=completed)
            if not launched and fragment.end_ms >= plan["initial_end_ms"]:
                self._checkpoint(job_id)
                # Persist the launch barrier before touching the consumer. On
                # restart launch is idempotent, but the remaining feed still runs.
                prepared = result or {**published, **dependencies}
                self.repository.begin_start(job_id, prepared)
                result = await self.adapter.launch(request, prepared, job_id)
                self.repository.update(job_id, stage="FETCHING", result=result)
                launched = True
        self._checkpoint(job_id)
        self._ready(job_id, request, result)

    def _ready(self, job_id, request, result):
        ready = self.repository.update(job_id, state="READY", stage="READY", result=result)
        if ready["state"] != "READY":
            return
        if request.consumer == "PREFETCH":
            self.repository.release(job_id)
        elif self.repository.settings()["prefetch_enabled"] and not self._closing:
            from .prefetch import next_prefetch
            planned = next_prefetch(self.repository.list(), now_ms=self.repository.now())
            if planned is not None:
                try:
                    self.submit(planned)
                except PreparationError:
                    # A speculative task cannot turn successful user work into
                    # failure or consume storage already reserved by other jobs.
                    logger.debug("Speculative history preparation was not admitted", exc_info=True)
