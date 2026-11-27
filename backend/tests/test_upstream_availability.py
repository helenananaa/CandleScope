"""Exchange outages become an explicit offline state (RC item 17, #383 RC-C9)."""
from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.stream import router as stream_router
from app.api.v1.stream_kline_batch import KlineBatchConnection, KlineBatchLimits, _BatchSubscription
from app.api.v1.subscriptions import _prices_with_availability
from app.core import config
from app.data_engine.data_manager.ingestion_price_source import IngestionPriceSource
from app.data_engine.data_manager.upstream_availability import UpstreamAvailability, UpstreamMarket


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Timer:
    def __init__(self, delay, callback) -> None:
        self.delay, self.callback, self.cancelled = delay, callback, False

    def cancel(self) -> None:
        self.cancelled = True


class _Timers:
    def __init__(self) -> None:
        self.pending: list[_Timer] = []

    def __call__(self, delay, callback) -> _Timer:
        timer = _Timer(delay, callback)
        self.pending.append(timer)
        return timer

    def fire(self) -> None:
        timers, self.pending = self.pending, []
        for timer in timers:
            if not timer.cancelled:
                timer.callback()


def _monitor():
    clock, timers = _Clock(), _Timers()
    availability = UpstreamAvailability(grace_seconds=6, break_window_seconds=20, clock=clock, schedule=timers)
    changes = []
    availability.subscribe(changes.append)
    return availability, clock, timers, changes


def _states(changes):
    return [change.offline for change in changes]


def test_connection_break_goes_offline_after_grace_and_data_restores() -> None:
    availability, clock, timers, changes = _monitor()
    probe = availability.probe("kline", "Binance", "futures", "btcusdt")
    probe.observe_data()
    clock.now += 1
    probe.observe_health("reconnecting", "Connection closed by remote server, closing code 1006")

    # Interrupted is not yet offline: a quick reconnect must not flash.
    assert changes == []
    assert [timer.delay for timer in timers.pending] == [6]
    timers.fire()
    assert _states(changes) == [True]
    assert availability.is_offline("kline", "binance", "FUTURES", "BTCUSDT")
    assert changes[0].market == UpstreamMarket("kline", "binance", "futures", "BTCUSDT")
    assert "1006" in changes[0].reason

    # Repeated failure reports during the outage add nothing.
    probe.observe_health("unhealthy", "Server disconnected")
    timers.fire()
    assert _states(changes) == [True]

    probe.observe_data()
    assert _states(changes) == [True, False]
    assert not availability.is_offline("kline", "binance", "futures", "BTCUSDT")


def test_reconnect_that_recovers_within_grace_stays_online() -> None:
    availability, clock, timers, changes = _monitor()
    probe = availability.probe("price", "binance", "spot", "ETHUSDT")
    probe.observe_data()
    probe.observe_health("reconnecting", "CCXT subscription cancelled during websocket recycle")
    probe.observe_health("connected", "CCXT stream active")
    timers.fire()
    assert changes == []
    assert not availability.is_offline("price", "binance", "spot", "ETHUSDT")


def test_quiet_market_stale_recycle_is_not_an_outage() -> None:
    availability, clock, timers, changes = _monitor()
    probe = availability.probe("kline", "binance", "spot", "ILLIQUIDUSDT")
    probe.observe_data()
    # The session recycles after its 30 s stale timeout without any data.
    clock.now += 30
    probe.observe_health("reconnecting", "")
    assert timers.pending == []
    clock.now += 120
    timers.fire()
    assert changes == []

    # Only an exhausted failure budget whose HTTP fallback also brings no
    # data counts as offline.
    probe.observe_health("unhealthy", "")
    timers.fire()
    assert _states(changes) == [True]


def test_http_fallback_data_keeps_an_unhealthy_websocket_online() -> None:
    availability, clock, timers, changes = _monitor()
    probe = availability.probe("price", "binance", "spot", "BTCUSDT")
    probe.observe_data()
    probe.observe_health("unhealthy", "websocket blocked")
    probe.observe_data()  # REST polling still reaches the exchange.
    timers.fire()
    assert changes == []


def test_startup_failure_counts_as_a_break() -> None:
    availability, clock, timers, changes = _monitor()
    probe = availability.probe("kline", "binance", "spot", "BTCUSDT")
    probe.observe_health("connecting", "CCXT runtime starting")
    clock.now += 0.2
    probe.observe_health("reconnecting", "Cannot connect to host")
    timers.fire()
    assert _states(changes) == [True]


