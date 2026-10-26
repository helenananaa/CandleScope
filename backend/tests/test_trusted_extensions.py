from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from app.plugin_core_v2.runtime import CorePluginPlatform
from app.plugin_security_v2.management import LocalManagementGuard
from app.trusted_extensions.api import create_extension_router
from app.trusted_extensions.runtime import ExtensionHost, HostContext, extension_factory
from app.plugin_security_v2.storage import atomic_write_json
from app.trusted_extensions.store import ExtensionStore


def bundle(*, extension_id="example.skin", version="1.0.0", entries=None, extra=None, **fields):
    manifest = {"schema": "candlescope.extension/1", "id": extension_id,
                "name": "Example", "version": version, "apiVersion": 1,
                "trust": "full-trust" if entries else "theme",
                "theme": {"base": "light", "tokens": {"bg-primary": "#ffffff"}}, **fields}
    if entries:
        manifest["entries"] = entries
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extension.json", json.dumps(manifest))
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    data = stream.getvalue()
    # ZipInfo normalizes Windows separators; preserve malicious wire names for validation.
    for name in extra or {}:
        if "\\" in name:
            data = data.replace(name.replace("\\", "/").encode(), name.encode())
    return data


def enable(store, data):
    review = store.stage(data)
    store.change("activate", review["manifest"]["id"], review["digest"],
                 f"{review['manifest']['trust']}:{review['digest']}")
    return review


def test_stage_is_inert_and_approval_is_bound_to_package_and_trust(tmp_path):
    store = ExtensionStore(tmp_path)
    review = store.stage(bundle(entries={"frontend": "main.mjs"}, extra={"main.mjs": "throw new Error('not executed')"}))
    assert store.plan()["active"] == []
    with pytest.raises(ValueError, match="Approval"):
        store.change("activate", "example.skin", review["digest"], "full-trust:wrong-digest")
    with pytest.raises(ValueError, match="Approval"):
        store.change("activate", "example.skin", review["digest"], f"theme:{review['digest']}")
    assert store.plan()["active"] == []


@pytest.mark.parametrize("filename", ["../outside.txt", "/absolute.txt", "C:/outside.txt", "a/../../outside", "a\\b", "NUL.txt", "a/CON", "a./b"])
def test_rejects_unsafe_archive_paths(tmp_path, filename):
    with pytest.raises(ValueError):
        ExtensionStore(tmp_path).stage(bundle(extra={filename: "unsafe"}))
    assert not (tmp_path / "outside.txt").exists()


def test_data_themes_cannot_request_code_or_css_injection(tmp_path):
    store = ExtensionStore(tmp_path)
    with pytest.raises(ValueError, match="full-trust"):
        store.stage(bundle(entries={"frontend": "main.mjs"}, extra={"main.mjs": ""}, trust="theme"))
    with pytest.raises(ValueError):
        store.stage(bundle(theme={"base": "dark", "tokens": {"bg-primary": "red; } body { display:none"}}))


def test_asset_ticket_survives_theme_switch_but_not_disable_reenable(tmp_path):
    store = ExtensionStore(tmp_path)
    review = enable(store, bundle(extra={"note.txt": "hello"}))
    plan = store.plan()
    ticket = plan["active"][0]["assetBase"].split("/")[-2]
    assert store.asset(ticket, "note.txt") == b"hello"
    store.change("theme", "example.skin")
    assert store.asset(ticket, "note.txt") == b"hello"
    store.change("disable", "example.skin")
    with pytest.raises(ValueError):
        store.asset(ticket, "note.txt")
    store.change("activate", "example.skin", review["digest"], f"theme:{review['digest']}")
    with pytest.raises(ValueError):
        store.asset(ticket, "note.txt")
    assert store.catalog()["theme"] is None


def test_integrity_and_explicit_rollback(tmp_path):
    store = ExtensionStore(tmp_path)
    first = enable(store, bundle())
    second = enable(store, bundle(version="2.0.0"))
    assert first["digest"] in store.catalog()["plugins"][0]["history"]
    store.change("activate", "example.skin", first["digest"], f"theme:{first['digest']}")
    assert store.plan()["active"][0]["manifest"]["version"] == "1.0.0"
    store._archive(first["digest"]).write_bytes(store._archive(second["digest"]).read_bytes())
    assert "integrity" in store.catalog()["plugins"][0]["error"]
    assert store.plan()["active"] == []


def test_dependencies_block_disable_and_incompatible_upgrade(tmp_path):
    store = ExtensionStore(tmp_path)
    dependent = bundle(extension_id="example.child", dependencies={"example.skin": "1.0.0"})
    with pytest.raises(ValueError, match="dependency"):
        enable(store, dependent)
    enable(store, bundle())
    enable(store, dependent)
    assert [item["manifest"]["id"] for item in store.plan()["active"]] == ["example.skin", "example.child"]
    with pytest.raises(ValueError, match="dependent"):
        store.change("disable", "example.skin")
    with pytest.raises(ValueError, match="dependent"):
        enable(store, bundle(version="2.0.0"))
    store.change("disable-all", "")
    assert store.plan()["active"] == []


