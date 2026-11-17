"""Shared resource accounting/admission for D126 consumers.

Owners retain their eviction algorithms. Leases protect in-flight allocations;
the registry never deletes durable recovery data or active aggregation state.
Heap traversal is opt-in diagnostics, never part of a tick or a cache read.
"""
from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager, ExitStack
from contextvars import ContextVar
from functools import wraps
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import sys
import asyncio
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass


class RetainedMetadata:
    """Opt-in value metadata included by owner diagnostic traversal."""
    __slots__ = ()

    def _memory_metadata(self):
        return ()


class MemoryBudgetExceeded(RuntimeError):
    def __init__(self, message, *, budget=None, owner=None, bytes_needed=None):
        super().__init__(message)
        self.budget, self.owner, self.bytes_needed = budget, owner, bytes_needed

    @property
    def waitable(self):
        return (self.budget is not None and self.owner in self.budget._owners
                and 0 < self.bytes_needed <= min(self.budget.total_bytes,
                    self.budget._owners[self.owner][0]))

    async def wait_for_capacity(self):
        await self.budget.wait_for_capacity(self.owner, self.bytes_needed)


class MemoryReservation:
    """Transfer admitted work to retained owner state under one budget lock.

    The synchronous commit callback must update the owner's cheap usage counter
    before returning. It must not acquire another owner's lock or perform I/O.
    Failed admission leaves the reservation intact for normal context cleanup.
    """
    def __init__(self, budget, owner, size, pool=None):
        self.budget, self.owner, self.size = budget, owner, size
        self.pool = pool
        self.active = True

    def retain(self, bytes_needed, commit, *, reclaim=None):
        if bytes_needed < 0:
            raise ValueError("retained size must be non-negative")
        with self.budget._lock:
            if not self.active:
                raise RuntimeError("memory reservation has already been consumed")
            if self.pool is not None:
                self.pool._grow(self, bytes_needed)
            else:
                self.budget._admit(self.owner, bytes_needed - self.size, reclaim,
                                   operation="retained memory")
            commit()
            self.budget._reserved[self.owner] -= self.size
            if self.pool is not None:
                self.pool.allocated -= self.size
                self.pool.children -= self.size
                self.pool.maximum -= self.size
            self.size = 0
            self.active = False
            self.budget._notify_capacity()

    def close(self):
        with self.budget._lock:
            if not self.active:
                return
            if self.pool is not None and self.pool.active:
                self.pool.children -= self.size
            else:
                self.budget._reserved[self.owner] -= self.size
                if self.pool is not None:
                    self.pool.allocated -= self.size
                    self.pool.children -= self.size
                    if not self.pool.allocated:
                        self.budget._work_pools.discard(self.pool)
            self.size = 0
            self.active = False
            self.budget._notify_capacity()


_pools = ContextVar('memory_work_pools', default=())


def current_work_pool(budget=None, owner='history-backfill'):
    return next((pool for pool in reversed(_pools.get()) if pool.active
                 and (budget is None or pool.budget is budget) and pool.owner == owner), None)


