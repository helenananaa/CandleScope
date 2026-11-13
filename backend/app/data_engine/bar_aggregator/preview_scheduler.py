"""Loop-owned, bounded deadlines for already accepted component previews.

No source queue, parallel accumulator, writer or recovery owner. A pending
entry references the existing builder and reserves its extra old-tail/work
allowance until calculation/publication, detach, failure or shutdown finishes.
"""
import asyncio
from contextlib import nullcontext
from dataclasses import dataclass
import logging
import time

from app.data_engine.memory_budget import MemoryBudgetExceeded
from .bar_state import ComponentSnapshotOHLCVMerge
from .finalizer import (BatchFinalizer, CompositeCloseFinalizer, EventDrivenFinalizer,
                        SourceCloseFinalizer, TimeBasedFinalizer)
from .models import BarInputSource, BarStatus, MergeMode

logger = logging.getLogger('bar_aggregator.preview')
ENTRY_BYTES = 16 * 1024
MAX_PENDING = 128
MAX_DRAIN = 16
_FINALIZERS = {BatchFinalizer, CompositeCloseFinalizer, EventDrivenFinalizer,
               SourceCloseFinalizer, TimeBasedFinalizer}


@dataclass(eq=False, slots=True)
class _Pending:
    state: object
    pipeline: object
    token: tuple
    due: float
    scope: object
    binding: tuple
    revision_floor: int | None


