"""Optional logical-work observer; resource owners still grant actual capacity."""
from contextlib import asynccontextmanager
from contextvars import ContextVar

enabled = ContextVar('resource_admission_enabled', default=False)
observer = ContextVar('resource_wait_observer', default=None)
claim_owner = ContextVar('resource_claim_owner', default=(100, 'anonymous'))


@asynccontextmanager
async def resource_wait(reason):
    current = observer.get()
    if current is None:
        yield
        return
    current.suspend(reason)
    try:
        yield
    except BaseException:
        raise
    else:
        await current.resume()
