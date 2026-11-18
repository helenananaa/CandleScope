"""Actual Python modules, JSONL processes and guarded HTTP through the new owner."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.local_data.runtime import LocalOfflineProfileMiddleware
from app.plugin_lifecycle import LifecycleError, PackageStore, build_package
from app.plugin_lifecycle.api import create_unified_router
from app.plugin_lifecycle.bootstrap import (
    activate_unified,
    prepare_unified,
    stop_unified,
)
from app.plugin_lifecycle.runtime import UnifiedRuntime
from app.plugin_security_v2.management import LocalManagementGuard
from app.plugin_security_v2.sandbox import restricted_runtime_profile

WORKER = """import json,sys,os
for line in sys.stdin:
    frame=json.loads(line)
    if frame['method']=='cancel': continue
    params=frame['params']
    result=({'protocol':params['protocol'],'identity':params['identity']} if frame['method']=='activate'
            else {'pid':os.getpid(),'input':params['input']})
    print(json.dumps({'jsonrpc':'2.0','id':frame['id'],'generation':frame['generation'],'result':result}),flush=True)
"""
BACKEND = """def activate(ctx):
    ctx.app.state.log.append(('start', ctx.entry_id))
    ctx.track(lambda: ctx.app.state.log.append(('stop', ctx.entry_id)))
    ctx.publish({'started':ctx.entry_id})
def invoke(ctx, payload):
    return {'entry':ctx.entry_id,'input':payload}