def test_market_is_offline_only_when_no_pipeline_is_live() -> None:
    availability, clock, timers, changes = _monitor()
    one_minute = availability.probe("kline", "binance", "spot", "BTCUSDT")
    one_hour = availability.probe("kline", "binance", "spot", "BTCUSDT")
    one_minute.observe_data()
    one_hour.observe_data()
    one_minute.observe_health("reconnecting", "closed")
    timers.fire()
    assert changes == []

    one_hour.observe_health("reconnecting", "closed")
    timers.fire()
    assert _states(changes) == [True]


def test_restarting_a_pipeline_during_an_outage_does_not_flash_online() -> None:
    availability, clock, timers, changes = _monitor()
    old = availability.probe("kline", "binance", "spot", "BTCUSDT")
    old.observe_data()
    old.observe_health("reconnecting", "closed")
    timers.fire()
    assert _states(changes) == [True]

    # An interval switch starts a new pipeline before closing the old one.
    new = availability.probe("kline", "binance", "spot", "BTCUSDT")
    old.close()
    assert _states(changes) == [True]
    assert availability.is_offline("kline", "binance", "spot", "BTCUSDT")
    new.observe_data()
    assert _states(changes) == [True, False]


def test_closing_a_probe_is_silent_and_ignores_later_health() -> None:
    availability, clock, timers, changes = _monitor()
    probe = availability.probe("kline", "binance", "spot", "BTCUSDT")
    probe.observe_data()
    probe.close()
    probe.observe_health("disconnected", "stopped")
    probe.observe_health("reconnecting", "closed")
    timers.fire()
    assert changes == []
    assert availability.snapshot()["probes"] == 0


def test_price_snapshot_marks_offline_symbols_stale() -> None:
    availability, clock, timers, changes = _monitor()
    probe = availability.probe("price", "binance", "futures", "BTCUSDT")
    probe.observe_data()
    probe.observe_health("reconnecting", "closed")
    timers.fire()

    class _Dm:
        upstream_availability = availability

    prices = [
        {"symbol": "futures:BTCUSDT", "exchange": "binance", "market_type": "futures", "price": 61668.79},
        {"symbol": "futures:ETHUSDT", "exchange": "binance", "market_type": "futures", "price": 1730.12},
    ]
    marked = _prices_with_availability(_Dm(), prices)
    assert marked[0]["stale"] is True
    assert "stale" not in marked[1]
    assert "stale" not in prices[0]


def test_price_source_reports_ticker_health_and_data() -> None:
    async def _run() -> None:
        availability, clock, timers, changes = _monitor()

        class _Handle:
            stopped = False

            async def stop(self) -> None:
                self.stopped = True

        class _Factory:
            on_health = None
            on_price = None

            async def start_price(self, symbol, on_price, exchange="binance", market_type="spot", on_health=None):
                self.on_price, self.on_health = on_price, on_health
                return _Handle()

        factory = _Factory()
        source = IngestionPriceSource(factory, availability=availability)
        updates = []

        async def _capture(items):
            updates.extend(items)

        source.on_price_update(_capture)
        await source.ensure_symbol("futures:BTCUSDT")
        await factory.on_price({"symbol": "BTCUSDT", "price": 1})
        await factory.on_health("reconnecting", "closed")
        timers.fire()
        assert availability.is_offline("price", "binance", "futures", "BTCUSDT")
        await factory.on_price({"symbol": "BTCUSDT", "price": 2})
        assert _states(changes) == [True, False]
        assert updates == [{"symbol": "BTCUSDT", "price": 1}, {"symbol": "BTCUSDT", "price": 2}]

        await source.remove_symbol("futures:BTCUSDT")
        assert availability.snapshot()["probes"] == 0

    asyncio.run(_run())


class _BatchDm:
    def __init__(self, availability: UpstreamAvailability) -> None:
        self.upstream_availability = availability

    async def ensure_stream(self, symbol, interval, **kwargs):
        return None

    async def release_stream(self, symbol, interval, **kwargs) -> None:
        return None

    async def subscribe_async(self, **kwargs):
        return object()

    async def unsubscribe_async(self, handle) -> None:
        return None


