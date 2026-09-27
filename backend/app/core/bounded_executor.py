"""Thread execution with finite admission and physically removable queued work."""
from __future__ import annotations

import time
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock


class ExecutorBusyError(RuntimeError):
    code = "EXECUTOR_BUSY"

    def __init__(self, name: str):
        self.executor = name
        super().__init__(f"{name} executor is at capacity; retry later")


class BoundedExecutor:
    """At most workers + pending admitted calls, with no admission waiters.

    The underlying pool receives only worker drainers. Logical jobs live in our
    removable queue, so repeated cancellation cannot grow its unbounded queue.
    A running call retains its slot until it physically returns.
    """

    def __init__(self, name: str, *, max_workers: int, max_pending: int):
        if max_workers < 1 or max_pending < 0:
            raise ValueError("Invalid executor capacity")
        self.name, self.max_workers, self.max_pending = name, max_workers, max_pending
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=name)
        self._lock = RLock()
        self._queue = OrderedDict()
        self._drainers = 0
        self._closed = False
        self._counts = dict(submitted=0, started=0, completed=0, failed=0,
                            cancelled=0, rejected=0, active=0)
        self._queue_ms = self._run_ms = self._max_queue_ms = self._max_run_ms = 0.0
        self._slow = deque(maxlen=64)

    def submit(self, function, *, operation: str | None = None) -> Future:
        with self._lock:
            if self._closed:
                raise RuntimeError(f"{self.name} executor is shut down")
            if len(self._queue) + self._counts["active"] >= self.max_workers + self.max_pending:
                self._counts["rejected"] += 1
                raise ExecutorBusyError(self.name)
            self._counts["submitted"] += 1
            sequence = self._counts["submitted"]
            future = Future()
            operation = operation or getattr(function, "__qualname__", type(function).__name__)
            self._queue[sequence] = (future, function, time.perf_counter(), operation)
            future.add_done_callback(lambda done: self._cancelled(sequence, done))
            if self._drainers < self.max_workers:
                self._drainers += 1
                try:
                    self._pool.submit(self._drain)
                except BaseException:
                    self._drainers -= 1
                    future.cancel()
                    raise
            return future

    def _cancelled(self, sequence, future):
        if future.cancelled():
            with self._lock:
                self._queue.pop(sequence, None)
                self._counts["cancelled"] += 1

    def _drain(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._drainers -= 1
                    return
                sequence, (future, function, submitted_at, operation) = self._queue.popitem(last=False)
                if not future.set_running_or_notify_cancel():
                    continue
                started_at = time.perf_counter()
                wait_ms = (started_at - submitted_at) * 1000
                self._counts["started"] += 1
                self._counts["active"] += 1
                self._queue_ms += wait_ms
                self._max_queue_ms = max(self._max_queue_ms, wait_ms)
            error = None
            result = None
            try:
                result = function()
            except BaseException as exc:
                error = exc
            run_ms = (time.perf_counter() - started_at) * 1000
            with self._lock:
                self._counts["active"] -= 1
                self._counts["completed"] += 1
                self._counts["failed"] += int(error is not None)
                self._run_ms += run_ms
                self._max_run_ms = max(self._max_run_ms, run_ms)
                if run_ms >= 20 or wait_ms >= 20:
                    self._slow.append(dict(sequence=sequence, operation=operation,
                                           queue_wait_ms=round(wait_ms, 2), run_ms=round(run_ms, 2),
                                           failed=error is not None))
            if error is None:
                future.set_result(result)
            else:
                future.set_exception(error)

    def snapshot(self):
        with self._lock:
            return dict(
                name=self.name, max_workers=self.max_workers, max_pending=self.max_pending,
                max_inflight=self.max_workers + self.max_pending, **self._counts,
                pending=len(self._queue), queued=len(self._queue),
                avg_queue_wait_ms=round(self._queue_ms / max(1, self._counts["started"]), 2),
                max_queue_wait_ms=round(self._max_queue_ms, 2),
                avg_run_ms=round(self._run_ms / max(1, self._counts["completed"]), 2),
                max_run_ms=round(self._max_run_ms, 2), recent_slow_operations=list(self._slow),
            )

    def shutdown(self, *, wait=True, cancel_futures=False):
        with self._lock:
            self._closed = True
            if cancel_futures:
                for future, *_ in list(self._queue.values()):
                    future.cancel()
        self._pool.shutdown(wait=wait)
