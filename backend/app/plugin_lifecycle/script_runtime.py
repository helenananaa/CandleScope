"""Typed indicator calculations through lifecycle-owned script sidecars."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path

from candlescope_plugin_sdk import AnalyzeResult, ExecuteBatchResult, RuntimeDescriptor

from app.core.executors import run_indicator
from app.core.runtime_output import RuntimeOutputReference, RuntimeOutputSnapshot
from app.plugin_security_v2.storage import atomic_write_json, read_json

from .bundle import verify_package
from .paths import is_link
from .script_bundle import SCRIPT_BUNDLES
from .store import LifecycleError

MAX_BYTES = 64 * 1024 * 1024


def bundled_scripts(environ):
    return {
        plugin_id: path
        for plugin_id, spec in SCRIPT_BUNDLES.items()
        if (path := environ.get(spec.environment)) is not None
    }


def stage_bundled_script(runtime, plugin_id, descriptor):
    """Seed a first-party default once. User disable, rollback and removal win."""
    spec = SCRIPT_BUNDLES[plugin_id]
    path = Path(descriptor)
    data = read_json(path, "bundled script runtime descriptor")
    if (
        not isinstance(data, dict)
        or set(data) != {"schema", "filename", "sha256", "size"}
        or data["schema"] != f"candlescope.bundled-unified-{spec.exchange}/1"
        or not isinstance(data["filename"], str)
        or not re.fullmatch(r"[a-zA-Z0-9_.-]+[.]cspkg", data["filename"])
    ):
        raise LifecycleError("invalid bundled script runtime descriptor")
    archive = path.parent / data["filename"]
    verified = verify_package(archive)
    manifest = verified.manifest
    if (
        verified.sha256 != data["sha256"]
        or verified.size != data["size"]
        or manifest.id != plugin_id
        or manifest.trust != "full-trust"
        or len(manifest.entries) != 1
        or manifest.entries[0].id != spec.entry
        or manifest.entries[0].runtime != "python-module"
        or manifest.dependencies
        or manifest.permissions
    ):
        raise LifecycleError(
            "bundled script runtime archive does not match its selected contract"
        )
    store = runtime.store
    marker = store.root / f"bundled-{spec.exchange}.json"
    store._check_path(marker)
    previous = (
        read_json(marker, "bundled script runtime seed receipt")
        if marker.exists()
        else {}
    )
    if not isinstance(previous, dict):
        raise LifecycleError("invalid bundled script runtime seed receipt")
    prior_digest = previous.get("sha256")
    snapshot = store.snapshot()
    existing = snapshot["plugins"].get(plugin_id)
    if prior_digest == verified.sha256:
        return
    package = store.stage(archive)
    if package.sha256 != verified.sha256:
        raise LifecycleError("bundled script runtime bytes changed during staging")
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


def pin_script(runtime, runtime_id):
    spec = SCRIPT_BUNDLES.get(runtime_id)
    if spec is None:
        raise LifecycleError("This script runtime package needs a unified update")
    run = runtime.running.get((runtime_id, spec.entry)) if runtime is not None else None
    if (
        run is None
        or run.entry.kind != "sidecar"
        or run.entry.runtime != "python-module"
        or run.executor.context.trust != "full-trust"
        or not runtime.packages.get(runtime_id, {}).get("coreReady")
        or not runtime._current(run)
    ):
        raise LifecycleError(f"Enable or restore the unified {spec.label} package")
    return run


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
                raise LifecycleError("script input exceeds 64 MiB")
            output.write(block)


def _read(path, expected_size):
    if is_link(path) or not path.is_file() or not 0 < expected_size <= MAX_BYTES:
        raise LifecycleError("script output is not a bounded regular file")
    with path.open("rb") as source:
        value = source.read(MAX_BYTES + 1)
    if len(value) != expected_size:
        raise LifecycleError("script output does not match its receipt")
    return json.loads(value)


class ScriptRuntimeHost:
    """Indicator host interface backed by a unified sidecar and activation lease."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.locks = {runtime_id: asyncio.Lock() for runtime_id in SCRIPT_BUNDLES}
        self.outputs = OrderedDict()

    async def _exchange(self, run, operation, payload):
        # A cancelled browser waiter does not kill the shared Pine worker.
        # Serialization and cleanup remain owned by the operation task.
        runtime_id = run.identity.plugin_id
        spec = SCRIPT_BUNDLES[runtime_id]
        async with self.locks[runtime_id]:
            if pin_script(self.runtime, runtime_id) is not run:
                raise LifecycleError("Script activation changed before execution")
            root = run.executor.context.root / f".{spec.exchange}-exchange"
            root.mkdir(exist_ok=True)
            if is_link(root):
                raise LifecycleError("invalid script exchange directory")
            exchange = uuid.uuid4().hex
            request = root / f"{exchange}.input"
            output = root / f"{exchange}.output"
            try:
                await run_indicator(
                    _write, request, {"operation": operation, "payload": payload}
                )
                receipt = await run.executor.transport.request(
                    f"{spec.exchange}.exchange",
                    {"exchangeId": exchange},
                    generation=run.identity.generation,
                    timeout=30,
                    send_cancel_on_cancel=False,
                )
                if (
                    receipt.get("exchangeId") != exchange
                    or type(receipt.get("size")) is not int
                ):
                    raise LifecycleError("script exchange acknowledgement is invalid")
                result = await run_indicator(_read, output, receipt["size"])
                if pin_script(self.runtime, runtime_id) is not run:
                    raise LifecycleError("Script activation changed during execution")
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
        return RuntimeDescriptor.from_wire(
            await self._call(pin_script(self.runtime, runtime_id), "describe", {})
        )

    async def analyze(self, runtime_id, request):
        return AnalyzeResult.from_wire(
            await self._call(
                pin_script(self.runtime, runtime_id), "analyze", request.to_wire()
            )
        )

    async def execute_batch(self, runtime_id, request):
        run = pin_script(self.runtime, runtime_id)
        if request.output_stream:
            self.outputs.pop((runtime_id, request.output_stream), None)
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
            self.outputs[(runtime_id, request.output_stream)] = RuntimeOutputSnapshot(
                ref, result.output
            )
            while len(self.outputs) > 64:
                self.outputs.popitem(last=False)
        return replace(result, output_revision=None, bars_revision=None)

    async def read_output(self, runtime_id, stream, *, expected=None):
        result = self.outputs.get((runtime_id, stream))
        if result is None:
            return None
        try:
            run = pin_script(self.runtime, runtime_id)
        except LifecycleError:
            return None
        return (
            result
            if result.reference.owner_epoch == run.instance
            and (expected is None or expected == result.reference)
            else None
        )

    async def release_stream(self, runtime_id, stream):
        self.outputs.pop((runtime_id, stream), None)
        await self._call(
            pin_script(self.runtime, runtime_id), "release", {"stream": stream}
        )
