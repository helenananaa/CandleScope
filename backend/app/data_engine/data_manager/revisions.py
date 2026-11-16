"""One cache adoption owner; storage supplies the durable change contract."""
from __future__ import annotations

from functools import wraps
from inspect import signature
from itertools import islice
from contextlib import nullcontext
from collections import deque
from dataclasses import dataclass
import threading
import sys
import time

from .models import BarData, QueryResult, QuerySource, SeriesKey
from app.data_engine.storage.revisions import ensure_acquisition, StaleAcquisition
from app.data_engine.memory_budget import MemoryBudgetExceeded, budgeted_query


class RevisionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HistoryReadback:
    key: SeriesKey
    revision: int
    bounds: tuple[int, int] | None


def _key_estimated_bytes(key):
    # Conservative value estimate, including full variable-length identity.
    # Shared string/key references may be counted repeatedly here; opt-in heap
    # diagnostics deduplicate the actual values instead.
    return sys.getsizeof(key) + sum(sys.getsizeof(getattr(key, name)) for name in key.__slots__)


class CacheRevisionConsumer:
    """Pull coalesced changes on a default 50 ms polling schedule.

    No subscription/listener lifecycle, and no unbounded process-local series
    tombstones. Failure leaves the watermark unchanged so the next read retries.
    A new process starts at zero and can reconstruct after missed notifications.
    """
    def __init__(self, cache, store, *, poll_seconds=0.05):
        self.cache, self.store = cache, store
        self.poll_seconds = poll_seconds
        self.revision = 0
        self.checked_at = 0.0
        self.failures = 0
        self.invalidations = 0
        self.resets = 0
        self._lock = threading.RLock()
        self._recent = deque(maxlen=4096)
        self._history_floor = 0
        self._recent_bytes = 0
        self._readback_bytes = 0
        self.on_rewind = None
        self.readbacks_enabled = False
        self._readbacks: dict[SeriesKey, HistoryReadback] = {}
        self._readback_reset: object | None = None

    def sync(self, *, force=False):
        with self._lock:
            if not force and time.monotonic() - self.checked_at < self.poll_seconds:
                return self.revision
            try:
                batch = self.store.changes_since(self.revision)
                if batch["reset"]:
                    self.cache.clear()
                    self.resets += 1
                    self._recent.clear()
                    self._recent_bytes = 0
                    self._history_floor = int(batch["revision"])
                    if self.readbacks_enabled:
                        self._reset_readbacks()
                    if self._history_floor < self.revision and self.on_rewind is not None:
                        self.on_rewind()
                else:
                    for change in batch["changes"]:
                        key = SeriesKey(**{name: change[name] for name in (
                            "symbol", "interval", "exchange", "market_type", "provider_id",
                            "venue", "asset_class", "series_variant", "price_adjustment",
                            "session_variant", "volume_semantics")})
                        self.cache.invalidate(key)
                        self.cache.invalidate_dependents(key)
                        if self.readbacks_enabled and (change.get("readback_revision") or 0) > self.revision:
                            self._queue_readback(key, change)
                        if len(self._recent) == self._recent.maxlen:
                            self._history_floor = max(self._history_floor, self._recent[0][0])
                            self._recent_bytes -= 512 + _key_estimated_bytes(self._recent[0][1])
                        self._recent.append((int(change["revision"]), key))
                        self._recent_bytes += 512 + _key_estimated_bytes(key)
                        self.invalidations += 1
                self.revision = int(batch["revision"])
                self.checked_at = time.monotonic()
                return self.revision
            except Exception as exc:
                self.failures += 1
                raise RevisionUnavailable("durable cache revision is unavailable") from exc

    def _reset_readbacks(self):
        self._readbacks.clear()
        self._readback_bytes = 0
        self._readback_reset = object()

    def _queue_readback(self, key, change):
        if self._readback_reset is not None:
            return
        previous = self._readbacks.get(key)
        if previous is None and len(self._readbacks) >= self._recent.maxlen:
            self._reset_readbacks()
            return
        start, end = change["readback_start_ms"], change["readback_end_ms"]
        # The database keeps the last exact mutation. If an observer skipped
        # another mutation of this series, the safe range is the whole series.
        bounds = ((start, end) if start is not None and end is not None
                  and change["readback_previous"] <= self.revision else None)
        if previous is not None:
            if previous.revision == change["readback_revision"]:
                return  # retry after a partially adopted batch
            bounds = (
                (min(bounds[0], previous.bounds[0]), max(bounds[1], previous.bounds[1]))
                if bounds is not None and previous.bounds is not None else None
            )
        if previous is None:
            self._readback_bytes += 512 + _key_estimated_bytes(key)
        self._readbacks[key] = HistoryReadback(key, change["readback_revision"], bounds)

    def readback_pending(self, key):
        with self._lock:
            if not self.readbacks_enabled:
                return False
            family = _family(key)
            return self._readback_reset is not None or any(_family(other) == family for other in self._readbacks)

    def pending_readbacks(self):
        with self._lock:
            return self._readback_reset, tuple(islice(self._readbacks.values(), 64))

    def acknowledge_readback(self, receipt):
        with self._lock:
            if self._readback_reset is receipt:
                self._readback_reset = None
            elif isinstance(receipt, HistoryReadback) and self._readbacks.get(receipt.key) is receipt:
                del self._readbacks[receipt.key]
                self._readback_bytes -= 512 + _key_estimated_bytes(receipt.key)

    def conflicts(self, revision, key, accepted=None):
        accepted = accepted or {}
        with self._lock:
            return revision < self._history_floor or any(
                changed > max(revision, accepted.get((other.exchange, other.market_type,
                    other.symbol, other.interval, *other.identity.storage_values), 0))
                and _family(other) == _family(key) for changed, other in self._recent)

    def memory_usage(self):
        with self._lock:
            return {"revision_recent_entries": len(self._recent),
                    "revision_pending_readbacks": len(self._readbacks),
                    "revision_reset_pending": self._readback_reset is not None,
                    "revision_estimated_bytes": self._recent_bytes + self._readback_bytes
                        + (64 if self._readback_reset is not None else 0)}

    def _memory_roots(self):
        # Private diagnostic roots only; do not expose mutable queue containers.
        with self._lock:
            return [list(self._recent), dict(self._readbacks), self._readback_reset]

    def snapshot(self):
        with self._lock:
            return {"revision": self.revision, "poll_interval_ms": self.poll_seconds * 1000,
                    "observed_age_ms": max(0, (time.monotonic() - self.checked_at) * 1000),
                    "failures": self.failures, "invalidations": self.invalidations,
                    "resets": self.resets}

    def adopt(self, key, load):
        """Canonicalize an unversioned notification before cache/event use."""
        for _ in range(2):
            self.sync(force=True)
            with self.cache.read_token(key) as token:
                bars = [BarData.from_storage_row(row, exchange=key.exchange,
                        market_type=key.market_type) for row in load()]
                if self.cache.bulk_load_if_unchanged(key, bars, read_token=token):
                    return bars
        raise RevisionUnavailable("canonical publication changed during adoption")


