"""Loop-owned handoff from bounded H127 reads to R129 live state.

The target's existing lifetime owns one finite serialization slot. Initial
history prepares outside its lock so live overlay can continue. Subsequent
uses validate/refresh before mutation. SQLite rechecks prefix versions at the
durable commit boundary, including a write after the final read fence.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any
from copy import deepcopy
import time
import heapq
import sys
from collections import OrderedDict
from itertools import chain

from app.core.async_cleanup import finish_cleanup
from app.core.bounded_executor import ExecutorBusyError
from app.core.executors import run_storage
from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge, has_complete_closed_component_coverage
from app.data_engine.bar_aggregator.component_memory import ComponentSnapshots
from app.data_engine.bar_aggregator.models import BarFinality, BarStatus, MergeMode
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size
from app.data_engine.aggregation.history_prefix import EmptyHistoryPrefix, PREFIX_BYTES, MAX_PREFIX_ROWS


@dataclass
class _Target:
    source: Any
    token: tuple
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    recovering: bool = False


class HistoryPrefixRuntime:
    MAX_TARGETS = 128
    MAX_TASKS = 64
    MAX_SEEDS = 8
    # Measurements favor compact retention/loop responsiveness for large
    # prefixes. Small histories keep the lower-cost existing component path.
    MIN_ROWS = 2048
    COMPACT_ROWS = 128
    MAX_CLOSED_JOBS = 128

    def __init__(self, reader, aggregator, require_recovery, *, flush_delivery=None):
        self.aggregator = aggregator
        self.reader = reader
        self.require_recovery = require_recovery
        self.flush_delivery = flush_delivery
        self.targets = {}
        # IDs/epoch/source spelling only; the existing closed-state index owns
        # payloads. The existing timeout loop drains one job, without a new timer.
        self.closed_jobs = OrderedDict()
        self._closed_draining = False
        self.tasks = set()
        self.seeding = set()
        self.closing = False
        self.last_adoption = None
        self.last_closed_compaction = None
        self._input_read_scope = ContextVar("history_prefix_input_read_scope", default=None)
        self.metrics = dict(adoptions=0, validations=0, refreshes=0, empty=0, failures=0,
                            adopted_pages=0, adopted_storage_rows=0, adopted_cache_hits=0,
                            compactions=0, compacted_components=0, compaction_deferred=0,
                            closed_compactions=0, closed_compacted_components=0,
                            closed_compaction_deferred=0, closed_compaction_pages=0,
                            closed_jobs_scheduled=0, closed_jobs_refused=0, closed_jobs_peak=0)

    def snapshot(self):
        return {**self.metrics, 'targets': len(self.targets), 'tasks': len(self.tasks),
                'seeding': len(self.seeding), 'max_targets': self.MAX_TARGETS,
                'max_tasks': self.MAX_TASKS, 'minimum_prefix_rows': self.MIN_ROWS, 'closing': self.closing,
                'last_adoption': dict(self.last_adoption) if self.last_adoption else None,
                'closed_jobs': len(self.closed_jobs), 'max_closed_jobs': self.MAX_CLOSED_JOBS,
                'closed_job_inflight': self._closed_draining,
                'last_closed_compaction': dict(self.last_closed_compaction) if self.last_closed_compaction else None}

    def _current(self, slot):
        return (not self.closing and self.targets.get(slot.token[0]) is slot
                and self.aggregator.history_target_token(slot.source, slot.token[0][3]) == slot.token)

    def detach(self, key):
        self.targets.pop(key, None)
        for job in tuple(self.closed_jobs):
            if job[0] == key: self.closed_jobs.pop(job,None)
        if not self.closed_jobs: self.closed_jobs.clear()

    def owns_target(self, source, interval):
        token = self.aggregator.history_target_token(source, interval)
        slot = self.targets.get(token[0]) if token is not None else None
        return slot is not None and slot.token == token and self._current(slot)

    def failed(self, slot):
        if self._current(slot):
            self.metrics['failures'] += 1
            self.require_recovery(replace(slot.source, interval=slot.token[0][3]))

    @asynccontextmanager
    async def _task(self):
        task = asyncio.current_task()
        if self.closing or len(self.tasks) >= self.MAX_TASKS:
            raise BarDeliveryUnavailable('history/live handoff is closed or at capacity')
        if task in self.tasks:
            raise RuntimeError('history/live handoff cannot reenter its owner')
        with self.reader.memory_budget.reserve('realtime-state', 8192) as lease:
            lease.retain(8192, lambda: self.tasks.add(task))
        try:
            yield
        finally:
            self.tasks.discard(task)

    async def close(self):
        self.closing = True
        pending = [task for task in self.tasks if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        drained = asyncio.gather(*pending, return_exceptions=True)
        cancelled = False
        while not drained.done():
            try:
                await asyncio.shield(drained)
            except asyncio.CancelledError:
                cancelled = True
        self.targets.clear()
        self.closed_jobs.clear()
        if cancelled:
            raise asyncio.CancelledError

    def _adopt(self, slot, prefix, *, refresh=False, replace_provisional=False, compact_closed=False):
        if not self._current(slot):
            raise BlockRevisionChanged('history target detached before adoption')
        result = None
        allowance = 0 if refresh else PREFIX_BYTES
        with self.reader.memory_budget.reserve('realtime-state', allowance) as lease:
            def commit():
                nonlocal result
                result = self.aggregator.adopt_history_prefix(
                    prefix, slot.token, refresh=refresh, replace_provisional=replace_provisional,
                    compact_closed=compact_closed,
                )
            lease.retain(allowance, commit)
        self.metrics['adoptions'] += 1
        self.metrics['adopted_pages'] += prefix.pages
        self.metrics['adopted_storage_rows'] += prefix.storage_rows
        self.metrics['adopted_cache_hits'] += prefix.cache_hits
        self.last_adoption = dict(source=prefix.summary.target.topic, interval=slot.token[0][3],
            start_ms=prefix.start_ms, through_ms=prefix.through_ms, pages=prefix.pages,
            accepted_slots=prefix.summary.coverage.count, complete=prefix.complete,
            storage_rows=prefix.storage_rows, cache_hits=prefix.cache_hits)
        return result

    async def seed(self, source, interval, start_ms, through_ms):
        """Return False outside qualified scope; partial coverage stays explicit."""
        target = parse_interval_spec(interval)
        base = parse_interval_spec(source.interval)
        token = self.aggregator.history_target_token(source, interval)
        if (token is None or target is None or base is None
                or target.alignment is not IntervalAlignment.FIXED_EPOCH
                or target.phase_ms != 0 or target.nominal_ms % base.nominal_ms
                or target.nominal_ms // base.nominal_ms > MAX_PREFIX_ROWS
                or target.nominal_ms // base.nominal_ms < self.MIN_ROWS
                or (through_ms - start_ms) // base.nominal_ms < self.MIN_ROWS):
            return False
        key = token[0]
        slot = self.targets.get(key)
        if slot is not None and slot.token != token:
            self.detach(key)
            slot = None
        if key in self.seeding:
            return True
        if len(self.seeding) >= self.MAX_SEEDS or (slot is None and len(self.targets) >= self.MAX_TARGETS):
            return False
        if slot is None:
            slot = _Target(source, token)
            with self.reader.memory_budget.reserve('realtime-state', 1024) as lease:
                lease.retain(1024, lambda: self.targets.__setitem__(key, slot))
        self.seeding.add(key)
        qualified = False
        try:
            # Qualification runs on a storage worker even at an empty new
            # bucket. Never fall back to an unbounded previous-bucket read.
            async with self._task():
                await run_storage(self.reader.qualify, source)
                qualified = True
            if through_ms <= start_ms:
                return True
            async with self._task(), self.reader.stage(source, start_ms, through_ms, require_complete=False) as prefix:
                async with slot.lock:
                    if not self._current(slot):
                        return True  # Detached caller must not run a late legacy seed.
                    await run_storage(self.reader.validate_bound, prefix)
                    if not self._current(slot):
                        return True
                    pipeline = self.aggregator._pipelines[self.aggregator._pipeline_key(interval, source.exchange, source.identity)]
                    state = pipeline.bar_state.get_state(source.exchange, source.market_type, source.symbol, start_ms)
                    adopted = self._adopt(slot, prefix, refresh=bool(state and state._history_prefix))
                    slot.recovering = False
                    await self.aggregator.publisher.emit_updated(adopted)
                    return True
        except EmptyHistoryPrefix:
            if self._current(slot):
                slot.recovering = True
                pipeline = self.aggregator._pipelines[self.aggregator._pipeline_key(interval, source.exchange, source.identity)]
                current = pipeline.bar_state.get_state(source.exchange, source.market_type, source.symbol, start_ms)
                if current is not None and current._history_prefix is not None:
                    pipeline.bar_state.expire_bar(source.exchange, source.market_type, source.symbol, start_ms)
                    self.require_recovery(replace(source, interval=interval))
            return True
        except (ValueError, BlockUnavailable, BlockRevisionChanged, MemoryBudgetExceeded) as error:
            self.metrics['failures'] += 1
            if not self._current(slot):
                return True
            # Keep a slot if it already protects live compact state. Fallback
            # must not replace that state with an unfenced full-range replay.
            pipeline = self.aggregator._pipelines.get(self.aggregator._pipeline_key(interval, source.exchange, source.identity))
            state = pipeline.bar_state.get_state(source.exchange, source.market_type, source.symbol, start_ms) if pipeline else None
            if state is not None and state._history_prefix is not None:
                self.require_recovery(replace(source, interval=interval))
                return True
            if qualified and isinstance(error, BlockRevisionChanged):
                # A cold backfill can change the revision while the first
                # bounded page set is being staged. Keep this admitted owner;
                # the next confirmed source input retries canonical staging.
                # Detaching here permanently lost the compact path, because
                # ordinary live input does not call warm-start again.
                slot.recovering = True
                return True
            self.detach(key)
            return False
        finally:
            self.seeding.discard(key)

    async def complete_repaired_bucket(self, pipeline, state, incoming):
        """Replace a missed Bybit prefix only with the entire canonical close."""
        if (state.finality != BarFinality.PROVISIONAL or state._history_prefix is not None
                or type(state.acquisition_revision) is not int or incoming.source_interval != "5m"
                or incoming.close_time_ms + 1 != state.bucket_end_ms
                or (state.status == BarStatus.FORMING and has_complete_closed_component_coverage(state))):
            return state
        target = parse_interval_spec(state.interval)
        if (target is None or target.alignment is not IntervalAlignment.FIXED_EPOCH
                or target.phase_ms != 0 or not 300_000 < target.nominal_ms <= 64 * 300_000):
            return state

        from app.data_engine.data_manager.models import SeriesKey

        source = SeriesKey.create(state.symbol, incoming.source_interval, exchange=state.exchange,
                                  market_type=state.market_type, identity=state.identity)
        token = self.aggregator.history_target_token(source, state.interval)
        if (self.closing or token is None or token[0] in self.targets
                or len(self.targets) >= self.MAX_TARGETS):
            return state
        key = (state.exchange, state.market_type, state.symbol, state.bucket_start_ms)
        def still_current():
            return (not self.closing and self.aggregator.history_target_token(source, state.interval) == token
                    and pipeline.bar_state.get_state(*key) is state and state.finality == BarFinality.PROVISIONAL)

        try:
            async with self._task():
                if self.flush_delivery is not None:
                    # The native receipt is enqueued first but another flush
                    # can still own the dispatcher when the derived input arrives.
                    async with asyncio.timeout(1.5):
                        await self.flush_delivery()
                # An exchange confirmation can arrive slightly ahead of the
                # local clock. The canonical reader still requires elapsed slots.
                remaining = state.bucket_end_ms / 1000 - time.time()
                if remaining > 2:
                    return state if still_current() else None
                if remaining > 0:
                    await asyncio.sleep(remaining + .002)
                if not still_current():
                    return None
                async with self.reader.stage(source, state.bucket_start_ms, state.bucket_end_ms) as prefix:
                    if not still_current():
                        return None
                    if token[0] in self.targets or len(self.targets) >= self.MAX_TARGETS:
                        return state
                    slot = _Target(source, token)
                    floor = state.acquisition_revision
                    with self.reader.memory_budget.reserve("realtime-state", 1024) as lease:
                        lease.retain(1024, lambda: self.targets.__setitem__(token[0], slot))
                    try:
                        self._adopt(slot, prefix, replace_provisional=state.status == BarStatus.CLOSED)
                    except BaseException:
                        self.detach(token[0])
                        raise
                    adopted = pipeline.bar_state.get_state(*key)
                    adopted.canonical_recovery_delete_floor = floor
                    return adopted
        except (ValueError, BlockUnavailable, BlockRevisionChanged, MemoryBudgetExceeded,
                BarDeliveryUnavailable, ExecutorBusyError, TimeoutError):
            # Incomplete or stale storage cannot turn a preview into a close.
            return state if still_current() else None

    @asynccontextmanager
    async def forming_input_scope(self, event):
        kind = getattr(event, "event_type", None)
        data = getattr(event, "data", None) or {}
        matches = 0
        if (len(self.targets) > 1 and getattr(kind, "value", kind) == "kline"
                and data.get("is_closed") is False):
            source_key = (
                getattr(event, "symbol", "").upper(), getattr(event, "exchange", "").lower(),
                getattr(event, "market_type", "").lower(), data.get("interval"),
            )
            matches = sum(
                (slot.source.symbol, slot.source.exchange, slot.source.market_type, slot.source.interval)
                == source_key for slot in self.targets.values()
            )
        read_scope = self.reader.scoped_version_reader() if matches > 1 else None
        if read_scope is None:
            yield
            return
        token = self._input_read_scope.set((asyncio.current_task(), read_scope))
        try:
            yield
        finally:
            self._input_read_scope.reset(token)

            try:
                await finish_cleanup(run_storage(read_scope.close))
            except ExecutorBusyError:
                # The dispatch has finished and no worker owns the connection.
                read_scope.close()

    async def _refresh(self, slot, pipeline, state, *, emit_events):
        prefix = state._history_prefix
        if prefix is None:
            return state
        valid = False
        try:
            owned = self._input_read_scope.get()
            if owned is not None and owned[0] is asyncio.current_task():
                await run_storage(self.reader.validate_bound, prefix, read_scope=owned[1])
            else:
                await run_storage(self.reader.validate_bound, prefix)
            self.metrics['validations'] += 1
            if not self._current(slot):
                raise BlockRevisionChanged('history target detached during validation')
            valid = True
        except BlockRevisionChanged:
            if not self._current(slot):
                raise
        if pipeline.bar_state.get_state(state.exchange, state.market_type,
                                        state.symbol, state.bucket_start_ms) is not state:
            raise BlockRevisionChanged('history builder replaced during validation')
        if valid:
            return state
        previous = deepcopy(state)
        # A closed bucket may still have a retained seam. The original
        # dispatcher has been drained by before_input, so rebuild its entire
        # canonical window instead of combining a fresh prefix with an old
        # acquisition-floor tail. Keep the old explicit-delete permission floor.
        closed_rebuild = (self.flush_delivery is not None and state.status == BarStatus.CLOSED
                          and state.finality == BarFinality.AUTHORITATIVE)
        through = state.bucket_end_ms if closed_rebuild else prefix.through_ms
        delete_floor = (state.canonical_recovery_delete_floor if state.canonical_recovery_delete_floor is not None
                        else state.acquisition_revision)
        try:
            async with self.reader.stage(slot.source, prefix.start_ms, through,
                                         require_complete=False) as fresh:
                if pipeline.bar_state.get_state(state.exchange, state.market_type,
                                                state.symbol, state.bucket_start_ms) is not state:
                    raise BlockRevisionChanged('history builder replaced during refresh')
                adopted = self._adopt(slot, fresh, refresh=True)
                if closed_rebuild and fresh.complete:
                    current = pipeline.bar_state.get_state(state.exchange,state.market_type,state.symbol,state.bucket_start_ms)
                    current.canonical_recovery_delete_floor = delete_floor
                    adopted.canonical_recovery_delete_floor = delete_floor
        except EmptyHistoryPrefix:
            if not self._current(slot):
                raise BlockRevisionChanged('empty history target detached')
            expired = pipeline.bar_state.expire_bar(state.exchange, state.market_type,
                                                   state.symbol, state.bucket_start_ms)
            self.metrics['empty'] += 1
            slot.recovering = True
            self.require_recovery(replace(slot.source, interval=state.interval))
            if emit_events and expired is not None:
                await self.aggregator.publisher.emit_expired(expired)
            return None
        self.metrics['refreshes'] += 1
        if previous.status == BarStatus.CLOSED and adopted.status != BarStatus.CLOSED:
            self.require_recovery(replace(slot.source, interval=state.interval))
        if emit_events:
            if adopted.status == BarStatus.CLOSED:
                await self.aggregator.publisher.emit_amended(adopted, previous)
            else:
                await self.aggregator.publisher.emit_updated(adopted)
        return pipeline.bar_state.get_state(state.exchange, state.market_type, state.symbol, state.bucket_start_ms)

    async def _compact_tail(self, slot, pipeline, state, incoming):
        """Retire one confirmed seam, without publishing a synthetic update.

        This is optional retention work. Unavailable, different or stale
        canonical input leaves the accepted prefix and overlay untouched.
        """
        prefix = state._history_prefix
        count = self.COMPACT_ROWS
        if (prefix is None or not prefix.complete or state.status != BarStatus.FORMING
                or not incoming.is_closed or len(state.source_snapshots) < count
                or incoming.open_time_ms < state._history_compaction_retry_ms):
            return
        try:
            # Finite leaf references / selection metadata remain charged across
            # worker awaits. All larger read/projection work reserves separately.
            with self.reader.memory_budget.reserve('realtime-state', 16 * 1024):
                await self._compact_tail_reserved(slot, pipeline, state, incoming, prefix, count)
        except MemoryBudgetExceeded:
            state._history_compaction_retry_ms = incoming.open_time_ms + count * prefix.source_width_ms
            self.metrics['compaction_deferred'] += 1

    def schedule_closed(self, state, incoming):
        """Admit bounded metadata after publication; never retain raw payloads."""
        agg = self.aggregator
        if (self.closing or not agg._previews.running or not agg.config.compact_closed_components
                or agg.memory_budget is not self.reader.memory_budget
                or incoming.merge_mode != MergeMode.COMPONENT or not state.source_snapshots
                or state.status != BarStatus.CLOSED or state.finality != BarFinality.AUTHORITATIVE
                or state._closed_compaction_attempt_version == state.preview_input_version):
            return
        base,target = parse_interval_spec(incoming.source_interval),parse_interval_spec(state.interval)
        if (base is None or target is None or base.alignment is not IntervalAlignment.FIXED_EPOCH
                or target.alignment is not IntervalAlignment.FIXED_EPOCH or base.phase_ms or target.phase_ms
                or not 60000 <= base.nominal_ms <= 86400000 or target.nominal_ms % base.nominal_ms
                or not 2 <= target.nominal_ms//base.nominal_ms <= MAX_PREFIX_ROWS
                or not state.identity.is_legacy_default_for(state.exchange)):
            return
        from app.data_engine.data_manager.models import SeriesKey
        source = SeriesKey.create(state.symbol,base.canonical,exchange=state.exchange,
                                  market_type=state.market_type,identity=state.identity)
        token = agg.history_target_token(source,state.interval)
        if token is None:
            return
        key = (token[0],state.bucket_start_ms)
        try:
            if key not in self.closed_jobs:
                if len(self.closed_jobs) >= self.MAX_CLOSED_JOBS:
                    raise MemoryBudgetExceeded('closed maintenance capacity')
                with self.reader.memory_budget.reserve('realtime-state',1024) as lease:
                    lease.retain(1024,lambda:self.closed_jobs.__setitem__(key,(token[1],base.canonical)))
                self.metrics['closed_jobs_scheduled'] += 1
                self.metrics['closed_jobs_peak'] = max(self.metrics['closed_jobs_peak'],len(self.closed_jobs))
            else:
                self.closed_jobs[key] = (token[1],base.canonical)
        except MemoryBudgetExceeded:
            self.metrics['closed_jobs_refused'] += 1
            self.last_closed_compaction = dict(symbol=state.symbol,interval=state.interval,
                exchange=state.exchange,market_type=state.market_type,bucket_start_ms=state.bucket_start_ms,
                components=len(state.source_snapshots),reason='admission_refused')

    async def drain_closed(self):
        """One bounded maintenance job on the original timeout/owner lifecycle."""
        if (self.closing or self._closed_draining or not self.closed_jobs
                or asyncio.current_task() in self.tasks):
            return
        self._closed_draining = True
        try:
            (key,start),(epoch,source_interval) = self.closed_jobs.popitem(last=False)
            if not self.closed_jobs: self.closed_jobs.clear()
            agg = self.aggregator
            if agg._target_epochs.get(key) is not epoch:
                return
            exchange,market_type,symbol,interval,identity = key
            pipeline = agg._pipelines.get(agg._pipeline_key(interval,exchange,identity))
            state = pipeline.bar_state.get_closed(exchange,market_type,symbol,start) if pipeline else None
            if state is not None:
                await self.compact_closed(pipeline,state,source_interval)
        finally:
            self._closed_draining = False

    async def compact_closed(self, pipeline, state, source_interval):
        """Retire closed input indexes only after exact, fenced canonical readback.

        Runs after the existing lifecycle publication, under the existing target
        owner. No extra publication, writer, journal, task or queue is created.
        A closed bucket without an initial prefix may enter this same H127 path.
        """
        agg = self.aggregator
        cfg, budget = agg.config, self.reader.memory_budget
        snapshots, prefix = state.source_snapshots, state._history_prefix
        if (self.closing or not agg._previews.running or not cfg.compact_closed_components
                or budget is not agg.memory_budget
                or state.status != BarStatus.CLOSED or state.finality != BarFinality.AUTHORITATIVE
                or state._preview_dirty or state._preview_publications or not snapshots
                or state._closed_compaction_attempt_version == state.preview_input_version
                or type(snapshots) is not ComponentSnapshots or snapshots.foreign_entries
                or pipeline.bar_state._merge_strategy_overridden
                or getattr(pipeline.bar_state._component_merge_strategy.apply,'__func__',None)
                    is not ComponentSnapshotOHLCVMerge.apply):
            return
        from app.data_engine.data_manager.models import SeriesKey
        source = (prefix.summary.target if prefix is not None else
                  SeriesKey.create(state.symbol,source_interval,exchange=state.exchange,
                                   market_type=state.market_type,identity=state.identity))
        target, base = parse_interval_spec(state.interval), parse_interval_spec(source.interval)
        if (target is None or base is None or target.alignment is not IntervalAlignment.FIXED_EPOCH
                or target.phase_ms != 0 or target.nominal_ms % base.nominal_ms
                or not 2 <= target.nominal_ms // base.nominal_ms <= MAX_PREFIX_ROWS
                or (prefix is not None and (not prefix.complete or prefix.source_width_ms != base.nominal_ms))):
            return
        start = prefix.through_ms if prefix is not None else state.bucket_start_ms
        count = (state.bucket_end_ms-start)//base.nominal_ms
        if len(snapshots) != count or state.tick_count != target.nominal_ms//base.nominal_ms:
            return
        token = agg.history_target_token(source,state.interval)
        if token is None:
            return
        state._closed_compaction_attempt_version = state.preview_input_version
        slot = self.targets.get(token[0])
        created = False
        success = False
        retained = agg.publisher._hold_payload('input',(state,))
        try:
            if slot is None:
                if len(self.targets) >= self.MAX_TARGETS:
                    raise BlockUnavailable('history target capacity')
                slot = _Target(source,token)
                with budget.reserve('realtime-state',1024) as lease:
                    lease.retain(1024,lambda:self.targets.__setitem__(token[0],slot))
                created = True
            if slot.source != source or slot.token != token:
                raise BlockRevisionChanged('closed source owner changed')
            # Stage immutable pages outside the target lock. New forming
            # buckets keep their ordinary owner; versions reject a concurrent
            # amendment. Only final validation/adoption takes the existing lock.
            async with self._task():
                success = await self._compact_closed_owned(slot,pipeline,state,start,base.nominal_ms)
        except Exception as error:
            self.metrics['closed_compaction_deferred'] += 1
            self.last_closed_compaction = dict(symbol=state.symbol,interval=state.interval,
                exchange=state.exchange,market_type=state.market_type,bucket_start_ms=state.bucket_start_ms,
                components=len(snapshots),reason=type(error).__name__,detail=str(error)[:160])
        finally:
            if created and not success and self.targets.get(token[0]) is slot:
                # This was an optional slot allocation, not target detachment.
                # New buckets may have queued work or adopted a prefix while
                # staging ran outside the lock. Keep their dependencies/jobs.
                needed = slot.lock.locked() or any(
                    other._history_prefix is not None
                    and (other.exchange,other.market_type,other.symbol)==(state.exchange,state.market_type,state.symbol)
                    for other in chain(pipeline.bar_state._active.values(),pipeline.bar_state._closed.values()))
                if not needed: self.targets.pop(token[0],None)
            agg.publisher._release_payload(retained)

    async def _compact_closed_owned(self, slot, pipeline, state, start, width):
        agg, reader = self.aggregator, self.reader
        cfg, budget = agg.config, reader.memory_budget
        engine = reader.engine
        storage, manager, policy = engine.storage, engine.shared_blocks, engine.history_policy
        snapshots, refs, prefix = state.source_snapshots, state.source_refs, state._history_prefix
        strategy = pipeline.bar_state._component_merge_strategy
        version = state.preview_input_version
        def current():
            return (self._current(slot) and agg.history_prefix_runtime is self and agg.config is cfg
                and cfg.compact_closed_components and agg.memory_budget is budget and reader.memory_budget is budget
                and engine.storage is storage and engine.shared_blocks is manager and engine.history_policy is policy
                and agg._pipelines.get(agg._pipeline_key(state.interval,state.exchange,state.identity)) is pipeline
                and pipeline.bar_state.get_closed(state.exchange,state.market_type,state.symbol,state.bucket_start_ms) is state
                and state.status == BarStatus.CLOSED and state.finality == BarFinality.AUTHORITATIVE
                and state.source_snapshots is snapshots and state.source_refs is refs and state._history_prefix is prefix
                and state.preview_input_version == version and not pipeline.bar_state._merge_strategy_overridden
                and pipeline.bar_state._component_merge_strategy is strategy
                and getattr(strategy.apply,'__func__',None) is ComponentSnapshotOHLCVMerge.apply)
        if not current():
            raise BlockRevisionChanged('closed builder changed')
        # Old indexes may outlive detach or adoption while a physical read
        # drains. Reuse publisher's existing payload registration and account
        # their full frozen graph in the original work budget.
        work = snapshots.estimated_bytes + snapshots.source_proof_bytes + sys.getsizeof(refs) + 2*PREFIX_BYTES + 16384
        with budget.reserve('realtime-state',work):
            retained = agg.publisher._hold_payload('input',(state,))
            try:
                if self.flush_delivery is not None:
                    # Publisher completion may mean durable admission while
                    # the existing dispatcher still owns the native commit.
                    # Drain that owner before taking a canonical read view.
                    async with asyncio.timeout(1.5):
                        await self.flush_delivery()
                if not current():
                    raise BlockRevisionChanged('closed owner changed during delivery drain')
                await run_storage(reader.qualify,slot.source)
                async with reader.stage(slot.source,state.bucket_start_ms,state.bucket_end_ms) as fresh:
                    key_prefix = f'{state.exchange}:{state.market_type}:{state.symbol}@{slot.source.interval}:'
                    for lo in range(start,state.bucket_end_ms,128*width):
                        leaves = tuple(snapshots.get(key_prefix+str(opened)) for opened in
                            range(lo,min(lo+128*width,state.bucket_end_ms),width))
                        try:
                            if (not current() or any(row is None for row in leaves)
                                    or not await run_storage(reader.matches_closed_overlay,slot.source,fresh,leaves)):
                                raise BlockUnavailable('closed canonical components differ')
                        finally:
                            leaves = ()
                        self.metrics['closed_compaction_pages'] += 1
                    if not current():
                        raise BlockRevisionChanged('closed builder changed during readback')
                    # Use the existing K130 projection, including field masks,
                    # coverage/count/times. Aggregate equality alone was not
                    # used to authorize dropping individual input evidence.
                    probe = replace(state,_component_accumulator=None)
                    strategy.adopt_history_prefix(probe,fresh)
                    fields = ('open','high','low','close','volume','quote_volume','trades','taker_buy_base',
                        'taker_buy_quote','enhanced_fields','tick_count','first_input_at_ms','last_input_at_ms','last_close_received')
                    if any(getattr(probe,name) != getattr(state,name) for name in fields):
                        raise BlockUnavailable('closed projection differs')
                    preserve = ('status','finality','close_reason','quality_source','created_at_ms','updated_at_ms',
                        'acquisition_revision','canonical_recovery_delete_floor','preview_input_version',
                        'preview_computed_version','preview_published_version')
                    async with slot.lock:
                        await run_storage(reader.validate_bound,fresh)
                        if not current():
                            raise BlockRevisionChanged('closed builder changed before adoption')
                        values = tuple(getattr(state,name) for name in preserve)
                        self._adopt(slot,fresh,refresh=prefix is not None,compact_closed=True)
                        for name,value in zip(preserve,values): setattr(state,name,value)
                        self.metrics['closed_compactions'] += 1
                        self.metrics['closed_compacted_components'] += len(snapshots)
                        self.last_closed_compaction = dict(symbol=state.symbol,interval=state.interval,
                            exchange=state.exchange,market_type=state.market_type,bucket_start_ms=state.bucket_start_ms,
                            components=len(snapshots),reason='compacted')
                        return True
            finally:
                agg.publisher._release_payload(retained)

    async def _compact_tail_reserved(self, slot, pipeline, state, incoming, prefix, count):
        width = prefix.source_width_ms
        # At most 128 leaf references, even if a legacy overlay is large.
        leaves = heapq.nsmallest(count, state.source_snapshots.values(),
                                 key=lambda row: row['open_time_ms'])
        if any(not row['is_closed']
               or row['open_time_ms'] != prefix.through_ms + index * width
               or row['close_time_ms'] + 1 != row['open_time_ms'] + width
               for index, row in enumerate(leaves)):
            return
        through = prefix.through_ms + count * width
        # Rate-limit failed optional reads by source progress, not wall time.
        state._history_compaction_retry_ms = incoming.open_time_ms + count * width
        try:
            async with self.reader.stage(slot.source, prefix.start_ms, through) as fresh:
                if not await run_storage(self.reader.matches_closed_overlay, slot.source, fresh, leaves):
                    self.metrics['compaction_deferred'] += 1
                    return
                if (not self._current(slot) or pipeline.bar_state.get_state(state.exchange,
                        state.market_type, state.symbol, state.bucket_start_ms) is not state
                        or state._history_prefix is not prefix):
                    raise BlockRevisionChanged('history target changed during compaction')
                # Check the exact public projection before mutating its owner.
                # replace shares the immutable leaves; adoption assigns new
                # indexes and never mutates these original index containers.
                work = (retained_size((state.source_snapshots, state.source_refs))[0]
                        + 2 * (sys.getsizeof(state.source_snapshots) + sys.getsizeof(state.source_refs))
                        + PREFIX_BYTES)
                with self.reader.memory_budget.reserve('realtime-state', work):
                    probe = replace(state, _component_accumulator=None)
                    pipeline.bar_state._component_merge_strategy.adopt_history_prefix(probe, fresh)
                    fields = ('open', 'high', 'low', 'close', 'volume', 'quote_volume',
                              'trades', 'taker_buy_base', 'taker_buy_quote', 'enhanced_fields',
                              'tick_count', 'first_input_at_ms', 'last_input_at_ms', 'last_close_received')
                    if any(getattr(probe, name) != getattr(state, name) for name in fields):
                        self.metrics['compaction_deferred'] += 1
                        return
                    updated = state.updated_at_ms
                    self._adopt(slot, fresh, refresh=True)
                    state.updated_at_ms = updated
                    state._history_compaction_retry_ms = 0
                    self.metrics['compactions'] += 1
                    self.metrics['compacted_components'] += count
        except (ValueError, BlockUnavailable, BlockRevisionChanged, MemoryBudgetExceeded,
                ExecutorBusyError):
            self.metrics['compaction_deferred'] += 1

    @asynccontextmanager
    async def hold(self, exchange, market_type, symbol, interval, identity):
        key = (exchange, market_type, symbol, interval, identity)
        slot = self.targets.get(key)
        if slot is None:
            yield None
            return
        async with self._task(), slot.lock:
            if not self._current(slot):
                raise BlockRevisionChanged('history target generation expired')
            yield slot

    async def before_input(self, slot, pipeline, incoming, *, emit_events):
        """Called under hold; returns whether the fine input remains applicable."""
        start = pipeline.time_bucket.compute_bucket(incoming.open_time_ms)
        state = pipeline.bar_state.get_state(incoming.exchange, incoming.market_type, incoming.symbol, start)
        states = pipeline.bar_state.get_all_active(incoming.exchange, incoming.market_type, incoming.symbol)
        if state is not None and all(item is not state for item in states):
            states.append(state)
        if (self.flush_delivery is not None and incoming.is_closed
                and any(item._history_prefix is not None
                        and incoming.open_time_ms < item._history_prefix.through_ms for item in states)):
            # Native-first dispatch promises durable admission, not necessarily
            # completion. A covered correction must observe that commit before
            # deciding its unchanged prefix can ignore the fine input.
            async with asyncio.timeout(1.5):
                await self.flush_delivery()
            if not self._current(slot):
                raise BlockRevisionChanged('history target detached during source drain')
        for item in states:
            current = await self._refresh(slot, pipeline, item, emit_events=emit_events)
            if current is not None:
                await self._compact_tail(slot, pipeline, current, incoming)
        if not self._current(slot):
            raise BlockRevisionChanged('history target detached during refresh')
        if slot.recovering:
            # A fully deleted prefix removed the old builder. Until a new warm
            # seed is adopted, historical inputs must come from canonical
            # readback; queued pre-delete snapshots cannot recreate the row.
            spec = parse_interval_spec(slot.source.interval)
            _, end = pipeline.time_bucket.compute_bucket_range(start)
            through = min(end, spec.floor_ms(int(time.time() * 1000)))
            if incoming.open_time_ms < through:
                try:
                    async with self.reader.stage(slot.source, start, through, require_complete=False) as prefix:
                        current = pipeline.bar_state.get_state(incoming.exchange, incoming.market_type, incoming.symbol, start)
                        adopted = self._adopt(slot, prefix, refresh=bool(current and current._history_prefix))
                        slot.recovering = False
                except EmptyHistoryPrefix:
                    return False
                if emit_events:
                    if has_complete_closed_component_coverage(adopted):
                        closed = pipeline.bar_state.close_bar(incoming.exchange, incoming.market_type, incoming.symbol, start)
                        if closed is not None:
                            await self.aggregator.publisher.emit_closed(closed)
                    else:
                        await self.aggregator.publisher.emit_updated(adopted)
                return False
        # Only a compact history input is skipped. The current cumulative live
        # tail remains a normal replaceable component, never a second prefix.
        state = pipeline.bar_state.get_state(incoming.exchange, incoming.market_type, incoming.symbol, start)
        return not (state is not None and state._history_prefix is not None
                    and incoming.open_time_ms < state._history_prefix.through_ms)