class MemoryWorkPool:
    """One admitted working set. Children borrow bytes, never race for them.

    A physical input lease can outlive its original work. Closing the work
    returns only unused capacity; outstanding children remain charged.
    """
    def __init__(self, budget, owner, size, maximum):
        self.budget, self.owner = budget, owner
        self.allocated, self.maximum = size, maximum
        self.children = 0
        self.active = True
        self.phase = 'work'

    @property
    def available(self):
        return self.allocated-self.children

    def reserve(self, size):
        if size < 0:
            raise ValueError('reservation must be non-negative')
        with self.budget._lock:
            if not self.active or size > self.available:
                raise MemoryBudgetExceeded('stage exceeds its admitted working set')
            self.children += size
            return MemoryReservation(self.budget,self.owner,size,pool=self)

    def _grow(self, child, size):
        delta = max(0,size-child.size)
        if delta > self.available:
            raise MemoryBudgetExceeded('retained value exceeds its admitted working set')
        self.children += delta
        child.size += delta

    async def resize(self, size):
        if size < self.children:
            raise ValueError('cannot withdraw active child allocations')
        if size > self.maximum:
            raise MemoryBudgetExceeded('execution working set exceeds the owner budget')
        await self.budget._acquire_pool(self.owner,size,size,pool=self)

    async def stage(self, size, maximum):
        """Return scratch before queueing the next phase's known claim.

        Retained plan/value children stay charged. The next maximum is declared
        before admitting more planners so future growth cannot deadlock.
        """
        with self.budget._lock:
            limit=min(self.budget.total_bytes,self.budget._owners[self.owner][0])
            if not self.children <= size <= maximum <= limit:
                raise MemoryBudgetExceeded('execution working set exceeds the owner budget')
            trim=max(0,self.allocated-size)
            self.budget._reserved[self.owner]-=trim
            self.allocated-=trim
            self.maximum=maximum
            self.active=False
            self.budget._notify_capacity()
        try:
            await self.budget._acquire_pool(self.owner,size,maximum,pool=self)
        except BaseException:
            with self.budget._lock:
                self.active=True
                self.close()
            raise

    def close(self):
        with self.budget._lock:
            if not self.active:
                return
            self.active = False
            self.budget._reserved[self.owner] -= self.available
            self.allocated = self.children
            self.maximum = self.children
            if not self.children:
                self.budget._work_pools.discard(self)
            self.budget._notify_capacity()

    @contextmanager
    def activate(self):
        token = _pools.set((*_pools.get(),self))
        try:
            yield self
        finally:
            _pools.reset(token)


@dataclass(eq=False)
class _PoolWaiter:
    owner: str
    size: int
    maximum: int
    future: object
    loop: object
    pool: object = None
    granted: object = None
    fairness: tuple = (100, 'anonymous')
    queued_at: float = 0


