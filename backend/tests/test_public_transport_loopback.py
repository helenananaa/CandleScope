"""Real loopback sockets; no exchange credentials or public network calls."""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import StreamDescriptor, StreamType, TransportRequest
from app.data_engine.ingestion.transport import TransportLayer
from app.exchanges.catalog_worker import run_catalog_loader, shutdown_catalog_worker
from app.exchanges.ccxt_ext import generic
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.profiles.binance_usdm import BinanceUsdmCcxtProfile
from app.exchanges.public_admission import get_public_admission
from app.exchanges.public_ws import AdmittedWebSocket, connection_rules
from app.exchanges.rate_limits import get_shared_rate_limit_manager


def point_at_loopback(exchange, origin):
    exchange.urls["api"] = {key: origin + urlsplit(value).path
                            for key, value in exchange.urls["api"].items() if isinstance(value, str)}


async def serve(handler):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


def test_default_provider_counts_metadata_and_pages_once_with_exact_route(monkeypatch):
    async def run():
        paths = []
        async def handle(request):
            paths.append(request.path)
            if request.path.endswith("exchangeInfo"):
                symbols = [{"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC",
                    "quoteAsset": "USDT", "baseAssetPrecision": 8, "quotePrecision": 8,
                    "isSpotTradingAllowed": True, "isMarginTradingAllowed": False,
                    "orderTypes": ["LIMIT", "MARKET"], "filters": []}]
                return web.json_response({"symbols": symbols if request.path.startswith("/api/") else []})
            return web.json_response([[0, "1", "2", "0.5", "1.5", "10", 59999, "15", 5, "2", "3", "0"]])
        runner, origin = await serve(handle)
        original = generic._create_exchange
        def create(*args, **kwargs):
            exchange = original(*args, **kwargs)
            point_at_loopback(exchange, origin)
            return exchange
        monkeypatch.setattr(generic, "_create_exchange", create)
        config = IngestionConfig(proxy_mode="none", proxy_egress_group="loopback-a")
        transport = TransportLayer(config)
        try:
            descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m", market_type="spot")
            first = await asyncio.wait_for(transport.http_fetch(TransportRequest(descriptor, limit=1)), 10)
            second = await asyncio.wait_for(transport.http_fetch(TransportRequest(descriptor, limit=1)), 10)
            assert first[0].payload == second[0].payload
            assert paths.count("/api/v3/exchangeInfo") == 1
            assert paths.count("/api/v3/klines") == 2
            snapshot = get_public_admission().snapshot()
            assert snapshot["counts"]["attempts"] == len(paths)
            assert snapshot["in_flight"] == 0
            assert all(":egress=loopback-a" in bucket for item in snapshot["recent"] for bucket in item["buckets"])
        finally:
            await transport.stop()
            await runner.cleanup()
    asyncio.run(run())


async def _catalog_http_loader(origin: str) -> list:
    exchange = generic._create_exchange(get_ccxt_catalog_entry("binance"),
        IngestionConfig(proxy_mode="none", proxy_egress_group="catalog-loopback"),
        market_type="spot", websocket=False)
    point_at_loopback(exchange, origin)
    try:
        result = await exchange.public_get_exchangeinfo()
        return [result]
    finally:
        await exchange.close()


def test_catalog_child_uses_parent_quota_and_settles_probe():
    async def run():
        received = []
        async def handle(request):
            received.append(request.path)
            return web.json_response({"symbols": []})
        runner, origin = await serve(handle)
        try:
            assert await asyncio.wait_for(run_catalog_loader(_catalog_http_loader, origin), 90) == [{"symbols": []}]
            snapshot = get_public_admission().snapshot()
            assert received == ["/api/v3/exchangeInfo"]
            assert snapshot["counts"]["attempts"] == snapshot["counts"]["class_background"] == 1
            assert snapshot["in_flight"] == 0
            bucket = get_shared_rate_limit_manager().snapshot()["binance:spot:request_weight:ip:egress=catalog-loopback"]
            assert not bucket["probe_in_flight"]
        finally:
            await shutdown_catalog_worker()
            await runner.cleanup()
    asyncio.run(run())


