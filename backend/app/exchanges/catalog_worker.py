"""Out-of-process loader for large exchange symbol catalogs.

One CCXT ``load_markets()`` for Binance spot parses a ~18 MB exchangeInfo
document and builds thousands of nested market dicts.  That is ~3 s of CPU,
and because the JSON decoder and the full GC passes that follow hold the GIL,
it stalls the event loop for 1-4 s even when run on a worker thread.

This module runs such loaders in one lazily spawned child process and sends
back only the compact catalog rows, in chunks small enough that unpickling a
chunk never holds the parent's GIL for long.  The child is shared by every
loader, handles requests concurrently on its own event loop, exits after
``SYMBOL_CATALOG_WORKER_IDLE_SECONDS`` without work, and is stopped by
:func:`shutdown_catalog_worker`.  It also exits when the parent's request pipe
closes, so it cannot outlive a crashed backend.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import itertools
import logging
import multiprocessing
import pickle
import signal
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core import config as app_config

logger = logging.getLogger("candlescope.catalog_worker")

# Rows per result message.  Each chunk is unpickled on the parent's reader
# thread while it holds the GIL; 256 catalog rows take about a millisecond.
_ROW_CHUNK = 256
# A cold child imports CCXT before it reports ready; on a busy Windows machine
# that has taken over 20 s.
_READY_TIMEOUT_SECONDS = 90.0
# After a start failure or crash, callers load inline for this long instead of
# respawning a worker on every catalog request.
_RESTART_COOLDOWN_SECONDS = 300.0
_EXIT_GRACE_SECONDS = 3.0


class CatalogWorkerUnavailable(RuntimeError):
    """The worker process could not run a request; callers may load inline."""


class CatalogWorkerError(RuntimeError):
    """A loader failed in the worker with an exception that cannot be rebuilt."""

    def __init__(self, type_name: str, message: str) -> None:
        super().__init__(f"{type_name}: {message}")
        self.type_name = type_name


def catalog_worker_enabled() -> bool:
    return bool(app_config.SYMBOL_CATALOG_WORKER_ENABLED)


async def run_catalog_loader(
    function: Callable[..., Awaitable[list[Any]]],
    *args: Any,
) -> list[Any]:
    """Await ``function(*args)`` in the catalog worker and return its rows.

    ``function`` must be a module-level coroutine function, and its arguments
    and returned list items must pickle.  Loader exceptions are re-raised
    here.  Raises :class:`CatalogWorkerUnavailable` when the worker cannot
    start or exits mid-request.
    """

    return await _worker.run(function, args)


async def shutdown_catalog_worker() -> None:
    """Stop the worker process; a later request starts a new one."""

    await _worker.shutdown()


# ── Parent side ──────────────────────────────────────────────


@dataclass(eq=False)
class _Request:
    future: asyncio.Future[list[Any]]
    rows: list[Any] = field(default_factory=list)


@dataclass(eq=False)
class _Generation:
    """One worker process and the parent's ends of its two pipes."""

    loop: asyncio.AbstractEventLoop
    process: Any
    requests: Any
    results: Any
    ready: asyncio.Future[None]
    pending: dict[int, _Request] = field(default_factory=dict)
    reader: threading.Thread | None = None
    reaper: threading.Thread | None = None
    retired: bool = False