@pytest.mark.anyio
async def test_python_host_prepare_activate_cleanup_and_safe_boot(tmp_path, monkeypatch):
    store = ExtensionStore(tmp_path)
    app = SimpleNamespace(state=SimpleNamespace(service="original"))
    enable(store, bundle(entries={"backend": "main.py"}, extra={"main.py":
        "def prepare(ctx):\n    ctx.replace_service('service', 'prepared')\n"
        "def activate(ctx):\n    ctx.replace_service('service', 'active')\n"}))
    host = ExtensionHost(app, store)
    await host.prepare()
    assert app.state.service == "prepared"
    await host.activate()
    assert app.state.service == "active"
    await host.stop()
    assert app.state.service == "original"
    monkeypatch.setenv("CANDLESCOPE_EXTENSIONS_SAFE_MODE", "1")
    host = ExtensionHost(app, store)
    await host.prepare()
    assert host.loaded == []


@pytest.mark.anyio
async def test_python_entry_supports_relative_modules_and_dataclasses(tmp_path):
    store = ExtensionStore(tmp_path)
    app = SimpleNamespace(state=SimpleNamespace())
    review = enable(store, bundle(entries={"backend": "main.py"}, extra={
        "main.py": "from dataclasses import dataclass\nfrom .helper import VALUE\n@dataclass\nclass Probe:\n    value: int\ndef activate(ctx):\n    ctx.replace_service('probe', Probe(VALUE))\n",
        "helper.py": "VALUE = 42\n",
    }))
    host = ExtensionHost(app, store)
    await host.prepare()
    await host.activate()
    assert not host.errors
    assert app.state.probe.value == 42
    namespace = f"candlescope_extension_{review['digest']}"
    assert namespace + ".helper" in sys.modules
    await host.stop()
    assert not any(name == namespace or name.startswith(namespace + ".") for name in sys.modules)


@pytest.mark.anyio
async def test_failed_activation_releases_registered_services(tmp_path):
    store = ExtensionStore(tmp_path)
    app = SimpleNamespace(state=SimpleNamespace())
    enable(store, bundle(entries={"backend": "main.py"}, extra={"main.py":
        "def activate(ctx):\n    ctx.replace_service('probe', 1)\n    raise RuntimeError('broken extension')\n"}))
    host = ExtensionHost(app, store)
    await host.prepare()
    await host.activate()
    assert "broken extension" in host.errors["example.skin"]
    assert not hasattr(app.state, "probe")


@pytest.mark.anyio
async def test_service_factory_wraps_real_composition_and_conflicts_are_explicit(tmp_path):
    app = SimpleNamespace(state=SimpleNamespace())
    first = HostContext(app, "example.first", tmp_path)
    second = HostContext(app, "example.second", tmp_path)
    first.wrap_factory("data-engine", lambda default, value: default(value) + 1)
    assert extension_factory(app, "data-engine", lambda value: value * 2)(3) == 7
    with pytest.raises(ValueError, match="already replaced"):
        second.wrap_factory("data-engine", lambda default: default())
    await first.dispose()
    assert extension_factory(app, "data-engine", lambda value: value * 2)(3) == 6


@pytest.mark.anyio
async def test_crash_marker_blocks_only_the_interrupted_activation(tmp_path):
    store = ExtensionStore(tmp_path)
    data = bundle(entries={"backend": "main.py"}, extra={"main.py": "def activate(ctx):\n    ctx.replace_service('probe', 1)\n"})
    review = enable(store, data)
    record = store.catalog()["plugins"][0]
    marker = {"digest": record["digest"], "generation": record["generation"]}
    atomic_write_json(store.root / "backend-loading.json", marker)
    app = SimpleNamespace(state=SimpleNamespace())
    host = ExtensionHost(app, store)
    await host.prepare()
    assert not host.loaded
    store.change("activate", "example.skin", review["digest"], f"full-trust:{review['digest']}")
    restarted = ExtensionHost(app, store)
    await restarted.prepare()
    await restarted.activate()
    assert app.state.probe == 1
    await restarted.stop()


@pytest.mark.anyio
async def test_management_guard_and_asset_revocation_end_to_end(tmp_path):
    app = FastAPI()
    platform = object.__new__(CorePluginPlatform)
    platform.root = tmp_path
    app.state.plugin_platform_v2 = platform
    guard = LocalManagementGuard(["http://127.0.0.1:15173"])
    app.state.plugin_platform_v2_management_guard = guard
    app.include_router(create_extension_router())
    transport = httpx.ASGITransport(app, client=("127.0.0.1", 20000))
    base = "/api/v2/plugins/manage/extensions"
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:18080") as client:
        assert (await client.post(base + "/stage", content=bundle())).status_code == 403
        headers = guard.trusted_headers(user_action="extension-test-action")
        response = await client.post(base + "/stage", content=bundle(extra={"note.txt": "asset"}), headers=headers)
        assert response.status_code == 200, response.text
        review = response.json()
        assert (await client.get(base + "/plan", headers=headers)).json()["active"] == []
        response = await client.post(base + "/change", json={"action": "activate", "id": "example.skin",
            "digest": review["digest"], "acknowledgement": f"theme:{review['digest']}"}, headers=headers)
        assert response.status_code == 200, response.text
        url = (await client.get(base + "/plan", headers=headers)).json()["active"][0]["assetBase"] + "note.txt"
        assert (await client.get(url)).text == "asset"
        await client.post(base + "/change", json={"action": "disable", "id": "example.skin"}, headers=headers)
        assert (await client.get(url)).status_code == 404


