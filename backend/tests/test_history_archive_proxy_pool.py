"""Real loopback CONNECT proxies and TLS origin; no TUN/internet assumptions.

Only the test CA is injected. Production aiohttp requests, proxy selection,
stream reads, archive factories, cache and storage remain in the tested path.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import ssl
import time
import zipfile
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.core.proxy_pool import get_proxy_pool
from app.data_engine.backfill import BackfillEngine
from app.data_engine.backfill.archive_cache import AiohttpArchiveHttpClient, HistoricalArchiveCache
from app.data_engine.backfill.archive_cleanup import ArchiveImportCleanup
from app.data_engine.backfill.models import BackfillPlan, BackfillStatus, BackfillTask
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.transport import TransportLayer
from app.exchanges.archive import ArchiveDataError, ArchiveHttpResponse, ArchiveTransportError
from app.exchanges.plugins.okx.archive import OkxKlineArchiveProvider
from tests.test_history_archive_import_cleanup import DAY, START, fixture_object, storage_at


@pytest.fixture
def tls(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "archive.invalid")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(host) for host in (
                "archive.invalid", "other.invalid", "data.binance.vision", "www.okx.com", "static.okx.com",
            )]), critical=False).sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "ca.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_path, key_path)
    return server, ssl.create_default_context(cafile=str(cert_path))


@asynccontextmanager
async def network(monkeypatch, tls, handler, modes=("good", "good")):
    requests, connects = [], [[] for _ in modes]
    tasks = set()
    async def origin(request):
        requests.append((request.method, request.host, request.path))
        return await handler(request)
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", origin)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls[0])
    await site.start()
    origin_port = site._server.sockets[0].getsockname()[1]

    async def proxy(index, reader, writer):
        tasks.add(asyncio.current_task())
        upstream = None
        pumps = []
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            method, target, _ = headers.split(b"\r\n", 1)[0].decode().split()
            assert method == "CONNECT"
            connects[index].append(target)
            if modes[index] != "good":
                status = b"407 Proxy Authentication Required" if modes[index] == "auth" else b"502 Bad Gateway"
                writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            upstream_reader, upstream = await asyncio.open_connection("127.0.0.1", origin_port)
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
            async def copy(source, dest):
                while data := await source.read(65536):
                    dest.write(data)
                    await dest.drain()
            pumps = [asyncio.create_task(copy(reader, upstream)),
                     asyncio.create_task(copy(upstream_reader, writer))]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (writer, upstream):
                if stream:
                    stream.close()
                    with suppress(ConnectionError):
                        await stream.wait_closed()
            tasks.discard(asyncio.current_task())

    servers = [await asyncio.start_server(lambda r, w, i=i: proxy(i, r, w), "127.0.0.1", 0)
               for i in range(len(modes))]
    urls = [f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}" for server in servers]
    connector = aiohttp.TCPConnector
    class TrustedConnector(connector):
        def __init__(self, **kwargs):
            kwargs.setdefault("ssl", tls[1])
            super().__init__(**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(aiohttp.client, "TCPConnector", TrustedConnector)
        try:
            yield urls, connects, requests
        finally:
            for server in servers:
                server.close()
                await server.wait_closed()
            for task in tuple(tasks):
                task.cancel()
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
            await runner.cleanup()


def config(urls, *, strategy="failover", groups=None):
    return IngestionConfig(proxy_mode="pool", proxy_strategy=strategy, proxy_routes=[
        {"id": f"route-{i}", "name": f"route-{i}", "url": url, "enabled": True,
         "exchanges": ["binance", "okx"], "egress_group": groups[i] if groups else f"exit-{i}",
         "max_concurrency": 1}
        for i, url in enumerate(urls)
    ])


def client(cfg, *, exchange="binance", timeout=5):
    return AiohttpArchiveHttpClient(request_runner=TransportLayer(cfg).archive_http_request,
                                   timeout_seconds=timeout).for_exchange(exchange)


def test_default_entry_cold_pool_failover_import_and_cleanup(monkeypatch, tmp_path, tls):
    async def run():
        cfg, provider, ref, fixture_http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        checksum = f"{hashlib.sha256(fixture_http.payload).hexdigest()}  {ref.expected_filename}\n".encode()
        async def serve(request):
            return web.Response(body=checksum if request.path.endswith(".CHECKSUM") else fixture_http.payload)
        async with network(monkeypatch, tls, serve, ("good", "bad", "good")) as (urls, connects, requests):
            ingestion = config(urls)
            ingestion.proxy_routes[0]["exchanges"] = ["okx"]
            transport = TransportLayer(ingestion)
            engine = BackfillEngine(cfg, storage, transport, ingestion_config=ingestion)
            async def no_rest(*args, **kwargs):
                raise AssertionError("Full archive should not use REST")
            transport.http_fetch = no_rest
            task = BackfillTask(ref.symbol, ref.interval, ref.start_ms, ref.end_ms,
                                exchange=ref.exchange, market_type=ref.market_type)
            try:
                fetched = await engine.fetcher.fetch([task])
                assert fetched[0].status == BackfillStatus.COMPLETED
                assert len(fetched[0].bars) == 31
                assert [len(items) for items in connects] == [0, 1, 2]
                assert len(requests) == 2
                router = engine.fetcher._source_router
                cache = router._cache
                async with cache.materialize(ref, provider, router._http_for(ref.exchange)) as warm:
                    assert warm.cache_hit
                assert [len(items) for items in connects] == [0, 1, 2]
                cached_at = cache._lookup(ref.object_key)["validated_at_ms"]
                with monkeypatch.context() as patch:
                    patch.setattr("app.data_engine.backfill.archive_cache._now_ms",
                                  lambda: cached_at + cache.revalidate_ms + 1)
                    async with cache.materialize(ref, provider, router._http_for(ref.exchange)) as rechecked:
                        assert rechecked.cache_hit and rechecked.cache_generation == warm.cache_generation
                assert [len(items) for items in connects] == [0, 1, 3]
                assert requests[-1][2].endswith(".CHECKSUM")
                reconciled = await engine.reconciler.reconcile(fetched, BackfillPlan(gaps=[], tasks=[task]))
                assert reconciled.archive_objects_imported == 1 and not reconciled.errors
                path = Path(cache._lookup(ref.object_key)["path"])
                await ArchiveImportCleanup(cfg, cache, storage.get_history_archive_import_proofs).sweep_page()
                assert not path.exists()
                pool = get_proxy_pool()
                assert not pool._archive_leases and not any(pool._active.values())
                assert pool.archive_traffic(urls[2])["payload_bytes_total"] == 2 * len(checksum) + len(fixture_http.payload)
            finally:
                await engine.close()
    asyncio.run(run())


def test_checksum_head_directory_and_zip_all_use_exchange_routes(monkeypatch, tmp_path, tls):
    async def run():
        async def serve(request):
            if request.method == "POST":
                assert await request.json() == {"period": "2024-01"}
                return web.json_response({"code": "0"})
            return web.Response(body=b"fixture")
        async with network(monkeypatch, tls, serve) as (urls, connects, requests):
            cfg = config(urls)
            cfg.proxy_routes[0]["exchanges"] = ["binance"]
            cfg.proxy_routes[1]["exchanges"] = ["okx"]
            http = client(cfg, exchange="okx")
            args = {"allowed_hosts": ("www.okx.com", "static.okx.com"), "max_bytes": 100}
            assert (await http.get_bytes("https://static.okx.com/check", **args)).body == b"fixture"
            assert (await http.head("https://static.okx.com/head", allowed_hosts=args["allowed_hosts"])).status == 200
            _, body = await http.post_json("https://www.okx.com/directory", {"period": "2024-01"}, **args)
            assert body == {"code": "0"}
            path = tmp_path / "zip"
            await http.download("https://static.okx.com/zip", path, **args)
            assert path.read_bytes() == b"fixture"
            assert len(connects[0]) == 0 and len(connects[1]) == 4
            assert [r[0] for r in requests] == ["GET", "HEAD", "POST", "GET"]
    asyncio.run(run())


def test_interrupted_stream_retries_other_route_and_truncates_partial_file(monkeypatch, tmp_path, tls):
    async def run():
        count = 0
        async def serve(request):
            nonlocal count
            count += 1
            if count == 1:
                response = web.StreamResponse(headers={"Content-Length": "1000"})
                await response.prepare(request)
                await response.write(b"partial-prefix")
                request.transport.close()
                return response
            return web.Response(body=b"complete")
        async with network(monkeypatch, tls, serve) as (urls, connects, _):
            path = tmp_path / "partial.zip"
            result = await client(config(urls)).download("https://archive.invalid/zip", path,
                                                       allowed_hosts=("archive.invalid",), max_bytes=2000)
            assert result.status == 200 and path.read_bytes() == b"complete"
            assert [len(items) for items in connects] == [1, 1]
            pool = get_proxy_pool()
            assert pool.archive_traffic(urls[0])["failures_total"] == 1
            assert not pool._archive_leases and not any(pool._active.values())
    asyncio.run(run())


@pytest.mark.parametrize("status", [408, 503])
def test_transient_http_response_fails_over_and_records_retry_after(monkeypatch, tls, status):
    async def run():
        calls = 0
        async def serve(request):
            nonlocal calls
            calls += 1
            return (web.Response(status=status, headers={"Retry-After": "20"}, body=b"busy")
                    if calls == 1 else web.Response(body=b"ok"))
        async with network(monkeypatch, tls, serve) as (urls, connects, _):
            cfg = config(urls)
            response = await client(cfg).get_bytes("https://archive.invalid/file",
                                                   allowed_hosts=("archive.invalid",), max_bytes=100)
            assert response.body == b"ok" and [len(items) for items in connects] == [1, 1]
            pool = get_proxy_pool()
            health = pool.health(pool.routes(cfg, "binance")[0], "binance", "archive:archive.invalid")
            assert health.last_status == status and health.retry_at > time.monotonic() + 15
    asyncio.run(run())


@pytest.mark.parametrize("status", [418, 429])
def test_host_throttle_respects_exit_aliases_without_blocking_rest_or_other_host(monkeypatch, tls, status):
    async def run():
        calls = 0
        async def serve(request):
            nonlocal calls
            calls += 1
            return web.Response(status=status, headers={"Retry-After": "120"}) if calls == 1 else web.Response(body=b"ok")
        async with network(monkeypatch, tls, serve, ("good",) * 3) as (urls, connects, _):
            cfg = config(urls, groups=["shared", "shared", "other"])
            http = client(cfg)
            assert (await http.get_bytes("https://archive.invalid/file", allowed_hosts=("archive.invalid",), max_bytes=100)).status == 200
            assert [len(items) for items in connects] == [1, 0, 1]
            pool = get_proxy_pool()
            assert pool._archive_cooldowns[("binance", "archive.invalid", "shared")] > time.monotonic() + 100
            route = pool.routes(cfg, "binance")[0]
            pool.begin(route, "binance")  # API policy has a distinct owner.
            pool.end(route)
            await http.get_bytes("https://other.invalid/file", allowed_hosts=("other.invalid",), max_bytes=100)
            assert [len(items) for items in connects] == [2, 0, 1]
    asyncio.run(run())


@pytest.mark.parametrize("strategy", ["balanced", "failover"])
def test_parallel_stream_leases_and_queued_cancellation(monkeypatch, tmp_path, tls, strategy):
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        count = 0
        async def serve(request):
            nonlocal count
            count += 1
            response = web.StreamResponse(headers={"Content-Length": "1000"})
            await response.prepare(request)
            await response.write(b"prefix")
            if count == 2:
                entered.set()
            await release.wait()
            return response
        async with network(monkeypatch, tls, serve) as (urls, connects, _):
            cfg = config(urls, strategy=strategy)
            http = client(cfg)
            async def download(name):
                return await http.download(f"https://archive.invalid/{name}", tmp_path / name,
                                           allowed_hosts=("archive.invalid",), max_bytes=1000)
            tasks = [asyncio.create_task(download(str(i))) for i in range(2)]
            try:
                await asyncio.wait_for(entered.wait(), 3)
                pool = get_proxy_pool()
                assert [pool._active[url] for url in urls] == [1, 1]
                assert [len(items) for items in connects] == [1, 1]
                # A queued cancellation owns no lease and releases neither reader.
                queued = asyncio.create_task(download("queued"))
                await asyncio.sleep(0)
                queued.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await queued
                assert [pool._active[url] for url in urls] == [1, 1]
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                release.set()
            assert not pool._archive_leases and not any(pool._active.values())
            assert sum(pool.archive_traffic(url)["cancellations_total"] for url in urls) == 2
    asyncio.run(run())


def test_all_proxies_fail_without_direct_fallback_or_secret_leaks(monkeypatch, tls):
    async def run():
        async def serve(request):
            raise AssertionError("Unreachable via the failing proxies")
        async with network(monkeypatch, tls, serve, ("auth", "bad")) as (urls, connects, requests):
            urls[0] = urls[0].replace("http://", "http://fixture:secret-password@")
            cfg = config(urls)
            with pytest.raises(ArchiveTransportError) as error:
                await client(cfg).get_bytes("https://archive.invalid/file", allowed_hosts=("archive.invalid",), max_bytes=100)
            assert "secret-password" not in str(error.value)
            assert "secret-password" not in json.dumps(get_proxy_pool().snapshot(cfg))
            assert [len(items) for items in connects] == [1, 1] and not requests
            assert not any(get_proxy_pool()._active.values())
    asyncio.run(run())


def test_missing_object_and_unsafe_redirect_do_not_failover(monkeypatch, tls):
    async def run():
        async def serve(request):
            return (web.Response(status=302, headers={"Location": "https://outside.invalid/file"})
                    if request.path == "/redirect" else web.Response(status=404))
        async with network(monkeypatch, tls, serve) as (urls, connects, requests):
            http = client(config(urls))
            args = {"allowed_hosts": ("archive.invalid",), "max_bytes": 100}
            assert (await http.get_bytes("https://archive.invalid/missing", **args)).status == 404
            with pytest.raises(ArchiveDataError, match="allowlist"):
                await http.get_bytes("https://archive.invalid/redirect", **args)
            with pytest.raises(ArchiveDataError, match="allowlist"):
                await http.get_bytes("https://outside.invalid/file", **args)
            assert [len(items) for items in connects] == [2, 0] and len(requests) == 2
    asyncio.run(run())


def test_local_write_failure_does_not_penalize_or_retry_proxies(monkeypatch, tmp_path, tls):
    async def run():
        async def serve(request):
            return web.Response(body=b"zip")
        async with network(monkeypatch, tls, serve) as (urls, connects, _):
            cfg = config(urls)
            with pytest.raises(FileNotFoundError):
                await client(cfg).download("https://archive.invalid/zip", tmp_path / "absent" / "zip",
                                           allowed_hosts=("archive.invalid",), max_bytes=100)
            assert [len(items) for items in connects] == [1, 0]
            pool = get_proxy_pool()
            assert pool.archive_traffic(urls[0])["failures_total"] == 0
            assert not pool._archive_leases and not any(pool._active.values())
    asyncio.run(run())


def test_rest_capacity_and_live_route_settings_are_respected(monkeypatch, tls):
    async def run():
        async def serve(request):
            return web.Response(body=b"ok")
        async with network(monkeypatch, tls, serve) as (urls, connects, _):
            cfg = config(urls)
            pool, http = get_proxy_pool(), client(cfg, timeout=1)
            first = pool.routes(cfg, "binance")[0]
            pool.begin(first, "binance")
            args = {"allowed_hosts": ("archive.invalid",), "max_bytes": 100}
            try:
                await http.get_bytes("https://archive.invalid/shared", **args)
                assert [len(items) for items in connects] == [0, 1]
                cfg.proxy_routes[1]["enabled"] = False
                # Queue time is inside the request deadline; it cannot release
                # capacity belonging to the still-running REST request.
                with pytest.raises(ArchiveTransportError, match="time budget"):
                    await http.get_bytes("https://archive.invalid/blocked", **args)
                assert pool._active[first.url] == 1 and not pool._archive_leases
                assert [len(items) for items in connects] == [0, 1]
            finally:
                pool.end(first)
            cfg.proxy_routes[0]["enabled"] = False
            cfg.proxy_routes[1]["enabled"] = True
            await http.get_bytes("https://archive.invalid/changed", **args)
            assert [len(items) for items in connects] == [0, 2]
            cfg.proxy_mode, cfg.http_proxy = "custom", urls[0]
            await http.get_bytes("https://archive.invalid/custom", **args)
            assert [len(items) for items in connects] == [1, 2]
            cfg.proxy_mode = "pool"
            await http.get_bytes("https://archive.invalid/pool-again", **args)
            assert [len(items) for items in connects] == [1, 3]
            assert not any(pool._active.values())
    asyncio.run(run())


def test_aliases_share_host_capacity_and_active_timeout_releases_lease():
    async def run():
        cfg = config(["http://127.0.0.1:31001", "http://127.0.0.1:31002", "http://127.0.0.1:31003"],
                     groups=["shared", "shared", "other"])
        pool = get_proxy_pool()
        lease = await pool.acquire_archive(cfg, "binance", "archive.invalid", exclude_urls=set())
        second = await pool.acquire_archive(cfg, "binance", "archive.invalid", exclude_urls=set())
        assert [lease.route.id, second.route.id] == ["route-0", "route-2"]
        pool.finish_archive(second, elapsed=0, received_bytes=0, cancelled=True)
        pool.finish_archive(lease, elapsed=0, received_bytes=0, cancelled=True)
        from app.data_engine.ingestion.archive_transport import request_archive
        async def hangs(proxy, observe):
            observe(5)
            await asyncio.Event().wait()
        with pytest.raises(ArchiveTransportError, match="time budget"):
            await request_archive(cfg, lambda: None, "binance", "https://archive.invalid/file", hangs,
                                  timeout_seconds=0.05)
        assert not pool._archive_leases and not any(pool._active.values())
        assert pool.archive_traffic(lease.route.url)["failures_total"] == 1
        assert pool.archive_traffic(lease.route.url)["payload_bytes_total"] == 5
    asyncio.run(run())


def test_okx_warm_zip_skips_resolver_probe_and_proxy_acquisition(monkeypatch, tmp_path):
    async def run():
        cfg, _, _, _ = fixture_object(tmp_path)
        cfg.history_archive_okx_enabled = True
        provider = OkxKlineArchiveProvider()
        start = START - 8 * 3600_000
        ref = provider.plan_objects(market_type="spot", symbol="BTC-USDT", interval="1m",
                                    start_ms=start, end_ms=start + DAY - 1, now_ms=start + 90 * DAY)[0]
        resolved = replace(ref, url="https://static.okx.com/cdn/okex/traderecords/candlesticks/" + ref.expected_filename)
        csv = "instrument_name,open,high,low,close,vol,vol_ccy,vol_quote,open_time,confirm\n"
        csv += "".join(f"BTC-USDT,100,110,90,105,1.5,1.5,157.5,{at},1\n" for at in range(start, start + DAY, 60_000))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(ref.expected_filename.removesuffix(".zip") + ".csv", csv)
        class Fixture:
            async def download(self, url, destination, **kwargs):
                destination.write_bytes(out.getvalue())
                return ArchiveHttpResponse(200, {})
        cache = HistoricalArchiveCache(cfg.history_archive_cache_dir, max_bytes=10**7)
        async with cache.materialize(resolved, provider, Fixture()):
            pass
        ingestion = config([])
        engine = BackfillEngine(cfg, transport=TransportLayer(ingestion), ingestion_config=ingestion)
        router = engine.fetcher._source_router
        async def no_network(*args, **kwargs):
            raise AssertionError("Warm OKX ZIP must not contact resolver, probe or proxy")
        router._http._request_runner = no_network
        engine._transport.http_fetch = no_network
        try:
            results = await engine.fetcher.fetch([BackfillTask(ref.symbol, ref.interval, ref.start_ms,
                                                  ref.end_ms, exchange="okx", market_type="spot")])
            assert results[0].status == BackfillStatus.COMPLETED
            assert len(results[0].bars) == 1440
            assert results[0].metadata["archive_cache_hits"] == 1
            assert not router._okx_probe_passed
        finally:
            await engine.close()
    asyncio.run(run())
