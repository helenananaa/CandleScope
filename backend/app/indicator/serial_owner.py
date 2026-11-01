"""Bounded ownership for mutable builtin indicators, separate from history.

Production uses one owned process; thread mode supports controlled comparison.
A command retains ownership until physical completion and loop-side delivery;
cancelling its waiter never permits overlapping state mutation.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import os
import threading
import time
import sys
try:
    import resource
except ImportError:  # Windows packaging uses the same worker protocol.
    resource = None
import logging
from typing import Any, Callable

from app.core.bounded_executor import BoundedExecutor, ExecutorBusyError
from app.core.process_lane import ProcessMessageTooLarge, SerialProcessLane
from app.data_engine.data_manager.models import BarData
from app.indicator.engine import IndicatorCapacityError, IndicatorParametersError, indicator_code_hash
from app.indicator.events import IndicatorEvent, IndicatorEventType
from app.indicator.types import IndicatorKey

logger = logging.getLogger("candlescope.indicator.owner")


class IndicatorInputChanged(RuntimeError):
    """A queued history snapshot no longer covers the owner's state."""

    code = "INDICATOR_INPUT_CHANGED"


class IndicatorGenerationChanged(IndicatorInputChanged):
    code = "INDICATOR_GENERATION_CHANGED"


def _argument(args: tuple, kwargs: dict, index: int, name: str, default=None):
    return args[index] if len(args) > index else kwargs.get(name, default)


def _revision_token(revision) -> str:
    return str(revision.get('revisionToken') or
               f"{revision.get('serverEpoch', '')}:{revision.get('correctionRevision', 0)}") if isinstance(revision, dict) else ''


def _command_key(method: str, args: tuple, kwargs: dict) -> IndicatorKey:
    subscribing = method == 'subscribe'
    name = _argument(args, kwargs, 3, 'indicator_name') if subscribing else '__topic__'
    return IndicatorKey(
        _argument(args, kwargs, 0, 'symbol'), _argument(args, kwargs, 1, 'interval'),
        name, _argument(args, kwargs, 4, 'params', {}) if subscribing else {},
        market_type=_argument(args, kwargs, 2 if subscribing else 3, 'market_type', 'spot'),
        exchange=_argument(args, kwargs, 6 if subscribing else 4, 'exchange', 'binance'),
        series_identity=_argument(args, kwargs, 9 if subscribing else 7, 'series_identity'),
        code_hash=indicator_code_hash(name) if subscribing else '',
    )


def _validate_history_state(engine, method: str, args: tuple, kwargs: dict) -> None:
    """Recheck at the physical owner boundary, without changing any state.

    The bridge's query fence is necessary but insufficient once another close
    can run between its last check and admission to this worker.
    """
    if method not in {"subscribe", "on_bars_backfilled"}:
        return
    subscribing = method == "subscribe"
    source = _argument(args, kwargs, 5 if subscribing else 2, "bars") or ()
    confirmed = [bar for bar in source if bar.is_closed]
    if not confirmed:
        return
    key = _command_key(method, args, kwargs)
    keys = [key] if subscribing else list(engine._stream_keys.get(key.series_topic, ()))
    last = max((engine._last_committed.get(key, 0) for key in keys), default=0)
    start, end = min(bar.time for bar in confirmed), max(bar.time for bar in confirmed)
    if end < last:
        raise IndicatorInputChanged("Indicator input state changed; history ends before the committed tail")
    if not subscribing:
        minimum = max((engine._instances[key].bar_count for key in keys if key in engine._instances), default=0)
        first = min((engine._first_committed[key] for key in keys if key in engine._first_committed), default=start)
        if len(confirmed) < minimum or start > first:
            raise IndicatorInputChanged("Indicator input state changed; correction omits part of the committed seed")


