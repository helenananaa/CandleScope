"""The read-only account's private session uses the proxy pool (#575 PL-11c)."""
import asyncio
import itertools
import json
from types import SimpleNamespace

import ccxt
import pytest

from app.api.v1 import settings
from app.core import config
from app.core.proxy_pool import get_proxy_pool
from app.readonly_accounts import service as service_module
from app.readonly_accounts.normalization import AccountDataError
from app.readonly_accounts.service import ROUTE_KIND, ReadOnlyAccountService, saved_network_options
from app.readonly_accounts.sync import AccountSynchronizer, RouteFailover

CREDENTIALS = {"apiKey": "fixture-key", "secret": "fixture-secret", "password": "fixture-passphrase"}
_ports = itertools.count(17100)  # Pool health is keyed by URL: each test gets its own.


def route(name, *, exchanges=(), enabled=True):
    return {"id": name, "name": name.upper(), "url": f"http://127.0.0.1:{next(_ports)}", "egress_group": name,
            "enabled": enabled, "exchanges": list(exchanges), "max_concurrency": 4}


def save(tmp_path, monkeypatch, mode, routes=(), custom=None):
    path = tmp_path / "proxy.json"
    monkeypatch.setattr(config, "PROXY_SETTINGS_PATH", path)
    path.write_text(json.dumps({"mode": mode, "custom_proxy": custom, "routes": list(routes), "strategy": "failover"}))


def fail(route_value, times=3):
    pool = get_proxy_pool()
    chosen = next(r for r in pool.routes(SimpleNamespace(
        proxy_mode="pool", proxy_routes=config.load_proxy_settings()["routes"], proxy_strategy="failover"), "okx")
        if r.id == route_value["id"])
    for _ in range(times):
        pool.record(chosen, "okx", error=ccxt.NetworkError("down"), kind=ROUTE_KIND)


@pytest.mark.anyio
async def test_pool_mode_uses_the_first_route_that_allows_okx(tmp_path, monkeypatch):
    binance_only, disabled, first, second = (route("binance", exchanges=["binance"]), route("off", enabled=False),
                                             route("first", exchanges=["okx"]), route("second"))
    save(tmp_path, monkeypatch, "pool", [binance_only, disabled, first, second])
    options = saved_network_options()
    assert (options["proxy"], options["trust_environment"], options["route"].id) == (first["url"], False, "first")
    save(tmp_path, monkeypatch, "pool", [binance_only])
    with pytest.raises(AccountDataError, match="ACCOUNT_PROXY_ROUTE_UNAVAILABLE"):
        saved_network_options()
    save(tmp_path, monkeypatch, "custom", custom="http://127.0.0.1:7890")
    assert saved_network_options() == {"proxy": "http://127.0.0.1:7890", "trust_environment": False}


def pool_route(routes, route_id):
    config_value = SimpleNamespace(proxy_mode="pool", proxy_routes=routes, proxy_strategy="failover")
    return next(r for r in get_proxy_pool().routes(config_value, "okx") if r.id == route_id)


@pytest.mark.anyio
async def test_the_session_stays_on_its_route_until_it_keeps_failing(tmp_path, monkeypatch):
    first, second = route("first"), route("second")
    save(tmp_path, monkeypatch, "pool", [first, second])
    current = pool_route([first, second], "second")
    assert saved_network_options(current)["route"].id == "second"  # sticky, though first is primary
    fail(second, times=2)
    assert saved_network_options(current)["route"].id == "second"  # a blip does not move it
    fail(second, times=1)
    assert saved_network_options(current)["route"].id == "first"  # three in a row: cooling down


@pytest.mark.anyio
async def test_public_traffic_failures_do_not_move_the_account(tmp_path, monkeypatch):
    first, second = route("first"), route("second")
    save(tmp_path, monkeypatch, "pool", [first, second])
    primary = pool_route([first, second], "first")
    for _ in range(3):
        get_proxy_pool().record(primary, "okx", error=ccxt.NetworkError("public"), kind="rest")
    assert saved_network_options()["route"].id == "first"