class _CatalogWorker:
    # Every method runs on the event loop thread, except ``_read`` (the result
    # reader thread) and ``_reap`` (a short-lived joiner thread).

    def __init__(self) -> None:
        self._generation: _Generation | None = None
        self._generations: set[_Generation] = set()
        self._starting: asyncio.Task[_Generation] | None = None
        self._restart_at = 0.0
        self._closing = False
        self._ids = itertools.count(1)
        self._idle_handle: asyncio.TimerHandle | None = None

    async def run(
        self,
        function: Callable[..., Awaitable[list[Any]]],
        args: tuple[Any, ...],
    ) -> list[Any]:
        generation = await self._ready_generation(function.__module__)
        self._cancel_idle()
        request_id = next(self._ids)
        request = _Request(generation.loop.create_future())
        generation.pending[request_id] = request
        try:
            try:
                # Requests are a few KB and the child drains its pipe on a
                # dedicated thread, so this write does not wait on the child.
                generation.requests.send(("load", request_id, function, args))
            except (EOFError, OSError) as exc:
                self._retire(generation, f"catalog worker pipe failed: {exc}")
                raise CatalogWorkerUnavailable(str(exc)) from exc
            except Exception as exc:
                raise CatalogWorkerUnavailable(
                    f"catalog request cannot be sent to the worker: {exc}"
                ) from exc
            try:
                return await request.future
            except asyncio.CancelledError:
                # Cancelling this task also cancels the Future it awaited.
                # Its done state does not mean the child loader has stopped.
                if not generation.retired:
                    with contextlib.suppress(EOFError, OSError):
                        generation.requests.send(("cancel", request_id))
                raise
        finally:
            generation.pending.pop(request_id, None)
            self._arm_idle(generation)

    async def _ready_generation(self, preload: str) -> _Generation:
        if self._closing:
            raise CatalogWorkerUnavailable("catalog worker is shutting down")
        loop = asyncio.get_running_loop()
        generation = self._generation
        if generation is not None and generation.loop is not loop:
            # Futures cannot cross event loops (tests run several in turn).
            self._retire(generation, "event loop changed")
            generation = None
        if generation is not None:
            return generation
        starting = self._starting
        if starting is not None and starting.get_loop() is not loop:
            starting = None
        if starting is None:
            if time.monotonic() < self._restart_at:
                raise CatalogWorkerUnavailable(
                    "catalog worker failed recently; loading inline until "
                    "its restart cooldown ends"
                )
            starting = loop.create_task(
                self._start(loop, preload),
                name="catalog-worker-start",
            )
            starting.add_done_callback(_consume_outcome)
            self._starting = starting
        # Callers may time out; the start itself is never cancelled, so a
        # spawned process is always either published or reaped.
        return await asyncio.shield(starting)

    async def _start(
        self,
        loop: asyncio.AbstractEventLoop,
        preload: str,
    ) -> _Generation:
        try:
            try:
                process, requests, results = await asyncio.to_thread(
                    _spawn_worker,
                    (preload,),
                )
            except Exception as exc:
                self._start_failed(f"catalog worker could not start: {exc}")
                raise CatalogWorkerUnavailable(str(exc)) from exc
            generation = _Generation(
                loop=loop,
                process=process,
                requests=requests,
                results=results,
                ready=loop.create_future(),
            )
            self._prune()
            self._generations.add(generation)
            generation.reader = threading.Thread(
                target=self._read,
                args=(generation,),
                name="catalog-worker-results",
                daemon=True,
            )
            generation.reader.start()
            if self._closing:
                self._retire(generation, "catalog worker is shutting down")
            try:
                async with asyncio.timeout(_READY_TIMEOUT_SECONDS):
                    await generation.ready
            except asyncio.CancelledError:
                self._retire(generation, "catalog worker start cancelled")
                raise
            except Exception as exc:
                self._retire(generation, "catalog worker did not become ready")
                if not self._closing:
                    self._start_failed(f"catalog worker did not become ready: {exc!r}")
                if isinstance(exc, CatalogWorkerUnavailable):
                    raise
                raise CatalogWorkerUnavailable(repr(exc)) from exc
            self._generation = generation
            return generation
        finally:
            if self._starting is asyncio.current_task():
                self._starting = None

    def _start_failed(self, reason: str) -> None:
        self._restart_at = time.monotonic() + _RESTART_COOLDOWN_SECONDS
        logger.warning(
            "%s; loading symbol catalogs inline for %.0f s",
            reason,
            _RESTART_COOLDOWN_SECONDS,
        )

    def _read(self, generation: _Generation) -> None:
        """Forward worker messages to the loop until the worker exits."""

        deliver = True
        while True:
            try:
                message = generation.results.recv()
            except (EOFError, OSError):
                break
            except Exception as exc:  # noqa: BLE001 - retire the transport on any decode failure
                message = ("lost", f"unreadable catalog worker message: {exc!r}")
            if not deliver:
                continue
            try:
                generation.loop.call_soon_threadsafe(self._deliver, generation, message)
            except RuntimeError:
                # The owning loop closed under a live worker.  Close its
                # request pipe so it exits, and keep draining until it does.
                deliver = False
                with contextlib.suppress(OSError):
                    generation.requests.close()
        with contextlib.suppress(OSError):
            generation.results.close()
        if deliver:
            with contextlib.suppress(RuntimeError):
                generation.loop.call_soon_threadsafe(self._exited, generation)

    def _deliver(self, generation: _Generation, message: tuple[Any, ...]) -> None:
        kind = message[0]
        if kind == "ready":
            if not generation.ready.done():
                generation.ready.set_result(None)
            return
        if kind == "lost":
            logger.warning("%s", message[1])
            self._retire(generation, message[1])
            return
        request = generation.pending.get(message[1])
        if request is None or request.future.done():
            return
        if kind == "rows":
            request.rows.extend(message[2])
        elif kind == "done":
            request.future.set_result(request.rows)
        elif kind == "error":
            request.future.set_exception(_decode_error(*message[2]))

    def _exited(self, generation: _Generation) -> None:
        if generation.retired:
            return
        exit_code = generation.process.exitcode
        if generation.ready.done():
            # Crashed while serving.  Back off before respawning, in case the
            # crash is deterministic (an import error, an OOM-sized catalog).
            self._start_failed(f"catalog worker exited unexpectedly (code {exit_code})")
        self._retire(generation, f"catalog worker exited (code {exit_code})")

    def _retire(self, generation: _Generation, reason: str) -> None:
        if generation.retired:
            return
        generation.retired = True
        if self._generation is generation:
            self._generation = None
            self._cancel_idle()
        # The child exits when its request pipe reaches EOF.
        with contextlib.suppress(OSError):
            generation.requests.close()
        # A future of an already closed loop (tests) cannot run callbacks.
        with contextlib.suppress(RuntimeError):
            if not generation.ready.done():
                generation.ready.set_exception(CatalogWorkerUnavailable(reason))
            for request in generation.pending.values():
                if not request.future.done():
                    request.future.set_exception(CatalogWorkerUnavailable(reason))
        generation.pending.clear()
        generation.reaper = threading.Thread(
            target=_reap,
            args=(generation,),
            name="catalog-worker-reaper",
            daemon=True,
        )
        generation.reaper.start()

    def _arm_idle(self, generation: _Generation) -> None:
        idle_seconds = float(app_config.SYMBOL_CATALOG_WORKER_IDLE_SECONDS)
        if (
            generation is not self._generation
            or generation.pending
            or idle_seconds <= 0
        ):
            return
        self._cancel_idle()
        self._idle_handle = generation.loop.call_later(
            idle_seconds,
            self._idle_expired,
            generation,
        )

    def _idle_expired(self, generation: _Generation) -> None:
        self._idle_handle = None
        if generation is self._generation and not generation.pending:
            self._retire(generation, "catalog worker idle")

    def _cancel_idle(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    async def shutdown(self) -> None:
        self._closing = True
        try:
            for generation in list(self._generations):
                self._retire(generation, "catalog worker shut down")
            starting = self._starting
            if (
                starting is not None
                and not starting.done()
                and starting.get_loop() is asyncio.get_running_loop()
            ):
                # Its spawn finishes quickly, then it sees ``_closing``.
                await asyncio.wait({starting}, timeout=_READY_TIMEOUT_SECONDS)
            for generation in list(self._generations):
                self._retire(generation, "catalog worker shut down")
            reapers = [
                generation.reaper
                for generation in self._generations
                if generation.reaper is not None
            ]
            if reapers:
                await asyncio.to_thread(_join_threads, reapers)
            self._prune()
        finally:
            self._closing = False

    def _prune(self) -> None:
        self._generations = {
            generation
            for generation in self._generations
            if generation.reaper is None or generation.reaper.is_alive()
        }


_worker = _CatalogWorker()


def _spawn_worker(preload: tuple[str, ...]) -> tuple[Any, Any, Any]:
    context = multiprocessing.get_context("spawn")
    request_reader, request_writer = context.Pipe(duplex=False)
    result_reader, result_writer = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_main,
        args=(request_reader, result_writer, preload),
        name="candlescope-catalog-worker",
        daemon=True,
    )
    try:
        process.start()
    except BaseException:
        request_writer.close()
        result_reader.close()
        raise
    finally:
        # Only the child may hold these ends, or neither side would see EOF.
        request_reader.close()
        result_writer.close()
    return process, request_writer, result_reader


