"""Backend and process executors sharing one package activation identity."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import shutil
import sys
import uuid
from pathlib import Path

from app.plugin_host.process import SidecarProcessSpec
from app.plugin_host.transport import PlatformV2Transport
from app.plugin_security_v2.sandbox import (
    SandboxPolicy,
    restricted_runtime_profile,
    sandbox_profile_name,
)

from .store import LifecycleError

PROTOCOL = "candlescope.unified-entry/1"


async def bounded(work, timeout):
    """Bound the wait even if in-process application code suppresses cancellation."""
    task = asyncio.ensure_future(work)

    def settled(done):
        if not done.cancelled():
            done.exception()

    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if done:
            return task.result()
        raise TimeoutError("plugin operation timed out; restart required")
    finally:
        if not task.done():
            task.cancel()
            task.add_done_callback(settled)


class OwnedContext:
    """SDK-owned resources are revoked before cleanup; full trust is application code."""

    api_version = 1

    def __init__(self, app, identity, entry, root, current, publish):
        self.app, self.identity, self.entry, self.root = app, identity, entry, root
        self.id, self.entry_id = identity.plugin_id, entry.id
        self._current, self._publish = current, publish
        self.cleanups = []
        self.disposed = False
        self.storage = None
        self.trust = "full-trust"
        self.timeout = 10
        self.failure = lambda _error: None

    def ensure_current(self):
        if self.disposed or not self._current():
            raise LifecycleError("plugin activation was revoked")

    def publish(self, value):
        self.ensure_current()
        self._publish(value)

    def track(self, cleanup):
        if not callable(cleanup):
            raise TypeError("cleanup must be callable")
        if self.disposed:
            value = cleanup()
            if inspect.isawaitable(value):

                async def finish():
                    await bounded(value, 5)

                asyncio.create_task(finish()).add_done_callback(
                    lambda task: None if task.cancelled() else task.exception()
                )
            raise LifecycleError("plugin activation was revoked")
        self.cleanups.append(cleanup)

    def task(self, coroutine):
        self.ensure_current()
        task = asyncio.create_task(coroutine)

        def finished(done):
            if not done.cancelled():
                error = done.exception()
                if error is not None and not self.disposed:
                    self.failure(error)

        task.add_done_callback(finished)

        async def stop():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.track(stop)
        return task

    async def dispose(self):
        self.disposed = True
        errors = []
        for cleanup in reversed(self.cleanups):
            try:
                value = cleanup()
                if inspect.isawaitable(value):
                    await bounded(value, 5)
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                errors.append(str(exc))
        self.cleanups.clear()
        return errors


class BackendEntry:
    def __init__(self, context):
        self.context = context
        self.namespace = "candlescope_unified_" + uuid.uuid4().hex
        self.module = None

    def load(self):
        context = self.context
        path = context.root / context.entry.path
        spec = importlib.util.spec_from_file_location(
            self.namespace, path, submodule_search_locations=[str(path.parent)]
        )
        if spec is None or spec.loader is None:
            raise LifecycleError("backend entry cannot be imported")
        module = importlib.util.module_from_spec(spec)
        self.module = module
        sys.modules[self.namespace] = module
        spec.loader.exec_module(module)
        return module

    async def prepare(self, register):
        module = self.load()
        prepare = getattr(module, "prepare", None)
        if not callable(prepare):
            raise LifecycleError("startup entry must export prepare(context)")
        self.context.wrap_factory = register
        await self._run_hook(prepare)

    async def start(self):
        module = self.module if self.module is not None else self.load()
        activate = getattr(module, "activate", None)
        if not callable(activate):
            raise LifecycleError("backend entry must export activate(context)")
        await self._run_hook(activate)

    async def _run_hook(self, hook):
        context = self.context
        value = hook(context)
        if inspect.isawaitable(value):

            async def finish_activation():
                cleanup = await value
                if callable(cleanup):
                    context.track(cleanup)

            await bounded(finish_activation(), context.timeout)
        elif callable(value):
            context.track(value)
        context.ensure_current()

    async def invoke(self, payload):
        self.context.ensure_current()
        handler = getattr(self.module, "invoke", None)
        if not callable(handler):
            raise LifecycleError("entry does not export invoke(context, payload)")
        value = handler(self.context, payload)
        return (
            await bounded(value, self.context.timeout)
            if inspect.isawaitable(value)
            else value
        )

    async def stop(self):
        # Mark revoked even when arbitrary plugin cleanup fails.
        self.context.disposed = True
        deactivate = getattr(self.module, "deactivate", None)
        if callable(deactivate):
            self.context.cleanups.append(lambda: deactivate(self.context))
        errors = await self.context.dispose()
        for name in tuple(sys.modules):
            if name == self.namespace or name.startswith(self.namespace + "."):
                sys.modules.pop(name, None)
        if errors:
            raise LifecycleError("; ".join(errors))


class SidecarEntry:
    def __init__(self, context, instance_id, executables):
        self.context, self.instance_id = context, instance_id
        entry, root = context.entry, context.root
        path = root / entry.path
        if entry.runtime == "native-executable":
            path.chmod(0o700)
            executable, arguments = path, ()
        else:
            executable = executables.get(entry.runtime)
            if not executable:
                raise LifecycleError(f"runtime unavailable: {entry.runtime}")
            arguments = (
                (
                    "-I",
                    "-u",
                    "-c",
                    "import runpy,sys;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2],run_name='__main__')",
                    str(root),
                    str(path),
                )
                if entry.runtime == "python-module"
                else ("-jar", str(path))
                if entry.runtime == "java-jar"
                else ("run", str(path))
                if entry.runtime == "wasm-component"
                else (str(path),)
            )
        self.transport = PlatformV2Transport(
            SidecarProcessSpec(
                identity=f"{context.id}:{entry.id}",
                executable=Path(executable),
                arguments=arguments,
                working_directory=root,
                manage_process_tree=True,
                terminate_on_cancel=True,
                trust_level="untrusted"
                if context.trust == "restricted"
                else "local-trusted",
                sandbox_policy=restricted_policy(context, executable)
                if context.trust == "restricted"
                else None,
            ),
            plugin_id=context.id,
            entrypoint_id=entry.id,
        )

    async def start(self):
        identity = {
            **self.context.identity.to_wire(),
            "entryId": self.context.entry_id,
            "instanceId": self.instance_id,
        }
        self.transport.set_active_generation(self.context.identity.generation)
        await self.transport.start()
        result = await self.transport.request(
            "activate",
            {
                "protocol": PROTOCOL,
                "identity": identity,
                "storage": str(self.context.storage),
            },
            generation=self.context.identity.generation,
            timeout=10,
        )
        if result != {"protocol": PROTOCOL, "identity": identity}:
            raise LifecycleError(
                "sidecar did not acknowledge the exact unified entry identity"
            )

    async def invoke(self, payload):
        return await self.transport.request(
            "invoke",
            {"input": payload},
            generation=self.context.identity.generation,
            timeout=10,
        )

    async def stop(self):
        self.context.disposed = True
        await self.transport.close()
        await self.context.dispose()


def restricted_policy(context, executable):
    profile = restricted_runtime_profile(context.entry.runtime)
    if not profile.supported():
        raise LifecycleError(
            "restricted sidecar requires a qualified isolated runtime; unavailable"
        )
    if context.entry.runtime in {"python-module", "native-executable"}:
        runtime = Path(sys.base_prefix)
        extras = (
            (Path(sys.prefix),)
            if context.entry.runtime == "python-module"
            and sys.prefix != sys.base_prefix
            else ()
        )
    else:
        runtime = Path(executable).resolve().parent
        if context.entry.runtime == "java-jar":
            runtime = runtime.parent
        extras = ()
    return SandboxPolicy(
        profile_name=sandbox_profile_name(
            context.id,
            context.identity.package_sha256,
            int(context.identity.plugin_version.split(".")[0]),
        ),
        installation_directory=context.root,
        private_directory=context.storage,
        runtime_directory=runtime,
        additional_read_only_paths=extras,
        memory_limit_bytes=profile.memory_limit_bytes,
        cpu_rate_percent=profile.cpu_rate_percent,
        cpu_time_seconds=profile.runtime_cpu_time_seconds,
        disk_limit_bytes=profile.disk_limit_bytes,
        max_processes=profile.max_processes,
        max_wall_seconds=profile.runtime_wall_seconds,
    )


def default_executables():
    return {
        "python-module": sys.executable,
        "node-module": shutil.which("node"),
        "java-jar": shutil.which("java"),
        "wasm-component": shutil.which("wasmtime"),
    }
