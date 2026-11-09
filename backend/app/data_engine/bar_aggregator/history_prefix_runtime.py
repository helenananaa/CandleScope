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

from app.core.async_cleanup import finish_cleanup
from app.core.bounded_executor import ExecutorBusyError
from app.core.executors import run_storage
from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.bar_aggregator.bar_state import has_complete_closed_component_coverage
from app.data_engine.bar_aggregator.models import BarStatus
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
from app.data_engine.memory_budget import MemoryBudgetExceeded
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

    def __init__(self, reader, aggregator, require_recovery):
        self.aggregator = aggregator
        self.reader = reader
        self.require_recovery = require_recovery
        self.targets = {}
        self.tasks = set()
        self.seeding = set()
        self.closing = False
        self.last_adoption = None
        self._input_read_scope = ContextVar("history_prefix_input_read_scope", default=None)
        self.metrics = dict(adoptions=0, validations=0, refreshes=0, empty=0, failures=0,
                            adopted_pages=0, adopted_storage_rows=0, adopted_cache_hits=0)

    def snapshot(self):
        return {**self.metrics, 'targets': len(self.targets), 'tasks': len(self.tasks),
                'seeding': len(self.seeding), 'max_targets': self.MAX_TARGETS,
                'max_tasks': self.MAX_TASKS, 'minimum_prefix_rows': self.MIN_ROWS, 'closing': self.closing,
                'last_adoption': dict(self.last_adoption) if self.last_adoption else None}

    def _current(self, slot):
        return (not self.closing and self.targets.get(slot.token[0]) is slot
                and self.aggregator.history_target_token(slot.source, slot.token[0][3]) == slot.token)

    def detach(self, key):
        self.targets.pop(key, None)

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
        if cancelled:
            raise asyncio.CancelledError

    def _adopt(self, slot, prefix, *, refresh=False):
        if not self._current(slot):
            raise BlockRevisionChanged('history target detached before adoption')
        result = None
        allowance = 0 if refresh else PREFIX_BYTES
        with self.reader.memory_budget.reserve('realtime-state', allowance) as lease:
            def commit():
                nonlocal result
                result = self.aggregator.adopt_history_prefix(prefix, slot.token, refresh=refresh)
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
        if (state.status != BarStatus.FORMING or state._history_prefix is not None
                or type(state.acquisition_revision) is not int or incoming.source_interval != "5m"
                or incoming.close_time_ms + 1 != state.bucket_end_ms
                or has_complete_closed_component_coverage(state)):
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
        try:
            async with self._task(), self.reader.stage(source, state.bucket_start_ms, state.bucket_end_ms) as prefix:
                if (self.closing or self.aggregator.history_target_token(source, state.interval) != token
                        or pipeline.bar_state.get_state(*key) is not state or state.status != BarStatus.FORMING):
                    return None
                if token[0] in self.targets or len(self.targets) >= self.MAX_TARGETS:
                    return state
                slot = _Target(source, token)
                floor = state.acquisition_revision
                with self.reader.memory_budget.reserve("realtime-state", 1024) as lease:
                    lease.retain(1024, lambda: self.targets.__setitem__(token[0], slot))
                try:
                    self._adopt(slot, prefix)
                except BaseException:
                    self.detach(token[0])
                    raise
                adopted = pipeline.bar_state.get_state(*key)
                adopted.canonical_recovery_delete_floor = floor
                return adopted
        except (ValueError, BlockUnavailable, BlockRevisionChanged, MemoryBudgetExceeded,
                BarDeliveryUnavailable, ExecutorBusyError):
            # Incomplete or stale storage cannot turn a preview into a close.
            if (self.aggregator.history_target_token(source, state.interval) != token
                    or pipeline.bar_state.get_state(*key) is not state or state.status != BarStatus.FORMING):
                return None
            return state

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
        try:
            async with self.reader.stage(slot.source, prefix.start_ms, prefix.through_ms,
                                         require_complete=False) as fresh:
                if pipeline.bar_state.get_state(state.exchange, state.market_type,
                                                state.symbol, state.bucket_start_ms) is not state:
                    raise BlockRevisionChanged('history builder replaced during refresh')
                adopted = self._adopt(slot, fresh, refresh=True)
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
        covered = state is not None and state._history_prefix is not None and incoming.open_time_ms < state._history_prefix.through_ms
        states = pipeline.bar_state.get_all_active(incoming.exchange, incoming.market_type, incoming.symbol)
        if state is not None and all(item is not state for item in states):
            states.append(state)
        for item in states:
            await self._refresh(slot, pipeline, item, emit_events=emit_events)
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
        return not covered
