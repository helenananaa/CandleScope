import base64
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
import requests
from cryptography.fernet import Fernet
from fastapi import FastAPI

from app.api.v1 import settings
from app.core import config
from app.core.proxy_pool import get_proxy_pool
from app.proxy_subscriptions import api, runtime
from app.proxy_subscriptions.source import SubscriptionError, parse_nodes
from app.proxy_subscriptions.store import SnapshotStore


SOURCE = "https://example.invalid/subscription?q=private-test-token"
PAYLOAD = b"""tun: {enable: true}
external-controller: 0.0.0.0:9090
proxies:
  - {name: first, type: ss, server: example.invalid, port: 443, cipher: aes-128-gcm, password: test-password}
  - {name: second, type: trojan, server: example.invalid, port: 444, password: second-password}
  - {name: ignored, type: direct}
"""


def test_import_accepts_only_node_data_and_preserves_identity():
    nodes, skipped = parse_nodes(PAYLOAD, SOURCE)
    assert skipped == 1
    assert list(nodes) == list(parse_nodes(PAYLOAD.replace(b"test-password", b"new-password"), SOURCE)[0])
    assert all(set(node) <= {"name", "type", "server", "port", "cipher", "password"} for node in nodes.values())
    for payload in [b"proxies: [&a {}, *a]", b"vmess://test", b"proxies: [{type: file}]",
                    PAYLOAD.replace(b"name: second", b"name: first")]:
        with pytest.raises(SubscriptionError):
            parse_nodes(payload, SOURCE)


class FakeCore:
    connection_sweep_due = False

    def sweep_retired_connections(self):
        pass

    @contextmanager
    def stage_update(self, nodes):
        yield
        self.reconfigure(nodes)
    def __init__(self, nodes):
        self.alive = True
        self.reconfigure(nodes)

    def reconfigure(self, nodes):
        self.nodes = nodes
        self.endpoints = {key: f"http://127.0.0.1:{10000 + i}" for i, key in enumerate(nodes)}

    def close(self):
        self.alive = False


@pytest.mark.anyio
async def test_trusted_import_save_restore_refresh_failure_and_disable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROXY_SETTINGS_PATH", tmp_path / "proxy.json")
    store = SnapshotStore(tmp_path / "private")
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr(store, "_cipher", lambda create: cipher)
    manager = runtime.ManagedRoutes(store)
    for module in (runtime, settings, api):
        monkeypatch.setattr(module, "managed", manager)
    monkeypatch.setattr(runtime, "Core", FakeCore)

    async def downloaded(url):
        assert url == SOURCE
        return parse_nodes(PAYLOAD, url)

    monkeypatch.setattr(api, "download", downloaded)
    app = FastAPI()
    app.include_router(settings.router)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1/settings/proxy/") as cli:
        denied = await cli.post("subscriptions/preview", json={"url": SOURCE}, headers={"Origin": "https://untrusted.invalid"})
        assert denied.status_code == 403
        view = (await cli.post("subscriptions/preview", json={"url": SOURCE})).json()
        assert view["skipped"] == 1 and len(view["nodes"]) == 2
        assert SOURCE not in str(view) and "password" not in str(view)
        selected = [n["id"] for n in view["nodes"]]
        rows = (await cli.post("subscriptions/routes", json={"preview": view["preview"], "nodes": selected})).json()["routes"]
        saved = await cli.put("", json={"mode": "pool", "routes": rows}, follow_redirects=True)
        assert saved.status_code == 200 and config.load_proxy_settings()["routes"] == rows
        draft = SimpleNamespace(proxy_mode="pool", proxy_routes=rows, proxy_strategy="balanced")
        bound = get_proxy_pool().routes(draft, "okx")
        assert len({r.url for r in bound}) == 2 and all(r.egress_group == "shared" for r in bound)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert SOURCE.encode() not in path.read_bytes() and b"test-password" not in path.read_bytes()
        manager.close()
        with pytest.raises(ValueError, match="no enabled proxy route"):
            get_proxy_pool().routes(draft, "okx")
        manager.restore()
        active = manager.active.core
        assert [r.url for r in get_proxy_pool().routes(draft, "okx")] == [r.url for r in bound]
        refresh = (await cli.post("subscriptions/preview", json={"saved_route_id": rows[0]["id"]})).json()
        assert refresh["nodes"] == view["nodes"]

        async def invalid_refresh(url):
            return parse_nodes(b"subscription unavailable", url)

        with monkeypatch.context() as patch:
            patch.setattr(api, "download", invalid_refresh)
            failed = await cli.post("subscriptions/preview", json={"saved_route_id": rows[0]["id"]})
        assert failed.status_code == 400 and config.load_proxy_settings()["routes"] == rows
        assert manager.active.core is active and active.alive
        invalid = [dict(rows[0], url="mihomo://" + "0" * 64 + "/" + selected[0])]
        result = await cli.put("", json={"mode": "pool", "routes": invalid}, follow_redirects=True)
        assert result.status_code == 400 and manager.active.core is active
        assert config.load_proxy_settings()["routes"] == rows
        active.alive = False
        manager.recover()
        assert manager.active.core is not active and manager.active.core.alive
        assert (await cli.put("", json={"mode": "none"}, follow_redirects=True)).status_code == 200
        assert manager.active.core is None


