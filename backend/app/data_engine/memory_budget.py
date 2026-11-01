"""Shared resource accounting/admission for D126 consumers.

Owners retain their eviction algorithms. Leases protect in-flight allocations;
the registry never deletes durable recovery data or active aggregation state.
Heap traversal is opt-in diagnostics, never part of a tick or a cache read.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from functools import wraps
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import sys
import threading


class MemoryBudgetExceeded(RuntimeError):
    pass


class MemoryReservation:
    """Transfer admitted work to retained owner state under one budget lock.

    The synchronous commit callback must update the owner's cheap usage counter
    before returning. It must not acquire another owner's lock or perform I/O.
    Failed admission leaves the reservation intact for normal context cleanup.
    """
    def __init__(self, budget, owner, size):
        self.budget, self.owner, self.size = budget, owner, size
        self.active = True

    def retain(self, bytes_needed, commit):
        if bytes_needed < 0:
            raise ValueError("retained size must be non-negative")
        with self.budget._lock:
            if not self.active:
                raise RuntimeError("memory reservation has already been consumed")
            snapshot = self.budget.snapshot()
            item = snapshot["owners"][self.owner]
            if (snapshot["estimated_bytes"] + snapshot["reserved_bytes"] - self.size + bytes_needed > self.budget.total_bytes
                    or item.get("estimated_bytes", 0) + item["reserved_bytes"] - self.size + bytes_needed > item["limit_bytes"]):
                self.budget.rejections += 1
                raise MemoryBudgetExceeded(f"retained memory admission deferred for {self.owner}")
            commit()
            self.budget._reserved[self.owner] -= self.size
            self.size = 0
            self.active = False


_work_leases = ContextVar("market_data_memory_leases", default=None)


def budgeted_query(function):
    """Keep synchronous history leases through adoption and publication.

    Nested source reads borrow the outer query's scope so retained components
    cannot outlive their admission lease between pages.
    """
    @wraps(function)
    def run(*args, **kwargs):
        if _work_leases.get() is not None:
            return function(*args, **kwargs)
        with ExitStack() as leases:
            token = _work_leases.set(leases)
            try:
                return function(*args, **kwargs)
            finally:
                _work_leases.reset(token)
    return run


def budgeted_work(function):
    @wraps(function)
    async def run(self, *args, **kwargs):
        with ExitStack() as leases:
            token = _work_leases.set(leases)
            try:
                return await function(self, *args, **kwargs)
            finally:
                _work_leases.reset(token)
    return run


def reserve_work(budget, owner, bytes_needed):
    if budget is not None:
        leases = _work_leases.get()
        if leases is None:
            raise RuntimeError("memory reservation requires a work scope")
        leases.enter_context(budget.reserve(owner, bytes_needed))


def retained_size(roots, seen=None):
    """Count reachable value/container objects once; do not traverse services."""
    seen = set() if seen is None else seen
    pending = list(roots)
    total = objects = 0
    while pending:
        value = pending.pop()
        if id(value) in seen or value is None or isinstance(value, (type, bool)):
            continue
        seen.add(id(value))
        total += sys.getsizeof(value)
        objects += 1
        if isinstance(value, Mapping):
            pending.extend(value.keys())
            pending.extend(value.values())
            if hasattr(value, "_values"):
                total += sys.getsizeof(dict(value))  # private map backing allocation
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
        elif is_dataclass(value):
            if hasattr(value, "__dict__"):
                pending.append(vars(value))
            else:
                pending.extend(getattr(value, field.name) for field in fields(value))
    return total, objects


class MemoryBudget:
    def __init__(self, total_bytes=256 * 1024 * 1024):
        if total_bytes <= 0:
            raise ValueError("total memory budget must be positive")
        self.total_bytes = int(total_bytes)
        self._owners = {}
        self._reserved = {}
        self._lock = threading.RLock()
        self.rejections = 0

    def register(self, owner, *, limit_bytes, usage, roots=None):
        """usage returns cheap estimated bytes/counts; roots is diagnostic only."""
        if limit_bytes <= 0:
            raise ValueError("owner budget must be positive")
        with self._lock:
            if owner in self._owners:
                raise ValueError(f"memory owner already registered: {owner}")
            self._owners[owner] = (int(limit_bytes), usage, roots)
            self._reserved[owner] = 0

    def unregister(self, owner):
        with self._lock:
            if self._reserved.get(owner, 0):
                raise RuntimeError("cannot unregister an owner with active leases")
            self._owners.pop(owner, None)
            self._reserved.pop(owner, None)

    def snapshot(self, *, measure_heap=False):
        with self._lock:
            owners = dict(self._owners)
            reserved = dict(self._reserved)
        result = {}
        seen = set()
        for name, (limit, usage, roots) in owners.items():
            item = dict(usage())
            used = max(0, int(item.get("estimated_bytes", 0)))
            item.update(limit_bytes=limit, reserved_bytes=reserved[name],
                        over_budget_bytes=max(0, used + reserved[name] - limit))
            if measure_heap and roots is not None:
                item["unique_retained_bytes"], item["unique_objects"] = retained_size(roots(), seen)
            result[name] = item
        estimated = sum(item.get("estimated_bytes", 0) for item in result.values())
        total_reserved = sum(reserved.values())
        return {"limit_bytes": self.total_bytes, "estimated_bytes": estimated,
                "reserved_bytes": total_reserved, "over_budget_bytes": max(0, estimated + total_reserved - self.total_bytes),
                "admission_rejections": self.rejections, "owners": result,
                "heap_measurement": "deduplicated reachable Python values; excludes allocator/RSS and external memory" if measure_heap else "not_requested"}

    @contextmanager
    def reserve(self, owner, bytes_needed):
        if bytes_needed < 0:
            raise ValueError("reservation must be non-negative")
        with self._lock:
            if owner not in self._owners:
                raise KeyError(owner)
            snapshot = self.snapshot()
            item = snapshot["owners"][owner]
            if (snapshot["estimated_bytes"] + snapshot["reserved_bytes"] + bytes_needed > self.total_bytes
                    or item.get("estimated_bytes", 0) + item["reserved_bytes"] + bytes_needed > item["limit_bytes"]):
                self.rejections += 1
                raise MemoryBudgetExceeded(f"memory admission deferred for {owner}")
            self._reserved[owner] += bytes_needed
        lease = MemoryReservation(self, owner, bytes_needed)
        try:
            yield lease
        finally:
            with self._lock:
                self._reserved[owner] -= lease.size
                lease.size = 0
                lease.active = False
