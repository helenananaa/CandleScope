"""Supervised whole-run BAR worker for built-ins and trusted Python only."""

from __future__ import annotations

import multiprocessing
import os
import threading
import sys
import time
from pathlib import Path
from dataclasses import fields, replace

from app.core.config import getenv
from .errors import BacktestError
from .strategy.isolated import IsolatedStrategyProvider
from .strategy.python_provider import PythonHostProvider


def provider_spec(provider):
    if getenv("BACKTEST_COLOCATED_BAR_ENABLED", "1").strip() != "1":
        return None
    if type(provider) is IsolatedStrategyProvider and provider._process is None and not provider._terminated:
        return {"kind": "builtin", "revision": provider._revision_id,
                "call_timeout": provider._step_timeout_s}
    if type(provider) is PythonHostProvider and provider.runner.mode == "TRUSTED_LOCAL" and provider.runner._process is None:
        return {"kind": "python", "bundle": provider.bundle_dir.resolve(),
                "entrypoint": provider.entrypoint, "parameters": provider.parameters,
                "call_timeout": provider.runner.step_timeout_s,
                "bound_transcript": provider.runner._bound_transcript}
    return None


class _GuardedProvider:
    """Publish deadlines in shared memory, without a per-call IPC exchange."""
    def __init__(self, provider, deadline, step_timeout, call_timeout):
        self.provider = provider
        self.deadline = deadline
        self.step_timeout = step_timeout
        self.call_timeout = call_timeout

    def __getattr__(self, name):
        method = getattr(self.provider, name)
        if not callable(method):
            return method
        def invoke(*args, **kwargs):
            timeout = (min(self.step_timeout, self.call_timeout) if name in {"step", "warmup"}
                       else self.call_timeout if name == "on_execution_report" else 5.0)
            self.deadline.value = time.monotonic() + timeout
            try:
                return method(*args, **kwargs)
            finally:
                self.deadline.value = 0.0
        return invoke


def _worker(connection, settings, run_id, spec, events, options, call_deadline, log_fd=None):
    from .service import BacktestService
    from .strategy.chart_pyne import CHART_PYNE_REVISION, ChartPyneStrategyProvider
    from .strategy.pine_adapter import PineStrategyProvider
    from .strategy.registry import build_default_strategy_registry
    from .strategy.local_python import LocalPythonRunner

    service = None
    working_directory = Path.cwd()
    stdout, stderr = sys.stdout, sys.stderr
    try:
        if log_fd is not None:
            os.dup2(log_fd, 1)
            os.dup2(log_fd, 2)
            os.close(log_fd)
            sys.stdout = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
            sys.stderr = os.fdopen(os.dup(2), "w", buffering=1, encoding="utf-8")
        service = BacktestService.start(settings)
        service._colocated_worker = True
        if spec["kind"] == "python":
            from .strategy.python_runner import SDK_SRC
            sys.path.insert(0, str(SDK_SRC))
            # Relative file access has always been rooted in the immutable bundle.
            os.chdir(spec["bundle"])
            provider = PythonHostProvider.__new__(PythonHostProvider)
            provider.bundle_dir = spec["bundle"]
            provider.entrypoint = spec["entrypoint"]
            provider.parameters = spec["parameters"]
            provider.runner = LocalPythonRunner(bound_transcript=spec["bound_transcript"])
        else:
            revision = spec["revision"]
            provider = (ChartPyneStrategyProvider() if revision == CHART_PYNE_REVISION
                        else PineStrategyProvider() if revision == "pine-long-flat-v1"
                        else build_default_strategy_registry().build(revision))
        guarded = _GuardedProvider(provider, call_deadline, settings.provider_step_timeout_ms / 1000,
                                   spec["call_timeout"])
        call_deadline.value = 0.0
        completed = service.execute_bar_run(run_id, events=events, provider=guarded, **options)
        completed["execution_lane"] = "COLOCATED_BAR_V1"
        completed["worker_python"] = sys.executable
        connection.send(("ok", completed))
    except BaseException as exc:
        connection.send(("error", (getattr(exc, "code", "PROVIDER_CRASH_UNRECOVERABLE"), str(exc))))
    finally:
        if log_fd is not None:
            sys.stdout.close()
            sys.stderr.close()
        sys.stdout, sys.stderr = stdout, stderr
        if service is not None:
            service.shutdown()
        os.chdir(working_directory)
        connection.close()


