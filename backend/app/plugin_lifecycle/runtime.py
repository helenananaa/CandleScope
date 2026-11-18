"""Unified desired/actual coordination for backend, sidecar and remote realms."""

from __future__ import annotations

import asyncio
import collections
import hashlib
import os
import secrets
import time
import uuid
from dataclasses import dataclass

from candlescope_plugin_sdk.platform_v2 import canonical_dumps, normalize_json
from candlescope_plugin_sdk.unified import ActivationIdentity, Entry
from candlescope_plugin_sdk.unified.chart import (
    validate_chart_frame,
    validate_chart_result,
)

from app.plugin_security_v2.sandbox import restricted_runtime_profile
from app.plugin_security_v2.storage import security_lock

from .appearance import APPEARANCE_KINDS, appearance_kind, parse_appearance
from .composition import StartupComposition
from .executors import (
    BackendEntry,
    OwnedContext,
    SidecarEntry,
    bounded,
    default_executables,
)
from .paths import is_link
from .script_bundle import PINE_ENTRY, PINE_ID, SCRIPT_BUNDLES
from .store import CHART_PERMISSION, LifecycleError, PackageStore


@dataclass
class RunningEntry:
    identity: ActivationIdentity
    entry: Entry
    instance: str
    executor: object
    active: bool = True


