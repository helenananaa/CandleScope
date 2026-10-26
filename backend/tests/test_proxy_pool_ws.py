"""Proxy-pool v2 qualification without any public exchange connections."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from websockets.asyncio.server import serve

from app.core.proxy_pool import ProxyPool, get_proxy_pool, normalize_proxy_pool
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import StreamDescriptor, StreamType
from app.data_engine.ingestion.session import SessionLayer
from app.data_engine.ingestion.shared_ws import SharedMultiplexHub, SharedWsHubRegistry
from app.data_engine.ingestion.transport import TransportError, TransportLayer
from app.exchanges.ccxt_ext.runtime import CcxtRuntimePool
from app.exchanges.ccxt_ext.session import CcxtProviderSession
from app.exchanges.plugins.binance.protocol import BinanceExchangeProtocol
from app.exchanges.protocol import WsConnectionSpec
from app.exchanges.rate_limits import RateLimitDeferred, RateLimitRule, get_shared_rate_limit_manager, scope_rate_limit_rule
from app.exchanges.ws_protocol import WsConnectionContext, WsSubscriptionSpec


def config(capacities=(4, 4), *, strategy="balanced", shared=False):
    return IngestionConfig(proxy_mode="pool", proxy_strategy=strategy, proxy_routes=[
        {"id": route_id, "name": route_id, "url": f"http://127.0.0.1:{31001 + index}",
         "egress_group": "shared" if shared else route_id, "max_ws_subscriptions": capacity,
         "enabled": True, "exchanges": [], "max_concurrency": 4}
        for index, (route_id, capacity) in enumerate(zip(("a", "b"), capacities))
    ])


def descriptor(index=0, *, market="spot"):
    return StreamDescriptor(f"SYM{index}USDT", StreamType.KLINE, interval="1m", market_type=market)


@pytest.mark.anyio
async def test_balancing_capacity_duplicate_references_and_idempotent_release():
    cfg, pool = config(), ProxyPool()
    leases = [pool.acquire_ws(cfg, [descriptor(index)]) for index in range(8)]
    assert [lease.route.id for lease in leases] == ["a", "b"] * 4
    duplicate = pool.acquire_ws(cfg, [descriptor(0)])
    assert duplicate.route == leases[0].route
    with pytest.raises(RateLimitDeferred) as deferred:
        pool.acquire_ws(cfg, [descriptor(8)])
    assert deferred.value.reason == "route_capacity"
    rows = pool.snapshot(cfg)["routes"]
    assert [row["ws_subscriptions"] for row in rows] == [4, 4]
    assert [row["ws_sessions"] for row in rows] == [5, 4]
    pool.release_ws(leases[0])
    assert pool.snapshot(cfg)["routes"][0]["ws_subscriptions"] == 4
    pool.release_ws(duplicate)
    pool.release_ws(duplicate)
    replacement = pool.acquire_ws(cfg, [descriptor(8)])
    assert replacement.route.id == "a"
    for lease in [*leases, replacement]:
        pool.release_ws(lease)
    assert all(row["ws_subscriptions"] == row["ws_sessions"] == 0 for row in pool.snapshot(cfg)["routes"])


@pytest.mark.anyio
async def test_capacity_weights_sticky_reconnect_market_identity_and_failover():
    cfg, pool = config((2, 4)), ProxyPool()
    leases = [pool.acquire_ws(cfg, [descriptor(index)]) for index in range(6)]
    assert [lease.route.id for lease in leases] == ["a", "b", "b", "a", "b", "b"]
    pool.release_ws(leases[1])
    reconnect = pool.acquire_ws(cfg, [descriptor(1)])
    assert reconnect.route.id == "b"
    for lease in [*leases, reconnect]:
        pool.release_ws(lease)
    first = pool.acquire_ws(cfg, [descriptor(10)])
    futures = pool.acquire_ws(cfg, [descriptor(10, market="futures")])
    assert first.route.id != futures.route.id
    pool.release_ws(first)
    pool.release_ws(futures)
    cfg.proxy_strategy = "failover"
    cfg.proxy_routes[0]["max_ws_subscriptions"] = 1
    a = pool.acquire_ws(cfg, [descriptor(20)])
    b = pool.acquire_ws(cfg, [descriptor(21)])
    assert a.route.id == "a" and b.route.id == "b"


@pytest.mark.anyio
async def test_multiplex_capacity_updates_are_atomic_and_duplicates_stay_on_route():
    cfg, pool = config((2, 2)), ProxyPool()
    lease = pool.acquire_ws(cfg, [descriptor(0), descriptor(1)])
    with pytest.raises(RateLimitDeferred):
        pool.update_ws(lease, [descriptor(0), descriptor(1), descriptor(2)])
    assert pool.snapshot(cfg)["routes"][0]["ws_subscriptions"] == 2
    pool.update_ws(lease, [descriptor(1)])
    another = pool.acquire_ws(cfg, [descriptor(2)])
    # The empty backup has less load, but an existing subscription is sticky.
    duplicate = pool.acquire_ws(cfg, [descriptor(1)])
    assert another.route.id == "b" and duplicate.route.id == "a"
    pool.release_ws(lease)
    pool.release_ws(duplicate)
    pool.release_ws(another)
    with pytest.raises(RateLimitDeferred):
        pool.acquire_ws(cfg, [descriptor(3), descriptor(4), descriptor(5)])
    assert all(row["ws_sessions"] == 0 for row in pool.snapshot(cfg)["routes"])


@pytest.mark.anyio
async def test_ip_ban_blocks_all_aliases_in_same_egress_and_network_failover_is_sticky():
    cfg, pool = config(shared=True), ProxyPool()
    lease = pool.acquire_ws(cfg, [descriptor()])
    manager = get_shared_rate_limit_manager()
    rule = scope_rate_limit_rule(RateLimitRule("weight", "binance:spot:ip", 10, 60), "shared")
    manager.record_response(rule, status_code=418, retry_after=10)
    with pytest.raises(RateLimitDeferred, match="route_cooldown"):
        pool.acquire_ws(cfg, [descriptor(1)])
    assert pool.health(lease.route, "binance", "ws").failures == 0
    pool.release_ws(lease)
    cfg = config()
    pool = ProxyPool()
    lease = pool.acquire_ws(cfg, [descriptor()])
    for _ in range(3):
        pool.record(lease.route, "binance", error=OSError("offline"), kind="ws")
    pool.release_ws(lease)
    backup = pool.acquire_ws(cfg, [descriptor()])
    assert backup.route.id == "b"
    pool.record(lease.route, "binance", kind="ws")
    pool.release_ws(backup)
    assert pool.acquire_ws(cfg, [descriptor()]).route.id == "b"


def test_legacy_routes_get_default_capacity_and_bad_capacities_are_rejected():
    routes = config().proxy_routes
    routes[0].pop("max_ws_subscriptions")
    assert normalize_proxy_pool(routes)[0][0]["max_ws_subscriptions"] == 64
    for invalid in (0, 4097, True, 1.5):
        with pytest.raises(ValueError, match="subscription capacity"):
            normalize_proxy_pool([{**routes[0], "max_ws_subscriptions": invalid}])


class Socket:
    def __init__(self):
        self.closed = 0
        self.sent = []
        self.receive = asyncio.Event()

    async def close(self):
        self.closed += 1

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        await self.receive.wait()
        return {}

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.receive.wait()
        raise StopAsyncIteration


@pytest.mark.anyio
async def test_native_connect_failure_cancellation_failed_handshake_and_stop_release_capacity(monkeypatch):
    cfg = config()
    transport = TransportLayer(cfg)
    pool = get_proxy_pool()
    sockets = []

    async def connect(desc, **kwargs):
        socket = Socket()
        sockets.append(socket)
        return WsConnectionContext(socket, "local", WsSubscriptionSpec())

    monkeypatch.setattr(transport, "_ws_connect", connect)
    a, b = await asyncio.gather(transport.ws_connect(descriptor()), transport.ws_connect(descriptor(1)))
    assert [a.proxy_route.id, b.proxy_route.id] == ["a", "b"]
    assert [row["native_websockets"] for row in pool.snapshot(cfg)["routes"]] == [1, 1]
    await transport.ws_close(a)

    async def rejected(_ctx, **kwargs):
        raise TransportError("fake subscription failure")

    monkeypatch.setattr(transport, "ws_subscribe", rejected)
    assert not await transport.ws_probe(descriptor(2))
    assert sockets[-1].closed == 1
    assert sum(row["ws_sessions"] for row in pool.snapshot(cfg)["routes"]) == 1
    ready = asyncio.Event()

    async def blocked(desc, **kwargs):
        ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(transport, "_ws_connect", blocked)
    task = asyncio.create_task(transport.ws_connect(descriptor(3)))
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sum(row["ws_sessions"] for row in pool.snapshot(cfg)["routes"]) == 1
    transport._registry = SimpleNamespace(list_plugins=lambda: [])
    await transport.stop()
    assert b.connection.closed == 1
    assert all(row["ws_sessions"] == 0 for row in pool.snapshot(cfg)["routes"])


@pytest.mark.anyio
async def test_native_session_failed_subscribe_closes_context_and_releases_lease(monkeypatch):
    cfg, transport = config(), TransportLayer(config())
    socket = Socket()

    async def connect(desc, **kwargs):
        return WsConnectionContext(socket, "local", WsSubscriptionSpec())

    async def subscribe(ctx, **kwargs):
        raise TransportError("fake rejection")

    monkeypatch.setattr(transport, "_ws_connect", connect)
    monkeypatch.setattr(transport, "ws_subscribe", subscribe)
    session = SessionLayer(cfg, transport, descriptor())
    await session._connect()
    assert socket.closed == 1 and session._ws_context is None
    assert all(row["ws_sessions"] == 0 for row in get_proxy_pool().snapshot(cfg)["routes"])


@pytest.mark.anyio
async def test_native_cancelled_handshake_and_capacity_deferral_do_not_leak_or_mark_failure(monkeypatch):
    cfg = config((1, 1))
    cfg.proxy_routes[1]["enabled"] = False
    transport = TransportLayer(cfg)
    socket = Socket()
    entered = asyncio.Event()

    async def connect(desc, **kwargs):
        return WsConnectionContext(socket, "local", WsSubscriptionSpec())

    async def subscribe(ctx, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(transport, "_ws_connect", connect)
    monkeypatch.setattr(transport, "ws_subscribe", subscribe)
    pool = get_proxy_pool()
    held = pool.acquire_ws(cfg, [descriptor(10)])
    session = SessionLayer(cfg, transport, descriptor(0))
    deferred = asyncio.Event()

    async def health(state, reason):
        if reason == "proxy capacity or cooldown":
            deferred.set()

    session.on_health_change(health)
    try:
        await session.start()
        await asyncio.wait_for(deferred.wait(), timeout=2)
        assert session.consecutive_failures == 0 and not entered.is_set()
        pool.release_ws(held)
        await asyncio.wait_for(entered.wait(), timeout=2)
    finally:
        pool.release_ws(held)
        await session.stop()
    assert socket.closed == 1
    assert all(row["ws_sessions"] == 0 for row in pool.snapshot(cfg)["routes"])


class Profile:
    exchange_id = "binance"
    market_type = "spot"

    def __init__(self, *, fail=False, block=None):
        self.exchanges = []
        self.fail, self.block = fail, block

    def runtime_key(self, cfg):
        return (self.exchange_id, self.market_type, cfg.http_proxy or "")

    def supports(self, desc):
        return True

    def create_exchange(self, cfg, **kwargs):
        profile = self

        class Exchange:
            clients = {"wss://local.invalid": object()}
            closed = False

            async def load_markets(self):
                if profile.block:
                    await profile.block.wait()
                if profile.fail:
                    raise OSError("fake load failure")

            async def close(self, clean_instance_data=False):
                self.closed = True
                self.clients = {}

        exchange = Exchange()
        self.exchanges.append(exchange)
        return exchange

    def resolve_symbol(self, exchange, desc):
        return desc.symbol


@pytest.mark.anyio
async def test_ccxt_real_pool_reuses_duplicate_descriptors_and_partitions_routes(monkeypatch):
    from app.exchanges.ccxt_ext import runtime as module
    cfg, pool, profile = config(), CcxtRuntimePool(), Profile()
    monkeypatch.setattr(module, "_SHARED_POOL", pool)
    sessions = [CcxtProviderSession(config=cfg, descriptor=descriptor(index), profile=profile, pool=pool)
                for index in [0, 1, 0, 2]]
    try:
        await asyncio.gather(*(session._attach_runtime() for session in sessions))
        assert [session._proxy_route.id for session in sessions] == ["a", "b", "a", "a"]
        assert sessions[0]._runtime is sessions[2]._runtime is sessions[3]._runtime
        assert len(profile.exchanges) == 2
        rows = get_proxy_pool().snapshot(cfg)["routes"]
        assert [row["ws_subscriptions"] for row in rows] == [2, 1]
        assert [row["ccxt_runtimes"] for row in rows] == [1, 1]
        assert [row["ccxt_physical_websockets"] for row in rows] == [1, 1]
    finally:
        for session in sessions:
            await session.stop()
    assert pool.snapshot() == {"runtimes": {}}
    assert all(exchange.closed for exchange in profile.exchanges)
    assert all(row["ws_sessions"] == 0 for row in get_proxy_pool().snapshot(cfg)["routes"])


@pytest.mark.anyio
@pytest.mark.parametrize("cancel", [False, True])
async def test_ccxt_start_failure_and_cancellation_do_not_hold_proxy_capacity(cancel):
    cfg, pool = config(), CcxtRuntimePool()
    unblock = asyncio.Event() if cancel else None
    profile = Profile(fail=not cancel, block=unblock)
    session = CcxtProviderSession(config=cfg, descriptor=descriptor(), profile=profile, pool=pool)
    if cancel:
        task = asyncio.create_task(session._attach_runtime())
        for _ in range(20):
            await asyncio.sleep(0)
            if profile.exchanges:
                break
        task.cancel()
        unblock.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(OSError):
            await session._attach_runtime()
    assert pool.snapshot() == {"runtimes": {}}
    assert all(exchange.closed for exchange in profile.exchanges)
    assert all(row["ws_sessions"] == 0 for row in get_proxy_pool().snapshot(cfg)["routes"])


@pytest.mark.anyio
async def test_shared_hub_capacity_counts_whole_batch_and_dynamic_unsubscribe(monkeypatch):
    cfg = config((2, 2))
    transport = TransportLayer(cfg)
    socket = Socket()

    async def connect(desc, **kwargs):
        return WsConnectionContext(socket, "local", WsSubscriptionSpec())

    monkeypatch.setattr(transport, "_ws_connect", connect)
    hub = SharedMultiplexHub(cfg, transport, "binance", "spot", "local", max_descriptors=2,
                             protocol=BinanceExchangeProtocol())
    monkeypatch.setattr(hub, "_ensure_runner", lambda: None)

    async def no_op(*args):
        pass

    first = await hub.subscribe(descriptor(0), no_op, no_op)
    second = await hub.subscribe(descriptor(1), no_op, no_op)
    hub._ctx = await transport.ws_connect(descriptor(0), shared_descriptors=hub._unique_descriptors())
    hub._conn = socket
    assert get_proxy_pool().snapshot(cfg)["routes"][0]["ws_subscriptions"] == 2
    await second.unsubscribe()
    assert get_proxy_pool().snapshot(cfg)["routes"][0]["ws_subscriptions"] == 1
    await first.unsubscribe()
    assert socket.closed == 1
    assert all(row["ws_sessions"] == 0 for row in get_proxy_pool().snapshot(cfg)["routes"])


@pytest.mark.anyio
async def test_shared_hub_registry_respects_smallest_route_capacity_for_backup(monkeypatch):
    from app.data_engine.ingestion import shared_ws as module
    protocol = BinanceExchangeProtocol()
    plugin = SimpleNamespace(capabilities=lambda: SimpleNamespace(
        capability_schema_version=1, ws_connection_model="shared_multiplex"), protocol=lambda: protocol)
    monkeypatch.setattr(module, "get_exchange_registry", lambda: SimpleNamespace(get_plugin=lambda exchange: plugin))
    cfg = config((1, 4))
    registry = SharedWsHubRegistry(cfg, TransportLayer(cfg), max_descriptors_per_shard=8)
    first = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m")
    second = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="5m")
    a, b = registry.get_hub(first), registry.get_hub(second)
    assert a is not None and b is not None and a is not b
    assert a.snapshot()["max_descriptors"] == 1


@pytest.mark.anyio
async def test_real_local_connect_proxies_carry_balanced_websocket_connections():
    """HTTP CONNECT and WebSocket traffic stay entirely on loopback, including DNS."""
    sockets = []
    proxy_servers = []
    proxy_tasks = set()
    connects = [0, 0]

    async def upstream(connection):
        await connection.send('{"test":"local websocket"}')
        await connection.wait_closed()

    async with serve(upstream, "127.0.0.1", 0) as websocket_server:
        upstream_port = websocket_server.sockets[0].getsockname()[1]

        def proxy_handler(index):
            async def handle(reader, writer):
                task = asyncio.current_task()
                proxy_tasks.add(task)
                remote_writer = None
                relays = []
                try:
                    request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3)
                    assert request.startswith(b"CONNECT exchange.invalid:80 HTTP/1.1")
                    connects[index] += 1
                    remote_reader, remote_writer = await asyncio.open_connection("127.0.0.1", upstream_port)
                    writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    await writer.drain()

                    async def relay(source, target):
                        while data := await source.read(65536):
                            target.write(data)
                            await target.drain()

                    relays = [asyncio.create_task(relay(reader, remote_writer)),
                              asyncio.create_task(relay(remote_reader, writer))]
                    await asyncio.wait(relays, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for relay_task in relays:
                        relay_task.cancel()
                    await asyncio.gather(*relays, return_exceptions=True)
                    for stream in (remote_writer, writer):
                        if stream is not None:
                            stream.close()
                            await stream.wait_closed()
                    proxy_tasks.discard(task)
            return handle

        cfg = config((1, 1))
        for index in range(2):
            server = await asyncio.start_server(proxy_handler(index), "127.0.0.1", 0)
            proxy_servers.append(server)
            cfg.proxy_routes[index]["url"] = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        protocol = SimpleNamespace(ws_connection=lambda desc, config: WsConnectionSpec(
            ["ws://exchange.invalid"], WsSubscriptionSpec(stream_name="local")))
        transport = TransportLayer(cfg)
        transport._registry = SimpleNamespace(get_plugin=lambda exchange: SimpleNamespace(protocol=lambda: protocol),
                                             list_plugins=lambda: [])
        try:
            sockets = await asyncio.gather(transport.ws_connect(descriptor(0)), transport.ws_connect(descriptor(1)))
            assert [ctx.proxy_route.id for ctx in sockets] == ["a", "b"]
            assert connects == [1, 1]
            for index, ctx in enumerate(sockets):
                session = SessionLayer(cfg, transport, descriptor(index))
                session._ws_context = ctx
                payload = await ctx.connection.recv()
                assert payload == '{"test":"local websocket"}'
                await session._handle_payload(payload)
            traffic = [row["ws_traffic"] for row in get_proxy_pool().snapshot(cfg)["routes"]]
            assert [row["messages_total"] for row in traffic] == [1, 1]
            assert [row["payload_bytes_total"] for row in traffic] == [26, 26]
            with pytest.raises(RateLimitDeferred, match="route_capacity"):
                await transport.ws_connect(descriptor(2))
            assert connects == [1, 1]
            await transport.stop()
            assert all(row["native_websockets"] == row["ws_sessions"] == 0
                       for row in get_proxy_pool().snapshot(cfg)["routes"])
        finally:
            for ctx in sockets:
                await transport.ws_close(ctx)
            for server in proxy_servers:
                server.close()
                await server.wait_closed()
            for task in list(proxy_tasks):
                task.cancel()
            await asyncio.gather(*proxy_tasks, return_exceptions=True)
