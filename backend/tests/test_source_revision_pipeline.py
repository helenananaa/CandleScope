from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.klines import router as klines_router
from app.api.v1.stream_klines import _serialize_kline_event
from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.errors import BacktestError

from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
from app.data_engine.bar_aggregator import aggregator as aggregation_module
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.aggregator_bridge import AggregatorBridge
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.data_manager.models import SeriesKey, DataEventType
from app.data_engine.ingestion import StreamPipeline
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import (
    DataSource,
    RawMessage,
    StreamDescriptor,
    StreamType,
)
from app.data_engine.storage import klines_repo, kline_sources
from app.data_engine.storage.prefix_watches import ProcessedPrefixChanged
from app.local_data.service import LocalDatasetService
from tests.test_ccxt_fork_kline import FRAME, MARKET, fork_exchange
from tests.test_continuous_bar_host import prepare

DESC = StreamDescriptor(
    "BTCUSDT", StreamType.KLINE, interval="1m", market_type="futures"
)
OPENED = 1772323200000


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "klines.sqlite")
    klines_repo.init_klines_storage()


def message(opened=OPENED, *, quote="1010", closed=True, event_time=None, high="103"):
    frame = copy.deepcopy(FRAME)
    frame["E"] = event_time or opened + 60001
    frame["k"].update(t=opened, T=opened + 59999, i="1m", q=quote, x=closed, h=high)
    return RawMessage(
        fork_exchange().parse_candlescope_ws_kline(frame),
        DataSource.WEBSOCKET,
        StreamType.KLINE,
        frame["E"] + 10,
    )


class Harness:
    def __init__(self, *intervals):
        self.aggregator = BarAggregator(BarAggregatorConfig())
        self.cache = BarCache()
        self.bus = DataEventBus()
        self.events = []

        async def receive(event):
            self.events.append(event)

        self.bus.subscribe(receive)
        self.bridge = AggregatorBridge(
            cache=self.cache,
            event_bus=self.bus,
            storage_provider=lambda: klines_repo.KlinesRepoAdapter(),
            mark_bar_received=lambda key: None,
            is_started=lambda: True,
        )
        self.aggregator.set_source_component_reader(self.bridge.read_source_components)
        self.aggregator.publisher.on_bar_event(self.bridge.on_bar_event)
        for interval in intervals or ("1m",):
            self.aggregator.add_target("BTCUSDT", interval, market_type="futures")
        self.pipeline = StreamPipeline(
            IngestionConfig(ccxt_fork_kline_enabled=True), None, DESC
        )
        self.pipeline.delivery.on_market_event(self.aggregator.on_market_event)

    async def ingest(self, value):
        await self.pipeline.normalize.ingest(value)
        await self.bridge.delivery.flush()

    async def close(self):
        await self.pipeline.recovery.stop()
        await self.bridge.delivery.stop()
        await self.bus.close()