def _reap(generation: _Generation) -> None:
    process = generation.process
    process.join(_EXIT_GRACE_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(2.0)
    if process.is_alive():
        process.kill()
        process.join(2.0)
    if generation.reader is not None:
        generation.reader.join(2.0)
    if not process.is_alive():
        with contextlib.suppress(ValueError):
            process.close()


def _join_threads(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.join(_EXIT_GRACE_SECONDS + 5.0)


def _consume_outcome(task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(BaseException):
        task.exception()


def _decode_error(type_name: str, message: str, payload: bytes | None) -> BaseException:
    if payload is not None:
        with contextlib.suppress(Exception):
            error = pickle.loads(payload)
            if isinstance(error, Exception):
                return error
    return CatalogWorkerError(type_name, message)


# ── Child side ───────────────────────────────────────────────


def _worker_main(requests: Any, results: Any, preload: tuple[str, ...]) -> None:
    # Ctrl+C in a shared console is the parent's to handle; the worker exits
    # once the parent closes its request pipe.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    for module in preload:
        importlib.import_module(module)
    asyncio.run(_serve(requests, results))


async def _serve(requests: Any, results: Any) -> None:
    loop = asyncio.get_running_loop()
    inbox: asyncio.Queue[tuple[Any, ...] | None] = asyncio.Queue()

    def receive() -> None:
        try:
            while True:
                message = requests.recv()
                loop.call_soon_threadsafe(inbox.put_nowait, message)
        except (EOFError, OSError):
            pass
        finally:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(inbox.put_nowait, None)

    threading.Thread(target=receive, name="catalog-worker-requests", daemon=True).start()
    results.send(("ready",))
    running: dict[int, asyncio.Task[None]] = {}
    while (message := await inbox.get()) is not None:
        kind, request_id = message[0], message[1]
        if kind == "load":
            task = asyncio.create_task(
                _answer(results, request_id, message[2], message[3]),
            )
            running[request_id] = task
            task.add_done_callback(
                lambda _task, key=request_id: running.pop(key, None),
            )
        elif kind == "cancel" and (task := running.get(request_id)) is not None:
            task.cancel()
    for task in list(running.values()):
        task.cancel()
    await asyncio.gather(*running.values(), return_exceptions=True)


async def _answer(
    results: Any,
    request_id: int,
    function: Callable[..., Awaitable[list[Any]]],
    args: tuple[Any, ...],
) -> None:
    try:
        rows = list(await function(*args))
    except asyncio.CancelledError:
        return
    except Exception as exc:  # noqa: BLE001 - preserve arbitrary loader errors across the process boundary
        results.send(("error", request_id, _encode_error(exc)))
        return
    for start in range(0, len(rows), _ROW_CHUNK):
        results.send(("rows", request_id, rows[start:start + _ROW_CHUNK]))
    results.send(("done", request_id))


def _encode_error(exc: Exception) -> tuple[str, str, bytes | None]:
    payload: bytes | None
    try:
        payload = pickle.dumps(exc)
        # Both processes run the same code, so a local round trip predicts
        # whether the parent can rebuild the exception.
        pickle.loads(payload)
    except Exception:  # noqa: BLE001 - unknown exception types may not support a pickle round trip
        payload = None
    return type(exc).__name__, str(exc), payload
