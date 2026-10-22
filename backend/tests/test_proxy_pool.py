from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import web

from app.core.proxy_pool import ProxyPool, get_proxy_pool, normalize_proxy_pool
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import StreamDescriptor, StreamType, TransportRequest
from app.data_engine.ingestion.transport import TransportLayer, TransportError
from app.exchanges.plugins.binance.plugin import BinancePlugin
from app.exchanges.rate_limits import (
    HistoricalRequest, RateLimitManager, RateLimitRule, scope_rate_limit_rule,
)


def config(*, shared=False, strategy="balanced", urls=None):
    urls = urls or ["http://127.0.0.1:31001", "http://127.0.0.1:31002"]
    routes = [{"id": name, "name": name, "url": url, "egress_group": "shared" if shared else name,
               "enabled": True, "exchanges": [], "max_concurrency": 1, "max_ws_subscriptions": 64}
              for name, url in zip(["a", "b"], urls)]
    return IngestionConfig(proxy_mode="pool", proxy_routes=routes, proxy_strategy=strategy)


def request():
    return HistoricalRequest("binance", "spot", "/api/v3/klines", "BTCUSDT", limit=1000)


def rule():
    return RateLimitRule("test", "binance:spot:request_weight:ip", 2, 60)


@pytest.mark.anyio
async def test_shared_exit_budget_and_independent_ip_ban():
    pool, manager = ProxyPool(), RateLimitManager()
    cfg = config(shared=True)
    a, b = pool.routes(cfg, "binance")
    ar = scope_rate_limit_rule(rule(), a.egress_group)
    br = scope_rate_limit_rule(rule(), b.egress_group)
    assert ar.bucket_key == br.bucket_key
    await manager.acquire_nowait(ar, request())
    await manager.acquire_nowait(br, request())
    assert not (await manager.inspect(ar, request())).allowed
    independent = scope_rate_limit_rule(rule(), "independent")
    manager.record_response(ar, status_code=418, retry_after=30)
    another_endpoint = scope_rate_limit_rule(
        RateLimitRule("other", "binance:futures:request_weight:ip", 20, 60), "shared")
    assert (await manager.inspect(another_endpoint, request())).reason == "circuit_open"
    assert (await manager.inspect(independent, request())).allowed
    assert (await pool.select_rest(config(), request(), rule(), manager)).id == "a"


def test_key_credits_are_not_multiplied_by_proxy_groups():
    key_rule = RateLimitRule("credits", "vendor:api-credits:key", 2, 60)
    assert scope_rate_limit_rule(key_rule, "a").bucket_key == scope_rate_limit_rule(key_rule, "b").bucket_key


@pytest.mark.anyio
async def test_selection_accounts_for_budget_load_and_health_without_resetting_quota():
    cfg, pool, manager = config(), ProxyPool(), RateLimitManager()
    a, b = pool.routes(cfg, "binance")
    assert (await pool.select_rest(cfg, request(), rule(), manager)).id == "a"
    pool.begin(a, "binance")
    assert (await pool.select_rest(cfg, request(), rule(), manager)).id == "b"
    pool.end(a)
    manager.record_response(scope_rate_limit_rule(rule(), "a"), status_code=429, retry_after=10)
    assert (await pool.select_rest(cfg, request(), rule(), manager)).id == "b"
    # A new alias of the same exit still sees the original cooldown.
    alias = config(shared=True)
    alias.proxy_routes[0]["egress_group"] = "a"
    alias.proxy_routes[1]["egress_group"] = "a"
    assert not (await manager.inspect(scope_rate_limit_rule(rule(), "a"), request())).allowed
    pool.record(b, "okx", error=OSError("offline"))
    assert pool.health(b, "binance").failures == 0