def test_closed_revision_reaches_native_derived_storage_cache_and_bus(database):
    async def run():
        harness = Harness("1m", "2m")
        try:
            await harness.ingest(message())
            await harness.ingest(message(OPENED + 60000))
            await harness.ingest(message(quote="1008", event_time=OPENED + 120010))
            rows = klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")
            assert rows[0]["quote_volume"] == 1008
            derived = klines_repo.query_klines("BTCUSDT", "2m", market_type="futures")
            assert len(derived) == 1 and derived[0]["quote_volume"] == 2018
            key = SeriesKey("BTCUSDT", "1m", market_type="futures")
            assert harness.cache.get_bar_at(key, OPENED // 1000).quote_volume == 1008
            assert any(
                event.event_type == DataEventType.BAR_AMENDED
                and event.bar.quote_volume == 1008
                for event in harness.events
            )
            assert not kline_sources.pending(DESC)
            count = len(harness.events)
            await harness.ingest(message(quote="1008", event_time=OPENED + 120010))
            await harness.ingest(message(quote="1007", event_time=OPENED + 120009))
            await harness.ingest(message(closed=False, event_time=OPENED + 120011))
            assert len(harness.events) == count
        finally:
            await harness.close()

    asyncio.run(run())


@pytest.mark.anyio
async def test_custom_chart_and_strategy_share_the_canonical_close_and_correction(database, tmp_path, monkeypatch):
    # Binance USD-M supplies 1m. 2m is a derived chart period. Continuous
    # strategies deliberately retain the qualified native 1m execution clock.
    minute = 60_000
    native = SeriesKey("BTCUSDT", "1m", market_type="futures")
    custom = SeriesKey("BTCUSDT", "2m", market_type="futures")
    manager = DataManager()
    manager.set_storage(klines_repo.KlinesRepoAdapter())
    manager._started = True  # drive the real ingestion path without external sockets
    aggregator = manager.bar_aggregator
    aggregator.add_target(native.symbol, native.interval, market_type=native.market_type)
    pipeline = StreamPipeline(IngestionConfig(ccxt_fork_kline_enabled=True), None, DESC)
    pipeline.delivery.on_market_event(aggregator.on_market_event)
    delivery = manager.aggregator_bridge.delivery
    events = []
    commit_visible, release = asyncio.Event(), asyncio.Event()
    recovery = asyncio.get_running_loop().create_future()
    next_open = OPENED + 2 * minute
    clock = next_open
    ingest_time = OPENED
    monkeypatch.setattr(aggregation_module, "time", SimpleNamespace(time=lambda: ingest_time / 1000))
    service, _, definition, provider, store = prepare(tmp_path, monkeypatch)
    source = ContinuousMarketBarSource(manager, LocalDatasetService(tmp_path / "local"), native,
                                      clock_ms=lambda: clock)
    host = None
    closing = None

    async def collect(event):
        events.append(event)

    async def recover(error):
        recovery.set_result(error)

    manager.event_bus.subscribe(collect, key=custom, on_recovery=recover)
    publish = delivery._publish

    async def pause_publish(event):
        if event.key == custom and event.event_type == DataEventType.BAR_CLOSED and event.bar.time_ms == next_open:
            commit_visible.set()
            await release.wait()
        await publish(event)

    monkeypatch.setattr(delivery, "_publish", pause_publish)

    async def ingest(frame):
        nonlocal ingest_time
        ingest_time = frame.received_at_ms
        await pipeline.normalize.ingest(frame)
        await delivery.flush()

    app = FastAPI()
    app.include_router(klines_router, prefix="/api/v1")
    app.state.data_manager = manager

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def chart(start, end):
            response = await client.get("/api/v1/klines/range", params={
                "symbol": custom.symbol, "market_type": custom.market_type, "interval": custom.interval,
                "start_ms": start, "end_ms": end, "repair": "none",
            })
            assert response.status_code == 200, response.text
            return response.json()

        try:
            await ingest(message())
            await ingest(message(OPENED + minute))
            first = await chart(OPENED, OPENED)
            assert first["complete"] and first["stream_version"]["stable"]
            assert first["data"][0]["quote_volume"] == 2020
            aggregator.add_target(custom.symbol, custom.interval, market_type=custom.market_type)

            receipt = source.register("cs_shared", from_ms=OPENED)
            definition.update(source_kind="MARKET_BAR", source_series=list(receipt.series),
                              market={"venue": native.exchange, "symbol": native.symbol})
            ContinuousBarHost.create_run(store, "cs_shared", definition=definition, mode="LIVE_ONLY",
                                         data_revision=receipt.incarnation, event_time_ms=receipt.through_ms,
                                         provider_factory=provider, source_receipt=receipt)
            host = ContinuousBarHost.resume(store, "cs_shared", provider)
            source.acquire(host, revealed_through_ms=clock - 1).apply(host, manager)
            assert host.row["sequence"] == 2

            await ingest(message(next_open, closed=False, event_time=next_open + 1))
            incomplete = await chart(OPENED, next_open)
            assert not incomplete["complete"] and incomplete["missing_ranges"]
            assert incomplete["data"] == []
            clock = next_open + 2 * minute
            with pytest.raises(BacktestError, match="complete the exact closed input window"):
                source.acquire(host, revealed_through_ms=clock - 1)
            assert host.row["sequence"] == 2

            await ingest(message(next_open))
            closing = asyncio.create_task(ingest(message(next_open + minute)))
            await asyncio.wait_for(commit_visible.wait(), timeout=5)
            committed = klines_repo.query_klines(custom.symbol, custom.interval, market_type=custom.market_type)
            assert committed[-1]["open_time"] == next_open
            racing = await chart(OPENED, next_open)
            assert racing["stream_version"]["stable"] is False
            assert racing["history_state"] == "pending" and racing["retryable"]
            assert not racing["complete"] and racing["data"] == []
            release.set()
            await closing

            closed = await chart(OPENED, next_open)
            close = next(event for event in events if event.event_type == DataEventType.BAR_CLOSED
                         and event.bar.time_ms == next_open)
            assert closed["complete"] and closed["stream_version"]["stable"]
            assert _serialize_kline_event(close)["data"] == closed["data"][-1]
            source.acquire(host, revealed_through_ms=clock - 1).apply(host, manager)
            assert host.row["sequence"] == 4
            saved = store.load("cs_shared")

            await ingest(message(next_open, quote="1008", event_time=clock + 10))
            # The canonical 1m amendment invalidates the persisted 2m
            # projection. The old derived receipt must recover by reading back.
            assert (await asyncio.wait_for(recovery, timeout=5)).reason == "source_revision_superseded"
            corrected = await chart(OPENED, next_open)
            assert corrected["complete"] and corrected["stream_version"]["stable"]
            assert corrected["stream_version"]["generation"] > closed["stream_version"]["generation"]
            assert corrected["data"][0] == first["data"][0]
            assert corrected["data"][-1]["quote_volume"] == 2018
            with pytest.raises(ProcessedPrefixChanged):
                source.acquire(host, revealed_through_ms=clock - 1)
            assert store.load("cs_shared") == saved
        finally:
            release.set()
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            if host is not None:
                host.close()
            source.close()
            store.close()
            service.shutdown()
            await pipeline.recovery.stop()
            await delivery.stop()
            await manager.event_bus.close()


def test_source_commit_survives_downstream_failure_and_replays_after_reconstruction(
    database,
):
    async def run():
        first = Harness()

        async def fail(event):
            raise OSError("injected consumer failure")

        first.pipeline.delivery._market_event_callbacks = [fail]
        with pytest.raises(OSError):
            await first.ingest(message())
        assert len(kline_sources.pending(DESC)) == 1
        await first.close()
        second = Harness()
        try:
            await second.pipeline.normalize.replay_source_pending()
            await second.bridge.delivery.flush()
            assert not kline_sources.pending(DESC)
            assert (
                klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")[0][
                    "quote_volume"
                ]
                == 1010
            )
        finally:
            await second.close()

    asyncio.run(run())


