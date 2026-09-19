"""One daemon worker per owner; timed-out work is never reused."""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable


class SerialWorker:
    def __init__(self, name: str) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._gate = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._serve, args=(self._jobs,), name=name, daemon=True
        )
        self._thread.start()

    @staticmethod
    def _serve(jobs: queue.Queue) -> None:
        while True:
            job = jobs.get()
            if job is None:
                return
            invoke, completed = job
            try:
                completed.put((True, invoke()))
            except BaseException as exc:
                completed.put((False, exc))
            finally:
                # Do not retain the last closure/provider while idle.
                del job, invoke, completed

    def call(self, invoke: Callable[[], Any], timeout: float) -> Any:
        if not self._gate.acquire(blocking=False):
            raise RuntimeError("concurrent serial worker call")
        try:
            if self._closed:
                raise RuntimeError("serial worker is closed")
            completed: queue.Queue = queue.Queue(maxsize=1)
            self._jobs.put((invoke, completed))
            try:
                ok, value = completed.get(timeout=timeout)
            except queue.Empty:
                self.close(wait=False)
                raise TimeoutError("serial worker call timed out") from None
            if not ok:
                raise value
            return value
        finally:
            self._gate.release()

    def close(self, *, wait: bool = True) -> None:
        if not self._closed:
            self._closed = True
            self._jobs.put(None)
        if wait and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)
