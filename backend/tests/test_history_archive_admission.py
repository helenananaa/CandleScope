"""Cross-loop admission, foreground reservation, replay wiring and drained writes."""
import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from aiohttp import web

from app.core.proxy_pool import ProxyPool, get_proxy_pool
from app.exchanges.archive import ArchiveHttpResponse
from tests.test_history_archive_proxy_pool import client, config, network, tls


async def queued(pool, count):
    async with asyncio.timeout(2):
        while pool.archive_admission_snapshot()["queued"] != count:
            await asyncio.sleep(0.005)


def test_archive_shares_public_execution_and_settles_each_attempt_once():
    from app.exchanges.public_admission import PublicDemand, TrafficClass, get_public_admission, public_demand
    from app.exchanges.rate_limits import HistoricalRequest, RateLimitDeferred, RateLimitRule

    async def run():
        pool, cfg = ProxyPool(), config(["http://localhost:31999"])
        scheduler = get_public_admission()
        scheduler.max_in_flight = 1
        rest = RateLimitRule("rest", "binance:ip", 10, 1)
        permit = await scheduler.acquire([rest], HistoricalRequest("binance", "spot", "/klines", ""))
        with public_demand(PublicDemand(TrafficClass.BACKGROUND, defer=True)):
            with pytest.raises(RateLimitDeferred, match="execution_capacity"):
                await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set())
        assert not pool._archive_leases and not any(pool._active.values())
        permit.finish(status_code=200)
        lease = await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set())
        assert lease.public_permit.scheduler is scheduler
        assert scheduler.snapshot()["in_flight"] == 1
        pool.finish_archive(lease, elapsed=1, received_bytes=20, status=200)
        pool.finish_archive(lease, elapsed=1, received_bytes=20, status=200)
        snapshot = scheduler.snapshot()
        assert snapshot["counts"]["attempts"] == snapshot["counts"]["completed"] == 2
        assert snapshot["in_flight"] == 0
        assert pool.archive_traffic(lease.route.url)["payload_bytes_total"] == 20
        assert snapshot["recent"][-1]["buckets"] == ["archive:cdn:egress=exit-0"]
    asyncio.run(run())


def test_archive_admission_deferral_is_not_negative_cached_or_probe_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.data_engine.backfill.config import BackfillConfig
    from app.data_engine.backfill.source_router import HistoricalSourceRouter
    from app.exchanges.rate_limits import HistoricalRequest, RateLimitRule
    from app.exchanges.public_admission import get_public_admission

    async def run():
        router = HistoricalSourceRouter(BackfillConfig(history_archive_cache_dir=str(tmp_path)))
        error = get_public_admission()._deferred(RateLimitRule("cdn", "archive:cdn", 1, 1),
            HistoricalRequest("binance", "archive", "/object", ""), "execution_capacity")
        async def deferred(*args):
            raise error
        task = asyncio.create_task(deferred())
        with pytest.raises(type(error)):
            await task
        router._remember_completed_failure("object", task)
        assert not router._failed_cache
        provider = SimpleNamespace(id="fixture", capabilities=lambda _: SimpleNamespace(
            probe_symbol="BTCUSDT", probe_market_type="spot", intervals=("1m",)),
            plan_objects=lambda **_: [], resolve_objects=deferred)
        with pytest.raises(type(error)):
            await router._probe_provider("binance", provider)
        assert not router._probe_retry_at and not router._disabled_providers
    asyncio.run(run())


def test_priority_queue_reserves_rest_and_is_bounded():
    async def run():
        pool, cfg = ProxyPool(), config(["http://localhost:32001"])
        held = await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set())
        # REST enters before the long ZIP stream ends; websocket capacity is independent.
        pool.begin(held.route, "binance")
        pool.end(held.route)
        order = []
        async def acquire(name, priority):
            lease = await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set(),
                                               priority=priority, source_id="fixture", object_key=name)
            order.append(name)
            pool.finish_archive(lease, elapsed=1, received_bytes=1, status=200)
        background = asyncio.create_task(acquire("background", "background"))
        await queued(pool, 1)
        foreground = asyncio.create_task(acquire("foreground", "foreground"))
        await queued(pool, 2)
        pool._http.queue_limit = 2
        with pytest.raises(ValueError, match="queue full"):
            await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set())
        pool.finish_archive(held, elapsed=1, received_bytes=1, status=200)
        await asyncio.wait_for(asyncio.gather(background, foreground), 2)
        assert order == ["foreground", "background"]
        assert pool.archive_admission_snapshot()["queued"] == 0
        cfg.proxy_routes[0]["max_concurrency"] = 1
        with pytest.raises(ValueError, match="foreground capacity"):
            await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set())
    asyncio.run(run())


