"""Real loopback sockets; no exchange credentials or public network calls."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.feed_control import FeedControlLayer
from app.data_engine.ingestion.models import DataSource, FeedMode, RawMessage, StreamDescriptor, StreamType, TransportRequest
from app.data_engine.ingestion.transport import TransportLayer
from app.exchanges.catalog_worker import run_catalog_loader, shutdown_catalog_worker
from app.exchanges.ccxt_ext import generic
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.profiles.binance_usdm import BinanceUsdmCcxtProfile
from app.exchanges.public_admission import PublicDemand, get_public_admission, public_demand
from app.exchanges.public_ws import AdmittedWebSocket, connection_rules
from app.exchanges.rate_limits import RateLimitDeferred, RateLimitPolicy, get_shared_rate_limit_manager


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
            if request.path.endswith("/time"):
                return web.json_response({"serverTime": 60001})
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
            # Identical candle content is observed twice, retaining distinct
            # receipts while selecting the same source revision.
            assert {k: v for k, v in first[0].payload.items() if k != "_source_receipt"} == {
                k: v for k, v in second[0].payload.items() if k != "_source_receipt"}
            assert first[0].payload["_source_receipt"]["ref"] == second[0].payload["_source_receipt"]["ref"]
            assert first[0].payload["_source_receipt"]["observation_id"] != second[0].payload["_source_receipt"]["observation_id"]
            assert paths.count("/api/v3/exchangeInfo") == 1
            assert paths.count("/api/v3/klines") == 2
            snapshot = get_public_admission().snapshot()
            assert snapshot["counts"]["attempts"] == len(paths)
            assert snapshot["in_flight"] == 0
            assert [item["endpoint"] for item in snapshot["recent"]] == paths
            assert all(item["exchange"] == "binance" and item["market_type"] == "spot"
                       for item in snapshot["recent"])
            assert all(":egress=loopback-a" in bucket for item in snapshot["recent"] for bucket in item["buckets"])
        finally:
            await transport.stop()
            await runner.cleanup()
    asyncio.run(run())


def test_bybit_body_quota_uses_exact_physical_bucket_and_resumes_polling():
    async def run():
        calls = []
        reset_ms = 0

        async def handle(request):
            nonlocal reset_ms
            assert request.path == "/v5/market/kline"
            category = request.query["category"]
            calls.append((category, time.time()))
            if category == "inverse" and not reset_ms:
                reset_ms = int(time.time() * 1000) + 900
                return web.json_response(
                    {"retCode": 10006, "retMsg": "Too many visits!", "result": {}},
                    headers={"X-Bapi-Limit-Reset-Timestamp": str(reset_ms)},
                )
            return web.json_response({"retCode": 0, "result": {"list": [[0, "1", "2", "1", "2", "9", "4"]]}})

        runner, origin = await serve(handle)
        entry = get_ccxt_catalog_entry("bybit")
        config = IngestionConfig(proxy_mode="none", proxy_egress_group="bybit-loopback")
        policy = RateLimitPolicy(default_concurrency=1, default_delay_seconds=.01,
                                 default_retry_429_backoff_seconds=.1)
        drivers = {
            category: generic._create_exchange(entry, config, market_type=market, websocket=False)
            for category, market in [("inverse", "swap.inverse"), ("linear", "swap.linear")]
        }
        for driver in drivers.values():
            point_at_loopback(driver, origin)
            driver._candlescope_rate_limit_policy = policy

        async def fetch(category):
            return await drivers[category].public_get_v5_market_kline({
                "category": category, "symbol": "BTCUSD" if category == "inverse" else "BTCUSDT",
                "interval": "5", "limit": 1,
            })

        class PollTransport:
            def __init__(self):
                self.deferred = asyncio.Event()
                self.error = None

            async def http_fetch(self, _):
                try:
                    response = await fetch("inverse")
                except RateLimitDeferred as exc:
                    self.error = exc
                    self.deferred.set()
                    raise
                return [RawMessage(response, DataSource.HTTP, StreamType.KLINE, int(time.time() * 1000))]

        transport = PollTransport()
        delivered = asyncio.Event()
        async def on_data(_):
            delivered.set()

        descriptor = StreamDescriptor("BTC/USD:BTC", StreamType.KLINE, exchange="bybit",
                                      market_type="swap.inverse", interval="5m", poll_interval_seconds=.01)
        feed = FeedControlLayer(config, transport, descriptor)
        feed._running = True
        feed._mode = FeedMode.HTTP_POLL
        feed.on_data(on_data)
        poll = asyncio.create_task(feed._http_poll_loop())
        try:
            await asyncio.wait_for(transport.deferred.wait(), 2)
            error = transport.error
            bucket_key = "bybit:swap.inverse:legacy:egress=bybit-loopback"
            assert (error.status_code, error.body_code, error.bucket_key, error.reason) == (
                200, "10006", bucket_key, "cooldown",
            )
            assert error.retry_at_ms >= reset_ms - 2
            bucket = get_shared_rate_limit_manager().snapshot()[bucket_key]
            assert bucket["last_status_code"] == 200 and bucket["last_body_code"] == "10006"
            assert bucket["last_headers"]["x-bapi-limit-reset-timestamp"] == str(reset_ms)
            with public_demand(PublicDemand(defer=True)), pytest.raises(RateLimitDeferred) as blocked:
                await fetch("inverse")
            assert blocked.value.bucket_key == bucket_key
            assert blocked.value.reason == "cooldown"
            assert (await fetch("linear"))["retCode"] == 0
            assert [category for category, _ in calls] == ["inverse", "linear"]
            await asyncio.wait_for(delivered.wait(), 2)
            assert [category for category, _ in calls] == ["inverse", "linear", "inverse"]
            assert calls[-1][1] >= reset_ms / 1000 - .005
            assert feed.snapshot()["metrics"]["counters"]["http_quota_deferrals"] == 1
            assert get_public_admission().snapshot()["in_flight"] == 0
        finally:
            poll.cancel()
            await asyncio.gather(poll, return_exceptions=True)
            await asyncio.gather(*(driver.close() for driver in drivers.values()))
            await runner.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize(("batch_size", "first_offset", "last_offset", "pages"), [
    (1000, 0, 0, [(0, 0, 1)]),
    (2, 0, 1_200_000, [(0, 1_200_000, 2), (0, 899_999, 2), (0, 299_999, 1)]),
    (1, 0, 300_000, [(0, 300_000, 1), (0, 299_999, 1)]),
    (2, 1, 600_000, [(300_000, 600_000, 2)]),
])
def test_bybit_backfill_uses_bounded_reverse_pages(monkeypatch, tmp_path, batch_size, first_offset, last_offset, pages):
    from app.data_engine.backfill import BackfillConfig
    from app.data_engine.backfill.fetcher import HistoricalFetcher
    from app.data_engine.backfill.models import BackfillStatus, BackfillTask
    from app.data_engine.storage import klines_repo

    opened, step = 1_794_138_000_000, 300_000
    market_type, symbol = "swap.inverse", "BTC/USD:BTC"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bybit-pages.sqlite")
    klines_repo.init_klines_storage()

    async def run():
        calls = []

        async def handle(request):
            assert request.path == "/v5/market/kline"
            assert request.query["category"] == "inverse" and request.query["symbol"] == "BTCUSD"
            lower = int(request.query["start"])
            upper = int(request.query.get("end", opened + 4 * step))
            limit = int(request.query["limit"])
            calls.append((lower, upper, limit))
            # The venue can round start down and selects newest rows first.
            lower -= lower % step
            rows = [
                [str(t), "1", "2", "1", "2", "9", "4"]
                for t in reversed(range(opened, opened + 5 * step, step))
                if lower <= t <= upper
            ][:limit]
            return web.json_response({"retCode": 0, "result": {"category": "inverse", "symbol": "BTCUSD", "list": rows}})

        runner, origin = await serve(handle)
        original = generic._create_exchange

        def create(*args, **kwargs):
            exchange = original(*args, **kwargs)
            point_at_loopback(exchange, origin)
            exchange.set_markets([dict(
                id="BTCUSD", symbol=symbol, base="BTC", quote="USD", settle="BTC",
                baseId="BTC", quoteId="USD", settleId="BTC", type="swap", contract=True,
                swap=True, linear=False, inverse=True, spot=False, active=True,
            )])
            return exchange

        monkeypatch.setattr(generic, "_create_exchange", create)
        config = IngestionConfig(proxy_mode="none")
        transport = TransportLayer(config)
        fetcher = HistoricalFetcher(BackfillConfig(history_archive_enabled=False, fetch_batch_size=batch_size),
                                    transport, ingestion_config=config)
        task = BackfillTask(symbol, "5m", opened + first_offset, opened + last_offset,
                            exchange="bybit", market_type=market_type)
        try:
            async with asyncio.timeout(6):
                while True:
                    try:
                        result = await fetcher._fetch_rest_task(task)
                        break
                    except RateLimitDeferred as exc:
                        if exc.reason != "metadata_pending":
                            raise
                        await asyncio.sleep(exc.retry_after_seconds)
            assert result.status is BackfillStatus.COMPLETED
            assert [b.open_time for b in result.bars] == [
                t for t in range(opened, opened + 5 * step, step) if task.start_ms <= t <= task.end_ms
            ]
            assert {b.volume for b in result.bars} == {4}
            assert not result.source_complete
            assert calls == [(opened + lo, opened + hi, limit) for lo, hi, limit in pages]
        finally:
            await fetcher.close()
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
            assert snapshot["recent"][-1]["endpoint"] == "/api/v3/exchangeInfo"
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
