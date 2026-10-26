"""Restart-bound Python host integration for fully trusted extension packages."""
from __future__ import annotations

import importlib.util
import asyncio
import inspect
import os
import sys
from functools import partial
from pathlib import Path
from typing import Any

from app.plugin_security_v2.storage import atomic_write_json, read_json
from .store import ExtensionStore


class HostContext:
    api_version = 1
    internal_api_version = 1

    def __init__(self, app: Any, extension_id: str, root: Path):
        self.app = app
        self.extension_id = extension_id
        self.root = root
        self.cleanups: list[Any] = []
        self.phase = "prepare"

    def wrap_factory(self, name: str, wrapper: Any) -> None:
        """Install one wrapper before a built-in runtime is constructed."""
        if self.phase != "prepare" or name not in {"data-engine", "replay", "alert-delivery", "indicator-range"} or not callable(wrapper):
            raise ValueError("Factory wrappers must target a supported startup service during prepare")
        factories = getattr(self.app.state, "trusted_extension_factories", None)
        if factories is None:
            factories = {}
            self.app.state.trusted_extension_factories = factories
        if name in factories:
            raise ValueError(f"Service factory already replaced: {name}")
        factories[name] = wrapper
        self.track(lambda: factories.pop(name, None) if factories.get(name) is wrapper else None)

    def track(self, cleanup: Any) -> Any:
        if not callable(cleanup):
            raise ValueError("Cleanup must be callable")
        self.cleanups.append(cleanup)
        return cleanup

    def replace_service(self, name: str, service: Any) -> None:
        """Replace an app.state binding; previously captured references stay unchanged."""
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise ValueError("Invalid service name")
        missing = object()
        previous = getattr(self.app.state, name, missing)
        setattr(self.app.state, name, service)

        def restore() -> None:
            if getattr(self.app.state, name, missing) is service:
                if previous is missing:
                    delattr(self.app.state, name)
                else:
                    setattr(self.app.state, name, previous)
        self.track(restore)

    async def dispose(self) -> list[str]:
        errors = []
        for cleanup in reversed(self.cleanups):
            try:
                value = cleanup()
                if inspect.isawaitable(value):
                    await asyncio.wait_for(value, timeout=10)
            except Exception as exc:
                errors.append(str(exc))
        self.cleanups.clear()
        return errors