@pytest.mark.anyio
async def test_reconcile_failures_report_to_the_owner_and_end_in_failover(monkeypatch):
    results = []

    class Repository:
        def status(self, *args, **kwargs):
            pass

    sync = AccountSynchronizer(Repository(), SimpleNamespace(), network_result=lambda error: results.append(error) or len(results) >= 3)
    calls = itertools.count()

    async def reconcile():
        if next(calls) == 0:
            return True
        raise ccxt.NetworkError("route down")

    sync.reconcile = reconcile
    sync.consume = lambda: asyncio.Event().wait()
    sync.watch = lambda channel: asyncio.Event().wait()
    real_wait_for = asyncio.wait_for

    async def no_wait(awaitable, timeout):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", no_wait)  # skip run()'s 1-30 s pauses
    with pytest.raises(RouteFailover):
        await real_wait_for(sync.run(), timeout=5)
    assert results[0] is None and all(isinstance(e, ccxt.NetworkError) for e in results[1:]) and len(results) == 3


@pytest.mark.anyio
async def test_the_service_reconnects_through_the_next_route(tmp_path, monkeypatch):
    first, second = route("first"), route("second")
    save(tmp_path, monkeypatch, "pool", [first, second])
    proxies, second_running = [], asyncio.Event()

    class Vault:
        def read(self, key):
            return dict(CREDENTIALS)

    class FakeSync:
        def __init__(self, repository, client, *, state_changed, network_result):
            self.client, self.network_result = client, network_result
            self.stream_status, self.last_ws_received_ms, self.ws_error = "live", None, None

        def observe(self, message):
            pass

        async def initialize(self, uid):
            pass

        async def run(self):
            if self.client.proxy == first["url"]:
                for _ in range(5):
                    if self.network_result(ccxt.NetworkError("down")):
                        raise RouteFailover()
            second_running.set()
            await asyncio.Event().wait()

    def client_factory(credentials, *, proxy, trust_environment):
        proxies.append((proxy, trust_environment))

        async def close():
            pass

        return SimpleNamespace(proxy=proxy, close=close)

    monkeypatch.setattr(service_module, "AccountSynchronizer", FakeSync)
    service = ReadOnlyAccountService(tmp_path / "account", client_factory=client_factory,
                                     vault_factory=lambda root: Vault(), network_options=saved_network_options)
    service.repository.account = lambda credential_reference=True: {"enabled": 1, "credential_id": "c", "venue_uid": "1"}
    task = asyncio.create_task(service._run())
    try:
        await asyncio.wait_for(second_running.wait(), timeout=5)
        assert proxies == [(first["url"], False), (second["url"], False)]
        state = await service.state()
        assert state["proxyRoute"] == {"id": "second", "name": "SECOND"}
        assert service.network_in_use == (second["url"], False)
        assert service.network_options_now() == (second["url"], False)  # first is cooling down
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert service.network_in_use is None


@pytest.mark.anyio
async def test_saving_settings_restarts_the_account_only_when_its_connection_would_change(tmp_path, monkeypatch):
    first, second = route("first"), route("second")
    save(tmp_path, monkeypatch, "pool", [first, second])
    account = SimpleNamespace(network_in_use=None, network_options_now=lambda: (saved_network_options()["proxy"], False))
    assert settings._account_network_changed(account)  # not connected
    account.network_in_use = (first["url"], False)
    assert not settings._account_network_changed(account)
    save(tmp_path, monkeypatch, "pool", [first, second, route("third")])
    assert not settings._account_network_changed(account)  # another route added
    save(tmp_path, monkeypatch, "pool", [second, first])
    assert settings._account_network_changed(account)  # the user made another route primary
    save(tmp_path, monkeypatch, "pool", [route("binance", exchanges=["binance"])])
    assert settings._account_network_changed(account)  # no route for OKX: restart reports it