class ComponentPreviewScheduler:
    def __init__(self, aggregator):
        self.aggregator = aggregator
        self.pending = {}
        self.inflight = []
        self.timer = self.task = None
        self.running = False
        self.metrics = dict(admitted=0, budget_fallbacks=0, capacity_fallbacks=0,
                            published=0, failures=0, detached=0, peak_pending=0,
                            source_checks=0,source_superseded=0,source_fallbacks=0)

    def start(self):
        self.running = True

    def _binding(self, pipeline):
        agg = self.aggregator
        runtime = agg.history_prefix_runtime
        source = getattr(getattr(getattr(runtime,'reader',None),'engine',None),'storage',None)
        strategies = tuple((name,type(strategy),getattr(strategy.should_close,'__func__',strategy.should_close))
                           for name,strategy in pipeline.finalizer._strategies)
        source_owner = agg._preview_source_binding() if agg._preview_source_binding is not None else None
        return (agg._cfg,agg.memory_budget,runtime,source,
                pipeline.bar_state._component_merge_strategy,pipeline.finalizer,
                source_owner,agg._preview_source_validator,
                pipeline.bar_state._merge_strategy_overridden,
                pipeline.bar_state._component_merge_strategy.incremental,
                agg._cfg.deferred_component_previews,agg._cfg.incremental_components,strategies)

    def _delay(self, state):
        publisher = self.aggregator.publisher
        if publisher._requires_every_update(state):
            return 0
        if state._preview_publications:
            return None  # Existing publication's finally wakes this deadline.
        if not publisher._cfg.emit_updated_events:
            return None
        interval = publisher._cfg.update_throttle_ms
        if type(interval) is not int or interval <= 0:
            return 0
        key = state.bar_key
        last = publisher._update_throttle.get(key)
        if last is None:
            return 0
        return max(0, last + interval - int(time.time() * 1000))

    def qualifies(self, pipeline, state, incoming, token, emit_events):
        agg = self.aggregator
        if (not self.running or not emit_events or token is None
                or not agg._cfg.deferred_component_previews or not agg._cfg.incremental_components
                or state is None or state.status != BarStatus.FORMING
                or incoming.merge_mode != MergeMode.COMPONENT or incoming.is_closed
                or incoming.source != BarInputSource.REALTIME
                or not agg.has_series_target(state.symbol,state.interval,state.exchange,state.market_type,state.identity)
                or pipeline.bar_state._merge_strategy_overridden
                or not pipeline.bar_state._component_merge_strategy.incremental
                or getattr(pipeline.bar_state._component_merge_strategy.apply,'__func__',None)
                    is not ComponentSnapshotOHLCVMerge.apply):
            return False
        if state.source_refs or incoming.extra.get('source_ref'):
            ref = incoming.extra.get('source_ref')
            provider = getattr(agg,'acquisition_revision_provider',None)
            if (agg._preview_source_validator is None or agg._preview_source_binding is None
                    or agg._preview_source_binding() is None or provider is None
                    or type(provider()) is not int or len(state.source_snapshots)>256
                    or not state.identity.is_legacy_default_for(state.exchange)
                    or ref is None or set(ref) != {'series','open_time','revision'}):
                state.preview_fallback_reason = 'source_reference_window'
                self.metrics['source_fallbacks'] += 1
                return False
        # Custom strategies may close on forming input or inspect projected
        # fields. Preserve their eager contract, including instance overrides.
        for _, strategy in pipeline.finalizer._strategies:
            if (type(strategy) not in _FINALIZERS
                    or getattr(strategy.should_close,'__func__',None) is not type(strategy).should_close):
                return False
            if isinstance(strategy,TimeBasedFinalizer) and (
                    int(time.time()*1000) >= state.bucket_end_ms + strategy._timeout_ms):
                return False
        merge = pipeline.bar_state._component_merge_strategy
        accumulator = state._component_accumulator
        return (accumulator is not None and accumulator.tail_unique
                and accumulator.tail_snapshot is not None
                and getattr(accumulator.tail_snapshot,'estimated_bytes',ENTRY_BYTES) <= 8192
                and merge._can_accumulate(state,incoming))

    def admit(self, pipeline, state, token):
        if id(state) in self.pending:
            return self._delay(state) != 0
        delay = self._delay(state)
        if delay == 0:
            return False
        if len(self.pending) + len(self.inflight) >= MAX_PENDING:
            self.metrics['capacity_fallbacks'] += 1
            state.preview_fallback_reason = 'pending_capacity'
            return False
        budget = self.aggregator.memory_budget
        scope = budget.reserve('realtime-state',ENTRY_BYTES) if budget is not None else nullcontext()
        try:
            scope.__enter__()
        except MemoryBudgetExceeded:
            self.metrics['budget_fallbacks'] += 1
            state.preview_fallback_reason = 'memory_admission'
            return False
        due = float('inf') if delay is None else asyncio.get_running_loop().time() + delay/1000
        provider = getattr(self.aggregator,'acquisition_revision_provider',None)
        floor = provider() if provider is not None else None
        self.pending[id(state)] = _Pending(state,pipeline,token,due,scope,self._binding(pipeline),floor)
        state.preview_fallback_reason = ''
        self.metrics['admitted'] += 1
        self.metrics['peak_pending'] = max(self.metrics['peak_pending'],len(self.pending))
        self._arm()
        return True

    def _arm(self):
        if not self.running or self.task is not None:
            return
        due = min((entry.due for entry in self.pending.values()),default=float('inf'))
        if due == float('inf'):
            return
        if self.timer is not None:
            if self.timer.when() <= due:
                return
            self.timer.cancel()
        self.timer = asyncio.get_running_loop().call_at(due,self._wake)

    def _wake(self):
        self.timer = None
        if self.running and self.task is None:
            self.task = asyncio.create_task(self._drain(),name='bar_agg_preview')

    def _current(self, entry):
        agg = self.aggregator
        state = entry.state
        current = self._binding(entry.pipeline)
        binding_matches = (all(a is b for a,b in zip(current[:8],entry.binding[:8]))
                           and current[8:] == entry.binding[8:])
        return (agg._target_epochs.get(entry.token[0]) is entry.token[1]
                and agg._pipelines.get(agg._pipeline_key(state.interval,state.exchange,state.identity)) is entry.pipeline
                and entry.pipeline.bar_state.get_active(state.exchange,state.market_type,state.symbol,
                                                       state.bucket_start_ms) is state
                and binding_matches)

    def _finish(self, entry):
        try:
            # Even a failed validation/detach must not leave an uncharged old
            # tail alive. This is calculation only; it grants no publication.
            try:
                entry.state.materialize_preview()
            except BaseException:
                # Accepted inputs remain authoritative; discard only the old
                # optional execution index, whose tail allowance is ending.
                entry.state._component_accumulator = None
                raise
        finally:
            entry.scope.__exit__(None,None,None)

    def publication_finished(self, state):
        if state.preview_published_version >= state.preview_input_version:
            state.preview_fallback_reason = ''
        entry = self.pending.get(id(state))
        if entry is None:
            return
        if state.preview_published_version >= state.preview_input_version:
            self.discard(state)
        elif self.running:
            delay = self._delay(state)
            entry.due = float('inf') if delay is None else asyncio.get_running_loop().time()+delay/1000
            self._arm()

    def discard(self, state):
        entry = self.pending.pop(id(state),None)
        if entry is not None:
            self._finish(entry)

    def detach(self, token):
        for entry in list(self.pending.values()):
            if entry.token[0] == token:
                self.pending.pop(id(entry.state),None)
                self._finish(entry)
                self.metrics['detached'] += 1

    async def _drain(self):
        owner = asyncio.current_task()
        if self.task is None:
            self.task = owner
        elif self.task is not owner:
            return
        try:
            now = asyncio.get_running_loop().time()
            keys = sorted((key for key,e in self.pending.items() if e.due <= now),
                          key=lambda key:self.pending[key].due)[:MAX_DRAIN]
            for key in keys:
                entry = self.pending.get(key)
                if entry is None:
                    continue
                if not self._current(entry):
                    self.discard(entry.state)
                    continue
                delay = self._delay(entry.state)
                if delay is None or delay > 0:
                    entry.due = float('inf') if delay is None else asyncio.get_running_loop().time()+delay/1000
                    continue
                self.pending.pop(id(entry.state),None)
                self.inflight.append(entry)
                try:
                    async with self.aggregator._validated_active_state(entry.pipeline,entry.state) as current:
                        if current is not entry.state or not self._current(entry):
                            continue
                        if current.source_refs:
                            version = current.preview_input_version
                            self.metrics['source_checks'] += 1
                            status = await self.aggregator._preview_source_validator(current,entry.revision_floor,
                                is_current=lambda: self._current(entry))
                            if (status != 'current' or not self._current(entry)
                                    or current.preview_input_version != version):
                                current.preview_fallback_reason = ('source_superseded'
                                    if status=='superseded' else 'source_view_unavailable')
                                self.metrics['source_superseded'] += 1
                                continue
                        current.materialize_preview()
                        if current.preview_published_version < current.preview_computed_version:
                            await self.aggregator.publisher.emit_updated(current)
                            self.metrics['published'] += 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.metrics['failures'] += 1
                    logger.exception('Component preview failed; accepted state remains with its owner')
                finally:
                    self.inflight.remove(entry)
                    self._finish(entry)
                    current = None
                    del entry
                await asyncio.sleep(0)
        finally:
            self.task = None
            self._arm()

    async def stop(self):
        self.running = False
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        for state in [e.state for e in self.pending.values()]:
            self.discard(state)

    def snapshot(self):
        return dict(self.metrics,running=self.running,pending=len(self.pending),inflight=len(self.inflight),
                    reserved_bytes=(len(self.pending)+len(self.inflight))*ENTRY_BYTES,
                    max_pending=MAX_PENDING,drain_batch=MAX_DRAIN)

    def roots(self):
        return [self.pending,self.inflight]
