"""Two consumers share one K-line pipeline and one authoritative repair."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.data_manager import ContinuityPolicy, DataManager
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from app.data_engine.data_manager.config import DataManagerConfig, EventBusConfig
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey
from app.data_engine.ingestion import StreamPipeline
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType
from app.data_engine.interval_policy import parse_interval_spec
from app.data_engine.storage import klines_repo
from app.exchanges.ccxt_ext.unified import make_unified_payload
from tests.test_recovery_delivery_integration import _until
from tests.test_recovery_kline_consumers import _Factory, _history_repair, _committed_backfill, _close, T, IDENTITY


class Factory(_Factory):
    async def start(self, symbol, interval, on_market_event, exchange="binance",
                    market_type="spot", on_gap=None, *, gap_repair_owner="inline"):
        self.pipeline = StreamPipeline(
            IngestionConfig(proxy_mode="none", http_proxy=None, proxy_routes=[]), self,
            StreamDescriptor(symbol, StreamType.KLINE, interval=interval,
                             exchange=exchange, market_type=market_type),
            gap_repair_owner=gap_repair_owner,
        )
        self.pipeline.delivery.on_market_event(on_market_event)
        self.pipeline.delivery.on_gap(on_gap)
        return self.pipeline


async def manager(tmp_path, monkeypatch, config=None, *, identity=IDENTITY):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    store = klines_repo.KlinesRepoAdapter()
    dm = DataManager(config)
    dm.set_storage(store)
    dm._started = True
    factory = Factory()
    dm.set_ingestion_factory(factory)
    requests = []
    dm.set_backfill_trigger(lambda *args, **kwargs: requests.append((args, kwargs)))
    await dm.ensure_stream(**identity)
    return dm, store, factory, requests


def capture(dm, *, policy="strict", identity=IDENTITY):
    events, errors = [], []
    async def receive(event):
        events.append(event)
    async def recover(error):
        errors.append(error)
    handle = dm.subscribe(receive, **identity, event_types={DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED},
                          continuity=policy, on_recovery=recover)
    return events, errors, handle


def closed(events):
    return [event.bar.time for event in events if event.event_type == DataEventType.BAR_CLOSED]


@pytest.mark.anyio
async def test_strict_and_gap_aware_share_repair_without_blocking_latest(tmp_path, monkeypatch):
    dm, store, factory, requests = await manager(tmp_path, monkeypatch)
    strict, errors, _ = capture(dm)
    live, _, _ = capture(dm, policy="gap_aware")
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(T + 120_000, 101)
        await _until(lambda: len(closed(live)) == 2)
        assert closed(strict) == [T // 1000]
        assert factory.pipeline.recovery.gap_repair_owner == "data_manager"
        assert factory.requests == []
        assert len(requests) == 1
        assert any(event.event_type == DataEventType.SOURCE_GAP for event in live)
        assert live[-1].detail["source_continuity"]["state"] == "gapped"
        await _history_repair(dm, store, T + 60_000, 150)
        await _until(lambda: len(closed(strict)) == 3)
        assert closed(strict) == [T // 1000, T // 1000 + 60, T // 1000 + 120]
        assert [event.bar.close for event in strict] == [99, 150, 101]
        assert strict[1].detail["continuity_replayed"] is True
        assert closed(live) == [T // 1000, T // 1000 + 120]
        assert any(event.event_type == DataEventType.BAR_AMENDED and event.bar.close == 150 for event in live)
        assert any(event.event_type == DataEventType.SOURCE_GAP_RESOLVED for event in live)
        assert errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
@pytest.mark.parametrize(("market_type", "symbol"), [
    ("swap.linear", "BTC/USDT:USDT"),
    ("swap.inverse", "BTC/USD:BTC"),
])
@pytest.mark.parametrize("delayed_confirm", [True, False])
async def test_bybit_http_poll_cannot_mask_a_missed_or_delayed_confirm(
    tmp_path, monkeypatch, market_type, symbol, delayed_confirm,
):
    from app.data_engine.bar_aggregator import aggregator as aggregator_module

    identity = dict(symbol=symbol, interval="5m", exchange="bybit", market_type=market_type)
    opened, step = 1_794_138_000_000, 300_000
    now = opened
    monkeypatch.setattr(aggregator_module, "time", SimpleNamespace(time=lambda: now / 1000))
    dm, store, factory, requests = await manager(tmp_path, monkeypatch, identity=identity)
    target = {**identity, "interval": "10m"}
    events, errors, _ = capture(dm, identity=identity)
    derived, derived_errors, _ = capture(dm, identity=target)

    async def feed(bar_open, price, source, received, *, closed):
        nonlocal now
        now = received
        fields = {"is_closed": closed}
        if source is DataSource.WEBSOCKET:
            fields["source_close_time_ms"] = bar_open + step - 1
        await factory.pipeline.normalize.ingest(RawMessage(
            payload=make_unified_payload("kline", [bar_open, price, price, price, price, 10], **fields),
            source=source, stream_type=StreamType.KLINE, received_at_ms=received,
        ))

    try:
        await dm.ensure_stream(**target)
        await feed(opened, 100, DataSource.WEBSOCKET, opened + step, closed=True)
        await feed(opened + step, 101, DataSource.WEBSOCKET, opened + 2 * step - 1000, closed=False)
        # A poll may label the elapsed slot closed based solely on wall time.
        await feed(opened + step, 101, DataSource.HTTP, opened + 2 * step + 1000, closed=True)

        if delayed_confirm:
            await feed(opened + step, 102, DataSource.WEBSOCKET, opened + 2 * step + 2000, closed=True)
        await feed(opened + 2 * step, 103, DataSource.HTTP, opened + 2 * step + 3000, closed=False)

        if delayed_confirm:
            await _until(lambda: len(closed(events)) == 2 and len(closed(derived)) == 1)
            rows = store.query_bars(**identity, start_ms=opened + step, end_ms=opened + step)
            assert [(bar["close"], bar["source"]) for bar in rows] == [(102, "bybit_ws_confirmed")]
            rows = store.query_bars(**target, start_ms=opened, end_ms=opened)
            assert [(bar["close"], bar["source"]) for bar in rows] == [(102, "data_manager_composite_closed")]
            assert dm.source_gaps.pending() == []
        else:
            pending = {gap.key.interval: gap.expected for gap in dm.source_gaps.pending()}
            assert pending == {"5m": {opened + step}, "10m": {opened}}
            submitted = {args[1]: (args[2], args[3]) for args, kwargs in requests
                         if kwargs.get("requester") == "ingestion_gap"}
            assert submitted == {"5m": (opened + step, opened + step), "10m": (opened, opened)}
            assert store.query_bars(**identity, start_ms=opened + step, end_ms=opened + step) == []
            from app.data_engine.backfill import BackfillConfig, BackfillEngine
            from app.data_engine.data_manager.backfill_contracts import RepairRequest
            from app.data_engine.history import (
                ExchangeHistoryPolicyResolver, HistoryAvailabilityService, HistoryBoundaryRepository,
                get_history_calendar_registry,
            )
            from app.data_engine.storage.gap_ledger import GapLedger

            rest_calls = []

            class Transport:
                async def http_fetch(self, request):
                    rest_calls.append((request.descriptor.interval, request.start_ms, request.end_ms))
                    await asyncio.sleep(.05)
                    return [
                        RawMessage(make_unified_payload(
                            "kline", [stamp, price, price, price, price, 10], is_closed=True,
                        ), DataSource.HTTP, StreamType.KLINE, stamp + step, http_status=200)
                        for stamp, price in [(opened, 100), (opened + step, 102)]
                        if request.start_ms <= stamp <= request.end_ms
                    ]

            history = HistoryAvailabilityService(
                calendars=get_history_calendar_registry(),
                boundaries=HistoryBoundaryRepository(klines_repo.KLINES_DB_PATH),
            )
            policy = ExchangeHistoryPolicyResolver(history)
            ledger = GapLedger(klines_repo.KLINES_DB_PATH)
            engine = BackfillEngine(
                BackfillConfig(history_archive_enabled=False, fetch_rate_limit_delay=0),
                klines_repo.AsyncKlinesRepoAdapter(), Transport(),
                ingestion_config=IngestionConfig(proxy_mode="none"),
            )
            async def no_rate_limit():
                pass

            engine.fetcher.set_rate_limiter(no_rate_limit)
            coordinator = BackfillCoordinator(
                storage=store, bars_backfilled=dm.on_bars_backfilled, emit_event=dm.emit_event,
                source_available=dm.source_storage_available, engine=engine, gap_ledger=ledger,
                history_service=history,
                history_policy_resolver=lambda repair: policy.resolve(policy.series_key(
                    exchange=repair.exchange, market_type=repair.market_type, symbol=repair.symbol,
                    channel="kline", variant=repair.interval,
                )),
                loop=asyncio.get_running_loop(), max_concurrency=2,
            )
            # Exercise both possible orders while retaining independent target tickets.
            repairs = [RepairRequest(
                args[0], args[1], args[2], args[3], exchange=args[4], market_type=args[5], **kwargs,
            ) for args, kwargs in requests if kwargs.get("requester") == "ingestion_gap"]
            repairs.sort(key=lambda repair: repair.interval != ("5m" if market_type == "swap.inverse" else "10m"))
            try:
                results = await asyncio.wait_for(asyncio.gather(*(
                    coordinator.request_and_wait(repair) for repair in repairs
                )), 5)
                assert all(result.status == "completed" and result.verified_contiguous for result in results)
                assert rest_calls == [("5m", opened + step, opened + step)]
                assert [ledger.get_status(repair)["status"] for repair in repairs] == ["filled", "filled"]
            finally:
                await coordinator.shutdown()
                await engine.close()
            await _until(lambda: len(closed(events)) == 2 and len(closed(derived)) == 1)
            assert events[-1].bar.close == derived[-1].bar.close == 102
            assert events[-1].detail["continuity_replayed"] is True
            assert derived[-1].detail["continuity_replayed"] is True
            assert dm.source_gaps.pending() == []
        assert errors == derived_errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
@pytest.mark.parametrize("repaired", [True, False])
async def test_browser_batch_gets_exact_gap_before_repair_and_http_fences_only_that_range(
    tmp_path, monkeypatch, repaired,
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.api.v1.klines import router as klines_router
    from app.api.v1.stream_kline_batch import KlineBatchConnection, KlineBatchLimits, _BatchSubscription, _EVENT_TYPES
    from tests.test_kline_batch_source_recovery import Socket
    from starlette.websockets import WebSocketDisconnect

    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    socket = Socket()
    connection = KlineBatchConnection(socket, dm, limits=KlineBatchLimits.from_config())
    wire = asyncio.create_task(connection.run())
    app = FastAPI()
    app.state.data_manager = dm
    app.include_router(klines_router, prefix="/api/v1")
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    async def strict_range(time):
        response = await http.get("/api/v1/klines/range", params={
            **IDENTITY, "start_ms": time, "end_ms": time, "strict": "true", "repair": "none",
        })
        assert response.status_code == 200, response.text
        return response.json()

    opened = T + 60_000
    subscription = _BatchSubscription(
        client_id="chart", consumer_id="chart-owner", exchange=IDENTITY["exchange"],
        market_type=IDENTITY["market_type"], symbol=IDENTITY["symbol"],
    )
    handle = await dm.subscribe_async(
        connection._event_callback(subscription), **IDENTITY, event_types=_EVENT_TYPES,
        on_recovery=connection._require_resync,
    )
    try:
        await factory.emit(T, 99)
        await _until(lambda: any(msg.get("event_type") == "bar.closed" for msg in socket.messages))
        before = dm.query(start_ms=T, end_ms=T, auto_backfill=False, **IDENTITY).metadata["stream_version"]
        await factory.emit(T + 120_000, 101)
        await _until(lambda: any(msg.get("status") == "source_gap" for msg in socket.messages))
        pending = next(msg for msg in socket.messages if msg.get("status") == "source_gap")
        assert pending["detail"]["state"] == "recovering"
        assert pending["detail"]["range_start_ms"] == pending["detail"]["range_end_ms"] == opened
        assert pending["stream_version"]["barrier"] > before["barrier"]
        assert not any(msg.get("data", {}).get("time") == (T + 120_000) // 1000 for msg in socket.messages)

        affected = await strict_range(opened)
        disjoint = await strict_range(T)
        assert affected["stream_version"]["stable"] is False
        assert affected["retryable"] and not affected["renderable"] and not affected["data"]
        assert disjoint["stream_version"]["stable"] and disjoint["data"][0]["close"] == 99
        if repaired:
            await _history_repair(dm, store, opened, 150)
            await _until(lambda: any(msg.get("detail", {}).get("reason") == "source_gap_resolved"
                                     for msg in socket.messages))
            resolved = next(msg for msg in socket.messages if msg.get("detail", {}).get("reason") == "source_gap_resolved")
            assert resolved["detail"]["gap_id"] == pending["detail"]["gap_id"]
            assert resolved["stream_version"]["barrier"] > pending["stream_version"]["barrier"]
            result = await strict_range(opened)
            assert result["stream_version"]["stable"] and result["verified_contiguous"]
            assert result["data"][0]["close"] == 150
        else:
            await dm.event_bus.emit(DataEvent(
                DataEventType.BACKFILL_FAILED, handle.key, detail={"source_gap_id": pending["detail"]["gap_id"]},
            ))
            await asyncio.wait_for(wire, 1)
            failed = next(msg for msg in socket.messages if msg.get("detail", {}).get("state") == "failed")
            assert failed["detail"]["error"] == "source_repair_failed"
            assert failed["detail"]["range_start_ms"] == opened
            assert socket.closes == [(1013, "CONSUMER_RESYNC_REQUIRED")]
            result = await strict_range(opened)
            assert not result["stream_version"]["stable"] and not result["data"]
    finally:
        await http.aclose()
        if not wire.done():
            await socket.input.put(WebSocketDisconnect(1000))
            await asyncio.wait_for(wire, 1)
        await _close(dm, factory)


@pytest.mark.anyio
async def test_partial_and_untrusted_repair_cannot_release_strict_subscriber(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    strict, errors, _ = capture(dm)
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 180_000, 102)
        await _history_repair(dm, store, T + 60_000, 100)
        await dm.on_bars_backfilled(bars=[BarData(T // 1000 + 120, 1, 1, 1, 1, 1)], **IDENTITY)
        assert dm.source_gaps.pending()
        await _history_repair(dm, store, T + 120_000, 101)
        await _until(lambda: len(closed(strict)) == 4)
        assert closed(strict) == [T // 1000 + i * 60 for i in range(4)]
        assert errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_timeout_is_per_subscriber_and_does_not_cancel_shared_repair(tmp_path, monkeypatch):
    dm, store, factory, requests = await manager(tmp_path, monkeypatch)
    quick, errors, _ = capture(dm, policy=ContinuityPolicy(max_wait_seconds=0.02))
    patient, patient_errors, _ = capture(dm)
    live, _, _ = capture(dm, policy="gap_aware")
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(closed(quick)) == 1)
        await factory.emit(T + 120_000, 101)
        await _until(lambda: bool(errors))
        assert errors[0].reason == "source_gap_timeout"
        await _history_repair(dm, store, T + 60_000, 100)
        await _until(lambda: len(closed(patient)) == 3)
        assert len(closed(quick)) == 1
        assert len(closed(live)) == 2
        assert len(requests) == 1 and patient_errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_new_subscriber_observes_an_already_pending_gap(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 120_000, 101)
        strict, errors, _ = capture(dm)
        live, _, _ = capture(dm, policy="gap_aware")
        await _until(lambda: any(event.event_type == DataEventType.SOURCE_GAP for event in live))
        await factory.emit(T + 180_000, 102)
        await _history_repair(dm, store, T + 60_000, 100)
        await _until(lambda: bool(errors))
        # It did not receive the pre-subscription tail. Repair alone cannot
        # make that old tail a continuous subscription: require a fresh seed.
        assert closed(strict) == []
        assert errors[0].reason == "source_gap_snapshot_required"
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_iterator_timeout_is_explicit_and_removes_subscription(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    iterator = dm.subscribe_iter(**IDENTITY, event_types={DataEventType.BAR_CLOSED},
                                 continuity=ContinuityPolicy(max_wait_seconds=0.02))
    next_event = asyncio.create_task(anext(iterator))
    try:
        await _until(lambda: dm.event_bus.get_subscriber_count() == 1)
        await factory.emit(T, 99)
        assert (await next_event).bar.time == T // 1000
        next_event = asyncio.create_task(anext(iterator))
        await factory.emit(T + 120_000, 101)
        with pytest.raises(ConsumerRecoveryRequired, match="source_gap_timeout"):
            await next_event
        assert dm.event_bus.get_subscriber_count() == 0
    finally:
        next_event.cancel()
        await iterator.aclose()
        await _close(dm, factory)


@pytest.mark.anyio
async def test_bounded_replay_exhaustion_terminates_waiter(tmp_path, monkeypatch):
    config = DataManagerConfig(event_bus=EventBusConfig(subscriber_queue_size=2, replay_capacity=3))
    dm, store, factory, _ = await manager(tmp_path, monkeypatch, config)
    strict, errors, _ = capture(dm)
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(T + 120_000, 101)
        for i in range(3, 15):
            await factory.emit(T + i * 60_000, 101)
        await _until(lambda: bool(errors))
        assert errors[0].reason == "replay_window_exhausted"
        await _history_repair(dm, store, T + 60_000, 100)
        assert closed(strict) == [T // 1000]
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_derived_gap_requires_verified_target_bars(tmp_path, monkeypatch):
    dm, store, factory, requests = await manager(tmp_path, monkeypatch)
    identity = {**IDENTITY, "interval": "7m"}
    await dm.ensure_stream(**identity)
    strict, errors, _ = capture(dm, identity=identity)
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 120_000, 101)
        target = SeriesKey(**identity)
        assert dm.source_gaps.pending(target)
        assert {request[0][1] for request in requests} == {"1m", "7m"}
        await _history_repair(dm, store, T + 60_000, 100)
        assert dm.source_gaps.pending(target) and closed(strict) == []
        opened = parse_interval_spec("7m").floor_ms(T + 60_000)
        await _committed_backfill(dm, store, bars=[BarData(opened // 1000, 99, 101, 99, 100, 7,
                                                 source="backfill_rest_verified")], **identity)
        await _until(lambda: len(closed(strict)) == 1)
        assert errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.parametrize("value", ["unknown", ContinuityPolicy("gap_aware")])
def test_policy_is_validated(value):
    if value == "unknown":
        with pytest.raises(ValueError):
            ContinuityPolicy.resolve(value)
    else:
        assert ContinuityPolicy.resolve(value) is value


@pytest.mark.anyio
async def test_real_coordinator_repairs_and_reads_storage_before_releasing_consumer(tmp_path, monkeypatch):
    from app.data_engine.backfill.config import BackfillConfig
    from app.data_engine.backfill.models import BackfillTask, BackfillPlan, FetchResult, FetchedBar
    from app.data_engine.backfill.reconciler import Reconciler

    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    gate = asyncio.Event()
    calls = []
    class Engine:
        async def run(self, **kwargs):
            calls.append(kwargs)
            await gate.wait()
            start, end = kwargs["range_start_ms"], kwargs["range_end_ms"]
            bars = [FetchedBar(open_time=opened, close_time=opened + 59_999,
                               open=100, high=100, low=100, close=100, volume=1, **IDENTITY)
                    for opened in range(start, end + 1, 60_000)]
            reconciler = Reconciler(BackfillConfig(), klines_repo.AsyncKlinesRepoAdapter())
            result = await reconciler.reconcile([FetchResult(
                task=BackfillTask(start_ms=start, end_ms=end, **IDENTITY), bars=bars,
            )], BackfillPlan(gaps=[]))
            return SimpleNamespace(status="completed", errors=[], reconcile_result=result)
    coordinator = BackfillCoordinator(storage=store, bars_backfilled=dm.on_bars_backfilled,
                                      emit_event=dm.emit_event, engine=Engine(), base_delay_seconds=0,
                                      max_retries=1)
    dm.set_backfill_trigger(coordinator.trigger)
    strict, errors, _ = capture(dm)
    live, _, _ = capture(dm, policy="gap_aware")
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 120_000, 101)
        await _until(lambda: len(closed(live)) == 2 and bool(calls))
        assert closed(strict) == [T // 1000]
        gate.set()
        await _until(lambda: len(closed(strict)) == 3)
        rows = store.query_bars(order="ASC", **IDENTITY)
        assert [row["open_time"] for row in rows] == [T, T + 60_000, T + 120_000]
        assert len(calls) == 1 and errors == []
    finally:
        gate.set()
        await coordinator.shutdown()
        await _close(dm, factory)


@pytest.mark.anyio
async def test_multiple_gaps_preserve_boundary_order(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    strict, errors, _ = capture(dm)
    try:
        for minute in [0, 2, 4]:
            await factory.emit(T + minute * 60_000, minute + 99)
        # Later REST work finishes first, but its bars cannot overtake the
        # earlier missing range or the intervening live boundary.
        await _history_repair(dm, store, T + 180_000, 102)
        await _history_repair(dm, store, T + 60_000, 100)
        await _until(lambda: len(closed(strict)) == 5)
        assert closed(strict) == [T // 1000 + i * 60 for i in range(5)]
        assert errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_cancel_waiting_consumer_does_not_cancel_shared_future(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    _, _, handle = capture(dm)
    patient, errors, _ = capture(dm)
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 120_000, 101)
        dm.unsubscribe(handle)
        await _history_repair(dm, store, T + 60_000, 100)
        await _until(lambda: len(closed(patient)) == 3)
        assert errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_terminal_repair_failure_notifies_strict_and_gap_aware(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    strict, errors, _ = capture(dm)
    live, _, _ = capture(dm, policy="gap_aware")
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 120_000, 101)
        gap = dm.source_gaps.pending()[0]
        await dm.emit_event(DataEvent(DataEventType.BACKFILL_FAILED, gap.key,
                                      detail={"source_gap_id": gap.id}))
        await _until(lambda: bool(errors) and any(e.detail.get("state") == "failed" for e in live))
        assert errors[0].reason == "source_repair_failed"
        assert closed(strict) == [T // 1000]
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_factory_uses_downstream_owner_before_start_and_refuses_mixed_reuse(tmp_path, monkeypatch):
    from app.data_engine.ingestion import MarketDataIngress
    from app.data_engine.ingestion.factory import ExchangeIngestionFactory
    async def start(pipeline):
        assert pipeline.recovery.gap_repair_owner == "data_manager"
    monkeypatch.setattr(StreamPipeline, "start", start)
    factory = ExchangeIngestionFactory()
    ingress = MarketDataIngress(factory.config)
    ingress._started = True
    factory._ingress = ingress
    dm, store, harness, requests = await manager(tmp_path, monkeypatch)
    await dm.coordinator.stop_all()
    dm.set_ingestion_factory(factory)
    strict, _, _ = capture(dm)
    live, _, _ = capture(dm, policy="gap_aware")
    try:
        await dm.ensure_stream(**IDENTITY)
        harness.pipeline = next(iter(ingress.pipelines.values()))
        await harness.emit(T, 99)
        await harness.emit(T + 120_000, 101)
        await _until(lambda: len(closed(live)) == 2)
        assert closed(strict) == [T // 1000]
        async def ignore(_):
            pass
        with pytest.raises(ValueError, match="gap repair owner"):
            await factory.start(on_market_event=ignore, **IDENTITY)
        await _history_repair(dm, store, T + 60_000, 100)
        await _until(lambda: len(closed(strict)) == 3)
    finally:
        await factory.shutdown()
        await _close(dm, harness)


@pytest.mark.anyio
async def test_alert_catchup_updates_state_without_firing_historical_crossings(tmp_path, monkeypatch):
    from app.alerts.facade import AlertFacade
    from app.alerts.runtime import AlertRuntimeEngine
    from tests.test_alerts_runtime import _rule_payload

    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    facade = AlertFacade(store_path=tmp_path / "alerts.json")
    rule = facade.save_rule(_rule_payload(target={
        "exchange": "binance", "marketType": "futures", "symbol": "BTCUSDT", "interval": "1m",
    }))
    alerts = AlertRuntimeEngine(facade=facade, data_manager=dm)
    triggers, evaluated, errors = [], [], []
    async def triggered(payload, **kwargs):
        triggers.append(payload)
        return payload
    async def evaluate(event):
        await alerts.evaluate_event(rule["id"], event)
        evaluated.append(event)
    async def recover(error):
        errors.append(error)
    monkeypatch.setattr(facade, "emit_triggered", triggered)
    dm.subscribe(evaluate, event_types={DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED},
                 on_recovery=recover, **IDENTITY)
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 120_000, 101)
        await _history_repair(dm, store, T + 60_000, 150)
        await _until(lambda: len(closed(evaluated)) == 3)
        assert triggers == []
        await factory.emit(T + 180_000, 99)
        await factory.emit(T + 240_000, 101)
        await _until(lambda: len(closed(evaluated)) == 5)
        assert len(triggers) == 1 and errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_calendar_gap_does_not_wait_for_closed_session_minutes(tmp_path, monkeypatch):
    from app.data_engine.history.calendar import AlwaysOpenCalendar
    dm, store, factory, requests = await manager(tmp_path, monkeypatch)
    class Calendar(AlwaysOpenCalendar):
        def next_expected_open(self, opened, interval):
            return {T: T + 60_000, T + 60_000: T + 180_000}.get(opened, opened + 60_000)
        def count_expected(self, start, end, interval):
            return 1
    factory.pipeline.continuity.set_calendar_resolver(lambda *args: Calendar())
    strict, errors, _ = capture(dm)
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 180_000, 101)
        assert dm.source_gaps.pending()[0].expected == {T + 60_000}
        assert requests[0][0][2:4] == (T + 60_000, T + 60_000)
        await _history_repair(dm, store, T + 60_000, 100)
        await _until(lambda: len(closed(strict)) == 3)
        assert closed(strict) == [T // 1000, T // 1000 + 60, T // 1000 + 180]
        assert errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_native_calendar_anchor_is_preserved_in_repair_request(tmp_path, monkeypatch):
    from app.data_engine.ingestion.models import GapMarker
    from app.exchanges.plugins.binance.calendar import BinanceFuturesCalendar
    dm, store, factory, requests = await manager(tmp_path, monkeypatch)
    try:
        calendar = BinanceFuturesCalendar()
        missing = calendar.next_expected_open(T, "3d")
        # This exchange's native anchor is deliberately different from the
        # generic synthetic 3d interval floor.
        assert missing != parse_interval_spec("3d").floor_ms(missing)
        key = SeriesKey(**{**IDENTITY, "interval": "3d"})
        await dm._handle_ingestion_gap(key, GapMarker(
            stream_key="native", symbol=key.symbol, stream_type=StreamType.KLINE,
            gap_start=missing - 259_200_000, gap_end=missing + 259_200_000,
            expected_count=1, expected_open_times=(missing,),
        ))
        assert requests[0][0][2:4] == (missing, missing)
        assert dm.source_gaps.pending(key)[0].expected == {missing}
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_derived_stream_started_during_base_gap_inherits_it(tmp_path, monkeypatch):
    dm, store, factory, requests = await manager(tmp_path, monkeypatch)
    try:
        await factory.emit(T, 99)
        await factory.emit(T + 120_000, 101)
        identity = {**IDENTITY, "interval": "7m"}
        await dm.ensure_stream(**identity)
        target = SeriesKey(**identity)
        assert dm.source_gaps.pending(target)
        assert {request[0][1] for request in requests} == {"1m", "7m"}
        await _history_repair(dm, store, T + 60_000, 100)
        assert dm.source_gaps.pending(target)
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_stop_wakes_strict_and_restart_does_not_reuse_failed_gap(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    strict, errors, _ = capture(dm)
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(T + 120_000, 101)
        await dm.coordinator.stop_all()
        await _until(lambda: bool(errors))
        assert errors[0].reason == "source_stream_closed"
        await dm.ensure_stream(**IDENTITY)
        assert dm.source_gaps.pending(SeriesKey(**IDENTITY)) == []
        restarted, new_errors, _ = capture(dm)
        await factory.emit(T + 180_000, 102)
        await _until(lambda: bool(closed(restarted)))
        assert new_errors == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_source_tracking_overflow_is_explicit_for_both_modes(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    dm.source_gaps.max_gaps = 1
    strict, errors, _ = capture(dm)
    live, _, _ = capture(dm, policy="gap_aware")
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(T + 120_000, 101)
        await factory.emit(T + 240_000, 102)
        await _until(lambda: bool(errors) and len(closed(live)) == 3)
        assert errors[0].reason in {"source_gap_history_exhausted", "source_gap_tracking_exhausted"}
        assert len(dm.source_gaps.gaps) == 1
        assert live[-1].detail["source_continuity"]["state"] == "unverified"
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
@pytest.mark.parametrize("subscriber", ["callback", "iterator"])
async def test_deferred_prior_receipt_is_not_silently_dropped_after_repair(tmp_path, monkeypatch, subscriber):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    strict, errors = [], []
    collector = None
    if subscriber == "callback":
        strict, errors, _ = capture(dm)
    else:
        async def collect():
            try:
                async for event in dm.subscribe_iter(**IDENTITY, event_types={DataEventType.BAR_CLOSED}):
                    strict.append(event)
            except ConsumerRecoveryRequired as error:
                errors.append(error)
        collector = asyncio.create_task(collect())
        await _until(lambda: dm.event_bus.get_subscriber_count() == 1)
    delivery = dm.aggregator_bridge.delivery
    try:
        # Reproduce the durable dispatcher's admission-without-publication
        # path, so a pre-gap final receipt is still pending at gap detection.
        async with delivery._dispatcher:
            await factory.emit(T, 99)
            await factory.emit(T + 120_000, 101)
            await _history_repair(dm, store, T + 60_000, 100)
            await _until(lambda: bool(closed(strict)))
        await delivery.flush()
        await _until(lambda: bool(errors))
        # With durable revision fencing the stale receipt never reaches the
        # bus; without it, the continuity adapter detects the late close.
        assert errors[0].reason in {"source_delivery_reordered", "source_revision_superseded"}
        assert closed(strict) == [T // 1000 + 60]
    finally:
        if collector is not None:
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)
        await _close(dm, factory)


@pytest.mark.anyio
async def test_recovery_stops_remaining_gap_replay_after_inflight_callback(tmp_path, monkeypatch):
    config = DataManagerConfig(event_bus=EventBusConfig(subscriber_queue_size=2, replay_capacity=3))
    dm, store, factory, _ = await manager(tmp_path, monkeypatch, config)
    events, errors = [], []
    entered, release = asyncio.Event(), asyncio.Event()

    async def receive(event):
        events.append(event)
        if event.detail.get("continuity_replayed"):
            entered.set()
            await release.wait()

    async def recover(error):
        errors.append(error)

    dm.subscribe(receive, **IDENTITY, event_types={DataEventType.BAR_CLOSED}, on_recovery=recover)
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(events) == 1)
        await factory.emit(T + 180_000, 102)
        await _history_repair(dm, store, T + 60_000, 100)
        await _history_repair(dm, store, T + 120_000, 101)
        await asyncio.wait_for(entered.wait(), 3)
        for minute in range(4, 15):
            await factory.emit(T + minute * 60_000, 102)
        await _until(lambda: bool(errors))
        assert errors[0].reason == "replay_window_exhausted"
        release.set()
        await _until(lambda: all(task.done() for task in dm.event_bus._worker_tasks))
        assert closed(events) == [T // 1000, T // 1000 + 60]
    finally:
        release.set()
        await _close(dm, factory)


@pytest.mark.anyio
async def test_iterator_seeds_gap_opened_while_registration_waits_for_gc(tmp_path, monkeypatch):
    from app.data_engine.data_manager import event_bus as bus_module
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    registering, release = asyncio.Event(), asyncio.Event()
    original = bus_module.apply_thread_guard
    async def delayed_guard(lock, operation):
        if operation.__name__ == "register":
            registering.set()
            await release.wait()
        return await original(lock, operation)
    monkeypatch.setattr(bus_module, "apply_thread_guard", delayed_guard)
    iterator = dm.subscribe_iter(**IDENTITY, event_types={DataEventType.BAR_CLOSED})
    next_event = asyncio.create_task(anext(iterator))
    try:
        await registering.wait()
        await factory.emit(T, 99)
        await factory.emit(T + 120_000, 101)
        release.set()
        await _until(lambda: dm.event_bus.get_subscriber_count() == 1)
        await _history_repair(dm, store, T + 60_000, 100)
        with pytest.raises(ConsumerRecoveryRequired, match="source_gap_snapshot_required"):
            await next_event
        assert dm.event_bus.get_subscriber_count() == 0
    finally:
        release.set()
        next_event.cancel()
        await asyncio.gather(next_event, return_exceptions=True)
        await iterator.aclose()
        await _close(dm, factory)


@pytest.mark.anyio
async def test_iterator_replay_exhaustion_wakes_wait_without_late_delivery(tmp_path, monkeypatch):
    config = DataManagerConfig(event_bus=EventBusConfig(subscriber_queue_size=2, replay_capacity=3))
    dm, store, factory, _ = await manager(tmp_path, monkeypatch, config)
    iterator = dm.subscribe_iter(**IDENTITY, event_types={DataEventType.BAR_CLOSED})
    next_event = asyncio.create_task(anext(iterator))
    try:
        await _until(lambda: dm.event_bus.get_subscriber_count() == 1)
        await factory.emit(T, 99)
        assert (await next_event).bar.time == T // 1000
        next_event = asyncio.create_task(anext(iterator))
        await factory.emit(T + 120_000, 101)
        for minute in range(3, 15):
            await factory.emit(T + minute * 60_000, 101)
        with pytest.raises(ConsumerRecoveryRequired, match="replay_window_exhausted"):
            await next_event
        await _history_repair(dm, store, T + 60_000, 100)
        assert dm.event_bus.get_subscriber_count() == 0
    finally:
        next_event.cancel()
        await asyncio.gather(next_event, return_exceptions=True)
        await iterator.aclose()
        await _close(dm, factory)


@pytest.mark.anyio
@pytest.mark.parametrize("notify_revision", [False, True])
async def test_partial_gap_repair_uses_latest_canonical_revision(tmp_path, monkeypatch, notify_revision):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    strict, errors, _ = capture(dm)
    live, _, _ = capture(dm, policy="gap_aware")
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(T + 180_000, 103)
        await _history_repair(dm, store, T + 60_000, 100)
        if notify_revision:
            await _history_repair(dm, store, T + 60_000, 150)
        else:
            # A durable writer can revise the first repair before its next
            # notification. Completion must re-read the whole missing range.
            row = store.query_bars(**IDENTITY, start_ms=T + 60_000, end_ms=T + 60_000)[0]
            row.update(open=150, high=150, low=150, close=150)
            store.upsert_bars(**IDENTITY, rows=[row], source="backfill_rest_verified")
        await _history_repair(dm, store, T + 120_000, 102)
        await _until(lambda: len(closed(strict)) == 4)
        assert errors == []
        assert [e.bar.close for e in strict if e.event_type == DataEventType.BAR_CLOSED] == [99, 150, 102, 103]
        repaired = [e.bar.close for e in live if e.event_type == DataEventType.BAR_AMENDED and e.bar.time == T // 1000 + 60]
        assert repaired == [100, 150]
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_deleted_partial_repair_cannot_complete_strict_gap(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    strict, errors, _ = capture(dm)
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(T + 180_000, 103)
        await _history_repair(dm, store, T + 60_000, 100)
        store.delete_bars(**IDENTITY, start_ms=T + 60_000, end_ms=T + 60_000)
        await _history_repair(dm, store, T + 120_000, 102)
        await _until(lambda: bool(errors) or len(closed(strict)) == 4)
        assert closed(strict) == [T // 1000]
        assert errors and errors[0].reason == "source_gap_revision_changed"
        assert store.query_bars(**IDENTITY, start_ms=T + 60_000, end_ms=T + 60_000) == []
    finally:
        await _close(dm, factory)


@pytest.mark.anyio
async def test_next_natural_close_survives_repair_of_older_gap(tmp_path, monkeypatch):
    dm, store, factory, _ = await manager(tmp_path, monkeypatch)
    strict, errors, _ = capture(dm)
    live, live_errors, _ = capture(dm, policy="gap_aware")
    try:
        await factory.emit(T, 99)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(T + 180_000, 103, closed=False)
        await _history_repair(dm, store, T + 60_000, 100)
        await _history_repair(dm, store, T + 120_000, 102)
        await _until(lambda: len(closed(strict)) == 3)
        # The forming candle was acquired before historical revisions, but its
        # input lies entirely after the repaired range. Its natural close must
        # still be delivered, including when composed with D126 fencing.
        await factory.emit(T + 180_000, 103)
        await _until(lambda: len(closed(strict)) == 4 or bool(errors))
        assert errors == live_errors == []
        assert closed(strict) == [T // 1000 + i * 60 for i in range(4)]
        assert closed(live) == [T // 1000, T // 1000 + 180]
    finally:
        await _close(dm, factory)
