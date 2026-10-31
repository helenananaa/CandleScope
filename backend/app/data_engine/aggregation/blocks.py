"""B130: process-local, bounded immutable blocks with explicit read leases.

Read views fence the whole operation on exit. Builders are synchronous pure CPU
callbacks running on their initiating worker, never scheduled back onto storage.
No lock is held across a builder, revision I/O, or a joined flight wait.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, CancelledError, TimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING

from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size
from .core import ALGORITHM_VERSION, AggregateSummary, InputRevision

if TYPE_CHECKING:
    from app.data_engine.data_manager.models import SeriesKey


class BlockRevisionChanged(RuntimeError):
    pass


class BlockUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BlockKey:
    """Source basis and actual range, independent of the consuming target.

    Legacy decoded adapters add a digest of accepted immutable input values;
    they cannot silently treat an uncommitted cache snapshot as a durable view.
    """
    series: SeriesKey
    start_ms: int
    end_ms: int
    input_fingerprint: str = ""
    algorithm_version: str = ALGORITHM_VERSION

    def __post_init__(self):
        if self.start_ms >= self.end_ms or self.algorithm_version != ALGORITHM_VERSION:
            raise ValueError("positive block range and supported algorithm required")
        if len(self.input_fingerprint) > 64:
            raise ValueError("input fingerprint must be bounded")


@dataclass(frozen=True, slots=True)
class SharedBlock:
    key: BlockKey
    version: int
    summary: AggregateSummary


@dataclass(eq=False)
class _Entry:
    block: SharedBlock
    size: int
    pins: int = 0
    valid: bool = True


@dataclass(eq=False)
class _Flight:
    future: Future
    participants: int = 1
    invalid: bool = False
    running: bool = True
    owner_thread: int = 0


@dataclass(frozen=True, slots=True)
class _Failure:
    """Flights never retain shared exception tracebacks and their input pages."""
    kind: type
    message: str


class BlockView:
    def __init__(self, manager, revisions, generation, size):
        self.manager, self.revisions = manager, revisions
        self.generation, self.size = generation, size
        self.active = self.valid = True
        self.leases = set()


class BlockLease:
    def __init__(self, manager, view, entry):
        self._manager, self._view, self._entry = manager, view, entry
        self._closed = False

    @property
    def block(self):
        with self._manager._lock:
            if self._closed:
                raise BlockRevisionChanged("block lease is released or invalidated")
            self._manager._check_view(self._view)
            if not self._entry.valid:
                raise BlockRevisionChanged("block lease is released or invalidated")
            return self._entry.block

    def close(self):
        with self._manager._lock:
            if not self._closed:
                self._closed = True
                self._view.leases.discard(self)
                self._manager._release_pin(self._entry)
                self._entry = self._view = None

    def __enter__(self):
        return self.block

    def __exit__(self, *exc):
        self.close()


class SharedBlockManager:
    LEASE_BYTES = 256

    def __init__(self, *, budget, source=None, owner="aggregation-blocks",
                 max_bytes=16 * 1024 * 1024, max_entries=1024, max_flights=8,
                 max_views=64, max_leases=256, max_dependencies=16, max_ranges=128):
        if min(max_bytes, max_entries, max_flights, max_views, max_leases,
               max_dependencies, max_ranges) <= 0 or max_dependencies > 32:
            raise ValueError("positive bounded block capacities required")
        self.budget, self.owner, self.source = budget, owner, source
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.max_flights, self.max_views, self.max_leases = max_flights, max_views, max_leases
        self.max_dependencies, self.max_ranges = max_dependencies, max_ranges
        self._lock, self._source_lock = threading.RLock(), threading.Lock()
        self._entries = OrderedDict()
        self._retired = set()
        self._dependencies = {}
        self._flights = {}
        self._views = set()
        self._bytes = self._claimed = self._generation = self._version = 0
        self._closed = False
        self._usage = {"estimated_bytes": 0}
        self._metrics = dict(hits=0, builds=0, joins=0, evictions=0,
                             invalidations=0, stale_builds=0, failures=0, resets=0)
        self._last_error = None
        # This callback intentionally does not acquire _lock. Budget admission
        # owns its own lock; reversing that order would deadlock other owners.
        budget.register(owner, limit_bytes=max_bytes, usage=self.memory_usage,
                        roots=self._memory_roots)

    def memory_usage(self):
        return dict(self._usage)

    def _publish_usage(self):
        self._usage = {"estimated_bytes": self._bytes, "entries": len(self._entries),
                       "retired_entries": len(self._retired), "leases": self._claimed,
                       "views": len(self._views), "inflight": len(self._flights)}

    def _memory_roots(self):
        with self._lock:
            return (tuple(e.block for e in (*self._entries.values(), *self._retired)),
                    tuple(self._entries), tuple(v.revisions for v in self._views),
                    tuple(self._dependencies), tuple(self._flights))

    def snapshot(self):
        with self._lock:
            return {**self._usage, **self._metrics, "last_error": self._last_error,
                    "generation": self._generation, "closed": self._closed,
                    "limits": {"bytes": self.max_bytes, "entries": self.max_entries,
                               "flights": self.max_flights, "views": self.max_views,
                               "leases": self.max_leases, "dependencies": self.max_dependencies,
                               "ranges": self.max_ranges}}

    def bind_source(self, source):
        with self._source_lock, self._lock:
            self._reset()
            self.source = source

    def _refresh(self, series, acquired_at=None):
        # Source adapters consume D126's ledger. The manager has no new ledger
        # or unbounded per-series tombstone map of its own.
        with self._source_lock:
            if self.source is None:
                raise BlockUnavailable("versioned block source is unavailable")
            try:
                revisions, changes, reset = self.source.read(series, acquired_at=acquired_at)
                if any(not isinstance(r, InputRevision) or type(r.version) is not int
                       or len(r.domain) > 256 for r in revisions):
                    raise ValueError("source returned an unsupported revision token")
                revisions = tuple(sorted(revisions, key=lambda r: (r.series.topic, r.domain)))
                if ((bool(series) and not revisions) or len(revisions) > self.max_dependencies
                        or {r.series for r in revisions} != set(series)
                        or len({(r.series, r.domain) for r in revisions}) != len(revisions)):
                    raise ValueError("source returned an invalid revision vector")
                with self._lock:
                    if reset:
                        self._reset()
                    for change in changes:
                        self._invalidate(change[0], change[1],
                                         except_version=change[2] if len(change) > 2 else None)
                    # Observe changed tokens even if the adapter's notification
                    # was coalesced or delivered more than once.
                    for revision in revisions:
                        self._invalidate(revision.series, revision.domain, except_version=revision.version)
                    self._last_error = None
                    return revisions, self._generation
            except BlockRevisionChanged:
                raise
            except Exception as exc:
                with self._lock:
                    self._reset()
                    self._metrics["failures"] += 1
                    self._last_error = type(exc).__name__
                raise BlockUnavailable("cannot verify the block source revision") from exc

    def poll(self):
        """Consume coalesced source changes without building or reading blocks."""
        with self._lock:
            if self._closed or not (self._entries or self._views or self._flights):
                return self._generation
        return self._refresh(())[1]

    @contextmanager
    def view(self, series, *, acquired_at=None):
        keys = tuple(dict.fromkeys(series))
        if not keys or len(keys) > self.max_dependencies:
            raise ValueError("bounded nonempty source dependencies required")
        revisions, generation = self._refresh(keys, acquired_at)
        size = 2048 + retained_size((revisions,))[0]
        with self._lock:
            if self._closed or generation != self._generation:
                raise BlockRevisionChanged("block manager changed during acquisition")
            if len(self._views) >= self.max_views:
                raise MemoryBudgetExceeded("block read-view capacity exhausted")
            self._make_room(size)
            view = BlockView(self, revisions, generation, size)
            with self.budget.reserve(self.owner, size) as admission:
                def commit():
                    self._views.add(view)
                    self._bytes += size
                    self._publish_usage()
                admission.retain(size, commit)
        try:
            yield view
            current, generation = self._refresh(keys)
            with self._lock:
                self._check_view(view)
                if current != revisions or generation != view.generation:
                    raise BlockRevisionChanged("source changed before block result publication")
        finally:
            with self._lock:
                for lease in tuple(view.leases):
                    lease.close()
                view.active = False
                self._views.discard(view)
                self._bytes -= view.size
                self._publish_usage()

    def _check_view(self, view):
        if (view.manager is not self or view not in self._views or not view.active or not view.valid
                or view.generation != self._generation or self._closed):
            raise BlockRevisionChanged("block read view expired or was invalidated")

    def _drop(self, key, entry):
        self._entries.pop(key, None)
        entry.valid = False
        for dep in entry.block.summary.revisions:
            index_key = (dep.series, dep.domain)
            indexed = self._dependencies.get(index_key)
            if indexed is not None:
                indexed.discard(key)
                if not indexed:
                    del self._dependencies[index_key]
        if entry.pins:
            self._retired.add(entry)
        else:
            self._bytes -= entry.size

    def _make_room(self, extra, slots=0, exclude=None):
        if self._bytes + extra <= self.max_bytes and len(self._entries) + len(self._retired) + slots <= self.max_entries:
            return
        for key, entry in tuple(self._entries.items()):
            if self._bytes + extra <= self.max_bytes and len(self._entries) + len(self._retired) + slots <= self.max_entries:
                break
            if not entry.pins and key != exclude:
                self._drop(key, entry)
                self._metrics["evictions"] += 1
        self._publish_usage()
        if self._bytes + extra > self.max_bytes or len(self._entries) + len(self._retired) + slots > self.max_entries:
            raise MemoryBudgetExceeded("block capacity is held by active consumers")

    def _invalidate(self, series, domain, *, except_version=None, start_ms=None, end_ms=None):
        def affected(deps):
            return any(d.series == series and d.domain == domain
                       and d.version != except_version for d in deps)
        def overlaps(key):
            return ((start_ms is None or key.end_ms > start_ms)
                    and (end_ms is None or key.start_ms < end_ms))
        for key in tuple(self._dependencies.get((series, domain), ())):
            entry = self._entries[key]
            if affected(entry.block.summary.revisions) and overlaps(key[0]):
                self._drop(key, entry)
                self._metrics["invalidations"] += 1
        for (key, deps), flight in self._flights.items():
            if affected(deps) and overlaps(key):
                flight.invalid = True
                if not flight.future.done():
                    flight.future.set_result(_Failure(BlockRevisionChanged, "source changed during block build"))
        for view in self._views:
            if affected(view.revisions):
                view.valid = False
        self._publish_usage()

    def invalidate(self, series, domain, *, start_ms=None, end_ms=None):
        """Explicit memory-source change; durable coalesced changes use whole series."""
        with self._lock:
            self._invalidate(series, domain, start_ms=start_ms, end_ms=end_ms)

    def _reset(self):
        self._generation += 1
        self._metrics["resets"] += 1
        for key, entry in tuple(self._entries.items()):
            self._drop(key, entry)
        for flight in self._flights.values():
            flight.invalid = True
            if not flight.future.done():
                flight.future.set_result(_Failure(BlockRevisionChanged, "block generation reset"))
        for view in self._views:
            view.valid = False
        self._publish_usage()

    def collect(self):
        """Evict reusable, unleased cache values; never delete source data."""
        with self._lock:
            for key, entry in tuple(self._entries.items()):
                if not entry.pins:
                    self._drop(key, entry)
                    self._metrics["evictions"] += 1
            self._publish_usage()

    def close(self):
        with self._lock:
            self._closed = True
            self._reset()

    def reopen(self):
        with self._lock:
            if self._closed:
                if self._views or self._flights or self._claimed:
                    raise BlockUnavailable("previous block consumers have not drained")
                self._closed = False

    def _release_pin(self, entry):
        entry.pins -= 1
        self._claimed -= 1
        self._bytes -= self.LEASE_BYTES
        if not entry.valid and not entry.pins:
            self._retired.discard(entry)
            self._bytes -= entry.size
        self._publish_usage()

    def acquire(self, key, view, build=None, *, work_bytes=64 * 1024, cancel=None):
        """Join one pure build; cancellation only releases this participant.

        Inputs and output construction must fit work_bytes (caller-owned input
        pages remain charged to their existing owner). Returned leases expire
        with their view. A caller may not publish results until view exit passes.
        With no builder this is a cache-only lookup: a miss returns None without
        I/O, a flight, or waiting for another consumer's build.
        """
        cache_key = (key, view.revisions)
        owner = False
        with self._lock:
            self._check_view(view)
            if cancel is not None and cancel.is_set():
                raise CancelledError()
            if self._claimed >= self.max_leases:
                raise MemoryBudgetExceeded("block lease capacity exhausted")
            entry = self._entries.get(cache_key)
            if entry is not None:
                self._make_room(self.LEASE_BYTES, exclude=cache_key)
                with self.budget.reserve(self.owner, self.LEASE_BYTES) as admission:
                    def commit():
                        self._bytes += self.LEASE_BYTES
                        self._claimed += 1
                        entry.pins += 1
                        self._publish_usage()
                    admission.retain(self.LEASE_BYTES, commit)
                self._entries.move_to_end(cache_key)
                self._metrics["hits"] += 1
                lease = BlockLease(self, view, entry)
                view.leases.add(lease)
                return lease
            if build is None:
                return None
            flight = self._flights.get(cache_key)
            if flight is None:
                if work_bytes <= 0 or work_bytes + 2048 > self.max_bytes:
                    raise MemoryBudgetExceeded("block working allowance exceeds its owner budget")
                if len(self._flights) >= self.max_flights:
                    raise MemoryBudgetExceeded("block build capacity exhausted")
                self._make_room(work_bytes + 2048)
                reservation = self.budget.reserve(self.owner, work_bytes + 2048)
                admission = reservation.__enter__()
                flight = _Flight(Future(), owner_thread=threading.get_ident())
                self._flights[cache_key] = flight
                owner = True
                self._metrics["builds"] += 1
            else:
                if flight.owner_thread == threading.get_ident() and flight.running:
                    raise RuntimeError("a block builder cannot join its own in-flight build")
                flight.participants += 1
                self._metrics["joins"] += 1
            self._claimed += 1
            self._publish_usage()
        if owner:
            try:
                summary = build()
                if (not isinstance(summary, AggregateSummary) or summary.target != key.series
                        or summary.algorithm_version != key.algorithm_version
                        or not summary.revisions_known or summary.revisions != view.revisions
                        or not summary.coverage.ranges or len(summary.coverage.ranges) > self.max_ranges
                        or summary.coverage.ranges[0][0] < key.start_ms
                        or summary.coverage.ranges[-1][1] > key.end_ms):
                    raise ValueError("block result violates its identity, bounds or dependency contract")
                size = retained_size((cache_key, summary))[0] + 1024 + 256 * len(view.revisions)
                if size > work_bytes:
                    raise MemoryBudgetExceeded("block result exceeds declared build allowance")
                with self._lock:
                    self._check_view(view)
                    if flight.invalid or flight.future.done():
                        raise BlockRevisionChanged("late block build cannot be adopted")
                    self._version += 1
                    entry = _Entry(SharedBlock(key, self._version, summary), size, flight.participants)
                    cost = size + entry.pins * self.LEASE_BYTES
                    self._make_room(cost, slots=1)
                    def commit():
                        self._entries[cache_key] = entry
                        for dep in view.revisions:
                            self._dependencies.setdefault((dep.series, dep.domain), set()).add(cache_key)
                        self._bytes += cost
                        self._publish_usage()
                    admission.retain(cost, commit)
                    flight.future.set_result(entry)
            except BaseException as exc:
                with self._lock:
                    self._metrics["stale_builds" if isinstance(exc, BlockRevisionChanged) else "failures"] += 1
                    if not flight.future.done():
                        kind = type(exc) if type(exc) in (
                            BlockRevisionChanged, BlockUnavailable, MemoryBudgetExceeded,
                            ValueError, TypeError, RuntimeError, TimeoutError, CancelledError,
                            KeyboardInterrupt, SystemExit,
                        ) else BlockUnavailable
                        flight.future.set_result(_Failure(kind, str(exc)[:512]))
            finally:
                reservation.__exit__(None, None, None)
                with self._lock:
                    flight.running = False
        claimed_lease = False
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise CancelledError()
                try:
                    entry = flight.future.result(timeout=0.05)
                    break
                except TimeoutError:
                    continue
            if isinstance(entry, _Failure):
                raise entry.kind(entry.message)
            with self._lock:
                self._check_view(view)
                if not entry.valid:
                    raise BlockRevisionChanged("joined block was invalidated")
                lease = BlockLease(self, view, entry)
                view.leases.add(lease)
                claimed_lease = True
                return lease
        finally:
            with self._lock:
                flight.participants -= 1
                if not claimed_lease:
                    if flight.future.done() and isinstance(flight.future.result(), _Entry):
                        self._release_pin(flight.future.result())
                    else:
                        self._claimed -= 1
                if not flight.participants and not flight.running:
                    self._flights.pop(cache_key, None)
                self._publish_usage()