def _input_snapshot(value: Any) -> Any:
    # Bars are frozen value objects. Copy containers, not every historical bar
    # on the event loop. Small mutable parameter/revision dictionaries are owned
    # by the admitted command from this point onwards.
    if isinstance(value, BarData):
        return value
    if isinstance(value, dict):
        return {key: _input_snapshot(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        if not value or isinstance(value[0], BarData):
            return value.copy() if isinstance(value, list) else value
        return type(value)(_input_snapshot(item) for item in value)
    return value


def _bar_count(value: Any) -> int:
    if isinstance(value, BarData):
        return 1
    if isinstance(value, dict):
        return sum(_bar_count(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        if value and isinstance(value[0], BarData):
            return len(value)
        return sum(_bar_count(item) for item in value)
    return 0


async def drain_control_task(task: asyncio.Task) -> None:
    """Finish one bounded control operation before propagating cancellation."""
    cancelled = False
    while True:
        try:
            await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.done():
                task.result()
                cancelled = True
                break
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError


class _IndicatorState:
    """Mutable state used exclusively by one physical worker."""

    def __init__(self, factory=None):
        self._factory = factory
        self._engine = None
        self._applied_revisions: dict[IndicatorKey, dict] = {}
        self._worker_snapshot: dict = {}
        self._worker_rows: dict[int, int] = {}
        self._worker_key_ids: tuple[int, ...] = ()
        self._worker_keys: tuple[IndicatorKey, ...] = ()

    def _validate_revision(self, engine, method, args, kwargs, input_revision):
        if method == 'subscribe':
            key = _command_key(method, args, kwargs)
            old = self._applied_revisions.get(key)
            if (key in engine._instances and engine._instances[key].is_initialized
                    and _revision_token(old) != _revision_token(input_revision)):
                if engine._refcounts.get(key, 0) > 0:
                    raise IndicatorInputChanged('Indicator correction is not applied to the shared instance yet')
                engine._destroy_instance(key)
                self._applied_revisions.pop(key, None)
        elif method == 'on_bars_backfilled' and isinstance(input_revision, dict):
            topic = _command_key(method, args, kwargs).series_topic
            for key, old in self._applied_revisions.items():
                if key.series_topic != topic or key not in engine._instances:
                    continue
                if (old.get('serverEpoch') != input_revision.get('serverEpoch') or
                        int(old.get('correctionRevision', 0)) > int(input_revision.get('correctionRevision', 0))):
                    raise IndicatorInputChanged('Correction snapshot predates applied indicator revision')
        elif method in {'preview_for_key', 'get_result'} and isinstance(input_revision, dict):
            if _revision_token(self._applied_revisions.get(args[0])) != _revision_token(input_revision):
                raise IndicatorInputChanged('Indicator state belongs to another source revision')

    def _stamp_revision(self, event, input_revision):
        revision = event.detail.get('dataRevision', input_revision)
        if revision is None:
            return
        old = self._applied_revisions.get(event.key)
        if event.event_type in {IndicatorEventType.INSTANCE_INITIALIZED, IndicatorEventType.INDICATOR_RECOMPUTED}:
            if isinstance(revision, dict):
                # A no-recompute invalidation is safe only if no earlier
                # correction remains unapplied to this instance.
                contiguous = old is not None and old.get('serverEpoch') == revision.get('serverEpoch') and (
                    int(revision.get('correctionRevision', 0)) - int(old.get('correctionRevision', 0)) in (0, 1))
                if event.full_result is not None or contiguous:
                    self._applied_revisions[event.key] = deepcopy(revision)
                else:
                    event.detail['resyncRequired'] = True
                    event.detail['dataRevision'] = deepcopy(old)
        elif event.event_type in {IndicatorEventType.INDICATOR_UPDATED, IndicatorEventType.INDICATOR_PREVIEW}:
            if isinstance(revision, dict):
                if _revision_token(old) != _revision_token(revision):
                    event.detail['resyncRequired'] = True
                elif old is not None:
                    old = {**old, 'closedThrough': max(int(old.get('closedThrough', 0)),
                           event.bar_timestamp if event.event_type == IndicatorEventType.INDICATOR_UPDATED else 0)}
                    self._applied_revisions[event.key] = old
                event.detail['dataRevision'] = deepcopy(old)

    def execute(self, method: str, args: tuple, kwargs: dict) -> tuple:
        kwargs = dict(kwargs)
        input_revision = kwargs.pop('__input_revision', None) or kwargs.get('data_revision')
        if method == "__reset_source":
            if self._engine is not None:
                try:
                    self._engine.stop()
                except Exception:
                    logger.exception("Discarding failed indicator engine")
            self._engine = None
            self._applied_revisions.clear()
            self._worker_snapshot = {}
            self._worker_rows.clear()
            self._worker_key_ids = ()
            self._worker_keys = ()
        if self._engine is None:
            if self._factory is None:
                from app.indicator import create_engine
                self._engine = create_engine()
            else:
                self._engine = self._factory()
        engine = self._engine
        self._validate_revision(engine, method, args, kwargs, input_revision)
        _validate_history_state(engine, method, args, kwargs)
        events: list = []
        committed: list[tuple[int, int]] = []
        changed_keys = None
        # Capture detached values while the worker owns the engine. Consumers
        # never run on this thread or inspect engine-owned mutable structures.
        def capture(event):
            self._stamp_revision(event, input_revision)
            if event.event_type == IndicatorEventType.INDICATOR_UPDATED:
                committed.append((id(event.key), event.bar_timestamp))
            # Realtime frames contain scalar values and a small bar detail.
            # Clone these explicitly; generic dataclass reconstruction for
            # every tick needlessly duplicates reflection and key identity.
            events.append(IndicatorEvent(
                event.event_type, replace(event.key, params=deepcopy(event.key.params)),
                values=dict(event.values), full_result=deepcopy(event.full_result),
                detail=deepcopy(event.detail), timestamp_ms=event.timestamp_ms,
                bar_timestamp=event.bar_timestamp,
            ))
        engine.add_listener(capture)
        try:
            if method == "__reset_source":
                result = None
            elif method == "__release_many":
                for key, count in args[0].items():
                    engine.unsubscribe(key, count=count)
                result = None
            elif method == "set_source_delivery_state":
                engine.source_delivery_state = dict(args[0])
                result = None
            else:
                result = getattr(engine, method)(*args, **kwargs)
            if any(event.event_type == IndicatorEventType.INDICATOR_ERROR for event in events):
                raise RuntimeError('Indicator calculation reported a state transition failure')
            steady_update = (method in {'on_bar_updated', 'on_bar_closed'} and self._worker_snapshot
                             and all(event.event_type in {IndicatorEventType.INDICATOR_UPDATED, IndicatorEventType.INDICATOR_PREVIEW}
                                     for event in events))
            if steady_update:
                # Copy-on-write diagnostic rows: preview changes no committed
                # field; each successful close advances only its own row.
                # Never mutate a snapshot already handed to the loop.
                snapshot = self._worker_snapshot
                if committed:
                    rows = list(snapshot['instances'])
                    for key_id, timestamp in committed:
                        index = self._worker_rows[key_id]
                        row = rows[index]
                        rows[index] = {**row, 'bar_count': row['bar_count'] + 1,
                                       'last_committed': timestamp}
                    snapshot = {**snapshot, 'instances': rows}
            else:
                snapshot = engine.snapshot()
                self._worker_rows = {id(key): index for index, key in enumerate(engine._instances)}
                self._applied_revisions = {key: revision for key, revision in self._applied_revisions.items()
                                           if key in engine._instances}
                key_ids = tuple(self._worker_rows)
                if key_ids != self._worker_key_ids:
                    self._worker_key_ids = key_ids
                    self._worker_keys = deepcopy(tuple(engine._instances))
                    changed_keys = self._worker_keys
            peak_rss = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
                        if resource is not None else None)
            snapshot = {**snapshot, "worker": {"pid": os.getpid(), "thread": threading.get_ident(),
                                              "cpu_seconds": time.process_time(), "peak_rss_bytes": peak_rss}}
            self._worker_snapshot = snapshot
            if method in {'stop', '__reset_source'}:
                changed_keys = self._worker_keys
            if steady_update:
                # The loop already owns the unchanged diagnostic metadata.
                # Only committed frontiers and worker telemetry cross IPC on
                # ordinary ticks; membership changes always send a full view.
                snapshot = {'_delta': True, 'worker': snapshot['worker'], 'committed': [
                    (self._worker_rows[key_id], self._worker_snapshot['instances'][self._worker_rows[key_id]]['bar_count'], timestamp)
                    for key_id, timestamp in committed
                ]}
            return deepcopy(result), events, snapshot, changed_keys
        finally:
            engine.remove_listener(capture)



_process_state = None


def _process_command(method, args, kwargs):
    global _process_state
    if _process_state is None:
        _process_state = _IndicatorState()
    return _process_state.execute(method, args, kwargs)


class SerialIndicatorOwner:
    """One physical worker, with finite commands and retained input rows.

    Listeners and adoption callbacks run on the creating loop. The engine is
    created, read, mutated and destroyed only by its worker. The facade never
    exposes a raw engine or a mutable indicator instance.
    """

    METHODS = frozenset({
        "subscribe", "unsubscribe", "on_bar_closed", "on_bar_updated",
        "preview_for_key", "plan_series_correction", "active_series_intervals",
        "resident_series_intervals", "on_series_correction_invalidated",
        "on_bars_backfilled", "invalidate_source_gap", "get_result",
        "list_instances", "destroy_all", "set_source_delivery_state",
    })

    def __init__(self, *, factory: Callable | None = None,
                 max_pending: int = 64, max_input_bars: int = 500_000,
                 execution_mode: str = "thread") -> None:
        if max_pending < 0 or max_input_bars < 1:
            raise ValueError("Invalid indicator owner capacity")
        self._loop = asyncio.get_running_loop()
        self._factory = factory
        if execution_mode not in {"thread", "process"}:
            raise ValueError("Invalid indicator execution mode")
        if execution_mode == "process" and factory is not None:
            raise ValueError("Process ownership uses the installed builtin registry")
        self._execution_mode = execution_mode
        self._state = _IndicatorState(factory)
        self._process_lane = None
        self._transport_snapshot = {}
        self._process_starts = 0
        self._executor = BoundedExecutor("indicator_realtime", max_workers=1, max_pending=0)
        self._lock = asyncio.Lock()
        self._max_inflight = max_pending + 1
        self._max_input_bars = max_input_bars
        self._inflight = self._input_bars = self._sequence = 0
        self._rejected = self._cancelled_queued = self._cancelled_running = 0
        self._closing = self._closed = False
        self._failure: str | None = None
        self._generation = 0
        self._recovering = False
        self._recovery_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._release_task: asyncio.Task | None = None
        self._pending_releases: dict[tuple[int, IndicatorKey], int] = {}
        self._known_keys: tuple[IndicatorKey, ...] = ()
        self._listeners: list[Callable] = []
        self._snapshot: dict[str, Any] = {"started": False, "instances": []}

    def _assert_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("Indicator owner used from another event loop")

    def add_listener(self, listener: Callable) -> None:
        self._assert_loop()
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable) -> None:
        self._assert_loop()
        if listener in self._listeners:
            self._listeners.remove(listener)

    @property
    def generation(self) -> int:
        self._assert_loop()
        return self._generation

    def _publish(self, events) -> None:
        for event in events:
            for listener in tuple(self._listeners):
                try:
                    listener(event)
                except Exception:
                    logger.exception("Indicator listener failed")

    def _notify_resync(self, detail: dict) -> None:
        self._publish(IndicatorEvent(IndicatorEventType.INDICATOR_ERROR, deepcopy(key),
            detail={**detail, "resyncRequired": True, "ownerGeneration": self._generation})
            for key in self._known_keys)

    def fail_recovery(self, error: Exception) -> None:
        self._assert_loop()
        self._failure = str(error) or type(error).__name__
        self._notify_resync({"error": "Indicator source recovery failed"})

    def snapshot(self) -> dict[str, Any]:
        self._assert_loop()
        state = ("recovering" if self._recovering else "recovery_failed" if self._failure else None)
        return {**deepcopy(self._snapshot), "listener_count": len(self._listeners),
                **({"source_delivery": {"state": state, "error": self._failure}} if state else {}),
                "serial_owner": {"execution_mode": self._execution_mode, "sequence": self._sequence, "inflight": self._inflight,
                    "max_inflight": self._max_inflight, "input_bars": self._input_bars,
                    "max_input_bars": self._max_input_bars, "rejected": self._rejected,
                    "cancelled_queued": self._cancelled_queued,
                    "cancelled_running": self._cancelled_running,
                    "closing": self._closing, "closed": self._closed,
                    "failure": self._failure,
                    "generation": self._generation, "recovering": self._recovering,
                    "release_targets": len(self._pending_releases),
                    "process_starts": self._process_starts,
                    "transport": dict(self._transport_snapshot),
                    "executor": self._executor.snapshot()}}

    def _adopt_snapshot(self, snapshot, keys):
        if snapshot.get('_delta'):
            rows = self._snapshot['instances']
            if snapshot['committed']:
                rows = list(rows)
                for index, count, timestamp in snapshot['committed']:
                    rows[index] = {**rows[index], 'bar_count': count, 'last_committed': timestamp}
            self._snapshot = {**self._snapshot, 'instances': rows, 'worker': snapshot['worker']}
        else:
            self._snapshot = snapshot
        if keys is not None:
            self._known_keys = keys

    def _execute(self, method: str, args: tuple, kwargs: dict) -> tuple:
        if self._execution_mode == "thread":
            return self._state.execute(method, args, kwargs)
        # This synchronous transport runs on the dedicated I/O thread, never
        # on the event loop. One worker process owns all mutable instances.
        if method == "__reset_source" and self._process_lane is not None:
            self._process_lane.close()
            self._process_lane = None
        if self._process_lane is None:
            self._process_lane = SerialProcessLane(_process_command, name="indicator-realtime")
            self._process_starts += 1
        try:
            return self._process_lane.call(method, args, kwargs)
        finally:
            self._transport_snapshot = self._process_lane.snapshot()
            if method == "stop":
                self._process_lane.close()
                self._process_lane = None

    async def _physical(self, method: str, args: tuple, kwargs: dict) -> tuple:
        physical = self._executor.submit(lambda: self._execute(method, args, kwargs), operation=method)
        future = asyncio.wrap_future(physical)
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(future)
                return result, cancelled
            except asyncio.CancelledError:
                if future.done():
                    # A command itself may fail with CancelledError. It must
                    # not be mistaken for another cancellation of the waiter.
                    result = future.result()
                    if not cancelled:
                        self._cancelled_running += 1
                    return result, True
                if not cancelled:
                    self._cancelled_running += 1
                cancelled = True
                # Ownership and physical capacity remain held. This command
                # has been accepted, so finish its ordered state transition.
                continue

    async def call(self, method: str, *args: Any,
                   adopt: Callable[[Any], None] | None = None,
                   expected_generation: int | None = None,
                   input_revision: dict | None = None, **kwargs: Any) -> Any:
        self._assert_loop()
        if method not in self.METHODS:
            raise ValueError(f"Unsupported indicator owner operation: {method}")
        if method == "unsubscribe":
            return await self.release(_argument(args, kwargs, 0, "key"), expected_generation=expected_generation)
        if self._closing:
            raise RuntimeError("Indicator owner is closing")
        generation = self._generation if expected_generation is None else expected_generation
        if generation != self._generation:
            if method == "unsubscribe":
                return None  # The old generation's engine has been discarded.
            raise IndicatorGenerationChanged("Indicator input generation changed; reload canonical history")
        if self._recovering:
            raise IndicatorGenerationChanged("Indicator input generation is recovering")
        if self._failure is not None:
            raise RuntimeError("Indicator owner failed; rebuild from canonical history")
        count = _bar_count(args) + _bar_count(kwargs)
        if self._inflight >= self._max_inflight or self._input_bars + count > self._max_input_bars:
            self._rejected += 1
            raise ExecutorBusyError("indicator_realtime")
        self._inflight += 1
        self._input_bars += count
        started = False
        try:
            args, kwargs = _input_snapshot(args), _input_snapshot(kwargs)
            if input_revision is not None:
                kwargs['__input_revision'] = deepcopy(input_revision)
            async with self._lock:
                if self._closing:
                    raise RuntimeError("Indicator owner is closing")
                if generation != self._generation or self._recovering:
                    if method == "unsubscribe":
                        return None
                    raise IndicatorGenerationChanged("Indicator input generation changed while queued")
                if self._failure is not None:
                    raise RuntimeError("Indicator owner failed; rebuild from canonical history")
                started = True
                try:
                    (result, events, snapshot, keys), cancelled = await self._physical(method, args, kwargs)
                except (IndicatorInputChanged, IndicatorCapacityError, IndicatorParametersError, ProcessMessageTooLarge):
                    # Rejected before any mutation; the caller can fetch a
                    # fresh canonical snapshot without poisoning valid state.
                    raise
                except BaseException as error:
                    # An unexpected worker failure may have partially changed
                    # state. Never continue issuing apparently valid results.
                    self._failure = str(error) or type(error).__name__
                    self._notify_resync({"error": "Indicator calculation failed; reload canonical history"})
                    raise
                if generation != self._generation or self._recovering:
                    # Recovery owns disposal of the old engine, including any
                    # subscription which completed after its caller became old.
                    raise IndicatorGenerationChanged("Indicator input generation changed while running")
                self._sequence += 1
                self._adopt_snapshot(snapshot, keys)
                # Adoption is synchronous on the loop, before a subsequent
                # command or listener can observe the new subscription.
                if adopt is not None:
                    adopt(result)
                for event in events:
                    event.detail["ownerGeneration"] = generation
                self._publish(events)
                if cancelled:
                    raise asyncio.CancelledError
                return result
        except asyncio.CancelledError:
            if not started:
                self._cancelled_queued += 1
            raise
        finally:
            self._inflight -= 1
            self._input_bars -= count

    async def release(self, key: IndicatorKey, *, expected_generation: int | None = None) -> None:
        """Coalesce cleanup by existing target; never compete with new work.

        There is one drain task and at most one counter per resident target,
        even if many clients disconnect while ordinary admission is full.
        """
        self._assert_loop()
        generation = self._generation if expected_generation is None else expected_generation
        if self._closing or generation != self._generation or self._recovering or key not in self._known_keys:
            return
        claim = generation, key
        self._pending_releases[claim] = self._pending_releases.get(claim, 0) + 1

        async def drain():
            while self._pending_releases:
                async with self._lock:
                    generation = self._generation
                    batch = {key: count for (epoch, key), count in self._pending_releases.items() if epoch == generation}
                    self._pending_releases.clear()
                    if not batch:
                        continue
                    try:
                        (_, events, snapshot, keys), _ = await self._physical("__release_many", (batch,), {})
                    except BaseException as error:
                        self._failure = str(error) or type(error).__name__
                        self._notify_resync({"error": "Indicator release failed; reload canonical history"})
                        raise
                    if generation == self._generation and not self._recovering:
                        self._adopt_snapshot(snapshot, keys)
                        self._sequence += 1
                        self._publish(events)

        if self._release_task is None or self._release_task.done():
            self._release_task = asyncio.create_task(drain(), name="indicator-owner-release")
        await drain_control_task(self._release_task)

    async def recover(self, detail: dict) -> None:
        """Invalidate old admissions immediately; replace state on its worker.

        One reserved control operation can recover even when ordinary admission
        is full. Old subscriptions are terminal; new clients seed from storage.
        """
        self._assert_loop()
        if self._closing:
            raise RuntimeError("Indicator owner is closing")
        if self._recovering:
            raise ExecutorBusyError("indicator_realtime_recovery")
        self._recovering = True
        self._generation += 1
        self._pending_releases.clear()
        self._notify_resync(detail)

        async def reset():
            try:
                async with self._lock:
                    (_, _, snapshot, keys), _ = await self._physical("__reset_source", (), {})
                    self._adopt_snapshot(snapshot, keys)
                    self._failure = None
                    self._sequence += 1
            except BaseException as error:
                self._failure = str(error) or type(error).__name__
                raise
            finally:
                self._recovering = False

        task = self._recovery_task = asyncio.create_task(reset(), name="indicator-owner-recovery")
        await drain_control_task(task)

    async def aclose(self) -> None:
        self._assert_loop()
        if self._closed:
            return
        self._closing = True

        async def stop():
            if self._recovery_task is not None:
                await asyncio.gather(self._recovery_task, return_exceptions=True)
            if self._release_task is not None:
                await asyncio.gather(self._release_task, return_exceptions=True)
            async with self._lock:
                try:
                    (_, _, snapshot, _), _ = await self._physical("stop", (), {})
                    self._snapshot = snapshot
                finally:
                    self._listeners.clear()
                    self._known_keys = ()
                    self._executor.shutdown(wait=False)
                    self._closed = True

        if self._close_task is None:
            self._close_task = asyncio.create_task(stop(), name="indicator-owner-close")
        await drain_control_task(self._close_task)


async def call_engine(engine: Any, method: str, *args: Any,
                      adopt: Callable[[Any], None] | None = None,
                      expected_generation: int | None = None,
                      input_revision: dict | None = None, **kwargs: Any) -> Any:
    """Support explicit standalone synchronous engines in isolated computations."""
    if isinstance(engine, SerialIndicatorOwner):
        return await engine.call(method, *args, adopt=adopt, expected_generation=expected_generation,
                                 input_revision=input_revision, **kwargs)
    if method == "set_source_delivery_state":
        engine.source_delivery_state = dict(args[0])
        return None
    result = getattr(engine, method)(*args, **kwargs)
    if adopt is not None:
        adopt(result)
    return result