@asynccontextmanager
async def work_pool(budget, size, *, owner='history-backfill', managed=True, carry=None, maximum=None, phase='work'):
    if budget is None or not managed:
        yield None
        return
    state = budget.snapshot()['owners'][owner]
    maximum = min(budget.total_bytes,state['limit_bytes']-state.get('estimated_bytes',0),
                  maximum if maximum is not None else budget.total_bytes)
    needed = min(size,maximum)+(carry.children if carry is not None else 0)
    if needed > maximum:
        raise MemoryBudgetExceeded('retained inputs and planning exceed the owner budget')
    pool = await budget._acquire_pool(owner,needed,maximum,pool=carry)
    pool.phase=phase
    try:
        with pool.activate():
            yield pool
    finally:
        pool.close()


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
                pending.append(value._values)
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
        elif is_dataclass(value):
            if hasattr(value, "__dict__"):
                pending.append(vars(value))
            else:
                pending.extend(getattr(value, field.name) for field in fields(value))
        if isinstance(value, RetainedMetadata):
            pending.extend(value._memory_metadata())
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
        self._capacity_waiters = set()
        self._pool_waiters = OrderedDict()
        self._work_pools = set()
        self._work_pollers = {}
        self.work_grants = self.work_waits = self.work_resizes = 0
        self._work_turns = OrderedDict()
        self._work_turn = 0

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
            if self._reserved.get(owner, 0) or any(w.owner==owner for w in self._pool_waiters):
                raise RuntimeError("cannot unregister an owner with active leases")
            self._owners.pop(owner, None)
            self._reserved.pop(owner, None)

    def snapshot(self, *, measure_heap=False):
        with self._lock:
            owners = dict(self._owners)
            reserved = dict(self._reserved)
            phase_bytes={}
            for pool in self._work_pools:
                phase_bytes[pool.phase]=phase_bytes.get(pool.phase,0)+pool.allocated
        result = {}
        seen = set()
        # Owners may construct temporary diagnostic containers. Keep their
        # views alive across owners: otherwise Python can reuse an already
        # counted container's id and hide a later owner's unrelated graph.
        root_views = []
        for name, (limit, usage, roots) in owners.items():
            item = dict(usage())
            used = max(0, int(item.get("estimated_bytes", 0)))
            item.update(limit_bytes=limit, reserved_bytes=reserved[name],
                        over_budget_bytes=max(0, used + reserved[name] - limit))
            if measure_heap and roots is not None:
                view = roots()
                root_views.append(view)
                item["unique_retained_bytes"], item["unique_objects"] = retained_size(view, seen)
            result[name] = item
        estimated = sum(item.get("estimated_bytes", 0) for item in result.values())
        total_reserved = sum(reserved.values())
        return {"limit_bytes": self.total_bytes, "estimated_bytes": estimated,
                "reserved_bytes": total_reserved, "over_budget_bytes": max(0, estimated + total_reserved - self.total_bytes),
                "admission_rejections": self.rejections, "owners": result,
                "work_grants":self.work_grants,"work_waits":self.work_waits,
                "work_resizes":self.work_resizes,"work_waiters":len(self._pool_waiters),
                "work_phase_bytes":phase_bytes,
                "heap_measurement": "deduplicated reachable Python values; excludes allocator/RSS and external memory" if measure_heap else "not_requested"}

    def _shortfall(self, owner, delta):
        snapshot = self.snapshot()
        item = snapshot["owners"][owner]
        shared = snapshot["estimated_bytes"] + snapshot["reserved_bytes"] + delta - self.total_bytes
        local = item.get("estimated_bytes", 0) + item["reserved_bytes"] + delta - item["limit_bytes"]
        return shared, max(local, 0)

    def _admit(self, owner, delta, reclaim, *, reclaim_shared=True, operation="memory"):
        shared, local = self._shortfall(owner, delta)
        shortfall = max(shared, local)
        if reclaim is None:
            if not shortfall:
                return
        elif (reclaim_shared or shared <= local) and reclaim(shortfall):
            if not shortfall or max(self._shortfall(owner, delta)) == 0:
                return
        self.rejections += 1
        raise MemoryBudgetExceeded(f"{operation} admission deferred for {owner}",
            budget=self, owner=owner, bytes_needed=delta)

    def _notify_capacity(self):
        self._grant_pools()
        for loop, event in tuple(self._capacity_waiters):
            if not loop.is_closed():
                loop.call_soon_threadsafe(event.set)

    def _safe_pool_grant(self, waiter):
        snapshot = self.snapshot()
        delta = waiter.size-(waiter.pool.allocated if waiter.pool else 0)
        free = self.total_bytes-snapshot['estimated_bytes']-snapshot['reserved_bytes']-delta
        local = {name:item['limit_bytes']-item.get('estimated_bytes',0)-item['reserved_bytes']
                 for name,item in snapshot['owners'].items()}
        local[waiter.owner] -= delta
        if free < 0 or local[waiter.owner] < 0:
            return False
        # Safe staged admission: every granted planner may still grow up to
        # its declared owner limit. Do not grant a combination in which all
        # planners hold metadata while none can finish its working set.
        remaining = [(p.owner, waiter.size if p is waiter.pool else p.allocated,
                      waiter.maximum if p is waiter.pool else p.maximum)
                     for p in self._work_pools if p.allocated]
        if waiter.pool is None or waiter.pool not in self._work_pools or not waiter.pool.allocated:
            remaining.append((waiter.owner,waiter.size,waiter.maximum))
        while remaining:
            for i,(owner,allocated,maximum) in enumerate(remaining):
                need = maximum-allocated
                if need <= free and need <= local[owner]:
                    free += allocated
                    local[owner] += allocated
                    remaining.pop(i)
                    break
            else:
                return False
        return True

    def _grant_pools(self):
        blocked = set()
        pending=list(self._pool_waiters)
        while pending:
            now=time.monotonic()
            waiter=min(pending,key=lambda w:(
                not (w.pool is not None and w.pool.active),
                0 if now-w.queued_at>=2 else w.fairness[0],
                self._work_turns.get((w.owner,w.fairness),0),w.queued_at))
            pending.remove(waiter)
            if waiter.future.cancelled() or waiter.loop.is_closed():
                self._pool_waiters.pop(waiter,None)
                continue
            if waiter.owner in blocked or not self._safe_pool_grant(waiter):
                blocked.add(waiter.owner)
                continue
            pool = waiter.pool
            previous = pool.allocated if pool else 0
            if pool is None:
                pool = MemoryWorkPool(self,waiter.owner,waiter.size,waiter.maximum)
                self._work_pools.add(pool)
                self.work_grants += 1
            else:
                pool.allocated, pool.maximum = waiter.size,waiter.maximum
                pool.active = True
                self._work_pools.add(pool)
                self.work_resizes += 1
            self._reserved[waiter.owner] += waiter.size-previous
            waiter.granted = pool
            self._work_turn+=1
            key=(waiter.owner,waiter.fairness)
            self._work_turns[key]=self._work_turn
            self._work_turns.move_to_end(key)
            while len(self._work_turns)>8192:
                self._work_turns.popitem(last=False)
            self._pool_waiters.pop(waiter,None)
            def deliver(waiter=waiter,pool=pool):
                if not waiter.future.done():
                    waiter.future.set_result(pool)
            waiter.loop.call_soon_threadsafe(deliver)
        self._stop_work_pollers()

    def _poll_work(self, loop):
        with self._lock:
            self._work_pollers.pop(loop,None)
            self._grant_pools()
            if any(w.loop is loop for w in self._pool_waiters):
                self._work_pollers[loop] = loop.call_later(0.5,self._poll_work,loop)

    def _stop_work_pollers(self):
        if self._pool_waiters:
            return
        for loop,handle in self._work_pollers.items():
            if not loop.is_closed():
                loop.call_soon_threadsafe(handle.cancel)
        self._work_pollers.clear()

    async def _acquire_pool(self, owner, size, maximum, pool=None):
        from app.core.resource_wait import resource_wait,claim_owner
        loop = asyncio.get_running_loop()
        waiter = _PoolWaiter(owner,size,maximum,loop.create_future(),loop,pool)
        waiter.fairness=claim_owner.get()
        waiter.queued_at=time.monotonic()
        with self._lock:
            if len(self._pool_waiters) >= 4096:
                raise MemoryBudgetExceeded('work admission metadata budget exhausted')
            self._pool_waiters[waiter] = None
            self._grant_pools()
            waiting = waiter.granted is None
            self.work_waits += int(waiting)
            if waiting and loop not in self._work_pollers:
                self._work_pollers[loop] = loop.call_later(0.5,self._poll_work,loop)
        try:
            if waiting:
                async with resource_wait('memory_working_set'):
                    result = await waiter.future
                return result
            return await waiter.future
        except BaseException:
            with self._lock:
                self._pool_waiters.pop(waiter,None)
                if waiter.granted is not None:
                    waiter.granted.close()
                self._notify_capacity()
            raise

    async def wait_for_capacity(self, owner, bytes_needed):
        """Wait outside execution slots; admission is checked again on use.

        Reservation releases wake waiters across storage threads. The bounded
        timeout also observes owner cache eviction without traversing its heap.
        """
        loop, event = asyncio.get_running_loop(), asyncio.Event()
        waiter = (loop, event)
        with self._lock:
            self._capacity_waiters.add(waiter)
        try:
            while True:
                with self._lock:
                    event.clear()
                    if max(self._shortfall(owner, bytes_needed)) <= 0:
                        return
                try:
                    await asyncio.wait_for(event.wait(), 1.0)
                except TimeoutError:
                    pass
        finally:
            with self._lock:
                self._capacity_waiters.discard(waiter)

    @contextmanager
    def reserve(self, owner, bytes_needed, *, reclaim=None, reclaim_shared=True):
        """Admit work, optionally reclaiming only this owner's reusable values.

        The synchronous reclaim callback runs under the budget lock and receives
        the byte shortfall, including zero. It may enforce local capacity as
        well. The caller must already hold its owner lock; the callback must
        update the usage counter, avoid I/O and other locks, and return False
        without evicting if it cannot meet the request. The same rules apply
        when transferring a reservation with retain(). Opportunistic work
        can decline reclamation beyond the owner's own limit.
        """
        if bytes_needed < 0:
            raise ValueError("reservation must be non-negative")
        pool = current_work_pool(self,owner)
        if pool is not None:
            lease = pool.reserve(bytes_needed)
        else:
            with self._lock:
                self._admit(owner, bytes_needed, reclaim, reclaim_shared=reclaim_shared)
                self._reserved[owner] += bytes_needed
            lease = MemoryReservation(self, owner, bytes_needed)
        try:
            yield lease
        finally:
            lease.close()
