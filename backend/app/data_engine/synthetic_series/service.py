"""DataManager-owned shared synthetic instances and consumer leases."""
from __future__ import annotations

import asyncio
from copy import copy, deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import time
from uuid import uuid4

from app.core.executors import run_preparation, run_storage
from app.core.async_cleanup import finish_cleanup
from app.core.bounded_executor import ExecutorBusyError
from app.data_engine.data_manager.models import DataEventType, SeriesKey
from app.data_engine.history.calendar import AlwaysOpenCalendar
from .core import MAX_SOURCE_ROWS, SyntheticConfig, SyntheticError, SyntheticKernel


@dataclass(frozen=True)
class SyntheticSourcePort:
    query: object
    subscribe: object
    unsubscribe: object
    ensure_stream: object
    release_stream: object
    clock: object
    query_row_limit: int


@dataclass(frozen=True)
class SyntheticDefinition:
    source: SeriesKey
    config: SyntheticConfig
    anchor: int
    through: int | None = None

    def __post_init__(self):
        if self.anchor < 0 or (self.through is not None and self.through < self.anchor):
            raise SyntheticError("invalid analysis range")
        if self.config.semantics == "display-window/1" and self.through is None:
            raise SyntheticError("display mode requires an explicit analysis range")
        if self.source.asset_class != "crypto" or self.source.session_variant != "continuous":
            raise SyntheticError("synthetic calendar not qualified for this source")

    def to_dict(self):
        return {"source": asdict(self.source), "config": self.config.to_dict(),
            "anchor": self.anchor, "through": self.through}

    @property
    def key(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SyntheticLease:
    def __init__(self, service, instance):
        self.service, self.instance = service, instance
        self.id = uuid4().hex
        self.queue = asyncio.Queue(maxsize=32)
        self.closed = False
        self.queued_rows = 0
        self._close_task = None

    async def snapshot(self, *, before=None, limit=2000, generation=None):
        return await self.instance.snapshot(before=before, limit=limit, generation=generation)

    async def next(self):
        message = await self.queue.get()
        self.queued_rows -= len(message.get("rows", ()))
        return await run_preparation(deepcopy, message)

    async def close(self):
        if self._close_task is None:
            self.closed = True
            self._close_task = asyncio.create_task(self.service.release(self))
        await finish_cleanup(asyncio.shield(self._close_task))


class _Instance:
    def __init__(self, service, definition):
        self.service, self.definition = service, definition
        self.key = definition.key
        self.consumer_id = "synthetic:" + uuid4().hex
        self.generation = uuid4().hex
        self.revision = 0
        self.status, self.reason = "preparing", None
        self.lock = asyncio.Lock()
        self.kernel = SyntheticKernel(definition.config)
        self.leases = {}
        self.subscription = None
        self.subscription_failed = False
        self.stream_claimed = False
        self.closed = False
        self.version = None
        self.source_revision = None
        self.start_task = None

    def source_options(self):
        key = self.definition.source
        return {"symbol": key.symbol, "interval": key.interval, "exchange": key.exchange,
            "market_type": key.market_type, "series_identity": key.identity}

    def envelope(self, kind):
        return {"protocol": "candlescope.synthetic/1", "type": kind, "series_id": self.key,
            "generation": self.generation, "revision": self.revision,
            "status": self.status, "reason": self.reason,
            "definition": self.definition.to_dict(), "source_version": self.version,
            "source_revision": self.source_revision,
            "strategy_qualified": False}

    def rows(self, start=0, end=None):
        result = deepcopy(self.kernel.output[start:end])
        for index, row in enumerate(result, start):
            row["id"] = f"{self.key}:{self.generation}:{index}"
            row["ordinal"] = index
        return result

    def broadcast(self, message):
        for lease in tuple(self.leases.values()):
            rows = len(message.get("rows", ()))
            if (lease.queue.full() or self.service.pending_rows() + rows > 10_000
                    or self.service.memory_usage()["estimated_bytes"] + rows * 1536 > self.service.max_bytes):
                # Never silently drop a close/correction. This consumer must
                # resnapshot independently; other consumers keep their cursor.
                while not lease.queue.empty():
                    lease.queue.get_nowait()
                lease.queued_rows = 0
                lease.queue.put_nowait({**self.envelope("resync"), "reason": "slow_consumer"})
            else:
                lease.queued_rows += rows
                lease.queue.put_nowait(message)

    def unavailable(self, reason):
        self.status, self.reason = "stale", reason
        self.revision += 1
        self.broadcast(self.envelope("status"))

    async def start(self):
        source = self.service.source
        options = self.source_options()
        async with self.lock:
            self.subscription = source.subscribe(self.on_event, **options,
                continuity="gap_aware", on_recovery=self.on_recovery)
            self.stream_claimed = True
            await source.ensure_stream(**options, consumer_id=self.consumer_id)
            await self.rebuild()

    async def recover_subscription(self):
        if self.subscription_failed:
            if self.subscription is not None:
                self.service.source.unsubscribe(self.subscription)
            self.subscription_failed = False
            self.subscription = self.service.source.subscribe(self.on_event, **self.source_options(),
                continuity="gap_aware", on_recovery=self.on_recovery)
        await self.rebuild()

    async def read(self):
        end = self.definition.through
        if end is None:
            end = int(time.time())
        calendar = AlwaysOpenCalendar()
        start_ms, end_ms = self.definition.anchor * 1000, end * 1000
        count = calendar.count_expected(start_ms, end_ms, self.definition.source.interval)
        if count > MAX_SOURCE_ROWS or count > self.service.source.query_row_limit:
            raise SyntheticError("synthetic source budget exceeded")
        result = await run_storage(self.service.source.query, **self.source_options(),
            start_ms=start_ms, end_ms=end_ms, limit=max(1, count),
            auto_backfill=True, backfill_reason="initial_history", backfill_requester=self.consumer_id)
        if any(bar.is_closed and not bar.trusted_final for bar in result.bars):
            raise SyntheticError("source finality not qualified")
        rows = [bar.to_dict() for bar in result.bars]
        actual = [int(row["time"] * 1000) for row in rows]
        expected = list(calendar.expected_opens(start_ms, end_ms, self.definition.source.interval))
        if actual != expected or not rows or rows[0]["time"] != self.definition.anchor:
            raise SyntheticError("source history incomplete")
        if result.has_tail_gap or result.missing_ranges:
            raise SyntheticError("source history incomplete")
        version = result.metadata.get("stream_version")
        if not version or version.get("stable") is not True:
            raise SyntheticError("source snapshot changed")
        return rows, version, result.metadata.get("storage_revision")

    async def rebuild(self):
        try:
            rows, version, storage_revision = await self.read()
            candidate = SyntheticKernel(self.definition.config)
            await run_preparation(candidate.replace, rows)
            if self.subscription_failed:
                raise SyntheticError("source delivery lost")
            current = self.service.source.clock.snapshot(self.definition.source)
            if any(current.get(field) != version.get(field) for field in ("epoch", "generation", "sequence")) or not current["stable"]:
                raise SyntheticError("source snapshot changed")
            self.service.check_capacity(self, candidate)
            self.kernel = candidate
            self.version, self.source_revision = version, storage_revision
            # The same immutable source snapshot can be queried in multiple
            # short-lived leases without manufacturing different page IDs.
            self.generation = hashlib.sha256(json.dumps(
                [self.key, version, storage_revision], sort_keys=True).encode()).hexdigest()[:32]
            self.status, self.reason = "ready", None
            self.revision += 1
            if self.revision > 1:
                self.broadcast(self.envelope("resync"))
        except (SyntheticError, ExecutorBusyError) as error:
            self.unavailable(str(error))

    async def on_recovery(self, _error):
        # Immediate fencing before waiting for an in-flight worker.
        self.subscription_failed = True
        self.unavailable("source delivery lost")

    async def on_event(self, event):
        if self.closed:
            return
        async with self.lock:
            if self.closed:
                return
            version = event.detail.get("stream_version")
            if self.version and version and all(self.version.get(field) == version.get(field) for field in ("epoch", "generation")):
                if version["sequence"] <= self.version["sequence"]:
                    return
            if event.event_type in {DataEventType.SOURCE_GAP, DataEventType.STREAM_STOPPED,
                    DataEventType.STREAM_ERROR, DataEventType.CACHE_EVICTION}:
                self.unavailable("source unavailable")
                return
            if event.event_type in {DataEventType.SOURCE_GAP_RESOLVED, DataEventType.BACKFILL_COMPLETED,
                    DataEventType.BAR_AMENDED}:
                await self.rebuild()
                return
            if event.bar is None:
                return
            if event.bar.time < self.definition.anchor or (
                    self.definition.through is not None and event.bar.time > self.definition.through):
                return
            if self.status != "ready":
                await self.rebuild()
                return
            if self.version and version and any(self.version.get(field) != version.get(field) for field in ("epoch", "generation")):
                await self.rebuild()
                return
            old = self.kernel.output
            old_options = self.kernel.options
            try:
                row = deepcopy(event.bar.to_dict())
                # K-line completeness follows the source calendar, never the
                # spacing between synthetic bricks.
                last = self.kernel.source[-1]["time"]
                if row["time"] > last and row["time"] * 1000 != AlwaysOpenCalendar().next_expected_open(last * 1000, self.definition.source.interval):
                    raise SyntheticError("source continuity lost")
                if event.bar.is_closed and not event.bar.trusted_final:
                    raise SyntheticError("source finality not qualified")
                candidate = copy(self.kernel)
                await run_preparation(candidate.apply, row)
                if self.subscription_failed:
                    raise SyntheticError("source delivery lost")
                self.service.check_capacity(self, candidate)
                self.kernel = candidate
            except (SyntheticError, ExecutorBusyError) as error:
                self.unavailable(str(error))
                return
            self.version = version
            self.source_revision = event.detail.get("storage_revision", self.source_revision)
            self.revision += 1
            if old_options != self.kernel.options:
                # Legacy display recalibration changes ordinal meanings.
                self.generation = uuid4().hex
                self.broadcast(self.envelope("resync"))
                return
            # Diff and payload materialization are bounded worker work.
            def patch():
                start = 0
                while start < min(len(old), len(self.kernel.output)) and old[start] == self.kernel.output[start]:
                    start += 1
                return {"from_index": start, "delete_count": len(old) - start,
                    "rows": self.rows(start), "total": len(self.kernel.output)}
            delta = await run_preparation(patch)
            self.broadcast({**self.envelope("patch"), **delta})

    async def snapshot(self, *, before, limit, generation):
        if not 1 <= limit <= 5000:
            raise SyntheticError("invalid synthetic page size")
        async with self.lock:
            if generation is not None and generation != self.generation:
                raise SyntheticError("synthetic generation changed")
            end = len(self.kernel.output) if before is None else before
            if not 0 <= end <= len(self.kernel.output):
                raise SyntheticError("invalid synthetic cursor")
            start = max(0, end - limit)
            rows = await run_preparation(self.rows, start, end)
            return {**self.envelope("snapshot"), "from_index": start, "rows": rows,
                "total": len(self.kernel.output), "before": start if start else None}

    async def close(self):
        self.closed = True
        if self.subscription is not None:
            self.service.source.unsubscribe(self.subscription)
            self.subscription = None
        async with self.lock:
            if self.stream_claimed:
                self.stream_claimed = False
                await self.service.source.release_stream(**self.source_options(), consumer_id=self.consumer_id)


class SyntheticSeriesService:
    """One owner per full identity; no per-chart transforms or exchange I/O."""

    def __init__(self, source, *, max_instances=32, max_bytes=64 * 1024 * 1024):
        self.source = source
        self.instances = {}
        self.lock = asyncio.Lock()
        self.max_instances, self.max_bytes = max_instances, max_bytes
        self.closed = False

    def memory_usage(self):
        instances = tuple(self.instances.values())
        rows = sum(len(instance.kernel.source) + len(instance.kernel.output) for instance in instances)
        return {"estimated_bytes": (rows + self.pending_rows()) * 1536, "instances": len(self.instances)}

    def diagnostics(self):
        return {**self.memory_usage(), "max_instances": self.max_instances, "max_bytes": self.max_bytes,
            "consumers": sum(len(instance.leases) for instance in self.instances.values()),
            "status": "closed" if self.closed else "available",
            "supported_transforms": ["renko", "heikin-ashi"], "strategy_qualified": False}

    def pending_rows(self):
        return sum(lease.queued_rows for instance in tuple(self.instances.values())
            for lease in tuple(instance.leases.values()))

    def _memory_roots(self):
        # Do not expose source ports/bound DM methods as owned cache roots.
        return [root for instance in tuple(self.instances.values())
            for root in (instance.kernel, *(lease.queue._queue for lease in tuple(instance.leases.values())))]

    def check_capacity(self, target, candidate):
        rows = sum(len(instance.kernel.source) + len(instance.kernel.output)
            for instance in self.instances.values() if instance is not target)
        if (rows + len(candidate.source) + len(candidate.output)) * 1536 > self.max_bytes:
            raise SyntheticError("shared synthetic memory budget exceeded")

    async def attach(self, definition):
        async with self.lock:
            if self.closed:
                raise SyntheticError("synthetic service closed")
            if sum(len(instance.leases) for instance in self.instances.values()) >= 128:
                raise SyntheticError("synthetic consumer budget exceeded")
            instance = self.instances.get(definition.key)
            existing = instance is not None
            if instance is None:
                if len(self.instances) >= self.max_instances:
                    raise SyntheticError("synthetic instance budget exceeded")
                instance = _Instance(self, definition)
                self.instances[definition.key] = instance
                instance.start_task = asyncio.create_task(instance.start())
            lease = SyntheticLease(self, instance)
            instance.leases[lease.id] = lease
        try:
            # One consumer's cancellation cannot cancel the shared seed.
            await asyncio.shield(instance.start_task)
            if existing and instance.status != "ready":
                async with instance.lock:
                    await instance.recover_subscription()
            return lease
        except BaseException:
            await lease.close()
            raise

    async def release(self, lease):
        close = False
        async with self.lock:
            instance = lease.instance
            instance.leases.pop(lease.id, None)
            if not instance.leases and self.instances.get(instance.key) is instance:
                self.instances.pop(instance.key)
                close = True
        if close:
            if instance.start_task is not None:
                if not instance.start_task.done():
                    instance.start_task.cancel()
                await asyncio.gather(instance.start_task, return_exceptions=True)
            await instance.close()

    async def close(self):
        async with self.lock:
            self.closed = True
            instances = list(self.instances.values())
            self.instances.clear()
            for instance in instances:
                if instance.start_task is not None and not instance.start_task.done():
                    instance.start_task.cancel()
                    await asyncio.gather(instance.start_task, return_exceptions=True)
                for lease in instance.leases.values():
                    lease.closed = True
                await instance.close()
