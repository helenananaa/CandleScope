"""In-flight native input subscriptions owned by HistoricalFetcher.

Identical physical requests share their original response contract. Qualified
closed native forward pages additionally share overlapping ranges. There is
no durable cache, writer, quota ledger or target-result permission here. Each
subscriber keeps normalization, selected windows, fences and reconciliation.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from functools import wraps
from itertools import count, islice

from app.data_engine.memory_budget import MemoryBudgetExceeded
from app.core.bounded_executor import ExecutorBusyError
from app.exchanges.public_admission import PublicDemand, TrafficClass, current_demand, public_demand

_adoption = ContextVar('historical_input_adoption',default=None)


class InputAdoption:
    def __init__(self,request=None):
        self._release = []
        self.managed = request is not None or bool(getattr(_adoption.get(), 'managed', False))
        self._request_metadata = request.metadata if request is not None else None
        self.permission_floor = (self._request_metadata or {}).get('acquisition_revision')
        self._tokens = []

    def remember_permission(self,floor):
        # Sibling chunks may have captured their read heads concurrently. The
        # first physical acquisition fixes the original parent's permission.
        if self._request_metadata is not None:
            floor = self._request_metadata.get('acquisition_revision',floor)
        if floor is not None and self.permission_floor is None:
            self.permission_floor = floor
        if self._request_metadata is not None and self.permission_floor is not None:
            self._request_metadata.setdefault('acquisition_revision',self.permission_floor)

    def __enter__(self):
        self._tokens.append(_adoption.set(self))
        return self

    def __exit__(self,*args):
        _adoption.reset(self._tokens.pop())

    def retain(self, release):
        self._release.append(release)

    def acknowledge(self):
        callbacks,self._release = self._release,[]
        for release in callbacks:
            release()

    close = acknowledge


@contextmanager
def input_adoption(*, inherit=False):
    """Keep shared bytes until their existing writer adopts or rejects them.

    Streaming callers acknowledge each page after its canonical commit.
    Ordinary bounded plans acknowledge when their engine run exits. Neither
    path leaves a completed-page cache after the last consumer releases it.
    """
    current = _adoption.get()
    if inherit and current is not None:
        yield current
        return
    scope = InputAdoption()
    token = _adoption.set(scope)
    try:
        yield scope
    finally:
        scope.acknowledge()
        _adoption.reset(token)


def adopts_inputs(function):
    @wraps(function)
    async def run(*args,**kwargs):
        with input_adoption(inherit=True) as scope:
            from app.data_engine.storage.revisions import acquisition_permission_floor
            if scope.permission_floor is None:
                scope.remember_permission(acquisition_permission_floor())
            return await function(*args,**kwargs)
    return run


def retain_input_payload(payload):
    scope = _adoption.get()
    if scope is not None:
        scope.retain(payload.pop_all().close)


def current_input_adoption():
    return _adoption.get()


def propagate_capacity_wait(error):
    scope = current_input_adoption()
    if (scope is not None and scope.managed and (isinstance(error, ExecutorBusyError)
            or isinstance(error, MemoryBudgetExceeded) and error.waitable)):
        raise error


@dataclass(eq=False)
class _Input:
    key: tuple
    first: int
    last: int
    demand: PublicDemand
    task: asyncio.Task | None = None
    consumers: dict[object, PublicDemand] = field(default_factory=dict)
    payload_lease: object | None = None
    request: object | None = None
    observed_revision: int | None = None


def _opened(message):
    raw = message.payload
    if isinstance(raw,dict):
        from app.exchanges.ccxt_ext.unified import CCXT_UNIFIED_MARKER
        from app.exchanges.ccxt_ext.fork_kline import SCHEMAS
        if raw.get('schema') in SCHEMAS:
            opened = raw.get('timestamp')
            if type(opened) is not int:
                raise ValueError('shared receipted candle has an invalid timestamp')
            return opened
        if raw.get('schema') != CCXT_UNIFIED_MARKER or raw.get('kind') != 'kline':
            raise ValueError('shared native page has an unknown envelope')
        raw = raw.get('value')
    if not isinstance(raw,(list,tuple)) or not raw or type(raw[0]) is not int:
        raise ValueError('shared native page has an invalid open-time payload')
    return raw[0]


class InputSubscriptions:
    """Partition a page against active coverage before taking any fetch slot."""

    MAX_INPUTS = 4096
    MAX_SUBSCRIPTIONS = 8192

    def __init__(self, *, receipts_current=None):
        self._receipts_current = receipts_current
        self.stale_inputs_retired = 0
        self._inputs: dict[tuple, list[_Input]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._ids = count()
        self._subscriptions = 0
        self.created = self.joined = self.residuals = self.cancelled = 0
        self.metadata_budget_rejections = 0
        self._closed = False

    def snapshot(self):
        registered=sum(len(items) for items in self._inputs.values())
        completed=sum(item.task.done() for group in self._inputs.values() for item in group)
        samples=[]
        for item in islice((item for group in self._inputs.values() for item in group),32):
            request=item.request
            descriptor=request.descriptor
            samples.append(dict(input_owner=item.demand.owner,exchange=descriptor.exchange,
                market_type=descriptor.market_type,symbol=descriptor.symbol,interval=descriptor.interval,
                start_ms=request.start_ms,end_ms=request.end_ms,limit=request.limit,
                subscribers=len(item.consumers),completed=item.task.done(),
                demand_owners=sorted({str(d.owner)[:160] for d in item.consumers.values()})[:32]))
        return dict(in_flight=registered-completed,registered_inputs=registered,
            subscriptions=self._subscriptions, physical_pages_created=self.created,
            shared_page_subscriptions=self.joined, residual_pages_created=self.residuals,
            abandoned_pages_cancelled=self.cancelled,
            completed_pages_awaiting_adoption=completed,active_input_sample=samples,
            metadata_budget_rejections=self.metadata_budget_rejections,
            stale_inputs_retired=self.stale_inputs_retired,
            scope='historical input requests and pending adoption; range slicing only for qualified closed native pages; no canonical coverage or write permission')

    def _retire(self, item):
        group = self._inputs.get(item.key, [])
        if item in group:
            group.remove(item)
        if not group:
            self._inputs.pop(item.key, None)

    def _finished(self, item, task):
        self._tasks.discard(task)
        if task.cancelled() or task.exception() is not None or not item.consumers:
            self._retire(item)

    def _update_demand(self, item):
        item.demand.dependencies[:] = list(dict.fromkeys(item.consumers.values()))

    async def _run(self, item, request, fetch):
        with public_demand(item.demand):
            return await fetch(request,item)

    async def acquire_exact(self,request,*,key,fetch):
        return await self.acquire(request,key=('exact',*key,request.start_ms,request.end_ms,
            request.limit,request.from_id),width=1,fetch=fetch,partition=False)

    async def acquire(self, request, *, key, width, fetch, exclude=frozenset(), partition=True):
        if self._closed:
            raise RuntimeError('historical input owner is closed')
        first, last = (request.start_ms, request.end_ms) if partition else (0,0)
        pending = [(first, last)]
        selected = []
        from app.data_engine.storage.revisions import acquisition_revision
        revision = acquisition_revision()
        # Validate retained raw frames before retry adoption. A newer source
        # selection can supersede a receipt even without a canonical write.
        # The transactional projection guard remains the final authority.
        from app.exchanges.ccxt_ext.fork_kline import SCHEMAS
        validated = set()
        def receipted(messages):
            return bool(messages) and all(isinstance(message.payload,dict)
                and message.payload.get('schema') in SCHEMAS
                and isinstance(message.payload.get('_source_receipt',{}).get('ref'),dict)
                for message in messages)
        if self._receipts_current is not None:
            for item in tuple(self._inputs.get(key, ())):
                if item.task.done() and not item.task.cancelled() and item.task.exception() is None:
                    messages = item.task.result()
                    if receipted(messages):
                        if await self._receipts_current(messages):
                            validated.add(item)
                        else:
                            self._retire(item)
                            self.stale_inputs_retired += 1
        # No await between coverage analysis and reservation: two logical
        # consumers on this event loop cannot both claim the same residual.
        for item in tuple(self._inputs.get(key, ())):
            if item in exclude:
                continue
            if item.task.done() and (item.task.cancelled() or item.task.exception() is not None):
                self._retire(item)
                continue
            if (self._receipts_current is not None and item.task.done()
                    and receipted(item.task.result()) and item not in validated):
                continue
            if item.observed_revision != revision:
                # Across refreshed read heads, only journal-receipted native
                # responses may be re-adopted. Existing projection validation
                # checks that each receipt remains current. Legacy bytes must
                # be fetched again; deletion permission is part of the key.
                from app.exchanges.ccxt_ext.fork_kline import SCHEMAS
                if not item.task.done():
                    continue
                messages = item.task.result()
                if not messages or not all(isinstance(message.payload,dict)
                        and message.payload.get('schema') in SCHEMAS
                        and isinstance(message.payload.get('_source_receipt'),dict)
                        for message in messages):
                    continue
            remaining = []
            for start, end in pending:
                lo, hi = max(start,item.first), min(end,item.last)
                if lo > hi:
                    remaining.append((start,end))
                    continue
                selected.append((item,lo,hi,False))
                if start < lo:
                    remaining.append((start,lo-width))
                if hi < end:
                    remaining.append((hi+width,end))
            pending = remaining
        if (sum(len(group) for group in self._inputs.values())+len(pending) > self.MAX_INPUTS
                or self._subscriptions+len(selected)+len(pending) > self.MAX_SUBSCRIPTIONS):
            self.metadata_budget_rejections += 1
            raise MemoryBudgetExceeded('historical input subscription metadata budget exhausted')
        overlap = bool(selected)
        for start,end in pending:
            demand = PublicDemand(TrafficClass.BACKGROUND, owner=f'history-input:{next(self._ids)}',
                purpose='shared_native_history', defer=True)
            item = _Input(key,start,end,demand)
            item.observed_revision = revision
            demand.alive = lambda item=item: bool(item.consumers)
            part = replace(request,quota_acquired=False,quota_semaphore_held=False,quota_reservation=None)
            if partition:
                part = replace(part,start_ms=start,end_ms=end,limit=(end-start)//width+1)
            item.request = part
            item.task = asyncio.create_task(self._run(item,part,fetch),name=demand.owner)
            self._tasks.add(item.task)
            self._inputs.setdefault(key,[]).append(item)
            item.task.add_done_callback(lambda task,item=item:self._finished(item,task))
            selected.append((item,start,end,True))
            self.created += 1
            self.residuals += int(overlap)
        token = object()
        for item,_,_,owned in selected:
            item.consumers[token] = current_demand()
            self._update_demand(item)
            self._subscriptions += 1
            self.joined += int(not owned)
        try:
            values = await asyncio.gather(*(asyncio.shield(item.task) for item,_,_,_ in selected))
            output = []
            missing = []
            for (item,start,end,owned),messages in zip(selected,values):
                # The physical owner's ordinary pagination retains its empty/
                # short-page evidence. Followers never infer that an unfetched
                # suffix of a short page is empty or complete history.
                if owned or not partition:
                    output.extend(deepcopy(messages))
                    continue
                present = set()
                for message in messages:
                    opened = _opened(message)
                    if start <= opened <= end:
                        present.add(opened)
                        output.append(deepcopy(message))
                begin = None
                for opened in range(start,end+width,width):
                    if opened not in present and begin is None:
                        begin = opened
                    if opened in present and begin is not None:
                        missing.append((begin,opened-width,item))
                        begin = None
                if begin is not None:
                    missing.append((begin,end,item))
            if missing:
                recovered = await asyncio.gather(*(self.acquire(
                    replace(request,start_ms=start,end_ms=end,limit=(end-start)//width+1),
                    key=key,width=width,fetch=fetch,exclude=exclude|{item}) for start,end,item in missing))
                for messages in recovered:
                    output.extend(messages)
            # Request ranges are disjoint. Sort shared and residual results as
            # one native page for the existing forward pagination policy.
            if partition:
                output.sort(key=_opened)
            scope = _adoption.get()
            if scope is not None:
                # Transfer only successful acquisition. Cancellation/failure
                # releases immediately; a last release retires all shared bytes.
                scope.retain(lambda selected=selected,token=token:self._release(selected,token))
                token = None
            return output
        except Exception:
            # A failed sibling does not discard a page already received by
            # this live consumer. Its retry reuses only the successful part;
            # the original permission and journal checks still apply.
            scope = _adoption.get()
            completed = [part for part in selected if part[0].task.done()
                and not part[0].task.cancelled() and part[0].task.exception() is None]
            if scope is not None and completed:
                scope.retain(lambda completed=completed,token=token:self._release(completed,token))
                selected = [part for part in selected if part not in completed]
            raise
        finally:
            if token is not None:
                self._release(selected,token)

    def _release(self,selected,token):
        for item,_,_,_ in selected:
            item.consumers.pop(token,None)
            self._update_demand(item)
            self._subscriptions -= 1
            if not item.consumers:
                self._retire(item)
                if not item.task.done():
                    self.cancelled += 1
                    item.task.cancel()
                if item.payload_lease is not None:
                    item.payload_lease.close()
                    item.payload_lease = None

    async def close(self):
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self._inputs.clear()
