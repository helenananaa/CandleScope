"""Request-local timings for replay work, including actor and worker handoffs."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from concurrent.futures import Executor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import partial
from threading import Lock
from time import perf_counter, thread_time
from typing import Any, TypeVar

T = TypeVar("T")


class RequestTiming:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}
        self.lock = Lock()
        self.active = True

    def add(self, name: str, milliseconds: float) -> None:
        with self.lock:
            if self.active:
                self.values[name] = self.values.get(name, 0.0) + max(0.0, milliseconds)


current_timing: ContextVar[RequestTiming | None] = ContextVar("replay_request_timing", default=None)


@contextmanager
def use_timing(timing: RequestTiming | None) -> Iterator[RequestTiming | None]:
    token = current_timing.set(timing)
    try:
        yield timing
    finally:
        current_timing.reset(token)


@contextmanager
def collect_timings(target: dict[str, float] | None) -> Iterator[None]:
    if target is None:
        yield
        return
    timing = RequestTiming()
    with use_timing(timing):
        try:
            yield
        finally:
            with timing.lock:
                target.update(timing.values)
                timing.active = False


def record_timing(name: str, start: float) -> None:
    timing = current_timing.get()
    if timing is not None:
        timing.add(name, (perf_counter() - start) * 1000)


async def timed_to_thread(name: str, function: Callable[..., T], *args: Any,
                          executor: Executor | None = None, **kwargs: Any) -> T:
    async def dispatch(callback: Callable[[], T]) -> T:
        if executor is None:
            return await asyncio.to_thread(callback)
        context = copy_context()
        return await asyncio.get_running_loop().run_in_executor(executor, context.run, callback)
    timing = current_timing.get()
    if timing is None or not timing.active:
        return await dispatch(partial(function, *args, **kwargs))
    submitted = perf_counter()
    finished: float | None = None

    def work() -> T:
        nonlocal finished
        started = perf_counter()
        cpu = thread_time()
        timing.add(name + "_queue", (started - submitted) * 1000)
        try:
            return function(*args, **kwargs)
        finally:
            finished = perf_counter()
            timing.add(name + "_work", (finished - started) * 1000)
            timing.add(name + "_cpu", (thread_time() - cpu) * 1000)

    try:
        return await dispatch(work)
    finally:
        if finished is not None:
            timing.add(name + "_resume", (perf_counter() - finished) * 1000)