def test_ccxt_actual_socket_reuse_and_frames_are_counted_once():
    async def run():
        sockets = []
        received = asyncio.Event()
        async def handle(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            sockets.append(socket)
            async for message in socket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    received.set()
            return socket
        runner, origin = await serve(handle)
        driver = BinanceUsdmCcxtProfile().create_exchange(
            IngestionConfig(proxy_mode="none", proxy_egress_group="ws-loopback"),
            raw_event_sink=None, lifecycle_sink=None)
        try:
            url = origin.replace("http:", "ws:") + "/stream"
            client = driver.client(url)
            assert driver.client(url) is client
            await asyncio.wait_for(client.connect(driver.session), 10)
            await asyncio.wait_for(client.connect(driver.session), 10)
            assert len(sockets) == 1
            assert isinstance(client.connection, AdmittedWebSocket)
            await client.send({"method": "SUBSCRIBE", "params": ["btcusdt@trade"], "id": 1})
            await asyncio.wait_for(received.wait(), 1)
            snapshot = get_public_admission().snapshot()
            # CCXT also sends its initial protocol ping; it is a distinct,
            # required frame, not another logical subscription/connection.
            assert snapshot["counts"]["attempts"] == 2 + snapshot["counts"].get("class_required", 0)
            assert snapshot["counts"]["class_recovery"] == 2
            assert sum(any(":ws_connect:" in key for key in item["buckets"])
                       for item in snapshot["recent"]) == 1
        finally:
            await driver.close()
            await runner.cleanup()
        assert not any(":ws_control:connection:" in key for key in get_shared_rate_limit_manager().snapshot())
    asyncio.run(run())


def test_okx_ccxt_swap_metadata_uses_native_futures_rule():
    async def run():
        async def handle(request):
            assert request.query["instType"] == "SWAP"
            return web.json_response({"code": "0", "data": []})
        runner, origin = await serve(handle)
        exchange = generic._create_exchange(get_ccxt_catalog_entry("okx"),
            IngestionConfig(proxy_mode="none", proxy_egress_group="okx-loopback"),
            market_type="swap", websocket=False)
        point_at_loopback(exchange, origin)
        try:
            result = await asyncio.wait_for(exchange.public_get_public_instruments({"instType": "SWAP"}), 10)
            assert result == {"code": "0", "data": []}
            attempts = get_public_admission().snapshot()["recent"]
            assert len(attempts) == 1
            assert attempts[0]["buckets"] == ["okx:public-instruments:futures:ip:egress=okx-loopback"]
        finally:
            await exchange.close()
            await runner.cleanup()
    asyncio.run(run())


def test_ccxt_close_cancels_quota_wait_before_opening_socket():
    async def run():
        sockets = []
        async def handle(request):
            sockets.append(request.path)
            return web.Response(status=500)
        runner, origin = await serve(handle)
        driver = BinanceUsdmCcxtProfile().create_exchange(
            IngestionConfig(proxy_mode="none", proxy_egress_group="ws-cancel"),
            raw_event_sink=None, lifecycle_sink=None)
        manager = get_shared_rate_limit_manager()
        manager.record_cooldown(connection_rules("binance", "ws-cancel")[0], 60)
        scheduled_sends = []
        try:
            client = driver.client(origin.replace("http:", "ws:") + "/stream")
            connected = client.connect(driver.session)
            subscription = client.future("pending-subscription")
            # CCXT's watch callback schedules sends when connected completes,
            # including cancellation. Closing must prevent a late send.
            connected.add_done_callback(lambda _: scheduled_sends.append(
                asyncio.create_task(client.send({"method": "SUBSCRIBE", "id": 1}))))
            async with asyncio.timeout(1):
                while get_public_admission().snapshot()["pending"] != 1:
                    await asyncio.sleep(0.001)
            await asyncio.wait_for(driver.close(), 2)
            async with asyncio.timeout(1):
                while not scheduled_sends:
                    await asyncio.sleep(0.001)
            results = await asyncio.gather(*scheduled_sends, return_exceptions=True)
            assert all(isinstance(result, asyncio.CancelledError) for result in results)
            assert connected.cancelled() and subscription.cancelled()
            assert sockets == []
            snapshot = get_public_admission().snapshot()
            assert snapshot["pending"] == snapshot["in_flight"] == 0
            assert snapshot["counts"].get("attempts", 0) == 0
        finally:
            await driver.close()
            await runner.cleanup()
    asyncio.run(run())


def test_ccxt_internal_retry_gets_a_new_physical_permit():
    from app.exchanges.ccxt_ext.source_capture import REST_CAPTURE

    async def run():
        hits = []
        async def handle(request):
            hits.append(request.path)
            if len(hits) == 1:
                return web.json_response({"code": -1000, "msg": "temporary outage"}, status=503)
            return web.json_response({"symbols": []})
        runner, origin = await serve(handle)
        exchange = generic._create_exchange(get_ccxt_catalog_entry("binance"),
            IngestionConfig(proxy_mode="none", proxy_egress_group="retry-loopback"),
            market_type="spot", websocket=False)
        point_at_loopback(exchange, origin)
        exchange.options["maxRetriesOnFailure"] = 1
        captured = []
        capture_token = REST_CAPTURE.set(captured)
        try:
            assert await asyncio.wait_for(exchange.public_get_exchangeinfo(), 10) == {"symbols": []}
            snapshot = get_public_admission().snapshot()
            assert len(hits) == snapshot["counts"]["attempts"] == 2
            assert snapshot["in_flight"] == 0
            assert [attempt["status_code"] for attempt in snapshot["recent"]] == [503, 200]
            # Source capture and physical admission must cooperate in the MRO:
            # both attempts are charged, the successful decoded body is kept once.
            assert len(captured) == 1
            assert captured[0]["payload"] == {"symbols": []}
            assert captured[0]["endpoint"] == origin + "/api/v3/exchangeInfo"
        finally:
            REST_CAPTURE.reset(capture_token)
            await exchange.close()
            await runner.cleanup()
    asyncio.run(run())


def test_fork_history_keeps_source_evidence_with_admission_and_boundaries(monkeypatch, tmp_path):
    from app.data_engine.ingestion.normalize import NormalizeLayer
    from app.data_engine.storage import klines_repo, kline_sources
    from tests.test_ccxt_fork_kline import fork_exchange

    # Fails instead of skipping in the required-fork CI job.
    fork_exchange()
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()

    async def run():
        paths = []
        row = [0, "1.00000000000000001", "2", "0.5", "1.5", "10",
               59999, "15", 5, "2", "3", "0"]

        async def handle(request):
            paths.append(request.path)
            if request.path.endswith("exchangeInfo"):
                return web.json_response({"symbols": [{
                    "symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC",
                    "quoteAsset": "USDT", "baseAssetPrecision": 8, "quotePrecision": 8,
                    "isSpotTradingAllowed": True, "isMarginTradingAllowed": False,
                    "orderTypes": ["LIMIT", "MARKET"], "filters": [],
                }]})
            if request.path.endswith("time"):
                return web.json_response({"serverTime": 120000})
            return web.json_response([row])

        runner, origin = await serve(handle)
        original = generic._create_exchange

        def create(*args, **kwargs):
            exchange = original(*args, **kwargs)
            point_at_loopback(exchange, origin)
            return exchange

        monkeypatch.setattr(generic, "_create_exchange", create)
        config = IngestionConfig(proxy_mode="none", proxy_egress_group="fork-loopback",
                                 ccxt_fork_kline_enabled=True)
        transport = TransportLayer(config)
        descriptor = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m", market_type="spot")
        try:
            messages = await transport.http_fetch(TransportRequest(descriptor, limit=1))
            event = NormalizeLayer(config, descriptor).parse_raw(messages[0])
            assert event.data["basis_qualification"] != "unknown"
            assert event.data["is_closed"] is True
            head = kline_sources.latest(descriptor, 0)
            assert head and head["is_closed"]
            assert "1.00000000000000001" in str(head)
            snapshot = get_public_admission().snapshot()
            assert len(paths) == snapshot["counts"]["attempts"] == 3
            assert sorted(paths) == ["/api/v3/exchangeInfo", "/api/v3/klines", "/api/v3/time"]
            assert snapshot["in_flight"] == 0
            assert all(":egress=fork-loopback" in bucket
                       for attempt in snapshot["recent"] for bucket in attempt["buckets"])
        finally:
            await transport.stop()
            await runner.cleanup()

    asyncio.run(run())


def test_catalog_cancellation_releases_parent_physical_permit():
    async def run():
        received, release = asyncio.Event(), asyncio.Event()
        async def handle(request):
            received.set()
            await release.wait()
            return web.json_response({"symbols": []})
        runner, origin = await serve(handle)
        pending = asyncio.create_task(run_catalog_loader(_catalog_http_loader, origin))
        try:
            await asyncio.wait_for(received.wait(), 90)
            assert get_public_admission().snapshot()["in_flight"] == 1
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(pending, 2)
            snapshot = get_public_admission().snapshot()
            assert snapshot["pending"] == snapshot["in_flight"] == 0
            assert snapshot["counts"]["unknown"] == snapshot["counts"]["attempts"] == 1
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            release.set()
            await shutdown_catalog_worker()
            await runner.cleanup()
    asyncio.run(run())
