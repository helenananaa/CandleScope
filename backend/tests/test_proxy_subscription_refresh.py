"""Real Mihomo connections for refresh, rollback and listener retirement."""
import base64
import http.client
import os
import shutil
import threading
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from cryptography.fernet import Fernet

from app.proxy_subscriptions.runtime import ManagedRoutes
from app.proxy_subscriptions.store import SnapshotStore


class MarketProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_CONNECT(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        marker = self.server.marker
        self.send_response(200)
        self.send_header("Content-Length", str(len(marker)))
        self.end_headers()
        self.wfile.write(marker)

    def log_message(self, *args):
        pass


@pytest.fixture
def subscription(tmp_path, monkeypatch):
    if not (os.getenv("CANDLESCOPE_MIHOMO") or shutil.which("mihomo")):
        pytest.skip("Mihomo required for live subscription refresh tests")
    store = SnapshotStore(tmp_path)
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr(store, "_cipher", lambda create: cipher)
    manager = ManagedRoutes(store)
    with ExitStack() as stack:
        nodes = {}
        for i in range(3):
            server = ThreadingHTTPServer(("127.0.0.1", 0), MarketProxy)
            server.marker = str(i).encode()
            stack.callback(server.server_close)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)
            nodes[f"{i:032x}"] = {"name": str(i), "type": "http", "server": "127.0.0.1", "port": server.server_port}
        stack.callback(manager.close)
        yield manager, nodes


def open_tunnel(url):
    address = urlsplit(url)
    auth = base64.b64encode(f"{address.username}:{address.password}".encode()).decode()
    conn = http.client.HTTPConnection(address.hostname, address.port, timeout=2)
    conn.set_tunnel("market.invalid", 80, {"Proxy-Authorization": "Basic " + auth})
    conn.connect()
    conn.auto_open = False  # A reconnect would hide a broken incumbent tunnel.
    return conn


def read_market(conn):
    conn.request("GET", "/ticker")
    response = conn.getresponse()
    assert response.status == 200
    return response.read()


def selected(manager, nodes):
    return manager.store.save("https://example.invalid/test", nodes)


@pytest.mark.parametrize("replace", [False, True], ids=["removed", "changed"])
def test_refresh_retires_only_the_affected_tunnel(subscription, replace):
    manager, nodes = subscription
    keep, retire, new = nodes.keys()
    original = selected(manager, {keep: nodes[keep], retire: nodes[retire]})
    manager.activate(original)
    with ExitStack() as stack:
        connections = []
        for route in original:
            conn = open_tunnel(manager.active.resolve(route["url"]))
            stack.callback(conn.close)
            connections.append(conn)
        assert [read_market(c) for c in connections] == [b"0", b"1"]
        update = {keep: nodes[keep]}
        if replace:
            update[retire] = {**nodes[retire], "port": nodes[new]["port"]}
        rows = selected(manager, update)
        manager.activate(rows)
        assert read_market(connections[0]) == b"0"
        with pytest.raises((ConnectionError, http.client.HTTPException)):
            read_market(connections[1])
        if replace:
            fresh = open_tunnel(manager.active.resolve(rows[1]["url"]))
            stack.callback(fresh.close)
            assert read_market(fresh) == b"2"


def test_failed_save_restores_exact_listener_and_existing_tunnel(subscription):
    manager, nodes = subscription
    keep, changed, new = nodes.keys()
    original = selected(manager, {keep: nodes[keep], changed: nodes[changed]})
    manager.activate(original)
    endpoint = manager.active.resolve(original[1]["url"])
    conn = open_tunnel(endpoint)
    try:
        assert read_market(conn) == b"1"

        def disk_full():
            raise OSError("simulated disk full")

        rows = selected(manager, {keep: nodes[keep], changed: {**nodes[changed], "port": nodes[new]["port"]}})
        with pytest.raises(OSError, match="disk full"):
            manager.activate(rows, disk_full)
        assert manager.active.resolve(original[1]["url"]) == endpoint
        assert read_market(conn) == b"1"
        fresh = open_tunnel(endpoint)
        try:
            assert read_market(fresh) == b"1"
        finally:
            fresh.close()
    finally:
        conn.close()


def test_failed_controller_cleanup_stops_forwarding_and_restores_committed_routes(subscription, tmp_path, monkeypatch):
    import requests
    from app.core import config

    monkeypatch.setattr(config, "PROXY_SETTINGS_PATH", tmp_path / "settings.json")
    manager, nodes = subscription
    rows = selected(manager, nodes)
    manager.activate(rows)
    core = manager.active.core
    with ExitStack() as stack:
        retired = open_tunnel(manager.active.resolve(rows[-1]["url"]))
        stack.callback(retired.close)
        assert read_market(retired) == b"2"
        with monkeypatch.context() as patch:
            def offline(*args, **kwargs):
                raise requests.ConnectionError("controller temporarily unavailable")

            patch.setattr(core.session, "delete", offline)
            manager.activate(rows[:-1], lambda: config.save_proxy_settings("pool", None, routes=rows[:-1]))
        assert not core.alive
        assert rows[-1]["url"] not in manager.active.references
        manager.recover()
        assert manager.active.core.alive and manager.active.core is not core
        assert set(manager.active.references) == {r["url"] for r in rows[:-1]}
        with pytest.raises((ConnectionError, http.client.HTTPException)):
            read_market(retired)


@pytest.mark.anyio
async def test_account_network_refresh_depends_on_bound_route(subscription, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx
    from fastapi import FastAPI
    from app.api.v1 import settings
    from app.core import config
    from app.proxy_subscriptions import runtime

    manager, nodes = subscription
    monkeypatch.setattr(config, "PROXY_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "managed", manager)
    monkeypatch.setattr(runtime, "managed", manager)
    from app.readonly_accounts.service import saved_network_options

    app = FastAPI()
    # Stands in for the account service: it reconnects with what the saved settings choose.
    account = SimpleNamespace(network_in_use=None,
                              network_options_now=lambda: (saved_network_options()["proxy"], False))

    async def reconnect():
        account.network_in_use = account.network_options_now()

    restart = account.reconfigure_network = AsyncMock(side_effect=reconnect)
    app.state.readonly_account_service = account
    app.include_router(settings.router)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as cli:
        async def save(rows):
            response = await cli.put("/settings/proxy", json={"mode": "pool", "routes": rows})
            assert response.status_code == 200

        rows = selected(manager, nodes)
        await save(rows)
        restart.assert_awaited_once()
        await save(rows[:2])
        restart.assert_awaited_once()
        await save(list(reversed(rows[:2])))
        assert restart.await_count == 2