"""


def bundle(
    tmp_path,
    *,
    entries=None,
    assets=None,
    trust="full-trust",
    plugin_id="example.multi",
    version="1.0.0",
    dependencies=None,
):
    folder = tmp_path / uuid.uuid4().hex
    folder.mkdir()
    entries = entries or [{"id": "service", "kind": "backend", "path": "backend.py"}]
    manifest = {
        "schema": "candlescope.unified-plugin/1",
        "id": plugin_id,
        "name": "Multi",
        "version": version,
        "hostApiVersion": 1,
        "trust": trust,
        "entries": entries,
        "dependencies": dependencies or {},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    for name, content in (assets or {"backend.py": BACKEND}).items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    output = tmp_path / (uuid.uuid4().hex + ".cspkg")
    build_package(folder, output)
    return output


def install(store, source):
    package = store.stage(source)
    store.activate(
        package.sha256,
        expected_revision=store.snapshot()["revision"],
        acknowledgement=f"{package.manifest.trust}:{package.sha256}",
    )
    return package


@asynccontextmanager
async def owner(tmp_path, store=None, **kwargs):
    app = SimpleNamespace(state=SimpleNamespace(log=[]))
    runtime = UnifiedRuntime(app, store or PackageStore(tmp_path / "store"), **kwargs)
    try:
        await runtime.start()
        yield runtime, app
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_same_package_runs_two_backend_entries_and_a_real_sidecar(tmp_path):
    entries = [
        {"id": "first", "kind": "backend", "path": "first.py"},
        {"id": "second", "kind": "backend", "path": "second.py"},
        {
            "id": "worker",
            "kind": "sidecar",
            "path": "worker.py",
            "runtime": "python-module",
        },
    ]
    async with owner(tmp_path) as (runtime, app):
        package = install(
            runtime.store,
            bundle(
                tmp_path,
                entries=entries,
                assets={"first.py": BACKEND, "second.py": BACKEND, "worker.py": WORKER},
            ),
        )
        await runtime.reconcile()
        assert app.state.log == [("start", "first"), ("start", "second")]
        assert len(runtime.running) == 3
        assert {run.identity for run in runtime.running.values()} == {
            runtime.store.identity(package.manifest.id)
        }
        for key, run in list(runtime.running.items()):
            result = await runtime.invoke(
                *key, run.identity.to_wire(), run.instance, {"probe": True}
            )
            assert result["input"] == {"probe": True}
        transport = runtime.running[(package.manifest.id, "worker")].executor.transport
        process = transport.process
        runtime.store.disable(package.manifest.id, expected_revision=1)
        await runtime.reconcile()
        assert not runtime.running
        assert process.returncode is not None
        assert app.state.log[-2:] == [("stop", "second"), ("stop", "first")]


@pytest.mark.anyio
async def test_partial_activation_failure_cleans_peers_and_never_offers_remote_entries(
    tmp_path,
):
    entries = [
        {"id": "first", "kind": "backend", "path": "first.py"},
        {"id": "bad", "kind": "backend", "path": "bad.py"},
        {"id": "ui", "kind": "frontend", "path": "ui.mjs"},
    ]
    async with owner(tmp_path) as (runtime, app):
        package = install(
            runtime.store,
            bundle(
                tmp_path,
                entries=entries,
                assets={
                    "first.py": BACKEND,
                    "bad.py": "def activate(ctx):\n    raise RuntimeError('broken-entry')\n",
                    "ui.mjs": "export function activate() {}",
                },
            ),
        )
        await runtime.reconcile()
        assert not runtime.running
        assert app.state.log == [("start", "first"), ("stop", "first")]
        assert "broken-entry" in runtime.errors[package.manifest.id]
        assert not runtime.outputs
        assert (await runtime.realm_plan("window", "frontend"))["entries"] == []
        await runtime.reconcile()
        assert len(app.state.log) == 2  # no automatic retry of arbitrary host code


@pytest.mark.anyio
async def test_unavailable_executor_rejects_whole_package_before_import(tmp_path):
    entries = [
        {"id": "service", "kind": "backend", "path": "backend.py"},
        {"id": "worker", "kind": "sidecar", "path": "app.jar", "runtime": "java-jar"},
    ]
    async with owner(tmp_path, executables={}) as (runtime, app):
        install(
            runtime.store,
            bundle(
                tmp_path,
                entries=entries,
                assets={"backend.py": BACKEND, "app.jar": "unavailable"},
            ),
        )
        await runtime.reconcile()
        assert not app.state.log and not runtime.running
        assert "runtime unavailable" in runtime.errors["example.multi"]


@pytest.mark.anyio
async def test_restricted_sidecar_never_silently_runs_as_full_trust(tmp_path):
    async with owner(tmp_path) as (runtime, _):
        install(
            runtime.store,
            bundle(
                tmp_path,
                trust="restricted",
                entries=[
                    {
                        "id": "worker",
                        "kind": "sidecar",
                        "path": "worker.py",
                        "runtime": "python-module",
                    }
                ],
                assets={"worker.py": WORKER},
            ),
        )
        await runtime.reconcile()
        if runtime.running:
            spec = runtime.running[
                ("example.multi", "worker")
            ].executor.transport.process_spec
            assert spec.trust_level == "untrusted" and spec.sandbox_policy is not None
        else:
            error = runtime.errors["example.multi"].lower()
            assert error
            if not restricted_runtime_profile("python-module").supported():
                assert "qualified isolated runtime" in error


@pytest.mark.anyio
async def test_late_results_and_published_callbacks_are_revoked_before_cleanup(
    tmp_path,
):
    source = (
        BACKEND
        + """
import asyncio
async def invoke(ctx, payload):
    try: await ctx.app.state.release.wait()
    except asyncio.CancelledError: await ctx.app.state.release.wait()
    return 'late'