class UnifiedRuntime:
    def __init__(
        self,
        app,
        store: PackageStore,
        *,
        safe_mode=False,
        executables=None,
        execution_timeout=10,
    ):
        if not 0 < execution_timeout <= 10:
            raise ValueError(
                "execution timeout must be positive and at most 10 seconds"
            )
        self.execution_timeout = execution_timeout
        self.app, self.store, self.safe_mode = app, store, bool(safe_mode)
        self.executables = default_executables() if executables is None else executables
        self.instance = uuid.uuid4().hex
        self.packages = {}
        self.running = {}
        self.errors = {}
        self.dirty_backend = set()
        self.quarantined = set()
        self.attempted = {}
        self.sessions = {}
        self.expired = {}
        self.tickets = {}
        self.outputs = collections.deque(maxlen=128)
        self.calls = {}
        self.lock = asyncio.Lock()
        self.ready = False
        self.revision = -1
        self.changed = False
        self.owner_lock = None
        self.watcher = None
        self.metadata = {}
        self.composition = StartupComposition(store)
        self.prepared = {}
        self.retained = {}
        self.script_host_disabled = False
        self.bundled_pine = False
        self.marketplace_policy = None
        self.marketplace_blocked = frozenset()

    def _current(self, run, *, permission=None):
        if (
            not run.active
            or self.running.get((run.identity.plugin_id, run.entry.id)) is not run
        ):
            return False
        if run.entry.kind == "sidecar":
            transport = run.executor.transport
            if (
                transport.process is None
                or transport.process.returncode is not None
                or transport.fatal_error
            ):
                return False
        record = self.store.snapshot()["plugins"].get(run.identity.plugin_id)
        return bool(
            record
            and record["enabled"]
            and self._marketplace_allowed(run.identity.plugin_id, record)
            and (
                permission is None
                or "marketplace" not in record
                or permission in record["marketplace"]["permissions"]
            )
            and record["generation"] == run.identity.generation
            and record["packageSha256"] == run.identity.package_sha256
            and run.identity.plugin_id not in self.errors
        )

    def _marketplace_allowed(self, plugin_id, record):
        return "marketplace" not in record or (
            self.marketplace_policy is not None
            and self.marketplace_policy(plugin_id, record)
        )

    def validate_marketplace(self, manifest):
        if manifest.trust != "restricted" or any(
            entry.kind not in {"data", "sidecar"} for entry in manifest.entries
        ):
            raise LifecycleError(
                "marketplace observation requires restricted data or sidecar entries"
            )
        if manifest.permissions and (
            manifest.permissions != (CHART_PERMISSION,)
            or not any(entry.kind == "sidecar" for entry in manifest.entries)
        ):
            raise LifecycleError(
                "marketplace package requests an unsupported capability"
            )
        self.validate(manifest, marketplace=True)

    def validate(self, manifest, *, marketplace=False):
        if manifest.trust == "restricted" and manifest.permissions and not marketplace:
            raise LifecycleError(
                "restricted capability grants are not wired for unified entries"
            )
        for entry in manifest.entries:
            if entry.kind == "sidecar":
                if (
                    manifest.trust == "restricted"
                    and not restricted_runtime_profile(entry.runtime).supported()
                ):
                    raise LifecycleError(
                        "restricted sidecar requires a qualified isolated runtime; unavailable"
                    )
                if entry.runtime != "native-executable" and not self.executables.get(
                    entry.runtime
                ):
                    raise LifecycleError(f"runtime unavailable: {entry.runtime}")

    def validate_activation(self, manifest):
        self.validate(manifest)
        _, plan = self.store.execution_plan()
        if (
            len(manifest.entries)
            + sum(len(item.entries) for item, _ in plan if item.id != manifest.id)
            > 256
        ):
            raise LifecycleError("active execution plan exceeds 256 entries")

    def publish(self, run, value):
        result = {
            "identity": run.identity.to_wire(),
            "entryId": run.entry.id,
            "instanceId": run.instance,
            "value": normalize_json(value),
        }
        if len(canonical_dumps(result).encode()) > 64 * 1024:
            raise LifecycleError("published result exceeds its byte budget")
        package = self.packages[run.identity.plugin_id]
        if package["coreReady"]:
            self.outputs.append(result)
        else:
            package["pendingOutputs"].append(result)

    def entry_failed(self, plugin_id, error):
        self.errors[plugin_id] = str(error)
        self.changed = True

    async def _stop_package(self, plugin_id, *, shutdown=False):
        # Revoke all remote assets/results before waiting on arbitrary cleanup.
        self.tickets = {
            key: value for key, value in self.tickets.items() if value[0] != plugin_id
        }
        for session in self.sessions.values():
            for key, value in list(session["entries"].items()):
                if value["pluginId"] == plugin_id:
                    value["state"] = (
                        "pending-restart"
                        if value["state"] == "failed"
                        else "pending-stop"
                    )
                    session["retired"][value["instanceId"]] = value
                    del session["entries"][key]
        runs = [
            run for run in self.running.values() if run.identity.plugin_id == plugin_id
        ]
        for run in runs:
            run.active = False
            if run.entry.kind == "backend":
                self.dirty_backend.add(plugin_id)
        if plugin_id == PINE_ID:
            from .pine import revoke_strategy_processes

            for run in runs:
                if run.entry.id == PINE_ENTRY:
                    await asyncio.to_thread(revoke_strategy_processes, run.instance)
        for task, owner in list(self.calls.items()):
            if owner == plugin_id and task is not asyncio.current_task():
                task.cancel()
        for run in reversed(runs):
            self.running.pop((plugin_id, run.entry.id), None)
            if not shutdown and run.entry.startup and plugin_id in self.prepared:
                self.retained[(plugin_id, run.entry.id)] = run
                continue
            try:
                await bounded(run.executor.stop(), 10)
            except Exception as exc:  # noqa: BLE001 -- arbitrary plugin cleanup is isolated
                self.quarantined.add(plugin_id)
                self.errors[plugin_id] = f"cleanup failed; restart required: {exc}"
        package = self.packages.pop(plugin_id, None)
        if package and not shutdown and plugin_id in self.prepared:
            self.retained[(plugin_id, None)] = package
        elif package:
            try:
                await asyncio.to_thread(
                    self.store.release_materialization,
                    package["root"],
                    package["files"],
                )
            except (ValueError, OSError) as exc:
                self.errors[plugin_id] = f"execution files retained for recovery: {exc}"

    async def reconcile(self, *, start_only=None):
        async with self.lock:
            previous_scripts = {
                runtime_id: self.running.get((runtime_id, spec.entry))
                for runtime_id, spec in SCRIPT_BUNDLES.items()
            }
            snapshot = await asyncio.to_thread(self.store.snapshot)
            for run in self.running.values():
                if run.entry.kind == "sidecar" and not self._current(run):
                    self.errors[run.identity.plugin_id] = (
                        "sidecar exited or lost its activation"
                    )
                    self.changed = True
            blocked = frozenset(
                plugin_id
                for plugin_id, record in snapshot["plugins"].items()
                if record["enabled"]
                and not self._marketplace_allowed(plugin_id, record)
            )
            if (
                start_only is None
                and snapshot["revision"] == self.revision
                and blocked == self.marketplace_blocked
                and not self.changed
            ):
                return
            self.changed = False
            revision, plan = await asyncio.to_thread(self.store.execution_plan)
            # Use the same desired revision for policy and for the execution plan.
            if revision != snapshot["revision"]:
                self.changed = True
                return
            self.marketplace_blocked = blocked
            desired = {}
            if not self.safe_mode:
                for manifest, identity in plan:
                    if manifest.id not in blocked and all(
                        dependency in desired for dependency, _ in manifest.dependencies
                    ):
                        desired[manifest.id] = (manifest, identity)
            if self.script_host_disabled:
                for runtime_id in SCRIPT_BUNDLES:
                    desired.pop(runtime_id, None)
            for key in set(self.attempted) - desired.keys():
                self.attempted.pop(key, None)
                if key not in self.dirty_backend and key not in self.quarantined:
                    self.errors.pop(key, None)
            changed = {
                key
                for key, package in self.packages.items()
                if key not in desired
                or package["identity"] != desired[key][1]
                or key in self.errors
            }
            # Existing consumers must release references to a changed provider too.
            while True:
                expanded = changed | {
                    key
                    for key, value in self.packages.items()
                    if any(dep in changed for dep, _ in value["manifest"].dependencies)
                }
                if expanded == changed:
                    break
                changed = expanded
            for plugin_id in reversed(list(self.packages)):
                if plugin_id in changed:
                    await self._stop_package(plugin_id)
                    if (
                        self.attempted.get(plugin_id)
                        != desired.get(plugin_id, (None, None))[1]
                    ):
                        self.errors.pop(plugin_id, None)
            if not self.ready and start_only is None:
                return
            total_entries = sum(
                len(manifest.entries) for manifest, _ in desired.values()
            )
            if total_entries > 256:
                self.revision = revision
                raise LifecycleError("active execution plan exceeds 256 entries")
            for plugin_id, (manifest, identity) in desired.items():
                if start_only is not None and plugin_id not in start_only:
                    continue
                if self.packages.get(plugin_id, {}).get("coreReady"):
                    continue
                if (
                    self.attempted.get(plugin_id) == identity
                    and plugin_id in self.errors
                ):
                    continue
                self.attempted[plugin_id] = identity
                self.errors.pop(plugin_id, None)
                try:
                    record = snapshot["plugins"][plugin_id]
                    if not self._marketplace_allowed(plugin_id, record):
                        raise LifecycleError(
                            "signed marketplace release is unavailable"
                        )
                    if "marketplace" in record:
                        self.validate_marketplace(manifest)
                    else:
                        self.validate(manifest)
                    if any(
                        entry.kind == "backend" for entry in manifest.entries
                    ) and self.composition.interrupted(identity):
                        raise LifecycleError(
                            "previous startup failed; disable or reapprove this activation"
                        )
                    if plugin_id in self.quarantined:
                        raise LifecycleError(
                            "previous cleanup incomplete; restart required"
                        )
                    if any(dep in self.errors for dep, _ in manifest.dependencies):
                        raise LifecycleError("dependency failed or requires restart")
                    if plugin_id in self.dirty_backend and any(
                        e.kind == "backend" for e in manifest.entries
                    ):
                        raise LifecycleError("backend code changed; restart required")
                    package = self.packages.get(plugin_id)
                    if package is None:
                        if any(
                            entry.kind == "backend" and entry.startup
                            for entry in manifest.entries
                        ):
                            raise LifecycleError(
                                "startup factory changed; restart required"
                            )
                        migration = snapshot.get("marketplaceMigrations", {}).get(
                            plugin_id
                        )
                        package = await self._materialize(
                            manifest, identity, migration=migration
                        )
                    root = package["root"]
                    for entry in manifest.entries:
                        if entry.kind not in {"backend", "sidecar", "data"}:
                            continue
                        if entry.kind == "data":
                            from candlescope_plugin_sdk.platform_v2 import (
                                JsonLimits,
                                loads_strict,
                            )

                            with (root / entry.path).open("rb") as content:
                                raw = content.read(256 * 1024 + 1)
                            if (
                                hashlib.sha256(raw).hexdigest()
                                != package["files"][entry.path]
                            ):
                                raise LifecycleError(
                                    "data entry changed after verified extraction"
                                )
                            kind = appearance_kind(entry)
                            package["data"][entry.id] = (
                                parse_appearance(kind, raw, manifest.trust)
                                if kind
                                else loads_strict(
                                    raw, limits=JsonLimits(max_message_bytes=256 * 1024)
                                )
                            )
                            continue
                        run = self.running.get((plugin_id, entry.id))
                        if run is None:
                            run = self._entry(package, entry)
                        if entry.kind == "backend":
                            with self.composition.executing(identity):
                                await run.executor.start()
                        else:
                            await run.executor.start()
                        if not self._current(run):
                            raise LifecycleError("activation changed while starting")
                    self.packages[plugin_id]["coreReady"] = True
                    self.outputs.extend(self.packages[plugin_id]["pendingOutputs"])
                    self.packages[plugin_id]["pendingOutputs"].clear()
                except asyncio.CancelledError:
                    await self._stop_package(plugin_id)
                    raise
                except Exception as exc:  # noqa: BLE001 -- arbitrary plugin activation is isolated
                    await self._stop_package(plugin_id)
                    self.errors[plugin_id] = str(exc)
            if start_only is None:
                self.revision = revision
            indicators = getattr(self.app.state, "indicator_runtime_service", None)
            if indicators is not None:
                for runtime_id, spec in SCRIPT_BUNDLES.items():
                    current = self.running.get((runtime_id, spec.entry))
                    if current is not previous_scripts[runtime_id]:
                        await indicators.refresh_runtime(runtime_id)

    async def _materialize(self, manifest, identity, *, migration=None):
        root, files = await asyncio.to_thread(
            self.store.materialize, identity.package_sha256
        )
        package = {
            "manifest": manifest,
            "identity": identity,
            "root": root,
            "files": files,
            "storage": self.store.private_directory(
                manifest.id,
                migration_generation=migration["generation"] if migration else None,
            ),
            "data": {},
            "coreReady": False,
            "pendingOutputs": collections.deque(maxlen=32),
        }
        self.packages[manifest.id] = package
        if self.bundled_pine and manifest.id == PINE_ID:
            from .pine import import_pine_observations

            await asyncio.to_thread(
                import_pine_observations, package["storage"], os.environ
            )
        self.metadata[identity.package_sha256] = manifest.to_wire()
        return package

    def _entry(self, package, entry):
        identity = package["identity"]
        plugin_id = identity.plugin_id
        run = RunningEntry(identity, entry, uuid.uuid4().hex, None)
        context = OwnedContext(
            self.app,
            identity,
            entry,
            package["root"],
            lambda: self._current(run),
            lambda value: self.publish(run, value),
        )
        context.storage = package["storage"]
        context.trust = package["manifest"].trust
        context.timeout = self.execution_timeout
        context.failure = lambda error: self.entry_failed(plugin_id, error)
        run.executor = (
            BackendEntry(context)
            if entry.kind == "backend"
            else SidecarEntry(context, run.instance, self.executables)
        )
        self.running[(plugin_id, entry.id)] = run
        return run

    def _lock_owner(self):
        if self.owner_lock is not None:
            return
        self.store.snapshot()
        path = self.store.root / "execution.lock"
        self.store._check_path(path)
        lock = security_lock(path, timeout_seconds=0)
        lock.__enter__()
        self.owner_lock = lock

    async def prepare_startup(self, *, recovery_target=None, bundled=None):
        """Load only declared trusted startup hooks before the app builds services."""
        self._lock_owner()
        await asyncio.to_thread(self.store.recover_marketplace)
        if recovery_target is not None:
            self.safe_mode = True
            disabled = await asyncio.to_thread(
                self.store.recover_disable, recovery_target
            )
            print(
                f"[startup] Unified recovery disabled: {', '.join(disabled) or 'already disabled'}"
            )
        bundled = bundled or {}
        self.bundled_pine = PINE_ID in bundled
        if bundled and not self.safe_mode and not self.script_host_disabled:
            from app.plugin_security_v2.errors import PlatformSecurityError

            from .script_runtime import stage_bundled_script

            for runtime_id, descriptor in bundled.items():
                try:
                    await asyncio.to_thread(
                        stage_bundled_script, self, runtime_id, descriptor
                    )
                except (OSError, ValueError, PlatformSecurityError) as exc:
                    self.errors[runtime_id] = str(exc)
        if not self.safe_mode:
            snapshot = await asyncio.to_thread(self.store.snapshot)
            _, plan = await asyncio.to_thread(self.store.execution_plan)
            if sum(len(manifest.entries) for manifest, _ in plan) > 256:
                raise LifecycleError("active execution plan exceeds 256 entries")
            deferred = set()
            for manifest, identity in plan:
                if "marketplace" in snapshot["plugins"].get(manifest.id, {}) or any(
                    dependency in deferred for dependency, _ in manifest.dependencies
                ):
                    deferred.add(manifest.id)
                    continue
                entries = [
                    entry
                    for entry in manifest.entries
                    if entry.kind == "backend" and entry.startup
                ]
                if not entries:
                    continue
                try:
                    self.validate(manifest)
                    if self.composition.interrupted(identity):
                        raise LifecycleError(
                            "previous startup failed; disable or reapprove this activation"
                        )
                    if any(dep in self.errors for dep, _ in manifest.dependencies):
                        raise LifecycleError("startup dependency failed")
                    package = await self._materialize(manifest, identity)
                    for entry in entries:
                        run = self._entry(package, entry)
                        with self.composition.executing(identity):
                            await run.executor.prepare(
                                lambda target, wrapper, run=run: (
                                    self.composition.register(run, target, wrapper)
                                )
                            )
                            if any(
                                target not in self.composition.factories
                                for target in entry.startup
                            ):
                                raise LifecycleError(
                                    "prepare did not register all declared startup factories"
                                )
                    self.prepared[manifest.id] = identity
                except Exception as exc:  # noqa: BLE001 -- use built-ins on prepare failure
                    self.composition.discard(identity)
                    await self._stop_package(manifest.id, shutdown=True)
                    self.attempted[manifest.id] = identity
                    self.errors[manifest.id] = str(exc)
        self.composition.frozen = True
        if not self.safe_mode and not self.script_host_disabled:
            await self.reconcile(start_only=SCRIPT_BUNDLES.keys())

    async def observe_marketplace(self, plugin_id, digest, generation):
        # Data is parsed by the host and sidecars must complete their real
        # activation handshake and remain alive through the observation window.
        async with asyncio.timeout(20):
            await self.reconcile()
            await asyncio.sleep(0.5)
            await self.reconcile()
            async with self.lock:
                package = self.packages.get(plugin_id)
                record = self.store.snapshot()["plugins"].get(plugin_id)
                if (
                    package is None
                    or not package["coreReady"]
                    or package["identity"].package_sha256 != digest
                    or package["identity"].generation != generation
                    or not record
                    or not record["enabled"]
                    or record["generation"] != generation
                    or not self._marketplace_allowed(plugin_id, record)
                    or plugin_id in self.errors
                ):
                    raise LifecycleError(
                        self.errors.get(
                            plugin_id, "marketplace activation is unavailable"
                        )
                    )
                evidence = []
                for entry in package["manifest"].entries:
                    if entry.kind == "sidecar":
                        run = self.running.get((plugin_id, entry.id))
                        if run is None or not self._current(run):
                            raise LifecycleError(
                                f"sidecar failed observation: {entry.id}"
                            )
                    elif entry.id not in package["data"]:
                        raise LifecycleError(
                            f"data entry failed observation: {entry.id}"
                        )
                    evidence.append({"entryId": entry.id, "kind": entry.kind})
                return evidence

    async def start(self):
        self._lock_owner()
        self.ready = True
        self.revision = -1
        await self.reconcile()

        async def watch():
            while self.ready:
                await asyncio.sleep(2)
                try:
                    await self.reconcile()
                except Exception as exc:  # noqa: BLE001 -- preserve management after owner errors
                    self.errors["runtime"] = str(exc)

        self.watcher = asyncio.create_task(watch(), name="unified-plugin-owner")

    async def stop(self):
        if self.watcher:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
            self.watcher = None
        async with self.lock:
            self.ready = False
            for plugin_id in reversed(list(self.packages)):
                await self._stop_package(plugin_id, shutdown=True)
            for (plugin_id, entry_id), value in reversed(list(self.retained.items())):
                try:
                    if entry_id is not None:
                        await bounded(value.executor.stop(), 10)
                except Exception as exc:  # noqa: BLE001 -- continue releasing other entries
                    self.errors[plugin_id] = str(exc)
            for (plugin_id, entry_id), value in self.retained.items():
                if entry_id is None:
                    try:
                        await asyncio.to_thread(
                            self.store.release_materialization,
                            value["root"],
                            value["files"],
                        )
                    except (ValueError, OSError) as exc:
                        self.errors[plugin_id] = str(exc)
            self.retained.clear()
            self.prepared.clear()
            self.composition.factories.clear()
            self.sessions.clear()
            self.expired.clear()
            self.tickets.clear()
            if self.owner_lock:
                self.owner_lock.__exit__(None, None, None)
                self.owner_lock = None

    async def invoke(
        self, plugin_id, entry_id, identity, instance_id, payload, *, chart=False
    ):
        if not all(
            isinstance(value, str) for value in (plugin_id, entry_id, instance_id)
        ):
            raise LifecycleError("invalid invocation identity")
        run = self.running.get((plugin_id, entry_id))
        if (
            run is None
            or not self.packages.get(plugin_id, {}).get("coreReady")
            or run.identity.to_wire() != identity
            or run.instance != instance_id
            or not self._current(run, permission=CHART_PERMISSION if chart else None)
        ):
            raise LifecycleError("entry activation or instance is no longer current")
        task = asyncio.current_task()
        if len(self.calls) >= 128:
            raise LifecycleError("plugin call budget exhausted")
        self.calls[task] = plugin_id
        try:
            execute = run.executor.compute_chart if chart else run.executor.invoke
            result = await execute(normalize_json(payload))
            if not self._current(run):
                raise LifecycleError("late result from a revoked entry")
            return normalize_json(result)
        except Exception as exc:
            if not chart and self._current(run):
                self.entry_failed(plugin_id, exc)
            raise LifecycleError(f"entry invocation failed: {exc}") from exc
        finally:
            self.calls.pop(task, None)

    async def compute_chart(self, target, scope, bars, payload):
        validate_chart_frame(scope, bars)
        if not isinstance(target, dict) or not isinstance(target.get("entryId"), str):
            raise LifecycleError("invalid chart computation target")
        if set(target) == {"sessionId", "frontendInstanceId", "entryId"}:
            origin = self.check_remote(
                target["sessionId"], target["frontendInstanceId"]
            )
            if origin["entry"]["kind"] != "frontend" or origin["state"] != "running":
                raise LifecycleError("chart caller must be an active frontend entry")
            plugin_id, identity = origin["pluginId"], origin["identity"]
            run = self.running.get((plugin_id, target["entryId"]))
            if run is None:
                raise LifecycleError("chart entry is unavailable")
            instance = run.instance
        elif set(target) == {
            "sessionId",
            "pluginId",
            "identity",
            "instanceId",
            "entryId",
        }:
            plugin_id, identity, instance = (
                target["pluginId"],
                target["identity"],
                target["instanceId"],
            )
        else:
            raise LifecycleError("invalid chart computation target")
        if not self._frontend_owns_document(target["sessionId"], scope["documentId"]):
            raise LifecycleError("chart belongs to another window")
        times = {bar["openTimeMs"] for bar in bars}
        result = await self.invoke(
            plugin_id,
            target["entryId"],
            identity,
            instance,
            {"scope": scope, "bars": bars, "input": payload},
            chart=True,
        )
        if "frontendInstanceId" in target:
            self.check_remote(target["sessionId"], target["frontendInstanceId"])
        if not self._frontend_owns_document(target["sessionId"], scope["documentId"]):
            raise LifecycleError("chart document is unavailable")
        validate_chart_result(result, times)
        return {
            "scope": scope,
            "identity": identity,
            "instanceId": instance,
            "result": result,
        }

    def _frontend_owns_document(self, session_id, document_id):
        session = self.sessions.get(("frontend", document_id))
        return bool(
            session
            and session["id"] == session_id
            and time.monotonic() - session["seen"] <= 120
        )

    def _session(self, client_id, realm):
        if (
            not isinstance(realm, str)
            or realm not in {"frontend", "desktop"}
            or not isinstance(client_id, str)
            or not 1 <= len(client_id) <= 128
        ):
            raise LifecycleError("invalid execution realm or client identity")
        now = time.monotonic()
        for key, value in list(self.sessions.items()):
            if now - value["seen"] > 120:
                for item in [*value["entries"].values(), *value["retired"].values()]:
                    self.expired[item["instanceId"]] = {**item, "state": "unavailable"}
                del self.sessions[key]
                self.tickets = {
                    ticket: binding
                    for ticket, binding in self.tickets.items()
                    if binding[1] is not value
                }
        key = (realm, client_id)
        if key not in self.sessions:
            if len(self.sessions) >= 32:
                raise LifecycleError("execution session budget exhausted")
            self.sessions[key] = {
                "id": secrets.token_urlsafe(32),
                "entries": {},
                "retired": {},
                "seen": now,
            }
        session = self.sessions[key]
        if len(self.expired) >= 256:
            raise LifecycleError(
                "unconfirmed execution budget exhausted; restart required"
            )
        if len(session["retired"]) >= 256:
            raise LifecycleError(
                "retired entry budget exhausted; restart this execution realm"
            )
        session["seen"] = now
        return session

    def _session_current(self, session, value):
        package = self.packages.get(value["pluginId"])
        if not package or value["pluginId"] in self.errors or self.safe_mode:
            return False
        record = self.store.snapshot()["plugins"].get(value["pluginId"])
        return bool(
            time.monotonic() - session["seen"] <= 120
            and record
            and record["enabled"]
            and record["generation"] == value["identity"]["generation"]
            and record["packageSha256"] == value["identity"]["packageSha256"]
        )

    def active_appearance(self):
        snapshot = self.store.snapshot()
        selections = snapshot.get("appearance", {})
        result = dict.fromkeys(APPEARANCE_KINDS)
        for kind in APPEARANCE_KINDS:
            plugin_id = selections.get(kind)
            package = self.packages.get(plugin_id)
            if (
                self.safe_mode
                or not package
                or not package["coreReady"]
                or plugin_id in self.errors
            ):
                continue
            record = snapshot["plugins"][plugin_id]
            identity = package["identity"]
            if (
                record["enabled"]
                and self._marketplace_allowed(plugin_id, record)
                and record["generation"] == identity.generation
                and record["packageSha256"] == identity.package_sha256
            ):
                result[kind] = package["data"].get(kind)
        return result

    async def realm_plan(self, client_id, realm):
        await self.reconcile()
        session = self._session(client_id, realm)
        entries = []
        for plugin_id, package in self.packages.items():
            if plugin_id in self.errors:
                continue
            manifest, identity = package["manifest"], package["identity"]
            for entry in manifest.entries:
                if entry.kind != realm and not (
                    realm == "frontend" and entry.kind == "sandbox-view"
                ):
                    continue
                key = f"{plugin_id}/{entry.id}"
                value = session["entries"].get(key)
                if value is None or value["identity"] != identity.to_wire():
                    ticket = secrets.token_urlsafe(32)
                    value = {
                        "pluginId": plugin_id,
                        "entry": entry.to_wire(),
                        "identity": identity.to_wire(),
                        "instanceId": uuid.uuid4().hex,
                        "state": "pending-start",
                        "ticket": ticket,
                    }
                    session["entries"][key] = value
                    self.tickets[ticket] = (plugin_id, session, value)
                item = {
                    **value,
                    "manifest": manifest.to_wire(),
                    "assetBase": f"/api/v2/plugins/unified-assets/{value['ticket']}/",
                }
                item.pop("ticket")
                if realm == "desktop":
                    item.update(
                        root=str(package["root"]),
                        files=package["files"],
                        storage=str(package["storage"]),
                    )
                entries.append(item)
        return {
            "sessionId": session["id"],
            "hostInstance": self.instance,
            "safeMode": self.safe_mode,
            "entries": entries,
            **({"appearance": self.active_appearance()} if realm == "frontend" else {}),
            "errors": dict(self.errors),
        }

    def check_remote(self, session_id, instance_id):
        for session in self.sessions.values():
            if session["id"] == session_id:
                for value in session["entries"].values():
                    if value["instanceId"] == instance_id and self._session_current(
                        session, value
                    ):
                        return value
        raise LifecycleError("entry activation or session is no longer current")

    def report(self, session_id, instance_id, state, error=None):
        if not all(
            isinstance(value, str) for value in (session_id, instance_id, state)
        ) or state not in {"running", "ready", "failed", "pending-restart", "stopped"}:
            raise LifecycleError("invalid entry status")
        for session in self.sessions.values():
            if session["id"] != session_id:
                continue
            for value in session["entries"].values():
                if value["instanceId"] == instance_id and self._session_current(
                    session, value
                ):
                    value["state"] = state
                    value["error"] = str(error or "")[:2048]
                    if state == "failed":
                        self.errors[value["pluginId"]] = (
                            "remote entry failed: " + value["error"]
                        )
                        self.changed = True
                    return
            retired = session["retired"].get(instance_id)
            if retired is not None and state in {"stopped", "pending-restart"}:
                retired["state"] = state
                if state == "stopped":
                    del session["retired"][instance_id]
                return
        raise LifecycleError("entry report belongs to a revoked session or instance")

    def asset(self, ticket, name):
        from candlescope_plugin_sdk.unified.manifest import package_path

        package_path(name)
        binding = self.tickets.get(ticket)
        if binding is None or not self._session_current(binding[1], binding[2]):
            raise LifecycleError("asset activation revoked")
        package = self.packages[binding[0]]
        if name not in package["files"]:
            raise LifecycleError("asset not pinned")
        target = package["root"]
        for part in name.split("/"):
            target = target / part
            if is_link(target):
                raise LifecycleError("asset path was replaced by a link")
        with target.open("rb") as source:
            data = source.read(8 * 1024 * 1024 + 1)
        if (
            len(data) > 8 * 1024 * 1024
            or hashlib.sha256(data).hexdigest() != package["files"][name]
        ):
            raise LifecycleError("asset bytes no longer match approved package")
        return data, binding[2]["entry"]["kind"] == "sandbox-view"

    def catalog(self):
        snapshot = self.store.snapshot()
        plugins = []
        for plugin_id, desired in snapshot["plugins"].items():
            try:
                digest = desired["packageSha256"]
                if digest not in self.metadata:
                    self.metadata[digest] = self.store.review(digest)["manifest"]
                manifest = self.metadata[digest]
            except Exception as exc:  # noqa: BLE001 -- a corrupt package stays individually inspectable
                plugins.append(
                    {
                        "id": plugin_id,
                        "desired": desired,
                        "error": str(exc),
                        "entries": [],
                    }
                )
                continue
            entries = []
            for entry in manifest["entries"]:
                runs = [
                    run
                    for (pid, eid), run in self.running.items()
                    if pid == plugin_id and eid == entry["id"]
                ]
                observed = [
                    {
                        "state": "running",
                        "instanceId": run.instance,
                        "identity": run.identity.to_wire(),
                    }
                    for run in runs
                    if self._current(run) and self.packages[plugin_id]["coreReady"]
                ]
                retained = self.retained.get((plugin_id, entry["id"]))
                if retained is not None:
                    observed.append(
                        {
                            "state": "pending-restart",
                            "instanceId": retained.instance,
                            "identity": retained.identity.to_wire(),
                        }
                    )
                if (
                    entry["kind"] == "data"
                    and plugin_id in self.packages
                    and entry["id"] in self.packages[plugin_id]["data"]
                ):
                    observed.append(
                        {
                            "state": "ready",
                            "identity": self.packages[plugin_id]["identity"].to_wire(),
                            "instanceId": "",
                        }
                    )
                observed += [
                    {key: value[key] for key in ("state", "instanceId", "identity")}
                    for session in self.sessions.values()
                    for value in session["entries"].values()
                    if value["pluginId"] == plugin_id
                    and value["entry"]["id"] == entry["id"]
                    and self._session_current(session, value)
                ]
                observed += [
                    {key: value[key] for key in ("state", "instanceId", "identity")}
                    for session in self.sessions.values()
                    for value in session["retired"].values()
                    if value["pluginId"] == plugin_id
                    and value["entry"]["id"] == entry["id"]
                ]
                if (
                    not observed
                    and desired["enabled"]
                    and "restart required" in self.errors.get(plugin_id, "")
                ):
                    observed = [
                        {
                            "state": "pending-restart",
                            "identity": ActivationIdentity(
                                plugin_id,
                                desired["version"],
                                desired["packageSha256"],
                                desired["generation"],
                            ).to_wire(),
                            "instanceId": "",
                        }
                    ]
                observed += [
                    {
                        "state": "unavailable",
                        "instanceId": value["instanceId"],
                        "identity": value["identity"],
                    }
                    for value in self.expired.values()
                    if value["pluginId"] == plugin_id
                    and value["entry"]["id"] == entry["id"]
                ]
                observed += [
                    {
                        "state": "unavailable",
                        "instanceId": value["instanceId"],
                        "identity": value["identity"],
                    }
                    for session in self.sessions.values()
                    if time.monotonic() - session["seen"] > 120
                    for value in session["entries"].values()
                    if value["pluginId"] == plugin_id
                    and value["entry"]["id"] == entry["id"]
                ]
                entries.append({**entry, "observed": observed})
            plugins.append(
                {
                    "id": plugin_id,
                    "manifest": manifest,
                    "desired": desired,
                    "entries": entries,
                    "error": (
                        "signed marketplace release is unavailable or revoked"
                        if desired["enabled"]
                        and not self._marketplace_allowed(plugin_id, desired)
                        else self.errors.get(plugin_id)
                    ),
                }
            )
        wanted = {record["packageSha256"] for record in snapshot["plugins"].values()}
        self.metadata = {
            key: value for key, value in self.metadata.items() if key in wanted
        }
        orphaned = [
            {
                "pluginId": value["pluginId"],
                "entryId": value["entry"]["id"],
                "state": value["state"],
                "identity": value["identity"],
            }
            for session in self.sessions.values()
            for value in session["retired"].values()
            if value["pluginId"] not in snapshot["plugins"]
        ]
        orphaned.extend(
            {
                "pluginId": plugin_id,
                "entryId": entry_id,
                "state": "pending-restart",
                "identity": run.identity.to_wire(),
            }
            for (plugin_id, entry_id), run in self.retained.items()
            if entry_id is not None and plugin_id not in snapshot["plugins"]
        )
        return {
            "revision": snapshot["revision"],
            "hostInstance": self.instance,
            "safeMode": self.safe_mode,
            "executorsAttached": self.ready,
            "plugins": plugins,
            "orphaned": orphaned,
            "appearance": snapshot.get("appearance", {}),
            "errors": dict(self.errors),
        }