def test_failed_persistence_rolls_back_in_place(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr(store, "_cipher", lambda create: cipher)
    monkeypatch.setattr(runtime, "Core", FakeCore)
    nodes, _ = parse_nodes(PAYLOAD, SOURCE)
    rows = store.save(SOURCE, nodes)
    manager = runtime.ManagedRoutes(store)
    manager.activate(rows[:1])
    first = manager.active
    def fail():
        raise OSError("simulated full disk")
    with pytest.raises(OSError):
        manager.activate(rows, fail)
    assert manager.active is first and len(first.core.nodes) == 1
    manager.close()



def test_real_core_two_independent_upstreams_and_no_direct_fallback():
    import os
    import shutil
    import threading
    from contextlib import ExitStack
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit

    import requests
    from app.proxy_subscriptions.core import Core

    if not (os.getenv("CANDLESCOPE_MIHOMO") or shutil.which("mihomo")):
        pytest.skip("Mihomo required for native listener integration")
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_CONNECT(self):
            self.send_response(200)
            self.end_headers()
            self.close_connection = False

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.server.marker)))
            self.end_headers()
            self.wfile.write(self.server.marker.encode())

        def log_message(self, *args):
            pass

    with ExitStack() as stack, requests.Session() as session:
        session.trust_env = False
        nodes = {}
        for key in ("first", "second"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server.marker = key
            stack.callback(server.server_close)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)
            nodes[key] = {"type": "http", "server": "127.0.0.1", "port": server.server_port}
        core = Core(nodes)
        stack.callback(core.close)
        for key, proxy in core.endpoints.items():
            target = "http://market.invalid/ticker"
            response = session.get(target, proxies={"http": proxy}, timeout=4)
            assert response.text == key
            unauthenticated = "http://127.0.0.1:" + str(urlsplit(proxy).port)
            assert session.get(target, proxies={"http": unauthenticated}, timeout=3).status_code == 407
        original = core.endpoints["first"]
        core.reconfigure({"first": nodes["first"]})
        assert core.endpoints == {"first": original}
        assert session.get(target, proxies={"http": original}, timeout=3).text == "first"


# --- PL-11a: occupied listener ports and process reaping -------------------------------------

BACKEND = Path(__file__).resolve().parents[1]
# The fake core is a shell script and the checks below signal its PID. Windows
# runs the real-core cases instead (windows-proxy-core.yml).
posix_only = pytest.mark.skipif(os.name != "posix", reason="shell-script fake core and POSIX signals")


def _mihomo():
    return os.getenv("CANDLESCOPE_MIHOMO") or shutil.which("mihomo")


