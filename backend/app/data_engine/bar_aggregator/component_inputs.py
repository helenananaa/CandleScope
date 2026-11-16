"""One bounded R129 component preparation per source dispatch.

This is a task-local work value, never a persistent/shared block cache. Target
replacement, coverage, finality and revision admission remain in BarStateEngine.
"""
from collections.abc import Mapping
import sys

from app.data_engine.memory_budget import MemoryBudgetExceeded
from .bar_state import ComponentSnapshotOHLCVMerge
from .models import BarInputSource

PREPARATION_BYTES = 16 * 1024
SCOPE_BYTES = 512
MAX_PREPARATION_TARGETS = 128


class SourcePreparationCapacity:
    """Bounded reusable work allowance, retaining no input between dispatches.

    Admission transfers its allowance to the existing realtime owner. Reusing
    an admitted slot avoids a whole-runtime budget traversal on every tick.
    Idle allowances disappear when targets detach, rollout stops or owner stops.
    """
    __slots__ = ("capacity", "in_use", "budget", "closing")
    MAX_SLOTS = 64

    def __init__(self):
        self.capacity = self.in_use = 0
        self.budget = None
        self.closing = False

    def acquire(self, budget):
        if self.closing or self.in_use >= self.MAX_SLOTS:
            raise MemoryBudgetExceeded('source preparation work slots unavailable')
        if self.budget is not budget:
            if self.in_use:
                raise MemoryBudgetExceeded('source preparation budget rebound while active')
            self.capacity = 0
            self.budget = budget
        if self.in_use < self.capacity:
            self.in_use += 1
            return
        def commit():
            self.capacity += 1
            self.in_use += 1
        if budget is None:
            commit()
        else:
            with budget.reserve('realtime-state',PREPARATION_BYTES) as lease:
                lease.retain(PREPARATION_BYTES,commit)

    def release(self, *, keep):
        self.in_use -= 1
        if self.closing or not keep:
            self.trim_idle()

    def trim_idle(self):
        self.capacity = self.in_use

    def close(self):
        self.closing = True
        self.trim_idle()


class SourceComponentPreparation:
    __slots__ = ("metrics","budget","fingerprint","snapshot","source_extra","pool","qualification","eligible","engines","_admitted","_deferred","_closed")

    def __init__(self, metrics, budget=None, pool=None):
        self.metrics, self.budget = metrics, budget
        self.fingerprint = self.snapshot = self.source_extra = None
        self.pool = pool or SourcePreparationCapacity()
        self.qualification = None
        self.eligible = False
        self.engines = ()
        self._closed = False
        self._admitted = False
        self._deferred = False

    def invalidate(self):
        self.fingerprint = self.snapshot = self.source_extra = None

    def close(self, *, keep_capacity=False):
        self.invalidate()
        self.qualification = None
        if self._admitted:
            self.pool.release(keep=keep_capacity)
            self._admitted = False
        self.engines = ()
        self.budget = self.pool = self.metrics = None
        self._closed = True

    def qualifies(self, key, decide):
        if self._closed:
            return False
        if key != self.qualification:
            self.qualification = key
            self.eligible, self.engines = decide()
        return self.eligible

    def memory_roots(self):
        return [self.snapshot,self.fingerprint,dict(self.source_extra) if self.source_extra is not None else None]

    def get(self, value):
        if self._closed:
            return None
        # Custom-adapter and nested/large provenance contracts keep their
        # existing independent preparation. No source values are dropped.
        ref = value.extra.get('source_ref')
        if (value.source not in {BarInputSource.REALTIME, BarInputSource.BACKFILL, BarInputSource.CORRECTION}
                or (ref is not None and (not isinstance(ref, Mapping) or len(ref) > 32
                    or any(not isinstance(k,str) or type(v) not in (str,int,float,bool,type(None))
                           for k,v in ref.items())
                    or sys.getsizeof(ref) + sum(sys.getsizeof(k)+sys.getsizeof(v) for k,v in ref.items()) > 2048))):
            self.invalidate()
            self.metrics['preparation_declines'] += 1
            return None
        signature = (value.exchange,value.market_type,value.symbol,value.source_interval,
            value.series_identity,
            ('revision',tuple(sorted(ref.items()))) if ref is not None else ('input',id(value.extra)),
            tuple(getattr(value,name) for name in ComponentSnapshotOHLCVMerge.INPUT_FIELDS),
            bool(value.extra.get('warm_start_seed')))
        if self.snapshot is not None and signature == self.fingerprint:
            self.metrics['preparation_hits'] += 1
            return self.snapshot
        if self._deferred:
            return None
        if not self._admitted:
            try:
                self.pool.acquire(self.budget)
                self._admitted = True
            except MemoryBudgetExceeded:
                # Preparation sharing is optional; mandatory source/close work
                # keeps its established route rather than dropping an input.
                self._deferred = True
                self.metrics['preparation_budget_deferred'] += 1
                return None
        snapshot = ComponentSnapshotOHLCVMerge._snapshot_from_input(value)
        self.fingerprint, self.snapshot = signature, snapshot
        # Retain only this input's small converter-owned extra mapping. Its
        # identity cannot be recycled into a different backfill input's key.
        self.source_extra = value.extra
        self.metrics['preparation_builds'] += 1
        return snapshot
