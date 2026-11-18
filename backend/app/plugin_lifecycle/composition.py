"""Trusted startup claims, frozen for the lifetime of constructed consumers."""

from __future__ import annotations

import hashlib
import inspect
from contextlib import contextmanager

from app.plugin_security_v2.storage import atomic_write_json, read_json

from .store import LifecycleError


class StartupComposition:
    def __init__(self, store):
        self.store = store
        self.factories = {}
        self.frozen = False

    def marker(self, identity):
        key = hashlib.sha256(identity.plugin_id.encode()).hexdigest()
        path = self.store.root / "startup" / f"{key}.json"
        self.store._check_path(path)
        return path

    def interrupted(self, identity):
        path = self.marker(identity)
        return (
            path.exists()
            and read_json(path, "unified startup marker") == identity.to_wire()
        )

    @contextmanager
    def executing(self, identity):
        path = self.marker(identity)
        if self.interrupted(identity):
            raise LifecycleError(
                "previous startup failed; disable or reapprove this activation"
            )
        atomic_write_json(path, identity.to_wire())
        yield
        atomic_write_json(path, {})

    def register(self, run, target, wrapper):
        if (
            self.frozen
            or not isinstance(target, str)
            or target not in run.entry.startup
        ):
            raise LifecycleError(
                "factory must be declared by this entry and registered during prepare"
            )
        run.executor.context.ensure_current()
        if not callable(wrapper) or target in self.factories:
            raise LifecycleError(f"invalid or duplicate startup factory: {target}")
        self.factories[target] = (run, wrapper)

    def discard(self, identity):
        self.factories = {
            target: binding
            for target, binding in self.factories.items()
            if binding[0].identity != identity
        }

    def resolve(self, target, default):
        binding = self.factories.get(target)
        if binding is None:
            return default
        run, wrapper = binding
        identity = run.identity

        def invoke(*args, **kwargs):
            run.executor.context.ensure_current()
            # FastAPI constructs these services sequentially. Leave the marker
            # on any error, including cancellation or abrupt process exit.
            with self.executing(identity):
                result = wrapper(default, *args, **kwargs)
                if not inspect.isawaitable(result):
                    return result
            return finish(result)

        async def finish(result):
            with self.executing(identity):
                return await result

        return invoke


def startup_factory(app, target, default):
    runtime = getattr(app.state, "unified_plugin_runtime", None)
    return runtime.composition.resolve(target, default) if runtime else default