@pytest.mark.anyio
async def test_catalog_distinguishes_desired_version_from_failed_or_running_backend(tmp_path):
    app = FastAPI()
    store = ExtensionStore(tmp_path)
    app.state.trusted_extension_store = store
    guard = LocalManagementGuard(["http://127.0.0.1:15173"])
    app.state.trusted_extension_management_guard = guard
    app.include_router(create_extension_router())
    first = enable(store, bundle(entries={"backend": "main.py"}, extra={"main.py": "def activate(ctx): pass\n"}))
    enable(store, bundle(extension_id="example.broken", entries={"backend": "main.py"},
        extra={"main.py": "def activate(ctx): raise RuntimeError('expected failure')\n"}))
    host = ExtensionHost(app, store)
    app.state.trusted_extension_host = host
    await host.prepare()
    await host.activate()
    enable(store, bundle(version="1.1.0", entries={"backend": "main.py"}, extra={"main.py": "def activate(ctx): pass\n"}))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("127.0.0.1", 20000)), base_url="http://127.0.0.1:18080") as client:
            result = await client.get("/api/v2/plugins/manage/extensions", headers=guard.trusted_headers())
            assert result.status_code == 200
            data = result.json()
            assert len(data["backendActive"]) == 1
            assert data["backendActive"][0]["digest"] == first["digest"]
            assert data["backendActive"][0]["version"] == "1.0.0"
            assert "expected failure" in data["backendErrors"]["example.broken"]
            assert next(item for item in data["plugins"] if item["manifest"]["id"] == "example.skin")["manifest"]["version"] == "1.1.0"
    finally:
        await host.stop()


def test_local_offline_boot_keeps_network_guard_and_protects_extension_management(tmp_path):
    from tests.source_checkout_testkit import BACKEND_ROOT, source_checkout_environment
    store = ExtensionStore(tmp_path / "plugins")
    enable(store, bundle(entries={"backend": "main.py"}, extra={"main.py":
        "import socket\ndef prepare(ctx):\n    try:\n        socket.getaddrinfo('example.com', 443)\n    except OSError:\n        ctx.replace_service('extension_offline_probe', 'guarded')\n    else:\n        raise RuntimeError('Network guard must precede extension startup')\n"}))
    script = """
from fastapi.testclient import TestClient
from app.main import app
class Peer:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope.get('type') in {'http', 'websocket'}:
            scope = {**scope, 'client': ('127.0.0.1', 50000)}
        await self.app(scope, receive, send)
with TestClient(Peer(app), base_url='http://127.0.0.1:18080') as client:
    assert app.state.extension_offline_probe == 'guarded'
    assert not app.state.trusted_extension_host.errors
    route = '/api/v2/plugins/manage/extensions'
    assert client.get(route).status_code == 403
    headers = app.state.trusted_extension_management_guard.trusted_headers()
    result = client.get(route, headers=headers)
    assert result.status_code == 200, result.text
    assert len(result.json()['backendLoaded']) == 1
    assert client.get('/api/v2/plugins/manage/catalog', headers=headers).status_code == 403
    revision = result.json()['revision']
    assert client.get(route + '/plan', params={'afterRevision': revision}, headers=headers).json() == {'unchanged': True}
assert not hasattr(app.state, 'extension_offline_probe')
"""
    environment = source_checkout_environment()
    environment.update({
        "CANDLESCOPE_RUNTIME_MODE": "LOCAL_OFFLINE", "BACKTEST_ENABLED": "0",
        "CANDLE_DATA_DIR": str(tmp_path / "data"),
        "CANDLESCOPE_LOCAL_DATA_DIR": str(tmp_path / "local-data"),
        "CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT": str(tmp_path / "plugins"),
        "CANDLESCOPE_PLUGIN_PLATFORM_V2_ENABLED": "1", "CANDLESCOPE_EXTENSIONS_SAFE_MODE": "0",
        "CANDLESCOPE_DESKTOP_PLUGIN_SESSION": "s" * 48, "CANDLESCOPE_DESKTOP_PLUGIN_CSRF": "c" * 48,
        "CANDLESCOPE_PLUGIN_PLATFORM_V2_MANAGEMENT_ORIGINS": "http://127.0.0.1:15173",
    })
    result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND_ROOT,
        env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