"""
    )
    async with owner(tmp_path) as (runtime, app):
        app.state.release = asyncio.Event()
        package = install(
            runtime.store, bundle(tmp_path, assets={"backend.py": source})
        )
        await runtime.reconcile()
        run = runtime.running[(package.manifest.id, "service")]
        task = asyncio.create_task(
            runtime.invoke(
                package.manifest.id, "service", run.identity.to_wire(), run.instance, {}
            )
        )
        await asyncio.sleep(0)
        runtime.store.disable(package.manifest.id, expected_revision=1)
        await runtime.reconcile()
        with pytest.raises(LifecycleError, match="revoked"):
            run.executor.context.publish("late publication")
        app.state.release.set()
        with pytest.raises((LifecycleError, asyncio.CancelledError)):
            await task


@pytest.mark.anyio
async def test_host_updates_report_restart_and_process_updates_get_fresh_instances(
    tmp_path,
):
    async with owner(tmp_path) as (runtime, app):
        package = install(runtime.store, bundle(tmp_path))
        await runtime.reconcile()
        install(runtime.store, bundle(tmp_path, version="2.0.0"))
        await runtime.reconcile()
        assert "restart required" in runtime.errors[package.manifest.id]
        assert app.state.log == [("start", "service"), ("stop", "service")]
        assert not runtime.running
    # A fresh process/owner has a new instance and may load the already approved version.
    async with owner(tmp_path, store=runtime.store) as (restarted, app):
        assert app.state.log == [("start", "service")]
        assert (
            restarted.running[(package.manifest.id, "service")].identity.plugin_version
            == "2.0.0"
        )


@pytest.mark.anyio
async def test_safe_mode_and_process_ownership_prevent_duplicate_execution(tmp_path):
    store = PackageStore(tmp_path / "store")
    install(store, bundle(tmp_path))
    async with owner(tmp_path, store=store, safe_mode=True) as (runtime, app):
        assert not runtime.running and not app.state.log
        other = UnifiedRuntime(app, store)
        with pytest.raises(Exception, match="lock"):
            await other.start()
        await other.stop()
        assert (await runtime.realm_plan("window", "frontend"))["entries"] == []


@pytest.mark.anyio
async def test_remote_instances_are_independent_and_revoked_assets_cannot_be_used(
    tmp_path,
):
    entries = [
        {"id": "ui", "kind": "frontend", "path": "ui.mjs"},
        {"id": "desktop", "kind": "desktop", "path": "desktop.mjs"},
    ]
    async with owner(tmp_path) as (runtime, _):
        package = install(
            runtime.store,
            bundle(
                tmp_path,
                entries=entries,
                assets={
                    "ui.mjs": "export function activate() {}",
                    "desktop.mjs": "export function activate() {}",
                },
            ),
        )
        one = await runtime.realm_plan("window-a", "frontend")
        two = await runtime.realm_plan("window-b", "frontend")
        desktop = await runtime.realm_plan("desktop", "desktop")
        assert (
            len(one["entries"]) == len(two["entries"]) == len(desktop["entries"]) == 1
        )
        first = one["entries"][0]
        assert (
            first["identity"]
            == two["entries"][0]["identity"]
            == desktop["entries"][0]["identity"]
        )
        assert first["instanceId"] != two["entries"][0]["instanceId"]
        with pytest.raises(LifecycleError):
            runtime.report(two["sessionId"], first["instanceId"], "running")
        ticket = first["assetBase"].split("/")[-2]
        assert runtime.asset(ticket, "ui.mjs")[0].startswith(b"export")
        runtime.store.disable(package.manifest.id, expected_revision=1)
        with pytest.raises(LifecycleError):
            runtime.asset(ticket, "ui.mjs")
        with pytest.raises(LifecycleError):
            runtime.report(one["sessionId"], first["instanceId"], "running")


@pytest.mark.anyio
async def test_guarded_http_lifecycle_uses_actual_bootstrap_and_rejects_stale_instances(
    tmp_path,
):
    app = FastAPI()
    app.state.log = []
    app.include_router(create_unified_router())
    store = PackageStore(tmp_path / "store")
    prepare_unified(app, store=store)
    guard = LocalManagementGuard(["http://127.0.0.1:15173"])
    app.state.trusted_extension_management_guard = guard
    await activate_unified(app)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
            base_url="http://127.0.0.1:18080",
        ) as client:
            base = "/api/v2/plugins/manage/unified"
            assert (await client.get(base)).status_code == 403
            headers = guard.trusted_headers(user_action="unified-test")
            source = bundle(tmp_path)
            review = (
                await client.post(
                    base + "/stage", content=source.read_bytes(), headers=headers
                )
            ).json()
            digest = review["packageSha256"]
            response = await client.post(
                base + "/change",
                json={
                    "action": "activate",
                    "digest": digest,
                    "revision": 0,
                    "acknowledgement": "full-trust:" + digest,
                },
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert app.state.log == [("start", "service")]
            entry = response.json()["catalog"]["plugins"][0]["entries"][0]["observed"][
                0
            ]
            call = {
                "pluginId": "example.multi",
                "entryId": "service",
                "identity": entry["identity"],
                "instanceId": entry["instanceId"],
                "input": {"ok": 1},
            }
            assert (
                await client.post(base + "/invoke", json=call, headers=headers)
            ).json()["result"]["input"] == {"ok": 1}
            rejected = await client.post(
                base + "/change",
                json={"action": "disable", "id": "example.multi", "revision": 0},
                headers=headers,
            )
            assert rejected.status_code == 409
            assert (
                await client.post(
                    base + "/change",
                    json={"action": "disable", "id": "example.multi", "revision": 1},
                    headers=headers,
                )
            ).status_code == 200
            assert (
                await client.post(base + "/invoke", json=call, headers=headers)
            ).status_code == 409
            forwarded = {**headers, "X-Forwarded-For": "127.0.0.1"}
            assert (await client.get(base, headers=forwarded)).status_code == 403
    finally:
        await stop_unified(app)


@pytest.mark.anyio
async def test_async_activation_timeout_cleans_a_late_returned_resource(tmp_path):
    source = """import asyncio
