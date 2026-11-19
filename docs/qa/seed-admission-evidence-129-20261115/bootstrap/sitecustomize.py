"""Diagnostic-only bounded admission/lifecycle tracing; no policy changes."""
import asyncio
from collections import Counter
import functools
import importlib
import json
import os
from pathlib import Path
import sys
import time

_counts = Counter()
_patched = False


def emit(kind, **values):
    try:
        if _counts[kind] >= 256 or sum(_counts.values()) >= 1024:
            return
        data = os.environ.get("CANDLE_DATA_DIR")
        if not data:
            return
        _counts[kind] += 1
        path = Path(data).parents[1] / "admission-lifecycle-trace.jsonl"
        entry = dict(kind=kind, at_ms=int(time.time() * 1000), pid=os.getpid(), **values)
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (json.dumps(entry, default=str) + "\n").encode())
        finally:
            os.close(descriptor)
    except Exception:
        pass  # Diagnostic failure must not change product behavior.


def resource_info(resource):
    result = {"type": type(resource).__name__ if resource is not None else None}
    # Only this known availability view has pure business-state reads.
    if type(resource).__name__ != "_DeferredSeriesLane":
        return result
    result["available"] = resource.available()
    state = resource.series.get(resource.key)
    result["series"] = resource.key
    result["series_active"] = state.active if state else None
    for cell in resource.capacity_available.__closure__ or ():
        owner = cell.cell_contents
        if hasattr(owner, "_tasks") and hasattr(owner, "_chunks"):
            result["running"] = len(owner._tasks)
            result["max_concurrency"] = owner._max_concurrency
            result["jobs"] = [
                {"interval": chunk.request.interval, "reason": chunk.request.reason,
                 "parent": chunk.parent_id}
                for key in list(owner._tasks)[:8]
                if (chunk := owner._chunks.get(key)) is not None
            ]
    return result


def streams(owner):
    coordinator = getattr(owner, "coordinator", owner)
    entries = getattr(coordinator, "_streams", {})
    leases = getattr(owner, "_stream_leases", {})
    return dict(streams=len(entries), leases=len(leases),
        lease_sample=[{"key": str(key), "consumers": len(value.consumers)}
                      for key, value in list(leases.items())[:8]],
        stream_sample=[{"key": str(key), "status": value.info.status.value}
                       for key, value in list(entries.items())[:8]])


def safe_streams(owner):
    try:
        return streams(owner)
    except Exception as exc:
        return {"diagnostic_error": type(exc).__name__}


def lifecycle(cls, name):
    original = getattr(cls, name)

    @functools.wraps(original)
    async def wrapped(self, *args, **kwargs):
        before = safe_streams(self)
        result = error = None
        try:
            result = await original(self, *args, **kwargs)
            return result
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            try:
                emit("stream-lifecycle", owner=cls.__name__, method=name,
                     arguments=[str(value)[:256] for value in args[:2]],
                     focus_scope=kwargs.get("focus_scope"),
                     subscription_tier=kwargs.get("subscription_tier"),
                     status=getattr(getattr(result, "status", None), "value", None),
                     error=error, before=before, after=safe_streams(self))
            except Exception:
                pass

    setattr(cls, name, wrapped)


def patch():
    global _patched
    if _patched:
        return
    try:
        module = importlib.import_module("app.exchanges.public_admission")
        admission = module.PublicAdmission
        original = admission._protects

        @functools.wraps(original)
        async def protects(self, other, current):
            result = await original(self, other, current)
            if result:
                try:
                    emit("priority-block", current_owner=current.demand.owner,
                         current_purpose=current.demand.purpose,
                         current_rank=self._rank(current),
                         blocking_owner=other.demand.owner,
                         blocking_purpose=other.demand.purpose,
                         blocking_rank=self._rank(other),
                         protected=self._protected.get(other.demand) is other,
                         resource=resource_info(other.resource),
                         buckets=sorted(other.keys & current.keys))
                except Exception:
                    pass
            return result

        admission._protects = protects
        manager = importlib.import_module("app.data_engine.data_manager.manager").DataManager
        coordinator = importlib.import_module("app.data_engine.data_manager.coordinator").StreamCoordinator
        for cls, names in ((manager, ("ensure_stream", "release_stream", "_stop_stream_owned")),
                           (coordinator, ("ensure_stream", "stop_stream"))):
            for name in names:
                lifecycle(cls, name)
        _patched = True
        emit("trace-installed", scope="diagnostic-only; bounded log; original results/exceptions retained")
    except Exception as exc:
        emit("trace-install-error", error=type(exc).__name__)


_run = asyncio.Runner.run


@functools.wraps(_run)
def run(self, *args, **kwargs):
    patch()
    return _run(self, *args, **kwargs)


asyncio.Runner.run = run
