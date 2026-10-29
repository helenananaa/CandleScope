"""Public physical-attempt admission. Business queues retain ordering and retries.

One instance per budget owner/event loop, using the existing RateLimitManager.
No second token ledger, cross-venue substitution, or cancellation refunds.
"""
from __future__ import annotations

import asyncio
import contextvars
import itertools
import time
from collections import Counter, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .rate_limits import (
    HistoricalRequest, RateLimitAdmission, RateLimitDeferred, RateLimitManager,
    RateLimitReservation, RateLimitRule, get_shared_rate_limit_manager,
)

_fairness_tickets = itertools.count()


class TrafficClass(IntEnum):
    REQUIRED = 0
    INTERACTIVE = 10
    RECOVERY = 20
    NORMAL = 50
    BACKGROUND = 100


@dataclass(eq=False)
class PublicDemand:
    traffic_class: TrafficClass = TrafficClass.NORMAL
    owner: str = "public"
    purpose: str = "public_request"
    deadline: float | None = None
    defer: bool = False
    # A deferred business chunk supplies a liveness check. Ordinary waiting
    # tasks remove their intent on exit, including cancellation.
    alive: Callable[[], bool] | None = field(default=None, repr=False)
    dependencies: list[PublicDemand] = field(default_factory=list, repr=False)
    wait_started: float | None = field(default=None, repr=False)
    bypasses: int = field(default=0, repr=False)
    wait_ticket: int | None = field(default=None, repr=False)

    def priority(self) -> TrafficClass:
        own = self.traffic_class if self.alive is None or self.alive() else TrafficClass.BACKGROUND
        return min([own, *(item.priority() for item in self.dependencies)])

    def inherit(self, demand: PublicDemand) -> None:
        if demand is self:
            return
        self.dependencies[:] = [item for item in self.dependencies
                                if item.alive is None or item.alive()]
        if demand not in self.dependencies:
            self.dependencies.append(demand)
            # Metadata loads may be joined repeatedly while a business queue
            # retries. Retain a bounded set, prioritizing live critical owners.
            if len(self.dependencies) > 128:
                self.dependencies.sort(key=lambda item: item.priority())
                del self.dependencies[128:]


_current: contextvars.ContextVar[PublicDemand | None] = contextvars.ContextVar(
    "public_market_demand", default=None,
)


def current_demand() -> PublicDemand:
    return _current.get() or PublicDemand()


@contextmanager
def public_demand(demand: PublicDemand) -> Iterator[PublicDemand]:
    token = _current.set(demand)
    try:
        yield demand
    finally:
        _current.reset(token)


@dataclass
class _Intent:
    demand: PublicDemand
    keys: frozenset[str]
    since: float
    rules: list[RateLimitRule] = field(default_factory=list)
    request: HistoricalRequest | None = None
    resource: Any = None


@dataclass
class PublicPermit:
    scheduler: PublicAdmission
    attempt_id: int
    reservations: list[RateLimitReservation]
    demand: PublicDemand
    started: float
    traffic_class: TrafficClass = TrafficClass.NORMAL
    settled: bool = False
    proxy_route: Any = None
    resource: Any = None
    resource_lease: Any = None

    @property
    def manager(self) -> RateLimitManager:
        return self.scheduler.manager

    @property
    def rule(self) -> RateLimitRule:
        return self.reservations[0].rule

    @property
    def request(self) -> HistoricalRequest:
        return self.reservations[0].request

    def record_response(self, **feedback: Any) -> bool:
        if self.settled:
            return False
        recorded = False
        for reservation in self.reservations:
            recorded = reservation.record_response(**feedback) or recorded
        if all(r.settled for r in self.reservations):
            self.settled = True
            self.scheduler._finish(self, feedback)
        return recorded

    def finish(self, **feedback: Any) -> None:
        if self.settled:
            return
        self.record_response(**feedback)