async def activate(ctx):
    try: await ctx.app.state.release.wait()
    except asyncio.CancelledError: await ctx.app.state.release.wait()
    return lambda: ctx.app.state.log.append('late-cleanup')
"""
    async with owner(tmp_path, execution_timeout=0.02) as (runtime, app):
        app.state.release = asyncio.Event()
        install(runtime.store, bundle(tmp_path, assets={"backend.py": source}))
        starting = asyncio.create_task(runtime.reconcile())
        done, _ = await asyncio.wait({starting}, timeout=1)
        app.state.release.set()
        await starting
        assert done, "coordinator waited indefinitely for cancelled activation"
        for _ in range(20):
            if "late-cleanup" in app.state.log:
                break
            await asyncio.sleep(0)
        assert app.state.log == ["late-cleanup"]
        assert not runtime.running
        assert "timed out" in runtime.errors["example.multi"]


@pytest.mark.anyio
async def test_worker_exit_stops_peers_and_is_not_reported_as_running(tmp_path):
    entries = [
        {"id": "service", "kind": "backend", "path": "backend.py"},
        {
            "id": "worker",
            "kind": "sidecar",
            "path": "worker.py",
            "runtime": "python-module",
        },
    ]
    async with owner(tmp_path) as (runtime, app):
        install(
            runtime.store,
            bundle(
                tmp_path,
                entries=entries,
                assets={"backend.py": BACKEND, "worker.py": WORKER},
            ),
        )
        await runtime.reconcile()
        worker = runtime.running[("example.multi", "worker")].executor.transport.process
        worker.kill()
        await worker.wait()
        await runtime.reconcile()
        assert not runtime.running
        assert app.state.log[-1] == ("stop", "service")
        assert "sidecar exited" in runtime.errors["example.multi"]


@pytest.mark.anyio
async def test_owned_background_failure_revokes_the_package(tmp_path):
    source = (
        BACKEND
        + """\nimport asyncio
def activate(ctx):
    async def work():
        await ctx.app.state.release.wait()
        raise RuntimeError('owned task failed')
    ctx.task(work())