def test_process_budget_spans_worker_loops_and_direct_downloads():
    cfg = config([f"http://localhost:{32100 + i}" for i in range(4)])
    release, entered = threading.Event(), threading.Event()
    counts = []
    def worker():
        async def run():
            pool = get_proxy_pool()
            leases = [await pool.acquire_archive(cfg, "binance", f"cdn{i}", exclude_urls=set())
                      for i in range(3)]
            entered.set()
            await asyncio.to_thread(release.wait)
            for lease in leases:
                pool.finish_archive(lease, elapsed=1, received_bytes=1, status=200)
        asyncio.run(run())
    async def foreground():
        pool = get_proxy_pool()
        assert pool.archive_admission_snapshot()["active"] == 3
        # The fourth slot is available to foreground replay, across loops/modes.
        direct = config([])
        direct.proxy_mode = "none"
        lease = await pool.acquire_archive(direct, "binance", "replay-cdn", exclude_urls=set(),
                                           priority="foreground")
        counts.append(pool.archive_admission_snapshot()["active"])
        waiting = asyncio.create_task(pool.acquire_archive(cfg, "binance", "fifth-cdn", exclude_urls=set(),
                                                           priority="foreground"))
        await queued(pool, 1)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        pool.finish_archive(lease, elapsed=1, received_bytes=1, status=200)
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker_result = executor.submit(worker)
        try:
            assert entered.wait(2)
            asyncio.run(foreground())
        finally:
            release.set()
        worker_result.result(timeout=3)
    assert counts == [4]
    async def empty():
        assert get_proxy_pool().archive_admission_snapshot()["active"] == 0
    asyncio.run(empty())


def test_balancing_uses_measured_bytes_per_second_for_large_bodies():
    async def run():
        pool = ProxyPool()
        cfg = config(["http://localhost:32200", "http://localhost:32201"], strategy="balanced")
        for index, (size, duration) in enumerate([(1024**2, 1), (10 * 1024**2, 2)]):
            excluded = {cfg.proxy_routes[1-index]["url"]}
            lease = await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=excluded)
            pool.finish_archive(lease, elapsed=duration, received_bytes=size, status=200)
        lease = await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set())
        assert lease.route.id == "route-1"  # Longer duration, five times the delivered throughput.
        pool.finish_archive(lease, elapsed=0, received_bytes=0, cancelled=True)
    asyncio.run(run())


def test_replay_uses_saved_pool_and_reopens_import_offline(monkeypatch, tmp_path, tls):
    from app.replay.official_chart_archive import OfficialChartArchive
    from tests.test_official_chart_archive import IDENTITY, START, DAY, payload
    from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider
    async def run():
        provider = BinanceKlineArchiveProvider()
        ref = provider.plan_objects(market_type="futures", symbol="BTCUSDT", interval="1m",
                                    start_ms=START, end_ms=START + DAY - 1,
                                    now_ms=START + 90 * DAY)[0]
        body = payload(ref.url)
        digest = hashlib.sha256(body).hexdigest()
        async def serve(request):
            return web.Response(body=(f"{digest}  {ref.expected_filename}\n".encode()
                                     if request.path.endswith(".CHECKSUM") else body))
        async with network(monkeypatch, tls, serve, ("bad", "good")) as (urls, connects, _):
            cfg = config(urls)
            saved = {"mode": "pool", "custom_proxy": None, "routes": cfg.proxy_routes, "strategy": "failover"}
            monkeypatch.setattr("app.core.config.load_proxy_settings", lambda: saved)
            archive = OfficialChartArchive(tmp_path, 5)
            root = tmp_path / "day"
            # A synchronous replay reader already owns the only storage worker.
            # Archive work must use its separate pool, including parser/import.
            from app.core import executors
            from app.core.bounded_executor import BoundedExecutor
            storage_executor = BoundedExecutor("test-storage", max_workers=1, max_pending=1)
            with monkeypatch.context() as patch:
                patch.setattr(executors, "_storage_executor", storage_executor)
                try:
                    await asyncio.wait_for(executors.run_storage(archive.download, root, IDENTITY, ref), 10)
                finally:
                    storage_executor.shutdown()

            assert [len(c) for c in connects] == [1, 2]
            assert not get_proxy_pool()._archive_leases
            # The replay repository is durable and does not rely on the ZIP.
            from app.replay.history_archive import ReplayHistoryRepository
            restored = ReplayHistoryRepository(root)
            assert restored.list_all_series()[0]["total_count"] == (ref.end_ms - ref.start_ms + 1) // 60_000
    asyncio.run(run())