def test_late_unversioned_and_versioned_projection_cannot_overwrite_selected_revision(
    database,
):
    async def run():
        harness = Harness()
        try:
            await harness.ingest(message())
            old = klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")[0]
            head = kline_sources.latest(DESC, OPENED)
            old["source_refs"] = [
                {k: head[k] for k in ("series", "open_time", "revision")}
            ]
            await harness.ingest(message(quote="1008", event_time=OPENED + 60002))
            assert (
                klines_repo.upsert_klines(
                    "BTCUSDT",
                    "1m",
                    [old],
                    "repair_binance_rest_verified",
                    market_type="futures",
                )
                == 0
            )
            old.pop("source_refs")
            assert (
                klines_repo.upsert_klines(
                    "BTCUSDT",
                    "1m",
                    [old],
                    "backfill_rest_verified",
                    market_type="futures",
                )
                == 0
            )
            assert (
                klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")[0][
                    "quote_volume"
                ]
                == 1008
            )
        finally:
            await harness.close()

    asyncio.run(run())


def test_publisher_retries_a_failed_receipt_after_state_has_already_closed(
    database, monkeypatch
):
    from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable

    async def run():
        harness = Harness()
        journal = harness.bridge.delivery.journal
        enqueue = journal.enqueue

        def fail(*args):
            raise OSError("injected journal admission failure")

        monkeypatch.setattr(journal, "enqueue", fail)
        harness.bridge.delivery.retry_delay = 0
        # Keep one adapter/journal instance for the injected failure.
        adapter = klines_repo.KlinesRepoAdapter()
        adapter.bar_delivery = journal
        harness.bridge._storage_provider = lambda: adapter
        harness.bridge.delivery._storage_provider = lambda: adapter
        try:
            with pytest.raises(BarDeliveryUnavailable):
                await harness.ingest(message())
            assert kline_sources.pending(DESC)
            monkeypatch.setattr(journal, "enqueue", enqueue)
            await harness.ingest(message())
            assert not kline_sources.pending(DESC)
            assert (
                klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")[0][
                    "quote_volume"
                ]
                == 1010
            )
        finally:
            await harness.close()

    asyncio.run(run())