class _QuietHandler(BaseHTTPRequestHandler):
    def reply(self, status):
        self.send_response(status)
        if status == 407:
            self.send_header("Proxy-Authenticate", 'Basic realm="other"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class _ForeignProxy(_QuietHandler):
    """Another local proxy on the port: it wants its own credentials for everything."""

    def do_GET(self):
        self.reply(407)


class _PlainServer(_QuietHandler):
    def do_GET(self):
        self.reply(200)


class _OwnListener(_QuietHandler):
    """How Mihomo answers an origin-form request on a listener with our password."""

    def do_GET(self):
        token = base64.b64encode(("candlescope:" + self.server.password).encode()).decode()
        self.reply(400 if self.headers.get("Proxy-Authorization") == "Basic " + token else 407)


@contextmanager
def _serve(handler, **attributes):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    for name, value in attributes.items():
        setattr(server, name, value)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _listener(port, password="p" * 48):
    return {"name": "in-test", "type": "http", "listen": "127.0.0.1", "port": port, "proxy": "node",
            "users": [{"username": "candlescope", "password": password}]}


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def _closed(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
    except OSError:
        return True
    return False


def _private_temp(monkeypatch, tmp_path):
    """Point the guard's temporary directory at an empty folder this test owns."""
    folder = tmp_path / "core-temp"
    folder.mkdir()
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(folder))
    return folder


def _gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_listener_check_never_adopts_a_port_held_by_another_local_service():
    from app.proxy_subscriptions.core import Core

    password = "s" * 48
    with _serve(_ForeignProxy) as foreign, _serve(_PlainServer) as plain, \
            _serve(_OwnListener, password=password) as own:
        assert not Core._owns_listener(_listener(foreign.server_port, password))
        assert not Core._owns_listener(_listener(plain.server_port, password))
        assert Core._owns_listener(_listener(own.server_port, password))
        # A listener with someone else's password is not ours either.
        assert not Core._owns_listener(_listener(own.server_port, "o" * 48))
    # Nothing bound yet is an OSError, which _ready() retries until its deadline.
    with pytest.raises(OSError):
        Core._owns_listener(_listener(_free_port(), password))


def test_real_core_refuses_an_occupied_listener_port_and_reaps_its_processes(monkeypatch):
    from app.proxy_subscriptions import core as core_module

    if not _mihomo():
        pytest.skip("Mihomo required for native listener integration")
    reserved, launched = [], []
    real_reserve, real_popen = core_module._reserve, subprocess.Popen
    with _serve(_ForeignProxy) as foreign, _serve(_PlainServer) as upstream:
        def reserve(stack):
            # The controller gets a free port. The listener's port is then taken
            # by another local proxy, as a racing app could between our
            # reservation and Mihomo's bind.
            port = foreign.server_port if reserved else real_reserve(stack)
            reserved.append(port)
            return port

        def popen(*args, **kwargs):
            launched.append(real_popen(*args, **kwargs))
            return launched[-1]

        monkeypatch.setattr(core_module, "_reserve", reserve)
        monkeypatch.setattr(core_module.subprocess, "Popen", popen)
        started = time.monotonic()
        with pytest.raises(SubscriptionError, match="could not start all selected listeners"):
            core_module.Core({"node": {"type": "http", "server": "127.0.0.1", "port": upstream.server_port}})
        assert time.monotonic() - started < 15
        assert reserved[1:] == [foreign.server_port] and len(launched) == 1
        # The guard was reaped, and Mihomo with it: its controller no longer accepts.
        assert launched[0].poll() is not None
        assert _until(lambda: _closed(reserved[0]))
        # The other proxy keeps its port and is never routed through.
        assert requests.get(f"http://127.0.0.1:{foreign.server_port}/", timeout=2).status_code == 407


FAKE_CORE = """
import json, os, signal, sys, time
record, mode, args = sys.argv[1], sys.argv[2], sys.argv[3:]
config = sys.stdin.buffer.read()
if mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
directory = args[args.index("-d") + 1]
state = {"pid": os.getpid(), "args": args, "dir": directory, "dirExisted": os.path.isdir(directory),
         "config": config.decode()}
with open(record + ".tmp", "w") as out:
    json.dump(state, out)
os.replace(record + ".tmp", record)
if mode == "exit":
    sys.exit(3)
while True:
    time.sleep(0.1)
"""


@pytest.fixture
def fake_core(tmp_path):
    """An executable standing in for Mihomo; it records how the guard ran it."""
    script = tmp_path / "fake_core.py"
    script.write_text(FAKE_CORE, encoding="utf-8")

    def make(mode="run"):
        record = tmp_path / f"core-{mode}.json"
        binary = tmp_path / f"mihomo-{mode}"
        binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "{record}" "{mode}" "$@"\n')
        binary.chmod(0o755)
        return binary, record

    return make


def _record(path, timeout=10.0):
    assert _until(path.exists, timeout), "fake core never started"
    return json.loads(path.read_text())


def _launch(monkeypatch, binary):
    from app.proxy_subscriptions.core import Core

    monkeypatch.setenv("CANDLESCOPE_MIHOMO", str(binary))
    core = Core.__new__(Core)
    core.process = None
    core.session = requests.Session()
    core._launch({"listeners": [], "secret": "fixture"})
    return core


@posix_only
def test_guard_gives_the_core_its_config_and_removes_its_directory_on_close(monkeypatch, fake_core):
    binary, record = fake_core()
    core = _launch(monkeypatch, binary)
    state = _record(record)
    assert state["args"] == ["-d", state["dir"], "-f", "-"] and state["dirExisted"]
    assert json.loads(state["config"]) == {"listeners": [], "secret": "fixture"}
    assert core.alive
    core.close()
    assert core.process.poll() is not None and not core.alive
    assert _until(lambda: _gone(state["pid"])) and not os.path.exists(state["dir"])


@posix_only
def test_guard_kills_a_core_that_ignores_terminate(monkeypatch, fake_core):
    binary, record = fake_core("ignore-term")
    core = _launch(monkeypatch, binary)
    state = _record(record)
    started = time.monotonic()
    core.close()
    # The guard asks once, waits two seconds, then kills; close() never needs its own kill.
    assert 1.5 <= time.monotonic() - started < 5
    assert core.process.returncode is not None
    assert _until(lambda: _gone(state["pid"])) and not os.path.exists(state["dir"])


@posix_only
def test_killed_backend_leaves_no_core_behind(fake_core):
    binary, record = fake_core()
    backend = subprocess.Popen([sys.executable, "-c", f"""
import sys, time
sys.path.insert(0, {str(BACKEND)!r})
import requests
from app.proxy_subscriptions.core import Core
core = Core.__new__(Core)
core.process = None
core._launch({{"listeners": []}})
print(core.process.pid, flush=True)
time.sleep(600)
"""], stdout=subprocess.PIPE, env={**os.environ, "CANDLESCOPE_MIHOMO": str(binary)})
    try:
        guard = int(backend.stdout.readline())
        state = _record(record)
        # No close(), no atexit: the backend dies and only the pipe closing tells the guard.
        os.kill(backend.pid, signal.SIGKILL)
        backend.wait(timeout=5)
        assert _until(lambda: _gone(state["pid"])) and _until(lambda: _gone(guard))
        assert not os.path.exists(state["dir"])
    finally:
        if backend.poll() is None:
            backend.kill()
            backend.wait()
        backend.stdout.close()


@posix_only
def test_core_that_exits_at_startup_fails_fast_and_is_not_restarted_by_the_guard(monkeypatch, fake_core):
    binary, record = fake_core("exit")
    core = _launch(monkeypatch, binary)
    state = _record(record)
    assert core.process.wait(timeout=5) == 3  # The guard reports the core's own status.
    started = time.monotonic()
    with pytest.raises(SubscriptionError, match="could not start"):
        core._ready({"node": {}}, {"node": _listener(_free_port())})
    assert time.monotonic() - started < 1  # Not the 8 s listener deadline.
    assert _gone(state["pid"])
    core.close()


@posix_only
def test_guard_without_a_config_never_starts_the_core(fake_core):
    from app.proxy_subscriptions import core as core_module

    binary, record = fake_core()
    guard = Path(core_module.__file__).with_name("guard.py")
    process = subprocess.Popen([sys.executable, "-I", str(guard), str(binary)], stdin=subprocess.PIPE)
    process.stdin.close()
    assert process.wait(timeout=5) == 1
    assert not record.exists()


def test_real_core_close_stops_it_and_removes_its_working_directory(monkeypatch, tmp_path):
    from urllib.parse import urlsplit

    from app.proxy_subscriptions.core import Core

    if not _mihomo():
        pytest.skip("Mihomo required for native listener integration")
    temp = _private_temp(monkeypatch, tmp_path)
    with _serve(_PlainServer) as upstream:
        core = Core({"node": {"type": "http", "server": "127.0.0.1", "port": upstream.server_port}})
        try:
            controller, listener = urlsplit(core.controller).port, urlsplit(core.endpoints["node"]).port
            # Mihomo runs in a private working directory of its own.
            assert [path.name.startswith("candlescope-proxy-") for path in temp.iterdir()] == [True]
        finally:
            core.close()
        assert core.process.poll() is not None and not core.alive
        assert _until(lambda: _closed(controller) and _closed(listener))
        # Windows refuses to delete files a running process still holds open.
        assert _until(lambda: not any(temp.iterdir()))


def test_real_core_exits_when_its_backend_is_killed(monkeypatch, tmp_path):
    if not _mihomo():
        pytest.skip("Mihomo required for native listener integration")
    temp = _private_temp(monkeypatch, tmp_path)
    with _serve(_PlainServer) as upstream:
        backend = subprocess.Popen([sys.executable, "-c", f"""
import sys, time
from urllib.parse import urlsplit
sys.path.insert(0, {str(BACKEND)!r})
from app.proxy_subscriptions.core import Core
core = Core({{"node": {{"type": "http", "server": "127.0.0.1", "port": {upstream.server_port}}}}})
print(urlsplit(core.controller).port, urlsplit(core.endpoints["node"]).port, flush=True)
time.sleep(600)
"""], stdout=subprocess.PIPE)
        try:
            controller, listener = map(int, backend.stdout.readline().split())
            assert not _closed(controller) and not _closed(listener)
            assert any(temp.iterdir())
            # SIGKILL on POSIX, TerminateProcess on Windows: no close(), no atexit.
            # Only the closing pipe tells the guard.
            backend.kill()
            backend.wait(timeout=5)
            assert _until(lambda: _closed(controller) and _closed(listener))
            assert _until(lambda: not any(temp.iterdir()))
        finally:
            if backend.poll() is None:
                backend.kill()
                backend.wait()
            backend.stdout.close()