@pytest.mark.anyio
async def test_websocket_primary_is_sticky_and_migrates_after_repeated_failure():
    cfg, pool = config(strategy="failover"), ProxyPool()
    a = pool.select_ws(cfg, "binance")
    for _ in range(2):
        pool.record(a, "binance", error=OSError("offline"), kind="ws")
        assert pool.select_ws(cfg, "binance").id == "a"
    pool.record(a, "binance", error=OSError("offline"), kind="ws")
    b = pool.select_ws(cfg, "binance")
    assert b.id == "b"
    # Recovery of primary does not bounce healthy new connections back.
    pool.record(a, "binance", kind="ws")
    assert pool.select_ws(cfg, "binance").id == "b"


def test_validation_and_legacy_config_migration(tmp_path, monkeypatch):
    from app.core import config as core_config
    path = tmp_path / "proxy.json"
    monkeypatch.setattr(core_config, "PROXY_SETTINGS_PATH", path)
    path.write_text('{"mode":"custom","custom_proxy":"http://localhost:7890"}')
    saved = core_config.load_proxy_settings()
    assert saved["custom_proxy"] == "http://localhost:7890" and saved["routes"] == []
    routes, strategy = normalize_proxy_pool(config().proxy_routes)
    core_config.save_proxy_settings("pool", None, routes=routes, strategy=strategy)
    assert core_config.load_proxy_settings()["routes"] == routes
    for patch in [{"url": "socks5://localhost:7890"}, {"max_concurrency": 0}, {"egress_group": "bad:group"}]:
        with pytest.raises(ValueError):
            normalize_proxy_pool([{**routes[0], **patch}])
    with pytest.raises(ValueError):
        normalize_proxy_pool([routes[0], routes[0]])


def test_invalid_saved_pool_never_falls_back_to_system_proxy(tmp_path, monkeypatch):
    from app.core import config as core_config
    path = tmp_path / "proxy.json"
    monkeypatch.setattr(core_config, "PROXY_SETTINGS_PATH", path)
    monkeypatch.setattr(core_config, "_get_system_proxy", lambda: "http://localhost:9999")
    path.write_text('{"mode":"pool","routes":[{"id":"a","url":"invalid"}]}')
    saved = core_config.load_proxy_settings()
    assert saved["mode"] == "pool" and saved["routes"] == []
    with pytest.raises(ValueError, match="no enabled proxy route"):
        core_config.get_effective_proxy()


@pytest.mark.anyio
async def test_credentials_are_redacted_and_route_binding_does_not_mutate_config():
    cfg = config(urls=["http://user:secret@localhost:7890", "http://localhost:7891"])
    route = get_proxy_pool().routes(cfg, "binance")[0]
    bound = route.bind(cfg)
    assert cfg.proxy_mode == "pool" and bound.proxy_mode == "custom"
    assert bound.http_proxy == route.url and bound.proxy_egress_group == "a"
    snapshot = get_proxy_pool().snapshot(cfg)
    assert "secret" not in str(snapshot) and "user:" not in str(snapshot)
    assert "secret" not in str(cfg.snapshot())
    cfg.proxy_routes[0]["exchanges"] = ["okx"]
    cfg.proxy_routes[1]["enabled"] = False
    with pytest.raises(ValueError, match="no enabled"):
        get_proxy_pool().routes(cfg, "binance")


