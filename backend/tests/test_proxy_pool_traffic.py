"""Measured placement and physical receive accounting, without public traffic."""
from __future__ import annotations

from types import SimpleNamespace

import ccxt.pro as ccxtpro
import pytest
from aiohttp import WSMessage, WSMsgType

from app.core import proxy_pool as module
from app.core.proxy_pool import ProxyPool, get_proxy_pool
from app.data_engine.ingestion.session import SessionLayer
from app.data_engine.ingestion.shared_ws import SharedMultiplexHub
from app.data_engine.ingestion.transport import _ProxyObservedWebSocket
from app.exchanges.ccxt_ext.models import CcxtRawMarketEvent
from app.exchanges.ccxt_ext.runtime import CcxtRuntime, CcxtRuntimePool
from app.exchanges.ccxt_ext.session import CcxtProviderSession
from app.exchanges.plugins.binance.protocol import BinanceExchangeProtocol
from app.exchanges.ws_protocol import WsConnectionContext, WsSubscriptionSpec
from tests.test_proxy_pool_ws import config, descriptor, Profile


@pytest.mark.anyio
async def test_window_bytes_expire_and_observations_are_bounded(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    cfg, pool = config(), ProxyPool()
    route = pool.routes(cfg, "binance")[0]
    pool.record_ws_traffic(route, "行情")
    pool.record_ws_traffic(route, b"1234")
    pool.record_ws_traffic(route, disconnected=True)
    row = pool.ws_traffic(route.url)
    assert row["messages_total"] == 2 and row["payload_bytes_total"] == 10
    assert row["messages_per_second"] == pytest.approx(2 / 30)
    assert row["payload_bytes_per_second"] == pytest.approx(10 / 30)
    assert row["disconnects_recent"] == 1
    clock[0] += 30
    row = pool.ws_traffic(route.url)
    assert row["messages_per_second"] == row["payload_bytes_per_second"] == row["disconnects_recent"] == 0
    assert row["messages_total"] == 2 and row["last_message_age_seconds"] == 30
    for index in range(200):
        pool.record_ws_traffic(f"http://localhost:{index + 1}", "x")
    assert len(pool._ws_traffic) == 128
    for index in range(100):
        clock[0] += 1
        pool.record_ws_traffic("http://localhost:200", "x")
    assert len(pool._ws_traffic["http://localhost:200"].buckets) == 30


@pytest.mark.anyio
async def test_measured_placement_reconnect_and_active_duplicate_affinity():
    cfg, pool = config((10, 10)), ProxyPool()
    a = pool.acquire_ws(cfg, [descriptor(0)])
    b = pool.acquire_ws(cfg, [descriptor(1)])
    for _ in range(30):
        pool.record_ws_traffic(a.route, "x" * 4096)
    pool.record_ws_traffic(b.route, "x")
    newcomer = pool.acquire_ws(cfg, [descriptor(2)])
    assert newcomer.route.id == "b"
    duplicate = pool.acquire_ws(cfg, [descriptor(0)])
    assert duplicate.route.id == "a"  # no relocation of a live descriptor
    pool.release_ws(a)
    pool.release_ws(duplicate)
    reconnect = pool.acquire_ws(cfg, [descriptor(0)])
    assert reconnect.route.id == "b"  # history cannot override measured pressure
    assert b.route.id == "b" and newcomer.route.id == "b"
    cfg.proxy_strategy = "failover"
    assert pool.acquire_ws(cfg, [descriptor(3)]).route.id == "a"


@pytest.mark.anyio
async def test_queue_pressure_clears_on_release_and_capacity_remains_hard_limit():
    cfg, pool = config((2, 2)), ProxyPool()
    a = pool.acquire_ws(cfg, [descriptor(0)])
    b = pool.acquire_ws(cfg, [descriptor(1)])
    pool.observe_ws_queue(a, 10, 10)
    pool.observe_ws_queue(b, 0, 10)
    assert pool.acquire_ws(cfg, [descriptor(2)]).route.id == "b"
    assert pool.acquire_ws(cfg, [descriptor(3)]).route.id == "a"  # b is full
    pool.release_ws(a)
    pool.observe_ws_queue(a, 10, 10)  # stale callback is ignored
    assert pool.ws_traffic(a.route.url)["queue_size"] == 0
    assert pool.ws_traffic(a.route.url)["queue_pressure"] == 0


@pytest.mark.anyio
async def test_receive_counted_once_at_real_ccxt_client_before_decoding():
    cfg = config()
    route = get_proxy_pool().routes(cfg, "binance")[0]
    exchange = ccxtpro.binance({"enableRateLimit": True})
    # Precreate the real CCXT client with inert lifecycle callbacks. No dial.
    upstream = exchange.client("wss://exchange.invalid/ws")
    decoded = []
    upstream.on_message_callback = lambda client, message: decoded.append(message)
    upstream.on_close = lambda code: None
    upstream.on_connected_callback = lambda client: None
    profile = SimpleNamespace(create_exchange=lambda *args, **kwargs: exchange)
    runtime = CcxtRuntime(profile, route.bind(cfg))
    client = exchange.client(upstream.url)
    assert exchange.client(upstream.url) is client
    payload = '{"行情": "价格"}'
    client.handle_message(WSMessage(WSMsgType.TEXT, payload, ""))
    client.handle_message(WSMessage(WSMsgType.BINARY, b'{"x":1}', ""))
    assert decoded == [{"行情": "价格"}, {"x": 1}]
    row = get_proxy_pool().ws_traffic(route.url)
    assert row["messages_total"] == 2
    assert row["payload_bytes_total"] == len(payload.encode()) + 7
    client.on_close(1006)
    client.on_close(1006)
    client.on_connected_callback(client)
    client.on_close(1006)  # reconnection can disconnect before first data
    assert get_proxy_pool().ws_traffic(route.url)["disconnects_total"] == 2
    runtime._closed = True
    client.handle_message(WSMessage(WSMsgType.TEXT, '{"x":2}', ""))
    assert get_proxy_pool().ws_traffic(route.url)["messages_total"] == 2
    await exchange.close()


@pytest.mark.anyio
async def test_native_receive_and_disconnect_counts_once():
    cfg, pool = config(), get_proxy_pool()
    lease = pool.acquire_ws(cfg, [descriptor()])
    pool.mark_ws_connected(lease)
    transport = SimpleNamespace(current_ws_base="local")
    session = SessionLayer(cfg, transport, descriptor())
    session._ws_context = WsConnectionContext(None, "local", WsSubscriptionSpec(),
                                             proxy_route=lease.route, proxy_ws_lease=lease)
    payloads = iter(['{"x":"行情"}', 'malformed'])
    async def recv():
        return next(payloads)
    socket = _ProxyObservedWebSocket(SimpleNamespace(recv=recv), pool, lease)
    await session._handle_payload(await socket.recv())
    await session._handle_payload(await socket.recv())
    assert pool.ws_traffic(lease.route.url)["messages_total"] == 2
    pool.mark_ws_disconnected(lease)
    pool.mark_ws_disconnected(lease)
    assert pool.ws_traffic(lease.route.url)["disconnects_total"] == 1
    pool.release_ws(lease)


@pytest.mark.anyio
async def test_native_multiplex_counts_receive_before_fanout(monkeypatch):
    cfg, pool = config(), get_proxy_pool()
    lease = pool.acquire_ws(cfg, [descriptor(0), descriptor(1)])
    hub = SharedMultiplexHub(cfg, SimpleNamespace(), "binance", "spot", "local",
                             max_descriptors=2, protocol=BinanceExchangeProtocol())
    reads = iter(['{"result":null,"id":1}', '{"s":"SYM0USDT"}'])
    async def recv():
        try:
            return next(reads)
        except StopIteration:
            raise OSError("controlled disconnect") from None
    hub._subscribers = {"dummy": object()}
    hub._conn = _ProxyObservedWebSocket(SimpleNamespace(recv=recv), pool, lease)
    hub._ctx = WsConnectionContext(hub._conn, "local", WsSubscriptionSpec(),
                                   proxy_route=lease.route, proxy_ws_lease=lease)
    dispatched = []
    async def dispatch(payload):
        dispatched.append(payload)
    monkeypatch.setattr(hub, "_dispatch_payload", dispatch)
    with pytest.raises(OSError):
        await hub._read_loop()
    assert len(dispatched) == 1  # ACK also contributes to actual receive traffic
    assert pool.ws_traffic(lease.route.url)["messages_total"] == 2
    pool.release_ws(lease)


@pytest.mark.anyio
async def test_ccxt_delivery_queue_observation_drains_and_releases():
    cfg, pool = config(), get_proxy_pool()
    session = CcxtProviderSession(config=cfg, descriptor=descriptor(), profile=Profile())
    session._proxy_ws_lease = pool.acquire_ws(cfg, [descriptor()], kind="ccxt")
    event = CcxtRawMarketEvent("kline", "SYM0USDT", {}, 123)
    session._enqueue_raw(event)
    row = pool.ws_traffic(session._proxy_ws_lease.route.url)
    assert row["queue_size"] == 1 and row["queue_capacity"] == session._queue.maxsize
    assert row["messages_total"] == 0  # fanout never counts a physical receive
    async def delivered(message):
        session._running = False
    session._on_message = delivered
    session._running = True
    await session._delivery_loop()
    assert pool.ws_traffic(session._proxy_ws_lease.route.url)["queue_size"] == 0
    await session.stop()
    assert pool.snapshot(cfg)["routes"][0]["ws_traffic"]["queue_capacity"] == 0


@pytest.mark.anyio
async def test_ccxt_reattachment_uses_measured_load_and_keeps_other_session():
    cfg, routes, runtimes, profile = config((10, 10)), get_proxy_pool(), CcxtRuntimePool(), Profile()
    a, b = [CcxtProviderSession(config=cfg, descriptor=descriptor(index), profile=profile, pool=runtimes)
            for index in (0, 1)]
    try:
        await a._attach_runtime()
        await b._attach_runtime()
        b_runtime = b._runtime
        for _ in range(30):
            routes.record_ws_traffic(a._proxy_route, "x" * 1024)
        await a._detach_runtime()
        await a._attach_runtime()
        assert a._proxy_route.id == "b"
        assert a._runtime is b_runtime is b._runtime
        assert routes.snapshot(cfg)["routes"][0]["ws_sessions"] == 0
        assert routes.snapshot(cfg)["routes"][1]["ws_sessions"] == 2
    finally:
        await a.stop()
        await b.stop()
    assert runtimes.snapshot() == {"runtimes": {}}
