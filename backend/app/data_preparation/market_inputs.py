"""Bounded immutable market objects and actual-time display projections.

Owned by the acquisition adapter, not a replay run. Public/blind timestamps,
accounts and indicator state never enter this cache. Misses use the verified
object reader; projection preserves the general BAR builder fallback.
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, fields, is_dataclass
from threading import RLock
from types import MappingProxyType

from .models import PreparationError


def retained_size(value, seen=None):
    """Charge owned Python storage, including strings and tuple/key overhead."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, Mapping):
        # MappingProxyType hides its backing dict's allocation.
        if isinstance(value, MappingProxyType):
            size += sys.getsizeof(dict(value))
        size += sum(
            retained_size(k, seen) + retained_size(v, seen) for k, v in value.items()
        )
    elif isinstance(value, (tuple, list)):
        size += sum(retained_size(v, seen) for v in value)
    elif is_dataclass(value):
        size += sum(retained_size(getattr(value, f.name), seen) for f in fields(value))
    return size


class MarketObjectCache:
    """One byte budget and bounded single-flight ownership for both layers."""

    def __init__(self, *, max_bytes=64 * 1024**2, max_inflight=8, max_entries=4096):
        if min(max_bytes, max_inflight, max_entries) < 1:
            raise ValueError("market cache budgets must be positive")
        self.max_bytes, self.max_inflight = max_bytes, max_inflight
        self.max_entries = max_entries
        self._lock = RLock()
        self._entries = OrderedDict()
        self._pending = {}
        self._generation = 0
        self._bytes = 0
        self._counts = {"hits": 0, "misses": 0, "shared": 0, "evictions": 0}

    def get(self, key, load):
        with self._lock:
            if key in self._entries:
                self._counts["hits"] += 1
                value, size = self._entries.pop(key)
                self._entries[key] = (value, size)
                return value
            pending_key = (self._generation, key)
            flight = self._pending.get(pending_key)
            owner = flight is None
            if owner:
                if len(self._pending) >= self.max_inflight:
                    raise PreparationError(
                        "HISTORY_CACHE_BUSY",
                        "Market input preparation is busy; retry",
                        retryable=True,
                    )
                flight = self._pending[pending_key] = Future()
                self._counts["misses"] += 1
            else:
                self._counts["shared"] += 1
            generation = self._generation
        if not owner:
            return flight.result()
        try:
            value = load()
            if isinstance(value, SizedValue):
                value, size = value.value, value.size + retained_size(key) + 256
            else:
                size = retained_size((key, value)) + 256
            with self._lock:
                if generation == self._generation and size <= self.max_bytes:
                    while self._entries and (
                        self._bytes + size > self.max_bytes
                        or len(self._entries) >= self.max_entries
                    ):
                        _, (_, removed) = self._entries.popitem(last=False)
                        self._bytes -= removed
                        self._counts["evictions"] += 1
                    self._entries[key] = (value, size)
                    self._bytes += size
            flight.set_result(value)
            return value
        except BaseException as exc:
            flight.set_exception(exc)
            # A Future with no waiters must not retain an unobserved exception.
            flight.exception()
            raise
        finally:
            with self._lock:
                del self._pending[pending_key]

    def clear(self):
        with self._lock:
            self._generation += 1
            self._entries.clear()
            self._bytes = 0

    def snapshot(self):
        with self._lock:
            return dict(
                **self._counts,
                retained_bytes=self._bytes,
                entries=len(self._entries),
                inflight=len(self._pending),
                max_bytes=self.max_bytes,
                max_inflight=self.max_inflight,
                max_entries=self.max_entries,
            )


@dataclass(frozen=True, slots=True)
class MarketRows(Sequence):
    """A request selection of immutable rows, with exact content identities."""

    rows: tuple
    sources: tuple
    cache: MarketObjectCache

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]

    @classmethod
    def join(cls, parts, start, end):
        parts = tuple(parts)
        selected = tuple(
            row for part in parts for row in part if start <= row["open_time"] < end
        )
        if not parts or not all(
            isinstance(part, cls) and part.cache is parts[0].cache for part in parts
        ):
            return list(selected)
        sources = tuple(source for part in parts for source in part.sources)
        return cls(selected, sources, parts[0].cache)


@dataclass(frozen=True, slots=True)
class SizedValue:
    value: object
    size: int


def frozen_object(data):
    # Stored input rows contain scalar provider fields only. Rejecting nested
    # values here would change the legacy importer; freeze them recursively.
    def freeze(value):
        if isinstance(value, dict):
            size = sys.getsizeof(value)
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    value[key], child_size = freeze(child)
                else:
                    child_size = sys.getsizeof(child)
                # Conservatively charge repeated/shared keys and scalar values
                # too. Count while freezing, avoiding a second full row walk.
                size += sys.getsizeof(key) + child_size
            proxy = MappingProxyType(value)
            return proxy, size + sys.getsizeof(proxy)
        if isinstance(value, list):
            values, size = [], 0
            for child in value:
                if isinstance(child, (dict, list)):
                    child, child_size = freeze(child)
                else:
                    child_size = sys.getsizeof(child)
                values.append(child)
                size += child_size
            values = tuple(values)
            return values, size + sys.getsizeof(values)
        return value, sys.getsizeof(value)

    value, size = freeze(data)
    return SizedValue(value, size)


def detached_value(value):
    if isinstance(value, Mapping):
        return {
            key: detached_value(child) if isinstance(child, (Mapping, tuple)) else child
            for key, child in value.items()
        }
    if isinstance(value, tuple):
        return [detached_value(child) for child in value]
    return value