@pytest.mark.anyio
async def test_real_local_http_proxies_route_feedback_and_429_no_immediate_replay():
    """Only loopback sockets are used; works with TUN and no public network."""
    calls = [0, 0]
    limited = [True]
    runners = []
    urls = []
    for index in range(2):
        async def handle(_request, index=index):
            calls[index] += 1
            if index == 0 and limited[0]:
                return web.json_response({"code": -1003}, status=429, headers={"Retry-After": "10"})
            return web.json_response([[1700000000000, "1", "2", "1", "2", "3", 1700000059999, "4", 1, "2", "2", "0"]])
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        urls.append(f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}")
        runners.append(runner)
    cfg = config(urls=urls)
    cfg.http_base_urls = ["http://exchange.invalid"]
    transport = TransportLayer(cfg)
    transport._registry = SimpleNamespace(get_plugin=lambda _exchange: BinancePlugin())
    transport._rate_limits = RateLimitManager()
    descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m")
    try:
        with pytest.raises(TransportError):
            await transport.http_fetch(TransportRequest(descriptor, limit=1000))
        assert calls == [1, 0]
        messages = await transport.http_fetch(TransportRequest(descriptor, limit=1000))
        assert len(messages) == 1 and calls == [1, 1]
        assert ":egress=a" in " ".join(transport._rate_limits.snapshot())
        assert ":egress=b" in " ".join(transport._rate_limits.snapshot())
        assert all(row["active_requests"] == 0 for row in get_proxy_pool().snapshot(cfg)["routes"])
    finally:
        # The fake registry only handles get_plugin, so close the owned session directly.
        if transport._http_session:
            await transport._http_session.close()
        for runner in runners:
            await runner.cleanup()


@pytest.mark.anyio
async def test_reservation_pins_route_and_provider_configs_are_reused_and_closed():
    from app.exchanges.rate_limits import RateLimitReservation
    cfg = config()
    pool = get_proxy_pool()
    a, b = pool.routes(cfg, "binance")
    seen, closed = [], []

    async def fetch(req, config):
        seen.append(config)
        return []

    async def close(config):
        closed.append(config)

    plugin = SimpleNamespace(id="binance", fetch_history_with_config=fetch,
        provider_rate_limit_endpoint=lambda req: "/api/v3/klines",
        rate_limit_policy=lambda cfg: BinancePlugin().rate_limit_policy(cfg),
        close_history_transport=close)
    transport = TransportLayer(cfg)
    transport._registry = SimpleNamespace(get_plugin=lambda _: plugin, list_plugins=lambda: [plugin])
    transport._rate_limits = RateLimitManager()
    scoped = scope_rate_limit_rule(rule(), "a")
    await transport._rate_limits.acquire_nowait(scoped, request())
    reservation = RateLimitReservation(transport._rate_limits, scoped, request(), proxy_route=a)
    descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m")
    req = TransportRequest(descriptor, quota_reservation=reservation, quota_acquired=True, proxy_route=b)
    await transport.http_fetch(req)
    assert seen[-1].http_proxy == a.url and reservation.settled
    await transport.http_fetch(TransportRequest(descriptor, proxy_route=a))
    assert seen[0] is seen[1]
    assert cfg.proxy_mode == "pool" and len(transport._route_configs) == 1
    await transport.stop()
    assert cfg in closed and seen[0] in closed and transport._route_configs == {}