"""
    )
    async with owner(tmp_path) as (runtime, app):
        app.state.release = asyncio.Event()
        install(runtime.store, bundle(tmp_path, assets={"backend.py": source}))
        await runtime.reconcile()
        app.state.release.set()
        for _ in range(20):
            if "example.multi" in runtime.errors:
                break
            await asyncio.sleep(0)
        await runtime.reconcile()
        assert not runtime.running
        assert "owned task failed" in runtime.errors["example.multi"]


@pytest.mark.anyio
async def test_node_desktop_and_backend_consume_one_owner_over_real_http(tmp_path):
    import uvicorn

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed on this runner")
    app = FastAPI()
    app.state.log = []
    app.include_router(create_unified_router())
    store = PackageStore(tmp_path / "store")
    desktop = """import {writeFile} from 'node:fs/promises';
import path from 'node:path';
export async function activate(ctx) {
  ctx.host.events.push(['start',ctx.entryId,ctx.identity.generation]);
  await writeFile(path.join(ctx.storage,'desktop-note.txt'),'preserve');
  ctx.track(()=>ctx.host.events.push(['stop',ctx.entryId]));
}
"""
    entries = [
        {"id": "service", "kind": "backend", "path": "backend.py"},
        {"id": "desktop", "kind": "desktop", "path": "desktop.mjs"},
    ]
    package = install(
        store,
        bundle(
            tmp_path,
            entries=entries,
            assets={"backend.py": BACKEND, "desktop.mjs": desktop},
        ),
    )
    prepare_unified(app, store=store)
    guard = LocalManagementGuard(["http://127.0.0.1:15173"])
    app.state.trusted_extension_management_guard = guard

    @asynccontextmanager
    async def lifespan(application):
        await activate_unified(application)
        try:
            yield
        finally:
            await stop_unified(application)

    app.router.lifespan_context = lifespan
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    process = None
    try:
        for _ in range(500):
            if server.started:
                break
            if serving.done():
                await serving
            await asyncio.sleep(0.01)
        assert server.started
        fixture = (
            Path(__file__).resolve().parents[2]
            / "frontend/tests/fixtures/unified-runtime-client.mjs"
        )
        process = await asyncio.create_subprocess_exec(
            node,
            str(fixture),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def command(message):
            process.stdin.write((json.dumps(message) + "\n").encode())
            await process.stdin.drain()
            return json.loads(await asyncio.wait_for(process.stdout.readline(), 10))

        base = f"http://127.0.0.1:{port}/api/v2/plugins/manage/unified"
        response = await command(
            {"action": "start", "base": base, "headers": guard.trusted_headers()}
        )
        assert response["events"] == [["start", "desktop", 1]]
        observed = response["diagnostics"]["active"][0]
        runtime = app.state.unified_plugin_runtime
        assert (
            observed["identity"]
            == runtime.running[(package.manifest.id, "service")].identity.to_wire()
        )
        assert app.state.log == [("start", "service")]
        async with httpx.AsyncClient() as client:
            result = await client.post(
                base + "/change",
                headers=guard.trusted_headers(user_action="disable-test"),
                json={"action": "disable", "id": package.manifest.id, "revision": 1},
            )
            assert result.status_code == 200, result.text
            assert (
                result.json()["catalog"]["plugins"][0]["entries"][1]["observed"][0][
                    "state"
                ]
                == "pending-stop"
            )
        stopped = await command({"action": "refresh"})
        assert stopped["diagnostics"]["active"] == []
        assert stopped["events"][-1] == ["stop", "desktop"]
        assert (
            runtime.catalog()["plugins"][0]["entries"][1]["observed"][0]["state"]
            == "pending-restart"
        )
        store.uninstall(package.manifest.id, expected_revision=2)
        await runtime.reconcile()
        assert runtime.catalog()["orphaned"][0]["pluginId"] == package.manifest.id
        assert (
            store.private_directory(package.manifest.id) / "desktop-note.txt"
        ).read_text() == "preserve"
        await command({"action": "stop"})
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 5)
        assert process.returncode == 0
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()


@pytest.mark.anyio
async def test_uninstall_keeps_private_data_and_unrecognized_execution_files(tmp_path):
    source = (
        BACKEND
        + """
def activate(ctx):
    (ctx.storage / 'private-note.txt').write_text('keep-private')
    (ctx.root / 'user-note.txt').write_text('keep-extra')
