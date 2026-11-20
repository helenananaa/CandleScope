from types import SimpleNamespace

import httpx
import pytest
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
