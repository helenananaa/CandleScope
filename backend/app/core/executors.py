"""Dedicated, bounded executors for blocking work owned by async paths."""
from __future__ import annotations

import asyncio
import functools
from contextvars import copy_context
from collections.abc import Callable
from typing import Any, TypeVar

from app.core import config
from app.core.bounded_executor import BoundedExecutor

T = TypeVar("T")


def _pool(name: str, workers: int, pending: int) -> BoundedExecutor:
    return BoundedExecutor(name, max_workers=max(1, workers), max_pending=max(0, pending))


_indicator_executor = _pool("indicator", config.INDICATOR_THREAD_WORKERS, config.INDICATOR_THREAD_PENDING)
_pyne_wait_executor = _pool("pyne_wait", config.PYNE_HTTP_THREAD_WORKERS, config.PYNE_HTTP_THREAD_PENDING)
_storage_executor = _pool("storage", config.STORAGE_THREAD_WORKERS, config.STORAGE_THREAD_PENDING)
_preparation_executor = _pool("preparation", config.PREPARATION_THREAD_WORKERS, config.PREPARATION_THREAD_PENDING)


async def _run(
    executor: BoundedExecutor,
    func: Callable[..., T],
    *args: Any,
    drain_on_cancel: bool = False,
    **kwargs: Any,
) -> T:
    target = args[0] if operation_is_dispatch_wrapper(func, args) else func
    operation = str(getattr(target, "__qualname__", None) or getattr(target, "__name__", None) or type(target).__name__)
    context = copy_context()
    physical = executor.submit(functools.partial(context.run, func, *args, **kwargs), operation=operation)
    future = asyncio.wrap_future(physical)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        # Retract queued work. A thread already executing a transaction cannot
        # be killed: retain its capacity and, for storage, its caller's ownership.
        cancelled_before_start = physical.cancel()
        if drain_on_cancel and not cancelled_before_start:
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
        def consume(done):
            if not done.cancelled():
                done.exception()
        future.add_done_callback(consume)
        raise


def operation_is_dispatch_wrapper(func: Callable[..., Any], args: tuple[Any, ...]) -> bool:
    """Expose the wrapped callable name for generic API compatibility shims."""
    return bool(args and callable(args[0]) and getattr(func, "__name__", "") == "_call_data_manager_method")


async def run_indicator(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await _run(_indicator_executor, func, *args, **kwargs)


async def run_pyne_wait(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await _run(_pyne_wait_executor, func, *args, **kwargs)


async def run_storage(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await _run(_storage_executor, func, *args, drain_on_cancel=True, **kwargs)


async def run_preparation(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await _run(_preparation_executor, func, *args, drain_on_cancel=True, **kwargs)


def executors_snapshot() -> dict[str, Any]:
    return {pool.name: pool.snapshot() for pool in
            (_indicator_executor, _preparation_executor, _pyne_wait_executor, _storage_executor)}
