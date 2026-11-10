"""Real loopback sockets; no exchange credentials or public network calls."""
from __future__ import annotations

import asyncio
import json
import time
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
from app.exchanges.rate_limits import RateLimitPolicy, RateLimitRule, get_shared_rate_limit_manager


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


@pytest.mark.parametrize("source_change", ["unchanged", "amended", "deleted"])
def test_bybit_derived_recovery_reuses_committed_components_after_restart(monkeypatch, tmp_path, source_change):
    from app.data_engine.backfill import BackfillConfig, BackfillEngine
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
    from app.data_engine.history import (
        ExchangeHistoryPolicyResolver,
        HistoryAvailabilityService,
        HistoryBoundaryRepository,
        get_history_calendar_registry,
    )
    from app.data_engine.storage import klines_repo
    from app.data_engine.storage.gap_ledger import GapLedger

    opened, step = 1_794_138_000_000, 300_000
    symbol, market = "BTC/USD:BTC", "swap.inverse"
    identity = {"exchange": "bybit", "market_type": market}
    db = tmp_path / "derived.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", db)
    klines_repo.init_klines_storage()

    async def run():
        pages = []
        adopted = []
        reset_ms = 0
        deferred = asyncio.Event()

        async def handle(http):
            nonlocal reset_ms
            assert http.path == "/v5/market/kline"
            assert http.query["interval"] == "5"
            start, end, limit = (int(http.query[key]) for key in ("start", "end", "limit"))
            pages.append((start, end, limit))
            if start == opened + 2 * step and not reset_ms:
                reset_ms = int(time.time() * 1000) + 1_500
                deferred.set()
                return web.json_response({"retCode": 10006, "retMsg": "Too many visits!"},
                    headers={"X-Bapi-Limit-Reset-Timestamp": str(reset_ms)})
            rows = [[str(ts), "1", "2", "1", "2", "9", str(4 + i)]
                    for i in reversed(range(-1, 4)) if start <= (ts := opened + i * step) <= end]
            return web.json_response({"retCode": 0, "result": {"list": rows[:limit]}})

        runner, origin = await serve(handle)
        create = generic._create_exchange
        policy = RateLimitPolicy(endpoint_rules=(RateLimitRule(
            name="bybit_derived_loopback", bucket_key="bybit:derived-loopback",
            capacity=16, refill_interval_seconds=.01, max_concurrency=1, cooldown_seconds=.1,
        ),))

        def routed(*args, **kwargs):
            exchange = create(*args, **kwargs)
            point_at_loopback(exchange, origin)
            exchange._candlescope_rate_limit_policy = policy
            exchange.set_markets([dict(
                id="BTCUSD", symbol=symbol, base="BTC", quote="USD", settle="BTC",
                baseId="BTC", quoteId="USD", settleId="BTC", type="swap", contract=True,
                swap=True, linear=False, inverse=True, spot=False, active=True,
            )])
            return exchange

        monkeypatch.setattr(generic, "_create_exchange", routed)
        config = IngestionConfig(proxy_mode="none", proxy_egress_group=f"derived-{urlsplit(origin).port}")
        storage = klines_repo.KlinesRepoAdapter()
        history = HistoryAvailabilityService(
            calendars=get_history_calendar_registry(), boundaries=HistoryBoundaryRepository(db),
        )
        history_policy = ExchangeHistoryPolicyResolver(history)

        async def publish(_symbol, interval, bars, **_kwargs):
            adopted.extend((interval, bar.time_ms) for bar in bars)

        async def emit(_event):
            pass

        def runtime():
            transport = TransportLayer(config)
            engine = BackfillEngine(BackfillConfig(
                history_archive_enabled=False, fetch_batch_size=2, fetch_concurrency=1, fetch_global_concurrency=1,
            ), klines_repo.AsyncKlinesRepoAdapter(), transport, ingestion_config=config)
            ledger = GapLedger(db)
            coordinator = BackfillCoordinator(
                storage=storage, bars_backfilled=publish, emit_event=emit, engine=engine, gap_ledger=ledger,
                history_service=history, history_policy_resolver=lambda repair: history_policy.resolve(
                    history_policy.series_key(
                        exchange=repair.exchange, market_type=repair.market_type, symbol=repair.symbol,
                        channel="kline", variant=repair.interval,
                    )
                ), loop=asyncio.get_running_loop(), max_retries=1, max_concurrency=1, chunk_bars=1000,
            )
            return transport, engine, ledger, coordinator

        def request(interval, start, end):
            return RepairRequest(symbol, interval, start, end, **identity, reason="tail_gap",
                                 requester="ingestion_gap", metadata={
                                     "requires_trusted_finality": True, "source_gap_id": "derived-gap",
                                 })

        transport, engine, ledger, coordinator = runtime()
        demand = None
        try:
            warmup = await coordinator.request_and_wait(request("5m", opened - step, opened - step))
            assert warmup.verified_contiguous
            pages.clear()
            adopted.clear()
            derived = request("10m", opened, opened + 2 * step)
            demand = asyncio.create_task(coordinator.request_and_wait(derived))
            await asyncio.wait_for(deferred.wait(), 5)
            async with asyncio.timeout(1):
                while True:
                    parent, = ledger.list_open()
                    if parent["status"] == "retry_wait":
                        break
                    await asyncio.sleep(.01)
            assert parent["next_retry_at"] >= reset_ms - 3
            assert not adopted and not storage.query_bars(symbol, "10m", **identity)
            committed = storage.query_bars(symbol, "5m", start_ms=opened, order="ASC", **identity)
            assert [row["open_time"] for row in committed] == [opened, opened + step]

            await coordinator.shutdown()
            await demand
            await engine.close()
            await transport.stop()
            if source_change == "amended":
                assert storage.upsert_bars(
                    symbol, "5m", [{**committed[0], "volume": 40}],
                    source="data_manager_amended", **identity,
                ) == 1
            if source_change == "deleted":
                assert storage.delete_bars(symbol, "5m", opened, opened + step, **identity) == 2
            transport, engine, ledger, coordinator = runtime()
            early = await coordinator.reconcile_gap_ledger(stale_after_ms=0)
            assert early.requeued == 0
            await asyncio.sleep(max(0, (parent["next_retry_at"] - time.time() * 1000) / 1000) + .025)
            recovered = await coordinator.reconcile_gap_ledger(stale_after_ms=0)
            assert recovered.requeued == 1, recovered
            outcome = await asyncio.wait_for(coordinator.wait_for_request(f"ledger-reconcile-{parent['id']}"), 5)
            final = ledger.get_status(derived)
            initial_metadata = json.loads(parent["metadata_json"])
            final_metadata = json.loads(final["metadata_json"])
            assert final_metadata["source_gap_id"] == initial_metadata["source_gap_id"]
            assert final_metadata["acquisition_revision"] == initial_metadata["acquisition_revision"]
            if source_change == "deleted":
                assert not outcome.verified_contiguous and final["status"] != "filled", outcome
                assert not adopted and not storage.query_bars(symbol, "10m", **identity)
                assert not storage.query_bars(symbol, "5m", start_ms=opened, end_ms=opened + step, **identity)
                return
            assert outcome.verified_contiguous and final["status"] == "filled", outcome
            assert pages == [
                (opened, opened + step, 2),
                (opened + 2 * step, opened + 3 * step, 2),
                (opened + 2 * step, opened + 3 * step, 2),
            ]
            rows = storage.query_bars(symbol, "10m", order="ASC", **identity)
            assert [(row["open_time"], row["volume"], row["source"]) for row in rows] == [
                (opened, 45 if source_change == "amended" else 9, "backfill_aggregated"),
                (opened + 2 * step, 13, "backfill_aggregated"),
            ]
            assert adopted == [("10m", opened), ("10m", opened + 2 * step)]
        finally:
            await coordinator.shutdown()
            if demand is not None:
                await asyncio.gather(demand, return_exceptions=True)
            await engine.close()
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