"""
    )
    async with owner(tmp_path) as (runtime, _):
        package = install(
            runtime.store, bundle(tmp_path, assets={"backend.py": source})
        )
        await runtime.reconcile()
        root = runtime.packages[package.manifest.id]["root"]
        runtime.store.uninstall(package.manifest.id, expected_revision=1)
        await runtime.reconcile()
        assert (root / "user-note.txt").read_text() == "keep-extra"
        assert not (root / "backend.py").exists()
        assert (
            runtime.store.private_directory(package.manifest.id) / "private-note.txt"
        ).read_text() == "keep-private"


@pytest.mark.anyio
async def test_expired_session_is_unknown_not_falsely_reported_stopped(tmp_path):
    async with owner(tmp_path) as (runtime, _):
        install(
            runtime.store,
            bundle(
                tmp_path,
                entries=[{"id": "ui", "kind": "frontend", "path": "ui.mjs"}],
                assets={"ui.mjs": "export function activate() {}"},
            ),
        )
        plan = await runtime.realm_plan("window", "frontend")
        first = plan["entries"][0]
        runtime.report(plan["sessionId"], first["instanceId"], "running")
        runtime.sessions[("frontend", "window")]["seen"] -= 121
        assert (
            runtime.catalog()["plugins"][0]["entries"][0]["observed"][0]["state"]
            == "unavailable"
        )
        new_plan = await runtime.realm_plan("window", "frontend")
        assert new_plan["entries"][0]["instanceId"] != first["instanceId"]
        with pytest.raises(LifecycleError):
            runtime.report(plan["sessionId"], first["instanceId"], "running")


@pytest.mark.anyio
async def test_restricted_view_serves_opaque_assets_and_revokes_tickets(tmp_path):
    app = FastAPI()
    app.include_router(create_unified_router())
    app.add_middleware(LocalOfflineProfileMiddleware, enabled=True)
    store = PackageStore(tmp_path / "store")
    package = install(
        store,
        bundle(
            tmp_path,
            trust="restricted",
            entries=[
                {"id": "view", "kind": "sandbox-view", "path": "index.html"},
                {"id": "config", "kind": "data", "path": "config.json"},
            ],
            assets={"index.html": "<p>Isolated</p>", "config.json": '{"value":42}'},
        ),
    )
    prepare_unified(app, store=store)
    guard = LocalManagementGuard(["http://127.0.0.1:15173"])
    app.state.trusted_extension_management_guard = guard
    await activate_unified(app)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
            base_url="http://127.0.0.1:18080",
        ) as client:
            base = "/api/v2/plugins/manage/unified"
            assert (await client.get(base)).status_code == 403
            catalog = await client.get(base, headers=guard.trusted_headers())
            assert catalog.status_code == 200
            online = await client.get(
                "/api/v2/plugins/manage/catalog", headers=guard.trusted_headers()
            )
            assert online.json()["detail"]["code"] == "offline_profile_boundary"
            plan = (
                await client.post(
                    base + "/realm",
                    headers=guard.trusted_headers(),
                    json={"clientId": "window", "realm": "frontend"},
                )
            ).json()
            item = plan["entries"][0]
            assert item["entry"]["kind"] == "sandbox-view"
            response = await client.get(item["assetBase"] + "index.html")
            assert response.status_code == 200
            assert (
                "sandbox allow-scripts" in response.headers["Content-Security-Policy"]
            )
            assert "connect-src 'none'" in response.headers["Content-Security-Policy"]
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert (
                app.state.unified_plugin_runtime.catalog()["plugins"][0]["entries"][1][
                    "observed"
                ][0]["state"]
                == "ready"
            )
            store.disable(package.manifest.id, expected_revision=1)
            assert (
                await client.get(item["assetBase"] + "index.html")
            ).status_code == 404
    finally:
        await stop_unified(app)


@pytest.mark.anyio
async def test_startup_claim_is_frozen_and_retained_until_consumers_stop(tmp_path):
    from app.plugin_lifecycle.composition import startup_factory

    store = PackageStore(tmp_path / "store")
    entries = [
        {
            "id": "service",
            "kind": "backend",
            "path": "backend.py",
            "startup": ["replay"],
        }
    ]
    source = """