@pytest.mark.anyio
async def test_provider_cancellation_releases_route_and_probe():
    import asyncio
    started = asyncio.Event()

    async def fetch(req, config):
        started.set()
        await asyncio.Event().wait()

    cfg = config()
    route = get_proxy_pool().routes(cfg, "binance")[0]
    plugin = SimpleNamespace(fetch_history_with_config=fetch,
        provider_rate_limit_endpoint=lambda req: "/api/v3/klines",
        rate_limit_policy=lambda cfg: BinancePlugin().rate_limit_policy(cfg))
    transport = TransportLayer(cfg)
    transport._registry = SimpleNamespace(get_plugin=lambda _: plugin)
    transport._rate_limits = RateLimitManager(conservative_cold_start=True)
    descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m")
    task = asyncio.create_task(transport.http_fetch(TransportRequest(descriptor, proxy_route=route)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert get_proxy_pool().snapshot(cfg)["routes"][0]["active_requests"] == 0
    assert not next(iter(transport._rate_limits.snapshot().values()))["probe_in_flight"]


@pytest.mark.anyio
@pytest.mark.parametrize("status", [429, 418])
async def test_ccxt_rate_errors_cool_exact_exit_without_proxy_health_failover(status):
    import ccxt
    cfg = config()
    route = get_proxy_pool().routes(cfg, "binance")[0]

    async def fetch(req, config):
        error = ccxt.RateLimitExceeded(f'binance {status} Too Many Requests {{"code":-1003}}')
        error.headers = {"Retry-After": "10"}
        raise error

    plugin = SimpleNamespace(fetch_history_with_config=fetch,
        provider_rate_limit_endpoint=lambda req: "/api/v3/klines",
        rate_limit_policy=lambda cfg: BinancePlugin().rate_limit_policy(cfg))
    transport = TransportLayer(cfg)
    transport._registry = SimpleNamespace(get_plugin=lambda _: plugin)
    transport._rate_limits = RateLimitManager()
    descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m")
    with pytest.raises(TransportError) as error:
        await transport.http_fetch(TransportRequest(descriptor, proxy_route=route))
    assert error.value.status_code == status and error.value.retry_after == 10
    bucket = next(iter(transport._rate_limits.snapshot().values()))
    assert bucket["cooldown_remaining_seconds"] > 0
    assert get_proxy_pool().health(route, "binance").failures == 0


def test_settings_roundtrip_status_and_invalid_pool_preserves_file(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1 import settings
    from app.core import config as core_config

    path = tmp_path / "proxy.json"
    monkeypatch.setattr(core_config, "PROXY_SETTINGS_PATH", path)
    app = FastAPI()
    app.include_router(settings.router)
    cfg = IngestionConfig(proxy_mode="none")
    updates, restarts = [], []

    async def restart():
        restarts.append(True)

    def update(**values):
        updates.append(values)
        cfg.update(**values)

    app.state.data_engine_runtime = SimpleNamespace(get_ingestion_config=lambda: cfg,
        update_ingestion_config=update, restart_transports=restart)
    with TestClient(app) as client:
        payload = {"mode": "pool", "routes": config().proxy_routes, "strategy": "balanced"}
        response = client.put("/settings/proxy", json=payload)
        assert response.status_code == 200, response.text
        assert restarts == [True] and updates[0]["proxy_routes"] == payload["routes"]
        assert client.get("/settings/proxy").json()["strategy"] == "balanced"
        assert len(client.get("/settings/proxy/status").json()["routes"]) == 2
        before = path.read_bytes()
        response = client.put("/settings/proxy", json={"mode": "pool", "routes": []})
        assert response.status_code == 422 and path.read_bytes() == before


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ["failover", "balanced"])
async def test_ccxt_session_releases_old_route_before_backup_attach(strategy):
    from app.exchanges.ccxt_ext.session import CcxtProviderSession

    cfg = config(strategy=strategy)
    cfg.ws_reconnect_delay_initial = 0
    cfg.ws_reconnect_delay_max = 0
    attached, released = [], []
    session = None

    class Runtime:
        websocket_generation = 0

        def __init__(self, route):
            self.route = route

        def resolve_symbol(self, descriptor):
            return "BTC/USDT"

        def subscribe(self, *args):
            return "subscription"

        def unsubscribe(self, token):
            pass

        def snapshot(self):
            return {"route": self.route}

        async def watch(self, descriptor, symbol):
            if self.route == "a":
                raise OSError("primary offline")
            session._running = False
            return []

        async def rebuild_if_generation(self, generation):
            return True

    class Pool:
        async def acquire(self, profile, config, descriptor):
            attached.append(config.proxy_route_id)
            return Runtime(config.proxy_route_id)

        async def release(self, runtime, descriptor):
            released.append(runtime.route)

    profile = SimpleNamespace(supports=lambda descriptor: True)
    descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m")
    session = CcxtProviderSession(config=cfg, descriptor=descriptor, profile=profile, pool=Pool())
    session._running = True
    await session._watch_loop()
    assert attached == ["a", "b"] and released == ["a"]
    assert session.snapshot()["proxy_route_id"] == "b"
    await session.stop()
    assert released == ["a", "b"]