def revision_checked_query(function):
    """Public range/before contract, including derived reads and min_revision.

    Default complete cache hits may lag for the configured poll interval.
    Storage/derived work validates the durable head before publication. A
    conflicting result is explicitly pending; callers retry a fresh request.
    """
    positional_names = tuple(signature(function).parameters)[3:]
    @wraps(function)
    def query(self, symbol, interval, *args, min_revision=None, **kwargs):
        context = {**dict(zip(positional_names, args)), **kwargs}
        if min_revision is not None and (type(min_revision) is not int or min_revision < 0):
            raise ValueError("min_revision must be a non-negative integer")
        consumer = self._cache.revision_consumer
        if consumer is None:
            if min_revision is None:
                return function(self, symbol, interval, *args, **kwargs)
            return _pending(symbol, interval, context, "revision_unsupported", min_revision)
        try:
            before = consumer.sync(force=min_revision is not None)
            if min_revision is not None and before < min_revision:
                return _pending(symbol, interval, context, "min_revision_pending", min_revision, before)
            limit = kwargs.get("limit")
            if limit is None:
                position = 1 if function.__name__ == "query_before" else 2
                limit = args[position] if len(args) > position else self._cfg.default_limit
            limit = min(int(limit or self._cfg.default_limit), self._cfg.max_limit)
            budget = getattr(self, "memory_budget", None)
            # Small warm pages already have bounded container allocation. Deep
            # reads reserve their working/output allowance before acquisition.
            lease = budget.reserve("history-query", limit * 1024) if budget and limit > 1000 else nullcontext()
            with lease, ensure_acquisition(before) as scope:
                result = function(self, symbol, interval, *args, **kwargs)
            # The native read path already revalidates every adoption. Custom
            # aggregation and all non-cache results must also validate the
            # complete source view (including multiple underlying series).
            after = consumer.sync(force=(not result.cache_hit or bool(result.metadata.get("storage_reads"))))
            result_key = SeriesKey(result.symbol, result.interval,
                exchange=result.exchange, market_type=result.market_type,
                **{name: getattr(result, name) for name in ("provider_id", "venue", "asset_class",
                    "series_variant", "price_adjustment", "session_variant", "volume_semantics")})
            if after < before or (
                consumer.conflicts(before, result_key, scope.accepted)
                and (result.metadata.get("derived_from") or not result.metadata.get("cache_read_retries"))
            ):
                # Evict any derived/unversioned late load performed by the
                # callback after the change was consumed by an inner query.
                self._cache.invalidate(result_key)
                return _pending(symbol, interval, context, "storage_revision_conflict", min_revision, after)
            result.metadata.update(storage_revision=after, required_revision=min_revision,
                                   revision_observation_age_ms=consumer.snapshot()["observed_age_ms"])
            return result
        except MemoryBudgetExceeded:
            return _pending(symbol, interval, context, "memory_budget_deferred", min_revision)
        except (RevisionUnavailable, StaleAcquisition):
            return _pending(symbol, interval, context, "revision_unavailable", min_revision)
    return budgeted_query(query)


def _pending(symbol, interval, kwargs, reason, required=None, observed=None):
    identity = kwargs.get("series_identity")
    return QueryResult(bars=[], symbol=symbol, interval=interval,
                       exchange=kwargs.get("exchange", "binance"), market_type=kwargs.get("market_type", "spot"),
                       **(identity.to_dict() if identity else {}), source=QuerySource.EMPTY,
                       total=0, has_more=True, cache_hit=False, history_state="pending", complete=False,
                       retryable=True, metadata={reason: True, "required_revision": required,
                                                 "storage_revision": observed})


def _family(key):
    return key.exchange, key.market_type, key.symbol, key.identity.storage_values
