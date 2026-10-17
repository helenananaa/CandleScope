"""Coordinate derived indicator work without occupying account writer lanes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import Event


@dataclass(slots=True)
class _Waiters:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class IndicatorPreparationJobs:
    def __init__(self):
        self._waiting: dict[tuple, _Waiters] = {}
        self._slots = asyncio.Semaphore(2)

    async def run(self, key: tuple, work, cancelled: Event):
        # Different view windows share prefix checkpoints. Serialize only their
        # preparation identity; the next window then loads the new checkpoint.
        entry = self._waiting.setdefault(key, _Waiters())
        entry.users += 1
        try:
            async with entry.lock, self._slots:
                task = asyncio.create_task(work())
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled.set()
                    # A Python worker cannot be stopped by cancelling its
                    # Future. Drain the bounded read before freeing this slot.
                    drain = asyncio.gather(task, return_exceptions=True)
                    while not drain.done():
                        try:
                            await asyncio.shield(drain)
                        except asyncio.CancelledError:
                            continue
                    drain.result()
                    raise
        finally:
            cancelled.set()
            entry.users -= 1
            if entry.users == 0:
                del self._waiting[key]