class ExtensionHost:
    def __init__(self, app: Any, store: ExtensionStore):
        self.app, self.store = app, store
        self.loaded: list[tuple[dict, Any, HostContext]] = []
        self.errors: dict[str, str] = {}
        self.marker = store.root / "backend-loading.json"

    async def prepare(self) -> None:
        try:
            blocked = read_json(self.marker, "extension crash marker") if self.marker.exists() else {}
            if not isinstance(blocked, dict):
                raise ValueError("Invalid extension crash marker")
            plan = self.store.plan()
        except Exception as exc:
            self.errors["runtime"] = str(exc)
            return
        for item in plan["active"]:
            manifest = item["manifest"]
            entry = manifest.get("entries", {}).get("backend")
            if not entry:
                continue
            key = manifest["id"]
            if item["digest"] == blocked.get("digest") and item["generation"] == blocked.get("generation"):
                self.errors[key] = "Previous startup was interrupted while loading this version; disable or reinstall after recovery"
                continue
            if any(dep in self.errors for dep in manifest.get("dependencies", {})):
                self.errors[key] = "A dependency failed to start"
                continue
            context = None
            try:
                root = self.store.materialize(item["digest"])
                atomic_write_json(self.marker, {"digest": item["digest"], "generation": item["generation"], "id": key})
                namespace = f"candlescope_extension_{item['digest']}"
                spec = importlib.util.spec_from_file_location(namespace, root / entry,
                    submodule_search_locations=[str((root / entry).parent)])
                if spec is None or spec.loader is None:
                    raise ValueError("Cannot load backend entry")
                module = importlib.util.module_from_spec(spec)
                context = HostContext(self.app, key, root)

                def unload(namespace=namespace):
                    for name in tuple(sys.modules):
                        if name == namespace or name.startswith(namespace + "."):
                            sys.modules.pop(name, None)
                context.track(unload)
                sys.modules[namespace] = module
                spec.loader.exec_module(module)
                prepare = getattr(module, "prepare", None)
                if prepare:
                    value = prepare(context)
                    if inspect.isawaitable(value):
                        await asyncio.wait_for(value, timeout=10)
                self.loaded.append((item, module, context))
            except Exception as exc:
                self.errors[key] = str(exc)
                if context:
                    await context.dispose()
            finally:
                # Retain an older crash marker until that package is deliberately recovered.
                atomic_write_json(self.marker, blocked)

    async def activate(self) -> None:
        for item, module, context in self.loaded:
            context.phase = "active"
            key = item["manifest"]["id"]
            if any(dep in self.errors for dep in item["manifest"].get("dependencies", {})):
                self.errors[key] = "A dependency failed to activate"
                await context.dispose()
                continue
            previous = read_json(self.marker, "extension crash marker") if self.marker.exists() else {"digest": None}
            try:
                atomic_write_json(self.marker, {"digest": item["digest"], "generation": item["generation"], "id": key})
                activate = getattr(module, "activate", None)
                if activate:
                    value = activate(context)
                    if inspect.isawaitable(value):
                        value = await asyncio.wait_for(value, timeout=10)
                    if callable(value):
                        context.track(value)
            except Exception as exc:
                self.errors[key] = str(exc)
                await context.dispose()
            finally:
                atomic_write_json(self.marker, previous)

    async def stop(self) -> None:
        for item, module, context in reversed(self.loaded):
            try:
                deactivate = getattr(module, "deactivate", None)
                if deactivate:
                    value = deactivate(context)
                    if inspect.isawaitable(value):
                        await asyncio.wait_for(value, timeout=10)
            except Exception as exc:
                self.errors[item["manifest"]["id"]] = str(exc)
            finally:
                await context.dispose()
        self.loaded.clear()


def extension_store(app: Any, root: Path | None = None) -> ExtensionStore:
    store = getattr(app.state, "trusted_extension_store", None)
    if store is None:
        from app.plugin_core_v2.bootstrap import default_platform_root
        configured = os.environ.get("CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT")
        root = root or (Path(configured) if configured else default_platform_root(os.environ))
        store = ExtensionStore(root)
        app.state.trusted_extension_store = store
    return store


def extension_factory(app: Any, name: str, default: Any) -> Any:
    wrapper = getattr(app.state, "trusted_extension_factories", {}).get(name)
    return partial(wrapper, default) if wrapper else default


async def prepare_extensions(app: Any) -> None:
    if os.environ.get("CANDLESCOPE_PLUGIN_PLATFORM_V2_ENABLED", "1") == "0":
        return
    # The offline profile has no v2 sidecar plane, but uses the same desktop credentials.
    if os.environ.get("CANDLESCOPE_DESKTOP_PLUGIN_SESSION") and os.environ.get("CANDLESCOPE_DESKTOP_PLUGIN_CSRF"):
        from app.plugin_security_v2.management import LocalManagementGuard
        origins = os.environ.get("CANDLESCOPE_PLUGIN_PLATFORM_V2_MANAGEMENT_ORIGINS", "http://127.0.0.1:15173")
        app.state.trusted_extension_management_guard = LocalManagementGuard(
            [item.strip() for item in origins.split(",") if item.strip()],
            session_token=os.environ["CANDLESCOPE_DESKTOP_PLUGIN_SESSION"],
            csrf_token=os.environ["CANDLESCOPE_DESKTOP_PLUGIN_CSRF"],
        )
    host = ExtensionHost(app, extension_store(app))
    app.state.trusted_extension_host = host
    await host.prepare()


async def activate_extensions(app: Any) -> None:
    host = getattr(app.state, "trusted_extension_host", None)
    if host:
        await host.activate()


async def stop_extensions(app: Any) -> None:
    host = getattr(app.state, "trusted_extension_host", None)
    if host:
        await host.stop()