def test_cancelled_disk_write_drains_before_route_release(monkeypatch, tmp_path, tls):
    from app.core.executors import run_storage
    started, release = threading.Event(), threading.Event()
    async def delayed_write(func, *args):
        def block():
            started.set()
            release.wait(3)
            return func(*args)
        return await run_storage(block)
    monkeypatch.setattr("app.data_engine.backfill.archive_cache.run_archive", delayed_write)
    async def run():
        async def serve(request):
            return web.Response(body=b"x" * 65536)
        async with network(monkeypatch, tls, serve, ("good",)) as (urls, _, _):
            task = asyncio.create_task(client(config(urls)).download(
                "https://archive.invalid/file", tmp_path / "file", allowed_hosts=("archive.invalid",), max_bytes=100000))
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            assert len(get_proxy_pool()._archive_leases) == 1
            # Event loop remains responsive while physical I/O owns its lease.
            await asyncio.wait_for(asyncio.sleep(0), .5)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not get_proxy_pool()._archive_leases
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_archive_stream_allows_real_foreground_rest_and_ws(monkeypatch, tmp_path, tls):
    import json
    import os
    import time
    from types import SimpleNamespace
    import aiohttp
    from app.data_engine.ingestion.transport import TransportLayer
    from app.data_engine.ingestion.models import StreamDescriptor, StreamType, TransportRequest
    from app.exchanges.plugins.binance.plugin import BinancePlugin
    from app.exchanges.rate_limits import RateLimitManager
    async def run():
        opened, release = asyncio.Event(), asyncio.Event()
        async def serve(request):
            if request.path == "/archive":
                response = web.StreamResponse(headers={"Content-Length": "65536"})
                await response.prepare(request)
                await response.write(b"x" * 65536)
                opened.set()
                await release.wait()
                return response
            if request.path == "/ws":
                ws = web.WebSocketResponse()
                await ws.prepare(request)
                for i in range(10):
                    await ws.send_str(str(i))
                    await asyncio.sleep(0)
                await ws.close()
                return ws
            return web.json_response([[1700000000000, "1", "2", "1", "2", "3", 1700000059999, "4", 1, "2", "2", "0"]])
        async with network(monkeypatch, tls, serve, ("good",)) as (urls, connects, requests):
            cfg = config(urls)
            cfg.http_base_urls = ["https://archive.invalid"]
            transport = TransportLayer(cfg)
            transport._registry = SimpleNamespace(get_plugin=lambda _: BinancePlugin())
            transport._rate_limits = RateLimitManager()
            # Hold a response body until both foreground paths have completed.
            async def long_attempt(proxy, observe):
                async with aiohttp.ClientSession() as session:
                    async with session.get("https://archive.invalid/archive", proxy=proxy) as response:
                        data = await response.content.readexactly(65536)
                        observe(len(data))
                        await release.wait()
                        return ArchiveHttpResponse(200, {})
            from app.data_engine.ingestion.archive_transport import request_archive
            task = asyncio.create_task(request_archive(cfg, lambda: None, "binance",
                "https://archive.invalid/archive", long_attempt, timeout_seconds=5))
            descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m")
            pool = get_proxy_pool()
            ws_lease = None
            try:
                await asyncio.wait_for(opened.wait(), 2)
                started = time.monotonic()
                messages = await asyncio.wait_for(transport.http_fetch(TransportRequest(descriptor, limit=1000)), 2)
                elapsed_ms = (time.monotonic() - started) * 1000
                assert len(messages) == 1 and not task.done()
                ws_lease = pool.acquire_ws(cfg, [descriptor])
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect("https://archive.invalid/ws", proxy=ws_lease.route.url) as ws:
                        received = []
                        async for message in ws:
                            received.append(message.data)
                            pool.record_ws_receive(ws_lease, message.data)
                assert received == [str(i) for i in range(10)] and not task.done()
                if destination := os.getenv("CANDLE_ARCHIVE_BENCH_OUTPUT"):
                    from pathlib import Path
                    Path(destination).write_text(json.dumps({"kind": "controlled-loopback-admission",
                        "foreground_rest_ms": round(elapsed_ms, 3), "ws_messages_during_archive": len(received),
                        "archive_payload_bytes": 65536, "proxy_connections": len(connects[0]),
                        "public_egress_verified": False, "native_first_paint_measured": False}, indent=2))
            finally:
                release.set()
                await task
                pool.release_ws(ws_lease)
                if transport._http_session:
                    await transport._http_session.close()
            assert not pool._archive_leases and not any(pool._active.values())
    asyncio.run(run())


def test_download_rollback_switch_rejects_waiting_work_and_leaves_owned_stream():
    async def run():
        pool, cfg = ProxyPool(), config(["http://localhost:32500"])
        held = await pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set())
        waiting = asyncio.create_task(pool.acquire_archive(cfg, "binance", "cdn", exclude_urls=set()))
        await queued(pool, 1)
        cfg.archive_downloads_enabled = False
        with pytest.raises(ValueError, match="downloads disabled"):
            await asyncio.wait_for(waiting, 1)
        assert len(pool._archive_leases) == 1 and not pool._http.waiters
        pool.finish_archive(held, elapsed=0, received_bytes=0, cancelled=True)
        from app.data_engine.ingestion.archive_transport import request_archive
        from app.exchanges.archive import ArchiveTransportError
        async def no_network(*args):
            raise AssertionError("Rollback must not initiate a request")
        with pytest.raises(ArchiveTransportError, match="downloads disabled"):
            await request_archive(cfg, lambda: None, "binance", "https://cdn/file", no_network, timeout_seconds=1)
    asyncio.run(run())