def test_batch_subscribe_reports_an_exchange_that_is_already_offline(monkeypatch) -> None:
    monkeypatch.setattr(config, "KLINE_BATCH_STREAM_ENABLED", True)
    availability, clock, timers, changes = _monitor()
    probe = availability.probe("kline", "binance", "futures", "BTCUSDT")
    probe.observe_data()
    probe.observe_health("reconnecting", "closed")
    timers.fire()

    app = FastAPI()
    app.include_router(stream_router, prefix="/api/v1")
    app.state.data_manager = _BatchDm(availability)
    item = dict(clientId="chart-cell-1", exchange="binance", market_type="futures",
                symbol="BTCUSDT", intervals=["1m"])
    with TestClient(app).websocket_connect("/api/v1/stream/klines_batch") as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json(dict(action="subscribe", items=[item]))
        assert ws.receive_json()["type"] == "subscription_ack"
        status = ws.receive_json()
    assert status["type"] == "stream_status"
    assert status["client_id"] == "chart-cell-1"
    assert status["status"] == "offline"
    assert status["source"] == "upstream"
    assert "interval" not in status


def test_batch_connection_relays_offline_and_online_changes() -> None:
    async def _run() -> None:
        availability, clock, timers, changes = _monitor()

        class _Socket:
            def __init__(self) -> None:
                self.sent: list[dict] = []

            async def send_json(self, payload) -> None:
                self.sent.append(payload)

        socket = _Socket()
        connection = KlineBatchConnection(socket, _BatchDm(availability), limits=KlineBatchLimits.from_config())
        connection._watch_upstream()
        connection.subscriptions["a"] = _BatchSubscription("a", "binance", "futures", "BTCUSDT", "c")
        connection.subscriptions["b"] = _BatchSubscription("b", "binance", "futures", "ETHUSDT", "c")
        probe = availability.probe("kline", "binance", "futures", "BTCUSDT")
        probe.observe_data()
        probe.observe_health("reconnecting", "closed")
        timers.fire()
        await asyncio.sleep(0)
        probe.observe_data()
        await asyncio.sleep(0)
        assert [(message["client_id"], message["status"]) for message in socket.sent] == [
            ("a", "offline"), ("a", "online"),
        ]
        await connection.close()
        probe.observe_health("reconnecting", "closed")
        timers.fire()
        await asyncio.sleep(0)
        assert len(socket.sent) == 2

    asyncio.run(_run())


def test_stream_coordinator_reports_each_kline_pipeline_and_detaches_on_stop() -> None:
    from app.data_engine.data_manager.coordinator import StreamCoordinator
    from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamType

    async def _run() -> None:
        availability, clock, timers, changes = _monitor()

        class _Handle:
            def __init__(self, factory) -> None:
                self.factory = factory

            async def stop(self) -> None:
                # The session reports its own shutdown; that is not an outage.
                await self.factory.on_health("disconnected", "stopped")

        class _Factory:
            on_health = None
            on_market_event = None

            async def start(self, symbol, interval, on_market_event, exchange="binance",
                            market_type="spot", on_gap=None, *, on_health=None):
                self.on_market_event, self.on_health = on_market_event, on_health
                return _Handle(self)

        class _Aggregator:
            async def on_market_event(self, event) -> None:
                return None

        factory = _Factory()
        coord = StreamCoordinator()
        coord.set_ingestion_factory(factory)
        coord.set_bar_aggregator(_Aggregator())
        coord.set_upstream_availability(availability)

        await coord.ensure_stream("BTCUSDT", "1m", exchange="binance", market_type="futures")
        assert factory.on_health is not None
        await factory.on_market_event(MarketEvent(
            event_type=StreamType.KLINE, symbol="BTCUSDT", exchange="binance",
            event_time_ms=60_000, received_at_ms=60_010, source=DataSource.WEBSOCKET,
            data={"interval": "1m", "open_time": 60_000, "close_time": 119_999, "open": 1,
                  "high": 2, "low": 1, "close": 2, "volume": 10, "is_closed": False},
            stream_key="futures:BTCUSDT@kline_1m", market_type="futures",
        ))
        await factory.on_health("reconnecting", "Connection closed by remote server, closing code 1006")
        timers.fire()
        assert availability.is_offline("kline", "binance", "futures", "BTCUSDT")

        await factory.on_health("connected", "CCXT stream active")
        assert _states(changes) == [True, False]

        await coord.stop_stream("BTCUSDT", "1m", exchange="binance", market_type="futures")
        timers.fire()
        assert _states(changes) == [True, False]
        assert availability.snapshot()["probes"] == 0

    asyncio.run(_run())
