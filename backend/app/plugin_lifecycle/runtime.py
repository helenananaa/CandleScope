"""Unified desired/actual coordination for backend, sidecar and remote realms."""

from __future__ import annotations

import asyncio
import collections
import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass

from candlescope_plugin_sdk.platform_v2 import canonical_dumps, normalize_json
from candlescope_plugin_sdk.unified import ActivationIdentity, Entry

from app.plugin_security_v2.sandbox import restricted_runtime_profile
from app.plugin_security_v2.storage import security_lock

from .executors import (
    BackendEntry,
    OwnedContext,
    SidecarEntry,
    bounded,
    default_executables,
)
from .paths import is_link
from .store import LifecycleError, PackageStore


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

    def _current(self, run):
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
            and record["generation"] == run.identity.generation
            and record["packageSha256"] == run.identity.package_sha256
            and run.identity.plugin_id not in self.errors
        )

    def validate(self, manifest):
        if manifest.trust == "restricted" and manifest.permissions:
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

    async def _stop_package(self, plugin_id):
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
        for task, owner in list(self.calls.items()):
            if owner == plugin_id and task is not asyncio.current_task():
                task.cancel()
        for run in reversed(runs):
            self.running.pop((plugin_id, run.entry.id), None)
            try:
                await bounded(run.executor.stop(), 10)
            except Exception as exc:  # noqa: BLE001 -- arbitrary plugin cleanup is isolated
                self.quarantined.add(plugin_id)
                self.errors[plugin_id] = f"cleanup failed; restart required: {exc}"
        package = self.packages.pop(plugin_id, None)
        if package:
            try:
                await asyncio.to_thread(
                    self.store.release_materialization,
                    package["root"],
                    package["files"],
                )
            except (ValueError, OSError) as exc:
                self.errors[plugin_id] = f"execution files retained for recovery: {exc}"

    async def reconcile(self):
        async with self.lock:
            snapshot = await asyncio.to_thread(self.store.snapshot)
            for run in self.running.values():
                if run.entry.kind == "sidecar" and not self._current(run):
                    self.errors[run.identity.plugin_id] = (
                        "sidecar exited or lost its activation"
                    )
                    self.changed = True
            if snapshot["revision"] == self.revision and not self.changed:
                return
            self.changed = False
            revision, plan = await asyncio.to_thread(self.store.execution_plan)
            desired = (
                {}
                if self.safe_mode
                else {manifest.id: (manifest, identity) for manifest, identity in plan}
            )
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
            if not self.ready:
                return
            total_entries = sum(
                len(manifest.entries) for manifest, _ in desired.values()
            )
            if total_entries > 256:
                self.revision = revision
                raise LifecycleError("active execution plan exceeds 256 entries")
            for plugin_id, (manifest, identity) in desired.items():
                if plugin_id in self.packages:
                    continue
                if (
                    self.attempted.get(plugin_id) == identity
                    and plugin_id in self.errors
                ):
                    continue
                self.attempted[plugin_id] = identity
                self.errors.pop(plugin_id, None)
                try:
                    self.validate(manifest)
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
                    root, files = await asyncio.to_thread(
                        self.store.materialize, identity.package_sha256
                    )
                    self.packages[plugin_id] = {
                        "manifest": manifest,
                        "identity": identity,
                        "root": root,
                        "files": files,
                        "storage": self.store.private_directory(plugin_id),
                        "data": {},
                        "coreReady": False,
                        "pendingOutputs": collections.deque(maxlen=32),
                    }
                    self.metadata[identity.package_sha256] = manifest.to_wire()
                    for entry in manifest.entries:
                        if entry.kind not in {"backend", "sidecar", "data"}:
                            continue
                        if entry.kind == "data":
                            from candlescope_plugin_sdk.platform_v2 import (
                                JsonLimits,
                                loads_strict,
                            )

                            with (root / entry.path).open("rb") as content:
                                self.packages[plugin_id]["data"][entry.id] = (
                                    loads_strict(
                                        content.read(256 * 1024 + 1),
                                        limits=JsonLimits(max_message_bytes=256 * 1024),
                                    )
                                )
                            continue
                        instance = uuid.uuid4().hex
                        run = RunningEntry(identity, entry, instance, None)
                        context = OwnedContext(
                            self.app,
                            identity,
                            entry,
                            root,
                            lambda run=run: self._current(run),
                            lambda value, run=run: self.publish(run, value),
                        )
                        context.storage = self.packages[plugin_id]["storage"]
                        context.trust = manifest.trust
                        context.timeout = self.execution_timeout
                        context.failure = lambda error, pid=plugin_id: (
                            self.entry_failed(pid, error)
                        )
                        run.executor = (
                            BackendEntry(context)
                            if entry.kind == "backend"
                            else SidecarEntry(context, instance, self.executables)
                        )
                        self.running[(plugin_id, entry.id)] = run
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
            self.revision = revision

    async def start(self):
        self.store.snapshot()
        path = self.store.root / "execution.lock"
        self.store._check_path(path)
        lock = security_lock(path, timeout_seconds=0)
        lock.__enter__()
        self.owner_lock = lock
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
                await self._stop_package(plugin_id)
            self.sessions.clear()
            self.expired.clear()
            self.tickets.clear()
            if self.owner_lock:
                self.owner_lock.__exit__(None, None, None)
                self.owner_lock = None

    async def invoke(self, plugin_id, entry_id, identity, instance_id, payload):
        if not all(
            isinstance(value, str) for value in (plugin_id, entry_id, instance_id)
        ):
            raise LifecycleError("invalid invocation identity")
        run = self.running.get((plugin_id, entry_id))
        if (
            run is None
            or run.identity.to_wire() != identity
            or run.instance != instance_id
            or not self._current(run)
        ):
            raise LifecycleError("entry activation or instance is no longer current")
        task = asyncio.current_task()
        if len(self.calls) >= 128:
            raise LifecycleError("plugin call budget exhausted")
        self.calls[task] = plugin_id
        try:
            result = await run.executor.invoke(normalize_json(payload))
            if not self._current(run):
                raise LifecycleError("late result from a revoked entry")
            return normalize_json(result)
        except Exception as exc:
            if self._current(run):
                self.entry_failed(plugin_id, exc)
            self.changed = True
            raise LifecycleError(f"entry invocation failed: {exc}") from exc
        finally:
            self.calls.pop(task, None)

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
            "errors": dict(self.errors),
        }

    def check_remote(self, session_id, instance_id):
        for session in self.sessions.values():
            if session["id"] == session_id:
                for value in session["entries"].values():
                    if value["instanceId"] == instance_id and self._session_current(
                        session, value
                    ):
                        return
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
                    if self._current(run)
                ]
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
                    "error": self.errors.get(plugin_id),
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
        return {
            "revision": snapshot["revision"],
            "hostInstance": self.instance,
            "safeMode": self.safe_mode,
            "executorsAttached": self.ready,
            "plugins": plugins,
            "orphaned": orphaned,
            "errors": dict(self.errors),
        }
