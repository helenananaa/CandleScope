"""Finite transport-neutral ownership of an already-qualified script runtime.

The owner retains cursors, not market history or another output replica. Its
reader borrows the supervisor's existing SDK projection. A chart-owned view is
distinct from a standalone/as-of history calculation: a range read never feeds
a shorter history into the live instance. Public HTTP/WS binding is separate.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import re
from uuid import uuid4

from app.core.async_cleanup import finish_cleanup
from app.core.runtime_output import RuntimeOutputReference, RuntimeOutputSnapshot

logger = logging.getLogger(__name__)


class CalculationOwnerError(RuntimeError):
    def __init__(self, code: str, *, payload: dict | None = None, detail: dict | None = None):
        self.code = code
        self.payload = payload
        self.detail = detail
        super().__init__(code)


class RuntimeTailReset(CalculationOwnerError):
    """A real runtime reset its partial input and must be reseeded from origin."""

    def __init__(self, reason='workerReset'):
        super().__init__('INDICATOR_CALCULATION_ORIGIN_REQUIRED', detail={'stage':'worker', 'reason':reason})


@dataclass(frozen=True, slots=True)
class CalculationPlan:
    owner_id: str
    semantic_identity: str
    start: int

    def __post_init__(self):
        if (not isinstance(self.owner_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', self.owner_id)
                or not isinstance(self.semantic_identity, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', self.semantic_identity)
                or type(self.start) is not int or self.start <= 0):
            raise CalculationOwnerError('INDICATOR_CALCULATION_PLAN_INVALID')


@dataclass(frozen=True, slots=True)
class CalculationCursor:
    owner_id: str
    generation: int
    sequence: int
    input_revision: str
    observed_through: int
    closed_through: int
    output: RuntimeOutputReference


@dataclass(frozen=True, slots=True)
class CalculationExecution:
    """Runtime adapter receipt, not supplied or trusted from a public caller."""

    output: RuntimeOutputReference
    retained: bool
    reset: bool


Execute = Callable[[str], Awaitable[CalculationExecution]]
Read = Callable[[RuntimeOutputReference], Awaitable[RuntimeOutputSnapshot | None]]


class ScriptCalculationOwner:
    def __init__(self, plan: CalculationPlan, *, read: Read, max_pending: int = 8):
        if type(max_pending) is not int or not 1 <= max_pending <= 64:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CAPACITY_INVALID')
        self.plan = plan
        self._read = read
        self._max_pending = max_pending
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._cursor: CalculationCursor | None = None
        self._runtime_epoch = uuid4().hex
        self._stale = False
        self._closing = False
        self._close_task: asyncio.Task | None = None

    @property
    def cursor(self): return self._cursor

    @property
    def requires_rebuild(self) -> bool:
        """The retained execution is no longer certified by the public cursor."""
        return self._stale

    def _admit(self):
        if self._closing:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CLOSED')
        if len(self._tasks) >= self._max_pending:
            raise CalculationOwnerError('INDICATOR_CALCULATION_BUSY')

    async def _owned(self, action):
        self._admit()
        async def run():
            async with self._lock:
                return await action()
        task = asyncio.create_task(run(), name='indicator-calculation:' + self.plan.owner_id)
        self._tasks.add(task)
        def done(completed):
            self._tasks.discard(completed)
            if not completed.cancelled(): completed.exception()
        task.add_done_callback(done)
        # A cancelled HTTP/WS waiter cannot release ownership while the actual
        # isolated runtime is still applying an input. A later command waits.
        return await asyncio.shield(task)

    def _expected(self, cursor):
        if cursor != self._cursor:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CHANGED')

    async def advance(self, *, semantic_identity: str, input_start: int,
                      observed_through: int, closed_through: int, input_revision: str,
                      expected: CalculationCursor | None, rebuild: bool,
                      is_current: Callable[[], bool], execute: Execute,
                      on_publish: Callable[[CalculationCursor], Awaitable[None]] | None = None,
                      commit_cursor: Callable[[Callable[[], None]], None] | None = None) -> CalculationCursor:
        if (semantic_identity != self.plan.semantic_identity or type(rebuild) is not bool
                or not isinstance(input_revision, str) or not input_revision or len(input_revision) > 256
                or any(type(value) is not int for value in (input_start, observed_through, closed_through))
                or not self.plan.start <= input_start <= observed_through
                or not 0 <= closed_through <= observed_through):
            raise CalculationOwnerError('INDICATOR_CALCULATION_INPUT_INVALID')
        async def apply():
            self._expected(expected)
            old = self._cursor
            if old is not None and (observed_through < old.observed_through or closed_through < old.closed_through):
                raise CalculationOwnerError('INDICATOR_CALCULATION_CLOCK_REGRESSED')
            if (old is None or rebuild or self._stale) and input_start != self.plan.start:
                logger.warning(
                    "Chart origin admission rejected owner=%s origin=%d input=%d:%d "
                    "expected=%s rebuild=%s stale=%s",
                    self.plan.owner_id, self.plan.start, input_start, observed_through,
                    old is not None, rebuild, self._stale,
                )
                raise CalculationOwnerError('INDICATOR_CALCULATION_ORIGIN_REQUIRED', detail={'stage':'ownerAdmission',
                    'origin':self.plan.start,'start':input_start,'through':observed_through})
            if self._stale and not rebuild:
                raise CalculationOwnerError('INDICATOR_CALCULATION_REBUILD_REQUIRED')
            if old is not None and input_revision != old.input_revision and not rebuild:
                raise CalculationOwnerError('INDICATOR_CALCULATION_REBUILD_REQUIRED')
            if not is_current():
                self._stale = True
                raise CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_CHANGED')
            try:
                runtime_epoch = uuid4().hex if rebuild else self._runtime_epoch
                execution = await execute(runtime_epoch)
                if not isinstance(execution, CalculationExecution) or execution.output.stream != self.plan.owner_id:
                    raise CalculationOwnerError('INDICATOR_CALCULATION_OUTPUT_IDENTITY_CHANGED')
                if rebuild and not execution.reset:
                    raise CalculationOwnerError('INDICATOR_CALCULATION_REBUILD_NOT_APPLIED')
                # A dropped runtime/session cannot silently restart a cumulative
                # script from the currently displayed/sliding tail.
                if not execution.retained:
                    logger.warning(
                        "Chart origin runtime rejected owner=%s origin=%d input=%d:%d reset=%s",
                        self.plan.owner_id, self.plan.start, input_start, observed_through,
                        execution.reset,
                    )
                    raise CalculationOwnerError('INDICATOR_CALCULATION_ORIGIN_REQUIRED', detail={'stage':'workerRetention',
                        'origin':self.plan.start,'start':input_start,'through':observed_through})
                if execution.reset and input_start != self.plan.start:
                    raise RuntimeTailReset()
                snapshot = await self._read(execution.output)
                if snapshot is None or snapshot.reference != execution.output:
                    raise CalculationOwnerError('INDICATOR_CALCULATION_OUTPUT_LOST')
                if not is_current():
                    raise CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_CHANGED')
                reset = old is None or rebuild or execution.reset or (
                    execution.output.owner_epoch, execution.output.generation) != (
                    old.output.owner_epoch, old.output.generation)
                candidate = CalculationCursor(self.plan.owner_id,
                    1 if old is None else old.generation + int(reset),
                    1 if old is None else old.sequence + 1, input_revision,
                    observed_through, closed_through, execution.output)
                def publish():
                    if not is_current():
                        raise CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_CHANGED')
                    self._cursor = candidate
                if commit_cursor is None: publish()
                else: commit_cursor(publish)
                self._runtime_epoch = runtime_epoch
                self._stale = False
            except BaseException:
                # The runtime may have progressed before failure/fencing. Only
                # a full-origin rebuild may make its projection current again.
                self._stale = True
                self._cursor = old
                raise
            if on_publish is not None:
                # Publication/observer ordering stays under the same owner.
                # Observer failure cannot undo or replay committed mathematics.
                await on_publish(self._cursor)
            return self._cursor
        return await self._owned(apply)

    async def read(self, *, expected: CalculationCursor) -> RuntimeOutputSnapshot:
        async def view():
            self._expected(expected)
            if self._stale or self._cursor is None:
                raise CalculationOwnerError('INDICATOR_CALCULATION_REBUILD_REQUIRED')
            snapshot = await self._read(self._cursor.output)
            if snapshot is None or snapshot.reference != self._cursor.output:
                self._stale = True
                raise CalculationOwnerError('INDICATOR_CALCULATION_OUTPUT_LOST')
            return snapshot
        return await self._owned(view)

    async def close(self, *, release: Callable[[], Awaitable[None]]):
        if self._close_task is None or (self._close_task.done() and (
                self._close_task.cancelled() or self._close_task.exception() is not None)):
            self._closing = True
            async def drain():
                if self._tasks: await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
                await release()
            self._close_task = asyncio.create_task(drain(), name='indicator-calculation-close:' + self.plan.owner_id)
        await finish_cleanup(self._close_task)
