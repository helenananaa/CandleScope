"""Host-owned persistent worker, with bounded IPC, cancellation and deadlines."""
from __future__ import annotations
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from .native import MAX_BYTES, PROTOCOL, encoded
from .errors import BacktestError


class SessionWorker:
    def __init__(self, plugin, wire, cancelled, *, evaluator=False):
        self.identity = wire["identity"]
        self.stderr = tempfile.TemporaryFile()
        command = [*plugin["command"], "--worker"] if evaluator else [*plugin["command"][:-1], plugin["command"][-1].replace(".native_strategy", ".native_session")]
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            self.stderr.close()
            raise
        self.supported = True if evaluator else self.request({**wire, "operation": "open"}, cancelled).get("supported") is True

    def request(self, payload, cancelled, timeout=120):
        response = queue.Queue(maxsize=1)
        raw = (encoded({**payload, "protocol": PROTOCOL, "identity": self.identity}) + "\n").encode("utf-8")
        if len(raw) > MAX_BYTES:
            self.close()
            raise BacktestError("BUDGET_EXCEEDED", "native session input exceeds 64 MiB")
        def exchange():
            try:
                self.process.stdin.write(raw)
                self.process.stdin.flush()
                line = self.process.stdout.readline(MAX_BYTES + 1)
                if len(line) > MAX_BYTES:
                    raise BacktestError("BUDGET_EXCEEDED", "native session output exceeds 64 MiB")
                response.put(json.loads(line))
            except Exception as exc:
                response.put(exc)
        worker = threading.Thread(target=exchange, daemon=True)
        worker.start()
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancelled.is_set():
                    raise BacktestError("NATIVE_CANCELLED", "native session cancelled")
                if time.monotonic() > deadline:
                    raise BacktestError("NATIVE_TIMEOUT", "native session exceeded host deadline")
                if os.fstat(self.stderr.fileno()).st_size > MAX_BYTES:
                    raise BacktestError("BUDGET_EXCEEDED", "native session stderr exceeds 64 MiB")
                try:
                    result = response.get(timeout=.05)
                except queue.Empty:
                    continue
                if isinstance(result, Exception):
                    raise result
                if not isinstance(result, dict) or result.get("ok") is not True:
                    raise BacktestError("NATIVE_EXECUTION_FAILED", "native session rejected the operation", details=result)
                if result.get("identity") != self.identity:
                    raise BacktestError("NATIVE_IDENTITY_MISMATCH", "unexpected session runtime")
                return result
        except Exception:
            self.close()
            raise
        finally:
            worker.join(timeout=2)

    def advance(self, target, cancelled):
        return self.request({"operation": "advance", "target": target}, cancelled)

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for stream in (self.process.stdin, self.process.stdout, self.stderr):
            if not stream.closed:
                stream.close()
