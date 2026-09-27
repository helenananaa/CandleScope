"""Preparation I/O has a separate bounded lane from live market storage."""
import asyncio

from app.core.executors import run_preparation


async def storage_call(function, *args, **kwargs):
    """Drain running writes, including repeated cancellation, before returning."""
    return await run_preparation(function, *args, **kwargs)


async def finish_before_cancel(task):
    """A lifecycle/ownership cleanup task must finish even if its waiter leaves."""
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if not task.cancelled():
            task.exception()
        raise