class PublicAdmission:
    """Bounded, resource-specific priority admission with atomic constraints.

    Pending critical demands protect their shared quota and execution slots.
    Critical work normally wins. After a bounded number of competing grants,
    the oldest bypassed demand gets one turn, without bypassing any quota or
    concurrency rule. This bounds starvation in executable work, not wall time
    while the source is unavailable. Deferred business retries retain their age.
    """

    def __init__(self, manager: RateLimitManager, *, max_in_flight: int = 32,
                 max_pending: int = 1024, max_priority_bypass: int = 8) -> None:
        self.manager = manager
        self.max_in_flight = max(1, max_in_flight)
        self.max_pending = max(1, max_pending)
        self.max_priority_bypass = max(1, max_priority_bypass)
        self.priority_enabled = True
        self._ids = itertools.count(1)
        self._intents: dict[int, _Intent] = {}
        self._protected: dict[PublicDemand, _Intent] = {}
        self._lock = asyncio.Lock()
        self._active: dict[int, PublicPermit] = {}
        self._by_bucket: Counter[str] = Counter()
        self._counts: Counter[str] = Counter()
        self._recent: deque[dict[str, Any]] = deque(maxlen=128)

    def forget(self, demand: PublicDemand) -> None:
        if self._protected.pop(demand, None) is not None:
            self.manager.notify_change()

    def refresh(self) -> None:
        """Wake consumers after business cancellation, completion or promotion."""
        self._prune()
        self.manager.notify_change()

    def set_priority_enabled(self, enabled: bool) -> None:
        """Rollback scheduling policy without resetting quota/cooldown/in-flight state."""
        self.priority_enabled = bool(enabled)
        self.manager.notify_change()

    def protect(self, demand: PublicDemand, bucket: str, *, rules=(), request=None, resource=None) -> None:
        self._prune()
        if len(self._protected) < self.max_pending or demand in self._protected:
            if demand.wait_started is None:
                demand.wait_started = time.monotonic()
                demand.wait_ticket = next(_fairness_tickets)
            keys = frozenset((bucket,)) | frozenset(resource.keys if resource else ())
            previous = self._protected.get(demand)
            self._protected[demand] = _Intent(demand, keys, demand.wait_started, list(rules), request, resource)
            if (previous is None or previous.keys != keys or previous.rules != list(rules)
                    or previous.request != request):
                self.manager.notify_change()

    def _prune(self) -> None:
        for demand in tuple(self._protected):
            if demand.alive is not None and not demand.alive():
                self.forget(demand)

    def _deferred(self, rule: RateLimitRule, request: HistoricalRequest,
                  reason: str, delay: float = 0.05) -> RateLimitDeferred:
        now = time.monotonic()
        return RateLimitDeferred(RateLimitAdmission(
            False, rule.bucket_key, rule.request_cost(request), reason, delay,
            now + delay, int((time.time() + delay) * 1000), rule.name,
        ))

    def _rank(self, intent: _Intent) -> tuple:
        if intent.demand.bypasses >= self.max_priority_bypass:
            return (0, intent.demand.wait_ticket or 0, 0)
        return (1, int(intent.demand.priority()), intent.demand.wait_ticket or 0)

    async def _protects(self, other: _Intent, current: _Intent) -> bool:
        if other.demand is current.demand or self._rank(other) >= self._rank(current):
            return False
        if not other.keys & current.keys:
            return False
        if other.resource is not None and not other.resource.available():
            return False
        # A composite request blocked by an unrelated resource cannot fence
        # runnable work. Shared quota may accumulate for an aged costly request.
        for rule in other.rules:
            if rule.bucket_key not in current.keys:
                if not (await self.manager.inspect(rule, other.request)).allowed:
                    return False
                if rule.max_concurrency and self._by_bucket[rule.bucket_key] >= rule.max_concurrency:
                    return False
        return True

    async def _higher_priority_can_run(self, current: _Intent) -> bool:
        """Protect scarce shared execution slots only for executable work.

        A higher-priority waiter blocked by an unrelated quota must not fence
        the entire process. Deferred business interests protect quota only.
        """
        for intent in self._intents.values():
            if intent.demand is current.demand or self._rank(intent) >= self._rank(current):
                continue
            if intent.resource is not None and not intent.resource.available():
                continue
            ready = True
            for rule in intent.rules:
                if rule.max_concurrency and self._by_bucket[rule.bucket_key] >= rule.max_concurrency:
                    ready = False
                    break
                if not (await self.manager.inspect(rule, intent.request)).allowed:
                    ready = False
                    break
            if ready:
                return True
        return False

    async def acquire(self, rules: list[RateLimitRule], request: HistoricalRequest,
                      *, demand: PublicDemand | None = None, resource: Any = None) -> PublicPermit:
        if not rules:
            raise ValueError("physical admission requires at least one constraint")
        demand = demand or current_demand()
        self._prune()
        keys = frozenset(rule.bucket_key for rule in rules) | frozenset(resource.keys if resource else ())
        if len(self._intents) >= self.max_pending:
            raise self._deferred(rules[0], request, "admission_queue_full")
        intent_id = next(self._ids)
        if demand.wait_started is None:
            demand.wait_started = time.monotonic()
            demand.wait_ticket = next(_fairness_tickets)
        current = _Intent(demand, keys, demand.wait_started, rules, request, resource)
        self._intents[intent_id] = current
        granted = False
        try:
            while True:
                async with self._lock:
                    self._prune()
                    error = None
                    for intent in (*self._intents.values(), *self._protected.values()):
                        if self.priority_enabled and await self._protects(intent, current):
                            error = self._deferred(rules[0], request, "critical_demand", 0.25)
                            break
                    if error is None and len(self._active) >= self.max_in_flight:
                        error = self._deferred(rules[0], request, "execution_capacity", 0.25)
                    if (error is None and self.priority_enabled
                            and len(self._active) >= self.max_in_flight - 1
                            and await self._higher_priority_can_run(current)):
                        error = self._deferred(rules[0], request, "execution_priority", 0.25)
                    for rule in rules:
                        if rule.max_concurrency and self._by_bucket[rule.bucket_key] >= rule.max_concurrency:
                            error = self._deferred(rule, request, "endpoint_concurrency", 0.25)
                            break
                    if error is None:
                        lease = None
                        try:
                            # External resources expose synchronous atomic try-
                            # reserve/release. Never hold them while waiting for
                            # quota, and never debit quota if reservation fails.
                            if resource is not None:
                                for rule in rules:
                                    admission = await self.manager.inspect(rule, request)
                                    if not admission.allowed:
                                        raise RateLimitDeferred(admission)
                                lease = resource.reserve()
                            reservations = await self.manager.acquire_many_nowait(rules, request)
                        except BaseException as exc:
                            if lease is not None:
                                resource.release(lease)
                            if isinstance(exc, RateLimitDeferred):
                                error = exc
                            else:
                                raise
                        else:
                            permit = PublicPermit(self, next(self._ids), reservations, demand,
                                                  time.monotonic(), demand.priority(),
                                                  resource=resource, resource_lease=lease)
                            self._active[permit.attempt_id] = permit
                            granted = True
                            self._by_bucket.update(r.rule.bucket_key for r in reservations)
                            self._counts["attempts"] += 1
                            self._counts[f"class_{demand.priority().name.lower()}"] += 1
                            aged_grant = demand.bypasses >= self.max_priority_bypass
                            if aged_grant:
                                self._counts["fairness_grants"] += 1
                            seen = set()
                            for waiting in (*self._intents.values(), *self._protected.values()):
                                if waiting.demand is demand or waiting.demand in seen:
                                    continue
                                seen.add(waiting.demand)
                                if waiting.keys & keys or len(self._active) >= self.max_in_flight:
                                    # One aged turn per fairness cycle. Otherwise
                                    # a whole old background cohort would leapfrog
                                    # foreground together and create a large burst.
                                    waiting.demand.bypasses = (0 if aged_grant else
                                        min(self.max_priority_bypass, waiting.demand.bypasses + 1))
                            demand.wait_started = None
                            demand.wait_ticket = None
                            demand.bypasses = 0
                            if demand.deadline is not None and permit.started > demand.deadline:
                                self._counts["deadline_misses"] += 1
                            return permit
                self._counts[f"deferred_{error.reason}"] += 1
                if demand.defer:
                    raise error
                await self.manager.wait_for_change(error.retry_after_seconds)
        finally:
            self._intents.pop(intent_id, None)
            # A non-blocking failed inspection changes no resource. Waking all
            # peers here lets deferred consumers wake each other indefinitely.
            if granted or not demand.defer:
                self.manager.notify_change()

    def _finish(self, permit: PublicPermit, feedback: dict[str, Any]) -> None:
        self._active.pop(permit.attempt_id, None)
        if permit.resource is not None:
            permit.resource.release(permit.resource_lease)
        for reservation in permit.reservations:
            key = reservation.rule.bucket_key
            self._by_bucket[key] -= 1
            if self._by_bucket[key] <= 0:
                del self._by_bucket[key]
        self._counts["unknown" if feedback.get("response_unknown") else "completed"] += 1
        self._recent.append({
            "attempt_id": permit.attempt_id,
            "buckets": [r.rule.bucket_key for r in permit.reservations],
            "costs": [r.rule.request_cost(r.request) for r in permit.reservations],
            "traffic_class": permit.traffic_class.name.lower(),
            "elapsed_ms": round((time.monotonic() - permit.started) * 1000, 3),
            "status_code": feedback.get("status_code"),
            "unknown": bool(feedback.get("response_unknown")),
        })
        self.manager.notify_change()

    def snapshot(self) -> dict[str, Any]:
        self._prune()
        return {
            "owner_scope": "backend_event_loop_and_catalog_worker",
            "coverage": "host_estimate_external_consumers_unknown",
            "priority_enabled": self.priority_enabled,
            "fairness": {"policy": "bounded_priority_bypass", "max_competing_grants": self.max_priority_bypass},
            "pending": len(self._intents), "protected": len(self._protected), "in_flight": len(self._active),
            "oldest_wait_seconds": max(
                (time.monotonic() - i.since for i in self._intents.values()), default=0.0),
            "counts": dict(self._counts), "recent": list(self._recent),
        }


_broker: contextvars.ContextVar[Any] = contextvars.ContextVar("public_admission_broker", default=None)


async def acquire_public(rules: list[RateLimitRule], request: HistoricalRequest,
                         *, manager: RateLimitManager | None = None) -> Any:
    broker = _broker.get()
    if broker is not None:
        return await broker.acquire(rules, request)
    return await get_public_admission(manager).acquire(rules, request)


def get_public_admission(manager: RateLimitManager | None = None) -> PublicAdmission:
    manager = manager or get_shared_rate_limit_manager()
    scheduler = getattr(manager, "_public_admission", None)
    if scheduler is None:
        scheduler = PublicAdmission(manager)
        manager._public_admission = scheduler
    return scheduler