def test_cold_derived_revision_restores_other_closed_components(database):
    async def run():
        first = Harness("1m", "2m")
        await first.ingest(message())
        await first.ingest(message(OPENED + 60000))
        await first.close()
        second = Harness("1m", "2m")
        try:
            await second.ingest(message(quote="1008", event_time=OPENED + 120010))
            rows = klines_repo.query_klines("BTCUSDT", "2m", market_type="futures")
            assert len(rows) == 1 and rows[0]["quote_volume"] == 2018
            assert (
                second.cache.get_bar_at(
                    SeriesKey("BTCUSDT", "2m", market_type="futures"), OPENED // 1000
                ).quote_volume
                == 2018
            )
        finally:
            await second.close()

    asyncio.run(run())


def test_native_final_snapshot_replaces_forming_extrema_without_decimal_rounding(
    database,
):
    async def run():
        harness = Harness()
        try:
            await harness.ingest(
                message(closed=False, high="104", event_time=OPENED + 59999)
            )
            await harness.ingest(message(quote="1010.000000001", high="103"))
            row = klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")[0]
            assert row["high"] == 103 and row["quote_volume"] == 1010.000000001
            assert not kline_sources.pending(DESC)
        finally:
            await harness.close()

    asyncio.run(run())


def test_factory_wires_consumer_before_replaying_pending_source(database, monkeypatch):
    from app.data_engine.ingestion import MarketDataIngress
    from app.data_engine.ingestion.factory import ExchangeIngestionFactory
    from app.exchanges.ccxt_ext.fork_kline import prepare_source_messages

    async def run():
        harness = Harness()
        await prepare_source_messages([message()], DESC)
        ingress = MarketDataIngress(IngestionConfig(ccxt_fork_kline_enabled=True))
        ingress._started = True

        async def no_network(self):
            pass

        monkeypatch.setattr(type(harness.pipeline.feed_control), "start", no_network)
        factory = ExchangeIngestionFactory(ingress.config)
        factory._ingress = ingress
        try:
            await factory._start_descriptor(DESC, harness.aggregator.on_market_event)
            await harness.bridge.delivery.flush()
            assert not kline_sources.pending(DESC)
            assert (
                klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")[0][
                    "quote_volume"
                ]
                == 1010
            )
        finally:
            await factory.shutdown()
            await harness.close()

    asyncio.run(run())


def test_conflicting_ws_timestamp_reconciles_through_rest_and_amends(
    database, monkeypatch
):
    from app.exchanges import get_exchange_registry
    from app.exchanges.ccxt_ext.fork_kline import prepare_source_messages

    async def run():
        harness = Harness()
        requests = []

        async def fetch(req, config):
            requests.append(req)
            row = [
                OPENED,
                "100",
                "103",
                "99",
                "102",
                "10",
                OPENED + 59999,
                "1008",
                4,
                "6",
                "606",
                "0",
            ]
            payload = fork_exchange().parse_candlescope_kline(row, MARKET, "1m")
            payload["_source_rest_server_time_ms"] = OPENED + 120000
            result = [
                RawMessage(payload, DataSource.HTTP, StreamType.KLINE, OPENED + 120001)
            ]
            await prepare_source_messages(
                result, DESC, watermark=kline_sources.rest_watermark()
            )
            return result

        monkeypatch.setattr(
            get_exchange_registry().get_plugin("binance"),
            "fetch_history_with_config",
            fetch,
        )
        try:
            await harness.ingest(message())
            await harness.ingest(message(quote="1009"))
            assert len(requests) == 1 and requests[0].start_ms == OPENED
            assert (
                klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")[0][
                    "quote_volume"
                ]
                == 1008
            )
            assert [
                r["decision"] for r in kline_sources.observations(DESC, OPENED)
            ] == ["selected", "reconcile", "selected"]
            assert not kline_sources.pending(DESC)
        finally:
            await harness.close()

    asyncio.run(run())
