"""Keep ownership of asynchronous cleanup until it is physically complete."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import anyio

T = TypeVar("T")


async def apply_thread_guard(
    lock: Any, operation: Callable[..., T], *args: Any, **kwargs: Any,
) -> T:
    """Apply a synchronous owner-loop mutation after cooperative lock admission."""
    while not lock.acquire(blocking=False):
        await asyncio.sleep(0.01)
    try:
        return operation(*args, **kwargs)
    finally:
        lock.release()


async def finish_cleanup(operation: Awaitable[T]) -> T:
    """Drain cleanup despite repeated caller cancellation, then propagate it."""
    cancelled: asyncio.CancelledError | None = None
    # ASGI uses AnyIO level cancellation, which otherwise re-cancels every
    # checkpoint and can starve the cleanup task. Explicit asyncio Task.cancel
    # still reaches this loop and is deferred until the owned work completes.
    with anyio.CancelScope(shield=True):
        task = asyncio.ensure_future(operation)
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError as error:
                if task.cancelled():
                    raise
                cancelled = error
    if cancelled is not None:
        raise cancelled
    return result
