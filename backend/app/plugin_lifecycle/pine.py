"""Bind the existing Pine chart and strategy consumers to the unified owner."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from candlescope_plugin_sdk import AnalyzeResult, ExecuteBatchResult, RuntimeDescriptor

from app.core.executors import run_indicator
from app.core.runtime_output import RuntimeOutputReference, RuntimeOutputSnapshot

from .bundle import verify_package
from .paths import is_link
from .pine_bundle import PINE_ENTRY, PINE_ID
from .store import LifecycleError

PINE_BUNDLE_ENV = "CANDLESCOPE_BUNDLED_UNIFIED_PINE"
MAX_BYTES = 64 * 1024 * 1024
INSTALLATION_SCHEMA = "candlescope.unified-pine-installation/1"
STRATEGY_MODULES = frozenset(
    {
        "native_strategy",
        "native_session",
        "external_strategy",
        "chart_strategy",
    }
)
_strategy_runtime = None
_strategy_required = False
_strategy_processes = {}
_process_lock = threading.Lock()


def bundled_path(environ):
    return environ.get(PINE_BUNDLE_ENV)


def stage_bundled_pine(runtime, descriptor):
    """Seed a first-party default once. User disable, rollback and removal win."""
    from app.plugin_security_v2.storage import atomic_write_json, read_json

    path = Path(descriptor)
    data = read_json(path, "bundled Pine descriptor")
    if (
        not isinstance(data, dict)
        or set(data) != {"schema", "filename", "sha256", "size"}
        or data["schema"] != "candlescope.bundled-unified-pine/1"
        or not isinstance(data["filename"], str)
        or not re.fullmatch(r"[a-zA-Z0-9_.-]+[.]cspkg", data["filename"])
    ):
        raise LifecycleError("invalid bundled Pine descriptor")
    archive = path.parent / data["filename"]
    verified = verify_package(archive)
    manifest = verified.manifest
    if (
        verified.sha256 != data["sha256"]
        or verified.size != data["size"]
        or manifest.id != PINE_ID
        or manifest.trust != "full-trust"
        or len(manifest.entries) != 1
        or manifest.entries[0].id != PINE_ENTRY
        or manifest.entries[0].runtime != "python-module"
        or manifest.dependencies
        or manifest.permissions
    ):
        raise LifecycleError(
            "bundled Pine archive does not match its selected contract"
        )
    store = runtime.store
    marker = store.root / "bundled-pine.json"
    store._check_path(marker)
    previous = read_json(marker, "bundled Pine seed receipt") if marker.exists() else {}
    if not isinstance(previous, dict):
        raise LifecycleError("invalid bundled Pine seed receipt")
    prior_digest = previous.get("sha256")
    snapshot = store.snapshot()
    existing = snapshot["plugins"].get(PINE_ID)
    if prior_digest == verified.sha256:
        return
    package = store.stage(archive)
    if package.sha256 != verified.sha256:
        raise LifecycleError("bundled Pine bytes changed during staging")
    # Existing user choices never activate implicitly. A desktop update may
    # replace its own still-enabled previous default through the common store.
    if (existing is None and not previous) or (
        existing and existing["enabled"] and existing["packageSha256"] == prior_digest
    ):
        store.activate(
            verified.sha256,
            expected_revision=snapshot["revision"],
            acknowledgement=f"full-trust:{verified.sha256}",
        )
    if not previous or existing is None or existing["packageSha256"] == prior_digest:
        atomic_write_json(marker, {"sha256": verified.sha256})


def import_pine_observations(storage, environ):
    """Copy a consistent legacy journal into private storage on first use."""
    target = storage / "observations-v1.sqlite3"
    if target.exists() or is_link(target):
        return
    explicit = environ.get("CANDLESCOPE_PINE_JOURNAL")
    if explicit:
        source = Path(explicit).expanduser().absolute()
    elif environ.get("CANDLESCOPE_DESKTOP_USER_DATA"):
        return
    else:
        root = Path(environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
        source = root / "CandleScope" / "pine" / target.name
    if not source.is_file():
        return

    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}")
    deadline = time.monotonic() + 5

    def check_progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise LifecycleError("Pine observation journal backup timed out")

    try:
        with (
            closing(
                sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=1)
            ) as old,
            closing(sqlite3.connect(temporary)) as new,
        ):
            page_size = old.execute("PRAGMA page_size").fetchone()[0]
            pages = old.execute("PRAGMA page_count").fetchone()[0]
            if page_size * pages > 512 * 1024 * 1024:
                raise LifecycleError(
                    "Pine observation journal exceeds the migration budget"
                )
            old.backup(new, pages=256, progress=check_progress, sleep=0.05)
        os.replace(temporary, target)
    except sqlite3.Error as exc:
        raise LifecycleError(
            f"Could not copy the previous Pine observation journal: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def bind_strategy_runtime(runtime, *, required):
    global _strategy_runtime, _strategy_required
    _strategy_runtime, _strategy_required = runtime, required


def _pin(runtime):
    run = runtime.running.get((PINE_ID, PINE_ENTRY)) if runtime is not None else None
    if (
        run is None
        or run.entry.kind != "sidecar"
        or run.entry.runtime != "python-module"
        or run.executor.context.trust != "full-trust"
        or not runtime.packages.get(PINE_ID, {}).get("coreReady")
        or not runtime._current(run)
    ):
        raise LifecycleError("Enable or restore the unified Pine package")
    return run


def strategy_launch():
    if not _strategy_required:
        return None
    run = _pin(_strategy_runtime)
    return _launch(run, "native_strategy")


def _launch(run, module):
    return {
        "command": [
            sys.executable,
            "-I",
            "-B",
            "-u",
            "-c",
            "import runpy,sys;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];runpy.run_module(sys.argv[0],run_name='__main__')",
            str(run.executor.context.root),
            f"candlescope_plugin_pine_compat.{module}",
        ],
        "plugin_id": PINE_ID,
        "plugin_version": run.identity.plugin_version,
        "installation": {
            "schema": INSTALLATION_SCHEMA,
            "packageSha256": run.identity.package_sha256,
            "generation": run.identity.generation,
        },
        "instanceId": run.instance,
    }


def pin_strategy_launch(plugin, *, restore=False):
    installation = plugin.get("installation")
    unified = (
        isinstance(installation, dict)
        and installation.get("schema") == INSTALLATION_SCHEMA
    )
    if not unified:
        if _strategy_required and plugin.get("plugin_id") == PINE_ID:
            raise LifecycleError(
                "This Pine run uses a retired runtime. Rerun it with the unified package."
            )
        return plugin
    run = _pin(_strategy_runtime)
    if installation.get("packageSha256") != run.identity.package_sha256 or (
        not restore
        and (
            plugin.get("instanceId") != run.instance
            or installation.get("generation") != run.identity.generation
        )
    ):
        raise LifecycleError(
            "Pine activation changed; restore the pinned package or rerun"
        )
    module = plugin["command"][-1].removeprefix("candlescope_plugin_pine_compat.")
    if module not in STRATEGY_MODULES:
        raise LifecycleError("Invalid unified Pine strategy entry")
    return _launch(run, module)


def track_strategy_process(plugin, process):
    instance = plugin.get("instanceId")
    if instance is None:
        return
    with _process_lock:
        pin_strategy_launch(plugin)
        _strategy_processes.setdefault(instance, set()).add(process)


def untrack_strategy_process(plugin, process):
    instance = plugin.get("instanceId")
    with _process_lock:
        processes = _strategy_processes.get(instance)
        if processes is not None:
            processes.discard(process)
            if not processes:
                _strategy_processes.pop(instance, None)


def revoke_strategy_processes(instance):
    with _process_lock:
        processes = _strategy_processes.pop(instance, ())
    for process in processes:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()


def _write(path, value):
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    size = 0
    with path.open("xb") as output:
        for chunk in encoder.iterencode(value):
            block = chunk.encode()
            size += len(block)
            if size > MAX_BYTES:
                raise LifecycleError("Pine input exceeds 64 MiB")
            output.write(block)


def _read(path, expected_size):
    if is_link(path) or not path.is_file() or not 0 < expected_size <= MAX_BYTES:
        raise LifecycleError("Pine output is not a bounded regular file")
    with path.open("rb") as source:
        value = source.read(MAX_BYTES + 1)
    if len(value) != expected_size:
        raise LifecycleError("Pine output does not match its receipt")
    return json.loads(value)


class PineRuntimeHost:
    """Indicator host interface backed by a unified sidecar and activation lease."""

    def __init__(self, runtime, legacy):
        self.runtime, self.legacy = runtime, legacy
        self.lock = asyncio.Lock()
        self.outputs = OrderedDict()

    async def _exchange(self, run, operation, payload):
        # A cancelled browser waiter does not kill the shared Pine worker.
        # Serialization and cleanup remain owned by the operation task.
        async with self.lock:
            if _pin(self.runtime) is not run:
                raise LifecycleError("Pine activation changed before execution")
            root = run.executor.context.root / ".pine-exchange"
            root.mkdir(exist_ok=True)
            if is_link(root):
                raise LifecycleError("invalid Pine exchange directory")
            exchange = uuid.uuid4().hex
            request = root / f"{exchange}.input"
            output = root / f"{exchange}.output"
            try:
                await run_indicator(
                    _write, request, {"operation": operation, "payload": payload}
                )
                receipt = await run.executor.transport.request(
                    "pine.exchange",
                    {"exchangeId": exchange},
                    generation=run.identity.generation,
                    timeout=30,
                    send_cancel_on_cancel=False,
                )
                if (
                    receipt.get("exchangeId") != exchange
                    or type(receipt.get("size")) is not int
                ):
                    raise LifecycleError("Pine exchange acknowledgement is invalid")
                result = await run_indicator(_read, output, receipt["size"])
                if _pin(self.runtime) is not run:
                    raise LifecycleError("Pine activation changed during execution")
                return result
            finally:
                for file in (request, output):
                    file.unlink(missing_ok=True)
                try:
                    root.rmdir()
                except OSError:
                    pass

    async def _call(self, run, operation, payload):
        task = asyncio.create_task(self._exchange(run, operation, payload))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            raise

    async def descriptor(self, runtime_id):
        if runtime_id != PINE_ID:
            return await self.legacy.descriptor(runtime_id)
        return RuntimeDescriptor.from_wire(
            await self._call(_pin(self.runtime), "describe", {})
        )

    async def analyze(self, runtime_id, request):
        if runtime_id != PINE_ID:
            return await self.legacy.analyze(runtime_id, request)
        return AnalyzeResult.from_wire(
            await self._call(_pin(self.runtime), "analyze", request.to_wire())
        )

    async def execute_batch(self, runtime_id, request):
        if runtime_id != PINE_ID:
            return await self.legacy.execute_batch(runtime_id, request)
        run = _pin(self.runtime)
        if request.output_stream:
            self.outputs.pop(request.output_stream, None)
        # An explicit full-window request preserves the engine's typed Render IR
        # and its durable Pine session while keeping wire-patch state private.
        wire = await run_indicator(
            replace(request, bars_stream=None, bars_base=None, output_base=None).to_wire
        )
        result = ExecuteBatchResult.from_wire(await self._call(run, "calculate", wire))
        if request.output_stream and result.ok and result.output is not None:
            ref = RuntimeOutputReference(
                run.instance,
                run.identity.generation,
                request.output_stream,
                uuid.uuid4().hex,
            )
            self.outputs[request.output_stream] = RuntimeOutputSnapshot(
                ref, result.output
            )
            while len(self.outputs) > 64:
                self.outputs.popitem(last=False)
        return replace(result, output_revision=None, bars_revision=None)

    async def read_output(self, runtime_id, stream, *, expected=None):
        if runtime_id != PINE_ID:
            return await self.legacy.read_output(runtime_id, stream, expected=expected)
        result = self.outputs.get(stream)
        if result is None:
            return None
        try:
            run = _pin(self.runtime)
        except LifecycleError:
            return None
        return (
            result
            if result.reference.owner_epoch == run.instance
            and (expected is None or expected == result.reference)
            else None
        )

    async def release_stream(self, runtime_id, stream):
        if runtime_id != PINE_ID:
            return await self.legacy.release_stream(runtime_id, stream)
        self.outputs.pop(stream, None)
        await self._call(_pin(self.runtime), "release", {"stream": stream})
