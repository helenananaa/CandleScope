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
        self._prefix_enabled = evaluator and self.identity.get("prefix_append") == "candlescope.pine-prefix/1"
        self._prefix_state = None
        self.input_bytes = 0
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
        wire_payload = self._prefix_payload(payload) if self._prefix_enabled else payload
        raw = (encoded({**wire_payload, "protocol": PROTOCOL, "identity": self.identity}) + "\n").encode("utf-8")
        self.input_bytes += len(raw)
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

    def _prefix_payload(self, payload):
        bars, accounts, passes = payload.get("bars"), payload.get("accounts"), payload.get("execution_passes")
        clocks = payload.get("execution_times")
        if (not isinstance(bars, list) or not isinstance(accounts, list) or len(bars) != len(accounts)
                or any(payload.get(key) for key in ("libraries", "magnifier"))
                or (clocks is not None and (self.identity.get("prefix_clocks") != "candlescope.pine-prefix-clocks/1"
                    or not isinstance(clocks, list) or len(clocks) != len(bars)))
                or (passes is not None and (self.identity.get("prefix_passes") != "candlescope.pine-prefix-passes/1"
                    or not isinstance(passes, list) or len(passes) != len(bars)))):
            self._prefix_state = None
            return payload
        static = {key: value for key, value in payload.items() if key not in {"bars", "accounts", "execution_passes", "execution_times"}}
        previous = self._prefix_state
        self._prefix_state = (static, list(bars), list(accounts), list(passes) if passes is not None else None,
                              list(clocks) if clocks is not None else None)
        if previous is not None:
            old_static, old_bars, old_accounts, old_passes, old_clocks = previous
            count = len(old_bars)
            stable_passes = passes is None and old_passes is None or (passes is not None and old_passes is not None
                and passes[:count] == old_passes and all(group and group[-1].get("confirmed") is True for group in old_passes))
            stable_clocks = clocks is None and old_clocks is None or (clocks is not None and old_clocks is not None
                and clocks[:count] == old_clocks)
            if (static == old_static and len(bars) > count and bars[:count] == old_bars
                    and accounts[:count] == old_accounts and stable_passes and stable_clocks):
                return {"operation": "append_prefix", "prefix_base": count,
                        "bars": bars[count:], "accounts": accounts[count:],
                        **({"execution_passes": passes[count:]} if passes is not None else {}),
                        **({"execution_times": clocks[count:]} if clocks is not None else {})}
        return payload

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for stream in (self.process.stdin, self.process.stdout, self.stderr):
            if not stream.closed:
                stream.close()