def execute(service, run_id, spec, events, options):
    from .worker_stdio import SpawnWriter
    from .strategy.python_runner import MAX_STDERR_BYTES

    context = multiprocessing.get_context("spawn")
    settings = replace(service.settings, **{
        item.name: getattr(service.settings, item.name).resolve()
        for item in fields(service.settings)
        if isinstance(getattr(service.settings, item.name), Path)
    })
    parent, child = context.Pipe(duplex=False)
    deadline = context.RawValue("d", time.monotonic() + 15.0)
    read_fd, write_fd = os.pipe()
    overflow = threading.Event()
    reader = None
    process = context.Process(target=_worker, args=(
        child, settings, run_id, spec, events, options, deadline, SpawnWriter(write_fd),
    ), name=f"backtest-run-{run_id}", daemon=True)
    generation = int(service.get_run(run_id)["generation"])
    overall_deadline = time.monotonic() + service.settings.max_run_seconds
    try:
        process.start()
        child.close()
        os.close(write_fd)
        write_fd = None
        def drain():
            size = 0
            try:
                while chunk := os.read(read_fd, 16384):
                    size += len(chunk)
                    if size > MAX_STDERR_BYTES:
                        overflow.set()
                        return
            except OSError:
                return
        reader = threading.Thread(target=drain, name="backtest-run-stderr", daemon=True)
        reader.start()
        while True:
            if overflow.is_set():
                raise BacktestError("STDERR_TOO_LARGE", "worker stderr exceeded budget")
            if parent.poll(.05):
                status, result = parent.recv()
                if status == "ok":
                    if overflow.is_set():
                        raise BacktestError("STDERR_TOO_LARGE", "worker stderr exceeded budget")
                    return result
                raise BacktestError(*result)
            current = service.repository.get_run_by_id(run_id)
            if current is None or int(current["generation"]) != generation or current["state"] in {"CANCELLED", "CANCELLING"}:
                raise BacktestError("IDENTITY_MUTATION", "backtest run was cancelled or superseded")
            now = time.monotonic()
            call_limit = deadline.value
            if call_limit and now > call_limit:
                raise BacktestError("PROVIDER_TIMEOUT", "whole-run worker provider call exceeded budget")
            if now > overall_deadline:
                raise BacktestError("BUDGET_EXCEEDED", "backtest run exceeded time ceiling")
            if not process.is_alive():
                raise BacktestError("PROVIDER_CRASH_UNRECOVERABLE", "whole-run worker exited without a result")
    except BaseException as exc:
        if process.pid is not None and process.is_alive():
            process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join(2)
        if not isinstance(exc, Exception):
            # Preserve the runtime's interruption/requeue path.
            raise
        error = exc if isinstance(exc, BacktestError) else BacktestError("PROVIDER_CRASH_UNRECOVERABLE", str(exc))
        current = service.repository.get_run_by_id(run_id)
        if current is not None and current["state"] == "QUEUED":
            service.fail_queued_run(run_id, error, now_ms=options.get("now_ms"),
                                    expected_generation=generation)
        service._mark_failed(run_id, options.get("now_ms") or int(time.time()*1000), error, expected_generation=generation)
        if error is exc:
            raise
        raise error from exc
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            process.join(2)
            if process.is_alive():
                process.terminate()
                process.join(2)
            process.close()
        if reader is not None:
            reader.join(2)
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
