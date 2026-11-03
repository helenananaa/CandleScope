"""Replay access and consumer lifetimes, without owning clocks or accounts.

ReplayRuntime remains the service/storage lifecycle owner. This application-loop
facade gates new access and releases only transport tasks when the host closes.
No market rows, account projections or command results are cached here.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.replay.errors import ReplayDomainError, ReplayErrorCode

if TYPE_CHECKING:
    from app.replay.runtime import ReplayRuntime
    from app.replay.service import ReplayService


class ReplayDataManager:
    def __init__(self, service: ReplayService, runtime: ReplayRuntime | None = None) -> None:
        self.service = service
        self.runtime = runtime
        self._closed = False
        self._accesses = 0
        self._streams: dict[asyncio.Task[None], tuple[str, str]] = {}

    @property
    def closed(self) -> bool:
        return self._closed or (self.runtime is not None and self.runtime.service is not self.service)

    def control_plane(self) -> ReplayService:
        if self.closed:
            raise ReplayDomainError(ReplayErrorCode.REPLAY_DISABLED, "Replay data manager is closed")
        self._accesses += 1
        return self.service

    @staticmethod
    def _cancel_once(task: asyncio.Task) -> None:
        if not task.done() and not task.cancelling():
            task.cancel()

    async def serve_stream(self, kind: str, identity: str, start: Callable[[], Awaitable[None]]) -> None:
        self.control_plane()
        async def consume() -> None:
            await start()
        task = asyncio.create_task(consume(), name=f"replay-manager-{kind}")
        self._streams[task] = (kind, identity)

        def finished(done: asyncio.Task) -> None:
            self._streams.pop(done, None)
            if not done.cancelled():
                done.exception()  # Cleanup can outlive a cancelled transport waiter.

        task.add_done_callback(finished)
        cancellation: asyncio.CancelledError | None = None
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            # Closing this facade cancels its child transports, not their ASGI
            # callers or any in-flight financial command owned by the service.
            if asyncio.current_task().cancelling() or not self.closed:
                cancellation = exc
        finally:
            self._cancel_once(task)
            cleanup = asyncio.create_task(asyncio.wait({task}, timeout=1.0))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError as exc:
                    cancellation = exc
            cleanup.result()
            # The task remains strongly owned until its own protocol cleanup
            # finishes, even if a broken transport exceeds this bounded wait.
            if cancellation is not None:
                raise cancellation

    def close(self) -> None:
        self._closed = True
        for task in tuple(self._streams):
            self._cancel_once(task)

    async def shutdown(self, *, step_timeout: float = 5.0) -> None:
        self.close()
        tasks = tuple(self._streams)
        if tasks:
            await asyncio.wait(tasks, timeout=step_timeout)

    def diagnostics(self) -> dict[str, object]:
        active = [scope for task, scope in self._streams.items() if not task.done()]
        return {"closed": self.closed, "control_accesses": self._accesses,
                "streams": len(active), "consumers": dict(Counter(kind for kind, _ in active)),
                "scopes": len(set(active))}


def optional_replay_service_from_state(state: object) -> ReplayService | None:
    core = getattr(state, "data_manager_core", None)
    if core is not None:
        manager = getattr(core, "replay", None)
        return manager.control_plane() if manager is not None and not manager.closed else None
    # Explicit standalone service hosts have no composition root. A production
    # root that is unbound/closed must never fall through to a stale alias.
    return getattr(state, "replay_service", None)
