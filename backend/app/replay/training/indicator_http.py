"""Stop disposable math work when its HTTP observer leaves; keep durable downloads."""

from __future__ import annotations

import asyncio

from .errors import TrainingRunError


async def compute_for_observer(request, compute):
    task = asyncio.create_task(compute)
    disconnected = False

    async def watch():
        nonlocal disconnected
        while not task.done():
            if await request.is_disconnected():
                disconnected = True
                task.cancel()
                return
            await asyncio.sleep(0.1)

    observer = asyncio.create_task(watch())
    try:
        return await task
    except asyncio.CancelledError:
        # An observer leaving is a normal request outcome after the owned work
        # has drained. Propagating this cancellation to ASGI produces a false
        # server-error traceback. External cancellation (e.g. shutdown) still
        # belongs to the caller and must retain its original control flow.
        owner = asyncio.current_task()
        if disconnected and owner is not None and not owner.cancelling():
            raise TrainingRunError(
                "INDICATOR_OBSERVER_DISCONNECTED",
                "The indicator observer disconnected",
                status_code=499,
            ) from None
        raise
    finally:
        observer.cancel()
        if not task.done():
            task.cancel()
        # The service drains its owned worker and async context reads before
        # completing cancellation. Do not abandon those leases on disconnect.
        await asyncio.gather(observer, task, return_exceptions=True)