def prepare(ctx):
    ctx.app.state.log.append('prepare')
    ctx.track(lambda: ctx.app.state.log.append('released'))
    async def wrap(default):
        consumer = await default()
        consumer['dependency'] = ctx.id
        return consumer
    ctx.wrap_factory('replay', wrap)
def activate(ctx):
    ctx.app.state.log.append('activate')
"""
    package = install(
        store, bundle(tmp_path, entries=entries, assets={"backend.py": source})
    )
    conflict = store.stage(
        bundle(
            tmp_path,
            entries=entries,
            assets={"backend.py": source},
            plugin_id="example.other",
        )
    )
    with pytest.raises(ValueError, match="startup target replay claimed"):
        store.activate(
            conflict.sha256,
            expected_revision=1,
            acknowledgement=f"full-trust:{conflict.sha256}",
        )

    app = SimpleNamespace(state=SimpleNamespace(log=[]))
    runtime = UnifiedRuntime(app, store)
    app.state.unified_plugin_runtime = runtime
    try:
        await runtime.prepare_startup()

        async def default():
            assert app.state.log == ["prepare"]
            return {"dependency": "builtin"}

        built = await startup_factory(app, "replay", default)()
        assert built["dependency"] == package.manifest.id
        await runtime.start()
        assert app.state.log == ["prepare", "activate"]
        store.disable(package.manifest.id, expected_revision=1)
        await runtime.reconcile()
        assert not runtime.running
        assert app.state.log == ["prepare", "activate"]
        assert (
            runtime.catalog()["plugins"][0]["entries"][0]["observed"][0]["state"]
            == "pending-restart"
        )
    finally:
        await runtime.stop()
    assert app.state.log == ["prepare", "activate", "released"]


@pytest.mark.anyio
async def test_interrupted_factory_and_independent_disable_keep_package_data(tmp_path):
    from app.plugin_lifecycle.composition import startup_factory

    store = PackageStore(tmp_path / "store")
    entries = [
        {
            "id": "service",
            "kind": "backend",
            "path": "backend.py",
            "startup": ["replay"],
        }
    ]
    source = """
def prepare(ctx):
    def fail(default):
        raise RuntimeError('simulated startup failure')
    ctx.wrap_factory('replay', fail)
def activate(ctx):
    pass
"""
    bad = install(
        store, bundle(tmp_path, entries=entries, assets={"backend.py": source})
    )
    child = install(
        store,
        bundle(
            tmp_path, plugin_id="example.child", dependencies={bad.manifest.id: "1.0.0"}
        ),
    )
    private = store.private_directory(bad.manifest.id) / "script.pine"
    private.write_text("preserve this script")
    app = SimpleNamespace(state=SimpleNamespace())
    runtime = UnifiedRuntime(app, store)
    app.state.unified_plugin_runtime = runtime
    try:
        await runtime.prepare_startup()
        with pytest.raises(RuntimeError, match="simulated startup failure"):
            startup_factory(app, "replay", object)()
    finally:
        await runtime.stop()

    retry = UnifiedRuntime(app, store)
    try:
        await retry.prepare_startup()
        assert "previous startup failed" in retry.errors[bad.manifest.id]
        assert not retry.composition.factories
    finally:
        await retry.stop()

    recovery = UnifiedRuntime(app, store)
    try:
        await recovery.prepare_startup(recovery_target=bad.manifest.id)
        await recovery.start()
        assert recovery.safe_mode and not recovery.running
        assert {
            key
            for key, record in store.snapshot()["plugins"].items()
            if not record["enabled"]
        } == {
            bad.manifest.id,
            child.manifest.id,
        }
        assert private.read_text() == "preserve this script"
        assert store.review(bad.sha256)["packageSha256"] == bad.sha256
    finally:
        await recovery.stop()
