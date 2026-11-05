"""Application ownership of bounded, shared chart calculations.

Entries contain an existing runtime owner, never another market/output cache.
A short HTTP borrow and a later WS borrow use the same opaque identity. Idle
entries expire; admitted opens, active borrows and failed cleanup keep their
capacity until the physical owner has actually been released. All mutations
run on the application's asyncio loop, with no await inside admission steps.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from app.core.async_cleanup import finish_cleanup
from .calculation_owner import CalculationOwnerError, ScriptCalculationOwner

class CalculationRuntime(Protocol):
    owner: ScriptCalculationOwner

    async def close(self) -> None: ...


@dataclass(slots=True)
class _Entry:
    owner_id: str
    last_used: float
    runtime: CalculationRuntime | None = None
    opening: asyncio.Task | None = None
    closing: asyncio.Task | None = None
    retired: bool = False
    borrowers: int = 0
    holders: int = 0
    unborrowed: asyncio.Event = field(default_factory=asyncio.Event)


class CalculationRegistry:
    def __init__(self, *, max_entries: int = 8, idle_seconds: float = 180,
                 sweep_seconds: float = 30, clock: Callable[[], float] = time.monotonic):
        if (type(max_entries) is not int or not 1 <= max_entries <= 128
                or isinstance(idle_seconds, bool) or not math.isfinite(idle_seconds) or idle_seconds <= 0
                or isinstance(sweep_seconds, bool) or not math.isfinite(sweep_seconds) or sweep_seconds <= 0):
            raise ValueError('Invalid calculation registry capacity or lifetime')
        self.max_entries = max_entries
        self.idle_seconds = float(idle_seconds)
        self.sweep_seconds = float(sweep_seconds)
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._collector: asyncio.Task | None = None
        self._closing = False
        self._stop_task: asyncio.Task | None = None

    async def open(self, factory: Callable[[str], Awaitable[CalculationRuntime]]) -> str:
        if self._closing:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CLOSED')
        self._expire_idle()
        if len(self._entries) >= self.max_entries:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CAPACITY')
        entry = _Entry(uuid4().hex, self._clock())
        entry.unborrowed.set()
        self._entries[entry.owner_id] = entry

        async def create():
            try:
                runtime = await factory(entry.owner_id)
                # The factory is application code, not a public transport.
                # Never adopt an owner under a different registry identity.
                entry.runtime = runtime
                if runtime.owner.plan.owner_id != entry.owner_id:
                    raise CalculationOwnerError('INDICATOR_CALCULATION_OUTPUT_IDENTITY_CHANGED')
                entry.last_used = self._clock()
                return runtime
            except BaseException:
                # A partially returned owner must still be drained. A factory
                # that fails before returning retains its own startup cleanup.
                if entry.runtime is None:
                    self._entries.pop(entry.owner_id, None)
                else:
                    self._begin_close(entry)
                raise

        entry.opening = asyncio.create_task(create(), name='indicator-calculation-open:' + entry.owner_id)
        entry.opening.add_done_callback(self._observe)
        if self._collector is None:
            self._collector = asyncio.create_task(self._collect(), name='indicator-calculation-collector')
        await asyncio.shield(entry.opening)
        if self._closing or entry.retired:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CLOSED')
        return entry.owner_id

    @staticmethod
    def _observe(task):
        if not task.cancelled():
            task.exception()

    def _begin_close(self, entry: _Entry) -> asyncio.Task:
        entry.retired = True
        if entry.closing is None or (entry.closing.done() and (
                entry.closing.cancelled() or entry.closing.exception() is not None)):
            async def drain():
                if entry.opening is not None:
                    try:
                        await asyncio.shield(entry.opening)
                    except Exception:
                        # If the factory returned the wrong owner it is held in
                        # entry.runtime and must be closed before slot removal.
                        if entry.runtime is None:
                            return
                await entry.unborrowed.wait()
                if entry.runtime is not None:
                    await entry.runtime.close()
                self._entries.pop(entry.owner_id, None)
            entry.closing = asyncio.create_task(drain(), name='indicator-calculation-retire:' + entry.owner_id)
            entry.closing.add_done_callback(self._observe)
        return entry.closing

    def _expire_idle(self):
        now = self._clock()
        for entry in tuple(self._entries.values()):
            if (not entry.retired and not entry.borrowers and not entry.holders
                    and entry.opening is not None and entry.opening.done()
                    and now - entry.last_used >= self.idle_seconds):
                self._begin_close(entry)

    async def _collect(self):
        while True:
            await asyncio.sleep(self.sweep_seconds)
            self._expire_idle()

    @asynccontextmanager
    async def borrow(self, owner_id: str) -> AsyncIterator[CalculationRuntime]:
        if self._closing:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CLOSED')
        self._expire_idle()
        entry = self._entries.get(owner_id)
        if entry is None or entry.retired:
            raise CalculationOwnerError('INDICATOR_CALCULATION_NOT_FOUND')
        if entry.runtime is None:
            raise CalculationOwnerError('INDICATOR_CALCULATION_NOT_READY')
        entry.borrowers += 1
        entry.unborrowed.clear()
        try:
            yield entry.runtime
        finally:
            # No checkpoint: even a cancelled transport releases this pin.
            # The runtime owner separately shields physical execution/drain.
            entry.borrowers -= 1
            entry.last_used = self._clock()
            if not entry.borrowers:
                entry.unborrowed.set()

    async def retire(self, owner_id: str):
        entry = self._entries.get(owner_id)
        if entry is not None:
            await finish_cleanup(self._begin_close(entry))

    @asynccontextmanager
    async def hold(self, owner_id: str) -> AsyncIterator[CalculationRuntime]:
        """Keep a connected transport alive while idle, without blocking retire.

        Holders must borrow separately for every command. Explicit retirement
        closes the resource and its transport hooks even with idle holders.
        """
        async with self.borrow(owner_id) as runtime:
            entry = self._entries[owner_id]
            entry.holders += 1
        try:
            yield runtime
        finally:
            entry.holders -= 1
            entry.last_used = self._clock()

    async def stop(self):
        if self._stop_task is None or (self._stop_task.done() and (
                self._stop_task.cancelled() or self._stop_task.exception() is not None)):
            self._closing = True

            async def drain():
                if self._collector is not None:
                    self._collector.cancel()
                    await asyncio.gather(self._collector, return_exceptions=True)
                results = await asyncio.gather(*(self._begin_close(entry)
                    for entry in tuple(self._entries.values())), return_exceptions=True)
                failure = next((value for value in results if isinstance(value, BaseException)), None)
                if failure is not None:
                    raise CalculationOwnerError('INDICATOR_CALCULATION_CLEANUP_FAILED') from failure

            self._stop_task = asyncio.create_task(drain(), name='indicator-calculation-registry-stop')
            self._stop_task.add_done_callback(self._observe)
        await finish_cleanup(self._stop_task)

    def snapshot(self) -> dict[str, int | bool]:
        entries = tuple(self._entries.values())
        return {'capacity': self.max_entries, 'entries': len(entries),
                'opening': sum(entry.runtime is None and not entry.retired for entry in entries),
                'borrowers': sum(entry.borrowers for entry in entries),
                'holders': sum(entry.holders for entry in entries),
                'retiring': sum(entry.retired for entry in entries), 'closed': self._closing}
