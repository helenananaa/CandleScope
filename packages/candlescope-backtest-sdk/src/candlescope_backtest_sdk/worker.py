"""User-strategy JSONL worker. Stdout is protocol only."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

if __name__ == "__main__" and len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])

from candlescope_backtest_sdk import (
    Observation,
    StrategyContext,
    encode_output,
    encode_snapshot,
    loads_strict,
)


def _load_strategy(bundle_dir: Path, entrypoint: str) -> Any:
    module_name, _, class_name = entrypoint.partition(":")
    source = bundle_dir / "strategy.py"
    spec = importlib.util.spec_from_file_location(module_name or "strategy", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load strategy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name or "Strategy")()


_PROTOCOL = sys.stdout
_STDERR_LIMIT = 64 * 1024
_LOG = None


class _BoundedLogBuffer:
    """Bound SDK log writes before a reply can overtake the host's drainer."""

    def __init__(self, stream):
        self.stream = stream
        self.sent = 0
        self.overflow = False
        self.lock = threading.Lock()

    def write(self, value):
        data = bytes(value)
        with self.lock:
            remaining = max(0, _STDERR_LIMIT + 1 - self.sent)
            if len(data) > _STDERR_LIMIT - self.sent:
                self.overflow = True
            # One excess byte also activates the independent host pipe guard.
            chunk = data[:remaining]
            if chunk:
                self.stream.write(chunk)
                self.sent += len(chunk)
        return len(data)

    def flush(self):
        self.stream.flush()

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _BoundedLog:
    def __init__(self, stream):
        self.stream = stream
        self.buffer = _BoundedLogBuffer(stream.buffer)

    def write(self, value):
        self.buffer.write(value.encode("utf-8"))
        return len(value)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        self.buffer.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _write(message: dict[str, Any]) -> bool:
    if _LOG is not None:
        _LOG.flush()
        if _LOG.buffer.overflow:
            message = {"id": message.get("id"), "ok": False,
                       "errorCode": "STDERR_TOO_LARGE", "error": "worker stderr exceeded budget"}
    _PROTOCOL.write(json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n")
    _PROTOCOL.flush()
    return _LOG is None or not _LOG.buffer.overflow


def _observe(strategy: Any, method: str, params: dict[str, Any]) -> Any:
    assert strategy is not None
    observation = Observation.from_wire(params["observation"])
    if method == "warmup":
        strategy.warmup(observation)
        return None
    output = strategy.step(observation)
    return None if output is None else encode_output(observation.sequence, output)


def _step_batch(strategy: Any, params: dict[str, Any]) -> None:
    """Consecutive warmup/step requests, one reply line each, as if sent singly.

    Stops after a result, an error or a step slower than the per-call budget;
    the host times out a single call at that budget and kills the worker.
    """
    budget = int(params["stepTimeoutMs"]) / 1000
    for item in params["requests"]:
        started = time.monotonic()
        error = None
        try:
            method = str(item.get("method") or "")
            if method not in {"warmup", "step"}:
                raise ValueError(f"unknown method {method}")
            result = _observe(strategy, method, item.get("params") or {})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            error = str(exc)
        if time.monotonic() - started > budget:
            _write({"id": item.get("id"), "ok": False, "late": True})
            return
        if error is not None:
            _write({"id": item.get("id"), "ok": False, "error": error})
            return
        if not _write({"id": item.get("id"), "ok": True, "result": result}):
            return
        if result is not None:
            return


def main() -> int:
    global _LOG
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    _LOG = _BoundedLog(sys.stderr)
    sys.stdout = sys.stderr = _LOG
    strategy = None
    for raw in sys.stdin:
        try:
            request = loads_strict(raw.encode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            request_id = request.get("id")
            method = str(request.get("method") or "")
            params = request.get("params") or {}
            if method == "step_batch":
                _step_batch(strategy, params)
                if _LOG.buffer.overflow:
                    return 0
                continue
            if method == "ping":
                result = {"ready": True}
            elif method == "prepare":
                bundle_dir = Path(str(params["bundleDir"]))
                strategy = _load_strategy(bundle_dir, str(params["entrypoint"]))
                strategy.prepare(
                    StrategyContext(
                        run_id=str(params.get("runId") or "bt_local"),
                        revision_id=str(params.get("revisionId") or "rev_local"),
                        parameters=dict(params.get("parameters") or {}),
                    )
                )
                result: Any = {"ok": True}
            elif method in {"warmup", "step"}:
                result = _observe(strategy, method, params)
            elif method == "on_execution_report":
                assert strategy is not None
                strategy.on_execution_report(params["report"])
                result = None
            elif method == "snapshot":
                assert strategy is not None
                result = encode_snapshot(strategy.snapshot())
            elif method == "restore":
                assert strategy is not None
                strategy.restore(dict(params["payload"]))
                result = None
            elif method == "close":
                if strategy is not None:
                    strategy.close()
                result = {"closed": True}
            else:
                raise ValueError(f"unknown method {method}")
            accepted = _write({"id": request_id, "ok": True, "result": result})
            if method == "close" or not accepted:
                return 0
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            if not _write({"id": request.get("id") if isinstance(request, dict) else None, "ok": False, "error": str(exc)}):
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
